import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import errors
from telethon.tl.types import UpdateTranscribedAudio
from telethon.tl.types.messages import TranscribedAudio

from suflor.media import describe, Transcriber

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

# Виды медиа, которые Telethon отдаёт свойствами сообщения. В фейке все
# выключены, включается ровно один — иначе describe проверял бы мок, а не себя.
_KINDS = ("voice", "video_note", "sticker", "gif", "photo", "video", "audio",
          "contact", "geo", "poll", "document")


def _msg(kind=None, text="", duration=None, emoji=None):
    m = SimpleNamespace(id=1, text=text, **{k: None for k in _KINDS})
    if kind:
        setattr(m, kind, object())
    m.file = (SimpleNamespace(duration=duration, emoji=emoji)
              if kind and (duration or emoji) else None)
    return m


def test_describes_a_voice_without_a_transcript():
    assert describe(_msg("voice", duration=12)) == "[голосовое 12 сек, не расшифровано]"


def test_puts_the_transcript_after_the_marker():
    got = describe(_msg("voice", duration=12), "привет, как ты")
    assert got == "[голосовое 12 сек] привет, как ты"


def test_marks_a_voice_of_unknown_length():
    assert describe(_msg("voice")) == "[голосовое, не расшифровано]"


def test_describes_a_video_note():
    assert describe(_msg("video_note", duration=15)) == "[кружок 15 сек]"


def test_describes_a_sticker_with_its_emoji():
    assert describe(_msg("sticker", emoji="😂")) == "[стикер 😂]"


def test_describes_a_sticker_without_an_emoji():
    assert describe(_msg("sticker")) == "[стикер]"


def test_describes_a_photo():
    assert describe(_msg("photo")) == "[фото]"


def test_keeps_the_caption_after_the_marker():
    assert describe(_msg("photo", text="я на море")) == "[фото] я на море"


def test_describes_unknown_media_as_an_attachment():
    assert describe(_msg("document")) == "[файл]"


def test_returns_empty_for_a_message_without_media():
    # Обычный текст describe не трогает — его берут как есть
    assert describe(_msg(text="привет")) == ""


def _client(result):
    """Telethon-клиент: await client(request). Ошибку тоже отдаёт он."""
    if isinstance(result, Exception):
        return AsyncMock(side_effect=result)
    return AsyncMock(return_value=result)


def _tr(client, timeout=5.0, now=NOW):
    return Transcriber(client, timeout=timeout, clock=lambda: now)


async def test_returns_the_text_when_telegram_answers_at_once():
    tr = _tr(_client(TranscribedAudio(transcription_id=1, text="привет")))
    assert await tr.transcribe(peer=1, msg=_msg("voice", duration=3)) == "привет"


async def test_waits_for_the_update_when_the_answer_is_pending():
    client = _client(TranscribedAudio(transcription_id=7, text="", pending=True))
    tr = _tr(client)
    task = asyncio.create_task(tr.transcribe(peer=1, msg=_msg("voice")))
    await asyncio.sleep(0.01)
    tr.on_update(UpdateTranscribedAudio(peer=1, msg_id=1, transcription_id=7,
                                        text="досказал", pending=False))
    assert await task == "досказал"


async def test_takes_an_update_that_arrived_before_the_request_returned():
    # Апдейт может обогнать ответ на запрос — тогда текст ждёт в кармане
    client = _client(TranscribedAudio(transcription_id=7, text="", pending=True))
    tr = _tr(client)
    tr.on_update(UpdateTranscribedAudio(peer=1, msg_id=1, transcription_id=7,
                                        text="обогнал", pending=False))
    assert await tr.transcribe(peer=1, msg=_msg("voice")) == "обогнал"


async def test_gives_up_when_the_update_never_comes():
    client = _client(TranscribedAudio(transcription_id=7, text="", pending=True))
    assert await _tr(client, timeout=0.05).transcribe(1, _msg("voice")) is None


async def test_ignores_a_still_pending_update():
    # pending-апдейт — промежуточный, текста в нём ещё нет
    client = _client(TranscribedAudio(transcription_id=7, text="", pending=True))
    tr = _tr(client, timeout=0.05)
    task = asyncio.create_task(tr.transcribe(peer=1, msg=_msg("voice")))
    await asyncio.sleep(0.01)
    tr.on_update(UpdateTranscribedAudio(peer=1, msg_id=1, transcription_id=7,
                                        text="", pending=True))
    assert await task is None


async def test_survives_an_rpc_error():
    tr = _tr(_client(errors.rpcerrorlist.MsgIdInvalidError(request=None)))
    assert await tr.transcribe(peer=1, msg=_msg("voice")) is None


async def test_stops_calling_the_api_once_the_trial_is_spent():
    # Пробная квота кончилась — до даты сброса дёргать Telegram незачем
    client = _client(TranscribedAudio(
        transcription_id=1, text="последняя", trial_remains_num=0,
        trial_remains_until_date=NOW + timedelta(days=3)))
    tr = _tr(client)
    assert await tr.transcribe(peer=1, msg=_msg("voice")) == "последняя"
    assert await tr.transcribe(peer=1, msg=_msg("voice")) is None
    assert client.await_count == 1


async def test_tries_again_after_the_quota_resets():
    client = _client(TranscribedAudio(
        transcription_id=1, text="последняя", trial_remains_num=0,
        trial_remains_until_date=NOW + timedelta(days=3)))
    tr = _tr(client)
    await tr.transcribe(peer=1, msg=_msg("voice"))
    tr._clock = lambda: NOW + timedelta(days=4)
    assert await tr.transcribe(peer=1, msg=_msg("voice")) == "последняя"
    assert client.await_count == 2
