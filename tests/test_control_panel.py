from suflor.control_panel import (
    format_suggestions, format_error, build_chat_link,
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
