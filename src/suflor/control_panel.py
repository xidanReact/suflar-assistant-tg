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


def _head(icon: str, sender_name: str, chat_link: str | None) -> str:
    """Шапка карточки. Имя кликабельно сущностями — их вешает main; ссылка
    в тексте нужна только там, где сущность построить не вышло.
    """
    head = f"{icon} {sender_name}"
    return f"{head} — {chat_link}" if chat_link else head


def format_suggestions(sender_name: str, last_text: str, variants: list[str],
                       chat_link: str | None = None,
                       analysis: str | None = None,
                       tones: list[str] | None = None) -> str:
    tones = tones or []
    lines = [_head("\U0001f4ac", sender_name, chat_link),
             f"«{last_text}»", ""]
    if analysis:
        lines += [f"\U0001f4ca {analysis}", ""]
    for i, v in enumerate(variants):
        tone = tones[i] if i < len(tones) else ""
        num = _NUMS[i] if i < len(_NUMS) else f"{i + 1})"
        tag = f" [{tone}]" if tone else ""
        lines.append(f"{num}{tag} {v}")
    return "\n".join(lines)


def format_auto_card(sender_name: str, incoming: str, reply: str,
                     seconds: float, chat_link: str | None = None) -> str:
    """Ответ, который уйдёт сам, если его не перехватить."""
    return "\n".join([
        _head("\U0001f916", sender_name, chat_link),
        f"«{incoming}»",
        "",
        f"➡️ {reply}",
        "",
        f"Уйдёт через {seconds:g} с. Отменить — /stop, "
        "заменить — ответь на это сообщение своим текстом.",
    ])


def format_auto_sent(sender_name: str, reply: str) -> str:
    return f"✅ {sender_name} — отправлено:\n{reply}"


def format_handoff(sender_name: str, reason: str,
                   chat_link: str | None = None) -> str:
    """Бот замолчал и отдал диалог мне."""
    return "\n".join([
        _head("✋", sender_name, chat_link),
        f"Передаю тебе: {reason}.",
        "Авторежим на паузе. Вернуть бота — /auto, "
        "он продолжит сам, как только ты напишешь в диалог.",
    ])


def format_stats(summary: dict, min_samples: int) -> str:
    """Что бот успел выучить — ответ на /stats."""
    samples = summary["samples"]
    lines = [f"\U0001f9e0 Моих сообщений в корпусе: {samples} "
             f"(из {summary['sent']} отправленных, {summary['chats']} диалогов)"]
    if samples < min_samples:
        lines.append(f"Профиль ещё не собирается: нужно минимум {min_samples}. "
                     "Собрать из истории — /train")

    lines.append(f"Подсказок выдано: {summary['suggestions']}")
    tones = summary.get("tones") or {}
    if tones:
        picked = ", ".join(f"{tone} — {n}"
                           for tone, n in sorted(tones.items(),
                                                 key=lambda kv: -kv[1]))
        lines.append(f"Выбранные тона: {picked}")
    else:
        lines.append("Выбранных вариантов пока нет — пишу своё")

    # summary.get, а не summary[...]: сводка из старой базы ключей auto
    # не содержит, и /stats не должен от этого падать
    auto = summary.get("auto") or 0
    if auto:
        line = f"Автоответов отправлено: {auto}"
        if summary.get("auto_score") is not None:
            line += f", средняя оценка: {summary['auto_score']:.2f}"
        lines.append(line)

    if summary.get("avg_score") is not None:
        lines.append(f"Средняя оценка ответов: {summary['avg_score']:.2f}")
    return "\n".join(lines)


def format_watchlist(people: list[dict], watch_mode: str) -> str:
    """Ответ на /watch без аргумента: за кем суфлёр сейчас следит."""
    if not people:
        return ("👀 Список наблюдения пуст — суфлёр молчит везде, "
                "работает только /hint.\n"
                "Взять диалог под наблюдение: /watch @username")

    lines = ["👀 Слежу за:"]
    for p in people:
        name = p.get("name") or "без имени"
        lines.append(f"- {name} (@{p['username']})" if p.get("username")
                     else f"- {name}")
    if watch_mode != "selected":
        lines.append("Список сейчас не используется: watch_mode: all — "
                     "суфлёр реагирует на всех подряд.")
    return "\n".join(lines)


def format_auto_list(people: list[dict], enabled: bool = True) -> str:
    """Ответ на /auto без аргумента: где бот отвечает сам."""
    if not people:
        return ("\U0001f916 Автопилот пуст — везде работает суфлёр.\n"
                "Включить в диалоге: /auto @username")

    lines = ["\U0001f916 Отвечаю сам:"]
    for p in people:
        name = p.get("name") or "без имени"
        line = (f"- {name} (@{p['username']})" if p.get("username")
                else f"- {name}")
        if p.get("paused_reason"):
            line += f" — на паузе: {p['paused_reason']}"
        lines.append(line)
    if not enabled:
        lines.append("Список сейчас не работает: в конфиге auto.enabled: "
                     "false — бот везде только подсказывает.")
    return "\n".join(lines)


def format_error(sender_name: str) -> str:
    return (
        f"⚠️ Не смог сгенерировать варианты для чата с {sender_name}. "
        "Попробуй позже."
    )


def format_send_error(sender_name: str, reply: str) -> str:
    return (f"⚠️ Не смог отправить ответ в чат с {sender_name}. "
            f"Вот текст, отправь руками:\n{reply}")
