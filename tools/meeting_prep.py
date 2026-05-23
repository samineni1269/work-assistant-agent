"""
meeting_prep.py — Automatic Pre-Meeting Context Builder
=========================================================
Builds a Markdown brief for an upcoming meeting by pulling related emails,
Jira tickets, Slack messages, and Confluence pages.
"""

import re
import datetime
from typing import Optional

# ─────────────────────────────────────────────
# KEYWORD EXTRACTION
# ─────────────────────────────────────────────

_STOPWORDS = {
    "about", "meeting", "weekly", "daily", "review", "standup",
    "planning", "session", "discussion",
}


def extract_keywords(meeting_title: str) -> list[str]:
    """
    Extract up to 5 meaningful keywords from a meeting title.

    Rules:
    - Capture capitalised proper-noun phrases first (e.g. "Sarah", "Sprint Planning")
    - Also capture all words > 4 chars that are NOT stopwords
    - Deduplicate, preserve order, return first 5
    """
    seen: set[str] = set()
    keywords: list[str] = []

    def _add(word: str) -> None:
        if word not in seen:
            seen.add(word)
            keywords.append(word)

    # 1. Capitalised words / phrases (proper nouns, names)
    for phrase in re.findall(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b", meeting_title):
        _add(phrase)

    # 2. All words > 4 chars, excluding stopwords (case-insensitive check)
    for word in re.findall(r"\b[a-zA-Z]{5,}\b", meeting_title):
        if word.lower() not in _STOPWORDS:
            _add(word)

    return keywords[:5]


# ─────────────────────────────────────────────
# BRIEF BUILDER
# ─────────────────────────────────────────────

def build_meeting_brief(event: dict, max_items_per_source: int = 5) -> str:
    """
    Build a Markdown pre-meeting brief from calendar event data.

    Args:
        event: dict with keys: subject, start, end, attendees (list[str]), body
        max_items_per_source: max results to pull from each integration

    Returns:
        Markdown string
    """
    from tools import ms365, atlassian, slack_tool

    title = event.get("subject", "Untitled Meeting")
    keywords = extract_keywords(title)

    lines: list[str] = [f"## \U0001f4c5 Pre-meeting brief: {title}", ""]

    # Metadata
    lines.append(f"**Start:** {event.get('start', 'N/A')}  ")
    lines.append(f"**End:** {event.get('end', 'N/A')}  ")
    attendees = event.get("attendees", [])
    lines.append(f"**Attendees:** {', '.join(attendees) if attendees else 'None listed'}")
    lines.append("")

    found_any = False

    # ── 1. Emails ───────────────────────────────
    try:
        email_query = " OR ".join(keywords[:3]) if keywords else title
        emails = ms365.search_emails(query=email_query, max_count=max_items_per_source)
        lines.append("### \U0001f4e7 Related emails")
        if emails:
            found_any = True
            for e in emails:
                subject = e.get("subject", "(no subject)")
                sender = e.get("from", {}).get("emailAddress", {}).get("address", "unknown")
                received = e.get("receivedDateTime", "")[:10]
                preview = e.get("bodyPreview", "")[:120]
                lines.append(f"- **{subject}** — from {sender} ({received})")
                if preview:
                    lines.append(f"  > {preview}")
        else:
            lines.append("_No related emails found._")
        lines.append("")
    except Exception as exc:
        lines.append("### \U0001f4e7 Related emails")
        lines.append(f"_Could not retrieve emails: {exc}_")
        lines.append("")

    # ── 2. Jira ─────────────────────────────────
    try:
        if len(keywords) >= 2:
            jql = f'text ~ "{keywords[0]}" OR text ~ "{keywords[1]}"'
        elif keywords:
            jql = f'text ~ "{keywords[0]}"'
        else:
            jql = f'text ~ "{title}"'
        tickets = atlassian.search_jira(jql=jql, max_results=max_items_per_source)
        lines.append("### \U0001f3ab Related Jira tickets")
        if tickets:
            found_any = True
            for t in tickets:
                key = t.get("key", "")
                summary = t.get("fields", {}).get("summary", t.get("summary", "(no summary)"))
                status = t.get("fields", {}).get("status", {}).get("name", "") or t.get("status", "")
                lines.append(f"- **{key}** {summary}" + (f" [{status}]" if status else ""))
        else:
            lines.append("_No related Jira tickets found._")
        lines.append("")
    except Exception as exc:
        lines.append("### \U0001f3ab Related Jira tickets")
        lines.append(f"_Could not retrieve Jira tickets: {exc}_")
        lines.append("")

    # ── 3. Slack — per attendee ──────────────────
    for attendee in attendees[:3]:
        first_name = attendee.split()[0] if attendee.split() else attendee
        try:
            messages = slack_tool.search_slack(f"from:{first_name}", max_results=3)
            lines.append(f"### \U0001f4ac Recent Slack from {first_name}")
            if messages:
                found_any = True
                for m in messages:
                    channel = m.get("channel", "")
                    text = m.get("text", "")[:200]
                    dt = m.get("datetime", "")
                    lines.append(f"- [{channel}] {text}" + (f" _{dt}_" if dt else ""))
            else:
                lines.append(f"_No recent Slack messages from {first_name}._")
            lines.append("")
        except Exception as exc:
            lines.append(f"### \U0001f4ac Recent Slack from {first_name}")
            lines.append(f"_Could not retrieve Slack messages: {exc}_")
            lines.append("")

    # ── 4. Confluence ────────────────────────────
    try:
        conf_query = " ".join(keywords[:2]) if keywords else title
        pages = atlassian.search_confluence(query=conf_query, max_results=3)
        lines.append("### \U0001f4d6 Related Confluence pages")
        if pages:
            found_any = True
            for p in pages:
                page_title = p.get("title", "(untitled)")
                space = p.get("space", {}).get("name", p.get("space", ""))
                url = p.get("_links", {}).get("webui", p.get("url", ""))
                line = f"- **{page_title}**"
                if space:
                    line += f" ({space})"
                if url:
                    line += f" — {url}"
                lines.append(line)
        else:
            lines.append("_No related Confluence pages found._")
        lines.append("")
    except Exception as exc:
        lines.append("### \U0001f4d6 Related Confluence pages")
        lines.append(f"_Could not retrieve Confluence pages: {exc}_")
        lines.append("")

    # ── Fallback message ─────────────────────────
    if not found_any:
        lines.append(
            "_No related context found — all integrated tools returned empty results._"
        )

    return "\n".join(lines)


# ─────────────────────────────────────────────
# NEXT MEETING BRIEF
# ─────────────────────────────────────────────

def get_next_meeting_brief() -> str:
    """
    Find the next meeting starting within the next 2 hours and return its brief.

    Returns:
        Markdown brief string, or "" if no upcoming meeting found.
    """
    from tools import ms365

    try:
        events = ms365.get_calendar_events(days_ahead=1)
    except Exception:
        return ""

    now = datetime.datetime.now(datetime.timezone.utc)

    for event in events:
        start_raw = event.get("start", {})
        # Graph API returns {"dateTime": "...", "timeZone": "..."}
        if isinstance(start_raw, dict):
            start_str = start_raw.get("dateTime", "")
        else:
            start_str = str(start_raw)

        if not start_str:
            continue

        # Normalise timezone: replace trailing Z, add UTC if naive
        start_str = start_str.replace("Z", "+00:00")
        try:
            start_dt = datetime.datetime.fromisoformat(start_str)
        except ValueError:
            continue

        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)

        delta_seconds = (start_dt - now).total_seconds()
        if 0 <= delta_seconds <= 7200:
            # Normalise attendees: Graph returns list of dicts
            raw_attendees = event.get("attendees", [])
            attendees: list[str] = []
            for a in raw_attendees:
                if isinstance(a, dict):
                    name = (
                        a.get("emailAddress", {}).get("name", "")
                        or a.get("emailAddress", {}).get("address", "")
                    )
                    attendees.append(name)
                else:
                    attendees.append(str(a))

            normalised_event = {
                "subject": event.get("subject", ""),
                "start": start_str,
                "end": (
                    event.get("end", {}).get("dateTime", "")
                    if isinstance(event.get("end"), dict)
                    else str(event.get("end", ""))
                ),
                "attendees": attendees,
                "body": (
                    event.get("body", {}).get("content", "")
                    if isinstance(event.get("body"), dict)
                    else str(event.get("body", ""))
                ),
            }
            return build_meeting_brief(normalised_event)

    return ""
