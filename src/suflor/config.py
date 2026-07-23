from dataclasses import dataclass, field
import yaml


@dataclass
class Config:
    panel_chat: str
    context_messages: int = 10
    ignore_usernames: list[str] = field(default_factory=list)
    ignore_user_ids: list[int] = field(default_factory=list)


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(
        panel_chat=data["panel_chat"],
        context_messages=data.get("context_messages", 10),
        ignore_usernames=data.get("ignore_usernames", []),
        ignore_user_ids=data.get("ignore_user_ids", []),
    )
