"""
atlassian.py — Jira + Confluence Tools
========================================
Covers: Jira (issues, search, comments, transitions), Confluence (pages, search, create/update)
Auth:   Email + API token from https://id.atlassian.com/manage-profile/security/api-tokens
API:    Jira REST v3 + Confluence REST v2
"""

import os
import requests
from typing import Optional
from requests.auth import HTTPBasicAuth

# ─────────────────────────────────────────────
# AUTH — Basic auth with API token
# ─────────────────────────────────────────────

def _get_auth() -> tuple:
    """Return (email, api_token) from environment variables."""
    email = os.getenv("ATLASSIAN_EMAIL")
    token = os.getenv("ATLASSIAN_API_TOKEN")
    domain = os.getenv("ATLASSIAN_DOMAIN")  # e.g. "mycompany.atlassian.net"

    missing = []
    if not email:
        missing.append("ATLASSIAN_EMAIL")
    if not token:
        missing.append("ATLASSIAN_API_TOKEN")
    if not domain:
        missing.append("ATLASSIAN_DOMAIN")

    if missing:
        raise ValueError(
            f"\n❌  Missing Atlassian env vars: {', '.join(missing)}\n"
            "   See README_SETUP.md Step 3 for how to get your API token.\n"
        )
    return email, token, domain


def _jira(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated Jira REST API v3 call."""
    email, token, domain = _get_auth()
    url = f"https://{domain}/rest/api/3{path}"
    resp = requests.request(
        method, url,
        auth=HTTPBasicAuth(email, token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        **kwargs,
    )
    if resp.status_code == 204:
        return {"status": "success"}
    if not resp.ok:
        raise RuntimeError(f"Jira API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def _confluence(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated Confluence REST API v2 call."""
    email, token, domain = _get_auth()
    url = f"https://{domain}/wiki/api/v2{path}"
    resp = requests.request(
        method, url,
        auth=HTTPBasicAuth(email, token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        **kwargs,
    )
    if resp.status_code == 204:
        return {"status": "success"}
    if not resp.ok:
        raise RuntimeError(f"Confluence API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()


# ─────────────────────────────────────────────
# JIRA — Issues
# ─────────────────────────────────────────────

def _jira_search(jql: str, fields: str, max_results: int) -> dict:
    """
    Run a JQL search using the new /search/jql POST endpoint (required since 2025).
    Falls back to GET /search for older instances.
    """
    payload = {
        "jql": jql,
        "maxResults": min(max_results, 50),
        "fields": [f.strip() for f in fields.split(",")],
    }
    try:
        return _jira("POST", "/search/jql", json=payload)
    except RuntimeError as e:
        # Fallback: old GET endpoint (on-premise Jira may still support it)
        if "410" in str(e) or "404" in str(e):
            return _jira(
                "GET",
                f"/search?jql={requests.utils.quote(jql)}&maxResults={min(max_results, 50)}"
                f"&fields={fields}",
            )
        raise


def get_my_jira_issues(max_results: int = 20, status: str = None) -> list[dict]:
    """
    Get Jira issues assigned to the current user.

    Args:
        max_results: How many issues to return
        status:      Filter by status e.g. 'In Progress', 'To Do', 'Done'

    Returns:
        List of issue dicts: key, summary, status, priority, dueDate, updated
    """
    jql = "assignee = currentUser()"
    if status:
        # Normalise common aliases
        status_map = {"open": "To Do", "todo": "To Do", "done": "Done", "closed": "Done"}
        mapped = status_map.get(status.lower(), status)
        jql += f" AND status = \"{mapped}\""
    jql += " ORDER BY updated DESC"

    data = _jira_search(jql, "summary,status,priority,duedate,updated,assignee,reporter", max_results)
    issues = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {})
        issues.append({
            "key": issue.get("key"),
            "summary": fields.get("summary"),
            "status": (fields.get("status") or {}).get("name"),
            "priority": (fields.get("priority") or {}).get("name"),
            "dueDate": fields.get("duedate"),
            "updated": fields.get("updated"),
        })
    return issues


def search_jira(jql: str, max_results: int = 20) -> list[dict]:
    """
    Search Jira issues with a JQL query.

    Args:
        jql:         JQL query string e.g. 'project = MYPROJECT AND status != Done'
        max_results: Max issues to return

    Returns:
        List of issue dicts: key, summary, status, assignee, priority, updated
    """
    data = _jira_search(jql, "summary,status,priority,updated,assignee", max_results)
    issues = []
    for issue in data.get("issues", []):
        fields = issue.get("fields", {})
        assignee = fields.get("assignee") or {}
        issues.append({
            "key": issue.get("key"),
            "summary": fields.get("summary"),
            "status": (fields.get("status") or {}).get("name"),
            "priority": (fields.get("priority") or {}).get("name"),
            "assignee": assignee.get("displayName", "Unassigned"),
            "updated": fields.get("updated"),
        })
    return issues


def get_jira_issue(issue_key: str) -> dict:
    """
    Get full details of a Jira issue.

    Args:
        issue_key: e.g. 'PROJ-123'

    Returns:
        Full issue dict including description, comments count, subtasks
    """
    data = _jira(
        "GET",
        f"/issue/{issue_key}?fields=summary,description,status,priority,assignee,"
        "reporter,duedate,created,updated,comment,subtasks,issuetype,labels",
    )
    fields = data.get("fields", {})

    # Extract description text from Atlassian Document Format (ADF)
    desc = fields.get("description") or {}
    desc_text = _adf_to_text(desc) if desc else "(no description)"

    return {
        "key": data.get("key"),
        "summary": fields.get("summary"),
        "description": desc_text,
        "status": (fields.get("status") or {}).get("name"),
        "priority": (fields.get("priority") or {}).get("name"),
        "issueType": (fields.get("issuetype") or {}).get("name"),
        "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
        "reporter": (fields.get("reporter") or {}).get("displayName"),
        "dueDate": fields.get("duedate"),
        "labels": fields.get("labels", []),
        "commentCount": (fields.get("comment") or {}).get("total", 0),
        "subtasks": [(s.get("key"), s.get("fields", {}).get("summary")) for s in fields.get("subtasks", [])],
    }


def create_jira_issue(
    project_key: str,
    summary: str,
    description: str = "",
    issue_type: str = "Task",
    priority: str = "Medium",
    assignee_email: str = None,
    labels: list[str] = None,
    due_date: str = None,
) -> dict:
    """
    Create a new Jira issue.

    Args:
        project_key:    Project key e.g. 'PROJ'
        summary:        Issue title
        description:    Issue description (plain text)
        issue_type:     'Task', 'Bug', 'Story', 'Epic', 'Sub-task'
        priority:       'Highest', 'High', 'Medium', 'Low', 'Lowest'
        assignee_email: Email to assign to (leave None for unassigned)
        labels:         List of label strings
        due_date:       Due date in 'YYYY-MM-DD' format

    Returns:
        {"status": "created", "key": "PROJ-123", "url": "..."}
    """
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
            "description": {
                "version": 1,
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
            } if description else None,
        }
    }

    if labels:
        payload["fields"]["labels"] = labels
    if due_date:
        payload["fields"]["duedate"] = due_date

    # Look up account ID for assignee
    if assignee_email:
        try:
            users = _jira("GET", f"/user/search?query={assignee_email}")
            if users:
                payload["fields"]["assignee"] = {"accountId": users[0]["accountId"]}
        except Exception:
            pass  # Assign silently fails — issue still created

    result = _jira("POST", "/issue", json=payload)
    _, _, domain = _get_auth()
    issue_key = result.get("key")
    return {
        "status": "created",
        "key": issue_key,
        "url": f"https://{domain}/browse/{issue_key}",
    }


def update_jira_issue(
    issue_key: str,
    summary: str = None,
    description: str = None,
    priority: str = None,
    labels: list[str] = None,
    due_date: str = None,
) -> dict:
    """
    Update fields on an existing Jira issue.

    Returns:
        {"status": "updated", "key": issue_key}
    """
    fields = {}
    if summary:
        fields["summary"] = summary
    if description:
        fields["description"] = {
            "version": 1, "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
        }
    if priority:
        fields["priority"] = {"name": priority}
    if labels is not None:
        fields["labels"] = labels
    if due_date:
        fields["duedate"] = due_date

    if not fields:
        return {"status": "no_changes"}

    _jira("PUT", f"/issue/{issue_key}", json={"fields": fields})
    return {"status": "updated", "key": issue_key}


def transition_jira_issue(issue_key: str, transition_name: str) -> dict:
    """
    Move a Jira issue to a different status.

    Args:
        issue_key:       e.g. 'PROJ-123'
        transition_name: e.g. 'In Progress', 'Done', 'In Review'

    Returns:
        {"status": "transitioned", "key": issue_key, "new_status": transition_name}
    """
    transitions = _jira("GET", f"/issue/{issue_key}/transitions")
    transition_id = None
    for t in transitions.get("transitions", []):
        if t.get("name", "").lower() == transition_name.lower():
            transition_id = t.get("id")
            break

    if not transition_id:
        available = [t.get("name") for t in transitions.get("transitions", [])]
        raise ValueError(f"Transition '{transition_name}' not found. Available: {available}")

    _jira("POST", f"/issue/{issue_key}/transitions", json={"transition": {"id": transition_id}})
    return {"status": "transitioned", "key": issue_key, "new_status": transition_name}


def add_jira_comment(issue_key: str, comment: str) -> dict:
    """
    Add a comment to a Jira issue.

    Args:
        issue_key: e.g. 'PROJ-123'
        comment:   Comment text

    Returns:
        {"status": "commented", "key": issue_key, "comment_id": id}
    """
    result = _jira(
        "POST",
        f"/issue/{issue_key}/comment",
        json={
            "body": {
                "version": 1, "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}],
            }
        },
    )
    return {"status": "commented", "key": issue_key, "comment_id": result.get("id")}


def get_jira_projects() -> list[dict]:
    """List all accessible Jira projects."""
    data = _jira("GET", "/project?expand=description&maxResults=50")
    return [{"key": p.get("key"), "name": p.get("name"), "id": p.get("id")} for p in data]


# ─────────────────────────────────────────────
# CONFLUENCE — Pages
# ─────────────────────────────────────────────

def search_confluence(query: str, max_results: int = 10) -> list[dict]:
    """
    Search Confluence pages and blog posts.

    Args:
        query:       Search term
        max_results: Max results

    Returns:
        List of results: id, title, space, url, excerpt
    """
    data = _confluence(
        "GET",
        f"/pages?title={requests.utils.quote(query)}&limit={min(max_results, 25)}"
        f"&body-format=none",
    )
    results = []
    for page in data.get("results", []):
        _, _, domain = _get_auth()
        results.append({
            "id": page.get("id"),
            "title": page.get("title"),
            "spaceId": page.get("spaceId"),
            "url": f"https://{domain}/wiki{page.get('_links', {}).get('webui', '')}",
            "version": (page.get("version") or {}).get("number"),
        })
    return results


def get_confluence_page(page_id: str) -> dict:
    """
    Get the content of a Confluence page.

    Returns:
        {"id": ..., "title": ..., "content": plain_text, "version": n, "url": ...}
    """
    data = _confluence("GET", f"/pages/{page_id}?body-format=storage")
    _, _, domain = _get_auth()
    body = data.get("body", {}).get("storage", {}).get("value", "")
    # Strip XML/HTML tags for readable text
    import re
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    return {
        "id": data.get("id"),
        "title": data.get("title"),
        "content": text,
        "version": (data.get("version") or {}).get("number", 1),
        "url": f"https://{domain}/wiki{data.get('_links', {}).get('webui', '')}",
    }


def create_confluence_page(
    space_id: str,
    title: str,
    content: str,
    parent_id: str = None,
) -> dict:
    """
    Create a new Confluence page.

    Args:
        space_id:  Space ID (get from list_confluence_spaces)
        title:     Page title
        content:   Page body in plain text (will be wrapped in Confluence storage format)
        parent_id: Optional parent page ID (for nested pages)

    Returns:
        {"status": "created", "id": page_id, "url": url}
    """
    # Convert plain text to Confluence storage format (basic HTML-like)
    storage_body = _text_to_confluence_storage(content)

    payload = {
        "spaceId": space_id,
        "title": title,
        "body": {
            "representation": "storage",
            "value": storage_body,
        },
    }
    if parent_id:
        payload["parentId"] = parent_id

    result = _confluence("POST", "/pages", json=payload)
    _, _, domain = _get_auth()
    return {
        "status": "created",
        "id": result.get("id"),
        "url": f"https://{domain}/wiki{result.get('_links', {}).get('webui', '')}",
    }


def update_confluence_page(
    page_id: str,
    new_content: str,
    title: str = None,
    append: bool = False,
) -> dict:
    """
    Update an existing Confluence page.

    Args:
        page_id:     ID of page to update
        new_content: New page content (plain text)
        title:       New title (leave None to keep existing)
        append:      If True, append new_content to existing page instead of replacing

    Returns:
        {"status": "updated", "id": page_id, "version": new_version}
    """
    # Get current page to get version number (required for update)
    current = _confluence("GET", f"/pages/{page_id}?body-format=storage")
    current_version = (current.get("version") or {}).get("number", 1)
    current_title = current.get("title", "Untitled")

    if append:
        existing_body = current.get("body", {}).get("storage", {}).get("value", "")
        storage_body = existing_body + "\n" + _text_to_confluence_storage(new_content)
    else:
        storage_body = _text_to_confluence_storage(new_content)

    payload = {
        "id": page_id,
        "status": "current",
        "title": title or current_title,
        "version": {"number": current_version + 1},
        "body": {
            "representation": "storage",
            "value": storage_body,
        },
    }

    result = _confluence("PUT", f"/pages/{page_id}", json=payload)
    return {
        "status": "updated",
        "id": page_id,
        "version": (result.get("version") or {}).get("number"),
    }


def list_confluence_spaces() -> list[dict]:
    """List all accessible Confluence spaces."""
    data = _confluence("GET", "/spaces?limit=50&status=current")
    return [
        {"id": s.get("id"), "key": s.get("key"), "name": s.get("name")}
        for s in data.get("results", [])
    ]


def get_space_pages(space_id: str, max_results: int = 20) -> list[dict]:
    """List pages in a Confluence space."""
    data = _confluence("GET", f"/pages?spaceId={space_id}&limit={min(max_results, 50)}&body-format=none")
    _, _, domain = _get_auth()
    return [
        {
            "id": p.get("id"),
            "title": p.get("title"),
            "url": f"https://{domain}/wiki{p.get('_links', {}).get('webui', '')}",
        }
        for p in data.get("results", [])
    ]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _adf_to_text(adf_node: dict, depth: int = 0) -> str:
    """
    Recursively extract plain text from Atlassian Document Format (ADF) JSON.
    Used to convert Jira issue descriptions to readable text.
    """
    if not isinstance(adf_node, dict):
        return ""

    node_type = adf_node.get("type", "")
    text = ""

    # Leaf text node
    if node_type == "text":
        return adf_node.get("text", "")

    # Recurse into content
    for child in adf_node.get("content", []):
        text += _adf_to_text(child, depth + 1)

    # Add newlines for block elements
    if node_type in ("paragraph", "heading", "bulletList", "orderedList", "listItem", "blockquote"):
        text = text.strip() + "\n"

    return text


def _text_to_confluence_storage(text: str) -> str:
    """
    Convert plain text to Confluence storage format (basic XHTML).
    Handles newlines as paragraph breaks and preserves code blocks (``` fences).
    """
    lines = text.split("\n")
    html_parts = []
    in_code = False
    code_block = []

    for line in lines:
        if line.startswith("```"):
            if in_code:
                # End code block
                code_content = "\n".join(code_block)
                html_parts.append(
                    f'<ac:structured-macro ac:name="code">'
                    f'<ac:plain-text-body><![CDATA[{code_content}]]></ac:plain-text-body>'
                    f'</ac:structured-macro>'
                )
                code_block = []
                in_code = False
            else:
                in_code = True
        elif in_code:
            code_block.append(line)
        elif line.startswith("# "):
            html_parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- ") or line.startswith("* "):
            html_parts.append(f"<ul><li>{line[2:]}</li></ul>")
        elif line.strip():
            import html as html_module
            escaped = html_module.escape(line)
            html_parts.append(f"<p>{escaped}</p>")
        else:
            html_parts.append("<p></p>")

    return "\n".join(html_parts)
