"""Хранилище сигналов для самообучения: что предложено, что я отправил,
как на это ответили.

Всё лежит в SQLite рядом с сессией. Времена хранятся строками ISO в UTC —
sqlite сравнивает их лексикографически, чего для сортировки и «свежее чем»
достаточно.
"""
import json
import sqlite3
from datetime import datetime, timezone

# Образец, собранный из истории командой /train, исхода не имеет. Ноль здесь
# был бы враньём (мы не знаем, ответили ли), поэтому считаем его средним.
DEFAULT_SCORE = 0.5

# Источник отправленного: взял вариант как есть / поправил / написал сам.
# В образцы моей манеры идут только два последних — см. план, «схлопывание».
MY_OWN_SOURCES = ("own", "edited")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    tones TEXT NOT NULL,
    variants TEXT NOT NULL,
    incoming_text TEXT
);

CREATE TABLE IF NOT EXISTS sent (
    id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    suggestion_id INTEGER REFERENCES suggestions(id) ON DELETE SET NULL,
    variant_index INTEGER
);

CREATE TABLE IF NOT EXISTS outcomes (
    sent_id INTEGER PRIMARY KEY REFERENCES sent(id) ON DELETE CASCADE,
    replied_at TEXT,
    reply_text TEXT,
    delay_s INTEGER,
    score REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    chat_id INTEGER NOT NULL,
    msg_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (chat_id, msg_id)
);

CREATE TABLE IF NOT EXISTS watched (
    chat_id INTEGER PRIMARY KEY,
    username TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auto_chats (
    chat_id INTEGER PRIMARY KEY,
    username TEXT,
    paused_reason TEXT,
    added_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sent_chat ON sent(chat_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_suggestions_chat
    ON suggestions(chat_id, created_at);
"""


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def open_store(path: str) -> sqlite3.Connection:
    """Открыть базу, создав схему, если её ещё нет."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def save_suggestion(conn, chat_id: int, tones: list[str], variants: list[str],
                    incoming_text: str | None,
                    created_at: datetime | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO suggestions (chat_id, created_at, tones, variants, "
        "incoming_text) VALUES (?, ?, ?, ?, ?)",
        (chat_id, _iso(created_at or datetime.now(timezone.utc)),
         json.dumps(tones, ensure_ascii=False),
         json.dumps(variants, ensure_ascii=False), incoming_text))
    conn.commit()
    return cur.lastrowid


def last_suggestion(conn, chat_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM suggestions WHERE chat_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1", (chat_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "chat_id": row["chat_id"],
            "created_at": _dt(row["created_at"]),
            "tones": json.loads(row["tones"]),
            "variants": json.loads(row["variants"]),
            "incoming_text": row["incoming_text"]}


def save_sent(conn, chat_id: int, text: str, source: str,
              suggestion_id: int | None = None,
              variant_index: int | None = None,
              sent_at: datetime | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO sent (chat_id, sent_at, text, source, suggestion_id, "
        "variant_index) VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, _iso(sent_at or datetime.now(timezone.utc)), text, source,
         suggestion_id, variant_index))
    conn.commit()
    return cur.lastrowid


def sent_exists(conn, chat_id: int, sent_at: datetime) -> bool:
    """Есть ли уже такое сообщение — защита /train от повторного сбора."""
    row = conn.execute(
        "SELECT 1 FROM sent WHERE chat_id = ? AND sent_at = ? LIMIT 1",
        (chat_id, _iso(sent_at))).fetchone()
    return row is not None


def save_outcome(conn, sent_id: int, replied_at: datetime | None,
                 reply_text: str | None, delay_s: int | None,
                 score: float) -> None:
    conn.execute(
        "INSERT INTO outcomes (sent_id, replied_at, reply_text, delay_s, "
        "score) VALUES (?, ?, ?, ?, ?) ON CONFLICT(sent_id) DO UPDATE SET "
        "replied_at = excluded.replied_at, reply_text = excluded.reply_text, "
        "delay_s = excluded.delay_s, score = excluded.score",
        (sent_id, _iso(replied_at), reply_text, delay_s, score))
    conn.commit()


def pending_outcomes(conn, chat_id: int) -> list[dict]:
    """Мои сообщения в чате, ответа на которые мы ещё не видели.

    Сюда попадает и то, что уже помечено «не ответила» по таймауту: ответ мог
    прийти позже, и тогда нулевую оценку надо исправить. Записи с реальным
    ответом не возвращаются — их исход окончателен.
    """
    rows = conn.execute(
        "SELECT s.id, s.sent_at FROM sent s "
        "LEFT JOIN outcomes o ON o.sent_id = s.id "
        "WHERE s.chat_id = ? AND (o.sent_id IS NULL OR o.replied_at IS NULL) "
        "ORDER BY s.sent_at", (chat_id,)).fetchall()
    return [{"id": r["id"], "sent_at": _dt(r["sent_at"])} for r in rows]


def expire_pending(conn, older_than: datetime) -> int:
    """Закрыть нулём всё, на что уже точно не ответят.

    Нужно для диалогов, которые просто заглохли: без этого «меня проигнорили»
    навсегда осталось бы без исхода и считалось бы средним по умолчанию.
    """
    cur = conn.execute(
        "INSERT INTO outcomes (sent_id, replied_at, reply_text, delay_s, score) "
        "SELECT s.id, NULL, NULL, NULL, 0.0 FROM sent s "
        "LEFT JOIN outcomes o ON o.sent_id = s.id "
        "WHERE o.sent_id IS NULL AND s.sent_at < ?", (_iso(older_than),))
    conn.commit()
    return cur.rowcount


def style_samples(conn, chat_id: int | None = None,
                  limit: int = 50) -> list[dict]:
    """Мои собственные сообщения — от удачных к неудачным, свежие раньше."""
    where = "s.source IN (?, ?)"
    params: list = list(MY_OWN_SOURCES)
    if chat_id is not None:
        where += " AND s.chat_id = ?"
        params.append(chat_id)
    params.append(limit)
    rows = conn.execute(
        f"SELECT s.id, s.chat_id, s.text, s.source, s.sent_at, "
        f"COALESCE(o.score, {DEFAULT_SCORE}) AS score FROM sent s "
        f"LEFT JOIN outcomes o ON o.sent_id = s.id WHERE {where} "
        "ORDER BY score DESC, s.sent_at DESC, s.id DESC LIMIT ?",
        params).fetchall()
    return [{"id": r["id"], "chat_id": r["chat_id"], "text": r["text"],
             "source": r["source"], "sent_at": _dt(r["sent_at"]),
             "score": r["score"]} for r in rows]


def _picked_rows(conn, chat_id: int | None):
    """Отправленное, за которым стоит конкретный предложенный вариант."""
    sql = ("SELECT g.tones, g.variants, s.variant_index, s.text FROM sent s "
           "JOIN suggestions g ON g.id = s.suggestion_id "
           "WHERE s.variant_index IS NOT NULL")
    params: list = []
    if chat_id is not None:
        sql += " AND s.chat_id = ?"
        params.append(chat_id)
    return conn.execute(sql + " ORDER BY s.id", params).fetchall()


def tone_stats(conn, chat_id: int | None = None) -> dict[str, int]:
    """Сколько раз какой тон был выбран. Тона живут в конфиге и меняются,
    поэтому индекс из старой подсказки может не попасть в её список тонов —
    такие записи молча пропускаем.
    """
    stats: dict[str, int] = {}
    for row in _picked_rows(conn, chat_id):
        tones = json.loads(row["tones"])
        idx = row["variant_index"]
        if 0 <= idx < len(tones):
            stats[tones[idx]] = stats.get(tones[idx], 0) + 1
    return stats


def edited_pairs(conn, chat_id: int | None = None) -> list[tuple[str, str]]:
    """Пары «что предложили — что я отправил» по правленым вариантам."""
    sql = ("SELECT g.variants, s.variant_index, s.text FROM sent s "
           "JOIN suggestions g ON g.id = s.suggestion_id "
           "WHERE s.source = 'edited' AND s.variant_index IS NOT NULL")
    params: list = []
    if chat_id is not None:
        sql += " AND s.chat_id = ?"
        params.append(chat_id)
    out = []
    for row in conn.execute(sql + " ORDER BY s.id", params):
        variants = json.loads(row["variants"])
        idx = row["variant_index"]
        if 0 <= idx < len(variants):
            out.append((variants[idx], row["text"]))
    return out


def suggestion_count(conn, chat_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM suggestions"
    params: list = []
    if chat_id is not None:
        sql += " WHERE chat_id = ?"
        params.append(chat_id)
    return conn.execute(sql, params).fetchone()["n"]


def forget_chat(conn, chat_id: int) -> None:
    """Стереть всё, что связано с этим человеком."""
    conn.execute(
        "DELETE FROM outcomes WHERE sent_id IN "
        "(SELECT id FROM sent WHERE chat_id = ?)", (chat_id,))
    conn.execute("DELETE FROM sent WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM suggestions WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM transcripts WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM watched WHERE chat_id = ?", (chat_id,))
    conn.execute("DELETE FROM auto_chats WHERE chat_id = ?", (chat_id,))
    conn.commit()


def save_transcript(conn, chat_id: int, msg_id: int, text: str,
                    created_at: datetime | None = None) -> None:
    """Запомнить расшифровку голосового.

    Кеш обязателен, а не удобен: историю перечитывают на каждое входящее, и
    без него одно голосовое расшифровывалось бы снова и снова, пока не
    кончится пробная квота.
    """
    conn.execute(
        "INSERT INTO transcripts (chat_id, msg_id, text, created_at) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(chat_id, msg_id) DO UPDATE SET "
        "text = excluded.text, created_at = excluded.created_at",
        (chat_id, msg_id, text,
         _iso(created_at or datetime.now(timezone.utc))))
    conn.commit()


def transcripts(conn, chat_id: int) -> dict[int, str]:
    """Все расшифровки диалога разом: id сообщения -> текст."""
    rows = conn.execute(
        "SELECT msg_id, text FROM transcripts WHERE chat_id = ?", (chat_id,))
    return {r["msg_id"]: r["text"] for r in rows}


def watch(conn, chat_id: int, username: str | None,
          added_at: datetime | None = None) -> None:
    """Взять диалог под наблюдение. Повтор просто освежает username."""
    conn.execute(
        "INSERT INTO watched (chat_id, username, added_at) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET username = excluded.username",
        (chat_id, username, _iso(added_at or datetime.now(timezone.utc))))
    conn.commit()


def unwatch(conn, chat_id: int) -> bool:
    """Снять наблюдение. False — его и не было, есть о чём сказать в пульт."""
    removed = conn.execute("DELETE FROM watched WHERE chat_id = ?",
                           (chat_id,)).rowcount
    conn.commit()
    return bool(removed)


def watched_chats(conn) -> list:
    """Весь список, в порядке добавления."""
    return conn.execute(
        "SELECT chat_id, username, added_at FROM watched ORDER BY added_at, "
        "chat_id").fetchall()


def is_watched(conn, chat_id: int) -> bool:
    return conn.execute("SELECT 1 FROM watched WHERE chat_id = ?",
                        (chat_id,)).fetchone() is not None


def auto_on(conn, chat_id: int, username: str | None,
            added_at: datetime | None = None) -> None:
    """Поставить диалог на автопилот. Повтор освежает username и
    снимает паузу: /auto — это «продолжай, я разрулил».
    """
    conn.execute(
        "INSERT INTO auto_chats (chat_id, username, paused_reason, added_at) "
        "VALUES (?, ?, NULL, ?) ON CONFLICT(chat_id) DO UPDATE SET "
        "username = excluded.username, paused_reason = NULL",
        (chat_id, username, _iso(added_at or datetime.now(timezone.utc))))
    conn.commit()


def auto_off(conn, chat_id: int) -> bool:
    """Снять с автопилота.

    False — его там и не было.
    """
    removed = conn.execute("DELETE FROM auto_chats WHERE chat_id = ?",
                           (chat_id,)).rowcount
    conn.commit()
    return bool(removed)


def auto_chats(conn) -> list:
    """Весь список, включая диалоги на паузе.

    В порядке добавления.
    """
    return conn.execute(
        "SELECT chat_id, username, paused_reason, added_at FROM auto_chats "
        "ORDER BY added_at, chat_id").fetchall()


def auto_state(conn, chat_id: int) -> dict | None:
    row = conn.execute(
        "SELECT chat_id, username, paused_reason FROM auto_chats "
        "WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None:
        return None
    return {"chat_id": row["chat_id"], "username": row["username"],
            "paused_reason": row["paused_reason"]}


def is_auto(conn, chat_id: int) -> bool:
    """Отвечать ли в этом диалоге самому.

    Пауза считается за «нет».
    """
    state = auto_state(conn, chat_id)
    return state is not None and state["paused_reason"] is None


def pause_auto(conn, chat_id: int, reason: str) -> None:
    conn.execute("UPDATE auto_chats SET paused_reason = ? WHERE chat_id = ?",
                 (reason, chat_id))
    conn.commit()


def resume_auto(conn, chat_id: int) -> bool:
    """Снять паузу.

    False — диалога нет в списке или паузы не было.
    """
    changed = conn.execute(
        "UPDATE auto_chats SET paused_reason = NULL "
        "WHERE chat_id = ? AND paused_reason IS NOT NULL",
        (chat_id,)).rowcount
    conn.commit()
    return bool(changed)


def auto_in_row(conn, chat_id: int, cap: int = 50) -> int:
    """Подряд идущие автосообщения в хвосте.

    По хвосту: моё сообщение обнуляет счёт. Дальше не смотрим, лимит
    в десятки.
    """
    rows = conn.execute(
        "SELECT source FROM sent WHERE chat_id = ? "
        "ORDER BY sent_at DESC, id DESC LIMIT ?", (chat_id, cap))
    count = 0
    for row in rows:
        if row["source"] != "auto":
            break
        count += 1
    return count


def learning_summary(conn) -> dict:
    """Сводка для /stats."""
    placeholders = ", ".join("?" * len(MY_OWN_SOURCES))
    samples = conn.execute(
        f"SELECT COUNT(*) AS n FROM sent WHERE source IN ({placeholders})",
        MY_OWN_SOURCES).fetchone()["n"]
    totals = conn.execute(
        "SELECT COUNT(*) AS sent, COUNT(DISTINCT chat_id) AS chats FROM sent"
    ).fetchone()
    avg = conn.execute("SELECT AVG(score) AS s FROM outcomes").fetchone()["s"]
    auto = conn.execute(
        "SELECT COUNT(*) AS n FROM sent WHERE source = 'auto'"
    ).fetchone()["n"]
    auto_score = conn.execute(
        "SELECT AVG(o.score) AS s FROM outcomes o JOIN sent s "
        "ON s.id = o.sent_id WHERE s.source = 'auto'").fetchone()["s"]
    return {"samples": samples, "sent": totals["sent"],
            "chats": totals["chats"], "suggestions": suggestion_count(conn),
            "tones": tone_stats(conn), "avg_score": avg, "auto": auto,
            "auto_score": auto_score}
