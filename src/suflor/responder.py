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

# Модель отдаёт управление, когда разговор дошёл до реального мира.
# Только в верхнем регистре и только в начале строки: слово
# «handoff» в обычной фразе не должно уводить диалог владельцу
_HANDOFF = re.compile(r"^\W{0,3}HANDOFF\b\W*:?\s*(.*)$")
_HANDOFF_DEFAULT = "разговор дошёл до договорённостей"

# Нумерация — только с пробелом после и без двоеточия в разделителях,
# иначе «18:00 подойдёт» превращается в «00 подойдёт». Подпись «я:» —
# только вплотную к двоеточию, иначе съедается смайл «я :)»
_PREFIX = re.compile(r"^(?:\d+[)\.]\s+)?(?:я:\s+)?", re.IGNORECASE)

# Пары кавычек: снимаем, только если в них обёрнута вся реплика.
# Типографские кавычки записаны escape-последовательностями: сырые
# символы не переживают редактирование файла
_QUOTE_PAIRS = (("«", "»"), ('"', '"'), ("\u201c", "\u201d"), ("'", "'"))

# Ответ без единой буквы или цифры отправлять нельзя
_HAS_CONTENT = re.compile(r"\w")


@dataclass
class Reply:
    """Либо текст реплики, либо причина передать диалог человеку."""
    text: str | None = None
    handoff: str | None = None


def _unwrap(text: str) -> str:
    """Снять кавычки, в которые модель завернула реплику целиком.

    Именно целиком: обрезать всё похожее на кавычки нельзя — реплика
    «он сказал "да"» осталась бы с непарной кавычкой. Удаляем пару
    только если внутри нет этих же кавычек.
    """
    for left, right in _QUOTE_PAIRS:
        if (len(text) >= 2 and text.startswith(left) and
                text.endswith(right)):
            inner = text[1:-1]
            # Убираем только если внутри нет этих же кавычек
            if left not in inner and right not in inner:
                return inner.strip()
    return text


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
    text = _PREFIX.sub("", " ".join(lines)).strip()
    text = _unwrap(text)
    if not _HAS_CONTENT.search(text):
        return Reply()
    return Reply(text=text)


def _about_block(about: str) -> str:
    """Факты обо мне. Запреты про выдумки стоят выше и здесь не
    повторяются: два правила об одном и том же модель разрешает в свою
    пользу. Профиля нет — блока нет вовсе, запретов сверху достаточно.
    """
    if not about:
        return ""
    return (
        "Факты обо мне ниже — это правда, противоречить им нельзя. "
        "Спрашивают о том, что в них есть, — отвечай по ним: коротко и "
        "по-человечески, не зачитывая анкету целиком. Мелкую бытовую "
        "деталь, которой в них нет, придумать можно: правдоподобную, "
        "одну на сообщение, и дальше держись её, если разговор к ней "
        f"вернётся.\n\nОбо мне:\n{about}\n\n")


def build_reply_prompt(style: str, about: str = "",
                       style_block: str = "") -> str:
    """Системный промпт собеседника.

    Порядок блоков продуман: модель сильнее держит начало и конец. Роль
    стоит первой, затем правила и примеры, потом мой профиль и стиль,
    и завершается протокол HANDOFF: отсюда он не соскочит в конце перед
    отправкой контекста к модели.
    """
    learned = f"\n\n{style_block}\n\n" if style_block else " "
    return (
        "Ты — это я. Пишешь от первого лица живому человеку в личной "
        "переписке на сайте знакомств. На выходе — только текст моей "
        "следующей реплики, ровно в том виде, в каком его отправят в "
        "мессенджере: голым текстом, одной репликой.\n\n"
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
        "[голосовое 12 сек], [кружок 15 сек] и дальше расшифровка. "
        "Голосовое — это голос, а не набранный текст. Стоит "
        "«не расшифровано» — содержимого не знает никто, не делай вид, "
        "что знаешь.\n\n"
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
        f"{_about_block(about)}{style}{learned}"
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
    history_text = dialog.format_history(tail, partner)
    blocks.append(f"Последние сообщения:\n{history_text}")
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
