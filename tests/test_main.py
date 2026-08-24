from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from suflor.main import (
    _ask_password, _collect_history, record_outgoing, resolve_outcomes,
)
from suflor.store import open_store, save_suggestion, style_samples, tone_stats


def _prompts(*values):
    seq = list(values)
    return lambda _prompt: seq.pop(0)


def test_returns_entered_password():
    assert _ask_password(_prompts("hunter2")) == "hunter2"


def test_reasks_until_non_empty(capsys):
    assert _ask_password(_prompts("", "   ", "hunter2")) == "hunter2"
    assert capsys.readouterr().out.count("не может быть пустым") == 2


def test_keeps_password_verbatim():
    # Пробелы могут быть частью пароля — обрезать нельзя, они только
    # не считаются за непустой ввод.
    assert _ask_password(_prompts(" hunter2 ")) == " hunter2 "


def _tg_message(text, out=False):
    return SimpleNamespace(text=text, out=out, date=None)


class _FakeClient:
    """Telethon отдаёт сообщения от новых к старым и режет выборку лимитом."""

    def __init__(self, messages):
        self._messages = messages

    def iter_messages(self, chat_id, limit):
        async def gen():
            for m in self._messages[:limit]:
                yield m
        return gen()


async def test_collect_history_orders_from_old_to_new():
    client = _FakeClient([_tg_message("второе", out=True),
                          _tg_message("первое")])
    history, _ = await _collect_history(client, 1, limit=10)
    assert [m["text"] for m in history] == ["первое", "второе"]
    assert [m["from_me"] for m in history] == [False, True]


async def test_collect_history_reports_whole_dialog():
    client = _FakeClient([_tg_message("привет")])
    _, full = await _collect_history(client, 1, limit=10)
    assert full is True


async def test_collect_history_reports_truncation_at_the_limit():
    client = _FakeClient([_tg_message(str(i)) for i in range(10)])
    _, full = await _collect_history(client, 1, limit=3)
    assert full is False


async def test_collect_history_counts_skipped_media_towards_the_limit():
    # Фото без подписи в историю не попадает, но лимит израсходовало —
    # значит, до начала переписки мы всё равно не дочитали.
    client = _FakeClient([_tg_message("привет"), _tg_message(None),
                          _tg_message("хай")])
    history, full = await _collect_history(client, 1, limit=3)
    assert [m["text"] for m in history] == ["хай", "привет"]
    assert full is False


NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
TONES = ["игривый", "тёплый", "с юмором"]
VARIANTS = ["Всё отлично, отдыхаю. А ты как проводишь вечер?",
            "У меня всё хорошо, отдыхаю. Приятно, что спрашиваешь.",
            "Норм, отдыхаю, ничего не делаю"]


def _conn(tmp_path):
    return open_store(str(tmp_path / "suflor.db"))


def _with_suggestion(tmp_path, created_at=NOW):
    conn = _conn(tmp_path)
    save_suggestion(conn, 1, TONES, VARIANTS, "чем занимаешься?", created_at)
    return conn


def test_record_outgoing_links_a_copied_variant(tmp_path):
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, VARIANTS[1], NOW + timedelta(minutes=2))

    assert style_samples(conn) == []          # чужой текст не образец моего стиля
    assert tone_stats(conn) == {"тёплый": 1}


def test_record_outgoing_keeps_my_edit_as_a_style_sample(tmp_path):
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, "У меня всё хорошо, отдыхаю.",
                    NOW + timedelta(minutes=2))

    assert [s["text"] for s in style_samples(conn)] == ["У меня всё хорошо, отдыхаю."]
    assert tone_stats(conn) == {"тёплый": 1}  # тон я всё-таки выбрал


def test_record_outgoing_treats_my_own_text_as_own(tmp_path):
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, "Слушай, а пойдём в субботу в кино?",
                    NOW + timedelta(minutes=2))

    assert [s["source"] for s in style_samples(conn)] == ["own"]
    assert tone_stats(conn) == {}             # ни один вариант не выбран


def test_record_outgoing_ignores_a_stale_suggestion(tmp_path):
    # Через сутки после подсказки совпадение было бы случайным
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, VARIANTS[1], NOW + timedelta(days=1))

    assert [s["source"] for s in style_samples(conn)] == ["own"]


def test_record_outgoing_without_any_suggestion(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "просто написал первым", NOW)
    assert [s["source"] for s in style_samples(conn)] == ["own"]


def test_record_outgoing_skips_empty_text(tmp_path):
    conn = _conn(tmp_path)
    assert record_outgoing(conn, 1, "   ", NOW) is None
    assert style_samples(conn) == []


def test_resolve_outcomes_scores_a_reply(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "моё сообщение", NOW)
    history = [{"from_me": True, "text": "моё сообщение", "date": NOW},
               {"from_me": False, "text": "ответ", "date": NOW + timedelta(minutes=5)}]

    assert resolve_outcomes(conn, 1, history, "ответ",
                            NOW + timedelta(minutes=5)) == 1
    assert style_samples(conn)[0]["score"] == 0.5


def test_resolve_outcomes_marks_zero_past_the_window(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "моё сообщение", NOW)
    late = NOW + timedelta(hours=20)

    resolve_outcomes(conn, 1, [], "ответила через сутки", late)
    assert style_samples(conn)[0]["score"] == 0.0


def test_resolve_outcomes_closes_a_burst_of_my_messages(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "первое моё", NOW)
    record_outgoing(conn, 1, "второе моё", NOW + timedelta(minutes=1))

    assert resolve_outcomes(conn, 1, [], "ответ", NOW + timedelta(minutes=5)) == 2


def test_resolve_outcomes_ignores_messages_sent_after_the_reply(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "уже после ответа", NOW + timedelta(hours=1))
    assert resolve_outcomes(conn, 1, [], "ответ", NOW) == 0


def test_resolve_outcomes_upgrades_a_late_reply(tmp_path):
    # Сначала пометили нулём по таймауту, потом она всё же ответила
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "моё сообщение", NOW)
    resolve_outcomes(conn, 1, [], "чужая реплика", NOW + timedelta(hours=20))
    assert style_samples(conn)[0]["score"] == 0.0

    resolve_outcomes(conn, 1, [], "ответ", NOW + timedelta(minutes=30))
    assert style_samples(conn)[0]["score"] == 0.5
