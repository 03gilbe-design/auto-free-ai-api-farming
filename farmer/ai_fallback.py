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
Pagina corrente (testo compatto, [X]=bottone <X>=link *X*=campo V-X-V=tendina):
{page}
Rispondi SOLO JSON con UNA azione:
{{"action":"click","text":"testo esatto bottone/link"}}
{{"action":"fill","placeholder":"testo campo","value":"valore"}}
{{"action":"check","text":"testo vicino alla checkbox"}}  per spuntare caselle (es. Accetto i Termini)
{{"action":"goto","url":"https://..."}}
{{"action":"done"}}  se goal raggiunto
{{"action":"giveup"}} se impossibile
REGOLE: usa SOLO testo che vedi ELENCATO sopra; NON inventare bottoni assenti. Se NON c'e' un
bottone Google nella lista, NON scriverlo: compila il modulo email/password presente o cerca il
campo email per ricevere un token. Google solo se compare davvero. Mai cookie/privacy/social."""

_SYS_VISION = """Sei un agente che automatizza signup per API key gratuite. Account: {acct}, nome {nm}.
La password NON ti viene fornita (la inserisce il codice): per un campo password usa value "";
NON scrivere mai una password.
Goal: {goal}
GUARDA lo SCREENSHOT della pagina e scegli UNA azione. Usa il testo VISIBILE dei bottoni/link.
Rispondi SOLO JSON:
{{"action":"click","text":"testo esatto visibile"}}
{{"action":"fill","placeholder":"testo vicino al campo","value":"valore"}}
{{"action":"check","text":"testo vicino alla checkbox"}}  per spuntare caselle (es. Accetto i Termini)
{{"action":"goto","url":"https://..."}}
{{"action":"done"}}  se il goal e' raggiunto (es. API key visibile)
{{"action":"giveup"}} se c'e' un muro (captcha immagine, telefono)
REGOLE: agisci SOLO su elementi che VEDI nello screenshot; non inventare un bottone Google se non
c'e'. Se vedi solo un campo email/token, compila quello. Google solo se visibile. Mai cookie/privacy/social."""


_TAG2TYPE = {"button": "button", "a": "link", "[role=button]": "button", "*": "button"}


async def _exec(page, act: dict, log=None) -> str | None:
    """Esegue l'azione. Ritorna il TIPO di elemento toccato (textbox/button/link/nav) se riuscita,
    None se fallita. Il tipo serve a learned.record (elemento gia' visto)."""
    a = act.get("action")
    try:
        if a == "click":
            t = act.get("text", "")
            for tag in ["button", "a", "[role=button]", "*"]:
                loc = page.locator(f"{tag}:has-text('{t}')").first
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
            ph = act.get("placeholder", "")
            loc = page.locator(f"input[placeholder*='{ph}' i], textarea[placeholder*='{ph}' i]").first
            if await loc.count():
                await loc.fill(act.get("value", ""), timeout=2500)
                return "textbox"
        elif a == "check":
            # SPUNTA una checkbox (es. "Accetto i Termini"). L'input VERO spesso e' nascosto
            # (opacity 0, stile custom sopra) -> is_visible()=False. Percio': prima l'input per
            # ruolo/tipo con FORCE (bypassa la visibilita'), poi la label/wrapper visibile cliccabile.
            t = act.get("text", "")
            # 1) input checkbox associato al testo, o il primo: check(force) anche se nascosto
            for sel in (f"label:has-text('{t}') input[type=checkbox]",
                        f"input[type=checkbox][aria-label*='{t}' i]",
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
            for sel in (f"label:has-text('{t}')", f"*:has-text('{t}')"):
                loc = page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2000)
                    return "checkbox"
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
    - LOOP-DETECTION: se la pagina (testo) non cambia per 3 step, o la stessa azione si ripete,
      l'AI sta girando a vuoto -> giveup. (l'utente odiava il "fermo a far niente").
    - max_steps basso (12): un muro non si sblocca con 100 tentativi lenti.
    """
    if not keypool.available():
        if log: log.step("AI", "non disponibile", "no LLM key (seed GROQ_KEY or harvest one first)", "warn")
        return {"done": False, "reason": "ai_unavailable"}
    if log: log.step("AI", "in campo", goal[:50], "ai")
    t0 = time.time()
    prev_txt = None
    stuck = 0
    last_act = None
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
        # stessa azione identica ripetuta = loop -> giveup
        if act == last_act:
            if log: log.step("AI", "azione ripetuta", "loop", "warn")
            return {"done": False, "reason": "ai_repeat"}
        last_act = act
        url_before = page.url
        el_type = await _exec(page, act, log)
        if not el_type and log:
            log.dbg("ai act non eseguita", act=act)
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
