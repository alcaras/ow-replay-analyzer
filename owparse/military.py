"""Combat/action attribution for one player-half.

Signals per diff window (S_a → S_b, one turn roll inside):
- P0 units keep their action Cooldown in S_b (COOLDOWN_ATTACK /
  ADDED_ROAD / FORTIFY / HEALED / PROMOTED / UPGRADED / BUY_TILE …).
  P1 cooldowns are cleared at the roll before the next archived save,
  so P1 actions rely on the signals below.
- Player.RecentAttacks: tile → count, +1 per attack that player makes on
  that tile, −1 decay per turn. delta = cur − max(0, prev − 1) ≈ attacks
  made on the tile during the window.
- Unit damage deltas / disappearances, with hex adjacency to pair
  attackers and targets. Pairings are tagged with a confidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .save import Snapshot, Unit

# Engine Utils.DIRECTION_OFFSET, dirs [NW,NE,E,SE,SW,W]
def neighbors(tile_id: int, width: int) -> list[int]:
    x, y = tile_id % width, tile_id // width
    odd = (y & 1) == 1
    ox = (-1, 0, 1, 0, -1, -1) if odd else (0, 1, 1, 1, 0, -1)
    oy = (1, 1, 0, -1, -1, 0)
    out = []
    for i in range(6):
        nx, ny = x + ox[i], y + oy[i]
        if 0 <= nx < width and ny >= 0:
            out.append(ny * width + nx)
    return out


def attack_tiles(prev: Snapshot | None, cur: Snapshot, pid: int) -> dict[int, int]:
    """tile_id → attacks made by `pid` on it during the window.

    RecentAttacks decays −1/turn ONLY on tiles passing
    Tile.shouldDecayRecentAttacks (damaged cities / contested settlements
    are exempt, and entries are observed sticky for decades). Counting
    only *increases* avoids false positives on sticky tiles, at the cost
    of missing an attack that exactly offsets a decay tick (rare)."""
    prev_map = dict(prev.players[pid].recent_attacks) if prev else {}
    cur_map = dict(cur.players[pid].recent_attacks)
    out = {}
    for tid, n in cur_map.items():
        d = n - prev_map.get(tid, 0)
        if d > 0:
            out[tid] = d
    return out


@dataclass
class CombatEvent:
    attacker_pid: int
    tile_id: int                 # tile attacked
    attacks: int                 # number of attacks on it in window
    target: Unit | None          # defender (from prev snapshot)
    target_killed: bool
    target_damage: int | None    # damage dealt to it (if it survived)
    attacker_units: list[Unit] = field(default_factory=list)  # candidates
    confidence: str = "inferred"  # 'cooldown' | 'inferred'


def combat_events(prev: Snapshot | None, cur: Snapshot, pid: int) -> list[CombatEvent]:
    """Attacks made by `pid` during the window prev→cur."""
    if prev is None:
        return []
    width = cur.map_width
    events = []
    at = attack_tiles(prev, cur, pid)
    # candidate attackers: player's units in cur (position at end of their
    # half for P0; for P1 the position also holds — opponent can't move them)
    my_units = cur.player_units(pid)
    with_cd = {u.id for u in my_units if u.cooldown == "COOLDOWN_ATTACK"}
    for tid, n in at.items():
        # defender: whoever stood there in prev (excluding own units)
        prev_tile = prev.tiles.get(tid)
        target = None
        if prev_tile:
            for uid in prev_tile.unit_ids:
                u = prev.units[uid]
                if u.player != pid:
                    target = u
                    break
        killed = target is not None and target.id not in cur.units
        dmg = None
        if target is not None and target.id in cur.units:
            dmg = cur.units[target.id].damage - target.damage
        nbs = set(neighbors(tid, width)) | {tid}
        # ranged units can attack from range 2 — include distance-2 ring
        ring2 = set()
        for nb in list(nbs):
            ring2.update(neighbors(nb, width))
        cands = [u for u in my_units
                 if u.tile_id in nbs or u.tile_id in ring2]
        cd_cands = [u for u in cands if u.id in with_cd]
        events.append(CombatEvent(
            attacker_pid=pid, tile_id=tid, attacks=n, target=target,
            target_killed=killed, target_damage=dmg,
            attacker_units=cd_cands or cands,
            confidence="cooldown" if cd_cands else "inferred",
        ))
    return events


ACTION_COOLDOWNS = {
    "COOLDOWN_ATTACK": "attacked",
    "COOLDOWN_ADDED_ROAD": "built road",
    "COOLDOWN_FORTIFY": "fortified",
    "COOLDOWN_HEALED": "healed up",
    "COOLDOWN_PROMOTED": "took promotion",
    "COOLDOWN_UPGRADED": "upgraded",
    "COOLDOWN_BUY_TILE": "bought tile",
    "COOLDOWN_GENERAL": "general action",
    "COOLDOWN_UNLIMBERED": "unlimbered",
    "COOLDOWN_BUILDING": "building",
}


def roads_built(prev: Snapshot | None, cur: Snapshot) -> list[int]:
    """Tiles whose road appeared during the window."""
    if prev is None:
        return []
    return [t.id for t in cur.tiles.values()
            if t.road and (t.id not in prev.tiles or not prev.tiles[t.id].road)]
