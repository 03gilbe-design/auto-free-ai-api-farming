"""Offline regression for the REPORT2_live_Groq bug: the AI reaches the real create-key
modal, but _exec() silently fails to click/fill because (a) it doesn't strip the page2text
decorators the AI copies verbatim ('[Close]' vs the real DOM text 'Close'), and (b) fill()
only tried a placeholder match with no fallback for a plain textbox inside an open dialog.

No live browser account, no AI call — pure DOM fixture + _exec logic.
Uso: py -3.11 -X utf8 test_exec_dialog.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer import ai_fallback

FIX = (Path(__file__).parent / "fixtures" / "create_key_modal.html").resolve().as_uri()


async def main():
    ok = True
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        page = await br.new_page()
        await page.goto(FIX)

        # 1) click with page2text's bracket decorator, as the AI actually sends it
        el = await ai_fallback._exec(page, {"action": "click", "text": "[Close]"})
        check1 = el == "button"
        print(f"  {'PASS' if check1 else 'FAIL'}  click '[Close]' (bracketed) resolves -> {el!r}")
        ok = ok and check1

        # 2) fill with no matching placeholder -> must fall back to the visible dialog textbox
        el2 = await ai_fallback._exec(page, {"action": "fill", "placeholder": "Key name",
                                             "value": "pcPersonale"})
        check2 = el2 == "textbox"
        print(f"  {'PASS' if check2 else 'FAIL'}  fill 'Key name' (no matching placeholder) -> {el2!r}")
        ok = ok and check2
        if check2:
            val = await page.locator("input[name=key_name]").input_value()
            check2b = val == "pcPersonale"
            print(f"  {'PASS' if check2b else 'FAIL'}  value actually written -> {val!r}")
            ok = ok and check2b

        await br.close()
    print("\n=== EXEC/DIALOG TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
