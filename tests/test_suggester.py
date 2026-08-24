from unittest.mock import MagicMock
import pytest
from suflor.suggester import (
    build_messages, parse_suggestions, parse_analysis, Suggester, SuggesterError,
)


def test_build_messages_has_system_and_user():
    history = [{"from_me": False, "text": "привет"}]
    msgs = build_messages(history)
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert "привет" in msgs[-1]["content"]


def test_parse_suggestions_extracts_three():
    raw = "1) Привет!\n2) Хэй, как ты?\n3) О, приветик :)"
    out = parse_suggestions(raw)
    assert out == ["Привет!", "Хэй, как ты?", "О, приветик :)"]


def test_parse_suggestions_tolerates_blank_lines():
    raw = "1) Один\n\n2) Два\n\n3) Три\n"
    assert parse_suggestions(raw) == ["Один", "Два", "Три"]


def _make_suggester_with_reply(text):
    s = Suggester.__new__(Suggester)
    s._model = "deepseek-chat"
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=msg)]
    )
    s._client = client
    return s


def test_analyze_raises_on_api_error():
    s = Suggester.__new__(Suggester)
    s._model = "deepseek-chat"
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    s._client = client
    with pytest.raises(SuggesterError):
        s.analyze([{"from_me": False, "text": "хай"}])


def test_analyze_returns_partial_when_model_gives_fewer_than_three():
    s = _make_suggester_with_reply("Разбор.\n1) Только один\n2) И второй")
    _, variants = s.analyze([{"from_me": False, "text": "хай"}])
    assert variants == ["Только один", "И второй"]


def test_parse_analysis_takes_text_before_first_variant():
    raw = "Отвечает коротко.\nИнициативу не берёт.\n\n1) А\n2) Б\n3) В"
    assert parse_analysis(raw) == "Отвечает коротко. Инициативу не берёт."


def test_parse_analysis_empty_when_model_skips_it():
    assert parse_analysis("1) А\n2) Б\n3) В") == ""


def test_analyze_returns_analysis_and_variants():
    s = _make_suggester_with_reply("Диалог заглох.\n\n1) А\n2) Б\n3) В")
    analysis, variants = s.analyze([{"from_me": True, "text": "хай"}])
    assert analysis == "Диалог заглох."
    assert variants == ["А", "Б", "В"]


def test_analyze_raises_when_reply_has_no_variants():
    s = _make_suggester_with_reply("только разбор, вариантов нет")
    with pytest.raises(SuggesterError):
        s.analyze([{"from_me": True, "text": "хай"}])
