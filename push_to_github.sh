#!/bin/bash
# push_to_github.sh — Push all changes to GitHub
# Run from the project folder:  bash push_to_github.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ⚡ Work Assistant Agent — GitHub Push"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Clean up any stale lock file ─────────────────────────────────────────────
rm -f .git/index.lock 2>/dev/null || true

git config user.name  "samineni1269"
git config user.email "gopik0808@gmail.com"

# ── Stage all changed files ───────────────────────────────────────────────────
echo "📦  Staging files..."
git add \
  README.md README_SETUP.md \
  .env.example .gitignore requirements.txt \
  agent.py app.py scheduler.py setup_wizard.py \
  launch.command setup.command setup.bat \
  fix_teams_auth.command debug_teams.py \
  tools/__init__.py tools/llm_provider.py tools/guardrails.py \
  tools/ms365.py tools/atlassian.py tools/github_tool.py \
  tools/linear_tool.py tools/office_docs.py tools/zoom_meet.py \
  tools/analytics.py tools/browser_tool.py tools/memory.py \
  tools/proactive.py tools/rag.py tools/tone_learner.py

git status --short

# ── Commit ─────────────────────────────────────────────────────────────────────
echo ""
echo "💾  Committing..."
git commit -m "fix: Teams API bugs + super-agent features + README troubleshooting guide

Teams Graph API fixes (tools/ms365.py):
- Remove \$orderby from /me/chats — not supported, caused 400 Bad Request
- Add Team.ReadBasic.All scope — was missing, caused 403 on /me/joinedTeams
- Remove ChannelMessage.Read.All from default scopes — requires admin consent
- Remove nested \$select from \$expand=members — not supported, caused 400
- Strip HTML from message bodies so the LLM reads plain text
- Rename chat id → chat_id so agent correctly passes it to get_chat_messages

Super-agent features:
- tools/memory.py: long-term persistent memory (SQLite)
- tools/rag.py: RAG knowledge base (ChromaDB + sentence-transformers)
- tools/proactive.py: background monitoring + SSE alerts
- tools/analytics.py: work pattern tracker
- tools/tone_learner.py: writing style learning
- tools/browser_tool.py: Playwright web automation
- agent.py: parallel tool execution, memory injection, post-turn analytics
- app.py: 13 per-tool workspaces, voice input, analytics dashboard

Tooling & docs:
- debug_teams.py: diagnostic script for Teams Graph API issues
- fix_teams_auth.command: clears token cache for scope re-auth
- README.md: full Teams API troubleshooting section with 6 documented issues" \
  2>/dev/null || echo "  (nothing new to commit)"

# ── Push ──────────────────────────────────────────────────────────────────────
echo ""
echo "🚀  Pushing to GitHub..."
echo "    (If prompted, enter your GitHub username and a Personal Access Token)"
echo "    Get a token at: https://github.com/settings/tokens"
echo ""
git push origin main

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Done! View your repo at:"
echo "      https://github.com/samineni1269/work-assistant-agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
