"""
tests/test_research.py — Research upgrade test suite
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock


# ── Task 1: trafilatura extraction ─────────────────────────────────────────

def test_extract_with_trafilatura_returns_text():
    from tools.browser_tool import _extract_with_trafilatura
    html = "<html><body><article><p>Hello world this is real content.</p></article></body></html>"
    result = _extract_with_trafilatura(html)
    assert result is not None
    assert "Hello world" in result


def test_extract_with_trafilatura_returns_none_on_empty():
    from tools.browser_tool import _extract_with_trafilatura
    result = _extract_with_trafilatura("")
    assert result is None


# ── Task 2: credibility scoring ────────────────────────────────────────────

def test_score_credibility_high_for_gov():
    from tools.browser_tool import _score_credibility
    result = _score_credibility("https://www.cdc.gov/article")
    assert result["tier"] == "HIGH"
    assert result["score"] >= 0.8


def test_score_credibility_medium_for_news():
    from tools.browser_tool import _score_credibility
    result = _score_credibility("https://www.reuters.com/technology/ai")
    assert result["tier"] in ("HIGH", "MEDIUM")


def test_score_credibility_low_for_reddit():
    from tools.browser_tool import _score_credibility
    result = _score_credibility("https://www.reddit.com/r/technology")
    assert result["tier"] == "LOW"


def test_score_credibility_unknown_domain():
    from tools.browser_tool import _score_credibility
    result = _score_credibility("https://somerandomblog123.com/post")
    assert result["tier"] == "UNKNOWN"
    assert "score" in result
