"""
tools/tone_learner.py — Writing Style Learning
===============================================
Learns how YOU write emails and messages.
Feed it 5-20 examples of your real emails.
It extracts your style fingerprint and injects it into the agent's system
prompt whenever it drafts something for you.

Style dimensions analysed:
  • Formality (casual ↔ formal)
  • Greeting style  (Hi / Hey / Dear / None)
  • Sign-off style  (Thanks / Cheers / Best / Regards / None)
  • Average sentence length
  • Emoji usage (yes / no / sometimes)
  • Use of bullet points
  • Directness (gets to the point quickly vs context first)

Storage: tone_profile.json at project root
"""

import re
import json
import datetime
from pathlib import Path
from typing import Optional

PROFILE_FILE  = Path(__file__).parent.parent / "tone_profile.json"
SAMPLES_FILE  = Path(__file__).parent.parent / "tone_samples.json"

_EMPTY_PROFILE = {
    "formality":         "professional",  # casual | professional | formal
    "greeting":          None,            # "Hi" | "Hey" | "Dear" | None
    "sign_off":          None,            # "Thanks" | "Cheers" | "Best" etc
    "avg_sentence_len":  15,              # words
    "uses_emoji":        False,
    "uses_bullets":      False,
    "direct_style":      True,            # True = gets to the point
    "common_phrases":    [],              # phrases that appear often
    "sample_count":      0,
    "updated_at":        None,
}


# ══════════════════════════════════════════════════════════════════════════════
# LOAD / SAVE
# ══════════════════════════════════════════════════════════════════════════════

def load_profile() -> dict:
    if PROFILE_FILE.exists():
        try:
            data = json.loads(PROFILE_FILE.read_text())
            for k, v in _EMPTY_PROFILE.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return dict(_EMPTY_PROFILE)


def save_profile(p: dict):
    p["updated_at"] = datetime.datetime.now().isoformat()
    PROFILE_FILE.write_text(json.dumps(p, indent=2))


def _load_samples() -> list[str]:
    if SAMPLES_FILE.exists():
        try:
            return json.loads(SAMPLES_FILE.read_text())
        except Exception:
            pass
    return []


def _save_samples(samples: list[str]):
    SAMPLES_FILE.write_text(json.dumps(samples, indent=2, ensure_ascii=False))


# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def _detect_formality(texts: list[str]) -> str:
    casual_signals  = ["hey", "hi there", "gonna", "wanna", "btw", "lol", "tbh", "👋", "cheers", "mate"]
    formal_signals  = ["dear", "sincerely", "please find", "herewith", "kindly", "pursuant", "regarding"]
    prof_signals    = ["hi ", "hello", "thanks", "best", "regards", "please", "could you", "would you"]

    combined = " ".join(texts).lower()
    casual  = sum(combined.count(s) for s in casual_signals)
    formal  = sum(combined.count(s) for s in formal_signals)
    prof    = sum(combined.count(s) for s in prof_signals)

    if casual > formal and casual > prof:
        return "casual"
    if formal > casual and formal > prof:
        return "formal"
    return "professional"


def _detect_greeting(texts: list[str]) -> Optional[str]:
    greetings = {}
    for text in texts:
        first_line = text.strip().split("\n")[0].strip().lower()
        for g in ["hey", "hi ", "hello", "dear", "good morning", "morning"]:
            if first_line.startswith(g):
                base = g.strip().capitalize()
                greetings[base] = greetings.get(base, 0) + 1
    return max(greetings, key=greetings.get) if greetings else None


def _detect_signoff(texts: list[str]) -> Optional[str]:
    signoffs = {}
    common = ["thanks", "thank you", "cheers", "best", "regards", "kind regards",
              "best regards", "many thanks", "warmly", "sincerely", "talk soon"]
    for text in texts:
        last_lines = text.strip().split("\n")[-3:]
        last_block = "\n".join(last_lines).lower()
        for s in common:
            if s in last_block:
                signoffs[s.capitalize()] = signoffs.get(s.capitalize(), 0) + 1
    return max(signoffs, key=signoffs.get) if signoffs else None


def _avg_sentence_length(texts: list[str]) -> int:
    all_sentences = []
    for text in texts:
        sentences = re.split(r'[.!?]+', text)
        for s in sentences:
            words = len(s.split())
            if 3 <= words <= 50:  # ignore outliers
                all_sentences.append(words)
    if not all_sentences:
        return 15
    return int(sum(all_sentences) / len(all_sentences))


def _uses_emoji(texts: list[str]) -> bool:
    emoji_pattern = re.compile(
        "[\U0001F300-\U0001F9FF\U0001FA00-\U0001FA9F"
        "\U00002600-\U000027BF\U0000FE00-\U0000FE0F]+",
        flags=re.UNICODE,
    )
    count = sum(1 for t in texts if emoji_pattern.search(t))
    return count >= len(texts) * 0.3  # uses emoji in ≥30% of messages


def _uses_bullets(texts: list[str]) -> bool:
    count = sum(1 for t in texts if re.search(r"^[\s]*[-•*]\s", t, re.MULTILINE))
    return count >= len(texts) * 0.25


def _common_phrases(texts: list[str]) -> list[str]:
    """Find 2-3 word phrases that appear in multiple emails."""
    phrase_counts: dict = {}
    for text in texts:
        words = re.findall(r"\b\w+\b", text.lower())
        for i in range(len(words) - 2):
            phrase = " ".join(words[i:i+3])
            phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1

    # Only keep phrases that appear in at least 2 different messages
    repeated = [p for p, c in phrase_counts.items() if c >= 2]
    # Remove generic filler
    filler = {"the the the", "and the and", "to the to", "i am i", "you can you"}
    repeated = [p for p in repeated if p not in filler]
    return repeated[:8]


def _is_direct(texts: list[str]) -> bool:
    """True if messages typically get to the point in the first sentence."""
    context_openers = [
        "i wanted to", "i hope this", "i hope you", "following up",
        "just circling", "as discussed", "as per", "with reference to",
        "i am writing to", "i'm writing to",
    ]
    direct_count = 0
    for text in texts:
        first = text.strip().split(".")[0].lower()
        if not any(o in first for o in context_openers):
            direct_count += 1
    return direct_count >= len(texts) * 0.5


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def add_sample(text: str) -> dict:
    """
    Add one email/message example to the training set and rebuild the profile.
    Returns the updated profile.
    """
    samples = _load_samples()
    text = text.strip()
    if not text:
        return {"error": "Empty sample"}
    if text in samples:
        return {"status": "already_exists", "sample_count": len(samples)}

    samples.append(text)
    _save_samples(samples)
    return rebuild_profile()


def add_samples_bulk(texts: list[str]) -> dict:
    """Add multiple samples at once."""
    samples = _load_samples()
    new_count = 0
    for t in texts:
        t = t.strip()
        if t and t not in samples:
            samples.append(t)
            new_count += 1
    _save_samples(samples)
    return rebuild_profile()


def rebuild_profile() -> dict:
    """Rebuild the style profile from all saved samples."""
    samples = _load_samples()
    if not samples:
        return {"error": "No samples yet. Add some email examples first."}

    profile = {
        "formality":        _detect_formality(samples),
        "greeting":         _detect_greeting(samples),
        "sign_off":         _detect_signoff(samples),
        "avg_sentence_len": _avg_sentence_length(samples),
        "uses_emoji":       _uses_emoji(samples),
        "uses_bullets":     _uses_bullets(samples),
        "direct_style":     _is_direct(samples),
        "common_phrases":   _common_phrases(samples),
        "sample_count":     len(samples),
        "updated_at":       datetime.datetime.now().isoformat(),
    }
    save_profile(profile)
    return profile


def get_tone_instructions() -> str:
    """
    Returns a style guide string injected into the system prompt.
    Empty string if no profile has been built yet.
    """
    profile = load_profile()
    if profile.get("sample_count", 0) == 0:
        return ""

    lines = ["## When drafting emails or messages, match this writing style:"]

    formality = profile.get("formality", "professional")
    lines.append(f"- Tone: **{formality}**")

    if profile.get("greeting"):
        lines.append(f"- Start with: **{profile['greeting']}**")
    else:
        lines.append("- No greeting (dive straight in)")

    if profile.get("sign_off"):
        lines.append(f"- Sign off with: **{profile['sign_off']}**")
    else:
        lines.append("- No formal sign-off")

    avg = profile.get("avg_sentence_len", 15)
    if avg < 10:
        lines.append("- Keep sentences **very short** (≤10 words)")
    elif avg < 17:
        lines.append("- Use **medium-length** sentences (~15 words)")
    else:
        lines.append("- Longer, more detailed sentences are fine")

    if profile.get("uses_emoji"):
        lines.append("- **Use emojis** where natural")
    else:
        lines.append("- **No emojis**")

    if profile.get("uses_bullets"):
        lines.append("- **Use bullet points** for lists")
    else:
        lines.append("- Write in **prose**, avoid bullet points")

    if profile.get("direct_style"):
        lines.append("- Get to the point immediately — no preamble")
    else:
        lines.append("- Provide brief context before the main request")

    if profile.get("common_phrases"):
        examples = ", ".join(f'"{p}"' for p in profile["common_phrases"][:3])
        lines.append(f"- Common phrases this person uses: {examples}")

    return "\n".join(lines)


def get_profile_display() -> dict:
    """Return profile info for the UI settings panel."""
    profile = load_profile()
    samples = _load_samples()
    return {
        "profile":      profile,
        "sample_count": len(samples),
        "has_profile":  profile.get("sample_count", 0) > 0,
    }
