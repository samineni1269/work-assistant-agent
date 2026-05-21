#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Work Assistant Agent — Setup Wizard Launcher (Mac / Linux)
# Double-click this file to run the interactive setup wizard.
# ─────────────────────────────────────────────────────────────────────────────

# Move to the folder this script lives in
cd "$(dirname "$0")"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       Work Assistant Agent — Setup Wizard                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Check Python 3 ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌  Python 3 is not installed."
    echo ""
    echo "   Install it from: https://www.python.org/downloads/"
    echo "   Then double-click this file again."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅  Python $PYTHON_VERSION found"

# ── Create virtual environment if missing ────────────────────────────────────
if [ ! -d "venv" ]; then
    echo "📦  Creating virtual environment (first time only)…"
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌  Failed to create virtual environment."
        read -p "Press Enter to close..."
        exit 1
    fi
    echo "✅  Virtual environment created"
fi

# ── Activate venv ────────────────────────────────────────────────────────────
source venv/bin/activate

# ── Install / update dependencies ────────────────────────────────────────────
echo "📦  Installing dependencies (this takes ~30 seconds on first run)…"
pip install -r requirements.txt --quiet --disable-pip-version-check 2>&1 | tail -3
if [ $? -ne 0 ]; then
    echo ""
    echo "⚠   pip install had warnings above. Trying with --break-system-packages…"
    pip install -r requirements.txt --quiet --break-system-packages 2>&1 | tail -3
fi
echo "✅  Dependencies ready"
echo ""

# ── Run the wizard ────────────────────────────────────────────────────────────
python3 setup_wizard.py "$@"

echo ""
read -p "Press Enter to close this window…"
