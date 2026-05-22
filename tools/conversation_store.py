"""
tools/conversation_store.py — Persistent conversation history
=============================================================
Stores all agent conversations in SQLite so users can browse,
search, and restore past sessions from the web UI.

DB: ~/.work-assistant-conversations.db
"""

import sqlite3
import datetime
import json
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".work-assistant-conversations.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT    PRIMARY KEY,
            tool_id     TEXT    NOT NULL DEFAULT 'home',
            title       TEXT    NOT NULL DEFAULT 'Untitled',
            started_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            turn_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL REFERENCES sessions(id),
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            ts          TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id)")
    conn.commit()
    return conn


def save_turn(session_id: str, tool_id: str, role: str, content: str, title: str = "") -> None:
    """Append a single turn to a session, creating the session if needed."""
    now = datetime.datetime.now().isoformat()
    db = _get_db()
    db.execute("""
        INSERT INTO sessions(id, tool_id, title, started_at, updated_at, turn_count)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            updated_at = excluded.updated_at,
            turn_count = turn_count + 1,
            title = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END
    """, (session_id, tool_id, title or "Untitled", now, now))
    db.execute(
        "INSERT INTO turns(session_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now)
    )
    db.commit()
    db.close()


def get_session_turns(session_id: str) -> list:
    """Return all turns for a session as list of {role, content, ts}."""
    db = _get_db()
    rows = db.execute(
        "SELECT role, content, ts FROM turns WHERE session_id=? ORDER BY id",
        (session_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def list_sessions(tool_id: Optional[str] = None, limit: int = 50) -> list:
    """List recent sessions, optionally filtered by tool_id."""
    db = _get_db()
    if tool_id:
        rows = db.execute(
            "SELECT id, tool_id, title, started_at, updated_at, turn_count FROM sessions "
            "WHERE tool_id=? ORDER BY updated_at DESC LIMIT ?",
            (tool_id, limit)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, tool_id, title, started_at, updated_at, turn_count FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def search_sessions(query: str, limit: int = 20) -> list:
    """Full-text search across turn content. Returns matching sessions."""
    db = _get_db()
    rows = db.execute("""
        SELECT DISTINCT s.id, s.tool_id, s.title, s.started_at, s.updated_at, s.turn_count
        FROM sessions s
        JOIN turns t ON t.session_id = s.id
        WHERE t.content LIKE ?
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (f"%{query}%", limit)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    """Delete a session and all its turns."""
    db = _get_db()
    db.execute("DELETE FROM turns WHERE session_id=?", (session_id,))
    db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    db.commit()
    db.close()


def get_session_title_from_first_user_message(session_id: str) -> str:
    """Generate a short title from the first user message in the session."""
    db = _get_db()
    row = db.execute(
        "SELECT content FROM turns WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
        (session_id,)
    ).fetchone()
    db.close()
    if not row:
        return "Untitled"
    text = row["content"]
    return text[:60] + ("…" if len(text) > 60 else "")
