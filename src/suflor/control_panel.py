_NUMS = ["1⃣", "2⃣", "3⃣", "4⃣", "5⃣"]


def utf16_span(text: str, fragment: str) -> tuple[int, int] | None:
    """Позиция фрагмента в UTF-16 кодовых единицах — в них Telegram считает
    офсеты сущностей форматирования. Обычный len() соврёт на эмодзи.
    """
    idx = text.find(fragment)
    if idx < 0:
        return None
    offset = len(text[:idx].encode("utf-16-le")) // 2
    length = len(fragment.encode("utf-16-le")) // 2
    return offset, length


def build_chat_link(username: str | None, sender_id: int) -> str:
    """Запасной текст, когда кликабельную ссылку сделать не вышло.

    У пользователя с username есть публичная ссылка t.me. Без username
    остаётся числовой id — по нему диалог находится поиском.
    """
    if username:
        return f"https://t.me/{username}"
    return f"id {sender_id}"


def format_suggestions(sender_name: str, last_text: str, variants: list[str],
                       chat_link: str | None = None,
                       analysis: str | None = None,
                       tones: list[str] | None = None) -> str:
    tones = tones or []
    head = f"\U0001f4ac {sender_name}"
    if chat_link:
        head += f" — {chat_link}"
    lines = [head, f"«{last_text}»", ""]
    if analysis:
        lines += [f"\U0001f4ca {analysis}", ""]
    for i, v in enumerate(variants):
        tone = tones[i] if i < len(tones) else ""
        num = _NUMS[i] if i < len(_NUMS) else f"{i + 1})"
        tag = f" [{tone}]" if tone else ""
        lines.append(f"{num}{tag} {v}")
    return "\n".join(lines)


def format_error(sender_name: str) -> str:
    return (
        f"⚠️ Не смог сгенерировать варианты для чата с {sender_name}. "
        "Попробуй позже."
    )
