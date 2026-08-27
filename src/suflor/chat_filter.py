from dataclasses import dataclass
from suflor.config import Config


@dataclass
class IncomingContext:
    is_private: bool
    is_bot: bool
    is_outgoing: bool
    sender_id: int
    sender_username: str | None


def should_suggest(ctx: IncomingContext, cfg: Config, enabled: bool,
                   is_watched: bool = False) -> bool:
    """Стоит ли тратить запрос к модели на это входящее сообщение.

    is_watched — стоит ли диалог в списке наблюдения. В режиме all он не
    учитывается, в selected — решает: остальные диалоги молчат, и токены на
    них не тратятся.
    """
    if not enabled:
        return False
    if ctx.is_outgoing or not ctx.is_private or ctx.is_bot:
        return False
    if ctx.sender_id in cfg.ignore_user_ids:
        return False
    if ctx.sender_username and ctx.sender_username in cfg.ignore_usernames:
        return False
    # Игнор-лист проверен раньше: он сильнее списка наблюдения
    if cfg.watch_mode == "selected" and not is_watched:
        return False
    return True
