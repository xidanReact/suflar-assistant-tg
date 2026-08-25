from datetime import datetime, timedelta, timezone

from suflor.dialog import (
    format_history, elapsed_since_last, questions_asked, variants_word,
)

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def _msg(text, minutes_ago, from_me=False):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def test_format_history_labels_both_sides():
    text = format_history([_msg("привет", 5),
                           _msg("привет!", 4, from_me=True)],
                          "Аня")
    assert text == "Аня: привет\nЯ: привет!"


def test_format_history_marks_long_pauses():
    # Час молчания в переписке заметен, и модель должна его видеть
    text = format_history([_msg("ты тут?", 200),
                           _msg("тут", 10, from_me=True)])
    assert "[пауза 3 часа]" in text


def test_format_history_ignores_short_pauses():
    text = format_history([_msg("а", 10),
                           _msg("б", 8)])
    assert "пауза" not in text


def test_format_history_uses_generic_partner_by_default():
    assert format_history([_msg("привет", 0)]).startswith("Собеседник: ")


def test_elapsed_since_last_measures_from_the_last_message():
    assert elapsed_since_last([_msg("привет", 90)],
                              NOW) == "1 час"


def test_elapsed_since_last_empty_without_dates():
    assert elapsed_since_last([{"from_me": False, "text": "привет"}],
                              NOW) == ""


def test_elapsed_since_last_empty_for_empty_history():
    assert elapsed_since_last([], NOW) == ""


def test_questions_lists_both_sides_with_authors():
    history = [_msg("Как дела?", 60, from_me=True),
               _msg("Нормально. А у тебя?)", 55),
               _msg("Чем занимаешься?", 50)]
    block = questions_asked(history, "Аня")
    assert "- я: Как дела?" in block
    assert "- Аня: А у тебя?" in block
    assert "- Аня: Чем занимаешься?" in block


def test_questions_ignore_statements():
    assert questions_asked([_msg("Привет, я дома!", 5)], "Аня") == ""


def test_questions_split_several_in_one_message():
    block = questions_asked([_msg("Привет! Как ты? Чем занят?", 5)], "Аня")
    assert "- Аня: Как ты?" in block
    assert "- Аня: Чем занят?" in block
    assert "Привет" not in block


def test_questions_collapse_repeats_keeping_the_latest():
    history = [_msg("Как дела?", 60, from_me=True),
               _msg("нормально", 55),
               _msg("как дела?)", 50, from_me=True)]
    block = questions_asked(history, "Аня")
    assert block.count("ак дела") == 1


def test_questions_keep_only_the_freshest():
    history = [_msg(f"вопрос {i}?", 100 - i) for i in range(20)]
    block = questions_asked(history, "Аня", limit=3)
    assert "вопрос 19?" in block
    assert "вопрос 0?" not in block


def test_variants_word_handles_teens():
    assert variants_word(1) == "вариант"
    assert variants_word(3) == "варианта"
    assert variants_word(11) == "вариантов"
    assert variants_word(21) == "вариант"
