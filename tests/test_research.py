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


# ── Task 3: parallel browsing ──────────────────────────────────────────────

def test_parallel_browse_returns_list():
    from tools.browser_tool import _parallel_browse
    from unittest.mock import patch
    with patch("tools.browser_tool.browse_url") as mock_browse:
        mock_browse.side_effect = lambda url, **kw: {"url": url, "text": f"content of {url}", "title": "Test"}
        results = _parallel_browse(["https://example.com", "https://example.org"], max_workers=2)
    assert len(results) == 2
    assert all("text" in r for r in results)


def test_parallel_browse_handles_errors_gracefully():
    from tools.browser_tool import _parallel_browse
    from unittest.mock import patch
    with patch("tools.browser_tool.browse_url") as mock_browse:
        def side_effect(url, **kw):
            if "bad" in url:
                raise RuntimeError("Network error")
            return {"url": url, "text": "ok", "title": "Test"}
        mock_browse.side_effect = side_effect
        results = _parallel_browse(["https://good.com", "https://bad.com"])
    assert len(results) == 2
    good = next(r for r in results if "good" in r["url"])
    bad  = next(r for r in results if "bad" in r["url"])
    assert good["text"] == "ok"
    assert "error" in bad


# ── Task 4: research cache ─────────────────────────────────────────────────

def test_cache_and_retrieve_research(tmp_path, monkeypatch):
    import tools.rag as rag_module
    monkeypatch.setattr(rag_module, "RESEARCH_CACHE_DIR", tmp_path / "research_cache")
    from tools.rag import cache_research, get_cached_research

    cache_research("what is quantum computing", {"summary": "Quantum computers use qubits", "sources": []})
    result = get_cached_research("what is quantum computing", max_age_hours=24)
    assert result is not None
    assert result["summary"] == "Quantum computers use qubits"


def test_cache_miss_returns_none(tmp_path, monkeypatch):
    import tools.rag as rag_module
    monkeypatch.setattr(rag_module, "RESEARCH_CACHE_DIR", tmp_path / "research_cache")
    from tools.rag import get_cached_research

    result = get_cached_research("something never searched", max_age_hours=24)
    assert result is None


def test_cache_expires(tmp_path, monkeypatch):
    import tools.rag as rag_module
    monkeypatch.setattr(rag_module, "RESEARCH_CACHE_DIR", tmp_path / "research_cache")
    from tools.rag import cache_research, get_cached_research
    import datetime

    cache_research("old topic", {"summary": "Old data"})
    # Manually backdate the file's mtime by 25 hours
    cache_dir = tmp_path / "research_cache"
    for f in cache_dir.iterdir():
        old_time = (datetime.datetime.now() - datetime.timedelta(hours=25)).timestamp()
        import os
        os.utime(f, (old_time, old_time))

    result = get_cached_research("old topic", max_age_hours=24)
    assert result is None
