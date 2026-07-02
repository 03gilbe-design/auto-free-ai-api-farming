"""Offline regression: nav bars used to render as ONE flat line ('||| A · B · C') with no way
to target an individual item. The AI couldn't precisely click "API Keys" in a nav bar and guessed
a nearby ref instead, repeatedly clicking the wrong link (found live on Cohere's dashboard nav,
right after reaching it for the first time — furthest any run got before this fix). Each nav
item now gets its own {ref:eN}, still on one compact line.

No live browser account, no AI call — pure DOM fixture + page2text + _exec.
Uso: py -3.11 -X utf8 test_nav_refs.py
"""
from __future__ import annotations
import asyncio, re
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer import ai_fallback, page2text

FIX = (Path(__file__).parent / "fixtures" / "nav_bar.html").resolve().as_uri()


async def main():
    ok = True
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        page = await br.new_page()
        await page.goto(FIX)
        txt = await page2text.page_to_text(page)

        check1 = "|||" in txt and "Dashboard" in txt and "API Keys" in txt
        print(f"  {'PASS' if check1 else 'FAIL'}  nav still one compact line -> "
              f"{[l for l in txt.splitlines() if l.startswith('|||')]}")
        ok = ok and check1

        m = re.search(r"API Keys\s*\{ref:(e\d+)\}", txt)
        check2 = bool(m)
        print(f"  {'PASS' if check2 else 'FAIL'}  'API Keys' has its OWN ref -> {m.group(1) if m else None}")
        ok = ok and check2

        if m:
            # confirm the ref really resolves to the #apikeys anchor specifically, not a
            # neighbor (data-af-ref is unique per element -> zero ambiguity by construction)
            resolved_id = await page.locator(f"[data-af-ref='{m.group(1)}']").get_attribute("id")
            check3 = resolved_id == "apikeys"
            print(f"  {'PASS' if check3 else 'FAIL'}  ref resolves to the RIGHT anchor (#apikeys) -> {resolved_id!r}")
            ok = ok and check3

            el = await ai_fallback._exec(page, {"action": "click", "text": "API Keys", "ref": m.group(1)})
            check4 = el == "button"
            print(f"  {'PASS' if check4 else 'FAIL'}  click by nav-item ref executes -> {el!r}")
            ok = ok and check4

        await br.close()
    print("\n=== NAV REFS TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
