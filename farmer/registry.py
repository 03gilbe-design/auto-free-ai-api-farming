"""Registro UNICO dei siti = sites.json (verita' singola).

Prima la conoscenza viveva in 3 posti divergenti (sites.py url, grabkey.PROVIDERS
key_url/key_re, site_recipes/* morte). Ora UN file dato. Il codice e' interprete.

Uso:
  from registry import load, site, automatable, wall_of, providers_compat
  cfg = site("Groq")            # dict completo del sito
  if not automatable("HuggingFace"):
      reason = wall_of("HuggingFace")   # -> "anti_bot": skippa con motivo

Compat: providers_compat() ricostruisce il vecchio dict grabkey.PROVIDERS dal
registro, cosi' grabkey.py non duplica piu' i dati (single source of truth).
"""
from __future__ import annotations
import json
from pathlib import Path

_PATH = Path(__file__).parent.parent / "data" / "sites.json"
_EXTRA_PATH = Path(__file__).parent.parent / "data" / "sites_extra.json"
_CACHE: dict | None = None

# campi che il vecchio grabkey.PROVIDERS si aspetta
_PROVIDER_KEYS = ("key_url", "key_re", "dropdowns", "key_panel")


def load(force: bool = False) -> list[dict]:
    """Carica e cacha la lista siti (salta la chiave _schema)."""
    global _CACHE
    if _CACHE is None or force:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        sites = list(data["sites"])
        if _EXTRA_PATH.exists():
            extra = json.loads(_EXTRA_PATH.read_text(encoding="utf-8"))
            sites.extend(extra.get("sites", []))
        # dedup per nome: il registro originale resta fonte primaria.
        merged = {}
        for s in sites:
            name = s.get("name")
            if name:
                merged[name] = s
        _CACHE = list(merged.values())
    return _CACHE


def site(name: str) -> dict:
    """Config completa di un sito (dict vuoto se assente)."""
    return next((s for s in load() if s["name"] == name), {})


def automatable(name: str) -> bool:
    """False = c'e' un muro esterno, il runner deve saltare."""
    return bool(site(name).get("automatable", True))


def wall_of(name: str) -> str:
    """Tipo di muro: 'none' o anti_bot|phone|captcha_v2|passkey|email_business|token_complex."""
    return site(name).get("wall", "none")


def names(only_automatable: bool = False) -> list[str]:
    return [s["name"] for s in load() if not only_automatable or s.get("automatable", True)]


def providers_compat() -> dict:
    """Ricostruisce il dict {name: {key_url, key_re, dropdowns}} per grabkey.py."""
    out = {}
    for s in load():
        out[s["name"]] = {k: s[k] for k in _PROVIDER_KEYS if k in s}
    return out


def sites_compat() -> list[dict]:
    """Ricostruisce la vecchia lista SITES (per sites.py)."""
    keep = ("name", "via_google", "logout_after")
    out = []
    for s in load():
        d = {k: s[k] for k in keep if k in s}
        d["url"] = s.get("signup_url", "")
        out.append(d)
    return out
