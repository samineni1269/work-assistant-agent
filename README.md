# ⚡ Work Assistant Agent

> An AI-powered work companion that handles your day-to-day company tasks in plain English — emails, calendar, GitHub, Jira, Linear, Teams, SharePoint, Confluence, Excel, Zoom, and more — all from a single browser tab.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-black?logo=flask)
![License](https://img.shields.io/badge/License-MIT-green)
![Providers](https://img.shields.io/badge/AI-Gemini%20%7C%20Claude%20%7C%20GPT--4o%20%7C%20MiniMax-purple)

---

## What it does

Type a request in plain English. The agent figures out which tools to call, does the work, and gives you a clean summary — no switching between apps, no manual copy-pasting.

```
> Show my PRs to review
> Create a Jira bug in MYPROJ: login crashes on mobile
> Summarise my unread emails
> What meetings do I have today?
> Move LINEAR-42 to In Progress
> Write my standup and post it to the dev-team channel
```

---

## Features

### 🔗 Integrations (13 services)

| Category | Services |
|---|---|
| **Email & Calendar** | Outlook, Microsoft Calendar |
| **Messaging** | Microsoft Teams (chats + channels) |
| **Project Management** | Jira (issues, transitions, comments), Linear (issues, projects) |
| **Docs & Knowledge** | Confluence (search, read, create, update), SharePoint |
| **Code & CI** | GitHub (notifications, PRs, issues, CI status, merge) |
| **Office Files** | Excel/OneDrive (read, write cells, append rows), Word (read, create, update), PowerPoint (read, create, add slides) |
| **Video Meetings** | Zoom (list, create, recordings), Google Meet (create via Calendar) |

### 🌐 Web UI (Flask)
- Clean dark-themed browser UI at `http://localhost:7432`
- **50+ quick-action buttons** organised into 13 categories in the sidebar
- Live connection status for all integrations
- Searchable action sidebar
- No install of native GUI dependencies needed

### 🤖 Multi-Provider AI
Switch between any of these by setting one environment variable:

| Provider | Key | Default Model |
|---|---|---|
| **Google Gemini** | `GEMINI_API_KEY` | `gemini-2.5-flash` |
| **Anthropic Claude** | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-4o` |
| **OpenRouter** | `OPENROUTER_API_KEY` | `anthropic/claude-sonnet-4-5` |
| **MiniMax** | `MINIMAX_API_KEY` | `MiniMax-Text-01` |

Auto-detects which provider to use based on which API keys are set. Override with `LLM_PROVIDER=claude` (or any provider name).

### 🛡 Security Guardrails (4, each toggleable)

Each guardrail can be toggled ON/OFF individually from the sidebar — no restart needed.

| Guardrail | What it does |
|---|---|
| 🧠 **Prompt Injection Defence** | Scans emails, tickets, and docs for embedded instructions that try to hijack the agent |
| 🔑 **Secret / Credential Scrubbing** | Redacts API keys, tokens, and passwords from every response before it reaches the screen |
| 📋 **Write-Op Audit Log** | Logs every write action (send email, create ticket, merge PR) with a timestamp to `audit.log` |
| 🚧 **Bulk-Op Protection** | Caps tool calls per turn (max 12) and email fetches (max 50) to prevent runaway loops |

Settings persist in `guardrail_settings.json` across restarts.

### ✅ Confirmation-First Write Ops
Every destructive or write operation (send email, create ticket, post message, merge PR) asks for confirmation before it executes. Read-only operations run immediately.

---

## Quick Start

### Prerequisites

- Python 3.11 or newer
- At least **one AI API key** (Gemini is free — see below)
- The integrations you want to use (Microsoft 365, Atlassian, GitHub, etc.)

### 1. Clone and install

```bash
git clone https://github.com/samineni1269/work-assistant-agent.git
cd work-assistant-agent

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Open .env in any editor and fill in your keys
```

See [Credential Setup](#credential-setup) below for where to get each key.

### 3. Launch

**Mac — double-click `launch.command`** (right-click → Open the first time to bypass Gatekeeper)

**Or run directly:**
```bash
python app.py
```

The browser opens automatically at `http://localhost:7432`.

---

## Credential Setup

### 🆓 Google Gemini (free tier, 1500 req/day)

1. Go to **https://aistudio.google.com/apikey**
2. Sign in → **Create API key** → copy it
3. Add to `.env`: `GEMINI_API_KEY=AIzaSy...`

### 🏢 Microsoft 365 (Outlook, Teams, SharePoint, Excel, Word, PPT)

Register a free Azure AD app (one-time, ~5 minutes):

1. Go to **https://portal.azure.com** → search **"App registrations"** → **New registration**
2. Name: anything (e.g. `Work Assistant`)
3. Account types: **"Accounts in any organizational directory and personal Microsoft accounts"**
4. Redirect URI: **Public client/native** → `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. Click **Register** → copy the **Application (client) ID** → this is `MS_CLIENT_ID`
6. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated**
7. Add these permissions:
   - `Mail.ReadWrite`, `Mail.Send`
   - `Calendars.ReadWrite`
   - `Chat.ReadWrite`, `ChannelMessage.Read.All`
   - `Files.ReadWrite.All`, `Sites.Read.All`
   - `User.Read`, `offline_access`
8. Click **Grant admin consent** (or ask your IT admin)

```env
MS_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MS_TENANT_ID=common
```

> On first run, a browser window will open asking you to sign in to your Microsoft account. After that, the token is cached locally and sign-in is automatic.

### 🟠 Atlassian (Jira + Confluence)

1. Go to **https://id.atlassian.com/manage-profile/security/api-tokens**
2. **Create API token** → copy it
3. Your domain is the prefix of your Jira URL: `mycompany.atlassian.net`

```env
ATLASSIAN_EMAIL=you@company.com
ATLASSIAN_API_TOKEN=ATATTx...
ATLASSIAN_DOMAIN=mycompany.atlassian.net
```

### 🐙 GitHub

1. Go to **https://github.com/settings/tokens** → **Generate new token (classic)**
2. Required scopes: `repo`, `notifications`, `read:user`

```env
GITHUB_TOKEN=ghp_...
```

### 📐 Linear

1. Go to **https://linear.app/settings/api** → **Personal API keys** → create one

```env
LINEAR_API_KEY=lin_api_...
```

### 📹 Zoom

1. Go to **https://marketplace.zoom.us** → **Build App** → **Server-to-Server OAuth**
2. Copy Account ID, Client ID, Client Secret
3. Activate the app and add scopes: `meeting:read`, `meeting:write`, `recording:read`

```env
ZOOM_ACCOUNT_ID=...
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
```

### 🎥 Google Meet (via Google Calendar API)

1. Go to **https://console.cloud.google.com/apis/credentials**
2. **Create credentials** → **OAuth client ID** → **Desktop app**
3. Enable the **Google Calendar API** for your project
4. Copy Client ID and Client Secret

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
```

### 🤖 Other AI Providers (optional)

```env
# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
OPENAI_API_KEY=sk-...

# OpenRouter (100+ models via one key)
OPENROUTER_API_KEY=sk-or-...

# MiniMax Token Plan
MINIMAX_API_KEY=sk-cp-...
```

---

## Usage

### Web UI (recommended)

```bash
python app.py
# Opens http://localhost:7432 automatically
```

Use the sidebar to browse 50+ quick actions, or type anything in the chat input.

### Command-line modes

```bash
# Interactive chat
python agent.py

# One-shot daily briefing (calendar + emails + Jira)
python agent.py briefing

# One-shot standup summary (paste-ready)
python agent.py standup
```

### Automated scheduler

```bash
# Run briefing at 09:00 and standup at 09:15 every weekday
python scheduler.py

# Fire both jobs right now (for testing)
python scheduler.py now
```

Customise times in `.env`:
```env
BRIEFING_TIME=08:30
STANDUP_TIME=08:45
```

---

## Example prompts

```
# Email
Summarise my unread emails
Draft a reply to the latest email from Sarah
Search my emails for "budget approval"

# Calendar
What meetings do I have today?
Create a 30-min meeting with john@company.com tomorrow at 2pm

# GitHub
Show my unread GitHub notifications
List open PRs where my review is requested
Check CI status for repo myorg/backend, PR 142
Create a GitHub issue in myorg/backend: API returns 500 on logout

# Jira
Show all Jira issues assigned to me
Create a bug in PROJ: login crashes on mobile, priority high
Move PROJ-55 to In Progress
Add a comment to PROJ-88: deployed fix to staging, awaiting QA

# Linear
Show my Linear issues grouped by state
Create a Linear issue in Backend team: refactor auth middleware
Move LIN-34 to Done

# Teams
Show my recent Teams chats
Post a message to the dev-team channel: deployment complete ✅

# Confluence / SharePoint
Search Confluence for "API design guidelines"
Read the Confluence page "Onboarding Checklist"
Search SharePoint for the Q3 budget spreadsheet

# Files
Read the file Budget.xlsx, sheet "Q2"
Append a row to Tracker.xlsx: ["Task A", "Done", "2024-06-01"]
Create a Word doc "Meeting Notes June": [content]

# Meetings
Create a Zoom meeting "Sprint Review" tomorrow at 3pm for 1 hour
Show my upcoming Zoom meetings with join links
Create a Google Meet for "Design Sync" on Friday at 11am

# Standup
Write my standup based on yesterday's Jira and GitHub activity
```

---

## Project structure

```
work-assistant-agent/
├── app.py                  # Flask web UI + REST API
├── agent.py                # Core agent loop (tool calling, history, confirmation)
├── scheduler.py            # Automated briefing/standup scheduler
├── setup_wizard.py         # Interactive credential setup wizard
├── launch.command          # Mac double-click launcher
├── setup.command           # Mac first-time setup launcher
├── setup.bat               # Windows first-time setup launcher
├── requirements.txt        # Python dependencies
├── .env.example            # Template for credentials (copy → .env)
├── .gitignore
├── tools/
│   ├── llm_provider.py     # Multi-provider AI abstraction (Gemini/Claude/OpenAI/etc.)
│   ├── guardrails.py       # 4 toggleable security guardrails
│   ├── ms365.py            # Microsoft 365 (Outlook, Teams, SharePoint, Calendar)
│   ├── atlassian.py        # Jira + Confluence
│   ├── github_tool.py      # GitHub (notifications, PRs, issues, CI, merge)
│   ├── linear_tool.py      # Linear issues + projects
│   ├── office_docs.py      # Excel, Word, PowerPoint
│   └── zoom_meet.py        # Zoom + Google Meet
└── guardrail_settings.json # Persisted guardrail ON/OFF state (auto-created)
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `MS_CLIENT_ID not set` | Check your `.env` file — copy from `.env.example` and fill in values |
| `Microsoft sign-in required on every run` | Run from the same directory each time so the token cache persists |
| `Jira 401 Unauthorized` | Wrong email or API token — re-check `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN` |
| `Confluence 404` | The space key or page ID doesn't exist — search first to find valid IDs |
| `quota exceeded` (Gemini) | Free tier: 60 req/min. Wait a moment and retry, or switch to a paid provider |
| `GitHub 401` | Token expired or missing scopes — regenerate at github.com/settings/tokens |
| Slow responses | Normal for multi-step requests (briefing = 3+ API calls). Expect 5–15s for complex tasks |
| Guardrail blocked my message | The message matched an injection pattern — rephrase or toggle the guardrail off temporarily |

---

## Security notes

- Your `.env` file contains sensitive credentials — it is in `.gitignore` and must never be committed
- Microsoft tokens are cached at `~/.work-assistant-token-cache.json` — this is private and local only
- The agent never writes email content, ticket data, or messages to disk — all processing is in memory
- Guardrail audit logs are written to `audit.log` in the project directory (`.gitignore`d)
- To revoke Microsoft access: delete `~/.work-assistant-token-cache.json` and remove the Azure AD app registration

---

## Switching AI provider

Set `LLM_PROVIDER` in `.env` to any of: `gemini`, `claude`, `openai`, `openrouter`, `minimax`

```env
LLM_PROVIDER=claude
LLM_MODEL=claude-opus-4-6   # optional: override the default model
```

Leave `LLM_PROVIDER` blank for auto-detection (uses the first key found in priority order: gemini → claude → openai → openrouter → minimax).

---

## Contributing

Pull requests welcome! To add a new integration:

1. Create `tools/mytool.py` — implement tool functions that return plain strings
2. Register the tool definitions in `agent.py` (`TOOL_DEFINITIONS` list)
3. Add the tool dispatcher case in `_dispatch_tool()` in `agent.py`
4. Add sidebar quick-action buttons in `SIDEBAR_GROUPS` in `app.py`
5. Add the required env vars to `.env.example` and `INTEGRATIONS` in `app.py`

---

## License

MIT — free to use, modify, and distribute.
