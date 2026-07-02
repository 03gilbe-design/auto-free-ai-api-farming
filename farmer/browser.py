"""Launch Chrome persistente. Profilo loggato Google riusato (chrome_profile/).

channel=chrome (Chrome vero, non Chromium) per ridurre bot-detection.
headed di default (headless = bloccato da molti siti). headless solo per test offline.
Un solo Chrome per volta sul profilo: chiudere altri prima.
"""
from __future__ import annotations
import os
from pathlib import Path
from playwright.async_api import async_playwright

# profilo Chrome. Default = quello condiviso (gia loggato primary@example.com).
# MULTI-PROFILO: SIGNUP_PROFILE=<nome> usa un profilo separato (un Google per profilo),
# cosi i siti che NON forzano il chooser (Cohere/Mistral/Google) auto-loggano l'account giusto.
#   SIGNUP_PROFILE=account_b  -> .../chrome_profile_account_b
#   (vuoto/account_a)       -> .../chrome_profile  (default storico)
_DEF_PROFILE = Path(__file__).parent.parent / "chrome_profile"
_prof = os.environ.get("SIGNUP_PROFILE", "").strip()
# SUB-PROFILO Chrome: gli account 2°/3° sono gia loggati in sub-profili DENTRO la user-data-dir
# condivisa (Default=account_a/3-account, Profile 1=account_b, Profile 2=account_c). Selezionarli
# con --profile-directory: il sito Google-OAuth auto-logga l'unico account del sub-profilo, no chooser.
_SUBPROFILE = {
    "account_a": "Default", "account_a": "Default", "default": "Default",
    "account_b": "Profile 1", "account_b": "Profile 1",
    "account_c": "Profile 2", "account_c": "Profile 2",
}
# override espliciti: puntano a una user-data-dir/subprofilo Chrome REALE gia' loggato
# (es. il Chrome di sistema dell'utente), invece del profilo vuoto del repo.
_user_data_dir = os.environ.get("SIGNUP_USER_DATA_DIR", "").strip()
_profile_dir_override = os.environ.get("SIGNUP_PROFILE_DIR", "").strip()
_sub = _profile_dir_override or (_SUBPROFILE.get(_prof.lower()) if _prof else None)
if _user_data_dir:
    PROFILE = Path(_user_data_dir)
elif _sub:
    PROFILE = _DEF_PROFILE                 # dir CONDIVISA (dove vivono i login)
elif _prof and _prof not in ("account_a", "account_a", "default"):
    PROFILE = _DEF_PROFILE.parent / f"chrome_profile_{_prof}"   # fallback: dir separata
    PROFILE.mkdir(parents=True, exist_ok=True)
else:
    PROFILE = _DEF_PROFILE

# META' SCHERMO destra: AUTO-rileva la risoluzione vera (no assunzioni su 1920).
# Override con SIGNUP_WIN="W,H,X,Y".
def _screen() -> tuple[int, int]:
    # NB: NON chiamare SetProcessDPIAware -> vogliamo i pixel LOGICI (scalati), che e' cio'
    # che Chrome usa per --window-size/--window-position. Su schermo 150% = 1280x720 logici.
    try:
        import ctypes
        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        return 1280, 720

if os.environ.get("SIGNUP_WIN"):
    _WW, _WH, _WX, _WY = (int(x) for x in (os.environ["SIGNUP_WIN"].split(",") + ["0", "0", "0", "0"])[:4])
else:
    _SW, _SH = _screen()
    _WW = _SW // 2          # larga meta schermo
    _WH = _SH - 48          # quasi tutta l'altezza (lascia la barra)
    _WX = _SW - _WW         # ancorata a DESTRA (terminale resta a sinistra)
    _WY = 0

_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run", "--no-default-browser-check",
    f"--window-position={_WX},{_WY}",
    f"--window-size={_WW},{_WH}",
]
if _sub:
    _ARGS.append(f"--profile-directory={_sub}")


def _snap_window(x: int, y: int, w: int, h: int):
    """Sposta la finestra Chrome appena aperta a meta schermo (Win32 MoveWindow).
    Serve perche Chrome ignora --window-size se ha uno stato finestra salvato nel profilo.
    Riprova qualche volta finche la finestra esiste. Solo Windows; no-op altrove."""
    try:
        import ctypes, time as _t
        from ctypes import wintypes
        u = ctypes.windll.user32
        EnumWindows = u.EnumWindows
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        for _ in range(12):
            hits = []
            def _cb(hwnd, _l):
                if not u.IsWindowVisible(hwnd):
                    return True
                n = u.GetWindowTextLengthW(hwnd)
                if n <= 0:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                t = buf.value
                if "Chromium" in t or "Google Chrome" in t or "accounts.google" in t.lower():
                    hits.append(hwnd)
                return True
            EnumWindows(CB(_cb), 0)
            if hits:
                for hwnd in hits:
                    u.ShowWindow(hwnd, 1)
                    u.MoveWindow(hwnd, x, y, w, h, True)
                return
            _t.sleep(0.7)
    except Exception:
        pass


class Browser:
    def __init__(self, headless: bool = False, profile: bool = True):
        self.headless = headless
        self.profile = profile
        self._pw = None
        self.ctx = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        # viewport = None: la pagina segue la dimensione VERA della finestra (metà schermo)
        kw = dict(headless=self.headless, args=_ARGS, viewport=None)
        # channel=chrome (Chrome vero) riduce bot-detection MA su Windows si FONDE col Chrome
        # dell'utente se aperto ("Apertura nella sessione esistente" -> Playwright senza browser).
        # SIGNUP_CHROMIUM=1 usa Chromium (binario diverso, niente merge): test live anche col
        # Chrome dell'utente aperto. Stesso profilo loggato (i cookie sono nel user-data-dir).
        if not os.environ.get("SIGNUP_CHROMIUM"):
            kw["channel"] = "chrome"
        if self.profile:
            self.ctx = await self._pw.chromium.launch_persistent_context(str(PROFILE), **kw)
        else:
            br = await self._pw.chromium.launch(headless=self.headless, args=_ARGS)
            self.ctx = await br.new_context(viewport={"width": 1280, "height": 720})
        try:
            await self.ctx.grant_permissions(["clipboard-read", "clipboard-write"])
        except Exception:
            pass
        # snap finestra SOLO se richiesto esplicito (SIGNUP_SNAP=1). Default: NON tocca la
        # finestra (l'utente non vuole riposizionamenti continui). Chrome resta dove sta.
        if not self.headless and os.environ.get("SIGNUP_SNAP"):
            _snap_window(_WX, _WY, _WW, _WH)
        return self.ctx

    async def __aexit__(self, *a):
        try:
            await self.ctx.close()
        finally:
            await self._pw.stop()

    async def page(self):
        return self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
