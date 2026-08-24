from telethon.tl import types

from suflor.control_panel import utf16_span
from suflor.main import _build_panel_message, parse_hint_target, forward_origin


class _Client:
    """Заглушка: отдаёт InputUser или падает, как настоящий get_input_entity."""

    def __init__(self, peer=None, error=None):
        self._peer = peer
        self._error = error

    async def get_input_entity(self, sender_id):
        if self._error:
            raise self._error
        return self._peer


class _Forward:
    def __init__(self, sender_id):
        self.sender_id = sender_id


class _Message:
    def __init__(self, forward=None):
        self.forward = forward


def test_parse_hint_target_accepts_all_forms():
    assert parse_hint_target("@anna") == "anna"
    assert parse_hint_target("anna") == "anna"
    assert parse_hint_target("https://t.me/anna") == "anna"
    assert parse_hint_target("t.me/anna") == "anna"
    assert parse_hint_target("123456789") == 123456789
    assert parse_hint_target("-1001234567890") == -1001234567890


def test_parse_hint_target_rejects_junk():
    assert parse_hint_target("") is None
    assert parse_hint_target("как дела") is None
    # инвайт-ссылка ведёт не в диалог, а в группу по хешу
    assert parse_hint_target("https://t.me/+AbCdEf") is None


def test_forward_origin_reads_sender():
    assert forward_origin(_Message(_Forward(555))) == 555


def test_forward_origin_none_without_forward():
    assert forward_origin(_Message()) is None
    assert forward_origin(None) is None


def test_forward_origin_none_when_sender_hidden():
    assert forward_origin(_Message(_Forward(None))) is None


def test_utf16_span_counts_emoji_as_two_units():
    # 💬 — суррогатная пара, в UTF-16 занимает 2 единицы, плюс пробел
    assert utf16_span("\U0001f4ac Аня", "Аня") == (3, 3)


def test_utf16_span_returns_none_when_absent():
    assert utf16_span("💬 Аня", "Оля") is None


async def test_username_becomes_text_url():
    text, entities = await _build_panel_message(
        _Client(), "Аня", "anna", 111, "привет", ["в1"])
    (entity,) = entities
    assert isinstance(entity, types.MessageEntityTextUrl)
    assert entity.url == "https://t.me/anna"
    assert (entity.offset, entity.length) == utf16_span(text, "Аня")
    assert "id 111" not in text


async def test_no_username_becomes_mention():
    peer = types.InputUser(user_id=111, access_hash=0)
    text, entities = await _build_panel_message(
        _Client(peer=peer), "Аня", None, 111, "привет", ["в1"])
    (entity,) = entities
    assert isinstance(entity, types.InputMessageEntityMentionName)
    assert entity.user_id is peer
    assert (entity.offset, entity.length) == utf16_span(text, "Аня")
    assert "id 111" not in text


async def test_unresolvable_peer_falls_back_to_plain_text():
    text, entities = await _build_panel_message(
        _Client(error=ValueError("no entity")), "Аня", None, 111, "привет",
        ["в1"])
    assert entities is None
    assert "id 111" in text


async def test_analysis_appears_before_variants():
    text, _ = await _build_panel_message(
        _Client(), "Аня", "anna", 111, "привет", ["в1"],
        analysis="Отвечает коротко.")
    assert text.index("Отвечает коротко.") < text.index("в1")
