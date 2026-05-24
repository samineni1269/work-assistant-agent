# Connections UI + Restart Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/connections-page` to the web UI where the user can view, connect, disconnect, and reconfigure every tool integration directly in the browser — plus a Restart button accessible from the nav.

**Architecture:** All changes are inside `app.py`. We add one new route (`POST /restart`), one new page route (`GET /connections-page`), and update `_PAGE_NAV`. The page reuses existing APIs: `GET /connections` (status), `GET|POST /credentials` (read/write creds), and the existing MS365 device-flow routes. No new Python files needed.

**Tech Stack:** Flask, vanilla JS (no framework), existing `_PAGE_STYLE` / `_PAGE_NAV` CSS, `os.execv` for restart.

---

### Task 1: Add `POST /restart` route

**Files:**
- Modify: `app.py` — add route after the existing `GET /connections` route (~line 1721)

- [ ] **Step 1: Write failing test**

```python
# tests/test_restart.py
import importlib, sys, os
os.environ.setdefault("TESTING", "1")

def test_restart_route_exists(client):
    """Route must exist and return 200 JSON before the process replaces itself."""
    # We can't actually restart in tests — mock os.execv
    import app as app_module
    orig = app_module.os.execv
    called = []
    app_module.os.execv = lambda *a: called.append(a)
    try:
        r = client.post("/restart")
        assert r.status_code == 200
        data = r.get_json()
        assert data.get("ok") is True
        assert len(called) == 1   # execv was invoked
    finally:
        app_module.os.execv = orig
```

Run: `pytest tests/test_restart.py -v`
Expected: FAIL with "404 Not Found"

- [ ] **Step 2: Add the route — insert after line ~1720 in app.py**

Find the block:
```python
@app.route("/connections")
def connections():
    return jsonify(_check_connections())
```

Add immediately after:
```python

@app.route("/restart", methods=["POST"])
def restart_server():
    """Restart the Flask process in-place. Safe for development server."""
    import threading
    def _do_restart():
        import time
        time.sleep(0.3)          # let the HTTP response fly first
        os.execv(sys.executable, [sys.executable] + sys.argv)
    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting…"})
```

Also ensure `import sys` is at the top of the file. Search for it first:

```bash
grep -n "^import sys" app.py | head -3
```

If missing, add `import sys` near the other stdlib imports at the top.

- [ ] **Step 3: Run test to verify it passes**

Run: `pytest tests/test_restart.py -v`
Expected: PASS

- [ ] **Step 4: Smoke-test manually**

```bash
curl -s -X POST http://localhost:5000/restart
```
Expected JSON: `{"message": "Restarting…", "ok": true}`
Server should restart within ~1 second (visible in the terminal running Flask).

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/work-assistant-agent
git add app.py tests/test_restart.py
git commit -m "feat: add POST /restart route (os.execv in-process restart)"
```

---

### Task 2: Add `GET /connections-page` route

**Files:**
- Modify: `app.py` — add route + f-string HTML page after the `/restart` route

The page must:
1. Load `GET /connections` on mount → show green ✅ / red ✗ badge per integration
2. Load `GET /credentials` on mount → show which fields are already set
3. "Configure" button per integration → opens modal with fields pre-labelled (never pre-filled with secrets)
4. Modal save → `POST /credentials` → refreshes status
5. MS365 card is special: shows Connect / Disconnect buttons wired to the existing `/ms365/auth/start`, `/ms365/auth/poll`, `/ms365/auth/status`, `/ms365/auth/disconnect` routes
6. Restart button at bottom of page (same action as nav button — calls `POST /restart`)

- [ ] **Step 1: Add the route to app.py**

After the `/restart` route, add:

```python
@app.route("/connections-page")
def connections_page():
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connections — Work Assistant</title>
{_PAGE_STYLE}
<style>
.conn-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;margin-top:20px}}
.conn-card{{background:#1e2028;border:1px solid #252836;border-radius:8px;padding:16px 18px;transition:border-color .15s}}
.conn-card:hover{{border-color:#2a3a50}}
.conn-card-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}}
.conn-name{{font-size:13px;font-weight:700;color:#d4d8e8}}
.conn-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:4px}}
.conn-badge-ok{{background:#0d2a1a;color:#50fa7b}}
.conn-badge-no{{background:#2a1010;color:#ff6e6e}}
.conn-desc{{font-size:11px;color:#6b7394;margin-bottom:12px;line-height:1.5}}
.conn-fields{{margin-bottom:12px}}
.conn-field{{display:flex;align-items:center;gap:6px;font-size:11px;color:#8892b0;margin-bottom:4px}}
.conn-field-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.conn-field-dot-ok{{background:#50fa7b}}
.conn-field-dot-no{{background:#ff6e6e}}
.conn-actions{{display:flex;gap:7px;flex-wrap:wrap}}
/* MS365 device-flow box */
.ms365-box{{background:#12141a;border:1px solid #252836;border-radius:6px;padding:12px;margin-top:10px;font-size:11px;display:none}}
.ms365-code{{font-size:20px;font-weight:700;color:#64ffda;letter-spacing:4px;text-align:center;padding:8px 0}}
</style>
</head>
<body>
{_PAGE_NAV}
<div class="page-wrap">
  <div class="page-hdr">
    <div>
      <div class="page-title">🔌 Connections</div>
      <div class="page-subtitle">Connect and manage all your tool integrations from one place</div>
    </div>
    <button class="btn btn-danger" onclick="restartApp()">↺ Restart App</button>
  </div>

  <div id="status-banner" style="display:none;padding:8px 14px;border-radius:6px;font-size:12px;margin-bottom:16px"></div>

  <div class="conn-grid" id="conn-grid">
    <div class="empty-state"><div class="empty-state-icon">⏳</div><div class="empty-state-txt">Loading connections…</div></div>
  </div>
</div>

<!-- Credentials modal -->
<div class="modal-overlay" id="creds-modal">
  <div class="modal-box" style="width:480px">
    <div class="modal-title" id="modal-title">Configure Integration</div>
    <div id="modal-desc" style="font-size:11px;color:#6b7394;margin-bottom:12px"></div>
    <div id="modal-fields"></div>
    <div id="modal-setup" style="font-size:11px;color:#6b7394;margin-top:6px"></div>
    <div class="modal-ftr">
      <button class="btn" style="background:#1e2028;color:#8892b0;border:1px solid #252836" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="modal-save-btn" onclick="saveCredentials()">Save</button>
    </div>
  </div>
</div>

<script>
let _credsConfig = {{}};
let _currentIntegration = null;

async function load() {{
  const [status, creds] = await Promise.all([
    fetch('/connections').then(r=>r.json()),
    fetch('/credentials').then(r=>r.json()),
  ]);
  _credsConfig = creds;
  renderGrid(status, creds);
}}

function renderGrid(status, creds) {{
  const statusMap = {{}};
  status.forEach(s => statusMap[s.name] = s.ok);

  const integrationOrder = ['M365','AI','Atlassian','GitHub','Slack','Linear','Notion','Zoom','G-Meet'];
  const html = integrationOrder.map(key => {{
    const cfg = creds[key];
    if (!cfg) return '';
    const connected = statusMap[cfg.label] ?? cfg.fields.some(f=>f.set);
    const badge = connected
      ? '<span class="conn-badge conn-badge-ok">✅ Connected</span>'
      : '<span class="conn-badge conn-badge-no">✗ Not set</span>';

    const fieldDots = cfg.fields.map(f =>
      `<div class="conn-field">
        <div class="conn-field-dot ${{f.set?'conn-field-dot-ok':'conn-field-dot-no'}}"></div>
        <span>${{f.label}}</span>${{f.set ? '' : ' <span style="color:#ff6e6e;font-size:10px">(missing)</span>'}}
      </div>`
    ).join('');

    const ms365Extra = key === 'M365' ? `
      <div id="ms365-box" class="ms365-box">
        <div id="ms365-instructions" style="color:#8892b0;margin-bottom:8px">Visit the URL below and enter the code:</div>
        <a id="ms365-link" href="#" target="_blank" style="font-size:11px;color:#64ffda"></a>
        <div class="ms365-code" id="ms365-user-code">—</div>
        <div id="ms365-spinner" style="text-align:center;font-size:18px;margin-top:6px">⏳</div>
      </div>` : '';

    const disconnectBtn = key === 'M365' && connected
      ? `<button class="btn btn-sm btn-danger" onclick="disconnectMs365()">Disconnect</button>` : '';

    const connectBtn = key === 'M365'
      ? `<button class="btn btn-sm btn-success" id="ms365-connect-btn" onclick="startMs365Auth()">${{connected ? 'Re-connect' : 'Connect'}}</button>`
      : '';

    const configBtn = `<button class="btn btn-sm" style="background:#252836;color:#8892b0;border:1px solid #2a3050" onclick="openModal('${{key}}')">⚙ Configure</button>`;
    const setupBtn = `<a href="${{cfg.setup_url}}" target="_blank" class="btn btn-sm" style="background:#12141a;color:#64ffda;border:1px solid #1e3050;font-size:10px">↗ Setup docs</a>`;

    return `<div class="conn-card" id="card-${{key}}">
      <div class="conn-card-hdr">
        <span class="conn-name">${{cfg.label}}</span>
        ${{badge}}
      </div>
      <div class="conn-desc">${{cfg.desc}}</div>
      <div class="conn-fields">${{fieldDots}}</div>
      ${{ms365Extra}}
      <div class="conn-actions">
        ${{configBtn}}
        ${{connectBtn}}
        ${{disconnectBtn}}
        ${{setupBtn}}
      </div>
    </div>`;
  }}).join('');

  document.getElementById('conn-grid').innerHTML = html || '<div class="empty-state"><div class="empty-state-txt">No integrations found.</div></div>';
}}

function openModal(key) {{
  const cfg = _credsConfig[key];
  if (!cfg) return;
  _currentIntegration = key;
  document.getElementById('modal-title').textContent = `Configure ${{cfg.label}}`;
  document.getElementById('modal-desc').textContent = cfg.desc;
  document.getElementById('modal-setup').innerHTML = `<a href="${{cfg.setup_url}}" target="_blank" style="color:#64ffda">↗ Setup guide</a>`;
  const fields = cfg.fields.map(f => `
    <div class="form-group">
      <label class="form-label">${{f.label}}${{f.set ? ' <span style="color:#50fa7b;font-size:9px">● set</span>' : ' <span style="color:#ff6e6e;font-size:9px">● missing</span>'}}</label>
      <input class="form-input" type="${{f.secret ? 'password' : 'text'}}" id="field-${{f.key}}"
             placeholder="${{f.set ? '(leave blank to keep current)' : f.placeholder}}" data-key="${{f.key}}">
    </div>`).join('');
  document.getElementById('modal-fields').innerHTML = fields;
  document.getElementById('creds-modal').classList.add('open');
}}

function closeModal() {{
  document.getElementById('creds-modal').classList.remove('open');
  _currentIntegration = null;
}}

async function saveCredentials() {{
  if (!_currentIntegration) return;
  const cfg = _credsConfig[_currentIntegration];
  const values = {{}};
  cfg.fields.forEach(f => {{
    const el = document.getElementById(`field-${{f.key}}`);
    if (el && el.value.trim()) values[f.key] = el.value.trim();
  }});
  if (!Object.keys(values).length) {{ closeModal(); return; }}
  const btn = document.getElementById('modal-save-btn');
  btn.textContent = 'Saving…';
  btn.disabled = true;
  try {{
    const r = await fetch('/credentials', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{integration: _currentIntegration, values}})
    }}).then(r=>r.json());
    if (r.error) {{ showBanner(r.error, 'error'); }}
    else {{ showBanner(`Saved: ${{r.saved.join(', ')}}`, 'ok'); }}
    closeModal();
    await load();
  }} finally {{
    btn.textContent = 'Save';
    btn.disabled = false;
  }}
}}

// MS365 device flow
let _ms365PollInterval = null;

async function startMs365Auth() {{
  const btn = document.getElementById('ms365-connect-btn');
  btn.disabled = true; btn.textContent = 'Starting…';
  const box = document.getElementById('ms365-box');
  box.style.display = 'block';
  try {{
    const r = await fetch('/ms365/auth/start', {{method:'POST'}}).then(r=>r.json());
    if (r.error) {{ showBanner(r.error, 'error'); box.style.display='none'; btn.disabled=false; btn.textContent='Connect'; return; }}
    document.getElementById('ms365-user-code').textContent = r.user_code || '—';
    const link = document.getElementById('ms365-link');
    link.href = r.verification_uri || '#';
    link.textContent = r.verification_uri || '';
    document.getElementById('ms365-spinner').textContent = '⏳';
    _ms365PollInterval = setInterval(pollMs365, 3000);
  }} catch(e) {{ showBanner('Failed to start auth: '+e.message, 'error'); btn.disabled=false; btn.textContent='Connect'; }}
}}

async function pollMs365() {{
  const r = await fetch('/ms365/auth/poll').then(r=>r.json());
  if (r.status === 'connected') {{
    clearInterval(_ms365PollInterval);
    document.getElementById('ms365-spinner').textContent = '✅';
    showBanner('Microsoft 365 connected!', 'ok');
    setTimeout(() => load(), 800);
  }} else if (r.status === 'failed') {{
    clearInterval(_ms365PollInterval);
    document.getElementById('ms365-spinner').textContent = '✗';
    showBanner(r.error || 'Sign-in failed.', 'error');
    const btn = document.getElementById('ms365-connect-btn');
    if (btn) {{ btn.disabled=false; btn.textContent='Connect'; }}
  }}
}}

async function disconnectMs365() {{
  await fetch('/ms365/auth/disconnect', {{method:'POST'}});
  showBanner('Microsoft 365 disconnected.', 'ok');
  load();
}}

async function restartApp() {{
  const banner = document.getElementById('status-banner');
  banner.style.display = 'block';
  banner.style.background = '#2a2010';
  banner.style.color = '#ffb86c';
  banner.style.border = '1px solid #4a3010';
  banner.textContent = '↺ Restarting server…';
  try {{
    await fetch('/restart', {{method:'POST'}});
  }} catch(e) {{}}  // connection drops — that's expected
  // Poll until back up
  const start = Date.now();
  while (Date.now() - start < 15000) {{
    await new Promise(r => setTimeout(r, 800));
    try {{
      const r = await fetch('/connections', {{signal: AbortSignal.timeout(1000)}});
      if (r.ok) {{
        banner.style.background = '#0d2a1a';
        banner.style.color = '#50fa7b';
        banner.style.border = '1px solid #1a4a2a';
        banner.textContent = '✅ Server restarted successfully.';
        load();
        return;
      }}
    }} catch(e) {{}}
  }}
  banner.textContent = '⚠ Server did not come back in time. Refresh manually.';
}}

function showBanner(msg, type) {{
  const el = document.getElementById('status-banner');
  el.style.display = 'block';
  if (type === 'ok') {{
    el.style.background='#0d2a1a'; el.style.color='#50fa7b'; el.style.border='1px solid #1a4a2a';
  }} else {{
    el.style.background='#2a1010'; el.style.color='#ff6e6e'; el.style.border='1px solid #4a2020';
  }}
  el.textContent = msg;
  setTimeout(() => {{ el.style.display='none'; }}, 4000);
}}

document.getElementById('creds-modal').addEventListener('click', e => {{
  if (e.target === document.getElementById('creds-modal')) closeModal();
}});

load();
</script>
</body>
</html>"""
```

- [ ] **Step 2: Verify the route syntax compiles**

```bash
cd ~/Desktop/work-assistant-agent
python -m py_compile app.py && echo "OK"
```
Expected: `OK`

- [ ] **Step 3: Manual smoke test in browser**

Open http://localhost:5000/connections-page
- All integration cards load with green/red badges
- Clicking "⚙ Configure" opens modal with correctly labelled fields
- Saving credentials calls POST /credentials and refreshes the page
- MS365 Connect button triggers device-flow auth box
- Restart button shows "Restarting…" banner, then "✅ Server restarted"

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add /connections-page with per-tool status, credential modals, MS365 flow"
```

---

### Task 3: Update `_PAGE_NAV`

**Files:**
- Modify: `app.py` — update `_PAGE_NAV` string (around line 2210)

- [ ] **Step 1: Locate the current _PAGE_NAV**

```bash
grep -n "_PAGE_NAV" app.py | head -5
```
Expected output: line numbers including the definition `_PAGE_NAV = """`

- [ ] **Step 2: Add Connections link and Restart button**

Find the first `<div style="display:flex;align-items:center;gap:12px;...` row inside `_PAGE_NAV`.

Replace the existing first row content (the line with all the nav links) with the version below — adding `🔌 Connections` link and a `↺ Restart` button at the right end:

```python
_PAGE_NAV = """
<div style="background:#1a1c24;border-bottom:1px solid #252836;padding:8px 20px">
  <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:6px">
    <a href="/" style="font-size:13px;font-weight:700;color:#64ffda;text-decoration:none;flex-shrink:0">⚡ Work Assistant</a>
    <span style="color:#252836;flex-shrink:0">|</span>
    <a href="/actions-page" class="nav-link">✅ Actions</a>
    <a href="/triggers-page" class="nav-link">⚡ Automation</a>
    <a href="/memory-page" class="nav-link">🧠 Memory</a>
    <a href="/scheduler-page" class="nav-link">🕐 Scheduler</a>
    <a href="/search-page" class="nav-link">🔍 Search</a>
    <a href="/inbox-page" class="nav-link">📧 Inbox</a>
    <a href="/calendar-page" class="nav-link">📅 Calendar</a>
    <a href="/documents-page" class="nav-link">📄 Documents</a>
    <a href="/analytics-page" class="nav-link">📊 Analytics</a>
    <a href="/guardrails-page" class="nav-link">🛡 Guardrails</a>
    <a href="/kb-page" class="nav-link">🧠 Knowledge Base</a>
    <a href="/alerts-page" class="nav-link">🔔 Alerts</a>
    <a href="/self-learning-page" class="nav-link">🧬 Self-Learning</a>
    <span style="flex:1"></span>
    <a href="/connections-page" class="nav-link" style="color:#64ffda;border:1px solid #1e3050;padding:3px 10px;border-radius:5px">🔌 Connections</a>
    <button onclick="navRestart(this)" class="nav-link" style="background:none;border:1px solid #2a2030;color:#8892b0;cursor:pointer;padding:3px 10px;border-radius:5px;font-family:inherit;font-size:11.5px">↺ Restart</button>
  </div>
  <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
    <span style="font-size:10px;color:#3a4060;font-weight:700;letter-spacing:.5px;flex-shrink:0">TOOLS:</span>
    <a href="/github-page" class="nav-link-tool">🐙 GitHub</a>
    <a href="/jira-page" class="nav-link-tool">📋 Jira</a>
    <a href="/linear-page" class="nav-link-tool">⚡ Linear</a>
    <a href="/slack-page" class="nav-link-tool">💬 Slack</a>
    <a href="/notion-page" class="nav-link-tool">📓 Notion</a>
    <a href="/meetings-page" class="nav-link-tool">📹 Meetings</a>
    <a href="/webhooks-page" class="nav-link-tool">🪝 Webhooks</a>
    <a href="/meeting-prep-page" class="nav-link-tool">🗓 Meeting Prep</a>
  </div>
</div>
<style>
.nav-link{font-size:11.5px;color:#8892b0;text-decoration:none;padding:3px 8px;border-radius:4px;transition:color .15s}
.nav-link:hover{color:#d4d8e8}
.nav-link-tool{font-size:11px;color:#6872a0;text-decoration:none;padding:2px 8px;border-radius:4px;border:1px solid #1e2030;background:#16171f;transition:all .15s}
.nav-link-tool:hover{color:#d4d8e8;border-color:#3a4060}
</style>
<script>
async function navRestart(btn) {
  const orig = btn.textContent;
  btn.textContent = '⏳…';
  btn.disabled = true;
  try { await fetch('/restart', {method:'POST'}); } catch(e) {}
  // Poll until back up
  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 800));
    try {
      const r = await fetch('/connections', {signal: AbortSignal.timeout(1000)});
      if (r.ok) { btn.textContent = '✅'; setTimeout(() => { btn.textContent = orig; btn.disabled = false; }, 2000); return; }
    } catch(e) {}
  }
  btn.textContent = '⚠'; btn.disabled = false;
}
</script>
"""
```

- [ ] **Step 3: Verify compile**

```bash
cd ~/Desktop/work-assistant-agent
python -m py_compile app.py && echo "OK"
```
Expected: `OK`

- [ ] **Step 4: Verify nav links render correctly**

Open any page (e.g. http://localhost:5000/actions-page) and confirm:
- 🔌 Connections link appears in the nav and navigates to /connections-page
- ↺ Restart button appears in the nav, when clicked shows ⏳… then ✅

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add Connections link + Restart button to _PAGE_NAV"
```

---

### Task 4: Full verification + push

- [ ] **Step 1: Syntax check**

```bash
cd ~/Desktop/work-assistant-agent
python -m py_compile app.py && echo "app.py OK"
python -m py_compile tests/test_restart.py && echo "test_restart.py OK"
```
Expected: both `OK`

- [ ] **Step 2: Run pytest**

```bash
pytest tests/ -x -q 2>&1 | tail -20
```
Expected: no failures (warnings OK)

- [ ] **Step 3: Push to GitHub**

```bash
git push origin main
```
Expected: `Branch 'main' set up to track remote branch 'main' from 'origin'.` or just the push summary.

---

## Self-Review

**Spec coverage:**
- ✅ Connect tools from browser → /connections-page with per-tool credential modals
- ✅ Disconnect account → MS365 Disconnect button + `/ms365/auth/disconnect`
- ✅ Change account → re-configure via credential modal (replaces .env values)
- ✅ Restart from UI → ↺ button in nav + on connections page
- ✅ MS365 device flow surfaced → inline Connect box on the M365 card

**No placeholders:** All HTML, JS, and Python code is fully written out in every step.

**Type consistency:** All route names (`/restart`, `/connections-page`) used consistently. `CREDS_CONFIG` key names (`M365`, `Atlassian`, `GitHub`, etc.) match what's in `app.py` exactly.
