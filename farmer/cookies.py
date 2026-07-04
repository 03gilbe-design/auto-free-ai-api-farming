"""Dismiss cookie banner deterministico. Selettori CMP reali (OneTrust, Cookiebot,
Quantcast, Didomi, TrustArc, Osano, Usercentrics) + fallback testo "rifiuta/reject".
Cerca su tutti i frame. No-op se nessun banner.
"""
from __future__ import annotations
import json

# selettori specifici CMP -> click diretto (preferisci REJECT, poi accept se reject assente)
_REJECT_SEL = [
    "#onetrust-reject-all-handler",
    "button#onetrust-reject-all-handler",
    ".ot-pc-refuse-all-handler",
    "#CybotCookiebotDialogBodyButtonDecline",          # Cookiebot
    "button[onclick*='Cookiebot'][id*=Decline]",
    ".qc-cmp2-summary-buttons button[mode=secondary]",  # Quantcast
    "#didomi-notice-disagree-button",                   # Didomi
    ".didomi-continue-without-agreeing",
    "#truste-consent-required",                         # TrustArc
    ".osano-cm-denyAll",                                # Osano
    "button[data-testid='uc-deny-all-button']",         # Usercentrics
    "[aria-label*='reject' i]", "[aria-label*='rifiuta' i]",
]
_REJECT_TEXT = ["rifiuta tutto", "reject all", "decline all", "rifiuta", "reject",
                "decline", "solo essenziali", "only essential", "necessari", "nega"]
_ACCEPT_SEL = ["#onetrust-accept-btn-handler", "#CybotCookiebotDialogBodyButtonAccept",
               "[aria-label*='accept' i]", "[aria-label*='accetta' i]"]
# NB: niente "ok" nudo (matchava bottoni a caso tipo "OK"/"Bookmark" su pagine senza banner,
# rompendo OpenRouter). Solo frasi tipiche cookie. Match ANCORATO (vedi _try).
_ACCEPT_TEXT = ["accetta tutto", "accept all", "accept cookies", "accetta i cookie",
                "ho capito", "got it", "i understand", "agree", "accetta", "accept"]


async def _try(scope, selectors, texts) -> str | None:
    for sel in selectors:
        try:
            loc = scope.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=1500)
                return sel
        except Exception:
            continue
    import re
    for t in texts:
        try:
            # ANCORATO (^...$): il testo del bottone DEVE essere la frase cookie, non contenerla
            # (re.compile("ok") matchava "Bookmark"/"OK" a caso -> click sbagliati).
            rx = re.compile(rf"^\s*{re.escape(t)}\s*$", re.I)
            loc = scope.get_by_role("button", name=rx).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=1500)
                return f"text:{t}"
        except Exception:
            continue
    # TIER CONTAINS per frasi cookie FORTI/sicure (Nebius: 'Accept all cookies', 'Allow all'...).
    for t in _STRONG_COOKIE:
        try:
            loc = scope.get_by_role("button", name=re.compile(re.escape(t), re.I)).first
            if not await loc.count():
                tq = json.dumps(t)
                loc = scope.locator(f"button:has-text({tq}), a:has-text({tq}), [role=button]:has-text({tq})").first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=1500)
                return f"contains:{t}"
        except Exception:
            continue
    # TIER SEMANTICO (pattern intelligente, non keyword): un bottone il cui testo ha
    # VERBO-azione + NOME-cookie. Cattura varianti future senza elencarle. Reject/deny prima
    # di accept (preferenza), e SOLO se c'e' anche un nome-cookie (no falsi positivi).
    try:
        txt = await scope.evaluate(r"""() => {
          const verb = /\b(reject|decline|deny|refuse|accept|allow|confirm|save|agree|manage|got it|rifiuta|accetta|conferma|salva|nega|gestisci)\b/i;
          const noun = /\b(all|cookies?|choices?|preferences?|consent|necessary|essential|tracking|selection|scelt\w*|preferenz\w*|essenzial\w*)\b/i;
          const cands = [];
          for (const e of document.querySelectorAll("button, a, [role=button]")) {
            const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
            if (r.width<4||r.height<4||s.visibility==='hidden'||s.display==='none') continue;
            const t=(e.innerText||e.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();
            if (!t || t.length>40) continue;
            if (verb.test(t) && noun.test(t)) {
              // priorita': reject/deny (1) > accept/allow/confirm/save (0)
              const rej = /reject|decline|deny|refuse|rifiuta|nega|necessary|essential/i.test(t) ? 1 : 0;
              cands.push({t, rej});
            }
          }
          cands.sort((a,b)=> (b.rej-a.rej) || (a.t.length-b.t.length));
          return cands.length ? cands[0].t : null;
        }""")
        if txt:
            loc = scope.get_by_text(txt, exact=False).first
            if await loc.count() and await loc.is_visible():
                await loc.click(timeout=1500)
                return f"semantic:{txt[:25]}"
    except Exception:
        pass
    return None


# frasi cookie FORTI (multi-parola) -> contains-match sicuro (preferenza reject, poi accept/allow).
# include "confirm my choice"/"save preferences" (Nebius cookie-preferences modal in primo piano).
_STRONG_COOKIE = ["reject all", "decline all", "deny all", "reject non-essential", "only necessary",
                  "only essential", "rifiuta tutto", "confirm my choice", "confirm choices",
                  "save preferences", "save my choices", "save choices", "conferma scelte",
                  "accept all cookies", "accept all", "allow all", "accetta tutti",
                  "agree and close", "agree and continue"]


async def dismiss(page, log=None) -> bool:
    """Ritorna True se ha chiuso un banner. Prova reject prima, poi accept."""
    for scope in [page, *page.frames]:
        hit = await _try(scope, _REJECT_SEL, _REJECT_TEXT)
        if hit:
            if log: log.step("COOKIE", "rifiutato", hit, "ok")
            return True
    for scope in [page, *page.frames]:
        hit = await _try(scope, _ACCEPT_SEL, _ACCEPT_TEXT)
        if hit:
            if log: log.step("COOKIE", "accettato", hit, "ok")
            return True
    if log: log.step("COOKIE", "assente", "", "skip")
    return False
