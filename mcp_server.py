"""
mcp_server.py — Model Context Protocol (MCP) Server
====================================================
Exposes the Work Assistant Agent's tools as an MCP server so that
Claude Desktop (and other MCP clients) can call them directly.

Requires:
    pip install fastmcp

Usage:
    python mcp_server.py          # stdio transport (Claude Desktop)
    python mcp_server.py --http   # HTTP transport (port 8765)

Add to Claude Desktop config (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "work-assistant": {
          "command": "python",
          "args": ["/path/to/work-assistant-agent/mcp_server.py"],
          "env": {
            "DOTENV_PATH": "/path/to/work-assistant-agent/.env"
          }
        }
      }
    }

Environment variables (loaded from .env):
    GEMINI_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY
    MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT_ID  (for M365 tools)
    GITHUB_TOKEN
    JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN
    SLACK_BOT_TOKEN
    LINEAR_API_KEY
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Any

# ── Load .env early (before any tools import) ─────────────────────────────────
from dotenv import load_dotenv

_ENV_PATH = Path(os.getenv("DOTENV_PATH", Path(__file__).parent / ".env"))
load_dotenv(_ENV_PATH, override=False)

# ── Add project root to path ──────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── FastMCP import with graceful fallback ─────────────────────────────────────
try:
    from fastmcp import FastMCP
except ImportError:
    print(
        "FastMCP is not installed.\n"
        "Install it with:  pip install fastmcp\n"
        "Then re-run this script.",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Create MCP server ─────────────────────────────────────────────────────────
mcp = FastMCP(
    name="work-assistant",
    description=(
        "Work Assistant Agent — access email, calendar, GitHub, Jira, "
        "Teams, SharePoint, memory, and analytics tools."
    ),
)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _safe_import(module_path: str):
    """Import a module, returning None on failure."""
    import importlib
    try:
        return importlib.import_module(module_path)
    except Exception as e:
        return None


def _json_result(data: Any) -> str:
    """Serialise result to JSON string (handles non-serialisable objects)."""
    try:
        return json.dumps(data, indent=2, default=str)
    except Exception:
        return str(data)


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_memory_summary() -> str:
    """Return everything the agent has learned and remembered about you."""
    from tools.memory import get_memory_summary as _fn
    return _json_result(_fn())


@mcp.tool()
def update_memory(category: str, key: str, value: str) -> str:
    """
    Store a fact in long-term memory.

    Args:
        category: One of: preferences, people, context, patterns, facts
        key: Fact identifier (e.g. "timezone", "current_sprint")
        value: Value to store (e.g. "BST", "Sprint 14")
    """
    from tools.memory import update_memory_entry
    return _json_result(update_memory_entry(category, key, value))


@mcp.tool()
def clear_memory() -> str:
    """Wipe all stored memory. Use with caution — this cannot be undone."""
    from tools.memory import clear_memory as _fn
    _fn()
    return "Memory cleared successfully."


@mcp.tool()
def search_memory(query: str) -> str:
    """
    Return memory facts most relevant to the query using keyword scoring.

    Args:
        query: Natural language query (e.g. "What sprint are we in?")
    """
    from tools.memory import get_relevant_memory_context
    result = get_relevant_memory_context(query)
    return result if result else "No relevant memory found."


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS & COST TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_analytics(days_back: int = 7) -> str:
    """
    Get work-pattern analytics summary for the last N days.

    Args:
        days_back: Number of days to look back (default 7)
    """
    from tools.analytics import get_analytics_summary
    return _json_result(get_analytics_summary(days_back))


@mcp.tool()
def get_cost_summary(days_back: int = 7) -> str:
    """
    Get LLM API cost summary for the last N days.

    Args:
        days_back: Number of days to look back (default 7)
    """
    from tools.analytics import get_cost_summary as _fn
    return _json_result(_fn(days_back))


# ══════════════════════════════════════════════════════════════════════════════
# GUARDRAIL TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_guardrail_status() -> str:
    """List all security guardrails and their current enabled/disabled state."""
    from tools.guardrails import get_status
    return _json_result(get_status())


@mcp.tool()
def toggle_guardrail(name: str) -> str:
    """
    Toggle a security guardrail on or off.

    Args:
        name: Guardrail name — one of:
              prompt_injection, secret_scrubbing, audit_log,
              bulk_protection, pii_redaction, topic_scope
    """
    from tools.guardrails import toggle
    new_settings = toggle(name)
    state = "enabled" if new_settings.get(name) else "disabled"
    return f"Guardrail '{name}' is now {state}."


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL TOOLS  (Microsoft 365 / Outlook)
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_emails(
    folder: str = "inbox",
    max_count: int = 10,
    unread_only: bool = False,
) -> str:
    """
    Fetch emails from Outlook.

    Args:
        folder: Mailbox folder (inbox, sent, drafts, etc.)
        max_count: Maximum number of emails to return (1-50)
        unread_only: If True, only return unread messages
    """
    try:
        from tools import ms365
        result = ms365.get_emails(folder=folder, max_count=max_count, unread_only=unread_only)
        return _json_result(result)
    except Exception as e:
        return f"Error fetching emails: {e}"


@mcp.tool()
def get_email_body(message_id: str) -> str:
    """
    Get the full body of an email by its ID.

    Args:
        message_id: The message ID from get_emails
    """
    try:
        from tools import ms365
        return ms365.get_email_body(message_id)
    except Exception as e:
        return f"Error reading email: {e}"


@mcp.tool()
def search_emails(query: str, max_count: int = 10) -> str:
    """
    Search emails by keyword.

    Args:
        query: Search query (e.g. "budget report from Ahmed")
        max_count: Maximum results to return
    """
    try:
        from tools import ms365
        return _json_result(ms365.search_emails(query=query, max_count=max_count))
    except Exception as e:
        return f"Error searching emails: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# CALENDAR TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_calendar_events(days_ahead: int = 7) -> str:
    """
    Get upcoming calendar events.

    Args:
        days_ahead: How many days ahead to look (default 7)
    """
    try:
        from tools import ms365
        return _json_result(ms365.get_calendar_events(days_ahead=days_ahead))
    except Exception as e:
        return f"Error fetching calendar: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# GITHUB TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_github_notifications(unread_only: bool = True) -> str:
    """
    Get GitHub notifications.

    Args:
        unread_only: If True, only return unread notifications
    """
    try:
        from tools import github as gh
        return _json_result(gh.get_notifications(unread_only=unread_only))
    except Exception as e:
        return f"Error fetching GitHub notifications: {e}"


@mcp.tool()
def list_pull_requests(repo: str, state: str = "open") -> str:
    """
    List pull requests for a repository.

    Args:
        repo: Full repo name (e.g. "owner/repo-name")
        state: PR state — open, closed, or all
    """
    try:
        from tools import github as gh
        return _json_result(gh.list_pull_requests(repo=repo, state=state))
    except Exception as e:
        return f"Error listing PRs: {e}"


@mcp.tool()
def get_my_review_requests() -> str:
    """Get GitHub PRs where you have been asked to review."""
    try:
        from tools import github as gh
        return _json_result(gh.get_my_review_requests())
    except Exception as e:
        return f"Error fetching review requests: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# JIRA TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_my_jira_issues(status: str = "") -> str:
    """
    Get Jira issues assigned to you.

    Args:
        status: Filter by status (e.g. "In Progress", "To Do"). Empty = all.
    """
    try:
        from tools import jira
        return _json_result(jira.get_my_issues(status=status))
    except Exception as e:
        return f"Error fetching Jira issues: {e}"


@mcp.tool()
def search_jira(jql: str, max_results: int = 20) -> str:
    """
    Run a JQL query against Jira.

    Args:
        jql: JQL query string (e.g. "project = PROJ AND sprint in openSprints()")
        max_results: Maximum issues to return
    """
    try:
        from tools import jira
        return _json_result(jira.search_issues(jql=jql, max_results=max_results))
    except Exception as e:
        return f"Error searching Jira: {e}"


@mcp.tool()
def create_jira_issue(
    project: str,
    summary: str,
    description: str = "",
    issue_type: str = "Task",
    priority: str = "Medium",
) -> str:
    """
    Create a new Jira issue.

    Args:
        project: Project key (e.g. "PROJ")
        summary: Issue title
        description: Issue description (optional)
        issue_type: Type — Task, Bug, Story, Epic (default Task)
        priority: Priority — Highest, High, Medium, Low, Lowest (default Medium)
    """
    try:
        from tools import jira
        return _json_result(jira.create_issue(
            project=project, summary=summary,
            description=description, issue_type=issue_type, priority=priority,
        ))
    except Exception as e:
        return f"Error creating Jira issue: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# TEAMS TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_teams_messages(chat_id: str, limit: int = 20) -> str:
    """
    Get messages from a Teams chat or channel.

    Args:
        chat_id: Teams chat or channel ID
        limit: Maximum messages to return (default 20)
    """
    try:
        from tools import ms365
        return _json_result(ms365.get_chat_messages(chat_id=chat_id, limit=limit))
    except Exception as e:
        return f"Error fetching Teams messages: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """
    Search the local knowledge base (RAG / ChromaDB).

    Args:
        query: Natural language search query
        top_k: Number of results to return (default 5)
    """
    try:
        from tools import knowledge_base as kb
        return _json_result(kb.search(query=query, top_k=top_k))
    except Exception as e:
        return f"Knowledge base search error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# AGENT TOOL — run a full agent turn from MCP
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def ask_agent(message: str, session_id: str = "mcp-default") -> str:
    """
    Run a full agent turn — the agent will use its tools and return a response.
    This is the most powerful tool: it gives you the full multi-tool pipeline.

    Args:
        message: Your request (e.g. "Summarise my unread emails and create Jira tasks")
        session_id: Session identifier for conversation continuity (default "mcp-default")
    """
    try:
        import agent as ag
        response = ag.run_agent_turn(
            user_message=message,
            session_id=session_id,
            interface="mcp",
        )
        return response
    except Exception as e:
        return f"Agent error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Work Assistant MCP Server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP transport instead of stdio (port 8765)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port (only used with --http, default 8765)",
    )
    args = parser.parse_args()

    if args.http:
        print(f"Starting Work Assistant MCP server on HTTP port {args.port} …", file=sys.stderr)
        mcp.run(transport="http", host="127.0.0.1", port=args.port)
    else:
        # stdio transport — Claude Desktop default
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
