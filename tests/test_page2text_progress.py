"""Offline regression for a live bug found on Cohere ("About You" onboarding step): the AI
fills a text field via ref, the fill succeeds, but the NEXT page2text snapshot showed the same
static placeholder (*First name*) instead of the just-typed value -> the AI thought its action
had no effect, refilled the identical field, hit the loop-guard, and gave up right before the
key page. Fix: page2text now reflects the field's current .value (never for password) so a
filled field renders visibly differently (*First name="API"*) from an empty one.

No live browser account, no AI call — pure DOM fixture + page2text.
Uso: py -3.11 -X utf8 test_page2text_progress.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer import page2text

FIX = (Path(__file__).parent / "fixtures" / "two_field_form.html").resolve().as_uri()


async def main():
    ok = True
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        page = await br.new_page()
        await page.goto(FIX)

        txt0 = await page2text.page_to_text(page)
        check1 = '*First name*' in txt0 and '="' not in txt0.split('First name')[1][:6]
        print(f"  {'PASS' if check1 else 'FAIL'}  empty field shows plain placeholder -> "
              f"{[l for l in txt0.splitlines() if 'First name' in l]}")
        ok = ok and check1

        await page.locator("input[placeholder='First name']").fill("API")
        txt1 = await page2text.page_to_text(page)
        check2 = '*First name="API"*' in txt1
        print(f"  {'PASS' if check2 else 'FAIL'}  filled field shows its value -> "
              f"{[l for l in txt1.splitlines() if 'First name' in l]}")
        ok = ok and check2

        # dedup regression: two DIFFERENT states (empty Last name vs filled First name) must
        # both survive dedup, they are genuinely different lines now
        check3 = '*Last name*' in txt1
        print(f"  {'PASS' if check3 else 'FAIL'}  unfilled sibling field still shown separately -> "
              f"{[l for l in txt1.splitlines() if 'Last name' in l]}")
        ok = ok and check3

        # password value must NEVER leak into the text, filled or not
        await page.locator("input[type=password]").fill("hunter2")
        txt2 = await page2text.page_to_text(page)
        check4 = "hunter2" not in txt2
        print(f"  {'PASS' if check4 else 'FAIL'}  password value never rendered -> leaked={not check4}")
        ok = ok and check4

        await br.close()
    print("\n=== PAGE2TEXT PROGRESS TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
