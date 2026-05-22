"""
tools/memory.py — Long-Term Persistent Memory
==============================================
Remembers facts about the user across ALL sessions.
Stored in memory.json at project root — survives restarts.

Memory categories:
  preferences  — response style, timezone, language, working hours
  people       — colleagues: name → {role, email, notes}
  context      — current sprint, active projects, team name, company
  patterns     — observed work habits
  facts        — free-form key→value facts the agent learns

Usage:
  from tools.memory import get_memory_context, save_fact, extract_and_save_facts
"""

import copy
import re
import json
import datetime
from pathlib import Path
from typing import Any

MEMORY_FILE = Path(__file__).parent.parent / "memory.json"

_EMPTY = {
    "preferences": {},
    "people":      {},
    "context":     {},
    "patterns":    {},
    "facts":       {},
    "updated_at":  None,
}


# ══════════════════════════════════════════════════════════════════════════════
# LOAD / SAVE
# ══════════════════════════════════════════════════════════════════════════════

def load_memory() -> dict:
    """Load memory from disk. Returns empty schema if file missing/corrupt."""
    if MEMORY_FILE.exists():
        try:
            data = json.loads(MEMORY_FILE.read_text())
            # Ensure all categories exist (handles older memory files)
            for key in _EMPTY:
                data.setdefault(key, {} if key != "updated_at" else None)
            return data
        except Exception:
            pass
    return copy.deepcopy(_EMPTY)


def save_memory(mem: dict):
    """Persist memory to disk."""
    mem["updated_at"] = datetime.datetime.now().isoformat()
    MEMORY_FILE.write_text(json.dumps(mem, indent=2, ensure_ascii=False))


def save_fact(category: str, key: str, value: Any):
    """
    Store a single fact.

    Examples:
        save_fact("context", "current_sprint", "Sprint 14")
        save_fact("people",  "Ahmed", {"role": "manager", "email": "ahmed@co.com"})
        save_fact("preferences", "response_style", "concise bullet points")
    """
    if category not in _EMPTY:
        category = "facts"
    mem = load_memory()
    mem[category][key] = value
    save_memory(mem)


def delete_fact(category: str, key: str):
    """Remove a fact from memory."""
    mem = load_memory()
    mem.get(category, {}).pop(key, None)
    save_memory(mem)


def clear_memory():
    """Wipe all memory."""
    save_memory(dict(_EMPTY))


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT INJECTION — what gets added to every system prompt
# ══════════════════════════════════════════════════════════════════════════════

def get_memory_context() -> str:
    """
    Returns a formatted string injected into the agent's system prompt.
    Empty string if no memory has been saved yet.
    """
    mem = load_memory()
    sections = []

    if mem.get("preferences"):
        lines = ["**Your preferences:**"]
        for k, v in mem["preferences"].items():
            lines.append(f"  - {k}: {v}")
        sections.append("\n".join(lines))

    if mem.get("context"):
        lines = ["**Your work context:**"]
        for k, v in mem["context"].items():
            lines.append(f"  - {k}: {v}")
        sections.append("\n".join(lines))

    if mem.get("people"):
        lines = ["**People you work with:**"]
        for name, info in mem["people"].items():
            if isinstance(info, dict):
                parts = [name]
                if info.get("role"):  parts.append(f"({info['role']})")
                if info.get("email"): parts.append(f"<{info['email']}>")
                if info.get("notes"): parts.append(f"— {info['notes']}")
                lines.append("  - " + " ".join(parts))
            else:
                lines.append(f"  - {name}: {info}")
        sections.append("\n".join(lines))

    if mem.get("patterns"):
        lines = ["**Your work patterns:**"]
        for k, v in mem["patterns"].items():
            lines.append(f"  - {k}: {v}")
        sections.append("\n".join(lines))

    if mem.get("facts"):
        lines = ["**Other facts about you:**"]
        for k, v in mem["facts"].items():
            lines.append(f"  - {k}: {v}")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = "## What I remember about you:"
    return header + "\n\n" + "\n\n".join(sections)


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-EXTRACTION — learn from each conversation turn
# ══════════════════════════════════════════════════════════════════════════════

# Patterns that reveal facts about the user
_PATTERNS = [
    # Manager / boss
    (r"my (?:manager|boss|lead|team lead) is (\w+)",
     "people", lambda m: (m.group(1), {"role": "manager"})),
    (r"(\w+) is my (?:manager|boss|lead|team lead)",
     "people", lambda m: (m.group(1), {"role": "manager"})),

    # Sprint
    (r"(?:we'?re? (?:in|on)|current) sprint\s+(\w+)",
     "context", lambda m: ("current_sprint", f"Sprint {m.group(1)}")),
    (r"sprint\s+(\w+)\s+(?:ends|started|finishes)",
     "context", lambda m: ("current_sprint", f"Sprint {m.group(1)}")),

    # Team
    (r"(?:my team|i'?m? on the?) (?:is (?:called )?|team )?([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)",
     "context", lambda m: ("team", m.group(1))),

    # Company / org
    (r"(?:my company|we work at|I work at|I work for) ([A-Z][a-zA-Z0-9 ]+?)(?:\.|,|$)",
     "context", lambda m: ("company", m.group(1).strip())),

    # Preferred response style
    (r"(?:please |always )?(?:give|show|use|write|keep) (?:me )?(concise|detailed|brief|bullet|markdown|plain text)",
     "preferences", lambda m: ("response_style", m.group(1))),

    # Timezone
    (r"(?:my timezone is|i'?m? in) ([A-Z]{2,4}(?:[+-]\d+)?|UTC[+-]\d+|GMT[+-]\d+)",
     "preferences", lambda m: ("timezone", m.group(1))),

    # Project name
    (r"(?:working on|my project is|the project is called) ([A-Z][a-zA-Z0-9 \-]+?)(?:\.|,|$)",
     "context", lambda m: ("active_project", m.group(1).strip())),
]


def extract_and_save_facts(user_message: str, assistant_response: str = ""):
    """
    Scan a conversation turn for learnable facts and persist them.
    Called automatically after every agent turn.
    """
    combined = user_message + " " + assistant_response
    mem = load_memory()
    changed = False

    for pattern, category, extractor in _PATTERNS:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            try:
                key, value = extractor(match)
                # For people: merge into existing entry
                if category == "people":
                    existing = mem["people"].get(key, {})
                    if isinstance(existing, dict):
                        existing.update(value)
                        value = existing
                mem[category][key] = value
                changed = True
            except Exception:
                pass

    if changed:
        save_memory(mem)

    # Also run regex-based entity extraction
    try:
        auto_save_entities(user_message, assistant_response)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# ENTITY EXTRACTION — fast regex-based, no LLM required
# ══════════════════════════════════════════════════════════════════════════════

def extract_entities(text: str) -> dict:
    """
    Extract named entities from text using regex patterns.
    Returns dict with: people (list), emails (list), projects (list).
    No LLM call — fast and always available.
    """
    # Email addresses
    emails = re.findall(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b', text)
    # Two consecutive title-case words (names), not at sentence start
    names = re.findall(r'(?<!\.\s)\b([A-Z][a-z]{1,20}\s+[A-Z][a-z]{1,20})\b', text)
    # Project-like terms: "Project X", "Sprint 12", ticket IDs like "PROJ-123"
    projects = re.findall(
        r'\b(?:Project|Sprint|Release|Milestone|Epic|Phase)\s+[\w.\-]+\b', text, re.I
    )
    tickets = re.findall(r'\b[A-Z]{2,10}-\d{1,6}\b', text)
    return {
        "emails":   list(set(emails)),
        "people":   list(set(names)),
        "projects": list(set(projects + tickets)),
    }


def auto_save_entities(user_message: str, assistant_response: str) -> None:
    """
    Extract entities from a conversation turn and persist to memory.
    Saves email → person mapping and project references automatically.
    """
    combined = f"{user_message}\n{assistant_response}"
    entities = extract_entities(combined)
    mem = load_memory()
    changed = False

    for email in entities["emails"]:
        # Derive a display name from the local part of the email
        local = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        if local and local not in mem["people"]:
            mem["people"][local] = {"email": email, "notes": "auto-extracted"}
            changed = True

    for proj in entities["projects"]:
        key = proj.strip()
        if key and key not in mem["context"]:
            mem["context"][key] = "seen in conversation"
            changed = True

    if changed:
        save_memory(mem)


# ══════════════════════════════════════════════════════════════════════════════
# TOOL-CALLABLE FUNCTIONS — the agent can explicitly update memory
# ══════════════════════════════════════════════════════════════════════════════

def update_memory_entry(category: str, key: str, value: str) -> dict:
    """
    Agent-callable: explicitly store a fact.
    Returns confirmation dict.
    """
    save_fact(category, key, value)
    return {"status": "saved", "category": category, "key": key, "value": value}


def get_memory_summary() -> dict:
    """
    Agent-callable: return the full memory as a dict for display.
    """
    mem = load_memory()
    mem.pop("updated_at", None)
    total = sum(len(v) for v in mem.values() if isinstance(v, dict))
    return {"total_facts": total, "memory": mem}
