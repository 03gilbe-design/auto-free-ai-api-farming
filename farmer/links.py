"""Trova e clicca link deterministico per intento: signup | signin | apikeys.

Scoring su href + testo visibile. Esclude trappole (play.google.com, social, footer legal).
Header/nav-first. Ritorna True se ha navigato, False se gia sulla pagina giusta, None se non trovato.
"""
from __future__ import annotations
import re

_INTENT = {
    "signup":  {"href": ["sign-up", "signup", "register", "join", "create-account", "get-started", "getstarted", "/start"],
                "text": ["sign up", "signup", "register", "registr", "get started", "create account", "crea account", "iscriviti", "join", "try free", "start free"]},
    "signin":  {"href": ["sign-in", "signin", "login", "log-in", "auth", "/account"],
                "text": ["sign in", "signin", "log in", "login", "accedi", "accesso", "entra",
                         # icone Material ricorrenti (JinaAI: il login e' un'icona 'person'/'account')
                         "person", "account_circle", "login", "vpn_key"]},
    "apikeys": {"href": ["api-key", "apikey", "api_key", "/keys", "/tokens", "token", "developer", "settings/api"],
                "text": ["api key", "api keys", "chiavi api", "tokens", "developer", "dashboard", "credentials", "manage keys"]},
}
_TRAP_HREF = ["play.google.com", "apps.apple.com", "twitter.com", "x.com", "facebook.com",
              "linkedin.com", "youtube.com", "instagram.com", "/privacy", "/terms", "/legal", "/cookie"]


_SEL = "a, button, [role=button], [role=link]"
_JS_CANDS = r"""
() => {
  const sel = 'a, button, [role=button], [role=link]';
  const els = document.querySelectorAll(sel);
  const out = [];
  els.forEach((el, i) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || s.visibility === 'hidden' || s.display === 'none') return;
    const txt = (el.innerText || el.textContent || '').trim().replace(/\s+/g,' ').slice(0,60).toLowerCase();
    const href = (el.getAttribute('href') || '').toLowerCase();
    out.push({i, href, txt});
  });
  return out;
}
"""


async def _candidates(page):
    """[(href, text, index)] sui clickable visibili — un solo evaluate."""
    try:
        rows = await page.evaluate(_JS_CANDS)
    except Exception:
        return []
    return [(r["href"], r["txt"], r["i"]) for r in rows]


def _score(href, txt, intent) -> int:
    if any(tr in href for tr in _TRAP_HREF):
        return -100
    sc = 0
    cfg = _INTENT[intent]
    for h in cfg["href"]:
        if h in href:
            sc += 5
    for t in cfg["text"]:
        if t in txt:
            sc += 4
    # esatto corto premia (es "Sign in") vs frase lunga
    if txt in cfg["text"]:
        sc += 2
    return sc


async def _already_on(page, intent) -> bool:
    # solo path-tail + query (evita falsi positivi dal dominio/dir, es "signup_kit")
    from urllib.parse import urlparse
    u = urlparse(page.url.lower())
    tail = (u.path.rsplit("/", 1)[-1] + "?" + (u.query or ""))
    return any(h.strip("/") in tail for h in _INTENT[intent]["href"])


async def find_and_click(page, intent: str, log=None, dry: bool = False):
    if await _already_on(page, intent):
        if log: log.step("ENTRY", "gia sulla pagina", intent, "skip")
        return False
    cands = await _candidates(page)
    best, best_sc = None, 0
    for href, txt, idx in cands:
        sc = _score(href, txt, intent)
        if sc > best_sc:
            best, best_sc = (href, txt, idx), sc
    if not best or best_sc < 4:
        if log: log.step("ENTRY", "link non trovato", intent, "ai")
        return None
    href, txt, idx = best
    if dry:
        return {"intent": intent, "href": href, "text": txt, "score": best_sc}
    el = page.locator(_SEL).nth(idx)
    try:
        await el.click(timeout=3000)
        await page.wait_for_load_state("domcontentloaded", timeout=8000)
        if log: log.step("ENTRY", "click", f"{intent}: '{txt or href}'", "ok")
        return True
    except Exception as e:
        if log: log.err("ENTRY", e)
        return None
