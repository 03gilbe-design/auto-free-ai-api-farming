"""Deterministic signup form filler: email/password/name/confirm, ticks consents, submits.
Detects phone fields (tree branch: phone -> AI attempts skip).
"""
from __future__ import annotations
import os, re

# Active account, set via env vars (multi-account collection). No placeholder fallback: a fake
# "you@example.com" here would let a live run silently proceed against fake data instead of
# failing loudly (run.py's main() raises if this is empty before opening a browser — see there).
# The signup password prefers the OS keyring (auto-free-ai-api-farming/signup_password), then
# SIGNUP_PASSWORD, then empties out — no real credential needs to live in the environment, and
# no fake one masks a missing one.
EMAIL = os.environ.get("SIGNUP_ACCOUNT", "").strip()
try:
    from . import secretstore as _ss
    PASSWORD = _ss.get("signup_password", env=("SIGNUP_PASSWORD",)) or ""
except Exception:
    PASSWORD = os.environ.get("SIGNUP_PASSWORD", "").strip()
NAME = os.environ.get("SIGNUP_NAME", "API Bot")   # pseudonym used on signup forms
# split for onboarding forms with SEPARATE first/last name fields (e.g. Cohere "About You").
# Without this the old code put the whole NAME into whichever field matched first (often the
# first-name one, since it's checked first) and left last-name empty -> the AI fallback had
# nothing sensible to fill there, tried an empty value, and looped (found live on Cohere).
_name_parts = NAME.strip().split(None, 1)
FIRST_NAME = _name_parts[0] if _name_parts else NAME
LAST_NAME = _name_parts[1] if len(_name_parts) > 1 else "Bot"  # never leave a last-name field empty

_FIRST_PW_DONE = "_pw_done"


async def _fill_first(page, selectors, value) -> bool:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible() and await loc.is_editable():
                await loc.fill(value, timeout=2000)
                return True
        except Exception:
            continue
    return False


async def fill_form(page, log=None) -> dict:
    rep = {}
    rep["email"] = await _fill_first(page, [
        "input[type=email]", "input[name*=email i]", "input[id*=email i]",
        "input[placeholder*=email i]", "input[autocomplete=email]"], EMAIL)
    # password (prima occorrenza)
    pw_sel = ["input[type=password]", "input[name*=pass i]", "input[id*=pass i]"]
    rep["password"] = await _fill_first(page, pw_sel, PASSWORD)
    # conferma password = seconda password visibile
    try:
        pws = page.locator("input[type=password]")
        if await pws.count() >= 2:
            loc = pws.nth(1)
            if await loc.is_visible():
                await loc.fill(PASSWORD, timeout=2000)
                rep["password2"] = True
    except Exception:
        pass
    # ORGANIZZAZIONE / azienda / team / workspace: campo tipico dell'onboarding (Mistral, ecc).
    # Va PRIMA del nome generico (altrimenti "name" lo intercetta). Valore innocuo.
    rep["org"] = await _fill_first(page, [
        "input[name*=org i]", "input[id*=org i]", "input[placeholder*=organizzaz i]",
        "input[placeholder*=organization i]", "input[name*=company i]", "input[name*=team i]",
        "input[name*=workspace i]", "input[placeholder*=team i]", "input[placeholder*=workspace i]"],
        "La mia org")
    # LAST NAME esplicito: va PRIMA del nome generico (altrimenti il selettore generico lo
    # intercetta e ci mette l'intero NAME, lasciando questo campo vuoto -> la pagina non avanza
    # e l'AI fallback non ha un valore sensato da scriverci, visto live su Cohere "About You").
    rep["last_name"] = await _fill_first(page, [
        "input[name*=last i]", "input[id*=last i]", "input[placeholder*=cognome i]",
        "input[placeholder*=last i]", "input[autocomplete=family-name]"], LAST_NAME)
    # FIRST NAME esplicito: se il form ha un campo dedicato, ci va solo la prima parola.
    rep["name"] = await _fill_first(page, [
        "input[name*=first i]", "input[id*=first i]", "input[placeholder*=first i]",
        "input[autocomplete=given-name]"], FIRST_NAME)
    if not rep["name"]:
        # nessun campo first/last dedicato: probabile form a UN campo "Full name" -> il NOME intero.
        rep["name"] = await _fill_first(page, [
            "input[name*=name i]:not([name*=user i]):not([name*=org i]):not([name*=company i])",
            "input[id*=name i]", "input[placeholder*=nome i]", "input[placeholder*=name i]",
            "input[autocomplete=name]"], NAME)
    # consensi: spunta OGNI checkbox non spuntata (tos/privacy). L'input vero e' spesso NASCOSTO
    # (opacity 0, stile custom sopra) -> check(force=True) bypassa la visibilita'. Un solo modo
    # generico, niente selettori per-sito.
    checks = 0

    async def _really_checked(cb) -> bool:
        """Verifica lo stato REALE dopo un tentativo di check, non assume successo dal solo
        'nessuna eccezione'. Un mouse-click a coordinate puo' mancare il bersaglio (overlay,
        scroll residuo, elemento spostato) e contare un consenso mai davvero spuntato -> submit
        bloccato piu' avanti senza motivo apparente. Se non verificabile (custom widget senza
        is_checked/aria-checked), resta ottimista come prima (non regredire su falsi negativi)."""
        try:
            return bool(await cb.is_checked())
        except Exception:
            pass
        try:
            aria = await cb.get_attribute("aria-checked")
            if aria is not None:
                return aria == "true"
        except Exception:
            pass
        return True  # non verificabile: comportamento precedente (ottimista)

    try:
        cbs = page.locator("input[type=checkbox], [role=checkbox]")
        n = await cbs.count()
        if log: log.dbg("form consensi", checkbox_trovati=n)
        for i in range(min(n, 10)):
            cb = cbs.nth(i)
            try:
                if await cb.is_checked():
                    continue
            except Exception as e:
                if log: log.dbg("is_checked fail", i=i, err=str(e))
            try:
                await cb.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            try:
                await cb.check(force=True, timeout=1500)
                if await _really_checked(cb):
                    checks += 1
                    continue
            except Exception as e1:
                if log: log.dbg("check fail", i=i, err=str(e1)[:150])
            try:
                await cb.click(force=True, timeout=1200)
                if await _really_checked(cb):
                    checks += 1
                    continue
            except Exception as e2:
                if log: log.dbg("click fail", i=i, err=str(e2)[:150])
            # ULTIMO tentativo: click MOUSE reale sulle coordinate (non .check/.click di
            # Playwright, non JS .checked). Componenti React-controllati (Radix/shadcn)
            # ignorano .checked+dispatchEvent: serve l'evento nativo del sistema operativo
            # che il synthetic event system di React intercetta davvero.
            try:
                box = await cb.bounding_box()
                if box:
                    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    await page.mouse.click(cx, cy)
                    if await _really_checked(cb):
                        checks += 1
            except Exception as e3:
                if log: log.dbg("mouse check fail", i=i, err=str(e3)[:150])
    except Exception as e:
        if log: log.dbg("consensi loop fail", err=str(e))
    rep["consents"] = checks
    if log:
        log.step("FORM", "compilato",
                 f"email={'✓' if rep['email'] else '✗'} pw={'✓' if rep['password'] else '✗'} "
                 f"nome={'✓' if rep['name'] else '–'} consensi={checks}", "ok")
    return rep


_SUBMIT_TEXT = ["sign up", "register", "create account", "crea account", "iscriviti",
                "get started", "continue", "continua", "submit", "create", "crea", "next", "avanti"]


async def _clickable(loc) -> bool:
    """Visibile E abilitato: molti form (Mistral 'Crea organizzazione') tengono il submit
    disabled finche' non spunti i consensi -> click su disabled va in timeout inutile."""
    try:
        if not await loc.is_visible():
            return False
        return await loc.is_enabled()
    except Exception:
        return False


async def submit(page, log=None) -> bool:
    # bottone submit esplicito
    for sel in ["button[type=submit]", "input[type=submit]"]:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await _clickable(loc):
                await loc.click(timeout=2500)
                if log: log.step("FORM", "submit", sel, "ok")
                return True
        except Exception:
            continue
    # match per PAROLA intera dentro al testo del bottone (non l'intero testo): "crea" deve
    # matchare "Crea organizzazione", non solo un bottone che dice esattamente "crea".
    for t in _SUBMIT_TEXT:
        try:
            loc = page.locator("button", has_text=re.compile(rf"\b{t}\b", re.I)).first
            if await loc.count() and await _clickable(loc):
                await loc.click(timeout=2500)
                if log: log.step("FORM", "submit", f"text:{t}", "ok")
                return True
        except Exception:
            continue
    if log: log.step("FORM", "submit assente", "", "warn")
    return False


async def complete_form(page, log=None) -> dict:
    """Componente GENERICO deterministico (no AI, no per-sito): compila i campi presenti
    (email/pw/nome/ORG), spunta i consensi (force, anche checkbox nascoste), poi submit.
    Usabile su QUALSIASI pagina con un form di onboarding/registrazione. Ritorna cosa ha fatto
    + se ha inviato. Chiamato prima del fallback AI: molti 'muri' sono solo un form da riempire."""
    before = page.url
    rep = await fill_form(page, log)
    acted = any([rep.get("email"), rep.get("name"), rep.get("org"), rep.get("consents")])
    sent = False
    if acted:
        sent = await submit(page, log)
        try:
            await page.wait_for_timeout(1500)
        except Exception:
            pass
    rep["submitted"] = sent
    rep["advanced"] = sent or page.url != before
    return rep


async def has_phone(page) -> bool:
    try:
        loc = page.locator("input[type=tel], input[name*=phone i], input[id*=phone i], "
                           "input[placeholder*=phone i], input[placeholder*=telefono i]")
        return bool(await loc.count() and await loc.first.is_visible())
    except Exception:
        return False
