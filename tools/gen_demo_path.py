"""Demo: runs the 2 e2e paths (Google OAuth + plain form) against local fixtures, no network,
then renders out/path.html. Used to produce the example screenshot for the README."""
import os, asyncio, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
os.environ["OAUTH_FAKE_HOST"] = "e2e_gchooser"
from farmer.browser import Browser
from farmer.log import Log
from farmer import tree
import path_viewer

FIX = ROOT / "fixtures"
U = lambda n: (FIX / f"{n}.html").as_uri()
CFG = {"key_url": U("e2e_keys"), "key_re": r"sk-e2e-[A-Za-z0-9]+"}


async def main():
    async with Browser(headless=True, profile=False) as ctx:
        await ctx.new_page()
        first = True
        for nm, vg in [("DemoSite-Google", True), ("DemoSite-Form", False)]:
            lg = Log(nm, reset=first); first = False
            await tree.run_site(ctx, {"name": nm, "url": U("e2e_landing"),
                                      "via_google": vg, "provider_cfg": CFG}, lg)
    path_viewer.render()
    out = ROOT / "out" / "path.html"
    print(f"open in browser: {out}")
    print(f"            file:///{out.as_posix()}")


asyncio.run(main())
