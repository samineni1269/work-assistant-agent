# Research Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the agent's research capability with parallel fetching, clean content extraction, source credibility scoring, research caching, and a new `deep_research` tool that autonomously searches → reads → synthesises → loops.

**Architecture:** All five improvements land in `tools/browser_tool.py` (parallel fetch, trafilatura extraction, credibility scoring, deep_research) and `tools/rag.py` (research cache). The new `deep_research` tool is wired into `tools/llm_provider.py` (tool definition) and `agent.py` (dispatch). No new files needed.

**Tech Stack:** Python stdlib `concurrent.futures.ThreadPoolExecutor` (parallel fetch), `trafilatura` (clean text extraction), Playwright (existing), ChromaDB via rag.py (research cache), JSON file cache fallback.

---

## File Map

| File | Change |
|---|---|
| `tools/browser_tool.py` | Add `_score_credibility()`, `_extract_with_trafilatura()`, `_parallel_browse()`, `deep_research()` — update `browse_url()` to use trafilatura |
| `tools/rag.py` | Add `cache_research()` and `get_cached_research()` |
| `tools/llm_provider.py` | Add `deep_research` tool definition to `TOOLS` list |
| `agent.py` | Add `deep_research` to `dispatch_tool` mapping |
| `requirements.txt` | Add `trafilatura>=1.9.0` |
| `tests/test_research.py` | New — pytest suite for all new functions |

---

## Task 1: Add trafilatura to requirements and test clean extraction

**Files:**
- Modify: `requirements.txt`
- Create: `tests/test_research.py`

- [ ] **Step 1: Add trafilatura to requirements.txt**

Open `requirements.txt` and add this line after the playwright line:

```
trafilatura>=1.9.0               # Clean article text extraction (replaces JS scraping)
```

- [ ] **Step 2: Install it**

```bash
cd ~/Desktop/work-assistant-agent
pip install trafilatura>=1.9.0 --break-system-packages
```

Expected: `Successfully installed trafilatura-...`

- [ ] **Step 3: Write the failing test**

Create `tests/test_research.py`:

```python
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
```

- [ ] **Step 4: Run test — expect ImportError (function doesn't exist yet)**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_extract_with_trafilatura_returns_text -v
```

Expected: `ImportError: cannot import name '_extract_with_trafilatura'`

- [ ] **Step 5: Implement `_extract_with_trafilatura` in browser_tool.py**

Open `tools/browser_tool.py`. After the existing imports block (after `from typing import Optional`), add:

```python
def _extract_with_trafilatura(html: str) -> str | None:
    """
    Use trafilatura to extract clean article text from raw HTML.
    Returns None if trafilatura finds nothing useful (e.g. navigation-only pages).
    Falls back gracefully if trafilatura is not installed.
    """
    if not html:
        return None
    try:
        import trafilatura
        return trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
    except ImportError:
        return None
    except Exception:
        return None
```

- [ ] **Step 6: Run test — expect PASS**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_extract_with_trafilatura_returns_text tests/test_research.py::test_extract_with_trafilatura_returns_none_on_empty -v
```

Expected: `2 passed`

- [ ] **Step 7: Update `browse_url()` to use trafilatura as primary extractor**

In `tools/browser_tool.py`, find the `browse_url` function. Inside the `if extract in ("text", "both"):` block, replace the existing JS `page.evaluate(...)` text extraction with this:

```python
            if extract in ("text", "both"):
                # Get raw HTML first, try trafilatura for clean extraction
                raw_html = page.content()
                clean = _extract_with_trafilatura(raw_html)
                if clean and len(clean) > 200:
                    # trafilatura gave us clean article text
                    text = clean
                else:
                    # Fallback: JS-based extraction (removes nav/footer/scripts)
                    text = page.evaluate("""() => {
                        const remove = document.querySelectorAll(
                            'nav,footer,header,script,style,noscript,.cookie-banner,.ad,.advertisement'
                        );
                        remove.forEach(el => el.remove());
                        return (document.body || document).innerText;
                    }""")
                    text = re.sub(r'\n{3,}', '\n\n', text.strip())
                    text = re.sub(r' {2,}', ' ', text)

                result["text"] = text[:max_chars]
                result["word_count"] = len(text.split())
```

- [ ] **Step 8: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add tools/browser_tool.py requirements.txt tests/test_research.py
git commit -m "feat: add trafilatura clean extraction to browse_url with JS fallback"
```

---

## Task 2: Source credibility scoring

**Files:**
- Modify: `tools/browser_tool.py`
- Modify: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_research.py`:

```python
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
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_score_credibility_high_for_gov -v
```

Expected: `ImportError: cannot import name '_score_credibility'`

- [ ] **Step 3: Implement `_score_credibility` in browser_tool.py**

After `_extract_with_trafilatura`, add:

```python
# ── CREDIBILITY SCORING ───────────────────────────────────────────────────

_HIGH_DOMAINS = {
    # Government / official
    ".gov", ".gov.uk", ".gov.au", ".eu", ".europa.eu",
    # Academic
    ".edu", ".ac.uk", ".ac.au",
    # Major wire services and encyclopedias
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    "npr.org", "pbs.org", "wikipedia.org",
    # Science / research
    "nature.com", "science.org", "pubmed.ncbi.nlm.nih.gov",
    "scholar.google.com", "arxiv.org", "ncbi.nlm.nih.gov",
    # Major tech documentation
    "docs.python.org", "developer.mozilla.org", "docs.microsoft.com",
    "learn.microsoft.com",
}

_MEDIUM_DOMAINS = {
    # Major newspapers / broadcasters
    "nytimes.com", "theguardian.com", "washingtonpost.com", "wsj.com",
    "economist.com", "ft.com", "bloomberg.com", "businessinsider.com",
    "forbes.com", "techcrunch.com", "wired.com", "arstechnica.com",
    "theatlantic.com", "time.com", "cnn.com", "nbcnews.com", "abcnews.go.com",
    # Quality tech sources
    "stackoverflow.com", "github.com", "medium.com",
    "towardsdatascience.com", "hackernews.com", "news.ycombinator.com",
}

_LOW_DOMAINS = {
    "reddit.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "tiktok.com", "youtube.com",
    "quora.com", "answers.yahoo.com",
}


def _score_credibility(url: str) -> dict:
    """
    Score a URL's source credibility based on its domain.

    Returns:
        {
            "url":    str,
            "domain": str,
            "tier":   "HIGH" | "MEDIUM" | "LOW" | "UNKNOWN",
            "score":  float,   # 0.0 – 1.0
            "reason": str,
        }
    """
    import urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
    except Exception:
        return {"url": url, "domain": "", "tier": "UNKNOWN", "score": 0.5, "reason": "Could not parse URL"}

    # Check TLD suffixes first (covers all .gov, .edu etc.)
    for suffix in _HIGH_DOMAINS:
        if domain == suffix or domain.endswith(suffix):
            return {"url": url, "domain": domain, "tier": "HIGH", "score": 0.9,
                    "reason": f"Trusted domain suffix: {suffix}"}

    # Check exact medium domains
    for d in _MEDIUM_DOMAINS:
        if domain == d or domain.endswith("." + d):
            return {"url": url, "domain": domain, "tier": "MEDIUM", "score": 0.65,
                    "reason": f"Known quality source: {d}"}

    # Check low-trust domains
    for d in _LOW_DOMAINS:
        if domain == d or domain.endswith("." + d):
            return {"url": url, "domain": domain, "tier": "LOW", "score": 0.3,
                    "reason": f"User-generated / social content: {d}"}

    return {"url": url, "domain": domain, "tier": "UNKNOWN", "score": 0.5,
            "reason": "Domain not in trust list — treat with caution"}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_score_credibility_high_for_gov tests/test_research.py::test_score_credibility_medium_for_news tests/test_research.py::test_score_credibility_low_for_reddit tests/test_research.py::test_score_credibility_unknown_domain -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add tools/browser_tool.py tests/test_research.py
git commit -m "feat: add source credibility scoring (_score_credibility) with domain tier list"
```

---

## Task 3: Parallel page reading

**Files:**
- Modify: `tools/browser_tool.py`
- Modify: `tests/test_research.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_research.py`:

```python
# ── Task 3: parallel browsing ──────────────────────────────────────────────

def test_parallel_browse_returns_list():
    from tools.browser_tool import _parallel_browse
    # Use a mock to avoid actual network calls in unit tests
    with patch("tools.browser_tool.browse_url") as mock_browse:
        mock_browse.side_effect = lambda url, **kw: {"url": url, "text": f"content of {url}", "title": "Test"}
        results = _parallel_browse(["https://example.com", "https://example.org"], max_workers=2)
    assert len(results) == 2
    assert all("text" in r for r in results)


def test_parallel_browse_handles_errors_gracefully():
    from tools.browser_tool import _parallel_browse
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
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_parallel_browse_returns_list -v
```

Expected: `ImportError: cannot import name '_parallel_browse'`

- [ ] **Step 3: Implement `_parallel_browse` in browser_tool.py**

After `_score_credibility`, add:

```python
# ── PARALLEL FETCH ────────────────────────────────────────────────────────

def _parallel_browse(
    urls: list[str],
    extract: str = "text",
    wait_seconds: int = 2,
    max_chars: int = 6000,
    max_workers: int = 4,
) -> list[dict]:
    """
    Fetch multiple URLs in parallel using a thread pool.

    Each URL gets its own Playwright browser instance running in a separate
    thread. Results are returned in the same order as the input urls list.

    Args:
        urls:        List of URLs to fetch
        extract:     "text" | "links" | "both" (passed to browse_url)
        wait_seconds: JS render wait per page (lower than single browse to save time)
        max_chars:   Max chars per page
        max_workers: Thread pool size (default 4 — avoids overwhelming CPU)

    Returns:
        List of dicts (same structure as browse_url). On per-URL error,
        the dict contains {"url": ..., "error": "..."}  instead of content.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(url: str) -> dict:
        try:
            return browse_url(url, extract=extract,
                              wait_seconds=wait_seconds, max_chars=max_chars)
        except Exception as exc:
            return {"url": url, "error": str(exc), "text": "", "title": ""}

    # Preserve input order
    results_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(urls))) as pool:
        future_to_url = {pool.submit(_fetch_one, url): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results_map[url] = future.result()
            except Exception as exc:
                results_map[url] = {"url": url, "error": str(exc), "text": "", "title": ""}

    return [results_map[url] for url in urls]
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_parallel_browse_returns_list tests/test_research.py::test_parallel_browse_handles_errors_gracefully -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add tools/browser_tool.py tests/test_research.py
git commit -m "feat: add _parallel_browse — fetch multiple URLs in parallel with ThreadPoolExecutor"
```

---

## Task 4: Research cache in rag.py

**Files:**
- Modify: `tools/rag.py`
- Modify: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_research.py`:

```python
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
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_cache_and_retrieve_research -v
```

Expected: `ImportError: cannot import name 'cache_research'`

- [ ] **Step 3: Add cache functions to rag.py**

Open `tools/rag.py`. After the existing constants block (after `CHUNK_OVERLAP = 50`), add:

```python
RESEARCH_CACHE_DIR = KB_DIR / "research_cache"
```

Then at the bottom of the file, after `kb_stats()`, append:

```python
# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH CACHE — avoid re-fetching the same topic
# ══════════════════════════════════════════════════════════════════════════════

def _research_cache_key(topic: str) -> str:
    """Stable filename for a research topic (normalised + hashed)."""
    normalised = topic.lower().strip()
    h = hashlib.md5(normalised.encode()).hexdigest()[:16]
    return h


def cache_research(topic: str, result: dict) -> None:
    """
    Store a research result to disk so future identical queries skip the web.

    Args:
        topic:  The original research query / topic string
        result: The research result dict (from deep_research or manual search)
    """
    RESEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key  = _research_cache_key(topic)
    path = RESEARCH_CACHE_DIR / f"{key}.json"
    payload = {
        "topic":     topic,
        "cached_at": datetime.datetime.now().isoformat(),
        "result":    result,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))


def get_cached_research(topic: str, max_age_hours: int = 24) -> dict | None:
    """
    Retrieve a cached research result if it exists and is not expired.

    Args:
        topic:         The research query to look up
        max_age_hours: Maximum age in hours before the cache is considered stale

    Returns:
        The cached result dict, or None if not found / expired
    """
    RESEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key  = _research_cache_key(topic)
    path = RESEARCH_CACHE_DIR / f"{key}.json"

    if not path.exists():
        return None

    # Check age via filesystem mtime
    import time as _time
    age_seconds = _time.time() - path.stat().st_mtime
    if age_seconds > max_age_hours * 3600:
        return None  # Expired

    try:
        payload = json.loads(path.read_text())
        return payload.get("result")
    except Exception:
        return None
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_cache_and_retrieve_research tests/test_research.py::test_cache_miss_returns_none tests/test_research.py::test_cache_expires -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add tools/rag.py tests/test_research.py
git commit -m "feat: add research cache (cache_research / get_cached_research) to rag.py"
```

---

## Task 5: deep_research() — the main tool

**Files:**
- Modify: `tools/browser_tool.py`
- Modify: `tests/test_research.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_research.py`:

```python
# ── Task 5: deep_research ──────────────────────────────────────────────────

def test_deep_research_returns_expected_keys():
    from tools.browser_tool import deep_research
    with patch("tools.browser_tool.search_web") as mock_search, \
         patch("tools.browser_tool._parallel_browse") as mock_browse, \
         patch("tools.rag.cache_research") as mock_cache, \
         patch("tools.rag.get_cached_research", return_value=None):

        mock_search.return_value = {
            "results": [
                {"title": "Quantum computing basics", "url": "https://example.com/q1", "snippet": "Quantum computers use qubits."},
                {"title": "IBM Quantum", "url": "https://ibm.com/quantum", "snippet": "IBM builds quantum hardware."},
                {"title": "Quantum explained", "url": "https://reuters.com/quantum", "snippet": "News article on quantum."},
            ]
        }
        mock_browse.return_value = [
            {"url": "https://example.com/q1",   "text": "Quantum computers use qubits to compute.", "title": "Quantum basics"},
            {"url": "https://ibm.com/quantum",   "text": "IBM builds quantum hardware with 100+ qubits.", "title": "IBM Quantum"},
            {"url": "https://reuters.com/quantum","text": "Quantum computing is growing rapidly.", "title": "Quantum news"},
        ]

        result = deep_research("quantum computing", depth=1)

    assert "topic" in result
    assert "summary" in result
    assert "sources" in result
    assert "credibility_summary" in result
    assert len(result["sources"]) > 0


def test_deep_research_returns_cache_on_hit():
    from tools.browser_tool import deep_research
    cached = {"topic": "ai news", "summary": "Cached summary", "sources": [], "credibility_summary": {}}
    with patch("tools.rag.get_cached_research", return_value=cached):
        result = deep_research("ai news", depth=2)
    assert result["summary"] == "Cached summary"
    assert result.get("from_cache") is True
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_deep_research_returns_expected_keys -v
```

Expected: `ImportError: cannot import name 'deep_research'`

- [ ] **Step 3: Implement `deep_research` in browser_tool.py**

At the bottom of `tools/browser_tool.py`, append:

```python
# ══════════════════════════════════════════════════════════════════════════════
# DEEP RESEARCH — multi-step: search → read → synthesise → loop
# ══════════════════════════════════════════════════════════════════════════════

def deep_research(
    topic: str,
    depth: int = 2,
    results_per_search: int = 5,
    pages_per_depth: int = 3,
    max_chars_per_page: int = 5000,
    use_cache: bool = True,
    cache_hours: int = 24,
) -> dict:
    """
    Agent-callable: autonomously research a topic and return a synthesised summary.

    Workflow per depth level:
      1. Search DuckDuckGo for the topic (+ any follow-up angles from prior round)
      2. Score all results by credibility, pick the best `pages_per_depth`
      3. Fetch those pages IN PARALLEL using _parallel_browse
      4. Concatenate all extracted text into a research corpus
      5. After all depth levels, build and return a structured result

    Args:
        topic:              What to research
        depth:              How many search → read rounds to run (default 2)
        results_per_search: DuckDuckGo results to fetch per round (default 5)
        pages_per_depth:    How many of those results to actually read (default 3)
        max_chars_per_page: Character limit per page read
        use_cache:          Check research cache first (default True)
        cache_hours:        How long cache entries are valid (default 24h)

    Returns dict:
        {
            "topic":               str,
            "summary":             str,   # Combined text corpus for the LLM to synthesise
            "sources":             list,  # [{title, url, snippet, tier, score}]
            "credibility_summary": dict,  # {"HIGH": n, "MEDIUM": n, "LOW": n, "UNKNOWN": n}
            "search_queries":      list,  # All queries that were run
            "depth_used":          int,
            "from_cache":          bool,
        }
    """
    # ── Cache check ──────────────────────────────────────────────────────────
    if use_cache:
        try:
            from tools.rag import get_cached_research, cache_research
            cached = get_cached_research(topic, max_age_hours=cache_hours)
            if cached:
                cached["from_cache"] = True
                return cached
        except Exception:
            pass  # Cache unavailable — continue without it

    all_sources: list[dict] = []
    all_text_chunks: list[str] = []
    search_queries: list[str] = [topic]
    credibility_counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}

    current_queries = [topic]

    for round_num in range(depth):
        query = current_queries[round_num] if round_num < len(current_queries) else topic

        # 1. Search
        search_result = search_web(query, max_results=results_per_search)
        raw_results   = search_result.get("results", [])

        if not raw_results:
            break

        # 2. Score and rank by credibility
        scored = []
        for r in raw_results:
            cred = _score_credibility(r.get("url", ""))
            scored.append({**r, **cred})

        # Sort: HIGH first, then MEDIUM, then UNKNOWN, then LOW
        tier_order = {"HIGH": 0, "MEDIUM": 1, "UNKNOWN": 2, "LOW": 3}
        scored.sort(key=lambda x: tier_order.get(x.get("tier", "UNKNOWN"), 2))

        # Pick top pages to actually read
        to_read = scored[:pages_per_depth]
        urls_to_fetch = [r["url"] for r in to_read if r.get("url")]

        # 3. Parallel fetch
        if urls_to_fetch:
            pages = _parallel_browse(
                urls_to_fetch,
                extract="text",
                wait_seconds=2,
                max_chars=max_chars_per_page,
                max_workers=min(4, len(urls_to_fetch)),
            )
            url_to_page = {p["url"]: p for p in pages}
        else:
            url_to_page = {}

        # 4. Collect results
        for r in to_read:
            url  = r.get("url", "")
            page = url_to_page.get(url, {})
            text = page.get("text", r.get("snippet", ""))

            # Update credibility counts
            tier = r.get("tier", "UNKNOWN")
            credibility_counts[tier] = credibility_counts.get(tier, 0) + 1

            all_sources.append({
                "title":   page.get("title") or r.get("title", ""),
                "url":     url,
                "snippet": r.get("snippet", ""),
                "tier":    tier,
                "score":   r.get("score", 0.5),
                "round":   round_num + 1,
            })

            if text:
                all_text_chunks.append(
                    f"--- Source: {r.get('title', url)} ({tier}) ---\n{text}\n"
                )

        # 5. Build a follow-up query for next round (angle variation)
        if round_num + 1 < depth:
            follow_ups = [
                f"{topic} explained in detail",
                f"{topic} latest developments 2025",
                f"{topic} research findings",
                f"{topic} practical applications",
            ]
            next_query = follow_ups[round_num % len(follow_ups)]
            current_queries.append(next_query)
            search_queries.append(next_query)

    # Combine all fetched text into a research corpus
    combined_text = "\n\n".join(all_text_chunks)
    if not combined_text:
        combined_text = f"No content could be retrieved for topic: {topic}"

    result = {
        "topic":               topic,
        "summary":             combined_text,
        "sources":             all_sources,
        "credibility_summary": credibility_counts,
        "search_queries":      search_queries,
        "depth_used":          depth,
        "from_cache":          False,
    }

    # Cache the result
    if use_cache:
        try:
            from tools.rag import cache_research
            cache_research(topic, result)
        except Exception:
            pass

    return result
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py::test_deep_research_returns_expected_keys tests/test_research.py::test_deep_research_returns_cache_on_hit -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add tools/browser_tool.py tests/test_research.py
git commit -m "feat: add deep_research() — multi-step autonomous research with parallel fetch, credibility scoring, cache"
```

---

## Task 6: Wire deep_research into llm_provider.py and agent.py

**Files:**
- Modify: `tools/llm_provider.py`
- Modify: `agent.py`

- [ ] **Step 1: Add tool definition to llm_provider.py**

Open `tools/llm_provider.py`. Find the `search_web` tool definition (around line 628). Immediately AFTER the `search_web` dict, add:

```python
    {"name": "deep_research",
     "description": (
         "Autonomously research a topic in depth: searches the web multiple times, "
         "reads the best pages in parallel, scores sources by credibility, and returns "
         "a comprehensive research corpus with credibility stats. Use instead of search_web "
         "when the user asks to 'research', 'investigate', 'find out everything about', "
         "'give me a detailed report on', or 'deep dive into' a topic."
     ),
     "parameters": {"type": "object", "required": ["topic"], "properties": {
         "topic":      {"type": "string",  "description": "The topic or question to research"},
         "depth":      {"type": "integer", "description": "Number of search rounds (1=quick, 2=standard, 3=thorough). Default 2."},
         "use_cache":  {"type": "boolean", "description": "Use cached results if topic was researched recently (default true)"},
         "cache_hours":{"type": "integer", "description": "Max age of cached research in hours (default 24)"},
     }}},
```

- [ ] **Step 2: Add deep_research to the general tool group**

In `tools/llm_provider.py`, find the `"general"` set in `_select_tools()` (around line 1350). Add `"deep_research"` to it:

```python
"general":  {"search_knowledge_base","browse_url","search_web","deep_research","update_memory_entry",
```

- [ ] **Step 3: Verify syntax**

```bash
cd ~/Desktop/work-assistant-agent
python -c "import tools.llm_provider; print('llm_provider OK')"
```

Expected: `llm_provider OK`

- [ ] **Step 4: Add dispatch entry to agent.py**

Open `agent.py`. Find the browser dispatch block:

```python
        "browse_url":            lambda: _browser().browse_url(**args),
        "search_web":            lambda: _browser().search_web(**args),
```

Add the new line immediately after `search_web`:

```python
        "browse_url":            lambda: _browser().browse_url(**args),
        "search_web":            lambda: _browser().search_web(**args),
        "deep_research":         lambda: _browser().deep_research(**args),
```

- [ ] **Step 5: Verify syntax**

```bash
cd ~/Desktop/work-assistant-agent
python -c "import agent; print('agent OK')"
```

Expected: `agent OK`

- [ ] **Step 6: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add tools/llm_provider.py agent.py
git commit -m "feat: wire deep_research tool into llm_provider.py and agent.py dispatch"
```

---

## Task 7: Full test run + push

**Files:**
- Modify: `tests/test_research.py` (fix any failures)

- [ ] **Step 1: Run the full research test suite**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_research.py -v
```

Expected: All tests pass. If any fail, read the error and fix the issue in the relevant file.

- [ ] **Step 2: Run the existing test suite to check for regressions**

```bash
cd ~/Desktop/work-assistant-agent
python -m pytest tests/test_agent.py -v --timeout=30 2>&1 | tail -30
```

Expected: Same pass/fail rate as before these changes. Fix any regressions introduced by this work.

- [ ] **Step 3: Syntax-check all modified files**

```bash
cd ~/Desktop/work-assistant-agent
python -m py_compile tools/browser_tool.py tools/rag.py tools/llm_provider.py agent.py && echo "All syntax OK"
```

Expected: `All syntax OK`

- [ ] **Step 4: Do a live smoke test of deep_research**

```bash
cd ~/Desktop/work-assistant-agent
python3 -c "
from dotenv import load_dotenv
load_dotenv('/Users/saisamineni/Desktop/work-assistant-agent/.env')
from tools.browser_tool import deep_research
result = deep_research('what is trafilatura', depth=1, use_cache=False)
print('Topic:', result['topic'])
print('Sources:', len(result['sources']))
print('Credibility:', result['credibility_summary'])
print('First 300 chars of summary:', result['summary'][:300])
print('From cache:', result['from_cache'])
"
```

Expected: Prints topic, source count, credibility breakdown, and the first 300 chars of real web content.

- [ ] **Step 5: Final push**

```bash
cd ~/Desktop/work-assistant-agent
git add -A
git commit -m "test: full research test suite passing; smoke test verified" 2>/dev/null || echo "Nothing to commit"
git push origin main
```

Expected: `main -> main` or `Everything up-to-date`

---

## Self-Review

**Spec coverage check:**
- ✅ Multi-step deep research — `deep_research()` in Task 5
- ✅ Research memory/cache — `cache_research()` / `get_cached_research()` in Task 4
- ✅ Source credibility scoring — `_score_credibility()` in Task 2
- ✅ Parallel page reading — `_parallel_browse()` in Task 3
- ✅ Clean content extraction (trafilatura) — `_extract_with_trafilatura()` + `browse_url()` update in Task 1
- ✅ Tool wired into agent — `deep_research` in llm_provider.py + agent.py in Task 6
- ✅ Full test suite + smoke test — Task 7

**Placeholder scan:** No TBDs, TODOs, or "similar to" references. All code blocks are complete.

**Type consistency:** `deep_research()` returns `dict`. `_parallel_browse()` returns `list[dict]`. `browse_url()` returns `dict`. `cache_research()` / `get_cached_research()` use the same `topic: str` parameter name throughout. Consistent.
