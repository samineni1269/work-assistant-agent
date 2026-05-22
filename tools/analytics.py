"""
tools/analytics.py — Work Pattern Analytics
=============================================
Logs every agent interaction and surfaces insights about how you work.

Tracks:
  • Which tools are called most (your biggest time-savers)
  • Which categories you use most (email vs code vs tickets)
  • Busiest hours of the day
  • Avg response time per tool
  • Weekly summary

Storage: analytics.jsonl (one JSON record per line) + summary cache
"""

import json
import datetime
import time
from pathlib import Path
from collections import defaultdict
from typing import Optional

_BASE         = Path(__file__).parent.parent
LOG_FILE      = _BASE / "analytics.jsonl"
SUMMARY_FILE  = _BASE / "analytics_summary.json"


# Tool → category mapping
TOOL_CATEGORIES = {
    # Email / Calendar
    "get_emails": "email", "get_email_body": "email", "send_email": "email",
    "search_emails": "email", "get_calendar_events": "calendar",
    "create_calendar_event": "calendar",
    # Teams
    "get_teams_chats": "teams", "get_chat_messages": "teams",
    "send_teams_message": "teams", "post_channel_message": "teams",
    "list_teams": "teams", "get_channel_messages": "teams",
    # GitHub
    "get_github_notifications": "github", "get_my_review_requests": "github",
    "list_pull_requests": "github", "get_pull_request": "github",
    "get_pr_checks": "github", "create_github_issue": "github",
    "merge_pull_request": "github", "add_pr_review": "github",
    "list_my_repos": "github", "get_repo_workflow_runs": "github",
    # Jira / Linear
    "get_my_jira_issues": "tickets", "search_jira": "tickets",
    "create_jira_issue": "tickets", "transition_jira_issue": "tickets",
    "add_jira_comment": "tickets", "update_jira_issue": "tickets",
    "get_my_linear_issues": "tickets", "search_linear_issues": "tickets",
    "create_linear_issue": "tickets", "transition_linear_issue": "tickets",
    # Docs / Files
    "search_sharepoint": "files", "list_sharepoint_files": "files",
    "read_excel_sheet": "docs", "write_excel_cell": "docs",
    "read_word_document": "docs", "create_word_document": "docs",
    "read_presentation": "docs", "create_presentation": "docs",
    # Knowledge
    "search_knowledge_base": "knowledge",
    "browse_url": "browser",
    # Memory
    "update_memory_entry": "memory", "get_memory_summary": "memory",
}


# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def log_interaction(
    user_message: str,
    tools_called: list[str],
    response_time_ms: int,
    success: bool = True,
):
    """
    Record one agent turn to the log file.
    Call this at the end of every run_agent_turn().
    """
    record = {
        "ts":             datetime.datetime.now().isoformat(),
        "hour":           datetime.datetime.now().hour,
        "weekday":        datetime.datetime.now().strftime("%A"),
        "tools":          tools_called,
        "categories":     list({TOOL_CATEGORIES.get(t, "other") for t in tools_called}),
        "tool_count":     len(tools_called),
        "response_ms":    response_time_ms,
        "success":        success,
        "message_len":    len(user_message),
    }
    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

    # Invalidate cached summary so it gets rebuilt on next request
    try:
        if SUMMARY_FILE.exists():
            SUMMARY_FILE.unlink()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def _load_log(days_back: int = 30) -> list[dict]:
    """Load log records from the last N days."""
    if not LOG_FILE.exists():
        return []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days_back)
    records = []
    try:
        with open(LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    ts = datetime.datetime.fromisoformat(r["ts"])
                    if ts >= cutoff:
                        records.append(r)
                except Exception:
                    pass
    except Exception:
        pass
    return records


def get_analytics_summary(days_back: int = 7) -> dict:
    """
    Agent-callable: return a human-readable analytics summary.
    Also used by the /analytics route in app.py.
    """
    # Use cached summary if fresh (< 5 minutes old)
    if SUMMARY_FILE.exists():
        try:
            cached = json.loads(SUMMARY_FILE.read_text())
            age_sec = (datetime.datetime.now() -
                       datetime.datetime.fromisoformat(cached["generated_at"])).total_seconds()
            if age_sec < 300:
                return cached
        except Exception:
            pass

    records = _load_log(days_back)

    if not records:
        return {
            "total_turns":    0,
            "message":        f"No data yet for the last {days_back} days.",
            "generated_at":   datetime.datetime.now().isoformat(),
        }

    # ── Aggregations ──────────────────────────────────────────────────────────
    tool_counts     = defaultdict(int)
    category_counts = defaultdict(int)
    hour_counts     = defaultdict(int)
    weekday_counts  = defaultdict(int)
    total_ms        = 0
    total_tools     = 0

    for r in records:
        for t in r.get("tools", []):
            tool_counts[t] += 1
            total_tools += 1
        for c in r.get("categories", []):
            category_counts[c] += 1
        hour_counts[r.get("hour", 0)] += 1
        weekday_counts[r.get("weekday", "?")] += 1
        total_ms += r.get("response_ms", 0)

    top_tools      = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
    top_categories = sorted(category_counts.items(), key=lambda x: -x[1])[:5]
    peak_hour      = max(hour_counts.items(), key=lambda x: x[1])[0] if hour_counts else 0
    busiest_day    = max(weekday_counts.items(), key=lambda x: x[1])[0] if weekday_counts else "?"
    avg_ms         = int(total_ms / len(records)) if records else 0

    # ── Human-readable insight sentences ─────────────────────────────────────
    insights = []
    if top_categories:
        top_cat = top_categories[0][0]
        insights.append(f"You use **{top_cat}** most — {top_categories[0][1]} requests this week.")
    if peak_hour is not None:
        am_pm = "am" if peak_hour < 12 else "pm"
        hour_12 = peak_hour if peak_hour <= 12 else peak_hour - 12
        insights.append(f"Your busiest hour is **{hour_12}{am_pm}**.")
    insights.append(f"Busiest day: **{busiest_day}**.")
    if avg_ms > 0:
        insights.append(f"Average response time: **{avg_ms // 1000}s**.")

    summary = {
        "days_back":        days_back,
        "total_turns":      len(records),
        "total_tool_calls": total_tools,
        "top_tools":        [{"tool": t, "count": c} for t, c in top_tools],
        "top_categories":   [{"category": c, "count": n} for c, n in top_categories],
        "peak_hour":        peak_hour,
        "busiest_day":      busiest_day,
        "avg_response_ms":  avg_ms,
        "insights":         insights,
        "hourly_breakdown": dict(hour_counts),
        "category_breakdown": dict(category_counts),
        "generated_at":     datetime.datetime.now().isoformat(),
    }

    try:
        SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    except Exception:
        pass

    return summary


# ══════════════════════════════════════════════════════════════════════════════
# TIMER CONTEXT MANAGER — measure how long a turn takes
# ══════════════════════════════════════════════════════════════════════════════

class TurnTimer:
    """
    Use as a context manager to time agent turns:

        with TurnTimer() as t:
            run_agent_turn(...)
        elapsed_ms = t.elapsed_ms
    """
    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = int((time.monotonic() - self._start) * 1000)

    @property
    def elapsed_ms(self):
        return getattr(self, "_elapsed_ms", 0)

    @elapsed_ms.setter
    def elapsed_ms(self, v):
        self._elapsed_ms = v
