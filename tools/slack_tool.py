"""
slack_tool.py — Slack Integration
====================================
Covers: channels, DMs, message history, search, send messages
Auth:   Slack Bot Token (xoxb-...) from https://api.slack.com/apps
        Set SLACK_BOT_TOKEN in .env
        Required scopes: channels:read, channels:history, groups:read, groups:history,
                         im:read, im:history, mpim:read, mpim:history,
                         users:read, search:read, chat:write
API:    Slack Web API v2  (https://slack.com/api)
"""

import os
import requests
from datetime import datetime, timezone
from typing import Optional

SLACK_BASE = "https://slack.com/api"


# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

def _slack(method: str, endpoint: str, **kwargs) -> dict:
    """Make an authenticated Slack API call. Returns parsed JSON."""
    token = os.getenv("SLACK_BOT_TOKEN")
    if not token:
        raise ValueError(
            "\n❌  SLACK_BOT_TOKEN not set in .env\n"
            "   Create a Slack app at: https://api.slack.com/apps\n"
            "   Required scopes: channels:read, channels:history, im:read,\n"
            "                    im:history, search:read, chat:write, users:read\n"
        )
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.request(method, f"{SLACK_BASE}/{endpoint}", headers=headers, **kwargs)
    if not resp.ok:
        raise RuntimeError(f"Slack API HTTP error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')} — {data}")
    return data


def _ts_to_datetime(ts: str) -> str:
    """Convert Slack timestamp (unix float string) to ISO datetime."""
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return ts or ""


# ─────────────────────────────────────────────
# CHANNELS
# ─────────────────────────────────────────────

def list_slack_channels(max_count: int = 50, exclude_archived: bool = True) -> list[dict]:
    """
    List public and private channels the bot has access to.

    Returns:
        List of channel dicts: id, name, is_private, member_count, purpose, topic
    """
    params = {
        "limit": min(max_count, 200),
        "exclude_archived": exclude_archived,
        "types": "public_channel,private_channel",
    }
    data = _slack("GET", "conversations.list", params=params)
    return [
        {
            "id":           ch.get("id"),
            "name":         ch.get("name"),
            "is_private":   ch.get("is_private", False),
            "member_count": ch.get("num_members", 0),
            "purpose":      ch.get("purpose", {}).get("value", ""),
            "topic":        ch.get("topic", {}).get("value", ""),
        }
        for ch in data.get("channels", [])
    ]


def get_slack_messages(channel_id: str, max_count: int = 20) -> list[dict]:
    """
    Get recent messages from a Slack channel or group.

    Args:
        channel_id: Channel ID (e.g. 'C01234567' for channel, 'D01234567' for DM)
        max_count:  Max messages to return

    Returns:
        List of message dicts: user, text, ts, datetime, reactions, reply_count
    """
    params = {"channel": channel_id, "limit": min(max_count, 100)}
    data = _slack("GET", "conversations.history", params=params)

    messages = []
    for msg in data.get("messages", []):
        if msg.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
            # Skip system messages unless it's a useful bot message
            if msg.get("subtype") != "bot_message":
                continue
        messages.append({
            "user":        msg.get("user") or msg.get("username", "bot"),
            "text":        msg.get("text", ""),
            "ts":          msg.get("ts"),
            "datetime":    _ts_to_datetime(msg.get("ts", "")),
            "reply_count": msg.get("reply_count", 0),
            "reactions":   [
                f":{r['name']}: x{r['count']}"
                for r in msg.get("reactions", [])
            ],
        })
    return messages


def get_slack_thread(channel_id: str, thread_ts: str, max_count: int = 20) -> list[dict]:
    """
    Get replies in a Slack thread.

    Args:
        channel_id: Channel ID
        thread_ts:  Timestamp of the parent message (the ts field)

    Returns:
        List of reply message dicts
    """
    params = {"channel": channel_id, "ts": thread_ts, "limit": min(max_count, 100)}
    data = _slack("GET", "conversations.replies", params=params)
    return [
        {
            "user":     msg.get("user", ""),
            "text":     msg.get("text", ""),
            "datetime": _ts_to_datetime(msg.get("ts", "")),
        }
        for msg in data.get("messages", [])
    ]


# ─────────────────────────────────────────────
# DIRECT MESSAGES
# ─────────────────────────────────────────────

def list_slack_dms(max_count: int = 20) -> list[dict]:
    """
    List recent direct message (DM) conversations.

    Returns:
        List of DM dicts: id, user_id, created
    """
    params = {"limit": min(max_count, 100), "types": "im"}
    data = _slack("GET", "conversations.list", params=params)
    return [
        {
            "id":       ch.get("id"),
            "user_id":  ch.get("user"),
            "created":  datetime.fromtimestamp(ch.get("created", 0), tz=timezone.utc).strftime("%Y-%m-%d"),
        }
        for ch in data.get("channels", [])
    ]


def get_slack_dm_history(user_id: str, max_count: int = 20) -> list[dict]:
    """
    Get DM history with a specific Slack user.

    Args:
        user_id:   Slack user ID (e.g. 'U01234567')
        max_count: Max messages

    First opens a DM channel with the user, then fetches history.
    """
    # Open or retrieve the DM channel
    data = _slack("POST", "conversations.open", json={"users": user_id})
    channel_id = data.get("channel", {}).get("id")
    if not channel_id:
        raise RuntimeError(f"Could not open DM with user {user_id}")
    return get_slack_messages(channel_id, max_count=max_count)


# ─────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────

def search_slack(query: str, max_results: int = 15) -> list[dict]:
    """
    Search Slack messages across all channels.

    Args:
        query:       Search query (supports Slack modifiers: from:user, in:#channel, etc.)
        max_results: Max results

    Returns:
        List of result dicts: channel, user, text, datetime, permalink
    """
    params = {"query": query, "count": min(max_results, 100), "sort": "timestamp"}
    data = _slack("GET", "search.messages", params=params)

    matches = data.get("messages", {}).get("matches", [])
    return [
        {
            "channel":   m.get("channel", {}).get("name", ""),
            "user":      m.get("username", m.get("user", "")),
            "text":      m.get("text", "")[:500],
            "datetime":  _ts_to_datetime(m.get("ts", "")),
            "permalink": m.get("permalink", ""),
        }
        for m in matches
    ]


# ─────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────

def get_slack_user_info(user_id: str) -> dict:
    """
    Get display name and profile info for a Slack user ID.

    Returns:
        {"id": ..., "name": ..., "real_name": ..., "email": ..., "title": ...}
    """
    data = _slack("GET", "users.info", params={"user": user_id})
    user = data.get("user", {})
    profile = user.get("profile", {})
    return {
        "id":        user.get("id"),
        "name":      user.get("name"),
        "real_name": user.get("real_name", ""),
        "email":     profile.get("email", ""),
        "title":     profile.get("title", ""),
    }


def lookup_slack_user_by_email(email: str) -> dict:
    """
    Find a Slack user by their email address.

    Returns:
        User dict with id, name, real_name
    """
    data = _slack("GET", "users.lookupByEmail", params={"email": email})
    user = data.get("user", {})
    return {
        "id":        user.get("id"),
        "name":      user.get("name"),
        "real_name": user.get("real_name", ""),
    }


# ─────────────────────────────────────────────
# SEND MESSAGE
# ─────────────────────────────────────────────

def send_slack_message(
    channel_id: str,
    text: str,
    thread_ts: str = None,
) -> dict:
    """
    Send a message to a Slack channel, DM, or thread.

    Args:
        channel_id: Channel or DM ID (e.g. 'C01234', 'D01234', or '#general')
        text:       Message text (supports Slack markdown: *bold*, _italic_, `code`)
        thread_ts:  If provided, replies to this thread (parent message ts)

    Returns:
        {"status": "sent", "channel": ..., "ts": ...}
    """
    payload = {"channel": channel_id, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts

    result = _slack("POST", "chat.postMessage", json=payload)
    return {
        "status":  "sent",
        "channel": result.get("channel"),
        "ts":      result.get("ts"),
    }
