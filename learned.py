"""Auto-apprendimento dai successi dell'AI fallback.

Quando l'AI risolve un passo (click/fill che fa AVANZARE la pagina), lo registriamo come
"ricetta" deterministica: (sito, punto-nella-mappa, tipo-elemento, testo/selettore). La volta
dopo il codice RIPROVA la ricetta da solo PRIMA di chiamare Groq -> meno usage AI, piu' robusto.

Ricetta = {
  "phase":   punto nella mappa (path URL, es. 'dashboard.cohere.com/api-keys'),
  "goal":    tag del goal in corso (es. 'apikey'),
  "el_type": "textbox" | "button" | "link" | "nav",   # elemento gia' visto
  "action":  {...}   # azione esatta da rieseguire (stesso formato di ai_fallback._exec)
}
Store: out/learned_actions.json  ->  { "<Sito>": [ricetta, ...] }
"""
from __future__ import annotations
import json, os
from pathlib import Path
from urllib.parse import urlparse

_STORE = Path(__file__).parent / "out" / "learned_actions.json"


def _path_sig(url: str) -> str:
    """Punto-nella-mappa stabile: host+path, senza query/fragment (che cambiano ogni volta)."""
    try:
        u = urlparse(url)
        return (u.netloc + u.path).rstrip("/").lower()
    except Exception:
        return (url or "").lower()


def _goal_tag(goal: str) -> str:
    g = (goal or "").lower()
    if "api key" in g or "apikey" in g or "chiave" in g:
        return "apikey"
    if "registr" in g or "sign" in g or "accedi" in g or "google" in g:
        return "login"
    if "email" in g or "verifica" in g:
        return "verify"
    return "other"


def _load() -> dict:
    try:
        return json.loads(_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(d: dict) -> None:
    try:
        _STORE.parent.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _key(r: dict) -> tuple:
    """Identita' ricetta per dedup: (phase, el_type, testo-o-selettore azione)."""
    a = r.get("action", {})
    sig = a.get("text") or a.get("placeholder") or a.get("selector") or a.get("url") or ""
    return (r.get("phase", ""), r.get("el_type", ""), a.get("action", ""), sig.lower())


def record(site: str, url: str, goal: str, action: dict, el_type: str) -> None:
    """Salva una ricetta riuscita. Dedup: non duplica la stessa (phase, elemento, azione).
    Mette in cima le piu' utili? No -> ordine di scoperta, ma la piu' recente vince nel replay."""
    if not site or not action:
        return
    r = {"phase": _path_sig(url), "goal": _goal_tag(goal), "el_type": el_type, "action": action}
    d = _load()
    lst = d.setdefault(site, [])
    k = _key(r)
    lst = [x for x in lst if _key(x) != k]   # rimuovi vecchia identica -> tieni la nuova
    lst.append(r)
    d[site] = lst[-40:]                       # cap per sito
    _save(d)


def suggest(site: str, url: str, goal: str = "") -> list[dict]:
    """Ricette da riprovare ORA: stesso sito + stesso punto-mappa (path). Se combacia anche il
    goal, prima quelle; poi le altre dello stesso path. Ordine: piu' recenti prima."""
    d = _load()
    lst = d.get(site, [])
    sig = _path_sig(url)
    gt = _goal_tag(goal)
    same_path = [r for r in lst if r.get("phase") == sig]
    same_path.reverse()   # recenti prima
    pri = [r for r in same_path if r.get("goal") == gt]
    rest = [r for r in same_path if r.get("goal") != gt]
    # dedup mantenendo ordine
    out, seen = [], set()
    for r in pri + rest:
        k = _key(r)
        if k not in seen:
            seen.add(k); out.append(r)
    return out
