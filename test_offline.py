"""TEST OFFLINE: carica una pagina-fixture LOCALE (file://) con Playwright HEADLESS e verifica
che i moduli di RICONOSCIMENTO (clickables + scoring) la processino correttamente — SENZA sito
live, SENZA login, SENZA immagini. Dimostra l'idea 'siti in locale' dell'utente.

Cosa prova: il codice TROVA i candidati giusti e scarta le trappole (API Reference) sulla base
del DOM statico salvato. Le interazioni (click che aprono pannelli via JS) NON si testano offline,
ma il riconoscimento — la parte fragile — SI.

Uso: py -3.11 -X utf8 test_offline.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import grabkey

FIX = (Path(__file__).parent / "fixtures" / "ai21_like.html").resolve().as_uri()


async def main():
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)   # headless: niente finestra, niente immagini
        page = await br.new_page()
        await page.goto(FIX)
        items = await grabkey._clickables(page)
        print(f"clickables trovati: {len(items)}")
        print("--- scoring (deterministico, spiegabile) ---")
        for it in items:
            sc = grabkey._keyarea_score(it["text"])
            mark = "  <- candidato" if sc > 0 else ""
            print(f"  score {sc}  {it['text']!r}{mark}")
        # verifica le aspettative
        scores = {it["text"]: grabkey._keyarea_score(it["text"]) for it in items}
        ok = True
        checks = [
            ("API Reference scartata (trappola)", scores.get("API Reference", 0) == 0),
            ("API Keys forte", scores.get("API Keys", 0) >= 4),
            ("Create new key forte", scores.get("Create new key", 0) >= 4),
            ("Settings = percorso", scores.get("Settings", 0) == 2),
            ("Docs/Jamba ignorati", scores.get("Docs", 0) == 0 and scores.get("Jamba", 0) == 0),
        ]
        print("--- verifiche ---")
        for name, passed in checks:
            print(f"  {'PASS' if passed else 'FAIL'}  {name}")
            ok = ok and passed
        await br.close()
        print("\n=== OFFLINE TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")


if __name__ == "__main__":
    asyncio.run(main())
