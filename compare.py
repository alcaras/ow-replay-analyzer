#!/usr/bin/env python3
"""Head-to-head metrics for a duel archive — feeds the written analysis.

Timing model: save S_N = end of P0's half of turn N. Each player's state is
sampled at the END OF THEIR OWN HALF: P0 turn N → S_N, P1 turn N → S_{N+1}.

Idle workers (fair): a worker is idle for a player's turn N if, at their
half-end snapshot, it stands on no in-progress build AND did not move during
their half AND (P1 only) is not standing on an improvement that completed in
the post-half roll — P1's builds finish AFTER his half, so a just-finished
build isn't neglect; P0's finish BEFORE his half, so his jobless workers had
a full turn to be reassigned.
"""
from __future__ import annotations

import sys
from collections import defaultdict

from owparse.gamedata import GameData
from owparse.save import Snapshot, series_value_at
from owparse.science import ScienceModel
from owparse.series import Series

CIVILIAN = {"UNIT_WORKER", "UNIT_SETTLER", "UNIT_SCOUT"}
DISCIPLE = "DISCIPLE"


def half_snaps(series: Series, pid: int):
    """(turn, cur, prev_of_own_half) samples at each player's own half-end."""
    turns = series.turns
    for i, t in enumerate(turns):
        if pid == 0:
            cur = series.snapshot(t)
            prev = series.snapshot(turns[i - 1]) if i > 0 else None
            yield t, cur, prev
        else:
            if i + 1 < len(turns):
                yield t, series.snapshot(turns[i + 1]), series.snapshot(t)


def idle_workers(cur: Snapshot, prev: Snapshot | None, pid: int) -> tuple[int, int]:
    """(idle, total) workers at this player's half-end."""
    idle = total = 0
    for u in cur.player_units(pid):
        if u.type != "UNIT_WORKER":
            continue
        total += 1
        tile = cur.tiles[u.tile_id]
        if tile.improvement and tile.improvement_turns_left > 0:
            continue  # building
        pu = prev.units.get(u.id) if prev else None
        if pu is None or pu.tile_id != u.tile_id:
            continue  # moved during the half (or new) — repositioning
        if pid == 1 and prev is not None:
            pt = prev.tiles.get(u.tile_id)
            if (tile.improvement and tile.improvement_turns_left == 0
                    and pt is not None and pt.improvement == tile.improvement
                    and pt.improvement_turns_left > 0):
                continue  # build completed at the roll AFTER his half
        idle += 1
    return idle, total


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: compare.py <archive dir>")
    archive = sys.argv[1]
    gd = GameData()
    series = Series(archive)
    sci = ScienceModel(gd)
    last = series.snapshot(series.turns[-1])
    names = {p.id: p.name for p in last.players.values()}

    rows = defaultdict(dict)   # turn -> {metric_pid: value}
    idle_tot = {0: [0, 0], 1: [0, 0]}
    for pid in (0, 1):
        for t, cur, prev in half_snaps(series, pid):
            r = rows[t]
            p = cur.players[pid]
            cities = cur.player_cities(pid)
            units = cur.player_units(pid)
            specs = sum(1 for x in cur.tiles.values()
                        if x.city_territory in {c.id for c in cities} and x.specialist)
            imps = sum(1 for x in cur.tiles.values()
                       if x.city_territory in {c.id for c in cities}
                       and x.improvement and x.improvement_turns_left == 0)
            mil = [u for u in units if u.type not in CIVILIAN and DISCIPLE not in u.type]
            workers = [u for u in units if u.type == "UNIT_WORKER"]
            idle, wtot = idle_workers(cur, prev, pid)
            idle_tot[pid][0] += idle
            idle_tot[pid][1] += wtot
            pop = sum(c.citizens for c in cities) + specs
            orate = series_value_at(p.yield_rate_history.get("YIELD_ORDERS", {}), t)
            r[f"cities{pid}"] = len(cities)
            r[f"pop{pid}"] = pop
            r[f"specs{pid}"] = specs
            r[f"imps{pid}"] = imps
            r[f"workers{pid}"] = len(workers)
            r[f"idle{pid}"] = idle
            r[f"mil{pid}"] = len(mil)
            r[f"milscore{pid}"] = series_value_at(p.military_power_history, t)
            r[f"sci{pid}"] = (p.science_rate_at(t) or 0) / 10
            r[f"techs{pid}"] = len(p.tech_count)
            r[f"laws{pid}"] = len(cur.player_roles(pid)["laws"])
            r[f"orders_left{pid}"] = (p.yield_stockpile.get("YIELD_ORDERS", 0)) / 10
            r[f"orate{pid}"] = (orate or 0) / 10
            r[f"goals{pid}"] = int(p.root_goals) if hasattr(p, "root_goals") else None

    # ── print per-turn table ────────────────────────────────────────
    cols = ["cities", "pop", "specs", "imps", "workers", "idle", "mil",
            "milscore", "sci", "techs", "laws", "orders_left"]
    hdr = "turn " + " ".join(f"{c}:{names[0][:3]}/{names[1][:3]}" for c in cols)
    print(hdr)
    for t in sorted(rows):
        r = rows[t]
        line = f"{t:>4} "
        for c in cols:
            a, b = r.get(f"{c}0"), r.get(f"{c}1")
            fa = "-" if a is None else (f"{a:g}" if isinstance(a, float) else str(a))
            fb = "-" if b is None else (f"{b:g}" if isinstance(b, float) else str(b))
            line += f"{fa}/{fb} ".rjust(len(c) + 8)
        print(line)

    print(f"\nIdle worker-turns: {names[0]} {idle_tot[0][0]}/{idle_tot[0][1]} "
          f"({100*idle_tot[0][0]/max(1,idle_tot[0][1]):.0f}%)  "
          f"{names[1]} {idle_tot[1][0]}/{idle_tot[1][1]} "
          f"({100*idle_tot[1][0]/max(1,idle_tot[1][1]):.0f}%)")

    # ── city foundings + captures ───────────────────────────────────
    print("\nCity timeline (founded / owner changes):")
    seen_owner = {}
    for t in series.turns:
        snap = series.snapshot(t)
        for c in snap.cities.values():
            key = c.id
            if key not in seen_owner:
                seen_owner[key] = c.player
                print(f"  T{c.founded_turn:>2} founded {gd.name(c.name_token):16s} by {names.get(c.player)}")
            elif seen_owner[key] != c.player:
                print(f"  T{t:>2} CAPTURED {gd.name(c.name_token):16s} {names.get(seen_owner[key])} → {names.get(c.player)}")
                seen_owner[key] = c.player

    # ── science gap decomposition at key turns ──────────────────────
    print("\nScience composition (grouped):")
    for T in (20, 30, 40, 50, 60):
        if T not in series.zips:
            continue
        snap = series.snapshot(T)
        line = f"  T{T}:"
        for pid in (0, 1):
            got = sci.player_science(snap, pid)
            groups = defaultdict(int)
            for c in got["cities"]:
                for lbl, v in c["items"]:
                    key = ("specialists" if "tier" in lbl or "specialist" in lbl.lower()
                           else "culture-scaled" if "culture" in lbl
                           else "projects" if any(k in lbl for k in ("Archive", "Treasury", "Forum"))
                           else "tiles/shrines" if "(tile)" in lbl or "Grove" in lbl
                           else "base/nation" if "Base" in lbl or "nation" in lbl or "Difficulty" in lbl
                           else "other-city")
                    groups[key] += v
            court = sum(v for lbl, v in got["rows"]
                        if any(k in lbl for k in ("Leader", "Heir", "Spouse", "Courtier")))
            flat = {k: round(v/10, 1) for k, v in groups.items()}
            line += (f"  {names[pid]}: total {got['total10']/10:.1f} "
                     f"(court {court/10:.1f}, {flat})")
        print(line)

    # ── kills / losses in the human war ─────────────────────────────
    from owparse.diff import unit_deltas
    losses = {0: 0, 1: 0}
    for i in range(1, len(series.turns)):
        a, b = series.snapshot(series.turns[i-1]), series.snapshot(series.turns[i])
        for pid in (0, 1):
            for d in unit_deltas(a, b, pid):
                if d.status == "gone" and d.unit.type not in CIVILIAN:
                    losses[pid] += 1
    print(f"\nMilitary units lost (whole game incl. tribes): "
          f"{names[0]} {losses[0]}, {names[1]} {losses[1]}")


if __name__ == "__main__":
    main()
