from unittest.mock import MagicMock
import pytest
from datetime import datetime, timedelta, timezone

from suflor.suggester import (
    build_messages, build_system_prompt, variants_word, humanize_delta,
    parse_suggestions, parse_analysis, Suggester, SuggesterError,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _msg(text, minutes_ago, from_me=False):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def test_humanize_delta_scales_units():
    assert humanize_delta(30) == "меньше минуты"
    assert humanize_delta(60 * 5) == "5 минут"
    assert humanize_delta(3600 * 2) == "2 часа"
    assert humanize_delta(86400 * 3) == "3 дня"
    assert humanize_delta(86400 * 90) == "3 месяца"


def test_humanize_delta_clamps_negative_skew():
    assert humanize_delta(-100) == "меньше минуты"


def test_build_messages_reports_time_since_last_message():
    msgs = build_messages([_msg("привет", 120)], "промпт", now=NOW)
    assert "С последнего сообщения прошло: 2 часа." in msgs[-1]["content"]


def test_build_messages_marks_long_pauses_between_messages():
    history = [_msg("привет", 60 * 25), _msg("ну как ты", 30)]
    body = build_messages(history, "промпт", now=NOW)[-1]["content"]
    assert "[пауза 1 день]" in body


def test_build_messages_ignores_short_pauses():
    history = [_msg("привет", 35), _msg("ну как ты", 30)]
    body = build_messages(history, "промпт", now=NOW)[-1]["content"]
    assert "пауза" not in body


def test_build_messages_works_without_dates():
    body = build_messages([{"from_me": False, "text": "привет"}],
                          "промпт", now=NOW)[-1]["content"]
    assert "Собеседник: привет" in body
    assert "С последнего сообщения" not in body


def test_build_messages_has_system_and_user():
    history = [{"from_me": False, "text": "привет"}]
    msgs = build_messages(history, "системный промпт")
    assert msgs[0] == {"role": "system", "content": "системный промпт"}
    assert msgs[-1]["role"] == "user"
    assert "привет" in msgs[-1]["content"]


def test_build_system_prompt_uses_configured_tones_and_style():
    prompt = build_system_prompt(["дерзкий", "спокойный"], "Пиши строчными.")
    assert "1) дерзкий" in prompt
    assert "2) спокойный" in prompt
    assert "Пиши строчными." in prompt
    assert "РОВНО 2 варианта" in prompt


def test_build_system_prompt_agrees_count_with_russian_plural():
    assert "РОВНО 1 вариант " in build_system_prompt(["а"], "стиль")
    assert "РОВНО 5 вариантов" in build_system_prompt(list("абвгд"), "стиль")


def test_variants_word_handles_teens():
    assert variants_word(1) == "вариант"
    assert variants_word(3) == "варианта"
    assert variants_word(11) == "вариантов"
    assert variants_word(21) == "вариант"


def test_parse_suggestions_extracts_three():
    raw = "1) Привет!\n2) Хэй, как ты?\n3) О, приветик :)"
    out = parse_suggestions(raw)
    assert out == ["Привет!", "Хэй, как ты?", "О, приветик :)"]


def test_parse_suggestions_tolerates_blank_lines():
    raw = "1) Один\n\n2) Два\n\n3) Три\n"
    assert parse_suggestions(raw) == ["Один", "Два", "Три"]


def _bare_suggester():
    """Suggester без обращения к сети: OpenAI-клиент подменяем моком."""
    s = Suggester.__new__(Suggester)
    s._model = "deepseek-chat"
    s._system_prompt = "системный промпт"
    s._max_tokens = 700
    return s


def _make_suggester_with_reply(text):
    s = _bare_suggester()
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=msg)]
    )
    s._client = client
    return s


def test_analyze_raises_on_api_error():
    s = _bare_suggester()
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


def test_parse_analysis_strips_label_the_model_adds():
    assert parse_analysis("Краткий разбор: Диалог живой.\n1) А") == "Диалог живой."
    assert parse_analysis("**Разбор диалога**: Живой.\n1) А") == "Живой."


def test_parse_analysis_keeps_text_that_merely_starts_with_a_word():
    assert parse_analysis("Разборчиво пишет.\n1) А") == "Разборчиво пишет."


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
