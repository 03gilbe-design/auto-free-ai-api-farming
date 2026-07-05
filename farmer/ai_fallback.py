"""AI fallback (text-first, vision as last resort). page_to_text -> LLM picks 1 action -> exec.

Runs on the self-harvested key pool (farmer/keypool.py): any OpenAI-compatible key the tool
already grabbed powers the fallback, rotating on rate-limit. An optional GROQ_KEY seeds the
first run. No LLM key available -> no-op ({"done":False,"reason":"ai_unavailable"}).

SECURITY: the account password is never put in the LLM prompt — the deterministic form filler
(forms.py) types it locally; the model is told to use an empty value for password fields.
"""
from __future__ import annotations
import base64, json, os, re, time, urllib.request, urllib.error
from pathlib import Path
from .page2text import page_to_text_all_frames
from . import forms, keypool


def _post(base: str, model: str, key: str, messages: list, timeout: int = 30) -> dict | None:
    """One OpenAI-compatible chat call. Returns parsed dict, or raises on HTTP error so the
    caller can decide whether to rotate to the next key."""
    body = json.dumps({
        "model": model, "messages": messages,
        "temperature": 0, "max_tokens": 200,
        "response_format": {"type": "json_object"},
    }).encode()
    # UA Mozilla obbligatorio: senza, alcuni provider (Cloudflare front) rispondono 403 err 1010
    req = urllib.request.Request(base, data=body,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return _parse(data["choices"][0]["message"]["content"])


def _ask_pool(messages: list, vision: bool = False, log=None) -> dict | None:
    """Ask the LLM using the SELF-HARVESTED key pool, rotating on failure.
    401/403 = dead key -> next provider. 429/5xx = rate/transient -> one backoff then next."""
    pool = keypool.clients(vision=vision)
    if not pool:
        return None
    for base, model, key, prov in pool:
        for attempt in range(2):
            try:
                out = _post(base, model, key, messages, timeout=40 if vision else 30)
                if out is not None:
                    if log and prov != "groq":
                        log.dbg("ai via harvested key", provider=prov)
                    return out
                break  # empty parse -> try next provider
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    break  # dead/invalid key -> next provider immediately
                if e.code == 429 or e.code >= 500:
                    time.sleep(1.5 * (attempt + 1)); continue
                break
            except Exception:
                time.sleep(1.0 * (attempt + 1)); continue
    return None


def _ask_vision(prompt: str, png_b64: str, retries: int = 2, log=None) -> dict | None:
    """Vision tier: attach the screenshot (only vision-capable pool keys are used).
    Rotates over the pool like _ask; None if no vision-capable key is available."""
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
    ]
    return _ask_pool([{"role": "user", "content": content}], vision=True, log=log)


async def _vision_rescue(page, goal: str, log=None) -> dict:
    """Un colpo di vista: screenshot -> llama-4-scout multimodale -> 1 azione -> esegui.
    Tier finale; non un loop (la vista costa). done/giveup/azione singola."""
    try:
        png = await page.screenshot(type="png")
    except Exception as e:
        if log: log.dbg("vision screenshot fail", err=str(e))
        return {"done": False, "reason": "vision_no_shot"}
    b64 = base64.b64encode(png).decode()
    prompt = (_SYS_VISION.format(goal=goal, acct=forms.EMAIL, nm=forms.NAME))
    act = _ask_vision(prompt, b64, log=log)
    if not act:
        if log: log.step("VISION", "no risposta", "", "warn")
        return {"done": False, "reason": "vision_no_reply"}
    a = act.get("action")
    if log: log.step("VISION", "azione", str(act)[:50], "ai")
    if a == "done":
        return {"done": True}
    if a == "giveup":
        return {"done": False, "reason": "vision_giveup"}
    ran = await _exec(page, act, log)
    await page.wait_for_timeout(1200)
    return {"done": bool(ran), "reason": "vision_acted" if ran else "vision_exec_fail"}


def _as_dict(j):
    """L'IA a volte risponde con un ARRAY [{...}] invece di un oggetto {...}: prendi il
    primo dict. Evita il crash 'list object has no attribute get' (uccideva Glhf/AI21)."""
    if isinstance(j, dict):
        return j
    if isinstance(j, list):
        for it in j:
            if isinstance(it, dict):
                return it
    return None


def _parse(txt: str) -> dict | None:
    try:
        return _as_dict(json.loads(txt))
    except Exception:
        pass
    m = re.search(r"[\{\[].*[\}\]]", txt or "", re.S)  # oggetto O array
    if m:
        try:
            return _as_dict(json.loads(m.group(0)))
        except Exception:
            return None
    return None


def _ask(prompt: str, log=None) -> dict | None:
    """Text-only ask over the self-harvested key pool (rotates on rate-limit/invalid)."""
    return _ask_pool([{"role": "user", "content": prompt}], vision=False, log=log)


_SYS = """Sei un agente che automatizza signup per API key gratuite. Account: {acct}, nome {nm}.
La password NON ti viene fornita e la inserisce il codice in automatico: se serve compilare un
campo password usa value "" (stringa vuota); NON inventare ne' scrivere mai una password.
Goal: {goal}
Pagina corrente (testo compatto, [X]=bottone <X>=link *X*=campo VUOTO *X="v"*=campo GIA'
riempito col valore v (non ricompilarlo, passa al prossimo campo/bottone) V-X-V=tendina,
{{ref:eN}}=id stabile):
{page}
Rispondi SOLO JSON con UNA azione. Se l'elemento ha un {{ref:eN}} accanto, INCLUDI SEMPRE "ref"
con quel valore esatto (es. "e3") oltre al testo — e' piu' affidabile del testo da solo:
{{"action":"click","text":"testo esatto bottone/link","ref":"e3"}}
{{"action":"fill","placeholder":"testo campo","value":"valore","ref":"e5"}}
{{"action":"check","text":"testo vicino alla checkbox","ref":"e7"}}  per spuntare caselle [ ] (es. Accetto i Termini)
{{"action":"radio","text":"testo vicino al radio","ref":"e8"}}  per scegliere UNA opzione ( ) tra piu' esclusive
{{"action":"select","option":"testo opzione da scegliere","ref":"e9"}}  per una tendina V-Label-V
{{"action":"goto","url":"https://..."}}
{{"action":"done"}}  se goal raggiunto
{{"action":"giveup"}} se impossibile
REGOLE: usa SOLO testo/ref che vedi ELENCATO sopra; NON inventare bottoni assenti. Se NON c'e' un
bottone Google nella lista, NON scriverlo: compila il modulo email/password presente o cerca il
campo email per ricevere un token. Google solo se compare davvero. Mai cookie/privacy/social.
PRIORITA' DI AVANZAMENTO: se un campo mostra gia' *X="v"* o un radio/checkbox e' gia' selezionato
E c'e' un bottone Continue/Next/Avanti/Continua/Skip/Salta visibile -> CLICCALO SUBITO, non
toccare altri campi opzionali (es. campo libero "specifica altro" quando hai gia' scelto un
radio). Rispondere a UNA domanda per pagina basta quasi sempre per sbloccare Continue."""

_SYS_VISION = """Sei un agente che automatizza signup per API key gratuite. Account: {acct}, nome {nm}.
La password NON ti viene fornita (la inserisce il codice): per un campo password usa value "";
NON scrivere mai una password.
Goal: {goal}
GUARDA lo SCREENSHOT della pagina e scegli UNA azione. Usa il testo VISIBILE dei bottoni/link.
Rispondi SOLO JSON:
{{"action":"click","text":"testo esatto visibile"}}
{{"action":"fill","placeholder":"testo vicino al campo","value":"valore"}}
{{"action":"check","text":"testo vicino alla checkbox"}}  per spuntare caselle (es. Accetto i Termini)
{{"action":"radio","text":"testo vicino al radio"}}  per scegliere UNA opzione tra piu' esclusive
{{"action":"goto","url":"https://..."}}
{{"action":"done"}}  se il goal e' raggiunto (es. API key visibile)
{{"action":"giveup"}} se c'e' un muro (captcha immagine, telefono)
REGOLE: agisci SOLO su elementi che VEDI nello screenshot; non inventare un bottone Google se non
c'e'. Se vedi solo un campo email/token, compila quello. Google solo se visibile. Mai cookie/privacy/social."""


_TAG2TYPE = {"button": "button", "a": "link", "[role=button]": "button", "*": "button"}


def _css_text(t: str) -> str:
    """Stringa sicura per :has-text(...) e attribute-selector *=...: se il testo (dell'AI o di
    un campo reale) contiene un apostrofo (es. \"Sono d'accordo\", \"I've read\"), l'interpolazione
    grezza f\"...'{t}'...\" spezza il selettore CSS a meta' stringa -> match silenziosamente
    sbagliato o eccezione. json.dumps produce una stringa JS a doppi apici correttamente
    escapata, che Playwright accetta ovunque serva un valore testuale nel selettore."""
    return json.dumps(t or "")


def _strip_deco(s: str) -> str:
    """page2text renders elements with decorators the AI copies verbatim into its action
    ([Text]=button, <Text>=link, *Text*=field, #Text=heading) — strip them before building a
    Playwright selector, or ':has-text(\"[Close]\")' never matches the real DOM text 'Close'.
    This was the actual reason live runs stalled right at the create-key modal (0 keys
    extracted even after reaching it): _exec silently failed to match anything."""
    return re.sub(r"^[\[\<\*#\s]+|[\]\>\*\s]+$", "", s or "").strip()


_FILLABLE_TAGS = {"input", "textarea"}


async def _exec_by_ref(page, ref: str, require_fillable: bool = False):
    """Risolve un ref stabile (data-af-ref, iniettato da page2text al momento della lettura) in
    un Locator visibile, o None se assente/non piu' visibile. Un solo selettore diretto, niente
    ambiguita' testuale: stesso pattern di Playwright MCP / browser-use ('snapshot + ref').

    require_fillable=True (usato da 'fill'): rifiuta un elemento che non e' input/textarea,
    invece di tentare .fill() su un bottone e poi cadere nel fallback "qualsiasi textbox
    visibile" — che una volta ha scritto un'email nel campo SBAGLIATO (visto live: l'AI ha
    provato a 'fill' un badge account [nome@mail] non un vero campo, il fallback generico ha
    trovato ed edited il campo testo libero di un'altra domanda della pagina)."""
    try:
        loc = page.locator(f"[data-af-ref='{ref}']").first
        if not (await loc.count() and await loc.is_visible()):
            return None
        if require_fillable:
            tag = await loc.evaluate("el => el.tagName.toLowerCase()")
            if tag not in _FILLABLE_TAGS:
                return None
        return loc
    except Exception:
        return None


async def _exec(page, act: dict, log=None) -> str | None:
    """Esegue l'azione. Ritorna il TIPO di elemento toccato (textbox/button/link/nav) se riuscita,
    None se fallita. Il tipo serve a learned.record (elemento gia' visto).

    Se act ha un "ref" (id stabile assegnato da page2text sull'ultimo snapshot), prova quello
    per PRIMO: risolve direttamente l'elemento via [data-af-ref='eN'], senza passare dal testo
    (quindi immune al bug dei decoratori [Text]/<Text> copiati dall'AI). Se il ref manca o e'
    stale (pagina cambiata dall'ultimo snapshot), cade nella cascata per-testo sotto — nessuna
    regressione, e' un livello di robustezza aggiuntivo, non un sostituto."""
    a = act.get("action")
    ref = act.get("ref")
    if ref and a in ("click", "check", "radio"):
        loc = await _exec_by_ref(page, ref)
        if loc is not None:
            try:
                if a == "click":
                    try:
                        if not await loc.is_enabled():
                            ref = None  # disabled: cadi nella cascata testo (puo' spuntare consensi prima)
                        else:
                            await loc.click(timeout=3000)
                            return "button"
                    except Exception:
                        ref = None
                else:  # check / radio: stesso trattamento (entrambi Playwright .check())
                    kind = "checkbox" if a == "check" else "radio"
                    try:
                        await loc.check(force=True, timeout=2500)
                        return kind
                    except Exception:
                        try:
                            await loc.click(force=True, timeout=2000)
                            return kind
                        except Exception:
                            ref = None
            except Exception:
                ref = None
    ref_blocked_fill = False
    if ref and a == "fill":
        loc = await _exec_by_ref(page, ref, require_fillable=True)
        if loc is not None:
            try:
                await loc.fill(act.get("value", ""), timeout=2500)
                return "textbox"
            except Exception:
                pass
        else:
            # ref presente ma punta a qualcosa che NON e' un vero campo (es. un bottone/badge
            # account) -> l'AI ha sbagliato bersaglio. NON degradare al fallback "qualsiasi
            # textbox visibile": scriverebbe il valore nel campo SBAGLIATO della pagina (visto
            # live: un fill fallito sul badge account ha finito per riscrivere il campo testo
            # libero di un'altra domanda). Meglio un fallimento pulito -> fail_streak, riprova.
            ref_blocked_fill = True
    elif ref and a == "select":
        loc = await _exec_by_ref(page, ref)
        if loc is not None:
            opt = _strip_deco(act.get("option", "") or act.get("value", ""))
            try:
                await loc.select_option(label=opt, timeout=2500)
                return "select"
            except Exception:
                try:
                    await loc.select_option(value=opt, timeout=2000)
                    return "select"
                except Exception:
                    pass
    try:
        if a == "click":
            t = _strip_deco(act.get("text", ""))
            for tag in ["button", "a", "[role=button]", "*"]:
                loc = page.locator(f"{tag}:has-text({_css_text(t)})").first
                if await loc.count() and await loc.is_visible():
                    # bottone disabled (es. submit bloccato finche' non spunti i termini):
                    # non forzare, segnala fallimento cosi' la catena spunta prima la checkbox.
                    try:
                        if not await loc.is_enabled():
                            return None
                    except Exception:
                        pass
                    await loc.click(timeout=3000)
                    return _TAG2TYPE[tag]
        elif a == "fill":
            if ref_blocked_fill:
                return None  # ref puntava a un non-campo: fallimento pulito, no fallback a caso
            ph = _strip_deco(act.get("placeholder", ""))
            val = act.get("value", "")
            # cascata: placeholder -> aria-label -> name/id -> textbox visibile dentro una modale
            # aperta (il caso reale che bloccava Groq: il campo "Key name" nel dialog create-key
            # non ha un placeholder che matcha) -> qualsiasi textbox visibile come ultima spiaggia.
            phq = _css_text(ph)
            cands = [
                f"input[placeholder*={phq} i], textarea[placeholder*={phq} i]",
                f"[aria-label*={phq} i]",
                f"input[name*={phq} i], input[id*={phq} i]",
                "[role=dialog] input:visible, dialog input:visible, [aria-modal='true'] input:visible",
                "input:visible, textarea:visible, [role=textbox]:visible",
            ] if ph else [
                "[role=dialog] input:visible, dialog input:visible, [aria-modal='true'] input:visible",
                "input:visible, textarea:visible, [role=textbox]:visible",
            ]
            for sel in cands:
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.fill(val, timeout=2500)
                    return "textbox"
        elif a == "check":
            # SPUNTA una checkbox (es. "Accetto i Termini"). L'input VERO spesso e' nascosto
            # (opacity 0, stile custom sopra) -> is_visible()=False. Percio': prima l'input per
            # ruolo/tipo con FORCE (bypassa la visibilita'), poi la label/wrapper visibile cliccabile.
            t = _strip_deco(act.get("text", ""))
            tq = _css_text(t)
            # 1) input checkbox associato al testo, o il primo: check(force) anche se nascosto
            for sel in (f"label:has-text({tq}) input[type=checkbox]",
                        f"input[type=checkbox][aria-label*={tq} i]",
                        "input[type=checkbox]", "[role=checkbox]"):
                loc = page.locator(sel).first
                if await loc.count():
                    try:
                        await loc.check(force=True, timeout=2500)
                        return "checkbox"
                    except Exception:
                        try:
                            await loc.click(force=True, timeout=2000)
                            return "checkbox"
                        except Exception:
                            pass
            # 2) fallback: clicca la label/wrapper VISIBILE (attiva la checkbox custom)
            for sel in (f"label:has-text({tq})", f"*:has-text({tq})"):
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    return "checkbox"
        elif a == "radio":
            # SELEZIONA un radio (gruppo di scelta esclusiva, es. "What is your role?"). Prima
            # non esisteva nessuna azione dedicata: l'AI provava a "click" sul testo del radio,
            # a volte funzionava per caso (colpiva la label), a volte no (colpiva un wrapper che
            # non propaga il click all'input reale) -> radio mai selezionato, la pagina non
            # avanzava, l'AI ripeteva l'unico altro campo compilabile finche' il loop-guard non
            # si arrendeva (visto live: pagina "role" di Cohere). Stesso pattern verificato dei
            # checkbox: input associato per label/aria-label PRIMA, wrapper visibile come fallback.
            t = _strip_deco(act.get("text", ""))
            tq = _css_text(t)
            for sel in (f"label:has-text({tq}) input[type=radio]",
                        f"input[type=radio][aria-label*={tq} i]",
                        "input[type=radio]", "[role=radio]"):
                loc = page.locator(sel).first
                if await loc.count():
                    try:
                        await loc.check(force=True, timeout=2500)
                        return "radio"
                    except Exception:
                        try:
                            await loc.click(force=True, timeout=2000)
                            return "radio"
                        except Exception:
                            pass
            for sel in (f"label:has-text({tq})", f"*:has-text({tq})"):
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    return "radio"
        elif a == "select":
            # tendina nativa <select>: nessun ref valido -> ricostruisce un locator dal testo
            # dell'opzione desiderata (fallback raro, il ramo ref-first sopra copre il caso normale).
            opt = _strip_deco(act.get("option", "") or act.get("value", ""))
            t = _strip_deco(act.get("text", ""))
            cand = page.locator(f"select:near(:text({_css_text(t)}))") if t else page.locator("select")
            loc = cand.first
            if await loc.count():
                try:
                    await loc.select_option(label=opt, timeout=2500)
                    return "select"
                except Exception:
                    try:
                        await loc.select_option(value=opt, timeout=2000)
                        return "select"
                    except Exception:
                        pass
        elif a == "goto":
            await page.goto(act["url"], timeout=15000)
            return "nav"
    except Exception as e:
        if log: log.dbg("ai exec fail", act=act, err=str(e))
    return None


_ELORD = {"textbox": 0, "checkbox": 1, "radio": 1, "select": 1, "button": 2, "link": 3, "nav": 4}


async def replay_learned(page, site: str, goal: str, log=None) -> int:
    """PRIMA di Groq: riprova le ricette gia' imparate per questo sito+punto-mappa.
    Deterministico, zero usage AI. Applica OGNI ricetta UNA volta, in ordine logico
    (prima campi/checkbox, poi bottoni submit) -> un form si compila e si invia da solo.
    Ritorna quante azioni sono andate a segno."""
    if not site:
        return 0
    try:
        from . import learned
    except Exception:
        return 0
    hits = 0
    for _ in range(4):   # ripeti su nuove pagine (dopo un submit ne compare un'altra)
        recs = learned.suggest(site, page.url, goal)
        if not recs:
            break
        # ordine logico: campi/checkbox PRIMA del bottone che invia; niente doppioni
        recs = sorted(recs, key=lambda r: _ELORD.get(r.get("el_type"), 9))
        before_url = page.url
        applied = 0
        for r in recs:
            el = await _exec(page, r.get("action", {}), log)
            if el:
                applied += 1; hits += 1
                if log: log.dbg("replay learned", action=r.get("action"), el=el)
                await page.wait_for_timeout(700)
                if page.url != before_url:   # un submit ha cambiato pagina -> ricomincia il set
                    break
        if applied == 0 or page.url == before_url:
            break   # nessuna ricetta ha agito, o nessun avanzamento di pagina -> stop
    if hits and log:
        log.step("LEARNED", "ricette riusate", f"{hits} azioni (no AI)", "ok")
    return hits


async def ai_step(page, goal: str, max_steps: int = 12, log=None, deadline_s: float = 75.0,
                  site: str = "") -> dict:
    """AI fallback con FAIL-FAST: mai appendere.
    - DEADLINE wall-clock (default 75s): scaduta -> stop, non importa quanti step.
    - LOOP-DETECTION: la stessa azione RIUSCITA due volte di fila = loop reale -> giveup.
      Un'azione FALLITA ripetuta (es. _exec non trova l'elemento) NON e' un loop: e' un
      fallimento di esecuzione, e va trattato separatamente (altrimenti un singolo selettore
      che non matcha abortisce il sito anche quando l'AI aveva gia raggiunto l'obiettivo -
      era il bug che azzerava le key estratte su Groq pur arrivando al modale create-key).
    - Se la pagina (testo) non cambia per 3 step, l'AI sta girando a vuoto -> tenta la vista.
    - max_steps basso (12): un muro non si sblocca con 100 tentativi lenti.
    """
    if not keypool.available():
        if log: log.step("AI", "non disponibile", "no LLM key (seed GROQ_KEY or harvest one first)", "warn")
        return {"done": False, "reason": "ai_unavailable"}
    if log: log.step("AI", "in campo", goal[:50], "ai")
    t0 = time.time()
    prev_txt = None
    stuck = 0
    last_ok_act = None    # ultima azione ESEGUITA CON SUCCESSO (loop-guard vero)
    fail_streak = 0        # fallimenti di _exec consecutivi (indipendente dal loop-guard)
    for i in range(max_steps):
        if time.time() - t0 > deadline_s:
            if log: log.step("AI", "stop deadline", f"{i} step / {int(deadline_s)}s", "warn")
            return {"done": False, "reason": "ai_deadline"}
        page_txt = await page_to_text_all_frames(page, max_lines=45)
        # loop-detection: pagina ferma = AI non sta concludendo nulla
        if page_txt == prev_txt:
            stuck += 1
            if stuck >= 3:
                if log: log.step("AI", "testo bloccato", "tento la VISTA", "ai")
                # TIER VISION: il testo non basta -> guarda lo screenshot (1 colpo)
                v = await _vision_rescue(page, goal, log)
                if v.get("done"):
                    return {"done": True}
                if v.get("reason") == "vision_acted":
                    stuck = 0; prev_txt = None; continue  # la vista ha mosso: riprova col testo
                return {"done": False, "reason": "ai_no_progress"}
        else:
            stuck = 0
        prev_txt = page_txt
        # DEBUG: salva cosa VEDE l'AI (page2text), non solo l'azione scelta. Cosi' si capisce
        # se l'AI allucina (bottone inesistente) o se page2text rende male la pagina.
        if log: log.dbg("ai vede", step=i, page=page_txt)
        act = _ask(_SYS.format(goal=goal, page=page_txt, acct=forms.EMAIL, nm=forms.NAME), log=log)
        if not act:
            if log: log.step("AI", "no risposta", f"step {i}", "warn")
            return {"done": False, "reason": "ai_no_reply"}
        a = act.get("action")
        if log: log.dbg("ai act", step=i, act=act)
        if a == "done":
            if log: log.step("AI", "done", f"{i} step", "ok")
            return {"done": True}
        if a == "giveup":
            if log: log.step("AI", "giveup", f"{i} step", "warn")
            return {"done": False, "reason": "ai_giveup"}
        # stessa azione ESEGUITA CON SUCCESSO ripetuta = loop reale -> giveup.
        # (un'azione fallita ripetuta NON conta qui: la gestisce fail_streak sotto)
        if act == last_ok_act:
            if log: log.step("AI", "azione ripetuta", "loop", "warn")
            return {"done": False, "reason": "ai_repeat"}
        url_before = page.url
        el_type = await _exec(page, act, log)
        if el_type:
            fail_streak = 0
            last_ok_act = act
        else:
            fail_streak += 1
            if log: log.dbg("ai act non eseguita", act=act, fail_streak=fail_streak)
            if fail_streak >= 3:
                if log: log.step("AI", "esecuzione fallita 3x", "azione non eseguibile, giveup", "warn")
                return {"done": False, "reason": "ai_exec_fail"}
        await page.wait_for_timeout(1000)
        # APPRENDIMENTO: azione riuscita che ha fatto AVANZARE (url cambiato, o fill/nav) ->
        # salvala come ricetta deterministica per le prossime volte (meno usage AI).
        if el_type and site:
            advanced = page.url != url_before or el_type in ("textbox", "nav", "checkbox")
            if advanced:
                try:
                    from . import learned
                    learned.record(site, url_before, goal, act, el_type)
                except Exception:
                    pass
    return {"done": False, "reason": "ai_max_steps"}
