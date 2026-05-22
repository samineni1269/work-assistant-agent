"""
tools/trigger_engine.py — Webhook-triggered automation rules
============================================================
Stores if-this-then-that rules in SQLite.
Called by webhook_server when a new event arrives.

Rule schema:
    source      — "github" | "jira" | "any"
    event_type  — "pull_request" | "issues" | "push" | "any"
    condition   — JSON dict of key:substring pairs to match in event payload
    action      — "slack_message" | "create_jira" | "create_linear" | "notify"
    action_args — JSON dict of args for the action

DB: ~/.work-assistant-triggers.db
"""

import sqlite3
import json
import datetime
from pathlib import Path

DB_PATH = Path.home() / ".work-assistant-triggers.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'any',
            event_type  TEXT    NOT NULL DEFAULT 'any',
            condition   TEXT    NOT NULL DEFAULT '{}',
            action      TEXT    NOT NULL,
            action_args TEXT    NOT NULL DEFAULT '{}',
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL,
            fire_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trigger_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id     INTEGER NOT NULL,
            rule_name   TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            result      TEXT    NOT NULL,
            fired_at    TEXT    NOT NULL
        )
    """)
    conn.commit()
    return conn


def add_rule(name: str, source: str, event_type: str,
             condition: dict, action: str, action_args: dict) -> dict:
    """Add a new automation rule. Returns the created rule."""
    db = _get_db()
    now = datetime.datetime.now().isoformat()
    cursor = db.execute("""
        INSERT INTO rules(name, source, event_type, condition, action, action_args, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, source, event_type,
          json.dumps(condition), action, json.dumps(action_args), now))
    db.commit()
    rule_id = cursor.lastrowid
    db.close()
    return {"id": rule_id, "name": name, "source": source,
            "event_type": event_type, "action": action}


def list_rules() -> list:
    """List all rules."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, name, source, event_type, condition, action, action_args, "
        "enabled, created_at, fire_count FROM rules ORDER BY id"
    ).fetchall()
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        d["condition"] = json.loads(d["condition"])
        d["action_args"] = json.loads(d["action_args"])
        result.append(d)
    return result


def delete_rule(rule_id: int) -> dict:
    """Delete a rule by ID."""
    db = _get_db()
    db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    db.commit()
    db.close()
    return {"deleted": rule_id}


def toggle_rule(rule_id: int, enabled: bool) -> dict:
    """Enable or disable a rule."""
    db = _get_db()
    db.execute("UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
    db.commit()
    db.close()
    return {"id": rule_id, "enabled": enabled}


def _matches(event: dict, condition: dict) -> bool:
    """Check if every key:substring pair in condition matches the event payload."""
    if not condition:
        return True
    payload_str = json.dumps(event).lower()
    for key, substr in condition.items():
        if str(substr).lower() not in payload_str:
            return False
    return True


def evaluate_event(source: str, event_type: str, event: dict) -> list:
    """
    Check all enabled rules against an incoming event.
    Returns list of rule dicts that matched (caller executes the actions).
    """
    db = _get_db()
    rows = db.execute("""
        SELECT id, name, source, event_type, condition, action, action_args
        FROM rules
        WHERE enabled=1
          AND (source='any' OR source=?)
          AND (event_type='any' OR event_type=?)
    """, (source, event_type)).fetchall()

    matched = []
    now = datetime.datetime.now().isoformat()
    for row in rows:
        condition = json.loads(row["condition"])
        if _matches(event, condition):
            action_args = json.loads(row["action_args"])
            matched.append({
                "rule_id":     row["id"],
                "rule_name":   row["name"],
                "action":      row["action"],
                "action_args": action_args,
            })
            db.execute("UPDATE rules SET fire_count=fire_count+1 WHERE id=?", (row["id"],))
            db.execute("""
                INSERT INTO trigger_log(rule_id, rule_name, event_type, result, fired_at)
                VALUES (?, ?, ?, ?, ?)
            """, (row["id"], row["name"], event_type, "matched", now))

    db.commit()
    db.close()
    return matched


def get_trigger_log(limit: int = 50) -> list:
    """Return recent trigger fire log entries."""
    db = _get_db()
    rows = db.execute(
        "SELECT rule_id, rule_name, event_type, result, fired_at "
        "FROM trigger_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
