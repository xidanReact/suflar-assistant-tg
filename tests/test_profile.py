from datetime import datetime, timedelta, timezone

from suflor.profile import style_block, length_habit, emoji_habit
from suflor.store import open_store, save_suggestion, save_sent, save_outcome

NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
TONES = ["игривый", "тёплый", "с юмором"]


def _conn(tmp_path):
    return open_store(str(tmp_path / "suflor.db"))


def _my_messages(conn, texts, chat_id=1, score=None):
    for i, text in enumerate(texts):
        sent_id = save_sent(conn, chat_id, text, "own",
                            sent_at=NOW - timedelta(minutes=i))
        if score is not None:
            save_outcome(conn, sent_id, NOW, "ответ", 60, score)


def _picked(conn, chat_id, index, my_text, source="variant",
            variants=("А", "Б", "В")):
    sid = save_suggestion(conn, chat_id, TONES, list(variants), "привет", NOW)
    save_sent(conn, chat_id, my_text, source, sid, index, sent_at=NOW)


def test_no_block_on_empty_store(tmp_path):
    assert style_block(_conn(tmp_path), chat_id=1, tones=TONES) == ""


def test_no_block_until_enough_samples(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, ["раз", "два", "три"])
    assert style_block(conn, chat_id=1, tones=TONES, min_samples=5) == ""


def test_block_lists_my_messages(tmp_path):
    conn = _conn(tmp_path)
    texts = ["норм, отдыхаю", "давай в четверг", "ну ты даёшь конечно",
             "сегодня никак", "созвонимся вечером"]
    _my_messages(conn, texts)
    block = style_block(conn, chat_id=1, tones=TONES)
    assert "как я пишу" in block.lower()
    for text in texts:
        assert text in block


def test_block_never_shows_untouched_variants(tmp_path):
    # Ключевая защита от схлопывания: текст модели не может стать образцом
    conn = _conn(tmp_path)
    _my_messages(conn, ["моё раз", "моё два", "моё три", "моё четыре",
                        "моё пять"])
    _picked(conn, 1, 0, "текст который написала модель")
    block = style_block(conn, chat_id=1, tones=TONES)
    assert "написала модель" not in block


def test_block_prefers_samples_from_the_same_chat(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, [f"чужой чат {i}" for i in range(8)], chat_id=2,
                 score=1.0)
    _my_messages(conn, ["этот чат раз", "этот чат два"], chat_id=1, score=0.0)

    block = style_block(conn, chat_id=1, tones=TONES, max_samples=4,
                        chat_quota=2, min_samples=4)
    assert "этот чат раз" in block
    assert "этот чат два" in block
    assert block.count("чужой чат") == 2


def test_block_does_not_repeat_a_sample(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, [f"сообщение {i}" for i in range(6)], chat_id=1)
    block = style_block(conn, chat_id=1, tones=TONES, max_samples=6,
                        chat_quota=5)
    assert block.count("сообщение 0") == 1


def test_block_reports_the_favourite_tone(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, [f"моё {i}" for i in range(5)])
    for _ in range(4):
        _picked(conn, 1, 2, "взял с юмором")
    _picked(conn, 1, 0, "взял игривый")

    block = style_block(conn, chat_id=1, tones=TONES)
    assert "с юмором" in block
    assert "4 из 5" in block


def test_block_marks_a_tone_i_never_pick(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, [f"моё {i}" for i in range(5)])
    for _ in range(20):
        _picked(conn, 1, 1, "снова тёплый")

    block = style_block(conn, chat_id=1, tones=TONES)
    assert "ни разу" in block
    assert "игривый" in block


def test_block_stays_silent_about_tones_on_thin_data(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, [f"моё {i}" for i in range(5)])
    _picked(conn, 1, 0, "единственный выбор")
    block = style_block(conn, chat_id=1, tones=TONES)
    assert "ни разу" not in block
    assert "из 1" not in block


def test_length_habit_needs_a_repeated_pattern():
    trimmed = [("Длинное предложенное сообщение с хвостом", "Длинное")] * 4
    assert length_habit(trimmed) == ""
    assert "сокращаю" in length_habit(trimmed * 2)


def test_length_habit_ignores_edits_that_keep_the_length():
    same = [("Привет, как ты сегодня?", "Привет, как ты сегодня!")] * 8
    assert length_habit(same) == ""


def test_length_habit_detects_that_i_write_longer():
    longer = [("Норм", "Норм, только вернулся с работы, устал как собака")] * 6
    assert "длиннее" in length_habit(longer)


def test_emoji_habit_needs_a_repeated_pattern():
    stripped = [("Привет 😉", "Привет")] * 4
    assert emoji_habit(stripped) == ""
    assert "меньше" in emoji_habit(stripped * 2)


def test_emoji_habit_ignores_untouched_emoji():
    kept = [("Привет 😉", "Привет 😉")] * 8
    assert emoji_habit(kept) == ""


def test_block_includes_edit_habits(tmp_path):
    conn = _conn(tmp_path)
    _my_messages(conn, [f"моё {i}" for i in range(5)])
    for _ in range(6):
        _picked(conn, 1, 0, "Коротко", source="edited",
                variants=("Длинное предложенное сообщение с хвостом 😉", "Б", "В"))

    block = style_block(conn, chat_id=1, tones=TONES)
    assert "сокращаю" in block
    assert "смайл" in block


def test_block_collapses_identical_samples(tmp_path):
    # Одно и то же сообщение, отправленное несколько раз, второй раз ничему
    # не учит, а строки в промпте занимает
    conn = _conn(tmp_path)
    _my_messages(conn, ["привет, как ты"] * 4 + ["давай завтра созвонимся",
                                                 "сегодня уже не успею",
                                                 "ну ты даёшь конечно",
                                                 "буду часов в восемь"])
    block = style_block(conn, chat_id=1, tones=TONES)
    assert block.count("привет, как ты") == 1
