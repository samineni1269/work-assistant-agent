"""
app.py — Work Assistant Web UI
================================
Tool-navigation UI: each app (Outlook, Teams, Jira, etc.) has its own
workspace with its own conversation history. Free-form chat in every tool.

Run:  python3 app.py
"""

import os
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
<div style="background:#1a1c24;border-bottom:1px solid #252836;padding:10px 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap">
  <a href="/" style="font-size:13px;font-weight:700;color:#64ffda;text-decoration:none">⚡ Work Assistant</a>
  <span style="color:#252836">|</span>
  <a href="/actions-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">✅ Actions</a>
  <a href="/triggers-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">⚡ Automation</a>
  <a href="/memory-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">🧠 Memory</a>
  <a href="/scheduler-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">🕐 Scheduler</a>
  <a href="/search-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">🔍 Search</a>
  <a href="/inbox-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">📧 Inbox</a>
  <a href="/calendar-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">📅 Calendar</a>
  <a href="/documents-page" style="font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px" onmouseover="this.style.color='#d4d8e8'" onmouseout="this.style.color='#8892b0'">📄 Documents</a>
</div>
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
        # Try to send via M365 if configured
        from tools.ms365 import send_email
        # Extract a recipient from context if available (basic heuristic)
        import re as _re
        emails = _re.findall(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
                              email_context)
        if not emails:
            return jsonify({"ok": False, "error": "No recipient found in email context. Copy the draft manually."}), 400
        result = send_email(to=emails[0], subject="Re: (Work Assistant draft)", body=draft)
        return jsonify({"ok": True, "result": str(result)})
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

async function refreshInbox(){{
  document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Loading emails…</div></div>';
  try{{
    // Call the agent to fetch emails
    const r=await fetch('/chat',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:'List my 10 most recent unread emails with sender, subject, date, and a 2-sentence summary. Return as JSON array with fields: sender, subject, date, summary, body_preview.',tool_id:'outlook'}})}}).then(r=>r.json());
    if(r.error)throw new Error(r.error);
    // Poll for result
    let tries=0;
    const poll=async()=>{{
      const j=await fetch('/poll/'+r.job_id).then(r=>r.json());
      if(j.status==='done'){{
        renderEmailsFromText(j.response);
        return;
      }}
      if(j.status==='error'){{
        document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">⚠️</div><div class="empty-state-txt">'+_esc(j.response)+'</div></div>';
        return;
      }}
      if(++tries<60)setTimeout(poll,1000);
    }};
    setTimeout(poll,1000);
  }}catch(e){{
    document.getElementById('inbox-list').innerHTML='<div class="empty-state"><div class="empty-state-icon">📧</div><div class="empty-state-txt">Connect Outlook in .env to load emails.<br><small style="color:#3a4060">M365 credentials required</small></div></div>';
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

async function refreshCalendar(){{
  const days=getWeekDates(_weekOffset);
  renderCalendar(days,[]);
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
    document.getElementById('cal-wrap').innerHTML='<div class="empty-state"><div class="empty-state-icon">📅</div><div class="empty-state-txt">Connect Outlook to load calendar events.<br><small style="color:#3a4060">M365 credentials required</small></div></div>';
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

    # Cloudflare tunnel
    threading.Thread(target=_start_tunnel, daemon=True).start()

    # Open browser
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    print(f"\n🚀  Work Assistant starting at http://localhost:{PORT}")
    print(f"     Press Ctrl+C to stop.\n")

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
