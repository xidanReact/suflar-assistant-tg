from datetime import datetime, timedelta, timezone

from suflor.store import (
    open_store, save_suggestion, last_suggestion, save_sent, sent_exists,
    save_outcome, pending_outcomes, expire_pending, style_samples, tone_stats,
    suggestion_count, edited_pairs, forget_chat, learning_summary,
)

NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
TONES = ["игривый", "тёплый", "с юмором"]


def _store(tmp_path):
    return open_store(str(tmp_path / "suflor.db"))


def _suggestion(conn, chat_id=1, at=NOW):
    return save_suggestion(conn, chat_id, TONES, ["А", "Б", "В"], "привет", at)


def test_open_store_creates_schema_on_empty_file(tmp_path):
    conn = _store(tmp_path)
    assert style_samples(conn) == []
    assert tone_stats(conn) == {}


def test_open_store_is_idempotent_and_keeps_data(tmp_path):
    path = str(tmp_path / "suflor.db")
    conn = open_store(path)
    save_sent(conn, 1, "моё сообщение", "own", sent_at=NOW)
    conn.close()

    conn = open_store(path)  # второй запуск бота не должен ронять схему
    assert [s["text"] for s in style_samples(conn)] == ["моё сообщение"]


def test_last_suggestion_returns_the_freshest_for_the_chat(tmp_path):
    conn = _store(tmp_path)
    save_suggestion(conn, 1, TONES, ["старое"], "а", NOW - timedelta(hours=2))
    save_suggestion(conn, 1, TONES, ["новое"], "б", NOW)
    save_suggestion(conn, 2, TONES, ["чужое"], "в", NOW)

    got = last_suggestion(conn, 1)
    assert got["variants"] == ["новое"]
    assert got["tones"] == TONES
    assert got["created_at"] == NOW


def test_last_suggestion_none_for_unknown_chat(tmp_path):
    assert last_suggestion(_store(tmp_path), 42) is None


def test_style_samples_exclude_untouched_variants(tmp_path):
    # Принятый как есть вариант писала модель, а не я: в образцы моей манеры
    # он попадать не должен — иначе модель учится на самой себе
    conn = _store(tmp_path)
    sid = _suggestion(conn)
    save_sent(conn, 1, "как есть", "variant", sid, 0, sent_at=NOW)
    save_sent(conn, 1, "с правкой", "edited", sid, 1, sent_at=NOW)
    save_sent(conn, 1, "своё", "own", sent_at=NOW)

    assert {s["text"] for s in style_samples(conn)} == {"своё", "с правкой"}


def test_style_samples_filter_by_chat(tmp_path):
    conn = _store(tmp_path)
    save_sent(conn, 1, "этому", "own", sent_at=NOW)
    save_sent(conn, 2, "другому", "own", sent_at=NOW)
    assert [s["text"] for s in style_samples(conn, chat_id=1)] == ["этому"]


def test_style_samples_rank_by_score_then_freshness(tmp_path):
    conn = _store(tmp_path)
    weak = save_sent(conn, 1, "слабое", "own", sent_at=NOW - timedelta(days=1))
    strong = save_sent(conn, 1, "сильное", "own", sent_at=NOW - timedelta(days=2))
    save_outcome(conn, weak, None, None, None, 0.0)
    save_outcome(conn, strong, NOW, "ответ", 60, 0.9)

    assert [s["text"] for s in style_samples(conn)] == ["сильное", "слабое"]


def test_style_samples_default_score_without_outcome(tmp_path):
    # Собранное командой /train исхода не имеет: считаем его средним, чтобы
    # оно не проигрывало заведомо всему, что с исходом
    conn = _store(tmp_path)
    trained = save_sent(conn, 1, "из истории", "own", sent_at=NOW)
    failed = save_sent(conn, 1, "без ответа", "own", sent_at=NOW)
    save_outcome(conn, failed, None, None, None, 0.0)

    assert [s["text"] for s in style_samples(conn)] == ["из истории", "без ответа"]


def test_style_samples_respect_limit(tmp_path):
    conn = _store(tmp_path)
    for i in range(10):
        save_sent(conn, 1, f"текст {i}", "own", sent_at=NOW)
    assert len(style_samples(conn, limit=3)) == 3


def test_tone_stats_count_picked_tones(tmp_path):
    conn = _store(tmp_path)
    sid = _suggestion(conn)
    save_sent(conn, 1, "а", "variant", sid, 0, sent_at=NOW)
    save_sent(conn, 1, "б", "edited", sid, 0, sent_at=NOW)
    save_sent(conn, 1, "в", "variant", sid, 2, sent_at=NOW)
    save_sent(conn, 1, "своё", "own", sent_at=NOW)

    assert tone_stats(conn) == {"игривый": 2, "с юмором": 1}


def test_tone_stats_filter_by_chat(tmp_path):
    conn = _store(tmp_path)
    here = _suggestion(conn, chat_id=1)
    there = _suggestion(conn, chat_id=2)
    save_sent(conn, 1, "а", "variant", here, 0, sent_at=NOW)
    save_sent(conn, 2, "б", "variant", there, 1, sent_at=NOW)

    assert tone_stats(conn, chat_id=1) == {"игривый": 1}


def test_tone_stats_survive_shortened_tone_list(tmp_path):
    # Тона живут в конфиге и могут поменяться: индекс из старой подсказки
    # не должен ронять статистику
    conn = _store(tmp_path)
    sid = save_suggestion(conn, 1, ["один"], ["А"], "привет", NOW)
    save_sent(conn, 1, "а", "variant", sid, 5, sent_at=NOW)
    assert tone_stats(conn) == {}


def test_suggestion_count(tmp_path):
    conn = _store(tmp_path)
    _suggestion(conn, chat_id=1)
    _suggestion(conn, chat_id=1)
    _suggestion(conn, chat_id=2)
    assert suggestion_count(conn) == 3
    assert suggestion_count(conn, chat_id=2) == 1


def test_edited_pairs_return_original_and_my_version(tmp_path):
    conn = _store(tmp_path)
    sid = _suggestion(conn)
    save_sent(conn, 1, "моя правка", "edited", sid, 1, sent_at=NOW)
    save_sent(conn, 1, "как есть", "variant", sid, 0, sent_at=NOW)
    assert edited_pairs(conn) == [("Б", "моя правка")]


def test_pending_outcomes_lists_only_unresolved(tmp_path):
    conn = _store(tmp_path)
    done = save_sent(conn, 1, "закрытое", "own", sent_at=NOW)
    waiting = save_sent(conn, 1, "висит", "own", sent_at=NOW)
    save_sent(conn, 2, "чужой чат", "own", sent_at=NOW)
    save_outcome(conn, done, NOW, "ответ", 60, 0.7)

    pending = pending_outcomes(conn, 1)
    assert [p["id"] for p in pending] == [waiting]
    assert pending[0]["sent_at"] == NOW


def test_pending_outcomes_keep_unanswered_open_for_a_late_reply(tmp_path):
    # Помеченное «не ответила» по таймауту должно вернуться в очередь: ответ
    # мог прийти позже, и ноль надо будет исправить
    conn = _store(tmp_path)
    timed_out = save_sent(conn, 1, "молчание", "own", sent_at=NOW)
    save_outcome(conn, timed_out, None, None, None, 0.0)
    assert [p["id"] for p in pending_outcomes(conn, 1)] == [timed_out]


def test_expire_pending_closes_only_the_old_ones(tmp_path):
    conn = _store(tmp_path)
    old = save_sent(conn, 1, "давнее", "own", sent_at=NOW - timedelta(days=1))
    fresh = save_sent(conn, 1, "свежее", "own", sent_at=NOW)

    assert expire_pending(conn, NOW - timedelta(hours=12)) == 1

    samples = {s["id"]: s["score"] for s in style_samples(conn)}
    assert samples[old] == 0.0
    assert samples[fresh] == 0.5      # исхода нет — значение по умолчанию


def test_expire_pending_does_not_touch_answered(tmp_path):
    conn = _store(tmp_path)
    answered = save_sent(conn, 1, "давнее", "own", sent_at=NOW - timedelta(days=1))
    save_outcome(conn, answered, NOW, "ответ", 60, 0.9)

    expire_pending(conn, NOW)

    assert style_samples(conn)[0]["score"] == 0.9


def test_save_outcome_overwrites_the_previous_verdict(tmp_path):
    conn = _store(tmp_path)
    sid = save_sent(conn, 1, "текст", "own", sent_at=NOW)
    save_outcome(conn, sid, None, None, None, 0.0)
    save_outcome(conn, sid, NOW, "всё же ответила", 60, 0.8)
    assert style_samples(conn)[0]["score"] == 0.8


def test_sent_exists_guards_train_from_duplicates(tmp_path):
    conn = _store(tmp_path)
    save_sent(conn, 1, "текст", "own", sent_at=NOW)
    assert sent_exists(conn, 1, NOW) is True
    assert sent_exists(conn, 1, NOW - timedelta(minutes=1)) is False
    assert sent_exists(conn, 2, NOW) is False


def test_forget_chat_wipes_everything_of_that_chat(tmp_path):
    conn = _store(tmp_path)
    sid = _suggestion(conn, chat_id=1)
    mine = save_sent(conn, 1, "моё", "edited", sid, 0, sent_at=NOW)
    save_outcome(conn, mine, NOW, "ответ", 60, 0.7)
    other = _suggestion(conn, chat_id=2)
    save_sent(conn, 2, "чужое", "own", sent_at=NOW)

    forget_chat(conn, 1)

    assert [s["text"] for s in style_samples(conn)] == ["чужое"]
    assert last_suggestion(conn, 1) is None
    assert last_suggestion(conn, 2) is not None
    assert suggestion_count(conn) == 1
    assert other  # подсказка второго чата на месте


def test_learning_summary_reports_what_was_collected(tmp_path):
    conn = _store(tmp_path)
    sid = _suggestion(conn)
    save_sent(conn, 1, "как есть", "variant", sid, 0, sent_at=NOW)
    save_sent(conn, 1, "своё", "own", sent_at=NOW)
    save_sent(conn, 2, "ещё своё", "own", sent_at=NOW)

    summary = learning_summary(conn)
    assert summary["samples"] == 2        # own + edited
    assert summary["sent"] == 3
    assert summary["chats"] == 2
    assert summary["suggestions"] == 1
    assert summary["tones"] == {"игривый": 1}
