"""Salva snapshot HTML degli STATI di un sito durante i run, per costruire la suite di test
OFFLINE ad albero (idea utente: non solo prima schermata, anche dopo login/onboard/chiavi).

- Un file per STATO: fixtures/snaps/<sito>/<stato>.html (es. arrivo, post_login, pagina_chiavi).
- SENZA LOOP: ogni stato si salva UNA volta per run (set in-memory). Se lo stato si ripete, skip.
- Zero costo extra: page.content() e' istantaneo, nessuna chiamata rete/AI.
- Disattivabile: salva solo se SIGNUP_SNAPSHOT=1 (default ON nei run, OFF in test).

Poi test_real_offline.py / un selftest possono girare il riconoscimento su questi HTML, offline.
"""
from __future__ import annotations
import hashlib, os, re
from pathlib import Path

ROOT = Path(__file__).parent / "fixtures" / "snaps"
_saved: set[str] = set()   # (sito/stato) gia' salvati in questo processo -> niente loop
_auto_hashes: set[str] = set()   # hash schermate gia' catturate (auto) -> niente doppioni
_auto_n = {"i": 0}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (s or "x").lower()).strip("_")[:40]


async def save(page, site: str, state: str, log=None) -> None:
    """Salva l'HTML corrente come fixtures/snaps/<site>/<state>.html (una volta per run)."""
    if os.environ.get("SIGNUP_SNAPSHOT", "1") == "0":
        return
    key = f"{_slug(site)}/{_slug(state)}"
    if key in _saved:
        return
    _saved.add(key)
    try:
        html = await page.content()
        d = ROOT / _slug(site)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_slug(state)}.html").write_text(html, encoding="utf-8")
        if log:
            log.dbg("snapshot salvato", site=site, state=state, bytes=len(html))
    except Exception as e:
        if log:
            log.dbg("snapshot fallito", err=str(e)[:80])


async def _capture_auto(page, site: str, log=None) -> None:
    """Salva la schermata CORRENTE in automatico, dedup per contenuto (no doppioni/loop)."""
    if os.environ.get("SIGNUP_SNAPSHOT", "1") == "0":
        return
    try:
        # DEDUP sul TESTO VISIBILE + URL (stabile: niente nonce/script che cambiano a ogni load).
        # Cosi' load+framenavigated multipli sulla stessa schermata = 1 sola cattura.
        try:
            vis = await page.inner_text("body")
        except Exception:
            vis = await page.content()
        sig = (page.url.split("?")[0] + "|" + re.sub(r"\s+", " ", vis)[:2000])
        h = hashlib.md5(sig.encode("utf-8", "replace")).hexdigest()[:12]
        if h in _auto_hashes:
            return   # schermata identica gia' catturata -> niente loop/doppioni
        _auto_hashes.add(h)
        html = await page.content()
        _auto_n["i"] += 1
        # nome = ordine + un pezzo di URL/host, per ritrovarla
        host = re.sub(r"^https?://", "", page.url or "").split("/")[0]
        d = ROOT / _slug(site) / "auto"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{_auto_n['i']:03d}_{_slug(host)}_{h}.html").write_text(html, encoding="utf-8")
        if log:
            log.dbg("auto-snapshot", n=_auto_n["i"], host=host, bytes=len(html))
    except Exception:
        pass


def attach_auto(ctx, site: str, log=None) -> None:
    """Installa UNA volta i listener che catturano OGNI schermata che si apre durante la
    navigazione (cambio pagina + popup nuovi). Dedup per contenuto -> niente loop/doppioni.
    Chiamare a inizio run, dopo aver il context."""
    if os.environ.get("SIGNUP_SNAPSHOT", "1") == "0":
        return
    import asyncio

    def _hook(page):
        def _on_nav(_frame=None):
            try:
                asyncio.create_task(_capture_auto(page, site, log))
            except Exception:
                pass
        page.on("load", lambda: _on_nav())
        page.on("framenavigated", _on_nav)

    # pagine gia' aperte + future (popup OAuth, nuove tab)
    for p in list(ctx.pages):
        _hook(p)
    ctx.on("page", _hook)
    if log:
        log.dbg("auto-snapshot attivo", site=site)
