"""Gira il RICONOSCIMENTO del nostro codice sugli HTML REALI scaricati (fixtures/real/), OFFLINE.
Prova che 'il codice funziona su robe gia funzionanti': carica la pagina vera salvata con file://
(headless, no login, no immagini) e verifica che trovi i bottoni OAuth / le voci chiave.

Uso: py -3.11 -X utf8 test_real_offline.py
"""
from __future__ import annotations
import asyncio, re
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer import grabkey, google_oauth, github_oauth

REAL = Path(__file__).parent / "fixtures" / "real"


async def main():
    files = sorted(REAL.glob("*.html"))
    if not files:
        print("Nessuna fixture reale. Esegui prima download_pages.py")
        return
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        for f in files:
            page = await br.new_page()
            # blocca JS-navigazione: alcune fixture salvate hanno script che tentano redirect al
            # load -> goto va in timeout. wait_until='commit' = appena il DOM c'e', non aspetta i JS.
            try:
                await page.goto(f.resolve().as_uri(), wait_until="commit", timeout=8000)
            except Exception:
                pass
            await page.wait_for_timeout(300)
            # 1) rilevazione con la LOGICA VERA del codice (_BTN_SEL + _BTN_TEXT), non solo testo
            has_google = 0
            for s in google_oauth._BTN_SEL:
                try:
                    if await page.locator(s).first.count(): has_google = 1; break
                except Exception: pass
            if not has_google:
                for t in google_oauth._BTN_TEXT:
                    if await page.locator(f":text-matches('{t}','i')").count(): has_google = 1; break
            has_github = await page.locator(":text-matches('continue with github|sign in with github', 'i')").count()
            # 2) clickables + scoring (riconoscimento generale)
            items = await grabkey._clickables(page)
            top = sorted(((grabkey._keyarea_score(it["text"]), it["text"]) for it in items),
                         key=lambda x: -x[0])[:5]
            print(f"\n=== {f.name} ({len(items)} cliccabili) ===")
            print(f"  Google btn presente: {'SI' if has_google else 'no'} | GitHub: {'SI' if has_github else 'no'}")
            print(f"  top candidati key/login: " + ", ".join(f"{t}({s})" for s, t in top if s > 0) or "  (nessuno)")
            await page.close()
        await br.close()
    print("\n=== TEST REALE OFFLINE FINE ===")


if __name__ == "__main__":
    asyncio.run(main())
