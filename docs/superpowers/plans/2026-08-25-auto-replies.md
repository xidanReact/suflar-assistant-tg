# Авто-ответы в диалогах — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Научить бота в отмеченных `/auto` диалогах самому формулировать и отправлять ответ после окна отмены, попутно заменив генератор «разбор + 4 варианта по тонам» на генератор одной живой реплики.

**Architecture:** Форматирование переписки переезжает из `suggester.py` в общий `dialog.py`, доступ к DeepSeek — в `llm.py`. Поверх них появляется второй генератор `responder.py` (одна реплика, свой промпт), детектор стоп-сигналов `handoff.py` и `autopilot.py`, который держит по одной отложенной отправке на диалог и умеет её отменить. `main.py` получает развилку внутри `run_analysis`: диалог в `auto_chats` идёт в автопилот, остальные — в суфлёр, как сейчас. Этап 2 добавляет `memory.py` — накопительную сводку диалога, которая заменяет 500 сырых сообщений в промпте.

**Tech Stack:** Python 3.10+, Telethon 1.36, openai 3.3.1 (клиент к DeepSeek), SQLite через `sqlite3`, pytest 8.3 + pytest-asyncio 0.24 (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-08-25-auto-replies-design.md`

## Global Constraints

- Python `>=3.10`; синтаксис типов `str | None` уже используется в проекте — держаться его.
- Тесты **никогда** не ходят в сеть: клиент DeepSeek подменяется `MagicMock`, Telethon — самодельными объектами/`SimpleNamespace`, как в `tests/test_main.py`.
- Запуск тестов: `pytest -q` из корня проекта. `pythonpath = ["src"]` уже настроен в `pyproject.toml`, ставить пакет не нужно.
- Код, комментарии, docstrings, сообщения в пульт — по-русски. Docstring объясняет **почему** так сделано, а не пересказывает сигнатуру: это устоявшийся стиль всех модулей проекта.
- Ширина строки — 79 символов, как в существующем коде.
- Старый `config.yaml` без секции `auto:` обязан работать как раньше — все новые поля с дефолтами.
- Автоответ **никогда** не попадает в образцы манеры письма: он пишется в `sent` с `source="auto"`, а `MY_OWN_SOURCES = ("own", "edited")` его не выбирает. Ни одна задача не смеет добавить `"auto"` в `MY_OWN_SOURCES`.
Отклонения от спеки, принятые осознанно (оба упрощают, ничего не теряя):

- У таблицы `auto_chats` нет колонки `enabled` — включённость выражается наличием строки, как у существующей `watched`. Пауза — непустой `paused_reason`.
- Карточка авторежима показывает имя обычной ссылкой `build_chat_link`, а не кликабельной сущностью через `_build_panel_message`. Сущность нужна была там, где ссылки нет вовсе; здесь диалог и так открыт, а машинерия с `InputUser` тянет за собой лишний запрос к Telegram на каждый автоответ.

---

### Task 1: `dialog.py` — общее форматирование переписки

Чистый переезд без изменения поведения плюс две новые функции. Нужен, потому что `responder.py` из задачи 6 требует тех же блоков (паузы, инициатива, прозвучавшие вопросы), а копировать их — гарантированно развести две копии.

**Files:**
- Create: `src/suflor/dialog.py`
- Create: `tests/test_dialog.py`
- Modify: `src/suflor/suggester.py` (удалить переехавшее, импортировать из `dialog`)
- Modify: `src/suflor/main.py:17` (импорт `plural` теперь из `dialog`)
- Modify: `tests/test_suggester.py` (перенести тесты переехавших функций)

**Interfaces:**
- Consumes: `suflor.matching.normalize` (уже есть).
- Produces: модуль `suflor.dialog` с `PAUSE_THRESHOLD: int`, `QUESTIONS_SHOWN: int`, `NO_FACTS_RULE: str`, `plural(n, one, few, many) -> str`, `variants_word(n) -> str`, `times_word(n) -> str`, `humanize_delta(seconds: float) -> str`, `with_gaps(history: list[dict])`, `initiative_summary(history, partner="Собеседник", full_history=True) -> str`, `questions_asked(history, partner="Собеседник", limit=QUESTIONS_SHOWN) -> str`, `facts_rules(about: str) -> str`, `format_history(history, partner="Собеседник") -> str`, `elapsed_since_last(history, now=None) -> str`.

- [ ] **Step 1: Зафиксировать зелёную базу**

Run: `pytest -q`
Expected: PASS. Записать число тестов — после переезда оно должно остаться тем же или вырасти.

- [ ] **Step 2: Написать падающие тесты на две новые функции**

Создать `tests/test_dialog.py`:

```python
from datetime import datetime, timedelta, timezone

from suflor.dialog import format_history, elapsed_since_last

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def _msg(text, from_me=False, minutes_ago=0):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def test_format_history_labels_both_sides():
    text = format_history([_msg("привет", minutes_ago=5),
                           _msg("привет!", from_me=True, minutes_ago=4)],
                          "Аня")
    assert text == "Аня: привет\nЯ: привет!"


def test_format_history_marks_long_pauses():
    # Час молчания в переписке заметен, и модель должна его видеть
    text = format_history([_msg("ты тут?", minutes_ago=200),
                           _msg("тут", from_me=True, minutes_ago=10)])
    assert "[пауза 3 часа]" in text


def test_format_history_ignores_short_pauses():
    text = format_history([_msg("а", minutes_ago=10),
                           _msg("б", minutes_ago=8)])
    assert "пауза" not in text


def test_format_history_uses_generic_partner_by_default():
    assert format_history([_msg("привет")]).startswith("Собеседник: ")


def test_elapsed_since_last_measures_from_the_last_message():
    assert elapsed_since_last([_msg("привет", minutes_ago=90)],
                              NOW) == "1 час"


def test_elapsed_since_last_empty_without_dates():
    assert elapsed_since_last([{"from_me": False, "text": "привет"}],
                              NOW) == ""


def test_elapsed_since_last_empty_for_empty_history():
    assert elapsed_since_last([], NOW) == ""
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `pytest tests/test_dialog.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.dialog'`

- [ ] **Step 4: Создать `src/suflor/dialog.py`**

Перенести из `suggester.py` **без изменения тел**: константы `_PAUSE_THRESHOLD` (переименовать в `PAUSE_THRESHOLD`), `_QUESTION_SENTENCE`, `_QUESTIONS_SHOWN` (в `QUESTIONS_SHOWN`), `NO_FACTS_RULE`; функции `plural`, `variants_word`, `times_word`, `humanize_delta`, `_with_gaps` (в `with_gaps`), `_pause_breaks`, `initiative_summary`, `questions_asked`, `_facts_rules` (в `facts_rules`). Внутренние обращения обновить под новые имена.

Шапка модуля и две новые функции:

```python
"""Переписка в том виде, в каком её читает модель.

Здесь всё, что считается по истории в коде, а не моделью: паузы между
репликами, кто тянет разговор, какие вопросы уже звучали. Модель считает
такое плохо — она видит текст, а не арифметику, — и охотно возвращает
собеседнику вопрос, который он сам только что задал.

Модуль общий для обоих генераторов: суфлёр (`suggester`) и собеседник
(`responder`) читают одну и ту же переписку и должны видеть её одинаково.
"""
import re
from datetime import datetime, timezone

from suflor.matching import normalize


def format_history(history: list[dict], partner: str = "Собеседник") -> str:
    """Переписка строками «кто: что» с пометками заметных пауз."""
    lines = []
    for m, gap in with_gaps(history):
        if gap is not None and gap >= PAUSE_THRESHOLD:
            lines.append(f"[пауза {humanize_delta(gap)}]")
        who = "Я" if m["from_me"] else partner
        lines.append(f"{who}: {m['text']}")
    return "\n".join(lines)


def elapsed_since_last(history: list[dict],
                       now: datetime | None = None) -> str:
    """Сколько прошло с последнего сообщения. Пусто, если дат нет.

    Ответ через пять минут и ответ через три дня звучат по-разному, а сама
    модель разницы во времени не видит — только текст.
    """
    last = history[-1].get("date") if history else None
    if not last:
        return ""
    now = now or datetime.now(timezone.utc)
    return humanize_delta((now - last).total_seconds())
```

- [ ] **Step 5: Прогнать новые тесты**

Run: `pytest tests/test_dialog.py -q`
Expected: PASS

- [ ] **Step 6: Перевести `suggester.py` на `dialog`**

Удалить переехавшие определения. Вверху:

```python
from suflor.dialog import (
    format_history, elapsed_since_last, initiative_summary, questions_asked,
    facts_rules, plural, variants_word, times_word, humanize_delta,
)
```

`build_messages` переписать на общие функции, поведение то же:

```python
def build_messages(history: list[dict], system_prompt: str,
                   now: datetime | None = None,
                   partner_name: str | None = None,
                   full_history: bool = True) -> list[dict]:
    """Диалог для модели: реплики, заметные паузы между ними, время,
    прошедшее с последнего сообщения, и сводка по инициативе.
    """
    partner = partner_name or "Собеседник"
    dialog_text = format_history(history, partner)
    elapsed = elapsed_since_last(history, now)
    since = f"\n\nС последнего сообщения прошло: {elapsed}." if elapsed else ""
    blocks = "".join(
        f"\n\n{block}" for block in
        (initiative_summary(history, partner, full_history),
         questions_asked(history, partner)) if block)
    user = (f"Вот переписка:\n{dialog_text}{since}{blocks}"
            "\n\nДай варианты моего ответа.")
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user},
    ]
```

В `_facts_rules(about)` внутри `build_system_prompt` заменить вызов на `facts_rules(about)`.

- [ ] **Step 7: Поправить импорт в `main.py`**

Было (строки 15-17):

```python
from suflor.suggester import Suggester, SuggesterError, plural
```

Стало:

```python
from suflor.dialog import plural
from suflor.suggester import Suggester, SuggesterError
```

- [ ] **Step 8: Перенести тесты переехавших функций**

Из `tests/test_suggester.py` в `tests/test_dialog.py` переехать целиком (тела не менять, только импорт): `test_humanize_delta_scales_units`, `test_humanize_delta_clamps_negative_skew`, все `test_initiative_*`, все `test_questions_*`, `test_variants_word_handles_teens`. Тесты `test_build_messages_*` и `test_build_system_prompt_*` **остаются** в `test_suggester.py` — они проверяют суфлёра, а не форматирование.

- [ ] **Step 9: Прогнать всё**

Run: `pytest -q`
Expected: PASS, число тестов не меньше зафиксированного в шаге 1.

- [ ] **Step 10: Commit**

```bash
git add src/suflor/dialog.py src/suflor/suggester.py src/suflor/main.py tests/test_dialog.py tests/test_suggester.py
git commit -m "refactor: форматирование переписки переехало в dialog.py"
```

---

### Task 2: `llm.py` — один клиент DeepSeek на всех

Сейчас клиент и разбор ответа зашиты в `Suggester._complete`. Второму генератору нужно то же самое, а второй `OpenAI(api_key=...)` на тот же ключ — лишний объект и второе место, где чинить обработку ошибок.

**Files:**
- Create: `src/suflor/llm.py`
- Create: `tests/test_llm.py`
- Modify: `src/suflor/suggester.py`

**Interfaces:**
- Produces: `suflor.llm.LLMError(Exception)`, `make_client(api_key: str) -> OpenAI`, `complete(client, model: str, messages: list[dict], temperature: float, max_tokens: int) -> str`.
- `suflor.suggester.SuggesterError` остаётся именем-псевдонимом `LLMError`, чтобы `main.py` и `tests/test_suggester.py` не переписывать.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_llm.py`:

```python
from unittest.mock import MagicMock

import pytest

from suflor.llm import complete, LLMError


def _client(text, finish_reason="stop"):
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


def test_returns_model_content():
    client = _client("привет")
    assert complete(client, "m", [{"role": "user", "content": "?"}],
                    0.7, 100) == "привет"


def test_passes_parameters_through():
    client = _client("ок")
    messages = [{"role": "user", "content": "?"}]
    complete(client, "deepseek-v4-pro", messages, 0.3, 555)
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "deepseek-v4-pro"
    assert kwargs["messages"] is messages
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 555


def test_explains_when_reasoning_ate_the_budget():
    # V4 тратит max_tokens на рассуждения; пустой content при
    # finish_reason=length — это не поломка сети, а слишком малый лимит
    with pytest.raises(LLMError, match="увеличь лимит"):
        complete(_client("", finish_reason="length"), "m", [], 0.7, 10)


def test_wraps_api_errors():
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    with pytest.raises(LLMError, match="сеть легла"):
        complete(client, "m", [], 0.7, 10)


def test_empty_content_without_length_is_returned_as_is():
    # Пустой ответ по другой причине разбирает вызывающий: у суфлёра и у
    # собеседника разные представления о том, что считать пустотой
    assert complete(_client(None), "m", [], 0.7, 10) == ""
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_llm.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.llm'`

- [ ] **Step 3: Создать `src/suflor/llm.py`**

```python
"""Доступ к DeepSeek: один клиент и один разбор ответа на всех.

Генераторов в проекте два — суфлёр и собеседник, — а ключ, базовый URL и
грабли у них общие. Главные грабли: V4 — рассуждающая модель, внутренние
рассуждения списываются из того же max_tokens, что и ответ. Кончился лимит
раньше ответа — приходит пустой content и finish_reason=length, что снаружи
выглядит как «модель промолчала», хотя чинится увеличением лимита.
"""
from openai import OpenAI

BASE_URL = "https://api.deepseek.com"


class LLMError(Exception):
    pass


def make_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def complete(client, model: str, messages: list[dict], temperature: float,
             max_tokens: int) -> str:
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens)
    except Exception as e:
        raise LLMError(str(e)) from e

    choice = resp.choices[0]
    content = choice.message.content or ""
    if not content and choice.finish_reason == "length":
        raise LLMError(
            "рассуждения модели съели весь max_tokens, на ответ не "
            "осталось места — увеличь лимит")
    return content
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_llm.py -q`
Expected: PASS

- [ ] **Step 5: Перевести `Suggester` на `llm`**

В `suggester.py` удалить `from openai import OpenAI`, класс `SuggesterError` и тело `_complete`. Добавить:

```python
from suflor.llm import LLMError, make_client, complete

# Имя, под которым ошибку ловит main и тесты: снаружи это по-прежнему
# «суфлёр не смог», внутри — общая ошибка обращения к модели
SuggesterError = LLMError
```

Конструктор принимает готовый клиент, но умеет создать свой — тесты и старый вызов с `api_key` должны продолжать работать:

```python
    def __init__(self, api_key: str | None = None, tones: list[str] = None,
                 style: str = "", temperature: float = 0.7,
                 model: str = "deepseek-v4-pro", about: str = "",
                 client=None):
        self._client = client or make_client(api_key)
```

`_complete` становится тонкой обёрткой:

```python
    def _complete(self, system_prompt: str, history: list[dict],
                  max_tokens: int, partner_name: str | None = None,
                  full_history: bool = True) -> str:
        return complete(
            self._client, self._model,
            build_messages(history, system_prompt, partner_name=partner_name,
                           full_history=full_history),
            self._temperature, max_tokens)
```

- [ ] **Step 6: Прогнать всё**

Run: `pytest -q`
Expected: PASS — `tests/test_suggester.py` не менялся и должен остаться зелёным.

- [ ] **Step 7: Commit**

```bash
git add src/suflor/llm.py src/suflor/suggester.py tests/test_llm.py
git commit -m "refactor: клиент DeepSeek вынесен в llm.py"
```

---

### Task 3: `handoff.py` — детектор договорённостей в реале

Единственный тип разговора, который бот не ведёт сам. Детектор в коде тупой, но не забывает; второй слой — флаг от модели — появится в задаче 6.

**Files:**
- Create: `src/suflor/handoff.py`
- Create: `tests/test_handoff.py`

**Interfaces:**
- Produces: `suflor.handoff.detect(text: str) -> str | None` — вернёт сработавшее слово (причина для пульта) или `None`.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_handoff.py`:

```python
import pytest

from suflor.handoff import detect

MEETING = [
    "может встретимся на выходных?",
    "давай пересечёмся в центре",
    "сходим куда-нибудь?",
    "погуляем завтра?",
    "го на свидание",
    "скинь номер, наберу",
    "давай созвонимся вечером",
    "позвони мне как освободишься",
    "напиши мне в вотсап",
    "я в whatsapp есть",
    "во сколько тебе удобно?",
    "какой у тебя адрес",
    "заеду за тобой в семь",
]

ORDINARY = [
    "привет, как дела?",
    "смотрел вчера новый фильм, вообще не зашёл",
    "я на работе до шести обычно",
    "люблю кофе и долгие прогулки в наушниках",
    "увидимся!",
    "ну ты и придумал конечно",
    "работаю в поддержке, отвечаю на звонки",
]


@pytest.mark.parametrize("text", MEETING)
def test_detects_real_world_arrangements(text):
    assert detect(text) is not None


@pytest.mark.parametrize("text", ORDINARY)
def test_ignores_ordinary_talk(text):
    assert detect(text) is None


def test_returns_the_matched_phrase_as_reason():
    # Причина уходит в пульт: «передаю тебе — созвонимся»
    assert "созвон" in detect("давай созвонимся вечером")


def test_case_and_punctuation_do_not_matter():
    assert detect("ВСТРЕТИМСЯ?!") is not None


def test_empty_text_is_safe():
    assert detect("") is None
    assert detect(None) is None
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_handoff.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.handoff'`

- [ ] **Step 3: Создать `src/suflor/handoff.py`**

```python
"""Разговор дошёл до реального мира — дальше без бота.

Договорённости о встрече, времени, месте и номере телефона — единственное,
что бот не ведёт сам: за них потом отдуваться живому человеку. Детектор
намеренно тупой, зато детерминированный и проверяемый тестами; второй слой —
флаг HANDOFF от самой модели — ловит то, что списком слов не выразить.

Ложное срабатывание здесь дёшево (диалог просто вернётся ко мне), пропуск —
дорого, поэтому список составлен с запасом. Единственное исключение —
«увидимся»: это прощание, а не договорённость, и по нему бот замолкал бы в
конце каждого разговора.
"""
import re

_PATTERNS = (
    r"встрет\w*", r"встреч\w*", r"пересеч\w*", r"пересек\w*",
    r"свидан\w*", r"погуля\w*", r"прогуля\w*", r"сходим", r"сходить",
    r"созвон\w*", r"позвон\w*", r"наберу", r"набери",
    r"номер", r"телефончик", r"whatsapp", r"вотсап", r"ватсап",
    r"телеграм\w* нет", r"инстаграм\w*", r"инсту",
    r"во сколько", r"адрес", r"приезжай", r"подъед\w*", r"заед\w*",
    r"кофе", r"в кино", r"в бар", r"в кафе",
)

_RE = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)


def detect(text: str | None) -> str | None:
    """Сработавшее слово — оно же причина для пульта. None — можно отвечать."""
    match = _RE.search(text or "")
    return match.group(0).lower() if match else None
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_handoff.py -q`
Expected: PASS. Если какой-то из `ORDINARY` ложно сработал — правится **список**, а не тест: тест описывает требование «на обычную болтовню бот не замолкает».

- [ ] **Step 5: Commit**

```bash
git add src/suflor/handoff.py tests/test_handoff.py
git commit -m "feat: детектор договорённостей в реале"
```

---

### Task 4: Хранилище — список диалогов на автопилоте

**Files:**
- Modify: `src/suflor/store.py` (схема, новые функции, `forget_chat`, `learning_summary`)
- Modify: `tests/test_store.py`

**Interfaces:**
- Consumes: `open_store`, `save_sent`, `_iso`, `_dt` (уже есть).
- Produces: `auto_on(conn, chat_id, username, added_at=None) -> None`, `auto_off(conn, chat_id) -> bool`, `auto_chats(conn) -> list[sqlite3.Row]`, `is_auto(conn, chat_id) -> bool`, `pause_auto(conn, chat_id, reason: str) -> None`, `resume_auto(conn, chat_id) -> bool`, `auto_state(conn, chat_id) -> dict | None`, `auto_in_row(conn, chat_id) -> int`. `learning_summary` дополняется ключами `auto` (int) и `auto_score` (float | None).

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_store.py` (импорты добавить в существующий блок вверху файла):

```python
def test_auto_on_puts_the_chat_on_autopilot(tmp_path):
    conn = _store(tmp_path)
    assert is_auto(conn, 1) is False
    auto_on(conn, 1, "anya", NOW)
    assert is_auto(conn, 1) is True


def test_auto_on_twice_refreshes_username_without_duplicating(tmp_path):
    conn = _store(tmp_path)
    auto_on(conn, 1, "anya", NOW)
    auto_on(conn, 1, "anna", NOW)
    rows = auto_chats(conn)
    assert len(rows) == 1
    assert rows[0]["username"] == "anna"


def test_auto_off_reports_whether_it_was_on(tmp_path):
    conn = _store(tmp_path)
    auto_on(conn, 1, None, NOW)
    assert auto_off(conn, 1) is True
    assert auto_off(conn, 1) is False   # второй раз — уже нечего снимать
    assert is_auto(conn, 1) is False


def test_paused_chat_is_not_auto_but_stays_in_the_list(tmp_path):
    # Пауза — не выключение: диалог виден в /auto с причиной
    conn = _store(tmp_path)
    auto_on(conn, 1, None, NOW)
    pause_auto(conn, 1, "договариваются о встрече")
    assert is_auto(conn, 1) is False
    assert auto_state(conn, 1)["paused_reason"] == "договариваются о встрече"
    assert len(auto_chats(conn)) == 1


def test_resume_auto_clears_the_pause(tmp_path):
    conn = _store(tmp_path)
    auto_on(conn, 1, None, NOW)
    pause_auto(conn, 1, "причина")
    assert resume_auto(conn, 1) is True
    assert is_auto(conn, 1) is True
    assert resume_auto(conn, 1) is False   # паузы не было — сообщать не о чем


def test_auto_on_lifts_an_existing_pause(tmp_path):
    conn = _store(tmp_path)
    auto_on(conn, 1, None, NOW)
    pause_auto(conn, 1, "причина")
    auto_on(conn, 1, None, NOW)
    assert is_auto(conn, 1) is True


def test_auto_state_is_none_for_unknown_chat(tmp_path):
    assert auto_state(_store(tmp_path), 42) is None


def test_auto_in_row_counts_the_tail_of_auto_messages(tmp_path):
    conn = _store(tmp_path)
    save_sent(conn, 1, "своё", "own", sent_at=NOW)
    for i in range(3):
        save_sent(conn, 1, f"бот {i}", "auto",
                  sent_at=NOW + timedelta(minutes=i + 1))
    assert auto_in_row(conn, 1) == 3


def test_my_own_message_resets_the_row(tmp_path):
    conn = _store(tmp_path)
    save_sent(conn, 1, "бот", "auto", sent_at=NOW)
    save_sent(conn, 1, "своё", "own", sent_at=NOW + timedelta(minutes=1))
    assert auto_in_row(conn, 1) == 0


def test_auto_in_row_is_per_chat(tmp_path):
    conn = _store(tmp_path)
    save_sent(conn, 1, "бот", "auto", sent_at=NOW)
    assert auto_in_row(conn, 2) == 0


def test_auto_messages_never_become_style_samples(tmp_path):
    # Иначе профиль манеры начнёт учиться на текстах самой модели
    conn = _store(tmp_path)
    save_sent(conn, 1, "текст модели", "auto", sent_at=NOW)
    assert style_samples(conn) == []


def test_forget_chat_removes_it_from_autopilot(tmp_path):
    conn = _store(tmp_path)
    auto_on(conn, 1, "anya", NOW)
    forget_chat(conn, 1)
    assert auto_chats(conn) == []


def test_learning_summary_counts_auto_messages(tmp_path):
    conn = _store(tmp_path)
    sent_id = save_sent(conn, 1, "бот", "auto", sent_at=NOW)
    save_outcome(conn, sent_id, NOW + timedelta(minutes=5), "ага", 300, 0.8)
    summary = learning_summary(conn)
    assert summary["auto"] == 1
    assert summary["auto_score"] == pytest.approx(0.8)
```

Наверху `tests/test_store.py` добавить `import pytest` и в импорт из `suflor.store` — `auto_on, auto_off, auto_chats, is_auto, pause_auto, resume_auto, auto_state, auto_in_row`.

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'auto_on'`

- [ ] **Step 3: Добавить таблицу в схему**

В `_SCHEMA` в `store.py`, после таблицы `watched`:

```sql
CREATE TABLE IF NOT EXISTS auto_chats (
    chat_id INTEGER PRIMARY KEY,
    username TEXT,
    paused_reason TEXT,
    added_at TEXT NOT NULL
);
```

`CREATE TABLE IF NOT EXISTS` — существующая база пользователя доживёт до новой схемы без миграции, как и все прежние таблицы.

- [ ] **Step 4: Добавить функции**

В `store.py`, рядом с блоком `watch`/`unwatch`:

```python
def auto_on(conn, chat_id: int, username: str | None,
            added_at: datetime | None = None) -> None:
    """Поставить диалог на автопилот. Повтор освежает username и снимает
    паузу: команда /auto — это и есть «продолжай, я разрулил».
    """
    conn.execute(
        "INSERT INTO auto_chats (chat_id, username, paused_reason, added_at) "
        "VALUES (?, ?, NULL, ?) ON CONFLICT(chat_id) DO UPDATE SET "
        "username = excluded.username, paused_reason = NULL",
        (chat_id, username, _iso(added_at or datetime.now(timezone.utc))))
    conn.commit()


def auto_off(conn, chat_id: int) -> bool:
    """Снять с автопилота. False — его там и не было."""
    removed = conn.execute("DELETE FROM auto_chats WHERE chat_id = ?",
                           (chat_id,)).rowcount
    conn.commit()
    return bool(removed)


def auto_chats(conn) -> list:
    """Весь список, включая диалоги на паузе, в порядке добавления."""
    return conn.execute(
        "SELECT chat_id, username, paused_reason, added_at FROM auto_chats "
        "ORDER BY added_at, chat_id").fetchall()


def auto_state(conn, chat_id: int) -> dict | None:
    row = conn.execute(
        "SELECT chat_id, username, paused_reason FROM auto_chats "
        "WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        return None
    return {"chat_id": row["chat_id"], "username": row["username"],
            "paused_reason": row["paused_reason"]}


def is_auto(conn, chat_id: int) -> bool:
    """Отвечать ли в этом диалоге самому. Пауза считается за «нет»."""
    state = auto_state(conn, chat_id)
    return state is not None and state["paused_reason"] is None


def pause_auto(conn, chat_id: int, reason: str) -> None:
    conn.execute("UPDATE auto_chats SET paused_reason = ? WHERE chat_id = ?",
                 (reason, chat_id))
    conn.commit()


def resume_auto(conn, chat_id: int) -> bool:
    """Снять паузу. False — диалога нет в списке или паузы не было."""
    changed = conn.execute(
        "UPDATE auto_chats SET paused_reason = NULL "
        "WHERE chat_id = ? AND paused_reason IS NOT NULL",
        (chat_id,)).rowcount
    conn.commit()
    return bool(changed)


def auto_in_row(conn, chat_id: int, cap: int = 50) -> int:
    """Сколько моих последних сообщений подряд написал бот.

    Считается по хвосту: первое же моё собственное сообщение обнуляет счёт —
    я вмешался в разговор, значит цепочка автоответов прервана. Дальше
    хвоста заглядывать незачем, лимит всё равно измеряется десятками.
    """
    rows = conn.execute(
        "SELECT source FROM sent WHERE chat_id = ? "
        "ORDER BY sent_at DESC, id DESC LIMIT ?", (chat_id, cap))
    count = 0
    for row in rows:
        if row["source"] != "auto":
            break
        count += 1
    return count
```

- [ ] **Step 5: Дополнить `forget_chat` и `learning_summary`**

В `forget_chat`, рядом с удалением из `watched`:

```python
    conn.execute("DELETE FROM auto_chats WHERE chat_id = ?", (chat_id,))
```

В конце `learning_summary`, перед `return`:

```python
    auto = conn.execute(
        "SELECT COUNT(*) AS n FROM sent WHERE source = 'auto'"
    ).fetchone()["n"]
    auto_score = conn.execute(
        "SELECT AVG(o.score) AS s FROM outcomes o JOIN sent s "
        "ON s.id = o.sent_id WHERE s.source = 'auto'").fetchone()["s"]
```

и в сам словарь — `"auto": auto, "auto_score": auto_score`.

- [ ] **Step 6: Прогнать тесты**

Run: `pytest tests/test_store.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/suflor/store.py tests/test_store.py
git commit -m "feat: хранилище списка диалогов на автопилоте"
```

---

### Task 5: Конфиг — секция `auto`

**Files:**
- Modify: `src/suflor/config.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Produces: датакласс `suflor.config.Auto` с полями `enabled: bool = True`, `cancel_window_seconds: float = 60.0`, `max_in_row: int = 10`, `typing_simulation: bool = True`, `memory_refresh_every: int = 10`, `recent_messages: int = 40`; поле `Config.auto: Auto`.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_config.py` (следовать тому, как в файле уже пишутся временные конфиги — тот же хелпер и стиль):

```python
def test_auto_section_is_read(tmp_path):
    cfg = _write_config(tmp_path, """
panel_chat: me
auto:
  enabled: false
  cancel_window_seconds: 30
  max_in_row: 3
  typing_simulation: false
  memory_refresh_every: 5
  recent_messages: 20
""")
    assert cfg.auto.enabled is False
    assert cfg.auto.cancel_window_seconds == 30
    assert cfg.auto.max_in_row == 3
    assert cfg.auto.typing_simulation is False
    assert cfg.auto.memory_refresh_every == 5
    assert cfg.auto.recent_messages == 20


def test_config_without_auto_section_gets_defaults(tmp_path):
    # Конфиг, написанный до этой фичи, обязан работать как раньше
    cfg = _write_config(tmp_path, "panel_chat: me\n")
    assert cfg.auto.enabled is True
    assert cfg.auto.cancel_window_seconds == 60
    assert cfg.auto.max_in_row == 10
    assert cfg.auto.recent_messages == 40


def test_unknown_auto_keys_are_ignored(tmp_path):
    # Как в learning: опечатка в ключе не должна ронять бота на старте
    cfg = _write_config(tmp_path, """
panel_chat: me
auto:
  max_in_row: 7
  какая_то_опечатка: 1
""")
    assert cfg.auto.max_in_row == 7
```

Если в `tests/test_config.py` нет хелпера `_write_config(tmp_path, text)`, добавить его:

```python
def _write_config(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return load_config(str(path))
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_config.py -q`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'auto'`

- [ ] **Step 3: Добавить датакласс и загрузку**

В `config.py`, после `Learning`:

```python
@dataclass
class Auto:
    """Авторежим: бот сам пишет и отправляет ответ в отмеченных диалогах.

    Список диалогов живёт в базе (команда /auto), здесь только правила игры.
    Правки применяются при перезапуске.
    """
    enabled: bool = True
    # Сколько ответ висит в пульте, прежде чем уйти собеседнику
    cancel_window_seconds: float = 60.0
    # Автоответов подряд без единого моего сообщения — дальше пауза
    max_in_row: int = 10
    typing_simulation: bool = True
    # Обновлять сводку диалога раз в столько новых сообщений
    memory_refresh_every: int = 10
    # Сколько последних реплик кладём в промпт ответа
    recent_messages: int = 40
```

В `Config` добавить поле:

```python
    auto: Auto = field(default_factory=Auto)
```

Загрузчик — копия `_load_learning`, потому что правило то же: неизвестные ключи молча отбрасываются, отсутствующая секция даёт дефолты:

```python
def _load_auto(data: dict) -> Auto:
    """Секции auto может не быть вовсе — старый конфиг должен работать."""
    known = {f.name for f in fields(Auto)}
    return Auto(**{k: v for k, v in (data or {}).items() if k in known})
```

В `load_config(...)` добавить `auto=_load_auto(data.get("auto")),`.

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/suflor/config.py tests/test_config.py
git commit -m "feat: секция auto в конфиге"
```

---

### Task 6: `responder.py` — генератор одной реплики

Сердце фичи. Промпт устроен противоположно суфлёрскому: одна задача вместо пяти, правила положительные, запретов три.

**Files:**
- Create: `src/suflor/responder.py`
- Create: `tests/test_responder.py`

**Interfaces:**
- Consumes: `suflor.dialog` (задача 1), `suflor.llm.complete`, `suflor.llm.LLMError` (задача 2).
- Produces: `suflor.responder.Reply` (датакласс с полями `text: str | None`, `handoff: str | None`), `parse_reply(raw: str) -> Reply`, `build_reply_prompt(style: str, about: str = "", style_block: str = "") -> str`, `build_reply_messages(history, system_prompt, summary="", now=None, partner_name=None, full_history=True, recent=40) -> list[dict]`, класс `Responder(client, style, temperature=0.7, model="deepseek-v4-pro", about="")` с методом `reply(history, partner_name=None, summary="", style_block="", full_history=True, recent=40) -> Reply`.

- [ ] **Step 1: Написать падающие тесты — разбор ответа**

Создать `tests/test_responder.py`:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from suflor.llm import LLMError
from suflor.responder import (
    Responder, build_reply_messages, build_reply_prompt, parse_reply,
)

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def _msg(text, from_me=False, minutes_ago=0):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def test_parse_reply_keeps_plain_text():
    assert parse_reply("да я тоже так думаю").text == "да я тоже так думаю"


def test_parse_reply_strips_the_speaker_prefix():
    # Модель иногда отвечает в формате переписки, хотя её не просили
    assert parse_reply("Я: ну такое").text == "ну такое"


def test_parse_reply_strips_quotes():
    assert parse_reply('«ну такое»').text == "ну такое"
    assert parse_reply('"ну такое"').text == "ну такое"


def test_parse_reply_strips_numbering():
    # Наследие суфлёра: модель по привычке нумерует единственный вариант
    assert parse_reply("1) ну такое").text == "ну такое"


def test_parse_reply_joins_wrapped_lines():
    assert parse_reply("первая строка\nвторая").text == "первая строка вторая"


def test_parse_reply_recognises_handoff():
    reply = parse_reply("HANDOFF: договариваются о встрече")
    assert reply.text is None
    assert reply.handoff == "договариваются о встрече"


def test_parse_reply_recognises_handoff_on_a_later_line():
    reply = parse_reply("Пояснение\nHANDOFF: зовёт гулять")
    assert reply.handoff == "зовёт гулять"


def test_parse_reply_handoff_without_reason_still_hands_off():
    assert parse_reply("HANDOFF").handoff


def test_parse_reply_empty_gives_nothing():
    empty = parse_reply("   \n  ")
    assert empty.text is None and empty.handoff is None
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_responder.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.responder'`

- [ ] **Step 3: Создать модуль с разбором ответа**

Создать `src/suflor/responder.py`:

```python
"""Собеседник: одна реплика от моего лица вместо витрины вариантов.

Отличие от суфлёра не в промпте, а в задаче. Суфлёр показывает мне четыре
тона, чтобы я выбрал; собеседник пишет то единственное, что уйдёт человеку.
Поэтому здесь нет ни разбора, ни нумерации, а правила сформулированы
положительно: стена запретов заставляет модель писать максимально безопасную
пустоту — дежурную фразу, к которой не придраться.
"""
import re
from dataclasses import dataclass
from datetime import datetime

from suflor import dialog
from suflor.llm import LLMError, complete

DEFAULT_MODEL = "deepseek-v4-pro"

# Замерено на deepseek-v4: рассуждения занимают 1900-3900 токенов и
# списываются из того же лимита, что и ответ
_REASONING_BUDGET = 6000

# Модель отдаёт управление, когда разговор дошёл до реального мира
_HANDOFF = re.compile(r"^\W*HANDOFF\b\W*:?\s*(.*)$", re.IGNORECASE)
_HANDOFF_DEFAULT = "разговор дошёл до договорённостей"

# Наследие суфлёрского формата: нумерация и «Я:» в начале реплики
_PREFIX = re.compile(r"^\s*(?:\d+[)\].:-]\s*)?(?:я\s*:\s*)?", re.IGNORECASE)
_QUOTES = "«»\"“”'"


@dataclass
class Reply:
    """Либо текст реплики, либо причина передать диалог человеку."""
    text: str | None = None
    handoff: str | None = None


def parse_reply(raw: str) -> Reply:
    """Из ответа модели — чистая реплика или сигнал передачи.

    Модель просили отдать голый текст, но она регулярно оборачивает его в
    кавычки, подписывает «Я:» или нумерует по привычке от суфлёра. Снимаем
    обёртки здесь, чтобы собеседник не получил их в сообщении.
    """
    lines = [line.strip() for line in (raw or "").splitlines() if line.strip()]
    for line in lines:
        match = _HANDOFF.match(line)
        if match:
            return Reply(handoff=match.group(1).strip() or _HANDOFF_DEFAULT)
    if not lines:
        return Reply()
    text = _PREFIX.sub("", " ".join(lines)).strip().strip(_QUOTES).strip()
    return Reply(text=text or None)
```

- [ ] **Step 4: Прогнать тесты разбора**

Run: `pytest tests/test_responder.py -q`
Expected: PASS

- [ ] **Step 5: Написать падающие тесты на промпт и сборку сообщений**

Дописать в `tests/test_responder.py`:

```python
def test_prompt_puts_the_model_in_my_shoes():
    prompt = build_reply_prompt("стиль")
    assert "от первого лица" in prompt
    assert "только текст" in prompt


def test_prompt_asks_for_one_short_message():
    assert "одна мысль" in build_reply_prompt("стиль")


def test_prompt_explains_the_handoff_protocol():
    prompt = build_reply_prompt("стиль")
    assert "HANDOFF:" in prompt


def test_prompt_keeps_the_three_hard_bans():
    prompt = build_reply_prompt("стиль")
    assert "о себе крупное" in prompt
    assert "о собеседнике" in prompt
    assert "ошлост" in prompt          # пошлость/пошлости


def test_prompt_includes_style_and_about():
    prompt = build_reply_prompt("мой стиль", about="Зовут Даниил, 23, Томск.")
    assert "мой стиль" in prompt
    assert "Зовут Даниил, 23, Томск." in prompt


def test_prompt_includes_the_learned_manner():
    prompt = build_reply_prompt("стиль", style_block="Вот как я пишу сам: ...")
    assert "Вот как я пишу сам" in prompt


def test_prompt_explains_media_markers():
    assert "[голосовое" in build_reply_prompt("стиль")


def test_messages_have_system_and_user_roles():
    messages = build_reply_messages([_msg("привет")], "промпт")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == "промпт"


def test_messages_include_only_the_recent_tail():
    history = [_msg(f"реплика {i}", minutes_ago=100 - i) for i in range(50)]
    user = build_reply_messages(history, "промпт", recent=10)[1]["content"]
    assert "реплика 49" in user
    assert "реплика 0" not in user


def test_messages_include_the_summary_when_there_is_one():
    user = build_reply_messages([_msg("привет")], "промпт",
                                summary="Аня, 24, из Томска")[1]["content"]
    assert "Аня, 24, из Томска" in user


def test_messages_skip_the_summary_block_when_empty():
    user = build_reply_messages([_msg("привет")], "промпт")[1]["content"]
    assert "помню об этом разговоре" not in user


def test_messages_report_time_since_the_last_message():
    user = build_reply_messages([_msg("ну что", minutes_ago=180)], "промпт",
                                now=NOW)[1]["content"]
    assert "3 часа" in user


def test_messages_carry_asked_questions_from_the_whole_history():
    # Вопросы ищутся по всей переписке, а не только по хвосту: круги
    # начинаются как раз со старых вопросов
    history = [_msg("чем занимаешься?", minutes_ago=100 - i)
               for i in range(1)] + [
        _msg(f"реплика {i}", minutes_ago=90 - i) for i in range(30)]
    user = build_reply_messages(history, "промпт", recent=5,
                                partner_name="Аня")[1]["content"]
    assert "чем занимаешься?" in user


def test_messages_end_with_the_task():
    user = build_reply_messages([_msg("привет")], "промпт")[1]["content"]
    assert user.rstrip().endswith("Только текст реплики.")
```

- [ ] **Step 6: Убедиться, что падают**

Run: `pytest tests/test_responder.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_reply_prompt'`

- [ ] **Step 7: Дописать промпт и сборку сообщений**

Добавить в `src/suflor/responder.py`:

```python
def build_reply_prompt(style: str, about: str = "",
                       style_block: str = "") -> str:
    """Системный промпт собеседника.

    Порядок блоков не случаен: модель сильнее держит начало и конец, поэтому
    роль стоит первой, а протокол передачи диалога — последним, у самой
    границы с перепиской.
    """
    learned = f"\n\n{style_block}\n\n" if style_block else " "
    return (
        "Ты — это я. Пишешь от первого лица живому человеку в личной "
        "переписке на сайте знакомств. Ты не ассистент: вариантов не "
        "предлагаешь, разбор не пишешь, о себе как о программе не "
        "упоминаешь. На выходе — только текст моей следующей реплики, без "
        "кавычек, без нумерации и без подписи.\n\n"
        "Как писать:\n"
        "- одна мысль, одна-две короткие фразы, как реально пишут в "
        "мессенджере;\n"
        "- цепляйся за конкретную деталь, которую собеседник только что "
        "назвал: она живее общих слов;\n"
        "- если он задал вопрос, сначала ответь на него, а потом уже "
        "спрашивай сам. Вопрос в каждой реплике не обязателен — живая "
        "реплика без него лучше дежурного «а ты?»;\n"
        "- ниже сказано, сколько прошло с его сообщения. Ответ через пять "
        "минут и ответ через три дня звучат по-разному, но извиняться за "
        "небольшую паузу не нужно;\n"
        "- медиа помечено в квадратных скобках: [фото], [стикер 😂], "
        "[голосовое 12 сек] и дальше расшифровка. Голосовое — это голос, а "
        "не набранный текст. Стоит «не расшифровано» — содержимого не знает "
        "никто, не делай вид, что знаешь.\n\n"
        "Чего нельзя:\n"
        "- выдумывать о себе крупное: другой город, другую работу, семью, "
        "серьёзные события, общие с собеседником воспоминания и планы;\n"
        "- выдумывать о собеседнике вообще ничего — о нём известно только "
        "то, что он сам сказал в переписке;\n"
        "- пошлость, двусмысленности и разговоры про тело в откровенном "
        "ключе. Тепло и лёгкий интерес — да, подтекст — нет.\n\n"
        "Если разговор дошёл до договорённостей в реальном мире — встреча, "
        "свидание, время, место, созвон, обмен номерами, переход в другой "
        "мессенджер, — отвечать не надо. Вместо реплики верни одну строку:\n"
        "HANDOFF: <в двух словах, о чём договариваются>\n\n"
        f"{dialog.facts_rules(about)}{style}{learned}"
    )


def build_reply_messages(history: list[dict], system_prompt: str,
                         summary: str = "", now: datetime | None = None,
                         partner_name: str | None = None,
                         full_history: bool = True,
                         recent: int = 40) -> list[dict]:
    """Контекст ответа: сводка, хвост переписки и посчитанные в коде блоки.

    Сырыми в промпт идут только последние `recent` реплик — остальное
    представлено сводкой. Пятьсот сообщений простынёй размывают внимание, и
    свежая часть разговора тонет в старой: ровно отсюда растёт «модель
    теряет нить».

    Вопросы и инициатива считаются по всей истории, а не по хвосту: круги в
    разговоре начинаются со старых вопросов, и обрезать их нельзя.
    """
    partner = partner_name or "Собеседник"
    tail = history[-recent:] if recent else history

    blocks = []
    if summary:
        blocks.append(f"Что я помню об этом разговоре:\n{summary}")
    blocks.append(f"Последние сообщения:\n{dialog.format_history(tail, partner)}")
    elapsed = dialog.elapsed_since_last(history, now)
    if elapsed:
        blocks.append(f"С последнего сообщения прошло: {elapsed}.")
    for block in (dialog.questions_asked(history, partner),
                  dialog.initiative_summary(history, partner, full_history)):
        if block:
            blocks.append(block)
    blocks.append("Напиши мою следующую реплику. Только текст реплики.")

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]
```

- [ ] **Step 8: Прогнать тесты**

Run: `pytest tests/test_responder.py -q`
Expected: PASS

- [ ] **Step 9: Написать падающие тесты на класс `Responder`**

Дописать в `tests/test_responder.py`:

```python
def _responder_with_reply(text, finish_reason="stop"):
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason=finish_reason)
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return Responder(client=client, style="стиль", about="Зовут Даниил.")


def test_reply_returns_parsed_text():
    r = _responder_with_reply("да я тоже так думаю")
    assert r.reply([_msg("привет")]).text == "да я тоже так думаю"


def test_reply_passes_handoff_through():
    r = _responder_with_reply("HANDOFF: зовёт гулять")
    assert r.reply([_msg("погуляем?")]).handoff == "зовёт гулять"


def test_reply_raises_on_empty_model_answer():
    with pytest.raises(LLMError, match="пуст"):
        _responder_with_reply("   ").reply([_msg("привет")])


def test_reply_raises_on_api_error():
    r = _responder_with_reply("неважно")
    r._client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    with pytest.raises(LLMError):
        r.reply([_msg("привет")])


def test_reply_sends_about_and_learned_style_to_the_model():
    r = _responder_with_reply("ок")
    r.reply([_msg("привет")], style_block="Вот как я пишу сам: ...")
    sent = r._client.chat.completions.create.call_args.kwargs["messages"]
    assert "Зовут Даниил." in sent[0]["content"]
    assert "Вот как я пишу сам" in sent[0]["content"]


def test_reply_sends_the_summary_to_the_model():
    r = _responder_with_reply("ок")
    r.reply([_msg("привет")], summary="Аня, 24, из Томска")
    sent = r._client.chat.completions.create.call_args.kwargs["messages"]
    assert "Аня, 24, из Томска" in sent[1]["content"]
```

- [ ] **Step 10: Убедиться, что падают**

Run: `pytest tests/test_responder.py -q`
Expected: FAIL — `ImportError: cannot import name 'Responder'`

- [ ] **Step 11: Дописать класс**

Добавить в `src/suflor/responder.py`:

```python
class Responder:
    """Пишет одну реплику от моего лица. Клиент DeepSeek — общий с суфлёром."""

    def __init__(self, client, style: str, temperature: float = 0.7,
                 model: str = DEFAULT_MODEL, about: str = ""):
        self._client = client
        self._style = style
        self._temperature = temperature
        self._model = model
        self._about = about
        # Одна короткая реплика поверх бюджета рассуждений
        self._max_tokens = _REASONING_BUDGET + 500

    def reply(self, history: list[dict], partner_name: str | None = None,
              summary: str = "", style_block: str = "",
              full_history: bool = True, recent: int = 40) -> Reply:
        """Реплика или сигнал передать диалог мне.

        Промпт собирается на каждый вызов, а не кешируется, как у суфлёра:
        выученная манера и сводка диалога меняются по ходу переписки.
        """
        prompt = build_reply_prompt(self._style, self._about, style_block)
        raw = complete(
            self._client, self._model,
            build_reply_messages(history, prompt, summary,
                                 partner_name=partner_name,
                                 full_history=full_history, recent=recent),
            self._temperature, self._max_tokens)
        reply = parse_reply(raw)
        if reply.text is None and reply.handoff is None:
            raise LLMError("модель вернула пустой ответ")
        return reply
```

- [ ] **Step 12: Прогнать всё**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add src/suflor/responder.py tests/test_responder.py
git commit -m "feat: генератор одной реплики вместо витрины тонов"
```

---

### Task 7: `autopilot.py` — окно отмены и отправка

**Files:**
- Create: `src/suflor/autopilot.py`
- Create: `tests/test_autopilot.py`

**Interfaces:**
- Produces: `suflor.autopilot.typing_delay(text, per_char=0.06, cap=10.0) -> float`, датакласс `Pending(chat_id: int, text: str, card_id: int | None = None, task=None)`, класс `Autopilot(sender, window: float, typing: bool = True)` с методами `schedule(chat_id, text) -> Pending`, `cancel(chat_id) -> Pending | None`, `pending(chat_id) -> Pending | None`, `all_pending() -> list[Pending]`, `attach_card(chat_id, card_id) -> None`, `chat_for_card(card_id) -> int | None`.
- `sender` — корутинная функция `sender(chat_id: int, text: str, typing_seconds: float)`. Telethon в модуль не проникает: отправку делает `main`, здесь только тайминг и отмена.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_autopilot.py`:

```python
import asyncio

from suflor.autopilot import Autopilot, typing_delay

WINDOW = 0.05


def _recorder(calls):
    async def send(chat_id, text, typing_seconds):
        calls.append((chat_id, text, typing_seconds))
    return send


def test_typing_delay_grows_with_length():
    assert typing_delay("привет") < typing_delay("привет, как твои дела")


def test_typing_delay_is_capped():
    assert typing_delay("а" * 10_000) == 10.0


def test_typing_delay_of_empty_text_is_zero():
    assert typing_delay("") == 0.0


async def test_sends_after_the_window():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "привет")
    assert calls == []                       # сразу — ещё рано
    await asyncio.sleep(WINDOW * 4)
    assert calls == [(1, "привет", typing_delay("привет"))]


async def test_cancel_stops_the_send():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "привет")
    assert a.cancel(1).text == "привет"      # вернули, что отменили
    await asyncio.sleep(WINDOW * 4)
    assert calls == []


async def test_cancel_of_nothing_is_harmless():
    a = Autopilot(_recorder([]), WINDOW)
    assert a.cancel(999) is None


async def test_scheduling_again_replaces_the_previous_reply():
    # Пришло новое сообщение — прежний ответ устарел и уходить не должен
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "старый ответ")
    a.schedule(1, "новый ответ")
    await asyncio.sleep(WINDOW * 4)
    assert [text for _, text, _ in calls] == ["новый ответ"]


async def test_different_chats_do_not_interfere():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "первому")
    a.schedule(2, "второму")
    await asyncio.sleep(WINDOW * 4)
    assert sorted(text for _, text, _ in calls) == ["второму", "первому"]


async def test_pending_is_forgotten_after_sending():
    a = Autopilot(_recorder([]), WINDOW)
    a.schedule(1, "привет")
    await asyncio.sleep(WINDOW * 4)
    assert a.pending(1) is None
    assert a.all_pending() == []


async def test_typing_can_be_switched_off():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW, typing=False)
    a.schedule(1, "длинное сообщение про всё на свете")
    await asyncio.sleep(WINDOW * 4)
    assert calls[0][2] == 0.0


async def test_card_maps_back_to_its_chat():
    # Реплай на карточку в пульте должен попасть в нужный диалог
    a = Autopilot(_recorder([]), WINDOW)
    a.schedule(7, "привет")
    a.attach_card(7, 555)
    assert a.chat_for_card(555) == 7
    assert a.pending(7).card_id == 555


async def test_card_is_forgotten_on_cancel():
    a = Autopilot(_recorder([]), WINDOW)
    a.schedule(7, "привет")
    a.attach_card(7, 555)
    a.cancel(7)
    assert a.chat_for_card(555) is None
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_autopilot.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.autopilot'`

- [ ] **Step 3: Создать `src/suflor/autopilot.py`**

```python
"""Отложенная отправка автоответа с окном отмены.

Ответ не уходит собеседнику сразу: он висит окно отмены, за которое его
можно перехватить. Отмена приходит с трёх сторон — новое входящее делает
ответ устаревшим, моё собственное сообщение означает, что разговор перехватил
я, и есть команда /stop. Поэтому задачей владеет отдельный объект, а не
таймер внутри обработчика: Debouncer умеет отменять только сам себя.

Telethon сюда не проникает: отправку делает переданный `sender`, здесь —
тайминг, отмена и связь карточки в пульте с диалогом. Так модуль
проверяется тестами без сети и без аккаунта.
"""
import asyncio
from dataclasses import dataclass

# Скорость «набора» — примерно человеческая для мессенджера
TYPING_PER_CHAR = 0.06
TYPING_CAP = 10.0


def typing_delay(text: str, per_char: float = TYPING_PER_CHAR,
                 cap: float = TYPING_CAP) -> float:
    """Сколько показывать «печатает…». Длинную мысль набирают дольше."""
    return min(cap, len(text or "") * per_char)


@dataclass
class Pending:
    """Ответ, ждущий своей отправки."""
    chat_id: int
    text: str
    card_id: int | None = None
    task: asyncio.Task | None = None


class Autopilot:
    def __init__(self, sender, window: float, typing: bool = True):
        self._sender = sender
        self._window = window
        self._typing = typing
        self._pending: dict[int, Pending] = {}
        self._cards: dict[int, int] = {}      # id карточки -> chat_id

    def pending(self, chat_id: int) -> Pending | None:
        return self._pending.get(chat_id)

    def all_pending(self) -> list[Pending]:
        return list(self._pending.values())

    def schedule(self, chat_id: int, text: str) -> Pending:
        """Запланировать отправку, отменив прежнюю по этому диалогу."""
        self.cancel(chat_id)
        item = Pending(chat_id=chat_id, text=text)
        item.task = asyncio.ensure_future(self._run(item))
        self._pending[chat_id] = item
        return item

    def cancel(self, chat_id: int) -> Pending | None:
        """Снять запланированную отправку. None — снимать было нечего."""
        item = self._pending.pop(chat_id, None)
        if item is None:
            return None
        self._forget_card(item)
        if item.task is not None and not item.task.done():
            item.task.cancel()
        return item

    def attach_card(self, chat_id: int, card_id: int) -> None:
        """Связать карточку в пульте с диалогом — для реплая своим текстом."""
        item = self._pending.get(chat_id)
        if item is None:
            return
        item.card_id = card_id
        self._cards[card_id] = chat_id

    def chat_for_card(self, card_id: int) -> int | None:
        return self._cards.get(card_id)

    def _forget_card(self, item: Pending) -> None:
        if item.card_id is not None:
            self._cards.pop(item.card_id, None)

    async def _run(self, item: Pending) -> None:
        try:
            if self._window > 0:
                await asyncio.sleep(self._window)
            delay = typing_delay(item.text) if self._typing else 0.0
            await self._sender(item.chat_id, item.text, delay)
        finally:
            # Снимаем только свою запись: пока мы ждали, на диалог могла
            # встать следующая, и затирать её нельзя
            if self._pending.get(item.chat_id) is item:
                del self._pending[item.chat_id]
                self._forget_card(item)
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_autopilot.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/suflor/autopilot.py tests/test_autopilot.py
git commit -m "feat: окно отмены для автоответов"
```

---

### Task 8: Пульт — карточки авторежима

**Files:**
- Modify: `src/suflor/control_panel.py`
- Modify: `tests/test_control_panel.py`

**Interfaces:**
- Produces: `format_auto_card(sender_name, incoming, reply, seconds, chat_link=None) -> str`, `format_auto_sent(sender_name, reply) -> str`, `format_handoff(sender_name, reason, chat_link=None) -> str`, `format_auto_list(people, enabled) -> str`, `format_send_error(sender_name, reply) -> str`. `format_stats` дополняется строкой про автоответы.
- `people` — список словарей `{"name": str | None, "username": str | None, "paused_reason": str | None}`.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_control_panel.py`:

```python
def test_auto_card_shows_incoming_reply_and_countdown():
    text = format_auto_card("Аня", "привет!", "привет, как ты?", 60)
    assert "Аня" in text
    assert "привет!" in text
    assert "привет, как ты?" in text
    assert "60" in text
    assert "/stop" in text          # как отменить, видно в самой карточке


def test_auto_card_includes_the_fallback_link():
    text = format_auto_card("Аня", "привет", "и тебе", 60,
                            chat_link="https://t.me/anya")
    assert "https://t.me/anya" in text


def test_auto_sent_confirms_what_went_out():
    text = format_auto_sent("Аня", "привет, как ты?")
    assert "Аня" in text
    assert "привет, как ты?" in text


def test_handoff_card_names_the_reason_and_says_it_is_paused():
    text = format_handoff("Аня", "зовёт гулять")
    assert "Аня" in text
    assert "зовёт гулять" in text
    assert "пауз" in text.lower()
    assert "/auto" in text           # как вернуть бота в диалог


def test_send_error_keeps_the_text_so_it_can_be_sent_by_hand():
    text = format_send_error("Аня", "привет, как ты?")
    assert "привет, как ты?" in text


def test_auto_list_is_explicit_when_empty():
    text = format_auto_list([], enabled=True)
    assert "пуст" in text
    assert "/auto" in text


def test_auto_list_marks_paused_chats():
    text = format_auto_list(
        [{"name": "Аня", "username": "anya", "paused_reason": None},
         {"name": "Лена", "username": None,
          "paused_reason": "зовёт гулять"}], enabled=True)
    assert "Аня" in text and "anya" in text
    assert "Лена" in text and "зовёт гулять" in text


def test_auto_list_warns_when_the_mode_is_off_in_config():
    text = format_auto_list(
        [{"name": "Аня", "username": None, "paused_reason": None}],
        enabled=False)
    assert "auto.enabled" in text


def test_stats_report_auto_replies():
    summary = {"samples": 10, "sent": 20, "chats": 2, "suggestions": 5,
               "tones": {}, "avg_score": 0.5, "auto": 7, "auto_score": 0.42}
    text = format_stats(summary, min_samples=5)
    assert "7" in text
    assert "0.42" in text


def test_stats_survive_a_summary_without_auto_keys():
    # Сводка из старой базы ключей auto не содержит — падать нельзя
    summary = {"samples": 1, "sent": 1, "chats": 1, "suggestions": 0,
               "tones": {}, "avg_score": None}
    assert format_stats(summary, min_samples=5)
```

Импорты новых функций добавить в шапку `tests/test_control_panel.py`.

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_control_panel.py -q`
Expected: FAIL — `ImportError: cannot import name 'format_auto_card'`

- [ ] **Step 3: Добавить форматирование**

В `src/suflor/control_panel.py`:

```python
def _head(icon: str, sender_name: str, chat_link: str | None) -> str:
    """Шапка карточки. Имя кликабельно сущностями — их вешает main; ссылка
    в тексте нужна только там, где сущность построить не вышло.
    """
    head = f"{icon} {sender_name}"
    return f"{head} — {chat_link}" if chat_link else head


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


def format_send_error(sender_name: str, reply: str) -> str:
    return (f"⚠️ Не смог отправить ответ в чат с {sender_name}. "
            f"Вот текст, отправь руками:\n{reply}")


def format_auto_list(people: list[dict], enabled: bool = True) -> str:
    """Ответ на /auto без аргумента: где бот отвечает сам."""
    if not people:
        return ("\U0001f916 Автопилот пуст — везде работает суфлёр.\n"
                "Включить в диалоге: /auto @username")

    lines = ["\U0001f916 Отвечаю сам:"]
    for p in people:
        name = p.get("name") or "без имени"
        line = f"- {name} (@{p['username']})" if p.get("username") else f"- {name}"
        if p.get("paused_reason"):
            line += f" — на паузе: {p['paused_reason']}"
        lines.append(line)
    if not enabled:
        lines.append("Список сейчас не работает: в конфиге auto.enabled: "
                     "false — бот везде только подсказывает.")
    return "\n".join(lines)
```

В `format_stats`, перед строкой про среднюю оценку:

```python
    auto = summary.get("auto") or 0
    if auto:
        line = f"Автоответов отправлено: {auto}"
        if summary.get("auto_score") is not None:
            line += f", средняя оценка: {summary['auto_score']:.2f}"
        lines.append(line)
```

`summary.get(...)` вместо `summary[...]` — сводка из старой базы ключей `auto` не содержит, и `/stats` не должен от этого падать.

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_control_panel.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/suflor/control_panel.py tests/test_control_panel.py
git commit -m "feat: карточки авторежима в пульте"
```

---

### Task 9: `main.py` — развилка режимов и автоотправка

Самая ответственная задача: здесь бот впервые пишет собеседнику сам.

**Files:**
- Modify: `src/suflor/main.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: всё из задач 1-8.
- Produces: `main.SENT_BY_BOT: set[tuple[int, int]]`, `main.is_bot_echo(chat_id, msg_id) -> bool`, `main.auto_pause_reason(conn, cfg, incoming, chat_id) -> str | None`, `main.build_auto_reply(responder, conn, cfg, chat_id, history, sender_name, full) -> Reply`.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_main.py`:

```python
def test_auto_pause_reason_fires_on_real_world_arrangements(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    cfg = SimpleNamespace(auto=SimpleNamespace(max_in_row=10))
    assert auto_pause_reason(conn, cfg, "давай встретимся в субботу", 1)


def test_auto_pause_reason_silent_on_ordinary_talk(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    cfg = SimpleNamespace(auto=SimpleNamespace(max_in_row=10))
    assert auto_pause_reason(conn, cfg, "как прошёл день?", 1) is None


def test_auto_pause_reason_fires_on_too_many_auto_in_row(tmp_path):
    # Защита от бесконечной беседы модели с человеком
    conn = open_store(str(tmp_path / "s.db"))
    cfg = SimpleNamespace(auto=SimpleNamespace(max_in_row=3))
    for i in range(3):
        save_sent(conn, 1, f"бот {i}", "auto",
                  sent_at=datetime(2026, 8, 25, 12, i, tzinfo=timezone.utc))
    reason = auto_pause_reason(conn, cfg, "как дела?", 1)
    assert reason is not None and "подряд" in reason


def test_bot_echo_is_recognised_once():
    # Автоответ вернётся в обработчик как моё исходящее — записать его в
    # корпус манеры значит учить модель на её же текстах
    SENT_BY_BOT.clear()
    SENT_BY_BOT.add((1, 100))
    assert is_bot_echo(1, 100) is True
    assert is_bot_echo(1, 100) is False   # запись разовая, память не течёт


def test_bot_echo_is_false_for_my_own_message():
    SENT_BY_BOT.clear()
    assert is_bot_echo(1, 100) is False
```

Импорты в шапку `tests/test_main.py`: `auto_pause_reason`, `is_bot_echo`, `SENT_BY_BOT` из `suflor.main`; `save_sent` из `suflor.store`; `timezone` уже импортирован.

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_main.py -q`
Expected: FAIL — `ImportError: cannot import name 'auto_pause_reason'`

- [ ] **Step 3: Добавить чистые функции в `main.py`**

Импорты вверху `main.py`:

```python
from suflor import store, profile, media, handoff, llm
from suflor.autopilot import Autopilot
from suflor.responder import Responder
from suflor.llm import LLMError
from suflor.control_panel import (
    format_suggestions, format_error, format_stats, build_chat_link,
    utf16_span, format_watchlist, format_auto_card, format_auto_sent,
    format_handoff, format_auto_list, format_send_error,
)
```

Рядом с `BURSTS`:

```python
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
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_main.py -q`
Expected: PASS

- [ ] **Step 5: Собрать генератор и автопилот в `_amain`**

В `_amain`, вместо создания `Suggester`:

```python
    llm_client = llm.make_client(deepseek_key)
    suggester = Suggester(tones=cfg.tones, style=cfg.style,
                          temperature=cfg.temperature, model=cfg.model,
                          about=cfg.about, client=llm_client)
    responder = Responder(client=llm_client, style=cfg.style,
                          temperature=cfg.temperature, model=cfg.model,
                          about=cfg.about)
```

После создания `debouncer` — отправитель и автопилот. `sender` замыкается на `client` и `conn`, поэтому объявляется здесь же:

```python
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
```

- [ ] **Step 6: Добавить ветку авторежима в `run_analysis`**

Внутри `handler`, в начале обработки входящего (сразу после `BURSTS.setdefault`), запланированный ответ устарел:

```python
        # Собеседник написал ещё раз — прежний ответ уже не к месту
        autopilot.cancel(event.chat_id)
```

В теле `run_analysis`, после `learned = _learned_style(...)`, заменить безусловный вызов суфлёра на развилку:

```python
            auto_on = (cfg.auto.enabled
                       and store.is_auto(conn, event.chat_id))
            if auto_on:
                await run_auto(history, full, learned)
                return
```

И рядом с `run_analysis` — сама ветка:

```python
        async def run_auto(history, full, learned):
            """Ответить самому: сгенерировать, показать в пульте, отправить."""
            NAMES[event.chat_id] = sender_name
            reason = auto_pause_reason(conn, cfg, incoming, event.chat_id)
            if not reason:
                try:
                    reply = await asyncio.to_thread(
                        responder.reply, history, sender_name, "", learned,
                        full, cfg.auto.recent_messages)
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
```

Третий аргумент `responder.reply` — сводка диалога, до задачи 14 она пустая.

- [ ] **Step 7: Разорвать петлю в ветке исходящих**

Ветку `if event.out and event.chat_id != panel_id and event.is_private:` заменить на:

```python
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
```

- [ ] **Step 8: Прогнать всё**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 9: Проверить, что бот стартует**

Run: `python -c "import suflor.main"`
Expected: без ошибок импорта. Полный прогон с живым Telegram здесь не делается — это ручная проверка владельца после задачи 11.

- [ ] **Step 10: Commit**

```bash
git add src/suflor/main.py tests/test_main.py
git commit -m "feat: авторежим отвечает и отправляет сам"
```

---

### Task 10: `main.py` — команды `/auto`, `/stop` и реплай на карточку

**Files:**
- Modify: `src/suflor/main.py`
- Modify: `tests/test_main.py`

**Interfaces:**
- Consumes: `store.auto_on/auto_off/auto_chats/auto_state`, `autopilot.cancel/chat_for_card`, `control_panel.format_auto_list`, `parse_hint_target`, `_resolve_target`.
- Produces: `parse_auto_arg(arg: str) -> tuple[bool, str]` — `(включить?, остаток аргумента)`; корутины `_handle_auto(client, conn, cfg, autopilot, arg)`, `_handle_stop(client, conn, cfg, autopilot, arg)`.

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_main.py`:

```python
def test_parse_auto_arg_reads_plain_target():
    assert parse_auto_arg("@anya") == (True, "@anya")


def test_parse_auto_arg_reads_the_off_form():
    assert parse_auto_arg("off @anya") == (False, "@anya")


def test_parse_auto_arg_accepts_russian_off():
    assert parse_auto_arg("выкл @anya") == (False, "@anya")


def test_parse_auto_arg_of_empty_string():
    assert parse_auto_arg("") == (True, "")


def test_parse_auto_arg_does_not_eat_a_username_starting_with_off():
    assert parse_auto_arg("@offline_girl") == (True, "@offline_girl")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_main.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_auto_arg'`

- [ ] **Step 3: Добавить разбор аргумента**

Рядом с `parse_hint_target` в `main.py`:

```python
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
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_main.py -q`
Expected: PASS

- [ ] **Step 5: Добавить обработчики команд**

Рядом с `_handle_watch` в `main.py`:

```python
async def _handle_auto(client, conn, cfg, autopilot, arg: str):
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
```

- [ ] **Step 6: Подключить команды и реплай в обработчик пульта**

В блоке команд пульта, рядом с `/watch`:

```python
            if cmd == "/auto" or cmd.startswith("/auto "):
                await _handle_auto(client, conn, cfg, autopilot,
                                   cmd[len("/auto"):].strip())
                return
            if cmd == "/stop" or cmd.startswith("/stop "):
                await _handle_stop(client, conn, cfg, autopilot,
                                   cmd[len("/stop"):].strip())
                return
```

Реплай своим текстом — там же, но **после** проверки команд, потому что реплай не начинается со слэша:

```python
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
                await client.send_message(cfg.panel_chat, "Отправил твой текст.",
                                          parse_mode=None)
                return
```

- [ ] **Step 7: Обновить стартовую строку в консоли**

В `print(f"Готово. ...")` добавить упоминание новых команд:

```python
          "/watch /unwatch, автоответы: /auto /stop, самообучение: "
          "/train /stats /learn /forget")
```

и строку про то, сколько диалогов на автопилоте:

```python
    on_auto = len(store.auto_chats(conn))
    auto_note = (f", на автопилоте: {on_auto}" if cfg.auto.enabled and on_auto
                 else "")
```

добавив `{auto_note}` в саму строку после `{scope}`.

- [ ] **Step 8: Прогнать всё**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/suflor/main.py tests/test_main.py
git commit -m "feat: команды /auto и /stop"
```

---

### Task 11: Документация этапа 1

Этап 1 закончен и его можно обкатывать. Документация — часть поставки: без неё владелец не узнает про `/auto`, а `config.example.yaml` разойдётся с рабочим конфигом.

**Files:**
- Modify: `README.md`
- Modify: `config.example.yaml`

- [ ] **Step 1: Добавить секцию `auto` в `config.example.yaml`**

После секции `watch_mode` (сохраняя стиль соседних комментариев — они объясняют, зачем поле, а не что оно значит):

```yaml
# Авто-ответы. Бот сам пишет и отправляет ответ в диалогах, отмеченных
# командой /auto. Ответ сначала висит окно отмены в пульте: не успел
# перехватить — уходит собеседнику. Стоп-сигналы (разговор дошёл до встречи,
# созвона, обмена номерами) и лимит ответов подряд ставят режим на паузу.
# Пауза снимается сама, как только ты сам напишешь в этот диалог.
auto:
  enabled: true              # общий рубильник; /auto по диалогам — поверх
  cancel_window_seconds: 60  # сколько ответ висит в пульте до отправки
  max_in_row: 10             # автоответов подряд без единого моего сообщения
  typing_simulation: true    # показывать «печатает…» перед отправкой
  memory_refresh_every: 10   # обновлять сводку диалога раз в N сообщений
  recent_messages: 40        # сколько последних реплик кладём в промпт
```

- [ ] **Step 2: То же самое дописать в рабочий `config.yaml`**

Секция та же. Рабочий конфиг в `.gitignore` не значится и в репозитории есть — расхождение с примером мешает.

- [ ] **Step 3: Добавить раздел в `README.md`**

Найти раздел про команды пульта (там, где описаны `/watch`, `/hint`, `/train`) и дописать `/auto` и `/stop` в том же формате. Затем добавить отдельный раздел «Авто-ответы», отвечающий на пять вопросов:

1. что делает режим и чем отличается от суфлёра;
2. как включить на диалог и как выключить;
3. что происходит с ответом в окне отмены и как его перехватить (`/stop` или реплай своим текстом);
4. когда бот замолкает сам — договорённости в реале и лимит `max_in_row`, как снимается пауза;
5. предупреждение: собеседник переписывается с моделью и не знает об этом, отвечает бот от твоего имени и с твоего аккаунта.

- [ ] **Step 4: Проверить, что конфиг из примера читается**

Run: `python -c "from suflor.config import load_config; c = load_config('config.example.yaml'); print(c.auto)"`
Expected: печатается `Auto(enabled=True, cancel_window_seconds=60, ...)` без исключений.

- [ ] **Step 5: Commit**

```bash
git add README.md config.example.yaml config.yaml
git commit -m "docs: авто-ответы в README и примере конфига"
```

---

### Task 12: Хранилище — сводка диалога (этап 2)

**Files:**
- Modify: `src/suflor/store.py`
- Modify: `tests/test_store.py`

**Interfaces:**
- Produces: `save_memory(conn, chat_id, summary: str, msg_count: int, updated_at=None) -> None`, `memory(conn, chat_id) -> dict | None` (ключи `summary: str`, `msg_count: int`, `updated_at: datetime`).

- [ ] **Step 1: Написать падающие тесты**

Дописать в `tests/test_store.py`:

```python
def test_memory_is_none_until_saved(tmp_path):
    assert memory(_store(tmp_path), 1) is None


def test_save_memory_round_trip(tmp_path):
    conn = _store(tmp_path)
    save_memory(conn, 1, "Аня, 24, из Томска", 30, NOW)
    stored = memory(conn, 1)
    assert stored["summary"] == "Аня, 24, из Томска"
    assert stored["msg_count"] == 30
    assert stored["updated_at"] == NOW


def test_save_memory_overwrites_the_previous_summary(tmp_path):
    # Сводка одна на диалог: она переписывается, а не копится версиями
    conn = _store(tmp_path)
    save_memory(conn, 1, "старая", 10, NOW)
    save_memory(conn, 1, "новая", 20, NOW)
    assert memory(conn, 1)["summary"] == "новая"
    assert memory(conn, 1)["msg_count"] == 20


def test_memory_is_per_chat(tmp_path):
    conn = _store(tmp_path)
    save_memory(conn, 1, "про Аню", 10, NOW)
    assert memory(conn, 2) is None


def test_forget_chat_erases_the_summary(tmp_path):
    conn = _store(tmp_path)
    save_memory(conn, 1, "про Аню", 10, NOW)
    forget_chat(conn, 1)
    assert memory(conn, 1) is None
```

Импорты `save_memory, memory` добавить в шапку файла.

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'save_memory'`

- [ ] **Step 3: Добавить таблицу и функции**

В `_SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS dialog_memory (
    chat_id INTEGER PRIMARY KEY,
    summary TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    msg_count INTEGER NOT NULL
);
```

Функции:

```python
def save_memory(conn, chat_id: int, summary: str, msg_count: int,
                updated_at: datetime | None = None) -> None:
    """Переписать сводку диалога.

    msg_count — длина истории на момент обновления. По разнице с текущей
    длиной решается, пора ли обновлять сводку снова.
    """
    conn.execute(
        "INSERT INTO dialog_memory (chat_id, summary, updated_at, msg_count) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET "
        "summary = excluded.summary, updated_at = excluded.updated_at, "
        "msg_count = excluded.msg_count",
        (chat_id, summary, _iso(updated_at or datetime.now(timezone.utc)),
         msg_count))
    conn.commit()


def memory(conn, chat_id: int) -> dict | None:
    row = conn.execute(
        "SELECT summary, updated_at, msg_count FROM dialog_memory "
        "WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        return None
    return {"summary": row["summary"], "msg_count": row["msg_count"],
            "updated_at": _dt(row["updated_at"])}
```

В `forget_chat`:

```python
    conn.execute("DELETE FROM dialog_memory WHERE chat_id = ?", (chat_id,))
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_store.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/suflor/store.py tests/test_store.py
git commit -m "feat: хранилище сводки диалога"
```

---

### Task 13: `memory.py` — сводка диалога

**Files:**
- Create: `src/suflor/memory.py`
- Create: `tests/test_memory.py`

**Interfaces:**
- Consumes: `suflor.dialog.format_history`, `suflor.llm.complete/LLMError`, `suflor.store.memory/save_memory`.
- Produces: `SUMMARY_MAX_CHARS: int`, `should_refresh(stored: dict | None, history_len: int, every: int) -> bool`, `build_summary_messages(history, previous="", partner_name=None) -> list[dict]`, класс `Summarizer(client, model, temperature=0.3)` с методом `summarize(history, previous="", partner_name=None) -> str`, функция `refresh(conn, summarizer, chat_id, history, every, partner_name=None) -> str`.

- [ ] **Step 1: Написать падающие тесты**

Создать `tests/test_memory.py`:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from suflor.memory import (
    Summarizer, build_summary_messages, refresh, should_refresh,
)
from suflor.store import open_store, save_memory, memory

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


def _msg(text, from_me=False, minutes_ago=0):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def _history(n):
    return [_msg(f"реплика {i}", minutes_ago=n - i) for i in range(n)]


def _summarizer(text):
    client = MagicMock()
    msg = MagicMock()
    msg.content = text
    choice = MagicMock(message=msg, finish_reason="stop")
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return Summarizer(client=client, model="m")


def test_should_refresh_without_a_stored_summary():
    assert should_refresh(None, history_len=5, every=10) is True


def test_should_refresh_after_enough_new_messages():
    stored = {"summary": "с", "msg_count": 10}
    assert should_refresh(stored, history_len=20, every=10) is True


def test_should_not_refresh_before_enough_new_messages():
    stored = {"summary": "с", "msg_count": 10}
    assert should_refresh(stored, history_len=15, every=10) is False


def test_summary_messages_carry_the_previous_summary():
    user = build_summary_messages(_history(3),
                                  previous="Аня, 24")[1]["content"]
    assert "Аня, 24" in user


def test_summary_messages_ask_for_the_four_sections():
    system = build_summary_messages(_history(3))[0]["content"]
    for section in ("Собеседник", "О чём говорили", "Как общается",
                    "Что открыто"):
        assert section in system


def test_summarize_returns_the_model_text():
    assert _summarizer("Аня, 24, из Томска").summarize(_history(3)) == \
        "Аня, 24, из Томска"


def test_summarize_trims_an_overlong_summary():
    # Сводка живёт в каждом промпте ответа: разросшаяся съедает контекст
    long_text = "а" * 5000
    assert len(_summarizer(long_text).summarize(_history(3))) <= 1200


def test_refresh_stores_the_summary_and_the_history_length(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    result = refresh(conn, _summarizer("сводка"), 1, _history(12), every=10)
    assert result == "сводка"
    assert memory(conn, 1)["summary"] == "сводка"
    assert memory(conn, 1)["msg_count"] == 12


def test_refresh_reuses_the_stored_summary_when_it_is_fresh(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    save_memory(conn, 1, "старая сводка", 10, NOW)
    s = _summarizer("новая сводка")
    assert refresh(conn, s, 1, _history(12), every=10) == "старая сводка"
    s._client.chat.completions.create.assert_not_called()


def test_refresh_survives_a_model_failure(tmp_path):
    # Память не точка отказа: не собралась — отвечаем без неё
    conn = open_store(str(tmp_path / "s.db"))
    save_memory(conn, 1, "старая сводка", 0, NOW)
    s = _summarizer("неважно")
    s._client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    assert refresh(conn, s, 1, _history(50), every=10) == "старая сводка"


def test_refresh_returns_empty_when_there_is_nothing_to_fall_back_on(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    s = _summarizer("неважно")
    s._client.chat.completions.create.side_effect = RuntimeError("сеть легла")
    assert refresh(conn, s, 1, _history(5), every=10) == ""
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_memory.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'suflor.memory'`

- [ ] **Step 3: Создать `src/suflor/memory.py`**

```python
"""Память о диалоге: короткая сводка вместо простыни из сотен сообщений.

Пятьсот сырых реплик в каждом запросе размывают внимание модели — свежая
часть разговора тонет в старой, и ответ приходит «в вакууме». Сводка держит
то, что стоит помнить долго, а сырыми в промпт идут только последние реплики.

Сводка обновляется не с нуля, а дописыванием: модели дают прошлую сводку и
накопившиеся с тех пор сообщения. Так она не переписывает историю заново на
каждом шаге и не забывает то, что уже вышло за окно.
"""
from suflor import dialog, store
from suflor.llm import LLMError, complete

# Сводка едет в каждом запросе ответа — разросшаяся съедает тот самый
# контекст, ради которого затевалась
SUMMARY_MAX_CHARS = 1200

_BUDGET = 6000

_SYSTEM = (
    "Ты ведёшь заметки о переписке, чтобы потом по ним отвечать. "
    "Перепиши сводку разговора: коротко, по делу, без вступлений и "
    "оценок. Четыре раздела, каждый с новой строки:\n"
    "Собеседник: имя, возраст, город, работа, увлечения — только то, что "
    "он сам сказал в переписке.\n"
    "О чём говорили: темы, закрытые и живые.\n"
    "Как общается: тон, длина реплик, что заходит, что нет.\n"
    "Что открыто: незакрытые вопросы, обещания, к чему шёл разговор.\n"
    "Ничего не выдумывай: чего в переписке нет, того нет в сводке. "
    "Раздел, про который сказать нечего, оставь пустым. "
    f"Уложись в {SUMMARY_MAX_CHARS} символов."
)


def should_refresh(stored: dict | None, history_len: int, every: int) -> bool:
    """Пора ли обновлять сводку.

    Считаем по длине истории, а не по времени: разговор мерится репликами.
    Сводки нет вовсе — собираем сразу.
    """
    if stored is None:
        return True
    return history_len - stored["msg_count"] >= every


def build_summary_messages(history: list[dict], previous: str = "",
                           partner_name: str | None = None) -> list[dict]:
    partner = partner_name or "Собеседник"
    blocks = []
    if previous:
        blocks.append(f"Прошлая сводка:\n{previous}")
    blocks.append(f"Переписка:\n{dialog.format_history(history, partner)}")
    blocks.append("Перепиши сводку с учётом переписки.")
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


class Summarizer:
    """Собирает сводку. Температура ниже, чем у ответов: это конспект, а не
    творчество — выдумки здесь дороже сухости.
    """

    def __init__(self, client, model: str, temperature: float = 0.3):
        self._client = client
        self._model = model
        self._temperature = temperature

    def summarize(self, history: list[dict], previous: str = "",
                  partner_name: str | None = None) -> str:
        raw = complete(
            self._client, self._model,
            build_summary_messages(history, previous, partner_name),
            self._temperature, _BUDGET + 600)
        return raw.strip()[:SUMMARY_MAX_CHARS]


def refresh(conn, summarizer: Summarizer, chat_id: int, history: list[dict],
            every: int, partner_name: str | None = None) -> str:
    """Готовая сводка диалога, обновлённая, если пора.

    Ошибка модели не пробрасывается наружу: без сводки ответ хуже, но он
    есть, а без ответа бот просто молчит.
    """
    stored = store.memory(conn, chat_id)
    if not should_refresh(stored, len(history), every):
        return stored["summary"]

    previous = stored["summary"] if stored else ""
    try:
        summary = summarizer.summarize(history, previous, partner_name)
    except LLMError:
        return previous
    if not summary:
        return previous

    store.save_memory(conn, chat_id, summary, len(history))
    return summary
```

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_memory.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/suflor/memory.py tests/test_memory.py
git commit -m "feat: сводка диалога"
```

---

### Task 14: Подключить память и закрыть этап 2

**Files:**
- Modify: `src/suflor/main.py`
- Modify: `src/suflor/suggester.py`
- Modify: `tests/test_suggester.py`
- Modify: `config.yaml`, `config.example.yaml`, `README.md`

**Interfaces:**
- `Suggester.analyze(history, partner_name=None, full_history=True, style_block="", summary="")` — новый последний аргумент со значением по умолчанию, старые вызовы не ломаются.
- `build_messages(history, system_prompt, now=None, partner_name=None, full_history=True, summary="")` — то же.

- [ ] **Step 1: Написать падающие тесты на сводку в суфлёре**

Дописать в `tests/test_suggester.py`:

```python
def test_build_messages_includes_the_summary():
    user = build_messages([{"from_me": False, "text": "привет"}], "промпт",
                          summary="Аня, 24, из Томска")[1]["content"]
    assert "Аня, 24, из Томска" in user


def test_build_messages_without_summary_is_unchanged():
    # Суфлёр без памяти обязан давать ровно тот же запрос, что и раньше
    history = [{"from_me": False, "text": "привет"}]
    assert build_messages(history, "промпт") == \
        build_messages(history, "промпт", summary="")
```

- [ ] **Step 2: Убедиться, что падают**

Run: `pytest tests/test_suggester.py -q`
Expected: FAIL — `TypeError: build_messages() got an unexpected keyword argument 'summary'`

- [ ] **Step 3: Провести сводку через суфлёра**

В `suggester.py`, в `build_messages` добавить параметр `summary: str = ""` и блок перед перепиской:

```python
    memory_block = (f"Что я помню об этом разговоре:\n{summary}\n\n"
                    if summary else "")
    user = (f"{memory_block}Вот переписка:\n{dialog_text}{since}{blocks}"
            "\n\nДай варианты моего ответа.")
```

В `Suggester._complete` и `Suggester.analyze` протянуть `summary` до `build_messages` тем же способом, каким уже протянут `full_history`.

- [ ] **Step 4: Прогнать тесты**

Run: `pytest tests/test_suggester.py -q`
Expected: PASS

- [ ] **Step 5: Подключить память в `main.py`**

Импорт: `from suflor.memory import Summarizer, refresh as refresh_memory`.

В `_amain`, рядом с созданием `responder`:

```python
    summarizer = Summarizer(client=llm_client, model=cfg.model)
```

Хелпер рядом с `_learned_style`:

```python
async def _dialog_memory(conn, cfg, summarizer, chat_id: int,
                         history: list[dict], partner_name: str) -> str:
    """Сводка диалога. Пустая строка — работаем без памяти, это допустимо."""
    if conn is None:
        return ""
    return await asyncio.to_thread(
        refresh_memory, conn, summarizer, chat_id, history,
        cfg.auto.memory_refresh_every, partner_name)
```

В `run_auto` заменить пустую сводку на настоящую:

```python
            summary = await _dialog_memory(conn, cfg, summarizer,
                                           event.chat_id, history,
                                           sender_name)
            ...
                    reply = await asyncio.to_thread(
                        responder.reply, history, sender_name, summary,
                        learned, full, cfg.auto.recent_messages)
```

Сводку получаем **после** проверки `auto_pause_reason`: диалог, уходящий на паузу, не должен оплачивать обновление памяти.

В `run_analysis` (суфлёрская ветка) и в `_handle_hint` — то же самое, сводка передаётся последним аргументом `suggester.analyze`.

В `_handle_auto` при включении режима собрать первую сводку сразу, чтобы первый же автоответ был с памятью:

```python
    store.auto_on(conn, chat_id, getattr(entity, "username", None))
    history, _ = await _collect_history(client, entity, cfg.context_messages,
                                        store.transcripts(conn, chat_id))
    if history:
        await _dialog_memory(conn, cfg, summarizer, chat_id, history, name)
```

`_handle_auto` получает `summarizer` новым параметром — обновить и вызов в обработчике команд.

- [ ] **Step 6: Снизить `context_messages` в рабочем конфиге**

В `config.yaml` и `config.example.yaml` заменить `context_messages: 500` на `context_messages: 200` и поправить комментарий: теперь долгую память держит сводка, а сырой хвост нужен только для свежей части разговора.

- [ ] **Step 7: Прогнать всё**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 8: Дополнить README**

В раздел «Авто-ответы» добавить абзац про память: что бот помнит о диалоге, как часто обновляется сводка (`memory_refresh_every`), что она стирается по `/forget` вместе с остальным и что суфлёр в `/hint` пользуется той же памятью.

- [ ] **Step 9: Commit**

```bash
git add src/suflor/main.py src/suflor/suggester.py tests/test_suggester.py config.yaml config.example.yaml README.md
git commit -m "feat: память диалога в ответах и подсказках"
```

---

## Ручная проверка после этапа 1 (задачи 1-11)

Автотесты сеть не трогают, поэтому связку с Telegram и DeepSeek владелец проверяет руками:

1. Запустить бота, убедиться, что стартовая строка упоминает `/auto`.
2. `/auto @свой_тестовый_аккаунт` — в ответ «Отвечаю сам в чате с …».
3. Написать боту с тестового аккаунта — в пульте появляется карточка с ответом и обратным отсчётом.
4. `/stop` до истечения окна — ответ не уходит.
5. Повторить и дать окну истечь — сообщение приходит на тестовый аккаунт, в пульте появляется «отправлено».
6. Написать с тестового аккаунта «давай встретимся в субботу» — приходит карточка «передаю тебе», ответ не уходит, `/auto` показывает диалог на паузе.
7. Написать в этот диалог самому — `/auto` показывает, что пауза снята.
8. `/stats` — счётчик автоответов вырос.
9. `/forget @тестовый_аккаунт`, затем `/auto` — диалога в списке нет.
