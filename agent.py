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
    # GitHub writes
    "create_github_issue", "add_pr_review", "merge_pull_request",
    # Linear writes
    "create_linear_issue", "update_linear_issue",
    "transition_linear_issue", "add_linear_comment",
    # Zoom / Meet writes
    "create_zoom_meeting", "create_google_meet",
    # Memory writes
    "update_memory_entry",
}


def dispatch_tool(name: str, args: dict) -> str:
    """Call the actual tool function and return result as JSON string."""
    ms   = _ms()
    atl  = _atl()
    docs = _docs()
    gh   = _gh()
    lin  = _lin()
    zoom = _zoom()

    dispatch = {
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
        "search_sharepoint":     lambda: ms.search_sharepoint(**args),
        "list_sharepoint_files": lambda: ms.list_sharepoint_files(**args),
        # Excel
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
        "create_word_document":    lambda: docs.create_word_document(**args),
        "update_word_document":    lambda: docs.update_word_document(**args),
        # PowerPoint
        "read_presentation":           lambda: docs.read_presentation(**args),
        "get_presentation_summary":    lambda: docs.get_presentation_summary(**args),
        "create_presentation":         lambda: docs.create_presentation(**args),
        "add_slide_to_presentation":   lambda: docs.add_slide_to_presentation(**args),
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

    try:
        result = dispatch[name]()
        return json.dumps(result, default=str, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


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

    base = f"""You are a professional work assistant for a corporate employee.
Today is {datetime.datetime.now().strftime("%A, %d %B %Y")}.

You have access to the following tools:
- Outlook: read emails, search emails, send emails, reply to emails
- Calendar: list events, create meetings (Teams or Google Meet)
- Teams: list chats, read messages, send messages, list channels, post to channels
- SharePoint: search documents, list files
- Excel (OneDrive): read sheets, write cells, append rows
- Jira: list my issues, search issues, view issue details, create issues, update issues, transition status, add comments
- Confluence: search pages, read pages, create pages, update pages
- Word (.docx): read documents, create documents, update documents
- PowerPoint (.pptx): read presentations, create presentations, add slides
- GitHub: notifications, pull requests, reviews, issues, workflow runs
- Linear: issues, projects, teams, workflow states
- Zoom: meetings, recordings
- Google Meet: calendar events with Meet links

Your principles:
1. READ operations (fetching, searching, listing) — execute immediately without asking.
2. WRITE operations (sending, creating, updating) — ALWAYS show a preview first and wait for confirmation.
3. Be concise and professional. Format results clearly using markdown.
4. If you need more information to complete a task (e.g. which project, which chat), ask the user a specific question.
5. For daily briefing, always fetch: today's calendar events, unread emails (top 10), and my Jira issues (In Progress).
6. For standup summary, fetch: my Jira issues updated in the last 24 hours, any blockers, and today's calendar.
7. Never guess IDs — if you don't know a chat ID, list chats first to find the right one.
"""

    if memory_ctx:
        base += f"\n\n{memory_ctx}"

    if tone_guide:
        base += f"\n\n{tone_guide}"

    return base


# ══════════════════════════════════════════════════════════════════════════════
# AGENTIC LOOP — multi-provider function calling with multi-turn
# ══════════════════════════════════════════════════════════════════════════════

def run_agent_turn(conversation_history: list, user_message: str,
                   auto_confirm: bool = False) -> tuple[str, list, list]:
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
    from tools.llm_provider import TOOLS, get_provider
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
        provider = get_provider()
    except RuntimeError as e:
        console.print(f"\n[red]❌  LLM provider error: {e}[/red]")
        console.print("[dim]Set at least one of: GEMINI_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY in your .env[/dim]\n")
        sys.exit(1)

    # Add user message to neutral history
    conversation_history.append({"role": "user", "content": user_message})

    tool_call_count = 0   # tracked for bulk_protection

    system_prompt = _build_system_prompt()

    while True:
        # run_turn returns (tool_calls, text)
        #   tool_calls: list of (name, args, call_id) — non-empty when model wants a tool
        #   text: final response string — non-empty when model is done
        tool_calls, text = provider.run_turn(system_prompt, conversation_history, TOOLS)

        if not tool_calls:
            # ── Guardrail 2: scrub secrets from final response ────────────────
            text = scrub_output(text)
            conversation_history.append({"role": "assistant", "content": text})

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

        # Model wants to call tools — record the assistant turn
        conversation_history.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": tc_id, "name": name, "args": args}
                for name, args, tc_id in tool_calls
            ],
        })

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
            conversation_history.append({
                "role": "tool",
                "call_id": tc_id,
                "name": t_name,
                "content": t_result,
            })

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
