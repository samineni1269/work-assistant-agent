"""
action_items.py — Action Item Extraction & Tracking
======================================================
Extracts concrete action items from text (emails, meeting notes, chat messages)
using the active LLM, and stores them in a local SQLite database.

Usage:
    from tools.action_items import extract_action_items, get_my_action_items, complete_action_item
"""

import os
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".work-assistant-action-items.db"


# ─────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS action_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            task        TEXT    NOT NULL,
            owner       TEXT    DEFAULT '',
            due_date    TEXT    DEFAULT '',
            source      TEXT    DEFAULT '',
            priority    TEXT    DEFAULT 'medium',
            status      TEXT    DEFAULT 'open',
            extracted_at TEXT   NOT NULL,
            completed_at TEXT   DEFAULT ''
        )
    """)
    conn.commit()
    return conn


# ─────────────────────────────────────────────
# EXTRACTION — uses the active LLM
# ─────────────────────────────────────────────

def extract_action_items(
    text: str,
    source: str = "manual",
    save: bool = True,
) -> list[dict]:
    """
    Extract concrete action items from a block of text using the LLM.
    Identifies who needs to do what, by when.

    Args:
        text:   The text to analyse (email body, meeting notes, chat, etc.)
        source: Label for where this text came from (e.g. 'email', 'meeting')
        save:   If True, save extracted items to SQLite automatically

    Returns:
        List of action item dicts: task, owner, due_date, priority
    """
    if not text or not text.strip():
        return []

    prompt = f"""Extract all concrete action items from the text below.
An action item is a specific task that someone needs to do (not vague ideas or FYI notes).

For each action item output a JSON object with these fields:
- task: clear description of what needs to be done (imperative, specific)
- owner: who must do it — use "me" if it's the reader's responsibility, or a name/email if mentioned
- due_date: deadline if mentioned (YYYY-MM-DD format, or "" if none)
- priority: "high" if urgent/blocking/ASAP, "medium" if normal, "low" if optional

Return ONLY a JSON array. No explanation, no markdown. Example:
[{{"task": "Send the revised proposal to John", "owner": "me", "due_date": "2025-06-10", "priority": "high"}}]

If there are no action items, return [].

TEXT:
---
{text[:4000]}
---"""

    try:
        from tools.llm_provider import get_fast_provider
        provider = get_fast_provider()
        _, response_text = provider.run_turn(
            system_prompt="You are a precise action item extractor. Output only valid JSON arrays.",
            history=[{"role": "user", "content": prompt}],
            tools=[],
        )
        # Parse JSON from response
        response_text = (response_text or "").strip()
        # Strip markdown code fences if present
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        items = json.loads(response_text)
        if not isinstance(items, list):
            return []
    except Exception as e:
        return [{"error": f"Extraction failed: {e}", "task": "", "owner": "", "due_date": "", "priority": ""}]

    # Validate and normalise
    valid_items = []
    for item in items:
        if not isinstance(item, dict) or not item.get("task"):
            continue
        clean = {
            "task":      str(item.get("task", "")).strip(),
            "owner":     str(item.get("owner", "me")).strip(),
            "due_date":  str(item.get("due_date", "")).strip(),
            "priority":  str(item.get("priority", "medium")).lower(),
            "source":    source,
        }
        valid_items.append(clean)

    if save and valid_items:
        save_action_items(valid_items)

    return valid_items


# ─────────────────────────────────────────────
# STORAGE
# ─────────────────────────────────────────────

def save_action_items(items: list[dict]) -> int:
    """
    Save a list of action item dicts to the database.
    Returns the number of items saved.
    """
    conn = _get_db()
    now = datetime.datetime.now().isoformat()
    count = 0
    for item in items:
        task = item.get("task", "").strip()
        if not task:
            continue
        conn.execute("""
            INSERT INTO action_items (task, owner, due_date, source, priority, status, extracted_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?)
        """, (
            task,
            item.get("owner", ""),
            item.get("due_date", ""),
            item.get("source", "manual"),
            item.get("priority", "medium"),
            now,
        ))
        count += 1
    conn.commit()
    conn.close()
    return count


def get_my_action_items(
    status: str = "open",
    priority: str = None,
    max_count: int = 30,
) -> list[dict]:
    """
    Retrieve action items from the database.

    Args:
        status:    'open', 'completed', or 'all'
        priority:  Filter by 'high', 'medium', 'low' (optional)
        max_count: Max items to return

    Returns:
        List of action item dicts ordered by priority then due_date
    """
    conn = _get_db()
    conditions = []
    params = []

    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order = """
        ORDER BY
            CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            CASE WHEN due_date = '' THEN 1 ELSE 0 END,
            due_date ASC
        LIMIT ?
    """
    params.append(max_count)

    rows = conn.execute(f"SELECT * FROM action_items {where} {order}", params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def complete_action_item(item_id: int) -> dict:
    """
    Mark an action item as completed.

    Args:
        item_id: The action item's database ID

    Returns:
        {"status": "completed", "id": item_id}
    """
    conn = _get_db()
    now = datetime.datetime.now().isoformat()
    conn.execute(
        "UPDATE action_items SET status='completed', completed_at=? WHERE id=?",
        (now, item_id)
    )
    conn.commit()
    conn.close()
    return {"status": "completed", "id": item_id}


def delete_action_item(item_id: int) -> dict:
    """Delete an action item from the database."""
    conn = _get_db()
    conn.execute("DELETE FROM action_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    return {"status": "deleted", "id": item_id}


# ─────────────────────────────────────────────
# PRIORITY SCORING — scores notification lists
# ─────────────────────────────────────────────

def score_notifications(notifications: list[dict], context: str = "") -> list[dict]:
    """
    Score a list of notification/email/issue dicts by urgency using the LLM.

    Each item in the list should have at minimum a 'title' or 'subject' or 'text' field.
    Adds a 'priority' field: 'urgent', 'action_today', 'fyi', or 'ignore'.
    Adds a 'reason' field explaining the score.

    Args:
        notifications: List of dicts (emails, GitHub notifs, Jira issues, etc.)
        context:       Optional context about the user (e.g. "senior engineer on platform team")

    Returns:
        Same list with 'priority' and 'reason' fields added, sorted by priority.
    """
    if not notifications:
        return []

    # Build a compact list for the LLM
    items_text = ""
    for i, n in enumerate(notifications):
        title = n.get("title") or n.get("subject") or n.get("text", "")[:100] or str(n)[:100]
        source = n.get("type") or n.get("source") or n.get("repo") or ""
        items_text += f"{i}: [{source}] {title}\n"

    prompt = f"""Score each notification by urgency. Return a JSON array with one object per item.

Context: {context or 'software engineer'}

Notifications (index: title):
{items_text}

For each notification return:
{{
  "index": <int>,
  "priority": "urgent" | "action_today" | "fyi" | "ignore",
  "reason": "<one short sentence why>"
}}

Priority definitions:
- urgent: blocks you or others, time-sensitive (< 2 hours), security issue, production down
- action_today: needs your attention today but not immediate
- fyi: informational, no action needed from you soon
- ignore: automated, irrelevant, noise

Return ONLY a JSON array, no markdown."""

    try:
        from tools.llm_provider import get_fast_provider
        provider = get_fast_provider()
        _, response_text = provider.run_turn(
            system_prompt="You are a concise notification prioritiser. Output only valid JSON.",
            history=[{"role": "user", "content": prompt}],
            tools=[],
        )
        response_text = (response_text or "").strip()
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        scores = json.loads(response_text)
    except Exception as e:
        # Fallback: return unsorted with unknown priority
        for n in notifications:
            n.setdefault("priority", "fyi")
            n.setdefault("reason", "Scoring unavailable")
        return notifications

    # Merge scores back
    score_map = {s["index"]: s for s in scores if isinstance(s, dict)}
    priority_order = {"urgent": 0, "action_today": 1, "fyi": 2, "ignore": 3}

    for i, n in enumerate(notifications):
        score = score_map.get(i, {})
        n["priority"] = score.get("priority", "fyi")
        n["reason"]   = score.get("reason", "")

    notifications.sort(key=lambda x: priority_order.get(x.get("priority", "fyi"), 2))
    return notifications
