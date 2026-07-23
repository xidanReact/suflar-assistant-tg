from dataclasses import dataclass
from suflor.config import Config


@dataclass
class IncomingContext:
    is_private: bool
    is_bot: bool
    is_outgoing: bool
    sender_id: int
    sender_username: str | None


def should_suggest(ctx: IncomingContext, cfg: Config, enabled: bool) -> bool:
    if not enabled:
        return False
    if ctx.is_outgoing or not ctx.is_private or ctx.is_bot:
        return False
    if ctx.sender_id in cfg.ignore_user_ids:
        return False
    if ctx.sender_username and ctx.sender_username in cfg.ignore_usernames:
        return False
    return True
