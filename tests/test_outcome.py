from datetime import datetime, timedelta, timezone

from suflor.outcome import score_reply, reply_stats, has_question

NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)


def _msg(text, minutes_ago, from_me=False):
    return {"from_me": from_me, "text": text,
            "date": NOW - timedelta(minutes=minutes_ago)}


def _score(**kw):
    base = dict(delay_s=600, reply_len=50, has_question=False,
                median_delay_s=600.0, median_len=50.0)
    base.update(kw)
    return score_reply(**base)


def test_no_reply_scores_zero():
    assert _score(delay_s=None) == 0.0


def test_plain_reply_scores_half():
    assert _score() == 0.5


def test_faster_than_usual_adds():
    assert _score(delay_s=60) == 0.7


def test_longer_than_usual_adds():
    assert _score(reply_len=200) == 0.7


def test_counter_question_adds():
    assert _score(has_question=True) == 0.6


def test_best_case_is_capped_at_one():
    assert _score(delay_s=10, reply_len=500, has_question=True) == 1.0


def test_unknown_medians_give_no_bonus():
    # Первый ответ в диалоге: сравнивать не с чем, дорисовывать бонусы нечестно
    assert _score(median_delay_s=0.0, median_len=0.0) == 0.5


def test_reply_stats_measure_her_delay_and_length():
    history = [_msg("вопрос", 30, from_me=True),
               _msg("ответ на пять слов", 20),
               _msg("ещё вопрос", 15, from_me=True),
               _msg("да", 5)]
    median_delay, median_len = reply_stats(history)
    assert median_delay == (600 + 600) / 2       # 10 минут и 10 минут
    assert median_len == (len("ответ на пять слов") + len("да")) / 2


def test_reply_stats_ignore_her_messages_that_follow_her_own():
    # Две подряд от неё — вторая не реакция на меня, её задержку не считаем
    history = [_msg("моё", 30, from_me=True),
               _msg("первое", 20),
               _msg("второе", 19)]
    median_delay, _ = reply_stats(history)
    assert median_delay == 600


def test_reply_stats_empty_history_is_unknown():
    assert reply_stats([]) == (0.0, 0.0)


def test_reply_stats_without_dates_is_unknown_delay():
    history = [{"from_me": True, "text": "моё"},
               {"from_me": False, "text": "ответ"}]
    median_delay, median_len = reply_stats(history)
    assert median_delay == 0.0
    assert median_len == len("ответ")


def test_has_question():
    assert has_question("а ты?") is True
    assert has_question("ну ладно") is False
    assert has_question("") is False
