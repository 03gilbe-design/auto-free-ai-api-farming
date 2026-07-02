"""Generates out/path.html: a visual tree of the path taken through each site.

Left: the fixed backbone of stages (green = visited, gray = skipped). Right: the
detailed step-by-step history, colored by outcome. No emoji, SVG icons only.
Readable on mobile too.

Usage: python path_viewer.py   (run after a farming run)
"""
from __future__ import annotations
import json, html
from pathlib import Path
from collections import OrderedDict

OUT = Path(__file__).parent.parent / "out"
JSONL = OUT / "debug.jsonl"
HTMLF = OUT / "path.html"

# Spina dorsale = tappe fisse dell'albero, in ordine. Etichette in italiano chiaro,
# senza sigle interne ne underscore. (codice tecnico -> nome leggibile)
SPINE = [
    ("COOKIE",  "Cookie banner"),
    ("ENTRY",   "Find signup"),
    ("GOOGLE",  "Google login"),
    ("FORM",    "Email/password form"),
    ("VERIFY",  "Email verification"),
    ("ONBOARD", "Skip onboarding"),
    ("KEY",     "Find/generate key"),
    ("AI",      "AI fallback"),
    ("DONE",    "Final outcome"),
]

# colori per esito di una riga
_COL = {"ok": "#36d399", "skip": "#7a8aa0", "ai": "#c084fc", "warn": "#fbbf24",
        "err": "#f87171", "key": "#22d3ee", "info": "#9aa7b8", "wait": "#fbbf24",
        "captcha": "#fb7185"}

# nome leggibile per ogni tappa tecnica (usato nella cronologia di destra)
_STAGE_EN = {
    "COOKIE": "Cookie banner", "ENTRY": "Find signup", "GOOGLE": "Google login",
    "FORM": "Email/password form", "VERIFY": "Email verification", "ONBOARD": "Skip onboarding",
    "KEY": "API key", "AI": "AI fallback", "DONE": "Outcome", "GOTO": "Open page",
    "GOOGLE-": "Google login", "KEY-NAV": "Go to key page", "RUN": "Run",
    "RESULT": "Result", "SKIP": "Skipped",
}

# Icone SVG (16x16, currentColor) per ogni tipo di esito. Niente emoji.
_SVG = {
    "ok":      '<path d="M3 8.5l3.2 3.2L13 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "key":     '<circle cx="6" cy="6" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M8.3 8.3L13 13m-2-2l1.4-1.4M9.6 9.6L11 11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    "skip":    '<path d="M4 4l5 4-5 4zM10 4v8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>',
    "ai":      '<rect x="3.5" y="5" width="9" height="7" rx="1.6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 2.5V5M5.5 8.5h.01M10.5 8.5h.01" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    "warn":    '<path d="M8 2.5L14.5 13.5H1.5z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 6.5v3M8 11.5h.01" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    "err":     '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    "wait":    '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    "captcha": '<rect x="2.5" y="4" width="11" height="8" rx="1.4" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M5 8h6M5 10h4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
    "info":    '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 7v3.5M8 4.8h.01" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
}
# freccia-marcatore a sinistra di ogni riga della cronologia
_ARROW = '<path d="M3 8h8M8 4.5L11.5 8 8 11.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
# pallino di tappa (spina): vuoto = saltata, pieno con spunta = attraversata
_DOT_HIT = '<circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="M5 8.2l2 2L11 5.6" fill="none" stroke="#0e1726" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
_DOT_MISS = '<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/>'
# albero (titolo)
_TREE = '<path d="M10 17v-4M10 13L6 9M10 11l4-3" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round"/><circle cx="10" cy="6" r="3.5" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="5" cy="9" r="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="15" cy="8" r="2.2" fill="none" stroke="currentColor" stroke-width="1.6"/>'


def _svg(name, size=15, cls=""):
    body = _SVG.get(name, _SVG["info"])
    c = f' class="{cls}"' if cls else ""
    return (f'<svg{c} width="{size}" height="{size}" viewBox="0 0 16 16" '
            f'aria-hidden="true" style="flex:0 0 auto;vertical-align:middle">{body}</svg>')


def _icon_raw(body, size=15, cls=""):
    c = f' class="{cls}"' if cls else ""
    return (f'<svg{c} width="{size}" height="{size}" viewBox="0 0 16 16" '
            f'aria-hidden="true" style="flex:0 0 auto;vertical-align:middle">{body}</svg>')


def _stage_en(code):
    return _STAGE_EN.get((code or "").upper(), (code or "").capitalize())


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


def _esc(s):
    return html.escape(str(s or ""))


def render(live: bool = False):
    """Render out/path.html from the run's debug.jsonl.
    live=True adds a 1.5s auto-refresh meta tag so the tree colors in as the run progresses
    (used by run.py while a run is in flight). Static exports leave it off."""
    sites = _load()
    refresh = '<meta http-equiv="refresh" content="1.5">' if live else ''
    parts = ["""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
""" + refresh + """
<title>Signup path tree — auto-free-ai-api-farming</title><style>
*{box-sizing:border-box}
body{margin:0;background:#0e1726;color:#e6edf6;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;padding:16px}
h1{font-size:20px;margin:0 0 4px;display:flex;gap:8px;align-items:center}
.sub{color:#7a8aa0;margin:0 0 18px;font-size:13px}
.legend{display:flex;flex-wrap:wrap;gap:14px;margin:0 0 18px;font-size:12.5px;color:#aeb9c9}
.legend span{display:flex;gap:5px;align-items:center}
.site{background:#16213a;border:1px solid #243352;border-radius:14px;padding:14px;margin:0 0 18px}
.site h2{font-size:16px;margin:0 0 12px;display:flex;gap:9px;align-items:center}
.badge{font-size:12px;padding:3px 10px;border-radius:20px;font-weight:700;display:flex;gap:5px;align-items:center;color:#0e1726}
.grid{display:grid;grid-template-columns:210px 1fr;gap:18px}
.spine{display:flex;flex-direction:column;gap:5px;position:relative}
.node{display:flex;gap:9px;align-items:center;font-size:13px;padding:6px 9px;border-radius:9px;border:1px solid #243352;color:#5b6b82}
.node .ico{color:#5b6b82}
.node.hit{color:#cfeede;border-color:#2c6b4f;background:#13312a}
.node.hit .ico{color:#36d399}
.tl{display:flex;flex-direction:column;gap:5px}
.row{display:grid;grid-template-columns:18px 16px 1fr;gap:9px;align-items:start;font-size:13.5px;padding:5px 8px;border-radius:8px;background:#10192c}
.row .arr{color:#5b6b82;margin-top:1px}
.row .ico{margin-top:1px}
.row .body{min-width:0}
.row .stg{font-weight:700;color:#cdd7e4}
.row .det{color:#9aa7b8}
.note{color:#7a8aa0;font-size:12px;margin-top:10px}
@media(max-width:600px){.grid{grid-template-columns:1fr}.spine{flex-direction:row;flex-wrap:wrap}.spine .node{flex:1 1 auto}}
</style></head><body>"""]

    parts.append(f'<h1>{_icon_raw(_TREE, 22)} Signup path tree</h1>')
    parts.append('<p class="sub">Stages followed for each site. Left: the fixed map '
                 '(green = visited, gray = skipped). Right: the step-by-step history, '
                 'one arrow per action. Generated from out/debug.jsonl.</p>')

    # legenda colori/icone
    parts.append('<div class="legend">')
    leg = [("ok", "success"), ("skip", "skipped"), ("ai", "AI fallback"),
           ("wait", "waiting"), ("warn", "warning"), ("err", "error"), ("key", "key")]
    for k, lab in leg:
        col = _COL.get(k, "#9aa7b8")
        parts.append(f'<span style="color:{col}">{_svg(k, 14)}</span>'
                     .replace("</span>", f' <span style="color:#aeb9c9">{lab}</span></span>'))
    parts.append('</div>')

    if not sites or not any(sites.values()):
        parts.append('<p class="note">No data yet: run a farming session or the demo first.</p></body></html>')
        HTMLF.write_text("\n".join(parts), encoding="utf-8")
        print(f"scritto {HTMLF}  (0 siti)")
        return

    for site, steps in sites.items():
        if not steps:
            continue
        hit_stages = {s.get("stage") for s in steps}
        last = steps[-1]
        ok = last.get("stage") == "DONE" and last.get("kind") == "key"
        if ok:
            bcol, bk, btxt = "#36d399", "key", "Key obtained"
        elif last.get("stage") == "DONE":
            bcol, bk, btxt = "#f87171", "err", "No key"
        else:
            bcol, bk, btxt = "#fbbf24", "warn", "Incomplete"

        parts.append(f'<div class="site"><h2>{_esc(site)} '
                     f'<span class="badge" style="background:{bcol}">{_svg(bk, 13)}{btxt}</span></h2>')
        parts.append('<div class="grid"><div class="spine">')
        for code, label in SPINE:
            hit = code in hit_stages
            dot = _icon_raw(_DOT_HIT if hit else _DOT_MISS, 16, "ico")
            parts.append(f'<div class="node{" hit" if hit else ""}">{dot}'
                         f'<span>{_esc(label)}</span></div>')
        parts.append('</div><div class="tl">')
        for s in steps:
            k = s.get("kind", "info")
            col = _COL.get(k, "#9aa7b8")
            det = (f'<span class="det"> — {_esc(s.get("detail"))}</span>'
                   if s.get("detail") else "")
            parts.append(
                f'<div class="row" style="border-left:3px solid {col}">'
                f'<span class="arr" style="color:{col}">{_icon_raw(_ARROW, 14)}</span>'
                f'<span class="ico" style="color:{col}">{_svg(k, 14)}</span>'
                f'<span class="body"><span class="stg">{_esc(_stage_en(s.get("stage")))}</span>: '
                f'{_esc(s.get("outcome"))}{det}</span></div>')
        parts.append('</div></div></div>')

    parts.append("</body></html>")
    HTMLF.write_text("\n".join(parts), encoding="utf-8")
    print(f"scritto {HTMLF}  ({sum(1 for v in sites.values() if v)} siti)")


if __name__ == "__main__":
    render()
