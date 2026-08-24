# src/suflor/main.py
import os
import re
import asyncio
import getpass
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telethon import TelegramClient, errors, events, utils
from telethon.tl import types

from suflor.config import load_config
from suflor.chat_filter import should_suggest, IncomingContext
from suflor.suggester import Suggester, SuggesterError
from suflor.matching import classify_sent
from suflor.outcome import reply_stats, score_reply, has_question
from suflor import store
from suflor.control_panel import (
    format_suggestions, format_error, build_chat_link, utf16_span,
)

load_dotenv()

CONFIG_PATH = os.getenv("SUFLOR_CONFIG", "config.yaml")
DB_PATH = os.getenv("SUFLOR_DB", "suflor.db")

# Насколько свежей должна быть подсказка, чтобы связывать её с отправленным,
# и сколько ждём ответа, прежде чем считать, что его не будет.
# Переезжают в config.yaml в задаче 8 плана.
MATCH_WINDOW_MINUTES = 60
OUTCOME_WINDOW_HOURS = 12

# Глобальное состояние: включён ли суфлёр (управляется /on /off из пульта)
STATE = {"enabled": True}


async def _collect_history(client, chat_id, limit):
    """История диалога и признак того, что она целиком, а не обрезана лимитом.

    Упёрлись в лимит — начала переписки не видно, и говорить, кто написал
    первым, нельзя: первым в выборке окажется случайный человек.
    """
    history = []
    seen = 0
    async for msg in client.iter_messages(chat_id, limit=limit):
        seen += 1
        if not msg.text:
            continue
        history.append({"from_me": bool(msg.out), "text": msg.text,
                        "date": msg.date})
    history.reverse()  # от старых к новым
    return history, seen < limit


def record_outgoing(conn, chat_id: int, text: str, sent_at: datetime,
                    match_window_minutes: int = 60) -> int | None:
    """Записать моё отправленное, определив, откуда оно взялось.

    Подсказка привязывается только свежая: если я отвечаю через сутки после
    неё, то почти наверняка пишу уже своё, а совпадение будет случайным.
    """
    if not (text or "").strip():
        return None
    suggestion = store.last_suggestion(conn, chat_id)
    variants, suggestion_id = [], None
    if suggestion:
        age = sent_at - suggestion["created_at"]
        if timedelta(0) <= age <= timedelta(minutes=match_window_minutes):
            variants = suggestion["variants"]
            suggestion_id = suggestion["id"]

    source, index, _ = classify_sent(text, variants)
    if source == "own":
        # Своё сообщение с подсказкой не связано, даже если она была свежей
        suggestion_id, index = None, None
    return store.save_sent(conn, chat_id, text, source, suggestion_id, index,
                           sent_at)


def resolve_outcomes(conn, chat_id: int, history: list[dict],
                     reply_text: str, replied_at: datetime,
                     outcome_window_hours: int = 12) -> int:
    """Закрыть исходы моих сообщений её ответом. Возвращает число закрытых.

    Ответ на серию моих сообщений подряд засчитывается всем: это один мой
    ход, разбитый на реплики.
    """
    median_delay, median_len = reply_stats(history)
    window = timedelta(hours=outcome_window_hours).total_seconds()
    closed = 0
    for row in store.pending_outcomes(conn, chat_id):
        sent_at = row["sent_at"]
        if sent_at is None or replied_at < sent_at:
            continue
        delay = (replied_at - sent_at).total_seconds()
        if delay <= window:
            score = score_reply(int(delay), len(reply_text or ""),
                                has_question(reply_text), median_delay,
                                median_len)
            store.save_outcome(conn, row["id"], replied_at, reply_text,
                               int(delay), score)
        else:
            store.save_outcome(conn, row["id"], None, None, None, 0.0)
        closed += 1
    return closed


def _ask_password(prompt_fn=getpass.getpass) -> str:
    """Спросить облачный пароль 2FA, не выпуская наружу пустую строку.

    Telethon трактует пустой пароль как «пароль не передан» и вместо проверки
    уходит переотправлять код входа, а Telegram на это отвечает
    SendCodeUnavailableError — ошибка выглядит как проблема с кодом.
    """
    while True:
        value = prompt_fn("Облачный пароль Telegram (2FA): ")
        if value.strip():
            return value
        print("Пароль не может быть пустым — введи облачный пароль 2FA.")


def _build_ctx(event, sender) -> IncomingContext:
    return IncomingContext(
        is_private=event.is_private,
        is_bot=bool(getattr(sender, "bot", False)),
        is_outgoing=bool(event.out),
        sender_id=event.sender_id or 0,
        sender_username=getattr(sender, "username", None),
    )


async def _build_panel_message(client, sender_name: str, username: str | None,
                               sender_id: int, last_text: str,
                               variants: list[str], analysis: str = None,
                               tones: list[str] = None):
    """Текст подсказки и сущности форматирования, делающие имя кликабельным.

    С username хватает обычной ссылки t.me. Без него единственный способ
    попасть в диалог — сущность-упоминание с InputUser, а он есть только если
    Telethon уже знает собеседника. Не вышло — отдаём текстом, без ссылки.
    """
    peer = None
    if not username:
        try:
            peer = await client.get_input_entity(sender_id)
        except (ValueError, TypeError):
            peer = None

    clickable = bool(username) or peer is not None
    fallback = None if clickable else build_chat_link(username, sender_id)
    text = format_suggestions(sender_name, last_text, variants, fallback,
                              analysis, tones)
    if not clickable:
        return text, None

    span = utf16_span(text, sender_name)
    if span is None:
        return text, None

    offset, length = span
    if username:
        entity = types.MessageEntityTextUrl(
            offset, length, f"https://t.me/{username}")
    else:
        entity = types.InputMessageEntityMentionName(offset, length, peer)
    return text, [entity]


def parse_hint_target(arg: str) -> str | int | None:
    """Цель команды /hint: @username, ссылка t.me или числовой id."""
    arg = arg.strip()
    if re.fullmatch(r"-?\d+", arg):
        return int(arg)
    m = re.fullmatch(
        r"(?:https?://)?(?:t\.me/|telegram\.me/)?@?([A-Za-z][\w\d_]{3,31})",
        arg)
    return m.group(1) if m else None


def forward_origin(message) -> int | None:
    """Автор пересланного сообщения. None, если форварда нет или он скрыт."""
    fwd = getattr(message, "forward", None) if message else None
    return getattr(fwd, "sender_id", None) if fwd else None


_HINT_USAGE = ("Не понял, какой чат. Пришли «/hint @username», «/hint "
               "https://t.me/username», «/hint 123456789» или ответь /hint "
               "на пересланное сообщение.")


async def _handle_hint(client, cfg, suggester, event, arg: str, conn=None):
    """Разбор уже существующего диалога по запросу из пульта."""
    if arg:
        target = parse_hint_target(arg)
    else:
        target = forward_origin(await event.get_reply_message())
    if target is None:
        await client.send_message(cfg.panel_chat, _HINT_USAGE, parse_mode=None)
        return

    try:
        entity = await client.get_entity(target)
    except (ValueError, TypeError, errors.RPCError):
        await client.send_message(
            cfg.panel_chat, f"Не нашёл диалог: {arg or target}",
            parse_mode=None)
        return

    name = utils.get_display_name(entity) or str(target)
    history, full = await _collect_history(client, entity, cfg.context_messages)
    if not history:
        await client.send_message(
            cfg.panel_chat, f"В диалоге с {name} нет текстовых сообщений.",
            parse_mode=None)
        return

    try:
        analysis, variants = await asyncio.to_thread(suggester.analyze,
                                                     history, name, full)
    except SuggesterError:
        await client.send_message(cfg.panel_chat, format_error(name),
                                  parse_mode=None)
        return

    chat_id = utils.get_peer_id(entity)
    if conn is not None:
        store.save_suggestion(conn, chat_id, cfg.tones, variants,
                              history[-1]["text"])

    text, entities = await _build_panel_message(
        client, name, getattr(entity, "username", None), chat_id,
        history[-1]["text"], variants, analysis, cfg.tones)
    await client.send_message(cfg.panel_chat, text,
                              formatting_entities=entities, parse_mode=None)


async def _amain():
    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    deepseek_key = os.environ["DEEPSEEK_API_KEY"]

    cfg = load_config(CONFIG_PATH)
    suggester = Suggester(api_key=deepseek_key, tones=cfg.tones,
                          style=cfg.style, temperature=cfg.temperature,
                          model=cfg.model)

    conn = store.open_store(DB_PATH)
    # Диалоги, заглохшие ещё до перезапуска, ответа уже не дождутся
    store.expire_pending(conn, datetime.now(timezone.utc) -
                         timedelta(hours=OUTCOME_WINDOW_HOURS))

    client = TelegramClient("suflor.session", api_id, api_hash)

    print("Суфлёр запущен. Первый вход — введи код из Telegram "
          "(и облачный пароль, если включена 2FA).")
    await client.start(password=_ask_password)

    # id пульта нужен, чтобы /on /off не срабатывали в живых переписках
    panel_id = utils.get_peer_id(await client.get_entity(cfg.panel_chat))

    @client.on(events.NewMessage)
    async def handler(event):
        # Команды управления — только из служебного чата-пульта
        if event.out and event.chat_id == panel_id:
            cmd = event.raw_text.strip()
            if cmd in ("/on", "/off"):
                STATE["enabled"] = cmd == "/on"
                await client.send_message(
                    cfg.panel_chat,
                    f"Суфлёр {'включён' if STATE['enabled'] else 'выключен'}.",
                )
                return
            if cmd == "/hint" or cmd.startswith("/hint "):
                await _handle_hint(client, cfg, suggester, event,
                                   cmd[len("/hint"):].strip(), conn)
                return

        # Моё сообщение в живом чате — образец манеры или выбор варианта.
        # Пишется до фильтра should_suggest: тот режет исходящие, а нам они и
        # нужны. Пульт исключён явно, иначе в корпус уедут /on и /hint.
        if event.out and event.chat_id != panel_id and event.is_private:
            record_outgoing(conn, event.chat_id, event.raw_text, event.date,
                            MATCH_WINDOW_MINUTES)
            return

        sender = await event.get_sender()
        ctx = _build_ctx(event, sender)
        if not should_suggest(ctx, cfg, STATE["enabled"]):
            return

        sender_name = getattr(sender, "first_name", None) or str(ctx.sender_id)

        # Форвард даёт второй путь в диалог — через шапку «Переслано от».
        # Собеседник мог запретить пересылку, тогда просто обходимся текстом.
        try:
            await client.forward_messages(cfg.panel_chat, event.message)
        except errors.RPCError:
            pass

        history, full = await _collect_history(client, event.chat_id,
                                               cfg.context_messages)
        # Её ответ закрывает исходы моих предыдущих сообщений в этом чате
        resolve_outcomes(conn, event.chat_id, history, event.raw_text,
                         event.date, OUTCOME_WINDOW_HOURS)

        try:
            analysis, variants = await asyncio.to_thread(suggester.analyze,
                                                         history, sender_name,
                                                         full)
        except SuggesterError:
            await client.send_message(cfg.panel_chat, format_error(sender_name),
                                      parse_mode=None)
            return

        store.save_suggestion(conn, event.chat_id, cfg.tones, variants,
                              event.raw_text)

        text, entities = await _build_panel_message(
            client, sender_name, ctx.sender_username, ctx.sender_id,
            event.raw_text, variants, analysis, cfg.tones)
        await client.send_message(cfg.panel_chat, text,
                                  formatting_entities=entities,
                                  parse_mode=None)

    print(f"Готово. Подсказки идут в: {cfg.panel_chat}. "
          "Управление: /on /off, разбор чата: /hint")
    await client.run_until_disconnected()


def main():
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
