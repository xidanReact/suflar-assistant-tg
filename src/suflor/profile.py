"""Профиль моей манеры письма — то, чему бот научился на моих же сообщениях.

Собирается в кусок промпта: несколько живых образцов, статистика по тонам и
привычки правки. Всё считается по базе, модель ничего не пересчитывает.

Правило, на котором держится смысл всей затеи: в образцы идут только тексты,
которые писал я (`own` и `edited`). Принятый без правок вариант писала модель,
и подсовывать его ей же — учить её на самой себе.
"""
import re
from statistics import median

from suflor import store
from suflor.matching import normalize

# Эмодзи и прочие пиктограммы. Диапазон грубый, но нам нужна не точность, а
# устойчивая разница «в предложенном их больше, чем в отправленном».
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF☀-➿⬀-⯿]")

# Пороги: сколько правок в одну сторону считать привычкой, а не случайностью
MIN_HABIT_EDITS = 5
SHORTER_RATIO = 0.85
LONGER_RATIO = 1.15

# Сколько подсказок нужно, чтобы «ни разу не выбрал» значило нежелание, а не
# отсутствие статистики
MIN_PICKS_FOR_FAVOURITE = 3
MIN_PICKS_FOR_NEVER = 15

# Слишком длинное сообщение манеру не показывает, а место в промпте занимает;
# слишком короткое («ок») не показывает ничего
MAX_SAMPLE_LEN = 300
MIN_SAMPLE_LEN = 4


def _fits(text: str) -> bool:
    return MIN_SAMPLE_LEN <= len((text or "").strip()) <= MAX_SAMPLE_LEN


def pick_samples(conn, chat_id: int | None, max_samples: int,
                 chat_quota: int) -> list[str]:
    """Образцы: сначала из этого же диалога, потом из общего корпуса.

    С каждым человеком у меня свой тон, поэтому свежий локальный образец
    ценнее общего — но одним диалогом ограничиваться нельзя, иначе бот
    выучит один разговор вместо манеры.
    """
    chosen: list[str] = []
    seen_ids: set[int] = set()
    seen_texts: set[str] = set()

    def take(rows, limit):
        for row in rows:
            if len(chosen) >= limit or row["id"] in seen_ids:
                continue
            text = (row["text"] or "").strip()
            # Одно и то же сообщение, отправленное дважды, второй раз ничему
            # не научит, а место в промпте займёт
            key = normalize(text)
            if not _fits(text) or key in seen_texts:
                continue
            seen_ids.add(row["id"])
            seen_texts.add(key)
            chosen.append(text)

    if chat_id is not None and chat_quota > 0:
        take(store.style_samples(conn, chat_id=chat_id, limit=chat_quota * 3),
             min(chat_quota, max_samples))
    take(store.style_samples(conn, limit=max_samples * 3), max_samples)
    return chosen


def length_habit(pairs: list[tuple[str, str]]) -> str:
    """«Предложенное я обычно сокращаю» — если это правда и повторяется."""
    shorter, longer = [], []
    for variant, mine in pairs:
        if not variant:
            continue
        ratio = len(mine) / len(variant)
        if ratio <= SHORTER_RATIO:
            shorter.append(ratio)
        elif ratio >= LONGER_RATIO:
            longer.append(ratio)

    if len(shorter) >= MIN_HABIT_EDITS and len(shorter) > len(longer):
        percent = int(round((1 - median(shorter)) * 100 / 5) * 5)
        return f"предложенное я обычно сокращаю примерно на {percent}%"
    if len(longer) >= MIN_HABIT_EDITS and len(longer) > len(shorter):
        percent = int(round((median(longer) - 1) * 100 / 5) * 5)
        return f"предложенное я обычно пишу длиннее примерно на {percent}%"
    return ""


def emoji_habit(pairs: list[tuple[str, str]]) -> str:
    """«Смайлов ставлю меньше» — тоже только при устойчивом повторении."""
    stripped = sum(1 for variant, mine in pairs
                   if len(_EMOJI.findall(mine)) < len(_EMOJI.findall(variant)))
    if stripped >= MIN_HABIT_EDITS:
        return "смайлов ставлю меньше, чем в предложенном"
    return ""


def tone_habit(conn, tones: list[str]) -> str:
    """Какой тон я выбираю чаще всего и какой не выбираю вовсе."""
    stats = store.tone_stats(conn)
    picks = sum(stats.values())
    if picks < MIN_PICKS_FOR_FAVOURITE:
        return ""

    top, count = max(stats.items(), key=lambda kv: kv[1])
    line = f"Чаще всего я беру вариант в тоне «{top}» ({count} из {picks})"

    if picks >= MIN_PICKS_FOR_NEVER:
        never = [t for t in tones if not stats.get(t)]
        if never:
            listed = ", ".join(f"«{t}»" for t in never)
            line += f", а {listed} — ни разу"
    return line + "."


def style_block(conn, chat_id: int | None = None,
                tones: list[str] | None = None, max_samples: int = 8,
                chat_quota: int = 5, min_samples: int = 5) -> str:
    """Кусок промпта с выученной манерой. Пустая строка, пока данных мало."""
    samples = pick_samples(conn, chat_id, max_samples, chat_quota)
    if len(samples) < min_samples:
        return ""

    lines = ["Вот как я пишу сам — держись этой манеры, она важнее общих "
             "правил о стиле:"]
    lines += [f"- «{s}»" for s in samples]

    tone_line = tone_habit(conn, tones or [])
    if tone_line:
        lines.append(tone_line)

    pairs = store.edited_pairs(conn)
    habits = [h for h in (length_habit(pairs), emoji_habit(pairs)) if h]
    if habits:
        lines.append("Когда правлю предложенное: " + ", ".join(habits) + ".")
    return "\n".join(lines)
