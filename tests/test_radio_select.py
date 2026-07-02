"""Offline regression: _exec() had no dedicated action for radio buttons or <select> dropdowns
before today. page2text already recognized them ('( ) Label' / 'V-Label-V') but the AI could
only issue a generic "click" on the label text, which sometimes missed the real input (custom
wrappers that don't propagate the click) -> the radio/select never actually changed state, the
page never advanced, and the loop-guard gave up (found live on Cohere's "What is your role?"
step, right after the page2text field-value fix unblocked the previous stall).

No live browser account, no AI call — pure DOM fixture + _exec logic.
Uso: py -3.11 -X utf8 test_radio_select.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer import ai_fallback, page2text

FIX = (Path(__file__).parent / "fixtures" / "role_page.html").resolve().as_uri()


async def main():
    ok = True
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        page = await br.new_page()
        await page.goto(FIX)

        # 1) page2text recognizes both node types with refs
        txt = await page2text.page_to_text(page)
        import re as _re
        m_radio = _re.search(r"\(\s?\)\s*Machine Learning Engineer\s*\{ref:(e\d+)\}", txt)
        m_select = _re.search(r"V-.*-V.*\{ref:(e\d+)\}", txt)
        check1 = bool(m_radio and m_select)
        print(f"  {'PASS' if check1 else 'FAIL'}  page2text shows radio+select with refs -> "
              f"radio={m_radio.group(1) if m_radio else None} select={m_select.group(1) if m_select else None}")
        ok = ok and check1

        # 2) select radio by ref -> verify actually checked (not just "no exception")
        if m_radio:
            el = await ai_fallback._exec(page, {"action": "radio", "ref": m_radio.group(1),
                                                "text": "Machine Learning Engineer"})
            check2 = el == "radio"
            print(f"  {'PASS' if check2 else 'FAIL'}  radio action resolves -> {el!r}")
            ok = ok and check2
            if check2:
                checked = await page.locator("input[value=mle]").is_checked()
                print(f"  {'PASS' if checked else 'FAIL'}  radio actually checked -> {checked}")
                ok = ok and checked

        # 3) radio by TEXT ONLY (no ref) — the fallback path, in case a stale/missing ref happens
        el2 = await ai_fallback._exec(page, {"action": "radio", "text": "Software Engineer"})
        check3 = el2 == "radio"
        print(f"  {'PASS' if check3 else 'FAIL'}  radio by text (no ref) -> {el2!r}")
        ok = ok and check3
        if check3:
            checked2 = await page.locator("input[value=se]").is_checked()
            print(f"  {'PASS' if checked2 else 'FAIL'}  text-only radio actually checked -> {checked2}")
            ok = ok and checked2

        # 4) select an option by ref
        if m_select:
            el3 = await ai_fallback._exec(page, {"action": "select", "ref": m_select.group(1),
                                                 "option": "Engineering"})
            check4 = el3 == "select"
            print(f"  {'PASS' if check4 else 'FAIL'}  select action resolves -> {el3!r}")
            ok = ok and check4
            if check4:
                val = await page.locator("select[name=team]").input_value()
                check4b = val == "eng"
                print(f"  {'PASS' if check4b else 'FAIL'}  select value actually set -> {val!r}")
                ok = ok and check4b

        await br.close()
    print("\n=== RADIO/SELECT TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
