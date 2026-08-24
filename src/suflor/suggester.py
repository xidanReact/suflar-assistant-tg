import re
from datetime import datetime, timezone
from openai import OpenAI

_NUMBERED = re.compile(r"^\d+[)\].:-]\s*(.+)$")

# Модель любит начинать разбор с заголовка «Краткий разбор:» — он лишний
_ANALYSIS_LABEL = re.compile(
    r"^\**(краткий|короткий)?\s*разбор( диалога)?\**\s*:\s*", re.IGNORECASE)

# Пауза, начиная с которой она заметна в переписке и стоит упоминания
_PAUSE_THRESHOLD = 3600

# Вопрос — предложение, оканчивающееся на «?». Скобки-смайлы после знака
# («как дела?)») в вопрос не входят.
_QUESTION_SENTENCE = re.compile(r"[^.!?\n]+\?")
# Для сравнения вопросов на повтор: «А ты?» и «а ты?)» — один и тот же вопрос
_PUNCT = re.compile(r"[^\w\s]+", re.UNICODE)
# Сколько последних вопросов показывать: повторяются в основном свежие
_QUESTIONS_SHOWN = 12

# Замерено на deepseek-v4-flash и -pro: рассуждения занимают 1900–3900 токенов
_REASONING_BUDGET = 6000


class SuggesterError(Exception):
    pass


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


def _with_gaps(history: list[dict]):
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
    for m, gap in _with_gaps(history):
        if gap is not None and gap >= _PAUSE_THRESHOLD:
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
                    limit: int = _QUESTIONS_SHOWN) -> str:
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
            key = _PUNCT.sub("", q.lower()).strip()
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


def build_system_prompt(tones: list[str], style: str) -> str:
    """Системный промпт из настроек: тона и манера письма задаются в конфиге,
    структура ответа (разбор + нумерованные варианты) — нет, её парсим.
    """
    n = len(tones)
    numbered = ", ".join(f"{i + 1}) {t}" for i, t in enumerate(tones))
    return (
        "Ты помогаешь мне вести переписку на сайте знакомств. "
        "Сначала дай краткий разбор диалога: 2-3 строки о том, как идёт "
        "общение, какой тон у собеседника и что стоит учесть. "
        "Разбор — без нумерации. "
        "Обязательно скажи про инициативу: кто начал переписку и кто её "
        "тянет. Данные об этом посчитаны за тебя и даны блоком «Инициатива в "
        "диалоге» после переписки — опирайся на них, не пересчитывай сам. "
        "Если первым написал собеседник или он сам возвращается после пауз — "
        "интерес есть, можно отвечать теплее и свободнее. Если переписку "
        "начал и тяну я, а в ответ идут короткие реплики без встречных "
        "вопросов — не дави: пиши короче и легче, дай собеседнику место. "
        "Если начало переписки не видно, про то, кто написал первым, не "
        "говори — суди только по тому, кто её тянет сейчас. "
        f"Затем предложи РОВНО {n} {variants_word(n)} моего следующего "
        f"сообщения, каждый своим тоном: {numbered}. "
        "Если последним в диалоге писал я и переписка заглохла — предлагай, "
        "как её оживить, а не отвечай сам себе. "
        "Чувствуй момент: в переписке отмечены паузы между сообщениями и "
        "указано, сколько времени прошло с последнего. Ответ через пять минут "
        "и ответ через три дня звучат по-разному — во втором случае неуместно "
        "продолжать фразу как ни в чём не бывало, но и извиняться за молчание "
        "не нужно, если пауза небольшая. Учитывай время суток, если оно видно "
        "по переписке. "
        "Не ходи по кругу. После переписки дан список уже прозвучавших "
        "вопросов — своих и чужих. Не задавай их заново. Главное: не возвращай "
        "собеседнику вопрос, который он сам только что задал мне — на «чем "
        "занимаешься?» надо ответить, а не переспросить «а ты чем "
        "занимаешься?». Отбить вопрос обратно («а ты?», «а у тебя?») можно "
        "только тогда, когда на него в переписке ещё никто не отвечал. "
        "Ответил — двигай разговор дальше: новая тема, деталь о себе, новый "
        "вопрос. Вопрос вообще не обязателен в каждом сообщении, живая реплика "
        "без него лучше дежурного «а ты?». "
        "Опирайся только на то, что реально сказано в переписке. Не выдумывай "
        "фактов обо мне и о собеседнике: общих воспоминаний, планов, мест, "
        "имён, деталей биографии, которых в диалоге нет. Если известно мало — "
        "пиши проще и короче, а не сочиняй подробности. "
        "Не переигрывай. Никакого пафоса, наигранного остроумия, заготовок в "
        "духе пикап-фраз, нагромождения шуток и метафор. Одна мысль на "
        "сообщение. Лучше проще и живее, чем эффектнее. "
        "Флирт держи лёгким: тепло и интерес — да, пошлый подтекст — нет. Без "
        "двусмысленностей, намёков на секс и разговоров про тело и внешность "
        "в откровенном ключе. Если собеседник сам шутит на грани, можно "
        "ответить в тон, но не подхватывать и не усиливать. "
        "Каждый вариант — одна-две короткие фразы, как реально пишут в "
        "мессенджере, а не абзац. "
        f"{style} "
        "Каждый вариант — на отдельной строке в формате '1) текст', "
        "'2) текст', без лишних пояснений."
    )


def build_messages(history: list[dict], system_prompt: str,
                   now: datetime | None = None,
                   partner_name: str | None = None,
                   full_history: bool = True) -> list[dict]:
    """Диалог для модели: реплики, заметные паузы между ними, время,
    прошедшее с последнего сообщения, и сводка по инициативе.
    """
    now = now or datetime.now(timezone.utc)
    partner = partner_name or "Собеседник"
    lines = []
    for m, gap in _with_gaps(history):
        if gap is not None and gap >= _PAUSE_THRESHOLD:
            lines.append(f"[пауза {humanize_delta(gap)}]")
        who = "Я" if m["from_me"] else partner
        lines.append(f"{who}: {m['text']}")

    dialog = "\n".join(lines)
    last_date = history[-1].get("date") if history else None
    since = ""
    if last_date:
        elapsed = humanize_delta((now - last_date).total_seconds())
        since = f"\n\nС последнего сообщения прошло: {elapsed}."

    blocks = "".join(
        f"\n\n{block}" for block in
        (initiative_summary(history, partner, full_history),
         questions_asked(history, partner)) if block)

    user = (f"Вот переписка:\n{dialog}{since}{blocks}"
            "\n\nДай варианты моего ответа.")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]


def parse_suggestions(raw: str) -> list[str]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _NUMBERED.match(line)
        if m:
            out.append(m.group(1).strip())
    return out


def parse_analysis(raw: str) -> str:
    """Всё до первого пронумерованного варианта — это разбор диалога."""
    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if _NUMBERED.match(line):
            break
        if line:
            lines.append(line)
    return _ANALYSIS_LABEL.sub("", " ".join(lines)).strip()


class Suggester:
    def __init__(self, api_key: str, tones: list[str], style: str,
                 temperature: float = 0.7,
                 model: str = "deepseek-v4-pro"):
        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self._model = model
        self._system_prompt = build_system_prompt(tones, style)
        self._temperature = temperature
        # DeepSeek V4 — рассуждающие модели: внутренние рассуждения списываются
        # из того же max_tokens, что и ответ, и съедают несколько тысяч токенов.
        # Без запаса поверх них content приходит пустым, а finish_reason=length.
        self._max_tokens = _REASONING_BUDGET + 500 * len(tones)

    def _complete(self, system_prompt: str, history: list[dict],
                  max_tokens: int, partner_name: str | None = None,
                  full_history: bool = True) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=build_messages(history, system_prompt,
                                        partner_name=partner_name,
                                        full_history=full_history),
                temperature=self._temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise SuggesterError(str(e)) from e

        choice = resp.choices[0]
        content = choice.message.content or ""
        if not content and choice.finish_reason == "length":
            raise SuggesterError(
                "рассуждения модели съели весь max_tokens, на ответ не "
                "осталось места — увеличь лимит")
        return content

    def analyze(self, history: list[dict],
                partner_name: str | None = None,
                full_history: bool = True) -> tuple[str, list[str]]:
        """Разбор диалога плюс варианты следующего сообщения.

        full_history=False — переписка обрезана лимитом контекста, начало не
        видно: тогда о том, кто написал первым, судить нельзя.
        """
        raw = self._complete(self._system_prompt, history, self._max_tokens,
                             partner_name, full_history)
        variants = parse_suggestions(raw)
        if not variants:
            raise SuggesterError("модель вернула пустой/неразборчивый ответ")
        return parse_analysis(raw), variants
