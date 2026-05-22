#!/bin/bash
# Push the super-agent update to GitHub
cd "$(dirname "$0")"

# Remove stale lock if it exists
rm -f .git/index.lock

git add agent.py app.py requirements.txt tools/llm_provider.py \
        tools/memory.py tools/rag.py tools/proactive.py \
        tools/analytics.py tools/tone_learner.py tools/browser_tool.py

git commit -m "feat: super agent — memory, RAG, proactive alerts, parallel tools, voice UI, analytics, tone learner, browser automation

- tools/memory.py: long-term persistent memory with auto-extraction
- tools/rag.py: RAG knowledge base (ChromaDB + sentence-transformers)
- tools/proactive.py: background monitor with SSE alert streaming
- tools/analytics.py: work pattern tracker (top tools, peak hours)
- tools/tone_learner.py: writing style fingerprinting from email samples
- tools/browser_tool.py: Playwright headless browser + DuckDuckGo search
- agent.py: _build_system_prompt() injects memory+tone, parallel tool
  execution via ThreadPoolExecutor, analytics logging every turn
- app.py: SSE /stream, voice mic (Web Speech API), analytics overlay,
  KB file upload, tone sample upload, notification bell,
  /analytics + /upload-doc + /upload-tone + /memory routes,
  proactive monitoring started on Flask startup
- requirements.txt: chromadb, sentence-transformers, playwright, pypdf"

git push
echo ""
echo "✅ Pushed to GitHub!"
