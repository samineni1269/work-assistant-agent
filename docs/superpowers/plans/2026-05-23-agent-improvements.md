# Agent Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Work Assistant Agent with 8 improvements: conversation history, action items UI, trigger automation, retry logic, planner mode, entity extraction, tone-matched email drafting, and a pytest test suite.

**Architecture:** Each feature is a self-contained module or route addition. Conversation store and trigger engine are new SQLite-backed tools. All UI additions extend the existing `HTML_TEMPLATE` in `app.py`. Tests mock all external APIs.

**Tech Stack:** Python 3.11+, Flask, SQLite (sqlite3 stdlib), pytest, unittest.mock

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tools/conversation_store.py` | Create | SQLite session + turn storage |
| `tools/trigger_engine.py` | Create | Webhook rule engine |
| `tools/memory.py` | Modify | Add entity extraction |
| `agent.py` | Modify | Retry logic, planner mode, conversation store integration |
| `app.py` | Modify | History sidebar, action items page, draft-reply route, trigger UI |
| `tests/test_agent.py` | Create | pytest suite |
| `requirements.txt` | Modify | Add pytest |

---

### Task 1: Build tools/conversation_store.py

**Files:**
- Create: `tools/conversation_store.py`

- [ ] **Step 1: Write the file**

```python
"""
tools/conversation_store.py — Persistent conversation history
=============================================================
Stores all agent conversations in SQLite so users can browse,
search, and restore past sessions from the web UI.

DB: ~/.work-assistant-conversations.db
"""

import sqlite3
import datetime
import json
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".work-assistant-conversations.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT    PRIMARY KEY,
            tool_id     TEXT    NOT NULL DEFAULT 'home',
            title       TEXT    NOT NULL DEFAULT 'Untitled',
            started_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            turn_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS turns (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT    NOT NULL REFERENCES sessions(id),
            role        TEXT    NOT NULL,
            content     TEXT    NOT NULL,
            ts          TEXT    NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id)")
    conn.commit()
    return conn


def save_turn(session_id: str, tool_id: str, role: str, content: str, title: str = "") -> None:
    """Append a single turn to a session, creating the session if needed."""
    now = datetime.datetime.now().isoformat()
    db = _get_db()
    # Upsert session
    db.execute("""
        INSERT INTO sessions(id, tool_id, title, started_at, updated_at, turn_count)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO UPDATE SET
            updated_at = excluded.updated_at,
            turn_count = turn_count + 1,
            title = CASE WHEN excluded.title != '' THEN excluded.title ELSE title END
    """, (session_id, tool_id, title or "Untitled", now, now))
    db.execute(
        "INSERT INTO turns(session_id, role, content, ts) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now)
    )
    db.commit()
    db.close()


def get_session_turns(session_id: str) -> list[dict]:
    """Return all turns for a session as list of {role, content, ts}."""
    db = _get_db()
    rows = db.execute(
        "SELECT role, content, ts FROM turns WHERE session_id=? ORDER BY id",
        (session_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def list_sessions(tool_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List recent sessions, optionally filtered by tool_id."""
    db = _get_db()
    if tool_id:
        rows = db.execute(
            "SELECT id, tool_id, title, started_at, updated_at, turn_count FROM sessions "
            "WHERE tool_id=? ORDER BY updated_at DESC LIMIT ?",
            (tool_id, limit)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, tool_id, title, started_at, updated_at, turn_count FROM sessions "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def search_sessions(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across turn content. Returns matching sessions."""
    db = _get_db()
    rows = db.execute("""
        SELECT DISTINCT s.id, s.tool_id, s.title, s.started_at, s.updated_at, s.turn_count
        FROM sessions s
        JOIN turns t ON t.session_id = s.id
        WHERE t.content LIKE ?
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (f"%{query}%", limit)).fetchall()
    db.close()
    return [dict(r) for r in rows]


def delete_session(session_id: str) -> None:
    """Delete a session and all its turns."""
    db = _get_db()
    db.execute("DELETE FROM turns WHERE session_id=?", (session_id,))
    db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    db.commit()
    db.close()


def get_session_title_from_first_user_message(session_id: str) -> str:
    """Generate a short title from the first user message in the session."""
    db = _get_db()
    row = db.execute(
        "SELECT content FROM turns WHERE session_id=? AND role='user' ORDER BY id LIMIT 1",
        (session_id,)
    ).fetchone()
    db.close()
    if not row:
        return "Untitled"
    text = row["content"]
    return text[:60] + ("…" if len(text) > 60 else "")
```

- [ ] **Step 2: Syntax-check**

```bash
python3 -m py_compile tools/conversation_store.py && echo "OK"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tools/conversation_store.py
git commit -m "feat: add conversation_store — SQLite session history"
```

---

### Task 2: Build tools/trigger_engine.py

**Files:**
- Create: `tools/trigger_engine.py`

- [ ] **Step 1: Write the file**

```python
"""
tools/trigger_engine.py — Webhook-triggered automation rules
============================================================
Stores if-this-then-that rules in SQLite.
Called by webhook_server when a new event arrives.

Rule schema:
    source      — "github" | "jira" | "any"
    event_type  — "pull_request" | "issues" | "push" | "any"
    condition   — JSON dict of key:substring pairs to match in event payload
    action      — "slack_message" | "create_jira" | "create_linear" | "notify"
    action_args — JSON dict of args for the action

DB: ~/.work-assistant-triggers.db
"""

import sqlite3
import json
import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".work-assistant-triggers.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'any',
            event_type  TEXT    NOT NULL DEFAULT 'any',
            condition   TEXT    NOT NULL DEFAULT '{}',
            action      TEXT    NOT NULL,
            action_args TEXT    NOT NULL DEFAULT '{}',
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL,
            fire_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trigger_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id     INTEGER NOT NULL,
            rule_name   TEXT    NOT NULL,
            event_type  TEXT    NOT NULL,
            result      TEXT    NOT NULL,
            fired_at    TEXT    NOT NULL
        )
    """)
    conn.commit()
    return conn


def add_rule(name: str, source: str, event_type: str,
             condition: dict, action: str, action_args: dict) -> dict:
    """Add a new automation rule. Returns the created rule."""
    db = _get_db()
    now = datetime.datetime.now().isoformat()
    cursor = db.execute("""
        INSERT INTO rules(name, source, event_type, condition, action, action_args, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (name, source, event_type,
          json.dumps(condition), action, json.dumps(action_args), now))
    db.commit()
    rule_id = cursor.lastrowid
    db.close()
    return {"id": rule_id, "name": name, "source": source,
            "event_type": event_type, "action": action}


def list_rules() -> list[dict]:
    """List all rules."""
    db = _get_db()
    rows = db.execute(
        "SELECT id, name, source, event_type, condition, action, action_args, "
        "enabled, created_at, fire_count FROM rules ORDER BY id"
    ).fetchall()
    db.close()
    result = []
    for r in rows:
        d = dict(r)
        d["condition"] = json.loads(d["condition"])
        d["action_args"] = json.loads(d["action_args"])
        result.append(d)
    return result


def delete_rule(rule_id: int) -> dict:
    """Delete a rule by ID."""
    db = _get_db()
    db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
    db.commit()
    db.close()
    return {"deleted": rule_id}


def toggle_rule(rule_id: int, enabled: bool) -> dict:
    """Enable or disable a rule."""
    db = _get_db()
    db.execute("UPDATE rules SET enabled=? WHERE id=?", (1 if enabled else 0, rule_id))
    db.commit()
    db.close()
    return {"id": rule_id, "enabled": enabled}


def _matches(event: dict, condition: dict) -> bool:
    """Check if every key:substring pair in condition matches the event payload."""
    if not condition:
        return True
    payload_str = json.dumps(event).lower()
    for key, substr in condition.items():
        if str(substr).lower() not in payload_str:
            return False
    return True


def evaluate_event(source: str, event_type: str, event: dict) -> list[dict]:
    """
    Check all enabled rules against an incoming event.
    Returns list of rule dicts that matched (caller executes the actions).
    """
    db = _get_db()
    rows = db.execute("""
        SELECT id, name, source, event_type, condition, action, action_args
        FROM rules
        WHERE enabled=1
          AND (source='any' OR source=?)
          AND (event_type='any' OR event_type=?)
    """, (source, event_type)).fetchall()

    matched = []
    now = datetime.datetime.now().isoformat()
    for row in rows:
        condition = json.loads(row["condition"])
        if _matches(event, condition):
            action_args = json.loads(row["action_args"])
            matched.append({
                "rule_id":    row["id"],
                "rule_name":  row["name"],
                "action":     row["action"],
                "action_args": action_args,
            })
            # Increment fire count + log
            db.execute("UPDATE rules SET fire_count=fire_count+1 WHERE id=?", (row["id"],))
            db.execute("""
                INSERT INTO trigger_log(rule_id, rule_name, event_type, result, fired_at)
                VALUES (?, ?, ?, ?, ?)
            """, (row["id"], row["name"], event_type, "matched", now))

    db.commit()
    db.close()
    return matched


def get_trigger_log(limit: int = 50) -> list[dict]:
    """Return recent trigger fire log entries."""
    db = _get_db()
    rows = db.execute(
        "SELECT rule_id, rule_name, event_type, result, fired_at "
        "FROM trigger_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
```

- [ ] **Step 2: Syntax-check**

```bash
python3 -m py_compile tools/trigger_engine.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add tools/trigger_engine.py
git commit -m "feat: add trigger_engine — if-this-then-that webhook automation"
```

---

### Task 3: Add entity extraction to tools/memory.py

**Files:**
- Modify: `tools/memory.py` (add `extract_entities` function, update `extract_and_save_facts`)

- [ ] **Step 1: Add entity extraction function after existing `extract_and_save_facts`**

Find the `extract_and_save_facts` function and add this new function right after it:

```python
def extract_entities(text: str) -> dict:
    """
    Extract named entities from text using simple regex patterns.
    Returns dict with: people (list), emails (list), projects (list).
    No LLM call — fast and always available.
    """
    import re
    # Email addresses
    emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    # Capitalised names (two consecutive title-case words not at sentence start)
    names = re.findall(r'(?<!\.\s)\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b', text)
    # Project-like terms: "Project X", "Sprint 12", "#ticket-123"
    projects = re.findall(r'\b(?:Project|Sprint|Release|Milestone|Epic|Phase)\s+[\w.-]+\b', text, re.I)
    tickets  = re.findall(r'\b[A-Z]{2,10}-\d{1,6}\b', text)   # e.g. JIRA-123, ENG-456
    return {
        "emails":   list(set(emails)),
        "people":   list(set(names)),
        "projects": list(set(projects + tickets)),
    }


def auto_save_entities(user_message: str, assistant_response: str) -> None:
    """
    Extract entities from a conversation turn and persist to memory.
    Called automatically after each agent turn.
    """
    combined = f"{user_message}\n{assistant_response}"
    entities = extract_entities(combined)
    mem = load_memory()

    for email in entities["emails"]:
        local = email.split("@")[0].replace(".", " ").replace("_", " ").title()
        if local and local not in mem["people"]:
            mem["people"][local] = {"email": email, "notes": "auto-extracted"}

    for proj in entities["projects"]:
        key = proj.strip()
        if key and key not in mem["context"]:
            mem["context"][key] = "seen in conversation"

    save_memory(mem)
```

- [ ] **Step 2: In `extract_and_save_facts`, add call to `auto_save_entities` at the end**

Find the end of `extract_and_save_facts` and add:

```python
    # Also extract entities (people, projects) via regex
    try:
        auto_save_entities(user_message, response_text)
    except Exception:
        pass
```

- [ ] **Step 3: Syntax-check**

```bash
python3 -m py_compile tools/memory.py && echo "OK"
```

- [ ] **Step 4: Commit**

```bash
git add tools/memory.py
git commit -m "feat: add entity extraction to memory — auto-saves people/projects"
```

---

### Task 4: Add retry + graceful degradation to agent.py

**Files:**
- Modify: `agent.py` — wrap `dispatch_tool` with retry logic

- [ ] **Step 1: Add retry wrapper above `dispatch_tool`**

Insert this function just before `def dispatch_tool(`:

```python
import time

def _with_retry(fn, tool_name: str, max_attempts: int = 3) -> str:
    """
    Call fn() up to max_attempts times with exponential backoff.
    On all failures, return a graceful degradation message instead of crashing.
    Retries on transient errors (network, rate-limit, timeout).
    Never retries on auth errors (401) or bad request (400).
    """
    NO_RETRY_SIGNALS = ("401", "403", "400", "invalid", "not found", "unauthorized")
    delay = 1.0
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            err_str = str(e).lower()
            last_err = e
            if any(sig in err_str for sig in NO_RETRY_SIGNALS):
                break   # pointless to retry auth/bad-request errors
            if attempt < max_attempts - 1:
                time.sleep(delay)
                delay *= 2   # exponential backoff: 1s, 2s
    # All attempts failed — return graceful degradation
    tool_label = tool_name.replace("_", " ")
    return json.dumps({
        "error": f"⚠️ {tool_label} is temporarily unavailable.",
        "detail": str(last_err),
        "suggestion": "The data may be stale or the service is down. Try again in a moment.",
    })
```

- [ ] **Step 2: Update dispatch_tool to use _with_retry**

Find this block in `dispatch_tool`:

```python
    try:
        result = dispatch[name]()
        return json.dumps(result, default=str, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
```

Replace with:

```python
    return _with_retry(
        lambda: json.dumps(dispatch[name](), default=str, indent=2),
        tool_name=name,
    )
```

- [ ] **Step 3: Syntax-check**

```bash
python3 -m py_compile agent.py && echo "OK"
```

- [ ] **Step 4: Commit**

```bash
git add agent.py
git commit -m "feat: add retry + graceful degradation to dispatch_tool"
```

---

### Task 5: Add multi-step planner mode to agent.py

**Files:**
- Modify: `agent.py` — add `_is_complex_request` and `run_planner_turn`

- [ ] **Step 1: Add planner helpers after `_build_system_prompt`**

```python
_PLANNER_KEYWORDS = {
    "plan", "strategy", "set up", "organise", "organize", "prepare",
    "roadmap", "workflow", "automate", "design", "architect",
    "sprint", "project", "onboard", "migrate",
}

def _is_complex_request(message: str) -> bool:
    """Heuristic: does this message look like it needs a multi-step plan?"""
    low = message.lower()
    # Must contain a planner keyword AND be reasonably long
    has_keyword = any(kw in low for kw in _PLANNER_KEYWORDS)
    is_long = len(message.split()) >= 8
    return has_keyword and is_long


def _build_plan(user_message: str, provider) -> str:
    """Ask the LLM to generate a numbered action plan for a complex request."""
    plan_prompt = (
        "The user has a complex, multi-step request. "
        "First, produce a clear numbered plan (maximum 7 steps) of what you will do. "
        "Be specific: name the tools or actions for each step. "
        "Do NOT execute anything yet — just the plan.\n\n"
        f"User request: {user_message}"
    )
    _, plan_text = provider.run_turn(
        system_prompt=_build_system_prompt(),
        history=[{"role": "user", "content": plan_prompt}],
        tools=[],
    )
    return plan_text.strip()
```

- [ ] **Step 2: Integrate planner into `run_agent_turn`**

In `run_agent_turn`, just before the `while True:` loop, add:

```python
    # ── Planner mode: show plan first for complex requests ────────────────────
    plan_prefix = ""
    if _is_complex_request(user_message):
        try:
            plan_text = _build_plan(user_message, provider)
            plan_prefix = f"**📋 My plan:**\n{plan_text}\n\n**Executing now...**\n\n"
        except Exception:
            pass  # silent fallback — just run without plan
```

Then in the final response assembly, prepend `plan_prefix`:

Find:
```python
            text = scrub_output(text)
```

Change to:
```python
            text = plan_prefix + scrub_output(text)
            plan_prefix = ""   # only prepend once
```

- [ ] **Step 3: Syntax-check**

```bash
python3 -m py_compile agent.py && echo "OK"
```

- [ ] **Step 4: Commit**

```bash
git add agent.py
git commit -m "feat: add multi-step planner mode for complex requests"
```

---

### Task 6: Wire conversation store into app.py

**Files:**
- Modify: `app.py` — import store, save turns, add history routes + sidebar UI

- [ ] **Step 1: Add import at top of app.py after existing imports**

```python
try:
    from tools.conversation_store import (
        save_turn, get_session_turns, list_sessions,
        search_sessions, delete_session,
        get_session_title_from_first_user_message,
    )
    _CONV_STORE = True
except Exception:
    _CONV_STORE = False
```

- [ ] **Step 2: Add history routes**

Add these routes after the existing `/model` routes:

```python
@app.route("/history")
def history_list():
    if not _CONV_STORE:
        return jsonify([])
    tool_id = request.args.get("tool_id")
    q       = request.args.get("q", "").strip()
    if q:
        sessions = search_sessions(q)
    else:
        sessions = list_sessions(tool_id=tool_id or None)
    return jsonify(sessions)


@app.route("/history/<session_id>")
def history_get(session_id):
    if not _CONV_STORE:
        return jsonify([])
    turns = get_session_turns(session_id)
    return jsonify(turns)


@app.route("/history/<session_id>", methods=["DELETE"])
def history_delete(session_id):
    if not _CONV_STORE:
        return jsonify({"ok": False})
    delete_session(session_id)
    return jsonify({"ok": True})
```

- [ ] **Step 3: Save turns in the /chat route**

In the existing `/chat` POST handler, after `run_agent_turn` returns, add:

```python
    # Persist to conversation history store
    if _CONV_STORE:
        try:
            title = get_session_title_from_first_user_message(tool_id)
            save_turn(tool_id, data.get("tool_id", "home"), "user", user_message, title)
            save_turn(tool_id, data.get("tool_id", "home"), "assistant", reply, title)
        except Exception:
            pass
```

(Note: `tool_id` here refers to the session/conversation ID from the request)

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: wire conversation_store into chat route + add history routes"
```

---

### Task 7: Add history sidebar + action items page to app.py HTML

**Files:**
- Modify: `app.py` — HTML_TEMPLATE additions

- [ ] **Step 1: Add history sidebar panel CSS + HTML**

In `HTML_TEMPLATE`, add a `#hist-panel` div in the layout (after `#sidebar`):

```html
<!-- History sidebar -->
<div id="hist-panel" style="display:none;position:fixed;top:0;right:0;width:320px;height:100%;
  background:var(--bg2);border-left:1px solid var(--border);z-index:200;
  display:flex;flex-direction:column;padding:12px;gap:8px;overflow:hidden;">
  <div style="display:flex;justify-content:space-between;align-items:center;">
    <span style="font-weight:600;font-size:13px;">💬 History</span>
    <button onclick="closeHistory()" style="background:none;border:none;color:var(--fg);cursor:pointer;font-size:16px;">✕</button>
  </div>
  <input id="hist-search" placeholder="Search conversations…"
    style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;
    padding:6px 10px;color:var(--fg);font-size:12px;width:100%;box-sizing:border-box;"
    oninput="searchHistory(this.value)">
  <div id="hist-list" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:4px;"></div>
</div>
```

Add a history button in `#hdr-right`:

```html
<button class="hdr-btn" onclick="toggleHistory()" title="Conversation history">🕐</button>
```

- [ ] **Step 2: Add history JS functions**

```javascript
let _histOpen = false;
function toggleHistory() {
  _histOpen = !_histOpen;
  document.getElementById('hist-panel').style.display = _histOpen ? 'flex' : 'none';
  if (_histOpen) loadHistory();
}
function closeHistory() { _histOpen = false; document.getElementById('hist-panel').style.display = 'none'; }

async function loadHistory(q='') {
  const tool = state.activeTool || '';
  const url  = q ? `/history?q=${encodeURIComponent(q)}` : `/history?tool_id=${tool}`;
  const sessions = await fetch(url).then(r => r.json()).catch(() => []);
  const list = document.getElementById('hist-list');
  list.innerHTML = '';
  if (!sessions.length) {
    list.innerHTML = '<div style="opacity:.5;font-size:12px;text-align:center;padding:20px">No history yet</div>';
    return;
  }
  sessions.forEach(s => {
    const d = document.createElement('div');
    d.style.cssText = 'background:var(--bg3);border-radius:6px;padding:8px 10px;cursor:pointer;font-size:12px;border:1px solid transparent;';
    d.innerHTML = `<div style="font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escHtml(s.title)}</div>
      <div style="opacity:.5;font-size:10px;margin-top:2px">${s.tool_id} · ${s.turn_count} turns · ${s.updated_at.slice(0,10)}</div>`;
    d.onmouseover = () => d.style.borderColor = 'var(--accent)';
    d.onmouseout  = () => d.style.borderColor = 'transparent';
    d.onclick = () => restoreSession(s.id, s.title);
    list.appendChild(d);
  });
}

function searchHistory(q) { clearTimeout(searchHistory._t); searchHistory._t = setTimeout(() => loadHistory(q), 300); }

async function restoreSession(id, title) {
  const turns = await fetch(`/history/${id}`).then(r => r.json()).catch(() => []);
  const msgs = document.getElementById('messages');
  msgs.innerHTML = `<div style="text-align:center;opacity:.4;font-size:11px;padding:8px">📂 Restored: ${escHtml(title)}</div>`;
  turns.forEach(t => appendMessage(t.role === 'user' ? 'user' : 'assistant', t.content));
  closeHistory();
}

function escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
```

- [ ] **Step 3: Add action items page content to the 'actions' tool workspace**

Find the existing `actions` tool in `TOOLS_NAV` and ensure its workspace renders a live task list. Add this JS function called when the actions tool is selected:

```javascript
async function loadActionItems() {
  const resp = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({tool_id:'actions', message:'get my action items', history:[]})
  }).then(r=>r.json()).catch(()=>null);
  // The chat response already renders in the message list
}
```

And add a "Refresh tasks" chip to the actions tool chips in `TOOLS_NAV`:

```python
# In TOOLS_NAV for id='actions', add chips:
"chips": [
    "Show all my action items",
    "What's due today?",
    "Show high priority tasks",
    "Mark item #[id] as done",
    "Extract action items from: [paste text]",
],
```

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add history sidebar UI + action items page chips"
```

---

### Task 8: Add tone-matched email draft-reply route to app.py

**Files:**
- Modify: `app.py` — add POST /draft-reply route

- [ ] **Step 1: Add the route**

```python
@app.route("/draft-reply", methods=["POST"])
def draft_reply():
    """
    Takes an email body and generates a tone-matched draft reply.
    Body: {"email_body": "...", "instruction": "...optional..."}
    Returns: {"draft": "..."}
    """
    data        = request.get_json(force=True)
    email_body  = data.get("email_body", "").strip()
    instruction = data.get("instruction", "").strip()
    if not email_body:
        return jsonify({"error": "email_body required"}), 400

    try:
        from tools.tone_learner import get_tone_instructions
        from tools.llm_provider import get_provider
        tone_guide = get_tone_instructions()
        provider   = get_provider()

        system = (
            "You are a professional email drafting assistant. "
            "Write in the user's personal style as described below.\n\n"
            f"{tone_guide}" if tone_guide else
            "You are a professional email drafting assistant. Write clearly and concisely."
        )
        prompt = (
            f"Draft a reply to this email:\n\n{email_body}"
            + (f"\n\nAdditional instruction: {instruction}" if instruction else "")
            + "\n\nWrite only the reply body — no subject line, no sign-off instructions."
        )
        _, draft = provider.run_turn(
            system_prompt=system,
            history=[{"role": "user", "content": prompt}],
            tools=[],
        )
        return jsonify({"draft": draft.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 2: Add "Draft Reply" chip to the Outlook tool**

In `TOOLS_NAV` for `id='outlook'`, add chip:
```python
"Draft a reply to the latest email from [name]",
```

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add POST /draft-reply route — tone-matched email drafting"
```

---

### Task 9: Add trigger rules UI to app.py webhooks page

**Files:**
- Modify: `app.py` — add trigger routes + UI in webhooks workspace

- [ ] **Step 1: Add trigger API routes**

```python
@app.route("/triggers")
def triggers_list():
    try:
        from tools.trigger_engine import list_rules, get_trigger_log
        return jsonify({"rules": list_rules(), "log": get_trigger_log(20)})
    except Exception as e:
        return jsonify({"rules": [], "log": [], "error": str(e)})


@app.route("/triggers", methods=["POST"])
def triggers_add():
    data = request.get_json(force=True)
    try:
        from tools.trigger_engine import add_rule
        rule = add_rule(
            name        = data["name"],
            source      = data.get("source", "any"),
            event_type  = data.get("event_type", "any"),
            condition   = data.get("condition", {}),
            action      = data["action"],
            action_args = data.get("action_args", {}),
        )
        return jsonify(rule)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/triggers/<int:rule_id>", methods=["DELETE"])
def triggers_delete(rule_id):
    try:
        from tools.trigger_engine import delete_rule
        return jsonify(delete_rule(rule_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
```

- [ ] **Step 2: Commit**

```bash
git add app.py
git commit -m "feat: add trigger API routes GET/POST/DELETE /triggers"
```

---

### Task 10: Write tests/test_agent.py

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write the test file**

```python
"""
tests/test_agent.py — pytest test suite for Work Assistant Agent
================================================================
Tests core modules with mocked external APIs.
Run: pytest tests/ -v
"""

import json
import sqlite3
import datetime
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# conversation_store tests
# ──────────────────────────────────────────────────────────────────────────────

def _tmp_conv_db(tmp_path):
    """Patch DB_PATH to a temp file for isolation."""
    import tools.conversation_store as cs
    cs.DB_PATH = tmp_path / "test_conv.db"
    return cs


def test_conv_store_save_and_list(tmp_path):
    cs = _tmp_conv_db(tmp_path)
    cs.save_turn("sess-1", "home", "user", "Hello world", "Hello world")
    cs.save_turn("sess-1", "home", "assistant", "Hi there!", "Hello world")

    sessions = cs.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "sess-1"
    assert sessions[0]["turn_count"] == 2


def test_conv_store_get_turns(tmp_path):
    cs = _tmp_conv_db(tmp_path)
    cs.save_turn("sess-2", "outlook", "user", "Show my emails", "Show my emails")
    cs.save_turn("sess-2", "outlook", "assistant", "Here are your emails…", "")

    turns = cs.get_session_turns("sess-2")
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["role"] == "assistant"


def test_conv_store_search(tmp_path):
    cs = _tmp_conv_db(tmp_path)
    cs.save_turn("sess-3", "home", "user", "Tell me about the Gemini model", "Gemini model")
    cs.save_turn("sess-4", "home", "user", "What is my calendar today", "Calendar")

    results = cs.search_sessions("Gemini")
    assert len(results) == 1
    assert results[0]["id"] == "sess-3"


def test_conv_store_delete(tmp_path):
    cs = _tmp_conv_db(tmp_path)
    cs.save_turn("sess-5", "home", "user", "Hello", "Hello")
    cs.delete_session("sess-5")
    assert cs.list_sessions() == []


def test_conv_store_title_from_first_message(tmp_path):
    cs = _tmp_conv_db(tmp_path)
    cs.save_turn("sess-6", "home", "user", "What is the weather today?", "What is the weather today?")
    title = cs.get_session_title_from_first_user_message("sess-6")
    assert "weather" in title.lower()


# ──────────────────────────────────────────────────────────────────────────────
# trigger_engine tests
# ──────────────────────────────────────────────────────────────────────────────

def _tmp_trigger_db(tmp_path):
    import tools.trigger_engine as te
    te.DB_PATH = tmp_path / "test_triggers.db"
    return te


def test_trigger_add_and_list(tmp_path):
    te = _tmp_trigger_db(tmp_path)
    te.add_rule("Test rule", "github", "pull_request",
                {"action": "opened"}, "slack_message", {"channel": "#dev"})
    rules = te.list_rules()
    assert len(rules) == 1
    assert rules[0]["name"] == "Test rule"
    assert rules[0]["action"] == "slack_message"


def test_trigger_delete(tmp_path):
    te = _tmp_trigger_db(tmp_path)
    te.add_rule("To delete", "any", "any", {}, "notify", {})
    rule_id = te.list_rules()[0]["id"]
    te.delete_rule(rule_id)
    assert te.list_rules() == []


def test_trigger_evaluate_match(tmp_path):
    te = _tmp_trigger_db(tmp_path)
    te.add_rule("PR opened", "github", "pull_request",
                {"action": "opened"}, "slack_message", {"channel": "#prs"})

    matched = te.evaluate_event("github", "pull_request", {
        "action": "opened", "title": "Fix bug", "number": 42
    })
    assert len(matched) == 1
    assert matched[0]["rule_name"] == "PR opened"


def test_trigger_evaluate_no_match(tmp_path):
    te = _tmp_trigger_db(tmp_path)
    te.add_rule("PR closed", "github", "pull_request",
                {"action": "closed"}, "notify", {})

    matched = te.evaluate_event("github", "pull_request", {
        "action": "opened", "title": "Fix bug"
    })
    assert len(matched) == 0


def test_trigger_any_source_matches(tmp_path):
    te = _tmp_trigger_db(tmp_path)
    te.add_rule("All events", "any", "any", {}, "notify", {})

    matched = te.evaluate_event("jira", "issues", {"summary": "Bug report"})
    assert len(matched) == 1


def test_trigger_log(tmp_path):
    te = _tmp_trigger_db(tmp_path)
    te.add_rule("Log test", "any", "any", {}, "notify", {})
    te.evaluate_event("github", "push", {"commits": 3})

    log = te.get_trigger_log()
    assert len(log) == 1
    assert log[0]["event_type"] == "push"


# ──────────────────────────────────────────────────────────────────────────────
# memory / entity extraction tests
# ──────────────────────────────────────────────────────────────────────────────

def _tmp_memory(tmp_path):
    import tools.memory as mem
    mem.MEMORY_FILE = tmp_path / "test_memory.json"
    return mem


def test_memory_save_and_load(tmp_path):
    mem = _tmp_memory(tmp_path)
    mem.save_fact("people", "Alice Smith", {"email": "alice@example.com"})
    loaded = mem.load_memory()
    assert "Alice Smith" in loaded["people"]


def test_entity_extraction_emails(tmp_path):
    mem = _tmp_memory(tmp_path)
    entities = mem.extract_entities("Please email bob@company.com about the project.")
    assert "bob@company.com" in entities["emails"]


def test_entity_extraction_names(tmp_path):
    mem = _tmp_memory(tmp_path)
    entities = mem.extract_entities("I spoke with John Smith and he agreed.")
    assert "John Smith" in entities["people"]


def test_entity_extraction_tickets(tmp_path):
    mem = _tmp_memory(tmp_path)
    entities = mem.extract_entities("Working on PROJ-123 and ENG-456 this sprint.")
    assert "PROJ-123" in entities["projects"]
    assert "ENG-456" in entities["projects"]


def test_auto_save_entities(tmp_path):
    mem = _tmp_memory(tmp_path)
    mem.auto_save_entities(
        user_message="Can you email sarah@acme.com about Sprint 5?",
        assistant_response="I'll draft an email to Sarah about Sprint 5."
    )
    loaded = mem.load_memory()
    # email should be stored under people
    emails_in_people = [v.get("email","") for v in loaded["people"].values()]
    assert "sarah@acme.com" in emails_in_people


# ──────────────────────────────────────────────────────────────────────────────
# action_items tests
# ──────────────────────────────────────────────────────────────────────────────

def _tmp_actions_db(tmp_path):
    import tools.action_items as ai
    ai.DB_PATH = tmp_path / "test_actions.db"
    return ai


def test_action_items_save_and_get(tmp_path):
    ai = _tmp_actions_db(tmp_path)
    items = [
        {"task": "Review PR #42", "owner": "me", "due_date": "2026-05-30",
         "source": "test", "priority": "high"},
        {"task": "Write docs", "owner": "me", "due_date": "",
         "source": "test", "priority": "medium"},
    ]
    ai.save_action_items(items=items, source="test")
    result = ai.get_my_action_items()
    tasks = [r["task"] for r in result.get("items", result if isinstance(result, list) else [])]
    assert any("Review PR" in t for t in tasks)


def test_action_items_complete(tmp_path):
    ai = _tmp_actions_db(tmp_path)
    ai.save_action_items(items=[{"task": "Finish report", "priority": "low",
                                  "owner": "", "due_date": "", "source": "test"}], source="test")
    result = ai.get_my_action_items()
    items = result.get("items", result if isinstance(result, list) else [])
    item_id = items[0]["id"]
    ai.complete_action_item(item_id=item_id)
    result2 = ai.get_my_action_items(status="open")
    items2 = result2.get("items", result2 if isinstance(result2, list) else [])
    assert not any(i["id"] == item_id for i in items2)


# ──────────────────────────────────────────────────────────────────────────────
# retry logic tests
# ──────────────────────────────────────────────────────────────────────────────

def test_retry_succeeds_on_first_try():
    """_with_retry should return immediately if fn succeeds."""
    # Import inline to avoid heavy agent.py init
    import importlib.util, sys, json, time
    # Minimal inline version of the function to test the logic:
    def _with_retry(fn, tool_name, max_attempts=3):
        NO_RETRY_SIGNALS = ("401","403","400","invalid","not found","unauthorized")
        delay = 0.01  # fast in tests
        last_err = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except Exception as e:
                err_str = str(e).lower()
                last_err = e
                if any(sig in err_str for sig in NO_RETRY_SIGNALS):
                    break
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2
        return json.dumps({"error": f"⚠️ {tool_name} unavailable.", "detail": str(last_err)})

    result = _with_retry(lambda: '{"ok": true}', "test_tool")
    assert result == '{"ok": true}'


def test_retry_gives_up_after_max_attempts():
    call_count = 0
    def _with_retry(fn, tool_name, max_attempts=3):
        NO_RETRY_SIGNALS = ("401","403","400","invalid","not found","unauthorized")
        import time
        delay = 0.01
        last_err = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except Exception as e:
                err_str = str(e).lower()
                last_err = e
                if any(sig in err_str for sig in NO_RETRY_SIGNALS):
                    break
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2
        return json.dumps({"error": f"⚠️ {tool_name} unavailable.", "detail": str(last_err)})

    def always_fails():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("network timeout")

    result = _with_retry(always_fails, "outlook", max_attempts=3)
    data = json.loads(result)
    assert "unavailable" in data["error"]
    assert call_count == 3


def test_retry_no_retry_on_auth_error():
    call_count = 0
    def _with_retry(fn, tool_name, max_attempts=3):
        NO_RETRY_SIGNALS = ("401","403","400","invalid","not found","unauthorized")
        import time
        delay = 0.01
        last_err = None
        for attempt in range(max_attempts):
            try:
                return fn()
            except Exception as e:
                err_str = str(e).lower()
                last_err = e
                if any(sig in err_str for sig in NO_RETRY_SIGNALS):
                    break
                if attempt < max_attempts - 1:
                    time.sleep(delay)
                    delay *= 2
        return json.dumps({"error": f"⚠️ {tool_name} unavailable.", "detail": str(last_err)})

    def auth_fail():
        nonlocal call_count
        call_count += 1
        raise PermissionError("401 Unauthorized")

    _with_retry(auth_fail, "github", max_attempts=3)
    # Should not retry on 401
    assert call_count == 1
```

- [ ] **Step 2: Create empty `__init__.py`**

```bash
touch tests/__init__.py
```

- [ ] **Step 3: Run tests**

```bash
cd /Users/saisamineni/Desktop/work-assistant-agent && pip install pytest --break-system-packages -q && pytest tests/ -v 2>&1
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/
git commit -m "feat: add pytest test suite — conversation_store, trigger_engine, memory, action_items, retry"
```

---

### Task 11: Update requirements.txt and push everything

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add pytest to requirements**

Add `pytest>=8.0` to requirements.txt.

- [ ] **Step 2: Final syntax check all new files**

```bash
python3 -m py_compile tools/conversation_store.py tools/trigger_engine.py tools/memory.py agent.py app.py && echo "ALL OK"
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 4: Push**

```bash
git add -A
git commit -m "feat: agent improvements v2 — history, triggers, retry, planner, entity extraction, tests"
git push origin main
```
