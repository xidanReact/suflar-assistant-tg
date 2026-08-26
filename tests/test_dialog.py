from datetime import datetime, timedelta, timezone

from suflor.dialog import (
    format_history, elapsed_since_last, questions_asked, variants_word,
    humanize_delta, initiative_summary,
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


def test_humanize_delta_scales_units():
    assert humanize_delta(30) == "меньше минуты"
    assert humanize_delta(60 * 5) == "5 минут"
    assert humanize_delta(3600 * 2) == "2 часа"
    assert humanize_delta(86400 * 3) == "3 дня"
    assert humanize_delta(86400 * 90) == "3 месяца"


def test_humanize_delta_clamps_negative_skew():
    assert humanize_delta(-100) == "меньше минуты"


def test_initiative_names_who_started_when_history_is_whole():
    history = [_msg("привет", 60), _msg("о, привет", 55, from_me=True)]
    summary = initiative_summary(history, "Аня")
    assert "начал переписку: Аня" in summary
    assert "последним писал: я" in summary


def test_initiative_marks_my_first_message():
    history = [_msg("привет", 60, from_me=True), _msg("хай", 55)]
    summary = initiative_summary(history, "Аня")
    assert "начал переписку: я" in summary
    assert "последним писал: Аня" in summary


def test_initiative_counts_messages_on_both_sides():
    history = [_msg("а", 60), _msg("б", 55, from_me=True), _msg("в", 50)]
    assert "сообщений всего: Аня — 2, я — 1" in initiative_summary(
        history, "Аня")


def test_initiative_counts_who_breaks_long_silences():
    history = [
        _msg("привет", 60 * 24 * 3),
        _msg("ну как ты", 60 * 24 * 2),
        _msg("нормально", 60 * 24 * 2 - 5, from_me=True),
        _msg("давно не виделись", 30, from_me=True),
    ]
    summary = initiative_summary(history, "Аня")
    assert "после долгой паузы: Аня — 1 раз, я — 1 раз" in summary


def test_initiative_omits_pause_line_without_long_pauses():
    history = [_msg("привет", 40), _msg("хай", 35, from_me=True)]
    assert "после долгой паузы" not in initiative_summary(history, "Аня")


def test_initiative_admits_when_start_is_cut_off_by_the_limit():
    # Обрезанная лимитом переписка: первый в выборке ≠ начавший диалог
    history = [_msg("привет", 60), _msg("о, привет", 55, from_me=True)]
    summary = initiative_summary(history, "Аня", full_history=False)
    assert "начал переписку" not in summary
    assert "начало переписки не видно" in summary
    assert "последним писал: я" in summary


def test_initiative_empty_for_empty_history():
    assert initiative_summary([], "Аня") == ""
