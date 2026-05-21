"""
zoom_meet.py — Zoom & Google Meet Tools
=========================================
Zoom:        Server-to-Server OAuth (no browser auth needed)
             Credentials: ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET
             App type: Server-to-Server OAuth at https://marketplace.zoom.us

Google Meet: Creates meetings via Google Calendar API
             Credentials: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
             Auth: OAuth 2.0 device code flow (user authenticates once in browser)
             Scopes: calendar.events, calendar.readonly
"""

import os
import base64
import json
import requests
import datetime
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════════════════════════
# ZOOM
# ══════════════════════════════════════════════════════════════════════════════

ZOOM_BASE = "https://api.zoom.us/v2"
_zoom_token_cache = {"token": None, "expires_at": 0}


def _get_zoom_token() -> str:
    """Get a Zoom access token using Server-to-Server OAuth. Caches until expiry."""
    import time

    if _zoom_token_cache["token"] and time.time() < _zoom_token_cache["expires_at"] - 60:
        return _zoom_token_cache["token"]

    account_id    = os.getenv("ZOOM_ACCOUNT_ID")
    client_id     = os.getenv("ZOOM_CLIENT_ID")
    client_secret = os.getenv("ZOOM_CLIENT_SECRET")

    missing = [k for k, v in {
        "ZOOM_ACCOUNT_ID": account_id,
        "ZOOM_CLIENT_ID": client_id,
        "ZOOM_CLIENT_SECRET": client_secret,
    }.items() if not v]

    if missing:
        raise ValueError(
            f"\n❌  Missing Zoom env vars: {', '.join(missing)}\n"
            "   Create a Server-to-Server OAuth app at: https://marketplace.zoom.us\n"
            "   See README_SETUP.md Step 5 (Zoom) for instructions.\n"
        )

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}",
        headers={"Authorization": f"Basic {credentials}"},
    )
    resp.raise_for_status()
    data = resp.json()

    import time
    _zoom_token_cache["token"] = data["access_token"]
    _zoom_token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)

    return data["access_token"]


def _zoom(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated Zoom API call."""
    token = _get_zoom_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, f"{ZOOM_BASE}{path}", headers=headers, **kwargs)
    if resp.status_code == 204:
        return {"status": "success"}
    if not resp.ok:
        raise RuntimeError(f"Zoom API error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


# ── Zoom meetings ─────────────────────────────────────────────────────────────

def list_zoom_meetings(meeting_type: str = "upcoming") -> list[dict]:
    """
    List Zoom meetings.

    Args:
        meeting_type: 'upcoming', 'live', or 'scheduled'

    Returns:
        List of meeting dicts: id, topic, start_time, duration, join_url, agenda
    """
    data = _zoom("GET", f"/users/me/meetings?type={meeting_type}&page_size=30")
    meetings = []
    for m in data.get("meetings", []):
        meetings.append({
            "id":         m.get("id"),
            "topic":      m.get("topic"),
            "start_time": m.get("start_time"),
            "duration":   m.get("duration"),    # minutes
            "join_url":   m.get("join_url"),
            "agenda":     m.get("agenda", ""),
            "status":     m.get("status", "waiting"),
        })
    return meetings


def get_zoom_meeting(meeting_id: str) -> dict:
    """
    Get full details of a Zoom meeting including join URL, password, and settings.
    """
    data = _zoom("GET", f"/meetings/{meeting_id}")
    return {
        "id":           data.get("id"),
        "topic":        data.get("topic"),
        "start_time":   data.get("start_time"),
        "duration":     data.get("duration"),
        "timezone":     data.get("timezone"),
        "join_url":     data.get("join_url"),
        "password":     data.get("password"),
        "agenda":       data.get("agenda"),
        "host_email":   data.get("host_email"),
        "settings": {
            "waiting_room":      data.get("settings", {}).get("waiting_room"),
            "join_before_host":  data.get("settings", {}).get("join_before_host"),
            "mute_upon_entry":   data.get("settings", {}).get("mute_upon_entry"),
            "auto_recording":    data.get("settings", {}).get("auto_recording"),
        },
    }


def create_zoom_meeting(
    topic: str,
    start_time: str,
    duration: int = 60,
    agenda: str = "",
    timezone: str = "UTC",
    waiting_room: bool = True,
    auto_record: bool = False,
) -> dict:
    """
    Create a Zoom meeting.

    Args:
        topic:       Meeting title
        start_time:  ISO 8601 start time e.g. '2025-06-01T14:00:00'
        duration:    Duration in minutes (default: 60)
        agenda:      Meeting description/agenda
        timezone:    Timezone string e.g. 'America/New_York', 'Europe/London', 'UTC'
        waiting_room: Enable waiting room (default: True)
        auto_record: Auto-record to cloud (default: False)

    Returns:
        {"status": "created", "id": ..., "join_url": ..., "password": ..., "start_time": ...}
    """
    payload = {
        "topic": topic,
        "type": 2,  # Scheduled meeting
        "start_time": start_time,
        "duration": duration,
        "agenda": agenda,
        "timezone": timezone,
        "settings": {
            "waiting_room": waiting_room,
            "auto_recording": "cloud" if auto_record else "none",
            "join_before_host": False,
            "mute_upon_entry": True,
            "participant_video": False,
        },
    }
    data = _zoom("POST", "/users/me/meetings", json=payload)
    return {
        "status":     "created",
        "id":         data.get("id"),
        "topic":      data.get("topic"),
        "join_url":   data.get("join_url"),
        "password":   data.get("password"),
        "start_time": data.get("start_time"),
        "duration":   data.get("duration"),
    }


def update_zoom_meeting(
    meeting_id: str,
    topic: str = None,
    start_time: str = None,
    duration: int = None,
    agenda: str = None,
) -> dict:
    """Update an existing Zoom meeting."""
    payload = {}
    if topic:      payload["topic"] = topic
    if start_time: payload["start_time"] = start_time
    if duration:   payload["duration"] = duration
    if agenda:     payload["agenda"] = agenda

    if not payload:
        return {"status": "no_changes"}

    _zoom("PATCH", f"/meetings/{meeting_id}", json=payload)
    return {"status": "updated", "id": meeting_id}


def delete_zoom_meeting(meeting_id: str) -> dict:
    """Delete a Zoom meeting."""
    _zoom("DELETE", f"/meetings/{meeting_id}")
    return {"status": "deleted", "id": meeting_id}


def list_zoom_recordings(days_back: int = 7) -> list[dict]:
    """
    List cloud recordings from the last N days.

    Returns:
        List of recording dicts: topic, start_time, duration, recording_files
    """
    from_date = (datetime.datetime.utcnow() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
    data = _zoom("GET", f"/users/me/recordings?from={from_date}&page_size=30")
    meetings = []
    for m in data.get("meetings", []):
        files = [
            {"type": f.get("recording_type"), "url": f.get("play_url"), "size": f.get("file_size")}
            for f in m.get("recording_files", [])
            if f.get("status") == "completed"
        ]
        meetings.append({
            "id":         m.get("id"),
            "topic":      m.get("topic"),
            "start_time": m.get("start_time"),
            "duration":   m.get("duration"),
            "files":      files,
        })
    return meetings


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE MEET
# ══════════════════════════════════════════════════════════════════════════════

GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]
GOOGLE_TOKEN_CACHE = Path.home() / ".work-assistant-google-token.json"
GOOGLE_CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"


def _get_google_token() -> str:
    """
    Get a Google OAuth token using device code flow.
    Caches the token locally — user only authenticates once.
    """
    import time
    client_id     = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "\n❌  GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set in .env\n"
            "   Create OAuth credentials at: https://console.cloud.google.com/apis/credentials\n"
            "   See README_SETUP.md Step 6 (Google Meet) for instructions.\n"
        )

    # Load cached token
    if GOOGLE_TOKEN_CACHE.exists():
        cached = json.loads(GOOGLE_TOKEN_CACHE.read_text())
        # Try refreshing
        if cached.get("refresh_token"):
            resp = requests.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id":     client_id,
                    "client_secret": client_secret,
                    "refresh_token": cached["refresh_token"],
                    "grant_type":    "refresh_token",
                },
            )
            if resp.ok:
                new_data = resp.json()
                cached["access_token"] = new_data["access_token"]
                GOOGLE_TOKEN_CACHE.write_text(json.dumps(cached))
                return new_data["access_token"]

    # Device code flow
    device_resp = requests.post(
        "https://oauth2.googleapis.com/device/code",
        data={
            "client_id": client_id,
            "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
        },
    )
    device_resp.raise_for_status()
    device_data = device_resp.json()

    print("\n" + "=" * 60)
    print("🔐  Google Sign-In Required (for Google Meet)")
    print("=" * 60)
    print(f"\n  1. Go to:  {device_data['verification_url']}")
    print(f"  2. Enter code:  {device_data['user_code']}")
    print("\n  Waiting for sign-in...")

    interval = device_data.get("interval", 5)
    deadline = time.time() + device_data.get("expires_in", 300)

    while time.time() < deadline:
        time.sleep(interval)
        poll = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id":   client_id,
                "client_secret": client_secret,
                "device_code": device_data["device_code"],
                "grant_type":  "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        poll_data = poll.json()
        if "access_token" in poll_data:
            GOOGLE_TOKEN_CACHE.write_text(json.dumps(poll_data))
            return poll_data["access_token"]
        if poll_data.get("error") not in ("authorization_pending", "slow_down"):
            raise RuntimeError(f"Google auth failed: {poll_data}")

    raise TimeoutError("Google authentication timed out")


def _gcal(method: str, path: str, **kwargs) -> dict:
    """Make an authenticated Google Calendar API call."""
    token = _get_google_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.request(
        method, f"{GOOGLE_CALENDAR_BASE}{path}", headers=headers, **kwargs
    )
    if resp.status_code == 204:
        return {"status": "success"}
    if not resp.ok:
        raise RuntimeError(f"Google Calendar API error {resp.status_code}: {resp.text[:400]}")
    return resp.json()


# ── Google Meet / Calendar ────────────────────────────────────────────────────

def list_google_calendar_events(days_ahead: int = 1) -> list[dict]:
    """
    List Google Calendar events for the next N days (includes Google Meet links).

    Returns:
        List of event dicts: summary, start, end, attendees, meet_link, hangout_link
    """
    now = datetime.datetime.utcnow().isoformat() + "Z"
    end = (datetime.datetime.utcnow() + datetime.timedelta(days=days_ahead)).isoformat() + "Z"
    data = _gcal(
        "GET",
        f"/calendars/primary/events"
        f"?timeMin={now}&timeMax={end}&singleEvents=true&orderBy=startTime&maxResults=50",
    )
    events = []
    for e in data.get("items", []):
        start = e.get("start", {})
        end_t = e.get("end", {})
        conf = e.get("conferenceData", {})
        meet_link = ""
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_link = ep.get("uri", "")

        events.append({
            "id":         e.get("id"),
            "summary":    e.get("summary", "(no title)"),
            "start":      start.get("dateTime") or start.get("date"),
            "end":        end_t.get("dateTime") or end_t.get("date"),
            "location":   e.get("location", ""),
            "description": (e.get("description") or "")[:200],
            "meet_link":  meet_link or e.get("hangoutLink", ""),
            "attendees":  [a.get("email") for a in e.get("attendees", [])],
            "status":     e.get("status"),
            "organizer":  e.get("organizer", {}).get("email", ""),
        })
    return events


def create_google_meet(
    title: str,
    start: str,
    end: str,
    attendees: list[str] = None,
    description: str = "",
    timezone: str = "UTC",
) -> dict:
    """
    Create a Google Calendar event with a Google Meet video link.

    Args:
        title:       Meeting title
        start:       ISO 8601 start time e.g. '2025-06-01T14:00:00'
        end:         ISO 8601 end time
        attendees:   List of attendee email addresses
        description: Meeting description
        timezone:    Timezone string e.g. 'Europe/London', 'America/New_York'

    Returns:
        {"status": "created", "id": ..., "meet_link": ..., "html_link": ...}
    """
    import uuid

    payload = {
        "summary": title,
        "description": description,
        "start":  {"dateTime": start, "timeZone": timezone},
        "end":    {"dateTime": end,   "timeZone": timezone},
        "conferenceData": {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    if attendees:
        payload["attendees"] = [{"email": a} for a in attendees]

    data = _gcal(
        "POST",
        "/calendars/primary/events?conferenceDataVersion=1",
        json=payload,
    )

    # Extract Meet link
    meet_link = ""
    for ep in data.get("conferenceData", {}).get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            meet_link = ep.get("uri", "")

    return {
        "status":    "created",
        "id":        data.get("id"),
        "title":     data.get("summary"),
        "start":     data.get("start", {}).get("dateTime"),
        "end":       data.get("end", {}).get("dateTime"),
        "meet_link": meet_link or data.get("hangoutLink", ""),
        "html_link": data.get("htmlLink", ""),
    }


def delete_google_calendar_event(event_id: str) -> dict:
    """Delete a Google Calendar event."""
    _gcal("DELETE", f"/calendars/primary/events/{event_id}")
    return {"status": "deleted", "id": event_id}
