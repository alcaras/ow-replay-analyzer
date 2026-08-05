#!/usr/bin/env python3
"""Emit the FACT SHEET for a duel archive — the single source of truth the
written report is allowed to cite.

Everything a narrative might claim gets computed here, once, from the saves
(or the game's XML/C# reference). The report writer (Claude) works FROM this
JSON; a number that isn't in it either gets added here first or doesn't go
in the report. See docs/game-report-method.md for the protocol.

Usage: python3 factsheet.py "<archive dir>" [--out analysis/factsheet.json]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from owparse.gamedata import GameData
from owparse.military import combat_events
from owparse.save import series_value_at
from owparse.science import ScienceModel
from owparse.series import Series
from owparse.diff import unit_deltas
from compare import half_snaps, idle_workers

CIVILIAN = {"UNIT_WORKER", "UNIT_SETTLER", "UNIT_SCOUT"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--out", default="analysis/factsheet.json")
    args = ap.parse_args()

    gd = GameData()
    s = Series(args.archive)
    sci = ScienceModel(gd)
    last = s.snapshot(s.turns[-1])
    final_turn = last.turn
    names = {p.id: p.name for p in last.players.values()}

    F: dict = {"archive": Path(args.archive).name, "turns": s.turns, "gaps": s.gaps,
               "players": {pid: {"name": p.name, "nation": gd.name(p.nation)}
                           for pid, p in last.players.items()}}

    # victory
    tv = last.root.find("Game/TeamVictoriesCompleted/Team")
    if tv is not None and tv.get("Victory"):
        F["victory"] = {"team": int(tv.text or -1),
                        "winner": names.get(int(tv.text or -1)),
                        "type": (tv.get("Victory") or "").replace("VICTORY_", "").title(),
                        "turn": final_turn}

    # ── per-turn metrics at each player's own half-end ──────────────
    metrics = defaultdict(lambda: {0: {}, 1: {}})
    idle_tot = {0: [0, 0], 1: [0, 0]}
    for pid in (0, 1):
        for t, cur, prev in half_snaps(s, pid):
            p = cur.players[pid]
            cities = cur.player_cities(pid)
            cid = {c.id for c in cities}
            specs = sum(1 for x in cur.tiles.values() if x.city_territory in cid and x.specialist)
            imps = sum(1 for x in cur.tiles.values() if x.city_territory in cid
                       and x.improvement and x.improvement_turns_left == 0)
            idle, wtot = idle_workers(cur, prev, pid)
            idle_tot[pid][0] += idle
            idle_tot[pid][1] += wtot
            money = series_value_at(p.yield_rate_history.get("YIELD_MONEY", {}), t) or 0
            gdp = money / 10
            for y in ("YIELD_FOOD", "YIELD_WOOD", "YIELD_STONE", "YIELD_IRON"):
                r = series_value_at(p.yield_rate_history.get(y, {}), t)
                pr = series_value_at(cur.yield_price_history.get(y, {}), t)
                if r and pr:
                    gdp += (r / 10) * (pr / 10_000)
            m = {"cities": len(cities),
                 "pop": sum(c.citizens for c in cities) + specs,
                 "specialists": specs, "improvements": imps,
                 "workers": sum(1 for u in cur.player_units(pid) if u.type == "UNIT_WORKER"),
                 "idle_workers": idle,
                 "military_units": sum(1 for u in cur.player_units(pid)
                                       if u.type not in CIVILIAN and "DISCIPLE" not in u.type),
                 "milscore": series_value_at(p.military_power_history, t),
                 "sci_rate": round((p.science_rate_at(t) or 0) / 10, 1),
                 "orders_rate": round((series_value_at(p.yield_rate_history.get("YIELD_ORDERS", {}), t) or 0) / 10, 1),
                 "orders_left": round(p.yield_stockpile.get("YIELD_ORDERS", 0) / 10, 1),
                 "gdp": round(gdp),
                 "techs": len(p.tech_count),
                 "laws": len(cur.player_roles(pid)["laws"])}
            for k, v in m.items():
                metrics[k][pid][t] = v
    F["metrics"] = {k: {pid: metrics[k][pid] for pid in (0, 1)} for k in metrics}
    F["idle_worker_turns"] = {pid: {"idle": idle_tot[pid][0], "total": idle_tot[pid][1],
                                    "pct": round(100 * idle_tot[pid][0] / max(1, idle_tot[pid][1]))}
                              for pid in (0, 1)}

    # ── timelines ───────────────────────────────────────────────────
    tl = {pid: {} for pid in (0, 1)}
    for pid in (0, 1):
        p = last.players[pid]
        tl[pid]["laws_adopted"] = [(e.turn, gd.name(e.data[0])) for e in p.permanent_log
                                   if e.type == "LAW_ADOPTED"]
        tl[pid]["wonders_completed"] = [(e.turn, e.text) for e in p.permanent_log
                                        if e.type == "WONDER_ACTIVITY" and "completed" in e.text
                                        and names[pid] in e.text]
        tl[pid]["techs_discovered"] = sorted((e.turn, gd.name(e.data[0]))
                                             for e in p.permanent_log if e.type == "TECH_DISCOVERED")
        tl[pid]["religions_founded"] = [(e.turn, e.text[:60]) for e in p.permanent_log
                                        if e.type == "RELIGION_FOUNDED"]
        tl[pid]["cities_founded"] = sorted((c.founded_turn, gd.name(c.name_token))
                                           for c in last.cities.values()
                                           if (c.player == pid or (c.player < 0 and pid == 0)))  # razed keep founder? see note
    F["timelines"] = tl
    F["timeline_note"] = ("cities_founded attribution uses final owner; a razed city (player -1) "
                          "is attributed by FirstPlayer if needed — verify per city when citing.")

    # ── diplomacy + combat between humans ───────────────────────────
    dipl = []
    prev_d = None
    for t in s.turns:
        d = s.snapshot(t).team_diplomacy(0, 1)
        if d != prev_d:
            dipl.append((t, d))
            prev_d = d
    F["human_diplomacy"] = dipl
    combat = []
    for i in range(1, len(s.turns)):
        a, b = s.snapshot(s.turns[i - 1]), s.snapshot(s.turns[i])
        for pid in (0, 1):
            for ev in combat_events(a, b, pid):
                if ev.target is not None and ev.target.player in (0, 1) and ev.target.player != pid:
                    combat.append({"turn": s.turns[i - 1] if pid == 1 else s.turns[i],
                                   "attacker": names[pid],
                                   "target_unit": gd.name(ev.target.type),
                                   "target_owner": names[ev.target.player],
                                   "xy": b.xy(ev.tile_id),
                                   "killed": bool(ev.target_killed),
                                   "damage": ev.target_damage})
    F["human_combat"] = combat
    losses = {0: 0, 1: 0}
    for i in range(1, len(s.turns)):
        a, b = s.snapshot(s.turns[i - 1]), s.snapshot(s.turns[i])
        for pid in (0, 1):
            for d in unit_deltas(a, b, pid):
                if d.status == "gone" and d.unit.type not in CIVILIAN:
                    losses[pid] += 1
    F["military_units_lost_incl_tribes"] = losses

    # ── landmarks (per-group ground truth; beware bonus-count proxies) ──
    groups: dict[str, list] = {}
    for t in last.tiles.values():
        if t.element_name:
            groups.setdefault(t.element_name, []).append(t)
    lm = []
    for tok, tiles in groups.items():
        revs = {}
        for team in (0, 1):
            rr = [x.revealed_turn.get(team) for x in tiles if x.revealed_turn.get(team) is not None]
            revs[team] = min(rr) if rr else None
        # game-end map reveal stamps final_turn — that is NOT scouting
        art = {team: (revs[team] == final_turn) for team in (0, 1)}
        eff = {team: (None if art[team] else revs[team]) for team in (0, 1)}
        if eff[0] is not None and (eff[1] is None or eff[0] < eff[1]):
            first = names[0]
        elif eff[1] is not None and (eff[0] is None or eff[1] < eff[0]):
            first = names[1]
        else:
            first = "tie/none"
        lm.append({"name": gd.text(tok) or tok, "tiles": len(tiles),
                   "revealed_turn": revs, "end_reveal_artifact": art, "first": first})
    F["landmarks"] = {"groups": lm,
                      "first_revealer_counts": dict(Counter(x["first"] for x in lm)),
                      "bonus_counts_note": (
                          "BONUS_NAMED/DISCOVERED_LANDMARK counts are lossy proxies: the naming "
                          "branch (Tile.cs ~8356) requires sole-revealer AND no landmark event "
                          "firing; the event branch pays NEITHER bonus. Use the per-group reveal "
                          "table above for who-found-what claims.")}
    for pid in (0, 1):
        bc = {c.tag: int(c.text or 0)
              for c in last.root.findall(f"Player[@ID='{pid}']/BonusCount/") }
        F["landmarks"][f"bonus_counts_{names[pid]}"] = {
            "named": bc.get("BONUS_NAMED_LANDMARK", 0),
            "discovered": bc.get("BONUS_DISCOVERED_LANDMARK", 0)}

    # ── science decomposition at checkpoints ────────────────────────
    decomp = {}
    for T in range(10, final_turn + 1, 10):
        if T not in s.zips:
            continue
        snap = s.snapshot(T)
        decomp[T] = {}
        for pid in (0, 1):
            got = sci.player_science(snap, pid)
            g = defaultdict(int)
            for c in got["cities"]:
                for lbl, v in c["items"]:
                    key = ("specialists" if "tier" in lbl or "specialist" in lbl.lower()
                           else "culture_scaled" if "culture" in lbl
                           else "projects" if any(k in lbl for k in ("Archive", "Treasury", "Forum"))
                           else "tiles" if "(tile)" in lbl or "Grove" in lbl
                           else "base_nation_difficulty" if ("Base" in lbl or "nation" in lbl or "Difficulty" in lbl)
                           else "other_city")
                    g[key] += v
            court = sum(v for lbl, v in got["rows"]
                        if any(k in lbl for k in ("Leader", "Heir", "Spouse", "Courtier")))
            decomp[T][pid] = {"total": round(got["total10"] / 10, 1),
                              "recorded": round((snap.players[pid].science_rate_at(T) or 0) / 10, 1),
                              "court": round(court / 10, 1),
                              **{k: round(v / 10, 1) for k, v in g.items()}}
    F["science_decomposition"] = decomp

    # ── court quality at checkpoints ────────────────────────────────
    court = {}
    for T in (10, 20, 30, 40, 50, 60):
        if T not in s.zips:
            continue
        snap = s.snapshot(T)
        court[T] = {}
        for pid in (0, 1):
            roles = snap.player_roles(pid)
            def wis(cid):
                return snap.characters.get(cid, {}).get("ratings", {}).get("RATING_WISDOM")
            court[T][pid] = {"leader_wis": wis(roles["leader"]),
                            "heir_wis": wis(roles["heir"]),
                            "spouse_wis": wis(roles["spouse"]),
                            "courtier_wis": [wis(c) for c in roles["courtiers"]]}
    F["court"] = court

    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(F, indent=1, default=str))
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
