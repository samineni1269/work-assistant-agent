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
         "team_id":    {"type": "string", "description": "Teams team ID (from list_teams)"},
         "channel_id": {"type": "string", "description": "Channel ID (from get_teams_channels)"},
         "message":    {"type": "string", "description": "Message text to post"},
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

    {"name": "get_sharepoint_sites",
     "description": "List all SharePoint sites the user has access to. Use when the user asks 'what SharePoint sites do I have', 'list my SharePoint sites', or before uploading to a specific site.",
     "parameters": {"type": "object", "properties": {
         "max_results": {"type": "integer", "description": "Max sites to return (default 20)"},
     }}},

    {"name": "upload_file_to_sharepoint",
     "description": "Upload a local file to SharePoint or OneDrive. Use when the user says 'upload this to SharePoint', 'save this file to SharePoint', 'put this on our SharePoint site', etc. WRITE — confirm before uploading.",
     "parameters": {"type": "object", "required": ["local_path"], "properties": {
         "local_path":  {"type": "string", "description": "Absolute path to the local file e.g. '/Users/me/report.docx'"},
         "site_id":     {"type": "string", "description": "SharePoint site ID (leave blank for OneDrive)"},
         "folder_path": {"type": "string", "description": "Destination folder in the drive e.g. '/Documents/Reports'"},
         "filename":    {"type": "string", "description": "Override filename (default: same as local file)"},
     }}},

    # ── EXCEL ─────────────────────────────────────────────────────────────────
    {"name": "create_excel_workbook",
     "description": "Create a new Excel workbook in OneDrive and populate it with data. Use when the user asks to 'create an Excel file', 'generate a spreadsheet', 'make an Excel sheet with records', 'generate employee data in Excel', etc. The LLM should generate the headers and rows based on the user's request.",
     "parameters": {"type": "object", "required": ["filename"], "properties": {
         "filename":   {"type": "string",  "description": "Name for the new file e.g. 'employees.xlsx'"},
         "sheet_name": {"type": "string",  "description": "Worksheet name (default 'Sheet1')"},
         "headers":    {"type": "array",   "items": {"type": "string"}, "description": "Column header row e.g. ['Name', 'Age', 'Department']"},
         "rows":       {"type": "array",   "items": {"type": "array", "items": {"type": "string"}},  "description": "Data rows, list of lists e.g. [['Alice', 30, 'HR'], ['Bob', 25, 'Eng']]"},
     }}},

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
     "description": "Create a new Word document saved locally (~/work-assistant-docs/). WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["title", "sections"], "properties": {
         "title":    {"type": "string", "description": "Document title shown as heading"},
         "subtitle": {"type": "string", "description": "Optional subtitle"},
         "filename": {"type": "string", "description": "Output filename e.g. 'Report.docx' (optional, auto-generated from title)"},
         "sections": {"type": "array", "description": "List of sections", "items": {"type": "object", "properties": {
             "heading": {"type": "string", "description": "Section heading"},
             "content": {"type": "array", "items": {"type": "string"}, "description": "Lines of text / bullet points"},
             "style":   {"type": "string", "enum": ["paragraph", "bullets", "table"], "description": "How to render content (default: paragraph)"},
             "table_data": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}, "description": "2-D array for table style — first row is headers"},
         }}},
     }}},

    {"name": "list_documents",
     "description": "List all locally saved documents (Word and PowerPoint) in the document library.",
     "parameters": {"type": "object", "properties": {
         "doc_type": {"type": "string", "enum": ["docx", "pptx"], "description": "Filter by type (optional)"},
     }}},

    {"name": "delete_document",
     "description": "Delete a document from the local library by its ID. WRITE — confirm before deleting.",
     "parameters": {"type": "object", "required": ["doc_id"], "properties": {
         "doc_id": {"type": "integer", "description": "Document ID from list_documents"},
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
     "description": "Create a PowerPoint presentation saved locally (~/work-assistant-docs/). WRITE — confirm.",
     "parameters": {"type": "object", "required": ["title", "slides"], "properties": {
         "title":    {"type": "string", "description": "Presentation title (shown on cover slide)"},
         "filename": {"type": "string", "description": "Output filename e.g. 'Deck.pptx' (optional, auto-generated)"},
         "theme":    {"type": "string", "enum": ["blue", "dark", "minimal"], "description": "Colour theme (default: blue)"},
         "slides":   {"type": "array", "description": "Slides to create", "items": {"type": "object", "properties": {
             "title":   {"type": "string", "description": "Slide title"},
             "layout":  {"type": "string", "enum": ["title", "bullets", "two_col", "blank"], "description": "Slide layout (default: bullets)"},
             "content": {"type": "array", "items": {"type": "string"}, "description": "Bullet points (for bullets layout)"},
             "col1":    {"type": "array", "items": {"type": "string"}, "description": "Left column bullets (two_col layout)"},
             "col2":    {"type": "array", "items": {"type": "string"}, "description": "Right column bullets (two_col layout)"},
             "notes":   {"type": "string", "description": "Speaker notes"},
         }}},
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
    {"name": "get_my_open_prs",
     "description": "Get all open pull requests authored by the current user across ALL repositories. Use this when the user asks 'list my open PRs', 'show my pull requests', 'what PRs do I have open' — i.e. without specifying a repo.",
     "parameters": {"type": "object", "properties": {
         "max_count": {"type": "integer", "description": "Max PRs to return (default 20)"},
     }}},

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

    # ── KNOWLEDGE BASE (RAG) ─────────────────────────────────────────────────
    {"name": "search_knowledge_base",
     "description": (
         "Search the personal knowledge base of uploaded documents (PDFs, policies, "
         "runbooks, notes). Use when the user asks about internal docs, company policies, "
         "or anything that might be in their uploaded files."
     ),
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string",  "description": "Natural language search query"},
         "max_results": {"type": "integer", "description": "Max results to return (default 4)"},
     }}},

    # ── BROWSER / WEB ────────────────────────────────────────────────────────
    {"name": "browse_url",
     "description": (
         "Visit any website and read its content. Use when the user asks about a specific "
         "webpage, wants to check a competitor's pricing, read an article, or access any "
         "site that has no dedicated API tool."
     ),
     "parameters": {"type": "object", "required": ["url"], "properties": {
         "url":          {"type": "string", "description": "Full URL to visit (https://...)"},
         "extract":      {"type": "string", "enum": ["text", "links", "both"],
                          "description": "What to extract from the page"},
         "wait_seconds": {"type": "integer", "description": "Wait for JS rendering (default 3)"},
     }}},

    {"name": "search_web",
     "description": (
         "Search the web via DuckDuckGo. Use when the user asks about current events, "
         "news, prices, or anything that requires up-to-date information from the internet."
     ),
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string",  "description": "Search query"},
         "max_results": {"type": "integer", "description": "Number of results (default 5)"},
     }}},

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

    # ── MEMORY ───────────────────────────────────────────────────────────────
    {"name": "update_memory_entry",
     "description": (
         "Save a fact about the user to long-term memory. Use when the user tells you "
         "something important to remember: their manager's name, current sprint, team, "
         "timezone, or any preference."
     ),
     "parameters": {"type": "object", "required": ["category", "key", "value"], "properties": {
         "category": {"type": "string",
                      "enum": ["preferences", "people", "context", "patterns", "facts"],
                      "description": "Memory category"},
         "key":      {"type": "string", "description": "Fact key e.g. 'manager', 'current_sprint'"},
         "value":    {"type": "string", "description": "Fact value"},
     }}},

    {"name": "get_memory_summary",
     "description": "Show the user everything the agent remembers about them.",
     "parameters": {"type": "object", "properties": {}}},

    # ── ANALYTICS ────────────────────────────────────────────────────────────
    {"name": "get_analytics_summary",
     "description": (
         "Show work pattern analytics — most-used tools, busiest hours, "
         "top categories. Use when the user asks 'how am I using the agent?' "
         "or 'what do I spend most time on?'"
     ),
     "parameters": {"type": "object", "properties": {
         "days_back": {"type": "integer", "description": "How many days to analyse (default 7)"},
     }}},

    # ── SLACK ────────────────────────────────────────────────────────────────
    {"name": "list_slack_channels",
     "description": "List public and private Slack channels the bot has access to.",
     "parameters": {"type": "object", "properties": {
         "max_count": {"type": "integer", "description": "Max channels to return (default 50)"},
     }}},

    {"name": "get_slack_messages",
     "description": "Get recent messages from a Slack channel or DM.",
     "parameters": {"type": "object", "required": ["channel_id"], "properties": {
         "channel_id": {"type": "string", "description": "Slack channel or DM ID (e.g. C01234567)"},
         "max_count":  {"type": "integer", "description": "Max messages to return (default 20)"},
     }}},

    {"name": "get_slack_thread",
     "description": "Get all replies in a Slack message thread.",
     "parameters": {"type": "object", "required": ["channel_id", "thread_ts"], "properties": {
         "channel_id": {"type": "string", "description": "Slack channel ID"},
         "thread_ts":  {"type": "string", "description": "Timestamp of the parent message"},
         "max_count":  {"type": "integer", "description": "Max replies to return"},
     }}},

    {"name": "list_slack_dms",
     "description": "List recent Slack direct message (DM) conversations.",
     "parameters": {"type": "object", "properties": {
         "max_count": {"type": "integer", "description": "Max DMs to list (default 20)"},
     }}},

    {"name": "get_slack_dm_history",
     "description": "Get DM message history with a specific Slack user by their user ID.",
     "parameters": {"type": "object", "required": ["user_id"], "properties": {
         "user_id":   {"type": "string", "description": "Slack user ID (e.g. U01234567)"},
         "max_count": {"type": "integer", "description": "Max messages to return"},
     }}},

    {"name": "search_slack",
     "description": "Search Slack messages across all channels by keyword.",
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string",  "description": "Search query (supports from:user, in:#channel modifiers)"},
         "max_results": {"type": "integer", "description": "Max results (default 15)"},
     }}},

    {"name": "get_slack_user_info",
     "description": "Get Slack user profile info by user ID.",
     "parameters": {"type": "object", "required": ["user_id"], "properties": {
         "user_id": {"type": "string", "description": "Slack user ID"},
     }}},

    {"name": "send_slack_message",
     "description": "Send a message to a Slack channel or DM. WRITE — confirm before sending.",
     "parameters": {"type": "object", "required": ["channel_id", "text"], "properties": {
         "channel_id": {"type": "string", "description": "Channel or DM ID (e.g. C01234 or D01234)"},
         "text":       {"type": "string", "description": "Message text (Slack markdown supported)"},
         "thread_ts":  {"type": "string", "description": "Reply to this thread timestamp (optional)"},
     }}},

    # ── NOTION ───────────────────────────────────────────────────────────────
    {"name": "search_notion",
     "description": "Search Notion pages and databases by keyword.",
     "parameters": {"type": "object", "required": ["query"], "properties": {
         "query":       {"type": "string",  "description": "Search string"},
         "max_results": {"type": "integer", "description": "Max results (default 10)"},
     }}},

    {"name": "get_notion_page",
     "description": "Read a Notion page — returns its full text content and properties.",
     "parameters": {"type": "object", "required": ["page_id"], "properties": {
         "page_id": {"type": "string", "description": "Notion page ID or full page URL"},
     }}},

    {"name": "create_notion_page",
     "description": "Create a new Notion page under an existing page or database. WRITE — confirm before creating.",
     "parameters": {"type": "object", "required": ["parent_id", "title"], "properties": {
         "parent_id":   {"type": "string", "description": "ID of parent page or database"},
         "title":       {"type": "string", "description": "Page title"},
         "content":     {"type": "string", "description": "Page content as plain text (markdown headings and bullets supported)"},
         "parent_type": {"type": "string", "description": "'page' or 'database'", "enum": ["page", "database"]},
     }}},

    {"name": "list_notion_databases",
     "description": "List all Notion databases the integration has access to.",
     "parameters": {"type": "object", "properties": {
         "max_results": {"type": "integer", "description": "Max databases to return (default 20)"},
     }}},

    {"name": "query_notion_database",
     "description": "Query a Notion database and return its entries.",
     "parameters": {"type": "object", "required": ["database_id"], "properties": {
         "database_id":     {"type": "string", "description": "Notion database ID"},
         "filter_property": {"type": "string", "description": "Property name to filter on (optional)"},
         "filter_value":    {"type": "string", "description": "Filter value to match (optional)"},
         "max_results":     {"type": "integer", "description": "Max entries to return (default 20)"},
     }}},

    # ── ACTION ITEMS & PRIORITY SCORING ─────────────────────────────────────
    {"name": "extract_action_items",
     "description": (
         "Extract concrete action items (TODOs, tasks) from a block of text using AI. "
         "Use on emails, meeting notes, or any text that might contain tasks. "
         "Automatically saves them to the action items database."
     ),
     "parameters": {"type": "object", "required": ["text"], "properties": {
         "text":   {"type": "string", "description": "The text to extract action items from"},
         "source": {"type": "string", "description": "Label for where this text came from (e.g. 'email', 'meeting')"},
         "save":   {"type": "boolean", "description": "Save extracted items to database (default true)"},
     }}},

    {"name": "get_my_action_items",
     "description": "Retrieve open or completed action items from the local database.",
     "parameters": {"type": "object", "properties": {
         "status":    {"type": "string", "description": "'open', 'completed', or 'all'", "enum": ["open", "completed", "all"]},
         "priority":  {"type": "string", "description": "Filter by priority: 'high', 'medium', 'low'"},
         "max_count": {"type": "integer", "description": "Max items to return (default 30)"},
     }}},

    {"name": "complete_action_item",
     "description": "Mark an action item as completed by its ID. WRITE — confirm before marking.",
     "parameters": {"type": "object", "required": ["item_id"], "properties": {
         "item_id": {"type": "integer", "description": "The action item's database ID"},
     }}},

    {"name": "score_notifications",
     "description": (
         "Score a list of notifications, emails, or issues by urgency using AI. "
         "Adds 'priority' (urgent/action_today/fyi/ignore) and 'reason' fields. "
         "Call this after fetching 5+ notifications to surface what needs attention."
     ),
     "parameters": {"type": "object", "required": ["notifications"], "properties": {
         "notifications": {
             "type": "array",
             "items": {"type": "object"},
             "description": "List of notification/email/issue dicts (each must have a 'title', 'subject', or 'text' field)",
         },
         "context": {"type": "string", "description": "Brief description of the user's role for better scoring (optional)"},
     }}},

    # ── CALENDAR SCHEDULING ──────────────────────────────────────────────────
    {"name": "find_free_slots",
     "description": (
         "Find available meeting slots when all attendees are free. "
         "Use before scheduling a meeting to avoid conflicts. "
         "Returns up to 10 free slots sorted by time."
     ),
     "parameters": {"type": "object", "required": ["attendees"], "properties": {
         "attendees":           {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses"},
         "duration_minutes":    {"type": "integer", "description": "Meeting duration in minutes (default 30)"},
         "days_ahead":          {"type": "integer", "description": "How many days to search (default 5)"},
         "working_hours_start": {"type": "integer", "description": "Start of working day in UTC hour (default 9)"},
         "working_hours_end":   {"type": "integer", "description": "End of working day in UTC hour (default 18)"},
     }}},

    # ── DAILY BRIEFING ───────────────────────────────────────────────────────
    {"name": "send_morning_briefing",
     "description": (
         "Compile and send the daily HTML briefing email. "
         "Aggregates: today's calendar, unread emails, open action items, open GitHub PRs, "
         "and GitHub notifications. WRITE — confirm before sending."
     ),
     "parameters": {"type": "object", "properties": {
         "recipient": {"type": "string", "description": "Override recipient email (defaults to BRIEFING_EMAIL env var)"},
     }}},

    # ── WEBHOOK EVENTS ───────────────────────────────────────────────────────
    {"name": "get_webhook_events",
     "description": "Retrieve recent real-time webhook events (GitHub, Jira) received by the listener.",
     "parameters": {"type": "object", "properties": {
         "source": {"type": "string", "description": "Filter by source: 'github' or 'jira' (default: all)"},
         "limit":  {"type": "integer", "description": "Max events to return (default 50)"},
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
        # Gemini requires array types to always declare their items schema
        if t == gt.Type.ARRAY:
            items = _schema(d["items"]) if d.get("items") else gt.Schema(type=gt.Type.STRING)
        else:
            items = None
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
    """Convert neutral tools to OpenAI/OpenRouter/MiniMax tool format.

    Strict-schema requirements (MiniMax M2.7, OpenAI strict mode):
      • Every parameter must have a non-empty 'description'
      • Top-level parameters object must include 'additionalProperties': false
      • Top-level parameters object must include 'type': 'object'

    This function enforces all three so every provider gets a valid schema.
    """
    result = []
    for tool in tools:
        params = dict(tool.get("parameters", {}))
        params["type"] = "object"
        if "properties" not in params:
            params["properties"] = {}

        # Ensure every parameter has a description
        fixed_props = {}
        for pname, pdef in params["properties"].items():
            pdef = dict(pdef)
            if not pdef.get("description"):
                pdef["description"] = pname.replace("_", " ").capitalize()
            fixed_props[pname] = pdef
        params["properties"] = fixed_props

        # MiniMax M2.7 strict mode: additionalProperties MUST be false
        params["additionalProperties"] = False

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


# ── Fast model names per provider ────────────────────────────────────────────
# These are used for simple, single-step read operations to save cost and latency.
FAST_MODELS = {
    "gemini":     "gemini-2.0-flash-lite",
    "claude":     "claude-haiku-4-5-20251001",
    "openai":     "gpt-4o-mini",
    "openrouter": "openai/gpt-4o-mini",
    "minimax":    "MiniMax-M2.5",
}

# Tools that are simple enough to run on the fast/cheap model
SIMPLE_READ_TOOLS = {
    "get_emails", "search_emails", "get_calendar_events",
    "get_teams_chats", "list_teams",
    "search_sharepoint", "list_sharepoint_files", "get_sharepoint_sites",
    "list_excel_sheets", "get_my_jira_issues", "get_jira_projects",
    "list_confluence_spaces", "get_github_notifications", "list_my_repos",
    "get_my_open_prs", "get_my_review_requests", "list_my_github_issues",
    "get_my_linear_issues", "list_linear_teams", "list_linear_projects",
    "list_zoom_meetings", "list_google_calendar_events",
    # Slack reads
    "list_slack_channels", "list_slack_dms", "get_slack_user_info",
    # Notion reads
    "search_notion", "list_notion_databases",
    # Action items / scheduling
    "get_my_action_items", "find_free_slots",
    # Webhook events
    "get_webhook_events",
    # Memory / analytics
    "get_memory_summary", "get_analytics_summary",
}


# ── Friendly API error parser ─────────────────────────────────────────────────

def _friendly_api_error(exc: Exception, provider: str, model: str) -> str:
    """
    Convert raw API errors into a clear, actionable user-facing message.
    Handles 429 quota/rate-limit, 400 schema errors, auth failures, etc.
    """
    msg = str(exc)
    low = msg.lower()

    # ── 429 / quota exhausted ────────────────────────────────────────────────
    if "429" in msg or "resource_exhausted" in low or "quota" in low or "rate" in low:
        # Check for free-tier limit: 0 means the model is not on free tier at all
        if "limit: 0" in msg or "free_tier" in low:
            return (
                f"⚠️ **{model}** is not available on the free Gemini tier (quota = 0).\n\n"
                f"**Quick fix:** Click the **🧠 AI Model** button in the top-right and switch to "
                f"`gemini-2.5-flash` (free) or add billing to your Google AI Studio account at "
                f"https://ai.dev/rate-limit"
            )
        # General rate limit (too many requests per minute)
        import re
        retry_match = re.search(r"retry[^0-9]*(\d+)", low)
        retry_hint  = f" Retry in ~{retry_match.group(1)}s." if retry_match else ""
        return (
            f"⚠️ **Rate limit hit** for `{model}` ({provider}).{retry_hint}\n\n"
            f"**Options:** Wait a moment and try again, or switch to a faster/cheaper model "
            f"using the **🧠 AI Model** button in the top-right."
        )

    # ── 401 / auth ───────────────────────────────────────────────────────────
    if "401" in msg or "unauthenticated" in low or "invalid_api_key" in low or "authentication" in low:
        return (
            f"⚠️ **API key invalid** for {provider}.\n\n"
            f"Click any **connection badge** at the bottom of the left sidebar to update your key."
        )

    # ── 400 schema error ─────────────────────────────────────────────────────
    if "400" in msg or "invalid_argument" in low:
        return (
            f"⚠️ **Bad request to {provider}** — there may be a schema mismatch for model `{model}`.\n\n"
            f"Try switching to a different model using the **🧠 AI Model** button, or check the terminal for details."
        )

    # ── Model not found ───────────────────────────────────────────────────────
    if "404" in msg or "not found" in low or "model_not_found" in low or "does not exist" in low:
        return (
            f"⚠️ **Model `{model}` not found** on {provider}.\n\n"
            f"Click the **🧠 AI Model** button to select a valid model."
        )

    # ── Fallback ─────────────────────────────────────────────────────────────
    return f"⚠️ **{provider} error:** {msg}"


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
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=gemini_history,
                config=gt.GenerateContentConfig(
                    system_instruction=system,
                    tools=gemini_tools,
                    temperature=0.1,
                ),
            )
        except Exception as exc:
            raise RuntimeError(_friendly_api_error(exc, "Gemini", self.model)) from exc
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
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=8096,
                system=system,
                messages=_to_claude_history(history),
                tools=_to_claude_tools(tools),
            )
        except Exception as exc:
            raise RuntimeError(_friendly_api_error(exc, "Claude", self.model)) from exc
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
        formatted_tools = _to_openai_tools(tools) if tools else None
        try:
            kwargs = dict(model=self.model, messages=messages, temperature=0.1)
            if formatted_tools:
                kwargs["tools"] = formatted_tools
            response = self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Log full error to terminal so we can diagnose the real cause
            import traceback
            print(f"\n[MiniMax ERROR] {type(exc).__name__}: {exc}")
            traceback.print_exc()
            raise RuntimeError(_friendly_api_error(exc, self.name.capitalize(), self.model)) from exc
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

    # MiniMax has a ~32 tool limit per request — group tools by domain
    _TOOL_GROUPS = {
        "email":    {"get_emails","get_email_body","send_email","search_emails"},
        "calendar": {"get_calendar_events","create_calendar_event","find_free_slots",
                     "list_google_calendar_events","create_google_meet"},
        "teams":    {"get_teams_chats","get_chat_messages","send_teams_message",
                     "list_teams","get_channel_messages","post_channel_message"},
        "slack":    {"list_slack_channels","get_slack_messages","get_slack_thread",
                     "list_slack_dms","get_slack_dm_history","search_slack",
                     "get_slack_user_info","send_slack_message"},
        "jira":     {"get_my_jira_issues","search_jira","get_jira_issue",
                     "create_jira_issue","update_jira_issue","transition_jira_issue",
                     "add_jira_comment","get_jira_projects"},
        "confluence":{"search_confluence","get_confluence_page","create_confluence_page",
                     "update_confluence_page","list_confluence_spaces"},
        "github":   {"get_my_open_prs","get_github_notifications","get_my_review_requests",
                     "list_my_repos","list_pull_requests","get_pull_request","get_pr_checks",
                     "get_repo_workflow_runs","search_github","list_my_github_issues",
                     "create_github_issue","add_pr_review","merge_pull_request"},
        "linear":   {"get_my_linear_issues","search_linear_issues","get_linear_issue",
                     "list_linear_teams","list_linear_workflow_states","list_linear_projects",
                     "create_linear_issue","update_linear_issue","transition_linear_issue",
                     "add_linear_comment"},
        "sharepoint":{"search_sharepoint","list_sharepoint_files","get_sharepoint_sites",
                     "upload_file_to_sharepoint"},
        "excel":    {"create_excel_workbook","read_excel_sheet","write_excel_cell",
                     "append_excel_row","list_excel_sheets"},
        "docs":     {"read_word_document","list_word_headings","create_word_document",
                     "list_documents","delete_document","update_word_document",
                     "read_presentation","get_presentation_summary","create_presentation",
                     "add_slide_to_presentation"},
        "zoom":     {"list_zoom_meetings","get_zoom_meeting","create_zoom_meeting",
                     "list_zoom_recordings"},
        "notion":   {"search_notion","get_notion_page","create_notion_page",
                     "list_notion_databases","query_notion_database"},
        "general":  {"search_knowledge_base","browse_url","search_web","deep_research","update_memory_entry",
                     "get_memory_summary","get_analytics_summary","extract_action_items",
                     "get_my_action_items","complete_action_item","score_notifications",
                     "send_morning_briefing","get_webhook_events"},
    }

    # Keywords that activate each group
    _GROUP_KEYWORDS = {
        "email":     ["email","mail","inbox","outlook","message","send","reply","unread"],
        "calendar":  ["calendar","meeting","schedule","event","slot","availability","book"],
        "teams":     ["teams","channel","chat","microsoft teams"],
        "slack":     ["slack","dm","channel"],
        "jira":      ["jira","ticket","issue","sprint","bug","story","epic"],
        "confluence":["confluence","wiki","page","space","documentation"],
        "github":    ["github","pr","pull request","repo","commit","branch","workflow","notification"],
        "linear":    ["linear","issue","roadmap"],
        "sharepoint":["sharepoint","onedrive","file","document","folder"],
        "excel":     ["excel","spreadsheet","worksheet","workbook"],
        "docs":      ["word","document","presentation","slide","deck","docx","pptx"],
        "zoom":      ["zoom","recording","webinar"],
        "notion":    ["notion","database","page"],
        "general":   [],  # always included
    }

    _MINIMAX_TOOL_LIMIT = 30

    def _select_tools(self, tools: list, history: list) -> list:
        """Return at most _MINIMAX_TOOL_LIMIT tools relevant to the current conversation."""
        # Get the last few user messages to detect intent
        recent_text = " ".join(
            m.get("content", "") or ""
            for m in history[-6:]
            if m.get("role") == "user"
        ).lower()

        tool_lookup = {t["name"]: t for t in tools}

        # Always include general tools
        selected = set(self._TOOL_GROUPS.get("general", set()))

        # Add groups whose keywords appear in recent messages
        for group, keywords in self._GROUP_KEYWORDS.items():
            if group == "general":
                continue
            if any(kw in recent_text for kw in keywords):
                selected |= self._TOOL_GROUPS.get(group, set())

        # If nothing matched (fresh conversation), include email + calendar + general
        if len(selected) <= len(self._TOOL_GROUPS.get("general", set())):
            selected |= self._TOOL_GROUPS.get("email", set())
            selected |= self._TOOL_GROUPS.get("calendar", set())

        # Build filtered list preserving original order, capped at limit
        filtered = [t for t in tools if t["name"] in selected]
        return filtered[:self._MINIMAX_TOOL_LIMIT]

    def run_turn(self, system, history, tools):
        import re
        # MiniMax rejects requests with too many tools — select relevant subset
        tools = self._select_tools(tools, history)
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


def _resolve_provider_name() -> str:
    """Return the active provider name string."""
    preferred = os.getenv("LLM_PROVIDER", "").strip().lower()
    if preferred and preferred in _REGISTRY:
        cls, key = _REGISTRY[preferred]
        if os.getenv(key):
            return preferred
        raise RuntimeError(
            f"LLM_PROVIDER={preferred!r} is set but {key} is missing in .env.\n"
            f"Add your {key} or change LLM_PROVIDER to an available provider."
        )
    for name in _PRIORITY:
        cls, key = _REGISTRY[name]
        if os.getenv(key):
            return name
    raise RuntimeError(
        "No LLM provider is configured.\n"
        "Add at least one of these to your .env file:\n"
        "  GEMINI_API_KEY      — https://aistudio.google.com/apikey (free)\n"
        "  ANTHROPIC_API_KEY   — https://console.anthropic.com\n"
        "  OPENAI_API_KEY      — https://platform.openai.com/api-keys\n"
        "  OPENROUTER_API_KEY  — https://openrouter.ai/keys\n"
        "  MINIMAX_API_KEY     — https://platform.minimax.io (Token Plan key: sk-cp-...)"
    )


def get_provider() -> BaseProvider:
    """
    Return an instantiated provider based on LLM_PROVIDER env var.
    Falls back through Gemini → Claude → OpenAI → OpenRouter until one is found.
    Raises RuntimeError if no provider is configured.
    """
    name = _resolve_provider_name()
    cls, _ = _REGISTRY[name]
    return cls()


def get_fast_provider() -> BaseProvider:
    """
    Return a provider configured with the fast/cheap model variant for the
    active provider. Used for simple single-tool reads to reduce cost and latency.
    If LLM_MODEL is explicitly overridden in .env, that takes precedence.
    """
    name = _resolve_provider_name()
    cls, _ = _REGISTRY[name]
    provider = cls()
    # Override to fast model only if user hasn't pinned a specific model
    if not os.getenv("LLM_MODEL") and name in FAST_MODELS:
        provider.default_model = FAST_MODELS[name]
    return provider


def should_use_fast_model(user_message: str, history_len: int) -> bool:
    """
    Heuristic: return True when the task is likely a simple single-step read.
    Uses keyword matching — no extra LLM call needed.
    """
    if history_len > 4:
        return False  # Mid-conversation — context matters, use full model
    msg = user_message.lower().strip()
    # Simple imperative patterns that map to a single list/get tool
    simple_patterns = [
        "list my", "show my", "what's on my", "what is on my",
        "get my", "fetch my", "check my",
        "list all", "show all", "how many",
        "what meetings", "what emails", "what issues",
        "my emails", "my calendar", "my jira", "my prs",
        "my notifications", "my channels", "my repos",
    ]
    return any(msg.startswith(p) or p in msg for p in simple_patterns)
