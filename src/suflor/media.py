"""Что подставить в историю вместо сообщения без текста.

Пустая строка на месте голосового — тихая ложь: модель видит, что собеседник
«ничего не сказал», и уверенно отвечает на пустоту. Поэтому любое медиа
получает пометку, а голосовое — ещё и расшифровку, если её удалось добыть.

Расшифровку делает сам Telegram (`messages.transcribeAudio`), без Premium —
по небольшой пробной квоте. Кончилась квота, отвалился запрос, не дождались
ответа — остаётся пометка, и бот работает дальше.
"""
import asyncio
from datetime import datetime, timezone

from telethon import errors
from telethon.tl.functions.messages import TranscribeAudioRequest

# Сколько ждать досылку расшифровки. Ответ на запрос может прийти пустым с
# pending=True, а текст догнать отдельным апдейтом. Ждать не жалко: DeepSeek
# после этого думает ещё секунд тринадцать.
DEFAULT_TIMEOUT = 15.0


def _seconds(msg) -> str:
    """« 12 сек» или пусто, если длительность неизвестна."""
    duration = getattr(msg.file, "duration", None) if msg.file else None
    return f" {int(duration)} сек" if duration else ""


def _marker(msg, transcript: str | None) -> str:
    if msg.voice:
        if transcript:
            return f"[голосовое{_seconds(msg)}]"
        return f"[голосовое{_seconds(msg)}, не расшифровано]"
    if msg.video_note:
        return f"[кружок{_seconds(msg)}]"
    if msg.sticker:
        emoji = getattr(msg.file, "emoji", None) if msg.file else None
        return f"[стикер {emoji}]" if emoji else "[стикер]"
    if msg.gif:
        return "[гифка]"
    if msg.photo:
        return "[фото]"
    if msg.video:
        return f"[видео{_seconds(msg)}]"
    if msg.audio:
        return "[аудио]"
    if msg.contact:
        return "[контакт]"
    if msg.geo:
        return "[геолокация]"
    if msg.poll:
        return "[опрос]"
    if msg.document:
        return "[файл]"
    return "[вложение]"


def describe(msg, transcript: str | None = None) -> str:
    """Текст сообщения для истории: пометка, а за ней расшифровка или подпись.

    Пустая строка означает «медиа нет» — такое сообщение берут как есть.
    """
    if not any((msg.voice, msg.video_note, msg.sticker, msg.gif, msg.photo,
                msg.video, msg.audio, msg.contact, msg.geo, msg.poll,
                msg.document)):
        return ""
    tail = transcript if msg.voice else (msg.text or "")
    marker = _marker(msg, transcript)
    return f"{marker} {tail.strip()}" if tail and tail.strip() else marker


class Transcriber:
    """Расшифровка голосовых силами Telegram, с оглядкой на пробную квоту.

    Вызывать строго на новое входящее голосовое: на историю квоты не хватит
    ни при каком раскладе — её перечитывают на каждое сообщение.
    """

    def __init__(self, client, timeout: float = DEFAULT_TIMEOUT, clock=None):
        self._client = client
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # transcription_id -> future, которого ждёт transcribe()
        self._waiters: dict[int, asyncio.Future] = {}
        # Тексты апдейтов, обогнавших ответ на запрос
        self._arrived: dict[int, str] = {}
        # До этого момента квота исчерпана и запрос слать бессмысленно
        self._blocked_until: datetime | None = None

    def on_update(self, update) -> None:
        """Скормить UpdateTranscribedAudio: он несёт досланный текст."""
        if update.pending or not update.text:
            return
        future = self._waiters.pop(update.transcription_id, None)
        if future is not None and not future.done():
            future.set_result(update.text)
        else:
            self._arrived[update.transcription_id] = update.text

    def _spent(self) -> bool:
        return (self._blocked_until is not None
                and self._clock() < self._blocked_until)

    def _remember_quota(self, result) -> None:
        """Квота на нуле — до даты сброса Telegram всё равно откажет."""
        if result.trial_remains_num == 0 and result.trial_remains_until_date:
            self._blocked_until = result.trial_remains_until_date

    async def transcribe(self, peer, msg) -> str | None:
        """Текст голосового или None, если добыть его не вышло."""
        if self._spent():
            return None
        try:
            result = await self._client(TranscribeAudioRequest(peer, msg.id))
        except errors.RPCError:
            return None

        self._remember_quota(result)
        if not result.pending:
            return result.text or None
        return await self._wait(result.transcription_id)

    async def _wait(self, transcription_id: int) -> str | None:
        """Дождаться досылки текста отдельным апдейтом."""
        early = self._arrived.pop(transcription_id, None)
        if early is not None:
            return early

        future = asyncio.get_running_loop().create_future()
        self._waiters[transcription_id] = future
        try:
            return await asyncio.wait_for(future, self._timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiters.pop(transcription_id, None)
