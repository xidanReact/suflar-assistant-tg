"""Что я на самом деле отправил: взял предложенный вариант, поправил его или
написал своё. Из этого потом собирается профиль манеры, поэтому ошибка здесь
дороже, чем кажется: чужой (модельный) текст, принятый за мой, отравляет
образцы.
"""
import re
from difflib import SequenceMatcher

# Всё, что не буква, не цифра и не пробел: знаки, скобки-смайлы, эмодзи
_NOT_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACES = re.compile(r"\s+")

# Ниже этого сходства считаем, что текст мой, а не правка предложенного
SIMILARITY_THRESHOLD = 0.72

# Короткие реплики («норм», «ок») случайно похожи на что угодно — для них
# только точное совпадение
MIN_FUZZY_LEN = 15


def normalize(text: str) -> str:
    """Текст в виде, пригодном для сравнения: без регистра, знаков и эмодзи."""
    return _SPACES.sub(" ", _NOT_WORD.sub("", (text or "").lower())).strip()


def _similarity(a: str, b: str) -> float:
    """Сходство с поправкой на обрезку.

    Самая частая моя правка — отрезать хвост предложенного. Обычный ratio за
    это наказывает разницей длин: половина варианта даёт всего ~0.67, и правка
    уезжает в «своё». Поэтому берём максимум из ratio и доли короткого текста,
    вошедшей в длинный одним куском.

    Именно одним куском, а не суммой совпавших кусочков: набор общих служебных
    слов («а ты», «в», «как») наберёт сумму и на двух совершенно разных
    фразах, а непрерывный кусок в размер всего текста — это уже цитата.
    """
    matcher = SequenceMatcher(None, a, b)
    ratio = matcher.ratio()
    shorter = min(len(a), len(b))
    if not shorter:
        return ratio
    longest = matcher.find_longest_match(0, len(a), 0, len(b)).size
    return max(ratio, longest / shorter)


def classify_sent(text: str, variants: list[str]) -> tuple[str, int | None, float]:
    """('variant'|'edited'|'own', индекс варианта, сходство)."""
    norm = normalize(text)
    if not norm:
        return "own", None, 0.0

    normalized = [normalize(v) for v in variants]
    for i, candidate in enumerate(normalized):
        if candidate and candidate == norm:
            return "variant", i, 1.0

    if len(norm) < MIN_FUZZY_LEN:
        return "own", None, 0.0

    best_index, best_ratio = None, 0.0
    for i, candidate in enumerate(normalized):
        if not candidate:
            continue
        ratio = _similarity(norm, candidate)
        if ratio > best_ratio:
            best_index, best_ratio = i, ratio

    if best_index is not None and best_ratio >= SIMILARITY_THRESHOLD:
        return "edited", best_index, best_ratio
    return "own", None, 0.0
