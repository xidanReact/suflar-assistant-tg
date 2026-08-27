from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from suflor.memory import (
    Summarizer, build_summary_messages, refresh, should_refresh,
)
from suflor.store import open_store, save_memory, memory

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def _msg(text, from_me=False, minutes_ago=0):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def _history(n):
    return [_msg(f"реплика {i}", minutes_ago=n - i) for i in range(n)]


def _summarizer(text):
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason="stop")
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return Summarizer(client=client, model="m")


def test_should_refresh_without_a_stored_summary():
    assert should_refresh(None, history_len=5, every=10) is True


def test_should_refresh_after_enough_new_messages():
    stored = {"summary": "с", "msg_count": 10}
    assert should_refresh(stored, history_len=20, every=10) is True


def test_should_not_refresh_before_enough_new_messages():
    stored = {"summary": "с", "msg_count": 10}
    assert should_refresh(stored, history_len=15, every=10) is False


def test_summary_messages_carry_the_previous_summary():
    user = build_summary_messages(_history(3),
                                  previous="Аня, 24")[1]["content"]
    assert "Аня, 24" in user


def test_summary_messages_ask_for_the_four_sections():
    system = build_summary_messages(_history(3))[0]["content"]
    for section in ("Собеседник", "О чём говорили", "Как общается",
                    "Что открыто"):
        assert section in system


def test_summarize_returns_the_model_text():
    assert _summarizer("Аня, 24, из Томска").summarize(_history(3)) == \
        "Аня, 24, из Томска"


def test_summarize_trims_an_overlong_summary():
    # Сводка живёт в каждом промпте ответа: разросшаяся съедает контекст
    long_text = "а" * 5000
    assert len(_summarizer(long_text).summarize(_history(3))) <= 1200


def test_refresh_stores_the_summary_and_the_history_length(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    result = refresh(conn, _summarizer("сводка"), 1, _history(12), every=10)
    assert result == "сводка"
    assert memory(conn, 1)["summary"] == "сводка"
    assert memory(conn, 1)["msg_count"] == 12


def test_refresh_reuses_the_stored_summary_when_it_is_fresh(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    save_memory(conn, 1, "старая сводка", 10, NOW)
    s = _summarizer("новая сводка")
    assert refresh(conn, s, 1, _history(12), every=10) == "старая сводка"
    s._client.chat.completions.create.assert_not_called()


def test_refresh_survives_a_model_failure(tmp_path):
    # Память не точка отказа: не собралась — отвечаем без неё
    conn = open_store(str(tmp_path / "s.db"))
    save_memory(conn, 1, "старая сводка", 0, NOW)
    s = _summarizer("неважно")
    s._client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    assert refresh(conn, s, 1, _history(50), every=10) == "старая сводка"


def test_refresh_returns_empty_when_there_is_nothing_to_fall_back_on(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    s = _summarizer("неважно")
    s._client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    assert refresh(conn, s, 1, _history(5), every=10) == ""
