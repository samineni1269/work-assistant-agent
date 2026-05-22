"""
briefing.py — Daily Work Briefing
===================================
Compiles and sends an HTML email briefing every morning (or on demand).
Aggregates: calendar events, unread emails, GitHub PRs/issues, and open action items.

Usage (on-demand):
    from tools.briefing import send_morning_briefing
    result = send_morning_briefing()

Scheduled (via APScheduler — run once at startup in app.py):
    from tools.briefing import start_briefing_scheduler
    start_briefing_scheduler()

Environment variables:
    BRIEFING_EMAIL   — recipient address (defaults to TARGET_EMAIL or BRIEFING_RECIPIENT)
    BRIEFING_HOUR    — UTC hour to send (default: 8)
    BRIEFING_MINUTE  — UTC minute (default: 0)
"""

import os
import datetime
import traceback
from typing import Optional


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _env_email() -> str:
    """Return the target briefing email from env vars."""
    return (
        os.getenv("BRIEFING_EMAIL")
        or os.getenv("TARGET_EMAIL")
        or os.getenv("BRIEFING_RECIPIENT", "")
    )


def _safe(fn, default=None):
    """Call fn(), return default on any exception (keeps briefing partial on tool failures)."""
    try:
        return fn()
    except Exception as e:
        return default


# ─────────────────────────────────────────────
# DATA GATHERING
# ─────────────────────────────────────────────

def _gather_data() -> dict:
    """
    Pull all data sections for the briefing.
    Each section is gathered independently so one failure doesn't kill the whole briefing.
    """
    data = {}

    # Calendar events for today
    def _calendar():
        from tools.ms365 import get_calendar_events
        return get_calendar_events(days_ahead=1)

    data["calendar"] = _safe(_calendar, [])

    # Unread emails (top 10)
    def _emails():
        from tools.ms365 import get_emails
        return get_emails(folder="inbox", max_count=10, unread_only=True)

    data["emails"] = _safe(_emails, [])

    # Open action items (high priority first)
    def _actions():
        from tools.action_items import get_my_action_items
        return get_my_action_items(status="open", max_count=15)

    data["action_items"] = _safe(_actions, [])

    # GitHub PRs needing review / open by me
    def _prs():
        from tools.github_tool import get_my_open_prs
        return get_my_open_prs(max_count=10)

    data["prs"] = _safe(_prs, [])

    # GitHub notifications
    def _notifs():
        from tools.github_tool import get_github_notifications
        return get_github_notifications(max_count=10)

    data["github_notifs"] = _safe(_notifs, [])

    return data


# ─────────────────────────────────────────────
# HTML RENDERING
# ─────────────────────────────────────────────

_CSS = """
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f4f6f9; margin: 0; padding: 20px; color: #1a1a2e; }
  .container { max-width: 680px; margin: 0 auto; }
  .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 28px 32px; border-radius: 12px 12px 0 0; }
  .header h1 { margin: 0; font-size: 24px; font-weight: 700; }
  .header p  { margin: 6px 0 0; opacity: 0.85; font-size: 14px; }
  .body { background: white; padding: 24px 32px; border-radius: 0 0 12px 12px;
          box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
  .section { margin-bottom: 28px; }
  .section-title { font-size: 16px; font-weight: 700; color: #4a4a8a;
                   border-bottom: 2px solid #e8eaf0; padding-bottom: 8px; margin-bottom: 14px; }
  .item { padding: 10px 14px; background: #f9fafb; border-radius: 8px;
          margin-bottom: 8px; border-left: 3px solid #667eea; }
  .item.urgent  { border-left-color: #e53e3e; background: #fff5f5; }
  .item.high    { border-left-color: #dd6b20; background: #fffaf0; }
  .item.medium  { border-left-color: #d69e2e; background: #fffff0; }
  .item.low     { border-left-color: #38a169; background: #f0fff4; }
  .item-title   { font-weight: 600; font-size: 14px; color: #1a1a2e; margin-bottom: 3px; }
  .item-meta    { font-size: 12px; color: #666; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 20px;
           font-size: 11px; font-weight: 600; margin-left: 6px; }
  .badge-red  { background: #fed7d7; color: #c53030; }
  .badge-orange { background: #feebc8; color: #c05621; }
  .badge-blue { background: #bee3f8; color: #2b6cb0; }
  .badge-green{ background: #c6f6d5; color: #276749; }
  .empty { color: #999; font-size: 13px; font-style: italic; padding: 8px 0; }
  .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #999; }
  a { color: #667eea; text-decoration: none; }
</style>
"""


def _render_html(data: dict) -> str:
    now = datetime.datetime.utcnow()
    date_str = now.strftime("%A, %B %-d %Y")  # e.g. "Monday, June 2 2025"
    time_str = now.strftime("%H:%M UTC")

    sections = []

    # ── Calendar ──
    cal = data.get("calendar", [])
    rows = ""
    if cal:
        for ev in cal[:8]:
            subj = ev.get("subject", "No title")
            start = (ev.get("start") or {}).get("dateTime", "")[:16].replace("T", " ")
            end   = (ev.get("end") or {}).get("dateTime", "")[:16].replace("T", " ")
            loc   = ev.get("location", {}).get("displayName", "") if isinstance(ev.get("location"), dict) else ""
            online = "🎥 Teams" if ev.get("isOnlineMeeting") else (f"📍 {loc}" if loc else "")
            rows += f"""
            <div class="item">
              <div class="item-title">📅 {subj}</div>
              <div class="item-meta">{start} → {end[-5:]} &nbsp;{online}</div>
            </div>"""
    else:
        rows = '<div class="empty">No meetings today 🎉</div>'
    sections.append(f'<div class="section"><div class="section-title">📅 Today\'s Calendar</div>{rows}</div>')

    # ── Unread Emails ──
    emails = data.get("emails", [])
    rows = ""
    if emails:
        for em in emails[:8]:
            subj = em.get("subject", "(no subject)")
            frm  = (em.get("from") or {}).get("emailAddress", {}).get("name", "Unknown")
            preview = em.get("bodyPreview", "")[:100]
            rows += f"""
            <div class="item">
              <div class="item-title">✉️ {subj}</div>
              <div class="item-meta">From: <strong>{frm}</strong> — {preview}</div>
            </div>"""
    else:
        rows = '<div class="empty">Inbox zero! No unread emails.</div>'
    sections.append(f'<div class="section"><div class="section-title">✉️ Unread Emails ({len(emails)})</div>{rows}</div>')

    # ── Action Items ──
    actions = data.get("action_items", [])
    rows = ""
    if actions:
        for a in actions[:10]:
            task     = a.get("task", "")
            priority = a.get("priority", "medium")
            due      = a.get("due_date", "")
            source   = a.get("source", "")
            due_tag  = f" · due {due}" if due else ""
            src_tag  = f" · {source}" if source else ""
            badge_cls = {"high": "badge-orange", "low": "badge-green"}.get(priority, "badge-blue")
            rows += f"""
            <div class="item {priority}">
              <div class="item-title">{task}
                <span class="badge {badge_cls}">{priority}</span>
              </div>
              <div class="item-meta">{due_tag}{src_tag}</div>
            </div>"""
    else:
        rows = '<div class="empty">No open action items.</div>'
    sections.append(f'<div class="section"><div class="section-title">✅ Open Action Items ({len(actions)})</div>{rows}</div>')

    # ── GitHub PRs ──
    prs = data.get("prs", [])
    rows = ""
    if prs:
        for pr in prs[:8]:
            title  = pr.get("title", "Untitled PR")
            repo   = pr.get("repository_url", "").split("/")[-1] if pr.get("repository_url") else pr.get("repo", "")
            url    = pr.get("html_url", pr.get("url", ""))
            number = pr.get("number", "")
            link   = f'<a href="{url}">#{number}</a>' if url else f"#{number}"
            rows += f"""
            <div class="item">
              <div class="item-title">🔀 {link} {title}</div>
              <div class="item-meta">{repo}</div>
            </div>"""
    else:
        rows = '<div class="empty">No open PRs.</div>'
    sections.append(f'<div class="section"><div class="section-title">🔀 My Open PRs ({len(prs)})</div>{rows}</div>')

    # ── GitHub Notifications ──
    notifs = data.get("github_notifs", [])
    rows = ""
    if notifs:
        for n in notifs[:8]:
            title  = n.get("subject", {}).get("title", "Notification") if isinstance(n.get("subject"), dict) else str(n.get("subject", ""))
            ntype  = n.get("subject", {}).get("type", "") if isinstance(n.get("subject"), dict) else ""
            repo   = n.get("repository", {}).get("full_name", "") if isinstance(n.get("repository"), dict) else ""
            rows += f"""
            <div class="item">
              <div class="item-title">🔔 {title}</div>
              <div class="item-meta">{repo} · {ntype}</div>
            </div>"""
    else:
        rows = '<div class="empty">No new GitHub notifications.</div>'
    sections.append(f'<div class="section"><div class="section-title">🔔 GitHub Notifications ({len(notifs)})</div>{rows}</div>')

    body_html = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">{_CSS}</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🌅 Good Morning, Daily Briefing</h1>
      <p>{date_str} &nbsp;·&nbsp; Generated at {time_str}</p>
    </div>
    <div class="body">
      {body_html}
    </div>
    <div class="footer">Sent by your Work Assistant Agent · <a href="http://localhost:7432">Open Dashboard</a></div>
  </div>
</body>
</html>"""


# ─────────────────────────────────────────────
# SEND
# ─────────────────────────────────────────────

def send_morning_briefing(recipient: str = None) -> dict:
    """
    Compile and send the daily briefing email.

    Args:
        recipient: Override email address (defaults to BRIEFING_EMAIL env var)

    Returns:
        {"status": "sent"|"error", "to": ..., "sections": [...], "message": ...}
    """
    to = recipient or _env_email()
    if not to:
        return {
            "status": "error",
            "message": (
                "No recipient email set. Add BRIEFING_EMAIL=your@email.com to .env, "
                "or pass recipient= to send_morning_briefing()."
            ),
        }

    try:
        data = _gather_data()
        html = _render_html(data)
        subject = f"🌅 Daily Briefing — {datetime.datetime.utcnow().strftime('%A %b %-d')}"

        from tools.ms365 import _graph
        _graph(
            "POST",
            "/me/sendMail",
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "HTML", "content": html},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                "saveToSentItems": True,
            },
        )

        sections_summary = {
            "calendar":     len(data.get("calendar", [])),
            "emails":       len(data.get("emails", [])),
            "action_items": len(data.get("action_items", [])),
            "prs":          len(data.get("prs", [])),
            "notifications": len(data.get("github_notifs", [])),
        }

        return {
            "status":   "sent",
            "to":       to,
            "subject":  subject,
            "sections": sections_summary,
        }

    except Exception as e:
        return {
            "status":  "error",
            "to":      to,
            "message": str(e),
            "trace":   traceback.format_exc()[-500:],
        }


# ─────────────────────────────────────────────
# SCHEDULER — APScheduler-based (optional)
# ─────────────────────────────────────────────

_scheduler = None


def start_briefing_scheduler(recipient: str = None) -> dict:
    """
    Start a background APScheduler job to send the briefing every morning.

    Reads BRIEFING_HOUR (default 8) and BRIEFING_MINUTE (default 0) from env.
    Safe to call multiple times — only starts once.

    Returns:
        {"status": "started"|"already_running"|"error", ...}
    """
    global _scheduler

    if _scheduler and _scheduler.running:
        return {"status": "already_running"}

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return {
            "status": "error",
            "message": "APScheduler not installed. Run: pip install apscheduler",
        }

    hour   = int(os.getenv("BRIEFING_HOUR", "8"))
    minute = int(os.getenv("BRIEFING_MINUTE", "0"))
    to     = recipient or _env_email()

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        func=lambda: send_morning_briefing(to),
        trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        id="daily_briefing",
        name="Daily Work Briefing",
        replace_existing=True,
    )
    _scheduler.start()

    return {
        "status":   "started",
        "schedule": f"Daily at {hour:02d}:{minute:02d} UTC",
        "recipient": to or "(not set)",
    }


def stop_briefing_scheduler() -> dict:
    """Stop the background briefing scheduler."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        return {"status": "stopped"}
    return {"status": "not_running"}
