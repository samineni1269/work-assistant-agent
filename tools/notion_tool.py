"""
notion_tool.py — Notion Integration
======================================
Covers: search, read pages, create pages, list/query databases
Auth:   Notion Integration Token from https://www.notion.so/my-integrations
        Set NOTION_TOKEN in .env
        Share your workspace pages/databases with the integration
API:    Notion REST API v1  (https://api.notion.com/v1)
"""

import os
import json
import requests
from typing import Optional

NOTION_BASE    = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

def _notion(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated Notion API call. Returns parsed JSON."""
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError(
            "\n❌  NOTION_TOKEN not set in .env\n"
            "   Create an integration at: https://www.notion.so/my-integrations\n"
            "   Then share your Notion pages/databases with the integration.\n"
        )
    headers = {
        "Authorization":  f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type":   "application/json",
    }
    resp = requests.request(method, f"{NOTION_BASE}{path}", headers=headers, **kwargs)
    if not resp.ok:
        raise RuntimeError(f"Notion API error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


# ─────────────────────────────────────────────
# HELPERS — extract rich text
# ─────────────────────────────────────────────

def _rich_text(rt_list: list) -> str:
    """Flatten a rich_text array into a plain string."""
    return "".join(seg.get("plain_text", "") for seg in (rt_list or []))


def _block_to_text(block: dict) -> str:
    """Convert a single Notion block to readable plain text."""
    btype = block.get("type", "")
    data  = block.get(btype, {})

    if btype in ("paragraph", "heading_1", "heading_2", "heading_3",
                 "bulleted_list_item", "numbered_list_item", "toggle",
                 "quote", "callout"):
        prefix = {
            "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
            "bulleted_list_item": "• ", "numbered_list_item": "1. ",
            "quote": "> ",
        }.get(btype, "")
        return prefix + _rich_text(data.get("rich_text", []))

    if btype == "code":
        lang = data.get("language", "")
        code = _rich_text(data.get("rich_text", []))
        return f"```{lang}\n{code}\n```"

    if btype == "divider":
        return "---"

    if btype == "to_do":
        checked = "✅" if data.get("checked") else "☐"
        return f"{checked} {_rich_text(data.get('rich_text', []))}"

    return ""  # Unsupported block type (image, embed, etc.)


# ─────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────

def search_notion(query: str, max_results: int = 10) -> list[dict]:
    """
    Search Notion for pages and databases matching a query.

    Args:
        query:       Search string
        max_results: Max results to return

    Returns:
        List of result dicts: id, title, type, url, last_edited
    """
    payload = {"query": query, "page_size": min(max_results, 100)}
    data = _notion("POST", "/search", json=payload)

    results = []
    for item in data.get("results", []):
        obj_type = item.get("object")  # "page" or "database"
        # Extract title
        if obj_type == "page":
            props = item.get("properties", {})
            title = ""
            for prop in props.values():
                if prop.get("type") == "title":
                    title = _rich_text(prop.get("title", []))
                    break
            if not title:
                title = _rich_text(item.get("properties", {}).get("title", {}).get("title", []))
        else:  # database
            title = _rich_text(item.get("title", []))

        results.append({
            "id":          item.get("id"),
            "title":       title or "(Untitled)",
            "type":        obj_type,
            "url":         item.get("url", ""),
            "last_edited": item.get("last_edited_time", ""),
        })
    return results


# ─────────────────────────────────────────────
# PAGES
# ─────────────────────────────────────────────

def get_notion_page(page_id: str) -> dict:
    """
    Read a Notion page — returns its title, properties, and full text content.

    Args:
        page_id: Notion page ID (UUID format or URL)

    Returns:
        {"id": ..., "title": ..., "url": ..., "content": str, "properties": dict}
    """
    # Normalise page_id (strip URL if full URL was passed)
    page_id = page_id.strip().rstrip("/").split("-")[-1] if "/" in page_id else page_id

    page = _notion("GET", f"/pages/{page_id}")

    # Extract title
    props = page.get("properties", {})
    title = ""
    for prop in props.values():
        if prop.get("type") == "title":
            title = _rich_text(prop.get("title", []))
            break

    # Fetch blocks (page content)
    blocks_data = _notion("GET", f"/blocks/{page_id}/children", params={"page_size": 100})
    content_lines = []
    for block in blocks_data.get("results", []):
        line = _block_to_text(block)
        if line.strip():
            content_lines.append(line)

    # Flatten simple properties for display
    flat_props = {}
    for key, val in props.items():
        vtype = val.get("type")
        if vtype == "title":
            flat_props[key] = _rich_text(val.get("title", []))
        elif vtype == "rich_text":
            flat_props[key] = _rich_text(val.get("rich_text", []))
        elif vtype == "select":
            flat_props[key] = (val.get("select") or {}).get("name", "")
        elif vtype == "multi_select":
            flat_props[key] = [s.get("name") for s in val.get("multi_select", [])]
        elif vtype == "date":
            flat_props[key] = (val.get("date") or {}).get("start", "")
        elif vtype == "checkbox":
            flat_props[key] = val.get("checkbox", False)
        elif vtype in ("number", "url", "email", "phone_number"):
            flat_props[key] = val.get(vtype)
        elif vtype == "people":
            flat_props[key] = [p.get("name", p.get("id")) for p in val.get("people", [])]

    return {
        "id":         page.get("id"),
        "title":      title or "(Untitled)",
        "url":        page.get("url", ""),
        "last_edited": page.get("last_edited_time", ""),
        "content":    "\n".join(content_lines),
        "properties": flat_props,
    }


def create_notion_page(
    parent_id: str,
    title: str,
    content: str = "",
    parent_type: str = "page",
) -> dict:
    """
    Create a new Notion page under an existing page or database.

    Args:
        parent_id:   ID of parent page or database
        title:       Page title
        content:     Plain text content — each line becomes a paragraph block
        parent_type: 'page' or 'database'

    Returns:
        {"status": "created", "id": ..., "url": ..., "title": ...}
    """
    parent = (
        {"type": "page_id",     "page_id":     parent_id}
        if parent_type == "page"
        else {"type": "database_id", "database_id": parent_id}
    )

    # Build children blocks from content lines
    children = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        block_type = "paragraph"
        text = line
        if line.startswith("# "):
            block_type, text = "heading_1", line[2:]
        elif line.startswith("## "):
            block_type, text = "heading_2", line[3:]
        elif line.startswith("### "):
            block_type, text = "heading_3", line[4:]
        elif line.startswith("- ") or line.startswith("• "):
            block_type, text = "bulleted_list_item", line[2:]
        elif len(line) >= 3 and line[0].isdigit() and line[1] == "." and line[2] == " ":
            block_type, text = "numbered_list_item", line[3:]

        children.append({
            "object": "block",
            "type": block_type,
            block_type: {
                "rich_text": [{"type": "text", "text": {"content": text}}]
            },
        })

    payload = {
        "parent":     parent,
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": children,
    }

    result = _notion("POST", "/pages", json=payload)
    return {
        "status": "created",
        "id":     result.get("id"),
        "url":    result.get("url", ""),
        "title":  title,
    }


# ─────────────────────────────────────────────
# DATABASES
# ─────────────────────────────────────────────

def list_notion_databases(max_results: int = 20) -> list[dict]:
    """
    List all Notion databases the integration has access to.

    Returns:
        List of database dicts: id, title, url, property_names
    """
    payload = {"filter": {"value": "database", "property": "object"}, "page_size": min(max_results, 100)}
    data = _notion("POST", "/search", json=payload)
    return [
        {
            "id":             db.get("id"),
            "title":          _rich_text(db.get("title", [])),
            "url":            db.get("url", ""),
            "property_names": list(db.get("properties", {}).keys()),
        }
        for db in data.get("results", [])
    ]


def query_notion_database(
    database_id: str,
    filter_property: str = None,
    filter_value: str = None,
    max_results: int = 20,
) -> list[dict]:
    """
    Query a Notion database and return its entries.

    Args:
        database_id:     Database ID
        filter_property: Property name to filter on (optional)
        filter_value:    Filter value (optional, used with filter_property)
        max_results:     Max entries to return

    Returns:
        List of entry dicts with flattened properties
    """
    payload: dict = {"page_size": min(max_results, 100)}

    if filter_property and filter_value:
        payload["filter"] = {
            "property": filter_property,
            "rich_text": {"contains": filter_value},
        }

    data = _notion("POST", f"/databases/{database_id}/query", json=payload)

    entries = []
    for page in data.get("results", []):
        props = page.get("properties", {})
        flat: dict = {"id": page.get("id"), "url": page.get("url", "")}
        for key, val in props.items():
            vtype = val.get("type")
            if vtype == "title":
                flat[key] = _rich_text(val.get("title", []))
            elif vtype == "rich_text":
                flat[key] = _rich_text(val.get("rich_text", []))
            elif vtype == "select":
                flat[key] = (val.get("select") or {}).get("name", "")
            elif vtype == "multi_select":
                flat[key] = [s.get("name") for s in val.get("multi_select", [])]
            elif vtype == "date":
                flat[key] = (val.get("date") or {}).get("start", "")
            elif vtype == "checkbox":
                flat[key] = val.get("checkbox", False)
            elif vtype in ("number", "url", "email"):
                flat[key] = val.get(vtype)
            elif vtype == "status":
                flat[key] = (val.get("status") or {}).get("name", "")
            elif vtype == "people":
                flat[key] = [p.get("name", p.get("id")) for p in val.get("people", [])]
        entries.append(flat)
    return entries
