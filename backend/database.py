"""SQLite persistence for word-pk."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "wordpk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    shanbay_cookie TEXT DEFAULT '',
    shanbay_status TEXT DEFAULT 'none',
    last_sync_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE,
    definitions TEXT NOT NULL DEFAULT '[]',
    definitions_json TEXT NOT NULL DEFAULT '[]',
    phonetic TEXT DEFAULT '',
    book_id TEXT DEFAULT '',
    freq_score REAL DEFAULT 0.5,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS user_words (
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    schedule REAL DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    learned INTEGER DEFAULT 0,
    proficiency REAL DEFAULT 0,
    last_seen_at REAL,
    source TEXT DEFAULT 'shanbay',
    PRIMARY KEY (user_id, word_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (word_id) REFERENCES words(id)
);

CREATE TABLE IF NOT EXISTS pk_memories (
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    wrong_count INTEGER DEFAULT 0,
    right_count INTEGER DEFAULT 0,
    last_wrong_at REAL,
    last_right_at REAL,
    streak INTEGER DEFAULT 0,
    weight REAL DEFAULT 0,
    PRIMARY KEY (user_id, word_id),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (word_id) REFERENCES words(id)
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_code TEXT NOT NULL,
    user_a INTEGER NOT NULL,
    user_b INTEGER NOT NULL,
    mode TEXT DEFAULT 'mixed',
    word_count INTEGER DEFAULT 20,
    status TEXT DEFAULT 'waiting',
    question_order TEXT DEFAULT '[]',
    score_a INTEGER DEFAULT 0,
    score_b INTEGER DEFAULT 0,
    time_a REAL DEFAULT 0,
    time_b REAL DEFAULT 0,
    started_at REAL,
    finished_at REAL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS match_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    q_index INTEGER NOT NULL,
    answer_text TEXT DEFAULT '',
    choice_index INTEGER,
    is_correct INTEGER DEFAULT 0,
    elapsed_ms INTEGER DEFAULT 0,
    created_at REAL NOT NULL,
    FOREIGN KEY (match_id) REFERENCES matches(id)
);

CREATE INDEX IF NOT EXISTS idx_user_words_user ON user_words(user_id);
CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
CREATE INDEX IF NOT EXISTS idx_matches_room ON matches(room_code);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now() -> float:
    return time.time()


def row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


def ensure_user(name: str, display_name: str | None = None) -> dict:
    name = name.strip().lower()
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
        if row:
            return dict(row)
        cur = conn.execute(
            "INSERT INTO users (name, display_name, created_at) VALUES (?, ?, ?)",
            (name, display_name or name, now()),
        )
        user_id = cur.lastrowid
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row)


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def delete_user(user_id: int) -> bool:
    """Remove a user and all personal progress. Words table is shared and kept."""
    with connect() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM user_words WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM pk_memories WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM match_answers WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return True


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def update_user(user_id: int, **fields) -> dict | None:
    if not fields:
        return get_user(user_id)
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [user_id]
    with connect() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id = ?", values)
    return get_user(user_id)


def upsert_word(
    word: str,
    definitions: list[str],
    phonetic: str = "",
    book_id: str = "",
    freq_score: float = 0.5,
) -> int:
    word = word.strip().lower()
    defs = [d.strip() for d in definitions if d and d.strip()]
    with connect() as conn:
        row = conn.execute("SELECT id FROM words WHERE word = ?", (word,)).fetchone()
        if row:
            conn.execute(
                "UPDATE words SET definitions = ?, definitions_json = ?, phonetic = ?, book_id = ?, freq_score = ? WHERE id = ?",
                (
                    " / ".join(defs),
                    json.dumps(defs, ensure_ascii=False),
                    phonetic,
                    book_id,
                    freq_score,
                    row["id"],
                ),
            )
            return int(row["id"])
        cur = conn.execute(
            "INSERT INTO words (word, definitions, definitions_json, phonetic, book_id, freq_score, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                word,
                " / ".join(defs),
                json.dumps(defs, ensure_ascii=False),
                phonetic,
                book_id,
                freq_score,
                now(),
            ),
        )
        return int(cur.lastrowid)


def get_word(word_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
        return dict(row) if row else None


def upsert_user_word(
    user_id: int,
    word_id: int,
    schedule: float = 0,
    failed_count: int = 0,
    learned: int = 1,
    proficiency: float | None = None,
    source: str = "shanbay",
) -> None:
    if proficiency is None:
        proficiency = compute_proficiency(schedule, failed_count, learned)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO user_words (user_id, word_id, schedule, failed_count, learned, proficiency, last_seen_at, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, word_id) DO UPDATE SET
                schedule = excluded.schedule,
                failed_count = excluded.failed_count,
                learned = excluded.learned,
                proficiency = excluded.proficiency,
                last_seen_at = excluded.last_seen_at,
                source = excluded.source
            """,
            (
                user_id,
                word_id,
                schedule,
                failed_count,
                learned,
                proficiency,
                now(),
                source,
            ),
        )


def compute_proficiency(schedule: float, failed_count: int, learned: int) -> float:
    """Map Shanbay fields into 0..1 mastery."""
    if not learned:
        return 0.0
    base = max(0.0, min(1.0, float(schedule) / 7.0))
    penalty = min(0.5, int(failed_count) * 0.08)
    return round(max(0.0, min(1.0, base - penalty)), 3)


def get_common_learned_words(user_a: int, user_b: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT w.*,
                   ua.proficiency AS prof_a, ua.schedule AS sch_a, ua.failed_count AS fail_a,
                   ub.proficiency AS prof_b, ub.schedule AS sch_b, ub.failed_count AS fail_b
            FROM words w
            JOIN user_words ua ON ua.word_id = w.id AND ua.user_id = ? AND ua.learned = 1
            JOIN user_words ub ON ub.word_id = w.id AND ub.user_id = ? AND ub.learned = 1
            """,
            (user_a, user_b),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pk_memory(user_id: int, word_ids: list[int]) -> dict[int, dict]:
    if not word_ids:
        return {}
    marks = ",".join("?" for _ in word_ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM pk_memories WHERE user_id = ? AND word_id IN ({marks})",
            [user_id, *word_ids],
        ).fetchall()
        return {int(r["word_id"]): dict(r) for r in rows}


def record_pk_answer(
    user_id: int, word_id: int, is_correct: bool, elapsed_ms: int
) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM pk_memories WHERE user_id = ? AND word_id = ?",
            (user_id, word_id),
        ).fetchone()
        if row:
            wrong = int(row["wrong_count"])
            right = int(row["right_count"])
            streak = int(row["streak"])
            if is_correct:
                right += 1
                streak = max(0, streak) + 1 if streak >= 0 else 1
                weight = max(0.0, float(row["weight"]) * 0.55)
            else:
                wrong += 1
                streak = min(0, streak) - 1 if streak <= 0 else -1
                weight = min(3.0, float(row["weight"]) + 1.0)
            conn.execute(
                """
                UPDATE pk_memories
                SET wrong_count = ?, right_count = ?, streak = ?, weight = ?,
                    last_wrong_at = ?, last_right_at = ?
                WHERE user_id = ? AND word_id = ?
                """,
                (
                    wrong,
                    right,
                    streak,
                    weight,
                    None if is_correct else now(),
                    now() if is_correct else row["last_right_at"],
                    user_id,
                    word_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO pk_memories (user_id, word_id, wrong_count, right_count, streak, weight, last_wrong_at, last_right_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    word_id,
                    0 if is_correct else 1,
                    1 if is_correct else 0,
                    1 if is_correct else -1,
                    0.0 if is_correct else 1.0,
                    None if is_correct else now(),
                    now() if is_correct else None,
                ),
            )


def create_match(
    room_code: str,
    user_a: int,
    user_b: int,
    mode: str,
    word_count: int,
    question_order: list[int],
) -> dict:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO matches (room_code, user_a, user_b, mode, word_count, question_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_code,
                user_a,
                user_b,
                mode,
                word_count,
                json.dumps(question_order),
                now(),
            ),
        )
        match_id = cur.lastrowid
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return dict(row)


def get_match(match_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        return dict(row) if row else None


def get_match_by_room(room_code: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM matches WHERE room_code = ? ORDER BY id DESC LIMIT 1",
            (room_code,),
        ).fetchone()
        return dict(row) if row else None


def update_match(match_id: int, **fields) -> dict | None:
    if not fields:
        return get_match(match_id)
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [match_id]
    with connect() as conn:
        conn.execute(f"UPDATE matches SET {cols} WHERE id = ?", values)
    return get_match(match_id)


def save_answer(
    match_id: int,
    word_id: int,
    user_id: int,
    q_index: int,
    answer_text: str,
    choice_index: int | None,
    is_correct: bool,
    elapsed_ms: int,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO match_answers (match_id, word_id, user_id, q_index, answer_text, choice_index, is_correct, elapsed_ms, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                word_id,
                user_id,
                q_index,
                answer_text,
                choice_index,
                1 if is_correct else 0,
                elapsed_ms,
                now(),
            ),
        )


def get_match_answers(match_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM match_answers WHERE match_id = ? ORDER BY q_index, user_id",
            (match_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_stats(user_id: int) -> dict:
    with connect() as conn:
        learned = conn.execute(
            "SELECT COUNT(*) AS c FROM user_words WHERE user_id = ? AND learned = 1",
            (user_id,),
        ).fetchone()["c"]
        weak = conn.execute(
            """
            SELECT COUNT(*) AS c FROM user_words
            WHERE user_id = ? AND learned = 1 AND proficiency < 0.45
            """,
            (user_id,),
        ).fetchone()["c"]
        matches = conn.execute(
            "SELECT COUNT(*) AS c FROM matches WHERE user_a = ? OR user_b = ?",
            (user_id, user_id),
        ).fetchone()["c"]
        return {"learned": learned, "weak": weak, "matches": matches}
