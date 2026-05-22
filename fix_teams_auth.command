#!/bin/bash
# Fix Teams auth — clears old token so agent re-authenticates with correct scopes
echo ""
echo "🔧  Fixing Teams auth..."
echo ""

CACHE="$HOME/.work-assistant-token-cache.json"

if [ -f "$CACHE" ]; then
    rm "$CACHE"
    echo "✅  Deleted old token cache: $CACHE"
    echo "    The agent will ask you to sign in again next time it starts."
else
    echo "ℹ️   No token cache found — nothing to delete."
fi

echo ""
echo "The 3 bugs fixed in tools/ms365.py:"
echo "  1. /me/chats $orderby → was causing 400 Bad Request (now sorted in Python)"
echo "  2. Team.ReadBasic.All scope was missing → list_teams() was getting 403"
echo "  3. ChannelMessage.Read.All removed from default scopes → needed admin consent"
echo ""
echo "Now restart your agent (python app.py) and sign in when prompted."
echo ""
read -p "Press Enter to close..."
