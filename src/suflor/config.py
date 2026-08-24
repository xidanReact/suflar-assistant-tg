from dataclasses import dataclass, field
import yaml

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_TONES = [
    "игривый, флиртующий",
    "тёплый, искренний",
    "лёгкий, с юмором",
    "спокойный, уместный — рекомендуемый",
]
DEFAULT_STYLE = (
    "Пиши на русском, как живой человек в обычной переписке: короткими "
    "простыми фразами, разговорно. Без канцелярита, пафоса, витиеватых "
    "метафор и пошлости. Не здоровайся, если разговор уже идёт, и не "
    "пересказывай то, что собеседник только что сказал."
)


@dataclass
class Config:
    panel_chat: str
    context_messages: int = 50
    tones: list[str] = field(default_factory=lambda: list(DEFAULT_TONES))
    style: str = DEFAULT_STYLE
    temperature: float = 0.7
    model: str = DEFAULT_MODEL
    ignore_usernames: list[str] = field(default_factory=list)
    ignore_user_ids: list[int] = field(default_factory=list)


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(
        panel_chat=data["panel_chat"],
        context_messages=data.get("context_messages", 50),
        # `or` вместо get с дефолтом: пустой список тонов сломал бы промпт,
        # а пустой style оставил бы модель без указаний про манеру письма
        tones=data.get("tones") or list(DEFAULT_TONES),
        style=(data.get("style") or DEFAULT_STYLE).strip(),
        temperature=float(data.get("temperature", 0.7)),
        model=data.get("model") or DEFAULT_MODEL,
        ignore_usernames=data.get("ignore_usernames", []),
        ignore_user_ids=data.get("ignore_user_ids", []),
    )
