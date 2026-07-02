"""Login con GitHub deterministico (analogo a google_oauth).
Sblocca i siti che entrano SOLO con GitHub (LLM7, GitHub Models, e altri).

Flusso:
  1. Trova+clicca "Continue with GitHub" / "Sign in with GitHub" (selettori + testo).
  2. GitHub si apre (popup o redirect su github.com/login|/login/oauth/authorize).
  3. Sulla pagina GitHub gestisci:
     A) gia loggato + schermata Authorize -> click "Authorize"
     B) login form (username+password) -> compila da ~/.gh_creds, submit, poi Authorize
     C) auto -> redirect, nessun click
  4. Aspetta URL != github.com -> torna al sito.

Credenziali GitHub opzionali in ~/.gh_creds (GH_USER=... GH_PASS=...). Se il profilo Chrome
ha gia la sessione GitHub, basta il caso A (Authorize) senza password.
Ritorna "github" se ha cliccato il bottone, None se assente.
"""
from __future__ import annotations
import os
from pathlib import Path

_CREDS = Path.home() / ".gh_creds"


def _is_github_host(url: str) -> bool:
    return "github.com" in (url or "").lower()


def _gh_creds() -> tuple[str | None, str | None]:
    u = p = None
    try:
        for ln in _CREDS.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("GH_USER="):
                u = ln.split("=", 1)[1].strip().strip('"')
            elif ln.startswith("GH_PASS="):
                p = ln.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return os.environ.get("GH_USER", u), os.environ.get("GH_PASS", p)


_BTN_SEL = [
    "[aria-label*='continue with github' i]", "[aria-label*='sign in with github' i]",
    "a[href*='github.com/login/oauth']", "a[href*='/auth/github']", "a[href*='/oauth/github']",
    "[data-provider='github']", "[data-connection='github']",
    "button[class*='github' i]", "[class*='github' i][role=button]",
]
_BTN_TEXT = ["continue with github", "sign in with github", "sign up with github",
             "log in with github", "continua con github", "accedi con github", "github"]

_AUTHORIZE_TEXT = ["authorize", "autorizza", "continue", "continua"]


async def _click_button(page) -> bool:
    # TESTO visibile prima (qualsiasi verbo: 'Get started with GitHub'...), attributi fallback.
    # Stessa logica condivisa di google_oauth (oauth_text) — niente frasi-esatte hardcoded.
    import oauth_text
    return await oauth_text.click_login(page, "github", _BTN_SEL, _BTN_TEXT)


async def handle_github_page(gp, log=None) -> None:
    """Gestisce la pagina GitHub: login (se serve) + Authorize."""
    try:
        await gp.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    await gp.wait_for_timeout(1000)
    user, pw = _gh_creds()
    for _ in range(8):
        try:
            if gp.is_closed():
                return
            cur = gp.url
        except Exception:
            return
        if not _is_github_host(cur):
            return  # uscito da GitHub -> fatto
        # B) login form (solo se sessione assente e abbiamo le credenziali)
        try:
            uloc = gp.locator("input[name=login], input#login_field").first
            if await uloc.count() and await uloc.is_visible() and user and pw:
                await uloc.fill(user, timeout=2500)
                ploc = gp.locator("input[name=password], input#password").first
                await ploc.fill(pw, timeout=2500)
                btn = gp.locator("input[type=submit], button[type=submit]").first
                await btn.click(timeout=2500)
                if log: log.step("GITHUB", "login", user, "ok")
                await gp.wait_for_timeout(2000)
                continue
        except Exception:
            pass
        # A0) CONSENSI: spunta i checkbox required (Terms of Service / Privacy) PRIMA di Authorize.
        #     (utente ha visto "agree to the Terms of Service and acknowledge the Privacy Policy")
        try:
            cbs = gp.locator("input[type=checkbox]")
            for i in range(min(await cbs.count(), 5)):
                cb = cbs.nth(i)
                if await cb.is_visible() and not await cb.is_checked():
                    try: await cb.check(timeout=1500)
                    except Exception: pass
        except Exception:
            pass
        # A) Authorize / Continue / Sign in (consent OAuth). Cerca per TESTO robusto.
        clicked = False
        for t in _AUTHORIZE_TEXT:
            try:
                loc = gp.locator(f"button:has-text('{t}'), input[value*='{t}' i], [role=button]:has-text('{t}')").first
                if await loc.count() and await loc.is_visible():
                    en = await loc.is_enabled()
                    if en:
                        await loc.click(timeout=2500)
                        if log: log.step("GITHUB", "authorize", t, "ok")
                        clicked = True
                        await gp.wait_for_timeout(1800)
                        break
            except Exception:
                continue
        if not clicked:
            await gp.wait_for_timeout(800)
    return


async def signup_with_github(ctx, page, log=None) -> str | None:
    """Click 'Continue with GitHub' + gestisce la pagina GitHub (popup o redirect)."""
    before = set(ctx.pages)
    clicked = await _click_button(page)
    if not clicked:
        if log: log.step("GITHUB", "bottone assente", "", "skip")
        return None
    if log: log.step("GITHUB", "bottone cliccato", "", "ok")
    gp = None
    for _ in range(16):  # ~8s: popup nuovo o redirect stessa scheda
        for p in list(ctx.pages):
            if p not in before:
                try:
                    if _is_github_host(p.url):
                        gp = p; break
                except Exception:
                    continue
        if gp:
            break
        if _is_github_host(page.url):
            gp = page; break
        await page.wait_for_timeout(500)
    if gp is None:
        gp = page
    await handle_github_page(gp, log)
    if gp is not page:
        for _ in range(16):
            try:
                if not _is_github_host(page.url):
                    break
            except Exception:
                pass
            await page.wait_for_timeout(500)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return "github"
