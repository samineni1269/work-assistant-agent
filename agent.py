"""
Work Assistant Agent
=====================
Powered by multiple LLM providers: Gemini, Claude, OpenAI, OpenRouter.
The provider is auto-detected from your .env file, or set LLM_PROVIDER explicitly.
Connects to: Outlook, Teams, SharePoint, Jira, Confluence, Excel,
             GitHub, Linear, Zoom, Google Meet.

Run:
    python agent.py           — interactive chat mode
    python agent.py briefing  — one-shot daily briefing
    python agent.py standup   — one-shot standup summary
"""

import os
import sys
import json
import time
import datetime
import concurrent.futures
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm

# ── Load env ──────────────────────────────────────────────────────────────────
load_dotenv()

console = Console()

# ── Lazy-import tool modules (only if credentials are present) ────────────────
def _ms():
    from tools import ms365
    return ms365

def _atl():
    from tools import atlassian
    return atlassian

def _docs():
    from tools import office_docs
    return office_docs

def _doc_creator():
    from tools import doc_creator
    return doc_creator

def _gh():
    from tools import github_tool
    return github_tool

def _lin():
    from tools import linear_tool
    return linear_tool

def _zoom():
    from tools import zoom_meet
    return zoom_meet

def _mem():
    from tools import memory
    return memory

def _rag():
    from tools import rag
    return rag

def _browser():
    from tools import browser_tool
    return browser_tool

def _analytics():
    from tools import analytics
    return analytics

def _slack():
    from tools import slack_tool
    return slack_tool

def _notion():
    from tools import notion_tool
    return notion_tool

def _actions():
    from tools import action_items
    return action_items

def _briefing():
    from tools import briefing
    return briefing


# ══════════════════════════════════════════════════════════════════════════════
# TOOL SETS — read vs write (provider-agnostic)
# ══════════════════════════════════════════════════════════════════════════════

# READ tools — execute immediately without confirmation
READ_TOOLS = {
    "get_emails", "get_email_body", "search_emails",
    "get_calendar_events",
    "get_teams_chats", "get_chat_messages", "list_teams", "get_channel_messages",
    "search_sharepoint", "list_sharepoint_files",
    "read_excel_sheet", "list_excel_sheets",
    "get_my_jira_issues", "search_jira", "get_jira_issue", "get_jira_projects",
    "search_confluence", "get_confluence_page", "list_confluence_spaces",
    # Word / PowerPoint reads
    "read_word_document", "list_word_headings",
    "read_presentation", "get_presentation_summary",
    # GitHub reads
    "get_github_notifications", "get_my_review_requests", "list_my_repos",
    "list_pull_requests", "get_pull_request", "get_pr_checks",
    "get_repo_workflow_runs", "search_github", "list_my_github_issues",
    # Linear reads
    "get_my_linear_issues", "search_linear_issues", "get_linear_issue",
    "list_linear_teams", "list_linear_workflow_states", "list_linear_projects",
    # Zoom / Meet reads
    "list_zoom_meetings", "get_zoom_meeting", "list_zoom_recordings",
    "list_google_calendar_events",
    # Super-agent reads
    "search_knowledge_base", "browse_url", "search_web",
    "get_memory_summary", "get_analytics_summary",
    # Slack reads
    "list_slack_channels", "get_slack_messages", "get_slack_thread",
    "list_slack_dms", "get_slack_dm_history", "search_slack", "get_slack_user_info",
    # Notion reads
    "search_notion", "get_notion_page", "list_notion_databases", "query_notion_database",
    # Action items / priority scoring
    "get_my_action_items", "extract_action_items", "score_notifications",
    # Calendar scheduling
    "find_free_slots",
    # SharePoint reads
    "get_sharepoint_sites",
    # Webhook events
    "get_webhook_events",
}

# WRITE tools — always show preview and require user confirmation
WRITE_TOOLS = {
    "send_email", "create_calendar_event",
    "send_teams_message", "post_channel_message",
    "write_excel_cell", "append_excel_row",
    "create_jira_issue", "update_jira_issue", "transition_jira_issue", "add_jira_comment",
    "create_confluence_page", "update_confluence_page",
    # Word / PowerPoint writes
    "create_word_document", "update_word_document",
    "create_presentation", "add_slide_to_presentation",
    "upload_file_to_sharepoint",
    # GitHub writes
    "create_github_issue", "add_pr_review", "merge_pull_request",
    # Linear writes
    "create_linear_issue", "update_linear_issue",
    "transition_linear_issue", "add_linear_comment",
    # Zoom / Meet writes
    "create_zoom_meeting", "create_google_meet",
    # Memory writes
    "update_memory_entry",
    # Slack writes
    "send_slack_message",
    # Notion writes
    "create_notion_page",
    # Action items writes
    "complete_action_item", "save_action_items",
    # Briefing
    "send_morning_briefing",
}


def _with_retry(fn, tool_name: str, max_attempts: int = 3) -> str:
    """
    Call fn() up to max_attempts times with exponential backoff.
    On all failures, return a graceful degradation message instead of crashing.
    Never retries on auth errors (401/403) or bad-request (400) since those
    are deterministic — retrying would waste time and quota.
    """
    NO_RETRY_SIGNALS = ("401", "403", "400", "invalid", "not found", "unauthorized")
    delay = 1.0
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            last_err = e
            if any(sig in err_str for sig in NO_RETRY_SIGNALS):
                break   # deterministic error — pointless to retry
            if attempt < max_attempts - 1:
                time.sleep(delay)
                delay *= 2   # exponential backoff: 1s, 2s
    tool_label = tool_name.replace("_", " ")
    return json.dumps({
        "error": f"⚠️ {tool_label} is temporarily unavailable.",
        "detail": str(last_err),
        "suggestion": "The service may be down or rate-limited. Try again in a moment.",
    })


def dispatch_tool(name: str, args: dict) -> str:
    """Call the actual tool function and return result as JSON string."""
    ms   = _ms()
    atl  = _atl()
    docs = _docs()
    gh   = _gh()
    lin  = _lin()
    zoom = _zoom()

    dispatch = {
        # Slack
        "list_slack_channels":    lambda: _slack().list_slack_channels(**args),
        "get_slack_messages":     lambda: _slack().get_slack_messages(**args),
        "get_slack_thread":       lambda: _slack().get_slack_thread(**args),
        "list_slack_dms":         lambda: _slack().list_slack_dms(**args),
        "get_slack_dm_history":   lambda: _slack().get_slack_dm_history(**args),
        "search_slack":           lambda: _slack().search_slack(**args),
        "get_slack_user_info":    lambda: _slack().get_slack_user_info(**args),
        "send_slack_message":     lambda: _slack().send_slack_message(**args),
        # Notion
        "search_notion":          lambda: _notion().search_notion(**args),
        "get_notion_page":        lambda: _notion().get_notion_page(**args),
        "create_notion_page":     lambda: _notion().create_notion_page(**args),
        "list_notion_databases":  lambda: _notion().list_notion_databases(**args),
        "query_notion_database":  lambda: _notion().query_notion_database(**args),
        # Action items
        "extract_action_items":   lambda: _actions().extract_action_items(**args),
        "save_action_items":      lambda: _actions().save_action_items(**args),
        "get_my_action_items":    lambda: _actions().get_my_action_items(**args),
        "complete_action_item":   lambda: _actions().complete_action_item(**args),
        "score_notifications":    lambda: _actions().score_notifications(**args),
        # Briefing
        "send_morning_briefing":  lambda: _briefing().send_morning_briefing(**args),
        # Webhook events
        "get_webhook_events": lambda: __import__("tools.webhook_server", fromlist=["get_recent_events"]).get_recent_events(**args),
        # Calendar scheduling
        "find_free_slots":        lambda: ms.find_free_slots(**args),
        # SharePoint sites
        "get_sharepoint_sites":   lambda: ms.get_sharepoint_sites(**args),

        # Outlook
        "get_emails":            lambda: ms.get_emails(**args),
        "get_email_body":        lambda: ms.get_email_body(**args),
        "send_email":            lambda: ms.send_email(**args),
        "search_emails":         lambda: ms.search_emails(**args),
        # Calendar
        "get_calendar_events":   lambda: ms.get_calendar_events(**args),
        "create_calendar_event": lambda: ms.create_calendar_event(**args),
        # Teams
        "get_teams_chats":       lambda: ms.get_teams_chats(**args),
        "get_chat_messages":     lambda: ms.get_chat_messages(**args),
        "send_teams_message":    lambda: ms.send_teams_message(**args),
        "list_teams":            lambda: ms.list_teams(),
        "get_channel_messages":  lambda: ms.get_channel_messages(**args),
        "post_channel_message":  lambda: ms.post_channel_message(**args),
        # SharePoint
        "search_sharepoint":          lambda: ms.search_sharepoint(**args),
        "list_sharepoint_files":      lambda: ms.list_sharepoint_files(**args),
        "upload_file_to_sharepoint":  lambda: ms.upload_file_to_sharepoint(**args),
        # Excel
        "create_excel_workbook": lambda: ms.create_excel_workbook(**args),
        "read_excel_sheet":      lambda: ms.read_excel_sheet(**args),
        "write_excel_cell":      lambda: ms.write_excel_cell(**args),
        "append_excel_row":      lambda: ms.append_excel_row(**args),
        "list_excel_sheets":     lambda: ms.list_excel_sheets(**args),
        # Jira
        "get_my_jira_issues":    lambda: atl.get_my_jira_issues(**args),
        "search_jira":           lambda: atl.search_jira(**args),
        "get_jira_issue":        lambda: atl.get_jira_issue(**args),
        "create_jira_issue":     lambda: atl.create_jira_issue(**args),
        "update_jira_issue":     lambda: atl.update_jira_issue(**args),
        "transition_jira_issue": lambda: atl.transition_jira_issue(**args),
        "add_jira_comment":      lambda: atl.add_jira_comment(**args),
        "get_jira_projects":     lambda: atl.get_jira_projects(),
        # Confluence
        "search_confluence":       lambda: atl.search_confluence(**args),
        "get_confluence_page":     lambda: atl.get_confluence_page(**args),
        "create_confluence_page":  lambda: atl.create_confluence_page(**args),
        "update_confluence_page":  lambda: atl.update_confluence_page(**args),
        "list_confluence_spaces":  lambda: atl.list_confluence_spaces(),
        # Word
        "read_word_document":      lambda: docs.read_word_document(**args),
        "list_word_headings":      lambda: docs.list_word_headings(**args),
        "update_word_document":    lambda: docs.update_word_document(**args),
        # PowerPoint
        "read_presentation":           lambda: docs.read_presentation(**args),
        "get_presentation_summary":    lambda: docs.get_presentation_summary(**args),
        "add_slide_to_presentation":   lambda: docs.add_slide_to_presentation(**args),
        # Local document creator (saves to ~/work-assistant-docs + tracked in web UI)
        "create_word_document":    lambda: _doc_creator().create_word_document(**args),
        "create_presentation":     lambda: _doc_creator().create_presentation(**args),
        "list_documents":          lambda: _doc_creator().list_documents(**args),
        "delete_document":         lambda: _doc_creator().delete_document(**args),
        # GitHub
        "get_my_open_prs":             lambda: gh.get_my_open_prs(**args),
        "get_github_notifications":    lambda: gh.get_github_notifications(**args),
        "get_my_review_requests":      lambda: gh.get_my_review_requests(**args),
        "list_my_repos":               lambda: gh.list_my_repos(**args),
        "list_pull_requests":          lambda: gh.list_pull_requests(**args),
        "get_pull_request":            lambda: gh.get_pull_request(**args),
        "get_pr_checks":               lambda: gh.get_pr_checks(**args),
        "get_repo_workflow_runs":      lambda: gh.get_repo_workflow_runs(**args),
        "search_github":               lambda: gh.search_github(**args),
        "list_my_github_issues":       lambda: gh.list_my_github_issues(**args),
        "create_github_issue":         lambda: gh.create_github_issue(**args),
        "add_pr_review":               lambda: gh.add_pr_review(**args),
        "merge_pull_request":          lambda: gh.merge_pull_request(**args),
        # Linear
        "get_my_linear_issues":        lambda: lin.get_my_linear_issues(**args),
        "search_linear_issues":        lambda: lin.search_linear_issues(**args),
        "get_linear_issue":            lambda: lin.get_linear_issue(**args),
        "list_linear_teams":           lambda: lin.list_linear_teams(),
        "list_linear_workflow_states": lambda: lin.list_linear_workflow_states(**args),
        "list_linear_projects":        lambda: lin.list_linear_projects(**args),
        "create_linear_issue":         lambda: lin.create_linear_issue(**args),
        "update_linear_issue":         lambda: lin.update_linear_issue(**args),
        "transition_linear_issue":     lambda: lin.transition_linear_issue(**args),
        "add_linear_comment":          lambda: lin.add_linear_comment(**args),
        # Zoom
        "list_zoom_meetings":          lambda: zoom.list_zoom_meetings(**args),
        "get_zoom_meeting":            lambda: zoom.get_zoom_meeting(**args),
        "create_zoom_meeting":         lambda: zoom.create_zoom_meeting(**args),
        "list_zoom_recordings":        lambda: zoom.list_zoom_recordings(**args),
        # Google Meet
        "list_google_calendar_events": lambda: zoom.list_google_calendar_events(**args),
        "create_google_meet":          lambda: zoom.create_google_meet(**args),
        # Knowledge base
        "search_knowledge_base": lambda: _rag().search_knowledge_base(**args),
        # Browser
        "browse_url":            lambda: _browser().browse_url(**args),
        "search_web":            lambda: _browser().search_web(**args),
        # Memory
        "update_memory_entry":   lambda: _mem().update_memory_entry(**args),
        "get_memory_summary":    lambda: _mem().get_memory_summary(),
        # Analytics
        "get_analytics_summary": lambda: _analytics().get_analytics_summary(**args),
    }

    if name not in dispatch:
        return json.dumps({"error": f"Unknown tool: {name}"})

    return _with_retry(
        lambda: json.dumps(dispatch[name](), default=str, indent=2),
        tool_name=name,
    )


# ══════════════════════════════════════════════════════════════════════════════
# CONFIRMATION SYSTEM — Zero-mistake write protection
# ══════════════════════════════════════════════════════════════════════════════

def confirm_write_operation(tool_name: str, args: dict) -> bool:
    """
    Show a preview of a write operation and ask the user to confirm.
    Returns True if the user confirms, False to cancel.
    """
    previews = {
        "send_email": lambda a: (
            f"📧  Send email\n"
            f"   To:      {a.get('to')}\n"
            f"   Subject: {a.get('subject')}\n"
            f"   Body:\n\n{_indent(a.get('body', ''), 6)}"
        ),
        "create_calendar_event": lambda a: (
            f"📅  Create calendar event\n"
            f"   Title:     {a.get('subject')}\n"
            f"   Start:     {a.get('start')}\n"
            f"   End:       {a.get('end')}\n"
            f"   Attendees: {', '.join(a.get('attendees', [])) or 'none'}\n"
            f"   Teams:     {'yes' if a.get('online', True) else 'no'}"
        ),
        "send_teams_message": lambda a: (
            f"💬  Send Teams message\n"
            f"   To chat: {a.get('chat_id')}\n"
            f"   Message: {a.get('message')}"
        ),
        "post_channel_message": lambda a: (
            f"💬  Post to Teams channel\n"
            f"   Team:    {a.get('team_id')}\n"
            f"   Channel: {a.get('channel_id')}\n"
            f"   Message: {a.get('message')}"
        ),
        "write_excel_cell": lambda a: (
            f"📊  Write Excel cell\n"
            f"   File:  {a.get('filename')}\n"
            f"   Sheet: {a.get('sheet_name')}\n"
            f"   Cell:  {a.get('cell')} = {a.get('value')}"
        ),
        "append_excel_row": lambda a: (
            f"📊  Append Excel row\n"
            f"   File:  {a.get('filename')}\n"
            f"   Sheet: {a.get('sheet_name')}\n"
            f"   Data:  {a.get('row_data')}"
        ),
        "create_jira_issue": lambda a: (
            f"🎫  Create Jira issue\n"
            f"   Project:  {a.get('project_key')}\n"
            f"   Type:     {a.get('issue_type', 'Task')}\n"
            f"   Summary:  {a.get('summary')}\n"
            f"   Priority: {a.get('priority', 'Medium')}\n"
            f"   Assignee: {a.get('assignee_email', 'unassigned')}\n"
            f"   Due:      {a.get('due_date', 'none')}\n"
            f"   Description:\n\n{_indent(a.get('description', '(none)'), 6)}"
        ),
        "update_jira_issue": lambda a: (
            f"✏️   Update Jira issue {a.get('issue_key')}\n"
            f"   Changes: {json.dumps({k: v for k, v in a.items() if k != 'issue_key'}, indent=2)}"
        ),
        "transition_jira_issue": lambda a: (
            f"🔄  Transition Jira issue\n"
            f"   Issue:      {a.get('issue_key')}\n"
            f"   New status: {a.get('transition_name')}"
        ),
        "add_jira_comment": lambda a: (
            f"💬  Add Jira comment\n"
            f"   Issue:   {a.get('issue_key')}\n"
            f"   Comment: {a.get('comment')}"
        ),
        "create_confluence_page": lambda a: (
            f"📄  Create Confluence page\n"
            f"   Space:  {a.get('space_id')}\n"
            f"   Title:  {a.get('title')}\n"
            f"   Parent: {a.get('parent_id', 'root')}\n"
            f"   Content preview:\n\n{_indent(a.get('content', '')[:400], 6)}"
        ),
        "update_confluence_page": lambda a: (
            f"📄  Update Confluence page {a.get('page_id')}\n"
            f"   New title:  {a.get('title', '(unchanged)')}\n"
            f"   Mode:       {'append' if a.get('append') else 'replace'}\n"
            f"   Content preview:\n\n{_indent(a.get('new_content', '')[:400], 6)}"
        ),
        "create_word_document": lambda a: (
            f"📝  Create Word document\n"
            f"   Filename: {a.get('filename')}\n"
            f"   Title:    {a.get('title')}\n"
            f"   Sections: {len(a.get('sections', []))} section(s)\n"
            f"   Folder:   {a.get('upload_folder', '/')}"
        ),
        "update_word_document": lambda a: (
            f"📝  Update Word document: {a.get('filename')}\n"
            f"   Append sections: {len(a.get('append_sections', []))}\n"
            f"   Find/replace:    {'yes' if a.get('replace_paragraph') else 'no'}"
        ),
        "create_presentation": lambda a: (
            f"📊  Create PowerPoint presentation\n"
            f"   Filename: {a.get('filename')}\n"
            f"   Title:    {a.get('title')}\n"
            f"   Slides:   {len(a.get('slides', []))} slides\n"
            f"   Theme:    {a.get('theme', 'dark')}\n"
            f"   Folder:   {a.get('upload_folder', '/')}"
        ),
        "add_slide_to_presentation": lambda a: (
            f"📊  Add slide to: {a.get('filename')}\n"
            f"   Title:   {a.get('slide_title')}\n"
            f"   Bullets: {len(a.get('bullets', []))}"
        ),
        "create_github_issue": lambda a: (
            f"🐛  Create GitHub issue\n"
            f"   Repo:    {a.get('repo')}\n"
            f"   Title:   {a.get('title')}\n"
            f"   Labels:  {', '.join(a.get('labels', [])) or 'none'}\n"
            f"   Assign:  {', '.join(a.get('assignees', [])) or 'none'}\n"
            f"   Body:\n\n{_indent(a.get('body', '(none)'), 6)}"
        ),
        "add_pr_review": lambda a: (
            f"👀  Submit PR review\n"
            f"   Repo:   {a.get('repo')}\n"
            f"   PR:     #{a.get('pr_number')}\n"
            f"   Action: {a.get('event', 'COMMENT')}\n"
            f"   Body:   {a.get('body', '')[:300]}"
        ),
        "merge_pull_request": lambda a: (
            f"🔀  Merge pull request ⚠️ This is irreversible\n"
            f"   Repo:   {a.get('repo')}\n"
            f"   PR:     #{a.get('pr_number')}\n"
            f"   Method: {a.get('merge_method', 'squash')}"
        ),
        "create_linear_issue": lambda a: (
            f"🎯  Create Linear issue\n"
            f"   Team:     {a.get('team_id')}\n"
            f"   Title:    {a.get('title')}\n"
            f"   Priority: {['No priority','Urgent','High','Medium','Low'][a.get('priority', 0)]}\n"
            f"   Due:      {a.get('due_date', 'none')}\n"
            f"   Description:\n\n{_indent(a.get('description', '(none)'), 6)}"
        ),
        "update_linear_issue": lambda a: (
            f"✏️   Update Linear issue: {a.get('issue_id')}\n"
            f"   Changes: {json.dumps({k: v for k, v in a.items() if k != 'issue_id'}, indent=2)}"
        ),
        "transition_linear_issue": lambda a: (
            f"🔄  Transition Linear issue\n"
            f"   Issue:     {a.get('issue_id')}\n"
            f"   New state: {a.get('state_name')}"
        ),
        "add_linear_comment": lambda a: (
            f"💬  Add Linear comment\n"
            f"   Issue:   {a.get('issue_id')}\n"
            f"   Comment: {a.get('comment', '')[:300]}"
        ),
        "create_zoom_meeting": lambda a: (
            f"📹  Create Zoom meeting\n"
            f"   Topic:    {a.get('topic')}\n"
            f"   Start:    {a.get('start_time')}\n"
            f"   Duration: {a.get('duration', 60)} min\n"
            f"   Timezone: {a.get('timezone', 'UTC')}\n"
            f"   Record:   {'yes' if a.get('auto_record') else 'no'}"
        ),
        "create_google_meet": lambda a: (
            f"📹  Create Google Meet\n"
            f"   Title:     {a.get('title')}\n"
            f"   Start:     {a.get('start')}\n"
            f"   End:       {a.get('end')}\n"
            f"   Attendees: {', '.join(a.get('attendees', [])) or 'none'}"
        ),
        "send_slack_message": lambda a: (
            f"💬  Send Slack message\n"
            f"   Channel: {a.get('channel_id')}\n"
            f"   Text:    {a.get('text', '')[:300]}\n"
            f"   Thread:  {a.get('thread_ts', 'none')}"
        ),
        "create_notion_page": lambda a: (
            f"📓  Create Notion page\n"
            f"   Parent:  {a.get('parent_id')}\n"
            f"   Title:   {a.get('title')}\n"
            f"   Content preview:\n\n{_indent(a.get('content', '')[:300], 6)}"
        ),
        "complete_action_item": lambda a: (
            f"✅  Mark action item #{a.get('item_id')} as completed"
        ),
        "send_morning_briefing": lambda a: (
            f"📧  Send daily briefing email\n"
            f"   To: {a.get('recipient', '(from BRIEFING_EMAIL env)')}"
        ),
    }

    preview_fn   = previews.get(tool_name)
    preview_text = (
        preview_fn(args) if preview_fn
        else f"Operation: {tool_name}\nArgs: {json.dumps(args, indent=2)}"
    )

    console.print()
    console.print(Panel(
        preview_text,
        title="[bold yellow]⚠  Confirm Action[/bold yellow]",
        border_style="yellow",
    ))

    try:
        return Confirm.ask("[yellow]Proceed?[/yellow]", default=False)
    except (KeyboardInterrupt, EOFError):
        return False


def _indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPT
# ══════════════════════════════════════════════════════════════════════════════

def _build_system_prompt() -> str:
    """Build the system prompt, injecting memory and tone guide dynamically."""
    from tools.memory import get_memory_context
    from tools.tone_learner import get_tone_instructions

    memory_ctx = get_memory_context()
    tone_guide = get_tone_instructions()
    today = datetime.datetime.now().strftime("%A, %d %B %Y — %H:%M")

    base = f"""# Work Assistant — System Prompt
Today: {today}

## Identity
You are a senior work assistant with deep expertise across software engineering workflows,
corporate communication, and project management. You are sharp, efficient, and professional —
you cut through noise, surface what matters, and act decisively within your constraints.
You never make things up. If you don't have data, you fetch it.

## Tools Available
### Communication
- **Outlook** — get_emails, get_email_body, search_emails, send_email
- **Teams** — get_teams_chats, get_chat_messages, send_teams_message, list_teams, get_channel_messages, post_channel_message
- **Slack** — list_slack_channels, get_slack_messages, search_slack, send_slack_message, get_slack_dm_history

### Calendar & Scheduling
- **Outlook Calendar** — get_calendar_events, create_calendar_event
- **Smart Scheduling** — find_free_slots (finds when all attendees are free)
- **Google Calendar** — list_google_calendar_events, create_google_meet
- **Zoom** — list_zoom_meetings, get_zoom_meeting, create_zoom_meeting, list_zoom_recordings

### Files & Documents
- **SharePoint/OneDrive** — search_sharepoint, list_sharepoint_files, get_sharepoint_sites, upload_file_to_sharepoint
- **Excel** — create_excel_workbook, read_excel_sheet, write_excel_cell, append_excel_row, list_excel_sheets
- **Word (.docx)** — create_word_document, read_word_document, update_word_document, list_word_headings
- **PowerPoint (.pptx)** — create_presentation, read_presentation, add_slide_to_presentation, get_presentation_summary

### Project Management
- **Jira** — get_my_jira_issues, search_jira, get_jira_issue, create_jira_issue, update_jira_issue, transition_jira_issue, add_jira_comment, get_jira_projects
- **Linear** — get_my_linear_issues, search_linear_issues, get_linear_issue, create_linear_issue, update_linear_issue, transition_linear_issue, add_linear_comment, list_linear_teams, list_linear_projects
- **Notion** — search_notion, get_notion_page, create_notion_page, list_notion_databases, query_notion_database

### Engineering
- **GitHub** — get_github_notifications, get_my_open_prs, get_my_review_requests, list_my_repos, list_pull_requests, get_pull_request, get_pr_checks, get_repo_workflow_runs, search_github, list_my_github_issues, create_github_issue, add_pr_review, merge_pull_request

### Intelligence & Productivity
- **Action Items** — extract_action_items (extract TODOs from text), get_my_action_items, complete_action_item
- **Priority Scoring** — score_notifications (scores urgency of a list of notifications)
- **Knowledge Base** — search_knowledge_base (search uploaded docs/policies)
- **Memory** — update_memory_entry, get_memory_summary
- **Analytics** — get_analytics_summary
- **Web** — browse_url, search_web

## Behavioural Rules

### Rule 1 — READ vs WRITE
- **READ** (fetching, listing, searching, reading) → execute immediately, no confirmation needed.
- **WRITE** (sending, creating, updating, deleting, merging) → ALWAYS show a clear preview and wait for "yes" before proceeding.
- When in doubt, treat it as WRITE.

### Rule 2 — Never guess IDs
If you need a chat ID, team ID, channel ID, issue key, or any identifier you don't have:
fetch the parent list first to find it. Example: asked to "read messages from Alex" → call
get_teams_chats() first, find Alex's chat, then call get_chat_messages(chat_id=...).

### Rule 3 — Parallel execution
When the user's request requires multiple independent data fetches (e.g. briefing = emails +
calendar + Jira), call ALL read tools simultaneously in a single response — do not wait for
one before calling the next.

### Rule 4 — Ambiguity resolution
If a request is ambiguous in a way that could lead to the wrong action (e.g. "delete that
issue" without specifying which), ask ONE targeted clarifying question before proceeding.
Do not ask multiple questions at once.

### Rule 5 — Response format
- Use **markdown** with clear headers (##), bullet points, and bold for key info.
- Keep responses concise — lead with the answer, then details.
- For lists of items (emails, issues, notifications), use a structured table or bullet list
  with the most important info first.
- For action-oriented responses, end with a "**What next?**" suggestion when relevant.

### Rule 6 — Proactive intelligence
After fetching notifications, emails, or issues, automatically apply priority scoring if
there are 5+ items — surface what needs action today without being asked.
After reading long emails or meeting notes, offer to extract action items.

### Rule 7 — Daily briefing
When asked for briefing, fetch ALL of these in parallel:
1. today's calendar events (get_calendar_events)
2. unread emails top 10 (get_emails unread_only=True)
3. my Jira issues In Progress (get_my_jira_issues)
4. GitHub notifications (get_github_notifications)
Format with clear sections: 📅 Calendar · 📧 Emails · 🎫 Jira · 🔔 GitHub

### Rule 8 — Standup summary
When asked for standup, fetch:
1. Jira issues updated in last 24h
2. My open GitHub PRs
3. Today's meetings
Format as a clean standup: **Yesterday / Today / Blockers**

## Tool Chaining Examples

### Example A — "What did Alex say in our latest chat?"
WRONG: Ask "what is Alex's chat ID?"
RIGHT: Call get_teams_chats() → find Alex → call get_chat_messages(chat_id="...")

### Example B — "Schedule a 30-min meeting with bob@company.com this week"
RIGHT: Call find_free_slots(attendee_emails=["bob@company.com"], duration_minutes=30, days_ahead=5)
→ present options → call create_calendar_event() after confirmation

### Example C — "Summarise my emails and create Jira tickets for anything actionable"
RIGHT: Call get_emails() and get_my_jira_issues() in PARALLEL
→ identify actionable emails
→ for each: show preview of proposed Jira ticket
→ create only after confirmation

### Example D — "What needs my attention right now?"
RIGHT: Call get_github_notifications(), get_emails(unread_only=True), get_my_jira_issues()
in PARALLEL → call score_notifications() on the combined results → present ranked list

## Error Handling
- If a tool returns an error, explain it briefly and suggest the fix (e.g. "token expired — run fix_teams_auth.command").
- If an API key is missing, tell the user which .env variable to set.
- Never crash silently — always report what went wrong.
"""

    if memory_ctx:
        base += f"\n\n## What I Know About You\n{memory_ctx}"

    if tone_guide:
        base += f"\n\n## Your Communication Style\n{tone_guide}"

    return base


# ══════════════════════════════════════════════════════════════════════════════
# AGENTIC LOOP — multi-provider function calling with multi-turn
# ══════════════════════════════════════════════════════════════════════════════

def _summarise_history(history: list, provider) -> list:
    """
    Keep the last 8 turns verbatim; compress older turns into a rolling summary.
    This prevents context drift in long sessions without losing key facts.
    Returns a new history list safe to pass to the LLM.
    """
    KEEP_RECENT = 8   # number of recent messages to keep verbatim
    if len(history) <= KEEP_RECENT:
        return history

    old_turns = history[:-KEEP_RECENT]
    recent    = history[-KEEP_RECENT:]

    # Build a plain text transcript of old turns
    transcript_lines = []
    for msg in old_turns:
        role = msg.get("role", "")
        if role == "user":
            transcript_lines.append(f"User: {msg.get('content','')}")
        elif role == "assistant" and msg.get("content"):
            transcript_lines.append(f"Assistant: {msg.get('content','')}")
        elif role == "assistant" and msg.get("tool_calls"):
            names = [tc.get("name","?") for tc in msg.get("tool_calls", [])]
            transcript_lines.append(f"Assistant called tools: {', '.join(names)}")
        elif role == "tool":
            pass  # skip raw tool results — too noisy
    transcript = "\n".join(transcript_lines)

    if not transcript.strip():
        return history

    # Summarise with a fast prompt
    summary_prompt = (
        "Summarise the following conversation history in under 150 words. "
        "Focus on: what the user asked, what data was fetched, what actions were taken, "
        "and any important facts mentioned (names, IDs, decisions). "
        "Write in third person, past tense. Be factual and brief.\n\n"
        f"---\n{transcript}\n---"
    )

    try:
        _, summary_text = provider.run_turn(
            system_prompt="You are a concise conversation summariser.",
            history=[{"role": "user", "content": summary_prompt}],
            tools=[],
        )
        summary_msg = {
            "role": "user",
            "content": f"[Earlier conversation summary]\n{summary_text.strip()}"
        }
        return [summary_msg] + recent
    except Exception:
        # On failure, just drop old turns — better than crashing
        return recent


# ══════════════════════════════════════════════════════════════════════════════
# PLANNER MODE — show a numbered plan before executing complex requests
# ══════════════════════════════════════════════════════════════════════════════

_PLANNER_KEYWORDS = {
    "plan", "strategy", "set up", "setup", "organise", "organize", "prepare",
    "roadmap", "workflow", "automate", "design", "architect",
    "sprint", "onboard", "migrate", "restructure", "build out",
}

def _is_complex_request(message: str) -> bool:
    """Heuristic: does this message look like it needs a multi-step plan?"""
    low = message.lower()
    has_keyword = any(kw in low for kw in _PLANNER_KEYWORDS)
    is_long = len(message.split()) >= 8
    return has_keyword and is_long


def _build_plan(user_message: str, provider) -> str:
    """Ask the LLM to produce a numbered action plan (no execution yet)."""
    plan_prompt = (
        "The user has a complex, multi-step request. "
        "Produce a clear numbered plan (maximum 7 steps) of exactly what you will do. "
        "Be specific: name the tools or concrete actions for each step. "
        "Do NOT execute anything yet — produce only the plan.\n\n"
        f"User request: {user_message}"
    )
    try:
        _, plan_text = provider.run_turn(
            system_prompt=_build_system_prompt(),
            history=[{"role": "user", "content": plan_prompt}],
            tools=[],
        )
        return plan_text.strip()
    except Exception:
        return ""


def run_agent_turn(conversation_history: list, user_message: str,
                   auto_confirm: bool = False,
                   max_iterations: int = 10,
                   progress_callback=None) -> tuple[str, list, list]:
    """
    Run one turn of the agent loop using the configured LLM provider.

    Provider is selected automatically from available API keys, or set
    explicitly via LLM_PROVIDER in .env.

    Neutral conversation history format:
        {"role": "user",      "content": "text"}
        {"role": "assistant", "content": "text"}
        {"role": "assistant", "content": None,
         "tool_calls": [{"id":"..","name":"..","args":{..}}]}
        {"role": "tool",      "call_id": "..", "name": "..", "content": ".."}

    Returns (final_response_text, updated_history, guardrail_warnings).
    guardrail_warnings is a list of warning strings (may be empty).
    """
    from tools.llm_provider import TOOLS, get_provider, get_fast_provider, should_use_fast_model
    from tools.guardrails import (
        check_input, check_tool_call, process_tool_result,
        audit_write, scrub_output,
    )
    from tools.memory import get_memory_context, extract_and_save_facts
    from tools.tone_learner import get_tone_instructions
    from tools.analytics import log_interaction, TurnTimer

    warnings: list[str] = []
    _tools_called: list[str] = []
    _turn_timer = TurnTimer()
    _turn_timer.__enter__()

    # ── Guardrail 1: validate user input ──────────────────────────────────────
    safe, reason = check_input(user_message)
    if not safe:
        return reason, conversation_history, warnings

    try:
        # Model routing: use fast/cheap model for simple single-step reads
        _use_fast = should_use_fast_model(user_message, len(conversation_history))
        provider = get_fast_provider() if _use_fast else get_provider()
    except RuntimeError as e:
        console.print(f"\n[red]❌  LLM provider error: {e}[/red]")
        console.print("[dim]Set at least one of: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY in your .env[/dim]\n")
        sys.exit(1)

    # Add user message to neutral history
    conversation_history.append({"role": "user", "content": user_message})

    # ── Summarise long histories to keep context focused ──────────────────────
    working_history = _summarise_history(conversation_history, provider)

    tool_call_count = 0   # tracked for bulk_protection
    iteration_count = 0   # cap runaway loops

    system_prompt = _build_system_prompt()

    # ── Planner mode: generate plan first for complex multi-step requests ─────
    plan_prefix = ""
    if _is_complex_request(user_message):
        try:
            plan_text = _build_plan(user_message, provider)
            if plan_text:
                plan_prefix = f"**📋 My plan:**\n{plan_text}\n\n---\n\n"
        except Exception:
            pass  # silent fallback — run without plan header

    while True:
        iteration_count += 1
        if iteration_count > max_iterations:
            cap_msg = (
                f"⚠️ Reached the maximum number of reasoning iterations ({max_iterations}). "
                "Stopping to prevent an infinite loop. Please try a more specific request."
            )
            warnings.append(cap_msg)
            final_turn = {"role": "assistant", "content": cap_msg}
            conversation_history.append(final_turn)
            working_history.append(final_turn)
            return cap_msg, conversation_history, warnings

        # run_turn returns (tool_calls, text)
        #   tool_calls: list of (name, args, call_id) — non-empty when model wants a tool
        #   text: final response string — non-empty when model is done
        tool_calls, text = provider.run_turn(system_prompt, working_history, TOOLS)

        if not tool_calls:
            # ── Guardrail 2: scrub secrets from final response ────────────────
            text = plan_prefix + scrub_output(text)
            plan_prefix = ""   # only prepend once; clear after first use
            final_turn = {"role": "assistant", "content": text}
            conversation_history.append(final_turn)
            working_history.append(final_turn)

            # ── Post-turn: learn from this exchange ───────────────────────────
            try:
                extract_and_save_facts(user_message, text)
            except Exception:
                pass

            # ── Post-turn: log analytics ──────────────────────────────────────
            try:
                _turn_timer.__exit__(None, None, None)
                log_interaction(
                    user_message=user_message,
                    tools_called=_tools_called,
                    response_time_ms=_turn_timer.elapsed_ms,
                    success=True,
                )
            except Exception:
                pass

            return text, conversation_history, warnings

        # Report progress if callback provided
        if progress_callback and tool_calls:
            try:
                progress_callback({
                    "type": "tool_calls",
                    "iteration": iteration_count,
                    "tools": [n for n, _, _ in tool_calls],
                })
            except Exception:
                pass

        # Model wants to call tools — record in BOTH histories
        tool_turn = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": tc_id, "name": name, "args": args}
                for name, args, tc_id in tool_calls
            ],
        }
        conversation_history.append(tool_turn)
        working_history.append(tool_turn)

        # Separate reads (parallelisable) from writes (must be sequential)
        read_calls  = [(n, a, i) for n, a, i in tool_calls if n not in WRITE_TOOLS]
        write_calls = [(n, a, i) for n, a, i in tool_calls if n in WRITE_TOOLS]

        tool_results: dict[str, str] = {}  # tc_id → result

        # ── Execute READ tools in parallel ────────────────────────────────────
        if read_calls:
            tool_call_count += len(read_calls)

            def _run_read(call_tuple):
                name, args, tc_id = call_tuple
                allowed, block_reason = check_tool_call(name, args, tool_call_count)
                if not allowed:
                    warnings.append(block_reason)
                    return tc_id, name, json.dumps({"status": "blocked", "reason": block_reason})
                raw = dispatch_tool(name, args)
                scrubbed, warn = process_tool_result(name, raw)
                if warn:
                    warnings.append(warn)
                return tc_id, name, scrubbed

            with console.status(f"[dim]Fetching {', '.join(n for n, _, _ in read_calls)}...[/dim]"):
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(read_calls), 6)) as pool:
                    futures = {pool.submit(_run_read, call): call for call in read_calls}
                    for future in concurrent.futures.as_completed(futures):
                        tc_id, name, result = future.result()
                        tool_results[tc_id] = (name, result)
                        _tools_called.append(name)

        # ── Execute WRITE tools sequentially ──────────────────────────────────
        for name, args, tc_id in write_calls:
            tool_call_count += 1
            allowed, block_reason = check_tool_call(name, args, tool_call_count)
            if not allowed:
                result = json.dumps({"status": "blocked", "reason": block_reason})
                warnings.append(block_reason)
                tool_results[tc_id] = (name, result)
                continue

            # ── Guardrail 4a: audit write op before execution ─────────────────
            audit_write(name, args)
            confirmed = True if auto_confirm else confirm_write_operation(name, args)
            if not confirmed:
                result = json.dumps({"status": "cancelled", "reason": "User cancelled this operation."})
            else:
                result = dispatch_tool(name, args)

            result, warn = process_tool_result(name, result)
            if warn:
                warnings.append(warn)
            tool_results[tc_id] = (name, result)
            _tools_called.append(name)

        # Append all results in the original call order
        for name, args, tc_id in tool_calls:
            if tc_id in tool_results:
                t_name, t_result = tool_results[tc_id]
            else:
                t_name, t_result = name, json.dumps({"status": "no_result"})
            result_turn = {
                "role": "tool",
                "call_id": tc_id,
                "name": t_name,
                "content": t_result,
            }
            conversation_history.append(result_turn)
            working_history.append(result_turn)

    # (loop continues until model returns a text-only response)


# ══════════════════════════════════════════════════════════════════════════════
# ONE-SHOT MODES
# ══════════════════════════════════════════════════════════════════════════════

def run_daily_briefing():
    """Run an automated daily briefing and print results."""
    console.print(Panel(
        f"[bold]Daily Work Briefing[/bold]\n{datetime.datetime.now().strftime('%A, %d %B %Y — %H:%M')}",
        border_style="blue",
    ))
    prompt = (
        "Give me my full daily briefing. Include: "
        "1) Today's calendar events, "
        "2) Unread emails summary (top 10), "
        "3) My Jira issues that are In Progress. "
        "Format clearly with sections. Be concise."
    )
    response, _, _w = run_agent_turn([], prompt)
    console.print(Markdown(response))


def run_standup_summary():
    """Generate a standup summary."""
    console.print(Panel("[bold]Generating Standup Summary...[/bold]", border_style="green"))
    prompt = (
        "Generate my daily standup summary. Cover: "
        "1) What I worked on yesterday (Jira issues updated in last 24h), "
        "2) What I'm working on today (my In Progress Jira issues + today's meetings), "
        "3) Any blockers. "
        "Format as a clean standup message I can paste into Teams."
    )
    response, _, _w = run_agent_turn([], prompt)
    console.print(Markdown(response))


# ══════════════════════════════════════════════════════════════════════════════
# INTERACTIVE CHAT MODE
# ══════════════════════════════════════════════════════════════════════════════

def _provider_label() -> str:
    """Return a short label for the active provider (best-effort)."""
    try:
        from tools.llm_provider import list_available_providers
        available = list_available_providers()          # list of dicts: [{"name":..., "available":...}, ...]
        available_names = [p["name"] for p in available if p.get("available")]
        if not available_names:
            return "no provider configured"
        preferred = os.getenv("LLM_PROVIDER", "").strip().lower()
        active = preferred if preferred in available_names else available_names[0]
        return active.capitalize()
    except Exception:
        return "AI"


def run_chat():
    """Interactive chat loop."""
    provider_name = _provider_label()

    console.print(Panel(
        f"[bold blue]Work Assistant Agent[/bold blue]  [dim](powered by {provider_name})[/dim]\n"
        "[dim]Connected to: Outlook · Teams · SharePoint · Excel · Jira · Confluence\n"
        "               GitHub · Linear · Zoom · Google Meet · Word · PowerPoint[/dim]\n\n"
        "[dim]Type your request in plain English. Type[/dim] [bold]help[/bold] [dim]for examples.[/dim]\n"
        "[dim]Type[/dim] [bold]quit[/bold] [dim]to exit.[/dim]",
        border_style="blue",
    ))

    examples = (
        "\n[bold]Example commands:[/bold]\n"
        "  • What's on my calendar today?\n"
        "  • Summarise my unread emails\n"
        "  • Create a Jira bug in project MYPROJ: login button broken\n"
        "  • Move PROJ-42 to In Progress\n"
        "  • Draft a reply to the email from Sarah about the Q3 report\n"
        "  • Search SharePoint for the architecture document\n"
        "  • Write today's standup summary for Teams\n"
        "  • Read the Budget.xlsx spreadsheet\n"
        "  • Create a Confluence page about our new onboarding process\n"
        "  • What PRs need my review on GitHub?\n"
        "  • List my Linear issues in progress\n"
        "  • Create a Zoom meeting tomorrow at 2pm for 45 minutes\n"
        "  • Give me my daily briefing\n"
    )

    conversation_history = []

    while True:
        try:
            console.print()
            user_input = Prompt.ask("[bold green]You[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if user_input.lower() == "help":
            console.print(examples)
            continue

        if user_input.lower() == "clear":
            conversation_history = []
            console.print("[dim]Conversation history cleared.[/dim]")
            continue

        try:
            response, conversation_history, _w = run_agent_turn(conversation_history, user_input)
            console.print()
            console.print(Panel(
                Markdown(response),
                title="[bold blue]Assistant[/bold blue]",
                border_style="blue",
            ))
        except Exception as e:
            console.print(f"\n[red]❌  Error: {e}[/red]\n")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "chat"

    if mode == "briefing":
        run_daily_briefing()
    elif mode == "standup":
        run_standup_summary()
    elif mode in ("chat", "interactive"):
        run_chat()
    else:
        console.print(f"[red]Unknown mode: {mode}[/red]")
        console.print("Usage:  python agent.py [chat|briefing|standup]")
        sys.exit(1)


if __name__ == "__main__":
    main()
