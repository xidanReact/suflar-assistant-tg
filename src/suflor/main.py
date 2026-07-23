# src/suflor/main.py
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient, events

from suflor.config import load_config
from suflor.chat_filter import should_suggest, IncomingContext
from suflor.suggester import Suggester, SuggesterError
from suflor.control_panel import format_suggestions, format_error

load_dotenv()

CONFIG_PATH = os.getenv("SUFLOR_CONFIG", "config.yaml")

# Глобальное состояние: включён ли суфлёр (управляется /on /off из пульта)
STATE = {"enabled": True}


async def _collect_history(client, chat_id, limit):
    history = []
    async for msg in client.iter_messages(chat_id, limit=limit):
        if not msg.text:
            continue
        history.append({"from_me": bool(msg.out), "text": msg.text})
    history.reverse()  # от старых к новым
    return history


def _build_ctx(event, sender) -> IncomingContext:
    return IncomingContext(
        is_private=event.is_private,
        is_bot=bool(getattr(sender, "bot", False)),
        is_outgoing=bool(event.out),
        sender_id=event.sender_id or 0,
        sender_username=getattr(sender, "username", None),
    )


def main():
    api_id = int(os.environ["TG_API_ID"])
    api_hash = os.environ["TG_API_HASH"]
    deepseek_key = os.environ["DEEPSEEK_API_KEY"]

    cfg = load_config(CONFIG_PATH)
    suggester = Suggester(api_key=deepseek_key)

    client = TelegramClient("suflor.session", api_id, api_hash)

    @client.on(events.NewMessage)
    async def handler(event):
        # Команды управления из служебного чата-пульта
        if event.out and event.raw_text.strip() in ("/on", "/off"):
            STATE["enabled"] = event.raw_text.strip() == "/on"
            await client.send_message(
                cfg.panel_chat,
                f"Суфлёр {'включён' if STATE['enabled'] else 'выключен'}.",
            )
            return

        sender = await event.get_sender()
        ctx = _build_ctx(event, sender)
        if not should_suggest(ctx, cfg, STATE["enabled"]):
            return

        sender_name = getattr(sender, "first_name", None) or str(ctx.sender_id)
        history = await _collect_history(client, event.chat_id, cfg.context_messages)
        try:
            variants = await asyncio.to_thread(suggester.suggest, history)
        except SuggesterError:
            await client.send_message(cfg.panel_chat, format_error(sender_name))
            return

        text = format_suggestions(sender_name, event.raw_text, variants)
        await client.send_message(cfg.panel_chat, text)

    print("Суфлёр запущен. Первый вход — введи код из Telegram.")
    client.start()
    print(f"Готово. Подсказки идут в: {cfg.panel_chat}. Управление: /on /off")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
