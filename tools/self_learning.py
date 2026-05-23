"""
tools/self_learning.py — Behavioural Self-Learning
====================================================
State stored in self_learning.json (never commit — gitignored).
Atomic writes via temp-file rename.

Public API:
  record_tool_usage(query_category, tools_used)
  get_tool_order(user_message) -> list[str]
  record_tool_error(tool_name, error_type)
  clear_tool_errors(tool_name)
  should_skip_tool(tool_name) -> bool
  get_skipped_tools() -> list[str]
  record_app_open(hour=None)
  get_optimal_briefing_hour() -> int
  record_alert_action(alert_type, action)
  get_alert_priority(alert_type) -> str
  record_query(user_message)
  get_query_clusters() -> list[dict]
  set_cluster_shortcut(label, shortcut)
  update_semantic_profile(conversation_snippet, llm_extract_fn=None)
  get_semantic_profile() -> str
  get_full_state() -> dict
"""

import re
import json
import copy
import datetime
from collections import Counter
from pathlib import Path
from typing import Optional

SL_FILE = Path(__file__).parent.parent / "self_learning.json"

_EMPTY_STATE = {
    "tool_usage":       {},   # category → {tool_name: count}
    "tool_errors":      {},   # tool_name → {error_type: count}
    "app_opens":        {},   # "HH" → count
    "alert_feedback":   {},   # alert_type → {"dismissed": n, "acted": n}
    "query_log":        [],   # last 500 raw queries
    "query_clusters":   [],   # [{label, count, shortcut}]
    "semantic_profile": "",
    "updated_at":       None,
}

_CATEGORY_KEYWORDS = {
    "github":   ["github", "pr", "pull request", "commit", "repo", "ci", "workflow"],
    "email":    ["email", "mail", "inbox", "outlook", "gmail"],
    "calendar": ["meeting", "calendar", "schedule", "event", "standup"],
    "jira":     ["jira", "ticket", "issue", "sprint", "board"],
    "slack":    ["slack", "channel", "dm", "message"],
    "docs":     ["document", "word", "excel", "sharepoint", "file"],
}

_ERROR_SKIP_THRESHOLD = 3

_STOPWORDS = {
    "show", "me", "my", "the", "a", "an", "what", "is", "are", "can",
    "you", "please", "get", "list", "give", "all", "of",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> dict:
    """Load state from disk; return a deep copy of _EMPTY_STATE on any failure."""
    try:
        with open(SL_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        state = copy.deepcopy(_EMPTY_STATE)
        for key in _EMPTY_STATE:
            if key in data:
                state[key] = data[key]
        return state
    except Exception:
        return copy.deepcopy(_EMPTY_STATE)


def _save(state: dict) -> None:
    """Atomic write: write to .tmp then rename over the real file."""
    state["updated_at"] = datetime.datetime.utcnow().isoformat()
    tmp = SL_FILE.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    tmp.replace(SL_FILE)


def _classify_query(msg: str) -> str:
    """Return best-matching category from _CATEGORY_KEYWORDS, else 'general'."""
    lower = msg.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                return category
    return "general"


def _normalise(q: str) -> str:
    """Lowercase, remove punctuation, strip stopwords."""
    q = q.lower()
    q = re.sub(r"[^a-z0-9 ]", " ", q)
    tokens = [t for t in q.split() if t and t not in _STOPWORDS]
    return " ".join(tokens)


def _rebuild_clusters(state: dict) -> None:
    """Rebuild query_clusters from query_log — top 20 normalised queries with count >= 2."""
    normalised = [_normalise(q) for q in state["query_log"] if q.strip()]
    counts = Counter(normalised)
    # Preserve existing shortcuts
    existing_shortcuts = {
        c["label"]: c.get("shortcut") for c in state.get("query_clusters", [])
    }
    clusters = []
    for label, count in counts.most_common(20):
        if count < 2:
            break
        clusters.append({
            "label": label,
            "count": count,
            "shortcut": existing_shortcuts.get(label),
        })
    state["query_clusters"] = clusters


# ── F5: Tool Usage Weighting ──────────────────────────────────────────────────

def record_tool_usage(query_category: str, tools_used: list) -> None:
    """Track which tools were used for a query category."""
    state = _load()
    cat_map = state["tool_usage"].setdefault(query_category, {})
    for tool in tools_used:
        cat_map[tool] = cat_map.get(tool, 0) + 1
    _save(state)


def get_tool_order(user_message: str) -> list:
    """Return tools sorted by descending usage count for the classified category."""
    state = _load()
    category = _classify_query(user_message)
    cat_map = state["tool_usage"].get(category, {})
    return sorted(cat_map.keys(), key=lambda t: cat_map[t], reverse=True)


# ── F12: Error Pattern Avoidance ─────────────────────────────────────────────

def record_tool_error(tool_name: str, error_type: str) -> None:
    """Record a tool failure."""
    state = _load()
    tool_errs = state["tool_errors"].setdefault(tool_name, {})
    tool_errs[error_type] = tool_errs.get(error_type, 0) + 1
    _save(state)


def clear_tool_errors(tool_name: str) -> None:
    """Clear all recorded errors for a tool."""
    state = _load()
    state["tool_errors"].pop(tool_name, None)
    _save(state)


def should_skip_tool(tool_name: str) -> bool:
    """Return True if total errors for tool >= _ERROR_SKIP_THRESHOLD."""
    state = _load()
    errors = state["tool_errors"].get(tool_name, {})
    return sum(errors.values()) >= _ERROR_SKIP_THRESHOLD


def get_skipped_tools() -> list:
    """Return list of all tools currently above the error threshold."""
    state = _load()
    return [
        tool for tool, errors in state["tool_errors"].items()
        if sum(errors.values()) >= _ERROR_SKIP_THRESHOLD
    ]


# ── F4: Smart Briefing Timing ─────────────────────────────────────────────────

def record_app_open(hour: Optional[int] = None) -> None:
    """Record that the app was opened at a given hour (defaults to current hour)."""
    if hour is None:
        hour = datetime.datetime.now().hour
    state = _load()
    key = f"{hour:02d}"
    state["app_opens"][key] = state["app_opens"].get(key, 0) + 1
    _save(state)


def get_optimal_briefing_hour() -> int:
    """Return the hour with the most app-open events; fallback to 8."""
    state = _load()
    opens = state["app_opens"]
    if not opens:
        return 8
    best_key = max(opens, key=lambda k: opens[k])
    return int(best_key)


# ── F6: Proactive Alert Tuning ────────────────────────────────────────────────

def record_alert_action(alert_type: str, action: str) -> None:
    """Record user response to an alert. action should be 'acted' or 'dismissed'."""
    state = _load()
    feedback = state["alert_feedback"].setdefault(alert_type, {"dismissed": 0, "acted": 0})
    if action in feedback:
        feedback[action] += 1
    else:
        feedback[action] = 1
    _save(state)


def get_alert_priority(alert_type: str) -> str:
    """
    Return 'high' if acted_ratio >= 0.5, 'muted' if < 0.2, else 'normal'.
    Returns 'normal' if total < 5.
    """
    state = _load()
    feedback = state["alert_feedback"].get(alert_type, {})
    total = sum(feedback.values())
    if total < 5:
        return "normal"
    acted = feedback.get("acted", 0)
    ratio = acted / total
    if ratio >= 0.5:
        return "high"
    if ratio < 0.2:
        return "muted"
    return "normal"


# ── F10: Query Clustering ─────────────────────────────────────────────────────

def record_query(user_message: str) -> None:
    """Append query to log (capped at 500), then rebuild clusters."""
    state = _load()
    state["query_log"].append(user_message)
    if len(state["query_log"]) > 500:
        state["query_log"] = state["query_log"][-500:]
    _rebuild_clusters(state)
    _save(state)


def get_query_clusters() -> list:
    """Return the current list of query clusters."""
    state = _load()
    return state["query_clusters"]


def set_cluster_shortcut(label: str, shortcut: str) -> None:
    """Attach a shortcut string to an existing cluster label."""
    state = _load()
    for cluster in state["query_clusters"]:
        if cluster["label"] == label:
            cluster["shortcut"] = shortcut
            break
    _save(state)


# ── F11: Semantic User Profile ────────────────────────────────────────────────

def _extract_facts_regex(snippet: str) -> str:
    """Extract simple facts from a conversation snippet using regex heuristics."""
    facts = []
    # Look for "I use/prefer/work with X"
    for m in re.finditer(r"\bI (?:use|prefer|work with|am|work at|am on)\b[^.!?\n]{3,60}", snippet, re.I):
        facts.append(m.group(0).strip())
    # Look for "my X is Y"
    for m in re.finditer(r"\bmy \w+ is [^.!?\n]{2,40}", snippet, re.I):
        facts.append(m.group(0).strip())
    return "\n".join(facts)


def update_semantic_profile(conversation_snippet: str, llm_extract_fn=None) -> None:
    """
    Extract facts from conversation_snippet and append to semantic profile.
    Uses llm_extract_fn if provided, else falls back to regex extraction.
    Profile is capped at 3000 chars.
    """
    state = _load()
    if llm_extract_fn is not None:
        new_facts = llm_extract_fn(conversation_snippet)
    else:
        new_facts = _extract_facts_regex(conversation_snippet)

    if new_facts and new_facts.strip():
        existing = state["semantic_profile"]
        combined = (existing + "\n" + new_facts).strip() if existing else new_facts.strip()
        # Cap at 3000 chars, keeping the most recent content
        state["semantic_profile"] = combined[-3000:]
    _save(state)


def get_semantic_profile() -> str:
    """Return formatted profile, or empty string if none recorded."""
    state = _load()
    profile = state["semantic_profile"]
    if not profile or not profile.strip():
        return ""
    return "## What I know about you:\n" + profile


# ── Utility ───────────────────────────────────────────────────────────────────

def get_full_state() -> dict:
    """Return a deep copy of the full persisted state."""
    return _load()
