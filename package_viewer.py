#!/usr/bin/env python3
"""Package a game's replay viewer into ONE self-contained HTML file.

Inlines data.js and every icon (as base64 data URIs) into viewer/index.html
so the result can be shared as a single file — open it in any browser, no
server, no other files.

Usage:
  python3 viewer_export.py "<archive dir>" --out viewer   # if not done yet
  python3 package_viewer.py [--viewer viewer] [--out "alcaras-v-lich.html"]
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewer", default="viewer")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    vdir = Path(args.viewer)
    html = (vdir / "index.html").read_text()
    data = (vdir / "data.js").read_text()

    # game name for the default output filename
    m = re.search(r'"game":"([^"]*)"', data) or re.search(r"game.{0,3}:.{0,2}\"([^\"]*)\"", data)
    game = (m.group(1) if m else "game").strip()
    out = Path(args.out) if args.out else Path(
        re.sub(r"[^A-Za-z0-9]+", "-", game).strip("-").lower() + "-replay.html")

    icons = {}
    for p in sorted((vdir / "icons").glob("*.png")):
        icons[p.stem] = "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()

    inline = (f"<script>const ICON_DATA={json.dumps(icons)};</script>\n"
              f"<script>{data}</script>")
    html = html.replace('<script src="data.js"></script>', inline)
    out.write_text(html)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB) — single file, "
          f"open in any browser or share as-is.")


if __name__ == "__main__":
    main()
