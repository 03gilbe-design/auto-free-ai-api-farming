"""Self-powering key pool: the AI fallback runs on the keys the tool itself harvested.

Bootstrap (resolves the chicken-and-egg): the first providers are solved by the deterministic
path with NO LLM (Google-chooser sites need no AI). Those runs write keys to out/keys.txt. From
then on the AI fallback pulls its LLM credentials straight from that file — the agent that signs
up for AI keys is powered by the AI keys it signed up for.

All providers here are OpenAI-compatible (/chat/completions). clients() returns a rotation list
(base_url, model, key, provider): try each in turn, move on when one is rate-limited or invalid.
An optional seed key (env GROQ_KEY) is tried first so behaviour is unchanged when one is set.
"""
from __future__ import annotations
import os
from pathlib import Path

# provider (as written in out/keys.txt, case-insensitive) -> (chat endpoint, chat model, supports_vision)
LLM_PROVIDERS = {
    "groq":       ("https://api.groq.com/openai/v1/chat/completions",
                   "meta-llama/llama-4-scout-17b-16e-instruct", True),
    "cerebras":   ("https://api.cerebras.ai/v1/chat/completions", "llama-3.3-70b", False),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions",
                   "meta-llama/llama-3.3-70b-instruct:free", False),
    "togetherai": ("https://api.together.xyz/v1/chat/completions",
                   "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", False),
    "sambanova":  ("https://api.sambanova.ai/v1/chat/completions",
                   "Meta-Llama-3.3-70B-Instruct", False),
    "fireworksai":("https://api.fireworks.ai/inference/v1/chat/completions",
                   "accounts/fireworks/models/llama-v3p3-70b-instruct", False),
    "deepinfra":  ("https://api.deepinfra.com/v1/openai/chat/completions",
                   "meta-llama/Llama-3.3-70B-Instruct", False),
    "novitaai":   ("https://api.novita.ai/v3/openai/chat/completions",
                   "meta-llama/llama-3.1-8b-instruct", False),
}

# keys.txt provider column -> registry key above (spellings vary)
_ALIAS = {
    "groq": "groq", "cerebras": "cerebras", "openrouter": "openrouter",
    "together": "togetherai", "togetherai": "togetherai", "together ai": "togetherai",
    "sambanova": "sambanova", "fireworks": "fireworksai", "fireworksai": "fireworksai",
    "deepinfra": "deepinfra", "novita": "novitaai", "novitaai": "novitaai",
}

_KEYFILE = Path(__file__).parent.parent / "out" / "keys.txt"
_SEED_FILES = [Path.home() / ".env"]
_SEED_NAMES = ("GROQ_KEY", "GROQ_API_KEY")


def _strip(v: str) -> str:
    return v.strip().strip('"').strip("'").strip()


def _seed_key() -> str | None:
    """Optional bootstrap Groq key: OS keyring (…/groq_seed) -> env GROQ_KEY -> ~/.env."""
    from . import secretstore
    v = secretstore.get("groq_seed", env=_SEED_NAMES)
    if v:
        return v
    for f in _SEED_FILES:
        try:
            for ln in f.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if ln.startswith("export "):
                    ln = ln[7:]
                for n in _SEED_NAMES:
                    if ln.startswith(n + "="):
                        return _strip(ln.split("=", 1)[1])
        except Exception:
            continue
    return None


def _harvested():
    """Read keys the tool harvested (out/keys.txt): rows 'Provider<TAB>KEY<TAB>...'.
    Yields (registry_name, key) for LLM-capable providers only, most recent first."""
    out = []
    try:
        for ln in _KEYFILE.read_text(encoding="utf-8").splitlines():
            p = ln.split("\t")
            if len(p) < 2:
                continue
            name = _ALIAS.get(p[0].strip().lower())
            key = _strip(p[1])
            if name and key:
                out.append((name, key))
    except Exception:
        return []
    out.reverse()  # newest keys first
    return out


def clients(vision: bool = False) -> list[tuple[str, str, str, str]]:
    """Rotation list of (base_url, model, key, provider). Seed Groq key first (if any), then
    harvested keys. vision=True keeps only providers whose model accepts images."""
    seen = set()
    res = []
    seed = _seed_key()
    if seed:
        base, model, vis = LLM_PROVIDERS["groq"]
        if not vision or vis:
            res.append((base, model, seed, "groq")); seen.add(("groq", seed))
    for name, key in _harvested():
        if (name, key) in seen:
            continue
        base, model, vis = LLM_PROVIDERS[name]
        if vision and not vis:
            continue
        res.append((base, model, key, name)); seen.add((name, key))
    return res


def available(vision: bool = False) -> bool:
    return bool(clients(vision))
