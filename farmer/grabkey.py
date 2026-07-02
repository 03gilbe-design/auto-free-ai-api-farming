"""Leggi o genera API key. Deterministico per provider (regex formato + url dashboard).

Strategia (albero step 6):
  1. goto key_url provider
  2. cerca key gia visibile in chiaro (regex su input readonly/code/body)
  3. se mascherata -> click "Copia" -> leggi clipboard
  4. se assente -> click "Create/Crea" -> [nome 'pcAi'] -> [dropdown obbligatori] -> conferma
     -> loading -> rileggi (modal/barra/clipboard)
  5. niente -> needs_ai=True
Regex formato da gitleaks/formati noti.
"""
from __future__ import annotations
import re

KEY_NAME = "pcAi"

# provider -> {key_url, key_re, dropdowns}
# FONTE UNICA = sites.json (via registry). Niente piu' dati duplicati qui.
from .registry import providers_compat as _providers_compat
PROVIDERS = _providers_compat()
_GEN_TEXT = ["create api key", "create new key", "create key", "new key", "+ create", "generate",
             "crea chiave", "crea nuova chiave", "crea chiave api", "nuova chiave", "genera", "create"]
_COPY_TEXT = ["copy api key", "copy key", "copy token", "copy secret", "copia chiave", "copy", "copia"]

# CONFERMA creazione key. PREFISSO-verbo (non ancorato a fine): cattura "Generate Trial key",
# "Create new key", "Crea nuova chiave" — verbo all'inizio, parole in mezzo (key/trial/api/...).
# L'opener viene escluso a parte (testo identico salvato) + filtro DENY per Cancel/Annulla/Delete.
_CONFIRM_RX = re.compile(
    r"^\s*(submit|invia|generate|genera|create|crea|save|salva|"
    r"confirm|conferma|done|ok|continue|continua|add|aggiungi)\b", re.I)
# Bottoni da NON cliccare mai (negativo): annullamento/chiusura/distruzione.
_DENY_RX = re.compile(
    r"\b(cancel|annulla|close|chiudi|delete|elimina|remove|rimuovi|back|indietro|"
    r"dismiss|rename|rinomina|revoke|revoca)\b|^\s*[x✕✖×]\s*$", re.I)
# Spinner/loading: elementi e testi che indicano caricamento in corso.
_LOADING_TXT = ("loading", "please wait", "caricamento", "attendere", "initializing",
                "inizializzazione", "generating", "generazione")


async def _wait_settled(page, timeout_ms: int = 5000):
    """Aspetta che la pagina/parte sia ferma: niente spinner visibile e niente testo di loading.
    Poi 400ms di settle (SPA). Risolve il caso 'parte della pagina si sta ancora caricando'."""
    steps = max(1, timeout_ms // 400)
    for _ in range(steps):
        busy = False
        try:
            busy = await page.evaluate(r"""(txts) => {
              if (document.querySelector('[aria-busy=true]')) return true;
              const sp = [...document.querySelectorAll(
                '[class*=spin i],[class*=load i],[role=progressbar],svg[class*=animate i],[class*=skeleton i]')];
              if (sp.some(e => { const r=e.getBoundingClientRect();
                const st=getComputedStyle(e);
                return r.width>4 && r.height>4 && st.visibility!=='hidden' && st.display!=='none'; })) return true;
              const t = (document.body.innerText||'').toLowerCase();
              return txts.some(x => t.includes(x));
            }""", list(_LOADING_TXT))
        except Exception:
            busy = False
        if not busy:
            break
        await page.wait_for_timeout(400)
    await page.wait_for_timeout(400)


_MASK_CHARS = ("*", "•", "·", "●", "·", "•", "∙", "·", "x x")


def _is_masked(s: str) -> bool:
    return any(c in s for c in _MASK_CHARS) or "..." in s or "…" in s


def _looks_like_words(s: str) -> bool:
    """Il candidato sembra TESTO/nav e non una chiave? (es. 'ModelsDocsPricingGPUsChat').
    Una chiave vera ha entropia: cifre + maiuscole/minuscole mescolate, NON parole leggibili.
    Scarta se: nessuna cifra E ha confini-parola CamelCase tipici del testo UI."""
    if any(c.isdigit() for c in s):
        return False   # ha cifre -> probabile chiave vera (key_re specifici hanno prefissi+cifre)
    # nessuna cifra: conta le transizioni minuscola->Maiuscola (CamelCase del testo nav)
    camel = sum(1 for i in range(1, len(s)) if s[i-1].islower() and s[i].isupper())
    return camel >= 3   # 3+ parole attaccate = testo UI, non chiave


def _all_matches(rx, text):
    """Tutti i match non mascherati, piu lunghi prima (le key vere sono lunghe).
    Scarta i match che sembrano TESTO/nav (no cifre + CamelCase) — bug DeepInfra: il key_re
    generico [A-Za-z0-9]{32,} matchava 'ModelsDocsPricingGPUs...' del menu."""
    out = [m.group(0) for m in rx.finditer(text or "")
           if not _is_masked(m.group(0)) and not _looks_like_words(m.group(0))]
    return sorted(set(out), key=len, reverse=True)


async def _read_visible_key(page, key_re) -> str | None:
    rx = re.compile(key_re)
    # input/textarea con value + elementi di testo (code/pre/span dashboard)
    try:
        inps = page.locator("input[readonly], input[disabled], input[type=text], textarea, code, pre, [class*=key i], [class*=token i]")
        for i in range(min(await inps.count(), 30)):
            el = inps.nth(i)
            v = (await el.get_attribute("value")) or ""
            if not v:
                try:
                    v = await el.inner_text()
                except Exception:
                    v = ""
            for cand in _all_matches(rx, v):
                return cand
    except Exception:
        pass
    # body intero (ultima spiaggia): preferisci il match piu lungo non mascherato
    try:
        body = await page.inner_text("body")
        cands = _all_matches(rx, body)
        if cands:
            return cands[0]
    except Exception:
        pass
    return None


def _css_str(t: str) -> str:
    # stringa CSS sicura per :has-text (apostrofi/virgolette nel testo)
    return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _click_text(page, texts) -> bool:
    for t in texts:
        for tag in ["button", "a", "[role=button]", "[type=submit]"]:
            try:
                loc = page.locator(f"{tag}:has-text({_css_str(t)})").first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2500)
                    return True
            except Exception:
                continue
    return False


async def _read_clipboard(page) -> str | None:
    try:
        v = await page.evaluate("() => navigator.clipboard.readText()")
        return v if v else None
    except Exception:
        return None


def _key_in(text: str, key_re: str) -> str | None:
    """Estrae una key valida (non mascherata) da un testo, o None."""
    cands = _all_matches(re.compile(key_re), text or "")
    return cands[0] if cands else None


async def _grab_clipboard(page, key_re) -> str | None:
    """Reveal 'viewable one time' / key mascherata: click su 'Copy' -> legge la clipboard.
    Prova testo, poi ICONA copy (aria-label/title/data-icon, Cerebras non ha testo 'copy')."""
    clicked = await _click_text(page, _COPY_TEXT)
    if not clicked:
        # icona senza testo: aria-label/title 'copy', o bottone con dentro un svg copy
        for sel in ["[aria-label*='copy' i]", "[title*='copy' i]", "[data-icon*='copy' i]",
                    "button:has(svg[class*='copy' i])", "[class*='copy' i][role=button]"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    clicked = True
                    break
            except Exception:
                continue
    if clicked:
        await page.wait_for_timeout(500)
        cb = await _read_clipboard(page)
        return _key_in(cb, key_re) if cb else None
    return None


async def _type_into(el, name: str) -> bool:
    """Scrive nel campo digitando char-by-char (press_sequentially): i form React (OpenRouter)
    NON registrano fill() -> il bottone conferma resta disabilitato. Il type emula tasti reali.
    Ritorna True SOLO se il valore e' davvero attecchito (altrimenti il chiamante prova il prossimo
    campo: un fill no-op non deve cortocircuitare)."""
    try:
        await el.click(timeout=2000)
        if (await el.input_value()):           # pulisci SOLO se c'e' gia un valore sbagliato
            await el.fill("", timeout=1500)    # (il fill("") su React vuoto puo rompere il campo)
    except Exception:
        pass
    try:
        await el.press_sequentially(name, delay=30, timeout=3000)
    except Exception:
        try:
            await el.fill(name, timeout=2000)  # fallback
        except Exception:
            return False
    try:
        return (await el.input_value()) != ""
    except Exception:
        return False


async def _fill_key_name(page, name: str) -> bool:
    """Compila l'input NOME della key. Itera TUTTI i match (non .first: un input vuoto altrove
    nella pagina rubava il fill) e riempie il primo VISIBILE. Preferisce campi key/token-name
    (overwrite), poi name generico se vuoto. Scope al dialog se presente (primo piano).
    Usa _type_into (keystroke reali) per i form React."""
    root = page
    try:
        dlg = page.locator("[role=dialog], [aria-modal=true]").first
        if await dlg.count() and await dlg.is_visible():
            root = dlg
    except Exception:
        pass
    # se un dialog e' aperto cerca SOLO dentro (la barra di ricerca della pagina, fuori dal dialog,
    # ha placeholder 'Search by name...' e rubava il fill). Altrimenti tutta la pagina.
    roots = [root] if root is not page else [page]
    # specifici key/token-name: overwrite anche se gia pieno (es. nome persona auto-compilato)
    for sel in ["input[placeholder*='key name' i]", "input[placeholder*='token name' i]",
                "input[aria-label*='key name' i]", "input[name*=key i]", "input[name*=token i]"]:
        for r in roots:
            try:
                for el in await r.locator(sel).all():
                    if await el.is_visible() and not await _is_search(el):
                        if await _type_into(el, name):
                            return True
            except Exception:
                continue
    # name generico: riempi il primo visibile e VUOTO
    for sel in ["input[placeholder*='add name' i]", "input[name*=name i]", "input[placeholder*=name i]",
                "input[id*=name i]", "input[aria-label*=name i]", "input[placeholder*='key' i]",
                "input[type=text]"]:
        for r in roots:
            try:
                for el in await r.locator(sel).all():
                    if await el.is_visible() and not await el.input_value() and not await _is_search(el):
                        if await _type_into(el, name):
                            return True
            except Exception:
                continue
    # ULTIMA spiaggia: primo input TEXT-LIKE visibile e vuoto nel modale (OpenRouter: name input
    # senza attr type/name, placeholder 'e.g. \"Chatbot Key\"' -> nessun selettore sopra lo prende).
    for r in roots:
        try:
            for el in await r.locator("input:visible").all():
                tp = (await el.get_attribute("type") or "text").lower()
                if tp in ("password", "email", "number", "checkbox", "radio", "hidden", "file", "range", "tel", "search"):
                    continue
                if not await el.input_value() and not await _is_search(el):
                    if await _type_into(el, name):
                        return True
        except Exception:
            continue
    return False


async def _is_search(el) -> bool:
    """True se l'input e' una barra di ricerca (placeholder/aria/name/type con 'search'/'cerca')
    -> non e' il campo nome-key, va saltato."""
    try:
        if (await el.get_attribute("type") or "").lower() == "search":
            return True
        if (await el.get_attribute("role") or "").lower() == "searchbox":
            return True
        blob = " ".join([
            (await el.get_attribute("placeholder") or ""),
            (await el.get_attribute("aria-label") or ""),
            (await el.get_attribute("name") or ""),
            (await el.get_attribute("id") or ""),
        ]).lower()
        return ("search" in blob) or ("cerca" in blob)
    except Exception:
        return False


async def _select_required(page):
    """Seleziona la prima opzione reale in tendine obbligatorie vuote (Workspace/Project/Category).
    Gestisce <select> nativi e combobox custom (click -> prima opzione)."""
    try:
        await page.evaluate(r"""() => {
          for(const s of document.querySelectorAll('select')){
            if(s.selectedIndex>0) continue;
            const o=[...s.options].find(x=>x.value && !/select|choose|seleziona|--/i.test(x.text));
            if(o){ s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true})); }
          }
        }""")
    except Exception:
        pass
    for ph in ["select a workspace", "workspace", "select a project", "project", "seleziona",
               "select a category", "category", "choose"]:
        try:
            cb = page.locator(f"[role=combobox]:has-text({_css_str(ph)}), button:has-text({_css_str(ph)})").first
            if await cb.count() and await cb.is_visible():
                await cb.click(timeout=1500)
                await page.wait_for_timeout(600)
                opt = page.locator("[role=option], [role=listbox] li, [role=menuitem]").first
                if await opt.count() and await opt.is_visible():
                    await opt.click(timeout=1500)
                    await page.wait_for_timeout(500)
                    return
        except Exception:
            continue


async def _cloudflare_token(page, log=None) -> dict:
    """Ramo deterministico per Cloudflare Workers AI.
    Cerca il token/API token nel dashboard e, se presente, estrae anche l'Account ID.
    Questo flusso resta separato dal grab generico per non toccare gli altri provider."""
    if log:
        log.step("KEY", "ramo Cloudflare", "dashboard/token", "ok")
    # navigazione testuale: token / workers ai / api tokens
    for _ in range(3):
        for txt in ["Workers AI", "API Tokens", "API token", "Tokens", "Create token", "Create API Token"]:
            try:
                loc = page.locator(f"button:has-text('{txt}'), a:has-text('{txt}'), [role=button]:has-text('{txt}')").first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    await page.wait_for_timeout(1200)
                    break
            except Exception:
                continue
    # token leggibile in chiaro o via clipboard/copy
    key_re = r"(?:cf_[A-Za-z0-9_-]{20,}|[A-Za-z0-9_-]{40,})"
    k = await _read_visible_key(page, key_re)
    if not k:
        k = await _grab_clipboard(page, key_re)
    if not k:
        # prova copy button generico se il token e' mostrato in modal
        for sel in ["[aria-label*='copy' i]", "[title*='copy' i]", "button:has(svg[class*='copy' i])"]:
            try:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    await page.wait_for_timeout(600)
                    k = await _grab_clipboard(page, key_re)
                    if k:
                        break
            except Exception:
                continue
    if not k:
        return {"key": None, "needs_ai": True}
    acc = None
    try:
        body = await page.inner_text("body")
        m = re.search(r"\b([a-f0-9]{32})\b", body or "", re.I)
        if m:
            acc = m.group(1)
    except Exception:
        pass
    out = {"key": k, "needs_ai": False}
    if acc:
        out["account_id"] = acc
    return out


async def _clickables(page) -> list[dict]:
    """TUTTI gli elementi cliccabili visibili con il loro testo. Per SAPERE cosa c'e' davvero
    sulla pagina (niente piu' indovinare): ritorna [{i, text}]. Lo logghiamo come stato reale."""
    try:
        return await page.evaluate(r"""() => {
          const out = [];
          const els = document.querySelectorAll("button, a, [role=button], [role=menuitem], [role=link], [role=tab]");
          let i = 0;
          for (const e of els) {
            const r = e.getBoundingClientRect();
            const st = getComputedStyle(e);
            if (r.width < 4 || r.height < 4 || st.visibility === 'hidden' || st.display === 'none') continue;
            const t = (e.innerText || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g,' ');
            if (t) out.push({ i: i++, text: t.slice(0, 40) });
          }
          return out.slice(0, 60);
        }""")
    except Exception:
        return []


# TRAPPOLE: contengono "api" ma NON sono le chiavi (documentazione, riferimenti, ecc.)
_TRAP_RX = re.compile(r"reference|docs?|document|demo|community|blog|pricing|tutorial|guide|example|playground", re.I)


def _keyarea_score(t: str) -> int:
    """Punteggio 'quanto e' probabile che porti alle API KEY'. Deterministico, spiegabile.
    Esclude le trappole (API Reference = docs). 'Settings' vale come PERCORSO (le chiavi spesso
    stanno sotto Settings anche se il testo non dice 'key')."""
    tl = t.lower()
    if _TRAP_RX.search(tl):
        return 0  # trappola: "API Reference", "Docs"... NON e' la pagina chiavi
    if re.search(r"api[\s\-_]*key|secret\s*key|api\s*token|chiav[ei]\s*api", tl): return 5
    if "create" in tl and "key" in tl: return 5
    if re.search(r"\bkeys?\b", tl): return 4           # "Keys", "Manage keys"
    if re.search(r"api\s*access|access\s*token", tl): return 3
    if re.search(r"\bsettings?\b|impostazion", tl): return 2   # PERCORSO: chiavi sotto Settings
    if re.search(r"\bapi\b", tl): return 1             # generico "api" (debole, ma meglio di niente)
    return 0


async def _click_item(page, text: str) -> bool:
    """Clicca un elemento dato il suo testo (visto da _clickables). Prova get_by_text poi ruolo."""
    try:
        loc = page.get_by_text(text, exact=False).first
        if await loc.count() and await loc.is_visible():
            await loc.click(timeout=2500); return True
    except Exception:
        pass
    try:
        loc = page.get_by_role("button", name=re.compile(re.escape(text[:24]), re.I)).first
        if await loc.count() and await loc.is_visible():
            await loc.click(timeout=2500); return True
    except Exception:
        pass
    return False


async def _is_key_area_now(page) -> bool:
    """Sono ARRIVATO alla zona chiavi? Segnali deterministici: bottone 'Create/Generate key',
    testo 'secret key', o un campo/elemento che sembra una key. Cosi' verifico DOPO ogni click
    se ho trovato la strada giusta (esplora-e-verifica), invece di fidarmi del punteggio."""
    try:
        return await page.evaluate(r"""() => {
          const t = (document.body.innerText || '').toLowerCase();
          if (/secret key|create (new )?(api )?key|generate (api )?key|your api key|crea (nuova )?chiave/.test(t)) return true;
          // bottone esplicito di creazione chiave
          for (const b of document.querySelectorAll('button,a,[role=button]')) {
            const x = (b.innerText||'').toLowerCase();
            if (/create.*key|generate.*key|new api key|crea.*chiave/.test(x)) return true;
          }
          return false;
        }""")
    except Exception:
        return False


async def _open_key_section(page, log=None, depth: int = 0) -> bool:
    """Modulo ESPLORA-E-VERIFICA (idea utente: non indovinare, NAVIGA e controlla).
    1) DUMPA tutti i cliccabili (stato reale, sempre loggato).
    2) Punteggia (esclude trappole). Prende i TOP candidati.
    3) Per ogni candidato in ordine: CLICCA -> sei arrivato alle chiavi? (_is_key_area_now)
         SI  -> fatto.
         NO  -> TORNA INDIETRO (go_back) e prova il prossimo. (backtracking)
       Se un candidato e' un PERCORSO che si espande in-page (Settings accordion), ricorsione.
    Vale lo stesso schema per login/form: prova candidato, verifica esito, altrimenti backtrack."""
    if await _is_key_area_now(page):
        return True
    items = await _clickables(page)
    if log:
        sample = " | ".join(it["text"] for it in items[:20])
        log.dbg("cliccabili visti", n=len(items), sample=sample, depth=depth)
        log.step("KEY", "esploro pagina", f"{len(items)} elementi (liv {depth})", "info")
    scored = sorted(((_keyarea_score(it["text"]), it["text"]) for it in items if _keyarea_score(it["text"]) > 0),
                    key=lambda x: -x[0])
    if not scored:
        return False
    start_url = page.url
    tried = set()
    # prova i top candidati (max 4): navigali UNO A UNO finche' uno porta alle chiavi
    for score, txt in scored[:4]:
        if txt in tried:
            continue
        tried.add(txt)
        if log: log.step("KEY", "provo", f"{txt} (score {score})", "ai")
        if not await _click_item(page, txt):
            continue
        await _wait_settled(page, 2500)
        # ARRIVATO? verifica deterministica
        if await _is_key_area_now(page):
            if log: log.step("KEY", "trovata sezione chiavi", txt, "ok")
            return True
        # il candidato si e' espanso in-page (Settings)? cerca piu' a fondo
        if depth < 2 and score <= 2:
            if await _open_key_section(page, log, depth + 1):
                return True
        # NON era la strada -> torna indietro e prova il prossimo (backtracking)
        try:
            if page.url != start_url:
                await page.go_back(timeout=8000)
                await _wait_settled(page, 2000)
            else:
                await page.goto(start_url, timeout=12000, wait_until="domcontentloaded")
                await _wait_settled(page, 2000)
        except Exception:
            pass
    return await _is_key_area_now(page)


async def grab_key(page, provider: str, cfg: dict | None = None, log=None) -> dict:
    cfg = cfg or PROVIDERS.get(provider, {})
    key_re = cfg.get("key_re", r"[A-Za-z0-9_\-]{24,}")

    if provider == "Cloudflare Workers AI":
        res = await _cloudflare_token(page, log)
        if res.get("key"):
            return res

    # 0. ASPETTA che la pagina sia ferma: alcune dashboard redirigono ancora (OpenRouter
    #    /keys -> /workspaces/default/keys) o caricano la lista key in ritardo. Partire troppo
    #    presto = opener non pronto / read su pagina incompleta. (caso 'pagina si sta caricando')
    await _wait_settled(page, 6000)

    # 0b. APRI SEZIONE CHIAVI (esplora-e-verifica) SOLO se il sito lo richiede (key_panel: true
    #     nel registro, es. AI21 dashboard SPA). Per i provider che gia' funzionano NON si attiva
    #     -> zero regressione (Groq/Cohere/... restano sul flow collaudato). OPT-IN, non globale.
    if cfg.get("key_panel"):
        await _open_key_section(page, log)

    # 1. key gia visibile in chiaro
    k = await _read_visible_key(page, key_re)
    if k:
        if log: log.step("KEY", "letta in chiaro", provider, "key")
        return {"key": k, "needs_ai": False}
    # 2. key esistente MASCHERATA -> 1 click Copy -> clipboard
    k = await _grab_clipboard(page, key_re)
    if k:
        if log: log.step("KEY", "letta da clipboard", provider, "key")
        return {"key": k, "needs_ai": False}

    # 3. genera nuova: apri l'opener (Create/Crea/Generate...) e TIENI il suo testo
    #    (serve per non ri-cliccarlo come fosse la conferma: spesso identico, es. Mistral).
    opener_txt = await _click_opener(page, _GEN_TEXT)
    if opener_txt is not None:
        await _wait_settled(page, 3000)
        # alcuni opener sono una TENDINA (Fireworks: "Create API Key" -> menu "API Key").
        # scegli la voce semplice, MAI "Service Account".
        try:
            for mi in ["api key", "secret key", "personal access"]:
                item = page.locator(
                    f"[role=menuitem]:has-text({_css_str(mi)}), [role=option]:has-text({_css_str(mi)}), "
                    f"[role=menu] a:has-text({_css_str(mi)}), [role=menu] li:has-text({_css_str(mi)})").first
                if await item.count() and await item.is_visible():
                    if "service account" in ((await item.inner_text()) or "").lower():
                        continue
                    await item.click(timeout=2000)
                    await _wait_settled(page, 2500)
                    break
        except Exception:
            pass
        # modal: nome key + tendine obbligatorie (Workspace/Project)
        await _fill_key_name(page, KEY_NAME)
        await _select_required(page)
        # conferma. Insidie reali: (1) DEBOUNCE ~1s, bottone puo stare FUORI dal dialog (Groq) -> POLL.
        # (2) il testo conferma puo avere parole in mezzo ("Generate Trial key"/"Crea nuova chiave")
        #     -> prefisso-verbo + filtro DENY (Cancel/Annulla) + esclusione testo-opener.
        for _attempt in range(2):
            clicked = False
            for _ in range(10):  # ~5s debounce
                # READ-FIRST: se il reveal con la key e' gia in primo piano, leggi e fermati
                # (evita di cliccare lo SFONDO dietro l'overlay).
                k = await _read_visible_key(page, key_re)
                if k:
                    if log: log.step("KEY", "generata", provider, "key")
                    return {"key": k, "needs_ai": False}
                if await _click_confirm(page, opener_txt):
                    clicked = True
                    break
                await _select_required(page)  # un warning puo rivelare una tendina obbligatoria
                await page.wait_for_timeout(500)
            await _wait_settled(page, 3000)
            # la key compare nel reveal 1-3s DOPO il submit (Groq ~2s): POLL, non lettura singola.
            k = None
            for _ in range(10):
                k = await _read_visible_key(page, key_re)
                if k:
                    break
                await page.wait_for_timeout(600)
            if not k:
                k = await _grab_clipboard(page, key_re)  # reveal dietro "Copy" -> 1 click
            if k:
                if log: log.step("KEY", "generata", provider, "key")
                return {"key": k, "needs_ai": False}
            if not clicked:
                break

    if log: log.step("KEY", "non ottenuta", provider, "ai")
    return {"key": None, "needs_ai": True}


_OPENER_RX = re.compile(r"\b(create|generate|new|add|get|crea|genera|nuov\w*|aggiungi|ottieni)\b.*\b(api\s*)?(key|token|chiave)\b", re.I)


async def _click_opener(page, texts) -> str | None:
    """Clicca il bottone che apre la creazione key. Ritorna il SUO testo (per escluderlo
    poi dalla conferma), o None. 2 TIER: 1) frasi note (texts) 2) FALLBACK regex semantica
    (verbo create/generate/new/add/get + key/token) -> cattura 'Get Your API Key' e varianti
    non in lista, senza inseguire frasi per-sito."""
    # 1) frasi note
    for t in texts:
        for tag in ["button", "a", "[role=button]"]:
            try:
                loc = page.locator(f"{tag}:has-text({_css_str(t)})").first
                if await loc.count() and await loc.is_visible():
                    txt = ((await loc.inner_text()) or t).strip()
                    await loc.click(timeout=2500)
                    return txt
            except Exception:
                continue
    # 2) FALLBACK regex semantica sul testo visibile (verbo + key/token)
    try:
        cand = await page.evaluate(r"""(rxSrc) => {
          const rx = new RegExp(rxSrc, 'i');
          for (const e of document.querySelectorAll("button, a, [role=button]")) {
            const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
            if (r.width<4||r.height<4||s.visibility==='hidden'||s.display==='none') continue;
            const t=(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim();
            if (t && rx.test(t)) return t;
          }
          return null;
        }""", _OPENER_RX.pattern)
        if cand:
            loc = page.get_by_text(cand, exact=False).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=2500)
                return cand.strip()
    except Exception:
        pass
    return None


async def _click_confirm(page, opener_txt: str | None) -> bool:
    """Clicca la conferma: prima DENTRO il dialog (primo piano), poi fuori (Groq Submit fuori-dialog).
    Match = prefisso-verbo (_CONFIRM_RX) AND non-DENY AND testo != opener (no ri-apertura)."""
    # (scope, escludi_opener): nel DIALOG l'opener non c'e' (e' dietro l'overlay) -> NON escluderlo
    # (Mistral: confirm ha lo stesso testo dell'opener). Nello scope PAGE invece escludilo (Groq/Cohere:
    # evita di ri-cliccare l'opener e riaprire il modal).
    scopes = []
    try:
        dlg = page.locator("[role=dialog], [aria-modal=true]").first
        if await dlg.count() and await dlg.is_visible():
            scopes.append((dlg, False))
    except Exception:
        pass
    scopes.append((page, True))
    opener_norm = (opener_txt or "").strip().lower()
    for scope, excl_opener in scopes:
        try:
            btns = scope.locator("button, [role=button], [type=submit]")
            n = await btns.count()
        except Exception:
            continue
        # SambaNova: la conferma del modale ha lo STESSO testo dell'opener ("Create API Key") e NON
        # e' un role=dialog. Quindi nello scope page non escludere TUTTE le occorrenze del testo-opener:
        # salta solo la PRIMA (l'opener vero, sempre nel DOM prima) e clicca la successiva (la conferma,
        # appare dopo). opener_seen traccia se abbiamo gia saltato l'opener.
        opener_seen = False
        for j in range(min(n, 150)):
            bb = btns.nth(j)
            try:
                if not (await bb.is_visible() and await bb.is_enabled()):
                    continue
                txt = ((await bb.inner_text()) or "").strip()
                if not txt:
                    txt = (await bb.get_attribute("aria-label") or "").strip()
                low = txt.lower()
                if not txt:
                    continue
                if excl_opener and low == opener_norm and not opener_seen:
                    opener_seen = True   # salta SOLO la prima (l'opener), poi accetta i gemelli
                    continue
                if _DENY_RX.search(txt):
                    continue
                if _CONFIRM_RX.match(txt):
                    await bb.click(timeout=2000)
                    return True
            except Exception:
                continue
    return False
