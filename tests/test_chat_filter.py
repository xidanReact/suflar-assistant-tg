from suflor.chat_filter import should_suggest, IncomingContext
from suflor.config import Config


def _cfg(**kw):
    return Config(panel_chat="p", **kw)


def _ctx(**kw):
    base = dict(is_private=True, is_bot=False, is_outgoing=False,
                sender_id=1, sender_username="anna")
    base.update(kw)
    return IncomingContext(**base)


def test_reacts_to_normal_private_incoming():
    assert should_suggest(_ctx(), _cfg(), enabled=True) is True


def test_ignores_when_disabled():
    assert should_suggest(_ctx(), _cfg(), enabled=False) is False


def test_ignores_outgoing():
    assert should_suggest(_ctx(is_outgoing=True), _cfg(), enabled=True) is False


def test_ignores_groups_and_channels():
    assert should_suggest(_ctx(is_private=False), _cfg(), enabled=True) is False


def test_ignores_bots():
    assert should_suggest(_ctx(is_bot=True), _cfg(), enabled=True) is False


def test_ignores_username_in_ignore_list():
    cfg = _cfg(ignore_usernames=["anna"])
    assert should_suggest(_ctx(sender_username="anna"), cfg, enabled=True) is False


def test_ignores_user_id_in_ignore_list():
    cfg = _cfg(ignore_user_ids=[1])
    assert should_suggest(_ctx(sender_id=1), cfg, enabled=True) is False
