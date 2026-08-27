import asyncio

from suflor.debounce import Debouncer

PAUSE = 0.05


def _record(calls, label):
    """Фабрика корутины: Debouncer запускает её, когда пауза выдержана."""
    async def run():
        calls.append(label)
    return run


async def test_runs_the_job_after_the_pause():
    calls = []
    Debouncer(PAUSE).schedule(1, _record(calls, "а"))
    assert calls == []                      # сразу — ещё рано
    await asyncio.sleep(PAUSE * 3)
    assert calls == ["а"]


async def test_a_new_message_cancels_the_previous_wait():
    # Ради этого всё и затевалось: серия реплик — один запрос, а не пять
    calls = []
    d = Debouncer(PAUSE)
    for label in "абвгд":
        d.schedule(1, _record(calls, label))
        await asyncio.sleep(PAUSE / 5)
    await asyncio.sleep(PAUSE * 3)
    assert calls == ["д"]


async def test_different_chats_do_not_interfere():
    calls = []
    d = Debouncer(PAUSE)
    d.schedule(1, _record(calls, "первый"))
    d.schedule(2, _record(calls, "второй"))
    await asyncio.sleep(PAUSE * 3)
    assert sorted(calls) == ["второй", "первый"]


async def test_a_second_burst_after_the_first_one_finished():
    calls = []
    d = Debouncer(PAUSE)
    d.schedule(1, _record(calls, "первая серия"))
    await asyncio.sleep(PAUSE * 3)
    d.schedule(1, _record(calls, "вторая серия"))
    await asyncio.sleep(PAUSE * 3)
    assert calls == ["первая серия", "вторая серия"]


async def test_zero_delay_still_runs_the_job():
    # debounce_seconds: 0 — склейка выключена, поведение как раньше
    calls = []
    Debouncer(0).schedule(1, _record(calls, "а"))
    await asyncio.sleep(0.01)
    assert calls == ["а"]


async def test_a_failed_job_does_not_break_the_next_one():
    calls = []
    d = Debouncer(PAUSE)

    async def boom():
        raise RuntimeError("разбор упал")

    d.schedule(1, boom)
    await asyncio.sleep(PAUSE * 3)
    d.schedule(1, _record(calls, "следующая"))
    await asyncio.sleep(PAUSE * 3)
    assert calls == ["следующая"]


async def test_forgets_finished_jobs():
    # Иначе словарь задач растёт на каждый диалог и не чистится никогда
    d = Debouncer(PAUSE)
    d.schedule(1, _record([], "а"))
    await asyncio.sleep(PAUSE * 3)
    assert d.pending() == 0
