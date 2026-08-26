from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from suflor.llm import LLMError
from suflor.responder import (
    Responder, build_reply_messages, build_reply_prompt, parse_reply,
)

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def _msg(text, from_me=False, minutes_ago=0):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def test_parse_reply_keeps_plain_text():
    assert parse_reply("да я тоже так думаю").text == "да я тоже так думаю"


def test_parse_reply_strips_the_speaker_prefix():
    # Модель иногда отвечает в формате переписки, хотя её не просили
    assert parse_reply("Я: ну такое").text == "ну такое"


def test_parse_reply_strips_quotes():
    assert parse_reply('«ну такое»').text == "ну такое"
    assert parse_reply('"ну такое"').text == "ну такое"


def test_parse_reply_strips_numbering():
    # Наследие суфлёра: модель по привычке нумерует единственный вариант
    assert parse_reply("1) ну такое").text == "ну такое"


def test_parse_reply_joins_wrapped_lines():
    assert parse_reply("первая строка\nвторая").text == "первая строка вторая"


def test_parse_reply_recognises_handoff():
    reply = parse_reply("HANDOFF: договариваются о встрече")
    assert reply.text is None
    assert reply.handoff == "договариваются о встрече"


def test_parse_reply_recognises_handoff_on_a_later_line():
    reply = parse_reply("Пояснение\nHANDOFF: зовёт гулять")
    assert reply.handoff == "зовёт гулять"


def test_parse_reply_handoff_without_reason_still_hands_off():
    assert parse_reply("HANDOFF").handoff


def test_parse_reply_empty_gives_nothing():
    empty = parse_reply("   \n  ")
    assert empty.text is None and empty.handoff is None


def test_parse_reply_strips_typographic_quotes():
    # DeepSeek часто оборачивает русский текст в типографские кавычки
    assert parse_reply('"ну такое"').text == "ну такое"


def test_parse_reply_preserves_internal_quotes():
    # Вторая кавычка внутри текста — не обёртка, а часть фразы
    assert (parse_reply('он сказал "да"').text ==
            'он сказал "да"')


def test_parse_reply_preserves_multiple_quote_pairs():
    # Несколько пар кавычек — всё это часть текста, не обёртка
    assert parse_reply('«да» и «нет»').text == '«да» и «нет»'


def test_parse_reply_rejects_only_punctuation():
    # Мусор из одних знаков препинания — не валидный ответ
    assert parse_reply("...").text is None
    assert parse_reply("?!").text is None


def test_parse_reply_preserves_times():
    # Время вида 18:00 не должно быть повреждено префиксной регуляркой
    assert parse_reply("18:00 подойдёт").text == "18:00 подойдёт"


def test_parse_reply_preserves_smileys():
    # Смайл «я :)» не должен быть повреждён префиксной регуляркой
    assert parse_reply("я :) не знаю").text == "я :) не знаю"


def test_parse_reply_rejects_lowercase_handoff():
    # handoff в обычной фразе не передаёт диалог, это просто текст
    reply = parse_reply("— handoff бывает разный")
    assert reply.text == "— handoff бывает разный"
    assert reply.handoff is None


def test_parse_reply_recognises_uppercase_handoff():
    # Только вверху регистра и в начале строки
    reply = parse_reply("HANDOFF: причина")
    assert reply.handoff == "причина"


def test_prompt_puts_the_model_in_my_shoes():
    prompt = build_reply_prompt("стиль")
    assert "от первого лица" in prompt
    assert "только текст" in prompt


def test_prompt_asks_for_one_short_message():
    assert "одна мысль" in build_reply_prompt("стиль")


def test_prompt_explains_the_handoff_protocol():
    prompt = build_reply_prompt("стиль")
    assert "HANDOFF:" in prompt


def test_prompt_keeps_the_three_hard_bans():
    prompt = build_reply_prompt("стиль")
    assert "о себе крупное" in prompt
    assert "о собеседнике" in prompt
    assert "ошлост" in prompt          # пошлость/пошлости


def test_prompt_includes_style_and_about():
    prompt = build_reply_prompt("мой стиль", about="Зовут Даниил, 23, Томск.")
    assert "мой стиль" in prompt
    assert "Зовут Даниил, 23, Томск." in prompt


def test_prompt_includes_the_learned_manner():
    prompt = build_reply_prompt("стиль", style_block="Вот как я пишу сам: ...")
    assert "Вот как я пишу сам" in prompt


def test_prompt_explains_media_markers():
    assert "[голосовое" in build_reply_prompt("стиль")


def test_messages_have_system_and_user_roles():
    messages = build_reply_messages([_msg("привет")], "промпт")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == "промпт"


def test_messages_include_only_the_recent_tail():
    history = [_msg(f"реплика {i}", minutes_ago=100 - i) for i in range(50)]
    user = build_reply_messages(history, "промпт", recent=10)[1]["content"]
    assert "реплика 49" in user
    assert "реплика 0" not in user


def test_messages_include_the_summary_when_there_is_one():
    user = build_reply_messages([_msg("привет")], "промпт",
                                summary="Аня, 24, из Томска")[1]["content"]
    assert "Аня, 24, из Томска" in user


def test_messages_skip_the_summary_block_when_empty():
    user = build_reply_messages([_msg("привет")], "промпт")[1]["content"]
    assert "помню об этом разговоре" not in user


def test_messages_report_time_since_the_last_message():
    user = build_reply_messages([_msg("ну что", minutes_ago=180)], "промпт",
                                now=NOW)[1]["content"]
    assert "3 часа" in user


def test_messages_carry_asked_questions_from_the_whole_history():
    # Вопросы ищутся по всей переписке, а не только по хвосту: круги
    # начинаются как раз со старых вопросов
    history = [_msg("чем занимаешься?", minutes_ago=100 - i)
               for i in range(1)] + [
        _msg(f"реплика {i}", minutes_ago=90 - i) for i in range(30)]
    user = build_reply_messages(history, "промпт", recent=5,
                                partner_name="Аня")[1]["content"]
    assert "чем занимаешься?" in user


def test_messages_end_with_the_task():
    user = build_reply_messages([_msg("привет")], "промпт")[1]["content"]
    assert user.rstrip().endswith("Только текст реплики.")


def _responder_with_reply(text, finish_reason="stop"):
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return Responder(client=client, style="стиль", about="Зовут Даниил.")


def test_reply_returns_parsed_text():
    r = _responder_with_reply("да я тоже так думаю")
    assert r.reply([_msg("привет")]).text == "да я тоже так думаю"


def test_reply_passes_handoff_through():
    r = _responder_with_reply("HANDOFF: зовёт гулять")
    assert r.reply([_msg("погуляем?")]).handoff == "зовёт гулять"


def test_reply_raises_on_empty_model_answer():
    with pytest.raises(LLMError, match="пуст"):
        _responder_with_reply("   ").reply([_msg("привет")])


def test_reply_raises_on_punctuation_only_answer():
    # Мусор из знаков препинания — не валидный ответ
    with pytest.raises(LLMError, match="пуст"):
        _responder_with_reply("...").reply([_msg("привет")])


def test_reply_raises_on_api_error():
    r = _responder_with_reply("неважно")
    r._client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    with pytest.raises(LLMError):
        r.reply([_msg("привет")])


def test_reply_sends_about_and_learned_style_to_the_model():
    r = _responder_with_reply("ок")
    r.reply([_msg("привет")], style_block="Вот как я пишу сам: ...")
    sent = r._client.chat.completions.create.call_args.kwargs["messages"]
    assert "Зовут Даниил." in sent[0]["content"]
    assert "Вот как я пишу сам" in sent[0]["content"]


def test_reply_sends_the_summary_to_the_model():
    r = _responder_with_reply("ок")
    r.reply([_msg("привет")], summary="Аня, 24, из Томска")
    sent = r._client.chat.completions.create.call_args.kwargs["messages"]
    assert "Аня, 24, из Томска" in sent[1]["content"]
