"""
webhook_server.py — Real-time Webhook Listener
================================================
Flask Blueprint that receives GitHub and Jira webhooks, validates signatures,
parses events, and stores them in a local SQLite database.

Events are also auto-processed:
  - GitHub PR opened/merged   → extract action items
  - GitHub issue assigned     → save as action item
  - Jira issue created/updated → extract action items

Setup:
  1. Add GITHUB_WEBHOOK_SECRET and JIRA_WEBHOOK_SECRET to .env
  2. Register this blueprint in app.py:
       from tools.webhook_server import webhook_bp, init_webhook_db
       init_webhook_db()
       app.register_blueprint(webhook_bp)
  3. Expose your server publicly (e.g. via Cloudflare Tunnel) and set:
       GitHub:  https://your-domain/webhooks/github
       Jira:    https://your-domain/webhooks/jira

Database:
  ~/.work-assistant-webhooks.db
"""

import os
import json
import hmac
import hashlib
import sqlite3
import datetime
from pathlib import Path
from typing import Optional

from flask import Blueprint, request, jsonify

WEBHOOK_DB_PATH = Path.home() / ".work-assistant-webhooks.db"

webhook_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def init_webhook_db():
    """Create the webhook events table if it doesn't exist."""
    conn = sqlite3.connect(str(WEBHOOK_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source       TEXT NOT NULL,
            event_type   TEXT NOT NULL,
            payload      TEXT NOT NULL,
            received_at  TEXT NOT NULL,
            processed    INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def _save_event(source: str, event_type: str, payload: dict) -> int:
    """Persist a webhook event to the DB. Returns the new row ID."""
    conn = sqlite3.connect(str(WEBHOOK_DB_PATH))
    cursor = conn.execute(
        "INSERT INTO webhook_events (source, event_type, payload, received_at) VALUES (?, ?, ?, ?)",
        (source, event_type, json.dumps(payload, default=str), datetime.datetime.utcnow().isoformat()),
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_recent_events(source: str = None, limit: int = 50) -> list[dict]:
    """
    Retrieve recent webhook events from the database.

    Args:
        source: Filter by 'github' or 'jira' (None = all)
        limit:  Max events to return

    Returns:
        List of event dicts: id, source, event_type, payload (dict), received_at
    """
    conn = sqlite3.connect(str(WEBHOOK_DB_PATH))
    conn.row_factory = sqlite3.Row
    if source:
        rows = conn.execute(
            "SELECT * FROM webhook_events WHERE source=? ORDER BY id DESC LIMIT ?",
            (source, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM webhook_events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    events = []
    for row in rows:
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            pass
        events.append(d)
    return events


# ─────────────────────────────────────────────
# SIGNATURE VALIDATION
# ─────────────────────────────────────────────

def _verify_github_signature(body: bytes, sig_header: str) -> bool:
    """Validate GitHub webhook HMAC-SHA256 signature."""
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return True  # No secret configured → skip validation (not recommended for prod)
    if not sig_header or not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


def _verify_jira_signature(body: bytes, sig_header: str) -> bool:
    """Validate Jira webhook HMAC-SHA256 signature (if secret configured)."""
    secret = os.getenv("JIRA_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not sig_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.lstrip("sha256="))


# ─────────────────────────────────────────────
# EVENT PROCESSING
# ─────────────────────────────────────────────

def _process_github_event(event_type: str, payload: dict):
    """
    Auto-process a GitHub event:
    - PR opened   → extract action items from PR body
    - Issue assigned to me → save as action item
    - PR review requested  → save as action item
    """
    try:
        from tools.action_items import extract_action_items, save_action_items

        if event_type == "pull_request":
            action = payload.get("action", "")
            pr = payload.get("pull_request", {})
            title = pr.get("title", "")
            body  = pr.get("body", "") or ""
            repo  = payload.get("repository", {}).get("full_name", "")
            url   = pr.get("html_url", "")

            if action in ("opened", "reopened") and body.strip():
                # Extract action items from PR description
                items = extract_action_items(
                    text=f"PR: {title}\n\n{body}",
                    source=f"github_pr:{repo}",
                    save=True,
                )

            if action == "review_requested":
                # Someone requested a review from me
                requested_reviewer = payload.get("requested_reviewer", {}).get("login", "")
                save_action_items([{
                    "task": f"Review PR: {title} ({repo})",
                    "owner": "me",
                    "due_date": "",
                    "priority": "high",
                    "source": f"github_pr:{repo}",
                }])

        elif event_type == "issues":
            action = payload.get("action", "")
            issue  = payload.get("issue", {})
            title  = issue.get("title", "")
            body   = issue.get("body", "") or ""
            repo   = payload.get("repository", {}).get("full_name", "")
            me     = os.getenv("GITHUB_USERNAME", "").lower()
            assignees = [a.get("login", "").lower() for a in issue.get("assignees", [])]

            if action == "assigned" and me and me in assignees:
                save_action_items([{
                    "task": f"Resolve issue: {title} ({repo})",
                    "owner": "me",
                    "due_date": "",
                    "priority": "medium",
                    "source": f"github_issue:{repo}",
                }])

    except Exception:
        pass  # Non-fatal — webhook was still received OK


def _process_jira_event(payload: dict):
    """
    Auto-process a Jira webhook event:
    - issue_created / issue_updated with assignee = me → save as action item
    """
    try:
        from tools.action_items import save_action_items

        event = payload.get("webhookEvent", "")
        issue = payload.get("issue", {})
        if not issue:
            return

        fields   = issue.get("fields", {})
        summary  = fields.get("summary", "")
        priority = (fields.get("priority") or {}).get("name", "Medium").lower()
        assignee = (fields.get("assignee") or {}).get("emailAddress", "")
        due_date = fields.get("duedate", "") or ""
        project  = (fields.get("project") or {}).get("key", "")
        issue_key = issue.get("key", "")

        me = os.getenv("JIRA_EMAIL", "").lower()
        if me and assignee.lower() != me:
            return  # Not assigned to me

        prio_map = {"highest": "high", "high": "high", "medium": "medium",
                    "low": "low", "lowest": "low"}
        mapped_prio = prio_map.get(priority, "medium")

        if event in ("jira:issue_created", "jira:issue_updated") and summary:
            save_action_items([{
                "task": f"[{issue_key}] {summary}",
                "owner": "me",
                "due_date": due_date,
                "priority": mapped_prio,
                "source": f"jira:{project}",
            }])
    except Exception:
        pass


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────

@webhook_bp.route("/github", methods=["POST"])
def github_webhook():
    """Receive GitHub webhook events."""
    body       = request.get_data()
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    event_type = request.headers.get("X-GitHub-Event", "unknown")

    if not _verify_github_signature(body, sig_header):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    event_id = _save_event("github", event_type, payload)
    _process_github_event(event_type, payload)

    return jsonify({"status": "received", "event_id": event_id, "type": event_type}), 200


@webhook_bp.route("/jira", methods=["POST"])
def jira_webhook():
    """Receive Jira webhook events."""
    body       = request.get_data()
    sig_header = request.headers.get("X-Hub-Signature", "")

    if not _verify_jira_signature(body, sig_header):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    event_type = payload.get("webhookEvent", "unknown")
    event_id = _save_event("jira", event_type, payload)
    _process_jira_event(payload)

    return jsonify({"status": "received", "event_id": event_id, "type": event_type}), 200


@webhook_bp.route("/events", methods=["GET"])
def list_events():
    """List recent webhook events (for debugging / dashboard)."""
    source = request.args.get("source")
    limit  = int(request.args.get("limit", 50))
    events = get_recent_events(source=source, limit=limit)
    return jsonify({"events": events, "count": len(events)})


@webhook_bp.route("/health", methods=["GET"])
def webhook_health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "listener": "active"})
