"""
ms365.py — Microsoft 365 Tools
================================
Covers: Outlook (email + calendar), Teams (messages + meetings), SharePoint (search + files), Excel (read/write)
Auth:   MSAL device code flow — user authenticates via browser on first run, token cached to ~/.work-assistant-token-cache.json
API:    Microsoft Graph REST API v1.0
"""

import os
import json
import base64
import datetime
import msal
import requests
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# AUTH — MSAL device code flow
# ─────────────────────────────────────────────

# All Graph API permissions this agent needs
# ⚠️  ChannelMessage.Read.All is NOT listed here — it requires admin consent
#     and breaks token acquisition for personal accounts and most work tenants.
#     Channel messages are fetched with a graceful fallback instead.
GRAPH_SCOPES = [
    "Mail.ReadWrite",
    "Mail.Send",
    "Calendars.ReadWrite",
    "Chat.ReadWrite",        # Direct chats (no admin consent needed)
    "Team.ReadBasic.All",    # /me/joinedTeams — was missing, caused 403
    "Files.ReadWrite.All",
    "Sites.Read.All",
    "User.Read",
    # Note: offline_access is handled automatically by MSAL — do NOT list it here
]

# Scopes that require admin consent — requested separately, failures are soft
GRAPH_SCOPES_ADMIN = [
    "ChannelMessage.Read.All",   # Read channel (team) messages
]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE_PATH = Path.home() / ".work-assistant-token-cache.json"


def is_authenticated() -> bool:
    """
    Non-blocking check — returns True if a valid token cache exists AND covers
    all current GRAPH_SCOPES.  If scopes have changed since the token was
    cached, returns False so the caller knows re-auth is needed.
    """
    if not TOKEN_CACHE_PATH.exists():
        return False
    try:
        app, _cache = _build_msal_app()
        accounts = app.get_accounts()
        if not accounts:
            return False
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])
        if not result or "access_token" not in result:
            return False
        # Check that the token actually covers our required scopes.
        # MSAL returns the granted scopes in result["scope"] as a space-separated string.
        granted = set((result.get("scope") or "").lower().split())
        required = {s.lower() for s in GRAPH_SCOPES}
        # "openid", "profile", "offline_access", "email" are added implicitly — ignore them
        _implicit = {"openid", "profile", "offline_access", "email"}
        missing = required - granted - _implicit
        if missing:
            # Stale token — clear cache so next call triggers fresh device-code flow
            TOKEN_CACHE_PATH.unlink(missing_ok=True)
            return False
        return True
    except Exception:
        return False


def start_device_flow() -> dict:
    """
    Initiate MSAL device code flow without blocking.
    Returns {"user_code": ..., "verification_uri": ..., "expires_in": ...}
    so the caller can display these to the user.
    The actual token acquisition must be done in a background thread via
    complete_device_flow(flow).
    """
    app, _cache = _build_msal_app()
    flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Device flow failed: {flow.get('error_description', flow)}")
    return flow


def complete_device_flow(flow: dict) -> bool:
    """
    Block until the user completes sign-in, then persist the token cache.
    Run this in a background thread — it blocks for up to ~15 minutes.
    Returns True on success, False on timeout/failure.
    """
    app, cache = _build_msal_app()
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        if cache.has_state_changed:
            TOKEN_CACHE_PATH.write_text(cache.serialize())
        return True
    return False


def clear_token_cache():
    """Delete the cached token so the user is prompted to sign in again.
    Call this if you change scopes or hit persistent auth errors."""
    if TOKEN_CACHE_PATH.exists():
        TOKEN_CACHE_PATH.unlink()
        return {"status": "cleared", "path": str(TOKEN_CACHE_PATH)}
    return {"status": "nothing_to_clear"}


def _build_msal_app() -> msal.PublicClientApplication:
    """Build the MSAL app using CLIENT_ID and TENANT_ID from environment."""
    client_id = os.getenv("MS_CLIENT_ID")
    tenant_id = os.getenv("MS_TENANT_ID", "common")

    if not client_id:
        raise ValueError(
            "\n❌  MS_CLIENT_ID not set in .env\n"
            "   See README_SETUP.md Step 2 for how to register your Azure AD app.\n"
        )

    # Persistent token cache — so user only logs in once
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text())

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    return app, cache


def get_access_token(force_refresh: bool = False) -> str:
    """
    Get a valid access token for Microsoft Graph.

    Uses cached token if available; triggers device code flow if not.
    MSAL's acquire_token_silent() automatically uses the refresh token
    to obtain a new access token when the cached one has expired.

    Args:
        force_refresh: If True, bypass the in-memory token cache and
                       force MSAL to use the refresh token, obtaining a
                       brand-new access token from the server.  Useful
                       when a Graph API call comes back with a 401 despite
                       having a cached token (clock skew, early revocation).
    """
    app, cache = _build_msal_app()

    # Try silent token first (uses cached refresh token automatically)
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(
            GRAPH_SCOPES,
            account=accounts[0],
            force_refresh=force_refresh,   # ← NEW: force server round-trip when needed
        )

    # If no cached token (first run), do device code flow
    if not result or "access_token" not in result:
        flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to create device flow: {flow.get('error_description')}")

        print("\n" + "=" * 60)
        print("🔐  Microsoft 365 Sign-In Required")
        print("=" * 60)
        print(f"\n  1. Open this URL in your browser:\n     {flow['verification_uri']}")
        print(f"\n  2. Enter this code when prompted:  {flow['user_code']}")
        print("\n  Waiting for you to sign in...")
        result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(f"Authentication failed: {result.get('error_description', result.get('error'))}")

    # Persist any cache changes (new access token, rotated refresh token)
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())

    return result["access_token"]


def _graph(method: str, endpoint: str, _retry_on_401: bool = True, **kwargs) -> dict:
    """
    Make an authenticated Microsoft Graph API call.

    Automatically retries once on a 401 Unauthorized response by force-
    refreshing the access token via the MSAL refresh-token grant.  This
    handles the edge case where the cached token was valid at call time
    but was already expired or revoked server-side.
    """
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{GRAPH_BASE}{endpoint}"
    response = requests.request(method, url, headers=headers, **kwargs)

    # Auto-refresh on 401: token may have just expired between cache read and server check
    if response.status_code == 401 and _retry_on_401:
        try:
            token = get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            response = requests.request(method, url, headers=headers, **kwargs)
        except Exception:
            pass  # Fall through to error handling below

    # 204 No Content and 202 Accepted both mean success with no body
    if response.status_code in (202, 204) or not response.content:
        return {"status": "success"}
    if not response.ok:
        raise RuntimeError(
            f"Graph API error {response.status_code}: {response.text[:500]}"
        )
    try:
        return response.json()
    except Exception:
        return {"status": "success", "raw": response.text[:200]}


# ─────────────────────────────────────────────
# OUTLOOK — Email
# ─────────────────────────────────────────────

def get_emails(folder: str = "inbox", max_count: int = 20, unread_only: bool = False) -> list[dict]:
    """
    Fetch emails from the specified folder.

    Args:
        folder:     'inbox', 'sentitems', 'drafts', or a folder name
        max_count:  How many emails to return (max 50)
        unread_only: If True, only return unread emails

    Returns:
        List of email dicts with keys: id, subject, from, receivedDateTime, bodyPreview, isRead, hasAttachments
    """
    filter_str = ""
    if unread_only:
        filter_str = "&$filter=isRead eq false"

    data = _graph(
        "GET",
        f"/me/mailFolders/{folder}/messages"
        f"?$top={min(max_count, 50)}"
        f"&$orderby=receivedDateTime desc"
        f"&$select=id,subject,from,receivedDateTime,bodyPreview,isRead,hasAttachments"
        f"{filter_str}",
    )
    return data.get("value", [])


def get_email_body(email_id: str) -> str:
    """Get the full body text of a specific email by ID."""
    data = _graph("GET", f"/me/messages/{email_id}?$select=body,subject,from,toRecipients")
    body = data.get("body", {})
    # Strip HTML tags for plain text if content is HTML
    content = body.get("content", "")
    if body.get("contentType") == "html":
        import re
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
    return content


def send_email(to: str, subject: str, body: str, reply_to_id: Optional[str] = None) -> dict:
    """
    Send an email.

    Args:
        to:           Recipient email address
        subject:      Email subject
        body:         Email body (plain text)
        reply_to_id:  If set, send as a reply to this email ID

    Returns:
        {"status": "sent", "to": to, "subject": subject}
    """
    if reply_to_id:
        _graph(
            "POST",
            f"/me/messages/{reply_to_id}/reply",
            json={"message": {"body": {"contentType": "Text", "content": body}}},
        )
    else:
        _graph(
            "POST",
            "/me/sendMail",
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                "saveToSentItems": True,
            },
        )
    return {"status": "sent", "to": to, "subject": subject}


def mark_email_read(email_id: str) -> dict:
    """Mark an email as read."""
    _graph("PATCH", f"/me/messages/{email_id}", json={"isRead": True})
    return {"status": "marked_read", "id": email_id}


def move_email(email_id: str, destination_folder: str) -> dict:
    """Move an email to another folder (e.g. 'archive', 'deleteditems')."""
    result = _graph(
        "POST",
        f"/me/messages/{email_id}/move",
        json={"destinationId": destination_folder},
    )
    return {"status": "moved", "new_id": result.get("id")}


def search_emails(query: str, max_count: int = 10) -> list[dict]:
    """
    Search emails using a keyword query.

    Args:
        query:     Search term (subject, body, sender)
        max_count: Max results

    Returns:
        List of matching email dicts
    """
    data = _graph(
        "GET",
        f"/me/messages?$search=\"{query}\"&$top={min(max_count, 25)}"
        f"&$select=id,subject,from,receivedDateTime,bodyPreview,isRead",
    )
    return data.get("value", [])


# ─────────────────────────────────────────────
# OUTLOOK — Calendar
# ─────────────────────────────────────────────

def get_calendar_events(days_ahead: int = 1) -> list[dict]:
    """
    Get calendar events for the next N days.

    Args:
        days_ahead: How many days ahead to look (default: today only)

    Returns:
        List of event dicts: subject, start, end, location, organizer, isOnlineMeeting, webLink
    """
    now = datetime.datetime.utcnow()
    end = now + datetime.timedelta(days=days_ahead)
    start_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ")

    data = _graph(
        "GET",
        f"/me/calendarView"
        f"?startDateTime={start_str}&endDateTime={end_str}"
        f"&$orderby=start/dateTime"
        f"&$select=subject,start,end,location,organizer,isOnlineMeeting,webLink,attendees",
    )
    return data.get("value", [])


def create_calendar_event(
    subject: str,
    start: str,
    end: str,
    attendees: list[str] = None,
    body: str = "",
    location: str = "",
    online: bool = True,
) -> dict:
    """
    Create a calendar event.

    Args:
        subject:   Meeting title
        start:     ISO 8601 start time e.g. "2025-06-01T14:00:00"
        end:       ISO 8601 end time
        attendees: List of attendee email addresses
        body:      Meeting description
        location:  Physical location (optional)
        online:    Whether to create a Teams meeting link

    Returns:
        {"status": "created", "id": event_id, "webLink": url}
    """
    payload = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": "UTC"},
        "end": {"dateTime": end, "timeZone": "UTC"},
        "body": {"contentType": "Text", "content": body},
        "isOnlineMeeting": online,
    }
    if location:
        payload["location"] = {"displayName": location}
    if attendees:
        payload["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in attendees
        ]

    result = _graph("POST", "/me/events", json=payload)
    return {"status": "created", "id": result.get("id"), "webLink": result.get("webLink")}


def find_free_slots(
    attendees: list[str],
    duration_minutes: int = 30,
    days_ahead: int = 5,
    working_hours_start: int = 9,
    working_hours_end: int = 18,
) -> list[dict]:
    """
    Find available time slots when all attendees are free.

    Uses Microsoft Graph /me/calendar/getSchedule to fetch availability,
    then identifies gaps that fit the requested duration.

    Args:
        attendees:             List of attendee email addresses
        duration_minutes:      Meeting duration to find a slot for (default: 30)
        days_ahead:            How many days to search (default: 5)
        working_hours_start:   Start of working day in UTC hour (default: 9)
        working_hours_end:     End of working day in UTC hour (default: 18)

    Returns:
        List of free slot dicts: start, end, duration_minutes
        (up to 10 slots, sorted by start time)
    """
    now = datetime.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    end_search = now + datetime.timedelta(days=days_ahead)

    start_str = now.strftime("%Y-%m-%dT%H:%M:%S")
    end_str = end_search.strftime("%Y-%m-%dT%H:%M:%S")

    payload = {
        "schedules": attendees,
        "startTime": {"dateTime": start_str, "timeZone": "UTC"},
        "endTime": {"dateTime": end_str, "timeZone": "UTC"},
        "availabilityViewInterval": duration_minutes,
    }

    try:
        data = _graph("POST", "/me/calendar/getSchedule", json=payload)
    except Exception as e:
        return [{"error": f"getSchedule failed: {e}"}]

    # Collect all busy intervals across all attendees
    # availabilityView is a string like "0002020000..." where each char = one interval
    # 0=free, 1=tentative, 2=busy, 3=OOF, 4=working elsewhere
    # We'll use scheduleItems (explicit busy blocks) for accuracy
    all_busy: list[tuple] = []
    for schedule in data.get("value", []):
        for item in schedule.get("scheduleItems", []):
            status = item.get("status", "free")
            if status in ("busy", "oof", "tentative"):
                s = item.get("start", {}).get("dateTime", "")
                e = item.get("end", {}).get("dateTime", "")
                if s and e:
                    try:
                        # Graph returns ISO strings — may have trailing Z or not
                        s_dt = datetime.datetime.fromisoformat(s.rstrip("Z"))
                        e_dt = datetime.datetime.fromisoformat(e.rstrip("Z"))
                        all_busy.append((s_dt, e_dt))
                    except ValueError:
                        pass

    # Sort and merge overlapping busy blocks
    all_busy.sort(key=lambda x: x[0])
    merged: list[tuple] = []
    for start_b, end_b in all_busy:
        if merged and start_b <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end_b))
        else:
            merged.append((start_b, end_b))

    # Walk each working day and find gaps >= duration_minutes
    slot_duration = datetime.timedelta(minutes=duration_minutes)
    free_slots = []
    cursor = now

    while cursor < end_search and len(free_slots) < 10:
        # Set working window for this day
        day_start = cursor.replace(hour=working_hours_start, minute=0, second=0)
        day_end = cursor.replace(hour=working_hours_end, minute=0, second=0)

        # Don't look in the past
        window_start = max(cursor, day_start)
        window_end = day_end

        if window_start >= window_end:
            cursor = (cursor + datetime.timedelta(days=1)).replace(
                hour=working_hours_start, minute=0, second=0
            )
            continue

        # Find free gaps in the working window
        pos = window_start
        for busy_start, busy_end in merged:
            if busy_start >= window_end:
                break
            if busy_end <= pos:
                continue
            # Gap before this busy block
            gap_end = min(busy_start, window_end)
            if gap_end - pos >= slot_duration:
                free_slots.append({
                    "start": pos.strftime("%Y-%m-%dT%H:%M:00Z"),
                    "end": (pos + slot_duration).strftime("%Y-%m-%dT%H:%M:00Z"),
                    "duration_minutes": duration_minutes,
                })
                if len(free_slots) >= 10:
                    break
            pos = max(pos, busy_end)

        # Remaining time after last busy block
        if len(free_slots) < 10 and pos < window_end and (window_end - pos) >= slot_duration:
            free_slots.append({
                "start": pos.strftime("%Y-%m-%dT%H:%M:00Z"),
                "end": (pos + slot_duration).strftime("%Y-%m-%dT%H:%M:00Z"),
                "duration_minutes": duration_minutes,
            })

        cursor = (cursor + datetime.timedelta(days=1)).replace(
            hour=working_hours_start, minute=0, second=0
        )

    return free_slots


# ─────────────────────────────────────────────
# TEAMS — Messages
# ─────────────────────────────────────────────

def get_teams_chats(max_count: int = 10) -> list[dict]:
    """
    Get recent Teams chats (direct messages and group chats).

    Note: /me/chats does NOT support $orderby — we sort in Python after fetching.

    Returns:
        List of chat dicts: id, topic, chatType, lastUpdatedDateTime, members
    """
    # $orderby is NOT supported on /me/chats — omit it or you get 400 Bad Request
    # $select inside $expand for members must only use base conversationMember fields
    # (displayName, id, roles) — "email" is on the derived type and causes 400 errors
    # Note: /me/chats $expand=members does NOT support nested $select — causes 400
    data = _graph(
        "GET",
        f"/me/chats?$top={min(max_count, 50)}"
        f"&$select=id,topic,chatType,lastUpdatedDateTime"
        f"&$expand=members",
    )
    chats = data.get("value", [])

    # Sort by lastUpdatedDateTime descending (most recent first)
    chats.sort(
        key=lambda c: c.get("lastUpdatedDateTime") or "",
        reverse=True,
    )

    # Simplify member list for readability
    for chat in chats:
        raw_members = chat.pop("members", []) or []
        chat["members"] = [
            m.get("displayName") or m.get("id") or "Unknown"
            for m in raw_members
            if not (m.get("displayName") or "").lower().startswith("me")
        ]
        if not chat.get("topic") and chat["members"]:
            chat["topic"] = ", ".join(chat["members"][:3])

        # Rename 'id' → 'chat_id' so the agent can directly use it in get_chat_messages
        chat["chat_id"] = chat.pop("id", None)

    return chats[:max_count]


def get_chat_messages(chat_id: str, max_count: int = 20) -> list[dict]:
    """
    Get recent messages from a Teams chat.

    Returns:
        List of message dicts: id, from, body, createdDateTime
    """
    import re as _re

    data = _graph(
        "GET",
        f"/me/chats/{chat_id}/messages?$top={min(max_count, 50)}",
    )
    messages = []
    for m in data.get("value", []):
        sender = m.get("from", {}) or {}
        user = sender.get("user", {}) or sender.get("application", {}) or {}

        # Strip HTML tags from message body so the agent sees plain text
        body_obj = m.get("body", {}) or {}
        body_text = body_obj.get("content", "") or ""
        if body_obj.get("contentType") == "html":
            body_text = _re.sub(r"<[^>]+>", " ", body_text)
            body_text = _re.sub(r"\s+", " ", body_text).strip()

        # Skip empty system messages (calls, attachments with no text)
        if not body_text or body_text in ("<attachment></attachment>", "​"):
            continue

        messages.append({
            "id": m.get("id"),
            "from": user.get("displayName", "Unknown"),
            "body": body_text[:500],          # cap per-message length
            "createdDateTime": m.get("createdDateTime"),
        })
    return messages


def send_teams_message(chat_id: str, message: str) -> dict:
    """
    Send a message to a Teams chat.

    Args:
        chat_id: The Teams chat ID
        message: Message text

    Returns:
        {"status": "sent", "id": message_id}
    """
    result = _graph(
        "POST",
        f"/me/chats/{chat_id}/messages",
        json={"body": {"content": message}},
    )
    return {"status": "sent", "id": result.get("id")}


def get_teams_channels(team_id: str) -> list[dict]:
    """Get channels in a Teams team."""
    data = _graph("GET", f"/teams/{team_id}/channels?$select=id,displayName,description")
    return data.get("value", [])


def get_channel_messages(team_id: str, channel_id: str, max_count: int = 20) -> list[dict]:
    """
    Get recent messages from a Teams channel.

    Requires ChannelMessage.Read.All (admin consent). Returns a clear error
    message if the permission has not been granted rather than crashing.
    """
    try:
        data = _graph(
            "GET",
            f"/teams/{team_id}/channels/{channel_id}/messages?$top={min(max_count, 50)}",
        )
    except RuntimeError as e:
        err = str(e)
        if "403" in err or "Forbidden" in err or "Authorization" in err:
            return [{
                "error": (
                    "Cannot read channel messages — the ChannelMessage.Read.All permission "
                    "requires admin consent in your Microsoft 365 tenant. "
                    "Ask your M365 admin to grant consent, or use the Teams app directly."
                )
            }]
        raise

    messages = []
    for m in data.get("value", []):
        sender = (m.get("from") or {}).get("user", {}) or {}
        messages.append({
            "id": m.get("id"),
            "from": sender.get("displayName", "Unknown"),
            "body": m.get("body", {}).get("content", ""),
            "createdDateTime": m.get("createdDateTime"),
        })
    return messages


def post_channel_message(team_id: str, channel_id: str, message: str) -> dict:
    """Post a message to a Teams channel."""
    result = _graph(
        "POST",
        f"/teams/{team_id}/channels/{channel_id}/messages",
        json={"body": {"content": message}},
    )
    return {"status": "posted", "id": result.get("id")}


def list_teams() -> list[dict]:
    """List all Teams the user is a member of."""
    data = _graph("GET", "/me/joinedTeams?$select=id,displayName,description")
    return data.get("value", [])


# ─────────────────────────────────────────────
# SHAREPOINT — Search and Files
# ─────────────────────────────────────────────

def search_sharepoint(query: str, max_results: int = 10) -> list[dict]:
    """
    Search SharePoint for documents, pages, and items.

    Args:
        query:       Search term
        max_results: Max results to return

    Returns:
        List of results: name, webUrl, lastModifiedDateTime, summary
    """
    payload = {
        "requests": [{
            "entityTypes": ["driveItem", "listItem", "site"],
            "query": {"queryString": query},
            "from": 0,
            "size": min(max_results, 25),
            "fields": ["name", "webUrl", "lastModifiedDateTime", "summary", "createdBy"],
        }]
    }
    data = _graph("POST", "/search/query", json=payload)
    results = []
    for batch in data.get("value", []):
        for hit_container in batch.get("hitsContainers", []):
            for hit in hit_container.get("hits", []):
                resource = hit.get("resource", {})
                results.append({
                    "name": resource.get("name", resource.get("displayName", "Untitled")),
                    "webUrl": resource.get("webUrl", ""),
                    "lastModified": resource.get("lastModifiedDateTime", ""),
                    "summary": hit.get("summary", ""),
                })
    return results


def list_sharepoint_files(site_id: str = None, drive_id: str = None, folder_path: str = "/") -> list[dict]:
    """
    List files in a SharePoint drive folder.

    Args:
        site_id:     SharePoint site ID (leave None to use root site)
        drive_id:    Drive ID (leave None to use default drive)
        folder_path: Path within the drive (default: root)

    Returns:
        List of file dicts: name, id, size, lastModifiedDateTime, webUrl, isFolder
    """
    if site_id and drive_id:
        base = f"/sites/{site_id}/drives/{drive_id}"
    elif site_id:
        base = f"/sites/{site_id}/drive"
    else:
        base = "/me/drive"

    path_seg = "root" if folder_path in ("/", "") else f"root:{folder_path}:"
    data = _graph("GET", f"{base}/{path_seg}/children?$select=id,name,size,lastModifiedDateTime,webUrl,folder")
    files = []
    for item in data.get("value", []):
        files.append({
            "name": item.get("name"),
            "id": item.get("id"),
            "size": item.get("size", 0),
            "lastModified": item.get("lastModifiedDateTime"),
            "webUrl": item.get("webUrl"),
            "isFolder": "folder" in item,
        })
    return files


def download_sharepoint_file(item_id: str, save_path: str) -> str:
    """
    Download a SharePoint/OneDrive file by item ID.

    Returns:
        Local path where file was saved.
    """
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE}/me/drive/items/{item_id}/content"
    resp = requests.get(url, headers=headers, allow_redirects=True)
    if not resp.ok:
        raise RuntimeError(f"Download failed: {resp.status_code}")
    Path(save_path).write_bytes(resp.content)
    return save_path


def upload_sharepoint_file(local_path: str, drive_folder: str = "/", filename: str = None) -> dict:
    """
    Upload a file to OneDrive/SharePoint.

    Args:
        local_path:   Path to the local file
        drive_folder: Destination folder path in drive
        filename:     Override filename (default: use local filename)

    Returns:
        {"status": "uploaded", "id": item_id, "webUrl": url}
    """
    path = Path(local_path)
    name = filename or path.name
    folder = drive_folder.rstrip("/")
    dest = f"root:{folder}/{name}:" if folder else f"root:/{name}:"

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    url = f"{GRAPH_BASE}/me/drive/{dest}/content"
    resp = requests.put(url, headers=headers, data=path.read_bytes())
    if not resp.ok:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text}")
    result = resp.json()
    return {"status": "uploaded", "id": result.get("id"), "webUrl": result.get("webUrl")}


def get_sharepoint_sites(max_results: int = 20) -> list[dict]:
    """
    List SharePoint sites the user has access to.

    Returns:
        List of site dicts: id, name, displayName, webUrl
    """
    params = {"$select": "id,name,displayName,webUrl", "$top": min(max_results, 50)}
    data = _graph("GET", "/sites?search=*", params=params)
    return [
        {
            "id":          s.get("id"),
            "name":        s.get("name"),
            "displayName": s.get("displayName"),
            "webUrl":      s.get("webUrl"),
        }
        for s in data.get("value", [])
    ]


def upload_file_to_sharepoint(
    local_path: str,
    site_id: str = None,
    folder_path: str = "/",
    filename: str = None,
) -> dict:
    """
    Upload a local file to a SharePoint site or OneDrive.

    Args:
        local_path:  Path to the local file (absolute or relative)
        site_id:     SharePoint site ID (leave None to upload to OneDrive)
        folder_path: Destination folder in the drive (default: root)
        filename:    Override filename (default: uses the local filename)

    Returns:
        {"status": "uploaded", "filename": ..., "webUrl": ..., "id": ...}
    """
    path = Path(local_path)
    name = filename or path.name
    folder = folder_path.rstrip("/")
    dest = f"root:{folder}/{name}:" if folder else f"root:/{name}:"

    if site_id:
        url = f"{GRAPH_BASE}/sites/{site_id}/drive/{dest}/content"
    else:
        url = f"{GRAPH_BASE}/me/drive/{dest}/content"

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
    }
    resp = requests.put(url, headers=headers, data=path.read_bytes())
    if not resp.ok:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text[:300]}")
    result = resp.json()
    return {
        "status":   "uploaded",
        "filename": name,
        "id":       result.get("id"),
        "webUrl":   result.get("webUrl"),
    }


# ─────────────────────────────────────────────
# EXCEL — Read and Write
# ─────────────────────────────────────────────

def create_excel_workbook(
    filename: str,
    sheet_name: str = "Sheet1",
    headers: list[str] = None,
    rows: list[list] = None,
) -> dict:
    """
    Create a new Excel workbook in OneDrive and optionally populate it with data.

    Args:
        filename:   Name for the new file, e.g. 'employees.xlsx'
        sheet_name: Name for the first worksheet (default 'Sheet1')
        headers:    Optional list of column header strings, e.g. ['Name', 'Age', 'Dept']
        rows:       Optional list of row data (list of lists), e.g. [['Alice', 30, 'HR'], ...]

    Returns:
        {"status": "created", "filename": ..., "webUrl": ..., "rows_written": N}
    """
    import io as _io

    # Build a minimal xlsx in-memory using only stdlib (no openpyxl needed)
    # We use the Graph API: upload a blank xlsx then write data via Workbook API
    # Step 1 — create an empty workbook by uploading a 1-byte placeholder first,
    # then use the Excel Workbook session to write headers + rows.

    # Upload empty xlsx content (Graph creates a valid workbook automatically
    # when you PUT an empty body to a .xlsx path)
    token = get_access_token()
    import requests as _req

    fname = filename if filename.endswith(".xlsx") else filename + ".xlsx"
    upload_url = f"{GRAPH_BASE}/me/drive/root:/{fname}:/content"
    headers_http = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }

    # Upload a minimal valid empty xlsx (44 bytes — just enough for Graph to accept)
    # Graph will initialise it as a proper workbook
    resp = _req.put(upload_url, headers=headers_http, data=b"")
    if not resp.ok:
        raise RuntimeError(f"Failed to create workbook: {resp.status_code} {resp.text[:300]}")

    item_id = resp.json().get("id")
    web_url = resp.json().get("webUrl", "")
    base    = f"/me/drive/items/{item_id}/workbook"

    # Get the actual first sheet name (Graph names it 'Sheet1' by default)
    sheets_data = _graph("GET", f"{base}/worksheets")
    actual_sheet = sheets_data["value"][0]["name"] if sheets_data.get("value") else "Sheet1"

    # Rename sheet if requested
    if sheet_name and sheet_name != actual_sheet:
        try:
            _graph("PATCH", f"{base}/worksheets/{actual_sheet}",
                   json={"name": sheet_name})
            actual_sheet = sheet_name
        except Exception:
            pass  # rename failed — use default name, not fatal

    rows_written = 0

    # Write headers + rows as a single range
    all_rows = []
    if headers:
        all_rows.append(headers)
    if rows:
        all_rows.extend(rows)

    if all_rows:
        n_cols = max(len(r) for r in all_rows)
        n_rows = len(all_rows)
        col_letter = chr(ord("A") + n_cols - 1)  # works for up to 26 cols
        range_addr = f"A1:{col_letter}{n_rows}"
        _graph(
            "PATCH",
            f"{base}/worksheets/{actual_sheet}/range(address='{range_addr}')",
            json={"values": all_rows},
        )
        rows_written = len(all_rows)

    return {
        "status":       "created",
        "filename":     fname,
        "sheet":        actual_sheet,
        "webUrl":       web_url,
        "rows_written": rows_written,
    }


def _find_excel_file(filename: str) -> str:
    """Search OneDrive for an Excel file by name, return its item ID."""
    results = _graph(
        "GET",
        f"/me/drive/root/search(q='{filename}')?$select=id,name,webUrl&$filter=file ne null",
    )
    items = results.get("value", [])
    # Prefer exact name match
    for item in items:
        if item["name"].lower() == filename.lower():
            return item["id"]
    if items:
        return items[0]["id"]
    raise FileNotFoundError(f"Excel file not found: {filename}")


def read_excel_sheet(filename: str, sheet_name: str = None, max_rows: int = 100) -> list[list]:
    """
    Read data from an Excel file stored in OneDrive.

    Args:
        filename:   Name of the .xlsx file (e.g. 'Budget.xlsx')
        sheet_name: Worksheet name (default: first sheet)
        max_rows:   Max rows to return

    Returns:
        2D list of cell values (row × column)
    """
    item_id = _find_excel_file(filename)
    base = f"/me/drive/items/{item_id}/workbook"

    # Get sheet name if not provided
    if not sheet_name:
        sheets = _graph("GET", f"{base}/worksheets?$select=name")
        sheet_name = sheets["value"][0]["name"]

    # Use usedRange to get all data in the sheet
    data = _graph("GET", f"{base}/worksheets/{sheet_name}/usedRange?$select=values")
    rows = data.get("values", [])
    return rows[:max_rows]


def write_excel_cell(filename: str, sheet_name: str, cell: str, value) -> dict:
    """
    Write a value to a specific cell in an Excel file on OneDrive.

    Args:
        filename:   Name of the .xlsx file
        sheet_name: Worksheet name
        cell:       Cell address e.g. 'B5'
        value:      Value to write

    Returns:
        {"status": "written", "cell": cell, "value": value}
    """
    item_id = _find_excel_file(filename)
    _graph(
        "PATCH",
        f"/me/drive/items/{item_id}/workbook/worksheets/{sheet_name}/range(address='{cell}')",
        json={"values": [[value]]},
    )
    return {"status": "written", "cell": cell, "value": value}


def write_excel_range(filename: str, sheet_name: str, start_cell: str, data: list[list]) -> dict:
    """
    Write a 2D array of values to an Excel range.

    Args:
        filename:    Name of the .xlsx file
        sheet_name:  Worksheet name
        start_cell:  Top-left cell of the range e.g. 'A1'
        data:        2D list of values [[row1_col1, row1_col2], [row2_col1, ...]]

    Returns:
        {"status": "written", "rows": n, "columns": m}
    """
    if not data:
        return {"status": "no_data"}

    rows = len(data)
    cols = max(len(r) for r in data)

    # Pad rows to same length
    padded = [r + [""] * (cols - len(r)) for r in data]

    item_id = _find_excel_file(filename)
    _graph(
        "PATCH",
        f"/me/drive/items/{item_id}/workbook/worksheets/{sheet_name}/range(address='{start_cell}')",
        json={"values": padded},
    )
    return {"status": "written", "rows": rows, "columns": cols}


def append_excel_row(filename: str, sheet_name: str, row_data: list) -> dict:
    """
    Append a new row at the end of the used range in an Excel sheet.

    Args:
        filename:   Name of the .xlsx file
        sheet_name: Worksheet name
        row_data:   List of values for the new row

    Returns:
        {"status": "appended", "row_number": n}
    """
    item_id = _find_excel_file(filename)
    base = f"/me/drive/items/{item_id}/workbook/worksheets/{sheet_name}"

    # Get used range to find next empty row
    used = _graph("GET", f"{base}/usedRange?$select=rowCount,address")
    row_count = used.get("rowCount", 0)
    next_row = row_count + 1

    # Write the new row starting at column A
    cols = len(row_data)
    end_col_letter = chr(ord("A") + cols - 1) if cols <= 26 else "Z"
    range_addr = f"A{next_row}:{end_col_letter}{next_row}"

    _graph(
        "PATCH",
        f"{base}/range(address='{range_addr}')",
        json={"values": [row_data]},
    )
    return {"status": "appended", "row_number": next_row}


def list_excel_sheets(filename: str) -> list[str]:
    """List all worksheet names in an Excel file."""
    item_id = _find_excel_file(filename)
    data = _graph("GET", f"/me/drive/items/{item_id}/workbook/worksheets?$select=name")
    return [s["name"] for s in data.get("value", [])]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def get_my_profile() -> dict:
    """Get the current user's profile (name, email, job title)."""
    data = _graph("GET", "/me?$select=displayName,mail,userPrincipalName,jobTitle,department")
    return {
        "name": data.get("displayName"),
        "email": data.get("mail") or data.get("userPrincipalName"),
        "jobTitle": data.get("jobTitle"),
        "department": data.get("department"),
    }


def sign_out() -> dict:
    """Remove the cached authentication token (forces re-login next time)."""
    if TOKEN_CACHE_PATH.exists():
        TOKEN_CACHE_PATH.unlink()
    return {"status": "signed_out"}
