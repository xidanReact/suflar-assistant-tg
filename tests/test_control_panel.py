from suflor.control_panel import (
    format_suggestions, format_error, build_chat_link,
    format_watchlist, format_auto_card, format_auto_sent,
    format_handoff, format_send_error, format_auto_list,
)


def test_format_suggestions_contains_all_parts():
    text = format_suggestions("Аня", "чем занимаешься?",
                              ["вариант1", "вариант2", "вариант3"])
    assert "Аня" in text
    assert "чем занимаешься?" in text
    assert "вариант1" in text
    assert "вариант2" in text
    assert "вариант3" in text
    assert "1" in text and "2" in text and "3" in text


def test_format_suggestions_labels_variants_with_configured_tones():
    text = format_suggestions("Аня", "привет", ["в1", "в2"],
                              tones=["дерзкий", "спокойный"])
    assert "[дерзкий] в1" in text
    assert "[спокойный] в2" in text


def test_format_suggestions_without_tones_has_no_labels():
    text = format_suggestions("Аня", "привет", ["в1"])
    assert "[" not in text


def test_format_suggestions_numbers_extra_variants():
    # эмодзи-цифры кончаются на пятой, дальше обычная нумерация
    text = format_suggestions("Аня", "привет", ["в"] * 6, tones=["т"] * 6)
    assert "6) [т] в" in text


def test_format_suggestions_includes_chat_link():
    text = format_suggestions("Аня", "привет", ["в1"],
                              chat_link="https://t.me/anna")
    assert "https://t.me/anna" in text


def test_build_chat_link_prefers_username():
    assert build_chat_link("anna", 111) == "https://t.me/anna"


def test_build_chat_link_falls_back_to_id():
    assert build_chat_link(None, 111) == "id 111"


def test_format_error_mentions_sender():
    text = format_error("Аня")
    assert "Аня" in text


def _summary(**kw):
    base = dict(samples=40, sent=55, chats=6, suggestions=18,
                tones={"с юмором": 11, "тёплый": 4}, avg_score=0.62)
    base.update(kw)
    return base


def test_format_stats_reports_the_corpus():
    from suflor.control_panel import format_stats
    text = format_stats(_summary(), min_samples=5)
    assert "40" in text and "55" in text and "6" in text
    assert "с юмором — 11" in text
    assert "0.62" in text
    assert "ещё не собирается" not in text


def test_format_stats_warns_while_the_corpus_is_thin():
    from suflor.control_panel import format_stats
    text = format_stats(_summary(samples=2), min_samples=5)
    assert "ещё не собирается" in text
    assert "/train" in text


def test_format_stats_survives_an_empty_store():
    from suflor.control_panel import format_stats
    text = format_stats(_summary(samples=0, sent=0, chats=0, suggestions=0,
                                 tones={}, avg_score=None), min_samples=5)
    assert "Выбранных вариантов пока нет" in text
    assert "Средняя оценка" not in text


def test_watchlist_shows_names_and_usernames():
    text = format_watchlist([{"name": "Аня", "username": "anna"},
                             {"name": "Катя", "username": None}], "selected")
    assert "Аня (@anna)" in text
    assert "Катя" in text
    assert "@None" not in text


def test_empty_watchlist_says_the_bot_is_silent():
    # В режиме selected пустой список — молчащий бот; об этом надо сказать
    text = format_watchlist([], "selected")
    assert "пуст" in text.lower()
    assert "/watch" in text


def test_watchlist_warns_that_the_list_is_unused_in_all_mode():
    text = format_watchlist([{"name": "Аня", "username": "anna"}], "all")
    assert "watch_mode" in text


def test_auto_card_shows_incoming_reply_and_countdown():
    text = format_auto_card("Аня", "привет!", "привет, как ты?", 60)
    assert "Аня" in text
    assert "привет!" in text
    assert "привет, как ты?" in text
    assert "60" in text
    assert "/stop" in text          # как отменить, видно в самой карточке


def test_auto_card_includes_the_fallback_link():
    text = format_auto_card("Аня", "привет", "и тебе", 60,
                            chat_link="https://t.me/anya")
    assert "https://t.me/anya" in text


def test_auto_sent_confirms_what_went_out():
    text = format_auto_sent("Аня", "привет, как ты?")
    assert "Аня" in text
    assert "привет, как ты?" in text


def test_handoff_card_names_the_reason_and_says_it_is_paused():
    text = format_handoff("Аня", "зовёт гулять")
    assert "Аня" in text
    assert "зовёт гулять" in text
    assert "пауз" in text.lower()
    assert "/auto" in text           # как вернуть бота в диалог


def test_send_error_keeps_the_text_so_it_can_be_sent_by_hand():
    text = format_send_error("Аня", "привет, как ты?")
    assert "привет, как ты?" in text


def test_auto_list_is_explicit_when_empty():
    text = format_auto_list([], enabled=True)
    assert "пуст" in text
    assert "/auto" in text


def test_auto_list_marks_paused_chats():
    text = format_auto_list(
        [{"name": "Аня", "username": "anya", "paused_reason": None},
         {"name": "Лена", "username": None,
          "paused_reason": "зовёт гулять"}], enabled=True)
    assert "Аня" in text and "anya" in text
    assert "Лена" in text and "зовёт гулять" in text


def test_auto_list_warns_when_the_mode_is_off_in_config():
    text = format_auto_list(
        [{"name": "Аня", "username": None, "paused_reason": None}],
        enabled=False)
    assert "auto.enabled" in text


def test_stats_report_auto_replies():
    from suflor.control_panel import format_stats
    summary = {"samples": 10, "sent": 20, "chats": 2, "suggestions": 5,
               "tones": {}, "avg_score": 0.5, "auto": 7, "auto_score": 0.42}
    text = format_stats(summary, min_samples=5)
    assert "7" in text
    assert "0.42" in text


def test_stats_survive_a_summary_without_auto_keys():
    # Сводка из старой базы ключей auto не содержит — падать нельзя
    from suflor.control_panel import format_stats
    summary = {"samples": 1, "sent": 1, "chats": 1, "suggestions": 0,
               "tones": {}, "avg_score": None}
    assert format_stats(summary, min_samples=5)
