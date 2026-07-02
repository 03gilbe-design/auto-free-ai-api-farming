"""Regressione permanente OFFLINE: gira il riconoscimento su TUTTE le fixture/real e verifica
le aspettative note. Fallisce (exit 1) se un fix futuro rompe un riconoscimento gia' funzionante.
Zero usage, zero browser live. Lanciare dopo OGNI modifica a grabkey/google_oauth/tree.

Uso: py -3.11 -X utf8 test_regression.py
"""
from __future__ import annotations
import asyncio, sys
from pathlib import Path
from playwright.async_api import async_playwright
import google_oauth, grabkey

REAL = Path(__file__).parent / "fixtures" / "real"

# aspettative VERIFICATE (lo stato buono noto). Se cambia -> regressione.
EXPECT = {
    "groq_login":        {"google": True},
    "cohere_login":      {"google": True},
    "openrouter_signup": {"google": True},   # img-button fix
    "apifreellm":        {"google": True, "key": True},
    "deepinfra":         {"google": True},
    "githubmodels":      {"google": True},
    "publicai":          {"key": True},      # landing mostra API key
    "nebius":            {"key": True},
    "togetherai":        {"google": True},
    "nebius_auth":       {"google": True},   # data-qa button fix   # caricata via wait_until=commit
    # hyperbolic ESCLUSO: lazy-render non deterministico offline (a volte 0 bottoni) -> non guardia.
}


async def _detect(page):
    goog = any([await page.locator(s).first.count() for s in google_oauth._BTN_SEL])
    if not goog:
        for t in google_oauth._BTN_TEXT:
            if await page.locator(f":text-matches('{t}','i')").count():
                goog = True; break
    items = await grabkey._clickables(page)
    has_key = any(grabkey._keyarea_score(it["text"]) >= 4 for it in items)
    return goog, has_key


async def main():
    fails = []
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        for name, exp in EXPECT.items():
            fp = REAL / f"{name}.html"
            if not fp.exists():
                fails.append(f"{name}: fixture MANCA"); continue
            page = await br.new_page()
            try:
                await page.goto(fp.resolve().as_uri(), wait_until="commit", timeout=8000)
                await page.wait_for_timeout(600)
                goog, key = await _detect(page)
                if exp.get("google") and not goog:
                    fails.append(f"{name}: Google NON rilevato (regressione!)")
                if exp.get("key") and not key:
                    fails.append(f"{name}: key-area NON rilevata (regressione!)")
            except Exception as e:
                fails.append(f"{name}: ERR {str(e)[:40]}")
            finally:
                await page.close()
        await br.close()
    if fails:
        print("REGRESSIONE:")
        for f in fails: print("  FAIL", f)
        sys.exit(1)
    print(f"OK - {len(EXPECT)} fixture, nessuna regressione")


if __name__ == "__main__":
    asyncio.run(main())
