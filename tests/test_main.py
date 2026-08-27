from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from suflor.main import (
    resolve_incoming_text,
    _ask_password, _collect_history, record_outgoing, resolve_outcomes,
    harvest_chat, _is_harvestable, auto_pause_reason, is_bot_echo,
    SENT_BY_BOT,
)
from suflor.store import (
    open_store, save_suggestion, style_samples, tone_stats,
    save_transcript, transcripts, save_sent,
)


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


_MEDIA_KINDS = ("voice", "video_note", "sticker", "gif", "photo", "video",
                "audio", "contact", "geo", "poll", "document")


def _tg_message(text, out=False, kind=None, duration=None, msg_id=1):
    m = SimpleNamespace(id=msg_id, text=text, out=out, date=None,
                        **{k: None for k in _MEDIA_KINDS})
    if kind:
        setattr(m, kind, object())
    m.file = SimpleNamespace(duration=duration, emoji=None) if duration else None
    return m


class _FakeClient:
    """Telethon отдаёт сообщения от новых к старым и режет выборку лимитом.

    Любой вызов самого клиента — запрос к Telegram. Здесь он падает: сбор
    истории обязан обходиться без сетевых запросов, иначе пробную квоту на
    расшифровку сожжёт первый же диалог.
    """

    def __init__(self, messages):
        self._messages = messages

    def iter_messages(self, chat_id, limit):
        async def gen():
            for m in self._messages[:limit]:
                yield m
        return gen()

    async def __call__(self, request):
        raise AssertionError(f"сбор истории полез в Telegram: {request!r}")


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


async def test_collect_history_counts_unusable_messages_towards_the_limit():
    # Сообщение без текста и без распознаваемого медиа в историю не попадает,
    # но лимит израсходовало — значит, до начала переписки мы не дочитали.
    client = _FakeClient([_tg_message("привет"), _tg_message(None),
                          _tg_message("хай")])
    history, full = await _collect_history(client, 1, limit=3)
    assert [m["text"] for m in history] == ["хай", "привет"]
    assert full is False


async def test_collect_history_marks_a_voice_without_a_transcript():
    # Пустая строка на месте голосового заставляла модель отвечать на пустоту
    client = _FakeClient([_tg_message(None, kind="voice", duration=12)])
    history, _ = await _collect_history(client, 1, limit=10)
    assert [m["text"] for m in history] == ["[голосовое 12 сек, не расшифровано]"]


async def test_collect_history_substitutes_a_cached_transcript():
    client = _FakeClient([_tg_message(None, kind="voice", duration=12,
                                      msg_id=42)])
    history, _ = await _collect_history(client, 1, limit=10,
                                        transcripts={42: "привет, как ты"})
    assert [m["text"] for m in history] == ["[голосовое 12 сек] привет, как ты"]


async def test_collect_history_keeps_a_photo_caption():
    client = _FakeClient([_tg_message("я на море", kind="photo")])
    history, _ = await _collect_history(client, 1, limit=10)
    assert [m["text"] for m in history] == ["[фото] я на море"]


async def test_collect_history_never_calls_telegram_for_transcripts():
    # Регрессия на квоту: историю перечитывают на каждое входящее, и запрос
    # расшифровки отсюда выел бы её за пару сообщений
    client = _FakeClient([_tg_message(None, kind="voice", duration=5, msg_id=i)
                          for i in range(5)])
    history, _ = await _collect_history(client, 1, limit=10)
    assert len(history) == 5


NOW = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
TONES = ["игривый", "тёплый", "с юмором"]
VARIANTS = ["Всё отлично, отдыхаю. А ты как проводишь вечер?",
            "У меня всё хорошо, отдыхаю. Приятно, что спрашиваешь.",
            "Норм, отдыхаю, ничего не делаю"]


def _conn(tmp_path):
    return open_store(str(tmp_path / "suflor.db"))


def _with_suggestion(tmp_path, created_at=NOW):
    conn = _conn(tmp_path)
    save_suggestion(conn, 1, TONES, VARIANTS, "чем занимаешься?", created_at)
    return conn


def test_record_outgoing_links_a_copied_variant(tmp_path):
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, VARIANTS[1], NOW + timedelta(minutes=2))

    assert style_samples(conn) == []          # чужой текст не образец моего стиля
    assert tone_stats(conn) == {"тёплый": 1}


def test_record_outgoing_keeps_my_edit_as_a_style_sample(tmp_path):
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, "У меня всё хорошо, отдыхаю.",
                    NOW + timedelta(minutes=2))

    assert [s["text"] for s in style_samples(conn)] == ["У меня всё хорошо, отдыхаю."]
    assert tone_stats(conn) == {"тёплый": 1}  # тон я всё-таки выбрал


def test_record_outgoing_treats_my_own_text_as_own(tmp_path):
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, "Слушай, а пойдём в субботу в кино?",
                    NOW + timedelta(minutes=2))

    assert [s["source"] for s in style_samples(conn)] == ["own"]
    assert tone_stats(conn) == {}             # ни один вариант не выбран


def test_record_outgoing_ignores_a_stale_suggestion(tmp_path):
    # Через сутки после подсказки совпадение было бы случайным
    conn = _with_suggestion(tmp_path)
    record_outgoing(conn, 1, VARIANTS[1], NOW + timedelta(days=1))

    assert [s["source"] for s in style_samples(conn)] == ["own"]


def test_record_outgoing_without_any_suggestion(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "просто написал первым", NOW)
    assert [s["source"] for s in style_samples(conn)] == ["own"]


def test_record_outgoing_skips_empty_text(tmp_path):
    conn = _conn(tmp_path)
    assert record_outgoing(conn, 1, "   ", NOW) is None
    assert style_samples(conn) == []


def test_resolve_outcomes_scores_a_reply(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "моё сообщение", NOW)
    history = [{"from_me": True, "text": "моё сообщение", "date": NOW},
               {"from_me": False, "text": "ответ", "date": NOW + timedelta(minutes=5)}]

    assert resolve_outcomes(conn, 1, history, "ответ",
                            NOW + timedelta(minutes=5)) == 1
    assert style_samples(conn)[0]["score"] == 0.5


def test_resolve_outcomes_marks_zero_past_the_window(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "моё сообщение", NOW)
    late = NOW + timedelta(hours=20)

    resolve_outcomes(conn, 1, [], "ответила через сутки", late)
    assert style_samples(conn)[0]["score"] == 0.0


def test_resolve_outcomes_closes_a_burst_of_my_messages(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "первое моё", NOW)
    record_outgoing(conn, 1, "второе моё", NOW + timedelta(minutes=1))

    assert resolve_outcomes(conn, 1, [], "ответ", NOW + timedelta(minutes=5)) == 2


def test_resolve_outcomes_ignores_messages_sent_after_the_reply(tmp_path):
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "уже после ответа", NOW + timedelta(hours=1))
    assert resolve_outcomes(conn, 1, [], "ответ", NOW) == 0


def test_resolve_outcomes_upgrades_a_late_reply(tmp_path):
    # Сначала пометили нулём по таймауту, потом она всё же ответила
    conn = _conn(tmp_path)
    record_outgoing(conn, 1, "моё сообщение", NOW)
    resolve_outcomes(conn, 1, [], "чужая реплика", NOW + timedelta(hours=20))
    assert style_samples(conn)[0]["score"] == 0.0

    resolve_outcomes(conn, 1, [], "ответ", NOW + timedelta(minutes=30))
    assert style_samples(conn)[0]["score"] == 0.5


def _harvest_message(text, out=True, minutes_ago=0):
    return SimpleNamespace(text=text, out=out,
                           date=NOW - timedelta(minutes=minutes_ago))


class _HistoryClient:
    def __init__(self, messages):
        self._messages = messages

    def iter_messages(self, entity, limit):
        async def gen():
            for m in self._messages[:limit]:
                yield m
        return gen()


async def test_harvest_takes_only_my_texts(tmp_path):
    conn = _conn(tmp_path)
    client = _HistoryClient([_harvest_message("моё", minutes_ago=1),
                             _harvest_message("её", out=False, minutes_ago=2),
                             _harvest_message(None, minutes_ago=3),
                             _harvest_message("   ", minutes_ago=4)])

    assert await harvest_chat(client, conn, object(), 1, limit=10) == 1
    assert [s["text"] for s in style_samples(conn)] == ["моё"]


async def test_harvest_is_idempotent(tmp_path):
    conn = _conn(tmp_path)
    client = _HistoryClient([_harvest_message("моё", minutes_ago=1)])

    assert await harvest_chat(client, conn, object(), 1, limit=10) == 1
    assert await harvest_chat(client, conn, object(), 1, limit=10) == 0
    assert len(style_samples(conn)) == 1


async def test_harvest_does_not_relabel_a_chosen_variant(tmp_path):
    # Бот уже записал это сообщение как выбранный вариант — /train не должен
    # превращать текст модели в образец моей манеры
    conn = _with_suggestion(tmp_path)
    sent_at = NOW + timedelta(minutes=2)
    record_outgoing(conn, 1, VARIANTS[1], sent_at)
    client = _HistoryClient([SimpleNamespace(text=VARIANTS[1], out=True,
                                             date=sent_at)])

    assert await harvest_chat(client, conn, object(), 1, limit=10) == 0
    assert style_samples(conn) == []


def _dialog(is_user=True, bot=False, is_self=False, uid=5, username="anna"):
    entity = SimpleNamespace(bot=bot, is_self=is_self, id=uid,
                             username=username)
    return SimpleNamespace(is_user=is_user, entity=entity)


def _train_cfg(**kw):
    from suflor.config import Config
    return Config(panel_chat="me", **kw)


def test_harvestable_accepts_a_normal_person():
    assert _is_harvestable(_dialog(), _train_cfg()) is True


def test_harvestable_skips_groups_bots_and_saved_messages():
    cfg = _train_cfg()
    assert _is_harvestable(_dialog(is_user=False), cfg) is False
    assert _is_harvestable(_dialog(bot=True), cfg) is False
    assert _is_harvestable(_dialog(is_self=True), cfg) is False


def test_harvestable_respects_the_ignore_list():
    assert _is_harvestable(_dialog(username="mom"),
                           _train_cfg(ignore_usernames=["mom"])) is False
    assert _is_harvestable(_dialog(uid=7),
                           _train_cfg(ignore_user_ids=[7])) is False


def test_harvestable_handles_a_person_without_username():
    assert _is_harvestable(_dialog(username=None), _train_cfg()) is True


class _FakeTranscriber:
    def __init__(self, result=None):
        self.result = result
        self.calls = 0

    async def transcribe(self, peer, msg):
        self.calls += 1
        return self.result


async def test_resolve_returns_plain_text_as_is(tmp_path):
    tr = _FakeTranscriber("не должно понадобиться")
    got = await resolve_incoming_text(_conn(tmp_path), tr, 1, "peer",
                                      _tg_message("привет"))
    assert got == "привет"
    assert tr.calls == 0


async def test_resolve_transcribes_a_voice_and_caches_it(tmp_path):
    conn = _conn(tmp_path)
    tr = _FakeTranscriber("привет, как ты")
    msg = _tg_message(None, kind="voice", duration=12, msg_id=42)
    got = await resolve_incoming_text(conn, tr, 1, "peer", msg)
    assert got == "[голосовое 12 сек] привет, как ты"
    assert transcripts(conn, 1) == {42: "привет, как ты"}


async def test_resolve_falls_back_to_the_marker_when_transcription_fails(tmp_path):
    conn = _conn(tmp_path)
    msg = _tg_message(None, kind="voice", duration=12, msg_id=42)
    got = await resolve_incoming_text(conn, _FakeTranscriber(None), 1, "peer", msg)
    assert got == "[голосовое 12 сек, не расшифровано]"
    assert transcripts(conn, 1) == {}


async def test_resolve_uses_the_cache_instead_of_the_quota(tmp_path):
    conn = _conn(tmp_path)
    save_transcript(conn, 1, 42, "уже расшифровано", NOW)
    tr = _FakeTranscriber("новое")
    msg = _tg_message(None, kind="voice", duration=12, msg_id=42)
    got = await resolve_incoming_text(conn, tr, 1, "peer", msg)
    assert got == "[голосовое 12 сек] уже расшифровано"
    assert tr.calls == 0


async def test_resolve_does_not_transcribe_a_photo(tmp_path):
    tr = _FakeTranscriber("не должно понадобиться")
    msg = _tg_message("я на море", kind="photo")
    got = await resolve_incoming_text(_conn(tmp_path), tr, 1, "peer", msg)
    assert got == "[фото] я на море"
    assert tr.calls == 0


async def test_resolve_works_without_a_store():
    # conn=None бывает, когда самообучение выключено совсем
    msg = _tg_message(None, kind="voice", duration=12, msg_id=42)
    got = await resolve_incoming_text(None, _FakeTranscriber("слышно"), 1,
                                      "peer", msg)
    assert got == "[голосовое 12 сек] слышно"


def test_auto_pause_reason_fires_on_real_world_arrangements(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    cfg = SimpleNamespace(auto=SimpleNamespace(max_in_row=10))
    assert auto_pause_reason(conn, cfg, "давай встретимся в субботу", 1)


def test_auto_pause_reason_silent_on_ordinary_talk(tmp_path):
    conn = open_store(str(tmp_path / "s.db"))
    cfg = SimpleNamespace(auto=SimpleNamespace(max_in_row=10))
    assert auto_pause_reason(conn, cfg, "как прошёл день?", 1) is None


def test_auto_pause_reason_fires_on_too_many_auto_in_row(tmp_path):
    # Защита от бесконечной беседы модели с человеком
    conn = open_store(str(tmp_path / "s.db"))
    cfg = SimpleNamespace(auto=SimpleNamespace(max_in_row=3))
    for i in range(3):
        save_sent(conn, 1, f"бот {i}", "auto",
                  sent_at=datetime(2026, 8, 25, 12, i, tzinfo=timezone.utc))
    reason = auto_pause_reason(conn, cfg, "как дела?", 1)
    assert reason is not None and "подряд" in reason


def test_bot_echo_is_recognised_once():
    # Автоответ вернётся в обработчик как моё исходящее — записать его в
    # корпус манеры значит учить модель на её же текстах
    SENT_BY_BOT.clear()
    SENT_BY_BOT.add((1, 100))
    assert is_bot_echo(1, 100) is True
    assert is_bot_echo(1, 100) is False   # запись разовая, память не течёт


def test_bot_echo_is_false_for_my_own_message():
    SENT_BY_BOT.clear()
    assert is_bot_echo(1, 100) is False
