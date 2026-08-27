"""Откладывание работы до паузы в разговоре.

В мессенджере мысль пишут не одним сообщением, а очередью коротких реплик.
Разбирать каждую — значит платить за пять запросов к модели там, где нужен
один, да ещё и по обрывку мысли вместо целой.

Debouncer держит по одной отложенной задаче на ключ (у нас ключ — диалог).
Пришло новое сообщение — прежнее ожидание отменяется и отсчёт начинается
заново. Работа выполняется, только когда собеседник замолчал.
"""
import asyncio


class Debouncer:
    def __init__(self, delay: float):
        self._delay = delay
        self._tasks: dict[object, asyncio.Task] = {}

    def pending(self) -> int:
        """Сколько задач ждёт своей паузы. Нужно, чтобы следить за утечкой."""
        return len(self._tasks)

    def schedule(self, key, factory) -> asyncio.Task:
        """Запустить factory() после паузы, отменив прежнее ожидание по key.

        factory — функция без аргументов, возвращающая корутину. Именно
        функция, а не готовая корутина: отменённая корутина, которую так и не
        запустили, роняет предупреждение «never awaited».
        """
        previous = self._tasks.get(key)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.ensure_future(self._run(key, factory))
        self._tasks[key] = task
        return task

    async def _run(self, key, factory) -> None:
        try:
            if self._delay > 0:
                await asyncio.sleep(self._delay)
            await factory()
        finally:
            # Снимаем только свою запись: пока мы работали, на этот ключ уже
            # могла встать следующая задача, и затирать её нельзя
            if self._tasks.get(key) is asyncio.current_task():
                del self._tasks[key]
