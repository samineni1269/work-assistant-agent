"""
tools/auto_ingest.py — Auto Knowledge Base Population + Continuous Tone Learning
==================================================================================
Feature 7 — Auto KB Population (every 6h):
  • ingest_starred_emails()   — high-importance Outlook emails → RAG KB
  • ingest_slack_reactions()  — starred/bookmarked Slack messages → RAG KB
  • ingest_github_readmes()   — README.md from own GitHub repos → RAG KB
  • run_auto_ingest()         — calls all three, returns summary dict

Feature 8 — Continuous Tone Learning (every 3h):
  • ingest_sent_emails_for_tone() — sent emails → tone learner

Deduplication via SHA-1 hashes stored in seen_ingested.json.
Scheduler: APScheduler (BlockingScheduler or BackgroundScheduler).
"""

import hashlib
import json
import re
from pathlib import Path

# ── Deduplication file ────────────────────────────────────────────────────────
SEEN_FILE = Path(__file__).parent.parent / "seen_ingested.json"


# ══════════════════════════════════════════════════════════════════════════════
# DEDUPLICATION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _hash(text: str) -> str:
    """Return first 16 chars of the SHA-1 hex digest of *text*."""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _load_seen() -> list:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text())
        except Exception:
            pass
    return []


def _save_seen(hashes: list):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(set(hashes)), indent=2))


def _already_seen(hash_val: str) -> bool:
    """Return True if *hash_val* has already been ingested."""
    return hash_val in _load_seen()


def _mark_seen(hash_val: str):
    """Persist *hash_val* so it is skipped in future runs."""
    hashes = _load_seen()
    if hash_val not in hashes:
        hashes.append(hash_val)
    _save_seen(hashes)


# ══════════════════════════════════════════════════════════════════════════════
# TONE SNIPPET EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _extract_tone_snippet(email_body: str) -> str:
    """
    Strip quoted reply lines (starting with '>') and reply-header lines
    (starting with 'On ') from an email body. Returns the cleaned text.
    """
    lines = email_body.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        if stripped.startswith("On ") and stripped.endswith(":"):
            continue
        # Also drop lines that are purely the "On ... wrote:" pattern
        if re.match(r"^On .+ wrote:$", stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


# ══════════════════════════════════════════════════════════════════════════════
# LAZY IMPORTS — wrapped so the module loads even without credentials
# ══════════════════════════════════════════════════════════════════════════════

def _get_ms365():
    try:
        import tools.ms365 as ms365
        return ms365
    except Exception:
        return None


def _get_slack():
    try:
        import tools.slack_tool as slack_tool
        return slack_tool
    except Exception:
        return None


def _get_github():
    try:
        import tools.github_tool as github_tool
        return github_tool
    except Exception:
        return None


def _get_rag():
    try:
        import tools.rag as rag
        return rag
    except Exception:
        return None


def _get_tone_learner():
    try:
        import tools.tone_learner as tone_learner
        return tone_learner
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 7 — AUTO KB POPULATION
# ══════════════════════════════════════════════════════════════════════════════

def ingest_starred_emails(max_items: int = 10) -> int:
    """
    Fetch high-importance / starred emails from Outlook and add them to the
    RAG knowledge base. Returns the number of newly ingested items.
    """
    ms365 = _get_ms365()
    rag = _get_rag()
    if ms365 is None or rag is None:
        return 0

    added = 0
    try:
        # get_emails returns a list of dicts with 'subject', 'body', 'from', etc.
        emails = ms365.get_emails(max_count=max_items, importance="high")
        if not isinstance(emails, list):
            emails = []
        for email in emails[:max_items]:
            subject = email.get("subject", "")
            body = email.get("body", "") or email.get("body_preview", "")
            content = f"Subject: {subject}\n\n{body}".strip()
            if not content:
                continue
            h = _hash(content)
            if _already_seen(h):
                continue
            try:
                rag.add_text(content, source_label=f"email:{subject[:60]}")
                _mark_seen(h)
                added += 1
            except Exception:
                pass
    except Exception:
        pass
    return added


def ingest_slack_reactions(max_items: int = 20) -> int:
    """
    Fetch Slack messages that have star/bookmark reactions and add them to the
    RAG knowledge base. Returns the number of newly ingested items.
    """
    slack_tool = _get_slack()
    rag = _get_rag()
    if slack_tool is None or rag is None:
        return 0

    added = 0
    try:
        # search_slack returns a list of message dicts with 'text', 'channel', etc.
        results = slack_tool.search_slack(query="has:star", max_results=max_items)
        messages = results if isinstance(results, list) else results.get("messages", [])
        for msg in messages[:max_items]:
            text = msg.get("text", "") or msg.get("message", {}).get("text", "")
            channel = msg.get("channel", {})
            channel_name = channel.get("name", "slack") if isinstance(channel, dict) else str(channel)
            content = text.strip()
            if not content:
                continue
            h = _hash(content)
            if _already_seen(h):
                continue
            try:
                rag.add_text(content, source_label=f"slack:{channel_name}")
                _mark_seen(h)
                added += 1
            except Exception:
                pass
    except Exception:
        pass
    return added


def ingest_github_readmes(max_repos: int = 10) -> int:
    """
    Fetch README.md from the authenticated user's own GitHub repos and add
    them to the RAG knowledge base. Returns the number of newly ingested items.
    """
    github_tool = _get_github()
    rag = _get_rag()
    if github_tool is None or rag is None:
        return 0

    added = 0
    try:
        repos = github_tool.list_my_repos(max_count=max_repos)
        if not isinstance(repos, list):
            repos = []
        for repo in repos[:max_repos]:
            repo_name = repo.get("full_name") or repo.get("name", "")
            if not repo_name:
                continue
            try:
                readme_data = github_tool._gh("GET", f"/repos/{repo_name}/readme")
                import base64
                content_b64 = readme_data.get("content", "")
                readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace").strip()
            except Exception:
                continue
            if not readme_text:
                continue
            h = _hash(readme_text)
            if _already_seen(h):
                continue
            try:
                rag.add_text(readme_text, source_label=f"github:{repo_name}")
                _mark_seen(h)
                added += 1
            except Exception:
                pass
    except Exception:
        pass
    return added


def run_auto_ingest() -> dict:
    """
    Run all three KB ingest functions and return a summary dict.
    Called every 6 hours by the scheduler.
    """
    emails_added = ingest_starred_emails()
    slack_added = ingest_slack_reactions()
    github_added = ingest_github_readmes()
    return {
        "emails_added": emails_added,
        "slack_added": slack_added,
        "github_added": github_added,
        "total_added": emails_added + slack_added + github_added,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 8 — CONTINUOUS TONE LEARNING
# ══════════════════════════════════════════════════════════════════════════════

def ingest_sent_emails_for_tone(max_items: int = 10) -> int:
    """
    Fetch recently sent emails, extract the personal writing snippet (stripping
    quoted replies), and feed each snippet to the tone learner.
    Returns the number of newly ingested samples.
    """
    ms365 = _get_ms365()
    tone_learner = _get_tone_learner()
    if ms365 is None or tone_learner is None:
        return 0

    added = 0
    try:
        sent = ms365.get_sent_emails(max_count=max_items)
        if not isinstance(sent, list):
            sent = []
        for email in sent[:max_items]:
            body = email.get("body", "") or email.get("body_preview", "")
            snippet = _extract_tone_snippet(body)
            if len(snippet) < 20:
                continue
            h = _hash(snippet)
            if _already_seen(h):
                continue
            try:
                tone_learner.add_sample(snippet)
                _mark_seen(h)
                added += 1
            except Exception:
                pass
    except Exception:
        pass
    return added


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════════════════════════════════════════

_scheduler = None


def start_auto_ingest_scheduler():
    """
    Register APScheduler background jobs:
      • run_auto_ingest()          — every 6 hours
      • ingest_sent_emails_for_tone() — every 3 hours

    Safe to call multiple times — only starts the scheduler once.
    """
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        _scheduler = BackgroundScheduler()

        _scheduler.add_job(
            run_auto_ingest,
            trigger="interval",
            hours=6,
            id="auto_ingest_kb",
            replace_existing=True,
        )

        _scheduler.add_job(
            ingest_sent_emails_for_tone,
            trigger="interval",
            hours=3,
            id="auto_ingest_tone",
            replace_existing=True,
        )

        _scheduler.start()
        return _scheduler

    except Exception:
        return None
