# auto-free-ai-api-farming

Automates signing up for **free-tier AI API keys** (Groq, OpenRouter, Cerebras, Mistral,
Cohere, Fireworks, DeepInfra, and more) and collects the resulting keys. Built with
Playwright; drives a real (or headless) Chrome/Chromium session, follows each site's signup
flow, extracts the API key, and saves it locally.

Works on both **English and Italian** UIs — button/link matching uses semantic patterns
(role/aria-label/visible text) with layered fallbacks, not hardcoded exact strings, so it
degrades gracefully across languages rather than breaking on a locale mismatch.

## How it works

1. **Deterministic first** (`forms.py`, `grabkey.py`, `cookies.py`, `oauth_text.py`) — cookie
   banners, login/signup buttons, Google/GitHub OAuth, and the common "create org / accept
   terms" onboarding form are all handled without AI, via cascading selector strategies
   (accessible-role match → visible text → attribute selectors → semantic keyword fallback).
2. **AI fallback** (`ai_fallback.py`) — when the deterministic path can't find the next step,
   a text-first LLM (Groq, no vision) reads a compact text rendering of the page
   (`page2text.py`) and picks one action (click/fill/check/goto). A vision tier (screenshot)
   kicks in only if the text-only agent gets stuck.
3. **Learns from the AI** (`learned.py`) — any action the AI resolves successfully is recorded
   as a deterministic "recipe" (page path + element type + action). Future runs replay the
   recipe first, skipping the AI call entirely — the system gets cheaper and more reliable the
   more sites it touches.

## Quick start

```bash
pip install playwright
playwright install chromium

export SIGNUP_ACCOUNT="you@example.com"
export SIGNUP_PASSWORD="something-strong"
export SIGNUP_NAME="API Bot"
export GROQ_KEY="..."          # only needed for the AI fallback tier

python run.py                  # runs every site in sites.json / sites_extra.json
python run.py Cohere           # runs a single site
```

Collected keys are written to `out/keys.txt`. A visual trace of the path taken through each
site's UI is written to `out/path.html`.

### Multiple accounts

Point `SIGNUP_PROFILE` at a separate Chrome sub-profile (`--profile-directory`) that's already
logged into a second Google account, and set `SIGNUP_ACCOUNT` to match. Google then auto-signs
into that account with no chooser prompt — no stored passwords, no 2FA risk.

```bash
export SIGNUP_PROFILE="secondary"
export SIGNUP_ACCOUNT="your-second-account@example.com"
python run.py Cohere
```

### Debugging what the AI "sees"

```bash
python page2text_demo.py
```

Generates `out/page2text_demo.html`: screenshot side-by-side with the compact text rendering
passed to the LLM, useful for diagnosing why the AI fallback stalled on a given page.

## Configuration

- `sites.json` / `sites_extra.json` — the site registry: signup URL, key page URL, key regex,
  OAuth provider, known quirks. Add a new site by adding an entry here.
- Env vars: `SIGNUP_ACCOUNT`, `SIGNUP_PASSWORD`, `SIGNUP_NAME`, `SIGNUP_PROFILE`,
  `GROQ_KEY`, `SIGNUP_CHROMIUM` (use Chromium instead of installed Chrome, avoids profile
  conflicts with a Chrome window you already have open), `SIGNUP_SNAPSHOT` (auto-capture every
  page visited, for offline debugging/fixtures).

## Ethics / ToS note

This automates account creation and API key retrieval. Only use it with accounts you own, and
review the target service's Terms of Service — some providers explicitly disallow automated
signups. This project is provided for personal/research use; you are responsible for how you
use it.

## License

MIT — see [LICENSE](LICENSE).
