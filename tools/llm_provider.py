"""
llm_provider.py — Multi-LLM Provider Abstraction
==================================================
Supported providers:
  • Gemini      (Google)     — GEMINI_API_KEY
  • Claude      (Anthropic)  — ANTHROPIC_API_KEY
  • OpenAI                   — OPENAI_API_KEY
  • OpenRouter               — OPENROUTER_API_KEY
  • MiniMax                  — MINIMAX_API_KEY  (Token Plan key: sk-cp-...)

.env configuration:
  LLM_PROVIDER=minimax       # gemini | claude | openai | openrouter | minimax
  LLM_MODEL=MiniMax-M2.7     # optional: override the default model for the chosen provider

Auto-detection order (if LLM_PROVIDER not set):
  Gemini → Claude → OpenAI → OpenRouter → MiniMax
"""

import os
import json
import uuid
from abc import ABC, abstractmethod

# ══════════════════════════════════════════════════════════════════════════════
# NEUTRAL TOOL DEFINITIONS  (OpenAI-compatible JSON Schema)
# ══════════════════════════════════════════════════════════════════════════════

TOOLS = [

    # ── OUTLOOK EMAIL ────────────────────────────────────────────────────────
    {"name": "get_emails",
     "description": "Fetch emails from Outlook inbox or another folder. Use to summarise inbox, list unread emails, or read recent messages.",
     "parameters": {"type": "object", "properties": {
         "folder":      {"type": "string",  "description": "Mailbox folder", "enum": ["inbox", "sentitems", "drafts"]},
         "max_count":   {"type": "integer", "description": "Number of emails to fetch (1-50)"},
         "unread_only": {"type": "boolean", "description": "Only return unread emails"},
     }}},

    {"name": "get_email_body",
     "description": "Get the full body text of a specific email by its ID.",
     "parameters": {"type": "object", "required": ["email_id"], "properties": {
         "email_id": {"type": "string", "description": "The email message ID"},
     }}},

    {"name": "send_email",
     "description": "Send an email or reply. WRITE — always show preview and confirm before sending.",
     "parameters": {"type": "object", "required": ["to", "subject", "body"], "properties": {
         "to":          {"type": "string", "description": "Recipient email address"},
         "subject":     {"type": "string", "description": "Email subject"},
         "body":        {"type": "string", "description": "Email body in plain text"},
         "reply_to_id": {"type": "string", "description": "ID of email to reply to (optional)"},
     }}},

    {"name": "search_emails",
     "description": "Search emails by keyword (subject, body, sender).",
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":     {"type": "string",  "description": "Search keyword"},
         "max_count": {"type": "integer", "description": "Max results (1-25)"},
     }}},

    # ── CALENDAR ─────────────────────────────────────────────────────────────
    {"name": "get_calendar_events",
     "description": "Get upcoming Outlook calendar events. Use for daily briefing, checking schedule.",
     "parameters": {"type": "object", "properties": {
         "days_ahead": {"type": "integer", "description": "How many days ahead to fetch (default 1)"},
     }}},

    {"name": "create_calendar_event",
     "description": "Create a new calendar event or Teams meeting. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["subject", "start", "end"], "properties": {
         "subject":   {"type": "string", "description": "Meeting title"},
         "start":     {"type": "string", "description": "ISO 8601 start time e.g. '2025-06-01T14:00:00'"},
         "end":       {"type": "string", "description": "ISO 8601 end time"},
         "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses"},
         "body":      {"type": "string", "description": "Meeting description"},
         "location":  {"type": "string", "description": "Physical location"},
         "online":    {"type": "boolean", "description": "True to generate Teams meeting link"},
     }}},

    # ── TEAMS ─────────────────────────────────────────────────────────────────
    {"name": "get_teams_chats",
     "description": "List recent Teams chats.",
     "parameters": {"type": "object", "properties": {
         "max_count": {"type": "integer", "description": "How many chats to list (default 10)"},
     }}},

    {"name": "get_chat_messages",
     "description": "Get recent messages from a specific Teams chat.",
     "parameters": {"type": "object", "required": ["chat_id"], "properties": {
         "chat_id":   {"type": "string",  "description": "Teams chat ID"},
         "max_count": {"type": "integer", "description": "Number of messages to fetch"},
     }}},

    {"name": "send_teams_message",
     "description": "Send a message to a Teams chat. WRITE — confirm before sending.",
     "parameters": {"type": "object", "required": ["chat_id", "message"], "properties": {
         "chat_id": {"type": "string", "description": "Teams chat ID"},
         "message": {"type": "string", "description": "Message to send"},
     }}},

    {"name": "list_teams",
     "description": "List all Microsoft Teams the user belongs to.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "get_channel_messages",
     "description": "Get recent messages from a Teams channel.",
     "parameters": {"type": "object", "required": ["team_id", "channel_id"], "properties": {
         "team_id":    {"type": "string",  "description": "Teams team ID"},
         "channel_id": {"type": "string",  "description": "Channel ID"},
         "max_count":  {"type": "integer", "description": "Number of messages"},
     }}},

    {"name": "post_channel_message",
     "description": "Post a message to a Teams channel. WRITE — confirm before posting.",
     "parameters": {"type": "object", "required": ["team_id", "channel_id", "message"], "properties": {
         "team_id":    {"type": "string"},
         "channel_id": {"type": "string"},
         "message":    {"type": "string"},
     }}},

    # ── SHAREPOINT ───────────────────────────────────────────────────────────
    {"name": "search_sharepoint",
     "description": "Search SharePoint for documents, files, and pages.",
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string",  "description": "Search keyword"},
         "max_results": {"type": "integer", "description": "Max results"},
     }}},

    {"name": "list_sharepoint_files",
     "description": "List files in a SharePoint/OneDrive folder.",
     "parameters": {"type": "object", "properties": {
         "site_id":     {"type": "string", "description": "SharePoint site ID (optional)"},
         "folder_path": {"type": "string", "description": "Folder path (default: root '/')"},
     }}},

    # ── EXCEL ─────────────────────────────────────────────────────────────────
    {"name": "read_excel_sheet",
     "description": "Read data from an Excel file stored in OneDrive/SharePoint.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename":   {"type": "string",  "description": "Excel filename e.g. 'Budget.xlsx'"},
         "sheet_name": {"type": "string",  "description": "Worksheet name (default: first sheet)"},
         "max_rows":   {"type": "integer", "description": "Max rows to return"},
     }}},

    {"name": "write_excel_cell",
     "description": "Write a value to a specific cell in an Excel file. WRITE — confirm before writing.",
     "parameters": {"type": "object", "required": ["filename", "sheet_name", "cell", "value"], "properties": {
         "filename":   {"type": "string"},
         "sheet_name": {"type": "string"},
         "cell":       {"type": "string", "description": "Cell address e.g. 'B5'"},
         "value":      {"type": "string", "description": "Value to write"},
     }}},

    {"name": "append_excel_row",
     "description": "Append a new row to an Excel sheet. WRITE — confirm before writing.",
     "parameters": {"type": "object", "required": ["filename", "sheet_name", "row_data"], "properties": {
         "filename":   {"type": "string"},
         "sheet_name": {"type": "string"},
         "row_data":   {"type": "array", "items": {"type": "string"}, "description": "Values for the new row"},
     }}},

    {"name": "list_excel_sheets",
     "description": "List all worksheet names in an Excel file.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename": {"type": "string"},
     }}},

    # ── JIRA ─────────────────────────────────────────────────────────────────
    {"name": "get_my_jira_issues",
     "description": "Get Jira issues assigned to the current user.",
     "parameters": {"type": "object", "properties": {
         "max_results": {"type": "integer", "description": "How many issues"},
         "status":      {"type": "string",  "description": "Filter by status e.g. 'In Progress'"},
     }}},

    {"name": "search_jira",
     "description": "Search Jira with a JQL query e.g. 'project = MYPROJECT AND status = Done'.",
     "parameters": {"type": "object", "required": ["jql"], "properties": {
         "jql":         {"type": "string",  "description": "JQL query string"},
         "max_results": {"type": "integer"},
     }}},

    {"name": "get_jira_issue",
     "description": "Get full details of a specific Jira issue by key e.g. 'PROJ-123'.",
     "parameters": {"type": "object", "required": ["issue_key"], "properties": {
         "issue_key": {"type": "string"},
     }}},

    {"name": "create_jira_issue",
     "description": "Create a new Jira issue/ticket. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["project_key", "summary"], "properties": {
         "project_key":    {"type": "string", "description": "Project key e.g. 'PROJ'"},
         "summary":        {"type": "string", "description": "Issue title"},
         "description":    {"type": "string"},
         "issue_type":     {"type": "string", "description": "'Task', 'Bug', 'Story', 'Epic'"},
         "priority":       {"type": "string", "description": "'Highest','High','Medium','Low','Lowest'"},
         "assignee_email": {"type": "string"},
         "labels":         {"type": "array", "items": {"type": "string"}},
         "due_date":       {"type": "string", "description": "YYYY-MM-DD"},
     }}},

    {"name": "update_jira_issue",
     "description": "Update fields on an existing Jira issue. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["issue_key"], "properties": {
         "issue_key":   {"type": "string"},
         "summary":     {"type": "string"},
         "description": {"type": "string"},
         "priority":    {"type": "string"},
         "labels":      {"type": "array", "items": {"type": "string"}},
         "due_date":    {"type": "string"},
     }}},

    {"name": "transition_jira_issue",
     "description": "Move a Jira issue to a different status. WRITE.",
     "parameters": {"type": "object", "required": ["issue_key", "transition_name"], "properties": {
         "issue_key":       {"type": "string"},
         "transition_name": {"type": "string", "description": "Target status name"},
     }}},

    {"name": "add_jira_comment",
     "description": "Add a comment to a Jira issue. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["issue_key", "comment"], "properties": {
         "issue_key": {"type": "string"},
         "comment":   {"type": "string"},
     }}},

    {"name": "get_jira_projects",
     "description": "List all Jira projects the user has access to.",
     "parameters": {"type": "object", "properties": {}}},

    # ── CONFLUENCE ───────────────────────────────────────────────────────────
    {"name": "search_confluence",
     "description": "Search Confluence pages and blog posts.",
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string"},
         "max_results": {"type": "integer"},
     }}},

    {"name": "get_confluence_page",
     "description": "Get the content of a Confluence page by ID.",
     "parameters": {"type": "object", "required": ["page_id"], "properties": {
         "page_id": {"type": "string"},
     }}},

    {"name": "create_confluence_page",
     "description": "Create a new Confluence page. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["space_id", "title", "content"], "properties": {
         "space_id":  {"type": "string", "description": "Confluence space ID"},
         "title":     {"type": "string"},
         "content":   {"type": "string", "description": "Page content (markdown-like)"},
         "parent_id": {"type": "string", "description": "Optional parent page ID"},
     }}},

    {"name": "update_confluence_page",
     "description": "Update an existing Confluence page. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["page_id", "new_content"], "properties": {
         "page_id":     {"type": "string"},
         "new_content": {"type": "string"},
         "title":       {"type": "string"},
         "append":      {"type": "boolean", "description": "Append instead of replace"},
     }}},

    {"name": "list_confluence_spaces",
     "description": "List all Confluence spaces.",
     "parameters": {"type": "object", "properties": {}}},

    # ── WORD (.docx) ─────────────────────────────────────────────────────────
    {"name": "read_word_document",
     "description": "Read a Word document (.docx) from OneDrive — returns text structured by headings.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename": {"type": "string", "description": "Word filename e.g. 'Report.docx'"},
     }}},

    {"name": "list_word_headings",
     "description": "Get the heading structure (table of contents) of a Word document.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename": {"type": "string"},
     }}},

    {"name": "create_word_document",
     "description": "Create a new Word document and upload it to OneDrive. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["filename", "title", "sections"], "properties": {
         "filename":      {"type": "string"},
         "title":         {"type": "string"},
         "sections":      {"type": "array", "items": {"type": "object", "properties": {
             "heading": {"type": "string"},
             "content": {"type": "string"},
         }}, "description": "List of sections"},
         "upload_folder": {"type": "string", "description": "OneDrive folder (default: '/')"},
     }}},

    {"name": "update_word_document",
     "description": "Update an existing Word document — append sections or replace text. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename":          {"type": "string"},
         "append_sections":   {"type": "array", "items": {"type": "object", "properties": {
             "heading": {"type": "string"}, "content": {"type": "string"},
         }}},
         "replace_paragraph": {"type": "object", "properties": {
             "find": {"type": "string"}, "replace": {"type": "string"},
         }},
     }}},

    # ── POWERPOINT (.pptx) ───────────────────────────────────────────────────
    {"name": "read_presentation",
     "description": "Read a PowerPoint file (.pptx) from OneDrive — returns all slide titles, content, and notes.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename": {"type": "string"},
     }}},

    {"name": "get_presentation_summary",
     "description": "Get a quick summary of a PowerPoint — just slide titles and bullet counts.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename": {"type": "string"},
     }}},

    {"name": "create_presentation",
     "description": "Create a PowerPoint presentation with a cover slide and content slides, then upload to OneDrive. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["filename", "title", "slides"], "properties": {
         "filename": {"type": "string"},
         "title":    {"type": "string"},
         "slides":   {"type": "array", "items": {"type": "object", "properties": {
             "title":   {"type": "string"},
             "bullets": {"type": "array", "items": {"type": "string"}},
             "notes":   {"type": "string"},
         }}},
         "theme":         {"type": "string", "enum": ["dark", "light"]},
         "upload_folder": {"type": "string"},
     }}},

    {"name": "add_slide_to_presentation",
     "description": "Add a new slide to an existing PowerPoint. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["filename", "slide_title", "bullets"], "properties": {
         "filename":    {"type": "string"},
         "slide_title": {"type": "string"},
         "bullets":     {"type": "array", "items": {"type": "string"}},
         "notes":       {"type": "string"},
     }}},

    # ── GITHUB ───────────────────────────────────────────────────────────────
    {"name": "get_github_notifications",
     "description": "Get GitHub notifications — PRs needing review, issue mentions, CI failures.",
     "parameters": {"type": "object", "properties": {
         "unread_only": {"type": "boolean"},
         "max_count":   {"type": "integer"},
     }}},

    {"name": "get_my_review_requests",
     "description": "Get all open pull requests where the current user's review has been requested.",
     "parameters": {"type": "object", "properties": {
         "max_count": {"type": "integer"},
     }}},

    {"name": "list_my_repos",
     "description": "List the current user's GitHub repositories.",
     "parameters": {"type": "object", "properties": {
         "visibility": {"type": "string", "enum": ["all", "public", "private"]},
         "max_count":  {"type": "integer"},
     }}},

    {"name": "list_pull_requests",
     "description": "List pull requests in a GitHub repository.",
     "parameters": {"type": "object", "required": ["repo"], "properties": {
         "repo":      {"type": "string", "description": "'owner/repo' format"},
         "state":     {"type": "string", "enum": ["open", "closed", "all"]},
         "max_count": {"type": "integer"},
     }}},

    {"name": "get_pull_request",
     "description": "Get full details of a pull request — body, files changed, reviews, CI checks.",
     "parameters": {"type": "object", "required": ["repo", "pr_number"], "properties": {
         "repo":      {"type": "string"},
         "pr_number": {"type": "integer"},
     }}},

    {"name": "get_pr_checks",
     "description": "Get CI/CD check results for a pull request.",
     "parameters": {"type": "object", "required": ["repo", "pr_number"], "properties": {
         "repo":      {"type": "string"},
         "pr_number": {"type": "integer"},
     }}},

    {"name": "get_repo_workflow_runs",
     "description": "Get recent GitHub Actions workflow runs for a repository.",
     "parameters": {"type": "object", "required": ["repo"], "properties": {
         "repo":      {"type": "string"},
         "max_count": {"type": "integer"},
     }}},

    {"name": "search_github",
     "description": "Search GitHub for issues, pull requests, or repositories.",
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string"},
         "search_type": {"type": "string", "enum": ["issues", "repositories"]},
         "max_count":   {"type": "integer"},
     }}},

    {"name": "list_my_github_issues",
     "description": "List GitHub issues assigned to the current user across all repos.",
     "parameters": {"type": "object", "properties": {
         "max_count": {"type": "integer"},
     }}},

    {"name": "create_github_issue",
     "description": "Create a new GitHub issue. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["repo", "title"], "properties": {
         "repo":      {"type": "string"},
         "title":     {"type": "string"},
         "body":      {"type": "string"},
         "labels":    {"type": "array", "items": {"type": "string"}},
         "assignees": {"type": "array", "items": {"type": "string"}},
     }}},

    {"name": "add_pr_review",
     "description": "Submit a review on a GitHub pull request. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["repo", "pr_number", "body"], "properties": {
         "repo":      {"type": "string"},
         "pr_number": {"type": "integer"},
         "body":      {"type": "string"},
         "event":     {"type": "string", "enum": ["COMMENT", "APPROVE", "REQUEST_CHANGES"]},
     }}},

    {"name": "merge_pull_request",
     "description": "Merge a GitHub pull request. WRITE — confirm before merging.",
     "parameters": {"type": "object", "required": ["repo", "pr_number"], "properties": {
         "repo":           {"type": "string"},
         "pr_number":      {"type": "integer"},
         "commit_message": {"type": "string"},
         "merge_method":   {"type": "string", "enum": ["merge", "squash", "rebase"]},
     }}},

    # ── LINEAR ───────────────────────────────────────────────────────────────
    {"name": "get_my_linear_issues",
     "description": "Get Linear issues assigned to the current user.",
     "parameters": {"type": "object", "properties": {
         "state_type": {"type": "string", "description": "Filter: 'started','unstarted','completed','cancelled','backlog'"},
         "max_count":  {"type": "integer"},
     }}},

    {"name": "search_linear_issues",
     "description": "Search Linear issues by keyword.",
     "parameters": {"type": "object", "required": ["query_str"], "properties": {
         "query_str": {"type": "string"},
         "max_count": {"type": "integer"},
     }}},

    {"name": "get_linear_issue",
     "description": "Get full details of a Linear issue by ID or identifier e.g. 'ENG-42'.",
     "parameters": {"type": "object", "required": ["issue_id"], "properties": {
         "issue_id": {"type": "string"},
     }}},

    {"name": "list_linear_teams",
     "description": "List all Linear teams the user is a member of.",
     "parameters": {"type": "object", "properties": {}}},

    {"name": "list_linear_workflow_states",
     "description": "List workflow states (columns) for a Linear team.",
     "parameters": {"type": "object", "required": ["team_id"], "properties": {
         "team_id": {"type": "string"},
     }}},

    {"name": "list_linear_projects",
     "description": "List Linear projects.",
     "parameters": {"type": "object", "properties": {
         "team_id": {"type": "string", "description": "Filter by team ID (optional)"},
     }}},

    {"name": "create_linear_issue",
     "description": "Create a new Linear issue. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["team_id", "title"], "properties": {
         "team_id":     {"type": "string"},
         "title":       {"type": "string"},
         "description": {"type": "string"},
         "priority":    {"type": "integer", "description": "0=No priority,1=Urgent,2=High,3=Medium,4=Low"},
         "assignee_id": {"type": "string"},
         "due_date":    {"type": "string"},
         "estimate":    {"type": "integer"},
     }}},

    {"name": "update_linear_issue",
     "description": "Update a Linear issue. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["issue_id"], "properties": {
         "issue_id":    {"type": "string"},
         "title":       {"type": "string"},
         "description": {"type": "string"},
         "priority":    {"type": "integer"},
         "due_date":    {"type": "string"},
         "estimate":    {"type": "integer"},
     }}},

    {"name": "transition_linear_issue",
     "description": "Move a Linear issue to a different workflow state. WRITE.",
     "parameters": {"type": "object", "required": ["issue_id", "state_name"], "properties": {
         "issue_id":   {"type": "string"},
         "state_name": {"type": "string"},
         "team_id":    {"type": "string"},
     }}},

    {"name": "add_linear_comment",
     "description": "Add a comment to a Linear issue. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["issue_id", "comment"], "properties": {
         "issue_id": {"type": "string"},
         "comment":  {"type": "string"},
     }}},

    # ── ZOOM ─────────────────────────────────────────────────────────────────
    {"name": "list_zoom_meetings",
     "description": "List upcoming Zoom meetings.",
     "parameters": {"type": "object", "properties": {
         "meeting_type": {"type": "string", "enum": ["upcoming", "live", "scheduled"]},
     }}},

    {"name": "get_zoom_meeting",
     "description": "Get full details of a Zoom meeting including join URL and password.",
     "parameters": {"type": "object", "required": ["meeting_id"], "properties": {
         "meeting_id": {"type": "string"},
     }}},

    {"name": "create_zoom_meeting",
     "description": "Create a new Zoom meeting. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["topic", "start_time"], "properties": {
         "topic":        {"type": "string"},
         "start_time":   {"type": "string", "description": "ISO 8601 start time"},
         "duration":     {"type": "integer", "description": "Duration in minutes"},
         "agenda":       {"type": "string"},
         "timezone":     {"type": "string"},
         "waiting_room": {"type": "boolean"},
         "auto_record":  {"type": "boolean"},
     }}},

    {"name": "list_zoom_recordings",
     "description": "List recent Zoom cloud recordings.",
     "parameters": {"type": "object", "properties": {
         "days_back": {"type": "integer"},
     }}},

    # ── GOOGLE MEET ──────────────────────────────────────────────────────────
    {"name": "list_google_calendar_events",
     "description": "List Google Calendar events — includes Google Meet video links.",
     "parameters": {"type": "object", "properties": {
         "days_ahead": {"type": "integer"},
     }}},

    {"name": "create_google_meet",
     "description": "Create a Google Calendar event with a Google Meet video link. WRITE — confirm.",
     "parameters": {"type": "object", "required": ["title", "start", "end"], "properties": {
         "title":       {"type": "string"},
         "start":       {"type": "string"},
         "end":         {"type": "string"},
         "attendees":   {"type": "array", "items": {"type": "string"}},
         "description": {"type": "string"},
         "timezone":    {"type": "string"},
     }}},
]

# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA CONVERTERS — neutral → provider-specific tool format
# ══════════════════════════════════════════════════════════════════════════════

def _to_gemini_tools(tools: list):
    """Convert neutral tools to Gemini FunctionDeclaration list."""
    from google.genai import types as gt

    def _schema(d: dict):
        if not d:
            return gt.Schema(type=gt.Type.OBJECT)
        type_map = {
            "string": gt.Type.STRING, "integer": gt.Type.INTEGER,
            "number": gt.Type.NUMBER, "boolean": gt.Type.BOOLEAN,
            "array":  gt.Type.ARRAY,  "object":  gt.Type.OBJECT,
        }
        t = type_map.get(d.get("type", "string"), gt.Type.STRING)
        props = {k: _schema(v) for k, v in d.get("properties", {}).items()} or None
        items = _schema(d["items"]) if d.get("items") else None
        return gt.Schema(
            type=t,
            description=d.get("description", ""),
            properties=props,
            items=items,
            enum=d.get("enum"),
            required=d.get("required") or None,
        )

    decls = []
    for tool in tools:
        params = tool.get("parameters", {})
        decls.append(gt.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=_schema(params),
        ))
    return decls


def _to_claude_tools(tools: list) -> list:
    """Convert neutral tools to Anthropic Claude tool format."""
    result = []
    for tool in tools:
        params = dict(tool.get("parameters", {}))
        # Claude's input_schema must have "type": "object"
        if "type" not in params:
            params["type"] = "object"
        if "properties" not in params:
            params["properties"] = {}
        result.append({
            "name":         tool["name"],
            "description":  tool["description"],
            "input_schema": params,
        })
    return result


def _to_openai_tools(tools: list) -> list:
    """Convert neutral tools to OpenAI/OpenRouter tool format."""
    result = []
    for tool in tools:
        params = dict(tool.get("parameters", {}))
        if "type" not in params:
            params["type"] = "object"
        if "properties" not in params:
            params["properties"] = {}
        result.append({
            "type": "function",
            "function": {
                "name":        tool["name"],
                "description": tool["description"],
                "parameters":  params,
            },
        })
    return result


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY CONVERTERS — neutral format → provider-specific
# ══════════════════════════════════════════════════════════════════════════════
#
# Neutral history format:
#   {"role": "user",      "content": "text"}
#   {"role": "assistant", "content": "text"}
#   {"role": "assistant", "content": None, "tool_calls": [{"id":..,"name":..,"args":{}}]}
#   {"role": "tool",      "call_id": "..", "name": "..", "content": ".."}

def _to_gemini_history(history: list) -> list:
    from google.genai import types as gt
    result = []
    i = 0
    while i < len(history):
        msg = history[i]
        role = msg["role"]

        if role == "user":
            result.append(gt.Content(role="user", parts=[gt.Part(text=msg["content"] or "")]))
            i += 1

        elif role == "assistant":
            if msg.get("tool_calls"):
                parts = [
                    gt.Part(function_call=gt.FunctionCall(name=tc["name"], args=tc["args"]))
                    for tc in msg["tool_calls"]
                ]
                result.append(gt.Content(role="model", parts=parts))
            else:
                result.append(gt.Content(role="model", parts=[gt.Part(text=msg.get("content") or "")]))
            i += 1

        elif role == "tool":
            # Group consecutive tool results into one "tool" message
            tool_parts = []
            while i < len(history) and history[i]["role"] == "tool":
                tr = history[i]
                try:
                    content_data = json.loads(tr["content"])
                except Exception:
                    content_data = tr["content"]
                tool_parts.append(gt.Part(
                    function_response=gt.FunctionResponse(
                        name=tr["name"],
                        response={"result": content_data},
                    )
                ))
                i += 1
            result.append(gt.Content(role="tool", parts=tool_parts))
        else:
            i += 1
    return result


def _to_claude_history(history: list) -> list:
    """Convert neutral history to Claude messages format.
    Claude tool results go in user role as tool_result blocks.
    Multiple consecutive tool results are merged into one user message.
    """
    result = []
    i = 0
    while i < len(history):
        msg = history[i]
        role = msg["role"]

        if role == "user":
            result.append({"role": "user", "content": msg["content"] or ""})
            i += 1

        elif role == "assistant":
            if msg.get("tool_calls"):
                content = [
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["args"]}
                    for tc in msg["tool_calls"]
                ]
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": "assistant", "content": msg.get("content") or ""})
            i += 1

        elif role == "tool":
            # Collect consecutive tool results into one user message
            tool_results = []
            while i < len(history) and history[i]["role"] == "tool":
                tr = history[i]
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tr["call_id"],
                    "content":     str(tr["content"]),
                })
                i += 1
            result.append({"role": "user", "content": tool_results})
        else:
            i += 1
    return result


def _to_openai_history(history: list) -> list:
    """Convert neutral history to OpenAI/OpenRouter messages format."""
    result = []
    for msg in history:
        role = msg["role"]
        if role == "user":
            result.append({"role": "user", "content": msg["content"] or ""})
        elif role == "assistant":
            if msg.get("tool_calls"):
                tool_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name":      tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
                result.append({
                    "role":       "assistant",
                    "content":    None,
                    "tool_calls": tool_calls,
                })
            else:
                result.append({"role": "assistant", "content": msg.get("content") or ""})
        elif role == "tool":
            result.append({
                "role":         "tool",
                "tool_call_id": msg["call_id"],
                "name":         msg["name"],
                "content":      str(msg["content"]),
            })
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER CLASSES
# ══════════════════════════════════════════════════════════════════════════════

class BaseProvider(ABC):
    name: str = "base"
    default_model: str = ""

    @property
    def model(self) -> str:
        return os.getenv("LLM_MODEL") or self.default_model

    @abstractmethod
    def run_turn(self, system: str, history: list, tools: list) -> tuple[list, str | None]:
        """
        Run one turn.
        Returns (tool_calls, text_response).
          tool_calls: list of (name, args_dict, call_id)
          text_response: str or None when tool calls are returned
        """


class GeminiProvider(BaseProvider):
    name = "gemini"
    default_model = "gemini-2.5-flash"

    def __init__(self):
        from google import genai
        self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def run_turn(self, system, history, tools):
        from google.genai import types as gt
        gemini_history = _to_gemini_history(history)
        gemini_tools   = [gt.Tool(function_declarations=_to_gemini_tools(tools))]

        response = self._client.models.generate_content(
            model=self.model,
            contents=gemini_history,
            config=gt.GenerateContentConfig(
                system_instruction=system,
                tools=gemini_tools,
                temperature=0.1,
            ),
        )
        parts = response.candidates[0].content.parts
        calls = [p.function_call for p in parts if p.function_call]
        if calls:
            return [(fc.name, dict(fc.args), f"gc_{uuid.uuid4().hex[:8]}") for fc in calls], None
        text = "\n".join(p.text for p in parts if hasattr(p, "text") and p.text)
        return [], text


class ClaudeProvider(BaseProvider):
    name = "claude"
    default_model = "claude-sonnet-4-6"

    def __init__(self):
        import anthropic
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def run_turn(self, system, history, tools):
        response = self._client.messages.create(
            model=self.model,
            max_tokens=8096,
            system=system,
            messages=_to_claude_history(history),
            tools=_to_claude_tools(tools),
        )
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        if tool_blocks:
            return [(b.name, b.input, b.id) for b in tool_blocks], None
        text = "\n".join(b.text for b in response.content if b.type == "text")
        return [], text


class OpenAIProvider(BaseProvider):
    name = "openai"
    default_model = "gpt-4o"
    _base_url = "https://api.openai.com/v1"
    _env_key  = "OPENAI_API_KEY"

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=os.environ[self._env_key],
            base_url=self._base_url,
        )

    def run_turn(self, system, history, tools):
        messages = [{"role": "system", "content": system}] + _to_openai_history(history)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=_to_openai_tools(tools),
            temperature=0.1,
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            calls = [
                (tc.function.name, json.loads(tc.function.arguments), tc.id)
                for tc in msg.tool_calls
            ]
            return calls, None
        return [], msg.content or ""


class OpenRouterProvider(OpenAIProvider):
    name = "openrouter"
    default_model = "anthropic/claude-sonnet-4-5"
    _base_url = "https://openrouter.ai/api/v1"
    _env_key  = "OPENROUTER_API_KEY"

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=os.environ[self._env_key],
            base_url=self._base_url,
            default_headers={
                "HTTP-Referer": "https://work-assistant-agent",
                "X-Title":      "Work Assistant Agent",
            },
        )


class MiniMaxProvider(OpenAIProvider):
    """MiniMax — OpenAI-compatible direct API.

    Supports both key types:
      • Token Plan key  (sk-cp-...)  — uses your 1,500 req/5-hour subscription quota
      • Pay-as-you-go key (sk-...)   — billed per token

    Set in .env:
      MINIMAX_API_KEY=sk-cp-...your key...
      LLM_PROVIDER=minimax
      LLM_MODEL=MiniMax-M2.7     # or MiniMax-M2.5 (optional)
    """
    name = "minimax"
    default_model = "MiniMax-M2.7"
    _base_url = "https://api.minimax.io/v1"
    _env_key  = "MINIMAX_API_KEY"

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI(
            api_key=os.environ[self._env_key],
            base_url=self._base_url,
        )

    def run_turn(self, system, history, tools):
        import re
        try:
            tool_calls, text = super().run_turn(system, history, tools)
        except Exception as e:
            err = str(e)
            # Friendly quota-exhausted message for Token Plan users
            if "429" in err or "quota" in err.lower() or "rate_limit" in err.lower():
                raise RuntimeError(
                    "⏳  MiniMax quota reached (1,500 requests per 5-hour window).\n"
                    "   Check your reset time at:\n"
                    "   https://platform.minimax.io/user-center/payment/token-plan\n"
                    "   The quota resets automatically — restart the agent after it resets."
                ) from e
            raise
        # Strip <think>...</think> blocks — MiniMax M2.7 uses interleaved thinking
        # which leaks reasoning text into the visible response.
        if text:
            text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
        return tool_calls, text


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER REGISTRY & FACTORY
# ══════════════════════════════════════════════════════════════════════════════

_REGISTRY = {
    "gemini":     (GeminiProvider,      "GEMINI_API_KEY"),
    "claude":     (ClaudeProvider,      "ANTHROPIC_API_KEY"),
    "openai":     (OpenAIProvider,      "OPENAI_API_KEY"),
    "openrouter": (OpenRouterProvider,  "OPENROUTER_API_KEY"),
    "minimax":    (MiniMaxProvider,     "MINIMAX_API_KEY"),
}

# Default fallback priority order
_PRIORITY = ["gemini", "claude", "openai", "openrouter", "minimax"]


def list_available_providers() -> list[dict]:
    """Return a list of providers with their availability status."""
    result = []
    for name in _PRIORITY:
        cls, key = _REGISTRY[name]
        available = bool(os.getenv(key))
        result.append({
            "name":      name,
            "env_key":   key,
            "available": available,
            "model":     os.getenv("LLM_MODEL") or cls.default_model,
        })
    return result


def get_provider() -> BaseProvider:
    """
    Return an instantiated provider based on LLM_PROVIDER env var.
    Falls back through Gemini → Claude → OpenAI → OpenRouter until one is found.
    Raises RuntimeError if no provider is configured.
    """
    preferred = os.getenv("LLM_PROVIDER", "").strip().lower()

    # Try preferred first
    if preferred and preferred in _REGISTRY:
        cls, key = _REGISTRY[preferred]
        if os.getenv(key):
            return cls()
        else:
            raise RuntimeError(
                f"LLM_PROVIDER={preferred!r} is set but {key} is missing in .env.\n"
                f"Add your {key} or change LLM_PROVIDER to an available provider."
            )

    # Auto-detect: first available in priority order
    for name in _PRIORITY:
        cls, key = _REGISTRY[name]
        if os.getenv(key):
            return cls()

    raise RuntimeError(
        "No LLM provider is configured.\n"
        "Add at least one of these to your .env file:\n"
        "  GEMINI_API_KEY      — https://aistudio.google.com/apikey (free)\n"
        "  ANTHROPIC_API_KEY   — https://console.anthropic.com\n"
        "  OPENAI_API_KEY      — https://platform.openai.com/api-keys\n"
        "  OPENROUTER_API_KEY  — https://openrouter.ai/keys\n"
        "  MINIMAX_API_KEY     — https://platform.minimax.io (Token Plan key: sk-cp-...)"
    )
