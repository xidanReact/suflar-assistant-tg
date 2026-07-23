# Суфлёр для переписок

Ассистент, который на входящие в Telegram предлагает тебе 3 варианта ответа
через DeepSeek-V3. Отправляешь ответы ты сам — бот собеседникам не пишет.

## Настройка

1. Установи зависимости:
   `.venv\Scripts\python.exe -m pip install -r requirements.txt`
2. Получи `api_id` и `api_hash` на https://my.telegram.org → API development tools.
3. Получи ключ DeepSeek на https://platform.deepseek.com.
4. Скопируй `.env.example` в `.env` и заполни `TG_API_ID`, `TG_API_HASH`, `DEEPSEEK_API_KEY`.
5. Скопируй `config.example.yaml` в `config.yaml`. Проще всего оставить
   `panel_chat: me` — подсказки будут приходить в твоё «Избранное» (Saved
   Messages). Если хочешь отдельный чат-пульт — создай приватную группу и
   укажи её **числовой** chat id (у приватных групп нет username, поэтому
   имя не подойдёт).

## Запуск

`.venv\Scripts\python.exe -m suflor.main`

При первом запуске введи код подтверждения из Telegram. Сессия сохранится в
`suflor.session`, повторный вход не потребуется.

## Управление

- `/on` / `/off` в чате-пульте — включить/выключить подсказки.
- Игнор-лист (мама, коллеги) — в `config.yaml`.
- Состояние `/on` / `/off` сбрасывается во «включено» при перезапуске бота.
