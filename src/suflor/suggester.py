import re
from openai import OpenAI

ANALYSIS_SYSTEM_PROMPT = (
    "Ты помогаешь мне вести переписку на сайте знакомств. "
    "Сначала дай краткий разбор диалога: 1-2 строки о том, как идёт общение, "
    "какой тон у собеседника и что стоит учесть. Разбор — без нумерации. "
    "Затем предложи РОВНО 3 варианта моего следующего сообщения, каждый своим "
    "тоном: 1) игривый/флиртующий, 2) тёплый/искренний, 3) лёгкий с юмором. "
    "Если последним в диалоге писал я и переписка заглохла — предлагай, как её "
    "оживить, а не отвечай сам себе. "
    "Отвечай на русском, живо и естественно, без пошлости. Каждый вариант — "
    "на отдельной строке в формате '1) текст', '2) текст', '3) текст'."
)

_NUMBERED = re.compile(r"^\d+[)\].:-]\s*(.+)$")


class SuggesterError(Exception):
    pass


def build_messages(history: list[dict],
                   system_prompt: str = ANALYSIS_SYSTEM_PROMPT) -> list[dict]:
    lines = []
    for m in history:
        who = "Я" if m["from_me"] else "Собеседник"
        lines.append(f"{who}: {m['text']}")
    dialog = "\n".join(lines)
    user = f"Вот переписка:\n{dialog}\n\nДай 3 варианта моего ответа."
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
    return " ".join(lines)


class Suggester:
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self._model = model

    def _complete(self, system_prompt: str, history: list[dict],
                  max_tokens: int) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=build_messages(history, system_prompt),
                temperature=0.9,
                max_tokens=max_tokens,
            )
        except Exception as e:
            raise SuggesterError(str(e)) from e
        return resp.choices[0].message.content or ""

    def analyze(self, history: list[dict]) -> tuple[str, list[str]]:
        """Разбор диалога плюс три варианта следующего сообщения."""
        raw = self._complete(ANALYSIS_SYSTEM_PROMPT, history, 700)
        variants = parse_suggestions(raw)
        if not variants:
            raise SuggesterError("модель вернула пустой/неразборчивый ответ")
        return parse_analysis(raw), variants
