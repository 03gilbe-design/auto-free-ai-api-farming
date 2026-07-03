"""Entry. Uso:
  py -3.11 -X utf8 run.py                 # tutti i siti, headed, profilo loggato
  py -3.11 -X utf8 run.py Cohere          # singolo sito (live)
  py -3.11 -X utf8 run.py --headless ...  # forza headless (debug)

Output: out/results.json (stato per sito) + out/trace.txt (step leggibili) + out/debug.jsonl (tutto).
Non interattivo: gira, salva, esce. Monitorabile da telefono leggendo out/trace.txt.
"""
from __future__ import annotations
import asyncio, json, os, sys, time
from pathlib import Path
from farmer.browser import Browser
from farmer.log import Log
from farmer.sites import SITES, site_cfg
from farmer import registry
from farmer import tree
from farmer import forms

OUT = Path(__file__).parent / "out"
RESULTS = OUT / "results.json"
KEYS_FILE = OUT / "keys.txt"   # key ottenute, CON l'account con cui sono state create
STOP = OUT / "STOP"  # crea questo file per fermare il run tra un sito e l'altro


def _save_key(provider: str, key: str, account: str):
    """Append della key con l'ACCOUNT con cui e' stata creata (l'utente lo vuole tracciato:
    la stessa key vale solo per quell'account/email)."""
    stamp = time.strftime("%Y-%m-%d %H:%M")
    line = f"{provider}\t{key}\taccount={account}\t{stamp}\n"
    with KEYS_FILE.open("a", encoding="utf-8") as f:
        f.write(line)


def _save_meta(provider: str, key: str, account: str, **meta):
    """Scrive metadati utili alla ripresa senza toccare il formato originale delle chiavi."""
    if not meta:
        return
    path = OUT / "meta.jsonl"
    stamp = time.strftime("%Y-%m-%d %H:%M")
    payload = {"provider": provider, "key": key[:12] + "…" if key else "", "account": account, "at": stamp}
    payload.update(meta)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _have_key(provider: str, account: str) -> bool:
    """Coppia (sito, account) gia in keys.txt? -> NON rifare lavoro gia fatto."""
    if not KEYS_FILE.exists():
        return False
    for ln in KEYS_FILE.read_text(encoding="utf-8").splitlines():
        p = ln.split("\t")
        if len(p) >= 3 and p[0] == provider and f"account={account}" in p[2]:
            return True
    return False


def _load():
    if RESULTS.exists():
        try:
            return json.loads(RESULTS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(d):
    RESULTS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


async def main():
    args = [a for a in sys.argv[1:]]
    headless = "--headless" in args
    args = [a for a in args if not a.startswith("--")]
    only = args[0] if args else None

    if not forms.EMAIL:
        raise RuntimeError(
            "SIGNUP_ACCOUNT is required for live runs (no placeholder fallback — set it via env "
            "var or the OS keyring so a run never proceeds silently against fake data).")

    targets = [site_cfg(only)] if only else [site_cfg(s["name"]) for s in SITES]
    results = _load()
    log = Log(reset=True)
    log.head(f"RUN {'1 sito: '+only if only else len(targets)} · headless={headless}")

    # MAPPA LIVE: apre out/path.html e la ri-genera ogni 1.5s in un thread, cosi' l'albero si
    # COLORA man mano che il run procede (la pagina si auto-ricarica). Stop con SIGNUP_NO_MAP=1.
    stop_live = _start_live_map()

    try:
        async with Browser(headless=headless, profile=True) as ctx:
            for site in targets:
                nm = site["name"]
                # stop manuale richiesto dall'utente: ci si ferma SOLO tra un sito e l'altro
                if STOP.exists():
                    log.step("STOP", "richiesto dall'utente", "interrompo (stato salvato)", "warn")
                    break
                # GIA FATTO per QUESTO account (sito+account in keys.txt) -> non rifare
                if _have_key(nm, forms.EMAIL):
                    log.step("SALTO", nm, f"gia presa per {forms.EMAIL}", "skip")
                    continue
                # NB (GPT bug 9): niente skip basato su results.json status=="ok" — non è
                # account-aware, un "ok" salvato da un altro account farebbe saltare il sito
                # anche per l'account corrente. _have_key() sopra è già la guardia giusta
                # (sito+account in keys.txt); se manca la chiave per QUESTO account, si rifà.
                # MURO esterno noto (dato in sites.json) -> skip CON MOTIVO, niente martellamento.
                if not registry.automatable(nm):
                    wall = registry.wall_of(nm)
                    log.step("MURO", nm, f"wall={wall} (non automatizzabile)", "warn")
                    results[nm] = {"status": "wall", "wall": wall,
                                   "provider": nm, "at": time.strftime("%Y-%m-%d %H:%M")}
                    _save(results)
                    continue
                lg = Log(nm)
                try:
                    res = await tree.run_site(ctx, site, lg)
                except Exception as e:
                    lg.err("RUN", e)
                    res = {"status": "error", "detail": str(e)[:120]}
                # traccia l'ACCOUNT con cui la key e' stata creata (richiesto dall'utente)
                res["account"] = forms.EMAIL
                res["provider"] = nm
                res["at"] = time.strftime("%Y-%m-%d %H:%M")
                results[nm] = res
                _save(results)
                if res.get("status") == "ok" and res.get("key"):
                    _save_key(nm, res["key"], forms.EMAIL)
                    _save_meta(nm, res["key"], forms.EMAIL, **{k: v for k, v in res.items() if k not in {"status", "key", "account", "provider", "at"}})

        ok = sum(1 for v in results.values() if v.get("status") == "ok")
        log.head(f"FINE · {ok}/{len(results)} key ottenute")
        for n, v in results.items():
            log.step("RESULT", n, v.get("status", "?") + (" " + v.get("key", "")[:14] if v.get("key") else ""), "key" if v.get("status") == "ok" else "info")
    finally:
        stop_live()          # ferma il thread della mappa live
        _render_map(live=False)   # render finale statico (albero completo, no auto-refresh)


def _path_viewer():
    sys.path.insert(0, str(Path(__file__).parent / "tools"))
    import path_viewer
    return path_viewer


def _render_map(live: bool):
    """Rigenera out/path.html dal debug.jsonl. live=True aggiunge l'auto-refresh (albero che
    si colora man mano). Riusa tools/path_viewer.render — nessuna logica duplicata."""
    try:
        _path_viewer().render(live=live)
    except Exception as e:
        print(f"(map render skipped: {e})")


def _open_map():
    html = OUT / "path.html"
    print(f"\nMap: {html}")
    try:
        os.startfile(str(html))          # Windows: apre nel browser di default
    except AttributeError:
        import webbrowser
        webbrowser.open(html.as_uri())   # macOS/Linux


def _start_live_map():
    """Apre subito la mappa (live) e la ri-genera ogni 1.5s in un thread finche' il run gira,
    cosi' l'albero si COLORA in tempo reale (la pagina si auto-ricarica). Ritorna una funzione
    stop(). Disattivabile con SIGNUP_NO_MAP=1 (in quel caso e' un no-op)."""
    if os.environ.get("SIGNUP_NO_MAP"):
        return lambda: None
    import threading, time as _t
    _render_map(live=True)   # prima versione, poi apri
    _open_map()
    stop = threading.Event()

    def loop():
        while not stop.wait(1.5):
            _render_map(live=True)
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    return stop.set


if __name__ == "__main__":
    asyncio.run(main())
