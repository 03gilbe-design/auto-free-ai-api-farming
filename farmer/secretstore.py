"""Central secret lookup: OS keyring first, then env var, then a dotfile.

Prefer the OS credential store (Windows Credential Manager / macOS Keychain / GNOME Secret
Service) over plaintext files. `keyring` is an optional dependency — if it isn't installed the
lookup silently falls back to env vars and dotfiles, so nothing breaks.

Store a secret once:
    keyring set auto-free-ai-api-farming google_pw       # prompts for the value
    keyring set auto-free-ai-api-farming groq_seed
    keyring set auto-free-ai-api-farming signup_password
"""
from __future__ import annotations
import os
from pathlib import Path

SERVICE = "auto-free-ai-api-farming"

try:
    import keyring as _keyring  # optional
except Exception:
    _keyring = None


def _strip(v: str) -> str:
    return v.strip().strip('"').strip("'").strip()


def _from_file(path: Path, key: str | None) -> str | None:
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("export "):
                ln = ln[7:]
            if key and ln.startswith(key + "="):
                return _strip(ln.split("=", 1)[1])
            if key is None and ln and "=" not in ln:
                return _strip(ln)
    except Exception:
        pass
    return None


def get(name: str, env: tuple[str, ...] = (), file: Path | None = None,
        file_key: str | None = None) -> str | None:
    """Resolve a secret by name. Order: keyring[SERVICE/name] -> env vars -> dotfile line."""
    if _keyring is not None:
        try:
            v = _keyring.get_password(SERVICE, name)
            if v:
                return _strip(v)
        except Exception:
            pass
    for e in env:
        if os.environ.get(e):
            return _strip(os.environ[e])
    if file is not None:
        v = _from_file(file, file_key)
        if v:
            return v
    return None


def available() -> bool:
    """True if the OS keyring backend is usable (for a friendly hint in the README/CLI)."""
    return _keyring is not None
