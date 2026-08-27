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
