"""Signup/login con Google deterministico.

Flusso (albero v2 - ALBERO GOOGLE OAuth):
  1. Trova+clicca bottone "Continue with Google" (selettori + testo, anti play.google)
  2. Google si apre: popup (nuova tab) O redirect in-page -> individua la pagina Google
  3. Sulla pagina Google gestisci 4 casi:
     A) account chooser -> clicca tile EMAIL (data-identifier/data-email/testo)
     B) "Continua come X" -> click unico
     C) consent/permission -> Allow/Consenti/Authorize
     D) auto-login -> redirect, nessun click
  4. Aspetta URL != google.com -> bring_to_front tab originale
Ritorna "google" se ha cliccato il bottone (login plausibile), None se bottone assente.
Profilo persistente gia loggato => di solito caso B/D.
"""
from __future__ import annotations
import os, re

# host considerato "pagina Google OAuth". In test offline: OAUTH_FAKE_HOST=substring url fittizio.
_FAKE = os.environ.get("OAUTH_FAKE_HOST", "")


def _google_pw() -> str | None:
    """Password Google da ~/.google_pw (GOOGLE_PW=...) o env. Stessa per account_a/account_b.
    Usata se Google chiede la pw nel popup (prompt=consent / sessione non fresca)."""
    import os as _os
    from pathlib import Path as _P
    if _os.environ.get("GOOGLE_PW"):
        return _os.environ["GOOGLE_PW"].strip()
    try:
        for ln in (_P.home() / ".google_pw").read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("GOOGLE_PW="):
                v = ln.split("=", 1)[1].strip().strip('"').strip("'")
                if v and v != "LA_TUA_PASSWORD":  # ignora il placeholder
                    return v
            elif ln and "=" not in ln:
                return ln
    except Exception:
        pass
    # FALLBACK: la password Google e' la STESSA del signup (gia nota, forms.PASSWORD).
    # Vale per account_a e account_b (stessa password, detto dall'utente). Niente file da gestire.
    try:
        import forms
        return forms.PASSWORD
    except Exception:
        return None


def _is_oauth_host(url: str) -> bool:
    url = (url or "").lower()
    return ("accounts.google" in url) or ("google.com" in url) or bool(_FAKE and _FAKE in url)

_BTN_SEL = [
    "[aria-label*='continue with google' i]", "[aria-label*='sign in with google' i]",
    "[aria-label*='sign up with google' i]", "[aria-label*='accedi con google' i]",
    "a[href*='google-oauth2']", "a[href*='connection=google']",
    "a[href*='/auth/google']", "a[href*='/oauth/google']", "a[href*='accounts.google.com/o/oauth2']",
    "a[href*='provider=google' i]", "a[href*='idp=google' i]", "a[href*='sso/google' i]",  # baseten ecc
    "[data-provider='google']", "[data-connection='google-oauth2']",
    ".auth0-lock-social-button[data-provider='google']",
    "button[class*='google' i]", "iframe[src*='accounts.google.com']",
    # FALLBACK per bottoni SENZA testo (icona/immagine): href/data-provider/img alt/title/class/id.
    # (NB: il testo visibile e' gestito PRIMA, in _click_button priorita' 1 — qui solo i muti)
    "button:has(img[alt*='google' i])", "a:has(img[alt*='google' i])",
    "[title*='sign in with google' i]", "[title*='continue with google' i]", "[title*='google' i][role=button]",
    "[data-provider*='google' i]", "[data-qa*='google' i]", "[data-testid*='google' i]", "[data-test*='google' i]",
    "[class*='login-google' i]", "[class*='google-login' i]", "[id*='google' i][role=button]",
]
_BTN_TEXT = ["continue with google", "sign up with google", "sign in with google",
             "log in with google", "continua con google", "accedi con google"]
# NB: mai a[href*='google'] da solo -> match play.google.com

_ALLOW_TEXT = ["allow", "consenti", "authorize", "autorizza", "continue", "continua", "accetto", "accept"]


async def _click_button(page) -> bool:
    """Trova il bottone 'login con Google': TESTO visibile prima (qualsiasi verbo), attributi fallback.
    Logica condivisa in oauth_text (stessa per GitHub) — niente keyword per-sito."""
    import oauth_text
    return await oauth_text.click_login(page, "google", _BTN_SEL, _BTN_TEXT)


async def handle_google_page(gp, email: str, log=None) -> None:
    """Gestisce la pagina Google (chooser/continua-come/consent/auto)."""
    try:
        await gp.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    await gp.wait_for_timeout(1500)  # il chooser Google carica i tile in ritardo (Cohere)
    user = email.split("@")[0]
    chosen = False  # account gia scelto (tile o email digitata) -> non ri-cliccare il testo
    for _ in range(10):  # piu' giri: alcuni flow (Cohere) mostrano il chooser dopo qualche secondo
        try:
            if gp.is_closed():
                return  # popup chiuso = login concluso
            cur = gp.url
        except Exception:
            return
        if not _is_oauth_host(cur):
            return  # uscito da Google -> fatto
        # A) tile per email/identifier (chooser "scegli account"). SOLO la PRIMA volta:
        # dopo aver scelto l'account, la pagina consent mostra ancora l'email come TESTO -> non
        # ri-cliccare (era il loop "tile account" x9). Tile = solo elementi CLICCABILI con
        # data-identifier (il vero tile del chooser), non un div di testo qualsiasi.
        # A-1) ACCOUNT SBAGLIATO: se Google mostra "Continua come <altro>" o NON c'e' il nostro
        # tile, clicca "Usa un altro account"/"Use another account" -> ricompare il chooser pulito.
        # (fix dubbio utente: il chooser auto-loggava l'account primario invece di SIGNUP_ACCOUNT)
        if not chosen:
            try:
                our = await gp.locator(f"[data-identifier='{email}'], [data-email='{email}']").count()
                if not our:
                    for t in ["Use another account", "Usa un altro account", "Add account",
                              "Aggiungi account", "Use another", "Sign in with another account"]:
                        alt = gp.get_by_text(t, exact=False).first
                        if await alt.count() and await alt.is_visible():
                            await alt.click(timeout=2000)
                            if log: log.step("GOOGLE", "usa altro account", t, "ok")
                            await gp.wait_for_timeout(1500)
                            break
            except Exception:
                pass
        picked = False
        if not chosen:
            for sel in [f"[data-identifier='{email}']", f"[data-email='{email}']",
                        f"[data-identifier*='{user}']"]:
                try:
                    loc = gp.locator(sel).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=2500)
                        if log: log.step("GOOGLE", "tile account", email, "ok")
                        await gp.wait_for_timeout(1500)
                        picked = True; chosen = True
                        break
                except Exception:
                    continue
        # A2) pagina IDENTIFIER "Email o telefono" -> DIGITA l'email + Avanti.
        # (AI21: Google non mostra il chooser ma chiede di scrivere l'email)
        if not picked:
            try:
                ident = gp.locator("input[type=email], input#identifierId, input[name=identifier]").first
                if await ident.count() and await ident.is_visible():
                    await ident.fill(email, timeout=2500)
                    chosen = True
                    if log: log.step("GOOGLE", "digito email", email, "ok")
                    for nx in ["Avanti", "Next", "Continua", "Continue"]:
                        b = gp.get_by_role("button", name=re.compile(rf"\b{nx}\b", re.I)).first
                        if await b.count() and await b.is_visible():
                            await b.click(timeout=2000); break
                    await gp.wait_for_timeout(1800)
            except Exception:
                pass
        # A3) pagina PASSWORD (challenge/pwd): Google chiede la pw (prompt=consent / sessione
        # non fresca). Digita la pw da ~/.google_pw (stessa per account_a e account_b) + Avanti.
        try:
            ploc = gp.locator("input[type=password]:visible").first
            if await ploc.count() and await ploc.is_visible():
                pw = _google_pw()
                if not pw:
                    if log: log.step("GOOGLE", "password richiesta", "manca ~/.google_pw - metti GOOGLE_PW", "warn")
                    return
                # NON ridigitare se gia inserita (era il loop x5): scrivi solo se il campo e' vuoto
                cur = ""
                try: cur = await ploc.input_value()
                except Exception: pass
                if not cur:
                    await ploc.fill(pw, timeout=2500)
                    if log: log.step("GOOGLE", "digito password", "ok", "ok")
                # INVIO = piu' affidabile del bottone 'Avanti' (testo/selettore variano per lingua)
                try:
                    await ploc.press("Enter", timeout=2000)
                except Exception:
                    for nx in ["Avanti", "Next", "Continua", "Continue"]:
                        b = gp.get_by_role("button", name=re.compile(rf"\b{nx}\b", re.I)).first
                        if await b.count() and await b.is_visible():
                            await b.click(timeout=2000); break
                await gp.wait_for_timeout(2500)
                # se DOPO l'invio siamo ancora sul campo password con lo stesso valore -> pw SBAGLIATA
                try:
                    still = gp.locator("input[type=password]:visible").first
                    if await still.count() and (await still.input_value()):
                        if log: log.step("GOOGLE", "password rifiutata?", "verifica GOOGLE_PW", "warn")
                except Exception:
                    pass
        except Exception:
            pass
        # B/C) bottoni continua/allow. Il consent OAuth puo' essere LUNGO (Nebius: "Scorri verso
        # il basso"/Scroll down -> il bottone Continue/Allow e' sotto). SCROLLA prima di cercarlo.
        try:
            # consent con SCROLL INTERNO (Nebius): "Scorri verso il basso" e' un bottone che
            # scrolla il container; cliccalo FINCHE' sparisce (max 6 volte), poi Continue appare.
            for _ in range(6):
                sb = gp.get_by_text(re.compile(r"scroll down|scorri verso il basso", re.I)).first
                if await sb.count() and await sb.is_visible():
                    try: await sb.click(timeout=1200)
                    except Exception: pass
                    await gp.wait_for_timeout(500)
                else:
                    break
            await gp.mouse.wheel(0, 4000)
            await gp.wait_for_timeout(400)
        except Exception:
            pass
        confirmed = False
        for t in _ALLOW_TEXT:
            try:
                loc = gp.get_by_role("button", name=re.compile(rf"\b{t}\b", re.I)).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    if log: log.step("GOOGLE", "conferma", t, "ok")
                    await gp.wait_for_timeout(1500)
                    confirmed = True
                    break
            except Exception:
                continue
        # consent "Continua su <App>" (Nebius): se _ALLOW_TEXT non ha trovato il bottone, cerca
        # un link/bottone "continua su"/"continue to" o il NOME APP cliccabile (e' il consent finale).
        if not confirmed:
            try:
                for pat in [r"continua su", r"continue to", r"vai a", r"proceed to"]:
                    loc = gp.get_by_text(re.compile(pat, re.I)).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=2000)
                        if log: log.step("GOOGLE", "consent continua-su", pat, "ok")
                        await gp.wait_for_timeout(1500)
                        confirmed = True
                        break
            except Exception:
                pass
        await gp.wait_for_timeout(700)
    return


async def signup_with_google(ctx, page, email: str, log=None) -> str | None:
    """ctx = browser context (per intercettare popup). page = pagina sito.
    Google puo aprirsi in 3 modi: POPUP (nuova finestra), REDIRECT stessa scheda, o auto-login.
    Catturiamo il popup confrontando le finestre prima/dopo il click (wait_for_event di 3s
    lo mancava su siti lenti come AI21)."""
    before = set(ctx.pages)
    clicked = await _click_button(page)
    if not clicked:
        if log: log.step("GOOGLE", "bottone assente", "", "skip")
        return None
    if log: log.step("GOOGLE", "bottone cliccato", "", "ok")
    # cerca la pagina Google: popup nuova (in ctx.pages, non c'era prima) O redirect stessa scheda
    gp = None
    for _ in range(16):  # ~8s
        for p in list(ctx.pages):
            if p not in before:
                try:
                    if _is_oauth_host(p.url):
                        gp = p; break
                except Exception:
                    continue
        if gp:
            break
        if _is_oauth_host(page.url):  # redirect nella stessa scheda
            gp = page; break
        await page.wait_for_timeout(500)
    if gp is None:
        gp = page  # nessun popup visto: forse auto-login gia fatto
    if log and gp is not page:
        log.step("GOOGLE", "finestra popup", "catturata", "ok")
        # DEBUG: cosa c'e' DENTRO il popup (url + testo)? cosi' si vede se c'e' il chooser.
        try:
            await gp.wait_for_timeout(1200)
            txt = (await gp.inner_text("body"))[:400]
            log.dbg("popup contenuto", url=gp.url, body=txt)
        except Exception as e:
            log.dbg("popup illeggibile", err=str(e))
    await handle_google_page(gp, email, log)
    # se era un popup, ora si chiude da solo: aspetta che la SCHEDA principale esca dal login
    if gp is not page:
        for _ in range(16):  # ~8s: la sessione deve propagarsi alla scheda madre
            try:
                if not _is_oauth_host(page.url) and "/auth" not in page.url and "login" not in page.url.lower():
                    break
            except Exception:
                pass
            await page.wait_for_timeout(500)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return "google"
