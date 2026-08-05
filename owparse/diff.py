"""Cross-save derivations: worker ordinals, build completions, unit deltas.

Timeline model (verified for this archive): every save S_N is taken right
after player 0 ends turn N (PlayerTurn=1). So:
  - P0's turn-N actions live in diff(S_{N-1} → S_N)
  - P1's turn-N actions live in diff(S_N → S_{N+1})
Turn-roll (production completion, yield accrual, tribe moves) happens when
P1 ends their half, and its log entries are tagged with the new turn.
"""
from __future__ import annotations

from dataclasses import dataclass

from .gamedata import GameData, YIELDS_MULTIPLIER
from .save import QueueItem, Snapshot, Unit
from .series import Series


# ── worker ordinals ──────────────────────────────────────────────────
def worker_ordinals(series: Series, unit_types: set[str] | None = None) -> dict[tuple[int, int], tuple[str, int]]:
    """(player, unit_id) → (family, per-family ordinal) for workers,
    numbered by production order (CreateTurn, then id), stable across the
    whole series (dead workers keep their number)."""
    unit_types = unit_types or {"UNIT_WORKER"}
    seen: dict[tuple[int, int], tuple[int, str]] = {}   # (pid, uid) → (create_turn, family)
    for t in series.turns:
        snap = series.snapshot(t)
        for u in snap.units.values():
            if u.type in unit_types and u.player >= 0:
                key = (u.player, u.id)
                if key not in seen:
                    seen[key] = (u.create_turn, u.family or "")
    counters: dict[tuple[int, str], int] = {}
    out: dict[tuple[int, int], tuple[str, int]] = {}
    for (pid, uid), (ct, fam) in sorted(seen.items(), key=lambda kv: (kv[0][0], kv[1][0], kv[0][1])):
        counters[(pid, fam)] = counters.get((pid, fam), 0) + 1
        out[(pid, uid)] = (fam, counters[(pid, fam)])
    return out


# ── build completion scanning ────────────────────────────────────────
def _city_specialist_count(snap: Snapshot, city_id: int) -> int:
    return sum(1 for t in snap.tiles.values()
               if t.city_territory == city_id and t.specialist)


def completion_turn(series: Series, from_turn: int, city_id: int, item: QueueItem) -> int | None:
    """First archived turn where `item` (queue head at from_turn) shows as
    completed for the city. None if it never completes in the series."""
    base = series.snapshot(from_turn)
    city0 = base.cities.get(city_id)
    if city0 is None:
        return None
    if item.build == "BUILD_UNIT":
        n0 = city0.unit_production_counts.get(item.ztype, 0)
        probe = lambda c, s: c.unit_production_counts.get(item.ztype, 0) > n0
    elif item.build == "BUILD_PROJECT":
        n0 = city0.project_counts.get(item.ztype, 0)
        probe = lambda c, s: c.project_counts.get(item.ztype, 0) > n0
    elif item.build == "BUILD_SPECIALIST":
        n0 = _city_specialist_count(base, city_id)
        probe = lambda c, s: _city_specialist_count(s, city_id) > n0
    else:
        return None
    t = series.next_turn(from_turn)
    while t is not None:
        snap = series.snapshot(t)
        c = snap.cities.get(city_id)
        if c is None:
            return None
        if probe(c, snap):
            return t
        t = series.next_turn(t)
    return None


@dataclass
class BuildStatus:
    item: QueueItem
    cost10: int | None          # cost ×10 (game scaling formula, no % modifiers)
    rate10: int | None          # observed progress gained this turn (×10)
    turns_left: int | None      # state-based estimate: ceil((cost−progress)/rate)
    completes_turn: int | None  # actual completion turn (verification only)


def _scaled_cost10(gd: GameData, snap, city_id: int, item: QueueItem) -> int | None:
    """Cost as the game computes it at this state (Player.getUnitBuildCost:
    base + per-player-produced + per-city-produced), % modifiers omitted."""
    base = gd.build_cost10(item.build, item.ztype)
    if base is None or item.build != "BUILD_UNIT":
        return base
    u = gd.units.get(item.ztype, {})
    city = snap.cities.get(city_id)
    if city is not None and u.get("prod_city"):
        base += city.unit_production_counts.get(item.ztype, 0) * u["prod_city"] * YIELDS_MULTIPLIER
    # per-player term uses units produced counts from the save when present
    return base


def build_status(series: Series, gd: GameData, turn: int, city_id: int,
                 item: QueueItem, prev_item: QueueItem | None) -> BuildStatus:
    snap = series.snapshot(turn)
    cost10 = _scaled_cost10(gd, snap, city_id, item)
    rate10 = None
    if prev_item is not None and prev_item.build == item.build and prev_item.ztype == item.ztype:
        d = item.progress - prev_item.progress
        if d > 0:
            rate10 = d
    est = None
    if cost10 and rate10:
        est = max(1, -(-(cost10 - item.progress) // rate10))  # ceil div
    done = completion_turn(series, turn, city_id, item)
    return BuildStatus(item, cost10, rate10, est, done)


# ── unit deltas ──────────────────────────────────────────────────────
@dataclass
class UnitDelta:
    unit: Unit                  # state in the later snapshot (or last known)
    status: str                 # 'active'|'new'|'gone'
    moved_from: int | None = None
    damage_delta: int = 0       # hp units; + = took damage
    promotions_gained: list[str] = None
    upgraded_from: str | None = None  # unit kept its id but changed type


def unit_deltas(prev: Snapshot | None, cur: Snapshot, pid: int) -> list[UnitDelta]:
    out = []
    prev_units = {u.id: u for u in prev.player_units(pid)} if prev else {}
    cur_units = {u.id: u for u in cur.player_units(pid)}
    for uid, u in cur_units.items():
        p = prev_units.get(uid)
        if p is None:
            out.append(UnitDelta(u, "new", promotions_gained=[]))
        else:
            out.append(UnitDelta(
                u, "active",
                moved_from=p.tile_id if p.tile_id != u.tile_id else None,
                damage_delta=u.damage - p.damage,
                promotions_gained=[x for x in u.promotions if x not in p.promotions],
                upgraded_from=p.type if p.type != u.type else None,
            ))
    for uid, p in prev_units.items():
        if uid not in cur_units:
            out.append(UnitDelta(p, "gone", promotions_gained=[]))
    return out
