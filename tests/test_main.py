from types import SimpleNamespace

from suflor.main import _ask_password, _collect_history


def _prompts(*values):
    seq = list(values)
    return lambda _prompt: seq.pop(0)


def test_returns_entered_password():
    assert _ask_password(_prompts("hunter2")) == "hunter2"


def test_reasks_until_non_empty(capsys):
    assert _ask_password(_prompts("", "   ", "hunter2")) == "hunter2"
    assert capsys.readouterr().out.count("не может быть пустым") == 2


def test_keeps_password_verbatim():
    # Пробелы могут быть частью пароля — обрезать нельзя, они только
    # не считаются за непустой ввод.
    assert _ask_password(_prompts(" hunter2 ")) == " hunter2 "


def _tg_message(text, out=False):
    return SimpleNamespace(text=text, out=out, date=None)


class _FakeClient:
    """Telethon отдаёт сообщения от новых к старым и режет выборку лимитом."""

    def __init__(self, messages):
        self._messages = messages

    def iter_messages(self, chat_id, limit):
        async def gen():
            for m in self._messages[:limit]:
                yield m
        return gen()


async def test_collect_history_orders_from_old_to_new():
    client = _FakeClient([_tg_message("второе", out=True),
                          _tg_message("первое")])
    history, _ = await _collect_history(client, 1, limit=10)
    assert [m["text"] for m in history] == ["первое", "второе"]
    assert [m["from_me"] for m in history] == [False, True]


async def test_collect_history_reports_whole_dialog():
    client = _FakeClient([_tg_message("привет")])
    _, full = await _collect_history(client, 1, limit=10)
    assert full is True


async def test_collect_history_reports_truncation_at_the_limit():
    client = _FakeClient([_tg_message(str(i)) for i in range(10)])
    _, full = await _collect_history(client, 1, limit=3)
    assert full is False


async def test_collect_history_counts_skipped_media_towards_the_limit():
    # Фото без подписи в историю не попадает, но лимит израсходовало —
    # значит, до начала переписки мы всё равно не дочитали.
    client = _FakeClient([_tg_message("привет"), _tg_message(None),
                          _tg_message("хай")])
    history, full = await _collect_history(client, 1, limit=3)
    assert [m["text"] for m in history] == ["хай", "привет"]
    assert full is False
