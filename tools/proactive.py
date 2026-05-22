"""
tools/proactive.py — Proactive Background Monitoring
======================================================
Runs a background thread that polls your tools every few minutes.
Pushes real-time alerts to the web UI via a queue consumed by SSE.

Monitors:
  • Urgent / unread emails (new since last check)
  • PRs waiting for your review (GitHub)
  • CI failures on your repos (GitHub Actions)
  • Calendar — meeting starting in ≤10 minutes
  • Linear issues that became Blocked
  • Jira issues overdue

Enable/disable each alert type via proactive_settings.json or the UI toggle.
"""

import os
import json
import queue
import threading
import datetime
import time
from pathlib import Path

_BASE = Path(__file__).parent.parent

SETTINGS_FILE = _BASE / "proactive_settings.json"

# Thread-safe queue consumed by the SSE endpoint in app.py
alert_queue: queue.Queue = queue.Queue(maxsize=100)

_DEFAULT_SETTINGS = {
    "enabled":           True,
    "poll_interval_sec": 300,   # 5 minutes
    "alerts": {
        "urgent_email":     True,
        "pr_review":        True,
        "ci_failure":       True,
        "meeting_reminder": True,
        "linear_blocked":   True,
        "jira_overdue":     True,
    },
}

# Track what we've already alerted about to avoid repeats
_seen: dict = {
    "email_ids":    set(),
    "pr_ids":       set(),
    "run_ids":      set(),
    "meeting_ids":  set(),
    "linear_ids":   set(),
    "jira_ids":     set(),
}

_thread: threading.Thread | None = None
_stop_event = threading.Event()


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            # Merge with defaults (handles new keys added later)
            merged = dict(_DEFAULT_SETTINGS)
            merged.update(data)
            merged["alerts"] = dict(_DEFAULT_SETTINGS["alerts"])
            merged["alerts"].update(data.get("alerts", {}))
            return merged
        except Exception:
            pass
    return dict(_DEFAULT_SETTINGS)


def save_settings(s: dict):
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))


def toggle_alert(alert_name: str) -> dict:
    s = load_settings()
    if alert_name not in s["alerts"]:
        return {"error": f"Unknown alert: {alert_name}"}
    s["alerts"][alert_name] = not s["alerts"][alert_name]
    save_settings(s)
    return {"alert": alert_name, "enabled": s["alerts"][alert_name]}


# ══════════════════════════════════════════════════════════════════════════════
# ALERT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _push(alert_type: str, title: str, body: str, priority: str = "normal"):
    """Push an alert onto the SSE queue."""
    alert = {
        "type":      alert_type,
        "title":     title,
        "body":      body,
        "priority":  priority,
        "timestamp": datetime.datetime.now().strftime("%H:%M"),
    }
    try:
        alert_queue.put_nowait(alert)
    except queue.Full:
        pass  # Drop oldest alert if queue is full


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL MONITORS
# ══════════════════════════════════════════════════════════════════════════════

def _check_urgent_emails():
    """Alert on new emails marked high importance or from manager."""
    try:
        from tools.ms365 import get_emails
        from tools.memory import load_memory

        emails = get_emails(folder="inbox", max_count=10, unread_only=True)
        mem    = load_memory()

        # Find manager names/emails from memory
        manager_names = set()
        for name, info in mem.get("people", {}).items():
            if isinstance(info, dict) and info.get("role") == "manager":
                manager_names.add(name.lower())
                if info.get("email"):
                    manager_names.add(info["email"].lower())

        for email in emails:
            eid = email.get("id", "")
            if eid in _seen["email_ids"]:
                continue

            importance  = email.get("importance", "").lower()
            sender_name = email.get("from", "").lower()
            subject     = email.get("subject", "(no subject)")

            if importance == "high" or any(m in sender_name for m in manager_names):
                priority = "high" if importance == "high" else "normal"
                _push(
                    "urgent_email",
                    f"📧 {'Urgent' if importance == 'high' else 'Manager'} email",
                    f"From: {email.get('from', '?')}\nSubject: {subject}",
                    priority,
                )
                _seen["email_ids"].add(eid)

    except Exception:
        pass


def _check_pr_reviews():
    """Alert when new PRs need review."""
    try:
        from tools.github_tool import get_my_review_requests

        prs = get_my_review_requests(max_count=10)
        for pr in prs:
            pr_id = str(pr.get("number", "")) + pr.get("repo", "")
            if pr_id in _seen["pr_ids"]:
                continue

            days_open = ""
            if pr.get("created_at"):
                try:
                    created = datetime.datetime.fromisoformat(
                        pr["created_at"].replace("Z", "+00:00")
                    )
                    days = (datetime.datetime.now(datetime.timezone.utc) - created).days
                    days_open = f" (open {days}d)" if days > 0 else ""
                except Exception:
                    pass

            _push(
                "pr_review",
                f"👀 PR needs your review{days_open}",
                f"#{pr.get('number')} in {pr.get('repo', '?')}\n{pr.get('title', '')}",
            )
            _seen["pr_ids"].add(pr_id)

    except Exception:
        pass


def _check_ci_failures():
    """Alert on CI failures across watched repos."""
    try:
        from tools.github_tool import list_my_repos, get_repo_workflow_runs

        repos = list_my_repos(max_count=5)
        for repo in repos:
            repo_name = repo.get("full_name", "")
            if not repo_name:
                continue

            runs = get_repo_workflow_runs(repo=repo_name, max_count=3)
            for run in runs:
                run_id  = str(run.get("id", ""))
                status  = run.get("conclusion", "")
                branch  = run.get("head_branch", "")

                if status == "failure" and run_id not in _seen["run_ids"]:
                    _push(
                        "ci_failure",
                        f"🚨 CI failed on {branch}",
                        f"Repo: {repo_name}\nWorkflow: {run.get('name', '?')}\n"
                        f"Commit: {run.get('head_commit_message', '')[:60]}",
                        "high",
                    )
                    _seen["run_ids"].add(run_id)

    except Exception:
        pass


def _check_meeting_reminders():
    """Alert when a meeting is starting within 10 minutes."""
    try:
        from tools.ms365 import get_calendar_events

        events = get_calendar_events(days_ahead=1)
        now    = datetime.datetime.now(datetime.timezone.utc)

        for event in events:
            eid   = event.get("id", "")
            start = event.get("start")
            if not start:
                continue

            try:
                start_dt = datetime.datetime.fromisoformat(
                    start.replace("Z", "+00:00")
                )
            except Exception:
                continue

            minutes_until = (start_dt - now).total_seconds() / 60

            if 0 < minutes_until <= 10 and eid not in _seen["meeting_ids"]:
                _push(
                    "meeting_reminder",
                    f"📅 Meeting in {int(minutes_until)} min",
                    f"{event.get('subject', 'Meeting')}\n"
                    f"At: {start_dt.strftime('%H:%M')}",
                )
                _seen["meeting_ids"].add(eid)

    except Exception:
        pass


def _check_linear_blocked():
    """Alert when one of your Linear issues becomes Blocked."""
    try:
        from tools.linear_tool import get_my_linear_issues

        issues = get_my_linear_issues(state_type="started", max_count=20)
        for issue in issues:
            issue_id = issue.get("id", "")
            state    = (issue.get("state") or {}).get("name", "").lower()

            if "blocked" in state and issue_id not in _seen["linear_ids"]:
                _push(
                    "linear_blocked",
                    "⛔ Linear issue blocked",
                    f"{issue.get('identifier', '?')}: {issue.get('title', '')}",
                    "high",
                )
                _seen["linear_ids"].add(issue_id)

    except Exception:
        pass


def _check_jira_overdue():
    """Alert on Jira issues that are past their due date."""
    try:
        from tools.atlassian import search_jira

        today = datetime.date.today().isoformat()
        jql   = f"assignee = currentUser() AND duedate < '{today}' AND status != Done"
        issues = search_jira(jql=jql, max_results=5)

        for issue in issues:
            issue_id = issue.get("key", "")
            if issue_id in _seen["jira_ids"]:
                continue

            _push(
                "jira_overdue",
                "⏰ Jira issue overdue",
                f"{issue_id}: {issue.get('summary', '')}\n"
                f"Due: {issue.get('duedate', '?')}",
                "high",
            )
            _seen["jira_ids"].add(issue_id)

    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# POLL LOOP
# ══════════════════════════════════════════════════════════════════════════════

def _poll_once():
    """Run all enabled monitors once."""
    settings = load_settings()
    if not settings.get("enabled"):
        return

    alerts = settings.get("alerts", {})

    if alerts.get("urgent_email"):     _check_urgent_emails()
    if alerts.get("pr_review"):        _check_pr_reviews()
    if alerts.get("ci_failure"):       _check_ci_failures()
    if alerts.get("meeting_reminder"): _check_meeting_reminders()
    if alerts.get("linear_blocked"):   _check_linear_blocked()
    if alerts.get("jira_overdue"):     _check_jira_overdue()


def _background_loop():
    """Main background thread loop."""
    # Wait 30 seconds after startup before first check (give APIs time to be ready)
    time.sleep(30)

    while not _stop_event.is_set():
        try:
            _poll_once()
        except Exception:
            pass

        settings = load_settings()
        interval = settings.get("poll_interval_sec", 300)

        # Sleep in 5-second increments so we can respond to stop_event quickly
        for _ in range(interval // 5):
            if _stop_event.is_set():
                break
            time.sleep(5)


# ══════════════════════════════════════════════════════════════════════════════
# START / STOP
# ══════════════════════════════════════════════════════════════════════════════

def start_monitoring():
    """Start the background monitoring thread. Safe to call multiple times."""
    global _thread
    if _thread and _thread.is_alive():
        return  # Already running

    _stop_event.clear()
    _thread = threading.Thread(target=_background_loop, daemon=True, name="proactive-monitor")
    _thread.start()


def stop_monitoring():
    """Signal the background thread to stop."""
    _stop_event.set()


def get_status() -> dict:
    s = load_settings()
    return {
        "running":       _thread is not None and _thread.is_alive(),
        "enabled":       s.get("enabled", True),
        "poll_interval": s.get("poll_interval_sec", 300),
        "alerts":        s.get("alerts", {}),
    }
