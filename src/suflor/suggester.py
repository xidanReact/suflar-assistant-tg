import re
from openai import OpenAI

SYSTEM_PROMPT = (
    "Ты помогаешь мне отвечать в переписке на сайте знакомств. "
    "На основе диалога предложи РОВНО 3 варианта моего следующего ответа, "
    "каждый своим тоном: 1) игривый/флиртующий, 2) тёплый/искренний, "
    "3) лёгкий с юмором. Отвечай на русском, живо и естественно, без пошлости. "
    "Каждый вариант — на отдельной строке в формате '1) текст', '2) текст', '3) текст', "
    "без лишних пояснений."
)


class SuggesterError(Exception):
    pass


def build_messages(history: list[dict]) -> list[dict]:
    lines = []
    for m in history:
        who = "Я" if m["from_me"] else "Собеседник"
        lines.append(f"{who}: {m['text']}")
    dialog = "\n".join(lines)
    user = f"Вот переписка:\n{dialog}\n\nДай 3 варианта моего ответа."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_suggestions(raw: str) -> list[str]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\d+[)\].:-]\s*(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


class Suggester:
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self._model = model

    def suggest(self, history: list[dict]) -> list[str]:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=build_messages(history),
                temperature=0.9,
                max_tokens=400,
            )
        except Exception as e:
            raise SuggesterError(str(e)) from e
        raw = resp.choices[0].message.content or ""
        variants = parse_suggestions(raw)
        if not variants:
            raise SuggesterError("модель вернула пустой/неразборчивый ответ")
        return variants
