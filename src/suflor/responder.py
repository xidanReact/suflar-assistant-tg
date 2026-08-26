"""Собеседник: одна реплика от моего лица вместо витрины вариантов.

Отличие от суфлёра не в промпте, а в задаче. Суфлёр показывает мне четыре
тона, чтобы я выбрал; собеседник пишет то единственное, что уйдёт человеку.
Поэтому здесь нет ни разбора, ни нумерации, а правила сформулированы
положительно: стена запретов заставляет модель писать максимально безопасную
пустоту — дежурную фразу, к которой не придраться.
"""
import re
from dataclasses import dataclass
from datetime import datetime

from suflor import dialog
from suflor.llm import LLMError, complete

DEFAULT_MODEL = "deepseek-v4-pro"

# Замерено на deepseek-v4: рассуждения занимают 1900-3900 токенов и
# списываются из того же лимита, что и ответ
_REASONING_BUDGET = 6000

# Модель отдаёт управление, когда разговор дошёл до реального мира
_HANDOFF = re.compile(r"^\W*HANDOFF\b\W*:?\s*(.*)$", re.IGNORECASE)
_HANDOFF_DEFAULT = "разговор дошёл до договорённостей"

# Наследие суфлёрского формата: нумерация и «Я:» в начале реплики
_PREFIX = re.compile(r"^\s*(?:\d+[)\].:-]\s*)?(?:я\s*:\s*)?", re.IGNORECASE)
_QUOTES = "«»\"""'"


@dataclass
class Reply:
    """Либо текст реплики, либо причина передать диалог человеку."""
    text: str | None = None
    handoff: str | None = None


def parse_reply(raw: str) -> Reply:
    """Из ответа модели — чистая реплика или сигнал передачи.

    Модель просили отдать голый текст, но она регулярно оборачивает его в
    кавычки, подписывает «Я:» или нумерует по привычке от суфлёра. Снимаем
    обёртки здесь, чтобы собеседник не получил их в сообщении.
    """
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    for line in lines:
        match = _HANDOFF.match(line)
        if match:
            return Reply(handoff=match.group(1).strip() or _HANDOFF_DEFAULT)
    if not lines:
        return Reply()
    text = _PREFIX.sub("", " ".join(lines)).strip().strip(_QUOTES).strip()
    return Reply(text=text or None)


def build_reply_prompt(style: str, about: str = "",
                       style_block: str = "") -> str:
    """Системный промпт собеседника.

    Порядок блоков не случаен: модель сильнее держит начало и конец, поэтому
    роль стоит первой, а протокол передачи диалога — последним, у самой
    границы с перепиской.
    """
    learned = f"\n\n{style_block}\n\n" if style_block else " "
    return (
        "Ты — это я. Пишешь от первого лица живому человеку в личной "
        "переписке на сайте знакомств. Ты не ассистент: вариантов не "
        "предлагаешь, разбор не пишешь, о себе как о программе не "
        "упоминаешь. На выходе — только текст моей следующей реплики, без "
        "кавычек, без нумерации и без подписи.\n\n"
        "Как писать:\n"
        "- одна мысль, одна-две короткие фразы, как реально пишут в "
        "мессенджере;\n"
        "- цепляйся за конкретную деталь, которую собеседник только что "
        "назвал: она живее общих слов;\n"
        "- если он задал вопрос, сначала ответь на него, а потом уже "
        "спрашивай сам. Вопрос в каждой реплике не обязателен — живая "
        "реплика без него лучше дежурного «а ты?»;\n"
        "- ниже сказано, сколько прошло с его сообщения. Ответ через пять "
        "минут и ответ через три дня звучат по-разному, но извиняться за "
        "небольшую паузу не нужно;\n"
        "- медиа помечено в квадратных скобках: [фото], [стикер 😂], "
        "[голосовое 12 сек] и дальше расшифровка. Голосовое — это голос, а "
        "не набранный текст. Стоит «не расшифровано» — содержимого не знает "
        "никто, не делай вид, что знаешь.\n\n"
        "Чего нельзя:\n"
        "- выдумывать о себе крупное: другой город, другую работу, семью, "
        "серьёзные события, общие с собеседником воспоминания и планы;\n"
        "- выдумывать о собеседнике вообще ничего — о нём известно только "
        "то, что он сам сказал в переписке;\n"
        "- пошлость, двусмысленности и разговоры про тело в откровенном "
        "ключе. Тепло и лёгкий интерес — да, подтекст — нет.\n\n"
        "Если разговор дошёл до договорённостей в реальном мире — встреча, "
        "свидание, время, место, созвон, обмен номерами, переход в другой "
        "мессенджер, — отвечать не надо. Вместо реплики верни одну строку:\n"
        "HANDOFF: <в двух словах, о чём договариваются>\n\n"
        f"{dialog.facts_rules(about)}{style}{learned}"
    )


def build_reply_messages(history: list[dict], system_prompt: str,
                         summary: str = "", now: datetime | None = None,
                         partner_name: str | None = None,
                         full_history: bool = True,
                         recent: int = 40) -> list[dict]:
    """Контекст ответа: сводка, хвост переписки и посчитанные в коде блоки.

    Сырыми в промпт идут только последние `recent` реплик — остальное
    представлено сводкой. Пятьсот сообщений простынёй размывают внимание, и
    свежая часть разговора тонет в старой: ровно отсюда растёт «модель
    теряет нить».

    Вопросы и инициатива считаются по всей истории, а не по хвосту: круги в
    разговоре начинаются со старых вопросов, и обрезать их нельзя.
    """
    partner = partner_name or "Собеседник"
    tail = history[-recent:] if recent else history

    blocks = []
    if summary:
        blocks.append(f"Что я помню об этом разговоре:\n{summary}")
    blocks.append(f"Последние сообщения:\n{dialog.format_history(tail, partner)}")
    elapsed = dialog.elapsed_since_last(history, now)
    if elapsed:
        blocks.append(f"С последнего сообщения прошло: {elapsed}.")
    for block in (dialog.questions_asked(history, partner),
                  dialog.initiative_summary(history, partner, full_history)):
        if block:
            blocks.append(block)
    blocks.append("Напиши мою следующую реплику. Только текст реплики.")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


class Responder:
    """Пишет одну реплику от моего лица. Клиент DeepSeek — общий с суфлёром."""

    def __init__(self, client, style: str, temperature: float = 0.7,
                 model: str = DEFAULT_MODEL, about: str = ""):
        self._client = client
        self._style = style
        self._temperature = temperature
        self._model = model
        self._about = about
        # Одна короткая реплика поверх бюджета рассуждений
        self._max_tokens = _REASONING_BUDGET + 500

    def reply(self, history: list[dict], partner_name: str | None = None,
              summary: str = "", style_block: str = "",
              full_history: bool = True, recent: int = 40) -> Reply:
        """Реплика или сигнал передать диалог мне.

        Промпт собирается на каждый вызов, а не кешируется, как у суфлёра:
        выученная манера и сводка диалога меняются по ходу переписки.
        """
        prompt = build_reply_prompt(self._style, self._about, style_block)
        raw = complete(
            self._client, self._model,
            build_reply_messages(history, prompt, summary,
                                 partner_name=partner_name,
                                 full_history=full_history, recent=recent),
            self._temperature, self._max_tokens)
        reply = parse_reply(raw)
        if reply.text is None and reply.handoff is None:
            raise LLMError("модель вернула пустой ответ")
        return reply
