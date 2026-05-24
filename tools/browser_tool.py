"""
tools/browser_tool.py — Browser Automation via Playwright
===========================================================
Gives the agent the ability to browse websites and scrape content.
Useful for: checking pages with no API, competitor research, news, pricing.

Requires: playwright (pip install playwright && playwright install chromium)

Tools exposed:
  browse_url(url, extract="text")    — fetch a page, return text or links
  scrape_structured(url, selector)   — extract specific HTML elements
"""

import re
import json
import time
from typing import Optional


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


# ══════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def _get_playwright_page():
    """Launch a headless Chromium browser and return a page object."""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        raise ImportError(
            "playwright not installed.\n"
            "Run: pip install playwright && playwright install chromium"
        )


def browse_url(
    url: str,
    extract: str = "text",
    wait_seconds: int = 3,
    max_chars: int = 8000,
) -> dict:
    """
    Agent-callable: visit a URL and return its content.

    Args:
        url:          The URL to visit
        extract:      "text" (default) | "links" | "both"
        wait_seconds: How long to wait for JS to render (default 3)
        max_chars:    Max characters to return (default 8000)

    Returns dict with: url, title, content (text and/or links), word_count
    """
    sync_playwright = _get_playwright_page()

    result = {"url": url, "title": "", "text": "", "links": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx     = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = ctx.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            if wait_seconds > 0:
                time.sleep(wait_seconds)

            result["title"] = page.title()

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

            if extract in ("links", "both"):
                links = page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('a[href]'))
                        .map(a => ({text: a.innerText.trim(), href: a.href}))
                        .filter(l => l.href.startsWith('http') && l.text.length > 0)
                        .slice(0, 30);
                }""")
                result["links"] = links

        except Exception as e:
            result["error"] = str(e)
        finally:
            browser.close()

    return result


def scrape_structured(
    url: str,
    css_selector: str,
    attribute: str = "innerText",
    max_items: int = 20,
) -> dict:
    """
    Agent-callable: extract specific elements from a page.

    Args:
        url:          URL to visit
        css_selector: CSS selector e.g. "h2.product-title" or "table tr"
        attribute:    "innerText" (default) | "href" | "src" | "innerHTML"
        max_items:    Maximum elements to return (default 20)

    Returns dict with: url, selector, items list
    """
    sync_playwright = _get_playwright_page()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_context().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)

            items = page.evaluate(f"""(sel, attr, limit) => {{
                const els = Array.from(document.querySelectorAll(sel)).slice(0, limit);
                return els.map(el => attr === 'innerText' ? el.innerText.trim() :
                               attr === 'innerHTML' ? el.innerHTML :
                               el.getAttribute(attr) || '');
            }}""", css_selector, attribute, max_items)

            return {
                "url":      url,
                "selector": css_selector,
                "count":    len(items),
                "items":    items,
            }
        except Exception as e:
            return {"url": url, "selector": css_selector, "error": str(e), "items": []}
        finally:
            browser.close()


def search_web(query: str, max_results: int = 5) -> dict:
    """
    Agent-callable: do a DuckDuckGo search and return top results.
    Uses no API key — just scrapes DuckDuckGo HTML.

    Args:
        query:       Search query
        max_results: Number of results to return (default 5)

    Returns dict with: query, results [{title, url, snippet}]
    """
    import urllib.parse
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://html.duckduckgo.com/html/?q={encoded}"

    sync_playwright = _get_playwright_page()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_context().new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(1)

            results = page.evaluate(f"""(limit) => {{
                const items = [];
                document.querySelectorAll('.result__body').forEach((el, i) => {{
                    if (i >= limit) return;
                    const titleEl   = el.querySelector('.result__a');
                    const snippetEl = el.querySelector('.result__snippet');
                    if (titleEl) items.push({{
                        title:   titleEl.innerText.trim(),
                        url:     titleEl.href,
                        snippet: snippetEl ? snippetEl.innerText.trim() : '',
                    }});
                }});
                return items;
            }}""", max_results)

            return {"query": query, "results": results}
        except Exception as e:
            return {"query": query, "error": str(e), "results": []}
        finally:
            browser.close()


def take_screenshot_url(url: str, output_path: str) -> dict:
    """
    Take a full-page screenshot of a URL and save it.

    Args:
        url:         URL to screenshot
        output_path: Where to save the .png file

    Returns dict with: url, saved_to, width, height
    """
    sync_playwright = _get_playwright_page()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page    = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=20000)
            page.screenshot(path=output_path, full_page=True)
            return {"url": url, "saved_to": output_path, "status": "success"}
        except Exception as e:
            return {"url": url, "error": str(e)}
        finally:
            browser.close()
