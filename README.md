# Суфлёр для переписок

Ассистент, который на входящие в Telegram предлагает тебе 3 варианта ответа
через DeepSeek-V3. Отправляешь ответы ты сам — бот собеседникам не пишет.

## Настройка

1. Установи зависимости:
   `.venv\Scripts\python.exe -m pip install -r requirements.txt`
2. Получи `api_id` и `api_hash` на https://my.telegram.org → API development tools.
3. Получи ключ DeepSeek на https://platform.deepseek.com.
4. Скопируй `.env.example` в `.env` и заполни `TG_API_ID`, `TG_API_HASH`, `DEEPSEEK_API_KEY`.
5. Скопируй `config.example.yaml` в `config.yaml`. Создай в Telegram приватную
   группу «только я» и укажи её username (или имя контакта) в `panel_chat`.
   Можно указать `me` — тогда подсказки будут приходить в «Избранное».

## Запуск

`.venv\Scripts\python.exe -m suflor.main`

При первом запуске введи код подтверждения из Telegram. Сессия сохранится в
`suflor.session`, повторный вход не потребуется.

## Управление

- `/on` / `/off` в чате-пульте — включить/выключить подсказки.
- Игнор-лист (мама, коллеги) — в `config.yaml`.
