"""
app.py — Work Assistant Web UI
================================
Tool-navigation UI: each app (Outlook, Teams, Jira, etc.) has its own
workspace with its own conversation history. Free-form chat in every tool.

Run:  python3 app.py
"""

import os
import sys
import json
import threading
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify

app = Flask(__name__)

# ── Register webhook blueprint ────────────────────────────────────────────────
try:
    from tools.webhook_server import webhook_bp, init_webhook_db
    init_webhook_db()
    app.register_blueprint(webhook_bp)
except Exception as _wh_err:
    print(f"⚠️  Webhook listener unavailable: {_wh_err}")
app.config["SECRET_KEY"] = "work-assistant-local-7432"

# ── Global state ───────────────────────────────────────────────────────────────
_histories: dict = {}   # tool_id -> list of conversation turns
_jobs: dict = {}
_lock = threading.Lock()

PORT = 7432


# ══════════════════════════════════════════════════════════════════════════════
# TOOL DEFINITIONS — navigation items, chips, placeholder text
# ══════════════════════════════════════════════════════════════════════════════

TOOLS_NAV = [
    {
        "id": "home",
        "icon": "🏠",
        "name": "Home",
        "desc": "Daily briefing & overview",
        "chips": [
            "Give me my daily briefing",
            "Write my standup summary",
            "What's urgent right now?",
            "Summarise everything I missed today",
        ],
        "placeholder": "Ask for your daily briefing, standup, or anything at all…",
    },
    {
        "id": "outlook",
        "icon": "📧",
        "name": "Outlook",
        "desc": "Email & Calendar",
        "chips": [
            "Show my unread emails",
            "What's on my calendar today?",
            "What's on my calendar this week?",
            "Search emails about [topic]",
            "Send an email to [person]",
            "Schedule a meeting with [person]",
            "Reply to the latest email from [name]",
            "Draft a reply to the latest email from [name]",
        ],
        "placeholder": "Ask about emails, calendar events, meetings, or drafts…",
    },
    {
        "id": "teams",
        "icon": "💬",
        "name": "Teams",
        "desc": "Chats & Channels",
        "chips": [
            "Show my recent chats",
            "List all my Teams",
            "Read messages from [channel]",
            "Post a message to [channel]",
            "Send a message to [person]",
        ],
        "placeholder": "Ask about chats, channels, read messages, or post something…",
    },
    {
        "id": "sharepoint",
        "icon": "📁",
        "name": "SharePoint",
        "desc": "Files & OneDrive",
        "chips": [
            "Search SharePoint for [keyword]",
            "List files in [folder]",
            "Find the latest version of [document]",
        ],
        "placeholder": "Search SharePoint, browse OneDrive files, find documents…",
    },
    {
        "id": "excel",
        "icon": "📊",
        "name": "Excel",
        "desc": "Spreadsheets",
        "chips": [
            "Read the file [filename.xlsx]",
            "Show all sheet names in [file]",
            "Write [value] to cell [A1] in [file]",
            "Add a new row with [data] to [file]",
        ],
        "placeholder": "Read, write, or update any Excel file…",
    },
    {
        "id": "word",
        "icon": "📄",
        "name": "Word",
        "desc": "Documents",
        "chips": [
            "Read [document.docx]",
            "Show headings in [document]",
            "Create a document about [topic]",
            "Update [document] to add [content]",
        ],
        "placeholder": "Read, create, or update Word documents…",
    },
    {
        "id": "powerpoint",
        "icon": "🖼️",
        "name": "PowerPoint",
        "desc": "Presentations",
        "chips": [
            "Read [presentation.pptx]",
            "Summarise the deck [filename]",
            "Create a presentation about [topic]",
            "Add a slide to [filename] about [topic]",
        ],
        "placeholder": "Read, create, or update PowerPoint presentations…",
    },
    {
        "id": "jira",
        "icon": "🎫",
        "name": "Jira",
        "desc": "Issues & Tickets",
        "chips": [
            "Show all my open issues",
            "Create a ticket in [PROJECT]: [summary]",
            "Move [PROJ-123] to In Progress",
            "Search Jira for [query]",
            "Add a comment to [PROJ-123]",
            "What's blocking me in Jira?",
        ],
        "placeholder": "List issues, create tickets, update status, add comments…",
    },
    {
        "id": "confluence",
        "icon": "📝",
        "name": "Confluence",
        "desc": "Wiki & Knowledge",
        "chips": [
            "Search Confluence for [topic]",
            "Read the page [title]",
            "Create a page about [topic] in [space]",
            "Update the page [title]",
            "List all spaces",
        ],
        "placeholder": "Search, read, create, or update Confluence wiki pages…",
    },
    {
        "id": "github",
        "icon": "⚙️",
        "name": "GitHub",
        "desc": "Code & PRs",
        "chips": [
            "Show my unread notifications",
            "Which PRs need my review?",
            "List my open pull requests",
            "Check CI status for [repo] PR #[n]",
            "Create an issue in [repo]: [title]",
            "Merge PR #[n] in [repo]",
        ],
        "placeholder": "Check notifications, review PRs, create issues, check CI…",
    },
    {
        "id": "linear",
        "icon": "🎯",
        "name": "Linear",
        "desc": "Project Tracking",
        "chips": [
            "Show all my issues",
            "Create an issue: [title]",
            "Move [issue-id] to [state]",
            "List all projects",
            "Search for [keyword]",
        ],
        "placeholder": "View issues, create tasks, update status, manage projects…",
    },
    {
        "id": "zoom",
        "icon": "📹",
        "name": "Zoom & Meet",
        "desc": "Video Meetings",
        "chips": [
            "Show my upcoming Zoom meetings",
            "Create a Zoom meeting: [topic] [date] [time]",
            "Show my Google Calendar with Meet links",
            "Create a Google Meet: [title] [date]",
            "Show my Zoom recordings",
        ],
        "placeholder": "View or create Zoom and Google Meet meetings…",
    },
    {
        "id": "slack",
        "icon": "💬",
        "name": "Slack",
        "desc": "Channels, DMs & Search",
        "chips": [
            "List all Slack channels",
            "Show messages in #[channel]",
            "Search Slack for [keyword]",
            "Send a message to [channel]",
            "Show DMs with [person]",
        ],
        "placeholder": "Browse channels, read messages, search, or send Slack messages…",
    },
    {
        "id": "notion",
        "icon": "📓",
        "name": "Notion",
        "desc": "Pages & Databases",
        "chips": [
            "Search Notion for [topic]",
            "Read the page [title]",
            "List all databases",
            "Query the [database] database",
            "Create a page about [topic]",
        ],
        "placeholder": "Search, read, create Notion pages and query databases…",
    },
    {
        "id": "actions",
        "icon": "✅",
        "name": "Action Items",
        "desc": "Extract & Track Tasks",
        "chips": [
            "Show all my open action items",
            "Show high priority items",
            "What's due today?",
            "Extract action items from: [text]",
            "Mark item #[id] as complete",
            "Show completed tasks",
            "Score these notifications by urgency",
        ],
        "placeholder": "View open tasks, extract action items from text, mark complete…",
    },
    {
        "id": "briefing",
        "icon": "🌅",
        "name": "Briefing",
        "desc": "Daily Email & Scheduling",
        "chips": [
            "Send me today's briefing now",
            "Find a free slot for [person] this week",
            "Schedule a 30-min meeting with [email]",
            "Start the daily 8am briefing scheduler",
        ],
        "placeholder": "Send daily briefing, find free meeting slots, schedule meetings…",
    },
    {
        "id": "webhooks",
        "icon": "🔔",
        "name": "Webhooks",
        "desc": "Live GitHub & Jira Events",
        "chips": [
            "Show recent webhook events",
            "Show GitHub events",
            "Show Jira events",
        ],
        "placeholder": "View real-time GitHub and Jira webhook events…",
    },
    {
        "id": "superagent",
        "icon": "🧠",
        "name": "Super Agent",
        "desc": "AI · Memory · Web · KB",
        "chips": [
            "What do you remember about me?",
            "Search my knowledge base for [topic]",
            "Browse [URL] and summarise it",
            "Search the web for [topic]",
            "Show my work pattern analytics",
        ],
        "placeholder": "Use AI memory, browse the web, search knowledge base, analytics…",
    },
]

TOOLS_NAV_JSON = json.dumps(TOOLS_NAV)


# ══════════════════════════════════════════════════════════════════════════════
# CONNECTION STATUS
# ══════════════════════════════════════════════════════════════════════════════

INTEGRATIONS = [
    ("M365",      ["MS_CLIENT_ID"],                   all, "Outlook · Teams · SharePoint · Excel · Word · PPT"),
    ("Atlassian", ["ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"], all, "Jira · Confluence"),
    ("GitHub",    ["GITHUB_TOKEN"],                   all, "GitHub"),
    ("Linear",    ["LINEAR_API_KEY"],                 all, "Linear"),
    ("AI",        ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                   "OPENROUTER_API_KEY", "MINIMAX_API_KEY"],  any, "AI Engine"),
    ("Zoom",      ["ZOOM_CLIENT_ID"],                 all, "Zoom"),
    ("G-Meet",    ["GOOGLE_CLIENT_ID"],               all, "Google Meet"),
    ("Slack",     ["SLACK_BOT_TOKEN"],                all, "Slack"),
    ("Notion",    ["NOTION_TOKEN"],                   all, "Notion"),
]


# ── Credentials config — drives the in-browser credentials modal ─────────────
CREDS_CONFIG = {
    "M365": {
        "label": "Microsoft 365",
        "desc": "Required for Outlook, Teams, SharePoint, Excel, Word, PowerPoint",
        "setup_url": "https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "fields": [
            {"key": "MS_CLIENT_ID",  "label": "Azure App Client ID",              "placeholder": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", "secret": False},
            {"key": "MS_TENANT_ID",  "label": "Tenant ID (use 'common' for any)", "placeholder": "common",                               "secret": False},
        ],
    },
    "Atlassian": {
        "label": "Atlassian — Jira & Confluence",
        "desc": "Get your API token at id.atlassian.com → Security → API tokens",
        "setup_url": "https://id.atlassian.com/manage-profile/security/api-tokens",
        "fields": [
            {"key": "ATLASSIAN_EMAIL",     "label": "Atlassian Email",  "placeholder": "you@company.com",           "secret": False},
            {"key": "ATLASSIAN_API_TOKEN", "label": "API Token",        "placeholder": "your-api-token",             "secret": True},
            {"key": "ATLASSIAN_DOMAIN",    "label": "Domain",           "placeholder": "your-company.atlassian.net", "secret": False},
        ],
    },
    "GitHub": {
        "label": "GitHub",
        "desc": "Create a PAT with repo, notifications, read:user scopes",
        "setup_url": "https://github.com/settings/tokens/new",
        "fields": [
            {"key": "GITHUB_TOKEN",    "label": "Personal Access Token", "placeholder": "ghp_...",       "secret": True},
            {"key": "GITHUB_USERNAME", "label": "Your GitHub username",  "placeholder": "your-username", "secret": False},
        ],
    },
    "Linear": {
        "label": "Linear",
        "desc": "Get your API key from Linear → Settings → API → Personal API keys",
        "setup_url": "https://linear.app/settings/api",
        "fields": [
            {"key": "LINEAR_API_KEY", "label": "API Key", "placeholder": "lin_api_...", "secret": True},
        ],
    },
    "AI": {
        "label": "AI Engine",
        "desc": "Add at least one provider key. Gemini has a free tier — great to start.",
        "setup_url": "https://aistudio.google.com/apikey",
        "fields": [
            {"key": "GEMINI_API_KEY",     "label": "Google Gemini API Key", "placeholder": "AIza...",    "secret": True},
            {"key": "ANTHROPIC_API_KEY",  "label": "Anthropic Claude Key",  "placeholder": "sk-ant-...", "secret": True},
            {"key": "OPENAI_API_KEY",     "label": "OpenAI API Key",        "placeholder": "sk-...",     "secret": True},
            {"key": "OPENROUTER_API_KEY", "label": "OpenRouter API Key",    "placeholder": "sk-or-...",  "secret": True},
            {"key": "MINIMAX_API_KEY",    "label": "MiniMax API Key",       "placeholder": "sk-cp-...",  "secret": True},
        ],
    },
    "Zoom": {
        "label": "Zoom",
        "desc": "Create a Server-to-Server OAuth app at marketplace.zoom.us",
        "setup_url": "https://marketplace.zoom.us/develop/create",
        "fields": [
            {"key": "ZOOM_ACCOUNT_ID",    "label": "Account ID",    "placeholder": "your-account-id",    "secret": False},
            {"key": "ZOOM_CLIENT_ID",     "label": "Client ID",     "placeholder": "your-client-id",     "secret": False},
            {"key": "ZOOM_CLIENT_SECRET", "label": "Client Secret", "placeholder": "your-client-secret", "secret": True},
        ],
    },
    "G-Meet": {
        "label": "Google Meet",
        "desc": "Create OAuth 'Desktop app' credentials in Google Cloud Console",
        "setup_url": "https://console.cloud.google.com/apis/credentials",
        "fields": [
            {"key": "GOOGLE_CLIENT_ID",     "label": "Client ID",     "placeholder": "...apps.googleusercontent.com", "secret": False},
            {"key": "GOOGLE_CLIENT_SECRET", "label": "Client Secret", "placeholder": "GOCSPX-...",                    "secret": True},
        ],
    },
    "Slack": {
        "label": "Slack",
        "desc": "Create a Slack app → OAuth & Permissions → Bot Token Scopes: channels:read, chat:write, search:read",
        "setup_url": "https://api.slack.com/apps",
        "fields": [
            {"key": "SLACK_BOT_TOKEN", "label": "Bot User OAuth Token", "placeholder": "xoxb-...", "secret": True},
        ],
    },
    "Notion": {
        "label": "Notion",
        "desc": "Create an integration at notion.so/my-integrations, then share pages with it",
        "setup_url": "https://www.notion.so/my-integrations",
        "fields": [
            {"key": "NOTION_TOKEN", "label": "Integration Secret", "placeholder": "secret_...", "secret": True},
        ],
    },
}


# ── Model presets — shown in the model-switcher dropdown ─────────────────────
MODEL_PRESETS = {
    "gemini": [
        {"id": "gemini-2.5-flash",      "label": "2.5 Flash",      "tag": "recommended · free"},
        {"id": "gemini-2.5-pro",        "label": "2.5 Pro",        "tag": "smartest"},
        {"id": "gemini-2.5-flash-lite", "label": "2.5 Flash Lite", "tag": "cheapest · free"},
    ],
    "claude": [
        {"id": "claude-sonnet-4-6",         "label": "Sonnet 4.6", "tag": "recommended"},
        {"id": "claude-opus-4-6",           "label": "Opus 4.6",   "tag": "powerful"},
        {"id": "claude-opus-4-7",           "label": "Opus 4.7",   "tag": "smartest"},
        {"id": "claude-haiku-4-5-20251001", "label": "Haiku 4.5",  "tag": "fastest"},
    ],
    "openai": [
        {"id": "gpt-4o",      "label": "GPT-4o",      "tag": "recommended"},
        {"id": "gpt-4o-mini", "label": "GPT-4o Mini", "tag": "fast · cheap"},
        {"id": "o3",          "label": "o3",           "tag": "reasoning"},
        {"id": "gpt-5.5",     "label": "GPT-5.5",     "tag": "flagship"},
    ],
    "openrouter": [
        {"id": "anthropic/claude-sonnet-4.6", "label": "Claude Sonnet 4.6", "tag": "recommended"},
        {"id": "anthropic/claude-opus-4.7",   "label": "Claude Opus 4.7",   "tag": "smartest"},
        {"id": "anthropic/claude-opus-4.6",   "label": "Claude Opus 4.6",   "tag": "powerful"},
        {"id": "deepseek/deepseek-v3.2",      "label": "DeepSeek V3.2",     "tag": "fast · cheap"},
        {"id": "deepseek/deepseek-chat:free", "label": "DeepSeek V3 Free",  "tag": "free"},
        {"id": "google/gemini-2.5-flash",     "label": "Gemini 2.5 Flash",  "tag": "free tier"},
        {"id": "openai/gpt-5.1",              "label": "GPT-5.1",           "tag": "powerful"},
    ],
    "minimax": [
        {"id": "MiniMax-M2.7",    "label": "M2.7",     "tag": "recommended"},
        {"id": "MiniMax-M2.5",    "label": "M2.5",     "tag": "stable"},
        {"id": "MiniMax-M1",      "label": "M1",       "tag": "reasoning"},
        {"id": "MiniMax-Text-01", "label": "Text-01",  "tag": "4M context"},
    ],
}


def _check_connections():
    result = []
    for name, env_keys, strategy, tooltip in INTEGRATIONS:
        configured = strategy(os.getenv(k) for k in env_keys)
        result.append({"name": name, "ok": bool(configured), "tooltip": tooltip})
    return result


def _write_env_vars(updates: dict) -> dict:
    """Write key=value pairs to .env and update os.environ in-process."""
    env_path = Path(__file__).parent / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    saved = []
    for key, value in updates.items():
        if not value:
            continue
        replaced = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                lines[i] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")
        os.environ[key] = value
        saved.append(key)
    env_path.write_text("\n".join(lines) + "\n")
    return {"saved": saved}


# ══════════════════════════════════════════════════════════════════════════════
# HTML TEMPLATE  (tool-navigation UI)
# ══════════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Work Assistant</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#16181d;color:#d4d8e8;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;display:flex;height:100vh;overflow:hidden;font-size:13px}

/* ── Left nav ── */
#nav{width:220px;min-width:220px;background:#1a1c24;display:flex;flex-direction:column;border-right:1px solid #252836;overflow:hidden}
#nav-logo{padding:14px 16px 12px;border-bottom:1px solid #252836;display:flex;align-items:center;gap:10px;flex-shrink:0}
#nav-logo-icon{font-size:20px}
#nav-logo-text{color:#64ffda;font-size:14px;font-weight:700;letter-spacing:-.3px}
#nav-logo-sub{color:#6b7394;font-size:10px;margin-top:1px}
#nav-items{flex:1;overflow-y:auto;padding:6px 0}
.ni{display:flex;align-items:center;gap:10px;padding:8px 14px;cursor:pointer;transition:background .12s,border-color .12s;color:#8892b0;font-size:12.5px;border-left:3px solid transparent;margin:1px 0;user-select:none}
.ni:hover{background:#21232e;color:#d4d8e8}
.ni.active{background:#1c2540;color:#64ffda;border-left-color:#64ffda}
.ni .ni-icon{font-size:15px;width:22px;text-align:center;flex-shrink:0}
.ni .ni-info{flex:1;min-width:0}
.ni .ni-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ni .ni-desc{font-size:10px;color:#6b7394;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ni.active .ni-desc{color:#4a9a7a}
.nav-sep{height:1px;background:#252836;margin:4px 10px}
#nav-bottom{border-top:1px solid #252836;flex-shrink:0;padding:8px 0}
#conn-strip{display:flex;flex-wrap:wrap;gap:3px;padding:6px 12px 4px}
.cd{font-size:10px;padding:2px 6px;border-radius:3px;font-weight:600}
.cd-ok{color:#50fa7b;background:#0d2a1a}.cd-no{color:#6b7394;background:#1e2028}
#nav-links{display:flex;justify-content:space-between;align-items:center;padding:4px 12px 6px}
.nav-link-btn{background:none;border:none;color:#6b7394;font-size:10px;cursor:pointer;padding:2px 0}
.nav-link-btn:hover{color:#d4d8e8}
#pub-url{font-size:9px;color:#6b7394;padding:0 12px 6px;word-break:break-all}

/* ── Main area ── */
#main{flex:1;display:flex;flex-direction:column;min-width:0}

/* ── Tool header ── */
#tool-hdr{display:flex;align-items:center;gap:12px;padding:11px 20px;border-bottom:1px solid #252836;background:#1a1c24;flex-shrink:0}
#tool-hdr-icon{font-size:24px;line-height:1}
#tool-hdr-info{flex:1;min-width:0}
#tool-hdr-name{font-size:15px;font-weight:700;color:#d4d8e8;white-space:nowrap}
#tool-hdr-desc{font-size:11px;color:#6b7394;margin-top:1px}
#hdr-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
.hdr-btn{background:none;border:none;color:#6b7394;font-size:14px;cursor:pointer;padding:4px;border-radius:4px;transition:color .15s,background .15s}
.hdr-btn:hover{color:#d4d8e8;background:#252836}

/* Bell */
#bell-wrap{position:relative}
#bell-dot{display:none;position:absolute;top:0;right:0;width:7px;height:7px;background:#ff5555;border-radius:50%;border:1px solid #1a1c24}
#alert-tray{display:none;position:absolute;right:0;top:28px;width:260px;background:#1e2028;border:1px solid #e94560;border-radius:6px;z-index:200;max-height:220px;overflow-y:auto;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.al-row{padding:8px 10px;border-bottom:1px solid #252836;font-size:11px;color:#d4d8e8;cursor:pointer}
.al-row:hover{background:#252836}.al-row b{color:#ff5555}

/* ── Chat area ── */
#chat{flex:1;overflow-y:auto;padding:20px 24px;scroll-behavior:smooth}

/* Welcome screen */
#welcome{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;text-align:center;padding:32px;gap:0}
#wlc-icon{font-size:44px;margin-bottom:14px}
#wlc-title{font-size:20px;font-weight:700;color:#d4d8e8;margin-bottom:6px}
#wlc-sub{font-size:13px;color:#6b7394;max-width:400px;line-height:1.6;margin-bottom:28px}
#chips{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:520px}
.chip{background:#1e2028;border:1px solid #2a2d3a;color:#c4cde8;border-radius:20px;padding:7px 15px;font-size:12px;cursor:pointer;transition:all .15s;text-align:left}
.chip:hover{background:#252836;border-color:#64ffda;color:#64ffda}

/* Messages */
.msg{margin-bottom:18px}
.mhdr{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.mn-u{color:#64ffda;font-weight:700;font-size:12px}
.mn-a{color:#bd93f9;font-weight:700;font-size:12px}
.mts{color:#6b7394;font-size:10px}
.mbody{line-height:1.7;white-space:pre-wrap;font-size:13px}
.mu{color:#cdd6f4}.ma{color:#d4d8e8}.me{color:#ff5555}
.mbody b,.mbody strong{font-weight:700}
.mbody code{background:#2a2a3e;color:#f8f8f2;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:11px}
.mbody .blt{display:block;padding-left:16px}.mbody .blt::before{content:"•";margin-left:-16px;margin-right:8px}
#thinking-msg{color:#6b7394;font-style:italic;font-size:12px;padding:6px 0;display:flex;align-items:center;gap:8px}
.spinner{width:12px;height:12px;border:2px solid #3a4a70;border-top-color:#64ffda;border-radius:50%;animation:spin .7s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}
.mwarn{background:#2a2010;border-left:3px solid #ffb86c;border-radius:4px;padding:5px 10px;margin-top:4px;font-size:11px;color:#ffb86c;white-space:pre-wrap}

/* ── Input bar ── */
#inp-area{background:#1a1c24;padding:12px 20px 14px;border-top:1px solid #252836;flex-shrink:0}
#inp-row{display:flex;gap:8px;align-items:flex-end}
#mic{background:#252836;color:#8892b0;border:none;border-radius:6px;padding:10px 13px;font-size:16px;cursor:pointer;align-self:stretch;flex-shrink:0;transition:all .15s}
#mic:hover{background:#2a2d3a;color:#d4d8e8}
#mic.listening{background:#e94560;color:#fff;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.55}}
#inp{flex:1;background:#13151a;border:1px solid #252836;border-radius:6px;padding:10px 14px;color:#d4d8e8;font-size:13px;font-family:inherit;resize:none;outline:none;height:58px;max-height:180px;transition:border-color .15s;line-height:1.5}
#inp:focus{border-color:#3a4a70}
#inp::placeholder{color:#3a4060}
#snd{background:#e94560;color:#fff;border:none;border-radius:6px;padding:10px 18px;font-size:14px;font-weight:700;cursor:pointer;align-self:stretch;flex-shrink:0;transition:background .15s}
#snd:hover{background:#c73652}
#snd:disabled{background:#2a2a3a;cursor:default}
#inp-hint{color:#6b7394;font-size:10px;margin-top:5px;display:flex;align-items:center;gap:12px}
.inp-hint-sep{color:#3a3a4a}

/* ── Analytics overlay ── */
#an-ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:300;align-items:center;justify-content:center}
#an-ov.show{display:flex}
#an-box{background:#1e2028;border:1px solid #2a2d3a;border-radius:10px;padding:22px 26px;width:480px;max-height:70vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,.5)}
#an-box h3{color:#64ffda;margin-bottom:14px;font-size:15px}
.ar{display:flex;justify-content:space-between;align-items:center;padding:5px 0;font-size:12px;border-bottom:1px solid #252836}
.al-lbl{color:#8892b0}.al-val{color:#d4d8e8;font-weight:700}
.bw{background:#13151a;border-radius:3px;height:5px;flex:1;margin:0 8px;overflow:hidden;min-width:40px}
.bf{height:100%;background:#64ffda;border-radius:3px}
#an-close{margin-top:16px;background:#e94560;color:#fff;border:none;border-radius:5px;padding:7px 18px;cursor:pointer;font-size:12px;font-weight:700}

/* Guardrails panel in nav */
#gr-panel{border-top:1px solid #252836;padding:6px 0;flex-shrink:0}
.gr-hdr{display:flex;justify-content:space-between;align-items:center;padding:4px 12px 5px}
.gr-hdr-lbl{color:#8892b0;font-size:9px;font-weight:700;letter-spacing:.06em}
.gr-badge{font-size:9px;color:#6b7394}
.gr-row{display:flex;align-items:center;padding:3px 8px 3px 12px;gap:6px}
.gr-icon{font-size:10px;width:14px}.gr-name{flex:1;font-size:10px;color:#d4d8e8;line-height:1.3}
.gr-btn{border:none;border-radius:8px;padding:1px 7px;font-size:9px;font-weight:700;cursor:pointer;transition:all .15s;min-width:30px}
.gr-on{background:#1a3a1a;color:#50fa7b;border:1px solid #2a5a2a}
.gr-off{background:#2a2020;color:#6b7394;border:1px solid #3a3a3a}

/* Upload tone panel */
#tone-panel{display:none;position:fixed;bottom:90px;right:20px;width:290px;background:#1e2028;border:1px solid #2a2d3a;border-radius:8px;padding:14px;z-index:150;box-shadow:0 4px 20px rgba(0,0,0,.4)}
#tone-panel h4{color:#d4d8e8;font-size:12px;margin-bottom:8px}
#tone-txt{width:100%;height:80px;background:#13151a;color:#d4d8e8;border:1px solid #252836;border-radius:4px;padding:7px;font-size:11px;resize:none;font-family:inherit;outline:none}
.tone-btns{display:flex;gap:6px;margin-top:7px}
.tone-save{flex:1;background:#1a3a1a;color:#50fa7b;border:1px solid #2a5a2a;border-radius:4px;padding:5px;font-size:11px;cursor:pointer}
.tone-cancel{background:#2a2020;color:#6b7394;border:1px solid #3a3a3a;border-radius:4px;padding:5px 10px;font-size:11px;cursor:pointer}

/* Scrollbar */
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#252836;border-radius:3px}::-webkit-scrollbar-thumb:hover{background:#2a2d3a}

/* ── Model Picker ── */
#model-btn-wrap{position:relative}
#model-btn{font-size:11px!important;padding:5px 9px!important;border:1px solid #2a2d3e!important;border-radius:5px!important;white-space:nowrap;color:#a8b4ff!important;display:flex!important;align-items:center;gap:5px;line-height:1.3}
#model-label{max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#model-picker{display:none;position:absolute;right:0;top:calc(100% + 6px);width:320px;background:#1a1c24;border:1px solid #2a2d3e;border-radius:8px;z-index:400;box-shadow:0 12px 40px rgba(0,0,0,.6)}
#model-picker.open{display:block}
.mp-hdr{display:flex;justify-content:space-between;align-items:center;padding:10px 14px 9px;border-bottom:1px solid #252836}
.mp-hdr-lbl{font-size:10px;font-weight:700;color:#8892b0;letter-spacing:.07em}
.mp-close{background:none;border:none;color:#6b7394;font-size:14px;cursor:pointer;line-height:1;padding:2px}
.mp-close:hover{color:#d4d8e8}
.mp-sec{font-size:9px;font-weight:700;color:#6b7394;letter-spacing:.08em;padding:9px 14px 4px}
.mp-tabs{display:flex;flex-wrap:wrap;gap:4px;padding:0 14px 2px}
.mp-tab{background:#1e2028;border:1px solid #2a2d3e;color:#8892b0;font-size:10px;padding:4px 9px;border-radius:4px;cursor:pointer;transition:all .12s;white-space:nowrap;font-family:inherit}
.mp-tab:hover:not(:disabled){background:#252836;color:#d4d8e8;border-color:#3a3d50}
.mp-tab.mp-active{background:#1c2540;color:#64ffda;border-color:#2a4070}
.mp-tab:disabled{opacity:.32;cursor:not-allowed}
.mp-presets{display:grid;grid-template-columns:1fr 1fr;gap:5px;padding:0 14px}
.mp-preset{background:#1e2028;border:1px solid #2a2d3e;border-radius:5px;padding:7px 9px;cursor:pointer;text-align:left;transition:all .12s;font-family:inherit;width:100%}
.mp-preset:hover{background:#252836;border-color:#3a3d50}
.mp-preset.mp-active{background:#1c2540;border-color:#2a4070}
.mp-preset-name{display:block;font-size:11px;color:#d4d8e8;font-weight:600}
.mp-preset-tag{display:block;font-size:9px;color:#6b7394;margin-top:2px}
.mp-preset.mp-active .mp-preset-name{color:#64ffda}
.mp-preset.mp-active .mp-preset-tag{color:#4a9a7a}
#mp-custom{width:calc(100% - 28px);margin:4px 14px 0;background:#12141a;border:1px solid #2a2d3e;border-radius:4px;color:#d4d8e8;font-size:11.5px;padding:7px 9px;outline:none;font-family:monospace;display:block;box-sizing:border-box}
#mp-custom:focus{border-color:#64ffda}
#mp-custom::placeholder{color:#3a3f5a;font-family:inherit;font-size:11px}
.mp-ftr{display:flex;align-items:center;gap:8px;padding:10px 14px 12px}
#mp-msg{font-size:11px;flex:1;min-width:0}
.mp-apply{background:#1a3a2a;color:#50fa7b;border:1px solid #2a5a3a;border-radius:4px;font-size:11px;font-weight:700;padding:6px 15px;cursor:pointer;flex-shrink:0}
.mp-apply:hover{background:#22472f}

/* ── Credentials Modal ── */
#cred-modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:500;align-items:center;justify-content:center}
#cred-modal.open{display:flex}
#cred-box{background:#1a1c24;border:1px solid #2a2d3e;border-radius:10px;width:480px;max-width:96vw;max-height:88vh;display:flex;flex-direction:column;box-shadow:0 24px 64px rgba(0,0,0,.6)}
#cred-hdr{padding:16px 20px 14px;border-bottom:1px solid #252836;display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-shrink:0}
#cred-title{font-size:14px;font-weight:700;color:#d4d8e8}
#cred-subtitle{font-size:11px;color:#6b7394;margin-top:4px;line-height:1.5;max-width:380px}
#cred-close{background:none;border:none;color:#6b7394;font-size:18px;cursor:pointer;line-height:1;padding:2px;flex-shrink:0}
#cred-close:hover{color:#d4d8e8}
#cred-body{overflow-y:auto;padding:16px 20px 4px;flex:1}
.cf-row{margin-bottom:15px}
.cf-label{font-size:11px;color:#8892b0;margin-bottom:5px;display:flex;align-items:center;gap:7px}
.cf-badge-set{color:#50fa7b;font-size:9px;background:#0d2a1a;padding:1px 6px;border-radius:3px;font-weight:700}
.cf-badge-unset{color:#ff6e6e;font-size:9px;background:#2a1010;padding:1px 6px;border-radius:3px;font-weight:700}
.cf-input{width:100%;background:#12141a;border:1px solid #2a2d3e;border-radius:5px;color:#d4d8e8;font-size:12.5px;padding:9px 11px;outline:none;transition:border-color .15s;font-family:inherit}
.cf-input:focus{border-color:#64ffda;background:#13151e}
.cf-input::placeholder{color:#3a3f5a}
#cred-setup-row{padding:8px 20px 12px;flex-shrink:0}
#cred-setup-link{font-size:10.5px;color:#64ffda;text-decoration:none;opacity:.8}
#cred-setup-link:hover{opacity:1;text-decoration:underline}
#cred-ftr{padding:12px 20px 14px;border-top:1px solid #252836;display:flex;align-items:center;gap:8px;flex-shrink:0}
#cred-msg{font-size:11px;flex:1;min-width:0}
.cred-btn{font-size:12px;padding:8px 18px;border-radius:5px;cursor:pointer;border:none;font-weight:600;flex-shrink:0}
.cred-btn-cancel{background:#252836;color:#8892b0}
.cred-btn-cancel:hover{background:#2e3145;color:#d4d8e8}
.cred-btn-save{background:#1a3a2a;color:#50fa7b;border:1px solid #2a5a3a}
.cred-btn-save:hover{background:#22472f}
.cred-btn-save:disabled{opacity:.5;cursor:default}
/* Make badges clickable */
.cd{cursor:pointer;transition:opacity .12s,transform .1s;user-select:none}
.cd:hover{opacity:.82;transform:scale(1.04)}
.cd:active{transform:scale(.97)}
</style>
</head>
<body>

<!-- Analytics overlay -->
<div id="an-ov">
  <div id="an-box">
    <h3>📊 Work Pattern Analytics</h3>
    <div id="an-content"><em style="color:#6b7394">Loading…</em></div>
    <button id="an-close" onclick="document.getElementById('an-ov').classList.remove('show')">Close</button>
  </div>
</div>

<!-- Tone upload panel -->
<div id="tone-panel">
  <h4>✍️ Train writing style</h4>
  <div style="font-size:10px;color:#6b7394;margin-bottom:6px">Paste one of your real emails or messages:</div>
  <textarea id="tone-txt" placeholder="Hi team, just wanted to loop in…"></textarea>
  <div class="tone-btns">
    <button class="tone-save" onclick="submitTone()">Save sample</button>
    <button class="tone-cancel" onclick="document.getElementById('tone-panel').style.display='none'">✕</button>
  </div>
</div>

<!-- ── Credentials modal ── -->
<div id="cred-modal" onclick="if(event.target===this)closeCredModal()">
  <div id="cred-box">
    <div id="cred-hdr">
      <div style="flex:1;min-width:0">
        <div id="cred-title">Configure integration</div>
        <div id="cred-subtitle"></div>
      </div>
      <button id="cred-close" onclick="closeCredModal()">✕</button>
    </div>
    <div id="cred-body"></div>
    <div id="cred-setup-row">
      <a id="cred-setup-link" href="#" target="_blank" rel="noopener">
        🔗 How to get these credentials ↗
      </a>
    </div>
    <div id="cred-ftr">
      <span id="cred-msg"></span>
      <button class="cred-btn cred-btn-cancel" onclick="closeCredModal()">Cancel</button>
      <button id="cred-save-btn" class="cred-btn cred-btn-save" onclick="saveCredentials()">Save & Apply</button>
    </div>
  </div>
</div>

<!-- ── Left nav ── -->
<nav id="nav">
  <div id="nav-logo">
    <span id="nav-logo-icon">⚡</span>
    <div>
      <div id="nav-logo-text">Work Assistant</div>
      <div id="nav-logo-sub">Your AI work companion</div>
    </div>
  </div>

  <div id="nav-items"><!-- built by JS --></div>

  <!-- Guardrails -->
  <div id="gr-panel">
    <div class="gr-hdr">
      <span class="gr-hdr-lbl">🛡 GUARDRAILS</span>
      <span class="gr-badge" id="gr-badge"></span>
    </div>
    <div id="gr-list"></div>
  </div>

  <!-- Quick page links -->
  <div style="border-top:1px solid #252836;padding:5px 0;flex-shrink:0">
    <div style="font-size:9px;color:#6b7394;font-weight:700;letter-spacing:.06em;padding:5px 12px 3px">⚡ DASHBOARDS</div>
    <a href="/actions-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">✅</span> Action Items Board</a>
    <a href="/triggers-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">⚡</span> Automation Rules</a>
    <a href="/memory-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">🧠</span> Memory Viewer</a>
    <a href="/scheduler-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">🕐</span> Scheduler</a>
    <a href="/search-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">🔍</span> Global Search</a>
    <a href="/inbox-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">📧</span> Email Inbox</a>
    <a href="/calendar-page" target="_blank" style="display:flex;align-items:center;gap:8px;padding:5px 14px;color:#8892b0;font-size:11.5px;text-decoration:none;transition:background .12s,color .12s" onmouseover="this.style.background='#21232e';this.style.color='#d4d8e8'" onmouseout="this.style.background='';this.style.color='#8892b0'"><span style="font-size:13px">📅</span> Calendar</a>
  </div>

  <!-- Connections & bottom links -->
  <div id="nav-bottom">
    <div id="conn-strip"></div>
    <div id="nav-links">
      <button class="nav-link-btn" onclick="clearTool()">🗑 Clear chat</button>
      <button class="nav-link-btn" onclick="showAnalytics()">📊 Analytics</button>
    </div>
    <div id="pub-url"></div>
  </div>
</nav>

<!-- ── Main panel ── -->
<div id="main">

  <!-- Tool header -->
  <div id="tool-hdr">
    <span id="tool-hdr-icon">🏠</span>
    <div id="tool-hdr-info">
      <div id="tool-hdr-name">Home</div>
      <div id="tool-hdr-desc">Daily briefing &amp; overview</div>
    </div>
    <div id="hdr-right">
      <!-- Model switcher -->
      <div id="model-btn-wrap">
        <button class="hdr-btn" id="model-btn" title="Switch AI model" onclick="toggleModelPicker()">
          🧠 <span id="model-label">AI Model</span> <span style="font-size:8px;opacity:.5">▾</span>
        </button>
        <div id="model-picker">
          <div class="mp-hdr">
            <span class="mp-hdr-lbl">🧠 AI MODEL</span>
            <button class="mp-close" onclick="closeModelPicker()">✕</button>
          </div>
          <div class="mp-sec">PROVIDER</div>
          <div id="mp-tabs" class="mp-tabs"></div>
          <div class="mp-sec" style="margin-top:8px">MODEL</div>
          <div id="mp-presets" class="mp-presets"></div>
          <div class="mp-sec" style="margin-top:8px">CUSTOM MODEL ID</div>
          <input id="mp-custom" placeholder="e.g. claude-opus-4-6" autocomplete="off" spellcheck="false"
            oninput="_mpCustomChanged(this.value)">
          <div class="mp-ftr">
            <span id="mp-msg"></span>
            <button class="mp-apply" onclick="applyModel()">Apply</button>
          </div>
        </div>
      </div>
      <!-- KB upload -->
      <label class="hdr-btn" title="Upload PDF/DOCX to knowledge base" style="cursor:pointer">
        📎
        <input type="file" id="kb-file" accept=".pdf,.docx,.txt,.md" style="display:none" onchange="uploadKB(this)">
      </label>
      <!-- Tone train -->
      <button class="hdr-btn" title="Train writing style" onclick="document.getElementById('tone-panel').style.display=document.getElementById('tone-panel').style.display==='none'?'block':'none'">✍️</button>
      <!-- History -->
      <button class="hdr-btn" title="Conversation history" onclick="toggleHistory()">🕐</button>
      <!-- Bell -->
      <div id="bell-wrap" onclick="toggleTray()" style="position:relative">
        <button class="hdr-btn" id="bell-btn" title="Alerts">🔔</button>
        <span id="bell-dot"></span>
        <div id="alert-tray"></div>
      </div>
    </div>
  </div>

  <!-- History panel -->
  <div id="hist-panel" style="display:none;position:fixed;top:0;right:0;width:300px;height:100%;
    background:var(--bg2);border-left:1px solid var(--border);z-index:300;
    flex-direction:column;padding:12px;gap:8px;overflow:hidden;">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <span style="font-weight:600;font-size:13px;">🕐 History</span>
      <button onclick="closeHistory()" style="background:none;border:none;color:var(--fg);cursor:pointer;font-size:16px;">✕</button>
    </div>
    <input id="hist-search" placeholder="Search conversations…"
      style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;
      padding:6px 10px;color:var(--fg);font-size:12px;width:100%;box-sizing:border-box;"
      oninput="searchHistory(this.value)">
    <div id="hist-list" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:4px;"></div>
  </div>

  <!-- Chat / welcome -->
  <div id="chat">
    <div id="welcome">
      <div id="wlc-icon">🏠</div>
      <div id="wlc-title">Good to see you!</div>
      <div id="wlc-sub">Click any suggestion below or type anything in the box.</div>
      <div id="chips"></div>
    </div>
  </div>

  <!-- Input -->
  <div id="inp-area">
    <div id="inp-row">
      <button id="mic" onclick="toggleVoice()" title="Voice input">🎤</button>
      <textarea id="inp" placeholder="Ask me anything…" onkeydown="onKey(event)"></textarea>
      <button id="snd" onclick="send()">Send ↑</button>
    </div>
    <div id="inp-hint">
      <span>Enter to send</span>
      <span class="inp-hint-sep">•</span>
      <span>Shift+Enter for new line</span>
      <span class="inp-hint-sep">•</span>
      <span id="status-dot" style="color:#50fa7b">● Ready</span>
    </div>
  </div>
</div>

<script>
// ── Tool data ─────────────────────────────────────────────────────────────────
const TOOLS = __TOOLS_JSON__;

// ── Per-tool conversation history (client-side messages for display)
const _msgs = {};   // tool_id -> [{role, text, ts}]
let _curTool = 'home';
let _busy = false;

// ── Build nav ─────────────────────────────────────────────────────────────────
function buildNav() {
  const c = document.getElementById('nav-items');
  c.innerHTML = '';
  TOOLS.forEach(t => {
    const d = document.createElement('div');
    d.className = 'ni' + (t.id === _curTool ? ' active' : '');
    d.dataset.id = t.id;
    d.innerHTML = `<span class="ni-icon">${t.icon}</span>
      <span class="ni-info"><div class="ni-name">${t.name}</div><div class="ni-desc">${t.desc}</div></span>`;
    d.onclick = () => switchTool(t.id);
    c.appendChild(d);
    if (t.id === 'home') {
      const sep = document.createElement('div'); sep.className = 'nav-sep'; c.appendChild(sep);
    }
    if (t.id === 'sharepoint') {
      const sep = document.createElement('div'); sep.className = 'nav-sep'; c.appendChild(sep);
    }
    if (t.id === 'confluence') {
      const sep = document.createElement('div'); sep.className = 'nav-sep'; c.appendChild(sep);
    }
    if (t.id === 'zoom') {
      const sep = document.createElement('div'); sep.className = 'nav-sep'; c.appendChild(sep);
    }
    if (t.id === 'webhooks') {
      const sep = document.createElement('div'); sep.className = 'nav-sep'; c.appendChild(sep);
    }
  });
}

// ── Switch tool ───────────────────────────────────────────────────────────────
function switchTool(id) {
  _curTool = id;
  const t = TOOLS.find(x => x.id === id);
  if (!t) return;

  // Update nav active state
  document.querySelectorAll('.ni').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });

  // Update header
  document.getElementById('tool-hdr-icon').textContent = t.icon;
  document.getElementById('tool-hdr-name').textContent = t.name;
  document.getElementById('tool-hdr-desc').textContent = t.desc;
  document.getElementById('inp').placeholder = t.placeholder;

  // Render chat area
  renderChatArea(id, t);
}

function renderChatArea(id, t) {
  const chat = document.getElementById('chat');
  chat.innerHTML = '';
  const msgs = _msgs[id] || [];

  if (msgs.length === 0) {
    // Show welcome + chips
    const wlc = document.createElement('div');
    wlc.id = 'welcome';
    wlc.innerHTML = `
      <div id="wlc-icon">${t.icon}</div>
      <div id="wlc-title">${t.name}</div>
      <div id="wlc-sub">${t.desc} — type anything below or pick a suggestion:</div>
      <div id="chips">${t.chips.map(c =>
        `<button class="chip" onclick="useChip(this)">${c}</button>`).join('')}</div>`;
    chat.appendChild(wlc);
  } else {
    msgs.forEach(m => renderMsg(m));
    chat.scrollTop = chat.scrollHeight;
  }
}

function useChip(btn) {
  document.getElementById('inp').value = btn.textContent;
  document.getElementById('inp').focus();
}

// ── Render a message ──────────────────────────────────────────────────────────
function ts() {
  return new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function fmt(t) {
  return t
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>')
    .replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/^[•\-] (.+)$/gm,'<span class="blt">$1</span>');
}

function renderMsg({role, text}) {
  const chat = document.getElementById('chat');
  const div = document.createElement('div');
  div.className = 'msg';
  if (role === 'user') {
    div.innerHTML = `<div class="mhdr"><span class="mn-u">You</span><span class="mts">${ts()}</span></div>
      <div class="mbody mu">${fmt(text)}</div>`;
  } else if (role === 'assistant') {
    div.innerHTML = `<div class="mhdr"><span class="mn-a">Assistant</span><span class="mts">${ts()}</span></div>
      <div class="mbody ma">${fmt(text)}</div>`;
  } else if (role === 'error') {
    div.innerHTML = `<div class="mbody me">❌ ${fmt(text)}</div>`;
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function addMsg(role, text) {
  if (!_msgs[_curTool]) _msgs[_curTool] = [];
  const m = {role, text};
  _msgs[_curTool].push(m);
  // Remove welcome screen if present
  const wlc = document.getElementById('welcome');
  if (wlc) wlc.remove();
  return renderMsg(m);
}

function showThinking() {
  const chat = document.getElementById('chat');
  const wlc = document.getElementById('welcome');
  if (wlc) wlc.remove();
  const d = document.createElement('div');
  d.id = 'thinking-msg';
  d.innerHTML = '<div class="spinner"></div> <span>Thinking…</span>';
  chat.appendChild(d); chat.scrollTop = chat.scrollHeight;
}
function removeThinking() {
  const e = document.getElementById('thinking-msg'); if (e) e.remove();
}

// ── Send / poll ───────────────────────────────────────────────────────────────
async function send() {
  if (_busy) return;
  const inp = document.getElementById('inp');
  const txt = inp.value.trim(); if (!txt) return;
  inp.value = ''; inp.style.height = '58px';
  await dispatch(txt);
}

async function dispatch(txt) {
  _busy = true;
  document.getElementById('snd').disabled = true;
  setStatus('thinking');
  addMsg('user', txt);
  showThinking();
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({message: txt, tool_id: _curTool}),
    });
    const {job_id, error} = await r.json();
    if (error) throw new Error(error);
    await poll(job_id);
  } catch(e) {
    removeThinking(); addMsg('error', 'Network error: ' + e.message); setStatus('error');
  } finally {
    _busy = false; document.getElementById('snd').disabled = false;
  }
}

// poll() is defined below with progress tracking support

function setStatus(s) {
  const e = document.getElementById('status-dot');
  if (s === 'ready')    {e.textContent='● Ready';      e.style.color='#50fa7b';}
  if (s === 'thinking') {e.textContent='⏳ Thinking…'; e.style.color='#ffb86c';}
  if (s === 'error')    {e.textContent='⚠ Error';      e.style.color='#ff5555';}
}

async function clearTool() {
  await fetch('/clear', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({tool_id: _curTool})});
  delete _msgs[_curTool];
  const t = TOOLS.find(x => x.id === _curTool);
  renderChatArea(_curTool, t);
}

function onKey(e) {
  if (e.key==='Enter' && !e.shiftKey) {e.preventDefault(); send();}
  // Auto-resize
  const el = document.getElementById('inp');
  el.style.height = '58px';
  el.style.height = Math.min(el.scrollHeight, 180) + 'px';
}

// ── Connections ───────────────────────────────────────────────────────────────
async function loadConns() {
  try {
    const d = await (await fetch('/connections')).json();
    const g = document.getElementById('conn-strip'); g.innerHTML = '';
    d.forEach(c => {
      const s = document.createElement('span');
      s.className = 'cd ' + (c.ok ? 'cd-ok' : 'cd-no');
      s.textContent = (c.ok ? '● ' : '○ ') + c.name;
      s.title = c.ok ? `${c.tooltip} — click to update keys` : `${c.tooltip} — click to add credentials`;
      s.onclick = () => openCredModal(c.name);
      g.appendChild(s);
    });
    return d;
  } catch(e) {return [];}
}

// ── Credentials Modal ─────────────────────────────────────────────────────────
let _credIntegration = null;
let _credConfigCache = null;

async function openCredModal(name) {
  _credIntegration = name;
  const modal = document.getElementById('cred-modal');
  const body  = document.getElementById('cred-body');
  const msg   = document.getElementById('cred-msg');
  body.innerHTML = '<div style="color:#6b7394;font-size:12px;padding:8px 0">Loading…</div>';
  msg.textContent = '';
  modal.classList.add('open');
  try {
    if (!_credConfigCache) {
      _credConfigCache = await (await fetch('/credentials')).json();
    }
    const cfg = _credConfigCache[name];
    if (!cfg) { body.innerHTML = '<div style="color:#ff5555">Unknown integration.</div>'; return; }
    document.getElementById('cred-title').textContent    = cfg.label;
    document.getElementById('cred-subtitle').textContent = cfg.desc;
    document.getElementById('cred-setup-link').href      = cfg.setup_url;
    body.innerHTML = '';
    cfg.fields.forEach(f => {
      const row = document.createElement('div');
      row.className = 'cf-row';
      const badgeCls = f.set ? 'cf-badge-set' : 'cf-badge-unset';
      const badgeTxt = f.set ? '✔ saved'       : '✗ not set';
      const pholder  = f.set ? '••••••  (leave blank to keep current)' : f.placeholder;
      row.innerHTML = `
        <div class="cf-label">
          ${f.label}
          <span class="${badgeCls}">${badgeTxt}</span>
        </div>
        <input class="cf-input"
          type="${f.secret ? 'password' : 'text'}"
          data-key="${f.key}"
          placeholder="${pholder}"
          autocomplete="off"
          spellcheck="false">`;
      body.appendChild(row);
    });
    // focus first empty field
    const first = body.querySelector('.cf-input:not([placeholder^="••"])');
    if (first) first.focus();
  } catch(e) {
    body.innerHTML = `<div style="color:#ff5555">Error loading config: ${e.message}</div>`;
  }
}

function closeCredModal() {
  document.getElementById('cred-modal').classList.remove('open');
  _credIntegration = null;
}

async function saveCredentials() {
  const inputs = document.querySelectorAll('#cred-body .cf-input');
  const values = {};
  inputs.forEach(inp => { if (inp.value.trim()) values[inp.dataset.key] = inp.value.trim(); });
  const msg     = document.getElementById('cred-msg');
  const saveBtn = document.getElementById('cred-save-btn');
  if (!Object.keys(values).length) {
    msg.textContent = 'Nothing to save — all fields are blank.';
    msg.style.color = '#ffb86c';
    return;
  }
  saveBtn.disabled = true;
  msg.textContent  = 'Saving…';
  msg.style.color  = '#ffb86c';
  try {
    const r = await fetch('/credentials', {
      method:  'POST',
      headers: {'Content-Type': 'application/json'},
      body:    JSON.stringify({integration: _credIntegration, values}),
    });
    const d = await r.json();
    if (d.error) {
      msg.textContent = '❌ ' + d.error;
      msg.style.color = '#ff5555';
      saveBtn.disabled = false;
      return;
    }
    msg.textContent = `✅ Saved ${d.saved.length} key(s) to .env`;
    msg.style.color = '#50fa7b';
    _credConfigCache = null;  // invalidate cache so badge re-reads fresh state
    setTimeout(async () => { closeCredModal(); await loadConns(); }, 1400);
  } catch(e) {
    msg.textContent  = '❌ Network error: ' + e.message;
    msg.style.color  = '#ff5555';
    saveBtn.disabled = false;
  }
}

// ── Guardrails ────────────────────────────────────────────────────────────────
async function loadGuardrails() {
  try {
    const d = await (await fetch('/guardrails')).json();
    const list = document.getElementById('gr-list'); list.innerHTML = '';
    let on = 0;
    d.forEach(g => {
      if (g.enabled) on++;
      const row = document.createElement('div'); row.className='gr-row'; row.title=g.description;
      row.innerHTML = `<span class="gr-icon">${g.icon}</span><span class="gr-name">${g.label}</span>
        <button class="gr-btn ${g.enabled?'gr-on':'gr-off'}" onclick="toggleGR('${g.name}')">${g.enabled?'ON':'OFF'}</button>`;
      list.appendChild(row);
    });
    document.getElementById('gr-badge').textContent = on+'/'+d.length;
  } catch(e) {}
}
async function toggleGR(name) {
  await fetch('/guardrails/'+name, {method:'POST'}); loadGuardrails();
}

// ── Voice ─────────────────────────────────────────────────────────────────────
let _recog=null,_listening=false;
function toggleVoice() {
  if (!('SpeechRecognition' in window||'webkitSpeechRecognition' in window)) {
    addMsg('error','Voice input not supported in this browser.'); return;
  }
  if (_listening) {_recog&&_recog.stop(); return;}
  const SR = window.SpeechRecognition||window.webkitSpeechRecognition;
  _recog = new SR(); _recog.continuous=false; _recog.interimResults=false;
  _recog.onstart = () => {_listening=true; document.getElementById('mic').classList.add('listening');}
  _recog.onend   = () => {_listening=false; document.getElementById('mic').classList.remove('listening');}
  _recog.onresult = e => { document.getElementById('inp').value=e.results[0][0].transcript; send(); }
  _recog.onerror  = () => {_listening=false; document.getElementById('mic').classList.remove('listening');}
  _recog.start();
}

// ── SSE proactive alerts (startSSEWithNotifs defined below) ──────────────────
const _alerts = [];
function renderTray() {
  const t = document.getElementById('alert-tray');
  if (!_alerts.length) {t.innerHTML='<div style="padding:8px 10px;color:#6b7394;font-size:11px">No alerts</div>';return;}
  t.innerHTML = _alerts.slice(0,8).map(a =>
    `<div class="al-row" onclick="dispatch('${(a.message||'').replace(/'/g,"\\'")}')"><b>${a.type||'Alert'}</b><br>${a.message||''}</div>`).join('');
}
function toggleTray() {
  const t = document.getElementById('alert-tray');
  if (t.style.display==='block') {t.style.display='none';}
  else {renderTray(); t.style.display='block'; document.getElementById('bell-dot').style.display='none';}
}
document.addEventListener('click', e => {
  const w = document.getElementById('bell-wrap');
  if (w && !w.contains(e.target)) document.getElementById('alert-tray').style.display='none';
});

// ── Analytics ─────────────────────────────────────────────────────────────────
async function showAnalytics() {
  document.getElementById('an-ov').classList.add('show');
  const el = document.getElementById('an-content');
  el.innerHTML = '<em style="color:#6b7394">Loading…</em>';
  try {
    const d = await (await fetch('/analytics')).json();
    if (d.total_turns===0) {el.innerHTML='<p style="color:#6b7394;font-size:12px">No data yet.</p>';return;}
    let h = `<div class="ar"><span class="al-lbl">Total turns (${d.days_back||7}d)</span><span class="al-val">${d.total_turns}</span></div>`;
    h += `<div class="ar"><span class="al-lbl">Tool calls</span><span class="al-val">${d.total_tool_calls}</span></div>`;
    h += `<div class="ar"><span class="al-lbl">Avg response</span><span class="al-val">${Math.round((d.avg_response_ms||0)/1000)}s</span></div>`;
    h += `<div class="ar"><span class="al-lbl">Peak hour</span><span class="al-val">${d.peak_hour!=null?d.peak_hour+':00':'—'}</span></div>`;
    h += `<div class="ar"><span class="al-lbl">Busiest day</span><span class="al-val">${d.busiest_day||'—'}</span></div>`;
    if (d.top_tools&&d.top_tools.length) {
      h += '<div style="margin-top:12px;margin-bottom:6px;font-size:10px;color:#8892b0;font-weight:700;letter-spacing:.05em">TOP TOOLS</div>';
      const max = d.top_tools[0].count||1;
      d.top_tools.forEach(t => {
        const pct = Math.round(t.count/max*100);
        h += `<div style="display:flex;align-items:center;padding:4px 0;font-size:11px">
          <span style="flex:1;color:#d4d8e8">${t.tool}</span>
          <div class="bw"><div class="bf" style="width:${pct}%"></div></div>
          <span style="color:#64ffda;min-width:22px;text-align:right">${t.count}</span></div>`;
      });
    }
    if (d.insights&&d.insights.length) {
      h += '<div style="margin-top:12px;margin-bottom:6px;font-size:10px;color:#8892b0;font-weight:700;letter-spacing:.05em">INSIGHTS</div>';
      d.insights.forEach(ins => {
        h += `<div style="font-size:11px;padding:3px 0;color:#d4d8e8">${ins.replace(/\*\*(.+?)\*\*/g,'<b>$1</b>')}</div>`;
      });
    }
    el.innerHTML = h;
  } catch(e) {el.innerHTML='<em style="color:#ff5555">Failed.</em>';}
}

// ── KB upload ─────────────────────────────────────────────────────────────────
async function uploadKB(input) {
  const file = input.files[0]; if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  showThinking();
  try {
    const r = await fetch('/upload-doc', {method:'POST', body:fd});
    const d = await r.json(); removeThinking();
    if (d.error) addMsg('error','Upload failed: '+d.error);
    else addMsg('assistant', `✅ **${file.name}** added to knowledge base. You can now ask questions about it.`);
  } catch(e) {removeThinking(); addMsg('error','Upload error: '+e.message);}
  input.value='';
}

// ── Tone train ────────────────────────────────────────────────────────────────
async function submitTone() {
  const txt = document.getElementById('tone-txt').value.trim(); if (!txt) return;
  try {
    const r = await fetch('/upload-tone', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:txt})});
    const d = await r.json();
    document.getElementById('tone-txt').value='';
    document.getElementById('tone-panel').style.display='none';
    addMsg('assistant', `✅ Writing style sample saved! You now have **${d.sample_count||'?'} samples**. The agent will match your tone when drafting emails.`);
  } catch(e) {addMsg('error','Error: '+e.message);}
}

// ── Public URL ────────────────────────────────────────────────────────────────
async function pollPublicUrl() {
  for (let i=0;i<30;i++) {
    await new Promise(r=>setTimeout(r,2000));
    try {
      const d = await (await fetch('/public-url')).json();
      if (d.url) {
        document.getElementById('pub-url').innerHTML =
          `🌐 <a href="${d.url}" target="_blank" style="color:#64ffda;text-decoration:none">${d.url}</a>`;
        return;
      }
    } catch(e){}
  }
}

// ── Model Picker ──────────────────────────────────────────────────────────────
let _mpData     = null;   // full /model response
let _mpProvider = null;   // currently selected provider in picker
let _mpModel    = null;   // currently selected model id in picker

const _PROV_ICONS  = {gemini:'✦', claude:'◆', openai:'⬡', openrouter:'⊕', minimax:'⊞'};
const _PROV_LABELS = {gemini:'Gemini', claude:'Claude', openai:'OpenAI', openrouter:'Router', minimax:'MiniMax'};

async function initModelBtn() {
  try {
    _mpData     = await (await fetch('/model')).json();
    _mpProvider = _mpData.active_provider || (_mpData.providers.find(p => p.available) || {}).name || 'claude';
    _mpModel    = _mpData.active_model || '';
    _mpUpdateBtnLabel();
  } catch(e) { document.getElementById('model-label').textContent = 'AI Model'; }
}

function _mpUpdateBtnLabel() {
  if (!_mpData) return;
  const prov    = _mpData.active_provider  || _mpProvider || '?';
  const modelId = _mpData.active_model     || _mpModel    || '';
  const presets = (_mpData.presets[prov]   || []);
  const preset  = presets.find(p => p.id === modelId);
  const mLabel  = preset ? preset.label : (modelId.split('/').pop() || _PROV_LABELS[prov] || prov);
  const pLabel  = _PROV_LABELS[prov] || prov;
  document.getElementById('model-label').textContent = `${pLabel} · ${mLabel}`;
}

function toggleModelPicker() {
  const picker = document.getElementById('model-picker');
  const isOpen = picker.classList.contains('open');
  if (isOpen) { closeModelPicker(); return; }
  picker.classList.add('open');
  if (!_mpData) { initModelBtn().then(() => _mpRender()); }
  else { _mpRender(); }
}

function closeModelPicker() {
  document.getElementById('model-picker').classList.remove('open');
}

// Close if click outside
document.addEventListener('click', e => {
  const wrap = document.getElementById('model-btn-wrap');
  if (wrap && !wrap.contains(e.target)) closeModelPicker();
});

function _mpRender() {
  if (!_mpData) return;
  const { providers, presets } = _mpData;
  // Provider tabs
  let tabsHtml = '';
  providers.forEach(p => {
    const isActive = p.name === _mpProvider;
    tabsHtml += `<button class="mp-tab${isActive ? ' mp-active' : ''}"
      onclick="mpSelectProvider('${p.name}')"
      ${!p.available ? 'disabled title="Not configured — add API key"' : `title="${p.name}"`}>
      ${_PROV_ICONS[p.name]||'·'} ${_PROV_LABELS[p.name]||p.name}
    </button>`;
  });
  // Preset chips
  const provPresets = presets[_mpProvider] || [];
  let presetsHtml = '';
  provPresets.forEach(pr => {
    const isCur = pr.id === _mpModel;
    presetsHtml += `<button class="mp-preset${isCur ? ' mp-active' : ''}"
      onclick="mpSelectPreset('${pr.id.replace(/'/g,"\\'")}')">
      <span class="mp-preset-name">${pr.label}</span>
      <span class="mp-preset-tag">${pr.tag}</span>
    </button>`;
  });
  document.getElementById('mp-tabs').innerHTML    = tabsHtml;
  document.getElementById('mp-presets').innerHTML = presetsHtml;
  document.getElementById('mp-custom').value      = _mpModel || '';
  document.getElementById('mp-msg').textContent   = '';
}

function mpSelectProvider(name) {
  _mpProvider = name;
  const first = (_mpData.presets[name] || [])[0];
  _mpModel = first ? first.id : '';
  _mpRender();
}

function mpSelectPreset(id) {
  _mpModel = id;
  document.getElementById('mp-custom').value = id;
  _mpRender();
}

function _mpCustomChanged(val) {
  _mpModel = val.trim();
  // clear active highlight on presets when user types custom
  document.querySelectorAll('.mp-preset').forEach(b => b.classList.remove('mp-active'));
}

async function applyModel() {
  const customVal = document.getElementById('mp-custom').value.trim();
  const model     = customVal || _mpModel || '';
  const provider  = _mpProvider;
  const msg       = document.getElementById('mp-msg');
  if (!provider) { msg.textContent = 'Select a provider first.'; msg.style.color='#ffb86c'; return; }
  msg.textContent = 'Saving…'; msg.style.color = '#ffb86c';
  try {
    const r = await fetch('/model', {
      method:  'POST',
      headers: {'Content-Type':'application/json'},
      body:    JSON.stringify({provider, model}),
    });
    const d = await r.json();
    if (!d.ok) { msg.textContent = '❌ ' + (d.error||'Error'); msg.style.color='#ff5555'; return; }
    _mpData.active_provider = provider;
    _mpData.active_model    = model;
    _mpUpdateBtnLabel();
    msg.textContent = '✅ Applied!'; msg.style.color = '#50fa7b';
    setTimeout(() => closeModelPicker(), 1100);
  } catch(e) { msg.textContent = '❌ ' + e.message; msg.style.color = '#ff5555'; }
}

// ── History sidebar ───────────────────────────────────────────────────────────
let _histOpen = false;

function toggleHistory() {
  _histOpen = !_histOpen;
  const p = document.getElementById('hist-panel');
  p.style.display = _histOpen ? 'flex' : 'none';
  if (_histOpen) loadHistory();
}

function closeHistory() {
  _histOpen = false;
  document.getElementById('hist-panel').style.display = 'none';
}

function _escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function restoreSession(id, title) {
  const turns = await fetch(`/history/${id}`).then(r => r.json()).catch(() => []);
  const chat = document.getElementById('chat');
  const wlc = document.getElementById('welcome');
  if (wlc) wlc.remove();
  const banner = document.createElement('div');
  banner.style.cssText = 'text-align:center;opacity:.4;font-size:11px;padding:8px';
  banner.textContent = '📂 Restored: ' + title;
  chat.appendChild(banner);
  turns.forEach(t => addMsg(t.role === 'user' ? 'user' : 'assistant', t.content));
  closeHistory();
}

// loadHistory, searchHistory, exportConversation defined below

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  const tag = document.activeElement?.tagName;
  const typing = tag === 'TEXTAREA' || tag === 'INPUT';

  // Cmd+Enter / Ctrl+Enter — send message (even while focused in textarea)
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault(); send(); return;
  }
  // Esc — close all overlays/panels
  if (e.key === 'Escape') {
    closeHistory();
    closeModelPicker();
    document.getElementById('tone-panel').style.display='none';
    document.getElementById('draft-modal')?.classList.remove('open');
    document.getElementById('alert-tray').style.display='none';
    return;
  }
  // Cmd+K / Ctrl+K — open tool picker / focus search
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    // Toggle tool picker: open nav search or focus text input
    const inp = document.getElementById('inp');
    if (inp) { inp.focus(); inp.select(); }
    return;
  }
  // Cmd+/ — open model picker
  if ((e.metaKey || e.ctrlKey) && e.key === '/') {
    e.preventDefault();
    toggleModelPicker();
    return;
  }
});

// ── Browser push notifications ────────────────────────────────────────────────
let _notifPermission = 'default';
async function requestNotifPermission() {
  if (!('Notification' in window)) return;
  try {
    _notifPermission = await Notification.requestPermission();
  } catch(e) {}
}
function sendBrowserNotif(title, body) {
  if (_notifPermission !== 'granted') return;
  try {
    const n = new Notification(title, {body, icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><text y="28" font-size="28">⚡</text></svg>'});
    n.onclick = () => { window.focus(); n.close(); };
    setTimeout(() => n.close(), 8000);
  } catch(e) {}
}

// Wire push notifs to the SSE alert stream
function startSSEWithNotifs() {
  try {
    const es = new EventSource('/stream');
    es.onmessage = e => {
      try {
        const a = JSON.parse(e.data); _alerts.unshift(a);
        document.getElementById('bell-dot').style.display='block';
        // Fire browser push notification for urgent alerts
        if (a.type === 'urgent' || a.priority === 'urgent') {
          sendBrowserNotif('⚡ Work Assistant Alert', a.message || 'Urgent item needs attention');
        }
      } catch(err){}
    };
  } catch(e){}
}

// ── Draft approval modal ──────────────────────────────────────────────────────
function _injectDraftModal() {
  if (document.getElementById('draft-modal')) return;
  const el = document.createElement('div');
  el.className = 'modal-overlay'; el.id = 'draft-modal';
  el.onclick = e => { if(e.target===el) closeDraftModal(); };
  el.innerHTML = `
    <div style="background:#1a1c24;border:1px solid #2a2d3e;border-radius:10px;width:520px;max-width:96vw;padding:22px 24px;box-shadow:0 24px 64px rgba(0,0,0,.6);max-height:90vh;overflow-y:auto">
      <div style="font-size:14px;font-weight:700;color:#d4d8e8;margin-bottom:4px">✍️ Draft Reply</div>
      <div id="draft-orig-preview" style="font-size:10px;color:#6b7394;margin-bottom:14px;max-height:80px;overflow:hidden;text-overflow:ellipsis"></div>
      <label style="font-size:11px;color:#8892b0;display:block;margin-bottom:5px">Edit before sending:</label>
      <textarea id="draft-edit" rows="8" style="width:100%;background:#12141a;border:1px solid #2a2d3e;border-radius:5px;color:#d4d8e8;font-size:12.5px;padding:10px;outline:none;resize:vertical;font-family:inherit;line-height:1.6"></textarea>
      <div style="display:flex;gap:8px;margin-top:14px;justify-content:flex-end">
        <button onclick="closeDraftModal()" style="background:#252836;color:#8892b0;border:none;border-radius:5px;padding:8px 16px;cursor:pointer;font-size:12px">Cancel</button>
        <button onclick="copyDraft()" style="background:#1c2540;color:#64ffda;border:1px solid #2a4070;border-radius:5px;padding:8px 16px;cursor:pointer;font-size:12px;font-weight:600">📋 Copy</button>
        <button onclick="sendDraft()" id="draft-send-btn" style="background:#e94560;color:#fff;border:none;border-radius:5px;padding:8px 18px;cursor:pointer;font-size:12px;font-weight:700">Send ↑</button>
      </div>
      <div id="draft-msg" style="font-size:11px;color:#50fa7b;margin-top:8px;text-align:right"></div>
    </div>`;
  document.body.appendChild(el);
}

let _draftEmailCtx = null;

async function openDraftModal(emailBody, instruction) {
  _injectDraftModal();
  const modal = document.getElementById('draft-modal');
  const edit = document.getElementById('draft-edit');
  const orig = document.getElementById('draft-orig-preview');
  const msg = document.getElementById('draft-msg');
  orig.textContent = emailBody ? ('Re: ' + emailBody.slice(0, 200)) : '';
  edit.value = 'Generating draft…';
  msg.textContent = '';
  modal.classList.add('open');
  _draftEmailCtx = {emailBody, instruction};
  try {
    const r = await fetch('/draft-reply', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email_body: emailBody, instruction: instruction||''})
    });
    const d = await r.json();
    edit.value = d.draft || d.error || '(empty)';
  } catch(e) {
    edit.value = 'Error generating draft: ' + e.message;
  }
}

function closeDraftModal() {
  document.getElementById('draft-modal')?.classList.remove('open');
  _draftEmailCtx = null;
}

function copyDraft() {
  const txt = document.getElementById('draft-edit')?.value || '';
  navigator.clipboard.writeText(txt).then(() => {
    document.getElementById('draft-msg').textContent = '✅ Copied to clipboard!';
  });
}

async function sendDraft() {
  const draft = document.getElementById('draft-edit')?.value?.trim();
  if (!draft) return;
  const btn = document.getElementById('draft-send-btn');
  const msg = document.getElementById('draft-msg');
  btn.disabled = true; btn.textContent = 'Sending…';
  try {
    const r = await fetch('/send-draft', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({draft, email_context: _draftEmailCtx?.emailBody || ''})
    });
    const d = await r.json();
    if (d.ok) {
      msg.textContent = '✅ Sent!'; msg.style.color='#50fa7b';
      setTimeout(() => closeDraftModal(), 1500);
    } else {
      msg.textContent = '❌ ' + (d.error || 'Failed'); msg.style.color='#ff5555';
      btn.disabled = false; btn.textContent = 'Send ↑';
    }
  } catch(e) {
    msg.textContent = '❌ ' + e.message; msg.style.color='#ff5555';
    btn.disabled = false; btn.textContent = 'Send ↑';
  }
}

// Expose globally so agent responses can trigger it via onclick
window.openDraftModal = openDraftModal;

// ── Conversation export ───────────────────────────────────────────────────────
async function exportConversation(sessionId, title) {
  try {
    const r = await fetch(`/export/${sessionId}`);
    const text = await r.text();
    const blob = new Blob([text], {type:'text/markdown'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = (title||'conversation').replace(/[^a-z0-9]/gi,'_').toLowerCase() + '.md';
    a.click();
    URL.revokeObjectURL(url);
  } catch(e) {addMsg('error','Export failed: '+e.message);}
}

// Update history panel to show export button
const _origLoadHistory = loadHistory;
async function loadHistory(q) {
  const tool  = _curTool || '';
  const url   = q
    ? `/history?q=${encodeURIComponent(q)}`
    : `/history?tool_id=${encodeURIComponent(tool)}`;
  const sessions = await fetch(url).then(r => r.json()).catch(() => []);
  const list = document.getElementById('hist-list');
  list.innerHTML = '';
  if (!sessions.length) {
    list.innerHTML = '<div style="opacity:.5;font-size:12px;text-align:center;padding:20px">No history yet</div>';
    return;
  }
  sessions.forEach(s => {
    const d = document.createElement('div');
    d.style.cssText = 'background:#1e2028;border-radius:6px;padding:8px 10px;cursor:pointer;font-size:12px;border:1px solid transparent;position:relative;';
    const dateStr = (s.updated_at || '').slice(0, 10);
    d.innerHTML = `<div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:50px">${_escHtml(s.title)}</div>
      <div style="opacity:.5;font-size:10px;margin-top:2px">${_escHtml(s.tool_id)} · ${s.turn_count} turns · ${dateStr}</div>
      <button onclick="event.stopPropagation();exportConversation('${s.id}','${s.title.replace(/'/g,"\\'")}')"
        style="position:absolute;top:8px;right:8px;background:#1c2540;border:1px solid #2a4070;color:#64ffda;border-radius:3px;padding:2px 7px;font-size:10px;cursor:pointer;font-weight:600">📥</button>`;
    d.onmouseover = () => d.style.borderColor = '#2a4070';
    d.onmouseout  = () => d.style.borderColor = 'transparent';
    d.onclick = () => restoreSession(s.id, s.title);
    list.appendChild(d);
  });
}

function searchHistory(q) {
  clearTimeout(searchHistory._t);
  searchHistory._t = setTimeout(() => loadHistory(q || undefined), 300);
}

// ── Tool call progress display ────────────────────────────────────────────────
async function poll(job_id) {
  let lastProgressLen = 0;
  for (;;) {
    await new Promise(r => setTimeout(r, 600));
    const j = await (await fetch('/poll/' + job_id)).json();
    // Update thinking message with progress
    const progress = j.progress || [];
    if (progress.length > lastProgressLen) {
      const latest = progress[progress.length - 1];
      const el = document.getElementById('thinking-msg');
      if (el && latest.tools) {
        el.innerHTML = `<div class="spinner"></div> <span>Calling: <b>${latest.tools.join(', ')}</b> (step ${latest.iteration||'?'})</span>`;
      }
      lastProgressLen = progress.length;
    }
    if (j.status === 'done') {
      removeThinking();
      addMsg('assistant', j.response);
      if (j.warnings && j.warnings.length) {
        const chat = document.getElementById('chat');
        j.warnings.forEach(w => {
          const d = document.createElement('div'); d.className='mwarn'; d.textContent=w; chat.appendChild(d);
        });
        chat.scrollTop = chat.scrollHeight;
      }
      setStatus('ready'); return;
    }
    if (j.status === 'error') {removeThinking(); addMsg('error', j.response); setStatus('error'); return;}
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  buildNav();
  switchTool('home');
  loadGuardrails();
  startSSEWithNotifs();
  requestNotifPermission();
  pollPublicUrl();
  initModelBtn();
  const conns = await loadConns();
  const ok    = conns.filter(c=>c.ok).map(c=>c.name).join(', ')||'none';
  const miss  = conns.filter(c=>!c.ok).map(c=>c.name);
  let msg = `👋 Hi Sai! I'm your Work Assistant.\n\n**Connected:** ${ok}`;
  if (miss.length) msg += `\n\n⚠️ **Not configured:** ${miss.join(', ')} — add keys to .env`;
  msg += `\n\nSelect a tool from the left sidebar, or just type anything below.\n\n💡 **Shortcuts:** ⌘+Enter send · ⌘+K focus input · ⌘+/ model picker · Esc close panels`;
  addMsg('assistant', msg);
}
init();
</script>
</body>
</html>"""

HTML = HTML_TEMPLATE.replace("__TOOLS_JSON__", TOOLS_NAV_JSON)


# ══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return HTML


@app.route("/connections")
def connections():
    return jsonify(_check_connections())


@app.route("/health")
def health():
    """Lightweight health-check used by the restart poller."""
    return jsonify({"ok": True})


@app.route("/restart", methods=["POST"])
def restart_server():
    """Restart the Flask process in-place using os.execv.
    Passes --no-browser so the restarted process doesn't open a new tab.
    """
    def _do_restart():
        import time
        time.sleep(0.4)   # let the HTTP response fly first
        # Build argv: keep original script path, add --no-browser if not already there
        argv = list(sys.argv)
        if "--no-browser" not in argv:
            argv.append("--no-browser")
        os.execv(sys.executable, [sys.executable] + argv)
    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting…"})


@app.route("/connections-page")
def connections_page():
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connections — Work Assistant</title>
{_PAGE_STYLE}
<style>
.conn-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;margin-top:20px}}
.conn-card{{background:#1e2028;border:1px solid #252836;border-radius:8px;padding:16px 18px;transition:border-color .15s}}
.conn-card:hover{{border-color:#2a3a50}}
.conn-card-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}}
.conn-name{{font-size:13px;font-weight:700;color:#d4d8e8}}
.conn-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px}}
.conn-badge-ok{{background:#0d2a1a;color:#50fa7b}}
.conn-badge-no{{background:#2a1010;color:#ff6e6e}}
.conn-desc{{font-size:11px;color:#6b7394;margin-bottom:12px;line-height:1.5}}
.conn-fields{{margin-bottom:12px}}
.conn-field{{display:flex;align-items:center;gap:6px;font-size:11px;color:#8892b0;margin-bottom:4px}}
.conn-field-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.conn-field-dot-ok{{background:#50fa7b}}
.conn-field-dot-no{{background:#ff6e6e}}
.conn-actions{{display:flex;gap:7px;flex-wrap:wrap}}
.ms365-box{{background:#12141a;border:1px solid #252836;border-radius:6px;padding:12px;margin-top:10px;font-size:11px;display:none}}
.ms365-code{{font-size:20px;font-weight:700;color:#64ffda;letter-spacing:4px;text-align:center;padding:8px 0}}
</style>
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">🔌 Connections</div>
      <div class="page-subtitle">Connect and manage all your tool integrations from one place</div>
    </div>
    <button class="btn btn-danger" onclick="restartApp()">↺ Restart App</button>
  </div>

  <div id="status-banner" style="display:none;padding:8px 14px;border-radius:6px;font-size:12px;margin-bottom:16px"></div>

  <div class="conn-grid" id="conn-grid">
    <div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Loading connections…</div></div>
  </div>
</div>

<!-- Credentials modal -->
<div class="modal-overlay" id="creds-modal">
  <div class="modal-box" style="width:480px">
    <div class="modal-title" id="modal-title">Configure Integration</div>
    <div id="modal-desc" style="font-size:11px;color:#6b7394;margin-bottom:12px"></div>
    <div id="modal-fields"></div>
    <div id="modal-setup" style="font-size:11px;color:#6b7394;margin-top:6px"></div>
    <div class="modal-ftr">
      <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modal-save-btn" onclick="saveCredentials()">Save</button>
    </div>
  </div>
</div>

<script>
let _credsConfig = {{}};
let _currentIntegration = null;

async function load() {{
  const [statusArr, creds] = await Promise.all([
    fetch('/connections').then(r=>r.json()),
    fetch('/credentials').then(r=>r.json()),
  ]);
  _credsConfig = creds;
  renderGrid(statusArr, creds);
}}

function renderGrid(statusArr, creds) {{
  const statusMap = {{}};
  statusArr.forEach(s => statusMap[s.name] = s.ok);

  const order = ['M365','AI','Atlassian','GitHub','Slack','Linear','Notion','Zoom','G-Meet'];
  const html = order.map(key => {{
    const cfg = creds[key];
    if (!cfg) return '';
    const connected = statusMap[cfg.label] ?? cfg.fields.some(f=>f.set);
    const badge = connected
      ? '<span class="conn-badge conn-badge-ok">✅ Connected</span>'
      : '<span class="conn-badge conn-badge-no">✗ Not configured</span>';

    const fieldDots = cfg.fields.map(f =>
      `<div class="conn-field">
        <div class="conn-field-dot ${{f.set ? 'conn-field-dot-ok' : 'conn-field-dot-no'}}"></div>
        <span>${{f.label}}</span>${{f.set ? '' : ' <span style="color:#ff6e6e;font-size:10px">(missing)</span>'}}
      </div>`
    ).join('');

    const ms365Extra = key === 'M365' ? `
      <div id="ms365-box" class="ms365-box">
        <div style="color:#8892b0;margin-bottom:8px;font-size:11px">Visit the URL below and enter the code to sign in:</div>
        <a id="ms365-link" href="#" target="_blank" style="font-size:11px;color:#64ffda;display:block;margin-bottom:4px"></a>
        <div class="ms365-code" id="ms365-user-code">—</div>
        <div id="ms365-spinner" style="text-align:center;font-size:18px;margin-top:6px">⏳</div>
      </div>` : '';

    const disconnectBtn = key === 'M365' && connected
      ? `<button class="btn btn-sm btn-danger" onclick="disconnectMs365()">Disconnect</button>` : '';
    const connectLabel = key === 'M365' ? (connected ? 'Re-connect' : '🔗 Connect') : null;
    const connectBtn = connectLabel
      ? `<button class="btn btn-sm btn-success" id="ms365-connect-btn" onclick="startMs365Auth()">${{connectLabel}}</button>`
      : '';
    const configBtn = `<button class="btn btn-sm" style="background:#252836;color:#8892b0;border:1px solid #2a3050" onclick="openModal('${{key}}')">⚙ Configure</button>`;
    const setupBtn = `<a href="${{cfg.setup_url}}" target="_blank" class="btn btn-sm" style="background:#12141a;color:#64ffda;border:1px solid #1e3050;font-size:10px">↗ Setup docs</a>`;

    return `<div class="conn-card" id="card-${{key}}">
      <div class="conn-card-hdr"><span class="conn-name">${{cfg.label}}</span>${{badge}}</div>
      <div class="conn-desc">${{cfg.desc}}</div>
      <div class="conn-fields">${{fieldDots}}</div>
      ${{ms365Extra}}
      <div class="conn-actions">${{configBtn}}${{connectBtn}}${{disconnectBtn}}${{setupBtn}}</div>
    </div>`;
  }}).join('');

  document.getElementById('conn-grid').innerHTML = html ||
    '<div class="empty-state"><div class="empty-state-txt">No integrations found.</div></div>';
}}

function openModal(key) {{
  const cfg = _credsConfig[key];
  if (!cfg) return;
  _currentIntegration = key;
  document.getElementById('modal-title').textContent = 'Configure ' + cfg.label;
  document.getElementById('modal-desc').textContent = cfg.desc;
  document.getElementById('modal-setup').innerHTML =
    `<a href="${{cfg.setup_url}}" target="_blank" style="color:#64ffda">↗ Setup guide</a>`;
  document.getElementById('modal-fields').innerHTML = cfg.fields.map(f => `
    <div class="form-group">
      <label class="form-label">${{f.label}}
        ${{f.set
          ? '<span style="color:#50fa7b;font-size:9px;margin-left:4px">● set</span>'
          : '<span style="color:#ff6e6e;font-size:9px;margin-left:4px">● missing</span>'}}
      </label>
      <input class="form-input" type="${{f.secret ? 'password' : 'text'}}" id="field-${{f.key}}"
        placeholder="${{f.set ? '(leave blank to keep current)' : f.placeholder}}" data-key="${{f.key}}">
    </div>`).join('');
  document.getElementById('creds-modal').classList.add('open');
}}

function closeModal() {{
  document.getElementById('creds-modal').classList.remove('open');
  _currentIntegration = null;
}}

async function saveCredentials() {{
  if (!_currentIntegration) return;
  const cfg = _credsConfig[_currentIntegration];
  const values = {{}};
  cfg.fields.forEach(f => {{
    const el = document.getElementById('field-' + f.key);
    if (el && el.value.trim()) values[f.key] = el.value.trim();
  }});
  if (!Object.keys(values).length) {{ closeModal(); return; }}
  const btn = document.getElementById('modal-save-btn');
  btn.textContent = 'Saving…'; btn.disabled = true;
  try {{
    const r = await fetch('/credentials', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{integration: _currentIntegration, values}})
    }}).then(r => r.json());
    showBanner(r.error ? r.error : 'Saved: ' + r.saved.join(', '), r.error ? 'error' : 'ok');
    closeModal();
    await load();
  }} finally {{ btn.textContent = 'Save'; btn.disabled = false; }}
}}

// ── MS365 device flow ──────────────────────────────────────────────────────
let _ms365Poll = null;

async function startMs365Auth() {{
  const btn = document.getElementById('ms365-connect-btn');
  btn.disabled = true; btn.textContent = 'Starting…';
  const box = document.getElementById('ms365-box');
  box.style.display = 'block';
  try {{
    const r = await fetch('/ms365/auth/start', {{method: 'POST'}}).then(r => r.json());
    if (r.error) {{ showBanner(r.error, 'error'); box.style.display = 'none'; btn.disabled = false; btn.textContent = '🔗 Connect'; return; }}
    document.getElementById('ms365-user-code').textContent = r.user_code || '—';
    const lnk = document.getElementById('ms365-link');
    lnk.href = r.verification_uri || '#';
    lnk.textContent = r.verification_uri || '';
    document.getElementById('ms365-spinner').textContent = '⏳';
    _ms365Poll = setInterval(pollMs365, 3000);
  }} catch(e) {{ showBanner('Failed to start auth: ' + e.message, 'error'); btn.disabled = false; btn.textContent = '🔗 Connect'; }}
}}

async function pollMs365() {{
  const r = await fetch('/ms365/auth/poll').then(r => r.json());
  if (r.status === 'connected') {{
    clearInterval(_ms365Poll);
    document.getElementById('ms365-spinner').textContent = '✅';
    showBanner('Microsoft 365 connected!', 'ok');
    setTimeout(() => load(), 800);
  }} else if (r.status === 'failed') {{
    clearInterval(_ms365Poll);
    document.getElementById('ms365-spinner').textContent = '✗';
    showBanner(r.error || 'Sign-in failed.', 'error');
    const btn = document.getElementById('ms365-connect-btn');
    if (btn) {{ btn.disabled = false; btn.textContent = '🔗 Connect'; }}
  }}
}}

async function disconnectMs365() {{
  await fetch('/ms365/auth/disconnect', {{method: 'POST'}});
  showBanner('Microsoft 365 disconnected.', 'ok');
  load();
}}

// ── Helpers ────────────────────────────────────────────────────────────────
function _fetchWithTimeout(url, ms) {{
  // Cross-browser compatible fetch with timeout (replaces AbortSignal.timeout)
  return new Promise((resolve, reject) => {{
    const ctrl = new AbortController();
    const timer = setTimeout(() => {{ ctrl.abort(); reject(new Error('timeout')); }}, ms);
    fetch(url, {{signal: ctrl.signal}})
      .then(r => {{ clearTimeout(timer); resolve(r); }})
      .catch(e => {{ clearTimeout(timer); reject(e); }});
  }});
}}

// ── Restart ────────────────────────────────────────────────────────────────
async function restartApp() {{
  const banner = document.getElementById('status-banner');
  banner.style.cssText = 'display:block;padding:8px 14px;border-radius:6px;font-size:12px;margin-bottom:16px;background:#2a2010;color:#ffb86c;border:1px solid #4a3010';
  banner.textContent = '↺ Restarting server… (this takes ~5 seconds)';
  // Fire restart — ignore connection errors (server dies immediately after)
  try {{ await _fetchWithTimeout('/restart', 3000); }} catch(e) {{}}
  // Wait 2 s before polling — gives the old process time to die
  await new Promise(r => setTimeout(r, 2000));
  // Poll /health — lightweight, no DB or env work, 30 attempts × 1 s = 30 s budget
  for (let i = 0; i < 30; i++) {{
    try {{
      const r = await _fetchWithTimeout('/health', 1500);
      if (r.ok) {{
        banner.style.cssText = 'display:block;padding:8px 14px;border-radius:6px;font-size:12px;margin-bottom:16px;background:#0d2a1a;color:#50fa7b;border:1px solid #1a4a2a';
        banner.textContent = '✅ Server restarted successfully.';
        load();
        return;
      }}
    }} catch(e) {{}}
    await new Promise(r => setTimeout(r, 1000));
  }}
  banner.textContent = '⚠ Server is taking longer than expected. Try refreshing the page manually.';
}}

function showBanner(msg, type) {{
  const el = document.getElementById('status-banner');
  el.style.cssText = type === 'ok'
    ? 'display:block;padding:8px 14px;border-radius:6px;font-size:12px;margin-bottom:16px;background:#0d2a1a;color:#50fa7b;border:1px solid #1a4a2a'
    : 'display:block;padding:8px 14px;border-radius:6px;font-size:12px;margin-bottom:16px;background:#2a1010;color:#ff6e6e;border:1px solid #4a2020';
  el.textContent = msg;
  setTimeout(() => {{ el.style.display = 'none'; }}, 5000);
}}

document.getElementById('creds-modal').addEventListener('click', e => {{
  if (e.target === document.getElementById('creds-modal')) closeModal();
}});

load();
</script>
</body>
</html>"""


@app.route("/chat", methods=["POST"])
def chat():
    data    = request.json or {}
    message = data.get("message", "").strip()
    tool_id = data.get("tool_id", "home")

    if not message:
        return jsonify({"error": "empty message"}), 400

    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"status": "thinking", "response": None, "warnings": [], "progress": []}
        history = list(_histories.get(tool_id, []))   # per-tool history, copy

    # Use a stable session ID: tool_id + date, so each tool gets a daily session
    import datetime as _dt
    session_id = f"{tool_id}_{_dt.date.today().isoformat()}"

    def progress_cb(event):
        with _lock:
            if job_id in _jobs:
                _jobs[job_id].setdefault("progress", []).append(event)

    def run():
        try:
            from agent import run_agent_turn
            response, updated, warnings = run_agent_turn(
                history, message, auto_confirm=True, progress_callback=progress_cb
            )
            with _lock:
                _histories[tool_id] = updated
            # Persist to conversation history store
            if _CONV_STORE:
                try:
                    title = _cs_get_title(session_id) or message[:60]
                    _cs_save_turn(session_id, tool_id, "user", message, title)
                    _cs_save_turn(session_id, tool_id, "assistant", response, "")
                except Exception:
                    pass
            with _lock:
                _jobs[job_id] = {"status": "done", "response": response, "warnings": warnings}
        except BaseException as exc:
            with _lock:
                _jobs[job_id] = {"status": "error", "response": str(exc), "warnings": []}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/poll/<job_id>")
def poll(job_id):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"status": "unknown"}), 404
    return jsonify(job)


@app.route("/clear", methods=["POST"])
def clear():
    data    = request.json or {}
    tool_id = data.get("tool_id")
    with _lock:
        if tool_id:
            _histories.pop(tool_id, None)
        else:
            _histories.clear()
        _jobs.clear()
    return jsonify({"ok": True})


# ── Super-agent routes ────────────────────────────────────────────────────────

@app.route("/stream")
def stream():
    """SSE endpoint — streams proactive alerts to the browser."""
    from tools.proactive import alert_queue

    def event_gen():
        while True:
            try:
                alert = alert_queue.get(timeout=30)
                yield f"data: {json.dumps(alert)}\n\n"
            except Exception:
                yield ": keepalive\n\n"

    return app.response_class(
        event_gen(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/analytics")
def analytics_route():
    from tools.analytics import get_analytics_summary
    return jsonify(get_analytics_summary())


@app.route("/upload-doc", methods=["POST"])
def upload_doc():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file provided"}), 400
    tmp = Path("/tmp") / (f.filename or "upload.txt")
    f.save(tmp)
    try:
        from tools.rag import add_document
        result = add_document(str(tmp), source_label=f.filename or "upload")
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/upload-tone", methods=["POST"])
def upload_tone():
    data = request.json or {}
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "no text provided"}), 400
    try:
        from tools.tone_learner import add_sample
        result = add_sample(text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/memory")
def memory_view():
    from tools.memory import load_memory
    return jsonify(load_memory())


# ── Model switcher ───────────────────────────────────────────────────────────

@app.route("/model")
def model_get():
    """Return active provider, active model, all providers+availability, presets."""
    from tools.llm_provider import list_available_providers, _resolve_provider_name
    try:
        active_provider = _resolve_provider_name()
    except Exception:
        active_provider = None
    return jsonify({
        "active_provider": active_provider,
        "active_model":    os.getenv("LLM_MODEL", ""),
        "providers":       list_available_providers(),
        "presets":         MODEL_PRESETS,
    })


@app.route("/model", methods=["POST"])
def model_post():
    """Save LLM_PROVIDER and/or LLM_MODEL to .env and update os.environ."""
    data     = request.json or {}
    provider = data.get("provider", "").strip().lower()
    model    = data.get("model", "").strip()
    updates  = {}
    if provider:
        updates["LLM_PROVIDER"] = provider
    if model:
        updates["LLM_MODEL"] = model
    else:
        # empty model string → clear override, fall back to provider default
        os.environ.pop("LLM_MODEL", None)
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            lines = env_path.read_text().splitlines()
            lines = [("LLM_MODEL=" if l.strip().startswith("LLM_MODEL=") else l) for l in lines]
            env_path.write_text("\n".join(lines) + "\n")
    if updates:
        _write_env_vars(updates)
    return jsonify({"ok": True, "provider": provider, "model": model})


# ── Credentials ──────────────────────────────────────────────────────────────

@app.route("/credentials")
def credentials_get():
    """Return credential config + which keys are already set (never expose values)."""
    result = {}
    for name, cfg in CREDS_CONFIG.items():
        result[name] = {
            "label":     cfg["label"],
            "desc":      cfg["desc"],
            "setup_url": cfg["setup_url"],
            "fields": [
                {
                    "key":         f["key"],
                    "label":       f["label"],
                    "placeholder": f["placeholder"],
                    "secret":      f.get("secret", False),
                    "set":         bool(os.getenv(f["key"])),
                }
                for f in cfg["fields"]
            ],
        }
    return jsonify(result)


@app.route("/credentials", methods=["POST"])
def credentials_post():
    """Save credentials to .env — only keys whitelisted for the given integration."""
    data        = request.json or {}
    integration = data.get("integration", "")
    values      = data.get("values", {})
    if integration not in CREDS_CONFIG:
        return jsonify({"error": "Unknown integration"}), 400
    allowed    = {f["key"] for f in CREDS_CONFIG[integration]["fields"]}
    safe_vals  = {k: v for k, v in values.items() if k in allowed and v}
    if not safe_vals:
        return jsonify({"error": "No values provided"}), 400
    result = _write_env_vars(safe_vals)
    return jsonify(result)


# ── Guardrails ────────────────────────────────────────────────────────────────

@app.route("/guardrails")
def guardrails_get():
    from tools.guardrails import get_status
    return jsonify(get_status())


@app.route("/guardrails/<name>", methods=["POST"])
def guardrails_toggle(name):
    from tools.guardrails import toggle
    return jsonify(toggle(name))


# ── Conversation history ─────────────────────────────────────────────────────

try:
    from tools.conversation_store import (
        save_turn as _cs_save_turn,
        get_session_turns as _cs_get_turns,
        list_sessions as _cs_list_sessions,
        search_sessions as _cs_search_sessions,
        delete_session as _cs_delete_session,
        get_session_title_from_first_user_message as _cs_get_title,
    )
    _CONV_STORE = True
except Exception:
    _CONV_STORE = False


@app.route("/history")
def history_list():
    if not _CONV_STORE:
        return jsonify([])
    tool_id = request.args.get("tool_id", "").strip() or None
    q       = request.args.get("q", "").strip()
    if q:
        sessions = _cs_search_sessions(q)
    else:
        sessions = _cs_list_sessions(tool_id=tool_id)
    return jsonify(sessions)


@app.route("/history/<session_id>")
def history_get(session_id):
    if not _CONV_STORE:
        return jsonify([])
    return jsonify(_cs_get_turns(session_id))


@app.route("/history/<session_id>", methods=["DELETE"])
def history_delete(session_id):
    if not _CONV_STORE:
        return jsonify({"ok": False})
    _cs_delete_session(session_id)
    return jsonify({"ok": True})


# ── Tone-matched email draft reply ────────────────────────────────────────────

@app.route("/draft-reply", methods=["POST"])
def draft_reply():
    """Generate a tone-matched draft email reply.
    Body: {"email_body": "...", "instruction": "...optional..."}
    Returns: {"draft": "..."}
    """
    data        = request.get_json(force=True)
    email_body  = data.get("email_body", "").strip()
    instruction = data.get("instruction", "").strip()
    if not email_body:
        return jsonify({"error": "email_body required"}), 400
    try:
        from tools.tone_learner import get_tone_instructions
        from tools.llm_provider import get_provider
        tone_guide = get_tone_instructions()
        provider   = get_provider()
        system = (
            "You are a professional email drafting assistant. "
            "Write in the user's personal style as described below.\n\n"
            + tone_guide
            if tone_guide else
            "You are a professional email drafting assistant. Write clearly and concisely."
        )
        prompt = (
            f"Draft a reply to this email:\n\n{email_body}"
            + (f"\n\nAdditional instruction: {instruction}" if instruction else "")
            + "\n\nWrite only the reply body — no subject line, no sign-off instructions."
        )
        _, draft = provider.run_turn(
            system_prompt=system,
            history=[{"role": "user", "content": prompt}],
            tools=[],
        )
        return jsonify({"draft": draft.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Trigger automation rules ──────────────────────────────────────────────────

@app.route("/triggers")
def triggers_list():
    try:
        from tools.trigger_engine import list_rules, get_trigger_log
        return jsonify({"rules": list_rules(), "log": get_trigger_log(20)})
    except Exception as e:
        return jsonify({"rules": [], "log": [], "error": str(e)})


@app.route("/triggers", methods=["POST"])
def triggers_add():
    data = request.get_json(force=True)
    try:
        from tools.trigger_engine import add_rule
        rule = add_rule(
            name        = data["name"],
            source      = data.get("source", "any"),
            event_type  = data.get("event_type", "any"),
            condition   = data.get("condition", {}),
            action      = data["action"],
            action_args = data.get("action_args", {}),
        )
        return jsonify(rule)
    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/triggers/<int:rule_id>", methods=["DELETE"])
def triggers_delete(rule_id):
    try:
        from tools.trigger_engine import delete_rule
        return jsonify(delete_rule(rule_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/triggers/toggle/<int:rule_id>", methods=["POST"])
def triggers_toggle(rule_id):
    try:
        from tools.trigger_engine import toggle_rule
        data = request.get_json(force=True) or {}
        enabled = bool(data.get("enabled", True))
        return jsonify(toggle_rule(rule_id, enabled))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/actions/add", methods=["POST"])
def actions_add():
    try:
        from tools.action_items import save_action_items
        data = request.get_json(force=True) or {}
        task = data.get("task", "").strip()
        if not task:
            return jsonify({"error": "task is required"}), 400
        count = save_action_items([{
            "task":     task,
            "owner":    data.get("owner", "me"),
            "due_date": data.get("due_date", ""),
            "source":   "manual",
            "priority": data.get("priority", "medium"),
        }])
        return jsonify({"saved": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD PAGES  — full standalone HTML pages linked from the nav sidebar
# ══════════════════════════════════════════════════════════════════════════════

_PAGE_STYLE = """
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#16181d;color:#d4d8e8;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;font-size:13px;min-height:100vh}
a{color:#64ffda;text-decoration:none}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#252836;border-radius:3px}
.page-wrap{max-width:960px;margin:0 auto;padding:28px 24px}
.page-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px}
.page-title{font-size:20px;font-weight:700;color:#d4d8e8;display:flex;align-items:center;gap:10px}
.page-subtitle{font-size:12px;color:#6b7394;margin-top:3px}
.back-link{font-size:11px;color:#6b7394;padding:5px 10px;border:1px solid #252836;border-radius:5px;cursor:pointer;background:none;transition:all .15s}
.back-link:hover{color:#d4d8e8;border-color:#3a4a70}
.stats-bar{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.stat-card{background:#1e2028;border:1px solid #252836;border-radius:7px;padding:10px 16px;flex:1;min-width:100px}
.stat-num{font-size:22px;font-weight:700;color:#64ffda}
.stat-lbl{font-size:10px;color:#6b7394;margin-top:2px}
.filter-bar{display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap}
.flt-btn{background:#1e2028;border:1px solid #252836;color:#8892b0;border-radius:5px;padding:5px 13px;font-size:11px;cursor:pointer;transition:all .15s;font-family:inherit}
.flt-btn:hover{border-color:#3a4a70;color:#d4d8e8}
.flt-btn.active{background:#1c2540;border-color:#2a4070;color:#64ffda}
.btn{border:none;border-radius:5px;padding:8px 16px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;font-family:inherit}
.btn-primary{background:#e94560;color:#fff}
.btn-primary:hover{background:#c73652}
.btn-success{background:#1a3a1a;color:#50fa7b;border:1px solid #2a5a2a}
.btn-success:hover{background:#22472f}
.btn-sm{padding:4px 10px;font-size:11px}
.btn-danger{background:#2a1010;color:#ff6e6e;border:1px solid #4a2020}
.btn-danger:hover{background:#3a1a1a}
.badge{display:inline-block;border-radius:4px;padding:2px 7px;font-size:10px;font-weight:700}
.badge-high{background:#2a1010;color:#ff5555}
.badge-medium{background:#2a2010;color:#ffb86c}
.badge-low{background:#0d2a1a;color:#50fa7b}
.badge-open{background:#1c2540;color:#8be9fd}
.badge-done{background:#1a1c24;color:#6b7394}
.card{background:#1e2028;border:1px solid #252836;border-radius:8px;padding:14px 16px;margin-bottom:10px;transition:border-color .15s}
.card:hover{border-color:#2a3a50}
.card-row{display:flex;align-items:flex-start;gap:12px}
.card-check{margin-top:2px;width:16px;height:16px;cursor:pointer;accent-color:#64ffda;flex-shrink:0}
.card-body{flex:1;min-width:0}
.card-task{font-size:13px;color:#d4d8e8;line-height:1.5;margin-bottom:6px}
.card-task.done{text-decoration:line-through;color:#6b7394}
.card-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.card-meta-item{font-size:10px;color:#6b7394}
.card-actions{display:flex;gap:6px;align-items:center;flex-shrink:0}
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:500;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal-box{background:#1a1c24;border:1px solid #2a2d3e;border-radius:10px;width:440px;max-width:96vw;padding:22px 24px;box-shadow:0 24px 64px rgba(0,0,0,.6)}
.modal-title{font-size:14px;font-weight:700;color:#d4d8e8;margin-bottom:16px}
.form-group{margin-bottom:13px}
.form-label{font-size:11px;color:#8892b0;margin-bottom:5px;display:block}
.form-input,.form-select,.form-textarea{width:100%;background:#12141a;border:1px solid #2a2d3e;border-radius:5px;color:#d4d8e8;font-size:12.5px;padding:8px 10px;outline:none;transition:border-color .15s;font-family:inherit}
.form-input:focus,.form-select:focus,.form-textarea:focus{border-color:#64ffda}
.form-select{appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236b7394'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center}
.form-textarea{resize:vertical;min-height:70px}
.form-row{display:flex;gap:10px}
.form-row .form-group{flex:1}
.modal-ftr{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}
.empty-state{text-align:center;padding:48px 24px;color:#6b7394}
.empty-state-icon{font-size:40px;margin-bottom:12px}
.empty-state-txt{font-size:13px}
table{width:100%;border-collapse:collapse}
th{font-size:10px;color:#6b7394;font-weight:700;letter-spacing:.07em;padding:8px 10px;text-align:left;border-bottom:1px solid #252836;white-space:nowrap}
td{padding:10px;font-size:12px;color:#d4d8e8;border-bottom:1px solid #1e2028;vertical-align:top}
tr:hover td{background:#1e2028}
.table-wrap{background:#1a1c24;border:1px solid #252836;border-radius:8px;overflow:hidden}
.section-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;margin-top:24px}
.section-title{font-size:12px;font-weight:700;color:#8892b0;letter-spacing:.06em}
.log-row{display:flex;gap:10px;padding:7px 0;border-bottom:1px solid #1e2028;font-size:11px;align-items:center}
.log-row:last-child{border-bottom:none}
.log-ts{color:#6b7394;min-width:130px;flex-shrink:0}
.log-name{color:#d4d8e8;flex:1}
.log-type{color:#8892b0;min-width:80px}
.log-result{color:#50fa7b}
.toggle-sw{position:relative;display:inline-block;width:32px;height:18px}
.toggle-sw input{opacity:0;width:0;height:0}
.toggle-slider{position:absolute;cursor:pointer;inset:0;background:#2a2020;border-radius:18px;transition:.3s}
.toggle-slider:before{position:absolute;content:'';height:12px;width:12px;left:3px;bottom:3px;background:#6b7394;border-radius:50%;transition:.3s}
input:checked+.toggle-slider{background:#1a3a1a}
input:checked+.toggle-slider:before{transform:translateX(14px);background:#50fa7b}
.mem-section{margin-bottom:22px}
.mem-section-hdr{font-size:10px;font-weight:700;color:#6b7394;letter-spacing:.08em;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #252836}
.mem-row{display:flex;align-items:flex-start;gap:10px;padding:7px 10px;border-radius:5px;transition:background .12s}
.mem-row:hover{background:#1e2028}
.mem-key{font-size:11px;color:#8892b0;min-width:150px;flex-shrink:0;margin-top:1px}
.mem-val{flex:1;font-size:12px;color:#d4d8e8;word-break:break-word}
.mem-del{background:none;border:none;color:#3a3a4a;font-size:13px;cursor:pointer;flex-shrink:0;transition:color .15s;line-height:1;padding:1px}
.mem-del:hover{color:#ff6e6e}
.updated-at{font-size:10px;color:#3a4060;margin-top:20px;text-align:right}
</style>
"""

_PAGE_NAV = """
<div style="background:#1a1c24;border-bottom:1px solid #252836;padding:8px 20px">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">
    <a href="/" style="font-size:13px;font-weight:700;color:#64ffda;text-decoration:none;flex-shrink:0">⚡ Work Assistant</a>
    <span style="color:#252836;flex-shrink:0">|</span>
    <a href="/actions-page" class="nav-link">✅ Actions</a>
    <a href="/triggers-page" class="nav-link">⚡ Automation</a>
    <a href="/memory-page" class="nav-link">🧠 Memory</a>
    <a href="/scheduler-page" class="nav-link">🕐 Scheduler</a>
    <a href="/search-page" class="nav-link">🔍 Search</a>
    <a href="/inbox-page" class="nav-link">📧 Inbox</a>
    <a href="/calendar-page" class="nav-link">📅 Calendar</a>
    <a href="/documents-page" class="nav-link">📄 Documents</a>
    <a href="/analytics-page" class="nav-link">📊 Analytics</a>
    <a href="/guardrails-page" class="nav-link">🛡 Guardrails</a>
    <a href="/kb-page" class="nav-link">🧠 Knowledge Base</a>
    <a href="/alerts-page" class="nav-link">🔔 Alerts</a>
    <a href="/self-learning-page" class="nav-link">🧬 Self-Learning</a>
    <span style="flex:1"></span>
    <a href="/connections-page" class="nav-link" style="color:#64ffda;border:1px solid #1e3050;padding:3px 10px;border-radius:5px;flex-shrink:0">🔌 Connections</a>
    <button onclick="navRestart(this)" class="nav-link" style="background:none;border:1px solid #2a2030;color:#8892b0;cursor:pointer;padding:3px 10px;border-radius:5px;font-family:inherit;font-size:11.5px;flex-shrink:0">↺ Restart</button>
  </div>
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
    <span style="font-size:10px;color:#3a4060;font-weight:700;letter-spacing:.5px;flex-shrink:0">TOOLS:</span>
    <a href="/github-page" class="nav-link-tool">🐙 GitHub</a>
    <a href="/jira-page" class="nav-link-tool">📋 Jira</a>
    <a href="/linear-page" class="nav-link-tool">⚡ Linear</a>
    <a href="/slack-page" class="nav-link-tool">💬 Slack</a>
    <a href="/teams-page" class="nav-link-tool">👥 Teams</a>
    <a href="/notion-page" class="nav-link-tool">📓 Notion</a>
    <a href="/confluence-page" class="nav-link-tool">📘 Confluence</a>
    <a href="/sharepoint-page" class="nav-link-tool">🗂 SharePoint</a>
    <a href="/excel-page" class="nav-link-tool">📊 Excel</a>
    <a href="/meetings-page" class="nav-link-tool">📹 Meetings</a>
    <a href="/research-page" class="nav-link-tool">🔭 Research</a>
    <a href="/briefing-page" class="nav-link-tool">📨 Briefing</a>
    <a href="/webhooks-page" class="nav-link-tool">🪝 Webhooks</a>
    <a href="/meeting-prep-page" class="nav-link-tool">🗓 Meeting Prep</a>
  </div>
</div>
<style>
.nav-link{font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px;transition:color .15s}
.nav-link:hover{color:#d4d8e8}
.nav-link-tool{font-size:11px;color:#6872a0;text-decoration:none;padding:2px 8px;border-radius:4px;border:1px solid #1e2030;background:#16171f;transition:all .15s}
.nav-link-tool:hover{color:#d4d8e8;border-color:#3a4060}
</style>
<script>
function _navFetchTimeout(url, ms) {
  return new Promise((resolve, reject) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => { ctrl.abort(); reject(new Error('timeout')); }, ms);
    fetch(url, {signal: ctrl.signal})
      .then(r => { clearTimeout(timer); resolve(r); })
      .catch(e => { clearTimeout(timer); reject(e); });
  });
}
async function navRestart(btn) {
  const orig = btn.textContent;
  btn.textContent = '⏳…'; btn.disabled = true;
  // Fire — ignore error (server dies right after)
  try { await _navFetchTimeout('/restart', 3000); } catch(e) {}
  // Wait 2 s for old process to die, then poll /health up to 30 s
  await new Promise(r => setTimeout(r, 2000));
  for (let i = 0; i < 30; i++) {
    try {
      const r = await _navFetchTimeout('/health', 1500);
      if (r.ok) {
        btn.textContent = '✅';
        setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2500);
        return;
      }
    } catch(e) {}
    await new Promise(r => setTimeout(r, 1000));
  }
  btn.textContent = '⚠'; btn.disabled = false;
}
</script>
"""


@app.route("/actions-page")
def actions_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Action Items — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">✅ Action Items Board</div>
      <div class="page-subtitle">Your open tasks, extracted from emails, meetings and chats</div>
    </div>
    <button class="btn btn-primary" onclick="openAddModal()">＋ Add Task</button>
  </div>

  <div class="stats-bar" id="stats-bar">
    <div class="stat-card"><div class="stat-num" id="stat-open">—</div><div class="stat-lbl">Open</div></div>
    <div class="stat-card"><div class="stat-num" id="stat-high" style="color:#ff5555">—</div><div class="stat-lbl">High Priority</div></div>
    <div class="stat-card"><div class="stat-num" id="stat-due" style="color:#ffb86c">—</div><div class="stat-lbl">Due Today</div></div>
    <div class="stat-card"><div class="stat-num" id="stat-done" style="color:#50fa7b">—</div><div class="stat-lbl">Completed</div></div>
  </div>

  <div class="filter-bar">
    <button class="flt-btn active" data-filter="open" onclick="setFilter('open',this)">Open</button>
    <button class="flt-btn" data-filter="high" onclick="setFilter('high',this)">🔴 High Priority</button>
    <button class="flt-btn" data-filter="medium" onclick="setFilter('medium',this)">🟡 Medium</button>
    <button class="flt-btn" data-filter="low" onclick="setFilter('low',this)">🟢 Low</button>
    <button class="flt-btn" data-filter="due" onclick="setFilter('due',this)">📅 Due Today</button>
    <button class="flt-btn" data-filter="completed" onclick="setFilter('completed',this)">✅ Completed</button>
    <button class="flt-btn" data-filter="all" onclick="setFilter('all',this)">All</button>
  </div>

  <div id="items-list"><div class="empty-state"><div class="empty-state-icon">📋</div><div class="empty-state-txt">Loading…</div></div></div>
</div>

<!-- Add Task Modal -->
<div class="modal-overlay" id="add-modal" onclick="if(event.target===this)closeAddModal()">
  <div class="modal-box">
    <div class="modal-title">＋ Add Task</div>
    <div class="form-group">
      <label class="form-label">Task description *</label>
      <input class="form-input" id="add-task" placeholder="What needs to be done?" autofocus>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Priority</label>
        <select class="form-select" id="add-priority">
          <option value="high">🔴 High</option>
          <option value="medium" selected>🟡 Medium</option>
          <option value="low">🟢 Low</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Due date</label>
        <input class="form-input" id="add-due" type="date">
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">Owner</label>
      <input class="form-input" id="add-owner" placeholder="me" value="me">
    </div>
    <div class="modal-ftr">
      <button class="btn" style="background:#252836;color:#8892b0" onclick="closeAddModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitAdd()">Add Task</button>
    </div>
  </div>
</div>

<script>
let _filter = 'open';
let _today = new Date().toISOString().slice(0,10);

function setFilter(f, btn) {{
  _filter = f;
  document.querySelectorAll('.flt-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderItems(_allItems);
}}

let _allItems = [];

async function loadItems() {{
  try {{
    const [openR, doneR] = await Promise.all([
      fetch('/action-items?status=open').then(r=>r.json()),
      fetch('/action-items?status=completed').then(r=>r.json()),
    ]);
    const open = openR.items || [];
    const done = doneR.items || [];
    _allItems = [...open, ...done];
    updateStats(open, done);
    renderItems(_allItems);
  }} catch(e) {{
    document.getElementById('items-list').innerHTML =
      '<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">Could not load tasks — make sure the agent is running.</div></div>';
  }}
}}

function updateStats(open, done) {{
  const today = _today;
  document.getElementById('stat-open').textContent = open.length;
  document.getElementById('stat-high').textContent = open.filter(i=>i.priority==='high').length;
  document.getElementById('stat-due').textContent = open.filter(i=>i.due_date && i.due_date<=today).length;
  document.getElementById('stat-done').textContent = done.length;
}}

function renderItems(items) {{
  let filtered = items;
  const today = _today;
  if (_filter === 'open') filtered = items.filter(i=>i.status==='open');
  else if (_filter === 'completed') filtered = items.filter(i=>i.status==='completed');
  else if (_filter === 'high') filtered = items.filter(i=>i.status==='open' && i.priority==='high');
  else if (_filter === 'medium') filtered = items.filter(i=>i.status==='open' && i.priority==='medium');
  else if (_filter === 'low') filtered = items.filter(i=>i.status==='open' && i.priority==='low');
  else if (_filter === 'due') filtered = items.filter(i=>i.status==='open' && i.due_date && i.due_date<=today);

  const el = document.getElementById('items-list');
  if (!filtered.length) {{
    el.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎉</div><div class="empty-state-txt">Nothing here! All clear.</div></div>';
    return;
  }}
  el.innerHTML = filtered.map(item => {{
    const done = item.status === 'completed';
    const pri = item.priority || 'medium';
    const priLabel = {{high:'🔴 High',medium:'🟡 Medium',low:'🟢 Low'}}[pri] || pri;
    const priBadge = `<span class="badge badge-${{pri}}">${{priLabel}}</span>`;
    const due = item.due_date ? `<span class="card-meta-item">📅 ${{item.due_date}}</span>` : '';
    const owner = item.owner && item.owner !== 'me' ? `<span class="card-meta-item">👤 ${{item.owner}}</span>` : '';
    const src = item.source ? `<span class="card-meta-item">📌 ${{item.source}}</span>` : '';
    const ts = item.extracted_at ? `<span class="card-meta-item">${{item.extracted_at.slice(0,10)}}</span>` : '';
    const checkAttr = done ? 'checked disabled' : `onchange="completeItem(${{item.id}},this)"`;
    return `<div class="card" id="card-${{item.id}}">
      <div class="card-row">
        <input type="checkbox" class="card-check" ${{checkAttr}}>
        <div class="card-body">
          <div class="card-task${{done?' done':''}}">${{_esc(item.task)}}</div>
          <div class="card-meta">${{priBadge}}${{due}}${{owner}}${{src}}${{ts}}</div>
        </div>
        <div class="card-actions">
          ${{!done ? `<button class="btn btn-danger btn-sm" onclick="deleteItem(${{item.id}})">✕</button>` : ''}}
        </div>
      </div>
    </div>`;
  }}).join('');
}}

async function completeItem(id, cb) {{
  cb.disabled = true;
  await fetch('/action-items/complete', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{id}})}});
  await loadItems();
}}

async function deleteItem(id) {{
  if (!confirm('Delete this task?')) return;
  await fetch('/action-items/delete', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{id}})}});
  document.getElementById('card-'+id)?.remove();
  _allItems = _allItems.filter(i=>i.id!==id);
  updateStats(_allItems.filter(i=>i.status==='open'), _allItems.filter(i=>i.status==='completed'));
}}

function openAddModal() {{
  document.getElementById('add-modal').classList.add('open');
  document.getElementById('add-task').focus();
}}
function closeAddModal() {{
  document.getElementById('add-modal').classList.remove('open');
  document.getElementById('add-task').value='';
  document.getElementById('add-due').value='';
  document.getElementById('add-owner').value='me';
}}

async function submitAdd() {{
  const task = document.getElementById('add-task').value.trim();
  if (!task) {{ document.getElementById('add-task').focus(); return; }}
  await fetch('/actions/add', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{
      task, priority: document.getElementById('add-priority').value,
      due_date: document.getElementById('add-due').value,
      owner: document.getElementById('add-owner').value || 'me',
    }})
  }});
  closeAddModal();
  loadItems();
}}

function _esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

// Add task on Enter in the task input
document.addEventListener('DOMContentLoaded', ()=>{{
  document.getElementById('add-task').addEventListener('keydown', e=>{{ if(e.key==='Enter') submitAdd(); }});
  loadItems();
  setInterval(loadItems, 30000);
}});
</script>
</body></html>"""
    return html


@app.route("/action-items")
def action_items_api():
    try:
        from tools.action_items import get_my_action_items
        status   = request.args.get("status", "open")
        priority = request.args.get("priority") or None
        items    = get_my_action_items(status=status, priority=priority)
        return jsonify({"items": items})
    except Exception as e:
        return jsonify({"items": [], "error": str(e)})


@app.route("/action-items/complete", methods=["POST"])
def action_items_complete():
    try:
        from tools.action_items import complete_action_item
        item_id = (request.get_json(force=True) or {}).get("id")
        return jsonify(complete_action_item(item_id=item_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/action-items/delete", methods=["POST"])
def action_items_delete():
    try:
        from tools.action_items import delete_action_item
        item_id = (request.get_json(force=True) or {}).get("id")
        return jsonify(delete_action_item(item_id=item_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/triggers-page")
def triggers_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Automation Rules — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">⚡ Automation Rules</div>
      <div class="page-subtitle">If-this-then-that rules triggered by GitHub, Jira, and other webhooks</div>
    </div>
    <button class="btn btn-primary" onclick="openAddModal()">＋ Add Rule</button>
  </div>

  <div class="table-wrap" id="rules-wrap">
    <table>
      <thead><tr>
        <th>Name</th><th>Source</th><th>Event</th><th>Condition</th><th>Action</th><th>Fires</th><th>Status</th><th></th>
      </tr></thead>
      <tbody id="rules-body"><tr><td colspan="8" style="text-align:center;color:#6b7394;padding:24px">Loading…</td></tr></tbody>
    </table>
  </div>

  <div class="section-hdr" style="margin-top:28px">
    <span class="section-title">🔥 RECENT FIRE LOG</span>
    <button class="btn btn-sm" style="background:#252836;color:#8892b0;border:1px solid #252836" onclick="loadData()">↻ Refresh</button>
  </div>
  <div class="table-wrap">
    <div id="log-body" style="padding:0 10px"></div>
  </div>
</div>

<!-- Add Rule Modal -->
<div class="modal-overlay" id="add-modal" onclick="if(event.target===this)closeAddModal()">
  <div class="modal-box" style="width:520px">
    <div class="modal-title">⚡ Add Automation Rule</div>
    <div class="form-group">
      <label class="form-label">Rule name *</label>
      <input class="form-input" id="r-name" placeholder="e.g. Notify on PR opened">
    </div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Source</label>
        <select class="form-select" id="r-source">
          <option value="any">Any</option>
          <option value="github">GitHub</option>
          <option value="jira">Jira</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Event type</label>
        <select class="form-select" id="r-event">
          <option value="any">Any</option>
          <option value="pull_request">pull_request</option>
          <option value="push">push</option>
          <option value="issues">issues</option>
          <option value="issue_comment">issue_comment</option>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">Condition (JSON key:value pairs to match in payload)</label>
      <input class="form-input" id="r-condition" placeholder='{{"action": "opened"}}'>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Action *</label>
        <select class="form-select" id="r-action">
          <option value="notify">notify</option>
          <option value="slack_message">slack_message</option>
          <option value="create_jira">create_jira</option>
          <option value="create_linear">create_linear</option>
        </select>
      </div>
    </div>
    <div class="form-group">
      <label class="form-label">Action args (JSON)</label>
      <input class="form-input" id="r-action-args" placeholder='{{"channel": "#dev", "message": "New PR!"}}'>
    </div>
    <div id="add-error" style="color:#ff6e6e;font-size:11px;margin-top:6px;display:none"></div>
    <div class="modal-ftr">
      <button class="btn" style="background:#252836;color:#8892b0" onclick="closeAddModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitAdd()">Add Rule</button>
    </div>
  </div>
</div>

<script>
let _rules = [];

async function loadData() {{
  try {{
    const data = await fetch('/triggers').then(r=>r.json());
    _rules = data.rules || [];
    renderRules(_rules);
    renderLog(data.log || []);
  }} catch(e) {{
    document.getElementById('rules-body').innerHTML =
      '<tr><td colspan="8" style="color:#ff6e6e;padding:16px;text-align:center">Could not load — make sure the agent is running</td></tr>';
  }}
}}

function renderRules(rules) {{
  const tb = document.getElementById('rules-body');
  if (!rules.length) {{
    tb.innerHTML = '<tr><td colspan="8" style="text-align:center;color:#6b7394;padding:24px">No rules yet. Click ＋ Add Rule to create one.</td></tr>';
    return;
  }}
  tb.innerHTML = rules.map(r => {{
    const cond = Object.keys(r.condition||{{}}).length
      ? Object.entries(r.condition).map(([k,v])=>`${{k}}=${{v}}`).join(', ')
      : '<em style="color:#6b7394">any</em>';
    const args = Object.keys(r.action_args||{{}}).length
      ? '<code style="font-size:10px;color:#8892b0">'+JSON.stringify(r.action_args)+'</code>'
      : '<em style="color:#6b7394">—</em>';
    return `<tr id="rule-${{r.id}}">
      <td style="font-weight:600">${{_esc(r.name)}}</td>
      <td><span class="badge badge-open">${{r.source}}</span></td>
      <td style="color:#8892b0">${{r.event_type}}</td>
      <td style="font-size:11px">${{cond}}</td>
      <td><span class="badge badge-medium">${{r.action}}</span><br><span style="font-size:10px;color:#6b7394">${{args}}</span></td>
      <td style="color:#64ffda;font-weight:700">${{r.fire_count||0}}</td>
      <td>
        <label class="toggle-sw">
          <input type="checkbox" ${{r.enabled?'checked':''}} onchange="toggleRule(${{r.id}},this.checked)">
          <span class="toggle-slider"></span>
        </label>
      </td>
      <td><button class="btn btn-danger btn-sm" onclick="deleteRule(${{r.id}})">Delete</button></td>
    </tr>`;
  }}).join('');
}}

function renderLog(log) {{
  const el = document.getElementById('log-body');
  if (!log.length) {{
    el.innerHTML = '<div style="padding:16px;color:#6b7394;text-align:center;font-size:12px">No events fired yet.</div>';
    return;
  }}
  el.innerHTML = log.map(l=>`
    <div class="log-row">
      <span class="log-ts">${{l.fired_at ? l.fired_at.slice(0,19).replace('T',' ') : '—'}}</span>
      <span class="log-name">${{_esc(l.rule_name)}}</span>
      <span class="log-type">${{l.event_type}}</span>
      <span class="log-result">✓ ${{l.result}}</span>
    </div>`).join('');
}}

async function toggleRule(id, enabled) {{
  await fetch('/triggers/toggle/'+id, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{enabled}})}});
}}

async function deleteRule(id) {{
  if (!confirm('Delete this rule?')) return;
  await fetch('/triggers/'+id, {{method:'DELETE'}});
  _rules = _rules.filter(r=>r.id!==id);
  renderRules(_rules);
}}

function openAddModal() {{
  document.getElementById('add-error').style.display='none';
  document.getElementById('add-modal').classList.add('open');
  document.getElementById('r-name').focus();
}}
function closeAddModal() {{
  document.getElementById('add-modal').classList.remove('open');
  ['r-name','r-condition','r-action-args'].forEach(id=>document.getElementById(id).value='');
}}

async function submitAdd() {{
  const name = document.getElementById('r-name').value.trim();
  const errEl = document.getElementById('add-error');
  if (!name) {{ errEl.textContent='Rule name is required'; errEl.style.display='block'; return; }}

  let condition = {{}}, action_args = {{}};
  try {{ const raw=document.getElementById('r-condition').value.trim(); if(raw) condition=JSON.parse(raw); }} catch(e) {{ errEl.textContent='Condition must be valid JSON'; errEl.style.display='block'; return; }}
  try {{ const raw=document.getElementById('r-action-args').value.trim(); if(raw) action_args=JSON.parse(raw); }} catch(e) {{ errEl.textContent='Action args must be valid JSON'; errEl.style.display='block'; return; }}

  errEl.style.display='none';
  const res = await fetch('/triggers', {{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{name, source:document.getElementById('r-source').value, event_type:document.getElementById('r-event').value, condition, action:document.getElementById('r-action').value, action_args}})
  }});
  const data = await res.json();
  if (data.error) {{ errEl.textContent=data.error; errEl.style.display='block'; return; }}
  closeAddModal();
  loadData();
}}

function _esc(s) {{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

document.addEventListener('DOMContentLoaded', ()=>{{ loadData(); setInterval(loadData, 15000); }});
</script>
</body></html>"""
    return html


@app.route("/memory-page")
def memory_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Memory Viewer — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">🧠 Memory Viewer</div>
      <div class="page-subtitle">Everything the agent has learned and remembered about you</div>
    </div>
    <button class="btn btn-primary" onclick="openAddModal()">＋ Add Fact</button>
  </div>

  <div id="mem-content"><div class="empty-state"><div class="empty-state-icon">🧠</div><div class="empty-state-txt">Loading…</div></div></div>
</div>

<!-- Add Fact Modal -->
<div class="modal-overlay" id="add-modal" onclick="if(event.target===this)closeAddModal()">
  <div class="modal-box">
    <div class="modal-title">＋ Add Fact</div>
    <div class="form-group">
      <label class="form-label">Category</label>
      <select class="form-select" id="f-category">
        <option value="preferences">preferences</option>
        <option value="context">context</option>
        <option value="people">people</option>
        <option value="patterns">patterns</option>
        <option value="facts" selected>facts</option>
      </select>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Key *</label>
        <input class="form-input" id="f-key" placeholder="e.g. timezone">
      </div>
      <div class="form-group">
        <label class="form-label">Value *</label>
        <input class="form-input" id="f-value" placeholder="e.g. GMT+5:30">
      </div>
    </div>
    <div class="modal-ftr">
      <button class="btn" style="background:#252836;color:#8892b0" onclick="closeAddModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitAdd()">Save</button>
    </div>
  </div>
</div>

<script>
const SECTION_META = {{
  preferences: {{ icon:'⚙️', label:'Preferences', desc:'Response style, timezone, language' }},
  context:     {{ icon:'📌', label:'Work Context', desc:'Sprint, projects, team, company' }},
  people:      {{ icon:'👥', label:'People',       desc:'Colleagues auto-extracted from conversations' }},
  patterns:    {{ icon:'📈', label:'Work Patterns', desc:'Observed habits and routines' }},
  facts:       {{ icon:'💡', label:'Other Facts',   desc:'Free-form facts the agent has learned' }},
}};

async function loadMemory() {{
  try {{
    const data = await fetch('/memory').then(r=>r.json());
    renderMemory(data);
  }} catch(e) {{
    document.getElementById('mem-content').innerHTML =
      '<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">Could not load — make sure the agent is running.</div></div>';
  }}
}}

function renderMemory(data) {{
  const mem = data.memory || {{}};
  const updatedAt = data.updated_at || '';
  const el = document.getElementById('mem-content');

  let totalFacts = 0;
  let html = '';

  for (const [cat, meta] of Object.entries(SECTION_META)) {{
    const entries = mem[cat] || {{}};
    const count = Object.keys(entries).length;
    totalFacts += count;
    html += `<div class="mem-section">
      <div class="mem-section-hdr">${{meta.icon}} ${{meta.label.toUpperCase()}} <span style="color:#3a4060;font-weight:400;letter-spacing:0;font-size:9px;margin-left:6px">${{meta.desc}}</span></div>`;

    if (!count) {{
      html += `<div style="padding:8px 10px;color:#3a4060;font-size:11px;font-style:italic">Nothing recorded yet.</div>`;
    }} else {{
      for (const [key, val] of Object.entries(entries)) {{
        const display = typeof val === 'object' ? JSON.stringify(val) : String(val);
        html += `<div class="mem-row">
          <span class="mem-key">${{_esc(key)}}</span>
          <span class="mem-val">${{_esc(display)}}</span>
          <button class="mem-del" title="Delete" onclick="deleteFact('${{_esc(cat)}}','${{_esc(key)}}')">✕</button>
        </div>`;
      }}
    }}
    html += `</div>`;
  }}

  if (!totalFacts) {{
    html = '<div class="empty-state"><div class="empty-state-icon">🌱</div><div class="empty-state-txt">No memories yet — start chatting with the agent and it will learn about you automatically.</div></div>';
  }}

  if (updatedAt) html += `<div class="updated-at">Last updated: ${{updatedAt.slice(0,19).replace('T',' ')}}</div>`;
  el.innerHTML = html;
}}

async function deleteFact(category, key) {{
  if (!confirm(`Delete "${{key}}" from ${{category}}?`)) return;
  await fetch('/memory/delete', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{category,key}})}});
  loadMemory();
}}

function openAddModal() {{
  document.getElementById('add-modal').classList.add('open');
  document.getElementById('f-key').focus();
}}
function closeAddModal() {{
  document.getElementById('add-modal').classList.remove('open');
  document.getElementById('f-key').value='';
  document.getElementById('f-value').value='';
}}

async function submitAdd() {{
  const category = document.getElementById('f-category').value;
  const key = document.getElementById('f-key').value.trim();
  const value = document.getElementById('f-value').value.trim();
  if (!key || !value) return;
  await fetch('/memory/add', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{category,key,value}})}});
  closeAddModal();
  loadMemory();
}}

function _esc(s) {{ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

document.addEventListener('DOMContentLoaded', ()=>{{ loadMemory(); }});
</script>
</body></html>"""
    return html


@app.route("/memory")
def memory_get():
    try:
        from tools.memory import get_memory_summary
        return jsonify(get_memory_summary())
    except Exception as e:
        return jsonify({"memory": {}, "total_facts": 0, "error": str(e)})


@app.route("/memory/add", methods=["POST"])
def memory_add():
    try:
        from tools.memory import save_fact
        data = request.get_json(force=True) or {}
        save_fact(data["category"], data["key"], data["value"])
        return jsonify({"status": "saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/memory/delete", methods=["POST"])
def memory_delete():
    try:
        from tools.memory import delete_fact
        data = request.get_json(force=True) or {}
        delete_fact(data["category"], data["key"])
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ══════════════════════════════════════════════════════════════════════════════
# CLOUDFLARE TUNNEL  (optional public URL)
# ══════════════════════════════════════════════════════════════════════════════

_PUBLIC_URL: str | None = None

def _start_tunnel():
    global _PUBLIC_URL
    import subprocess, re
    candidates = ["cloudflared", "/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"]
    binary = next((c for c in candidates
                   if subprocess.run(["which", c] if c=="cloudflared" else ["test","-f",c],
                                     capture_output=True).returncode == 0), None)
    if not binary:
        print("⚠️  cloudflared not found — running local only.")
        return
    try:
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        url_re = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")
        for line in proc.stdout:
            m = url_re.search(line)
            if m:
                _PUBLIC_URL = m.group(0)
                print(f"\n  🌐  Public URL : {_PUBLIC_URL}")
                print(f"  💻  Local URL  : http://localhost:{PORT}\n")
                break
    except Exception as e:
        print(f"⚠️  Tunnel error: {e}")


@app.route("/public-url")
def public_url():
    return jsonify({"url": _PUBLIC_URL})


# ══════════════════════════════════════════════════════════════════════════════
# NEW FEATURE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

# ── Action item dependencies ──────────────────────────────────────────────────

@app.route("/action-items/depends", methods=["POST"])
def action_items_depends():
    try:
        from tools.action_items import set_depends_on
        data = request.get_json(force=True) or {}
        item_id = int(data["id"])
        depends_on = list(data.get("depends_on", []))
        return jsonify(set_depends_on(item_id, depends_on))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ── Conversation export ───────────────────────────────────────────────────────

@app.route("/export/<session_id>")
def export_conversation(session_id):
    if not _CONV_STORE:
        return "No conversation store available", 404
    turns = _cs_get_turns(session_id)
    sessions = _cs_list_sessions()
    session_meta = next((s for s in sessions if s["id"] == session_id), {})
    title = session_meta.get("title", session_id)
    lines = [f"# {title}", "", f"*Exported from Work Assistant — {session_id}*", ""]
    for t in turns:
        role = "**You**" if t["role"] == "user" else "**Assistant**"
        ts = t.get("ts", "")[:19].replace("T", " ")
        lines.append(f"### {role}  _{ts}_")
        lines.append("")
        lines.append(t.get("content", ""))
        lines.append("")
    md = "\n".join(lines)
    from flask import Response
    return Response(
        md,
        mimetype="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{session_id}.md"'},
    )


# ── Send draft email ──────────────────────────────────────────────────────────

@app.route("/send-draft", methods=["POST"])
def send_draft():
    data = request.get_json(force=True) or {}
    draft = data.get("draft", "").strip()
    email_context = data.get("email_context", "")
    if not draft:
        return jsonify({"ok": False, "error": "No draft provided"}), 400
    try:
        import re as _re, os as _os
        emails = _re.findall(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
                              email_context)
        if not emails:
            return jsonify({"ok": False, "error": "No recipient found in email context. Copy the draft manually."}), 400
        to = emails[0]
        if _os.getenv("GMAIL_APP_PASSWORD", "").strip():
            from tools.gmail_smtp import send_email
        else:
            from tools.ms365 import send_email
        result = send_email(to=to, subject="Re: (Work Assistant draft)", body=draft)
        return jsonify({"ok": True, "result": str(result)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Direct email send (bypasses agent — always uses Gmail SMTP) ───────────────

@app.route("/email/send", methods=["POST"])
def email_send_direct():
    """
    Send an email directly via Gmail SMTP, bypassing the agent entirely.
    Body: { "to": "...", "subject": "...", "body": "...", "html_body": "..." (optional) }
    """
    data = request.get_json(force=True) or {}
    to      = (data.get("to")      or "").strip()
    subject = (data.get("subject") or "").strip()
    body    = (data.get("body")    or "").strip()
    html_body = data.get("html_body", "")

    if not to or not subject or not body:
        return jsonify({"ok": False, "error": "Missing required fields: to, subject, body"}), 400

    # Prefer Gmail SMTP; fall back to MS365 if not configured
    try:
        import os as _os
        if _os.getenv("GMAIL_APP_PASSWORD", "").strip():
            from tools.gmail_smtp import send_email as gmail_send
            result = gmail_send(to=to, subject=subject, body=body,
                                html_body=html_body if html_body else None)
        else:
            from tools.ms365 import send_email as ms_send
            result = ms_send(to=to, subject=subject, body=body)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Global smart search ───────────────────────────────────────────────────────

@app.route("/search")
def global_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"results": [], "error": "empty query"})
    results = []
    import concurrent.futures as _cf

    def search_memory(q):
        try:
            from tools.memory import load_memory
            mem = load_memory()
            hits = []
            for cat, items in mem.items():
                if not isinstance(items, dict):
                    continue
                for k, v in items.items():
                    text = f"{k} {v}".lower()
                    if q.lower() in text:
                        hits.append({"source": "memory", "category": cat, "key": k,
                                     "snippet": f"{k}: {str(v)[:200]}"})
            return hits
        except Exception:
            return []

    def search_actions(q):
        try:
            from tools.action_items import get_my_action_items
            items = get_my_action_items(status="all", max_count=100)
            return [{"source": "actions", "id": i["id"], "snippet": i["task"],
                     "priority": i["priority"], "status": i["status"]}
                    for i in items if q.lower() in i["task"].lower()]
        except Exception:
            return []

    def search_history_items(q):
        try:
            sessions = _cs_search_sessions(q) if _CONV_STORE else []
            return [{"source": "history", "id": s["id"], "snippet": s["title"],
                     "tool_id": s.get("tool_id", "")} for s in sessions]
        except Exception:
            return []

    def search_kb(q):
        try:
            from tools.rag import search_knowledge_base
            hits = search_knowledge_base(q, max_results=5)
            return [{"source": "knowledge_base", "snippet": h.get("text", "")[:200],
                     "doc": h.get("source", "")} for h in hits]
        except Exception:
            return []

    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(fn, q) for fn in [search_memory, search_actions,
                                                search_history_items, search_kb]]
        for f in _cf.as_completed(futs):
            results.extend(f.result())

    return jsonify({"results": results, "query": q})


@app.route("/search-page")
def search_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Search — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">🔍 Global Search</div>
      <div class="page-subtitle">Search across memory, action items, conversation history, and knowledge base</div>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-bottom:24px">
    <input id="search-input" class="form-input" placeholder="Search everything…" autofocus
      style="flex:1;padding:12px 16px;font-size:14px"
      onkeydown="if(event.key==='Enter')doSearch()">
    <button class="btn btn-primary" onclick="doSearch()" style="padding:12px 24px;font-size:14px">Search</button>
  </div>

  <div id="search-results" style="display:none">
    <div id="results-count" style="font-size:12px;color:#6b7394;margin-bottom:16px"></div>
    <div id="results-memory" class="mem-section" style="display:none">
      <div class="mem-section-hdr">🧠 MEMORY</div>
      <div id="results-memory-items"></div>
    </div>
    <div id="results-actions" class="mem-section" style="display:none">
      <div class="mem-section-hdr">✅ ACTION ITEMS</div>
      <div id="results-actions-items"></div>
    </div>
    <div id="results-history" class="mem-section" style="display:none">
      <div class="mem-section-hdr">🕐 CONVERSATIONS</div>
      <div id="results-history-items"></div>
    </div>
    <div id="results-kb" class="mem-section" style="display:none">
      <div class="mem-section-hdr">📚 KNOWLEDGE BASE</div>
      <div id="results-kb-items"></div>
    </div>
  </div>
  <div id="search-empty" class="empty-state" style="display:none">
    <div class="empty-state-icon">🔍</div>
    <div class="empty-state-txt" id="search-empty-txt">No results found.</div>
  </div>
</div>

<script>
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}

async function doSearch() {{
  const q = document.getElementById('search-input').value.trim();
  if (!q) return;
  document.getElementById('search-results').style.display='none';
  document.getElementById('search-empty').style.display='none';
  document.getElementById('results-count').textContent='Searching…';
  document.getElementById('search-results').style.display='block';
  try {{
    const d = await fetch('/search?q='+encodeURIComponent(q)).then(r=>r.json());
    const res = d.results || [];
    if (!res.length) {{
      document.getElementById('search-results').style.display='none';
      document.getElementById('search-empty').style.display='block';
      document.getElementById('search-empty-txt').textContent='No results for "'+_esc(q)+'"';
      return;
    }}
    document.getElementById('results-count').textContent=res.length+' result(s) for "'+_esc(q)+'"';
    const groups = {{}};
    res.forEach(r => {{ (groups[r.source]||=(groups[r.source]=[])).push(r); }});

    const showSection = (id, items, renderFn) => {{
      const sec = document.getElementById('results-'+id);
      const inner = document.getElementById('results-'+id+'-items');
      if (items && items.length) {{
        sec.style.display='';
        inner.innerHTML = items.map(renderFn).join('');
      }} else {{
        sec.style.display='none';
      }}
    }};

    showSection('memory', groups['memory'], r =>
      `<div class="mem-row"><span class="mem-key">${{_esc(r.category)}} / ${{_esc(r.key)}}</span><span class="mem-val">${{_esc(r.snippet)}}</span></div>`);

    showSection('actions', groups['actions'], r =>
      `<div class="mem-row"><span class="badge badge-${{r.priority||'medium'}}" style="min-width:50px;margin-top:1px">${{_esc(r.priority||'medium')}}</span><span class="mem-val">${{_esc(r.snippet)}}</span></div>`);

    showSection('history', groups['history'], r =>
      `<div class="mem-row"><span class="mem-key">${{_esc(r.tool_id)}}</span><span class="mem-val"><a href="/" style="color:#64ffda">${{_esc(r.snippet)}}</a></span></div>`);

    showSection('kb', groups['knowledge_base'], r =>
      `<div class="mem-row"><span class="mem-key">${{_esc(r.doc||'doc')}}</span><span class="mem-val">${{_esc(r.snippet)}}</span></div>`);

  }} catch(e) {{
    document.getElementById('results-count').textContent='Error: '+e.message;
  }}
}}

document.addEventListener('DOMContentLoaded', () => {{
  document.getElementById('search-input').focus();
  const params = new URLSearchParams(location.search);
  const q = params.get('q');
  if (q) {{ document.getElementById('search-input').value=q; doSearch(); }}
}});
</script>
</body></html>"""
    return html


# ── Meeting prep ──────────────────────────────────────────────────────────────

@app.route("/meeting-prep", methods=["POST"])
def meeting_prep():
    data = request.get_json(force=True) or {}
    title = data.get("title", "").strip()
    attendees = data.get("attendees", [])  # list of names or emails
    if not title:
        return jsonify({"error": "title required"}), 400
    result = {"title": title, "attendees": [], "action_items": [], "memory": {}}
    # 1. Look up each attendee in memory
    try:
        from tools.memory import load_memory
        mem = load_memory()
        people = mem.get("people", {})
        for att in attendees:
            att_lower = att.lower()
            match = next((v for k, v in people.items() if att_lower in k.lower()), None)
            result["attendees"].append({"name": att, "info": match or {}})
        result["memory"] = {
            "context": mem.get("context", {}),
            "relevant_people": {k: v for k, v in people.items()
                                if any(a.lower() in k.lower() for a in attendees)},
        }
    except Exception:
        pass
    # 2. Related action items
    try:
        from tools.action_items import get_my_action_items
        items = get_my_action_items(status="open", max_count=20)
        related = [i for i in items if any(
            a.lower() in i["task"].lower() or a.lower() in i["owner"].lower()
            for a in ([title] + attendees)
        )]
        result["action_items"] = related
    except Exception:
        pass
    return jsonify(result)


@app.route("/meeting-prep-page")
def meeting_prep_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meeting Prep — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">📅 Meeting Prep</div>
      <div class="page-subtitle">Auto-pull context, attendee info and action items before your meeting</div>
    </div>
  </div>

  <div style="background:#1e2028;border:1px solid #252836;border-radius:8px;padding:20px;margin-bottom:24px">
    <div class="form-group">
      <label class="form-label">Meeting title *</label>
      <input class="form-input" id="meet-title" placeholder="e.g. Q2 Sprint Review">
    </div>
    <div class="form-group">
      <label class="form-label">Attendees (names or emails, comma-separated)</label>
      <input class="form-input" id="meet-attendees" placeholder="e.g. Ahmed, sarah@company.com, John">
    </div>
    <button class="btn btn-primary" onclick="prepMeeting()" style="margin-top:4px">Prepare Briefing →</button>
  </div>

  <div id="prep-result" style="display:none"></div>
</div>

<script>
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}

async function prepMeeting() {{
  const title = document.getElementById('meet-title').value.trim();
  const att = document.getElementById('meet-attendees').value.split(',').map(s=>s.trim()).filter(Boolean);
  if (!title) {{document.getElementById('meet-title').focus();return;}}
  const res = document.getElementById('prep-result');
  res.style.display='block';
  res.innerHTML='<div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Preparing briefing…</div></div>';
  try {{
    const d = await fetch('/meeting-prep',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{title,attendees:att}})}}).then(r=>r.json());
    let html='';
    // Action items
    if (d.action_items && d.action_items.length) {{
      html+='<div class="mem-section"><div class="mem-section-hdr">✅ RELATED ACTION ITEMS</div>';
      d.action_items.forEach(i=>{{
        html+=`<div class="mem-row"><span class="badge badge-${{_esc(i.priority)}}" style="min-width:50px;margin-top:1px">${{_esc(i.priority)}}</span><span class="mem-val">${{_esc(i.task)}}</span></div>`;
      }});
      html+='</div>';
    }}
    // Attendees
    if (d.attendees && d.attendees.length) {{
      html+='<div class="mem-section"><div class="mem-section-hdr">👥 ATTENDEES</div>';
      d.attendees.forEach(a=>{{
        const info=a.info||{{}};
        html+=`<div class="mem-row"><span class="mem-key">${{_esc(a.name)}}</span><span class="mem-val">${{info.role?'Role: '+_esc(info.role):''}}</span></div>`;
      }});
      html+='</div>';
    }}
    // Work context
    const ctx=d.memory&&d.memory.context||{{}};
    if (Object.keys(ctx).length) {{
      html+='<div class="mem-section"><div class="mem-section-hdr">📌 WORK CONTEXT</div>';
      Object.entries(ctx).forEach(([k,v])=>{{
        html+=`<div class="mem-row"><span class="mem-key">${{_esc(k)}}</span><span class="mem-val">${{_esc(String(v))}}</span></div>`;
      }});
      html+='</div>';
    }}
    if (!html) html='<div class="empty-state"><div class="empty-state-icon">ℹ️</div><div class="empty-state-txt">No relevant context found yet. Add memory facts and action items to get a richer briefing.</div></div>';
    res.innerHTML=html;
  }} catch(e) {{
    res.innerHTML='<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">Error: '+_esc(e.message)+'</div></div>';
  }}
}}
</script>
</body></html>"""
    return html


# ── Scheduler routes ──────────────────────────────────────────────────────────

@app.route("/scheduler")
def scheduler_list():
    try:
        from tools.scheduler import list_tasks, get_next_run
        tasks = list_tasks()
        for t in tasks:
            t["next_run"] = get_next_run(t["id"])
        return jsonify({"tasks": tasks})
    except Exception as e:
        return jsonify({"tasks": [], "error": str(e)})


@app.route("/scheduler", methods=["POST"])
def scheduler_add():
    data = request.get_json(force=True) or {}
    try:
        from tools.scheduler import add_task
        task = add_task(
            name=data["name"],
            cron_expr=data["cron_expr"],
            query=data["query"],
            tool_id=data.get("tool_id", "home"),
        )
        return jsonify(task)
    except KeyError as e:
        return jsonify({"error": f"Missing field: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/scheduler/<int:task_id>", methods=["DELETE"])
def scheduler_delete(task_id):
    try:
        from tools.scheduler import delete_task
        return jsonify(delete_task(task_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/scheduler/toggle/<int:task_id>", methods=["POST"])
def scheduler_toggle(task_id):
    try:
        from tools.scheduler import toggle_task
        data = request.get_json(force=True) or {}
        enabled = bool(data.get("enabled", True))
        return jsonify(toggle_task(task_id, enabled))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/scheduler-page")
def scheduler_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scheduler — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">🕐 Scheduled Tasks</div>
      <div class="page-subtitle">Recurring agent queries that run automatically on a cron schedule</div>
    </div>
    <button class="btn btn-primary" onclick="openAddModal()">＋ Add Task</button>
  </div>

  <div class="table-wrap">
    <table>
      <thead><tr>
        <th>Name</th><th>Schedule</th><th>Query</th><th>Runs</th><th>Last run</th><th>Next run</th><th>Enabled</th><th></th>
      </tr></thead>
      <tbody id="tasks-body"><tr><td colspan="8" style="text-align:center;color:#6b7394;padding:24px">Loading…</td></tr></tbody>
    </table>
  </div>

  <div style="margin-top:16px;background:#1e2028;border:1px solid #252836;border-radius:6px;padding:14px">
    <div style="font-size:11px;font-weight:700;color:#8892b0;margin-bottom:8px">📖 CRON EXAMPLES</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;color:#6b7394">
      <div><code style="color:#64ffda">0 8 * * *</code> — Every day at 08:00</div>
      <div><code style="color:#64ffda">0 9 * * 1</code> — Every Monday at 09:00</div>
      <div><code style="color:#64ffda">*/30 * * * *</code> — Every 30 minutes</div>
      <div><code style="color:#64ffda">0 0 * * *</code> — Midnight every day</div>
      <div><code style="color:#64ffda">0 8 * * 1-5</code> — Weekdays at 08:00</div>
      <div><code style="color:#64ffda">0 17 * * 5</code> — Fridays at 17:00</div>
    </div>
  </div>
</div>

<!-- Add Task Modal -->
<div class="modal-overlay" id="add-modal" onclick="if(event.target===this)closeAddModal()">
  <div class="modal-box">
    <div class="modal-title">🕐 Add Scheduled Task</div>
    <div class="form-group">
      <label class="form-label">Name *</label>
      <input class="form-input" id="add-name" placeholder="e.g. Daily briefing" autofocus>
    </div>
    <div class="form-group">
      <label class="form-label">Cron expression *</label>
      <input class="form-input" id="add-cron" placeholder="e.g. 0 8 * * *">
    </div>
    <div class="form-group">
      <label class="form-label">Query (what the agent will run) *</label>
      <textarea class="form-textarea" id="add-query" placeholder="e.g. Give me my daily briefing including emails and calendar"></textarea>
    </div>
    <div class="form-group">
      <label class="form-label">Tool context</label>
      <select class="form-select" id="add-tool">
        <option value="home">Home</option>
        <option value="outlook">Outlook</option>
        <option value="github">GitHub</option>
        <option value="jira">Jira</option>
        <option value="slack">Slack</option>
        <option value="actions">Action Items</option>
      </select>
    </div>
    <div class="modal-ftr">
      <button class="btn" style="background:#252836;color:#8892b0" onclick="closeAddModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitAdd()">Add Task</button>
    </div>
    <div id="add-msg" style="font-size:11px;color:#ff5555;margin-top:8px"></div>
  </div>
</div>

<script>
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
let _tasks=[];

async function loadTasks(){{
  try{{
    const d=await fetch('/scheduler').then(r=>r.json());
    _tasks=d.tasks||[];
    renderTasks();
  }}catch(e){{
    document.getElementById('tasks-body').innerHTML='<tr><td colspan="8" style="color:#ff5555;text-align:center;padding:16px">Error: '+_esc(e.message)+'</td></tr>';
  }}
}}

function renderTasks(){{
  const body=document.getElementById('tasks-body');
  if(!_tasks.length){{
    body.innerHTML='<tr><td colspan="8" style="text-align:center;color:#6b7394;padding:32px">No tasks yet. Click ＋ Add Task to get started.</td></tr>';
    return;
  }}
  body.innerHTML=_tasks.map(t=>`
    <tr id="row-${{t.id}}">
      <td style="font-weight:600;color:#d4d8e8">${{_esc(t.name)}}</td>
      <td><code style="color:#64ffda;font-size:11px">${{_esc(t.cron_expr)}}</code></td>
      <td style="max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${{_esc(t.query)}}">${{_esc(t.query.slice(0,60))}}</td>
      <td style="color:#6b7394">${{t.run_count||0}}</td>
      <td style="color:#6b7394;font-size:11px">${{t.last_run?t.last_run.slice(0,16).replace('T',' '):'Never'}}</td>
      <td style="color:#6b7394;font-size:11px">${{t.next_run?t.next_run.slice(0,16).replace('T',' '):'—'}}</td>
      <td>
        <label class="toggle-sw"><input type="checkbox" ${{t.enabled?'checked':''}} onchange="toggleTask(${{t.id}},this.checked)"><span class="toggle-slider"></span></label>
      </td>
      <td><button class="btn btn-danger btn-sm" onclick="deleteTask(${{t.id}})">✕</button></td>
    </tr>`).join('');
}}

async function toggleTask(id,enabled){{
  await fetch('/scheduler/toggle/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{enabled}})}});
  loadTasks();
}}

async function deleteTask(id){{
  if(!confirm('Delete this scheduled task?')) return;
  await fetch('/scheduler/'+id,{{method:'DELETE'}});
  _tasks=_tasks.filter(t=>t.id!==id);
  renderTasks();
}}

function openAddModal(){{document.getElementById('add-modal').classList.add('open');document.getElementById('add-name').focus();}}
function closeAddModal(){{document.getElementById('add-modal').classList.remove('open');['add-name','add-cron','add-query'].forEach(id=>document.getElementById(id).value='');document.getElementById('add-msg').textContent='';}}

async function submitAdd(){{
  const name=document.getElementById('add-name').value.trim();
  const cron=document.getElementById('add-cron').value.trim();
  const query=document.getElementById('add-query').value.trim();
  const tool=document.getElementById('add-tool').value;
  const msg=document.getElementById('add-msg');
  if(!name||!cron||!query){{msg.textContent='All starred fields are required.';return;}}
  try{{
    const d=await fetch('/scheduler',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,cron_expr:cron,query,tool_id:tool}})}}).then(r=>r.json());
    if(d.error){{msg.textContent='❌ '+d.error;return;}}
    closeAddModal();
    loadTasks();
  }}catch(e){{msg.textContent='Error: '+e.message;}}
}}

document.addEventListener('DOMContentLoaded',()=>{{loadTasks();setInterval(loadTasks,30000);}});
</script>
</body></html>"""
    return html


# ── Microsoft 365 Auth (device code flow via browser) ────────────────────────

# Shared state for the background device-flow thread
_ms365_flow_state: dict = {}   # keys: flow, status ("pending"/"connected"/"failed"), error

@app.route("/ms365/auth/status")
def ms365_auth_status():
    """Returns whether the user is authenticated with Microsoft 365."""
    try:
        from tools.ms365 import is_authenticated
        ok = is_authenticated()
    except Exception as e:
        ok = False
    return jsonify({"authenticated": ok})


@app.route("/ms365/auth/start", methods=["POST"])
def ms365_auth_start():
    """Initiate device code flow. Returns user_code + verification_uri."""
    import threading
    global _ms365_flow_state

    try:
        from tools.ms365 import start_device_flow, complete_device_flow
        flow = start_device_flow()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    _ms365_flow_state = {"status": "pending", "flow": flow, "error": None}

    def _bg():
        global _ms365_flow_state
        try:
            ok = complete_device_flow(flow)
            _ms365_flow_state["status"] = "connected" if ok else "failed"
            _ms365_flow_state["error"] = None if ok else "Sign-in timed out or was cancelled."
        except Exception as ex:
            _ms365_flow_state["status"] = "failed"
            _ms365_flow_state["error"] = str(ex)

    threading.Thread(target=_bg, daemon=True).start()

    return jsonify({
        "user_code":        flow.get("user_code"),
        "verification_uri": flow.get("verification_uri"),
        "expires_in":       flow.get("expires_in", 900),
    })


@app.route("/ms365/auth/poll")
def ms365_auth_poll():
    """Poll for device flow completion. Returns status: pending/connected/failed."""
    status  = _ms365_flow_state.get("status", "idle")
    error   = _ms365_flow_state.get("error")
    return jsonify({"status": status, "error": error})


@app.route("/ms365/auth/disconnect", methods=["POST"])
def ms365_auth_disconnect():
    """Remove the cached token (forces re-login next time)."""
    global _ms365_flow_state
    from tools.ms365 import clear_token_cache
    _ms365_flow_state = {}
    return jsonify(clear_token_cache())


# ── Email inbox page ──────────────────────────────────────────────────────────

@app.route("/inbox-page")
def inbox_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Email Inbox — Work Assistant</title>
{_PAGE_STYLE}
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">📧 Email Inbox</div>
      <div class="page-subtitle">Your recent emails — click to reply with a tone-matched draft</div>
    </div>
    <button class="btn btn-success" onclick="refreshInbox()">↻ Refresh</button>
  </div>

  <div id="inbox-list"><div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Loading emails…</div></div></div>
</div>

<!-- Draft modal injected by JS -->
<script>
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}

// Draft approval modal (inline, no external dependency)
function _injectDraftModal(){{
  if(document.getElementById('draft-modal')) return;
  const el=document.createElement('div');
  el.className='modal-overlay';el.id='draft-modal';
  el.onclick=e=>{{if(e.target===el)closeDraftModal();}};
  el.innerHTML=`
    <div style="background:#1a1c24;border:1px solid #2a2d3e;border-radius:10px;width:520px;max-width:96vw;padding:22px 24px;box-shadow:0 24px 64px rgba(0,0,0,.6);max-height:90vh;overflow-y:auto">
      <div style="font-size:14px;font-weight:700;color:#d4d8e8;margin-bottom:12px">✍️ Draft Reply</div>
      <label style="font-size:11px;color:#8892b0;display:block;margin-bottom:5px">Edit before sending:</label>
      <textarea id="draft-edit" rows="8" style="width:100%;background:#12141a;border:1px solid #2a2d3e;border-radius:5px;color:#d4d8e8;font-size:12.5px;padding:10px;outline:none;resize:vertical;font-family:inherit;line-height:1.6"></textarea>
      <div style="display:flex;gap:8px;margin-top:14px;justify-content:flex-end">
        <button onclick="closeDraftModal()" style="background:#252836;color:#8892b0;border:none;border-radius:5px;padding:8px 16px;cursor:pointer;font-size:12px">Cancel</button>
        <button onclick="navigator.clipboard.writeText(document.getElementById('draft-edit').value);document.getElementById('draft-copy-msg').textContent='✅ Copied!';" style="background:#1c2540;color:#64ffda;border:1px solid #2a4070;border-radius:5px;padding:8px 16px;cursor:pointer;font-size:12px;font-weight:600">📋 Copy</button>
      </div>
      <div id="draft-copy-msg" style="font-size:11px;color:#50fa7b;margin-top:8px;text-align:right"></div>
    </div>`;
  document.body.appendChild(el);
}}
function closeDraftModal(){{document.getElementById('draft-modal')?.classList.remove('open');}}

async function openDraftFor(emailBody){{
  _injectDraftModal();
  const modal=document.getElementById('draft-modal');
  const edit=document.getElementById('draft-edit');
  edit.value='Generating draft…';
  document.getElementById('draft-copy-msg').textContent='';
  modal.classList.add('open');
  try{{
    const r=await fetch('/draft-reply',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{email_body:emailBody}})}});
    const d=await r.json();
    edit.value=d.draft||d.error||'(empty)';
  }}catch(e){{edit.value='Error: '+e.message;}}
}}

let _emails=[];
let _authPollingInterval=null;

// ── Microsoft 365 auth flow ──────────────────────────────────────────────────
function _authBanner(){{
  return `<div style="background:#12141a;border:1px solid #2a3050;border-radius:10px;max-width:480px;margin:60px auto;padding:32px 36px;text-align:center">
    <div style="font-size:40px;margin-bottom:12px">🔐</div>
    <div style="font-size:16px;font-weight:700;color:#d4d8e8;margin-bottom:8px">Connect Microsoft 365</div>
    <div style="font-size:12px;color:#8892b0;margin-bottom:20px">Sign in to load your Outlook emails and calendar</div>
    <button id="ms365-connect-btn" class="btn btn-success" onclick="startMs365Auth()" style="padding:10px 28px;font-size:13px">🔗 Connect Outlook</button>
    <div id="ms365-code-box" style="display:none;margin-top:20px">
      <div style="font-size:11px;color:#8892b0;margin-bottom:8px">1. Open <a href="#" id="ms365-link" target="_blank" style="color:#64ffda">microsoft.com/devicelogin</a> in your browser</div>
      <div style="font-size:11px;color:#8892b0;margin-bottom:12px">2. Enter this code:</div>
      <div id="ms365-code" style="font-size:28px;font-weight:700;letter-spacing:4px;color:#64ffda;background:#1c2540;border-radius:8px;padding:14px 20px;display:inline-block;margin-bottom:14px">—</div>
      <div style="font-size:11px;color:#6b7394">Waiting for sign-in… <span id="ms365-spinner">⏳</span></div>
    </div>
    <div id="ms365-auth-err" style="color:#ff6b6b;font-size:11px;margin-top:10px;display:none"></div>
  </div>`;
}}

async function startMs365Auth(){{
  document.getElementById('ms365-connect-btn').disabled=true;
  document.getElementById('ms365-connect-btn').textContent='Starting…';
  try{{
    const r=await fetch('/ms365/auth/start',{{method:'POST'}}).then(r=>r.json());
    if(r.error){{showAuthErr(r.error);return;}}
    document.getElementById('ms365-code').textContent=r.user_code||'—';
    const link=document.getElementById('ms365-link');
    link.href=r.verification_uri||'https://microsoft.com/devicelogin';
    link.textContent=r.verification_uri||'microsoft.com/devicelogin';
    link.onclick=e=>{{e.preventDefault();window.open(r.verification_uri,'_blank');}};
    document.getElementById('ms365-code-box').style.display='block';
    document.getElementById('ms365-connect-btn').style.display='none';
    _authPollingInterval=setInterval(pollMs365Auth,3000);
  }}catch(e){{showAuthErr(e.message);}}
}}

async function pollMs365Auth(){{
  try{{
    const r=await fetch('/ms365/auth/poll').then(r=>r.json());
    if(r.status==='connected'){{
      clearInterval(_authPollingInterval);
      document.getElementById('ms365-spinner').textContent='✅';
      setTimeout(()=>refreshInbox(),800);
    }}else if(r.status==='failed'){{
      clearInterval(_authPollingInterval);
      showAuthErr(r.error||'Sign-in failed. Please try again.');
      document.getElementById('ms365-connect-btn').style.display='inline-block';
      document.getElementById('ms365-connect-btn').disabled=false;
      document.getElementById('ms365-connect-btn').textContent='🔗 Try Again';
    }}
  }}catch(e){{}}
}}

function showAuthErr(msg){{
  const el=document.getElementById('ms365-auth-err');
  if(el){{el.textContent=msg;el.style.display='block';}}
}}

async function refreshInbox(){{
  document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Checking Microsoft 365 connection…</div></div>';
  // Check auth first
  try{{
    const auth=await fetch('/ms365/auth/status').then(r=>r.json());
    if(!auth.authenticated){{
      document.getElementById('inbox-list').innerHTML=_authBanner();
      return;
    }}
  }}catch(e){{}}
  document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Loading emails…</div></div>';
  try{{
    const r=await fetch('/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:'List my 10 most recent unread emails with sender, subject, date, and a 2-sentence summary. Return as JSON array with fields: sender, subject, date, summary, body_preview.',tool_id:'outlook'}})}}).then(r=>r.json());
    if(r.error)throw new Error(r.error);
    let tries=0;
    const poll=async()=>{{
      const j=await fetch('/poll/'+r.job_id).then(r=>r.json());
      if(j.status==='done'){{renderEmailsFromText(j.response);return;}}
      if(j.status==='error'){{
        document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">'+_esc(j.response)+'</div></div>';
        return;
      }}
      if(++tries<60)setTimeout(poll,1000);
    }};
    setTimeout(poll,1000);
  }}catch(e){{
    document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">Error: '+_esc(e.message)+'</div></div>';
  }}
}}

function renderEmailsFromText(text){{
  // Try to parse JSON from agent response
  const el=document.getElementById('inbox-list');
  try{{
    const match=text.match(/\[[\s\S]+\]/);
    if(match){{
      const emails=JSON.parse(match[0]);
      _emails=emails;
      el.innerHTML=emails.map((e,i)=>`
        <div class="card">
          <div class="card-row">
            <div class="card-body">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
                <div style="font-weight:600;color:#d4d8e8;font-size:13px">${{_esc(e.subject||'(no subject)')}}</div>
                <div style="font-size:10px;color:#6b7394;white-space:nowrap;margin-left:12px">${{_esc(e.date||'')}}</div>
              </div>
              <div style="font-size:11px;color:#8892b0;margin-bottom:8px">From: ${{_esc(e.sender||'')}}</div>
              <div style="font-size:12px;color:#a8b0c8;line-height:1.5">${{_esc(e.summary||e.body_preview||'')}}</div>
            </div>
            <div class="card-actions" style="margin-left:12px">
              <button class="btn btn-success btn-sm" onclick="openDraftFor(_emails[${{i}}].body_preview||_emails[${{i}}].summary||'')">✍️ Reply</button>
            </div>
          </div>
        </div>`).join('');
      return;
    }}
  }}catch(e){{}}
  // Fallback: show raw text
  el.innerHTML=`<div class="card"><div class="card-body"><div class="mbody" style="white-space:pre-wrap;font-size:12px;color:#d4d8e8">${{_esc(text)}}</div></div></div>`;
}}

document.addEventListener('DOMContentLoaded',refreshInbox);
</script>
</body></html>"""
    return html


# ── Calendar week view page ───────────────────────────────────────────────────

@app.route("/calendar-page")
def calendar_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calendar — Work Assistant</title>
{_PAGE_STYLE}
<style>
.cal-grid{{display:grid;grid-template-columns:60px repeat(7,1fr);gap:0;border:1px solid #252836;border-radius:8px;overflow:hidden}}
.cal-head{{background:#1a1c24;padding:10px 6px;text-align:center;font-size:11px;font-weight:700;color:#8892b0;border-bottom:1px solid #252836}}
.cal-head.today{{color:#64ffda;background:#1c2540}}
.cal-time{{background:#1a1c24;padding:4px 6px;text-align:right;font-size:10px;color:#3a4060;border-bottom:1px solid #1e2028;border-right:1px solid #252836}}
.cal-cell{{border-bottom:1px solid #1e2028;border-right:1px solid #252836;min-height:40px;padding:2px;position:relative}}
.cal-cell:last-child{{border-right:none}}
.cal-event{{background:#1c2540;border-left:3px solid #64ffda;border-radius:3px;padding:3px 5px;font-size:10px;color:#d4d8e8;margin-bottom:2px;cursor:default;line-height:1.3}}
.cal-event:hover{{background:#22304a}}
</style>
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">📅 Calendar</div>
      <div class="page-subtitle" id="week-label">This week</div>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836" onclick="changeWeek(-1)">← Prev</button>
      <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836" onclick="changeWeek(0)">Today</button>
      <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836" onclick="changeWeek(1)">Next →</button>
      <button class="btn btn-success" onclick="refreshCalendar()">↻ Load</button>
    </div>
  </div>

  <div id="cal-wrap">
    <div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Loading calendar…</div></div>
  </div>
</div>

<script>
function _esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}

let _weekOffset=0;
let _events=[];

function getWeekDates(offset){{
  const now=new Date();
  const monday=new Date(now);
  const dow=now.getDay()||7;
  monday.setDate(now.getDate()-dow+1+(offset*7));
  return Array.from({{length:7}},(_,i)=>{{
    const d=new Date(monday);d.setDate(monday.getDate()+i);return d;
  }});
}}

const DAYS=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
const HOURS=Array.from({{length:16}},(_,i)=>i+7); // 7am-10pm

function renderCalendar(days,events){{
  const today=new Date().toDateString();
  const first=days[0];
  const last=days[6];
  const fmt=d=>`${{d.getMonth()+1}}/${{d.getDate()}}`;
  document.getElementById('week-label').textContent=`${{fmt(first)}} – ${{fmt(last)}}`;

  let grid=`<div class="cal-grid">`;
  // Headers
  grid+=`<div class="cal-head"></div>`;
  days.forEach((d,i)=>{{
    const isTd=d.toDateString()===today;
    grid+=`<div class="cal-head${{isTd?' today':''}}">${{DAYS[i]}}<br><span style="font-size:13px">${{d.getDate()}}</span></div>`;
  }});
  // Hour rows
  HOURS.forEach(h=>{{
    grid+=`<div class="cal-time">${{h}}:00</div>`;
    days.forEach(d=>{{
      const ds=d.toISOString().slice(0,10);
      const dayEvts=events.filter(e=>{{
        if(!e.start)return false;
        const eDate=e.start.slice(0,10);
        const eHour=parseInt(e.start.slice(11,13)||'0');
        return eDate===ds&&eHour===h;
      }});
      grid+=`<div class="cal-cell">${{dayEvts.map(e=>`<div class="cal-event" title="${{_esc(e.subject||'')}} — ${{_esc(e.organizer||'')}}">${{_esc((e.subject||'Event').slice(0,25))}}</div>`).join('')}}</div>`;
    }});
  }});
  grid+='</div>';
  document.getElementById('cal-wrap').innerHTML=grid;
}}

function changeWeek(delta){{
  _weekOffset=delta===0?0:_weekOffset+delta;
  renderCalendar(getWeekDates(_weekOffset),_events);
  if(delta===0||_events.length===0)refreshCalendar();
}}

// ── Microsoft 365 auth flow (calendar page) ─────────────────────────────────
let _calAuthPolling=null;

function _calAuthBanner(){{
  return `<div style="background:#12141a;border:1px solid #2a3050;border-radius:10px;max-width:480px;margin:40px auto;padding:32px 36px;text-align:center">
    <div style="font-size:40px;margin-bottom:12px">🔐</div>
    <div style="font-size:16px;font-weight:700;color:#d4d8e8;margin-bottom:8px">Connect Microsoft 365</div>
    <div style="font-size:12px;color:#8892b0;margin-bottom:20px">Sign in to load your Outlook calendar</div>
    <button id="cal-connect-btn" class="btn btn-success" onclick="startCalAuth()" style="padding:10px 28px;font-size:13px">🔗 Connect Outlook</button>
    <div id="cal-code-box" style="display:none;margin-top:20px">
      <div style="font-size:11px;color:#8892b0;margin-bottom:8px">1. Open <a id="cal-ms-link" href="#" target="_blank" style="color:#64ffda">microsoft.com/devicelogin</a></div>
      <div style="font-size:11px;color:#8892b0;margin-bottom:12px">2. Enter this code:</div>
      <div id="cal-code" style="font-size:28px;font-weight:700;letter-spacing:4px;color:#64ffda;background:#1c2540;border-radius:8px;padding:14px 20px;display:inline-block;margin-bottom:14px">—</div>
      <div style="font-size:11px;color:#6b7394">Waiting for sign-in… <span id="cal-spinner">⏳</span></div>
    </div>
    <div id="cal-auth-err" style="color:#ff6b6b;font-size:11px;margin-top:10px;display:none"></div>
  </div>`;
}}

async function startCalAuth(){{
  document.getElementById('cal-connect-btn').disabled=true;
  document.getElementById('cal-connect-btn').textContent='Starting…';
  try{{
    const r=await fetch('/ms365/auth/start',{{method:'POST'}}).then(r=>r.json());
    if(r.error){{document.getElementById('cal-auth-err').textContent=r.error;document.getElementById('cal-auth-err').style.display='block';return;}}
    document.getElementById('cal-code').textContent=r.user_code||'—';
    const link=document.getElementById('cal-ms-link');
    link.href=r.verification_uri||'https://microsoft.com/devicelogin';
    link.onclick=e=>{{e.preventDefault();window.open(r.verification_uri,'_blank');}};
    document.getElementById('cal-code-box').style.display='block';
    document.getElementById('cal-connect-btn').style.display='none';
    _calAuthPolling=setInterval(async()=>{{
      const s=await fetch('/ms365/auth/poll').then(r=>r.json());
      if(s.status==='connected'){{clearInterval(_calAuthPolling);document.getElementById('cal-spinner').textContent='✅';setTimeout(()=>refreshCalendar(),800);}}
      else if(s.status==='failed'){{clearInterval(_calAuthPolling);document.getElementById('cal-auth-err').textContent=s.error||'Sign-in failed.';document.getElementById('cal-auth-err').style.display='block';}}
    }},3000);
  }}catch(e){{document.getElementById('cal-auth-err').textContent=e.message;document.getElementById('cal-auth-err').style.display='block';}}
}}

async function refreshCalendar(){{
  const days=getWeekDates(_weekOffset);
  renderCalendar(days,[]);
  // Check auth first
  try{{
    const auth=await fetch('/ms365/auth/status').then(r=>r.json());
    if(!auth.authenticated){{
      document.getElementById('cal-wrap').innerHTML=_calAuthBanner();
      return;
    }}
  }}catch(e){{}}
  try{{
    const r=await fetch('/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:'List all my calendar events for this week. Return JSON array with fields: subject, start (ISO datetime), end (ISO datetime), organizer.',tool_id:'outlook'}})}}).then(r=>r.json());
    if(r.error)throw new Error(r.error);
    let tries=0;
    const poll=async()=>{{
      const j=await fetch('/poll/'+r.job_id).then(r=>r.json());
      if(j.status==='done'){{
        try{{
          const match=j.response.match(/\[[\s\S]+?\]/);
          if(match){{_events=JSON.parse(match[0]);renderCalendar(getWeekDates(_weekOffset),_events);return;}}
        }}catch(e){{}}
        document.getElementById('cal-wrap').innerHTML='<div class="card"><div class="card-body"><div style="white-space:pre-wrap;font-size:12px;color:#d4d8e8">'+_esc(j.response)+'</div></div></div>';
        return;
      }}
      if(j.status==='error'){{document.getElementById('cal-wrap').innerHTML='<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">'+_esc(j.response)+'</div></div>';return;}}
      if(++tries<60)setTimeout(poll,1000);
    }};
    setTimeout(poll,1000);
  }}catch(e){{
    document.getElementById('cal-wrap').innerHTML='<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">Error: '+_esc(e.message)+'</div></div>';
  }}
}}

document.addEventListener('DOMContentLoaded',()=>{{
  renderCalendar(getWeekDates(0),[]);
  refreshCalendar();
}});
</script>
</body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# DOCUMENTS LIBRARY
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/documents")
def api_documents():
    doc_type = request.args.get("type")
    try:
        from tools import doc_creator
        docs = doc_creator.list_documents(doc_type=doc_type or None)
        return jsonify({"documents": docs})
    except Exception as e:
        return jsonify({"documents": [], "error": str(e)})


@app.route("/documents/<int:doc_id>", methods=["DELETE"])
def api_delete_document(doc_id):
    try:
        from tools import doc_creator
        result = doc_creator.delete_document(doc_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/documents-page")
def documents_page():
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Documents — Work Assistant</title>
{_PAGE_STYLE}
<style>
.doc-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;margin-top:4px}}
.doc-card{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:10px;transition:border-color .2s,box-shadow .2s}}
.doc-card:hover{{border-color:#3a4060;box-shadow:0 4px 20px rgba(0,0,0,.4)}}
.doc-icon{{font-size:32px;line-height:1}}
.doc-name{{font-size:13px;font-weight:700;color:#d4d8e8;word-break:break-word}}
.doc-meta{{font-size:11px;color:#8892b0;line-height:1.7}}
.doc-badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:10px;font-weight:700;letter-spacing:.5px}}
.badge-docx{{background:#1c2540;color:#64ffda;border:1px solid #243060}}
.badge-pptx{{background:#2a1f3a;color:#bd93f9;border:1px solid #3a2a5a}}
.doc-actions{{display:flex;gap:8px;margin-top:auto}}
.btn-open{{flex:1;padding:6px 0;border-radius:6px;border:none;background:#1c2540;color:#64ffda;font-size:12px;cursor:pointer;font-weight:600}}
.btn-open:hover{{background:#22304a}}
.btn-del{{padding:6px 10px;border-radius:6px;border:none;background:#1e1e2a;color:#ff5555;font-size:12px;cursor:pointer}}
.btn-del:hover{{background:#2a1e1e}}
.empty-state{{text-align:center;padding:80px 20px;color:#8892b0}}
.empty-state .es-icon{{font-size:48px;margin-bottom:12px}}
.empty-state h3{{color:#d4d8e8;margin:0 0 8px}}
.filter-tabs{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.ftab{{padding:6px 14px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.ftab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.doc-stats{{display:flex;gap:12px;margin-bottom:8px;flex-wrap:wrap}}
.dstat{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:10px 18px;text-align:center;min-width:100px}}
.dstat-num{{font-size:22px;font-weight:800;color:#64ffda}}
.dstat-lbl{{font-size:11px;color:#8892b0;margin-top:2px}}
</style>
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">📄 Document Library</div>
      <div class="page-subtitle">Word documents and PowerPoint presentations created by the agent</div>
    </div>
    <button class="btn btn-primary" onclick="window.location='/'">＋ Create in Chat</button>
  </div>

  <div class="doc-stats">
    <div class="dstat"><div class="dstat-num" id="stat-total">—</div><div class="dstat-lbl">Total</div></div>
    <div class="dstat"><div class="dstat-num" id="stat-docx" style="color:#64ffda">—</div><div class="dstat-lbl">Word Docs</div></div>
    <div class="dstat"><div class="dstat-num" id="stat-pptx" style="color:#bd93f9">—</div><div class="dstat-lbl">Presentations</div></div>
    <div class="dstat"><div class="dstat-num" id="stat-size">—</div><div class="dstat-lbl">Total Size</div></div>
  </div>

  <div class="filter-tabs">
    <button class="ftab active" data-f="all" onclick="setFilter('all',this)">All</button>
    <button class="ftab" data-f="docx" onclick="setFilter('docx',this)">📄 Word</button>
    <button class="ftab" data-f="pptx" onclick="setFilter('pptx',this)">📊 PowerPoint</button>
  </div>

  <div class="doc-grid" id="doc-grid">
    <div class="empty-state"><div class="es-icon">⏳</div><h3>Loading…</h3></div>
  </div>
</div>

<script>
let _allDocs = [];
let _filter  = 'all';

async function loadDocs() {{
  try {{
    const r = await fetch('/documents');
    const d = await r.json();
    _allDocs = d.documents || [];
    renderStats();
    renderGrid();
  }} catch(e) {{
    document.getElementById('doc-grid').innerHTML =
      `<div class="empty-state"><div class="es-icon">❌</div><h3>Failed to load</h3><p>${{e.message}}</p></div>`;
  }}
}}

function renderStats() {{
  const docx = _allDocs.filter(d=>d.doc_type==='docx');
  const pptx = _allDocs.filter(d=>d.doc_type==='pptx');
  const totalBytes = _allDocs.reduce((s,d)=>s+(d.size_bytes||0),0);
  document.getElementById('stat-total').textContent = _allDocs.length;
  document.getElementById('stat-docx').textContent  = docx.length;
  document.getElementById('stat-pptx').textContent  = pptx.length;
  document.getElementById('stat-size').textContent  = fmtBytes(totalBytes);
}}

function fmtBytes(b) {{
  if(b<1024) return b+'B';
  if(b<1048576) return (b/1024).toFixed(1)+'KB';
  return (b/1048576).toFixed(1)+'MB';
}}

function fmtDate(s) {{
  if(!s) return '';
  const d = new Date(s);
  return d.toLocaleDateString('en-GB',{{day:'2-digit',month:'short',year:'numeric'}});
}}

function setFilter(f, el) {{
  _filter = f;
  document.querySelectorAll('.ftab').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  renderGrid();
}}

function renderGrid() {{
  const docs = _filter==='all' ? _allDocs : _allDocs.filter(d=>d.doc_type===_filter);
  const grid = document.getElementById('doc-grid');
  if(!docs.length) {{
    const msg = _filter==='all'
      ? '<h3>No documents yet</h3><p>Ask the agent to create a Word document or presentation.</p>'
      : `<h3>No ${{_filter==='docx'?'Word documents':'presentations'}} yet</h3>`;
    grid.innerHTML = `<div class="empty-state"><div class="es-icon">📂</div>${{msg}}</div>`;
    return;
  }}
  grid.innerHTML = docs.map(doc => {{
    const icon  = doc.doc_type==='pptx' ? '📊' : '📄';
    const badge = doc.doc_type==='pptx'
      ? '<span class="doc-badge badge-pptx">PPTX</span>'
      : '<span class="doc-badge badge-docx">DOCX</span>';
    const extra = doc.doc_type==='pptx'
      ? (doc.slide_count ? `<span>🖼 ${{doc.slide_count}} slides</span>` : '')
      : (doc.page_count  ? `<span>📃 ${{doc.page_count}} pages</span>` : '');
    return `
    <div class="doc-card" id="card-${{doc.id}}">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:8px">
        <div class="doc-icon">${{icon}}</div>
        ${{badge}}
      </div>
      <div class="doc-name">${{escHtml(doc.title)}}</div>
      <div class="doc-meta">
        <span>📁 ${{escHtml(doc.filename)}}</span><br>
        <span>📅 ${{fmtDate(doc.created_at)}}</span>
        ${{doc.size_bytes ? `&nbsp;·&nbsp;<span>${{fmtBytes(doc.size_bytes)}}</span>` : ''}}
        ${{extra ? `<br>${{extra}}` : ''}}
      </div>
      <div class="doc-actions">
        <button class="btn-open" onclick="openDoc(${{doc.id}}, '${{escAttr(doc.filepath)}}')">📂 Open File</button>
        <button class="btn-del" onclick="deleteDoc(${{doc.id}})" title="Delete">🗑</button>
      </div>
    </div>`;
  }}).join('');
}}

function escHtml(s) {{
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}
function escAttr(s) {{
  return String(s||'').replace(/'/g,"\\'");
}}

async function openDoc(id, filepath) {{
  // Use fetch to get the system path and open it via the OS open command
  try {{
    const r = await fetch('/document-open', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{id}}) }});
    const d = await r.json();
    if(d.status!=='ok') alert('Could not open file: '+d.message);
  }} catch(e) {{
    alert('Could not open: '+e.message);
  }}
}}

async function deleteDoc(id) {{
  if(!confirm('Delete this document? This cannot be undone.')) return;
  const r = await fetch('/documents/'+id, {{method:'DELETE'}});
  const d = await r.json();
  if(d.status==='deleted') {{
    _allDocs = _allDocs.filter(x=>x.id!==id);
    renderStats();
    renderGrid();
  }} else {{
    alert('Delete failed: '+(d.message||'unknown error'));
  }}
}}

loadDocs();
</script>
</body></html>"""
    return html


@app.route("/document-open", methods=["POST"])
def api_open_document():
    """Open a document with the OS default application."""
    import subprocess
    data = request.get_json() or {}
    doc_id = data.get("id")
    try:
        from tools import doc_creator
        path = doc_creator.get_document_path(doc_id)
        if not path:
            return jsonify({"status": "error", "message": "Document not found"})
        subprocess.Popen(["open", path])  # macOS; works for .docx and .pptx
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# GITHUB DASHBOARD — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/github/prs")
def api_github_prs():
    try:
        from tools import github_tool
        return jsonify({"prs": github_tool.get_my_open_prs(max_count=20)})
    except Exception as e:
        return jsonify({"prs": [], "error": str(e)})

@app.route("/github/notifications")
def api_github_notifications():
    try:
        from tools import github_tool
        return jsonify({"notifications": github_tool.get_github_notifications(unread_only=True, max_count=30)})
    except Exception as e:
        return jsonify({"notifications": [], "error": str(e)})

@app.route("/github/reviews")
def api_github_reviews():
    try:
        from tools import github_tool
        return jsonify({"reviews": github_tool.get_my_review_requests(max_count=20)})
    except Exception as e:
        return jsonify({"reviews": [], "error": str(e)})

@app.route("/github/issues")
def api_github_issues():
    try:
        from tools import github_tool
        return jsonify({"issues": github_tool.list_my_github_issues(max_count=20)})
    except Exception as e:
        return jsonify({"issues": [], "error": str(e)})

@app.route("/github-page")
def github_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GitHub — Work Assistant</title>{_PAGE_STYLE}
<style>
.gh-tab-bar{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
.gh-tab{{padding:7px 16px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.gh-tab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.gh-badge{{display:inline-block;background:#ff5555;color:#fff;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:5px}}
.pr-item{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:14px 16px;margin-bottom:8px;display:flex;align-items:flex-start;gap:12px}}
.pr-item:hover{{border-color:#3a4060}}
.pr-icon{{font-size:18px;flex-shrink:0;margin-top:2px}}
.pr-body{{flex:1;min-width:0}}
.pr-title{{font-size:13px;font-weight:600;color:#d4d8e8;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pr-meta{{font-size:11px;color:#8892b0;display:flex;gap:10px;flex-wrap:wrap}}
.state-open{{color:#50fa7b}}.state-closed{{color:#ff5555}}.state-merged{{color:#bd93f9}}
.notif-item{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:6px;display:flex;gap:10px;align-items:flex-start}}
.notif-item:hover{{border-color:#3a4060}}
.notif-body{{flex:1;min-width:0}}
.notif-title{{font-size:12.5px;color:#d4d8e8;margin-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.notif-sub{{font-size:11px;color:#8892b0}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">🐙 GitHub</div><div class="page-subtitle">Pull requests, reviews, notifications and issues</div></div>
    <button class="btn btn-primary" onclick="loadAll()">↻ Refresh</button>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="s-prs">—</div><div class="stat-lbl">Open PRs</div></div>
    <div class="stat-card"><div class="stat-num" id="s-rev" style="color:#ffb86c">—</div><div class="stat-lbl">Review Requests</div></div>
    <div class="stat-card"><div class="stat-num" id="s-notif" style="color:#ff5555">—</div><div class="stat-lbl">Notifications</div></div>
    <div class="stat-card"><div class="stat-num" id="s-issues" style="color:#bd93f9">—</div><div class="stat-lbl">My Issues</div></div>
  </div>
  <div class="gh-tab-bar">
    <button class="gh-tab active" onclick="showTab('prs',this)">🔀 My PRs <span class="gh-badge" id="b-prs">…</span></button>
    <button class="gh-tab" onclick="showTab('reviews',this)">👁 Reviews <span class="gh-badge" id="b-rev">…</span></button>
    <button class="gh-tab" onclick="showTab('notifications',this)">🔔 Notifications <span class="gh-badge" id="b-notif">…</span></button>
    <button class="gh-tab" onclick="showTab('issues',this)">🐛 Issues <span class="gh-badge" id="b-issues">…</span></button>
  </div>
  <div id="tab-prs"></div>
  <div id="tab-reviews" style="display:none"></div>
  <div id="tab-notifications" style="display:none"></div>
  <div id="tab-issues" style="display:none"></div>
</div>
<script>
let _data = {{prs:[],reviews:[],notifications:[],issues:[]}};
function showTab(name,el){{
  ['prs','reviews','notifications','issues'].forEach(t=>{{
    document.getElementById('tab-'+t).style.display='none';
  }});
  document.querySelectorAll('.gh-tab').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).style.display='';
  el.classList.add('active');
}}
function prCard(p){{
  const state=p.state||'open';
  const cls='state-'+state;
  const repo=(p.repo||'').split('/').pop()||p.repo||'';
  return `<div class="pr-item"><div class="pr-icon">🔀</div><div class="pr-body">
    <div class="pr-title" title="${{escH(p.title||'')}}">${{escH(p.title||'Untitled')}}</div>
    <div class="pr-meta">
      <span>${{escH(repo)}}</span>
      <span class="${{cls}}">● ${{state}}</span>
      ${{p.number?`<span>#${{p.number}}</span>`:''}}
      ${{p.created_at?`<span>📅 ${{fmtDate(p.created_at)}}</span>`:''}}
    </div>
  </div></div>`;
}}
function notifCard(n){{
  const icon = n.type==='PullRequest'?'🔀':n.type==='Issue'?'🐛':n.type==='Release'?'🚀':'🔔';
  return `<div class="notif-item"><div style="font-size:18px;flex-shrink:0">${{icon}}</div><div class="notif-body">
    <div class="notif-title" title="${{escH(n.title||'')}}">${{escH(n.title||'')}}</div>
    <div class="notif-sub">${{escH(n.repo||'')}}&nbsp;·&nbsp;${{n.type||''}}&nbsp;·&nbsp;${{fmtDate(n.updated_at||'')}}</div>
  </div></div>`;
}}
function issueCard(i){{
  return `<div class="pr-item"><div class="pr-icon">🐛</div><div class="pr-body">
    <div class="pr-title">${{escH(i.title||'')}}</div>
    <div class="pr-meta">
      <span>${{escH(i.repo||'')}}</span>
      ${{i.number?`<span>#${{i.number}}</span>`:''}}
      ${{i.state?`<span class="state-${{i.state}}">● ${{i.state}}</span>`:''}}
      ${{i.labels&&i.labels.length?i.labels.slice(0,3).map(l=>`<span style="color:#bd93f9">${{escH(l)}}</span>`).join(''):''}}
    </div>
  </div></div>`;
}}
function renderList(containerId, items, cardFn){{
  const el=document.getElementById(containerId);
  el.innerHTML=items.length?items.map(cardFn).join(''):'<div class="empty-msg">Nothing here ✓</div>';
}}
async function loadAll(){{
  const endpoints=[
    ['/github/prs','prs','s-prs','b-prs',prCard,'tab-prs'],
    ['/github/reviews','reviews','s-rev','b-rev',prCard,'tab-reviews'],
    ['/github/notifications','notifications','s-notif','b-notif',notifCard,'tab-notifications'],
    ['/github/issues','issues','s-issues','b-issues',issueCard,'tab-issues'],
  ];
  for(const [url,key,sid,bid,cardFn,tabId] of endpoints){{
    try{{
      const r=await fetch(url); const d=await r.json();
      const items=d[key]||[];
      _data[key]=items;
      document.getElementById(sid).textContent=items.length;
      document.getElementById(bid).textContent=items.length;
      renderList(tabId,items,cardFn);
    }}catch(e){{
      document.getElementById(tabId).innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;
    }}
  }}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fmtDate(s){{if(!s)return'';const d=new Date(s);return d.toLocaleDateString('en-GB',{{day:'2-digit',month:'short'}});}}
loadAll();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# JIRA / CONFLUENCE — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/jira/issues")
def api_jira_issues():
    status = request.args.get("status")
    try:
        from tools import atlassian
        return jsonify({"issues": atlassian.get_my_jira_issues(max_results=30, status=status or None)})
    except Exception as e:
        return jsonify({"issues": [], "error": str(e)})

@app.route("/jira/projects")
def api_jira_projects():
    try:
        from tools import atlassian
        return jsonify({"projects": atlassian.get_jira_projects()})
    except Exception as e:
        return jsonify({"projects": [], "error": str(e)})

@app.route("/confluence/search")
def api_confluence_search():
    q = request.args.get("q", "")
    try:
        from tools import atlassian
        return jsonify({"pages": atlassian.search_confluence(q, max_results=15)})
    except Exception as e:
        return jsonify({"pages": [], "error": str(e)})

@app.route("/jira-page")
def jira_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jira — Work Assistant</title>{_PAGE_STYLE}
<style>
.jtab-bar{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
.jtab{{padding:7px 16px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.jtab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.issue-row{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:7px;display:flex;gap:10px;align-items:flex-start}}
.issue-row:hover{{border-color:#3a4060}}
.issue-key{{font-size:11px;font-weight:700;color:#64ffda;flex-shrink:0;min-width:80px;padding-top:2px}}
.issue-title{{font-size:13px;color:#d4d8e8;flex:1;min-width:0}}
.issue-meta{{font-size:11px;color:#8892b0;margin-top:4px;display:flex;gap:8px;flex-wrap:wrap}}
.prio-highest{{color:#ff5555}}.prio-high{{color:#ffb86c}}.prio-medium{{color:#f1fa8c}}.prio-low{{color:#8892b0}}
.proj-card{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:14px;display:flex;gap:10px;align-items:center}}
.proj-card:hover{{border-color:#3a4060}}
.conf-item{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:7px}}
.conf-item:hover{{border-color:#3a4060}}
.conf-title{{font-size:13px;color:#d4d8e8;margin-bottom:4px}}
.conf-meta{{font-size:11px;color:#8892b0}}
.search-bar{{display:flex;gap:8px;margin-bottom:14px}}
.search-bar input{{flex:1;background:#1a1c24;border:1px solid #252836;border-radius:6px;padding:8px 12px;color:#d4d8e8;font-size:13px}}
.search-bar input:focus{{outline:none;border-color:#64ffda}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">📋 Jira / Confluence</div><div class="page-subtitle">Issues, projects and knowledge pages</div></div>
    <button class="btn btn-primary" onclick="loadAll()">↻ Refresh</button>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="s-open">—</div><div class="stat-lbl">My Open</div></div>
    <div class="stat-card"><div class="stat-num" id="s-inprog" style="color:#ffb86c">—</div><div class="stat-lbl">In Progress</div></div>
    <div class="stat-card"><div class="stat-num" id="s-proj" style="color:#64ffda">—</div><div class="stat-lbl">Projects</div></div>
  </div>
  <div class="jtab-bar">
    <button class="jtab active" onclick="showJTab('issues',this)">🐛 My Issues</button>
    <button class="jtab" onclick="showJTab('projects',this)">📁 Projects</button>
    <button class="jtab" onclick="showJTab('confluence',this)">📖 Confluence</button>
  </div>
  <div id="jtab-issues"></div>
  <div id="jtab-projects" style="display:none"></div>
  <div id="jtab-confluence" style="display:none">
    <div class="search-bar">
      <input id="conf-q" placeholder="Search Confluence…" onkeydown="if(event.key==='Enter')searchConf()">
      <button class="btn btn-primary" onclick="searchConf()">Search</button>
    </div>
    <div id="conf-results"></div>
  </div>
</div>
<script>
function showJTab(name,el){{
  ['issues','projects','confluence'].forEach(t=>document.getElementById('jtab-'+t).style.display='none');
  document.querySelectorAll('.jtab').forEach(b=>b.classList.remove('active'));
  document.getElementById('jtab-'+name).style.display='';
  el.classList.add('active');
}}
function prioClass(p){{
  const m={{Highest:'prio-highest',High:'prio-high',Medium:'prio-medium',Low:'prio-low'}};
  return m[p]||'prio-low';
}}
function issueRow(i){{
  return `<div class="issue-row">
    <div class="issue-key">${{escH(i.key||'')}}</div>
    <div style="flex:1;min-width:0">
      <div class="issue-title">${{escH(i.summary||i.title||'')}}</div>
      <div class="issue-meta">
        <span>${{escH(i.status||'')}}</span>
        ${{i.priority?`<span class="${{prioClass(i.priority)}}">${{escH(i.priority)}}</span>`:''}}
        ${{i.type?`<span>${{escH(i.type)}}</span>`:''}}
        ${{i.project?`<span>${{escH(i.project)}}</span>`:''}}
      </div>
    </div>
  </div>`;
}}
function projCard(p){{
  return `<div class="proj-card" style="margin-bottom:7px">
    <div style="font-size:20px">📁</div>
    <div><div style="font-size:13px;font-weight:600;color:#d4d8e8">${{escH(p.name||'')}}</div>
    <div style="font-size:11px;color:#8892b0">${{escH(p.key||'')}}&nbsp;·&nbsp;${{escH(p.type||'')}}</div></div>
  </div>`;
}}
async function loadAll(){{
  // Issues
  try{{
    const r=await fetch('/jira/issues'); const d=await r.json();
    const issues=d.issues||[];
    const open=issues.filter(i=>i.status&&!['Done','Closed','Resolved'].includes(i.status));
    const inprog=issues.filter(i=>i.status&&i.status.toLowerCase().includes('progress'));
    document.getElementById('s-open').textContent=open.length;
    document.getElementById('s-inprog').textContent=inprog.length;
    document.getElementById('jtab-issues').innerHTML=issues.length?issues.map(issueRow).join(''):'<div class="empty-msg">No issues assigned ✓</div>';
  }}catch(e){{document.getElementById('jtab-issues').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
  // Projects
  try{{
    const r=await fetch('/jira/projects'); const d=await r.json();
    const projs=d.projects||[];
    document.getElementById('s-proj').textContent=projs.length;
    document.getElementById('jtab-projects').innerHTML=projs.length?projs.map(projCard).join(''):'<div class="empty-msg">No projects found</div>';
  }}catch(e){{document.getElementById('jtab-projects').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function searchConf(){{
  const q=document.getElementById('conf-q').value.trim();
  if(!q)return;
  document.getElementById('conf-results').innerHTML='<div class="empty-msg">Searching…</div>';
  try{{
    const r=await fetch('/confluence/search?q='+encodeURIComponent(q)); const d=await r.json();
    const pages=d.pages||[];
    document.getElementById('conf-results').innerHTML=pages.length?pages.map(p=>`
      <div class="conf-item">
        <div class="conf-title">${{escH(p.title||'')}}</div>
        <div class="conf-meta">${{escH(p.space||'')}}&nbsp;·&nbsp;${{escH(p.last_modified||'')}}</div>
      </div>`).join(''):'<div class="empty-msg">No pages found</div>';
  }}catch(e){{document.getElementById('conf-results').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadAll();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# LINEAR — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/linear/issues")
def api_linear_issues():
    state = request.args.get("state")
    try:
        from tools import linear_tool
        return jsonify({"issues": linear_tool.get_my_linear_issues(state_type=state or None, max_count=30)})
    except Exception as e:
        return jsonify({"issues": [], "error": str(e)})

@app.route("/linear/teams")
def api_linear_teams():
    try:
        from tools import linear_tool
        return jsonify({"teams": linear_tool.list_linear_teams()})
    except Exception as e:
        return jsonify({"teams": [], "error": str(e)})

@app.route("/linear/projects")
def api_linear_projects():
    try:
        from tools import linear_tool
        return jsonify({"projects": linear_tool.list_linear_projects()})
    except Exception as e:
        return jsonify({"projects": [], "error": str(e)})

@app.route("/linear-page")
def linear_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Linear — Work Assistant</title>{_PAGE_STYLE}
<style>
.ltab-bar{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
.ltab{{padding:7px 16px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.ltab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.li-row{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:7px;display:flex;gap:10px;align-items:flex-start}}
.li-row:hover{{border-color:#3a4060}}
.li-id{{font-size:11px;color:#8892b0;flex-shrink:0;min-width:60px;padding-top:2px}}
.li-title{{font-size:13px;color:#d4d8e8;flex:1;min-width:0}}
.li-meta{{font-size:11px;color:#8892b0;margin-top:4px;display:flex;gap:8px;flex-wrap:wrap}}
.prio-urgent{{color:#ff5555}}.prio-high{{color:#ffb86c}}.prio-medium{{color:#f1fa8c}}.prio-low{{color:#8892b0}}
.state-pill{{padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;background:#1c2540;color:#64ffda}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">⚡ Linear</div><div class="page-subtitle">Issues, teams and projects</div></div>
    <button class="btn btn-primary" onclick="loadAll()">↻ Refresh</button>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="s-total">—</div><div class="stat-lbl">My Issues</div></div>
    <div class="stat-card"><div class="stat-num" id="s-inprog" style="color:#ffb86c">—</div><div class="stat-lbl">In Progress</div></div>
    <div class="stat-card"><div class="stat-num" id="s-todo" style="color:#64ffda">—</div><div class="stat-lbl">To Do</div></div>
    <div class="stat-card"><div class="stat-num" id="s-teams" style="color:#bd93f9">—</div><div class="stat-lbl">Teams</div></div>
  </div>
  <div class="ltab-bar">
    <button class="ltab active" onclick="showLTab('issues',this)">📋 My Issues</button>
    <button class="ltab" onclick="showLTab('teams',this)">👥 Teams</button>
    <button class="ltab" onclick="showLTab('projects',this)">🗂 Projects</button>
  </div>
  <div id="ltab-issues"></div>
  <div id="ltab-teams" style="display:none"></div>
  <div id="ltab-projects" style="display:none"></div>
</div>
<script>
function showLTab(name,el){{
  ['issues','teams','projects'].forEach(t=>document.getElementById('ltab-'+t).style.display='none');
  document.querySelectorAll('.ltab').forEach(b=>b.classList.remove('active'));
  document.getElementById('ltab-'+name).style.display='';
  el.classList.add('active');
}}
function prioIcon(p){{const m={{urgent:'🔴',high:'🟠',medium:'🟡',low:'🟢',none:'⚪'}};return m[String(p||'').toLowerCase()]||'⚪';}}
function liRow(i){{
  return `<div class="li-row">
    <div class="li-id">${{escH(i.identifier||i.id||'')}}</div>
    <div style="flex:1;min-width:0">
      <div class="li-title">${{escH(i.title||'')}}</div>
      <div class="li-meta">
        ${{i.state?`<span class="state-pill">${{escH(i.state)}}</span>`:''}}
        ${{i.priority_label||i.priority?`<span>${{prioIcon(i.priority_label||i.priority)}} ${{escH(i.priority_label||String(i.priority||''))}}</span>`:''}}
        ${{i.team?`<span>${{escH(i.team)}}</span>`:''}}
        ${{i.estimate?`<span>${{i.estimate}}pts</span>`:''}}
      </div>
    </div>
  </div>`;
}}
function teamCard(t){{
  return `<div style="background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:14px;margin-bottom:7px;display:flex;gap:10px;align-items:center">
    <div style="font-size:20px">👥</div>
    <div><div style="font-size:13px;font-weight:600;color:#d4d8e8">${{escH(t.name||'')}}</div>
    <div style="font-size:11px;color:#8892b0">${{escH(t.key||'')}}</div></div>
  </div>`;
}}
function projCard(p){{
  return `<div style="background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:14px;margin-bottom:7px">
    <div style="font-size:13px;font-weight:600;color:#d4d8e8;margin-bottom:4px">${{escH(p.name||'')}}</div>
    <div style="font-size:11px;color:#8892b0">${{escH(p.state||'')}}&nbsp;·&nbsp;${{escH(p.team||'')}}</div>
  </div>`;
}}
async function loadAll(){{
  try{{
    const r=await fetch('/linear/issues'); const d=await r.json();
    const issues=d.issues||[];
    const inprog=issues.filter(i=>String(i.state||'').toLowerCase().includes('progress'));
    const todo=issues.filter(i=>String(i.state||'').toLowerCase().includes('todo')||String(i.state||'').toLowerCase().includes('backlog'));
    document.getElementById('s-total').textContent=issues.length;
    document.getElementById('s-inprog').textContent=inprog.length;
    document.getElementById('s-todo').textContent=todo.length;
    document.getElementById('ltab-issues').innerHTML=issues.length?issues.map(liRow).join(''):'<div class="empty-msg">No issues assigned ✓</div>';
  }}catch(e){{document.getElementById('ltab-issues').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
  try{{
    const r=await fetch('/linear/teams'); const d=await r.json();
    const teams=d.teams||[];
    document.getElementById('s-teams').textContent=teams.length;
    document.getElementById('ltab-teams').innerHTML=teams.length?teams.map(teamCard).join(''):'<div class="empty-msg">No teams found</div>';
  }}catch(e){{document.getElementById('ltab-teams').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
  try{{
    const r=await fetch('/linear/projects'); const d=await r.json();
    const projs=d.projects||[];
    document.getElementById('ltab-projects').innerHTML=projs.length?projs.map(projCard).join(''):'<div class="empty-msg">No projects found</div>';
  }}catch(e){{document.getElementById('ltab-projects').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadAll();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# SLACK — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/slack/channels")
def api_slack_channels():
    try:
        from tools import slack_tool
        return jsonify({"channels": slack_tool.list_slack_channels(max_count=50)})
    except Exception as e:
        return jsonify({"channels": [], "error": str(e)})

@app.route("/slack/messages")
def api_slack_messages():
    channel_id = request.args.get("channel_id", "")
    try:
        from tools import slack_tool
        return jsonify({"messages": slack_tool.get_slack_messages(channel_id, max_count=30)})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})

@app.route("/slack/dms")
def api_slack_dms():
    try:
        from tools import slack_tool
        return jsonify({"dms": slack_tool.list_slack_dms(max_count=20)})
    except Exception as e:
        return jsonify({"dms": [], "error": str(e)})

@app.route("/slack/send", methods=["POST"])
def api_slack_send():
    data = request.get_json() or {}
    try:
        from tools import slack_tool
        result = slack_tool.send_slack_message(
            channel_id=data.get("channel_id", ""),
            message=data.get("message", ""),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/slack-page")
def slack_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Slack — Work Assistant</title>{_PAGE_STYLE}
<style>
.slack-layout{{display:grid;grid-template-columns:260px 1fr;gap:16px;height:calc(100vh - 180px)}}
.slack-sidebar{{background:#1a1c24;border:1px solid #252836;border-radius:10px;overflow-y:auto;padding:8px 0}}
.slack-main{{background:#1a1c24;border:1px solid #252836;border-radius:10px;display:flex;flex-direction:column}}
.ch-item{{padding:8px 14px;cursor:pointer;font-size:13px;color:#8892b0;border-radius:6px;margin:0 6px;display:flex;gap:8px;align-items:center}}
.ch-item:hover{{background:#1e2028;color:#d4d8e8}}
.ch-item.active{{background:#1c2540;color:#64ffda}}
.ch-hash{{color:#8892b0;font-size:14px}}
.msg-list{{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}}
.msg-bubble{{display:flex;gap:10px;align-items:flex-start}}
.msg-avatar{{width:32px;height:32px;border-radius:8px;background:#1c2540;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}}
.msg-body{{flex:1;min-width:0}}
.msg-user{{font-size:12px;font-weight:700;color:#64ffda}}
.msg-time{{font-size:11px;color:#8892b0;margin-left:8px}}
.msg-text{{font-size:13px;color:#d4d8e8;margin-top:3px;word-break:break-word}}
.send-bar{{padding:12px;border-top:1px solid #252836;display:flex;gap:8px}}
.send-bar input{{flex:1;background:#12131a;border:1px solid #252836;border-radius:6px;padding:8px 12px;color:#d4d8e8;font-size:13px}}
.send-bar input:focus{{outline:none;border-color:#64ffda}}
.slack-hdr{{padding:12px 14px;border-bottom:1px solid #252836;font-size:13px;font-weight:700;color:#d4d8e8;display:flex;justify-content:space-between;align-items:center}}
.tab-row{{display:flex;gap:6px;padding:8px 8px 0}}
.stab{{padding:5px 12px;border-radius:16px;border:1px solid #252836;background:#12131a;color:#8892b0;font-size:11px;cursor:pointer}}
.stab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap" style="padding-bottom:0">
  <div class="page-hdr">
    <div><div class="page-title">💬 Slack</div><div class="page-subtitle">Channels, DMs and messages</div></div>
  </div>
  <div class="tab-row" style="margin-bottom:12px">
    <button class="stab active" onclick="loadChannels(this)">📢 Channels</button>
    <button class="stab" onclick="loadDMs(this)">💬 Direct Messages</button>
  </div>
  <div class="slack-layout">
    <div class="slack-sidebar" id="ch-list"><div class="empty-msg">Loading…</div></div>
    <div class="slack-main">
      <div class="slack-hdr"><span id="ch-name">Select a channel</span><button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="refreshMsgs()">↻</button></div>
      <div class="msg-list" id="msg-list"><div class="empty-msg">Pick a channel to see messages</div></div>
      <div class="send-bar">
        <input id="send-input" placeholder="Send a message…" onkeydown="if(event.key==='Enter')sendMsg()">
        <button class="btn btn-primary" onclick="sendMsg()">Send</button>
      </div>
    </div>
  </div>
</div>
<script>
let _activeCh=null; let _activeChName='';
function renderChannelList(items, isDM){{
  const list=document.getElementById('ch-list');
  if(!items.length){{list.innerHTML='<div class="empty-msg">None found</div>';return;}}
  list.innerHTML=items.map(c=>{{
    const icon=isDM?'👤':'#';
    const name=isDM?(c.user_name||c.name||c.id):( c.name||c.id);
    return `<div class="ch-item" id="ch-${{c.id}}" onclick="selectChannel('${{c.id}}','${{escH(name)}}')">
      <span class="ch-hash">${{icon}}</span><span>${{escH(name)}}</span>
      ${{c.unread_count?`<span style="margin-left:auto;background:#ff5555;color:#fff;border-radius:10px;padding:1px 6px;font-size:10px">${{c.unread_count}}</span>`:''}}
    </div>`;
  }}).join('');
}}
async function loadChannels(el){{
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('ch-list').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/slack/channels'); const d=await r.json();
    renderChannelList(d.channels||[], false);
  }}catch(e){{document.getElementById('ch-list').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function loadDMs(el){{
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('ch-list').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/slack/dms'); const d=await r.json();
    renderChannelList(d.dms||[], true);
  }}catch(e){{document.getElementById('ch-list').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function selectChannel(id, name){{
  _activeCh=id; _activeChName=name;
  document.querySelectorAll('.ch-item').forEach(el=>el.classList.remove('active'));
  const el=document.getElementById('ch-'+id);
  if(el)el.classList.add('active');
  document.getElementById('ch-name').textContent=name;
  await refreshMsgs();
}}
async function refreshMsgs(){{
  if(!_activeCh)return;
  document.getElementById('msg-list').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/slack/messages?channel_id='+encodeURIComponent(_activeCh));
    const d=await r.json();
    const msgs=(d.messages||[]).reverse();
    const list=document.getElementById('msg-list');
    list.innerHTML=msgs.length?msgs.map(m=>{{
      const user=escH(m.user_name||m.user||'?');
      const text=escH(m.text||'');
      const time=m.timestamp?new Date(parseFloat(m.timestamp)*1000).toLocaleTimeString('en-GB',{{hour:'2-digit',minute:'2-digit'}}):'';
      return `<div class="msg-bubble"><div class="msg-avatar">${{user[0]||'?'}}</div>
        <div class="msg-body">
          <div><span class="msg-user">${{user}}</span><span class="msg-time">${{time}}</span></div>
          <div class="msg-text">${{text}}</div>
        </div></div>`;
    }}).join(''):'<div class="empty-msg">No messages</div>';
    list.scrollTop=list.scrollHeight;
  }}catch(e){{document.getElementById('msg-list').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function sendMsg(){{
  if(!_activeCh){{alert('Select a channel first');return;}}
  const inp=document.getElementById('send-input');
  const msg=inp.value.trim();
  if(!msg)return;
  inp.value='';
  try{{
    const r=await fetch('/slack/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{channel_id:_activeCh,message:msg}})}});
    const d=await r.json();
    if(d.status==='error'){{alert('Send failed: '+d.message);inp.value=msg;return;}}
    await refreshMsgs();
  }}catch(e){{alert('Error: '+e.message);inp.value=msg;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadChannels(document.querySelector('.stab'));
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# NOTION — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/notion/search")
def api_notion_search():
    q = request.args.get("q", "")
    try:
        from tools import notion_tool
        return jsonify({"pages": notion_tool.search_notion(q, max_results=20)})
    except Exception as e:
        return jsonify({"pages": [], "error": str(e)})

@app.route("/notion/page/<page_id>")
def api_notion_page(page_id):
    try:
        from tools import notion_tool
        return jsonify(notion_tool.get_notion_page(page_id))
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/notion-page")
def notion_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Notion — Work Assistant</title>{_PAGE_STYLE}
<style>
.notion-search{{display:flex;gap:8px;margin-bottom:16px}}
.notion-search input{{flex:1;background:#1a1c24;border:1px solid #252836;border-radius:6px;padding:9px 14px;color:#d4d8e8;font-size:13px}}
.notion-search input:focus{{outline:none;border-color:#64ffda}}
.page-item{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:14px 16px;margin-bottom:8px;cursor:pointer;display:flex;gap:10px;align-items:flex-start}}
.page-item:hover{{border-color:#3a4060}}
.page-icon{{font-size:20px;flex-shrink:0}}
.page-title{{font-size:13px;font-weight:600;color:#d4d8e8}}
.page-meta{{font-size:11px;color:#8892b0;margin-top:4px;display:flex;gap:8px}}
.page-content{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:16px;margin-top:12px;display:none}}
.page-content h2{{color:#64ffda;font-size:14px;margin:0 0 10px}}
.page-content pre{{white-space:pre-wrap;font-size:12px;color:#d4d8e8;font-family:inherit;line-height:1.6}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">📓 Notion</div><div class="page-subtitle">Search and browse your workspace pages</div></div>
  </div>
  <div class="notion-search">
    <input id="notion-q" placeholder="Search pages, docs, wikis…" onkeydown="if(event.key==='Enter')searchNotion()">
    <button class="btn btn-primary" onclick="searchNotion()">Search</button>
    <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836" onclick="searchNotion(true)">Browse Recent</button>
  </div>
  <div id="notion-results"><div class="empty-msg">Type above to search your Notion workspace</div></div>
  <div class="page-content" id="page-viewer">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <h2 id="pv-title">Page</h2>
      <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="document.getElementById('page-viewer').style.display='none'">✕ Close</button>
    </div>
    <pre id="pv-content"></pre>
  </div>
</div>
<script>
async function searchNotion(recent){{
  const q=recent?'':document.getElementById('notion-q').value.trim();
  const el=document.getElementById('notion-results');
  el.innerHTML='<div class="empty-msg">Searching…</div>';
  try{{
    const r=await fetch('/notion/search?q='+encodeURIComponent(q||''));
    const d=await r.json();
    const pages=d.pages||[];
    el.innerHTML=pages.length?pages.map(p=>{{
      const icon=p.icon||'📄';
      return `<div class="page-item" onclick="openPage('${{p.id}}','${{escH(p.title||'')}}')">
        <div class="page-icon">${{icon}}</div>
        <div>
          <div class="page-title">${{escH(p.title||'Untitled')}}</div>
          <div class="page-meta">
            ${{p.type?`<span>${{escH(p.type)}}</span>`:''}}
            ${{p.last_edited?`<span>📅 ${{escH(p.last_edited.slice(0,10))}} </span>`:''}}
            ${{p.workspace?`<span>${{escH(p.workspace)}}</span>`:''}}
          </div>
        </div>
      </div>`;
    }}).join(''):'<div class="empty-msg">No pages found</div>';
  }}catch(e){{el.innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function openPage(id, title){{
  const viewer=document.getElementById('page-viewer');
  const content=document.getElementById('pv-content');
  document.getElementById('pv-title').textContent=title;
  content.textContent='Loading…';
  viewer.style.display='block';
  viewer.scrollIntoView({{behavior:'smooth'}});
  try{{
    const r=await fetch('/notion/page/'+id);
    const d=await r.json();
    content.textContent=d.content||d.text||JSON.stringify(d,null,2);
  }}catch(e){{content.textContent='Error: '+e.message;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# MEETINGS (ZOOM + GOOGLE MEET) — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/zoom/meetings")
def api_zoom_meetings():
    try:
        from tools import zoom_meet
        return jsonify({"meetings": zoom_meet.list_zoom_meetings(meeting_type="upcoming")})
    except Exception as e:
        return jsonify({"meetings": [], "error": str(e)})

@app.route("/zoom/recordings")
def api_zoom_recordings():
    try:
        from tools import zoom_meet
        return jsonify({"recordings": zoom_meet.list_zoom_recordings(days_back=14)})
    except Exception as e:
        return jsonify({"recordings": [], "error": str(e)})

@app.route("/gcal/events")
def api_gcal_events():
    try:
        from tools import zoom_meet
        return jsonify({"events": zoom_meet.list_google_calendar_events(days_ahead=7)})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})

@app.route("/meetings-page")
def meetings_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Meetings — Work Assistant</title>{_PAGE_STYLE}
<style>
.mtab-bar{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
.mtab{{padding:7px 16px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.mtab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.meeting-card{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:14px 16px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start}}
.meeting-card:hover{{border-color:#3a4060}}
.meeting-icon{{font-size:24px;flex-shrink:0}}
.meeting-title{{font-size:13px;font-weight:600;color:#d4d8e8;margin-bottom:5px}}
.meeting-meta{{font-size:11px;color:#8892b0;display:flex;gap:10px;flex-wrap:wrap}}
.join-btn{{padding:5px 12px;border-radius:6px;border:none;background:#1c2540;color:#64ffda;font-size:11px;cursor:pointer;font-weight:600;white-space:nowrap}}
.join-btn:hover{{background:#22304a}}
.rec-card{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:7px}}
.rec-title{{font-size:13px;color:#d4d8e8;margin-bottom:4px}}
.rec-meta{{font-size:11px;color:#8892b0;display:flex;gap:8px}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">📹 Meetings</div><div class="page-subtitle">Zoom meetings, Google Calendar events and recordings</div></div>
    <button class="btn btn-primary" onclick="loadAll()">↻ Refresh</button>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="s-zoom">—</div><div class="stat-lbl">Zoom Upcoming</div></div>
    <div class="stat-card"><div class="stat-num" id="s-gcal" style="color:#64ffda">—</div><div class="stat-lbl">GCal Events</div></div>
    <div class="stat-card"><div class="stat-num" id="s-rec" style="color:#bd93f9">—</div><div class="stat-lbl">Recordings</div></div>
  </div>
  <div class="mtab-bar">
    <button class="mtab active" onclick="showMTab('zoom',this)">📹 Zoom</button>
    <button class="mtab" onclick="showMTab('gcal',this)">📅 Google Calendar</button>
    <button class="mtab" onclick="showMTab('recordings',this)">🎬 Recordings</button>
  </div>
  <div id="mtab-zoom"></div>
  <div id="mtab-gcal" style="display:none"></div>
  <div id="mtab-recordings" style="display:none"></div>
</div>
<script>
function showMTab(name,el){{
  ['zoom','gcal','recordings'].forEach(t=>document.getElementById('mtab-'+t).style.display='none');
  document.querySelectorAll('.mtab').forEach(b=>b.classList.remove('active'));
  document.getElementById('mtab-'+name).style.display='';
  el.classList.add('active');
}}
function fmtDT(s){{if(!s)return'';try{{return new Date(s).toLocaleString('en-GB',{{weekday:'short',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}});}}catch{{return s;}}}}
function meetCard(m){{
  const joinBtn=m.join_url?`<button class="join-btn" onclick="window.open('${{m.join_url}}','_blank')">🔗 Join</button>`:'';
  return `<div class="meeting-card">
    <div class="meeting-icon">📹</div>
    <div style="flex:1;min-width:0">
      <div class="meeting-title">${{escH(m.topic||m.title||'Meeting')}}</div>
      <div class="meeting-meta">
        ${{m.start_time?`<span>🕐 ${{fmtDT(m.start_time)}}</span>`:''}}
        ${{m.duration?`<span>⏱ ${{m.duration}}min</span>`:''}}
        ${{m.host?`<span>👤 ${{escH(m.host)}}</span>`:''}}
      </div>
    </div>
    ${{joinBtn}}
  </div>`;
}}
function gcalCard(e){{
  const joinBtn=e.meeting_link?`<button class="join-btn" onclick="window.open('${{e.meeting_link}}','_blank')">🔗 Join</button>`:'';
  return `<div class="meeting-card">
    <div class="meeting-icon">📅</div>
    <div style="flex:1;min-width:0">
      <div class="meeting-title">${{escH(e.title||e.summary||'Event')}}</div>
      <div class="meeting-meta">
        ${{e.start?`<span>🕐 ${{fmtDT(e.start)}}</span>`:''}}
        ${{e.attendees&&e.attendees.length?`<span>👥 ${{e.attendees.length}} attendees</span>`:''}}
        ${{e.location?`<span>📍 ${{escH(e.location)}}</span>`:''}}
      </div>
    </div>
    ${{joinBtn}}
  </div>`;
}}
function recCard(r){{
  const playBtn=r.play_url?`<button class="join-btn" onclick="window.open('${{r.play_url}}','_blank')">▶ Play</button>`:'';
  return `<div class="rec-card">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
      <div>
        <div class="rec-title">${{escH(r.topic||r.title||'Recording')}}</div>
        <div class="rec-meta">
          ${{r.start_time?`<span>📅 ${{fmtDT(r.start_time)}}</span>`:''}}
          ${{r.duration?`<span>⏱ ${{r.duration}}min</span>`:''}}
          ${{r.file_size?`<span>${{(r.file_size/1048576).toFixed(1)}}MB</span>`:''}}
        </div>
      </div>
      ${{playBtn}}
    </div>
  </div>`;
}}
async function loadAll(){{
  try{{const r=await fetch('/zoom/meetings');const d=await r.json();const m=d.meetings||[];document.getElementById('s-zoom').textContent=m.length;document.getElementById('mtab-zoom').innerHTML=m.length?m.map(meetCard).join(''):'<div class="empty-msg">No upcoming Zoom meetings</div>';}}catch(e){{document.getElementById('mtab-zoom').innerHTML=`<div class="empty-msg" style="color:#ff5555">Zoom: ${{e.message}}</div>`;}}
  try{{const r=await fetch('/gcal/events');const d=await r.json();const ev=d.events||[];document.getElementById('s-gcal').textContent=ev.length;document.getElementById('mtab-gcal').innerHTML=ev.length?ev.map(gcalCard).join(''):'<div class="empty-msg">No upcoming Google Calendar events</div>';}}catch(e){{document.getElementById('mtab-gcal').innerHTML=`<div class="empty-msg" style="color:#ff5555">Google Calendar: ${{e.message}}</div>`;}}
  try{{const r=await fetch('/zoom/recordings');const d=await r.json();const rec=d.recordings||[];document.getElementById('s-rec').textContent=rec.length;document.getElementById('mtab-recordings').innerHTML=rec.length?rec.map(recCard).join(''):'<div class="empty-msg">No recent recordings</div>';}}catch(e){{document.getElementById('mtab-recordings').innerHTML=`<div class="empty-msg" style="color:#ff5555">Recordings: ${{e.message}}</div>`;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadAll();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS — FULL PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/analytics-page")
def analytics_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Analytics — Work Assistant</title>{_PAGE_STYLE}
<style>
.an-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;margin-bottom:20px}}
.an-card{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:16px}}
.an-card h3{{font-size:12px;font-weight:700;color:#8892b0;letter-spacing:.5px;text-transform:uppercase;margin:0 0 12px}}
.bar-row{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.bar-label{{font-size:12px;color:#8892b0;width:100px;flex-shrink:0;text-align:right}}
.bar-track{{flex:1;background:#12131a;border-radius:3px;height:8px;overflow:hidden}}
.bar-fill{{height:100%;background:#64ffda;border-radius:3px;transition:width .4s}}
.bar-val{{font-size:11px;color:#64ffda;width:32px;text-align:right}}
.big-num{{font-size:36px;font-weight:800;color:#64ffda}}
.big-lbl{{font-size:12px;color:#8892b0;margin-top:4px}}
.tool-tag{{display:inline-block;padding:3px 10px;border-radius:12px;background:#1c2540;color:#64ffda;font-size:11px;margin:3px 2px;border:1px solid #243060}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">📊 Analytics</div><div class="page-subtitle">Your work patterns and agent usage over time</div></div>
    <div style="display:flex;gap:8px">
      <select id="days-sel" style="background:#1a1c24;border:1px solid #252836;color:#d4d8e8;padding:6px 10px;border-radius:6px;font-size:12px" onchange="loadAnalytics()">
        <option value="7">Last 7 days</option>
        <option value="14">Last 14 days</option>
        <option value="30">Last 30 days</option>
      </select>
      <button class="btn btn-primary" onclick="loadAnalytics()">↻ Refresh</button>
    </div>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="a-total">—</div><div class="stat-lbl">Total Requests</div></div>
    <div class="stat-card"><div class="stat-num" id="a-tools" style="color:#ffb86c">—</div><div class="stat-lbl">Tools Used</div></div>
    <div class="stat-card"><div class="stat-num" id="a-avg" style="color:#64ffda">—</div><div class="stat-lbl">Avg/Day</div></div>
    <div class="stat-card"><div class="stat-num" id="a-peak" style="color:#bd93f9">—</div><div class="stat-lbl">Peak Hour</div></div>
  </div>
  <div class="an-grid">
    <div class="an-card" style="grid-column:span 2">
      <h3>Tool Usage</h3>
      <div id="tool-bars"><div class="empty-msg">Loading…</div></div>
    </div>
    <div class="an-card">
      <h3>Hourly Activity</h3>
      <div id="hour-bars"><div class="empty-msg">Loading…</div></div>
    </div>
    <div class="an-card">
      <h3>Top Queries</h3>
      <div id="top-queries"><div class="empty-msg">Loading…</div></div>
    </div>
    <div class="an-card">
      <h3>Tools Accessed</h3>
      <div id="tool-tags"><div class="empty-msg">Loading…</div></div>
    </div>
  </div>
</div>
<script>
async function loadAnalytics(){{
  const days=document.getElementById('days-sel').value;
  try{{
    const r=await fetch('/analytics?days_back='+days);
    const d=await r.json();
    const s=d.summary||d||{{}};
    document.getElementById('a-total').textContent=s.total_requests||s.total_interactions||0;
    document.getElementById('a-tools').textContent=Object.keys(s.tool_usage||s.tools||{{}}).length;
    const avg=s.avg_per_day||(s.total_requests?Math.round(s.total_requests/parseInt(days)):0);
    document.getElementById('a-avg').textContent=avg||'—';
    // Peak hour
    const hours=s.hourly_activity||s.by_hour||{{}};
    const peakH=Object.entries(hours).sort((a,b)=>b[1]-a[1])[0];
    document.getElementById('a-peak').textContent=peakH?peakH[0]+':00':'—';
    // Tool bars
    const tools=s.tool_usage||s.tools||{{}};
    const toolEntries=Object.entries(tools).sort((a,b)=>b[1]-a[1]).slice(0,10);
    const maxT=toolEntries[0]?toolEntries[0][1]:1;
    document.getElementById('tool-bars').innerHTML=toolEntries.length?toolEntries.map(([k,v])=>
      `<div class="bar-row"><div class="bar-label" title="${{k}}">${{k.slice(-12)}}</div><div class="bar-track"><div class="bar-fill" style="width:${{Math.round(v/maxT*100)}}%"></div></div><div class="bar-val">${{v}}</div></div>`
    ).join(''):'<div class="empty-msg">No data yet</div>';
    // Tool tags
    document.getElementById('tool-tags').innerHTML=toolEntries.length?toolEntries.map(([k])=>`<span class="tool-tag">${{k}}</span>`).join(''):'<div class="empty-msg">No data</div>';
    // Hour bars
    const hourEntries=Object.entries(hours).sort((a,b)=>parseInt(a[0])-parseInt(b[0]));
    const maxH=hourEntries.length?Math.max(...hourEntries.map(([,v])=>v)):1;
    document.getElementById('hour-bars').innerHTML=hourEntries.length?hourEntries.map(([h,v])=>
      `<div class="bar-row"><div class="bar-label">${{String(h).padStart(2,'0')}}:00</div><div class="bar-track"><div class="bar-fill" style="width:${{Math.round(v/maxH*100)}}%"></div></div><div class="bar-val">${{v}}</div></div>`
    ).join(''):'<div class="empty-msg">No hourly data</div>';
    // Top queries
    const queries=s.top_queries||s.recent_queries||[];
    document.getElementById('top-queries').innerHTML=queries.length?queries.slice(0,8).map(q=>
      `<div style="font-size:12px;color:#d4d8e8;padding:5px 0;border-bottom:1px solid #1e2028">${{escH(typeof q==='string'?q:q.query||JSON.stringify(q))}}</div>`
    ).join(''):'<div class="empty-msg">No queries logged</div>';
  }}catch(e){{document.querySelector('.an-grid').innerHTML=`<div style="grid-column:span 2"><div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div></div>`;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadAnalytics();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# KNOWLEDGE BASE — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/kb")
def api_kb_list():
    try:
        from tools import rag
        return jsonify({"documents": rag.list_documents(), "stats": rag.kb_stats()})
    except Exception as e:
        return jsonify({"documents": [], "error": str(e)})

@app.route("/kb/search")
def api_kb_search():
    q = request.args.get("q", "")
    try:
        from tools import rag
        return jsonify(rag.search_knowledge_base(q, max_results=6))
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})

@app.route("/kb/<doc_id>", methods=["DELETE"])
def api_kb_delete(doc_id):
    try:
        from tools import rag
        return jsonify(rag.delete_document(doc_id))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/kb-page")
def kb_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Knowledge Base — Work Assistant</title>{_PAGE_STYLE}
<style>
.kbtab-bar{{display:flex;gap:6px;margin-bottom:16px}}
.kbtab{{padding:7px 16px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.kbtab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.kb-doc{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:7px;display:flex;align-items:center;gap:10px}}
.kb-doc:hover{{border-color:#3a4060}}
.kb-meta{{flex:1;min-width:0}}
.kb-title{{font-size:13px;font-weight:600;color:#d4d8e8}}
.kb-sub{{font-size:11px;color:#8892b0;margin-top:3px;display:flex;gap:8px}}
.kb-del{{padding:5px 10px;border-radius:6px;border:none;background:#1e1e2a;color:#ff5555;font-size:12px;cursor:pointer;flex-shrink:0}}
.kb-del:hover{{background:#2a1e1e}}
.search-bar{{display:flex;gap:8px;margin-bottom:14px}}
.search-bar input{{flex:1;background:#1a1c24;border:1px solid #252836;border-radius:6px;padding:8px 12px;color:#d4d8e8;font-size:13px}}
.search-bar input:focus{{outline:none;border-color:#64ffda}}
.res-item{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:8px}}
.res-source{{font-size:11px;color:#64ffda;margin-bottom:5px}}
.res-text{{font-size:12px;color:#d4d8e8;line-height:1.6}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">🧠 Knowledge Base</div><div class="page-subtitle">Uploaded documents and RAG search</div></div>
    <button class="btn btn-primary" onclick="document.getElementById('kb-upload-input').click()">＋ Upload Document</button>
    <input type="file" id="kb-upload-input" style="display:none" accept=".pdf,.txt,.md,.docx" onchange="uploadDoc(this)">
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="kb-count">—</div><div class="stat-lbl">Documents</div></div>
    <div class="stat-card"><div class="stat-num" id="kb-chunks" style="color:#64ffda">—</div><div class="stat-lbl">Chunks</div></div>
    <div class="stat-card"><div class="stat-num" id="kb-size" style="color:#ffb86c">—</div><div class="stat-lbl">Total Size</div></div>
  </div>
  <div class="kbtab-bar">
    <button class="kbtab active" onclick="showKBTab('docs',this)">📁 Documents</button>
    <button class="kbtab" onclick="showKBTab('search',this)">🔍 Search KB</button>
  </div>
  <div id="kbtab-docs"></div>
  <div id="kbtab-search" style="display:none">
    <div class="search-bar">
      <input id="kb-q" placeholder="Ask a question or search for content…" onkeydown="if(event.key==='Enter')searchKB()">
      <button class="btn btn-primary" onclick="searchKB()">Search</button>
    </div>
    <div id="kb-results"></div>
  </div>
</div>
<script>
function showKBTab(name,el){{
  ['docs','search'].forEach(t=>document.getElementById('kbtab-'+t).style.display='none');
  document.querySelectorAll('.kbtab').forEach(b=>b.classList.remove('active'));
  document.getElementById('kbtab-'+name).style.display='';
  el.classList.add('active');
}}
async function loadKB(){{
  try{{
    const r=await fetch('/kb'); const d=await r.json();
    const docs=d.documents||[]; const stats=d.stats||{{}};
    document.getElementById('kb-count').textContent=docs.length;
    document.getElementById('kb-chunks').textContent=stats.total_chunks||stats.chunks||'—';
    document.getElementById('kb-size').textContent=stats.total_size||'—';
    document.getElementById('kbtab-docs').innerHTML=docs.length?docs.map(doc=>
      `<div class="kb-doc" id="kbdoc-${{doc.id}}">
        <div style="font-size:22px">📄</div>
        <div class="kb-meta">
          <div class="kb-title">${{escH(doc.source||doc.title||doc.id)}}</div>
          <div class="kb-sub">
            ${{doc.chunks?`<span>${{doc.chunks}} chunks</span>`:''}}
            ${{doc.added_at?`<span>📅 ${{doc.added_at.slice(0,10)}}</span>`:''}}
            ${{doc.size?`<span>${{doc.size}}</span>`:''}}
          </div>
        </div>
        <button class="kb-del" onclick="deleteKB('${{doc.id}}')">🗑 Delete</button>
      </div>`
    ).join(''):'<div class="empty-msg">No documents yet. Upload one to get started.</div>';
  }}catch(e){{document.getElementById('kbtab-docs').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function deleteKB(id){{
  if(!confirm('Delete this document from the knowledge base?'))return;
  const r=await fetch('/kb/'+encodeURIComponent(id),{{method:'DELETE'}});
  const d=await r.json();
  if(d.status==='deleted'||d.status==='ok'){{document.getElementById('kbdoc-'+id)?.remove();}}
  else alert('Delete failed: '+(d.message||'unknown'));
}}
async function uploadDoc(input){{
  const file=input.files[0]; if(!file)return;
  const fd=new FormData(); fd.append('file',file);
  try{{
    const r=await fetch('/upload-doc',{{method:'POST',body:fd}});
    const d=await r.json();
    if(d.error)alert('Upload failed: '+d.error);
    else{{alert('Uploaded: '+file.name); loadKB();}}
  }}catch(e){{alert('Error: '+e.message);}}
  input.value='';
}}
async function searchKB(){{
  const q=document.getElementById('kb-q').value.trim(); if(!q)return;
  document.getElementById('kb-results').innerHTML='<div class="empty-msg">Searching…</div>';
  try{{
    const r=await fetch('/kb/search?q='+encodeURIComponent(q));
    const d=await r.json();
    const results=d.results||[];
    document.getElementById('kb-results').innerHTML=results.length?results.map(res=>
      `<div class="res-item">
        <div class="res-source">📄 ${{escH(res.source||res.document||'')}}&nbsp;·&nbsp;Score: ${{res.score?res.score.toFixed(2):'—'}}</div>
        <div class="res-text">${{escH(res.text||res.content||'')}}</div>
      </div>`
    ).join(''):'<div class="empty-msg">No matching content found</div>';
  }}catch(e){{document.getElementById('kb-results').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadKB();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# PROACTIVE ALERTS — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/alerts/status")
def api_alerts_status():
    try:
        from tools import proactive
        return jsonify(proactive.get_status())
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/alerts/toggle/<name>", methods=["POST"])
def api_alerts_toggle(name):
    try:
        from tools import proactive
        return jsonify(proactive.toggle_alert(name))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/alerts-page")
def alerts_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alerts — Work Assistant</title>{_PAGE_STYLE}
<style>
.alert-card{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:16px 18px;margin-bottom:10px;display:flex;align-items:center;gap:14px}}
.alert-card:hover{{border-color:#3a4060}}
.alert-icon{{font-size:24px;flex-shrink:0}}
.alert-info{{flex:1;min-width:0}}
.alert-name{{font-size:13px;font-weight:700;color:#d4d8e8}}
.alert-desc{{font-size:12px;color:#8892b0;margin-top:3px}}
.toggle-sw{{position:relative;width:44px;height:24px;flex-shrink:0}}
.toggle-sw input{{opacity:0;width:0;height:0;position:absolute}}
.toggle-slider{{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#252836;border-radius:24px;transition:.3s}}
.toggle-slider:before{{position:absolute;content:'';height:18px;width:18px;left:3px;bottom:3px;background:#8892b0;border-radius:50%;transition:.3s}}
.toggle-sw input:checked+.toggle-slider{{background:#1c4030}}
.toggle-sw input:checked+.toggle-slider:before{{transform:translateX(20px);background:#64ffda}}
.alert-last{{font-size:11px;color:#8892b0;flex-shrink:0;text-align:right;min-width:80px}}
.running-badge{{padding:3px 10px;border-radius:10px;font-size:11px;font-weight:700;background:#1c4030;color:#64ffda;border:1px solid #1a6040}}
.stopped-badge{{padding:3px 10px;border-radius:10px;font-size:11px;background:#2a1e1e;color:#ff5555;border:1px solid #4a1e1e}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">🔔 Proactive Alerts</div><div class="page-subtitle">Configure background monitoring and alert rules</div></div>
    <div id="monitor-status"></div>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="a-enabled">—</div><div class="stat-lbl">Enabled</div></div>
    <div class="stat-card"><div class="stat-num" id="a-total" style="color:#8892b0">—</div><div class="stat-lbl">Total Alerts</div></div>
  </div>
  <div id="alerts-list"><div style="text-align:center;padding:40px;color:#8892b0">Loading…</div></div>
</div>
<script>
const ALERT_ICONS={{
  urgent_emails:'📧', pr_reviews:'🔀', ci_failures:'❌',
  meeting_reminders:'📅', linear_blocked:'⚡', jira_overdue:'📋'
}};
const ALERT_DESCS={{
  urgent_emails:'Notifies when high-priority or flagged emails arrive',
  pr_reviews:'Reminds you when your PR review is requested',
  ci_failures:'Alerts on GitHub Actions CI/CD pipeline failures',
  meeting_reminders:'Sends a reminder 5 minutes before calendar events',
  linear_blocked:'Flags your Linear issues that are marked as blocked',
  jira_overdue:'Highlights Jira issues past their due date'
}};
async function loadAlerts(){{
  try{{
    const r=await fetch('/alerts/status'); const d=await r.json();
    const alerts=d.alerts||{{}};
    const running=d.monitoring_active||d.running;
    document.getElementById('monitor-status').innerHTML=running
      ?'<span class="running-badge">● Monitoring Active</span>'
      :'<span class="stopped-badge">● Monitoring Stopped</span>';
    const entries=Object.entries(alerts);
    document.getElementById('a-total').textContent=entries.length;
    document.getElementById('a-enabled').textContent=entries.filter(([,v])=>v===true||v?.enabled).length;
    document.getElementById('alerts-list').innerHTML=entries.length?entries.map(([name,val])=>{{
      const enabled=val===true||val?.enabled;
      const icon=ALERT_ICONS[name]||'🔔';
      const desc=ALERT_DESCS[name]||'Background alert monitor';
      const lastFired=val?.last_fired?`Last: ${{val.last_fired.slice(0,16)}}`:d.last_run?`Last run: ${{d.last_run.slice(0,16)}}`:' ';
      return `<div class="alert-card">
        <div class="alert-icon">${{icon}}</div>
        <div class="alert-info">
          <div class="alert-name">${{escH(name.replace(/_/g,' ').replace(/\\b\\w/g,c=>c.toUpperCase()))}}</div>
          <div class="alert-desc">${{desc}}</div>
        </div>
        <div class="alert-last">${{lastFired}}</div>
        <label class="toggle-sw" title="${{{{'enabled':'Disable','disabled':'Enable'}}[enabled?'enabled':'disabled']}}">
          <input type="checkbox" ${{enabled?'checked':''}} onchange="toggleAlert('${{name}}',this)">
          <span class="toggle-slider"></span>
        </label>
      </div>`;
    }}).join(''):'<div style="text-align:center;padding:40px;color:#8892b0">No alerts configured</div>';
  }}catch(e){{document.getElementById('alerts-list').innerHTML=`<div style="text-align:center;padding:40px;color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function toggleAlert(name, checkbox){{
  try{{
    const r=await fetch('/alerts/toggle/'+name,{{method:'POST'}});
    const d=await r.json();
    if(d.status==='error'){{alert('Failed: '+d.message);checkbox.checked=!checkbox.checked;}}
    else loadAlerts();
  }}catch(e){{alert('Error: '+e.message);checkbox.checked=!checkbox.checked;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadAlerts();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# GUARDRAILS — FULL PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/guardrails-page")
def guardrails_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guardrails — Work Assistant</title>{_PAGE_STYLE}
<style>
.gr-card{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:18px 20px;margin-bottom:12px;display:flex;align-items:flex-start;gap:14px}}
.gr-card:hover{{border-color:#3a4060}}
.gr-icon{{font-size:26px;flex-shrink:0}}
.gr-info{{flex:1;min-width:0}}
.gr-name{{font-size:14px;font-weight:700;color:#d4d8e8;margin-bottom:4px}}
.gr-desc{{font-size:12px;color:#8892b0;line-height:1.6}}
.gr-toggle{{position:relative;width:50px;height:26px;flex-shrink:0;margin-top:4px}}
.gr-toggle input{{opacity:0;width:0;height:0;position:absolute}}
.gr-slider{{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:#252836;border-radius:26px;transition:.3s}}
.gr-slider:before{{position:absolute;content:'';height:20px;width:20px;left:3px;bottom:3px;background:#8892b0;border-radius:50%;transition:.3s}}
.gr-toggle input:checked+.gr-slider{{background:#1c4030}}
.gr-toggle input:checked+.gr-slider:before{{transform:translateX(24px);background:#64ffda}}
.on-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px;background:#1c4030;color:#64ffda;border:1px solid #1a6040}}
.off-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:8px;background:#2a1e1e;color:#ff5555;border:1px solid #4a1e1e}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">🛡 Guardrails</div><div class="page-subtitle">Control safety filters and agent behaviour policies</div></div>
    <button class="btn btn-primary" onclick="loadGuardrails()">↻ Refresh</button>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="gr-on">—</div><div class="stat-lbl">Enabled</div></div>
    <div class="stat-card"><div class="stat-num" id="gr-off" style="color:#ff5555">—</div><div class="stat-lbl">Disabled</div></div>
  </div>
  <div id="guardrails-list"><div style="text-align:center;padding:40px;color:#8892b0">Loading…</div></div>
</div>
<script>
const GR_META={{
  pii_filter:{{icon:'🔒',desc:'Strips emails, phone numbers and personal identifiers from agent output before displaying it to you.'}},
  injection_guard:{{icon:'💉',desc:'Detects and blocks prompt injection attacks — attempts by malicious content to hijack the agent.'}},
  rate_limit:{{icon:'🚦',desc:'Caps the number of tool calls per agent turn to prevent runaway loops or excessive API usage.'}},
  write_confirm:{{icon:'✏️',desc:'Requires your confirmation before the agent performs any write operations (send email, create issue, etc.).'}}
}};
async function loadGuardrails(){{
  try{{
    const r=await fetch('/guardrails'); const d=await r.json();
    const items=d.guardrails||d||[];
    const on=items.filter(g=>g.enabled).length;
    document.getElementById('gr-on').textContent=on;
    document.getElementById('gr-off').textContent=items.length-on;
    document.getElementById('guardrails-list').innerHTML=items.map(g=>{{
      const meta=GR_META[g.name]||{{icon:'🛡',desc:g.description||''}};
      return `<div class="gr-card">
        <div class="gr-icon">${{meta.icon}}</div>
        <div class="gr-info">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
            <div class="gr-name">${{escH(g.name.replace(/_/g,' ').replace(/\\b\\w/g,c=>c.toUpperCase()))}}</div>
            <span class="${{g.enabled?'on-badge':'off-badge'}}" id="badge-${{g.name}}">${{g.enabled?'ON':'OFF'}}</span>
          </div>
          <div class="gr-desc">${{meta.desc||escH(g.description||'')}}</div>
        </div>
        <label class="gr-toggle" title="Toggle ${{g.name}}">
          <input type="checkbox" ${{g.enabled?'checked':''}} onchange="toggleGR('${{g.name}}',this)">
          <span class="gr-slider"></span>
        </label>
      </div>`;
    }}).join('');
  }}catch(e){{document.getElementById('guardrails-list').innerHTML=`<div style="text-align:center;padding:40px;color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
async function toggleGR(name, checkbox){{
  try{{
    const r=await fetch('/guardrails/'+name,{{method:'POST'}});
    const d=await r.json();
    const badge=document.getElementById('badge-'+name);
    if(badge){{badge.textContent=d.enabled?'ON':'OFF';badge.className=d.enabled?'on-badge':'off-badge';}}
    const on=document.querySelectorAll('.gr-card input:checked').length;
    document.getElementById('gr-on').textContent=on;
    document.getElementById('gr-off').textContent=document.querySelectorAll('.gr-card input').length-on;
  }}catch(e){{alert('Error: '+e.message);checkbox.checked=!checkbox.checked;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadGuardrails();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOKS EVENT LOG — API + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/webhooks/events")
def api_webhook_events():
    source = request.args.get("source")
    try:
        from tools.webhook_server import get_recent_events
        return jsonify({"events": get_recent_events(source=source or None, limit=50)})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})

@app.route("/webhooks-page")
def webhooks_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Webhooks — Work Assistant</title>{_PAGE_STYLE}
<style>
.whtab-bar{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
.whtab{{padding:7px 16px;border-radius:20px;border:1px solid #252836;background:#1a1c24;color:#8892b0;font-size:12px;cursor:pointer;transition:all .2s}}
.whtab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.ev-row{{background:#1a1c24;border:1px solid #252836;border-radius:8px;padding:12px 14px;margin-bottom:7px;display:flex;gap:10px;align-items:flex-start}}
.ev-row:hover{{border-color:#3a4060}}
.ev-badge{{padding:2px 8px;border-radius:8px;font-size:10px;font-weight:700;flex-shrink:0}}
.ev-gh{{background:#1c2c1c;color:#50fa7b;border:1px solid #1a4a1a}}
.ev-jira{{background:#1c2040;color:#64ffda;border:1px solid #1a3060}}
.ev-body{{flex:1;min-width:0}}
.ev-type{{font-size:13px;font-weight:600;color:#d4d8e8;margin-bottom:3px}}
.ev-meta{{font-size:11px;color:#8892b0;display:flex;gap:8px;flex-wrap:wrap}}
.ev-payload{{font-size:11px;color:#8892b0;font-family:monospace;margin-top:6px;background:#12131a;border-radius:4px;padding:6px 8px;max-height:80px;overflow:auto}}
.setup-box{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:20px}}
.setup-box h3{{color:#d4d8e8;font-size:14px;margin:0 0 10px}}
.url-copy{{display:flex;gap:8px;align-items:center;margin-bottom:10px}}
.url-copy input{{flex:1;background:#12131a;border:1px solid #252836;border-radius:6px;padding:7px 10px;color:#64ffda;font-size:12px;font-family:monospace}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">🪝 Webhooks</div><div class="page-subtitle">Incoming GitHub and Jira real-time events</div></div>
    <button class="btn btn-primary" onclick="loadEvents('all',document.querySelector('.whtab.active'))">↻ Refresh</button>
  </div>
  <div class="stats-bar">
    <div class="stat-card"><div class="stat-num" id="wh-total">—</div><div class="stat-lbl">Total Events</div></div>
    <div class="stat-card"><div class="stat-num" id="wh-gh" style="color:#50fa7b">—</div><div class="stat-lbl">GitHub</div></div>
    <div class="stat-card"><div class="stat-num" id="wh-jira" style="color:#64ffda">—</div><div class="stat-lbl">Jira</div></div>
  </div>
  <div class="whtab-bar">
    <button class="whtab active" onclick="loadEvents('all',this)">All Events</button>
    <button class="whtab" onclick="loadEvents('github',this)">🐙 GitHub</button>
    <button class="whtab" onclick="loadEvents('jira',this)">📋 Jira</button>
    <button class="whtab" onclick="showSetup(this)">⚙️ Setup</button>
  </div>
  <div id="wh-events"></div>
  <div id="wh-setup" style="display:none">
    <div class="setup-box">
      <h3>Configure Webhook URLs</h3>
      <p style="font-size:12px;color:#8892b0;margin:0 0 14px">Add these URLs to your GitHub repo or Jira project to receive real-time events.</p>
      <div class="url-copy">
        <input id="gh-url" readonly>
        <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="copyUrl('gh-url')">Copy</button>
      </div>
      <p style="font-size:11px;color:#8892b0;margin:0 0 12px">GitHub → Settings → Webhooks → Add webhook → Content type: application/json</p>
      <div class="url-copy">
        <input id="jira-url" readonly>
        <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="copyUrl('jira-url')">Copy</button>
      </div>
      <p style="font-size:11px;color:#8892b0;margin:0">Jira → Project Settings → Automation → Webhook</p>
    </div>
  </div>
</div>
<script>
let _allEvents=[];
function showSetup(el){{
  document.querySelectorAll('.whtab').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('wh-events').style.display='none';
  document.getElementById('wh-setup').style.display='';
  const base=window.location.origin;
  document.getElementById('gh-url').value=base+'/webhooks/github';
  document.getElementById('jira-url').value=base+'/webhooks/jira';
}}
function copyUrl(id){{navigator.clipboard.writeText(document.getElementById(id).value).then(()=>alert('Copied!'));}}
async function loadEvents(source,el){{
  document.querySelectorAll('.whtab').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('wh-setup').style.display='none';
  document.getElementById('wh-events').style.display='';
  document.getElementById('wh-events').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const url='/webhooks/events'+(source&&source!=='all'?'?source='+source:'');
    const r=await fetch(url); const d=await r.json();
    const events=d.events||[];
    if(source==='all'){{
      _allEvents=events;
      document.getElementById('wh-total').textContent=events.length;
      document.getElementById('wh-gh').textContent=events.filter(e=>e.source==='github').length;
      document.getElementById('wh-jira').textContent=events.filter(e=>e.source==='jira').length;
    }}
    document.getElementById('wh-events').innerHTML=events.length?events.map(ev=>{{
      const badge=ev.source==='github'?'ev-gh':'ev-jira';
      const payload=ev.payload?JSON.stringify(ev.payload).slice(0,200)+'…':'';
      return `<div class="ev-row">
        <span class="ev-badge ${{badge}}">${{escH(ev.source||'')}}</span>
        <div class="ev-body">
          <div class="ev-type">${{escH(ev.event_type||ev.type||'event')}}</div>
          <div class="ev-meta">
            ${{ev.repo?`<span>📁 ${{escH(ev.repo)}}</span>`:''}}
            ${{ev.received_at?`<span>🕐 ${{escH(ev.received_at.slice(0,16))}}</span>`:''}}
          </div>
          ${{payload?`<div class="ev-payload">${{escH(payload)}}</div>`:''}}
        </div>
      </div>`;
    }}).join(''):'<div class="empty-msg">No events received yet. Configure the webhook URLs in the Setup tab.</div>';
  }}catch(e){{document.getElementById('wh-events').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{e.message}}</div>`;}}
}}
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
loadEvents('all',document.querySelector('.whtab'));
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# SELF-LEARNING DASHBOARD — APIs + Page
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/alert-feedback", methods=["POST"])
def api_alert_feedback():
    """Record user feedback on an alert (Feature 6 — Proactive Alert Tuning)."""
    data = request.get_json(silent=True) or {}
    alert_type = (data.get("alert_type", "") or "")[:64]
    action = data.get("action", "")   # "dismissed" or "acted"
    if not alert_type or action not in ("dismissed", "acted"):
        return jsonify({"error": "invalid input"}), 400
    try:
        from tools.self_learning import record_alert_action
        record_alert_action(alert_type, action)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/corrections", methods=["GET"])
def api_get_corrections():
    """Return stored corrections for the UI."""
    try:
        from tools.corrections import get_all_corrections
        return jsonify(get_all_corrections())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/corrections/<int:idx>", methods=["DELETE"])
def api_delete_correction(idx):
    """Delete a correction by index."""
    try:
        from tools.corrections import delete_correction
        delete_correction(idx)
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/self-learning", methods=["GET"])
def api_self_learning_state():
    """Return full self-learning state for the dashboard."""
    try:
        from tools.self_learning import get_full_state, get_query_clusters, get_skipped_tools, get_optimal_briefing_hour
        return jsonify({
            "state":            get_full_state(),
            "query_clusters":   get_query_clusters(),
            "skipped_tools":    get_skipped_tools(),
            "briefing_hour":    get_optimal_briefing_hour(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auto-ingest/run", methods=["POST"])
def api_run_auto_ingest():
    """Manually trigger auto-ingestion (Feature 7)."""
    try:
        from tools.auto_ingest import run_auto_ingest
        summary = run_auto_ingest()
        return jsonify(summary)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/self-learning-page")
def self_learning_page():
    return f"""<!DOCTYPE html>
<html><head><title>Self-Learning — Work Assistant</title>
<style>
  body {{ font-family: system-ui; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }}
  h1 {{ color: #818cf8; }} h2 {{ color: #94a3b8; border-bottom: 1px solid #334155; padding-bottom: 8px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 12px; margin: 2px; }}
  .high {{ background: #16a34a; }} .muted {{ background: #dc2626; }} .normal {{ background: #475569; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td, th {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #334155; }}
  button {{ background: #ef4444; color: white; border: none; padding: 4px 10px; border-radius: 6px; cursor: pointer; }}
  .run-btn {{ background: #6366f1; padding: 8px 18px; border-radius: 8px; border: none; color: white; cursor: pointer; font-size: 14px; }}
</style></head>
<body>
  <h1>🧠 Self-Learning Dashboard</h1>

  <div class="card">
    <h2>⚡ Query Clusters (most common patterns)</h2>
    <div id="clusters">Loading...</div>
  </div>

  <div class="card">
    <h2>🔧 Tool Error Avoidance</h2>
    <div id="skipped">Loading...</div>
  </div>

  <div class="card">
    <h2>⏰ Smart Briefing Time</h2>
    <p>Optimal hour based on your app-open patterns: <strong id="briefing-hour">...</strong></p>
  </div>

  <div class="card">
    <h2>✏️ Corrections Memory</h2>
    <table><thead><tr><th>Correction</th><th>Times</th><th>Delete</th></tr></thead>
    <tbody id="corrections-tbody"></tbody></table>
  </div>

  <div class="card">
    <h2>📚 Auto Knowledge Base Ingestion</h2>
    <button class="run-btn" onclick="runIngest()">▶ Run Now</button>
    <pre id="ingest-result" style="margin-top:12px;color:#94a3b8;"></pre>
  </div>

<script>
async function load() {{
  const r = await fetch('/api/self-learning');
  const d = await r.json();

  document.getElementById('briefing-hour').textContent = d.briefing_hour + ':00';

  const clusters = d.query_clusters || [];
  if (clusters.length) {{
    let rows = clusters.map(c => {{
      const label = c.label.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return `<tr><td>${{label}}</td><td>${{c.count}}</td></tr>`;
    }}).join('');
    document.getElementById('clusters').innerHTML =
      '<table><thead><tr><th>Pattern</th><th>Count</th></tr></thead><tbody>' + rows + '</tbody></table>';
  }} else {{
    document.getElementById('clusters').innerHTML = '<p style="color:#64748b">No clusters yet — chat more with the agent!</p>';
  }}

  const skipped = d.skipped_tools || [];
  document.getElementById('skipped').innerHTML = skipped.length
    ? skipped.map(t => {{ const s = t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); return `<span class="badge muted">⚠ ${{s}}</span>`; }}).join(' ')
    : '<span style="color:#64748b">No tools are being skipped</span>';
}}

async function loadCorrections() {{
  const r = await fetch('/api/corrections');
  const data = await r.json();
  const tbody = document.getElementById('corrections-tbody');
  tbody.innerHTML = data.map((c, i) => {{
    const correction = (c.correction || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    return `<tr><td>${{correction}}</td><td>${{c.count}}</td>
     <td><button onclick="deleteCorrection(${{i}})">✕</button></td></tr>`;
  }}).join('');
}}

async function deleteCorrection(idx) {{
  await fetch('/api/corrections/' + idx, {{method: 'DELETE'}});
  loadCorrections();
}}

async function runIngest() {{
  document.getElementById('ingest-result').textContent = 'Running...';
  const r = await fetch('/api/auto-ingest/run', {{method: 'POST'}});
  const d = await r.json();
  document.getElementById('ingest-result').textContent = JSON.stringify(d, null, 2);
}}

load();
loadCorrections();
</script>
</body></html>"""


# ══════════════════════════════════════════════════════════════════════════════
# TEAMS — API routes + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/teams/chats")
def api_teams_chats():
    try:
        from tools.ms365 import get_teams_chats
        return jsonify({"chats": get_teams_chats(max_results=30)})
    except Exception as e:
        return jsonify({"chats": [], "error": str(e)})

@app.route("/teams/chat-messages")
def api_teams_chat_messages():
    chat_id = request.args.get("chat_id", "")
    try:
        from tools.ms365 import get_chat_messages
        return jsonify({"messages": get_chat_messages(chat_id, max_results=30)})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})

@app.route("/teams/send-dm", methods=["POST"])
def api_teams_send_dm():
    data = request.json or {}
    try:
        from tools.ms365 import send_teams_message
        result = send_teams_message(data["chat_id"], data["message"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/teams/list")
def api_teams_list():
    try:
        from tools.ms365 import list_teams
        return jsonify({"teams": list_teams()})
    except Exception as e:
        return jsonify({"teams": [], "error": str(e)})

@app.route("/teams/channels")
def api_teams_channels():
    team_id = request.args.get("team_id", "")
    try:
        from tools.ms365 import _graph
        data = _graph("GET", f"/teams/{team_id}/channels?$select=id,displayName")
        return jsonify({"channels": [{"id": c["id"], "name": c["displayName"]} for c in data.get("value", [])]})
    except Exception as e:
        return jsonify({"channels": [], "error": str(e)})

@app.route("/teams/channel-messages")
def api_teams_channel_messages():
    team_id   = request.args.get("team_id", "")
    channel_id = request.args.get("channel_id", "")
    try:
        from tools.ms365 import get_channel_messages
        return jsonify({"messages": get_channel_messages(team_id, channel_id, max_results=30)})
    except Exception as e:
        return jsonify({"messages": [], "error": str(e)})

@app.route("/teams/post-channel", methods=["POST"])
def api_teams_post_channel():
    data = request.json or {}
    try:
        from tools.ms365 import post_channel_message
        result = post_channel_message(data["team_id"], data["channel_id"], data["message"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/teams-page")
def teams_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teams — Work Assistant</title>{_PAGE_STYLE}
<style>
.teams-layout{{display:grid;grid-template-columns:260px 1fr;gap:16px;height:calc(100vh - 195px)}}
.teams-sidebar{{background:#1a1c24;border:1px solid #252836;border-radius:10px;overflow-y:auto;padding:8px 0}}
.teams-main{{background:#1a1c24;border:1px solid #252836;border-radius:10px;display:flex;flex-direction:column}}
.t-item{{padding:8px 14px;cursor:pointer;font-size:13px;color:#8892b0;border-radius:6px;margin:0 6px;display:flex;flex-direction:column;gap:2px}}
.t-item:hover{{background:#1e2028;color:#d4d8e8}}
.t-item.active{{background:#1c2540;color:#64ffda}}
.t-name{{font-weight:600;font-size:13px}}
.t-sub{{font-size:11px;color:#8892b0}}
.msg-list{{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}}
.msg-bubble{{display:flex;gap:10px;align-items:flex-start}}
.msg-avatar{{width:32px;height:32px;border-radius:8px;background:#1c2540;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}}
.msg-body{{flex:1;min-width:0}}
.msg-user{{font-size:12px;font-weight:700;color:#64ffda}}
.msg-time{{font-size:11px;color:#8892b0;margin-left:8px}}
.msg-text{{font-size:13px;color:#d4d8e8;margin-top:3px;word-break:break-word}}
.send-bar{{padding:12px;border-top:1px solid #252836;display:flex;gap:8px}}
.send-bar input{{flex:1;background:#12131a;border:1px solid #252836;border-radius:6px;padding:8px 12px;color:#d4d8e8;font-size:13px}}
.send-bar input:focus{{outline:none;border-color:#64ffda}}
.t-hdr{{padding:12px 14px;border-bottom:1px solid #252836;font-size:13px;font-weight:700;color:#d4d8e8;display:flex;justify-content:space-between;align-items:center}}
.tab-row{{display:flex;gap:6px;padding:8px 8px 0;margin-bottom:12px}}
.stab{{padding:5px 12px;border-radius:16px;border:1px solid #252836;background:#12131a;color:#8892b0;font-size:11px;cursor:pointer}}
.stab.active{{background:#1c2540;color:#64ffda;border-color:#243060}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
.sid-hdr{{padding:8px 14px;font-size:10px;font-weight:700;color:#3a4060;letter-spacing:.5px;text-transform:uppercase}}
.back-btn{{font-size:11px;color:#64ffda;cursor:pointer;padding:4px 8px;border-radius:4px;border:1px solid #1e3050;background:none;margin:4px 6px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap" style="padding-bottom:0">
  <div class="page-hdr">
    <div><div class="page-title">💬 Teams</div><div class="page-subtitle">Chats, channels and messages</div></div>
  </div>
  <div class="tab-row">
    <button class="stab active" onclick="switchTab('chats',this)">💬 Chats</button>
    <button class="stab" onclick="switchTab('teams',this)">👥 Teams &amp; Channels</button>
  </div>
  <div class="teams-layout">
    <div class="teams-sidebar" id="t-sidebar"><div class="empty-msg">Loading…</div></div>
    <div class="teams-main">
      <div class="t-hdr"><span id="t-title">Select a chat</span><button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="refreshMsgs()">↻</button></div>
      <div class="msg-list" id="t-msgs"><div class="empty-msg">Pick a chat or channel to see messages</div></div>
      <div class="send-bar">
        <input id="t-input" placeholder="Send a message…" onkeydown="if(event.key==='Enter')sendMsg()">
        <button class="btn btn-primary" onclick="sendMsg()">Send</button>
      </div>
    </div>
  </div>
</div>
<script>
let _tmode='chats',_activeId=null,_activeTeamId=null,_activeChannelId=null;
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function switchTab(mode,el){{
  _tmode=mode;_activeId=null;_activeTeamId=null;_activeChannelId=null;
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));el.classList.add('active');
  document.getElementById('t-msgs').innerHTML='<div class="empty-msg">Pick a chat or channel to see messages</div>';
  document.getElementById('t-title').textContent='Select a '+(mode==='chats'?'chat':'channel');
  if(mode==='chats')loadChats();else loadTeamsList();
}}
async function loadChats(){{
  document.getElementById('t-sidebar').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/teams/chats');const d=await r.json();
    const chats=d.chats||[];
    if(!chats.length){{document.getElementById('t-sidebar').innerHTML='<div class="empty-msg">No chats found</div>';return;}}
    document.getElementById('t-sidebar').innerHTML='<div class="sid-hdr">Chats</div>'+chats.map(c=>{{
      const name=escH(c.topic||c.chatType||'Chat');
      const upd=c.lastUpdatedDateTime?new Date(c.lastUpdatedDateTime).toLocaleDateString('en-GB',{{day:'2-digit',month:'short'}}):'';
      return `<div class="t-item" id="ci-${{escH(c.id)}}" onclick="selectChat('${{escH(c.id)}}','${{name}}')">
        <div class="t-name">${{name}}</div><div class="t-sub">${{escH(c.chatType||'')}} · ${{upd}}</div></div>`;
    }}).join('');
    if(d.error)document.getElementById('t-sidebar').innerHTML+=`<div style="padding:8px 14px;font-size:11px;color:#ff5555">${{escH(d.error)}}</div>`;
  }}catch(e){{document.getElementById('t-sidebar').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function loadTeamsList(){{
  document.getElementById('t-sidebar').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/teams/list');const d=await r.json();
    const teams=d.teams||[];
    if(!teams.length){{document.getElementById('t-sidebar').innerHTML='<div class="empty-msg">No teams found</div>';return;}}
    document.getElementById('t-sidebar').innerHTML='<div class="sid-hdr">Teams</div>'+teams.map(t=>{{
      const name=escH(t.displayName||t.name||'Team');
      return `<div class="t-item" onclick="loadChannels('${{escH(t.id)}}','${{name}}')">
        <div class="t-name">👥 ${{name}}</div><div class="t-sub">${{escH(t.description||'')}}</div></div>`;
    }}).join('');
    if(d.error)document.getElementById('t-sidebar').innerHTML+=`<div style="padding:8px 14px;font-size:11px;color:#ff5555">${{escH(d.error)}}</div>`;
  }}catch(e){{document.getElementById('t-sidebar').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function loadChannels(teamId,teamName){{
  _activeTeamId=teamId;
  document.getElementById('t-sidebar').innerHTML='<div class="empty-msg">Loading channels…</div>';
  try{{
    const r=await fetch('/teams/channels?team_id='+encodeURIComponent(teamId));const d=await r.json();
    const channels=d.channels||[];
    document.getElementById('t-sidebar').innerHTML=
      `<button class="back-btn" onclick="loadTeamsList()">← Back</button><div class="sid-hdr">${{escH(teamName)}}</div>`+
      (channels.length?channels.map(c=>`<div class="t-item" onclick="selectChannel('${{escH(c.id)}}','${{escH(c.name)}}')">
        <div class="t-name"># ${{escH(c.name)}}</div></div>`).join(''):'<div class="empty-msg">No channels</div>');
  }}catch(e){{document.getElementById('t-sidebar').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
function selectChat(id,name){{
  _activeId=id;_tmode='chats';
  document.querySelectorAll('.t-item').forEach(el=>el.classList.remove('active'));
  const el=document.getElementById('ci-'+id);if(el)el.classList.add('active');
  document.getElementById('t-title').textContent=name;
  refreshMsgs();
}}
function selectChannel(channelId,name){{
  _activeChannelId=channelId;
  document.getElementById('t-title').textContent='# '+name;
  refreshMsgs();
}}
async function refreshMsgs(){{
  const msgEl=document.getElementById('t-msgs');
  msgEl.innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    let d;
    if(_tmode==='chats'&&_activeId){{
      const r=await fetch('/teams/chat-messages?chat_id='+encodeURIComponent(_activeId));d=await r.json();
    }}else if(_tmode==='teams'&&_activeTeamId&&_activeChannelId){{
      const r=await fetch('/teams/channel-messages?team_id='+encodeURIComponent(_activeTeamId)+'&channel_id='+encodeURIComponent(_activeChannelId));d=await r.json();
    }}else{{msgEl.innerHTML='<div class="empty-msg">Select a chat or channel</div>';return;}}
    const msgs=d.messages||[];
    msgEl.innerHTML=msgs.length?msgs.map(m=>{{
      const user=escH(m.sender||m.from||'?');
      const text=escH(m.body||m.content||m.text||'');
      const time=m.createdDateTime?new Date(m.createdDateTime).toLocaleTimeString('en-GB',{{hour:'2-digit',minute:'2-digit'}}):'';
      return `<div class="msg-bubble"><div class="msg-avatar">${{user[0]||'?'}}</div>
        <div class="msg-body"><div><span class="msg-user">${{user}}</span><span class="msg-time">${{time}}</span></div>
        <div class="msg-text">${{text}}</div></div></div>`;
    }}).join(''):'<div class="empty-msg">No messages</div>';
    msgEl.scrollTop=msgEl.scrollHeight;
  }}catch(e){{msgEl.innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function sendMsg(){{
  const inp=document.getElementById('t-input');const msg=inp.value.trim();if(!msg)return;
  inp.value='';
  try{{
    let url,body;
    if(_tmode==='chats'&&_activeId){{url='/teams/send-dm';body={{chat_id:_activeId,message:msg}};}}
    else if(_tmode==='teams'&&_activeTeamId&&_activeChannelId){{url='/teams/post-channel';body={{team_id:_activeTeamId,channel_id:_activeChannelId,message:msg}};}}
    else{{alert('Select a chat or channel first');inp.value=msg;return;}}
    const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    const d=await r.json();
    if(d.status==='error'){{alert('Send failed: '+d.message);inp.value=msg;return;}}
    await refreshMsgs();
  }}catch(e){{alert('Error: '+e.message);inp.value=msg;}}
}}
loadChats();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# SHAREPOINT — API routes + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/sharepoint/sites")
def api_sharepoint_sites():
    try:
        from tools.ms365 import get_sharepoint_sites
        return jsonify({"sites": get_sharepoint_sites()})
    except Exception as e:
        return jsonify({"sites": [], "error": str(e)})

@app.route("/sharepoint/files")
def api_sharepoint_files():
    site_id = request.args.get("site_id", "")
    folder  = request.args.get("folder", "")
    try:
        from tools.ms365 import list_sharepoint_files
        return jsonify({"files": list_sharepoint_files(site_id, folder or None)})
    except Exception as e:
        return jsonify({"files": [], "error": str(e)})

@app.route("/sharepoint/search-files")
def api_sharepoint_search_files():
    q       = request.args.get("q", "")
    site_id = request.args.get("site_id", "")
    try:
        from tools.ms365 import search_sharepoint
        return jsonify({"results": search_sharepoint(q, site_id or None)})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})

@app.route("/sharepoint/upload", methods=["POST"])
def api_sharepoint_upload():
    data = request.json or {}
    try:
        from tools.ms365 import upload_file_to_sharepoint
        result = upload_file_to_sharepoint(data["site_id"], data["file_path"], data.get("dest_folder", ""))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/sharepoint-page")
def sharepoint_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SharePoint — Work Assistant</title>{_PAGE_STYLE}
<style>
.sp-layout{{display:grid;grid-template-columns:260px 1fr;gap:16px;height:calc(100vh - 195px)}}
.sp-sidebar{{background:#1a1c24;border:1px solid #252836;border-radius:10px;overflow-y:auto;padding:8px 0}}
.sp-main{{background:#1a1c24;border:1px solid #252836;border-radius:10px;display:flex;flex-direction:column;overflow:hidden}}
.sp-item{{padding:8px 14px;cursor:pointer;font-size:13px;color:#8892b0;border-radius:6px;margin:0 6px}}
.sp-item:hover{{background:#1e2028;color:#d4d8e8}}
.sp-item.active{{background:#1c2540;color:#64ffda}}
.sp-hdr{{padding:12px 14px;border-bottom:1px solid #252836;font-size:13px;font-weight:700;color:#d4d8e8;display:flex;justify-content:space-between;align-items:center;gap:8px}}
.sp-hdr input{{flex:1;background:#12131a;border:1px solid #252836;border-radius:6px;padding:6px 10px;color:#d4d8e8;font-size:12px}}
.sp-hdr input:focus{{outline:none;border-color:#64ffda}}
.file-grid{{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:6px}}
.file-row{{display:flex;align-items:center;gap:10px;padding:8px 12px;background:#12131a;border-radius:6px;font-size:13px;color:#d4d8e8}}
.file-icon{{font-size:18px;flex-shrink:0}}
.file-name{{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.file-size{{font-size:11px;color:#8892b0;flex-shrink:0}}
.sid-hdr{{padding:8px 14px;font-size:10px;font-weight:700;color:#3a4060;letter-spacing:.5px;text-transform:uppercase}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap" style="padding-bottom:0">
  <div class="page-hdr">
    <div><div class="page-title">📁 SharePoint</div><div class="page-subtitle">Sites, files and search</div></div>
  </div>
  <div class="sp-layout">
    <div class="sp-sidebar" id="sp-sidebar"><div class="empty-msg">Loading sites…</div></div>
    <div class="sp-main">
      <div class="sp-hdr">
        <span id="sp-site-name" style="flex-shrink:0;font-size:13px">Select a site</span>
        <input id="sp-search" placeholder="Search files…" onkeydown="if(event.key==='Enter')searchFiles()">
        <button class="btn btn-primary" style="font-size:12px;padding:6px 12px" onclick="searchFiles()">Search</button>
        <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="refreshFiles()">↻</button>
      </div>
      <div class="file-grid" id="sp-files"><div class="empty-msg">Select a site to browse files</div></div>
    </div>
  </div>
</div>
<script>
let _spActiveSite=null;
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fileIcon(name){{const ext=(name||'').split('.').pop().toLowerCase();const icons={{xlsx:'📊',xls:'📊',docx:'📝',doc:'📝',pptx:'📊',ppt:'📊',pdf:'📄',png:'🖼',jpg:'🖼',jpeg:'🖼',mp4:'🎬',zip:'🗜',txt:'📃'}};return icons[ext]||'📄';}}
function fmtSize(b){{if(!b)return'';b=parseInt(b);if(b>1e6)return(b/1e6).toFixed(1)+'MB';if(b>1e3)return(b/1e3).toFixed(0)+'KB';return b+'B';}}
async function loadSites(){{
  document.getElementById('sp-sidebar').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/sharepoint/sites');const d=await r.json();
    const sites=d.sites||[];
    if(!sites.length){{document.getElementById('sp-sidebar').innerHTML='<div class="empty-msg">No sites found</div>';return;}}
    document.getElementById('sp-sidebar').innerHTML='<div class="sid-hdr">Sites</div>'+
      sites.map(s=>`<div class="sp-item" onclick="selectSite(${{JSON.stringify(s.id||s.siteId||'')}}, ${{JSON.stringify(s.displayName||s.name||'Site')}})">
        🌐 ${{escH(s.displayName||s.name||s.url||'Site')}}</div>`).join('');
  }}catch(e){{document.getElementById('sp-sidebar').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
function selectSite(id,name){{
  _spActiveSite=id;
  document.getElementById('sp-site-name').textContent=name;
  refreshFiles();
}}
async function refreshFiles(){{
  if(!_spActiveSite)return;
  document.getElementById('sp-files').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/sharepoint/files?site_id='+encodeURIComponent(_spActiveSite));const d=await r.json();
    renderFiles(d.files||[]);
    if(d.error)document.getElementById('sp-files').innerHTML+=`<div style="padding:8px;font-size:11px;color:#ff5555">${{escH(d.error)}}</div>`;
  }}catch(e){{document.getElementById('sp-files').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function searchFiles(){{
  const q=document.getElementById('sp-search').value.trim();if(!q)return;
  document.getElementById('sp-files').innerHTML='<div class="empty-msg">Searching…</div>';
  try{{
    let url='/sharepoint/search-files?q='+encodeURIComponent(q);
    if(_spActiveSite)url+='&site_id='+encodeURIComponent(_spActiveSite);
    const r=await fetch(url);const d=await r.json();
    renderFiles(d.results||[]);
  }}catch(e){{document.getElementById('sp-files').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
function renderFiles(files){{
  const el=document.getElementById('sp-files');
  el.innerHTML=files.length?files.map(f=>{{
    const name=escH(f.name||f.fileName||'?');
    const size=fmtSize(f.size);
    const url=f.webUrl||f.url||'#';
    return `<div class="file-row"><div class="file-icon">${{fileIcon(name)}}</div>
      <div class="file-name"><a href="${{escH(url)}}" target="_blank" style="color:#d4d8e8;text-decoration:none">${{name}}</a></div>
      <div class="file-size">${{size}}</div></div>`;
  }}).join(''):'<div class="empty-msg">No files found</div>';
}}
loadSites();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# EXCEL — API routes + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/excel/sheets")
def api_excel_sheets():
    workbook = request.args.get("workbook", "")
    try:
        from tools.ms365 import list_excel_sheets
        return jsonify({"sheets": list_excel_sheets(workbook)})
    except Exception as e:
        return jsonify({"sheets": [], "error": str(e)})

@app.route("/excel/read")
def api_excel_read():
    workbook = request.args.get("workbook", "")
    sheet    = request.args.get("sheet", "Sheet1")
    try:
        from tools.ms365 import read_excel_sheet
        return jsonify({"data": read_excel_sheet(workbook, sheet)})
    except Exception as e:
        return jsonify({"data": [], "error": str(e)})

@app.route("/excel/append", methods=["POST"])
def api_excel_append():
    data = request.json or {}
    try:
        from tools.ms365 import append_excel_row
        result = append_excel_row(data["workbook"], data["sheet"], data["values"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/excel/write-cell", methods=["POST"])
def api_excel_write_cell():
    data = request.json or {}
    try:
        from tools.ms365 import write_excel_cell
        result = write_excel_cell(data["workbook"], data["sheet"], data["cell"], data["value"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/excel-page")
def excel_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Excel — Work Assistant</title>{_PAGE_STYLE}
<style>
.xl-controls{{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}}
.xl-controls input{{background:#12131a;border:1px solid #252836;border-radius:6px;padding:7px 11px;color:#d4d8e8;font-size:13px}}
.xl-controls input:focus{{outline:none;border-color:#64ffda}}
.xl-table-wrap{{background:#1a1c24;border:1px solid #252836;border-radius:10px;overflow:auto;flex:1;min-height:200px}}
.xl-table{{border-collapse:collapse;width:100%;font-size:12px}}
.xl-table th{{background:#12131a;color:#64ffda;padding:8px 12px;text-align:left;border-bottom:1px solid #252836;font-weight:600;white-space:nowrap}}
.xl-table td{{padding:7px 12px;border-bottom:1px solid #1e2030;color:#d4d8e8;white-space:nowrap}}
.xl-table tr:hover td{{background:#1e2028}}
.append-form{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:16px;margin-top:14px}}
.append-form h3{{font-size:13px;color:#d4d8e8;margin:0 0 10px}}
.append-row{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.append-row input{{flex:1;min-width:120px;background:#12131a;border:1px solid #252836;border-radius:6px;padding:7px 11px;color:#d4d8e8;font-size:13px}}
.append-row input:focus{{outline:none;border-color:#64ffda}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">📊 Excel</div><div class="page-subtitle">OneDrive workbooks and sheets</div></div>
  </div>
  <div class="xl-controls">
    <input id="xl-workbook" placeholder="Workbook name e.g. AgentTest.xlsx" style="min-width:220px" onkeydown="if(event.key==='Enter')loadSheets()">
    <button class="btn btn-primary" onclick="loadSheets()">Load</button>
    <select id="xl-sheet" style="background:#12131a;border:1px solid #252836;border-radius:6px;padding:7px 11px;color:#d4d8e8;font-size:13px" onchange="loadSheet()">
      <option value="">Select sheet…</option>
    </select>
    <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="loadSheet()">↻</button>
  </div>
  <div class="xl-table-wrap" id="xl-table-wrap"><div class="empty-msg">Enter a workbook name and click Load</div></div>
  <div class="append-form" id="xl-append" style="display:none">
    <h3>➕ Append Row</h3>
    <div class="append-row">
      <input id="xl-v1" placeholder="Value 1">
      <input id="xl-v2" placeholder="Value 2">
      <input id="xl-v3" placeholder="Value 3">
      <input id="xl-v4" placeholder="Value 4">
      <button class="btn btn-primary" onclick="appendRow()">Append</button>
    </div>
    <div id="xl-append-status" style="font-size:12px;color:#64ffda;margin-top:8px"></div>
  </div>
</div>
<script>
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
async function loadSheets(){{
  const wb=document.getElementById('xl-workbook').value.trim();if(!wb)return;
  try{{
    const r=await fetch('/excel/sheets?workbook='+encodeURIComponent(wb));const d=await r.json();
    const sel=document.getElementById('xl-sheet');
    sel.innerHTML='<option value="">Select sheet…</option>'+(d.sheets||[]).map(s=>`<option value="${{escH(s)}}">${{escH(s)}}</option>`).join('');
    if(d.error){{document.getElementById('xl-table-wrap').innerHTML=`<div class="empty-msg" style="color:#ff5555">${{escH(d.error)}}</div>`;return;}}
    if(d.sheets&&d.sheets.length){{sel.value=d.sheets[0];loadSheet();}}
  }}catch(e){{document.getElementById('xl-table-wrap').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function loadSheet(){{
  const wb=document.getElementById('xl-workbook').value.trim();
  const sh=document.getElementById('xl-sheet').value;if(!wb||!sh)return;
  document.getElementById('xl-table-wrap').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch(`/excel/read?workbook=${{encodeURIComponent(wb)}}&sheet=${{encodeURIComponent(sh)}}`);const d=await r.json();
    const rows=d.data||[];
    if(!rows.length){{document.getElementById('xl-table-wrap').innerHTML='<div class="empty-msg">Sheet is empty</div>';document.getElementById('xl-append').style.display='block';return;}}
    const headers=rows[0];const body=rows.slice(1);
    document.getElementById('xl-table-wrap').innerHTML=`<table class="xl-table">
      <thead><tr>${{headers.map(h=>`<th>${{escH(String(h||''))}}</th>`).join('')}}</tr></thead>
      <tbody>${{body.map(row=>`<tr>${{headers.map((_,i)=>`<td>${{escH(String(row[i]??''))}}</td>`).join('')}}</tr>`).join('')}}</tbody>
    </table>`;
    document.getElementById('xl-append').style.display='block';
  }}catch(e){{document.getElementById('xl-table-wrap').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function appendRow(){{
  const wb=document.getElementById('xl-workbook').value.trim();
  const sh=document.getElementById('xl-sheet').value;
  const vals=[1,2,3,4].map(i=>document.getElementById('xl-v'+i).value).filter(v=>v!=='');
  if(!wb||!sh||!vals.length){{alert('Fill in workbook, sheet and at least one value');return;}}
  const status=document.getElementById('xl-append-status');
  status.textContent='Appending…';status.style.color='#64ffda';
  try{{
    const r=await fetch('/excel/append',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{workbook:wb,sheet:sh,values:vals}})}});
    const d=await r.json();
    if(d.status==='error'){{status.style.color='#ff5555';status.textContent='Error: '+d.message;return;}}
    status.style.color='#64ffda';status.textContent='✅ Row appended!';
    [1,2,3,4].forEach(i=>document.getElementById('xl-v'+i).value='');
    loadSheet();
  }}catch(e){{status.style.color='#ff5555';status.textContent='Error: '+e.message;}}
}}
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE — Full API routes + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/confluence/spaces")
def api_confluence_spaces():
    try:
        from tools.atlassian import list_confluence_spaces
        return jsonify({"spaces": list_confluence_spaces()})
    except Exception as e:
        return jsonify({"spaces": [], "error": str(e)})

@app.route("/confluence/pages")
def api_confluence_pages():
    space_key = request.args.get("space", "")
    try:
        from tools.atlassian import _confluence
        data = _confluence("GET", f"/content?type=page&spaceKey={space_key}&limit=50&expand=title,space")
        pages = [{"id": p["id"], "title": p["title"], "space": p.get("space", {}).get("key", "")} for p in data.get("results", [])]
        return jsonify({"pages": pages})
    except Exception as e:
        return jsonify({"pages": [], "error": str(e)})

@app.route("/confluence/page/<page_id>")
def api_confluence_page_detail(page_id):
    try:
        from tools.atlassian import get_confluence_page
        return jsonify(get_confluence_page(page_id))
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/confluence/create", methods=["POST"])
def api_confluence_create():
    data = request.json or {}
    try:
        from tools.atlassian import create_confluence_page
        result = create_confluence_page(data["space_key"], data["title"], data.get("body", ""))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/confluence/update/<page_id>", methods=["POST"])
def api_confluence_update(page_id):
    data = request.json or {}
    try:
        from tools.atlassian import update_confluence_page
        result = update_confluence_page(page_id, data.get("title"), data.get("body"))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/confluence-page")
def confluence_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Confluence — Work Assistant</title>{_PAGE_STYLE}
<style>
.cf-layout{{display:grid;grid-template-columns:240px 1fr;gap:16px;height:calc(100vh - 195px)}}
.cf-sidebar{{background:#1a1c24;border:1px solid #252836;border-radius:10px;overflow-y:auto;padding:8px 0}}
.cf-main{{background:#1a1c24;border:1px solid #252836;border-radius:10px;display:flex;flex-direction:column;overflow:hidden}}
.cf-item{{padding:7px 14px;cursor:pointer;font-size:13px;color:#8892b0;border-radius:6px;margin:0 6px}}
.cf-item:hover{{background:#1e2028;color:#d4d8e8}}
.cf-item.active{{background:#1c2540;color:#64ffda}}
.cf-hdr{{padding:12px 14px;border-bottom:1px solid #252836;font-size:13px;font-weight:700;color:#d4d8e8;display:flex;justify-content:space-between;align-items:center}}
.cf-body{{flex:1;overflow-y:auto;padding:20px;color:#d4d8e8;font-size:13px;line-height:1.6}}
.sid-hdr{{padding:8px 14px;font-size:10px;font-weight:700;color:#3a4060;letter-spacing:.5px;text-transform:uppercase}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
.page-chip{{padding:10px 14px;background:#12131a;border-radius:6px;cursor:pointer;color:#d4d8e8;font-size:13px;margin-bottom:6px}}
.page-chip:hover{{background:#1e2028}}
.cf-modal{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}}
.cf-modal.open{{display:flex}}
.cf-modal-box{{background:#1a1c24;border:1px solid #252836;border-radius:12px;padding:24px;width:480px;display:flex;flex-direction:column;gap:12px}}
.cf-modal-box h2{{font-size:15px;color:#d4d8e8;margin:0}}
.cf-modal-box input,.cf-modal-box textarea{{background:#12131a;border:1px solid #252836;border-radius:6px;padding:8px 12px;color:#d4d8e8;font-size:13px;width:100%;box-sizing:border-box}}
.cf-modal-box textarea{{min-height:100px;resize:vertical;font-family:inherit}}
.cf-modal-box input:focus,.cf-modal-box textarea:focus{{outline:none;border-color:#64ffda}}
.modal-btns{{display:flex;gap:8px;justify-content:flex-end}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap" style="padding-bottom:0">
  <div class="page-hdr">
    <div><div class="page-title">📖 Confluence</div><div class="page-subtitle">Spaces, pages and documentation</div></div>
    <button class="btn btn-primary" onclick="document.getElementById('cf-modal').classList.add('open')">＋ New Page</button>
  </div>
  <div class="cf-layout">
    <div class="cf-sidebar" id="cf-spaces-list"><div class="empty-msg">Loading…</div></div>
    <div class="cf-main">
      <div class="cf-hdr"><span id="cf-title">Select a space</span><button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836;font-size:11px" onclick="cfRefresh()">↻</button></div>
      <div class="cf-body" id="cf-body"><div class="empty-msg">Pick a space from the sidebar to browse pages</div></div>
    </div>
  </div>
</div>
<div class="cf-modal" id="cf-modal">
  <div class="cf-modal-box">
    <h2>📝 Create Confluence Page</h2>
    <select id="cf-space-sel" style="background:#12131a;border:1px solid #252836;border-radius:6px;padding:8px 12px;color:#d4d8e8;font-size:13px"><option value="">Select space…</option></select>
    <input id="cf-new-title" placeholder="Page title">
    <textarea id="cf-new-body" placeholder="Page body (plain text)"></textarea>
    <div id="cf-create-status" style="font-size:12px;color:#64ffda"></div>
    <div class="modal-btns">
      <button class="btn" onclick="document.getElementById('cf-modal').classList.remove('open')">Cancel</button>
      <button class="btn btn-primary" onclick="createCfPage()">Create</button>
    </div>
  </div>
</div>
<script>
let _cfSpaces=[],_cfActiveSpace=null,_cfActivePage=null;
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
async function loadCfSpaces(){{
  try{{
    const r=await fetch('/confluence/spaces');const d=await r.json();
    _cfSpaces=d.spaces||[];
    const sel=document.getElementById('cf-space-sel');
    sel.innerHTML='<option value="">Select space…</option>'+_cfSpaces.map(s=>`<option value="${{escH(s.key||'')}}">${{escH(s.name||s.key||'')}}</option>`).join('');
    document.getElementById('cf-spaces-list').innerHTML=_cfSpaces.length?
      '<div class="sid-hdr">Spaces</div>'+_cfSpaces.map(s=>`<div class="cf-item" onclick="selectCfSpace('${{escH(s.key||'')}}','${{escH(s.name||s.key||'')}}')"
        >🗂 ${{escH(s.name||s.key||'')}}</div>`).join(''):
      '<div class="empty-msg">No spaces found</div>';
    if(d.error)document.getElementById('cf-spaces-list').innerHTML+=`<div style="padding:8px 14px;font-size:11px;color:#ff5555">${{escH(d.error)}}</div>`;
  }}catch(e){{document.getElementById('cf-spaces-list').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function selectCfSpace(key,name){{
  _cfActiveSpace=key;_cfActivePage=null;
  document.getElementById('cf-title').textContent=name+' — Pages';
  document.getElementById('cf-body').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/confluence/pages?space='+encodeURIComponent(key));const d=await r.json();
    const pages=d.pages||[];
    document.getElementById('cf-body').innerHTML=pages.length?
      pages.map(p=>`<div class="page-chip" onclick="loadCfPage('${{escH(p.id)}}','${{escH(p.title)}}')">📄 ${{escH(p.title)}}</div>`).join(''):
      '<div class="empty-msg">No pages in this space</div>';
    if(d.error)document.getElementById('cf-body').innerHTML+=`<div style="padding:8px;font-size:11px;color:#ff5555">${{escH(d.error)}}</div>`;
  }}catch(e){{document.getElementById('cf-body').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
async function loadCfPage(id,title){{
  _cfActivePage=id;
  document.getElementById('cf-title').textContent=title;
  document.getElementById('cf-body').innerHTML='<div class="empty-msg">Loading…</div>';
  try{{
    const r=await fetch('/confluence/page/'+encodeURIComponent(id));const d=await r.json();
    if(d.error){{document.getElementById('cf-body').innerHTML=`<div class="empty-msg" style="color:#ff5555">${{escH(d.error)}}</div>`;return;}}
    const body=d.body||d.content||'<em>No content</em>';
    document.getElementById('cf-body').innerHTML=`<div style="line-height:1.7">${{body}}</div>`;
  }}catch(e){{document.getElementById('cf-body').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
}}
function cfRefresh(){{if(_cfActivePage)loadCfPage(_cfActivePage,'');else if(_cfActiveSpace)selectCfSpace(_cfActiveSpace,'');}}
async function createCfPage(){{
  const spaceKey=document.getElementById('cf-space-sel').value;
  const title=document.getElementById('cf-new-title').value.trim();
  const body=document.getElementById('cf-new-body').value.trim();
  if(!spaceKey||!title){{alert('Space and title are required');return;}}
  const status=document.getElementById('cf-create-status');
  status.textContent='Creating…';status.style.color='#64ffda';
  try{{
    const r=await fetch('/confluence/create',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{space_key:spaceKey,title,body}})}});
    const d=await r.json();
    if(d.status==='error'){{status.style.color='#ff5555';status.textContent='Error: '+d.message;return;}}
    status.textContent='✅ Page created!';
    setTimeout(()=>{{document.getElementById('cf-modal').classList.remove('open');document.getElementById('cf-create-status').textContent='';if(_cfActiveSpace)selectCfSpace(_cfActiveSpace,'');}},1200);
  }}catch(e){{status.style.color='#ff5555';status.textContent='Error: '+e.message;}}
}}
loadCfSpaces();
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH — API route + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/research/run", methods=["POST"])
def api_research_run():
    data  = request.json or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"status": "error", "message": "Query is required"})
    try:
        from tools.browser_tool import deep_research
        result = deep_research(query, max_sources=data.get("max_sources", 5))
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/research-page")
def research_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Research — Work Assistant</title>{_PAGE_STYLE}
<style>
.research-box{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:20px;margin-bottom:16px}}
.research-input{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.research-input input{{flex:1;min-width:220px;background:#12131a;border:1px solid #252836;border-radius:6px;padding:9px 14px;color:#d4d8e8;font-size:14px}}
.research-input input:focus{{outline:none;border-color:#64ffda}}
.research-results{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:20px;min-height:200px;color:#d4d8e8;font-size:13px;line-height:1.7}}
.sources-list{{margin-top:16px;border-top:1px solid #252836;padding-top:14px}}
.source-chip{{display:inline-block;background:#12131a;border:1px solid #252836;border-radius:14px;padding:3px 10px;font-size:11px;color:#8892b0;margin:3px;text-decoration:none}}
.source-chip:hover{{color:#64ffda;border-color:#243060}}
.empty-msg{{text-align:center;padding:40px;color:#8892b0;font-size:13px}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">🔬 Deep Research</div><div class="page-subtitle">Multi-source AI-powered research with credibility scoring</div></div>
  </div>
  <div class="research-box">
    <div class="research-input">
      <input id="r-query" placeholder="What do you want to research? e.g. latest Python 3.13 features" onkeydown="if(event.key==='Enter')runResearch()">
      <select id="r-sources" style="background:#12131a;border:1px solid #252836;border-radius:6px;padding:9px 11px;color:#d4d8e8;font-size:13px">
        <option value="3">3 sources</option>
        <option value="5" selected>5 sources</option>
        <option value="8">8 sources</option>
      </select>
      <button class="btn btn-primary" id="r-btn" onclick="runResearch()">Research</button>
    </div>
  </div>
  <div class="research-results" id="r-results"><div class="empty-msg">Enter a query above and click Research</div></div>
</div>
<script>
function escH(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
async function runResearch(){{
  const query=document.getElementById('r-query').value.trim();if(!query)return;
  const maxSrc=parseInt(document.getElementById('r-sources').value);
  const btn=document.getElementById('r-btn');btn.textContent='Researching…';btn.disabled=true;
  document.getElementById('r-results').innerHTML='<div class="empty-msg">🔍 Researching across '+maxSrc+' sources… this may take 20–30 seconds</div>';
  try{{
    const r=await fetch('/research/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{query,max_sources:maxSrc}})}});
    const d=await r.json();
    if(d.status==='error'){{document.getElementById('r-results').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(d.message)}}</div>`;return;}}
    const res=d.result||{{}};
    const summary=typeof res==='string'?escH(res):escH(res.summary||res.answer||JSON.stringify(res,null,2));
    const sources=res.sources||[];
    document.getElementById('r-results').innerHTML=
      `<div style="white-space:pre-wrap">${{summary}}</div>`+
      (sources.length?`<div class="sources-list"><div style="font-size:11px;color:#8892b0;margin-bottom:6px;font-weight:700">SOURCES</div>`+
        sources.map(s=>{{const url=typeof s==='string'?s:s.url||'';const title=typeof s==='string'?s:s.title||url;
          return `<a href="${{escH(url)}}" target="_blank" class="source-chip">${{escH(String(title).slice(0,60))}}</a>`;
        }}).join('')+'</div>':'');
  }}catch(e){{document.getElementById('r-results').innerHTML=`<div class="empty-msg" style="color:#ff5555">Error: ${{escH(e.message)}}</div>`;}}
  finally{{btn.textContent='Research';btn.disabled=false;}}
}}
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# BRIEFING — API route + PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/briefing/send", methods=["POST"])
def api_briefing_send():
    try:
        from tools.briefing import send_morning_briefing
        result = send_morning_briefing()
        return jsonify({"status": "ok", "result": str(result)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/briefing-page")
def briefing_page():
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Briefing — Work Assistant</title>{_PAGE_STYLE}
<style>
.brief-card{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:32px;margin-bottom:16px;text-align:center}}
.brief-card h2{{font-size:22px;color:#d4d8e8;margin:0 0 10px}}
.brief-card p{{font-size:13px;color:#8892b0;margin:0 0 22px;max-width:500px;margin-left:auto;margin-right:auto}}
.brief-status{{font-size:13px;margin-top:14px;min-height:22px}}
.brief-what{{background:#1a1c24;border:1px solid #252836;border-radius:10px;padding:20px}}
.brief-what h3{{font-size:14px;color:#d4d8e8;margin:0 0 14px}}
.brief-section{{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-bottom:1px solid #1e2030;font-size:13px;color:#8892b0}}
.brief-section:last-child{{border:none;padding-bottom:0}}
.brief-icon{{font-size:22px;flex-shrink:0;width:32px;text-align:center}}
</style></head><body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div><div class="page-title">☀️ Morning Briefing</div><div class="page-subtitle">Get a complete daily digest sent to your email</div></div>
  </div>
  <div class="brief-card">
    <h2>☀️ Send Today's Briefing</h2>
    <p>Compiles a rich HTML email covering your emails, calendar, Jira issues, GitHub notifications and Slack highlights — sent directly to your inbox</p>
    <button class="btn btn-primary" id="brief-btn" onclick="sendBriefing()" style="font-size:14px;padding:11px 32px">Send My Briefing Now</button>
    <div class="brief-status" id="brief-status"></div>
  </div>
  <div class="brief-what">
    <h3>What's included</h3>
    <div class="brief-section"><div class="brief-icon">📧</div><div><strong style="color:#d4d8e8">Outlook Inbox</strong> — Your 5 most recent unread emails with sender, subject and preview</div></div>
    <div class="brief-section"><div class="brief-icon">📅</div><div><strong style="color:#d4d8e8">Calendar</strong> — Today's meetings and appointments</div></div>
    <div class="brief-section"><div class="brief-icon">🐛</div><div><strong style="color:#d4d8e8">Jira</strong> — Your open issues and high-priority items</div></div>
    <div class="brief-section"><div class="brief-icon">🐙</div><div><strong style="color:#d4d8e8">GitHub</strong> — Notifications, open PRs and review requests</div></div>
    <div class="brief-section"><div class="brief-icon">💬</div><div><strong style="color:#d4d8e8">Slack</strong> — Recent messages from your channels</div></div>
  </div>
</div>
<script>
async function sendBriefing(){{
  const btn=document.getElementById('brief-btn');const status=document.getElementById('brief-status');
  btn.textContent='Sending…';btn.disabled=true;status.textContent='Building your briefing…';status.style.color='#64ffda';
  try{{
    const r=await fetch('/briefing/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}});
    const d=await r.json();
    if(d.status==='error'){{status.style.color='#ff5555';status.textContent='Error: '+d.message;return;}}
    status.style.color='#64ffda';status.textContent='✅ Briefing sent to your inbox!';
  }}catch(e){{status.style.color='#ff5555';status.textContent='Error: '+e.message;}}
  finally{{btn.textContent='Send My Briefing Now';btn.disabled=false;}}
}}
</script></body></html>"""
    return html


# ══════════════════════════════════════════════════════════════════════════════
# JIRA ACTIONS — transition + comment
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/jira/transition", methods=["POST"])
def api_jira_transition():
    data = request.json or {}
    try:
        from tools.atlassian import transition_jira_issue
        result = transition_jira_issue(data["issue_key"], data["status"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/jira/comment", methods=["POST"])
def api_jira_comment():
    data = request.json or {}
    try:
        from tools.atlassian import add_jira_comment
        result = add_jira_comment(data["issue_key"], data["comment"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# LINEAR ACTIONS — transition + comment
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/linear/transition", methods=["POST"])
def api_linear_transition():
    data = request.json or {}
    try:
        from tools.linear_tool import transition_linear_issue
        result = transition_linear_issue(data["issue_id"], data["status"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/linear/comment", methods=["POST"])
def api_linear_comment():
    data = request.json or {}
    try:
        from tools.linear_tool import add_linear_comment
        result = add_linear_comment(data["issue_id"], data["comment"])
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# NOTION CREATE PAGE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/notion/create-page", methods=["POST"])
def api_notion_create():
    data = request.json or {}
    try:
        from tools import notion_tool
        result = notion_tool.create_notion_page(data["title"], data.get("content", ""), data.get("parent_id"))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# ZOOM CREATE MEETING
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/zoom/create", methods=["POST"])
def api_zoom_create():
    data = request.json or {}
    try:
        from tools.zoom_tool import create_zoom_meeting
        result = create_zoom_meeting(data["topic"], data.get("start_time"), data.get("duration", 60))
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import webbrowser
    os.chdir(Path(__file__).parent)

    # Start proactive monitoring
    try:
        from tools.proactive import start_monitoring
        start_monitoring()
        print("     Proactive monitoring: ✅  started")
    except Exception as e:
        print(f"     Proactive monitoring: ⚠️  unavailable ({e})")

    # Start daily briefing scheduler
    try:
        from tools.briefing import start_briefing_scheduler
        start_briefing_scheduler()
        print("     Daily briefing:       ✅  scheduled")
    except Exception as e:
        print(f"     Daily briefing:       ⚠️  unavailable ({e})")

    try:
        from tools.auto_ingest import start_auto_ingest_scheduler
        start_auto_ingest_scheduler()
    except Exception as e:
        print(f"[auto_ingest] scheduler not started: {e}")

    # Cloudflare tunnel
    threading.Thread(target=_start_tunnel, daemon=True).start()

    # Open browser — skip if restarted via the UI (--no-browser flag)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    print(f"\n🚀  Work Assistant starting at http://localhost:{PORT}")
    print(f"     Press Ctrl+C to stop.\n")

    # Smart briefing timing — record app open (Feature 4)
    try:
        from tools.self_learning import record_app_open
        record_app_open()
    except Exception:
        pass

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
