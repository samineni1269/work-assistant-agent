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
