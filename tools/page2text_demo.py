"""Demo VISIVA: come un sito viene convertito in page2text (cio' che 'vede' l'AI testuale).
Per ogni snapshot: a SINISTRA lo screenshot renderizzato, a DESTRA il testo compatto page2text.
Serve a capire a colpo d'occhio se page2text rende bene una pagina (o se perde form/bottoni).

Uso: py -3.11 -X utf8 page2text_demo.py [snap1.html snap2.html ...]
     senza argomenti usa un set di default (Mistral form, Cohere, DeepInfra).
Output: out/page2text_demo.html  (apri nel browser)
"""
from __future__ import annotations
import asyncio, sys, base64, html as _h
from pathlib import Path
from playwright.async_api import async_playwright
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from farmer.page2text import page_to_text_all_frames

ROOT = Path(__file__).parent
OUT = ROOT / "out" / "page2text_demo.html"

DEFAULTS = [
    ("Mistral — form crea organizzazione", "fixtures/snaps/mistral/pagina_chiavi.html"),
    ("Cohere — dashboard chiavi",          "fixtures/snaps/cohere/pagina_chiavi.html"),
    ("Fireworks — dashboard",              "fixtures/snaps/fireworksai/pagina_chiavi.html"),
]


async def one(pw, title, path):
    p = ROOT / path
    if not p.exists():
        return None
    b = await pw.chromium.launch()
    pg = await b.new_page(viewport={"width": 1000, "height": 760})
    try:
        await pg.set_content(p.read_text(encoding="utf-8", errors="ignore"), wait_until="domcontentloaded")
        await pg.wait_for_timeout(400)
        png = await pg.screenshot(type="png", full_page=False)
        txt = await page_to_text_all_frames(pg, max_lines=60)
    except Exception as e:
        txt = f"[errore render: {e}]"; png = b""
    await b.close()
    return {"title": title, "png": base64.b64encode(png).decode(), "txt": txt}


CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f4f5;color:#18181b}
header{padding:18px 24px;background:#fff;border-bottom:1px solid #e4e4e7}
header h1{margin:0;font-size:19px} header p{margin:4px 0 0;color:#71717a;font-size:13px}
.card{background:#fff;margin:20px;border:1px solid #e4e4e7;border-radius:12px;overflow:hidden}
.card>h2{margin:0;padding:12px 16px;font-size:15px;background:#fafafa;border-bottom:1px solid #e4e4e7}
.split{display:grid;grid-template-columns:1fr 1fr;gap:0}
@media(max-width:820px){.split{grid-template-columns:1fr}}
.side{padding:14px;min-width:0}
.side.left{border-right:1px solid #e4e4e7}
.side h3{margin:0 0 8px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#a1a1aa}
.side img{max-width:100%;border:1px solid #e4e4e7;border-radius:6px;display:block}
pre{margin:0;white-space:pre-wrap;word-break:break-word;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
    background:#0f172a;color:#e2e8f0;padding:12px;border-radius:6px;overflow-x:auto}
.legend{margin:20px;padding:12px 16px;background:#fff;border:1px solid #e4e4e7;border-radius:10px;font-size:13px;color:#3f3f46}
.legend code{background:#f4f4f5;padding:1px 5px;border-radius:4px}
"""

LEGEND = """<div class="legend"><b>Legenda page2text:</b>
<code>[X]</code> bottone · <code>&lt;X&gt;</code> link · <code>*X*(t)</code> campo input (t=tipo) ·
<code>[ ] Y</code> checkbox vuota · <code>[x] Y</code> spuntata · <code>V-X-V</code> tendina ·
<code># H</code> titolo · <code>~testo~</code> nota</div>"""


async def main():
    args = sys.argv[1:]
    items = [(Path(a).stem, a) for a in args] if args else DEFAULTS
    async with async_playwright() as pw:
        cards = []
        for title, path in items:
            r = await one(pw, title, path)
            if not r:
                cards.append(f'<div class="card"><h2>{_h.escape(title)}</h2>'
                             f'<div class="side">snapshot non trovato: {_h.escape(path)}</div></div>')
                continue
            img = (f'<img src="data:image/png;base64,{r["png"]}">' if r["png"]
                   else "<i>nessuno screenshot</i>")
            cards.append(
                f'<div class="card"><h2>{_h.escape(r["title"])}</h2><div class="split">'
                f'<div class="side left"><h3>Sito (come lo vede un umano)</h3>{img}</div>'
                f'<div class="side"><h3>page2text (come lo vede l\'AI)</h3>'
                f'<pre>{_h.escape(r["txt"])}</pre></div></div></div>')
    doc = (f'<!doctype html><meta charset="utf-8"><title>page2text — conversione</title>'
           f'<style>{CSS}</style><header><h1>Come un sito diventa page2text</h1>'
           f'<p>Sinistra: pagina renderizzata. Destra: testo compatto passato all\'AI (no vision).</p>'
           f'</header>{LEGEND}{"".join(cards)}')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print("scritto:", OUT)


if __name__ == "__main__":
    asyncio.run(main())
