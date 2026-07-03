# auto-free-ai-api-farming

![Sign up to free AI APIs, harvest the keys](docs/banner.png)

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-3776AB?logo=python&logoColor=white">
  <img alt="Playwright" src="https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-16a34a">
  <img alt="Providers" src="https://img.shields.io/badge/providers-33-db2777">
</p>

**Automates signing up for free-tier AI API keys** — Groq, OpenRouter, Cerebras, Mistral,
Cohere, Fireworks, DeepInfra, and 25+ more. Drives a real (or headless) Chrome/Chromium
session with Playwright, follows each site's signup flow, extracts the API key, and saves it
locally.

![Real screenshots: signing in with Google and landing on the live API-keys dashboard, key row highlighted](docs/run-google-signup.gif)

*A real run (redacted) — Google sign-in with no chooser prompt (one account already linked),
straight onto the actual dashboard, real API key highlighted. Interactive version:
[`docs/banner-google-signup.html`](docs/banner-google-signup.html).*

Every run also generates a step-by-step map (`out/path.html`) and opens it automatically — this
is the terminal-style replay of the same real run, side by side with the backbone lighting up
stage by stage:

![The agent farming a key live: the terminal types each real step while the stage backbone lights up](docs/run.gif)

*Interactive version: [`docs/live-demo.html`](docs/live-demo.html).*

Works on both **English and Italian** UIs — matching uses semantic patterns (accessible
role, aria-label, visible text) with layered fallbacks instead of hardcoded exact strings, so
it degrades gracefully across languages instead of breaking on a locale mismatch.

## How it works

```
     ┌──────────────┐     stuck?     ┌───────────────┐    resolved?    ┌────────────────┐
      1. Deterministic ───────────►    2. AI fallback  ───────────►     3. Learned recipe
      cookies, OAuth,                  Groq (text-only,                 replayed next time,
      forms, key page                  vision as last resort)           no AI call needed
     └──────────────┘                 └───────────────┘                └────────────────┘
```

**[Full decision-flow diagram → `docs/how-it-works.html`](docs/how-it-works.html)** — a
plain-language, node-by-node walkthrough of `farmer/tree.py`'s `run_site()`, kept in sync with
the code (every box names the real function it maps to).

1. **Deterministic first** (`farmer/forms.py`, `farmer/grabkey.py`, `farmer/cookies.py`,
   `farmer/oauth_text.py`) — cookie banners, login/signup buttons, Google/GitHub OAuth, and
   the common "create org / accept terms" onboarding form are all handled without AI, via
   cascading selector strategies: accessible-role match → visible text → attribute selectors
   → semantic keyword fallback.
2. **AI fallback** (`farmer/ai_fallback.py`) — when the deterministic path can't find the next
   step, a text-first LLM (Groq, no vision) reads a compact text rendering of the page
   (`farmer/page2text.py`) and picks one action: click / fill / check / goto. A vision tier
   (screenshot) kicks in only if the text-only agent gets stuck.
3. **Learns from the AI** (`farmer/learned.py`) — any action the AI resolves successfully is
   recorded as a deterministic "recipe" (page path + element type + action). Future runs
   replay the recipe first, skipping the AI call entirely.
4. **Runs on the keys it harvests** (`farmer/keypool.py`) — the AI fallback doesn't need a
   pre-provisioned key. The first providers are solved with no LLM at all (steps 1 & 3), and
   the OpenAI-compatible keys they yield (Groq, Cerebras, OpenRouter, …) feed the fallback on
   later runs, rotating on rate-limit. An optional `GROQ_KEY` seeds the very first run; after
   that it's self-sustaining. *(A short "auto AI sign-up loop": harvest → power the agent →
   harvest more.)*

**Status:** functional core (steps 1–2 work end-to-end on most sites); steps 3–4 (learned
recipes, self-harvested key pool) are implemented and unit-tested but not yet proven over a
long live run — see [Known limitations](#known-limitations).

## Quick start

```bash
pip install -r requirements.txt      # playwright (+ optional keyring)
playwright install chromium
```

**Windows PowerShell** — use the launcher, no flags to remember:

```powershell
.\run.ps1                                    # every site in the registry
.\run.ps1 Cohere                             # one site
.\run.ps1 Cohere -Account you@example.com    # pick the account
.\run.ps1 Cohere -Profile secondary          # use a second Chrome sub-profile
.\run.ps1 -Headless                          # no visible window
```

**macOS / Linux (or plain Python anywhere):**

```bash
export SIGNUP_ACCOUNT="you@example.com"
export SIGNUP_NAME="API Bot"
python run.py                  # runs every site in data/sites.json + data/sites_extra.json
python run.py Cohere           # runs a single site
```

Credentials come from the OS keyring first, then env vars — nothing sensitive has to live in
your shell history (see [Security](#security)):

```bash
keyring set auto-free-ai-api-farming signup_password   # the signup-form password
keyring set auto-free-ai-api-farming google_pw         # only if Google asks for it
keyring set auto-free-ai-api-farming groq_seed         # optional seed key for the first run
```

Collected keys are written to `out/keys.txt`. When the run finishes it **generates
`out/path.html` and opens it in your browser automatically** — the visual map shown above, one
per run, so you can see exactly what the agent did on each site (set `SIGNUP_NO_MAP=1` to skip
the auto-open, or regenerate any time with `python tools/path_viewer.py`).

> **Two-factor / device approval:** if Google asks you to approve the sign-in on your phone or
> to check your email, the tool **stops and tells you** — it never tries to defeat a 2FA or
> email-verification challenge. Approve it yourself, then re-run.

## Project layout

```
farmer/           the engine (import as a package)
  browser.py         Playwright context setup (profile, window, multi-account sub-profiles)
  cookies.py         cookie banner detection/dismissal
  forms.py           generic deterministic form filler (email/password/org/consents/submit)
  google_oauth.py    github_oauth.py    oauth_text.py    -- OAuth flows
  grabkey.py         API key extraction from the dashboard/settings page
  ai_fallback.py      Groq-backed text (then vision) fallback agent
  learned.py         AI-resolved actions replayed deterministically on later runs
  page2text.py       page -> compact text rendering (what the AI agent "sees")
  tree.py            orchestrates the full per-site flow
  registry.py sites.py  loads data/sites.json into the site registry
data/
  sites.json sites_extra.json   site registry: signup URL, key page, key regex, quirks
tools/
  path_viewer.py       renders out/path.html from a run's debug.jsonl
  page2text_demo.py    side-by-side site screenshot vs. page2text rendering, for debugging
tests/
  test_offline.py test_real_offline.py test_regression.py   fixture-based regression suite
fixtures/          static HTML snapshots used by the offline tests (no live network)
run.py             entry point
```

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
python tools/page2text_demo.py
```

Generates `out/page2text_demo.html`: screenshot side-by-side with the compact text rendering
passed to the LLM — useful for diagnosing why the AI fallback stalled on a given page.

## Configuration

- `data/sites.json` / `data/sites_extra.json` — the site registry. Add a new site by adding
  an entry here: signup URL, key page URL, key regex, OAuth provider, known quirks.
- Env vars: `SIGNUP_ACCOUNT`, `SIGNUP_PASSWORD`, `SIGNUP_NAME`, `SIGNUP_PROFILE`, `GROQ_KEY`,
  `SIGNUP_CHROMIUM` (use Chromium instead of installed Chrome, avoids profile conflicts with a
  Chrome window you already have open), `SIGNUP_SNAPSHOT` (auto-capture every page visited,
  for offline debugging/fixtures), `SIGNUP_USER_DATA_DIR` (point at an existing Chrome
  user-data-dir that's already signed in, instead of the repo's empty profile — useful on a
  fresh clone), `SIGNUP_PROFILE_DIR` (pick a specific sub-profile inside that dir, e.g.
  `"Profile 2"`).

## Known limitations

- **Payment/card walls** are detected and skipped, not bypassed (by design).
- **React-controlled custom checkboxes** (some onboarding forms) can resist even a real
  Playwright click when off-screen; `forms.py` scrolls into view and falls back to a native
  mouse click, but a handful of heavily-customized forms still need a manual pass.
- **`learned.py` replay** is unit-tested (record → suggest round-trips correctly) but hasn't
  yet been proven to fully replace an AI call end-to-end on a live site — contributions
  welcome here.
- Sites change their UI regularly; a selector or regex in `data/sites.json` going stale is
  expected maintenance, not a design flaw.

## Security

Be aware of what this handles and where data goes:

- **Input secrets prefer the OS keyring.** The signup password, Google password, and seed key
  are read from the OS credential store first (`keyring set auto-free-ai-api-farming <name>`),
  then env vars, then a dotfile — so no real credential has to sit in your shell history or a
  plaintext file. Install `keyring` (in `requirements.txt`) to enable it.
- **Harvested keys are still written in plaintext** to `out/keys.txt` (that's the point — you
  export them to another project), and the learned recipes live in `out/` too. Everything in
  `out/`, any `chrome_profile*/`, and `~/.google_pw` is `.gitignore`d so it never reaches the
  repo — but anyone with disk access can read it. Don't run this on a shared machine.
- **A pre-commit secret scanner is included.** `pip install pre-commit && pre-commit install`
  runs [gitleaks](https://github.com/gitleaks/gitleaks) on every commit and blocks it if a real
  key slips in (test placeholders are allowlisted in `.gitleaks.toml`).
- **Page content goes to third-party LLMs.** The AI fallback sends a compact text (or a
  screenshot) of the current page to whichever provider key is active. The account **password
  is never included** in the prompt — the deterministic form filler types it locally. Your
  account **email** and visible page text are sent, so don't point the AI fallback at pages
  with data you wouldn't share with an LLM provider.
- **Prompt-injection surface.** The LLM's chosen action (click / fill / goto) is executed. A
  malicious or compromised page could try to steer the agent. Only run it against providers you
  trust and chose yourself — it never discovers sites on its own.
- **Clipboard is read** when grabbing a masked key (`navigator.clipboard.readText()`), so it
  can pick up whatever else is on your clipboard at that moment.
- **The Chrome profile holds a live Google session** on disk. Treat that directory like a
  credential.

## Ethics / ToS note

This automates account creation and API key retrieval. Only use it with accounts you own, and
review the target service's Terms of Service — some providers explicitly disallow automated
signups. This project is provided for personal/research use; you are responsible for how you
use it.

## Contributing

Issues and PRs welcome — especially around the AI-fallback learning loop, new site entries in
`data/sites.json`, and hardening the form-filling for React/custom-component sites.

## License

MIT — see [LICENSE](LICENSE).
