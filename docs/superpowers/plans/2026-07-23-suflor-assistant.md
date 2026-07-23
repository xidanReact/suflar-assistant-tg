# Ассистент-суфлёр (Дайвинчик / Telegram) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать userbot на аккаунте пользователя, который на каждое входящее из личек предлагает 3 варианта ответа (через DeepSeek-V3) в служебный чат-пульт; отправку делает сам пользователь.

**Architecture:** Модульный Python-проект. Telethon слушает входящие → фильтр решает, стоит ли реагировать → suggester зовёт DeepSeek (OpenAI-совместимый API) за 3 вариантами → control_panel шлёт их в служебный чат. Бот собеседникам ничего не отправляет.

**Tech Stack:** Python 3.13, telethon, openai (клиент для DeepSeek через base_url), pyyaml, python-dotenv, pytest, pytest-asyncio.

## Global Constraints

- Python 3.13 (venv уже создан в `.venv`).
- Бот **никогда** не отправляет сообщения собеседникам — только пользователю в чат-пульт.
- DeepSeek вызывается через `openai` SDK с `base_url="https://api.deepseek.com"`, модель `deepseek-chat`.
- Секреты только в `.env` (в git не попадают); настройки в `config.yaml`.
- Все пути указаны от корня проекта `davincikBot/`.
- Исходники в `src/suflor/`, тесты в `tests/`.

---

### Task 1: Скелет проекта и зависимости

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/suflor/__init__.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Consumes: ничего.
- Produces: структуру пакета `src/suflor/`, установленные зависимости.

- [ ] **Step 1: Создать `requirements.txt`**

```
telethon==1.36.0
openai==1.54.0
pyyaml==6.0.2
python-dotenv==1.0.1
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Создать `.gitignore`**

```
.venv/
.idea/
__pycache__/
*.pyc
.env
*.session
*.session-journal
```

- [ ] **Step 3: Создать `.env.example`**

```
TG_API_ID=
TG_API_HASH=
DEEPSEEK_API_KEY=
```

- [ ] **Step 4: Создать пустые пакеты**

`src/suflor/__init__.py` — пустой файл.
`tests/__init__.py` — пустой файл.

- [ ] **Step 5: Установить зависимости**

Run (PowerShell): `.venv\Scripts\python.exe -m pip install -r requirements.txt`
Expected: установка без ошибок, в конце `Successfully installed ...`.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .gitignore .env.example src/suflor/__init__.py tests/__init__.py
git commit -m "chore: project skeleton and dependencies"
```

---

### Task 2: Конфиг (`config`)

**Files:**
- Create: `src/suflor/config.py`
- Create: `config.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: ничего.
- Produces:
  - `@dataclass Config` с полями: `context_messages: int`, `ignore_usernames: list[str]`, `ignore_user_ids: list[int]`, `panel_chat: str`.
  - `load_config(path: str) -> Config` — читает YAML, подставляет дефолты для отсутствующих полей.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_config.py
from suflor.config import load_config, Config


def test_load_config_reads_values(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "context_messages: 8\n"
        "ignore_usernames: [mom, boss]\n"
        "ignore_user_ids: [111, 222]\n"
        "panel_chat: suflor_panel\n",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_file))
    assert isinstance(cfg, Config)
    assert cfg.context_messages == 8
    assert cfg.ignore_usernames == ["mom", "boss"]
    assert cfg.ignore_user_ids == [111, 222]
    assert cfg.panel_chat == "suflor_panel"


def test_load_config_applies_defaults(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("panel_chat: suflor_panel\n", encoding="utf-8")
    cfg = load_config(str(cfg_file))
    assert cfg.context_messages == 10
    assert cfg.ignore_usernames == []
    assert cfg.ignore_user_ids == []
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.config'`.

- [ ] **Step 3: Реализовать `config.py`**

```python
# src/suflor/config.py
from dataclasses import dataclass, field
import yaml


@dataclass
class Config:
    panel_chat: str
    context_messages: int = 10
    ignore_usernames: list[str] = field(default_factory=list)
    ignore_user_ids: list[int] = field(default_factory=list)


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(
        panel_chat=data["panel_chat"],
        context_messages=data.get("context_messages", 10),
        ignore_usernames=data.get("ignore_usernames", []),
        ignore_user_ids=data.get("ignore_user_ids", []),
    )
```

- [ ] **Step 4: Создать `config.example.yaml`**

```yaml
# Куда слать подсказки: username служебной группы или "me" для Избранного
panel_chat: suflor_panel
# Сколько последних сообщений диалога отдавать модели как контекст
context_messages: 10
# Кого игнорировать (не предлагать ответы)
ignore_usernames: []
ignore_user_ids: []
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/suflor/config.py config.example.yaml tests/test_config.py
git commit -m "feat: config loading with defaults"
```

---

### Task 3: Фильтр чатов (`chat_filter`)

**Files:**
- Create: `src/suflor/chat_filter.py`
- Test: `tests/test_chat_filter.py`

**Interfaces:**
- Consumes: `Config` из Task 2.
- Produces:
  - `@dataclass IncomingContext` с полями: `is_private: bool`, `is_bot: bool`, `is_outgoing: bool`, `sender_id: int`, `sender_username: str | None`.
  - `should_suggest(ctx: IncomingContext, cfg: Config, enabled: bool) -> bool` — чистая функция, решает, реагировать ли.

Правила: реагируем только если `enabled` и `is_private` и не `is_bot` и не `is_outgoing` и sender не в ignore-list.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_chat_filter.py
from suflor.chat_filter import should_suggest, IncomingContext
from suflor.config import Config


def _cfg(**kw):
    return Config(panel_chat="p", **kw)


def _ctx(**kw):
    base = dict(is_private=True, is_bot=False, is_outgoing=False,
                sender_id=1, sender_username="anna")
    base.update(kw)
    return IncomingContext(**base)


def test_reacts_to_normal_private_incoming():
    assert should_suggest(_ctx(), _cfg(), enabled=True) is True


def test_ignores_when_disabled():
    assert should_suggest(_ctx(), _cfg(), enabled=False) is False


def test_ignores_outgoing():
    assert should_suggest(_ctx(is_outgoing=True), _cfg(), enabled=True) is False


def test_ignores_groups_and_channels():
    assert should_suggest(_ctx(is_private=False), _cfg(), enabled=True) is False


def test_ignores_bots():
    assert should_suggest(_ctx(is_bot=True), _cfg(), enabled=True) is False


def test_ignores_username_in_ignore_list():
    cfg = _cfg(ignore_usernames=["anna"])
    assert should_suggest(_ctx(sender_username="anna"), cfg, enabled=True) is False


def test_ignores_user_id_in_ignore_list():
    cfg = _cfg(ignore_user_ids=[1])
    assert should_suggest(_ctx(sender_id=1), cfg, enabled=True) is False
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_chat_filter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.chat_filter'`.

- [ ] **Step 3: Реализовать `chat_filter.py`**

```python
# src/suflor/chat_filter.py
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
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest tests/test_chat_filter.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/suflor/chat_filter.py tests/test_chat_filter.py
git commit -m "feat: chat filter logic"
```

---

### Task 4: Генератор вариантов (`suggester`)

**Files:**
- Create: `src/suflor/suggester.py`
- Test: `tests/test_suggester.py`

**Interfaces:**
- Consumes: ничего из своих модулей (принимает историю как список dict).
- Produces:
  - `build_messages(history: list[dict]) -> list[dict]` — собирает промпт (system + user) для DeepSeek. `history` — список `{"from_me": bool, "text": str}`.
  - `parse_suggestions(raw: str) -> list[str]` — парсит ответ модели в список из 3 строк (модель просят вернуть по одной на строку, с префиксами `1)`/`2)`/`3)`).
  - `Suggester` с методом `suggest(history: list[dict]) -> list[str]` — зовёт API, возвращает 3 варианта; при ошибке кидает `SuggesterError`.

- [ ] **Step 1: Написать падающие тесты (чистые функции)**

```python
# tests/test_suggester.py
from suflor.suggester import build_messages, parse_suggestions


def test_build_messages_has_system_and_user():
    history = [{"from_me": False, "text": "привет"}]
    msgs = build_messages(history)
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert "привет" in msgs[-1]["content"]


def test_parse_suggestions_extracts_three():
    raw = "1) Привет!\n2) Хэй, как ты?\n3) О, приветик :)"
    out = parse_suggestions(raw)
    assert out == ["Привет!", "Хэй, как ты?", "О, приветик :)"]


def test_parse_suggestions_tolerates_blank_lines():
    raw = "1) Один\n\n2) Два\n\n3) Три\n"
    assert parse_suggestions(raw) == ["Один", "Два", "Три"]
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `.venv\Scripts\python.exe -m pytest tests/test_suggester.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.suggester'`.

- [ ] **Step 3: Реализовать `suggester.py`**

```python
# src/suflor/suggester.py
import re
from openai import OpenAI

SYSTEM_PROMPT = (
    "Ты помогаешь мне отвечать в переписке на сайте знакомств. "
    "На основе диалога предложи РОВНО 3 варианта моего следующего ответа, "
    "каждый своим тоном: 1) игривый/флиртующий, 2) тёплый/искренний, "
    "3) лёгкий с юмором. Отвечай на русском, живо и естественно, без пошлости. "
    "Каждый вариант — на отдельной строке в формате '1) текст', '2) текст', '3) текст', "
    "без лишних пояснений."
)


class SuggesterError(Exception):
    pass


def build_messages(history: list[dict]) -> list[dict]:
    lines = []
    for m in history:
        who = "Я" if m["from_me"] else "Собеседник"
        lines.append(f"{who}: {m['text']}")
    dialog = "\n".join(lines)
    user = f"Вот переписка:\n{dialog}\n\nДай 3 варианта моего ответа."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_suggestions(raw: str) -> list[str]:
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\d+[)\].:-]\s*(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


class Suggester:
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self._client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self._model = model

    def suggest(self, history: list[dict]) -> list[str]:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=build_messages(history),
                temperature=0.9,
                max_tokens=400,
            )
        except Exception as e:
            raise SuggesterError(str(e)) from e
        raw = resp.choices[0].message.content or ""
        variants = parse_suggestions(raw)
        if not variants:
            raise SuggesterError("модель вернула пустой/неразборчивый ответ")
        return variants
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest tests/test_suggester.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Добавить тест на `Suggester.suggest` с моком клиента**

Дописать в `tests/test_suggester.py`:

```python
from unittest.mock import MagicMock
import pytest
from suflor.suggester import Suggester, SuggesterError


def _make_suggester_with_reply(text):
    s = Suggester.__new__(Suggester)
    s._model = "deepseek-chat"
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=msg)]
    )
    s._client = client
    return s


def test_suggest_returns_three_variants():
    s = _make_suggester_with_reply("1) А\n2) Б\n3) В")
    assert s.suggest([{"from_me": False, "text": "хай"}]) == ["А", "Б", "В"]


def test_suggest_raises_on_api_error():
    s = Suggester.__new__(Suggester)
    s._model = "deepseek-chat"
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    s._client = client
    with pytest.raises(SuggesterError):
        s.suggest([{"from_me": False, "text": "хай"}])
```

- [ ] **Step 6: Запустить все тесты suggester — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest tests/test_suggester.py -v`
Expected: PASS (5 passed).

- [ ] **Step 7: Commit**

```bash
git add src/suflor/suggester.py tests/test_suggester.py
git commit -m "feat: DeepSeek suggester with 3 tone variants"
```

---

### Task 5: Форматирование пульта (`control_panel`)

**Files:**
- Create: `src/suflor/control_panel.py`
- Test: `tests/test_control_panel.py`

**Interfaces:**
- Consumes: список вариантов из Task 4.
- Produces:
  - `format_suggestions(sender_name: str, last_text: str, variants: list[str]) -> str` — собирает текст-подсказку для чат-пульта.
  - `format_error(sender_name: str) -> str` — текст на случай ошибки генерации.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_control_panel.py
from suflor.control_panel import format_suggestions, format_error


def test_format_suggestions_contains_all_parts():
    text = format_suggestions("Аня", "чем занимаешься?",
                              ["вариант1", "вариант2", "вариант3"])
    assert "Аня" in text
    assert "чем занимаешься?" in text
    assert "вариант1" in text
    assert "вариант2" in text
    assert "вариант3" in text
    assert "1" in text and "2" in text and "3" in text


def test_format_error_mentions_sender():
    text = format_error("Аня")
    assert "Аня" in text
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control_panel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.control_panel'`.

- [ ] **Step 3: Реализовать `control_panel.py`**

```python
# src/suflor/control_panel.py
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
```

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `.venv\Scripts\python.exe -m pytest tests/test_control_panel.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/suflor/control_panel.py tests/test_control_panel.py
git commit -m "feat: control panel message formatting"
```

---

### Task 6: Точка входа и склейка (`main`)

**Files:**
- Create: `src/suflor/main.py`
- Create: `README.md`

**Interfaces:**
- Consumes: `load_config` (Task 2), `should_suggest`/`IncomingContext` (Task 3), `Suggester`/`SuggesterError` (Task 4), `format_suggestions`/`format_error` (Task 5).
- Produces: запускаемое приложение `python -m suflor.main`.

Примечание: main тестируется вручную (реальный Telegram), автотестов нет — вся тестируемая логика уже покрыта в Tasks 2–5.

- [ ] **Step 1: Реализовать `main.py`**

```python
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
```

- [ ] **Step 2: Создать `README.md`**

```markdown
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
```

- [ ] **Step 3: Проверить, что модуль импортируется без ошибок**

Run: `.venv\Scripts\python.exe -c "import ast; ast.parse(open('src/suflor/main.py', encoding='utf-8').read()); print('ok')"`
Expected: `ok` (проверка синтаксиса без реального запуска и без секретов).

- [ ] **Step 4: Запустить весь набор тестов**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: PASS (все тесты из Tasks 2–5, ошибок нет).

- [ ] **Step 5: Commit**

```bash
git add src/suflor/main.py README.md
git commit -m "feat: main entrypoint and telegram wiring"
```

---

### Task 7: Настройка запуска pytest (pythonpath)

**Files:**
- Create: `pyproject.toml`

**Interfaces:**
- Consumes: ничего.
- Produces: конфиг pytest, чтобы `src/` был в путях импорта (`import suflor...` работал без установки пакета).

Примечание: если тесты в Tasks 2–5 не находили `suflor`, эта задача решает проблему — её можно выполнить сразу после Task 1. Оставлена отдельно, чтобы не смешивать с бизнес-логикой.

- [ ] **Step 1: Создать `pyproject.toml`**

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Убедиться, что все тесты проходят с этим конфигом**

Run: `.venv\Scripts\python.exe -m pytest -v`
Expected: PASS (все тесты).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: pytest config with src on pythonpath"
```

---

## Порядок выполнения

Task 1 → Task 7 (pytest-конфиг нужен, чтобы `import suflor` работал в тестах) →
Task 2 → 3 → 4 → 5 → 6. То есть **Task 7 выполнить сразу после Task 1**, до первого
теста. Он вынесен в конец документа только чтобы не разрывать бизнес-логику;
в реальном порядке он идёт вторым.
