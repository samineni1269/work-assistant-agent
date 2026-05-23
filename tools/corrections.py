"""
tools/corrections.py — Correction Memory
==========================================
Detects when the user corrects the agent and stores the correction
as a rule injected into every future system prompt.

Correction triggers:
  "that's wrong", "no,", "I meant", "actually", "not X, Y", "incorrect"
Stored in corrections.json: list of {bad, correction, query, ts, count}
"""

import re
import json
import datetime
from pathlib import Path
from typing import Optional

CORRECTIONS_FILE = Path(__file__).parent.parent / "corrections.json"
MAX_CORRECTIONS       = 100   # cap to avoid bloating the prompt
MAX_PROMPT_CORRECTIONS = 20   # max corrections to inject into system prompt

_TRIGGERS = [
    r"\bthat'?s wrong\b",
    r"\bno[,!]\s+(?:actually|the answer is|it'?s|I meant)\b",
    r"\bI meant\b",
    r"\bactually\b",
    r"\bincorrect\b",
    r"\bnot\s+\w+[,\s]+(?:it'?s|use|try)\b",
]
_TRIGGER_RE = re.compile("|".join(_TRIGGERS), re.IGNORECASE)


def detect_correction(user_message: str) -> Optional[tuple]:
    """
    Return (correction_text, wrong_term) if the message looks like a correction,
    else None.
    """
    if not _TRIGGER_RE.search(user_message):
        return None
    correction = _TRIGGER_RE.sub("", user_message).strip(" ,.")
    if not correction:
        return None
    wrong = None
    m = re.search(r"\bnot\s+(\w+)", user_message, re.IGNORECASE)
    if m:
        wrong = m.group(1)
    return (correction, wrong)


def _load() -> list:
    if CORRECTIONS_FILE.exists():
        try:
            return json.loads(CORRECTIONS_FILE.read_text())
        except Exception:
            pass
    return []


def _save(data: list):
    tmp = CORRECTIONS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(CORRECTIONS_FILE)


def save_correction(bad_response: str, correction: str, user_message: str = ""):
    """Persist a new correction, or increment count if same correction seen before."""
    data = _load()
    for entry in data:
        if entry["correction"].strip().lower() == correction.strip().lower():
            entry["count"] = entry.get("count", 1) + 1
            entry["ts"] = datetime.datetime.now().isoformat()
            _save(data)
            return
    data.append({
        "bad":        bad_response[:200],
        "correction": correction,
        "query":      user_message[:200],
        "ts":         datetime.datetime.now().isoformat(),
        "count":      1,
    })
    data = sorted(data, key=lambda x: -x.get("count", 1))[:MAX_CORRECTIONS]
    _save(data)


def get_corrections_context() -> str:
    """Return formatted corrections string for injection into system prompt."""
    data = _load()
    if not data:
        return ""
    lines = ["## Past corrections — always follow these rules:"]
    for entry in data[:MAX_PROMPT_CORRECTIONS]:
        lines.append(f"- Previously said: \"{entry['bad'][:80]}\"")
        lines.append(f"  Correct: \"{entry['correction']}\"")
    return "\n".join(lines)


def get_all_corrections() -> list:
    """Return raw correction list (for UI display)."""
    return _load()


def delete_correction(index: int):
    """Remove a correction by list index."""
    data = _load()
    if 0 <= index < len(data):
        data.pop(index)
        _save(data)
