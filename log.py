"""Debug logger token-efficient.

2 canali:
  - FILE (out/debug.jsonl): TUTTO, una riga JSON per evento. Per forensics, non per Claude.
  - CONSOLE: solo righe step gerarchiche compatte. Quello che l'umano/Claude legge.

Claude legge `out/trace.txt` = solo gli step (no rumore). debug.jsonl solo se serve scavare.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path

OUT = Path(__file__).parent / "out"
OUT.mkdir(exist_ok=True)
_JSONL = OUT / "debug.jsonl"
_TRACE = OUT / "trace.txt"

_ICON = {"ok": "✅", "skip": "⏭", "ai": "🤖", "warn": "⚠️", "err": "💥",
         "info": "·", "key": "🔑", "captcha": "🧩", "wait": "⏳"}

# Traduce il codice-fase in una frase semplice ma precisa (mostrata LIVE nel terminale).
_PHRASE = {
    "ARRIVO": "Apro il sito",
    "COOKIE": "Banner cookie",
    "ENTRY": "Cerco come registrarmi",
    "INGRESSO": "Ingresso",
    "GOOGLE": "Accesso con Google",
    "ACCESSO": "Accesso",
    "MODULO": "Modulo di registrazione",
    "FORM": "Compilo il modulo",
    "VERIFICA": "Verifica email",
    "ONBOARD": "Schermate iniziali",
    "KEY": "Pagina della chiave",
    "CHIAVI": "Prendo la chiave",
    "AI": "L'IA decide da sola",
    "VISION": "Guardo lo screenshot",
    "ESITO": "RISULTATO",
    "MURO": "Barriera nota",
    "SALTO": "Salto",
    "STOP": "Stop richiesto",
}


class Log:
    def __init__(self, site: str = "-", reset: bool = False):
        self.site = site
        self.t0 = time.time()
        if reset:
            _JSONL.write_text("", encoding="utf-8")
            _TRACE.write_text("", encoding="utf-8")

    def _raw(self, **kw):
        kw["t"] = round(time.time() - self.t0, 2)
        kw["site"] = self.site
        with _JSONL.open("a", encoding="utf-8") as f:
            f.write(json.dumps(kw, ensure_ascii=False) + "\n")

    def step(self, stage: str, outcome: str, detail: str = "", kind: str = "info"):
        """Riga gerarchica compatta -> console + trace.txt. Questo Claude lo legge."""
        ic = _ICON.get(kind, "·")
        phrase = _PHRASE.get(stage, stage)
        # CONSOLE LIVE: frase semplice. "✅ Apro il sito → pagina aperta: token.llm7.io"
        live = f"  {ic} {phrase} → {outcome}" + (f": {detail}" if detail else "")
        print(live, flush=True)
        # trace.txt resta col codice-fase (per ricerca/debug)
        line = f"  {ic} [{stage}] {outcome}" + (f" — {detail}" if detail else "")
        with _TRACE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._raw(ev="step", stage=stage, outcome=outcome, detail=detail, kind=kind)

    def head(self, txt: str):
        line = f"\n=== {txt} ==="
        print(line, flush=True)
        with _TRACE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._raw(ev="head", txt=txt)

    def dbg(self, msg: str, **kw):
        """Solo file. Mai console. Per dettagli verbosi (selettori, url, dump)."""
        self._raw(ev="dbg", msg=msg, **kw)

    def err(self, where: str, exc: Exception):
        self.step(where, "errore", str(exc)[:120], "err")
        self._raw(ev="err", where=where, exc=repr(exc))


def tail_trace(n: int = 40) -> str:
    if not _TRACE.exists():
        return "(vuoto)"
    return "\n".join(_TRACE.read_text(encoding="utf-8").splitlines()[-n:])


if __name__ == "__main__":
    lg = Log("Test", reset=True)
    lg.head("demo")
    lg.step("COOKIE", "rifiutato", "onetrust", "ok")
    lg.step("ENTRY", "non trovato", "AI in campo", "ai")
    lg.dbg("dettaglio verboso che non sporca console", sel="#x")
    print("\n--- tail_trace ---")
    print(tail_trace())
