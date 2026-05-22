#!/usr/bin/env python3
"""
debug_teams.py — run this from the work-assistant-agent folder to see the
exact Graph API error when fetching Teams chats.

Usage:
    source venv/bin/activate
    python3 debug_teams.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from tools.ms365 import _graph, get_access_token, GRAPH_SCOPES, TOKEN_CACHE_PATH

print("=" * 60)
print("Work Assistant — Teams Debug")
print("=" * 60)

# 1. Check token cache
print(f"\n1. Token cache: {TOKEN_CACHE_PATH}")
print(f"   Exists: {TOKEN_CACHE_PATH.exists()}")

# 2. Get token
print("\n2. Acquiring token (may prompt you to sign in)...")
try:
    token = get_access_token()
    print(f"   ✅  Got token ({len(token)} chars)")
except Exception as e:
    print(f"   ❌  Auth failed: {e}")
    sys.exit(1)

# 3. Check /me
print("\n3. Testing /me endpoint...")
try:
    me = _graph("GET", "/me?$select=displayName,mail,userPrincipalName")
    print(f"   ✅  Signed in as: {me.get('displayName')} ({me.get('mail') or me.get('userPrincipalName')})")
except Exception as e:
    print(f"   ❌  /me failed: {e}")

# 4. Raw chats call — no $expand to isolate the issue
print("\n4. Testing /me/chats (no expand)...")
try:
    data = _graph("GET", "/me/chats?$top=5&$select=id,topic,chatType,lastUpdatedDateTime")
    chats = data.get("value", [])
    print(f"   ✅  Got {len(chats)} chats")
    for c in chats[:3]:
        print(f"       - [{c.get('chatType')}] {c.get('topic') or '(no topic)'} — {c.get('lastUpdatedDateTime', '')[:10]}")
except Exception as e:
    print(f"   ❌  /me/chats failed: {e}")

# 5. Chats with members expand
print("\n5. Testing /me/chats with $expand=members...")
try:
    data = _graph("GET", "/me/chats?$top=5&$select=id,topic,chatType,lastUpdatedDateTime&$expand=members($select=id,displayName,roles)")
    chats = data.get("value", [])
    print(f"   ✅  Got {len(chats)} chats with members")
except Exception as e:
    print(f"   ❌  /me/chats + expand failed: {e}")

# 6. List joined teams
print("\n6. Testing /me/joinedTeams...")
try:
    data = _graph("GET", "/me/joinedTeams?$select=id,displayName")
    teams = data.get("value", [])
    print(f"   ✅  Got {len(teams)} teams")
    for t in teams[:3]:
        print(f"       - {t.get('displayName')}")
except Exception as e:
    print(f"   ❌  /me/joinedTeams failed: {e}")

# 7. Read messages from first chat
print("\n7. Testing message read from first chat...")
try:
    data = _graph("GET", "/me/chats?$top=1&$select=id,topic,chatType")
    chats = data.get("value", [])
    if chats:
        chat_id = chats[0]["id"]
        print(f"   Chat ID: {chat_id[:40]}...")
        msgs = _graph("GET", f"/me/chats/{chat_id}/messages?$top=5")
        print(f"   ✅  Got {len(msgs.get('value', []))} messages")
        for m in msgs.get("value", [])[:3]:
            sender = m.get("from", {})
            user = sender.get("user", {}) or {}
            body = m.get("body", {}).get("content", "")[:80]
            print(f"       [{user.get('displayName','?')}]: {body}")
    else:
        print("   No chats found")
except Exception as e:
    print(f"   ❌  Message read failed: {e}")

print("\n" + "=" * 60)
print("Debug complete.")
print("=" * 60)
