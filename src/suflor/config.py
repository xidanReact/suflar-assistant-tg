from dataclasses import dataclass, field, fields
from pathlib import Path
import yaml

DEFAULT_MODEL = "deepseek-v4-pro"

# Реагировать на всех подряд или только на отмеченные /watch диалоги.
# По умолчанию all: конфиг, написанный до списка наблюдения, не должен
# внезапно замолчать.
WATCH_MODES = ("all", "selected")
DEFAULT_WATCH_MODE = "all"
DEFAULT_TONES = [
    "игривый, с лёгким флиртом",
    "тёплый, искренний",
    "лёгкий, с юмором",
    "спокойный, уместный — рекомендуемый",
]
DEFAULT_STYLE = (
    "Пиши на русском, как живой человек в обычной переписке: короткими "
    "простыми фразами, разговорно. Без канцелярита, пафоса, витиеватых "
    "метафор, пошлости и двусмысленных намёков. Не здоровайся, если разговор "
    "уже идёт, и не пересказывай то, что собеседник только что сказал."
)


@dataclass
class Learning:
    """Настройки самообучения. Правки применяются при перезапуске."""
    enabled: bool = True
    # Меньше этого числа моих сообщений — профиль не собирается вовсе
    min_samples: int = 5
    style_examples: int = 8
    chat_examples: int = 5
    # Насколько свежей должна быть подсказка, чтобы связывать её с отправленным
    match_window_minutes: int = 60
    # Сколько ждём ответа, прежде чем считать, что его не будет
    outcome_window_hours: int = 12
    train_chats: int = 20
    train_messages: int = 200


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


@dataclass
class Config:
    panel_chat: str
    context_messages: int = 50
    tones: list[str] = field(default_factory=lambda: list(DEFAULT_TONES))
    style: str = DEFAULT_STYLE
    temperature: float = 0.7
    model: str = DEFAULT_MODEL
    ignore_usernames: list[str] = field(default_factory=list)
    ignore_user_ids: list[int] = field(default_factory=list)
    learning: Learning = field(default_factory=Learning)
    watch_mode: str = DEFAULT_WATCH_MODE
    # Сколько ждать тишины, прежде чем разбирать диалог. Серия реплик подряд
    # превращается в один запрос вместо пяти. 0 — отвечать сразу.
    debounce_seconds: float = 0.0
    # Факты обо мне — текст файла about_file, уже прочитанный. Пустая строка,
    # пока профиля нет: промпт тогда обязан остаться прежним.
    about: str = ""
    auto: Auto = field(default_factory=Auto)


def _load_about(path: str, name: str | None) -> str:
    """Профиль из отдельного файла: длинный текст в YAML править неудобно.

    Путь считается от config.yaml, а не от рабочей директории: бота запускают
    из разных мест, и относительный путь иначе то находится, то нет. Файла
    нет — падаем на старте: молча отвечать «за меня» без фактов хуже, чем
    отказаться запускаться.
    """
    if not name:
        return ""
    file = Path(path).resolve().parent / name
    if not file.is_file():
        raise FileNotFoundError(f"не найден файл профиля: {file}")
    return file.read_text(encoding="utf-8").strip()


def _watch_mode(value: str | None) -> str:
    """Опечатка в режиме — это молчащий бот, поэтому падаем сразу и внятно."""
    if not value:
        return DEFAULT_WATCH_MODE
    if value not in WATCH_MODES:
        raise ValueError(
            f"watch_mode: ожидалось одно из {', '.join(WATCH_MODES)}, "
            f"а не «{value}»")
    return value


def _load_learning(data: dict) -> Learning:
    """Секции learning может не быть вовсе — старый конфиг должен работать."""
    known = {f.name for f in fields(Learning)}
    return Learning(**{k: v for k, v in (data or {}).items() if k in known})


def _load_auto(data: dict) -> Auto:
    """Секции auto может не быть вовсе — старый конфиг должен работать."""
    known = {f.name for f in fields(Auto)}
    return Auto(**{k: v for k, v in (data or {}).items() if k in known})


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config(
        learning=_load_learning(data.get("learning")),
        panel_chat=data["panel_chat"],
        context_messages=data.get("context_messages", 50),
        # `or` вместо get с дефолтом: пустой список тонов сломал бы промпт,
        # а пустой style оставил бы модель без указаний про манеру письма
        tones=data.get("tones") or list(DEFAULT_TONES),
        style=(data.get("style") or DEFAULT_STYLE).strip(),
        temperature=float(data.get("temperature", 0.7)),
        model=data.get("model") or DEFAULT_MODEL,
        ignore_usernames=data.get("ignore_usernames", []),
        ignore_user_ids=data.get("ignore_user_ids", []),
        about=_load_about(path, data.get("about_file")),
        watch_mode=_watch_mode(data.get("watch_mode")),
        debounce_seconds=float(data.get("debounce_seconds", 0)),
        auto=_load_auto(data.get("auto")),
    )
