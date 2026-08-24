import re
from datetime import datetime, timezone
from openai import OpenAI

_NUMBERED = re.compile(r"^\d+[)\].:-]\s*(.+)$")

# Модель любит начинать разбор с заголовка «Краткий разбор:» — он лишний
_ANALYSIS_LABEL = re.compile(
    r"^\**(краткий|короткий)?\s*разбор( диалога)?\**\s*:\s*", re.IGNORECASE)

# Пауза, начиная с которой она заметна в переписке и стоит упоминания
_PAUSE_THRESHOLD = 3600

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


def build_system_prompt(tones: list[str], style: str) -> str:
    """Системный промпт из настроек: тона и манера письма задаются в конфиге,
    структура ответа (разбор + нумерованные варианты) — нет, её парсим.
    """
    n = len(tones)
    numbered = ", ".join(f"{i + 1}) {t}" for i, t in enumerate(tones))
    return (
        "Ты помогаешь мне вести переписку на сайте знакомств. "
        "Сначала дай краткий разбор диалога: 1-2 строки о том, как идёт "
        "общение, какой тон у собеседника и что стоит учесть. "
        "Разбор — без нумерации. "
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
        "Опирайся только на то, что реально сказано в переписке. Не выдумывай "
        "фактов обо мне и о собеседнике: общих воспоминаний, планов, мест, "
        "имён, деталей биографии, которых в диалоге нет. Если известно мало — "
        "пиши проще и короче, а не сочиняй подробности. "
        "Не переигрывай. Никакого пафоса, наигранного остроумия, заготовок в "
        "духе пикап-фраз, нагромождения шуток и метафор. Одна мысль на "
        "сообщение. Лучше проще и живее, чем эффектнее. "
        "Каждый вариант — одна-две короткие фразы, как реально пишут в "
        "мессенджере, а не абзац. "
        f"{style} "
        "Каждый вариант — на отдельной строке в формате '1) текст', "
        "'2) текст', без лишних пояснений."
    )


def build_messages(history: list[dict], system_prompt: str,
                   now: datetime | None = None,
                   partner_name: str | None = None) -> list[dict]:
    """Диалог для модели: реплики, заметные паузы между ними и время,
    прошедшее с последнего сообщения.
    """
    now = now or datetime.now(timezone.utc)
    partner = partner_name or "Собеседник"
    lines = []
    prev = None
    for m in history:
        date = m.get("date")
        if date and prev:
            gap = (date - prev).total_seconds()
            if gap >= _PAUSE_THRESHOLD:
                lines.append(f"[пауза {humanize_delta(gap)}]")
        who = "Я" if m["from_me"] else partner
        lines.append(f"{who}: {m['text']}")
        prev = date or prev

    dialog = "\n".join(lines)
    last_date = history[-1].get("date") if history else None
    since = ""
    if last_date:
        elapsed = humanize_delta((now - last_date).total_seconds())
        since = f"\n\nС последнего сообщения прошло: {elapsed}."

    user = f"Вот переписка:\n{dialog}{since}\n\nДай варианты моего ответа."
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
                  max_tokens: int, partner_name: str | None = None) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=build_messages(history, system_prompt,
                                        partner_name=partner_name),
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
                partner_name: str | None = None) -> tuple[str, list[str]]:
        """Разбор диалога плюс варианты следующего сообщения."""
        raw = self._complete(self._system_prompt, history, self._max_tokens,
                             partner_name)
        variants = parse_suggestions(raw)
        if not variants:
            raise SuggesterError("модель вернула пустой/неразборчивый ответ")
        return parse_analysis(raw), variants
