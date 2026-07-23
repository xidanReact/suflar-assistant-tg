_TONES = ["игривый", "тёплый", "с юмором"]
_NUMS = ["1⃣", "2⃣", "3⃣"]


def format_suggestions(sender_name: str, last_text: str, variants: list[str]) -> str:
    lines = [f"\U0001f4ac {sender_name}: «{last_text}»", ""]
    for i, v in enumerate(variants):
        tone = _TONES[i] if i < len(_TONES) else ""
        num = _NUMS[i] if i < len(_NUMS) else f"{i + 1})"
        tag = f" [{tone}]" if tone else ""
        lines.append(f"{num}{tag} {v}")
    return "\n".join(lines)


def format_error(sender_name: str) -> str:
    return (
        f"⚠️ Не смог сгенерировать варианты для чата с {sender_name}. "
        "Попробуй позже."
    )
