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
