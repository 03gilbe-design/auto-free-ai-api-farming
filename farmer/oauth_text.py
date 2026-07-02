"""Helper CONDIVISO per trovare il bottone 'login con <provider>' in modo robusto.
SCALA DI PRIORITA' (come un umano legge la pagina):
  1) TESTO VISIBILE che contiene il nome del provider su un bottone/link — QUALSIASI verbo
     (continue / sign in / sign up / log in / get started / accedi / usa / connect...). Niente
     frasi esatte hardcoded: leggiamo il testo. Esclude le trappole (ads/play/marketplace...).
  2) il chiamante usa i suoi selettori-attributo come FALLBACK per i bottoni SENZA testo (icone).

Usato da google_oauth e github_oauth -> stessa logica, niente duplicazione, niente keyword per-sito.
"""
from __future__ import annotations
import json, re


def _css_text(t: str) -> str:
    """Stringa sicura per :has-text(...): un apostrofo nel testo (es. 'L'accordo') spezzerebbe
    l'interpolazione grezza f\"...'{t}'...\"."""
    return json.dumps(t or "")

# trappole per provider: contengono il nome ma NON sono login
_TRAPS = {
    "google": r"\bads\b|play\.google|business|cloud|maps|drive|workspace|store|developer|pay|scholar|translate",
    "github": r"marketplace|sponsor|docs|gist|status|blog|pricing|features|/topics|stars|fork|issues|pulls",
}

_LOGIN_VERB = re.compile(
    r"continue|sign\s?in|sign\s?up|log\s?in|get started|accedi|registra|usa|connect|with", re.I)


async def find_login_text(page, provider: str) -> str | None:
    """Ritorna il TESTO VISIBILE del miglior bottone 'login con <provider>', o None.
    provider = 'google' | 'github' (minuscolo)."""
    trap = _TRAPS.get(provider, "")
    try:
        return await page.evaluate(r"""([prov, trapSrc, verbSrc]) => {
          const trap = trapSrc ? new RegExp(trapSrc, 'i') : null;
          const verb = new RegExp(verbSrc, 'i');
          const provRx = new RegExp(prov, 'i');
          const els = document.querySelectorAll("button, a, [role=button], [role=link]");
          const out = [];
          for (const e of els) {
            const r = e.getBoundingClientRect(); const st = getComputedStyle(e);
            if (r.width<4||r.height<4||st.visibility==='hidden'||st.display==='none'||+st.opacity===0) continue;
            let t = (e.innerText||e.textContent||'').trim();
            if (!t) { const im=e.querySelector('img[alt],img[aria-label]'); if(im) t=(im.alt||im.getAttribute('aria-label')||''); }
            if (!t) t = (e.getAttribute('aria-label')||e.title||'');
            t = t.replace(/\s+/g,' ').trim();
            if (!t || !provRx.test(t)) continue;
            const href = e.getAttribute('href')||'';
            if (trap && (trap.test(t) || trap.test(href))) continue;
            out.push({t, v: verb.test(t)?1:0, len: t.length});
          }
          // preferisci con verbo di login, poi testo piu' corto (bottone vero, non frase lunga)
          out.sort((a,b)=> (b.v-a.v) || (a.len-b.len));
          return out.length ? out[0].t : null;
        }""", [provider, trap, _LOGIN_VERB.pattern])
    except Exception:
        return None


async def click_login(page, provider: str, attr_selectors: list[str],
                      text_phrases: list[str] | None = None) -> bool:
    """Clicca il bottone login a CASCATA di fallback (3 tier, dal robusto al letterale):
    1) TESTO VISIBILE che contiene il provider (qualsiasi verbo) — il piu' robusto.
    2) ATTRIBUTI (href/data-*/class/img alt) — per i bottoni SENZA testo (icone/immagini).
    3) FRASI ESATTE via :has-text (la vecchia lista _BTN_TEXT) — rete di sicurezza finale,
       cattura casi dove get_by_text fallisce (testo in span annidati, ecc.).
    Nessun tier rimosso: piu' fallback = piu' robusto."""
    # 0) get_by_role con regex sul NOME ACCESSIBILE (modo Playwright-idiomatico confermato best-practice:
    #    il nome accessibile include gia' testo + img alt + aria-label, calcolato da Playwright).
    try:
        rx = re.compile(provider, re.I)
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=rx).first
            if await loc.count() and await loc.is_visible():
                nm = (await loc.inner_text() or "").lower()
                trap = _TRAPS.get(provider, "")
                if not (trap and re.search(trap, nm)):
                    await loc.click(timeout=2500); return True
    except Exception:
        pass
    # 1) testo visibile (JS: legge innerText + img alt + aria + title, con scelta per verbo)
    txt = await find_login_text(page, provider)
    if txt:
        try:
            loc = page.get_by_text(txt, exact=False).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=2500); return True
        except Exception:
            pass
    # 2) attributi (bottoni muti)
    for sel in attr_selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=2500); return True
        except Exception:
            continue
    # 3) frasi esatte :has-text (vecchio fallback, mantenuto)
    for t in (text_phrases or []):
        for tag in ["button", "a", "[role=button]"]:
            try:
                loc = page.locator(f"{tag}:has-text({_css_text(t)})").first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=2500); return True
            except Exception:
                continue
    return False
