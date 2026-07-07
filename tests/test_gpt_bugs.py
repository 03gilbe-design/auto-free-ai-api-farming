"""Fixture minime per i bug dell'audit GPT (handoff 2026-07-03): 1 cookies, 2 links,
3+5 grabkey docs-page. OFFLINE, zero usage. Uso: py -3.11 -X utf8 tests/test_gpt_bugs.py"""
from __future__ import annotations
import asyncio, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from playwright.async_api import async_playwright
from farmer import cookies, links, grabkey


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # BUG1: "Manage cookies" NON deve contare come dismiss
        await page.set_content("<div>We use cookies <button>Manage cookies</button></div>")
        assert not await cookies.dismiss(page), "BUG1: Manage cookies contato come dismiss"
        # controprova: un vero reject chiude
        await page.set_content("<div><button>Reject all</button></div>")
        assert await cookies.dismiss(page), "BUG1 controprova: Reject all non riconosciuto"

        # BUG2: "Dashboard" da solo non deve vincere per intent apikeys
        await page.set_content('<nav><a href="/dashboard">Dashboard</a></nav>')
        assert await links.find_and_click(page, "apikeys", dry=True) is None, \
            "BUG2: Dashboard scelto per apikeys"
        # controprova: link con segnale forte vince
        await page.set_content('<nav><a href="/settings/api-keys">API Keys</a></nav>')
        assert await links.find_and_click(page, "apikeys", dry=True) is not None, \
            "BUG2 controprova: API Keys non trovato"

        # BUG3: docs page non e' la zona chiavi
        await page.set_content("<main><h1>How to create API keys</h1><p>Read the guide.</p></main>")
        assert not await grabkey._is_key_area_now(page), "BUG3: docs page = key area"
        # controprova: dashboard vera con bottone
        await page.set_content("<main><button>Create API Key</button></main>")
        assert await grabkey._is_key_area_now(page), "BUG3 controprova: bottone vero non visto"

        # BUG5: link docs unico non va cliccato come opener
        await page.set_content('<main><a href="/docs">How to create API keys</a></main>')
        assert await grabkey._click_opener(page, grabkey._GEN_TEXT) is None, \
            "BUG5: docs phrase cliccata come opener"
        # controprova: bottone vero viene cliccato
        await page.set_content("<main><button>Create API Key</button></main>")
        assert await grabkey._click_opener(page, grabkey._GEN_TEXT) is not None, \
            "BUG5 controprova: opener vero non cliccato"

        await browser.close()
    print("test_gpt_bugs: PASS (bug 1,2,3,5 + controprove)")


if __name__ == "__main__":
    asyncio.run(main())
