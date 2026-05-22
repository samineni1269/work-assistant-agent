#!/bin/bash
# launch.command — double-click this file to start Work Assistant
# macOS: right-click → Open the first time (to bypass Gatekeeper)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Activate virtual environment ──────────────────────────────────────────────
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "❌  Virtual environment not found."
    echo "   Run:  python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    read -p "Press Enter to close..."
    exit 1
fi

# ── Check .env ────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "❌  .env file not found."
    echo "   Copy .env.example to .env and fill in your API keys."
    read -p "Press Enter to close..."
    exit 1
fi

# ── Install any missing dependencies ─────────────────────────────────────────
python3 -c "import flask" 2>/dev/null || {
    echo "📦  Installing dependencies..."
    pip3 install -r requirements.txt --quiet
}

# ── Launch ────────────────────────────────────────────────────────────────────
echo "🚀  Starting Work Assistant..."
echo "     Browser will open automatically at http://localhost:7432"
echo "     Close this window to stop the server."
python3 app.py
