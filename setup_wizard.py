#!/usr/bin/env python3
"""
Work Assistant Agent — Interactive Setup Wizard
================================================
Run this once per machine / per person to configure credentials.
Guides you step-by-step, tests each connection, and saves your .env file.

Usage:
  python setup_wizard.py          # full setup
  python setup_wizard.py --test   # re-test existing .env without re-entering keys
"""

import os
import sys
import json
import time
import base64
import subprocess
from pathlib import Path

# ── Bootstrap rich (may not be installed yet) ────────────────────────────────
def _ensure_rich():
    try:
        import rich  # noqa
    except ImportError:
        print("Installing required packages (first time only)…")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "rich", "--quiet",
             "--break-system-packages"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

_ensure_rich()

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()
ENV_PATH = Path(__file__).parent / ".env"

# ── Credential definitions ────────────────────────────────────────────────────
STEPS = [
    # ── LLM PROVIDERS ────────────────────────────────────────────────────────
    {
        "group": "🤖  AI Brain — LLM Provider",
        "intro": (
            "The agent needs at least ONE AI provider key to function.\n"
            "You can set multiple — the agent auto-selects based on availability.\n"
            "Auto-detection priority: Gemini → Claude → OpenAI → OpenRouter\n"
            "Or pin a specific provider by setting LLM_PROVIDER."
        ),
        "fields": [
            {
                "key": "GEMINI_API_KEY",
                "label": "Google Gemini API Key",
                "url": "https://aistudio.google.com/apikey",
                "instructions": (
                    "FREE tier available. Recommended default.\n"
                    "   1. Open the URL above → click [bold]Create API key[/bold]\n"
                    "   2. Copy and paste it here (starts with AIza...)"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": "gemini",
            },
            {
                "key": "ANTHROPIC_API_KEY",
                "label": "Anthropic Claude API Key",
                "url": "https://console.anthropic.com/settings/keys",
                "instructions": (
                    "Paid API — great for complex reasoning.\n"
                    "   1. Open the URL above → click [bold]Create Key[/bold]\n"
                    "   2. Copy and paste it here (starts with sk-ant-...)"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": "claude",
            },
            {
                "key": "OPENAI_API_KEY",
                "label": "OpenAI API Key",
                "url": "https://platform.openai.com/api-keys",
                "instructions": (
                    "Paid API — GPT-4o and other OpenAI models.\n"
                    "   1. Open the URL above → click [bold]Create new secret key[/bold]\n"
                    "   2. Copy and paste it here (starts with sk-proj-...)"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": "openai",
            },
            {
                "key": "OPENROUTER_API_KEY",
                "label": "OpenRouter API Key",
                "url": "https://openrouter.ai/keys",
                "instructions": (
                    "Access 100+ models (Claude, GPT-4, Mistral, Llama, etc.) with one key.\n"
                    "   1. Open the URL above → click [bold]Create Key[/bold]\n"
                    "   2. Copy and paste it here (starts with sk-or-...)"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": None,
            },
            {
                "key": "MINIMAX_API_KEY",
                "label": "MiniMax API Key (Token Plan)",
                "url": "https://platform.minimax.io/user-center/payment/token-plan",
                "instructions": (
                    "Your Token Plan key — works for the Starter plan and above.\n"
                    "   1. Open the URL above → scroll to [bold]API Key[/bold] section\n"
                    "   2. Copy your key (starts with [bold]sk-cp-...[/bold])\n"
                    "   Quota: 1,500 requests / 5 hours (Starter plan)"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": "minimax",
            },
            {
                "key": "LLM_PROVIDER",
                "label": "LLM Provider override (optional)",
                "url": None,
                "instructions": (
                    "Leave blank to auto-select based on whichever key(s) you set above.\n"
                    "   Or type one of: [bold]gemini[/bold]  [bold]claude[/bold]  [bold]openai[/bold]  [bold]openrouter[/bold]"
                ),
                "required": False,
                "secret": False,
                "default": "",
                "test": None,
            },
            {
                "key": "LLM_MODEL",
                "label": "LLM Model override (optional)",
                "url": None,
                "instructions": (
                    "Leave blank to use the default model for your provider.\n"
                    "   Defaults: Gemini → gemini-2.5-flash · Claude → claude-sonnet-4-6\n"
                    "            OpenAI → gpt-4o · OpenRouter → anthropic/claude-sonnet-4-5"
                ),
                "required": False,
                "secret": False,
                "default": "",
                "test": None,
            },
        ],
    },
    # ── MICROSOFT 365 ────────────────────────────────────────────────────────
    {
        "group": "📧  Microsoft 365 (Outlook · Teams · SharePoint · Excel · Word · PowerPoint)",
        "intro": "One Azure AD app registration unlocks all Microsoft services.\nIf someone in your company already registered this app, ask them for the Client ID.",
        "fields": [
            {
                "key": "MS_CLIENT_ID",
                "label": "Azure App Client ID",
                "url": "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps",
                "instructions": (
                    "1. Sign in to portal.azure.com\n"
                    "   2. [bold]App registrations[/bold] → [bold]New registration[/bold]\n"
                    "   3. Name it anything (e.g. 'Work Assistant')\n"
                    "   4. Supported account types: [bold]Accounts in any org + personal[/bold]\n"
                    "   5. Copy [bold]Application (client) ID[/bold]\n"
                    "   6. Go to [bold]API permissions[/bold] → Add:\n"
                    "      Mail.ReadWrite, Mail.Send, Calendars.ReadWrite,\n"
                    "      Chat.ReadWrite, ChannelMessage.Send,\n"
                    "      Files.ReadWrite.All, Sites.ReadWrite.All,\n"
                    "      User.Read  (all Microsoft Graph, Delegated)"
                ),
                "required": True,
                "secret": False,
                "default": None,
                "test": None,
            },
            {
                "key": "MS_TENANT_ID",
                "label": "Tenant ID",
                "url": None,
                "instructions": (
                    "Use [bold]common[/bold] if you want to support both personal\n"
                    "   and work Microsoft accounts.\n"
                    "   Use your company's tenant GUID to restrict to your org only.\n"
                    "   (Find it in Azure Portal → Azure Active Directory → Overview)"
                ),
                "required": True,
                "secret": False,
                "default": "common",
                "test": None,
            },
        ],
    },
    # ── ATLASSIAN ────────────────────────────────────────────────────────────
    {
        "group": "🎯  Atlassian (Jira · Confluence)",
        "intro": "Lets the agent read and create Jira tickets and Confluence pages.",
        "fields": [
            {
                "key": "ATLASSIAN_EMAIL",
                "label": "Atlassian account email",
                "url": None,
                "instructions": "The email address you use to log in to Jira/Confluence",
                "required": True,
                "secret": False,
                "default": None,
                "test": None,
            },
            {
                "key": "ATLASSIAN_API_TOKEN",
                "label": "Atlassian API Token",
                "url": "https://id.atlassian.com/manage-profile/security/api-tokens",
                "instructions": (
                    "1. Open the URL above\n"
                    "   2. Click [bold]Create API token[/bold]\n"
                    "   3. Give it any label (e.g. 'Work Assistant')\n"
                    "   4. Copy and paste the token here"
                ),
                "required": True,
                "secret": True,
                "default": None,
                "test": "atlassian",
            },
            {
                "key": "ATLASSIAN_DOMAIN",
                "label": "Atlassian domain",
                "url": None,
                "instructions": (
                    "Your Jira/Confluence URL without https://\n"
                    "   Example: [bold]your-company.atlassian.net[/bold]"
                ),
                "required": True,
                "secret": False,
                "default": None,
                "test": None,
            },
        ],
    },
    # ── GITHUB ───────────────────────────────────────────────────────────────
    {
        "group": "🐙  GitHub",
        "intro": "Access pull requests, code reviews, notifications, and issues.",
        "fields": [
            {
                "key": "GITHUB_TOKEN",
                "label": "GitHub Personal Access Token",
                "url": "https://github.com/settings/tokens/new",
                "instructions": (
                    "1. Open the URL above\n"
                    "   2. Give it a name (e.g. 'Work Assistant')\n"
                    "   3. Expiration: No expiration (or 1 year)\n"
                    "   4. Tick these scopes: [bold]repo[/bold], [bold]notifications[/bold], [bold]read:user[/bold]\n"
                    "   5. Click [bold]Generate token[/bold] → copy it here"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": "github",
            },
        ],
    },
    # ── LINEAR ───────────────────────────────────────────────────────────────
    {
        "group": "📐  Linear",
        "intro": "Manage Linear issues and projects (popular at startups and fast-moving teams).",
        "fields": [
            {
                "key": "LINEAR_API_KEY",
                "label": "Linear API Key",
                "url": "https://linear.app/settings/api",
                "instructions": (
                    "1. Open the URL above (sign in first)\n"
                    "   2. Scroll to [bold]Personal API keys[/bold]\n"
                    "   3. Click [bold]Create key[/bold] → copy it here"
                ),
                "required": False,
                "secret": True,
                "default": None,
                "test": "linear",
            },
        ],
    },
    # ── ZOOM ─────────────────────────────────────────────────────────────────
    {
        "group": "📹  Zoom",
        "intro": "Schedule, list, and manage Zoom meetings.",
        "fields": [
            {
                "key": "ZOOM_ACCOUNT_ID",
                "label": "Zoom Account ID",
                "url": "https://marketplace.zoom.us/develop/create",
                "instructions": (
                    "1. Open the URL above → choose [bold]Server-to-Server OAuth[/bold]\n"
                    "   2. Name the app and click [bold]Create[/bold]\n"
                    "   3. Under [bold]App Credentials[/bold] copy [bold]Account ID[/bold]"
                ),
                "required": False,
                "secret": False,
                "default": None,
                "test": None,
            },
            {
                "key": "ZOOM_CLIENT_ID",
                "label": "Zoom Client ID",
                "url": None,
                "instructions": "Copy [bold]Client ID[/bold] from the same Zoom app page",
                "required": False,
                "secret": False,
                "default": None,
                "test": None,
            },
            {
                "key": "ZOOM_CLIENT_SECRET",
                "label": "Zoom Client Secret",
                "url": None,
                "instructions": "Copy [bold]Client Secret[/bold] from the same Zoom app page",
                "required": False,
                "secret": True,
                "default": None,
                "test": "zoom",
            },
        ],
    },
    # ── GOOGLE MEET ──────────────────────────────────────────────────────────
    {
        "group": "🎥  Google Meet",
        "intro": "Create Google Meet meetings via Google Calendar.",
        "fields": [
            {
                "key": "GOOGLE_CLIENT_ID",
                "label": "Google OAuth Client ID",
                "url": "https://console.cloud.google.com/apis/credentials",
                "instructions": (
                    "1. Open the URL above → [bold]Create Credentials[/bold] → [bold]OAuth client ID[/bold]\n"
                    "   2. Application type: [bold]Desktop app[/bold]\n"
                    "   3. Enable [bold]Google Calendar API[/bold] in the project\n"
                    "   4. Copy [bold]Client ID[/bold]"
                ),
                "required": False,
                "secret": False,
                "default": None,
                "test": None,
            },
            {
                "key": "GOOGLE_CLIENT_SECRET",
                "label": "Google OAuth Client Secret",
                "url": None,
                "instructions": "Copy [bold]Client Secret[/bold] from the same Google credentials page",
                "required": False,
                "secret": True,
                "default": None,
                "test": None,
            },
        ],
    },
    # ── SCHEDULER ────────────────────────────────────────────────────────────
    {
        "group": "⏰  Schedule (optional)",
        "intro": "Set when you want the automatic morning briefing and standup summary.",
        "fields": [
            {
                "key": "BRIEFING_TIME",
                "label": "Daily briefing time (HH:MM, 24h)",
                "url": None,
                "instructions": "e.g. [bold]09:00[/bold] for 9 AM",
                "required": False,
                "secret": False,
                "default": "09:00",
                "test": None,
            },
            {
                "key": "STANDUP_TIME",
                "label": "Standup summary time (HH:MM, 24h)",
                "url": None,
                "instructions": "e.g. [bold]09:15[/bold] for 9:15 AM",
                "required": False,
                "secret": False,
                "default": "09:15",
                "test": None,
            },
        ],
    },
]

# ── Connection testers ────────────────────────────────────────────────────────

def _test_claude(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error
    key = values.get("ANTHROPIC_API_KEY", "")
    if not key:
        return False, "No key provided"
    try:
        body = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "Hi"}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        if data.get("content"):
            return True, "Connected — Claude API working"
        return False, "Unexpected response"
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            err = json.loads(body_bytes).get("error", {}).get("message", "")
        except Exception:
            err = ""
        if e.code == 401:
            return False, "Invalid API key"
        if e.code == 403:
            return False, f"Permission denied: {err[:80]}"
        return False, f"HTTP {e.code}: {err[:80]}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def _test_openai(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error
    key = values.get("OPENAI_API_KEY", "")
    if not key:
        return False, "No key provided"
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        count = len(data.get("data", []))
        return True, f"Connected — {count} models available"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid API key"
        if e.code == 429:
            return True, "Key valid — rate limit hit (still works)"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def _test_gemini(values: dict) -> tuple[bool, str]:
    key = values.get("GEMINI_API_KEY", "")
    if not key:
        return False, "No key provided"
    try:
        import urllib.request
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"?key={key}&pageSize=1"
        )
        req = urllib.request.urlopen(url, timeout=8)
        data = json.loads(req.read())
        models = data.get("models", [])
        if models:
            return True, f"Connected — {len(models)}+ models available"
        return True, "Connected"
    except Exception as e:
        msg = str(e)
        if "400" in msg or "API_KEY_INVALID" in msg:
            return False, "Invalid API key"
        if "403" in msg:
            return False, "Key exists but access denied — check billing"
        return False, f"Error: {msg[:80]}"


def _test_atlassian(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error
    email  = values.get("ATLASSIAN_EMAIL", "")
    token  = values.get("ATLASSIAN_API_TOKEN", "")
    domain = values.get("ATLASSIAN_DOMAIN", "")
    if not all([email, token, domain]):
        return False, "Incomplete credentials"
    try:
        creds = base64.b64encode(f"{email}:{token}".encode()).decode()
        url = f"https://{domain}/rest/api/3/myself"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Basic {creds}", "Accept": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        name = data.get("displayName", "unknown")
        return True, f"Connected as {name}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid email or API token"
        if e.code == 403:
            return False, "Authenticated but permission denied"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def _test_github(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error
    token = values.get("GITHUB_TOKEN", "")
    if not token:
        return False, "No token provided"
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        )
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        login = data.get("login", "unknown")
        return True, f"Connected as @{login}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid token"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def _test_linear(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error
    key = values.get("LINEAR_API_KEY", "")
    if not key:
        return False, "No key provided"
    try:
        body = json.dumps({"query": "{ viewer { name email } }"}).encode()
        req = urllib.request.Request(
            "https://api.linear.app/graphql",
            data=body,
            headers={
                "Authorization": key,
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        viewer = data.get("data", {}).get("viewer", {})
        name = viewer.get("name", "unknown")
        return True, f"Connected as {name}"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def _test_minimax(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error
    key = values.get("MINIMAX_API_KEY", "")
    if not key:
        return False, "No key provided"
    try:
        body = json.dumps({
            "model": "MiniMax-M2.7",
            "max_tokens": 10,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hi"},
            ],
        }).encode()
        req = urllib.request.Request(
            "https://api.minimax.io/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type":  "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=12)
        data = json.loads(resp.read())
        if data.get("choices"):
            return True, "Connected — MiniMax M2.7 responding"
        return False, f"Unexpected response: {str(data)[:80]}"
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            err_msg = json.loads(body_bytes).get("error", {})
            if isinstance(err_msg, dict):
                err_msg = err_msg.get("message", str(err_msg))
        except Exception:
            err_msg = body_bytes.decode(errors="replace")[:80]
        if e.code == 401:
            return False, "Invalid API key — check your sk-cp-... Token Plan key"
        if e.code == 429:
            return False, "⏳ Quota reached — resets in your 5-hour window"
        return False, f"HTTP {e.code}: {str(err_msg)[:80]}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


def _test_zoom(values: dict) -> tuple[bool, str]:
    import urllib.request, urllib.error, urllib.parse
    account_id    = values.get("ZOOM_ACCOUNT_ID", "")
    client_id     = values.get("ZOOM_CLIENT_ID", "")
    client_secret = values.get("ZOOM_CLIENT_SECRET", "")
    if not all([account_id, client_id, client_secret]):
        return False, "Incomplete credentials"
    try:
        creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
        req = urllib.request.Request(
            url,
            method="POST",
            headers={"Authorization": f"Basic {creds}"},
        )
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        if "access_token" in data:
            return True, "Token obtained — Zoom connected"
        return False, f"Unexpected response: {data}"
    except urllib.error.HTTPError as e:
        if e.code in (400, 401):
            return False, "Invalid credentials — check Account ID / Client ID / Secret"
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, f"Error: {str(e)[:80]}"


TESTERS = {
    "gemini":    _test_gemini,
    "claude":    _test_claude,
    "openai":    _test_openai,
    "minimax":   _test_minimax,
    "atlassian": _test_atlassian,
    "github":    _test_github,
    "linear":    _test_linear,
    "zoom":      _test_zoom,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_existing_env() -> dict:
    """Load current .env values if the file exists."""
    values = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                values[k.strip()] = v.strip()
    return values


def _save_env(values: dict):
    """Write all values to .env, preserving comment headers."""
    lines = [
        "# Work Assistant Agent — Environment Variables",
        "# Generated by setup_wizard.py — do not commit this file",
        "",
    ]
    sections = {
        "LLM SETTINGS":  ["LLM_PROVIDER", "LLM_MODEL"],
        "GEMINI":        ["GEMINI_API_KEY"],
        "ANTHROPIC CLAUDE": ["ANTHROPIC_API_KEY"],
        "OPENAI":        ["OPENAI_API_KEY"],
        "OPENROUTER":    ["OPENROUTER_API_KEY"],
        "MINIMAX":       ["MINIMAX_API_KEY"],
        "MICROSOFT 365": ["MS_CLIENT_ID", "MS_TENANT_ID"],
        "ATLASSIAN":     ["ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "ATLASSIAN_DOMAIN"],
        "GITHUB":        ["GITHUB_TOKEN"],
        "LINEAR":        ["LINEAR_API_KEY"],
        "ZOOM":          ["ZOOM_ACCOUNT_ID", "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"],
        "GOOGLE MEET":   ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "SCHEDULER":     ["BRIEFING_TIME", "STANDUP_TIME"],
    }
    for section, keys in sections.items():
        lines.append(f"# ── {section} {'─' * max(0, 50 - len(section))}")
        for k in keys:
            v = values.get(k, "")
            lines.append(f"{k}={v}")
        lines.append("")
    ENV_PATH.write_text("\n".join(lines))


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


def _run_test(test_key: str, values: dict) -> tuple[bool, str]:
    tester = TESTERS.get(test_key)
    if not tester:
        return True, "skipped"
    console.print("   [dim]Testing connection…[/dim]", end="\r")
    ok, msg = tester(values)
    return ok, msg

# ── Main wizard ───────────────────────────────────────────────────────────────

def run_wizard(test_only: bool = False):
    console.clear()
    console.print(Panel(
        "[bold cyan]Work Assistant Agent — Setup Wizard[/bold cyan]\n\n"
        "This wizard will guide you through setting up your credentials.\n"
        "You need [bold]at least one LLM API key[/bold] (Gemini, Claude, OpenAI, or OpenRouter)\n"
        "and [bold]Microsoft 365[/bold] for email/calendar/Teams. Everything else is optional.\n\n"
        "Press [bold]Enter[/bold] to accept a default value shown in [bold green]brackets[/bold green].\n"
        "You can re-run this wizard any time to update credentials.",
        title="👋  Welcome",
        border_style="cyan",
        padding=(1, 2),
    ))
    console.print()

    existing = _load_existing_env()
    if existing and not test_only:
        console.print(
            f"[yellow]Found existing .env with {len(existing)} values.[/yellow] "
            "Press Enter to keep each current value, or type a new one.\n"
        )

    all_values = dict(existing)
    results: list[dict] = []   # for final summary

    if test_only:
        console.print("[bold]Re-testing existing credentials…[/bold]\n")
        for step in STEPS:
            for field in step["fields"]:
                test_key = field.get("test")
                if not test_key:
                    continue
                ok, msg = _run_test(test_key, all_values)
                icon = "✅" if ok else "❌"
                results.append({"name": field["label"], "ok": ok, "msg": msg})
                console.print(f"  {icon}  {field['label']}: {msg}")
        _print_summary(results)
        return

    # ── Walk through each step ────────────────────────────────────────────────
    for step_idx, step in enumerate(STEPS, 1):
        console.rule(f"[bold]{step_idx}/{len(STEPS)}  {step['group']}[/bold]")
        console.print(f"\n[dim]{step['intro']}[/dim]\n")

        last_test_key  = None
        last_test_field = None

        for field in step["fields"]:
            key          = field["key"]
            label        = field["label"]
            url          = field.get("url")
            instructions = field.get("instructions", "")
            secret       = field.get("secret", False)
            default      = field.get("default")
            required     = field.get("required", False)
            test_key     = field.get("test")

            # Show URL
            if url:
                console.print(f"  🔗  [link={url}]{url}[/link]")

            # Show instructions
            if instructions:
                for line in instructions.split("\n"):
                    console.print(f"  {line}")
            console.print()

            # Build prompt
            current = existing.get(key, "")
            if current:
                hint = f" [[green]{_mask(current) if secret else current}[/green]]"
            elif default is not None:
                hint = f" [[green]{default}[/green]]"
            else:
                hint = ""

            required_tag = " [red](required)[/red]" if required else " [dim](optional — press Enter to skip)[/dim]"

            prompt_label = f"  [bold]{label}[/bold]{required_tag}{hint}"

            while True:
                value = Prompt.ask(prompt_label, password=secret, default="", console=console)
                value = value.strip()

                if not value:
                    if current:
                        value = current      # keep existing
                    elif default is not None:
                        value = default      # use default
                    # else empty — fine if optional

                if required and not value:
                    console.print("  [red]This field is required.[/red]")
                    continue
                break

            all_values[key] = value

            # Track which field triggers a test
            if test_key:
                last_test_key   = test_key
                last_test_field = label

        # Run connection test after all fields in the group are collected
        if last_test_key:
            console.print()
            ok, msg = _run_test(last_test_key, all_values)
            icon = "✅" if ok else "❌"
            colour = "green" if ok else "red"
            console.print(f"  {icon}  Connection test: [{colour}]{msg}[/{colour}]")
            results.append({"name": step["group"], "ok": ok, "msg": msg})
            if not ok:
                console.print(
                    f"\n  [yellow]⚠  Connection failed. You can continue and fix this later.[/yellow]\n"
                    "  The credential has been saved — just re-run this wizard after fixing it.\n"
                )
        console.print()

    # ── Save ─────────────────────────────────────────────────────────────────
    _save_env(all_values)
    console.print(f"[bold green]✅  .env saved to {ENV_PATH}[/bold green]\n")

    _print_summary(results)

    # ── Offer to launch ───────────────────────────────────────────────────────
    console.print()
    if Confirm.ask("  Launch the Work Assistant app now?", default=True, console=console):
        console.print("\n[bold cyan]Starting app…[/bold cyan]")
        app_path = Path(__file__).parent / "app.py"
        os.execv(sys.executable, [sys.executable, str(app_path)])


def _print_summary(results: list[dict]):
    if not results:
        return

    table = Table(
        title="Connection Test Results",
        box=box.ROUNDED,
        border_style="dim",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Integration", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details")

    for r in results:
        if r["ok"]:
            status = "[green]✅ Connected[/green]"
        else:
            status = "[red]❌ Failed[/red]"
        table.add_row(r["name"], status, r["msg"])

    console.print()
    console.print(table)
    console.print()

    ok_count   = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count

    if fail_count == 0:
        console.print("[bold green]🎉  All connections verified! Your agent is ready.[/bold green]")
    else:
        console.print(
            f"[yellow]⚠  {ok_count} connected, {fail_count} failed.[/yellow] "
            "Re-run [bold]python setup_wizard.py[/bold] after fixing failed credentials."
        )

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_only = "--test" in sys.argv
    try:
        run_wizard(test_only=test_only)
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Setup cancelled. Run again any time.[/yellow]")
        sys.exit(0)
