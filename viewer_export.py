#!/usr/bin/env python3
"""Export viewer/data.js + icons for the dual-POV replay viewer.

Base map (terrain/height/veg/rivers/resources) comes from the FINAL save
(terrain changes over a game are rare; noted limitation). Fog needs no
per-turn storage: a tile is revealed to team t at turn T iff
revealedTurn[t] <= T. Per-turn state (improvements, roads, territory,
units, cities, attacks) is sparse; each turn also embeds the two report
halves for the sidebars.

Usage: python3 viewer_export.py "<archive dir>" [--out viewer]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from owparse.gamedata import GameData
from owparse.military import combat_events
from owparse.report import Reporter
from owparse.series import Series

import os
# PNG dumps of game icons (improvements/resources/units/specialists +
# archetype crests). Point OW_IMG at your own extracted-assets dir.
OWREF = Path(os.environ.get(
    "OW_IMG", str(Path.home() / "Library/CloudStorage/Dropbox/cc/owreference/dist/img")))


def slug(ztype: str) -> str:
    for pre in ("IMPROVEMENT_", "RESOURCE_", "UNIT_", "SPECIALIST_"):
        if ztype.startswith(pre):
            return ztype[len(pre):].lower()
    return ztype.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive")
    ap.add_argument("--out", default="viewer")
    args = ap.parse_args()

    gd = GameData()
    series = Series(args.archive)
    rep = Reporter(series, gd)
    last = series.snapshot(series.turns[-1])
    W = last.map_width
    H = max(t.id for t in last.tiles.values()) // W + 1

    # ── base map from final save ────────────────────────────────────
    terr_l, hgt_l, veg_l = [""], [""], [""]
    def idx(lst, v):
        v = v or ""
        if v not in lst:
            lst.append(v)
        return lst.index(v)

    n = W * H
    terr = [0] * n; hgt = [0] * n; veg = [0] * n
    riv = [0] * n; res = [""] * n; rev0 = [-1] * n; rev1 = [-1] * n
    for t in last.tiles.values():
        i = t.id
        terr[i] = idx(terr_l, t.terrain.replace("TERRAIN_", ""))
        hgt[i] = idx(hgt_l, t.height.replace("HEIGHT_", ""))
        veg[i] = idx(veg_l, (t.vegetation or "").replace("VEGETATION_", ""))
        riv[i] = (1 if t.river_w else 0) | (2 if t.river_sw else 0) | (4 if t.river_se else 0)
        if t.resource:
            res[i] = slug(t.resource)
        rev0[i] = t.revealed_turn.get(0, -1)
        rev1[i] = t.revealed_turn.get(1, -1)

    players = {p.id: {"name": p.name, "nation": gd.name(p.nation),
                      "color": gd.nation_color(p.nation) or ("#e8b45a" if p.id == 0 else "#6ea0d2")}
               for p in last.players.values()}

    # ── landmarks: tiles sharing an ElementName form one landmark; a team
    # "discovers" it on first reveal of any of its tiles ────────────────
    lm_groups: dict[str, list[int]] = {}
    for t in last.tiles.values():
        if t.element_name:
            lm_groups.setdefault(t.element_name, []).append(t.id)
    landmarks = []
    for token, ids in sorted(lm_groups.items()):
        revs = {}
        for team in (0, 1):
            turns_rev = [last.tiles[i].revealed_turn.get(team) for i in ids]
            turns_rev = [x for x in turns_rev if x is not None]
            revs[str(team)] = min(turns_rev) if turns_rev else -1
        name = gd.text(token) or token.replace("TEXT_", "").replace("_", " ").title()
        # star at the centroid tile
        cx = sum(i % W for i in ids) / len(ids)
        cy = sum(i // W for i in ids) / len(ids)
        center = min(ids, key=lambda i: (i % W - cx) ** 2 + (i // W - cy) ** 2)
        landmarks.append({"n": name, "x": center, "tiles": ids, "rev": revs})

    # ── per-turn state ──────────────────────────────────────────────
    icon_slugs, crest_slugs = set(), set()
    turns_out = []
    for T in series.turns:
        snap = series.snapshot(T)
        prev_t = series.prev_turn(T)
        prev = series.snapshot(prev_t) if prev_t is not None else None

        tiles = {}
        for t in snap.tiles.values():
            e = {}
            if t.improvement:
                e["i"] = slug(t.improvement)
                icon_slugs.add(e["i"])
                if t.improvement_turns_left:
                    e["b"] = t.improvement_turns_left  # under construction
            if t.road:
                e["r"] = 1
            if t.city_territory is not None:
                c = snap.cities.get(t.city_territory)
                if c is not None:
                    e["o"] = c.player
                    e["c"] = c.id
            if t.city_site and t.city_site != "USED":
                # free or tribe-held city site (tribal camps live here)
                e["s"] = (t.tribe_site or "FREE").replace("TRIBE_", "").title()
            if e:
                tiles[t.id] = e

        units = []
        for u in snap.units.values():
            hp_max = gd.units.get(u.type, {}).get("hp", 20)
            units.append({
                "id": u.id, "t": slug(u.type), "n": gd.name(u.type),
                "p": u.player, "x": u.tile_id,
                "hp": hp_max - u.damage, "mhp": hp_max, "lv": u.level,
                "tribe": u.tribe if u.player < 0 else None,
            })
            icon_slugs.add(slug(u.type))

        cities = []
        for c in snap.cities.values():
            head = c.queue[0] if c.queue else None
            fam = gd.families.get(c.family, {})
            crest = (fam.get("class") or "").replace("FAMILYCLASS_", "").lower()
            crest_slugs.add(crest)
            spec = sum(1 for t in snap.tiles.values()
                       if t.city_territory == c.id and t.specialist)
            cities.append({
                "id": c.id, "x": c.tile_id, "p": c.player,
                "n": gd.name(c.name_token), "f": fam.get("class_name", ""),
                "crest": crest, "pop": c.citizens + spec,
                "prod": gd.name(head.ztype) if head else None,
                "cap": c.capital,
            })

        attacks = {pid: [{"x": ev.tile_id, "n": ev.attacks,
                          "k": bool(ev.target_killed)}
                         for ev in combat_events(prev, snap, pid)]
                   for pid in snap.players}

        # current vision per team: geometric approximation (unit iVision
        # radii + city territory + adjacent ring) unioned with the save's
        # WasVisibleThisTurn flags (only kept for the pending player).
        vis = {}
        from owparse.military import neighbors
        for team in snap.players:
            seen = set()
            for u in snap.units.values():
                if u.player != team:
                    continue
                rng = gd.units.get(u.type, {}).get("vision", 2) or 2
                frontier = {u.tile_id}
                seen.add(u.tile_id)
                for _ in range(rng):
                    nxt = set()
                    for tid in frontier:
                        for nb in neighbors(tid, W):
                            if nb not in seen:
                                seen.add(nb)
                                nxt.add(nb)
                    frontier = nxt
            for t in snap.tiles.values():
                c = snap.cities.get(t.city_territory) if t.city_territory is not None else None
                if c is not None and c.player == team:
                    seen.add(t.id)
                    seen.update(neighbors(t.id, W))
            for t in snap.tiles.values():
                if team in t.was_visible:
                    seen.add(t.id)
            vis[team] = sorted(seen)

        report = rep.turn_report(T)
        turns_out.append({"t": T, "tiles": tiles, "units": units,
                          "cities": cities, "attacks": attacks,
                          "vis": vis, "report": report})

    game_over = None
    tv = last.root.find("Game/TeamVictoriesCompleted/Team")
    if tv is not None and tv.get("Victory"):
        team = int(tv.text or -1)
        game_over = {
            "team": team,
            "winner": players.get(team, {}).get("name", f"team {team}"),
            "victory": (tv.get("Victory") or "").replace("VICTORY_", "").title(),
            "turn": last.turn,
        }

    data = {
        "game": last.game_name, "w": W, "h": H,
        "players": players,
        "gameOver": game_over,
        "L": {"terr": terr_l, "hgt": hgt_l, "veg": veg_l},
        "terr": terr, "hgt": hgt, "veg": veg, "riv": riv, "res": res,
        "rev": {"0": rev0, "1": rev1},
        "landmarks": landmarks,
        "turns": turns_out,
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.js").write_text("const DATA=" + json.dumps(data, separators=(",", ":")) + ";")

    # ── icons ───────────────────────────────────────────────────────
    icon_dir = out / "icons"
    icon_dir.mkdir(exist_ok=True)
    for s in sorted(icon_slugs | {r for r in res if r}):
        for sub in ("improvements", "resources", "shrines", "units", "specialists"):
            p = OWREF / "icons" / sub / f"{s}.png"
            if p.exists():
                shutil.copy(p, icon_dir / f"{s}.png")
                break
    for s in sorted(crest_slugs):
        p = OWREF / "archetypes" / f"{s}.png"
        if p.exists():
            shutil.copy(p, icon_dir / f"crest_{s}.png")

    kb = (out / "data.js").stat().st_size // 1024
    print(f"Wrote {out}/data.js ({kb} KB), {len(list(icon_dir.glob('*.png')))} icons, "
          f"{len(turns_out)} turns")


if __name__ == "__main__":
    main()
