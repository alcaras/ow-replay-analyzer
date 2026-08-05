#!/usr/bin/env python3
"""Turn-by-turn analysis of an Old World mp-archive save folder.

Usage:
  python3 analyze.py "<archive dir>" [--turns A-B] [--out reports/]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from owparse.gamedata import GameData
from owparse.report import Reporter, render_markdown
from owparse.series import Series


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--turns", default=None, help="e.g. 5-20 or 12")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--stdout", action="store_true", help="print markdown instead of writing files")
    args = ap.parse_args()

    gd = GameData()
    series = Series(args.archive)
    rep = Reporter(series, gd)

    turns = series.turns
    if args.turns:
        lo, _, hi = args.turns.partition("-")
        lo, hi = int(lo), int(hi or lo)
        turns = [t for t in turns if lo <= t <= hi]

    out = Path(args.out)
    all_reports = []
    for t in turns:
        r = rep.turn_report(t)
        all_reports.append(r)
        md = render_markdown(r)
        if args.stdout:
            print(md)
        else:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"turn-{t:03d}.md").write_text(md)
    if not args.stdout:
        (out / "turns.json").write_text(json.dumps(all_reports, indent=1))
        print(f"Wrote {len(turns)} turn reports + turns.json to {out}/  (gaps: {series.gaps})")


if __name__ == "__main__":
    main()
