"""
github_tool.py — GitHub Tools
================================
Covers: notifications, pull requests, CI checks, issues, repos, code review
Auth:   Personal Access Token (PAT) from https://github.com/settings/tokens
        Set GITHUB_TOKEN in .env — needs scopes: repo, notifications, read:user
API:    GitHub REST v3  (https://api.github.com)
"""

import os
import requests
from typing import Optional

GITHUB_BASE = "https://api.github.com"


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

def _gh(method: str, path: str, **kwargs) -> any:
    """Make an authenticated GitHub API call. Returns parsed JSON."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError(
            "\n❌  GITHUB_TOKEN not set in .env\n"
            "   Create one at: https://github.com/settings/tokens\n"
            "   Required scopes: repo, notifications, read:user\n"
        )
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.request(method, f"{GITHUB_BASE}{path}", headers=headers, **kwargs)
    if resp.status_code == 204:
        return {"status": "success"}
    if not resp.ok:
        raise RuntimeError(f"GitHub API error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def _default_owner() -> str:
    """Return the authenticated user's GitHub login."""
    data = _gh("GET", "/user")
    return data.get("login", "")


# ─────────────────────────────────────────────
# NOTIFICATIONS
# ─────────────────────────────────────────────

def get_github_notifications(unread_only: bool = True, max_count: int = 20) -> list[dict]:
    """
    Get GitHub notifications (PRs, issues, mentions, CI failures etc.)

    Args:
        unread_only: If True, only return unread notifications
        max_count:   Max notifications to return

    Returns:
        List of notification dicts: id, title, type, repo, reason, updated_at, url
    """
    params = {"all": not unread_only, "per_page": min(max_count, 50)}
    data = _gh("GET", "/notifications", params=params)
    results = []
    for n in data:
        subject = n.get("subject", {})
        results.append({
            "id":         n.get("id"),
            "title":      subject.get("title"),
            "type":       subject.get("type"),           # PullRequest, Issue, Release…
            "repo":       n.get("repository", {}).get("full_name"),
            "reason":     n.get("reason"),               # review_requested, mention, assign…
            "unread":     n.get("unread"),
            "updated_at": n.get("updated_at"),
            "url":        subject.get("url", "").replace("api.github.com/repos", "github.com").replace("/pulls/", "/pull/"),
        })
    return results


def mark_notification_read(notification_id: str) -> dict:
    """Mark a single GitHub notification as read."""
    _gh("PATCH", f"/notifications/threads/{notification_id}")
    return {"status": "marked_read", "id": notification_id}


# ─────────────────────────────────────────────
# REPOSITORIES
# ─────────────────────────────────────────────

def list_my_repos(visibility: str = "all", max_count: int = 30) -> list[dict]:
    """
    List the authenticated user's repositories.

    Args:
        visibility: 'all', 'public', or 'private'
        max_count:  Max repos to return

    Returns:
        List of repo dicts: name, full_name, description, language, stars, open_issues, updated_at, url
    """
    params = {"visibility": visibility, "sort": "updated", "per_page": min(max_count, 100)}
    data = _gh("GET", "/user/repos", params=params)
    return [
        {
            "name":         r.get("name"),
            "full_name":    r.get("full_name"),
            "description":  r.get("description", ""),
            "language":     r.get("language"),
            "stars":        r.get("stargazers_count", 0),
            "open_issues":  r.get("open_issues_count", 0),
            "updated_at":   r.get("updated_at"),
            "url":          r.get("html_url"),
            "default_branch": r.get("default_branch", "main"),
        }
        for r in data
    ]


# ─────────────────────────────────────────────
# PULL REQUESTS
# ─────────────────────────────────────────────

def list_pull_requests(
    repo: str,
    state: str = "open",
    max_count: int = 20,
) -> list[dict]:
    """
    List pull requests in a repository.

    Args:
        repo:      Repository in 'owner/repo' format e.g. 'myorg/myapp'
        state:     'open', 'closed', or 'all'
        max_count: Max PRs to return

    Returns:
        List of PR dicts: number, title, author, state, created_at, updated_at, url, draft, review_count
    """
    params = {"state": state, "per_page": min(max_count, 50), "sort": "updated"}
    data = _gh("GET", f"/repos/{repo}/pulls", params=params)
    return [
        {
            "number":       pr.get("number"),
            "title":        pr.get("title"),
            "author":       pr.get("user", {}).get("login"),
            "state":        pr.get("state"),
            "draft":        pr.get("draft", False),
            "created_at":   pr.get("created_at"),
            "updated_at":   pr.get("updated_at"),
            "url":          pr.get("html_url"),
            "labels":       [l["name"] for l in pr.get("labels", [])],
            "review_count": pr.get("review_comments", 0),
            "base_branch":  pr.get("base", {}).get("ref"),
            "head_branch":  pr.get("head", {}).get("ref"),
        }
        for pr in data
    ]


def get_pull_request(repo: str, pr_number: int) -> dict:
    """
    Get full details of a pull request including files changed and review status.

    Args:
        repo:      'owner/repo' format
        pr_number: PR number

    Returns:
        Full PR dict with body, changed files, review status, CI checks summary
    """
    pr = _gh("GET", f"/repos/{repo}/pulls/{pr_number}")
    files_data = _gh("GET", f"/repos/{repo}/pulls/{pr_number}/files")
    reviews_data = _gh("GET", f"/repos/{repo}/pulls/{pr_number}/reviews")

    files_changed = [
        {
            "filename": f.get("filename"),
            "status":   f.get("status"),        # added, modified, removed
            "additions": f.get("additions", 0),
            "deletions": f.get("deletions", 0),
        }
        for f in files_data
    ]

    reviews = [
        {
            "reviewer": r.get("user", {}).get("login"),
            "state":    r.get("state"),          # APPROVED, CHANGES_REQUESTED, COMMENTED
            "submitted_at": r.get("submitted_at"),
        }
        for r in reviews_data
    ]

    return {
        "number":       pr.get("number"),
        "title":        pr.get("title"),
        "author":       pr.get("user", {}).get("login"),
        "state":        pr.get("state"),
        "draft":        pr.get("draft"),
        "body":         (pr.get("body") or "")[:1000],
        "url":          pr.get("html_url"),
        "base_branch":  pr.get("base", {}).get("ref"),
        "head_branch":  pr.get("head", {}).get("ref"),
        "mergeable":    pr.get("mergeable"),
        "additions":    pr.get("additions", 0),
        "deletions":    pr.get("deletions", 0),
        "changed_files": pr.get("changed_files", 0),
        "files":        files_changed[:20],      # First 20 files
        "reviews":      reviews,
        "labels":       [l["name"] for l in pr.get("labels", [])],
        "created_at":   pr.get("created_at"),
        "updated_at":   pr.get("updated_at"),
    }


def get_pr_checks(repo: str, pr_number: int) -> dict:
    """
    Get CI/CD check results for a pull request.

    Args:
        repo:      'owner/repo' format
        pr_number: PR number

    Returns:
        {"overall": "success|failure|pending", "checks": [{name, status, conclusion, url}]}
    """
    pr = _gh("GET", f"/repos/{repo}/pulls/{pr_number}")
    sha = pr.get("head", {}).get("sha", "")
    if not sha:
        return {"overall": "unknown", "checks": []}

    data = _gh("GET", f"/repos/{repo}/commits/{sha}/check-runs")
    checks = []
    for run in data.get("check_runs", []):
        checks.append({
            "name":       run.get("name"),
            "status":     run.get("status"),        # queued, in_progress, completed
            "conclusion": run.get("conclusion"),    # success, failure, skipped, cancelled
            "started_at": run.get("started_at"),
            "url":        run.get("html_url"),
        })

    # Overall status
    conclusions = [c["conclusion"] for c in checks if c["conclusion"]]
    if "failure" in conclusions or "timed_out" in conclusions:
        overall = "failure"
    elif all(c == "success" or c == "skipped" for c in conclusions) and conclusions:
        overall = "success"
    else:
        overall = "pending"

    return {"overall": overall, "checks": checks}


def add_pr_review(
    repo: str,
    pr_number: int,
    body: str,
    event: str = "COMMENT",
) -> dict:
    """
    Submit a review on a pull request.

    Args:
        repo:      'owner/repo' format
        pr_number: PR number
        body:      Review comment text
        event:     'COMMENT', 'APPROVE', or 'REQUEST_CHANGES'

    Returns:
        {"status": "reviewed", "event": event, "url": url}
    """
    result = _gh(
        "POST",
        f"/repos/{repo}/pulls/{pr_number}/reviews",
        json={"body": body, "event": event},
    )
    return {
        "status": "reviewed",
        "event": event,
        "url": result.get("html_url", ""),
        "id": result.get("id"),
    }


def merge_pull_request(
    repo: str,
    pr_number: int,
    commit_message: str = "",
    merge_method: str = "squash",
) -> dict:
    """
    Merge a pull request.

    Args:
        repo:           'owner/repo' format
        pr_number:      PR number
        commit_message: Optional custom merge commit message
        merge_method:   'merge', 'squash', or 'rebase'

    Returns:
        {"status": "merged", "sha": commit_sha}
    """
    payload = {"merge_method": merge_method}
    if commit_message:
        payload["commit_message"] = commit_message

    result = _gh("PUT", f"/repos/{repo}/pulls/{pr_number}/merge", json=payload)
    return {
        "status": "merged" if result.get("merged") else "failed",
        "sha": result.get("sha"),
        "message": result.get("message"),
    }


# ─────────────────────────────────────────────
# ISSUES
# ─────────────────────────────────────────────

def list_my_github_issues(max_count: int = 20) -> list[dict]:
    """
    List GitHub issues assigned to the current user across all repos.

    Returns:
        List of issue dicts: number, title, repo, state, labels, url, updated_at
    """
    params = {"filter": "assigned", "state": "open", "per_page": min(max_count, 50)}
    data = _gh("GET", "/issues", params=params)
    return [
        {
            "number":     i.get("number"),
            "title":      i.get("title"),
            "repo":       i.get("repository", {}).get("full_name", ""),
            "state":      i.get("state"),
            "labels":     [l["name"] for l in i.get("labels", [])],
            "url":        i.get("html_url"),
            "updated_at": i.get("updated_at"),
            "comments":   i.get("comments", 0),
        }
        for i in data
        if "pull_request" not in i   # Exclude PRs (GitHub returns both from /issues)
    ]


def search_github(query: str, search_type: str = "issues", max_count: int = 15) -> list[dict]:
    """
    Search GitHub for issues, PRs, or code.

    Args:
        query:       Search query e.g. 'is:pr is:open review-requested:@me'
        search_type: 'issues', 'repositories', or 'code'
        max_count:   Max results

    Returns:
        List of result dicts
    """
    params = {"q": query, "per_page": min(max_count, 30)}
    data = _gh("GET", f"/search/{search_type}", params=params)
    items = data.get("items", [])

    if search_type == "issues":
        return [
            {
                "number":   i.get("number"),
                "title":    i.get("title"),
                "type":     "PR" if "pull_request" in i else "Issue",
                "repo":     i.get("repository_url", "").split("/repos/")[-1],
                "state":    i.get("state"),
                "url":      i.get("html_url"),
                "updated":  i.get("updated_at"),
            }
            for i in items
        ]
    elif search_type == "repositories":
        return [
            {
                "name":        r.get("full_name"),
                "description": r.get("description", ""),
                "stars":       r.get("stargazers_count", 0),
                "language":    r.get("language"),
                "url":         r.get("html_url"),
            }
            for r in items
        ]
    return items


def create_github_issue(
    repo: str,
    title: str,
    body: str = "",
    labels: list[str] = None,
    assignees: list[str] = None,
) -> dict:
    """
    Create a new GitHub issue.

    Args:
        repo:      'owner/repo' format
        title:     Issue title
        body:      Issue description (markdown supported)
        labels:    List of label strings
        assignees: List of GitHub usernames to assign

    Returns:
        {"status": "created", "number": n, "url": url}
    """
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    if assignees:
        payload["assignees"] = assignees

    result = _gh("POST", f"/repos/{repo}/issues", json=payload)
    return {
        "status": "created",
        "number": result.get("number"),
        "url":    result.get("html_url"),
    }


def get_repo_workflow_runs(repo: str, max_count: int = 10) -> list[dict]:
    """
    Get recent GitHub Actions workflow runs for a repo (CI/CD pipeline status).

    Returns:
        List of runs: workflow, status, conclusion, branch, triggered_by, url
    """
    params = {"per_page": min(max_count, 30)}
    data = _gh("GET", f"/repos/{repo}/actions/runs", params=params)
    return [
        {
            "id":           run.get("id"),
            "workflow":     run.get("name"),
            "status":       run.get("status"),        # queued, in_progress, completed
            "conclusion":   run.get("conclusion"),    # success, failure, cancelled
            "branch":       run.get("head_branch"),
            "triggered_by": run.get("triggering_actor", {}).get("login", ""),
            "created_at":   run.get("created_at"),
            "url":          run.get("html_url"),
        }
        for run in data.get("workflow_runs", [])
    ]


def get_my_open_prs(max_count: int = 20) -> list[dict]:
    """
    Get all open pull requests authored by the current user across ALL repositories.

    Use this when the user asks "list my open PRs", "what PRs do I have open",
    "show my pull requests" — i.e. without specifying a particular repo.

    Returns:
        List of PR dicts: number, title, repo, state, url, created_at, updated_at
    """
    login = _default_owner()
    query = f"is:pr is:open author:{login}"
    return search_github(query, search_type="issues", max_count=max_count)


def get_my_review_requests(max_count: int = 20) -> list[dict]:
    """
    Get all PRs where the current user's review has been requested.

    Returns:
        List of PRs needing your review
    """
    login = _default_owner()
    query = f"is:pr is:open review-requested:{login}"
    return search_github(query, search_type="issues", max_count=max_count)
