"""
linear_tool.py — Linear Issue Tracker Tools
=============================================
Covers: issues, teams, workflow states, projects, cycles, comments
Auth:   Linear Personal API Key from https://linear.app/settings/api
        Set LINEAR_API_KEY in .env
API:    Linear GraphQL API  (https://api.linear.app/graphql)
"""

import os
import requests
from typing import Optional

LINEAR_GQL = "https://api.linear.app/graphql"


# ─────────────────────────────────────────────
# AUTH + QUERY
# ─────────────────────────────────────────────

def _query(gql: str, variables: dict = None) -> dict:
    """Run a Linear GraphQL query/mutation."""
    token = os.getenv("LINEAR_API_KEY")
    if not token:
        raise ValueError(
            "\n❌  LINEAR_API_KEY not set in .env\n"
            "   Get your key at: https://linear.app/settings/api\n"
            "   Click 'Personal API keys' → Create key\n"
        )
    resp = requests.post(
        LINEAR_GQL,
        headers={"Authorization": token, "Content-Type": "application/json"},
        json={"query": gql, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    if "errors" in result:
        raise RuntimeError(f"Linear GraphQL error: {result['errors']}")
    return result.get("data", {})


# ─────────────────────────────────────────────
# VIEWER (ME)
# ─────────────────────────────────────────────

def get_linear_me() -> dict:
    """Get the current Linear user's profile."""
    data = _query("""
        query { viewer { id name email displayName } }
    """)
    return data.get("viewer", {})


# ─────────────────────────────────────────────
# TEAMS
# ─────────────────────────────────────────────

def list_linear_teams() -> list[dict]:
    """
    List all Linear teams the user is a member of.

    Returns:
        List of team dicts: id, name, key, description
    """
    data = _query("""
        query {
            teams {
                nodes { id name key description }
            }
        }
    """)
    return data.get("teams", {}).get("nodes", [])


def list_linear_workflow_states(team_id: str) -> list[dict]:
    """
    List all workflow states (columns) for a Linear team.

    Returns:
        List of state dicts: id, name, type, color, position
    """
    data = _query("""
        query($teamId: String!) {
            workflowStates(filter: { team: { id: { eq: $teamId } } }) {
                nodes { id name type color position }
            }
        }
    """, {"teamId": team_id})
    states = data.get("workflowStates", {}).get("nodes", [])
    return sorted(states, key=lambda s: s.get("position", 0))


# ─────────────────────────────────────────────
# ISSUES
# ─────────────────────────────────────────────

_ISSUE_FIELDS = """
    id identifier title description
    state { id name type color }
    assignee { id name displayName email }
    creator { id name displayName }
    priority priorityLabel
    dueDate createdAt updatedAt completedAt
    team { id name key }
    labels { nodes { id name color } }
    url
    estimate
    cycleState
"""


def get_my_linear_issues(state_type: str = None, max_count: int = 25) -> list[dict]:
    """
    Get Linear issues assigned to the current user.

    Args:
        state_type: Filter by state type — 'started', 'unstarted', 'completed', 'cancelled', 'backlog'
        max_count:  Max issues to return

    Returns:
        List of issue dicts with full details
    """
    filter_clause = 'filter: { assignee: { isMe: { eq: true } }'
    if state_type:
        filter_clause += f', state: {{ type: {{ eq: {state_type.upper()} }} }}'
    filter_clause += ' }'

    data = _query(f"""
        query($first: Int) {{
            issues({filter_clause}, first: $first, orderBy: updatedAt) {{
                nodes {{
                    {_ISSUE_FIELDS}
                }}
            }}
        }}
    """, {"first": min(max_count, 50)})

    return _format_issues(data.get("issues", {}).get("nodes", []))


def search_linear_issues(query_str: str, max_count: int = 20) -> list[dict]:
    """
    Search Linear issues by keyword.

    Args:
        query_str: Search term
        max_count: Max results

    Returns:
        List of matching issue dicts
    """
    data = _query("""
        query($term: String!, $first: Int) {
            issueSearch(query: $term, first: $first, orderBy: updatedAt) {
                nodes {
                    id identifier title
                    state { name type }
                    assignee { displayName }
                    priority priorityLabel
                    team { name key }
                    url updatedAt
                }
            }
        }
    """, {"term": query_str, "first": min(max_count, 50)})

    nodes = data.get("issueSearch", {}).get("nodes", [])
    return [
        {
            "id":         n.get("id"),
            "identifier": n.get("identifier"),
            "title":      n.get("title"),
            "state":      (n.get("state") or {}).get("name"),
            "assignee":   (n.get("assignee") or {}).get("displayName", "Unassigned"),
            "priority":   n.get("priorityLabel"),
            "team":       (n.get("team") or {}).get("name"),
            "url":        n.get("url"),
            "updated_at": n.get("updatedAt"),
        }
        for n in nodes
    ]


def get_linear_issue(issue_id: str) -> dict:
    """
    Get full details of a Linear issue by ID or identifier (e.g. 'TEAM-123').

    Returns:
        Full issue dict including description, labels, comments
    """
    # Accept both UUID and identifier like "ENG-42"
    if "-" in issue_id and not issue_id.startswith("issue_") and len(issue_id) < 20:
        # Looks like an identifier — search for it
        results = search_linear_issues(issue_id, max_count=5)
        if results:
            issue_id = results[0]["id"]
        else:
            raise ValueError(f"Issue not found: {issue_id}")

    data = _query(f"""
        query($id: String!) {{
            issue(id: $id) {{
                {_ISSUE_FIELDS}
                comments {{
                    nodes {{
                        id body createdAt user {{ displayName }}
                    }}
                }}
            }}
        }}
    """, {"id": issue_id})

    issue = data.get("issue", {})
    if not issue:
        raise ValueError(f"Issue not found: {issue_id}")

    return _format_issue(issue, include_comments=True)


def create_linear_issue(
    team_id: str,
    title: str,
    description: str = "",
    priority: int = 0,
    assignee_id: str = None,
    label_ids: list[str] = None,
    due_date: str = None,
    estimate: int = None,
) -> dict:
    """
    Create a new Linear issue.

    Args:
        team_id:     Team ID (get from list_linear_teams)
        title:       Issue title
        description: Issue description (markdown supported)
        priority:    0=No priority, 1=Urgent, 2=High, 3=Medium, 4=Low
        assignee_id: User ID to assign (optional)
        label_ids:   List of label IDs
        due_date:    Due date 'YYYY-MM-DD'
        estimate:    Story points estimate

    Returns:
        {"status": "created", "id": ..., "identifier": ..., "url": ...}
    """
    input_fields = {
        "teamId": team_id,
        "title": title,
        "description": description,
        "priority": priority,
    }
    if assignee_id:
        input_fields["assigneeId"] = assignee_id
    if label_ids:
        input_fields["labelIds"] = label_ids
    if due_date:
        input_fields["dueDate"] = due_date
    if estimate is not None:
        input_fields["estimate"] = estimate

    data = _query("""
        mutation($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id identifier title url
                    state { name }
                    team { name }
                }
            }
        }
    """, {"input": input_fields})

    result = data.get("issueCreate", {})
    if not result.get("success"):
        raise RuntimeError("Failed to create Linear issue")

    issue = result.get("issue", {})
    return {
        "status": "created",
        "id":         issue.get("id"),
        "identifier": issue.get("identifier"),
        "title":      issue.get("title"),
        "team":       (issue.get("team") or {}).get("name"),
        "state":      (issue.get("state") or {}).get("name"),
        "url":        issue.get("url"),
    }


def update_linear_issue(
    issue_id: str,
    title: str = None,
    description: str = None,
    state_id: str = None,
    priority: int = None,
    assignee_id: str = None,
    due_date: str = None,
    estimate: int = None,
) -> dict:
    """
    Update an existing Linear issue.

    Returns:
        {"status": "updated", "id": ..., "identifier": ..., "url": ...}
    """
    # Resolve identifier to UUID if needed
    if "-" in issue_id and len(issue_id) < 20:
        results = search_linear_issues(issue_id, max_count=3)
        if results:
            issue_id = results[0]["id"]

    input_fields = {}
    if title is not None:        input_fields["title"] = title
    if description is not None:  input_fields["description"] = description
    if state_id is not None:     input_fields["stateId"] = state_id
    if priority is not None:     input_fields["priority"] = priority
    if assignee_id is not None:  input_fields["assigneeId"] = assignee_id
    if due_date is not None:     input_fields["dueDate"] = due_date
    if estimate is not None:     input_fields["estimate"] = estimate

    if not input_fields:
        return {"status": "no_changes"}

    data = _query("""
        mutation($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue { id identifier title url state { name } }
            }
        }
    """, {"id": issue_id, "input": input_fields})

    result = data.get("issueUpdate", {})
    issue = result.get("issue", {})
    return {
        "status": "updated" if result.get("success") else "failed",
        "id":         issue.get("id"),
        "identifier": issue.get("identifier"),
        "url":        issue.get("url"),
    }


def transition_linear_issue(issue_id: str, state_name: str, team_id: str = None) -> dict:
    """
    Move a Linear issue to a different workflow state by name.

    Args:
        issue_id:   Issue ID or identifier e.g. 'ENG-42'
        state_name: State name e.g. 'In Progress', 'Done', 'In Review'
        team_id:    Team ID (needed to look up states — auto-detected if not provided)

    Returns:
        {"status": "transitioned", "identifier": ..., "new_state": ...}
    """
    # Resolve identifier
    if "-" in issue_id and len(issue_id) < 20:
        results = search_linear_issues(issue_id, max_count=3)
        if not results:
            raise ValueError(f"Issue not found: {issue_id}")
        resolved = results[0]
        issue_id = resolved["id"]
        if not team_id:
            # Get team from the issue
            teams = list_linear_teams()
            for t in teams:
                if t["name"] == resolved.get("team"):
                    team_id = t["id"]
                    break

    if not team_id:
        # Fall back: get team from issue details
        issue_data = _query("""
            query($id: String!) { issue(id: $id) { team { id } } }
        """, {"id": issue_id})
        team_id = (issue_data.get("issue", {}).get("team") or {}).get("id")

    # Find the state ID
    states = list_linear_workflow_states(team_id) if team_id else []
    state_id = None
    for s in states:
        if s["name"].lower() == state_name.lower():
            state_id = s["id"]
            break

    if not state_id:
        available = [s["name"] for s in states]
        raise ValueError(f"State '{state_name}' not found. Available: {available}")

    result = update_linear_issue(issue_id, state_id=state_id)
    result["new_state"] = state_name
    result["status"] = "transitioned"
    return result


def add_linear_comment(issue_id: str, comment: str) -> dict:
    """
    Add a comment to a Linear issue.

    Returns:
        {"status": "commented", "id": comment_id}
    """
    if "-" in issue_id and len(issue_id) < 20:
        results = search_linear_issues(issue_id, max_count=3)
        if results:
            issue_id = results[0]["id"]

    data = _query("""
        mutation($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) {
                success
                comment { id }
            }
        }
    """, {"issueId": issue_id, "body": comment})

    result = data.get("commentCreate", {})
    return {
        "status": "commented" if result.get("success") else "failed",
        "id": (result.get("comment") or {}).get("id"),
    }


def list_linear_projects(team_id: str = None) -> list[dict]:
    """List Linear projects (optionally filtered by team)."""
    filter_clause = f'filter: {{ teams: {{ id: {{ eq: "{team_id}" }} }} }}' if team_id else ""
    data = _query(f"""
        query {{
            projects({filter_clause}, first: 30) {{
                nodes {{
                    id name description state slugId url
                    progress startDate targetDate
                }}
            }}
        }}
    """)
    return data.get("projects", {}).get("nodes", [])


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _format_issue(node: dict, include_comments: bool = False) -> dict:
    result = {
        "id":          node.get("id"),
        "identifier":  node.get("identifier"),
        "title":       node.get("title"),
        "description": (node.get("description") or "")[:500],
        "state":       (node.get("state") or {}).get("name"),
        "state_type":  (node.get("state") or {}).get("type"),
        "assignee":    (node.get("assignee") or {}).get("displayName", "Unassigned"),
        "priority":    node.get("priorityLabel", "No priority"),
        "due_date":    node.get("dueDate"),
        "team":        (node.get("team") or {}).get("name"),
        "labels":      [l["name"] for l in (node.get("labels") or {}).get("nodes", [])],
        "estimate":    node.get("estimate"),
        "url":         node.get("url"),
        "created_at":  node.get("createdAt"),
        "updated_at":  node.get("updatedAt"),
    }
    if include_comments:
        comments_nodes = (node.get("comments") or {}).get("nodes", [])
        result["comments"] = [
            {
                "author": (c.get("user") or {}).get("displayName", "Unknown"),
                "body":   c.get("body", ""),
                "date":   c.get("createdAt"),
            }
            for c in comments_nodes
        ]
    return result


def _format_issues(nodes: list) -> list[dict]:
    return [_format_issue(n) for n in nodes]
