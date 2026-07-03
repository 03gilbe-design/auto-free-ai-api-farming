"""Logout dal SITO per cambiare account. Un sito gia loggato come account1 non mostra il
chooser Google -> entra dritto come account1. Per prendere la key di account2 bisogna prima
sloggarsi dal sito, cosi al re-login Google mostra il chooser e google_oauth sceglie l'account
giusto (per email, gia loggato nel profilo Chrome).

Strategia (generica, deterministica):
  1. UI: clicca avatar/menu account poi voce 'Sign out / Log out / Esci'.
  2. URL noti: prova <dominio>/logout, /signout, /auth/logout, /api/auth/logout, ...
Ritorna True se ha (probabilmente) sloggato.
"""
from __future__ import annotations
import json
from urllib.parse import urlparse

_LOGOUT_TXT = ["sign out", "log out", "logout", "esci", "disconnetti", "sign-out"]


def _css_text(t: str) -> str:
    return json.dumps(t or "")
_MENU_SEL = ["[aria-label*='account' i]", "[aria-label*='profile' i]", "[aria-label*='menu' i]",
             "button[class*='avatar' i]", "img[alt*='avatar' i]", "[data-testid*='user' i]",
             "[class*='avatar' i]", "[class*='userMenu' i]"]
_PATHS = ["/logout", "/signout", "/sign-out", "/auth/logout", "/api/auth/logout",
          "/account/logout", "/users/sign_out", "/session/logout"]


async def _click_text(page, words) -> bool:
    for t in words:
        for tag in ["button", "a", "[role=menuitem]", "[role=button]"]:
            try:
                loc = page.locator(f"{tag}:has-text({_css_text(t)})").first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    return True
            except Exception:
                continue
    return False


async def logout(page, site: dict, log=None) -> bool:
    name = site.get("name", "?")
    key_url = site.get("provider_cfg", {}).get("key_url") or site.get("key_url") or page.url
    base = f"{urlparse(key_url).scheme}://{urlparse(key_url).netloc}"
    # 1) UI diretta: a volte il 'Sign out' e' gia visibile
    if await _click_text(page, _LOGOUT_TXT):
        if log: log.step("LOGOUT", "via UI", name, "ok")
        await page.wait_for_timeout(1500)
        return True
    # 2) apri un menu account, poi cerca 'Sign out'
    for sel in _MENU_SEL:
        try:
            m = page.locator(sel).first
            if await m.count() and await m.is_visible():
                await m.click(timeout=1500)
                await page.wait_for_timeout(700)
                if await _click_text(page, _LOGOUT_TXT):
                    if log: log.step("LOGOUT", "via menu", name, "ok")
                    await page.wait_for_timeout(1500)
                    return True
        except Exception:
            continue
    # 3) URL di logout noti
    for p in _PATHS:
        try:
            await page.goto(base + p, timeout=12000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
            body = (await page.inner_text("body"))[:1500].lower()
            # "continue with" removed: a page saying "Continue with Google to connect another
            # workspace" is NOT proof of logout (GPT bug 10). Keep only signals that a logged-in
            # session is actually gone: an explicit sign-in prompt or a logged-out confirmation.
            if any(w in body for w in ["sign in", "log in", "accedi", "logged out", "signed out"]):
                if log: log.step("LOGOUT", "via url", p, "ok")
                return True
        except Exception:
            continue
    if log: log.step("LOGOUT", "non riuscito", name, "warn")
    return False
