from unittest.mock import MagicMock
import pytest
from datetime import datetime, timedelta, timezone

from suflor.suggester import (
    build_messages, build_system_prompt, variants_word, humanize_delta,
    initiative_summary, questions_asked, parse_suggestions, parse_analysis,
    Suggester, SuggesterError,
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


def test_build_messages_uses_partner_name():
    body = build_messages([_msg("привет", 5)], "промпт", now=NOW,
                          partner_name="Аня")[-1]["content"]
    assert "Аня: привет" in body
    assert "Собеседник:" not in body


def test_build_messages_falls_back_to_generic_partner():
    body = build_messages([_msg("привет", 5)], "промпт", now=NOW)[-1]["content"]
    assert "Собеседник: привет" in body


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
    assert "сообщений всего: Аня — 2, я — 1" in initiative_summary(history, "Аня")


def test_initiative_counts_who_breaks_long_silences():
    history = [
        _msg("привет", 60 * 24 * 3),          # начало
        _msg("ну как ты", 60 * 24 * 2),       # она вернулась через сутки
        _msg("нормально", 60 * 24 * 2 - 5, from_me=True),  # мой ответ сразу
        _msg("давно не виделись", 30, from_me=True),       # я после паузы
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


def test_build_messages_includes_initiative_block():
    history = [_msg("привет", 60), _msg("о, привет", 55, from_me=True)]
    body = build_messages(history, "промпт", now=NOW,
                          partner_name="Аня")[-1]["content"]
    assert "Инициатива в диалоге:" in body
    assert "начал переписку: Аня" in body


def test_build_messages_passes_through_truncation_flag():
    history = [_msg("привет", 60)]
    body = build_messages(history, "промпт", now=NOW, partner_name="Аня",
                          full_history=False)[-1]["content"]
    assert "начало переписки не видно" in body


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


def test_build_messages_includes_asked_questions():
    history = [_msg("Чем занимаешься?", 5)]
    body = build_messages(history, "промпт", now=NOW,
                          partner_name="Аня")[-1]["content"]
    assert "Вопросы, которые уже звучали" in body
    assert "- Аня: Чем занимаешься?" in body


def test_build_messages_skips_question_block_when_there_are_none():
    body = build_messages([_msg("привет", 5)], "промпт", now=NOW)[-1]["content"]
    assert "Вопросы, которые уже звучали" not in body
    assert "Инициатива в диалоге:" in body


def test_build_system_prompt_forbids_bouncing_the_same_question_back():
    prompt = build_system_prompt(["дерзкий"], "стиль")
    assert "не возвращай" in prompt.lower()
    assert "Вопросы, которые уже звучали" not in prompt  # это блок в user-части


def test_build_system_prompt_forbids_rephrasing_answered_questions():
    prompt = build_system_prompt(["дерзкий"], "стиль")
    assert "по смыслу, а не по буквам" in prompt
    assert "Переформулировка".lower() in prompt.lower()


def test_build_system_prompt_asks_to_analyze_initiative():
    prompt = build_system_prompt(["дерзкий"], "стиль")
    assert "инициативу" in prompt.lower()
    assert "Инициатива в диалоге" in prompt


def test_build_system_prompt_keeps_flirt_light():
    prompt = build_system_prompt(["дерзкий"], "стиль")
    assert "пошлый подтекст — нет" in prompt


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
    s._about = ""
    s._temperature = 0.7
    s._max_tokens = 700
    return s


def _make_suggester_with_reply(text, finish_reason="stop"):
    s = _bare_suggester()
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    s._client = client
    return s


def test_analyze_reports_when_reasoning_ate_the_token_budget():
    # V4 тратит токены на рассуждения; если лимит кончился раньше ответа,
    # content приходит пустым — ошибка должна называть настоящую причину
    s = _make_suggester_with_reply("", finish_reason="length")
    with pytest.raises(SuggesterError, match="max_tokens"):
        s.analyze([{"from_me": False, "text": "хай"}])


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


def test_empty_style_block_keeps_the_prompt_unchanged():
    # Регрессия: пока профиль пуст, поведение должно быть ровно прежним
    assert (build_system_prompt(["дерзкий"], "стиль", "")
            == build_system_prompt(["дерзкий"], "стиль"))


def test_style_block_goes_after_the_configured_style():
    block = "Вот как я пишу сам:\n- «норм, отдыхаю»"
    prompt = build_system_prompt(["дерзкий"], "МАНЕРА ИЗ КОНФИГА", block)
    assert block in prompt
    assert prompt.index("МАНЕРА ИЗ КОНФИГА") < prompt.index(block)


def test_style_block_does_not_override_the_response_format():
    block = "Вот как я пишу сам:\n- «норм»"
    prompt = build_system_prompt(["дерзкий"], "стиль", block)
    assert "'1) текст'" in prompt
    assert prompt.index(block) < prompt.index("'1) текст'")


def test_style_block_does_not_override_the_flirt_ceiling():
    prompt = build_system_prompt(["дерзкий"], "стиль", "Вот как я пишу сам:")
    assert "пошлый подтекст — нет" in prompt


def test_analyze_passes_the_style_block_into_the_prompt():
    s = _make_suggester_with_reply("Разбор.\n1) А")
    s._tones = ["дерзкий"]
    s._style = "стиль"
    s.analyze([{"from_me": False, "text": "хай"}],
              style_block="Вот как я пишу сам:\n- «норм»")
    sent = s._client.chat.completions.create.call_args.kwargs["messages"]
    assert "Вот как я пишу сам" in sent[0]["content"]


def test_analyze_without_a_style_block_uses_the_cached_prompt():
    s = _make_suggester_with_reply("Разбор.\n1) А")
    s.analyze([{"from_me": False, "text": "хай"}])
    sent = s._client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0]["content"] == "системный промпт"


def test_empty_about_keeps_the_prompt_unchanged():
    # Регрессия: без профиля промпт обязан остаться ровно прежним
    assert (build_system_prompt(["дерзкий"], "стиль", "", "")
            == build_system_prompt(["дерзкий"], "стиль"))


def test_about_goes_into_the_prompt_as_a_block():
    prompt = build_system_prompt(["дерзкий"], "стиль",
                                 about="Зовут Даниил, 23, Томск.")
    assert "Обо мне:" in prompt
    assert "Зовут Даниил, 23, Томск." in prompt


def test_about_replaces_the_blanket_ban_on_inventing_facts():
    # Без профиля выдумывать нельзя ничего; с профилем запрет становится
    # исключением, иначе две инструкции противоречат друг другу
    plain = build_system_prompt(["дерзкий"], "стиль")
    assert "Не выдумывай фактов обо мне и о собеседнике" in plain
    with_about = build_system_prompt(["дерзкий"], "стиль", about="Даниил.")
    assert "Не выдумывай фактов обо мне и о собеседнике" not in with_about


def test_about_allows_small_details_and_forbids_big_ones():
    prompt = build_system_prompt(["дерзкий"], "стиль", about="Даниил.")
    assert "противоречить ему нельзя" in prompt
    assert "бытового масштаба, одну на сообщение" in prompt
    assert "Про собеседника не выдумывай ничего" in prompt


def test_about_asks_to_lean_on_shared_interests():
    prompt = build_system_prompt(["дерзкий"], "стиль", about="Даниил.")
    assert "цепляйся за пересечение" in prompt
    assert "выдуманного совпадения" in prompt


def test_about_does_not_override_the_flirt_ceiling_or_the_format():
    prompt = build_system_prompt(["дерзкий"], "стиль", about="Даниил.")
    assert "пошлый подтекст — нет" in prompt
    assert "'1) текст'" in prompt


def test_analyze_keeps_about_when_the_style_block_rebuilds_the_prompt():
    # Промпт пересобирается ради выученной манеры — профиль при этом теряться
    # не должен
    s = _make_suggester_with_reply("Разбор.\n1) А")
    s._tones = ["дерзкий"]
    s._style = "стиль"
    s._about = "Зовут Даниил, 23, Томск."
    s.analyze([{"from_me": False, "text": "хай"}],
              style_block="Вот как я пишу сам:\n- «норм»")
    sent = s._client.chat.completions.create.call_args.kwargs["messages"]
    assert "Зовут Даниил, 23, Томск." in sent[0]["content"]
    assert "Вот как я пишу сам" in sent[0]["content"]


def test_suggester_puts_about_into_the_cached_prompt():
    s = Suggester(api_key="k", tones=["дерзкий"], style="стиль",
                  about="Зовут Даниил, 23, Томск.")
    assert "Зовут Даниил, 23, Томск." in s._system_prompt
