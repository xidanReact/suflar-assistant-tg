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
from suflor.dialog import plural
from suflor.suggester import Suggester, SuggesterError
from suflor.matching import classify_sent
from suflor.outcome import reply_stats, score_reply, has_question
from suflor import store, profile, media, handoff, llm
from suflor.autopilot import Autopilot
from suflor.responder import Responder
from suflor.memory import Summarizer, refresh as refresh_memory
from suflor.llm import LLMError
from suflor.debounce import Debouncer
from suflor.control_panel import (
    format_suggestions, format_error, format_stats, build_chat_link,
    utf16_span, format_watchlist, format_auto_card, format_auto_sent,
    format_handoff, format_auto_list, format_send_error,
)

load_dotenv()

CONFIG_PATH = os.getenv("SUFLOR_CONFIG", "config.yaml")
DB_PATH = os.getenv("SUFLOR_DB", "suflor.db")

# Глобальное состояние: включён ли суфлёр (/on /off) и копится ли корпус
# самообучения (/learn on|off). Оба сбрасываются к значениям конфига при
# перезапуске.
STATE = {"enabled": True, "learning": True}

# Начало текущей серии реплик по диалогу: chat_id -> (текст, время).
# Нужно, чтобы склейка не портила замер скорости ответа.
BURSTS: dict[int, tuple[str, object]] = {}

# Сообщения, отправленные ботом: (chat_id, message_id). Они вернутся в
# обработчик как мои исходящие, и без этой отметки уехали бы в корпус манеры
# как мой собственный текст — модель начала бы учиться на самой себе.
SENT_BY_BOT: set[tuple[int, int]] = set()

# Как зовут собеседника в диалоге. Отправка происходит через минуту после
# разбора, отдельной задачей, и знает только chat_id — а в пульте писать
# «отправлено в 123456789» вместо имени незачем.
NAMES: dict[int, str] = {}


def is_bot_echo(chat_id: int, msg_id: int) -> bool:
    """Это эхо нашей же отправки? Отметка разовая: множество не должно расти."""
    key = (chat_id, msg_id)
    if key in SENT_BY_BOT:
        SENT_BY_BOT.discard(key)
        return True
    return False


def auto_pause_reason(conn, cfg, incoming: str, chat_id: int) -> str | None:
    """Причина не отвечать самому — или None, если можно.

    Обе проверки дешёвые и идут до обращения к модели: платить за ответ,
    который всё равно не уйдёт, незачем.
    """
    reason = handoff.detect(incoming)
    if reason:
        return reason
    in_row = store.auto_in_row(conn, chat_id)
    if in_row >= cfg.auto.max_in_row:
        return f"{in_row} автоответов подряд без тебя"
    return None


async def _collect_history(client, chat_id, limit, transcripts=None):
    """История диалога и признак того, что она целиком, а не обрезана лимитом.

    Упёрлись в лимит — начала переписки не видно, и говорить, кто написал
    первым, нельзя: первым в выборке окажется случайный человек.

    Медиа получает пометку вместо пустой строки, а голосовое — расшифровку из
    `transcripts`, если она там есть. В Telegram отсюда не ходим ни за чем:
    историю перечитывают на каждое входящее, и запрос расшифровки на каждое
    голосовое в ней выел бы пробную квоту за пару сообщений.
    """
    transcripts = transcripts or {}
    history = []
    seen = 0
    async for msg in client.iter_messages(chat_id, limit=limit):
        seen += 1
        text = media.describe(msg, transcripts.get(msg.id)) or msg.text
        if not text:
            continue
        history.append({"from_me": bool(msg.out), "text": text,
                        "date": msg.date})
    history.reverse()  # от старых к новым
    return history, seen < limit


async def resolve_incoming_text(conn, transcriber, chat_id: int, peer,
                                msg) -> str:
    """Текст входящего сообщения — тот, на который бот будет отвечать.

    Обычный текст возвращается как есть. Медиа получает пометку. Голосовое —
    единственное, ради чего мы ходим в Telegram, и ровно один раз: сперва
    смотрим кеш, а добытую расшифровку сразу в него кладём. Кеш не
    оптимизация, а условие работы: без него пробная квота кончится за день.
    """
    marker = media.describe(msg)
    if not marker:
        return msg.text or ""
    if not msg.voice:
        return marker

    cached = store.transcripts(conn, chat_id).get(msg.id) if conn else None
    if cached:
        return media.describe(msg, cached)

    text = await transcriber.transcribe(peer, msg) if transcriber else None
    if text and conn is not None:
        store.save_transcript(conn, chat_id, msg.id, text)
    return media.describe(msg, text)


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


_AUTO_OFF = ("off", "выкл", "стоп")


def parse_auto_arg(arg: str) -> tuple[bool, str]:
    """«off @anya» — выключить, «@anya» — включить.

    Слово-выключатель отделяется только пробелом: @offline_girl — это
    username, а не команда.
    """
    parts = (arg or "").strip().split(None, 1)
    if parts and parts[0].lower() in _AUTO_OFF:
        return False, parts[1].strip() if len(parts) > 1 else ""
    return True, (arg or "").strip()


def forward_origin(message) -> int | None:
    """Автор пересланного сообщения. None, если форварда нет или он скрыт."""
    fwd = getattr(message, "forward", None) if message else None
    return getattr(fwd, "sender_id", None) if fwd else None


_HINT_USAGE = ("Не понял, какой чат. Пришли «/hint @username», «/hint "
               "https://t.me/username», «/hint 123456789» или ответь /hint "
               "на пересланное сообщение.")


def _learned_style(conn, cfg, chat_id: int) -> str:
    """Выученная манера для этого диалога. Пусто, если обучение выключено."""
    if conn is None or not STATE["learning"]:
        return ""
    return profile.style_block(conn, chat_id, cfg.tones,
                               max_samples=cfg.learning.style_examples,
                               chat_quota=cfg.learning.chat_examples,
                               min_samples=cfg.learning.min_samples)


async def _dialog_memory(conn, cfg, summarizer, chat_id: int,
                         history: list[dict], partner_name: str) -> str:
    """Сводка диалога. Пустая строка — работаем без памяти, это допустимо."""
    if conn is None:
        return ""
    return await asyncio.to_thread(
        refresh_memory, conn, summarizer, chat_id, history,
        cfg.auto.memory_refresh_every, partner_name)


async def _handle_forget(client, conn, cfg, arg: str):
    """Стереть из базы всё, что связано с человеком."""
    target = parse_hint_target(arg) if arg else None
    if target is None:
        await client.send_message(
            cfg.panel_chat,
            "Кого забыть? «/forget @username» или «/forget 123456789».",
            parse_mode=None)
        return
    try:
        entity = await client.get_entity(target)
    except (ValueError, TypeError, errors.RPCError):
        await client.send_message(cfg.panel_chat, f"Не нашёл диалог: {arg}",
                                  parse_mode=None)
        return
    name = utils.get_display_name(entity) or str(target)
    store.forget_chat(conn, utils.get_peer_id(entity))
    await client.send_message(
        cfg.panel_chat, f"Забыл всё, что собрал по диалогу с {name}.",
        parse_mode=None)


async def _resolve_target(client, cfg, arg: str, usage: str):
    """Диалог по аргументу команды. None — уже отписались в пульт, почему."""
    target = parse_hint_target(arg) if arg else None
    if target is None:
        await client.send_message(cfg.panel_chat, usage, parse_mode=None)
        return None
    try:
        return await client.get_entity(target)
    except (ValueError, TypeError, errors.RPCError):
        await client.send_message(cfg.panel_chat, f"Не нашёл диалог: {arg}",
                                  parse_mode=None)
        return None


async def _handle_watch(client, conn, cfg, arg: str):
    """Взять диалог под наблюдение, а без аргумента — показать список."""
    if not arg:
        people = []
        for row in store.watched_chats(conn):
            try:
                entity = await client.get_entity(row["chat_id"])
                name = utils.get_display_name(entity)
            except (ValueError, TypeError, errors.RPCError):
                name = None
            people.append({"name": name, "username": row["username"]})
        await client.send_message(
            cfg.panel_chat, format_watchlist(people, cfg.watch_mode),
            parse_mode=None)
        return

    entity = await _resolve_target(
        client, cfg, arg, "За кем следить? «/watch @username».")
    if entity is None:
        return

    name = utils.get_display_name(entity) or str(arg)
    store.watch(conn, utils.get_peer_id(entity),
                getattr(entity, "username", None))
    total = len(store.watched_chats(conn))
    note = ("" if cfg.watch_mode == "selected"
            else " Но watch_mode: all — суфлёр и так реагирует на всех.")
    await client.send_message(
        cfg.panel_chat, f"Слежу за {name}. Всего в списке: {total}.{note}",
        parse_mode=None)


async def _handle_auto(client, conn, cfg, autopilot, summarizer, arg: str):
    """Управление автопилотом, а без аргумента — список диалогов."""
    turn_on, target_arg = parse_auto_arg(arg)
    if not target_arg:
        people = []
        for row in store.auto_chats(conn):
            try:
                entity = await client.get_entity(row["chat_id"])
                name = utils.get_display_name(entity)
            except (ValueError, TypeError, errors.RPCError):
                name = None
            people.append({"name": name, "username": row["username"],
                           "paused_reason": row["paused_reason"]})
        await client.send_message(
            cfg.panel_chat, format_auto_list(people, cfg.auto.enabled),
            parse_mode=None)
        return

    usage = ("Кому отвечать самому? «/auto @username», выключить — "
             "«/auto off @username».")
    entity = await _resolve_target(client, cfg, target_arg, usage)
    if entity is None:
        return

    name = utils.get_display_name(entity) or str(target_arg)
    chat_id = utils.get_peer_id(entity)
    if not turn_on:
        autopilot.cancel(chat_id)
        known = store.auto_off(conn, chat_id)
        note = (f"Больше не отвечаю за тебя в чате с {name}." if known
                else f"За тебя в чате с {name} я и не отвечал.")
        await client.send_message(cfg.panel_chat, note, parse_mode=None)
        return

    store.auto_on(conn, chat_id, getattr(entity, "username", None))
    # Первую сводку собираем сразу, чтобы и первый автоответ был с памятью
    history, _ = await _collect_history(client, entity, cfg.context_messages,
                                        store.transcripts(conn, chat_id))
    if history:
        await _dialog_memory(conn, cfg, summarizer, chat_id, history, name)
    total = len(store.auto_chats(conn))
    note = ("" if cfg.auto.enabled
            else " Но в конфиге auto.enabled: false — режим выключен целиком.")
    await client.send_message(
        cfg.panel_chat,
        f"Отвечаю сам в чате с {name}. Всего на автопилоте: {total}."
        f"{note}", parse_mode=None)


async def _handle_stop(client, conn, cfg, autopilot, arg: str):
    """Отменить ответ, висящий в окне отмены."""
    if arg:
        entity = await _resolve_target(
            client, cfg, arg, "Чей ответ отменить? «/stop @username».")
        if entity is None:
            return
        cancelled = autopilot.cancel(utils.get_peer_id(entity))
        name = utils.get_display_name(entity) or str(arg)
        note = (f"Отменил ответ в чат с {name}." if cancelled
                else f"В чате с {name} ничего не ждало отправки.")
        await client.send_message(cfg.panel_chat, note, parse_mode=None)
        return

    waiting = autopilot.all_pending()
    if not waiting:
        await client.send_message(cfg.panel_chat,
                                  "Ничего не ждёт отправки.", parse_mode=None)
        return
    if len(waiting) > 1:
        await client.send_message(
            cfg.panel_chat,
            f"Ответов в очереди: {len(waiting)}. Скажи, какой отменить: "
            "«/stop @username».", parse_mode=None)
        return
    autopilot.cancel(waiting[0].chat_id)
    await client.send_message(cfg.panel_chat, "Отменил, ответ не уйдёт.",
                              parse_mode=None)


async def _handle_unwatch(client, conn, cfg, arg: str):
    """Снять диалог с наблюдения."""
    entity = await _resolve_target(
        client, cfg, arg, "Кого снять? «/unwatch @username».")
    if entity is None:
        return

    name = utils.get_display_name(entity) or str(arg)
    if not store.unwatch(conn, utils.get_peer_id(entity)):
        await client.send_message(
            cfg.panel_chat, f"За {name} я и не следил.", parse_mode=None)
        return
    total = len(store.watched_chats(conn))
    await client.send_message(
        cfg.panel_chat, f"Больше не слежу за {name}. Осталось: {total}.",
        parse_mode=None)


async def harvest_chat(client, conn, entity, chat_id: int, limit: int) -> int:
    """Собрать мои сообщения из истории одного диалога. Возвращает число новых.

    Уже известные сообщения пропускаются по времени отправки — повторный
    /train не должен плодить дубли и, главное, не должен переписывать в «own»
    то, что бот уже записал как выбранный вариант.
    """
    added = 0
    async for msg in client.iter_messages(entity, limit=limit):
        if not msg.out or not msg.text or not msg.text.strip():
            continue
        if store.sent_exists(conn, chat_id, msg.date):
            continue
        store.save_sent(conn, chat_id, msg.text, "own", sent_at=msg.date)
        added += 1
    return added


def _is_harvestable(dialog, cfg) -> bool:
    """Личный диалог живого человека, не пульт и не из игнор-листа.

    Игнор-лист уважается намеренно: переписка с мамой — тоже мой текст, но
    совсем другого регистра, и в образцах для знакомств она только мешает.
    """
    entity = dialog.entity
    if not dialog.is_user or getattr(entity, "bot", False):
        return False
    if getattr(entity, "is_self", False):
        return False
    if getattr(entity, "id", None) in cfg.ignore_user_ids:
        return False
    username = getattr(entity, "username", None)
    return not (username and username in cfg.ignore_usernames)


async def _handle_train(client, conn, cfg, arg: str):
    """Собрать корпус моей манеры из уже существующей переписки."""
    limit = cfg.learning.train_messages
    if arg:
        target = parse_hint_target(arg)
        try:
            entity = await client.get_entity(target) if target else None
        except (ValueError, TypeError, errors.RPCError):
            entity = None
        if entity is None:
            await client.send_message(cfg.panel_chat,
                                      f"Не нашёл диалог: {arg}", parse_mode=None)
            return
        added = await harvest_chat(client, conn, entity,
                                   utils.get_peer_id(entity), limit)
        name = utils.get_display_name(entity) or str(target)
        await client.send_message(
            cfg.panel_chat,
            f"Собрал {added} моих сообщений из диалога с {name}.",
            parse_mode=None)
        return

    await client.send_message(cfg.panel_chat, "Собираю корпус, это небыстро…",
                              parse_mode=None)
    total, chats = 0, 0
    async for dialog in client.iter_dialogs(limit=cfg.learning.train_chats):
        if not _is_harvestable(dialog, cfg):
            continue
        added = await harvest_chat(client, conn, dialog.entity,
                                   utils.get_peer_id(dialog.entity), limit)
        if added:
            chats += 1
            total += added
    await client.send_message(
        cfg.panel_chat,
        f"Собрал {total} моих сообщений из {chats} диалогов.", parse_mode=None)


async def _handle_hint(client, cfg, suggester, summarizer, event,
                       arg: str, conn=None):
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
    chat_id = utils.get_peer_id(entity)
    # Расшифровки берём только из кеша: /hint можно звать сколько угодно, а
    # пробная квота на расшифровку одна на неделю
    cached = store.transcripts(conn, chat_id) if conn is not None else None
    history, full = await _collect_history(client, entity,
                                           cfg.context_messages, cached)
    if not history:
        await client.send_message(
            cfg.panel_chat, f"В диалоге с {name} нет текстовых сообщений.",
            parse_mode=None)
        return

    learned = _learned_style(conn, cfg, chat_id)
    summary = await _dialog_memory(conn, cfg, summarizer, chat_id, history,
                                   name)
    try:
        analysis, variants = await asyncio.to_thread(suggester.analyze,
                                                     history, name, full,
                                                     learned, summary)
    except SuggesterError:
        await client.send_message(cfg.panel_chat, format_error(name),
                                  parse_mode=None)
        return

    if conn is not None and STATE["learning"]:
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
    llm_client = llm.make_client(deepseek_key)
    suggester = Suggester(tones=cfg.tones, style=cfg.style,
                          temperature=cfg.temperature, model=cfg.model,
                          about=cfg.about, client=llm_client)
    responder = Responder(client=llm_client, style=cfg.style,
                          temperature=cfg.temperature, model=cfg.model,
                          about=cfg.about)
    summarizer = Summarizer(client=llm_client, model=cfg.model)

    conn = store.open_store(DB_PATH)
    # Диалоги, заглохшие ещё до перезапуска, ответа уже не дождутся
    STATE["learning"] = cfg.learning.enabled
    store.expire_pending(conn, datetime.now(timezone.utc) -
                         timedelta(hours=cfg.learning.outcome_window_hours))

    client = TelegramClient("suflor.session", api_id, api_hash)

    print("Суфлёр запущен. Первый вход — введи код из Telegram "
          "(и облачный пароль, если включена 2FA).")
    await client.start(password=_ask_password)

    transcriber = media.Transcriber(client)
    debouncer = Debouncer(cfg.debounce_seconds)

    async def send_auto(chat_id: int, text: str, typing_seconds: float):
        """Отправка автоответа. Всё, что связано с Telethon, живёт здесь."""
        name = NAMES.get(chat_id, str(chat_id))
        try:
            if typing_seconds:
                async with client.action(chat_id, "typing"):
                    await asyncio.sleep(typing_seconds)
            message = await client.send_message(chat_id, text)
        except errors.RPCError:
            await client.send_message(
                cfg.panel_chat, format_send_error(name, text), parse_mode=None)
            return

        SENT_BY_BOT.add((chat_id, message.id))
        store.save_sent(conn, chat_id, text, "auto", sent_at=message.date)
        await client.send_message(
            cfg.panel_chat, format_auto_sent(name, text), parse_mode=None)

    autopilot = Autopilot(send_auto, cfg.auto.cancel_window_seconds,
                          cfg.auto.typing_simulation)

    @client.on(events.Raw(types.UpdateTranscribedAudio))
    async def _on_transcribed(update):
        """Досланная расшифровка: Telegram отвечает на запрос пустым pending,
        а текст присылает отдельным апдейтом."""
        transcriber.on_update(update)

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
                await _handle_hint(client, cfg, suggester, summarizer, event,
                                   cmd[len("/hint"):].strip(), conn)
                return
            if cmd == "/train" or cmd.startswith("/train "):
                await _handle_train(client, conn, cfg,
                                    cmd[len("/train"):].strip())
                return
            if cmd == "/stats":
                await client.send_message(
                    cfg.panel_chat,
                    format_stats(store.learning_summary(conn),
                                 cfg.learning.min_samples), parse_mode=None)
                return
            if cmd in ("/learn on", "/learn off"):
                STATE["learning"] = cmd.endswith("on")
                state = "копится" if STATE["learning"] else "остановлен"
                await client.send_message(
                    cfg.panel_chat, f"Корпус самообучения {state}.",
                    parse_mode=None)
                return
            if cmd == "/watch" or cmd.startswith("/watch "):
                await _handle_watch(client, conn, cfg,
                                    cmd[len("/watch"):].strip())
                return
            if cmd == "/unwatch" or cmd.startswith("/unwatch "):
                await _handle_unwatch(client, conn, cfg,
                                      cmd[len("/unwatch"):].strip())
                return
            if cmd == "/auto" or cmd.startswith("/auto "):
                await _handle_auto(client, conn, cfg, autopilot, summarizer,
                                   cmd[len("/auto"):].strip())
                return
            if cmd == "/stop" or cmd.startswith("/stop "):
                await _handle_stop(client, conn, cfg, autopilot,
                                   cmd[len("/stop"):].strip())
                return
            if cmd == "/forget" or cmd.startswith("/forget "):
                await _handle_forget(client, conn, cfg,
                                     cmd[len("/forget"):].strip())
                return

            # Реплай на карточку — не команда и со слэша не начинается,
            # поэтому идёт после всех команд
            reply_to = event.reply_to_msg_id
            target_chat = (autopilot.chat_for_card(reply_to)
                           if reply_to else None)
            if target_chat is not None and event.raw_text.strip():
                # Я перехватил ответ своим текстом: бота снимаем, отправляем
                # моё и записываем как правку — это мой текст, он годится
                # в образцы манеры
                autopilot.cancel(target_chat)
                message = await client.send_message(target_chat,
                                                    event.raw_text)
                SENT_BY_BOT.add((target_chat, message.id))
                store.save_sent(conn, target_chat, event.raw_text, "edited",
                                sent_at=message.date)
                await client.send_message(cfg.panel_chat,
                                          "Отправил твой текст.",
                                          parse_mode=None)
                return

        # Моё сообщение в живом чате — образец манеры или выбор варианта.
        # Пишется до фильтра should_suggest: тот режет исходящие, а нам они и
        # нужны. Пульт исключён явно, иначе в корпус уедут /on и /hint.
        if event.out and event.chat_id != panel_id and event.is_private:
            if is_bot_echo(event.chat_id, event.message.id):
                return          # это наш же автоответ, он уже записан
            # Я вмешался в разговор: запланированный ответ снимаем, а паузу
            # авторежима, наоборот, снимаем — разрулил, пусть продолжает
            autopilot.cancel(event.chat_id)
            store.resume_auto(conn, event.chat_id)
            if STATE["learning"]:
                record_outgoing(conn, event.chat_id, event.raw_text,
                                event.date,
                                cfg.learning.match_window_minutes)
            return

        sender = await event.get_sender()
        ctx = _build_ctx(event, sender)
        if not should_suggest(ctx, cfg, STATE["enabled"],
                              store.is_watched(conn, event.chat_id)):
            return

        sender_name = getattr(sender, "first_name", None) or str(ctx.sender_id)

        # Форвард даёт второй путь в диалог — через шапку «Переслано от».
        # Собеседник мог запретить пересылку, тогда просто обходимся текстом.
        try:
            await client.forward_messages(cfg.panel_chat, event.message)
        except errors.RPCError:
            pass

        # Голосовое расшифровываем здесь и только здесь — один запрос на
        # одно новое сообщение. Дальше везде идёт уже разрешённый текст:
        # event.raw_text у голосового пустой, и бот отвечал бы на пустоту.
        incoming = await resolve_incoming_text(
            conn, transcriber, event.chat_id,
            await event.get_input_chat(), event.message)

        # Первую реплику серии запоминаем отдельно: исход — это «как быстро
        # она ответила», и считать его надо по первой, иначе задержка
        # окажется завышена на всю длину серии.
        reply_text, reply_at = BURSTS.setdefault(event.chat_id,
                                                 (incoming, event.date))

        # Собеседник написал ещё раз — прежний ответ уже не к месту
        autopilot.cancel(event.chat_id)

        async def run_auto(history, full, learned):
            """Ответить самому: сгенерировать, показать в пульте, отправить."""
            NAMES[event.chat_id] = sender_name
            reason = auto_pause_reason(conn, cfg, incoming, event.chat_id)
            if not reason:
                summary = await _dialog_memory(conn, cfg, summarizer,
                                               event.chat_id, history,
                                               sender_name)
                try:
                    reply = await asyncio.to_thread(
                        responder.reply, history, sender_name, summary,
                        learned, full, cfg.auto.recent_messages)
                except LLMError:
                    await client.send_message(
                        cfg.panel_chat, format_error(sender_name),
                        parse_mode=None)
                    return
                reason = reply.handoff

            if reason:
                store.pause_auto(conn, event.chat_id, reason)
                await client.send_message(
                    cfg.panel_chat, format_handoff(sender_name, reason),
                    parse_mode=None)
                return

            autopilot.schedule(event.chat_id, reply.text)
            card = await client.send_message(
                cfg.panel_chat,
                format_auto_card(sender_name, incoming, reply.text,
                                 cfg.auto.cancel_window_seconds,
                                 build_chat_link(ctx.sender_username,
                                                 ctx.sender_id)),
                parse_mode=None)
            autopilot.attach_card(event.chat_id, card.id)

        async def run_analysis():
            """Дорогая часть: выполняется один раз, когда собеседник замолчал.

            incoming, sender_name и ctx замкнуты на последнее сообщение серии
            — предыдущие отложенные задачи по этому диалогу уже отменены.
            """
            BURSTS.pop(event.chat_id, None)
            history, full = await _collect_history(
                client, event.chat_id, cfg.context_messages,
                store.transcripts(conn, event.chat_id))
            # Её ответ закрывает исходы моих предыдущих сообщений в этом чате
            if STATE["learning"]:
                resolve_outcomes(conn, event.chat_id, history, reply_text,
                                 reply_at, cfg.learning.outcome_window_hours)

            learned = _learned_style(conn, cfg, event.chat_id)
            auto_on = (cfg.auto.enabled
                       and store.is_auto(conn, event.chat_id))
            if auto_on:
                await run_auto(history, full, learned)
                return

            summary = await _dialog_memory(conn, cfg, summarizer,
                                           event.chat_id, history,
                                           sender_name)
            try:
                analysis, variants = await asyncio.to_thread(
                    suggester.analyze, history, sender_name, full, learned,
                    summary)
            except SuggesterError:
                await client.send_message(
                    cfg.panel_chat, format_error(sender_name), parse_mode=None)
                return

            if STATE["learning"]:
                store.save_suggestion(conn, event.chat_id, cfg.tones, variants,
                                      incoming)

            text, entities = await _build_panel_message(
                client, sender_name, ctx.sender_username, ctx.sender_id,
                incoming, variants, analysis, cfg.tones)
            await client.send_message(cfg.panel_chat, text,
                                      formatting_entities=entities,
                                      parse_mode=None)

        debouncer.schedule(event.chat_id, run_analysis)

    watched = len(store.watched_chats(conn))
    if cfg.watch_mode == "selected":
        # Пустой список — молчащий бот, и по логам это не отличить от поломки
        scope = (f"Слежу за {watched} "
                 f"{plural(watched, 'диалогом', 'диалогами', 'диалогами')}"
                 if watched else
                 "Список наблюдения ПУСТ: суфлёр молчит везде, отметь диалог "
                 "командой /watch @username")
    else:
        scope = "Реагирую на всех подряд (watch_mode: all)"
    on_auto = len(store.auto_chats(conn))
    auto_note = (f", на автопилоте: {on_auto}" if cfg.auto.enabled and on_auto
                 else "")
    pause = (f", склейка серий: {cfg.debounce_seconds:g} с"
             if cfg.debounce_seconds else "")
    print(f"Готово. Подсказки идут в: {cfg.panel_chat}. "
          f"{scope}{auto_note}{pause}. "
          "Управление: /on /off, разбор чата: /hint, наблюдение: "
          "/watch /unwatch, автоответы: /auto /stop, самообучение: "
          "/train /stats /learn /forget")
    await client.run_until_disconnected()


def main():
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
