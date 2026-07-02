"""Offline regression for a live bug found on Cohere's "About You" step: forms.py's generic
name selector matched whichever first/last field it hit first and put the WHOLE SIGNUP_NAME
into it, leaving the other field empty. The page never advanced (a required field stayed
empty), the AI fallback had no sensible value for the leftover field, and looped.

Covers both real shapes: a form with SEPARATE first/last fields (should split), and a form with
a single "Full name" field (should still get the whole name, unchanged behavior).

No live browser account, no AI call — pure DOM fixtures + forms.fill_form.
Uso: py -3.11 -X utf8 test_name_split.py
"""
from __future__ import annotations
import asyncio, os
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

os.environ["SIGNUP_NAME"] = "API Bot"
os.environ.setdefault("SIGNUP_ACCOUNT", "you@example.com")
from farmer import forms

TWO = (Path(__file__).parent / "fixtures" / "two_name_fields.html").resolve().as_uri()
ONE = (Path(__file__).parent / "fixtures" / "one_name_field.html").resolve().as_uri()


async def main():
    ok = True
    async with async_playwright() as pw:
        br = await pw.chromium.launch(headless=True)

        # two separate fields: First name -> "API", Last name -> "Bot" (never left empty)
        page = await br.new_page()
        await page.goto(TWO)
        await forms.fill_form(page)
        first = await page.locator("input[placeholder='First name']").input_value()
        last = await page.locator("input[placeholder='Last name']").input_value()
        check1 = first == "API"
        print(f"  {'PASS' if check1 else 'FAIL'}  first name field gets first word -> {first!r}")
        ok = ok and check1
        check2 = bool(last) and last != ""
        print(f"  {'PASS' if check2 else 'FAIL'}  last name field is NEVER left empty -> {last!r}")
        ok = ok and check2
        await page.close()

        # single "Full name" field: unchanged behavior, gets the whole NAME
        page2 = await br.new_page()
        await page2.goto(ONE)
        await forms.fill_form(page2)
        full = await page2.locator("input[name=name]").input_value()
        check3 = full == "API Bot"
        print(f"  {'PASS' if check3 else 'FAIL'}  single full-name field gets the whole name -> {full!r}")
        ok = ok and check3
        await page2.close()

        await br.close()
    print("\n=== NAME SPLIT TEST:", "TUTTO PASS" if ok else "QUALCOSA FALLISCE", "===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
