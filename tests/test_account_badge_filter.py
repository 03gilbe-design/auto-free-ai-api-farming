"""Offline regression: header "account badge" buttons whose entire text is just an email
address (e.g. Cohere's [you@example.com] profile menu) used to be rendered as an actionable
[Text] button in page2text. The AI had no way to know it's informational-only and kept trying
to click/fill it instead of the real task (found live: 3 failed attempts -> giveup right on
Cohere's role-selection page). Now filtered out entirely, real buttons stay.

No live browser account, no AI call — pure DOM fixture + page2text.
Uso: py -3.11 -X utf8 test_account_badge_filter.py
"""
from __future__ import annotations
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer import page2text

FIX = (Path(__file__).parent / "fixtures" / "account_badge.html").resolve().as_uri()


async def main():
    ok = True
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)
        page = await br.new_page()
        await page.goto(FIX)
        txt = await page2text.page_to_text(page)

        check1 = "you@example.com" not in txt
        print(f"  {'PASS' if check1 else 'FAIL'}  email-only badge button filtered out -> "
              f"leaked={'you@example.com' in txt}")
        ok = ok and check1

        check2 = "[Continue]" in txt
        print(f"  {'PASS' if check2 else 'FAIL'}  real button still shown -> {'[Continue]' in txt}")
        ok = ok and check2

        await br.close()
    print("\n=== ACCOUNT BADGE FILTER TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
