"""Orchestratore = albero decisioni v2. MAI fermarsi a meta: ogni blocco ha AI fallback.
Unico esito di stop = no_key finale (oppure telefono richiesto -> sito abbandonato).

Pipeline 6 passi: COOKIE -> SIGNUP -> VERIFY -> ONBOARDING -> KEY -> SAVE
(passi 0/2/3 = arrivo + accesso; salvataggio = lato run.py).

Stop manuale: se l'utente crea il file out/STOP, run.py interrompe tra un sito e l'altro.
A meta sito non ci si ferma mai: si arriva sempre a un esito.
"""
from __future__ import annotations
import os, re
from . import cookies, links, google_oauth, forms, grabkey, ai_fallback, logout, github_oauth, snapshot

KEY_HINT = ("api-key", "apikey", "/keys", "/tokens", "developer", "dashboard")
NOT_LOGGED = ("sign in", "sign up", "log in", "accedi", "registrati", "create account")
VERIFY_HINT = ("verify", "verifica", "conferma", "check your email", "controlla la", "confirm your email")
ONB_SKIP = ["skip", "maybe later", "salta", "più tardi", "not now", "no thanks", "dismiss"]

# host considerato pagina Google OAuth (stessa logica di google_oauth, usata per il settle)
_FAKE = os.environ.get("OAUTH_FAKE_HOST", "")


def _is_oauth_host(url: str) -> bool:
    url = (url or "").lower()
    return ("accounts.google" in url) or ("google.com" in url) or bool(_FAKE and _FAKE in url)


async def _wait_render(page, timeout_ms: int = 8000):
    """SPA: la pagina puo arrivare VUOTA (form disegnato da JS dopo). Aspetta che compaia
    almeno un campo o bottone reale, non un timeout fisso. (AI21: page2text leggeva vuoto)."""
    try:
        await page.wait_for_selector(
            "input:visible, button:visible, [role=button]:visible, a[href]:visible",
            timeout=timeout_ms, state="visible")
    except Exception:
        pass  # se scade, prosegue comunque (meglio provare che bloccare)



async def _is_github_host(page) -> bool:
    return 'github.com' in (page.url or '').lower()

async def _body(page) -> str:
    try:
        return (await page.inner_text("body"))[:3000].lower()
    except Exception:
        return ""


async def _click_text(page, texts) -> bool:
    for t in texts:
        for tag in ["button", "a", "[role=button]", "[type=submit]"]:
            try:
                loc = page.locator(f"{tag}:has-text('{t}')").first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2500)
                    return True
            except Exception:
                continue
    return False


_KEYAREA_POS = ("api key", "create key", "create new key", "generate key", "secret key",
                "your api key", "api keys are used", "manage keys", "chiave api")


async def _is_key_area(page) -> bool:
    url = page.url.lower()
    if not any(h in url for h in KEY_HINT):
        return False
    body = await _body(page)
    # SEGNALI POSITIVI: se la pagina parla di API key/create key, sei nell'area chiavi ANCHE se
    # c'e' "Log in" nell'header (Nebius: header ha sempre "Log in" pur essendo loggato -> falso
    # negativo che innescava il loop muro-login). I positivi vincono sui negativi.
    if any(h in body for h in _KEYAREA_POS):
        return True
    return not any(h in body for h in NOT_LOGGED)  # se chiede login -> non sei nell'area key


# segnali CARTA DI CREDITO richiesta per creare la key (TogetherAI: "Deposit $5 ... to create API keys")
_CARD_RX = re.compile(
    r"add (credits|payment|a card)|deposit \$|purchase credits|payment (information|method)|"
    r"billing (information|details) required|enter your card|add funds|"
    r"\$\d+ to (create|purchase|start)|carta di credito|metodo di pagamento", re.I)


async def _needs_card(page) -> bool:
    """La pagina chiede la CARTA per creare la key? (rilevamento automatico -> skip con motivo)."""
    try:
        body = (await page.inner_text("body"))[:4000]
        return bool(_CARD_RX.search(body))
    except Exception:
        return False


async def run_site(ctx, site: dict, log) -> dict:
    name = site["name"]
    cfg = site.get("provider_cfg", {})
    log.head(name)
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    # AUTO-SNAPSHOT: cattura OGNI schermata che si apre navigando (cambio pagina + popup),
    # dedup per contenuto (no loop). Costruisce l'albero offline completo, non solo 3 punti.
    snapshot.attach_auto(ctx, name, log)

    # CAMBIO ACCOUNT: slogga prima dal sito (env SIGNUP_LOGOUT_FIRST), cosi il re-login
    # mostra il chooser Google e google_oauth sceglie l'account in SIGNUP_ACCOUNT.
    if os.environ.get("SIGNUP_LOGOUT_FIRST") and cfg.get("key_url"):
        try:
            await page.goto(cfg["key_url"], timeout=20000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1200)
            await logout.logout(page, site, log)
        except Exception as e:
            log.err("LOGOUT", e)

    # PASSO arrivo — apri il sito
    try:
        await page.goto(site["url"], timeout=25000, wait_until="domcontentloaded")
        log.step("ARRIVO", "pagina aperta", site["url"], "ok")
    except Exception as e:
        log.err("ARRIVO", e)
    await page.wait_for_timeout(1200)
    await _wait_render(page)  # SPA: aspetta che i campi compaiano prima di leggere
    await snapshot.save(page, name, "arrivo", log)   # snapshot stato: landing

    # PASSO 1 — COOKIE
    await cookies.dismiss(page, log)

    # RAMO GITHUB ANTICIPATO (solo siti via_github, es. LLM7): il bottone "Continue with GitHub"
    # e' sulla landing ma sparisce se links/ai navigano via. Provalo SUBITO. Condizionato a
    # via_github -> NON tocca il flow dei siti via-Google (zero regressione sui 9 funzionanti).
    gh_early = False
    if site.get("via_github") and not await _is_key_area(page):
        # i bottoni OAuth sono SPA-render lento (LLM7): aspetta che compaia un bottone "github".
        try:
            await page.wait_for_selector(
                "button:has-text('github'), a:has-text('github'), [aria-label*='github' i]",
                timeout=6000, state="visible")
        except Exception:
            pass
        gh = await github_oauth.signup_with_github(ctx, page, log)
        # bottone GitHub sulla LANDING assente (Nebius/LLM7: sta sulla pagina AUTH dopo redirect/
        # click 'Log in'). Vai a signup_url e ai link signin, poi riprova github.
        if not gh:
            for target in [site.get("url"), None]:
                try:
                    if target:
                        await page.goto(target, timeout=20000, wait_until="domcontentloaded")
                    else:
                        await links.find_and_click(page, "signin", log)  # clicca 'Log in'
                    # la pagina AUTH (Nebius tokenfactory) renderizza i bottoni OAuth via JS DOPO:
                    # aspetta networkidle + che compaia davvero il bottone github (fino a 12s),
                    # altrimenti controlliamo troppo presto = 'assente' (era il bug Nebius/LLM7).
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_selector(
                            "button:has-text('github'), a:has-text('github'), [aria-label*='github' i], [data-qa*='github' i]",
                            timeout=12000, state="visible")
                    except Exception:
                        pass
                    await cookies.dismiss(page, log)
                    gh = await github_oauth.signup_with_github(ctx, page, log)
                    if gh:
                        break
                except Exception:
                    continue
        if gh:
            await page.wait_for_timeout(1500)
            gh_early = True

    # gia loggato/entrato -> salta la registrazione, vai al PASSO 6 chiavi
    if gh_early or await _is_key_area(page):
        log.step("INGRESSO", "gia dentro" if gh_early else "gia nell'area chiavi",
                 "salto la registrazione", "skip")
    else:
        # PASSO 2 — SIGNUP: trova dove registrarsi
        r = await links.find_and_click(page, "signup", log)
        if r is None:
            r2 = await links.find_and_click(page, "signin", log)  # alcuni siti: accedi con Google = registrati
            if r2 is None:
                log.step("INGRESSO", "link non trovato", "passo all'IA", "ai")
                await ai_fallback.ai_step(page, f"vai alla pagina di registrazione di {name}", 20, log, site=name)
        await page.wait_for_timeout(1200)
        await cookies.dismiss(page, log)  # il banner puo ricomparire sulla pagina di registrazione

        # PASSO 3 — ACCESSO (Google oppure modulo)
        done_signup = False
        if site.get("via_google", True):
            # se c'e il campo telefono nel modulo Google e' raro; il telefono lo controlliamo sul modulo
            g = await google_oauth.signup_with_google(ctx, page, forms.EMAIL, log)
            if g:
                # settle: dopo il click su Google la pagina puo navigare in ritardo.
                # Se siamo (ancora) sul selettore account Google, gestiscilo davvero, niente passo saltato.
                await page.wait_for_timeout(1500)
                for _ in range(3):
                    if _is_oauth_host(page.url):
                        await google_oauth.handle_google_page(page, forms.EMAIL, log)
                        await page.wait_for_timeout(1200)
                    else:
                        break
                done_signup = True

        # RAMO GITHUB: siti che entrano con GitHub (LLM7, GitHub Models). Provato se il sito
        # lo dichiara (via_github) OPPURE se Google non ha funzionato e c'e' un bottone GitHub.
        if not done_signup and not await _is_key_area(page):
            if site.get("via_github") or True:  # tenta sempre: _click_button ritorna None se assente
                gh = await github_oauth.signup_with_github(ctx, page, log)
                if gh:
                    await page.wait_for_timeout(1500)
                    done_signup = True

        if not done_signup and not await _is_key_area(page):
            # REGOLA FERREA: telefono richiesto -> sito abbandonato (no_key), niente trucchi
            if await forms.has_phone(page):
                log.step("MODULO", "richiede telefono", "sito abbandonato", "warn")
                log.step("ESITO", "nessuna chiave", f"{name}: numero di telefono obbligatorio", "err")
                return {"status": "no_key", "reason": "phone_required"}
            rep = await forms.fill_form(page, log)
            if rep.get("email"):
                # Cloudflare Dashboard: il bottone "Sign in" spesso non ha un submit
                # standard; clicco il testo esplicito prima del fallback generico.
                if name == "Cloudflare Workers AI":
                    clicked = await _click_text(page, ["Sign in", "Continue", "Log in", "Login"])
                    if clicked:
                        log.step("MODULO", "submit esplicito", "Cloudflare Sign in", "ok")
                    else:
                        await forms.submit(page, log)
                else:
                    await forms.submit(page, log)
                await page.wait_for_timeout(2500)
                # un modulo puo introdurre il telefono in un secondo passo
                if await forms.has_phone(page):
                    log.step("MODULO", "richiede telefono", "sito abbandonato", "warn")
                    log.step("ESITO", "nessuna chiave", f"{name}: numero di telefono obbligatorio", "err")
                    return {"status": "no_key", "reason": "phone_required"}
            else:
                # niente modulo e niente Google -> IA
                log.step("ACCESSO", "ne Google ne modulo", "passo all'IA", "ai")
                await ai_fallback.ai_step(page, f"registrati o accedi con Google su {name}", 100, log, site=name)

        # PASSO 4 — VERIFICA EMAIL (solo se la pagina la chiede; con Google e' gia verificata)
        body = await _body(page)
        if any(h in body for h in VERIFY_HINT) and not _is_oauth_host(page.url):
            log.step("VERIFICA", "email da confermare", "(Gmail manuale / IA)", "wait")
            await ai_fallback.ai_step(page, f"completa la verifica email per {name}", 30, log, site=name)
        else:
            log.step("VERIFICA", "non necessaria", "proseguo", "skip")

        # PASSO 5 — ONBOARDING: salta i pannelli iniziali
        onb = 0
        for _ in range(4):
            clicked = False
            for t in ONB_SKIP:
                try:
                    loc = page.get_by_role("button", name=re.compile(rf"\b{t}\b", re.I)).first
                    if await loc.count() and await loc.is_visible():
                        await loc.click(timeout=1500)
                        log.step("ONBOARD", "pannello saltato", t, "skip")
                        clicked = True
                        onb += 1
                        await page.wait_for_timeout(800)
                        break
                except Exception:
                    pass
            if not clicked:
                break
        if onb == 0:
            log.step("ONBOARD", "niente da saltare", "proseguo", "skip")
        await snapshot.save(page, name, "post_accesso", log)   # snapshot stato: dopo login/onboard

    # PASSO 6 — KEY: vai alla sezione chiavi
    key_url = cfg.get("key_url")
    if key_url:
        try:
            await page.goto(key_url, timeout=20000, wait_until="domcontentloaded")
            await page.wait_for_timeout(1500)
            await cookies.dismiss(page, log)
        except Exception as e:
            log.err("CHIAVI-NAV", e)
        # REDIRECT ONBOARDING: alcuni key_url rimbalzano su get-started/onboarding (Cerebras:
        # /apikeys -> /get-started). Se non siamo nell'area chiavi, clicca la voce di nav "API keys".
        url_low = page.url.lower()
        if ("get-started" in url_low or "onboarding" in url_low) or not await _is_key_area(page):
            for nm in ["API keys", "API Keys", "Api Keys"]:
                try:
                    nav = page.get_by_role("link", name=nm).first
                    if not await nav.count():
                        nav = page.get_by_role("button", name=nm).first
                    if await nav.count() and await nav.is_visible():
                        await nav.click(timeout=2500)
                        log.step("CHIAVI", "nav voce chiavi", nm, "ok")
                        await page.wait_for_timeout(1200)
                        break
                except Exception:
                    continue
    elif not await _is_key_area(page):
        await links.find_and_click(page, "apikeys", log)
        await page.wait_for_timeout(1200)

    # MURO LOGIN: il key_url puo rimandare a una pagina di accesso (sessione scaduta o
    # provider che slogga, es. SambaNova Auth0 con logout_after). Ri-autentica via Google e
    # ritorna sul key_url. (stessa logica dell'oracolo api_signup)
    if site.get("via_google", True) or site.get("via_github"):
        body = await _body(page)
        on_login = (("continue with google" in body or "continue with github" in body
                     or "log in" in body or "sign in" in body or "accedi" in body)
                    and not _is_oauth_host(page.url) and not await _is_github_host(page)
                    and not await _is_key_area(page))
        if on_login:
            # GitHub-first se il sito lo usa (DeepInfra/Nebius/LLM7); altrimenti Google.
            g = None
            if site.get("via_github") or "continue with github" in body:
                log.step("CHIAVI", "muro login", "ri-accesso con GitHub", "ai")
                g = await github_oauth.signup_with_github(ctx, page, log)
            if not g:
                log.step("CHIAVI", "muro login", "ri-accesso con Google", "ai")
                g = await google_oauth.signup_with_google(ctx, page, forms.EMAIL, log)
            # Bottone Google ASSENTE sulla pagina chiavi (Mistral: admin.mistral.ai non lo mostra,
            # sta su auth.mistral.ai). Vai alla signup_url del sito, dove il bottone c'e', poi torna.
            if not g and site.get("url"):
                try:
                    await page.goto(site["url"], timeout=20000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(1200)
                    await _wait_render(page)
                    await cookies.dismiss(page, log)
                    log.step("CHIAVI", "login via signup_url", site["url"], "ai")
                    g = await google_oauth.signup_with_google(ctx, page, forms.EMAIL, log)
                except Exception as e:
                    log.err("CHIAVI-LOGIN", e)
            if g:
                await page.wait_for_timeout(1500)
                # Nebius rimbalza sul chooser piu' volte (consent multi-step): piu' giri (6) +
                # attesa networkidle per far propagare la sessione prima di andare al key_url.
                for _ in range(6):
                    if _is_oauth_host(page.url):
                        await google_oauth.handle_google_page(page, forms.EMAIL, log)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=6000)
                        except Exception:
                            pass
                        await page.wait_for_timeout(1200)
                    else:
                        break
                if key_url:
                    try:
                        await page.goto(key_url, timeout=20000, wait_until="domcontentloaded")
                        await page.wait_for_timeout(1500)
                        await cookies.dismiss(page, log)
                    except Exception as e:
                        log.err("CHIAVI-NAV2", e)

    await snapshot.save(page, name, "pagina_chiavi", log)   # snapshot stato: dove si prende la key
    # OAUTH BLOCCATO: alcuni siti (Nscale) RIFIUTANO il login OAuth automatizzato -> l'URL torna
    # con ?error=OAuthCallback. Rilevamento automatico -> skip con motivo, niente AI sprecata.
    if re.search(r"error=oauth|oauthcallback|authentication failed|access_denied", (page.url or ""), re.I):
        log.step("CHIAVI", "OAuth rifiutato", "muro oauth_blocked (bot-detection)", "warn")
        log.step("ESITO", "nessuna chiave", f"{name}: OAuth bloccato", "err")
        return {"status": "no_key", "reason": "oauth_blocked", "wall": "oauth_blocked"}
    # COOKIE BANNER sulla PAGINA CHIAVI (Nebius: "Manage cookies/Allow all/Confirm my choices"
    # in primo piano copre il bottone genera-key). Chiudilo PRIMA di leggere/generare la chiave.
    await cookies.dismiss(page, log)
    # CARTA richiesta? -> skip automatico con motivo, niente AI sprecata (TogetherAI: deposito $5)
    if await _needs_card(page):
        log.step("CHIAVI", "richiede carta di credito", "muro, sito abbandonato", "warn")
        log.step("ESITO", "nessuna chiave", f"{name}: serve carta di credito", "err")
        return {"status": "no_key", "reason": "card_required", "wall": "card"}
    # leggi o genera la chiave
    res = await grabkey.grab_key(page, name, cfg, log)
    if not res.get("key"):
        # CARTA puo' comparire dopo il click su 'create' (deposito per creare) -> ricontrolla
        if await _needs_card(page):
            log.step("ESITO", "nessuna chiave", f"{name}: serve carta di credito", "err")
            return {"status": "no_key", "reason": "card_required", "wall": "card"}
        goal_key = f"trova e copia la API key di {name} (creane una nuova se serve)"
        # 1) FORM ONBOARDING generico e deterministico (crea org/team, consensi, submit):
        #    tanti "muri" sono solo un modulo da riempire. Un solo componente, nessun per-sito.
        await _wait_render(page)   # SPA: i campi (React) devono esistere prima di compilarli
        fr = await forms.complete_form(page, log)
        if fr.get("advanced"):
            await _wait_render(page)
            await cookies.dismiss(page, log)
            res = await grabkey.grab_key(page, name, cfg, log)
        # 2) RICETTE IMPARATE dai successi passati dell'AI (zero usage)
        if not res.get("key") and await ai_fallback.replay_learned(page, name, goal_key, log):
            res = await grabkey.grab_key(page, name, cfg, log)
        if not res.get("key"):
            # 3) IA come ultima spiaggia (mai fermarsi prima)
            log.step("CHIAVI", "non trovata in automatico", "passo all'IA", "ai")
            ar = await ai_fallback.ai_step(page, goal_key, 60, log, site=name)
            if ar.get("done"):
                res = await grabkey.grab_key(page, name, cfg, log)

    # ESITO
    if res.get("key"):
        log.step("ESITO", "chiave ottenuta", res["key"][:14] + "…", "key")
        return {"status": "ok", "key": res["key"]}
    log.step("ESITO", "nessuna chiave", name, "err")
    return {"status": "no_key"}
