"""Насколько удачным оказалось моё сообщение — по тому, как на него ответили.

Это эвристика, а не истина: быстрый короткий ответ может значить и живой
интерес, и вежливую отписку. Она нужна лишь для того, чтобы ранжировать мои
же сообщения между собой, поэтому промах в отдельном случае не страшен.

Сравнение идёт с медианой конкретной собеседницы, а не с абсолютными числами:
у одной норма — ответ через минуту, у другой — через день.
"""
from statistics import median

REPLIED = 0.5
FASTER_BONUS = 0.2
LONGER_BONUS = 0.2
QUESTION_BONUS = 0.1


def has_question(text: str | None) -> bool:
    return "?" in (text or "")


def score_reply(delay_s: int | None, reply_len: int, has_question: bool,
                median_delay_s: float, median_len: float) -> float:
    """0.0 — не ответили, 1.0 — ответили быстро, длинно и со встречным вопросом.

    Нулевая медиана значит «сравнивать не с чем» (первый ответ в диалоге) —
    тогда бонусы не начисляем, а не выдаём их даром.
    """
    if delay_s is None:
        return 0.0
    score = REPLIED
    if median_delay_s > 0 and delay_s < median_delay_s:
        score += FASTER_BONUS
    if median_len > 0 and reply_len > median_len:
        score += LONGER_BONUS
    if has_question:
        score += QUESTION_BONUS
    # Округление не косметика: сумма долей даёт 0.9999999999999999, и это
    # уезжает в базу и в сравнения
    return round(min(score, 1.0), 3)


def reply_stats(history: list[dict]) -> tuple[float, float]:
    """Медианные задержка и длина её ответов. 0.0 — данных нет.

    Задержка считается только у первого её сообщения после моего: вторая
    реплика подряд — продолжение её же мысли, а не реакция на меня.
    """
    delays, lengths = [], []
    prev_mine = None
    for m in history:
        if m["from_me"]:
            prev_mine = m.get("date")
            continue
        lengths.append(len(m.get("text") or ""))
        date = m.get("date")
        if prev_mine and date:
            delays.append((date - prev_mine).total_seconds())
        prev_mine = None  # следующая её реплика идёт уже не на моё сообщение
    return (median(delays) if delays else 0.0,
            median(lengths) if lengths else 0.0)
