"""Generates out/path.html: an animated replay of a farming run, straight from debug.jsonl.

Left: a fixed backbone of stages that lights up as the run reaches them.
Right: a terminal that types each real step, colored by outcome (green ok / purple AI /
amber warning / red error / cyan key).

The step data is the ACTUAL debug.jsonl the code wrote — nothing hand-authored. Re-run a farm,
re-render, and the page (and any GIF you capture of it) reflects exactly what happened.

Usage: python tools/path_viewer.py   (after a run)
  render(live=True) adds a 1.5s meta-refresh so the page colors in while a run is still going;
  run.py calls it that way during the run, then once more static at the end.
"""
from __future__ import annotations
import json, html
from pathlib import Path
from collections import OrderedDict

OUT = Path(__file__).parent.parent / "out"
JSONL = OUT / "debug.jsonl"
HTMLF = OUT / "path.html"

# Fixed backbone, in order. Real stage codes emitted by the code -> plain English label.
# A step's stage maps to a backbone node via STAGE2NODE (many codes fold into one node).
SPINE = [
    ("OPEN",    "Open page"),
    ("COOKIE",  "Cookie banner"),
    ("ENTRY",   "Find signup"),
    ("LOGIN",   "Sign in"),
    ("FORM",    "Onboarding form"),
    ("VERIFY",  "Email verify"),
    ("ONBOARD", "Skip onboarding"),
    ("KEY",     "API key"),
    ("AI",      "AI fallback"),
    ("DONE",    "Outcome"),
]

# real stage code (from log.step) -> backbone node id above
STAGE2NODE = {
    "ARRIVO": "OPEN", "GOTO": "OPEN",
    "COOKIE": "COOKIE",
    "ENTRY": "ENTRY", "INGRESSO": "ENTRY",
    "GOOGLE": "LOGIN", "GITHUB": "LOGIN", "ACCESSO": "LOGIN", "LOGOUT": "LOGIN",
    "MODULO": "FORM", "FORM": "FORM",
    "VERIFICA": "VERIFY",
    "ONBOARD": "ONBOARD",
    "KEY": "KEY", "CHIAVI": "KEY",
    "AI": "AI", "VISION": "AI", "LEARNED": "AI",
    "ESITO": "DONE", "MURO": "DONE", "SALTO": "DONE",
}

# real stage code -> readable line label in the terminal
STAGE_EN = {
    "ARRIVO": "Open page", "GOTO": "Open page", "COOKIE": "Cookie banner",
    "ENTRY": "Find signup", "INGRESSO": "Already in", "GOOGLE": "Google login",
    "GITHUB": "GitHub login", "ACCESSO": "Sign in", "LOGOUT": "Sign out",
    "MODULO": "Signup form", "FORM": "Onboarding form", "VERIFICA": "Email verify",
    "ONBOARD": "Skip onboarding", "KEY": "API key", "CHIAVI": "API key",
    "AI": "AI fallback", "VISION": "AI vision", "LEARNED": "Learned recipe",
    "ESITO": "Outcome", "MURO": "Known wall", "SALTO": "Skipped", "RESULT": "Result",
}

# muted palette — desaturated ~30% to match the softer look of the compressed GIF
COL = {"ok": "#63c497", "skip": "#6d7fa3", "ai": "#a794d1", "warn": "#dcbd7a",
       "err": "#dd8b94", "key": "#66bcc7", "info": "#8496b6", "wait": "#dcbd7a",
       "captcha": "#dd8b94"}


def _load():
    sites = OrderedDict()
    cur = None
    if not JSONL.exists():
        return sites
    for ln in JSONL.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except Exception:
            continue
        if e.get("ev") == "head":
            cur = e.get("txt", "?")
            sites.setdefault(cur, [])
        elif e.get("ev") == "step":
            site = e.get("site", cur or "-")
            sites.setdefault(site, []).append(e)
    return sites


# redact anything that looks like an email or a real key before it reaches the page.
# PRIMARY: the exact key values out/keys.txt already recorded for THIS run — no guessing,
# whatever provider/prefix it is gets caught (a prefix whitelist is whack-a-mole: cohere_ was
# missing until it bit us). FALLBACK: a generic prefix heuristic, only as a safety net for a
# key that for some reason isn't in keys.txt yet.
import re as _re
_EMAIL = _re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
_KEYISH = _re.compile(r"\b(gsk_|sk-|co_|cohere_|fw_|csk-|di_|key_)[A-Za-z0-9_\-]{6,}")
_KEYSFILE = Path(__file__).parent.parent / "out" / "keys.txt"


def _harvested_keys() -> list[str]:
    out = []
    try:
        for ln in _KEYSFILE.read_text(encoding="utf-8").splitlines():
            parts = ln.split("\t")
            if len(parts) >= 2 and parts[1].strip():
                out.append(parts[1].strip())
    except Exception:
        pass
    return out


def _redact(s: str) -> str:
    s = _EMAIL.sub("you@example.com", s or "")
    for real_key in _harvested_keys():
        if real_key and real_key in s:
            head = real_key[:min(8, len(real_key) // 2)]
            s = s.replace(real_key, head + "•" * 8)
    s = _KEYISH.sub(lambda m: m.group(1) + "•" * 8, s)  # rete di sicurezza per key non ancora salvate
    return s


# The code logs outcome/detail free-text in Italian; translate the common phrases so the public
# English viewer reads cleanly. Unknown phrases pass through unchanged (still real data).
_TR = {
    "pagina aperta": "page opened", "rifiutato": "rejected", "accettato": "accepted",
    "assente": "none", "click": "clicked", "bottone cliccato": "button clicked",
    "usa altro account": "use another account", "digito email": "type email",
    "digito password": "type password", "password richiesta": "password required",
    "non necessaria": "not required", "niente da saltare": "nothing to skip",
    "pannello saltato": "panel skipped", "gia dentro": "already in",
    "gia nell'area chiavi": "already on key page", "compilato": "filled",
    "submit assente": "no submit button", "non trovata in automatico": "not found automatically",
    "non ottenuta": "not found yet", "in campo": "engaged", "azione ripetuta": "repeated action",
    "creata": "created", "generata": "generated", "letta in chiaro": "read in clear",
    "letta da clipboard": "read from clipboard", "chiave ottenuta": "key obtained",
    "nessuna chiave": "no key", "muro login": "login wall", "ri-accesso con Google": "re-auth via Google",
    "ri-accesso con GitHub": "re-auth via GitHub", "OAuth rifiutato": "OAuth refused",
    "richiede telefono": "phone required", "richiede carta di credito": "credit card required",
    "ricette riusate": "recipes reused", "proseguo": "continue", "salto la registrazione": "skip signup",
    "passo all'IA": "hand to AI", "sito abbandonato": "site abandoned",
    "trovata sezione chiavi": "found key section", "nav voce chiavi": "clicked key nav item",
    "passo all'ia": "hand to AI",
}
# phrases that appear inside a longer detail string -> substring replacements
_TR_SUB = {
    "trova e copia la api key di": "find & copy the API key of",
    "creane una nuova se serve": "create one if needed",
}


def _tr(s: str) -> str:
    low = (s or "").strip().lower()
    if low in _TR:
        return _TR[low]
    out = s or ""
    for it, en in _TR_SUB.items():
        idx = out.lower().find(it)
        if idx >= 0:
            out = out[:idx] + en + out[idx + len(it):]
    return out


def _steps_for(steps):
    """Turn raw log steps into the compact records the page animates."""
    out = []
    for s in steps:
        stage = s.get("stage", "")
        out.append({
            "node": STAGE2NODE.get(stage, ""),
            "stage": STAGE_EN.get(stage, stage.title()),
            "outcome": _redact(_tr(s.get("outcome", ""))),
            "detail": _redact(_tr(s.get("detail", ""))),
            "kind": s.get("kind", "info"),
        })
    return out


def render(live: bool = False):
    """Render out/path.html — the animated terminal replay. live=True adds a meta-refresh so
    the page updates while a run is still writing debug.jsonl."""
    sites = _load()
    # pick the most interesting site to feature: the running/last one with the most steps
    runs = [(name, _steps_for(st)) for name, st in sites.items() if st]
    payload = [{"name": n, "steps": st} for n, st in runs]
    refresh = '<meta http-equiv="refresh" content="1.5">' if live else ""
    data_json = json.dumps(payload, ensure_ascii=False)
    spine_json = json.dumps(SPINE, ensure_ascii=False)
    col_json = json.dumps(COL, ensure_ascii=False)
    HTMLF.parent.mkdir(parents=True, exist_ok=True)
    HTMLF.write_text(_TEMPLATE
                     .replace("/*REFRESH*/", refresh)
                     .replace("/*DATA*/", data_json)
                     .replace("/*SPINE*/", spine_json)
                     .replace("/*COLORS*/", col_json)
                     .replace("/*ANIM*/", "false" if live else "true"),
                     encoding="utf-8")
    n = len(payload)
    print(f"wrote {HTMLF}  ({n} site{'s' if n != 1 else ''})")


_TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">/*REFRESH*/
<title>Signup run — live replay</title>
<style>
:root{--ink:#0a0e1a;--panel:#121a2e;--line:#202c47;--txt:#e8eefb;--dim:#7c8bab;--faint:#4a5877;
 --ok:#63c497;--skip:#6d7fa3;--ai:#a794d1;--warn:#dcbd7a;--err:#dd8b94;--key:#66bcc7;
 --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--sans:system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}html,body{margin:0}
body{background:radial-gradient(1200px 600px at 78% -10%,#14203a 0%,transparent 60%),
 radial-gradient(900px 500px at -5% 110%,#161033 0%,transparent 55%),var(--ink);
 color:var(--txt);font-family:var(--sans);line-height:1.5;padding:clamp(16px,3vw,40px);min-height:100vh}
.wrap{max-width:1060px;margin:0 auto}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px 16px}
h1{font-size:clamp(19px,3vw,27px);margin:0;letter-spacing:-.02em;font-weight:700}
.pill{font-family:var(--mono);font-size:13px;color:var(--key);border:1px solid #1c4a55;
 background:#0c2830;padding:3px 11px;border-radius:20px}
.sub{color:var(--dim);font-size:14px;margin:4px 0 18px;max-width:66ch}
.stage{display:grid;grid-template-columns:220px 1fr;gap:18px}
@media(max-width:660px){.stage{grid-template-columns:1fr}}
.spine{display:flex;flex-direction:column;gap:4px;position:relative}
.spine::before{content:"";position:absolute;left:15px;top:14px;bottom:14px;width:2px;background:var(--line);z-index:0}
.node{display:flex;align-items:center;gap:11px;padding:7px 10px;border-radius:10px;position:relative;z-index:1;
 opacity:.36;transition:opacity .4s,background .4s}
.node .dot{flex:0 0 auto;width:18px;height:18px;border-radius:50%;border:2px solid var(--faint);
 background:var(--ink);display:grid;place-items:center;transition:all .35s}
.node .dot svg{width:11px;height:11px;opacity:0;transform:scale(.4);transition:all .3s;color:var(--c)}
.node .lbl{font-size:13px;color:var(--dim);transition:color .35s}
.node.on{opacity:1;background:#101a30}.node.on .lbl{color:var(--txt)}
.node.on .dot{border-color:var(--c);background:color-mix(in srgb,var(--c) 22%,var(--ink))}
.node.on .dot svg{opacity:1;transform:scale(1)}
.node.pulse .dot{animation:ping .7s ease-out}
@keyframes ping{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--c) 70%,transparent)}100%{box-shadow:0 0 0 13px transparent}}
.term{background:linear-gradient(#0c1322,#0a1020);border:1px solid var(--line);border-radius:14px;overflow:hidden;
 box-shadow:0 24px 60px -30px #000,inset 0 1px 0 #ffffff08}
.tbar{display:flex;align-items:center;gap:8px;padding:10px 13px;border-bottom:1px solid var(--line);background:#0e1626}
.tbar .b{width:11px;height:11px;border-radius:50%}.b1{background:#ff5f57}.b2{background:#febc2e}.b3{background:#28c840}
.tbar .nm{font-family:var(--mono);font-size:12px;color:var(--faint);margin-left:6px}
.tbar .pr{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums}
.log{padding:13px 15px;font-family:var(--mono);font-size:13px;min-height:330px;display:flex;flex-direction:column;gap:3px}
.ln{display:grid;grid-template-columns:15px 1fr;gap:9px;align-items:start;opacity:0;transform:translateY(6px);animation:in .28s forwards}
@keyframes in{to{opacity:1;transform:none}}
.ln .ic{margin-top:2px;color:var(--c)}.ln .ic svg{width:13px;height:13px;display:block}
.ln .tx{min-width:0;color:var(--txt)}.ln .stg{color:var(--c);font-weight:600}.ln .det{color:var(--faint)}
.ln.warnrow .tx{color:#ffe2a6}.ln.errrow .tx{color:#ffc2c9}
.cursor{display:inline-block;width:8px;height:14px;background:var(--key);margin-left:3px;vertical-align:-2px;animation:blink 1s step-end infinite}
@keyframes blink{50%{opacity:0}}
.verdict{margin-top:13px;display:flex;align-items:center;gap:11px;flex-wrap:wrap;opacity:0;transition:opacity .5s}
.verdict.show{opacity:1}
.badge{font-family:var(--mono);font-size:13px;font-weight:700;padding:6px 13px;border-radius:22px;display:inline-flex;align-items:center;gap:8px}
.badge.no{color:#ffd7dc;background:#2a0f16;border:1px solid #57202a}
.badge.yes{color:#c9fff0;background:#082922;border:1px solid #17564a}
.vtext{color:var(--dim);font-size:13px}
.controls{display:flex;gap:9px;margin:20px 0 8px;flex-wrap:wrap}
button{font-family:var(--sans);font-size:14px;font-weight:600;color:var(--ink);background:var(--key);border:0;
 padding:8px 16px;border-radius:10px;cursor:pointer}button.ghost{background:transparent;color:var(--dim);border:1px solid var(--line)}
button:focus-visible{outline:2px solid var(--key);outline-offset:2px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 14px}
.tab{font-family:var(--mono);font-size:12px;padding:5px 11px;border-radius:20px;border:1px solid var(--line);
 background:transparent;color:var(--dim);cursor:pointer}.tab.sel{border-color:var(--key);color:var(--key);background:#0c2830}
.legend{display:flex;flex-wrap:wrap;gap:8px 15px;margin-top:20px;padding-top:15px;border-top:1px solid var(--line);font-size:12px;color:var(--dim)}
.legend span{display:inline-flex;align-items:center;gap:6px}.legend i{width:9px;height:9px;border-radius:50%}
.foot{color:var(--faint);font-size:12px;margin-top:13px;font-family:var(--mono)}
.empty{color:var(--faint);font-family:var(--mono);padding:40px;text-align:center}
</style></head><body>
<div class="wrap">
<header><h1>Watch the agent farm an API key</h1><span class="pill" id="pill">—</span></header>
<p class="sub">A real replay from <b>out/debug.jsonl</b> — every line is one thing the agent actually
did: dismiss the cookie wall, click through OAuth, land on the key page. The backbone on the
left lights up as stages are reached; the AI fallback steps in only when the deterministic path
runs out.</p>
<div class="tabs" id="tabs"></div>
<div class="stage">
  <div class="spine" id="spine"></div>
  <div><div class="term"><div class="tbar"><span class="b b1"></span><span class="b b2"></span><span class="b b3"></span>
    <span class="nm" id="agentnm">agent — live</span><span class="pr" id="pr">0 / 0</span></div>
    <div class="log" id="log"></div></div>
    <div class="verdict" id="verdict"></div></div>
</div>
<div class="controls"><button id="replay">▶ Replay</button><button class="ghost" id="skip">Skip to end</button></div>
<div class="legend" id="legend"></div>
<p class="foot">Generated from out/debug.jsonl · emails &amp; key values redacted</p>
</div>
<script>
const DATA=/*DATA*/, SPINE=/*SPINE*/, COL=/*COLORS*/, ANIM=/*ANIM*/;
const S='fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"';
const ICON={
 ok:`<path d="M3 8.5l3.2 3.2L13 5" ${S} stroke-width="2"/>`,
 skip:`<path d="M4 4l5 4-5 4zM10 4v8" ${S} stroke-width="1.7"/>`,
 ai:`<rect x="3.3" y="5" width="9.4" height="7" rx="1.7" ${S}/><path d="M8 2.3V5M5.4 8.5h.01M10.6 8.5h.01" ${S}/>`,
 warn:`<path d="M8 2.4L14.6 13.6H1.4z" ${S}/><path d="M8 6.4v3M8 11.4h.01" ${S}/>`,
 err:`<circle cx="8" cy="8" r="6" ${S}/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" ${S} stroke-width="1.6"/>`,
 key:`<circle cx="6" cy="6" r="3.1" ${S} stroke-width="1.6"/><path d="M8.3 8.3L13 13m-2-2l1.3-1.3" ${S} stroke-width="1.6"/>`,
 // action-specific
 globe:`<circle cx="8" cy="8" r="6" ${S}/><path d="M2 8h12M8 2c2 2 2 10 0 12M8 2c-2 2-2 10 0 12" ${S}/>`,
 google:`<path d="M14 8.2c0-.5 0-.9-.1-1.3H8v2.6h3.4c-.15 1-.9 1.9-2 2.4v1.6h2C13 12.7 14 10.7 14 8.2z" fill="currentColor" stroke="none"/><path d="M8 14c1.6 0 3-.5 4-1.5l-2-1.6c-.5.4-1.2.6-2 .6-1.6 0-2.9-1-3.4-2.5H2.5v1.6C3.5 12.6 5.5 14 8 14z" fill="currentColor" stroke="none" opacity=".85"/><path d="M4.6 8.6c-.15-.4-.2-.8-.2-1.1s.05-.7.2-1.1V4.8H2.5C2.15 5.6 2 6.5 2 7.5s.15 1.9.5 2.7l2.1-1.6z" fill="currentColor" stroke="none" opacity=".55"/><path d="M8 4.4c.9 0 1.7.3 2.3.9l1.7-1.7C10.9 2.7 9.6 2 8 2 5.5 2 3.5 3.4 2.5 5.3l2.1 1.6C5.1 5.4 6.4 4.4 8 4.4z" fill="currentColor" stroke="none" opacity=".7"/>`,
 github:`<path d="M8 1.5a6.5 6.5 0 0 0-2 12.7c.3.05.4-.15.4-.3v-1.1c-1.8.4-2.2-.8-2.2-.8-.3-.75-.7-.95-.7-.95-.6-.4 0-.4 0-.4.65.05 1 .7 1 .7.6 1 1.55.7 1.9.55.05-.45.25-.75.4-.9-1.4-.15-2.9-.7-2.9-3.1 0-.7.25-1.25.65-1.7-.05-.15-.3-.8.05-1.65 0 0 .55-.15 1.75.65a6 6 0 0 1 3.2 0c1.2-.8 1.75-.65 1.75-.65.35.85.1 1.5.05 1.65.4.45.65 1 .65 1.7 0 2.4-1.5 2.95-2.9 3.1.25.2.45.6.45 1.2v1.8c0 .15.1.35.4.3A6.5 6.5 0 0 0 8 1.5z" fill="currentColor" stroke="none"/>`,
 email:`<rect x="2" y="4" width="12" height="8" rx="1.5" ${S}/><path d="M2.5 5l5.5 3.7L13.5 5" ${S}/>`,
 lock:`<rect x="3.5" y="7" width="9" height="6" rx="1.3" ${S}/><path d="M5.5 7V5.3a2.5 2.5 0 0 1 5 0V7" ${S}/>`,
 textbox:`<rect x="2" y="5" width="12" height="6" rx="1.3" ${S}/><path d="M5 8h4" ${S}/>`,
 person:`<circle cx="8" cy="5.5" r="2.4" ${S}/><path d="M3.5 13c0-2.6 9-2.6 9 0" ${S}/>`,
 cookie:`<circle cx="8" cy="8" r="6" ${S}/><circle cx="6" cy="6.3" r=".9" fill="currentColor" stroke="none"/><circle cx="10" cy="7.3" r=".9" fill="currentColor" stroke="none"/><circle cx="7.3" cy="10.2" r=".9" fill="currentColor" stroke="none"/>`,
 check:`<rect x="2.5" y="2.5" width="11" height="11" rx="2.5" ${S}/><path d="M5.3 8l2 2 3.4-4" ${S} stroke-width="1.7"/>`,
 search:`<circle cx="7" cy="7" r="4" ${S}/><path d="M10 10l3.5 3.5" ${S} stroke-width="1.7"/>`,
 org:`<rect x="3" y="4" width="10" height="9" rx="1" ${S}/><path d="M6 7h1M9 7h1M6 9.5h1M9 9.5h1M6 12v-1.5h4V12" ${S}/>`,
 doc:`<path d="M4.5 2h5L13 5.5V13a1 1 0 0 1-1 1H4.5a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" ${S}/><path d="M9 2v3.5h4" ${S}/>`,
 swap:`<path d="M4 5h7M9 3l2.5 2L9 7M12 11H5M7 9l-2.5 2L7 13" ${S}/>`,
 wall:`<rect x="2.5" y="7.5" width="11" height="6" rx="1" ${S}/><path d="M5 7.5V5.5a3 3 0 0 1 6 0v2" ${S}/>`,
 write:`<path d="M10.5 3.2l2.3 2.3-7.1 7.1-2.6.3.3-2.6z" ${S}/><path d="M9.6 4.1l2.3 2.3" ${S}/>`,
 password:`<path d="M8 3.2v9.6M8 3.2l3.6 1.6M8 3.2L4.4 4.8M8 12.8l3.6-1.6M8 12.8l-3.6-1.6M4.4 4.8v6.4M11.6 4.8v6.4" ${S}/><circle cx="8" cy="8" r="1.3" fill="currentColor" stroke="none"/>`,
 account:`<rect x="2.5" y="3.5" width="11" height="9" rx="1.6" ${S}/><circle cx="6" cy="7.3" r="1.5" ${S}/><path d="M3.8 11c0-1.6 4.4-1.6 4.4 0M10 6.5h2.3M10 8.6h2.3" ${S}/>`};
const svg=b=>`<svg viewBox="0 0 16 16" aria-hidden="true">${b}</svg>`;
// pick a specific icon from the line text; fall back to the kind icon
function pickIcon(s){
 const t=((s.stage||'')+' '+(s.outcome||'')+' '+(s.detail||'')).toLowerCase();
 if(s.kind==='key')return ICON.key;
 if(s.kind==='err')return ICON.err;
 if(/google/.test(t))return ICON.google;
 if(/github/.test(t))return ICON.github;
 if(/another account|account|chooser|switch/.test(t))return ICON.account;
 if(/password/.test(t))return ICON.password;
 if(/email|verify|inbox/.test(t))return ICON.email;
 if(/organi|team|company|workspace/.test(t))return ICON.org;
 if(/consent|terms|checkbox|tick/.test(t))return ICON.check;
 if(/name/.test(t))return ICON.person;
 if(/cookie/.test(t))return ICON.cookie;
 if(/find signup|search|entry/.test(t))return ICON.search;
 if(/open page|page opened|dashboard|landed/.test(t))return ICON.globe;
 if(/type|write|digito|fill/.test(t))return ICON.write;
 if(/form|submit/.test(t))return ICON.textbox;
 if(/wall|card|blocked|refused|phone/.test(t))return ICON.wall;
 if(s.kind==='ai')return ICON.ai;
 if(s.kind==='warn')return ICON.warn;
 if(s.kind==='skip')return ICON.skip;
 return ICON.ok;
}
const $=s=>document.querySelector(s);
const spineEl=$('#spine'),logEl=$('#log'),prEl=$('#pr'),vEl=$('#verdict'),pill=$('#pill');
const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
let sel=0,timers=[];
function ic(k){return svg(ICON[k]||ICON.ok)}
function col(k){return COL[k]||COL.info}
// one distinct icon per backbone stage
const NODE_ICON={OPEN:'globe',COOKIE:'cookie',ENTRY:'search',LOGIN:'google',FORM:'textbox',
 VERIFY:'email',ONBOARD:'skip',KEY:'key',AI:'ai',DONE:'ok'};
function buildSpine(){
 spineEl.innerHTML='';window.NODE={};
 SPINE.forEach(([id,label])=>{const n=document.createElement('div');n.className='node';
  const ik=NODE_ICON[id]||'ok';
  n.innerHTML=`<span class="dot">${svg(ICON[ik]||ICON.ok)}</span><span class="lbl">${label}</span>`;
  spineEl.appendChild(n);window.NODE[id]=n;});
}
function clearAll(){timers.forEach(clearTimeout);timers=[];logEl.innerHTML='';vEl.className='verdict';vEl.innerHTML='';
 Object.values(window.NODE||{}).forEach(n=>n.className='node');}
function lightNode(id,kind){const n=window.NODE[id];if(!n)return;n.style.setProperty('--c',col(kind));
 n.classList.add('on','pulse');setTimeout(()=>n.classList.remove('pulse'),700);}
function addLine(s,i,last){const c=col(s.kind);
 const det=s.detail?` <span class="det">— ${esc(s.detail)}</span>`:'';
 const row=document.createElement('div');
 row.className='ln'+(s.kind==='warn'?' warnrow':'')+(s.kind==='err'?' errrow':'');
 row.style.setProperty('--c',c);
 row.innerHTML=`<span class="ic">${svg(pickIcon(s))}</span><span class="tx"><span class="stg">${esc(s.stage)}</span> · ${esc(s.outcome)}${det}${last?'':' <span class="cursor"></span>'}</span>`;
 const prev=logEl.querySelector('.cursor');if(prev)prev.remove();
 logEl.appendChild(row);logEl.scrollTop=logEl.scrollHeight;
 if(s.node)lightNode(s.node,s.kind);prEl.textContent=`${i+1} / ${cur().steps.length}`;}
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')}
function cur(){return DATA[sel]||{name:'—',steps:[]}}
function finish(){const st=cur().steps;const last=st[st.length-1];
 const ok=st.some(s=>s.kind==='key');
 vEl.innerHTML=ok?`<span class="badge yes">${svg(ICON.key)} Key obtained</span><span class="vtext">saved to out/keys.txt</span>`
  :`<span class="badge no">${svg(ICON.err)} No key this run</span><span class="vtext">${esc((last&&last.detail)||(last&&last.outcome)||'walled')}</span>`;
 vEl.classList.add('show');}
function play(force){clearAll();const st=cur().steps;pill.textContent=cur().name;
 if(!st.length){logEl.innerHTML='<div class="empty">No steps recorded yet — run a farm first.</div>';return;}
 // autoplay respects reduced-motion / live mode (dump static); the Replay button forces animation.
 if(!force&&(reduce||!ANIM)){st.forEach((s,i)=>addLine(s,i,i===st.length-1));finish();return;}
 const step=560;
 st.forEach((s,i)=>{timers.push(setTimeout(()=>{addLine(s,i,i===st.length-1);
  if(i===st.length-1)timers.push(setTimeout(finish,480));},i*step));});}
function skip(){clearAll();const st=cur().steps;pill.textContent=cur().name;
 st.forEach((s,i)=>addLine(s,i,i===st.length-1));finish();}
function buildTabs(){const t=$('#tabs');if(DATA.length<2){t.style.display='none';return;}
 t.innerHTML='';DATA.forEach((d,i)=>{const b=document.createElement('button');
  b.className='tab'+(i===sel?' sel':'');b.textContent=d.name;
  b.onclick=()=>{sel=i;[...t.children].forEach((c,j)=>c.classList.toggle('sel',j===i));play();};
  t.appendChild(b);});}
$('#replay').onclick=()=>play(true);$('#skip').onclick=skip;
const LEG=[['ok','done'],['skip','skipped'],['ai','AI fallback'],['warn','warning'],['err','error'],['key','key']];
$('#legend').innerHTML=LEG.map(([k,l])=>`<span><i style="background:${col(k)}"></i>${l}</span>`).join('');
buildSpine();buildTabs();
if(!DATA.length){logEl.innerHTML='<div class="empty">No run yet — run <b>python run.py &lt;Site&gt;</b> then reload.</div>';pill.textContent='no data';}
else play();
</script></body></html>"""


if __name__ == "__main__":
    render()
