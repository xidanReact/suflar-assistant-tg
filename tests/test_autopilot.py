import asyncio

from suflor.autopilot import Autopilot, typing_delay

WINDOW = 0.05


def _recorder(calls):
    async def send(chat_id, text, typing_seconds):
        calls.append((chat_id, text, typing_seconds))
    return send


def test_typing_delay_grows_with_length():
    assert typing_delay("привет") < typing_delay("привет, как твои дела")


def test_typing_delay_is_capped():
    assert typing_delay("а" * 10_000) == 10.0


def test_typing_delay_of_empty_text_is_zero():
    assert typing_delay("") == 0.0


async def test_sends_after_the_window():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "привет")
    assert calls == []                       # сразу — ещё рано
    await asyncio.sleep(WINDOW * 4)
    assert calls == [(1, "привет", typing_delay("привет"))]


async def test_cancel_stops_the_send():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "привет")
    assert a.cancel(1).text == "привет"      # вернули, что отменили
    await asyncio.sleep(WINDOW * 4)
    assert calls == []


async def test_cancel_of_nothing_is_harmless():
    a = Autopilot(_recorder([]), WINDOW)
    assert a.cancel(999) is None


async def test_scheduling_again_replaces_the_previous_reply():
    # Пришло новое сообщение — прежний ответ устарел и уходить не должен
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "старый ответ")
    a.schedule(1, "новый ответ")
    await asyncio.sleep(WINDOW * 4)
    assert [text for _, text, _ in calls] == ["новый ответ"]


async def test_different_chats_do_not_interfere():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW)
    a.schedule(1, "первому")
    a.schedule(2, "второму")
    await asyncio.sleep(WINDOW * 4)
    assert sorted(text for _, text, _ in calls) == ["второму", "первому"]


async def test_pending_is_forgotten_after_sending():
    a = Autopilot(_recorder([]), WINDOW)
    a.schedule(1, "привет")
    await asyncio.sleep(WINDOW * 4)
    assert a.pending(1) is None
    assert a.all_pending() == []


async def test_typing_can_be_switched_off():
    calls = []
    a = Autopilot(_recorder(calls), WINDOW, typing=False)
    a.schedule(1, "длинное сообщение про всё на свете")
    await asyncio.sleep(WINDOW * 4)
    assert calls[0][2] == 0.0


async def test_card_maps_back_to_its_chat():
    # Реплай на карточку в пульте должен попасть в нужный диалог
    a = Autopilot(_recorder([]), WINDOW)
    a.schedule(7, "привет")
    a.attach_card(7, 555)
    assert a.chat_for_card(555) == 7
    assert a.pending(7).card_id == 555
    a.cancel(7)                              # чтобы отправка не пережила тест


async def test_card_is_forgotten_on_cancel():
    a = Autopilot(_recorder([]), WINDOW)
    a.schedule(7, "привет")
    a.attach_card(7, 555)
    a.cancel(7)
    assert a.chat_for_card(555) is None
