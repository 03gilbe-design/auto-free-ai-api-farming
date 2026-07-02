"""Lista siti target. Solo AI gratis veri (Gmail ok, no telefono/carta obbligatori).
provider = chiave in grabkey.PROVIDERS. via_google = preferisci OAuth Google.
"""
from grabkey import PROVIDERS
from registry import sites_compat

# FONTE UNICA = sites.json (via registry). SITES qui ricostruito, non hardcoded.
SITES = sites_compat()


def site_cfg(name: str) -> dict:
    s = next((x for x in SITES if x["name"] == name), {"name": name})
    s = dict(s)
    s["provider_cfg"] = PROVIDERS.get(name, {})
    return s
