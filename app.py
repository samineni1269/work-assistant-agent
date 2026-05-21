"""
app.py — Work Assistant Web UI
================================
Flask-based local web app.  No native GUI framework required.
Opens automatically in your default browser at http://localhost:7432

Run:
    python app.py
"""

import os
import sys
import json
import threading
import uuid
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify

app = Flask(__name__)
app.config["SECRET_KEY"] = "work-assistant-local-7432"

# ── Global state ───────────────────────────────────────────────────────────────
_history: list = []
_jobs: dict = {}
_lock = threading.Lock()

PORT = 7432


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — same groups as before
# ══════════════════════════════════════════════════════════════════════════════

SIDEBAR_GROUPS = [
    ("OVERVIEW", [
        ("🌅  Daily Briefing",
         "Give me my full daily briefing: today's calendar, unread emails, GitHub notifications, "
         "my Jira issues In Progress, and my Linear issues started."),
        ("📋  Standup Summary",
         "Write my standup: what I worked on yesterday (from Jira/Linear/GitHub activity), "
         "what I'm doing today, and any blockers. Format ready to paste into Teams."),
    ]),
    ("EMAIL & CALENDAR", [
        ("📧  Unread Emails",        "Show me my unread emails — summarise each one concisely."),
        ("📨  Search Emails",        "I want to search my emails. What keyword should I search for?"),
        ("📅  Today's Calendar",     "What meetings do I have today? Include Outlook, Zoom, and Google Meet."),
        ("📅  This Week's Calendar", "What meetings do I have this week?"),
        ("📅  New Meeting",          "I want to schedule a new meeting. Should I use Teams, Zoom, or Google Meet?"),
    ]),
    ("TEAMS & CHANNELS", [
        ("💬  Teams Chats",    "Show me my recent Teams chats and any unread messages."),
        ("📢  Channel Messages", "I want to read messages from a Teams channel. Which team and channel?"),
        ("📢  Post to Channel", "I want to post a message to a Teams channel."),
    ]),
    ("GITHUB", [
        ("🔔  Notifications",       "Show me all my unread GitHub notifications."),
        ("👀  PRs to Review",       "Show me all open GitHub pull requests where my review is requested."),
        ("🔀  My Pull Requests",    "List all open pull requests I've authored across my repos."),
        ("✅  CI / Build Status",   "I want to check CI build status. Which repo and PR?"),
        ("🐛  Create GitHub Issue", "I want to create a GitHub issue. Which repo and what's the problem?"),
        ("🔀  Merge a PR",          "I want to merge a pull request. Which repo and PR number?"),
    ]),
    ("LINEAR", [
        ("🎯  My Issues",    "Show me all Linear issues assigned to me — grouped by state."),
        ("🔍  Search Linear", "I want to search Linear. What should I look for?"),
        ("🎯  Create Issue", "I want to create a Linear issue. What team, title, and description?"),
        ("🔄  Move Issue",   "I want to move a Linear issue to a different state. Which issue?"),
        ("📁  Projects",     "List all my Linear projects and their progress."),
    ]),
    ("JIRA", [
        ("🎫  My Issues",   "Show me all Jira issues assigned to me — list by status."),
        ("🔍  Search Jira", "I want to search Jira with a JQL query. What are you looking for?"),
        ("🎫  Create Ticket", "I want to create a Jira issue. What project, type, and summary?"),
        ("🔄  Move Ticket", "I want to transition a Jira issue. Which issue and what status?"),
        ("💬  Add Comment", "I want to add a comment to a Jira issue. Which one?"),
    ]),
    ("CONFLUENCE", [
        ("🔍  Search Pages", "I want to search Confluence. What topic?"),
        ("📖  Read a Page",  "I want to read a Confluence page. What's the page title or ID?"),
        ("📝  Create Page",  "I want to create a new Confluence page. Which space, title, and content?"),
        ("📝  Update Page",  "I want to update a Confluence page. Which page?"),
    ]),
    ("SHAREPOINT & FILES", [
        ("🔍  Search SharePoint", "I want to search SharePoint for a document. What keyword?"),
        ("📁  Browse Files",      "List files in my OneDrive or a SharePoint folder."),
    ]),
    ("EXCEL", [
        ("📊  Read Spreadsheet", "I want to read an Excel file. What filename and sheet?"),
        ("📊  Write to Cell",    "I want to write a value to an Excel cell. Which file, sheet, and cell?"),
        ("📊  Append Row",       "I want to add a new row to an Excel sheet. Which file and what data?"),
    ]),
    ("WORD DOCUMENTS", [
        ("📄  Read Document",   "I want to read a Word document. What filename?"),
        ("📄  Create Document", "I want to create a new Word document. What title and content?"),
        ("📄  Update Document", "I want to update an existing Word document. Which file?"),
        ("📑  Document Outline", "Show me the heading structure of a Word document. What filename?"),
    ]),
    ("POWERPOINT", [
        ("🖼  Read Presentation", "I want to read a PowerPoint file. What filename?"),
        ("🖼  Slide Summary",     "Give me a quick summary (just titles) of a PowerPoint deck. What filename?"),
        ("🖼  Create Deck",       "I want to create a new PowerPoint presentation. What topic and slides?"),
        ("🖼  Add Slide",         "I want to add a slide to an existing PowerPoint. Which file?"),
    ]),
    ("ZOOM & GOOGLE MEET", [
        ("📹  Upcoming Zoom Calls", "Show me my upcoming Zoom meetings with join links."),
        ("📹  Create Zoom Meeting", "I want to create a Zoom meeting. What topic, date, and time?"),
        ("🎥  Google Calendar",     "Show me my Google Calendar events and Google Meet links for today."),
        ("🎥  Create Google Meet",  "I want to create a Google Meet. What title, date, and attendees?"),
        ("🎞  Zoom Recordings",     "Show me my recent Zoom cloud recordings."),
    ]),
]

TOTAL_ACTIONS = sum(len(g) for _, g in SIDEBAR_GROUPS)


# ══════════════════════════════════════════════════════════════════════════════
# CONNECTION STATUS
# ══════════════════════════════════════════════════════════════════════════════

INTEGRATIONS = [
    ("M365",      ["MS_CLIENT_ID"],
     all,  "Outlook · Teams · SharePoint · Excel · Word · PPT"),
    ("Atlassian", ["ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN"],
     all,  "Jira · Confluence"),
    ("GitHub",    ["GITHUB_TOKEN"],
     all,  "GitHub"),
    ("Linear",    ["LINEAR_API_KEY"],
     all,  "Linear"),
    ("AI",        ["GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                   "OPENROUTER_API_KEY", "MINIMAX_API_KEY"],
     any,  "AI Engine"),
    ("Zoom",      ["ZOOM_CLIENT_ID"],
     all,  "Zoom"),
    ("G-Meet",    ["GOOGLE_CLIENT_ID"],
     all,  "Google Meet"),
]


def _check_connections():
    result = []
    for name, env_keys, strategy, tooltip in INTEGRATIONS:
        configured = strategy(os.getenv(k) for k in env_keys)
        result.append({"name": name, "ok": bool(configured), "tooltip": tooltip})
    return result


# ══════════════════════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ══════════════════════════════════════════════════════════════════════════════

_SIDEBAR_JSON = json.dumps(SIDEBAR_GROUPS)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Work Assistant</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#16181d;color:#d4d8e8;font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display',sans-serif;display:flex;height:100vh;overflow:hidden;font-size:13px}

/* ── Sidebar ── */
#sb{width:240px;min-width:240px;background:#1e2028;display:flex;flex-direction:column;border-right:1px solid #2a2d3a}
#sb-hdr{padding:16px 14px 10px;border-bottom:1px solid #2a2d3a}
#sb-title{color:#64ffda;font-size:15px;font-weight:700}
#sb-sub{color:#6b7394;font-size:11px;margin-top:2px}
#sb-srch{padding:8px;border-bottom:1px solid #2a2d3a}
#srch-inp{width:100%;background:#13151a;border:none;border-radius:4px;padding:7px 10px;color:#d4d8e8;font-size:12px;outline:none}
#srch-inp::placeholder{color:#6b7394}
#sb-acts{flex:1;overflow-y:auto;padding-bottom:8px}
.sec-hdr{background:#13151a;color:#8892b0;font-size:10px;font-weight:700;padding:6px 10px;letter-spacing:.05em;margin-top:4px}
.act-btn{display:block;width:100%;text-align:left;background:#1e2028;color:#d4d8e8;border:none;padding:7px 14px;font-size:12px;cursor:pointer;margin:1px 0;transition:background .1s}
.act-btn:hover{background:#2a2d3a}
.act-btn:active{background:#e94560;color:#fff}
#sb-status{background:#13151a;padding:10px;border-top:1px solid #2a2d3a}
.conn-lbl{color:#6b7394;font-size:10px;font-weight:700;margin-bottom:6px}
.conn-grid{display:grid;grid-template-columns:1fr 1fr;gap:2px}
.ci{font-size:10px;padding:1px 4px}
.ci-ok{color:#50fa7b}.ci-no{color:#6b7394}
.sb-bot{display:flex;justify-content:space-between;align-items:center;margin-top:8px}
.clr-btn{background:none;border:none;color:#6b7394;font-size:11px;cursor:pointer}
.clr-btn:hover{color:#d4d8e8}
#dot{font-size:11px;color:#50fa7b}

/* ── Main panel ── */
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#chat{flex:1;overflow-y:auto;padding:20px 24px}
.msg{margin-bottom:18px}
.mhdr{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.mn-u{color:#64ffda;font-weight:700}.mn-a{color:#bd93f9;font-weight:700}
.mts{color:#6b7394;font-size:11px}
.mbody{line-height:1.65;white-space:pre-wrap}
.mu{color:#cdd6f4}.ma{color:#d4d8e8}.me{color:#ff5555}
.mbody b{font-weight:700}
.mbody code{background:#2a2a3e;color:#f8f8f2;padding:1px 5px;border-radius:3px;font-family:monospace;font-size:12px}
.mbody .blt{display:block;padding-left:16px}
.mbody .blt::before{content:"•";margin-left:-16px;margin-right:8px}
#thinking{color:#6b7394;font-style:italic;padding:8px 0}

/* ── Input ── */
#inp-area{background:#1e2028;padding:12px 16px;border-top:1px solid #2a2d3a}
#inp-row{display:flex;gap:10px;align-items:flex-end}
#inp{flex:1;background:#13151a;border:none;border-radius:6px;padding:10px 14px;color:#d4d8e8;font-size:13px;font-family:inherit;resize:none;outline:none;height:60px;max-height:200px}
#inp::placeholder{color:#3a4a60}
#snd{background:#e94560;color:#fff;border:none;border-radius:6px;padding:10px 18px;font-size:13px;font-weight:700;cursor:pointer;align-self:stretch}
#snd:hover{background:#c73652}
#snd:disabled{background:#3a3a4a;cursor:default}
#hint{color:#6b7394;font-size:11px;margin-top:4px}

/* ── Guardrails panel ── */
#sb-guard{background:#13151a;border-top:1px solid #2a2d3a;padding:6px 0}
.gr-hdr-row{display:flex;justify-content:space-between;align-items:center;padding:4px 10px 5px;cursor:default}
.gr-hdr-lbl{color:#8892b0;font-size:10px;font-weight:700;letter-spacing:.05em}
.gr-badge{font-size:10px;color:#6b7394}
.gr-row{display:flex;align-items:center;padding:4px 8px 4px 10px;gap:6px}
.gr-icon{font-size:11px;width:16px}.gr-name{flex:1;font-size:11px;color:#d4d8e8;line-height:1.3}
.gr-toggle{border:none;border-radius:10px;padding:2px 8px;font-size:10px;font-weight:700;cursor:pointer;transition:all .15s;min-width:34px}
.gr-on{background:#1a3a1a;color:#50fa7b;border:1px solid #2a5a2a}.gr-on:hover{background:#2a4a2a}
.gr-off{background:#2a2020;color:#6b7394;border:1px solid #3a3a3a}.gr-off:hover{background:#3a3a3a;color:#d4d8e8}
.mwarn{background:#2a2010;border-left:3px solid #ffb86c;border-radius:4px;padding:6px 10px;margin-top:6px;font-size:11px;color:#ffb86c;white-space:pre-wrap}

/* ── Scrollbar ── */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#2a2d3a;border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:#3a3d4a}
</style>
</head>
<body>

<div id="sb">
  <div id="sb-hdr">
    <div id="sb-title">&#9889; Work Assistant</div>
    <div id="sb-sub">Your AI work companion</div>
    <div id="sb-pub" style="margin-top:6px;font-size:10px;color:#6b7394;word-break:break-all"></div>
  </div>
  <div id="sb-srch">
    <input id="srch-inp" type="text" placeholder="&#128270;  Filter actions..." oninput="filter(this.value)">
  </div>
  <div id="sb-acts"></div>
  <div id="sb-guard">
    <div class="gr-hdr-row">
      <span class="gr-hdr-lbl">&#128737; GUARDRAILS</span>
      <span class="gr-badge" id="gr-badge"></span>
    </div>
    <div id="gr-list"></div>
  </div>
  <div id="sb-status">
    <div class="conn-lbl">CONNECTIONS</div>
    <div class="conn-grid" id="cg"></div>
    <div class="sb-bot">
      <button class="clr-btn" onclick="clearChat()">&#128465; Clear chat</button>
      <span id="dot">&#9679; Ready</span>
    </div>
  </div>
</div>

<div id="main">
  <div id="chat"></div>
  <div id="inp-area">
    <div id="inp-row">
      <textarea id="inp" placeholder="Ask me anything… (e.g. show my PRs to review)"
                onkeydown="onKey(event)"></textarea>
      <button id="snd" onclick="send()">Send &#8593;</button>
    </div>
    <div id="hint">Enter to send &nbsp;•&nbsp; Shift+Enter for new line</div>
  </div>
</div>

<script>
const GROUPS = __SIDEBAR_JSON__;
const TOTAL  = GROUPS.reduce((n,[,a])=>n+a.length,0);

// ── Build sidebar ─────────────────────────────────────────────────────────────
function buildSidebar(q=''){
  const c=document.getElementById('sb-acts');
  c.innerHTML='';
  const f=q.trim().toLowerCase();
  for(const[sec,acts] of GROUPS){
    const vis=f?acts.filter(([l,p])=>l.toLowerCase().includes(f)||p.toLowerCase().includes(f)):acts;
    if(!vis.length)continue;
    const h=document.createElement('div');h.className='sec-hdr';h.textContent=sec;c.appendChild(h);
    for(const[lbl,prm] of vis){
      const b=document.createElement('button');b.className='act-btn';b.textContent='  '+lbl;
      b.onclick=()=>dispatch(prm);c.appendChild(b);
    }
  }
}
function filter(v){buildSidebar(v);}

// ── Connections ───────────────────────────────────────────────────────────────
async function loadConns(){
  try{
    const d=await(await fetch('/connections')).json();
    const g=document.getElementById('cg');g.innerHTML='';
    for(const c of d){
      const s=document.createElement('span');
      s.className='ci '+(c.ok?'ci-ok':'ci-no');
      s.textContent=(c.ok?'● ':'○ ')+c.name;
      g.appendChild(s);
    }
    return d;
  }catch(e){return[];}
}

// ── Text formatting ───────────────────────────────────────────────────────────
function fmt(t){
  return t
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/\*\*([^*\\n]+)\*\*/g,'<b>$1</b>')
    .replace(/`([^`\\n]+)`/g,'<code>$1</code>')
    .replace(/^[•\-] (.+)$/gm,'<span class="blt">$1</span>');
}

// ── Chat messages ─────────────────────────────────────────────────────────────
function ts(){return new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});}

function addMsg(role,text){
  const chat=document.getElementById('chat');
  const div=document.createElement('div');div.className='msg';
  if(role==='user'){
    div.innerHTML=`<div class="mhdr"><span class="mn-u">You</span><span class="mts">${ts()}</span></div><div class="mbody mu">${fmt(text)}</div>`;
  }else if(role==='assistant'){
    div.innerHTML=`<div class="mhdr"><span class="mn-a">Assistant</span><span class="mts">${ts()}</span></div><div class="mbody ma">${fmt(text)}</div>`;
  }else if(role==='thinking'){
    div.id='thinking';div.innerHTML=`<span>&#9203;  ${text}</span>`;
  }else if(role==='error'){
    div.innerHTML=`<div class="mbody me">&#10060;  ${fmt(text)}</div>`;
  }
  chat.appendChild(div);chat.scrollTop=chat.scrollHeight;
  return div;
}
function removeThinking(){const e=document.getElementById('thinking');if(e)e.remove();}

// ── Send / poll ───────────────────────────────────────────────────────────────
let busy=false;

async function send(){
  if(busy)return;
  const inp=document.getElementById('inp');
  const txt=inp.value.trim();if(!txt)return;
  inp.value='';
  dispatch(txt);
}

async function dispatch(txt){
  busy=true;
  document.getElementById('snd').disabled=true;
  setDot('thinking');
  addMsg('user',txt);
  addMsg('thinking','Thinking…');
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:txt})});
    const {job_id,error}=await r.json();
    if(error){throw new Error(error);}
    await poll(job_id);
  }catch(e){
    removeThinking();addMsg('error','Network error: '+e.message);setDot('error');
  }finally{
    busy=false;document.getElementById('snd').disabled=false;
  }
}

async function poll(job_id){
  for(;;){
    await new Promise(r=>setTimeout(r,600));
    const j=await(await fetch('/poll/'+job_id)).json();
    if(j.status==='done'){
      removeThinking();
      addMsg('assistant',j.response);
      if(j.warnings&&j.warnings.length){
        const chat=document.getElementById('chat');
        for(const w of j.warnings){
          const d=document.createElement('div');d.className='mwarn';d.textContent=w;chat.appendChild(d);
        }
        chat.scrollTop=chat.scrollHeight;
      }
      setDot('ready');return;
    }
    if(j.status==='error'){removeThinking();addMsg('error',j.response);setDot('error');return;}
  }
}

async function clearChat(){
  await fetch('/clear',{method:'POST'});
  document.getElementById('chat').innerHTML='';
  addMsg('assistant','Chat cleared. How can I help?');
}

function setDot(s){
  const e=document.getElementById('dot');
  if(s==='ready')   {e.innerHTML='&#9679; Ready';   e.style.color='#50fa7b';}
  if(s==='thinking'){e.innerHTML='&#9203; Thinking&hellip;';e.style.color='#ffb86c';}
  if(s==='error')   {e.innerHTML='&#9888; Error';   e.style.color='#ff5555';}
}

function onKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send();}}

// ── Public URL (Cloudflare tunnel) ───────────────────────────────────────────
async function pollPublicUrl(){
  for(let i=0;i<30;i++){
    await new Promise(r=>setTimeout(r,2000));
    try{
      const d=await(await fetch('/public-url')).json();
      if(d.url){
        const el=document.getElementById('sb-pub');
        el.innerHTML=`&#127760; <a href="${d.url}" target="_blank" style="color:#64ffda;text-decoration:none">${d.url}</a>`;
        return;
      }
    }catch(e){}
  }
}

// ── Guardrails ────────────────────────────────────────────────────────────────
async function loadGuardrails(){
  try{
    const d=await(await fetch('/guardrails')).json();
    const list=document.getElementById('gr-list');list.innerHTML='';
    let on=0;
    for(const g of d){
      if(g.enabled)on++;
      const row=document.createElement('div');row.className='gr-row';
      row.title=g.description;
      row.innerHTML=`<span class="gr-icon">${g.icon}</span>`+
        `<span class="gr-name">${g.label}</span>`+
        `<button class="gr-toggle ${g.enabled?'gr-on':'gr-off'}" `+
        `onclick="toggleGuardrail('${g.name}')">${g.enabled?'ON':'OFF'}</button>`;
      list.appendChild(row);
    }
    document.getElementById('gr-badge').textContent=on+'/'+d.length;
  }catch(e){}
}
async function toggleGuardrail(name){
  await fetch('/guardrails/'+name,{method:'POST'});
  loadGuardrails();
}

// ── Welcome ───────────────────────────────────────────────────────────────────
async function init(){
  buildSidebar();
  loadGuardrails();
  pollPublicUrl();
  const conns=await loadConns();
  const ok=conns.filter(c=>c.ok).map(c=>c.name).join(', ')||'none';
  const miss=conns.filter(c=>!c.ok).map(c=>c.name);
  let msg=`👋  Hi! I'm your Work Assistant.\\n\\n**Connected:** ${ok}`;
  if(miss.length) msg+=`\\n\\n⚠️  **Not configured:** ${miss.join(', ')} — add keys to \`.env\``;
  msg+=`\\n\\nUse the sidebar to browse all **${TOTAL} quick actions** across ${GROUPS.length} categories, or type anything below.\\n\\n**Examples:**\\n• Show my PRs to review\\n• Create a Linear issue: payment page crashes on mobile\\n• Summarise my unread emails\\n• What meetings do I have today?`;
  addMsg('assistant',msg);
}
init();
</script>
</body>
</html>"""

HTML = HTML_TEMPLATE.replace("__SIDEBAR_JSON__", _SIDEBAR_JSON)


# ══════════════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return HTML


@app.route("/connections")
def connections():
    return jsonify(_check_connections())


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400

    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"status": "thinking", "response": None, "warnings": []}

    def run():
        try:
            from agent import run_agent_turn
            response, updated, warnings = run_agent_turn(_history, message, auto_confirm=True)
            _history.clear()
            _history.extend(updated)
            with _lock:
                _jobs[job_id] = {"status": "done", "response": response, "warnings": warnings}
        except BaseException as exc:
            with _lock:
                _jobs[job_id] = {"status": "error", "response": str(exc), "warnings": []}

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/poll/<job_id>")
def poll(job_id):
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"status": "unknown"}), 404
    return jsonify(job)


@app.route("/clear", methods=["POST"])
def clear():
    _history.clear()
    with _lock:
        _jobs.clear()
    return jsonify({"ok": True})


# ── Guardrails API ─────────────────────────────────────────────────────────────

@app.route("/guardrails")
def guardrails_get():
    from tools.guardrails import get_status
    return jsonify(get_status())


@app.route("/guardrails/<name>", methods=["POST"])
def guardrails_toggle(name):
    from tools.guardrails import toggle
    new_settings = toggle(name)
    return jsonify(new_settings)


# ══════════════════════════════════════════════════════════════════════════════
# CLOUDFLARE TUNNEL  (optional public URL)
# ══════════════════════════════════════════════════════════════════════════════

_PUBLIC_URL: str | None = None

def _start_tunnel():
    """Launch cloudflared quick-tunnel in background; parse and store the URL."""
    global _PUBLIC_URL
    import subprocess, re

    # Common install locations for cloudflared on macOS
    candidates = [
        "cloudflared",
        "/opt/homebrew/bin/cloudflared",
        "/usr/local/bin/cloudflared",
    ]
    binary = next((c for c in candidates
                   if subprocess.run(["which", c] if c == "cloudflared"
                                     else ["test", "-f", c],
                                     capture_output=True).returncode == 0), None)
    if not binary:
        print("⚠️  cloudflared not found — running local only.")
        return

    try:
        proc = subprocess.Popen(
            [binary, "tunnel", "--url", f"http://localhost:{PORT}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        url_re = re.compile(r"https://[a-z0-9\-]+\.trycloudflare\.com")
        for line in proc.stdout:
            m = url_re.search(line)
            if m:
                _PUBLIC_URL = m.group(0)
                print("\n" + "━" * 54)
                print(f"  🌐  Public URL : {_PUBLIC_URL}")
                print(f"  💻  Local URL  : http://localhost:{PORT}")
                print("━" * 54 + "\n")
                break
    except Exception as e:
        print(f"⚠️  Tunnel error: {e}")


@app.route("/public-url")
def public_url():
    return jsonify({"url": _PUBLIC_URL})


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    os.chdir(Path(__file__).parent)
    import webbrowser

    local_url = f"http://localhost:{PORT}"

    # Start Cloudflare tunnel in background thread
    tunnel_thread = threading.Thread(target=_start_tunnel, daemon=True)
    tunnel_thread.start()

    # Open browser after Flask is ready
    threading.Timer(1.5, lambda: webbrowser.open(local_url)).start()

    print(f"\n🚀  Work Assistant starting...")
    print(f"     Local  : {local_url}")
    print(f"     Public : fetching tunnel URL…  (appears in ~5 seconds)")
    print(f"     Press Ctrl+C to stop.\n")

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
