# Work Assistant Agent — Setup Guide

## What this agent does

This agent is your AI-powered work companion. You talk to it in plain English and it handles your day-to-day company tasks — reading emails, checking your calendar, creating Jira tickets, searching SharePoint docs, writing Confluence pages, sending Teams messages, and updating spreadsheets — all without switching between apps.

### Capabilities at a glance

| Tool | What the agent can do |
|---|---|
| **Outlook** | Read emails, summarise inbox, draft & send replies, search by keyword |
| **Calendar** | List today's meetings, create new events with Teams link |
| **Teams** | Read chat messages, send messages, post to channels |
| **SharePoint** | Search documents, list files in any drive/folder |
| **Excel (OneDrive)** | Read spreadsheets, write cells, append rows |
| **Jira** | List my issues, search by JQL, create tickets, update issues, transition status, add comments |
| **Confluence** | Search pages, read page content, create pages, update pages |

### Zero-mistake protection

Every **write operation** (send, create, update, delete) shows you a full preview and asks for your confirmation before it executes. Read operations (fetching, searching, listing) run instantly with no confirmation needed.

---

## Requirements

- Python 3.11 or newer
- Internet connection
- A free Google Gemini API key
- Microsoft 365 work/school account (Outlook, Teams, SharePoint, Excel)
- Atlassian account with Jira + Confluence access

---

## Setup

### Step 1 — Get your Gemini API key

1. Go to **https://aistudio.google.com/apikey**
2. Sign in with your Google account
3. Click **Create API key** → copy the key (starts with `AIza...`)

---

### Step 2 — Register a Microsoft Azure AD app (for Outlook, Teams, SharePoint, Excel)

This is a one-time setup to connect the agent to your Microsoft 365 account. It's free and takes about 5 minutes.

1. Go to **https://portal.azure.com** and sign in with your work/school Microsoft account
2. Search for **"App registrations"** in the top search bar → click it
3. Click **"New registration"**
4. Fill in:
   - **Name:** `Work Assistant Agent` (anything is fine)
   - **Supported account types:** Select **"Accounts in any organizational directory and personal Microsoft accounts"** (the second option) — this works for both work and personal accounts
   - **Redirect URI:** Choose **"Public client / native"** from the dropdown, then enter:
     ```
     https://login.microsoftonline.com/common/oauth2/nativeclient
     ```
5. Click **Register**
6. On the next page, copy the **Application (client) ID** — this is your `MS_CLIENT_ID`
7. Click **"API permissions"** in the left sidebar
8. Click **"Add a permission"** → **"Microsoft Graph"** → **"Delegated permissions"**
9. Search for and add each of these permissions (one by one):
   - `Mail.ReadWrite`
   - `Mail.Send`
   - `Calendars.ReadWrite`
   - `Chat.ReadWrite`
   - `ChannelMessage.Read.All`
   - `Files.ReadWrite.All`
   - `Sites.Read.All`
   - `User.Read`
   - `offline_access`
10. Click **"Grant admin consent"** (if you have admin rights) — or ask your IT admin to do this

Your `MS_TENANT_ID` can be left as `common` unless your IT team tells you otherwise.

> **Note:** On first run the agent will open a browser page asking you to sign into your Microsoft account. After that, it stays logged in automatically (token is cached locally).

---

### Step 3 — Get your Atlassian API token (for Jira + Confluence)

1. Go to **https://id.atlassian.com/manage-profile/security/api-tokens**
2. Sign in with your Atlassian account
3. Click **"Create API token"** → give it a name → copy the token
4. Your domain is the part of your Jira URL before `.atlassian.net` — e.g. if your Jira is `https://mycompany.atlassian.net` then your domain is `mycompany.atlassian.net`

---

### Step 4 — Save your credentials to the .env file

1. Find the file called `.env.example` in the `work-assistant-agent` folder
2. Make a copy of it and rename the copy to `.env`
3. Open `.env` in any text editor (Notepad on Windows, TextEdit on Mac)
4. Fill in your values:

```
GEMINI_API_KEY=AIzaSy...your key...
MS_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MS_TENANT_ID=common
ATLASSIAN_EMAIL=you@yourcompany.com
ATLASSIAN_API_TOKEN=your_token_here
ATLASSIAN_DOMAIN=yourcompany.atlassian.net
```

5. Save the file. Never share it or commit it to git.

---

### Step 5 — Install Python packages

Open Terminal (Mac) or Command Prompt (Windows) and navigate to the `work-assistant-agent` folder:

```
cd ~/Desktop/work-assistant-agent
```

Create a virtual environment and install packages:

**Mac / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

---

### Step 6 — Run the agent

**Interactive chat mode** (type requests in plain English):
```bash
python agent.py
```

**One-shot daily briefing** (calendar + emails + Jira):
```bash
python agent.py briefing
```

**One-shot standup summary** (paste-ready):
```bash
python agent.py standup
```

**Automated scheduler** (runs briefing at 09:00 and standup at 09:15 every day):
```bash
python scheduler.py
```

**Test scheduler immediately** (fires both jobs now):
```bash
python scheduler.py now
```

---

## Example commands (chat mode)

Once running, type any of these:

```
What's on my calendar today?
Summarise my unread emails
Give me my daily briefing
Draft a reply to the email from Sarah about the Q3 report
Create a Jira bug in project MYPROJ: login button broken on mobile
Move PROJ-42 to In Progress
Add a comment to PROJ-55: reviewed and approved
Search SharePoint for the architecture decision document
Read the Budget.xlsx spreadsheet — sheet "Q2"
Append a new row to Budget.xlsx: ["Marketing", "1500", "June"]
Create a Confluence page in space DEV titled "API Design Guidelines"
Write my standup summary and send it to the team chat
What meetings do I have this week?
List my Teams chats
```

---

## If something goes wrong

**"MS_CLIENT_ID not set"**
→ Your `.env` file is missing or the key is misspelled. Check Step 4.

**"Microsoft 365 Sign-In Required" on every run**
→ The token cache isn't persisting. Make sure you're running from the same folder each time.

**"Jira API error 401"**
→ Wrong API token or email. Re-check `ATLASSIAN_EMAIL` and `ATLASSIAN_API_TOKEN` in `.env`.

**"Confluence API error 404"**
→ The page ID or space ID doesn't exist. Use `list_confluence_spaces` first to find valid IDs.

**"quota exceeded" (Gemini)**
→ You've hit the free-tier rate limit (60 requests/min). Wait a moment and try again.

**Agent is slow to respond**
→ Normal for complex requests that need multiple API calls. Gemini's function calling is sequential — a briefing with 3 data sources takes ~5–10 seconds.

---

## Security notes

- Your `.env` file contains sensitive credentials — never commit it to git (`.gitignore` covers this)
- Microsoft tokens are cached at `~/.work-assistant-token-cache.json` — this file is also private
- The agent never stores email content or Jira data to disk — all processing is in memory
- To revoke access: delete `~/.work-assistant-token-cache.json` and remove the app from your Azure AD app registrations
