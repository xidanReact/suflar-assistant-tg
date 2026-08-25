"""Переписка в том виде, в каком её читает модель.

Здесь всё, что считается по истории в коде, а не моделью: паузы между
репликами, кто тянет разговор, какие вопросы уже звучали. Модель считает
такое плохо — она видит текст, а не арифметику, — и охотно возвращает
собеседнику вопрос, который он сам только что задал.

Модуль общий для обоих генераторов: суфлёр (`suggester`) и собеседник
(`responder`) читают одну и ту же переписку и должны видеть её одинаково.
"""
import re
from datetime import datetime, timezone

from suflor.matching import normalize

# Пауза, начиная с которой она заметна в переписке и стоит упоминания
PAUSE_THRESHOLD = 3600

# Вопрос — предложение, оканчивающееся на «?». Скобки-смайлы после знака
# («как дела?)») в вопрос не входят.
_QUESTION_SENTENCE = re.compile(r"[^.!?\n]+\?")
# Сколько последних вопросов показывать: повторяются в основном свежие
QUESTIONS_SHOWN = 12


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское согласование числительного: 1 вариант, 2 варианта, 5 вариантов."""
    if 11 <= n % 100 <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def variants_word(n: int) -> str:
    return plural(n, "вариант", "варианта", "вариантов")


def times_word(n: int) -> str:
    return plural(n, "раз", "раза", "раз")


def humanize_delta(seconds: float) -> str:
    """Промежуток времени словами — модель должна понимать его без вычислений."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return "меньше минуты"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} {plural(minutes, 'минута', 'минуты', 'минут')}"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} {plural(hours, 'час', 'часа', 'часов')}"
    days = hours // 24
    if days < 30:
        return f"{days} {plural(days, 'день', 'дня', 'дней')}"
    months = days // 30
    return f"{months} {plural(months, 'месяц', 'месяца', 'месяцев')}"


def with_gaps(history: list[dict]):
    """Сообщения вместе с паузой перед каждым (None, если дат нет)."""
    prev = None
    for m in history:
        date = m.get("date")
        gap = (date - prev).total_seconds() if date and prev else None
        yield m, gap
        prev = date or prev


def _pause_breaks(history: list[dict]) -> tuple[int, int]:
    """Сколько раз молчание после долгой паузы нарушал я и сколько — он."""
    mine = theirs = 0
    for m, gap in with_gaps(history):
        if gap is not None and gap >= PAUSE_THRESHOLD:
            if m["from_me"]:
                mine += 1
            else:
                theirs += 1
    return mine, theirs


def initiative_summary(history: list[dict], partner: str = "Собеседник",
                       full_history: bool = True) -> str:
    """Кто начинает разговор и кто его тянет — сигнал интереса, который модель
    по сырой переписке считает плохо, поэтому считаем в коде.

    Формат — подписи вида «кто: значение», без согласования по роду: имя
    собеседника подставляется как есть, а «начала» рядом с мужским именем
    выглядело бы ошибкой.
    """
    if not history:
        return ""
    mine = sum(1 for m in history if m["from_me"])
    theirs = len(history) - mine
    broke_mine, broke_theirs = _pause_breaks(history)
    def who(m: dict) -> str:
        return "я" if m["from_me"] else partner

    lines = ["Инициатива в диалоге:"]
    if full_history:
        lines.append(f"- начал переписку: {who(history[0])}")
    else:
        lines.append("- начало переписки не видно: показан только её "
                     "последний кусок, кто написал первым — неизвестно")
    lines.append(f"- сообщений всего: {partner} — {theirs}, я — {mine}")
    if broke_mine or broke_theirs:
        lines.append(
            f"- писал первым после долгой паузы: {partner} — {broke_theirs} "
            f"{times_word(broke_theirs)}, я — {broke_mine} "
            f"{times_word(broke_mine)}")
    lines.append(f"- последним писал: {who(history[-1])}")
    return "\n".join(lines)


def questions_asked(history: list[dict], partner: str = "Собеседник",
                    limit: int = QUESTIONS_SHOWN) -> str:
    """Вопросы, которые в переписке уже звучали, с указанием, кто спросил.

    Модель охотно возвращает собеседнику тот же вопрос, который он только что
    задал («а ты чем занимаешься?»), — история у неё перед глазами, но сама
    она её на повторы не проверяет. Готовый список удерживает от кольца.
    """
    seen: dict[str, tuple[str, str]] = {}
    for m in history:
        who = "я" if m["from_me"] else partner
        for q in _QUESTION_SENTENCE.findall(m.get("text") or ""):
            q = q.strip()
            key = normalize(q)
            if not key:
                continue
            # Повтор вытесняет прежнее вхождение в конец: важна свежесть
            seen.pop(key, None)
            seen[key] = (who, q)
    if not seen:
        return ""
    lines = ["Вопросы, которые уже звучали (свежие внизу):"]
    lines += [f"- {who}: {q}" for who, q in list(seen.values())[-limit:]]
    return "\n".join(lines)


NO_FACTS_RULE = (
    "Опирайся только на то, что реально сказано в переписке. Не выдумывай "
    "фактов обо мне и о собеседнике: общих воспоминаний, планов, мест, "
    "имён, деталей биографии, которых в диалоге нет. Если известно мало — "
    "пиши проще и короче, а не сочиняй подробности. ")


def facts_rules(about: str) -> str:
    """Чем модели разрешено пользоваться, отвечая за меня.

    Без профиля — прежний глухой запрет выдумывать. С профилем он смягчается
    ровно настолько, насколько просили: мелочь досочинить можно, крупное —
    нет, а про собеседника по-прежнему нельзя ничего.
    """
    if not about:
        return NO_FACTS_RULE
    return (
        "Факты обо мне даны ниже блоком «Обо мне». Это правда, противоречить "
        "ему нельзя. Спрашивают о том, что в блоке есть, — отвечай по нему: "
        "коротко и по-человечески, не зачитывая анкету целиком и не вываливая "
        "разом всё, о чём не спросили. Мелкую деталь, которой в блоке нет, "
        "придумать можно: правдоподобную, бытового масштаба, одну на "
        "сообщение — и дальше держись её, если разговор к ней вернётся. "
        "Крупное не выдумывай: другой город, другую работу, семью, серьёзные "
        "события в жизни, общие с собеседником воспоминания и планы, которых "
        "не было. Про собеседника не выдумывай ничего — о нём известно только "
        "то, что он сам сказал в переписке. "
        "Если его увлечения пересекаются с моими, цепляйся за пересечение и "
        "говори именно о нём. Но не изображай общую страсть там, где её нет: "
        "искренний интерес и вопрос живее выдуманного совпадения, и "
        "подстраиваться под каждую его тему подряд не надо. "
        f"\n\nОбо мне:\n{about}\n\n")


def format_history(history: list[dict], partner: str = "Собеседник") -> str:
    """Переписка строками «кто: что» с пометками заметных пауз."""
    lines = []
    for m, gap in with_gaps(history):
        if gap is not None and gap >= PAUSE_THRESHOLD:
            lines.append(f"[пауза {humanize_delta(gap)}]")
        who = "Я" if m["from_me"] else partner
        lines.append(f"{who}: {m['text']}")
    return "\n".join(lines)


def elapsed_since_last(history: list[dict],
                       now: datetime | None = None) -> str:
    """Сколько прошло с последнего сообщения. Пусто, если дат нет.

    Ответ через пять минут и ответ через три дня звучат по-разному, а сама
    модель разницы во времени не видит — только текст.
    """
    last = history[-1].get("date") if history else None
    if not last:
        return ""
    now = now or datetime.now(timezone.utc)
    return humanize_delta((now - last).total_seconds())
