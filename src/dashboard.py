"""Dashboard HTML generator — single self-contained HTML page per user."""

import base64
import json
import re
from html import escape as html_escape
from pathlib import Path

from .config import OUTPUT_DIR, SESSION_TYPES

_LOGO_PATH = Path(__file__).parent.parent / "logo.png"

# Reverse mapping: Hebrew/English label -> type key
_TYPE_BY_LABEL: dict[str, str] = {}
for _k, _v in SESSION_TYPES.items():
    _TYPE_BY_LABEL[_v["he"]] = _k
    _TYPE_BY_LABEL[_v["en"]] = _k


def _logo_b64() -> str:
    """Load logo.png as base64 data URI."""
    if not _LOGO_PATH.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(
        _LOGO_PATH.read_bytes()
    ).decode("ascii")


def _detect_type(label: str) -> str:
    """Extract session type key from label like '🎓 הדרכה' -> 'training'."""
    cleaned = re.sub(r'^[^\u0590-\u05FEA-Za-z]+', '', label).strip()
    return _TYPE_BY_LABEL.get(cleaned, "other")


def _parse_transcript_text(text: str) -> dict | None:
    """Parse transcript markdown text -> {title, meta, content}."""
    if not text:
        return None

    lines = text.split("\n")
    title = lines[0].lstrip("# ").strip() if lines and lines[0].startswith("#") else ""

    meta = {}
    for line in lines:
        m = re.match(r'\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|', line)
        if m:
            meta[m.group(1)] = m.group(2)

    sep = text.find("\n---\n")
    content = text[sep + 5:].strip() if sep >= 0 else ""

    return {"title": title, "meta": meta, "content": content}


def _parse_transcript(path: Path) -> dict | None:
    """Parse transcript.md file -> {title, meta, content}."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    return _parse_transcript_text(text)


def _load_sessions(slug: str) -> list[dict]:
    """Scan output/{slug}/ for session folders, newest first."""
    base = OUTPUT_DIR / slug
    if not base.exists():
        return []

    sessions = []
    for folder in sorted(base.iterdir(), reverse=True):
        if not folder.is_dir() or len(folder.name) < 16 or folder.name[4] != "-":
            continue
        tp = folder / "transcript.md"
        if not tp.exists():
            continue
        parsed = _parse_transcript(tp)
        if not parsed:
            continue

        meta = parsed["meta"]
        stype = _detect_type(meta.get("Session Type", ""))

        analysis = None
        ap = folder / "analysis.md"
        if ap.exists():
            try:
                analysis = ap.read_text(encoding="utf-8")
            except Exception:
                pass

        sessions.append({
            "id": folder.name,
            "title": parsed["title"],
            "date": meta.get("Date", folder.name[:10]),
            "type": stype,
            "typeLabel": meta.get("Session Type", "\u05D0\u05D7\u05E8"),
            "speakers": meta.get("Speakers", "\u2014"),
            "originalDuration": meta.get("Original Duration", "\u2014"),
            "trimmedDuration": meta.get("Trimmed Duration", "\u2014"),
            "transcript": parsed["content"],
            "analysis": analysis,
        })

    return sessions


def _load_sessions_from_github(slug: str) -> list[dict]:
    """Load sessions from GitHub repo (for non-local / deployed mode)."""
    from github import GithubException
    from .storage import _get_repo
    from .config import GITHUB_BRANCH

    repo = _get_repo()
    sessions = []

    try:
        contents = repo.get_contents(slug, ref=GITHUB_BRANCH)
    except GithubException:
        return []

    for item in contents:
        if item.type != "dir" or len(item.name) < 16 or item.name[4] != "-":
            continue

        try:
            tf = repo.get_contents(f"{item.path}/transcript.md", ref=GITHUB_BRANCH)
            transcript_text = tf.decoded_content.decode("utf-8")
        except GithubException:
            continue

        parsed = _parse_transcript_text(transcript_text)
        if not parsed:
            continue

        meta = parsed["meta"]
        stype = _detect_type(meta.get("Session Type", ""))

        analysis = None
        try:
            af = repo.get_contents(f"{item.path}/analysis.md", ref=GITHUB_BRANCH)
            analysis = af.decoded_content.decode("utf-8")
        except GithubException:
            pass

        sessions.append({
            "id": item.name,
            "title": parsed["title"],
            "date": meta.get("Date", item.name[:10]),
            "type": stype,
            "typeLabel": meta.get("Session Type", "\u05D0\u05D7\u05E8"),
            "speakers": meta.get("Speakers", "\u2014"),
            "originalDuration": meta.get("Original Duration", "\u2014"),
            "trimmedDuration": meta.get("Trimmed Duration", "\u2014"),
            "transcript": parsed["content"],
            "analysis": analysis,
        })

    sessions.sort(key=lambda s: s["id"], reverse=True)
    return sessions


def generate_dashboard_from_github(
    slug: str, name: str = "", pw_hash: str | None = None,
) -> str:
    """Generate dashboard HTML using sessions from GitHub."""
    sessions = _load_sessions_from_github(slug)
    logo = _logo_b64()
    display = html_escape(name or slug)

    return (
        _TEMPLATE
        .replace("__LOGO__", logo)
        .replace("__NAME__", display)
        .replace("__COUNT__", str(len(sessions)))
        .replace("__SESSIONS__", _safe_json(sessions))
        .replace("__PW_HASH__", json.dumps(pw_hash) if pw_hash else "null")
    )


def _safe_json(data) -> str:
    """JSON-encode safe for embedding inside <script> tags."""
    s = json.dumps(data, ensure_ascii=False)
    return s.replace("</", "<\\/").replace("<!--", "<\\!--")


def generate_dashboard(slug: str, name: str = "", pw_hash: str | None = None) -> str:
    """Generate the full self-contained HTML dashboard."""
    sessions = _load_sessions(slug)
    logo = _logo_b64()
    display = html_escape(name or slug)

    return (
        _TEMPLATE
        .replace("__LOGO__", logo)
        .replace("__NAME__", display)
        .replace("__COUNT__", str(len(sessions)))
        .replace("__SESSIONS__", _safe_json(sessions))
        .replace("__PW_HASH__", json.dumps(pw_hash) if pw_hash else "null")
    )


def save_dashboard(slug: str, name: str = "", pw_hash: str | None = None) -> Path:
    """Generate and save dashboard to output/{slug}/index.html."""
    html = generate_dashboard(slug, name, pw_hash)
    out = OUTPUT_DIR / slug / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>zumo — __NAME__</title>
<link rel="icon" type="image/png" href="__LOGO__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;500;600;700&family=DM+Serif+Display&display=swap" rel="stylesheet">
<style>
:root {
    --bg-base: #09090B;
    --bg-surface: rgba(255,255,255,0.03);
    --bg-elevated: rgba(255,255,255,0.06);
    --bg-hover: rgba(255,255,255,0.08);
    --border: rgba(255,255,255,0.08);
    --border-strong: rgba(255,255,255,0.14);
    --accent-from: #F59E0B;
    --accent-to: #F97316;
    --accent-text: #FBBF24;
    --accent-muted: rgba(251,191,36,0.12);
    --text-primary: #FAFAFA;
    --text-secondary: #A1A1AA;
    --text-muted: #52525B;
    --success: #34D399;
    --warning: #FBBF24;
    --error: #F87171;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Rubik',sans-serif;background:var(--bg-base);color:var(--text-secondary);font-size:15px;line-height:1.7;-webkit-font-smoothing:antialiased;overflow-x:hidden}

/* Ambient */
.ambient{position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden}
.orb{position:absolute;border-radius:50%;filter:blur(130px);opacity:0.06}
.orb-1{width:600px;height:600px;background:var(--accent-from);top:-200px;right:-100px}
.orb-2{width:500px;height:500px;background:#7C3AED;bottom:-150px;left:-100px}

/* Layout */
.container{position:relative;z-index:1;max-width:768px;margin:0 auto;padding:0 20px}
@media(min-width:640px){.container{padding:0 32px}}

/* Password Gate */
#gate{position:fixed;inset:0;z-index:100;display:flex;align-items:center;justify-content:center;background:var(--bg-base)}
.gate-card{background:var(--bg-surface);border:1px solid var(--border);border-radius:24px;padding:40px 28px;text-align:center;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);max-width:380px;width:90%}
.gate-logo{width:80px;height:80px;border-radius:22px;margin-bottom:16px}
.gate-wordmark{font-family:'DM Serif Display',Georgia,serif;font-size:28px;background:linear-gradient(135deg,var(--accent-from),var(--accent-to));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:4px}
.gate-lock{color:var(--text-muted);opacity:0.5;margin-bottom:16px}
.gate-sub{font-size:13px;color:var(--text-muted);margin-bottom:28px}
.gate-input{width:100%;background:var(--bg-elevated);border:2px solid var(--border);border-radius:14px;padding:14px 16px;font-size:15px;font-family:inherit;color:var(--text-primary);text-align:center;outline:none;transition:border-color 200ms;direction:ltr}
.gate-input::placeholder{color:var(--text-muted)}
.gate-input:focus{border-color:var(--accent-text)}
.gate-input.error{border-color:var(--error);animation:shake 300ms ease}
.gate-btn{width:100%;border:none;border-radius:14px;padding:14px;font-size:15px;font-weight:600;font-family:inherit;cursor:pointer;background:linear-gradient(135deg,var(--accent-from),var(--accent-to));color:#000;margin-top:12px;transition:all 200ms}
.gate-btn:hover{opacity:0.9;transform:translateY(-1px)}
.gate-error{color:var(--error);font-size:13px;margin-top:10px;display:none}
@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}

/* Sticky Header */
.header{position:sticky;top:12px;z-index:50;background:rgba(9,9,11,0.7);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid var(--border);border-radius:20px;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
.header-brand{display:flex;align-items:center;gap:10px}
.header-brand img{width:44px;height:44px;border-radius:12px}
.header .wordmark{font-family:'DM Serif Display',Georgia,serif;font-size:22px;background:linear-gradient(135deg,var(--accent-from),var(--accent-to));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.pill{background:var(--accent-muted);color:var(--accent-text);font-size:12px;font-weight:600;padding:6px 16px;border-radius:100px}

/* Session Cards */
.sessions{display:flex;flex-direction:column;gap:8px;padding-bottom:64px}
.card{background:var(--bg-surface);border:1px solid var(--border);border-radius:20px;overflow:hidden;transition:all 200ms;position:relative}
.card::before{content:'';position:absolute;top:20px;bottom:20px;right:0;width:4px;background:linear-gradient(180deg,var(--accent-from),var(--accent-to));border-radius:0 4px 4px 0}
.card:hover{background:var(--bg-elevated);border-color:var(--border-strong)}
.card-header{display:flex;align-items:flex-start;gap:14px;padding:18px 22px;cursor:pointer;user-select:none}
.card-icon{width:42px;height:42px;background:var(--accent-muted);border-radius:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.card-icon svg{width:20px;height:20px;color:var(--accent-text)}
.card-info{flex:1;min-width:0}
.card-title{font-size:15px;font-weight:600;color:var(--text-primary);margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-meta{font-size:13px;color:var(--text-muted);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.meta-dot{width:4px;height:4px;background:var(--text-muted);border-radius:50%;flex-shrink:0}
.card-date{font-size:13px;font-weight:500;color:var(--text-muted);font-variant-numeric:tabular-nums;flex-shrink:0;direction:ltr}
.card-chevron{width:20px;height:20px;color:var(--text-muted);flex-shrink:0;transition:transform 200ms;margin-top:4px}
.card.open .card-chevron{transform:rotate(180deg)}

/* Card Body */
.card-body{display:none}
.card.open .card-body{display:block}

/* Tabs */
.tabs{display:flex;gap:6px;padding:12px 22px;border-top:1px solid var(--border)}
.tab{padding:10px 24px;font-size:13px;font-weight:600;color:var(--text-muted);cursor:pointer;border-radius:100px;border:2px solid transparent;transition:all 200ms;background:transparent;font-family:inherit}
.tab:hover{color:var(--text-secondary);background:var(--bg-hover)}
.tab.active{color:var(--accent-text);background:var(--accent-muted);border-color:rgba(251,191,36,0.2)}

/* Content Panel */
.content-area{padding:0 22px 22px}
.content-inner{background:var(--bg-elevated);border:1px solid var(--border);border-radius:16px;padding:24px;max-height:70vh;overflow-y:auto}

/* Markdown Content */
.md h1{font-size:20px;font-weight:700;color:var(--text-primary);margin:24px 0 12px;line-height:1.3}
.md h1:first-child{margin-top:0}
.md h2{font-size:17px;font-weight:600;color:var(--text-primary);margin:20px 0 10px;line-height:1.3}
.md h2:first-child{margin-top:0}
.md h3{font-size:15px;font-weight:600;color:var(--text-primary);margin:16px 0 8px;line-height:1.4}
.md h3:first-child{margin-top:0}
.md p{margin-bottom:12px;line-height:1.7}
.md p:last-child{margin-bottom:0}
.md strong{color:var(--text-primary);font-weight:600}
.md em{font-style:italic}
.md blockquote{border-right:3px solid var(--accent-from);padding-right:16px;margin:16px 0;color:var(--text-primary);font-style:italic}
.md blockquote p{margin-bottom:8px}
.md hr{border:none;height:1px;background:var(--border);margin:20px 0}
.md ul,.md ol{padding-right:24px;margin:8px 0 12px}
.md li{margin-bottom:4px}
.md table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14px}
.md th{text-align:right;font-weight:600;font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.5px;padding:10px 12px;border-bottom:2px solid var(--border-strong)}
.md td{padding:12px;border-bottom:1px solid var(--border)}
.md code{background:var(--bg-hover);padding:2px 6px;border-radius:6px;font-size:13px}
.md a{color:var(--accent-text);text-decoration:none}
.md a:hover{text-decoration:underline}

/* Scrollbar */
.content-inner::-webkit-scrollbar{width:6px}
.content-inner::-webkit-scrollbar-track{background:transparent}
.content-inner::-webkit-scrollbar-thumb{background:var(--border-strong);border-radius:3px}

/* Empty State */
.empty{text-align:center;padding:64px 24px;color:var(--text-muted)}
.empty svg{width:48px;height:48px;margin-bottom:16px;opacity:0.3}
.empty p{font-size:15px}

/* Responsive */
@media(max-width:640px){
    .container{padding:0 16px}
    .card-header{padding:14px 16px;gap:12px}
    .card-icon{width:38px;height:38px;border-radius:12px}
    .card-icon svg{width:18px;height:18px}
    .card-title{font-size:14px}
    .tabs{padding:10px 16px;gap:4px}
    .tab{padding:8px 16px;font-size:12px}
    .content-area{padding:0 16px 16px}
    .content-inner{padding:16px}
    .header{padding:10px 16px;border-radius:16px}
    .header-brand img{width:36px;height:36px}
    .header .wordmark{font-size:18px}
}

/* Reduced Motion */
@media(prefers-reduced-motion:reduce){
    *,*::before,*::after{transition-duration:0.01ms!important;animation-duration:0.01ms!important}
}

/* Focus */
*:focus-visible{outline:none;box-shadow:0 0 0 2px var(--bg-base),0 0 0 4px rgba(245,158,11,0.4);border-radius:12px}
</style>
</head>
<body>

<div class="ambient"><div class="orb orb-1"></div><div class="orb orb-2"></div></div>

<!-- Password Gate -->
<div id="gate">
    <div class="gate-card">
        <img class="gate-logo" src="__LOGO__" alt="Zumo">
        <div class="gate-wordmark">zumo</div>
        <div class="gate-lock">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
        </div>
        <div class="gate-sub">הזן סיסמה כדי לגשת לתמלולים</div>
        <input type="password" class="gate-input" id="pw" placeholder="Passcode" autocomplete="off">
        <button class="gate-btn" id="pw-btn">כניסה</button>
        <div class="gate-error" id="pw-error">סיסמה שגויה</div>
    </div>
</div>

<!-- App -->
<div id="app" style="display:none">
    <div class="container">
        <div style="height:16px"></div>
        <header class="header">
            <div class="header-brand">
                <img src="__LOGO__" alt="Zumo">
                <span class="wordmark">zumo</span>
            </div>
            <span class="pill" id="count-pill"></span>
        </header>
        <div class="sessions" id="sessions"></div>
    </div>
</div>

<script>
var SESSIONS = __SESSIONS__;
var PW_HASH = __PW_HASH__;

var ICONS = {
    'team-meeting': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    'training': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg>',
    'client-call': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m11 17 2 2a1 1 0 1 0 3-3"/><path d="m14 14 2.5 2.5a1 1 0 1 0 3-3l-3.88-3.88a3 3 0 0 0-4.24 0l-.88.88a1 1 0 1 1-3-3l2.81-2.81a5.79 5.79 0 0 1 7.06-.87l.47.28a2 2 0 0 0 1.42.25L21 4"/><path d="m21 3 1 11h-2"/><path d="M3 3 2 14h2"/><path d="m8 7-3 3 2.81 2.81a5.79 5.79 0 0 0 .69.57"/><path d="m6.5 12.5 3.88 3.88a3 3 0 0 0 1.78.91"/></svg>',
    'phone-call': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    'coaching': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/></svg>',
    'other': '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/></svg>'
};

/* ─── Password Gate ─── */
(function(){
    if(!PW_HASH){
        document.getElementById('gate').style.display='none';
        document.getElementById('app').style.display='';
        init();
        return;
    }
    var inp=document.getElementById('pw'),btn=document.getElementById('pw-btn'),err=document.getElementById('pw-error');
    async function check(){
        var v=inp.value;if(!v)return;
        var hash=await sha256(v);
        if(hash===PW_HASH){
            document.getElementById('gate').style.display='none';
            document.getElementById('app').style.display='';
            init();
        }else{
            inp.classList.add('error');err.style.display='block';
            setTimeout(function(){inp.classList.remove('error')},300);
        }
    }
    btn.addEventListener('click',check);
    inp.addEventListener('keydown',function(e){if(e.key==='Enter')check()});
    async function sha256(s){
        var buf=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s));
        return Array.from(new Uint8Array(buf)).map(function(b){return b.toString(16).padStart(2,'0')}).join('');
    }
})();

/* ─── App ─── */
function init(){
    var container=document.getElementById('sessions');
    document.getElementById('count-pill').textContent=SESSIONS.length+' \u05EA\u05DE\u05DC\u05D5\u05DC\u05D9\u05DD';

    if(!SESSIONS.length){
        container.innerHTML='<div class="empty"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg><p>\u05D0\u05D9\u05DF \u05EA\u05DE\u05DC\u05D5\u05DC\u05D9\u05DD \u05E2\u05D3\u05D9\u05D9\u05DF</p></div>';
        return;
    }

    SESSIONS.forEach(function(s,i){
        var card=document.createElement('div');
        card.className='card';
        card.id=s.id;

        var dp=s.date.split(/[\s-]/);
        var dd=dp.length>=3?dp[2]+'.'+dp[1]:s.date;
        var hasA=!!s.analysis;

        card.innerHTML=
            '<div class="card-header" tabindex="0" role="button" aria-expanded="false" onclick="toggle('+i+')" onkeydown="if(event.key===\'Enter\')toggle('+i+')">'+
                '<div class="card-icon">'+(ICONS[s.type]||ICONS['other'])+'</div>'+
                '<div class="card-info">'+
                    '<div class="card-title">'+esc(s.title)+'</div>'+
                    '<div class="card-meta"><span>'+esc(s.speakers)+'</span><span class="meta-dot"></span><span>'+esc(s.trimmedDuration)+'</span></div>'+
                '</div>'+
                '<span class="card-date">'+dd+'</span>'+
                '<svg class="card-chevron" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>'+
            '</div>'+
            '<div class="card-body">'+
                '<div class="tabs">'+
                    '<button class="tab active" onclick="event.stopPropagation();switchTab('+i+',\'transcript\')">\u05EA\u05DE\u05DC\u05D5\u05DC</button>'+
                    (hasA?'<button class="tab" onclick="event.stopPropagation();switchTab('+i+',\'analysis\')">\u05E0\u05D9\u05EA\u05D5\u05D7</button>':'')+
                '</div>'+
                '<div class="content-area">'+
                    '<div class="content-inner md" id="content-'+i+'"></div>'+
                '</div>'+
            '</div>';

        container.appendChild(card);
    });

    if(location.hash){
        var target=document.getElementById(location.hash.slice(1));
        if(target&&target.classList.contains('card')){
            var idx=Array.from(document.querySelectorAll('.card')).indexOf(target);
            if(idx>=0)toggle(idx);
            setTimeout(function(){target.scrollIntoView({behavior:'smooth',block:'start'})},100);
        }
    }
}

function toggle(i){
    var cards=document.querySelectorAll('.card');
    var card=cards[i];
    var wasOpen=card.classList.contains('open');

    cards.forEach(function(c){c.classList.remove('open');c.querySelector('.card-header').setAttribute('aria-expanded','false')});

    if(!wasOpen){
        card.classList.add('open');
        card.querySelector('.card-header').setAttribute('aria-expanded','true');
        var content=document.getElementById('content-'+i);
        if(!content.innerHTML){
            content.innerHTML=renderMd(SESSIONS[i].transcript);
        }
        // Reset tabs to transcript
        var tabs=card.querySelectorAll('.tab');
        tabs.forEach(function(t,ti){t.classList.toggle('active',ti===0)});
    }
}

function switchTab(i,tab){
    var card=document.querySelectorAll('.card')[i];
    var tabs=card.querySelectorAll('.tab');
    var content=document.getElementById('content-'+i);
    var s=SESSIONS[i];

    tabs.forEach(function(t){t.classList.remove('active')});
    if(tab==='transcript'){
        tabs[0].classList.add('active');
        content.innerHTML=renderMd(s.transcript);
    }else{
        if(tabs[1])tabs[1].classList.add('active');
        content.innerHTML=renderMd(s.analysis||'');
    }
    content.scrollTop=0;
}

function esc(s){
    var d=document.createElement('div');
    d.textContent=s||'';
    return d.innerHTML;
}

/* ─── Markdown Renderer ─── */
function renderMd(text){
    if(!text)return '<p style="color:var(--text-muted)">\u05D0\u05D9\u05DF \u05EA\u05D5\u05DB\u05DF</p>';

    var lines=text.split('\n');
    var html='';
    var inUl=false,inOl=false,inTable=false,inBq=false,tHead=false;
    var para=[];

    function flush(){
        if(para.length){html+='<p>'+inl(para.join(' '))+'</p>';para=[];}
    }
    function closeAll(){
        if(inUl){html+='</ul>';inUl=false;}
        if(inOl){html+='</ol>';inOl=false;}
        if(inTable){html+='</tbody></table>';inTable=false;tHead=false;}
        if(inBq){html+='</blockquote>';inBq=false;}
    }

    for(var i=0;i<lines.length;i++){
        var t=lines[i].trim();

        if(!t){flush();if(!inTable)closeAll();continue;}

        // Heading
        var hm=t.match(/^(#{1,3})\s+(.+)/);
        if(hm){flush();closeAll();var lv=hm[1].length;html+='<h'+lv+'>'+inl(hm[2])+'</h'+lv+'>';continue;}

        // HR
        if(/^[-*_]{3,}$/.test(t)){flush();closeAll();html+='<hr>';continue;}

        // Table
        if(t.charAt(0)==='|'&&t.charAt(t.length-1)==='|'){
            flush();
            if(/^\|[\s:|-]+\|$/.test(t))continue;
            if(!inTable){
                closeAll();
                html+='<table><thead><tr>';
                t.split('|').slice(1,-1).forEach(function(c){html+='<th>'+inl(c.trim())+'</th>'});
                html+='</tr>';
                var nx=(lines[i+1]||'').trim();
                if(/^\|[\s:|-]+\|$/.test(nx))i++;
                html+='</thead><tbody>';
                inTable=true;tHead=true;
                continue;
            }
            html+='<tr>';
            t.split('|').slice(1,-1).forEach(function(c){html+='<td>'+inl(c.trim())+'</td>'});
            html+='</tr>';
            continue;
        }
        if(inTable){html+='</tbody></table>';inTable=false;tHead=false;}

        // Blockquote
        if(t.charAt(0)==='>'){
            flush();
            if(!inBq){closeAll();html+='<blockquote>';inBq=true;}
            html+='<p>'+inl(t.replace(/^>\s*/,''))+'</p>';
            continue;
        }
        if(inBq){html+='</blockquote>';inBq=false;}

        // Unordered list
        if(/^[-*]\s/.test(t)){
            flush();if(inOl){html+='</ol>';inOl=false;}
            if(!inUl){html+='<ul>';inUl=true;}
            html+='<li>'+inl(t.replace(/^[-*]\s+/,''))+'</li>';
            continue;
        }

        // Ordered list
        if(/^\d+[.)]\s/.test(t)){
            flush();if(inUl){html+='</ul>';inUl=false;}
            if(!inOl){html+='<ol>';inOl=true;}
            html+='<li>'+inl(t.replace(/^\d+[.)]\s+/,''))+'</li>';
            continue;
        }

        if(inUl){html+='</ul>';inUl=false;}
        if(inOl){html+='</ol>';inOl=false;}

        para.push(t);
    }
    flush();closeAll();
    return html;
}

function inl(s){
    return s
        .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
        .replace(/\*(.+?)\*/g,'<em>$1</em>')
        .replace(/`(.+?)`/g,'<code>$1</code>')
        .replace(/\[(.+?)\]\((.+?)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
}

/* ─── Keyboard: Escape to close ─── */
document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){
        document.querySelectorAll('.card.open').forEach(function(c){
            c.classList.remove('open');
            c.querySelector('.card-header').setAttribute('aria-expanded','false');
        });
    }
});
</script>
</body>
</html>
"""
