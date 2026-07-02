"""Convertitore sito -> testo compatto. Il pezzo chiave.

Notazione (richiesta utente):
  [Testo]            bottone
  <Testo>            link
  *Placeholder*(t)   campo input, t = tipo (email/password/text/tel...)
  [____](t)          campo input senza placeholder
  V-Label-V          tendina/select (opzioni elencate se poche)
  [ ] Label          checkbox vuoto      [x] Label  spuntato
  ( ) Label          radio vuoto         (o) Label  scelto
  ||| Voce1 · Voce2  nav/menu
  # Testo            heading
  ~Testo~            testo statico rilevante (max poche righe)
  (CAPTCHA: tipo)    widget captcha visibile
  icone -> ASCII (vedi _ICON_MAP), sconosciute -> [icon]
  {ref:eN}           id stabile dell'elemento (vedi sotto)

REF STABILI (come Playwright MCP / browser-use "snapshot+ref"): ogni elemento azionabile
riceve un attributo DOM `data-af-ref="eN"` iniettato al momento della lettura, e il suo `{ref:eN}`
appare accanto al testo. L'AI puo' rispondere con `{"action":"click","ref":"e3"}` invece di
ripetere il testo — _exec lo risolve con un solo selettore diretto (`[data-af-ref='e3']`), niente
match testuale da rompere (era la causa del bug "0 key estratte pur raggiunto il modale": l'AI
copiava i decoratori `[Text]` nel testo dell'azione). Il testo resta comunque disponibile come
fallback (es. per il tier vision, dove non c'e' DOM da annotare).

Obiettivo: poche centinaia di token, abbastanza per decidere il prossimo click.
Fonte: JS in-page (visibilita reale + ordine DOM). a11y tree come arricchimento ruolo.
"""
from __future__ import annotations
import re

# mappa nomi-icona comuni -> ascii. Esteso al volo.
_ICON_MAP = {
    "menu": "|||", "hamburger": "|||", "search": "(cerca)", "close": "(x)",
    "user": "(utente)", "account": "(utente)", "settings": "(ingr)", "gear": "(ingr)",
    "google": "G", "github": "GH", "microsoft": "MS", "apple": "(apple)",
    "arrow": "->", "chevron": "v", "check": "ok", "warning": "!", "error": "!",
    "home": "(home)", "key": "(key)", "copy": "(copia)", "eye": "(occhio)",
}

# JS: estrae nodi interattivi+testo visibili, in ordine documento, gia semi-formattati.
# Ritorna lista di dict {k: kind, t: text, ty: type, opt: [..], ck: bool}.
_JS_EXTRACT = r"""
() => {
  const out = [];
  const seen = new Set();
  let _refN = 0;
  // ref stabile per l'elemento appena letto: iniettato come attributo DOM, cosi' Python puo'
  // rilocalizzarlo con [data-af-ref='eN'] invece di ri-matchare per testo dopo che l'AI l'ha
  // riscritto (spesso coi decoratori [X]/<X> compresi -> mismatch, era il bug del create-key
  // modal). Riassegnato ad ogni lettura: harmless, e' un attributo solo-nostro.
  const _mkref = (el) => { const r = 'e' + (_refN++); el.setAttribute('data-af-ref', r); return r; };
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) return false;
    return true;
  };
  const txt = (el) => {
    let t = (el.innerText || el.textContent || '').trim().replace(/\s+/g,' ');
    // bottone/link con dentro solo IMMAGINE (OpenRouter: <button><img alt='Sign in with Google'>)
    // -> usa l'alt/aria-label dell'img, altrimenti l'AI non vede il bottone.
    if (!t) {
      const im = el.querySelector('img[alt],img[aria-label]');
      if (im) t = (im.getAttribute('alt') || im.getAttribute('aria-label') || '').trim();
    }
    if (!t) t = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
    return t.replace(/\s+/g,' ').slice(0,80);
  };
  const labelFor = (el) => {
    // testo della label associata: aria-label > <label for=id> > <label> contenitore > prossimo testo
    let a = el.getAttribute('aria-label'); if (a) return a.trim();
    if (el.id) { const l = document.querySelector("label[for='" + CSS.escape(el.id) + "']"); if (l) return txt(l); }
    const wrap = el.closest('label'); if (wrap) return txt(wrap);
    const sib = el.parentElement; if (sib) { const tt = txt(sib); if (tt) return tt; }
    return '';
  };
  const iconName = (el) => {
    // prova aria-label, classi, nomi svg
    const a = (el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
    const c = (el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className || '').toString().toLowerCase();
    const blob = a + ' ' + c;
    return blob;
  };
  // rileva MODALE in primo piano: se presente, scansiona SOLO quello (sfondo oscurato = rumore)
  let modalEl = null, bgHidden = 0;
  // un COOKIE-banner usa spesso role=dialog -> NON e' il modale vero (nasconderebbe il login dietro).
  // Escludi i dialog il cui contenuto/classe parla di cookie/consenso/privacy.
  const _isCookieDialog = (el) => {
    const cls = (el.className && el.className.toString ? el.className.toString() : '') + ' ' + (el.id||'');
    if (/cookie|consent|gdpr|cybot|onetrust|didomi|privacy.?choice/i.test(cls)) return true;
    const tx = (el.innerText||'').toLowerCase();
    return /(accept|allow|deny|reject).{0,30}(cookie|all|selection)|cookie (policy|settings|preferences)|privacy choices/.test(tx);
  };
  const modalCands = [...document.querySelectorAll(
     "[role=dialog][aria-modal='true'], dialog[open], [aria-modal='true'], [role=dialog], [role=alertdialog]")]
     .filter(vis).filter(e => !_isCookieDialog(e));
  if (modalCands.length) {
    // il piu in alto: maggior z-index, poi ultimo nel DOM
    modalEl = modalCands.sort((a,b) => {
      const za = +getComputedStyle(a).zIndex || 0, zb = +getComputedStyle(b).zIndex || 0;
      return za - zb;
    }).pop();
  }
  // walk in document order su un set di selettori
  const sel = 'a,button,input,select,textarea,[role=button],[role=link],[role=checkbox],[role=radio],[role=menuitem],h1,h2,h3,nav,[role=navigation],label';
  const root = modalEl || document;
  if (modalEl) bgHidden = document.querySelectorAll(sel).length - modalEl.querySelectorAll(sel).length;
  const nodes = root.querySelectorAll(sel);
  // COOKIE-BANNER: i bottoni di consenso (Accept/Necessary/Reject) confondono l'AI navigatrice.
  // Saltiamo gli elementi dentro un container cookie/consent (id/class noti) — il banner va
  // gestito da cookies.dismiss, non scelto come azione. (gap anyscale: AI cliccava '[x] Necessary')
  const _inCookie = (el) => !!el.closest(
    "[id*='cookie' i],[class*='cookie' i],[id*='consent' i],[class*='consent' i]," +
    "[id*='gdpr' i],[class*='gdpr' i],[aria-label*='cookie' i]," +
    "[id*='cybot' i],[class*='cybot' i],[id*='onetrust' i],[class*='onetrust' i]," +
    "[id*='didomi' i],[class*='didomi' i],[id*='usercentrics' i]");
  for (const el of nodes) {
    if (!vis(el)) continue;
    if (!modalEl && _inCookie(el)) continue;   // banner cookie = rumore, salta
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const t = txt(el);
    // dedupe per posizione+testo
    const r = el.getBoundingClientRect();
    const id = tag + '|' + Math.round(r.top) + '|' + Math.round(r.left) + '|' + t.slice(0,20);
    if (seen.has(id)) continue; seen.add(id);

    if (tag === 'input') {
      const ty = (el.type || 'text').toLowerCase();
      if (ty === 'hidden') continue;
      if (ty === 'checkbox') { out.push({k:'check', t: labelFor(el) || el.name || '', ck: el.checked, ref: _mkref(el)}); continue; }
      if (ty === 'radio')    { out.push({k:'radio', t: labelFor(el) || el.value || '', ck: el.checked, ref: _mkref(el)}); continue; }
      if (ty === 'submit' || ty === 'button') { out.push({k:'btn', t: el.value || t || 'Invia', ref: _mkref(el)}); continue; }
      out.push({k:'field', t: el.placeholder || el.getAttribute('aria-label') || el.name || '', ty: ty, ref: _mkref(el)});
      continue;
    }
    if (tag === 'textarea') { out.push({k:'field', t: el.placeholder || el.name || '', ty:'area', ref: _mkref(el)}); continue; }
    if (tag === 'select') {
      const opts = [...el.options].map(o => o.text.trim()).filter(Boolean).slice(0,6);
      out.push({k:'select', t: el.getAttribute('aria-label') || el.name || '', opt: opts, ref: _mkref(el)}); continue;
    }
    if (tag === 'button' || role === 'button') {
      if (t) { out.push({k:'btn', t, ref: _mkref(el)}); } else { out.push({k:'icon', t: iconName(el), ref: _mkref(el)}); }
      continue;
    }
    if (tag === 'a' || role === 'link' || role === 'menuitem') {
      if (t) out.push({k:'link', t, ref: _mkref(el)}); else { const ic = iconName(el); if (ic.trim()) out.push({k:'icon', t: ic, ref: _mkref(el)}); }
      continue;
    }
    if (role === 'checkbox') { out.push({k:'check', t, ck: el.getAttribute('aria-checked')==='true', ref: _mkref(el)}); continue; }
    if (role === 'radio')    { out.push({k:'radio', t, ck: el.getAttribute('aria-checked')==='true', ref: _mkref(el)}); continue; }
    if (tag === 'nav' || role === 'navigation') {
      const items = [...el.querySelectorAll('a,button,[role=menuitem]')].filter(vis).map(txt).filter(Boolean).slice(0,8);
      if (items.length) out.push({k:'nav', opt: items});
      continue;
    }
    if (/^h[1-3]$/.test(tag)) { if (t) out.push({k:'head', t}); continue; }
    if (tag === 'label') { /* di solito gia coperto da field; salta per non duplicare */ continue; }
  }
  // captcha visibili
  const cap = [];
  document.querySelectorAll("iframe[src*='recaptcha/api2/anchor'], .g-recaptcha, iframe[src*='hcaptcha'], .h-captcha").forEach(el=>{
    if (vis(el)) cap.push(el.className && el.className.toString().includes('h-') ? 'hcaptcha' : 'recaptcha');
  });
  // un po' di testo statico saliente (titolo pagina + primi paragrafi forti)
  let lead = '';
  const p = document.querySelector('main p, .content p, p');
  if (p && vis(p)) lead = txt(p);
  return {nodes: out, captcha: [...new Set(cap)], title: document.title, url: location.href, lead,
          modal: !!modalEl, modalLabel: modalEl ? (modalEl.getAttribute('aria-label')||'') : '', bgHidden};
}
"""


def _ascii_icon(blob: str) -> str:
    blob = (blob or "").strip()
    if not blob:
        return "[icon]"
    for k, v in _ICON_MAP.items():
        if k in blob:
            return v
    # niente match: prima parola utile
    w = "".join(ch for ch in blob if ch.isalnum() or ch == " ").split()
    return f"[{w[0][:10]}]" if w else "[icon]"


def _ref_tag(n: dict) -> str:
    r = n.get("ref")
    return f" {{ref:{r}}}" if r else ""


def _fmt(n: dict) -> str | None:
    k = n.get("k")
    t = (n.get("t") or "").strip()
    if k == "btn":
        return f"[{t or 'BOTTONE'}]{_ref_tag(n)}"
    if k == "link":
        return f"<{t}>{_ref_tag(n)}" if t else None
    if k == "field":
        ty = n.get("ty", "text")
        body = f"*{t}*" if t else "[____]"
        return f"{body}({ty}){_ref_tag(n)}"
    if k == "select":
        opts = n.get("opt") or []
        label = t or (opts[0] if opts else "scelta")
        tail = (" {" + " · ".join(opts[:5]) + "}") if opts else ""
        return f"V-{label}-V{tail}{_ref_tag(n)}"
    if k == "check":
        return f"[{'x' if n.get('ck') else ' '}] {t}{_ref_tag(n)}".rstrip()
    if k == "radio":
        return f"({'o' if n.get('ck') else ' '}) {t}{_ref_tag(n)}".rstrip()
    if k == "nav":
        items = n.get("opt") or []
        return ("||| " + " · ".join(items)) if items else None
    if k == "head":
        return f"# {t}" if t else None
    if k == "icon":
        return _ascii_icon(t)
    return None


async def page_to_text(page, max_lines: int = 60) -> str:
    """Serializza la pagina (frame principale) in testo compatto."""
    try:
        data = await page.evaluate(_JS_EXTRACT)
    except Exception as e:
        return f"(page2text errore: {e})"
    lines = []
    seen = set()
    nav_items = set()
    for n in data.get("nodes", []):
        s = _fmt(n)
        if not s:
            continue
        # dedup normalizzato: ignora maiuscole/spazi multipli (odia doppioni) E il {ref:eN}
        # (altrimenti ogni elemento avrebbe un ref diverso -> stringa sempre unica -> il dedup
        # smetterebbe di funzionare, gonfiando il testo con bottoni "duplicati" per l'AI)
        norm = " ".join(s.lower().split())
        norm = re.sub(r"\{ref:e\d+\}", "", norm).strip()
        if norm in seen:
            continue
        # raccogli voci nav per sopprimere link standalone duplicati
        if n.get("k") == "nav":
            nav_items.update((i or "").strip().lower() for i in (n.get("opt") or []))
        elif n.get("k") == "link" and (n.get("t") or "").strip().lower() in nav_items:
            continue
        seen.add(norm)
        lines.append(s)
        if len(lines) >= max_lines:
            lines.append("… (troncato)")
            break
    head = [f"URL: {data.get('url','')}", f"TITOLO: {data.get('title','')}"]
    if data.get("modal"):
        lbl = data.get("modalLabel") or "dialog"
        head.append(f"⊞ MODALE ATTIVA: {lbl} (sfondo oscurato: {data.get('bgHidden',0)} elementi ignorati)")
    if data.get("lead"):
        head.append(f"~{data['lead'][:120]}~")
    if data.get("captcha"):
        head.append("CAPTCHA: " + ", ".join(data["captcha"]))
    return "\n".join(head + ["---"] + lines)


async def page_to_text_all_frames(page, max_lines: int = 60) -> str:
    """Come page_to_text ma include iframe (Auth0/Google spesso in frame)."""
    main = await page_to_text(page, max_lines)
    out = [main]
    for fr in page.frames:
        if fr == page.main_frame:
            continue
        try:
            data = await fr.evaluate(_JS_EXTRACT)
        except Exception:
            continue
        ns = [s for n in data.get("nodes", []) if (s := _fmt(n))]
        if ns:
            out.append(f"\n[FRAME {fr.url[:60]}]\n" + "\n".join(ns[:20]))
    return "\n".join(out)
