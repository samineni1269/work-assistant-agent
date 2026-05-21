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
GRAPH_SCOPES = [
    "Mail.ReadWrite",
    "Mail.Send",
    "Calendars.ReadWrite",
    "Chat.ReadWrite",
    "ChannelMessage.Read.All",
    "Files.ReadWrite.All",
    "Sites.Read.All",
    "User.Read",
    "offline_access",      # For refresh tokens (persistent login)
]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE_PATH = Path.home() / ".work-assistant-token-cache.json"


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


def get_access_token() -> str:
    """
    Get a valid access token for Microsoft Graph.
    Uses cached token if available; triggers device code flow if not.
    """
    app, cache = _build_msal_app()

    # Try silent token first (uses cached refresh token)
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])

    # If no cached token, do device code flow
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

    # Save updated cache
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize())

    return result["access_token"]


def _graph(method: str, endpoint: str, **kwargs) -> dict:
    """Make an authenticated Microsoft Graph API call."""
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{GRAPH_BASE}{endpoint}"
    response = requests.request(method, url, headers=headers, **kwargs)

    if response.status_code == 204:
        return {"status": "success"}
    if not response.ok:
        raise RuntimeError(
            f"Graph API error {response.status_code}: {response.text[:500]}"
        )
    return response.json()


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


# ─────────────────────────────────────────────
# TEAMS — Messages
# ─────────────────────────────────────────────

def get_teams_chats(max_count: int = 10) -> list[dict]:
    """
    Get recent Teams chats.

    Returns:
        List of chat dicts: id, topic, chatType, lastUpdatedDateTime
    """
    data = _graph(
        "GET",
        f"/me/chats?$top={min(max_count, 50)}&$orderby=lastUpdatedDateTime desc"
        f"&$select=id,topic,chatType,lastUpdatedDateTime",
    )
    return data.get("value", [])


def get_chat_messages(chat_id: str, max_count: int = 20) -> list[dict]:
    """
    Get recent messages from a Teams chat.

    Returns:
        List of message dicts: id, from, body, createdDateTime
    """
    data = _graph(
        "GET",
        f"/me/chats/{chat_id}/messages?$top={min(max_count, 50)}",
    )
    messages = []
    for m in data.get("value", []):
        sender = m.get("from", {})
        user = sender.get("user", {}) or sender.get("application", {}) or {}
        messages.append({
            "id": m.get("id"),
            "from": user.get("displayName", "Unknown"),
            "body": m.get("body", {}).get("content", ""),
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
    """Get recent messages from a Teams channel."""
    data = _graph(
        "GET",
        f"/teams/{team_id}/channels/{channel_id}/messages?$top={min(max_count, 50)}",
    )
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


# ─────────────────────────────────────────────
# EXCEL — Read and Write
# ─────────────────────────────────────────────

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
