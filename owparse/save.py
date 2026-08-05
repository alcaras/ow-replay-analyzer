"""Parse one Old World save XML into a typed Snapshot.

Conventions of the save format (verified against v1.0.84044 saves):
- Yield-ish numbers (progress, stockpiles, rates, costs) are ×10.
- Serializer omits default values: a missing <Damage> means 0, missing
  <Citizens> means 0, missing Player attr on Unit never happens but
  Player="-1" means tribe-owned.
- Units are nested inside <Tile> elements.
- Per-team maps appear as <T0>/<T1>/… or <T.0>/… child tags; per-player as
  <P.0>/…
- LogData Text is TMP rich text; we strip markup but keep the raw too.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_TAGRE = re.compile(r"<[^>]+>")


def strip_markup(s: str) -> str:
    return _TAGRE.sub("", html.unescape(s or "")).strip()


def _int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _kv_int(elem) -> dict[str, int]:
    """<X><YIELD_FOOD>100</YIELD_FOOD>…</X> → {'YIELD_FOOD': 100}"""
    return {} if elem is None else {c.tag: _int(c.text) for c in elem}


def _team_map(elem) -> dict[int, int]:
    """<RevealedTurn><T1>33</T1></RevealedTurn> → {1: 33} (T or T. prefix)."""
    out = {}
    if elem is not None:
        for c in elem:
            m = re.fullmatch(r"T\.?(\d+)", c.tag)
            if m:
                out[int(m.group(1))] = _int(c.text)
    return out


def _turn_series(elem) -> dict[int, int]:
    """<YIELD_SCIENCE><T44>536</T44>…</YIELD_SCIENCE> → {44: 536} sparse:
    a value is recorded on the turn the rate *changed*."""
    out = {}
    if elem is not None:
        for c in elem:
            m = re.fullmatch(r"T(\d+)", c.tag)
            if m:
                out[int(m.group(1))] = _int(c.text)
    return out


def series_value_at(series: dict[int, int], turn: int) -> int | None:
    """Value of a sparse turn-series at `turn` (last change ≤ turn)."""
    best = None
    for t in sorted(series):
        if t <= turn:
            best = series[t]
        else:
            break
    return best


@dataclass
class QueueItem:
    build: str          # BUILD_UNIT / BUILD_PROJECT / BUILD_SPECIALIST / ...
    ztype: str          # UNIT_SETTLER / PROJECT_TREASURY_1 / ...
    progress: int       # ×10
    cost: dict[str, int]  # resource YieldCost (×10)
    data: int = -1


@dataclass
class LogEntry:
    type: str
    turn: int
    data: list[str]
    text: str
    raw_text: str


@dataclass
class Unit:
    id: int
    type: str
    player: int          # -1 = tribe
    tribe: str
    tile_id: int
    create_turn: int
    original_player: int
    family: str | None   # FAMILY_* for the owning player, if any
    damage: int = 0
    xp: int = 0
    level: int = 0
    promotions: list[str] = field(default_factory=list)
    promotions_available: list[str] = field(default_factory=list)
    cooldown: str | None = None
    cooldown_turns: int = 0
    turn_steps: int = 0
    turns_since_last_move: int = 0
    general_id: int | None = None


@dataclass
class City:
    id: int
    tile_id: int
    player: int
    family: str
    founded_turn: int
    name_token: str
    citizens: int
    governor_id: int | None
    capital: bool
    queue: list[QueueItem]
    yield_progress: dict[str, int]        # ×10 (GROWTH/CULTURE/HAPPINESS)
    unit_production_counts: dict[str, int]
    project_counts: dict[str, int]
    culture: str = ""            # owner-team culture level (CULTURE_*)
    culture_step: int = 0        # owner-team culture step within the level
    happiness_level: int = 0     # owner-team level; negative = discontent


@dataclass
class Tile:
    id: int
    terrain: str
    height: str
    improvement: str | None = None
    improvement_turns_left: int = 0
    improvement_turns_orig: int = 0
    city_territory: int | None = None     # owning city id
    city_site: str | None = None
    tribe_site: str | None = None     # tribe zone/holder (TRIBE_*)
    resource: str | None = None
    vegetation: str | None = None
    specialist: str | None = None
    road: bool = False
    was_visible: set = field(default_factory=set)  # teams w/ vision flag (pending player only)
    element_name: str | None = None   # landmark TEXT_* token (or custom name)
    river_w: bool = False
    river_sw: bool = False
    river_se: bool = False
    revealed_turn: dict[int, int] = field(default_factory=dict)  # team→turn
    unit_ids: list[int] = field(default_factory=list)


@dataclass
class Player:
    id: int
    name: str
    nation: str
    dynasty: str
    tech_researching: str | None
    tech_target: str | None
    tech_available: list[str]
    tech_progress: dict[str, int]     # ×10
    tech_count: dict[str, int]        # researched techs → count
    tech_passed: list[str]
    yield_stockpile: dict[str, int]   # ×10
    yield_rate_history: dict[str, dict[int, int]]  # yield→{turn→rate×10}
    turn_log: list[LogEntry]
    permanent_log: list[LogEntry]
    recent_attacks: list[tuple[int, int]]  # (tile_id, count)
    legitimacy: int
    start_turn_cities: int
    legitimacy_history: dict[int, int] = field(default_factory=dict)
    event_turns: list[tuple[str, str, int]] = field(default_factory=list)   # (scope, EVENTSTORY_*, turn)
    event_options: set = field(default_factory=set)                          # (scope, EVENTOPTION_*)
    military_power_history: dict[int, int] = field(default_factory=dict)
    yield_total_history: dict[str, dict[int, int]] = field(default_factory=dict)

    def science_rate_at(self, turn: int) -> int | None:
        return series_value_at(self.yield_rate_history.get("YIELD_SCIENCE", {}), turn)


class Snapshot:
    """One parsed save file. All raw ET access stays in here."""

    def __init__(self, xml_path: Path | str):
        self.path = Path(xml_path)
        self.root = ET.parse(self.path).getroot()
        g = self.root.find("Game")
        self.turn = _int(g.findtext("Turn"))
        self.player_turn = _int(g.findtext("PlayerTurn"))
        # market price history: yield → {turn → price ×10,000 money}
        self.yield_price_history: dict[str, dict[int, int]] = {}
        yph = g.find("YieldPriceHistory")
        if yph is not None:
            for y in yph:
                self.yield_price_history[y.tag] = _turn_series(y)
        self.map_width = _int(self.root.get("MapWidth"))
        self.game_name = self.root.get("GameName") or ""
        self.version = self.root.get("Version") or ""
        self.difficulties = [(e.text or "").strip() for e in
                             self.root.findall("Difficulty/PlayerDifficulty")]

        self.players = {p.id: p for p in self._parse_players()}
        self.tiles: dict[int, Tile] = {}
        self.units: dict[int, Unit] = {}
        self._parse_tiles()
        self.cities = {c.id: c for c in self._parse_cities()}
        self.characters = self._parse_characters()

    # ── coordinates ─────────────────────────────────────────────────
    def xy(self, tile_id: int) -> tuple[int, int]:
        return tile_id % self.map_width, tile_id // self.map_width

    # ── parsing ─────────────────────────────────────────────────────
    def _parse_log(self, elem) -> list[LogEntry]:
        out = []
        if elem is None:
            return out
        for ld in elem.findall("LogData"):
            raw = ld.findtext("Text") or ""
            out.append(LogEntry(
                type=ld.findtext("Type") or "",
                turn=_int(ld.findtext("Turn"), -1),
                data=[(ld.findtext(f"Data{i}") or "") for i in (1, 2, 3, 4)],
                text=strip_markup(raw),
                raw_text=raw,
            ))
        return out

    def _parse_players(self):
        for p in self.root.findall("Player"):
            hist = {}
            yrh = p.find("YieldRateHistory")
            if yrh is not None:
                for y in yrh:
                    hist[y.tag] = _turn_series(y)
            techres = (p.findtext("TechResearching") or "").strip() or None
            techtgt = (p.findtext("TechTarget") or "").strip() or None
            avail = [c.tag for c in (p.find("TechAvailable") or [])]
            passed = [c.tag for c in (p.find("TechPassed") or [])]
            ra = [( _int(a.get("TileID")), _int(a.get("Attacks")))
                  for a in p.findall("RecentAttacks/RecentAttack")]
            # event stories: fired turns + chosen options, across all scopes.
            # Keys look like "P.1.EVENTSTORY_X" / "FAMILY_KASSITE.EVENTSTORY_X"
            # / "RELIGION_JUDAISM.EVENTOPTION_Y"; split scope off the last
            # EVENT- component.
            ev_turns, ev_opts = [], set()
            for tag in ("PlayerEventStoryTurn", "FamilyEventStoryTurn",
                        "ReligionEventStoryTurn", "TribeEventStoryTurn"):
                e = p.find(tag)
                if e is None:
                    continue
                for c in e:
                    k = c.tag
                    i = k.find("EVENTSTORY_")
                    if i >= 0:
                        ev_turns.append((k[:i].rstrip("."), k[i:], _int(c.text, -1)))
            for tag in ("PlayerEventStoryOption", "FamilyEventStoryOption",
                        "ReligionEventStoryOption", "TribeEventStoryOption"):
                e = p.find(tag)
                if e is None:
                    continue
                for c in e:
                    k = c.tag
                    i = k.find("EVENTOPTION_")
                    if i >= 0:
                        ev_opts.add((k[:i].rstrip("."), k[i:]))
            lh = p.find("LegitimacyHistory")
            mil = _turn_series(p.find("MilitaryPowerHistory"))
            ytot = {}
            yth = p.find("YieldTotalHistory")
            if yth is not None:
                for y in yth:
                    ytot[y.tag] = _turn_series(y)
            yield Player(
                id=_int(p.get("ID")),
                name=p.get("Name") or "",
                nation=p.get("Nation") or "",
                dynasty=p.get("Dynasty") or "",
                tech_researching=techres,
                tech_target=techtgt,
                tech_available=avail,
                tech_progress=_kv_int(p.find("TechProgress")),
                tech_count=_kv_int(p.find("TechCount")),
                tech_passed=passed,
                yield_stockpile=_kv_int(p.find("YieldStockpile")),
                yield_rate_history=hist,
                turn_log=self._parse_log(p.find("TurnLogList")),
                permanent_log=self._parse_log(p.find("PermanentLogList")),
                recent_attacks=ra,
                legitimacy=_int(p.findtext("Legitimacy")),
                start_turn_cities=_int(p.findtext("StartTurnCities")),
                legitimacy_history=_turn_series(lh),
                event_turns=ev_turns,
                event_options=ev_opts,
                military_power_history=mil,
                yield_total_history=ytot,
            )

    def _parse_tiles(self):
        for t in self.root.findall("Tile"):
            tid = _int(t.get("ID"))
            ct = t.findtext("CityTerritory")
            tile = Tile(
                id=tid,
                terrain=t.findtext("Terrain") or "",
                height=t.findtext("Height") or "",
                improvement=t.findtext("Improvement"),
                improvement_turns_left=_int(t.findtext("ImprovementBuildTurnsLeft")),
                improvement_turns_orig=_int(t.findtext("ImprovementBuildTurnsOriginal")),
                city_territory=_int(ct) if ct not in (None, "") else None,
                city_site=t.findtext("CitySite"),
                tribe_site=(t.findtext("TribeSite") or "").strip() or None,
                resource=t.findtext("Resource"),
                vegetation=t.findtext("Vegetation"),
                specialist=t.findtext("Specialist"),
                road=t.find("Road") is not None,
                was_visible={int(c.tag[2:]) for c in (t.find("WasVisibleThisTurn") if t.find("WasVisibleThisTurn") is not None else [])
                             if c.tag.startswith("ID") and c.tag[2:].isdigit()},
                element_name=(t.findtext("ElementName") or t.findtext("CustomElementName") or "").strip() or None,
                # River elements hold a RotationType (0/1 = flow direction);
                # PRESENCE means river — value 0 is a river too, not "none".
                river_w=t.find("RiverW") is not None,
                river_sw=t.find("RiverSW") is not None,
                river_se=t.find("RiverSE") is not None,
                revealed_turn=_team_map(t.find("RevealedTurn")),
            )
            for u in t.findall("Unit"):
                unit = self._parse_unit(u, tid)
                self.units[unit.id] = unit
                tile.unit_ids.append(unit.id)
            self.tiles[tid] = tile

    def _parse_unit(self, u, tile_id: int) -> Unit:
        player = _int(u.get("Player"), -1)
        fam = None
        pf = u.find("PlayerFamily")
        if pf is not None and player >= 0:
            fam = (pf.findtext(f"P.{player}") or "").strip() or None
        gid = u.findtext("GeneralID")
        return Unit(
            id=_int(u.get("ID")),
            type=u.get("Type") or "",
            player=player,
            tribe=u.get("Tribe") or "NONE",
            tile_id=tile_id,
            create_turn=_int(u.findtext("CreateTurn")),
            original_player=_int(u.findtext("OriginalPlayer"), -1),
            family=fam,
            damage=_int(u.findtext("Damage")),
            xp=_int(u.findtext("XP")),
            level=_int(u.findtext("Level")),
            promotions=[c.tag for c in (u.find("Promotions") or [])],
            promotions_available=[c.tag for c in (u.find("PromotionsAvailable") or [])],
            cooldown=(u.findtext("Cooldown") or "").strip() or None,
            cooldown_turns=_int(u.findtext("CooldownTurns")),
            turn_steps=_int(u.findtext("TurnSteps")),
            turns_since_last_move=_int(u.findtext("TurnsSinceLastMove")),
            general_id=_int(gid) if gid not in (None, "") else None,
        )

    def _parse_cities(self):
        for c in self.root.findall("City"):
            queue = []
            for q in c.findall("BuildQueue/QueueInfo"):
                queue.append(QueueItem(
                    build=q.findtext("Build") or "",
                    ztype=q.findtext("Type") or "",
                    progress=_int(q.findtext("Progress")),
                    cost=_kv_int(q.find("YieldCost")),
                    data=_int(q.findtext("Data"), -1),
                ))
            gov = c.findtext("GovernorID")
            owner = _int(c.get("Player"))
            tc = c.find("TeamCulture")
            culture = (tc.findtext(f"T.{owner}") or "").strip() if tc is not None else ""
            th = c.find("TeamHappinessLevel")
            happiness = _int(th.findtext(f"T.{owner}")) if th is not None else 0
            tcs = c.find("TeamCultureStep")
            culture_step = _int(tcs.findtext(f"T.{owner}")) if tcs is not None else 0
            yield City(
                id=_int(c.get("ID")),
                tile_id=_int(c.get("TileID")),
                player=_int(c.get("Player")),
                family=c.get("Family") or "",
                founded_turn=_int(c.get("Founded")),
                name_token=c.findtext("NameType") or "",
                citizens=_int(c.findtext("Citizens")),
                governor_id=_int(gov) if gov not in (None, "") else None,
                capital=c.find("Capital") is not None,
                queue=queue,
                yield_progress=_kv_int(c.find("YieldProgress")),
                unit_production_counts=_kv_int(c.find("UnitProductionCounts")),
                project_counts=_kv_int(c.find("ProjectCount")),
                culture=culture,
                culture_step=culture_step,
                happiness_level=happiness,
            )

    def _parse_characters(self) -> dict[int, dict]:
        out = {}
        for ch in self.root.findall("Character"):
            cid = _int(ch.get("ID"))
            sp = ch.findtext("SpouseID")
            out[cid] = {
                "first_name": ch.get("FirstName") or ch.findtext("NameType") or "",
                "player": _int(ch.get("Player"), -1),
                "gender": ch.get("Gender") or "",
                "birth_turn": _int(ch.get("BirthTurn")),
                "death_turn": _int(ch.findtext("DeathTurn"), -1),
                "cognomen": ch.findtext("Cognomen") or "",
                "ratings": _kv_int(ch.find("Rating")),
                "traits": [c.tag for c in (ch.find("TraitTurn") if ch.find("TraitTurn") is not None else [])],
                "courtier": (ch.findtext("Courtier") or "").strip() or None,
                "spouse_id": _int(sp) if sp not in (None, "") else None,
                "father_id": _int(ch.findtext("FatherID"), -1),
                "mother_id": _int(ch.findtext("MotherID"), -1),
                "leader_turn": _int(ch.findtext("LeaderTurn"), -1),
                "religion": (ch.findtext("Religion") or "").strip() or None,
                "nation": (ch.findtext("Nation") or "").strip() or None,
                "tribe": (ch.findtext("Tribe") or "").strip() or None,
            }
        return out

    # ── diplomacy / heads / agents ──────────────────────────────────
    def team_diplomacy(self, a: int, b: int) -> str:
        g = self.root.find("Game/TeamDiplomacy")
        return (g.findtext(f"T.{a}.{b}") or "").strip() if g is not None else ""

    def tribe_diplomacy(self, tribe: str, team: int) -> str:
        g = self.root.find("Game/TribeDiplomacy")
        return (g.findtext(f"{tribe}.{team}") or "").strip() if g is not None else ""

    def tribes_alive(self) -> list[str]:
        g = self.root.find("Game/TribeDiplomacy")
        return sorted({c.tag.rsplit(".", 1)[0] for c in (g if g is not None else [])})

    def religion_heads(self) -> dict[str, int]:
        g = self.root.find("Game/ReligionHeadID")
        return {c.tag: _int(c.text, -1) for c in (g if g is not None else [])}

    def family_heads(self, pid: int) -> set[int]:
        for p in self.root.findall("Player"):
            if _int(p.get("ID")) == pid:
                e = p.find("FamilyHeadID")
                return {_int(c.text, -1) for c in (e if e is not None else [])}
        return set()

    def city_agents(self, pid: int) -> list[tuple[int, int]]:
        """(city_id, agent_character_id) for this player's planted agents."""
        out = []
        for c in self.root.findall("City"):
            e = c.find("AgentCharacterID")
            if e is not None:
                v = e.findtext(f"P.{pid}")
                if v not in (None, ""):
                    out.append((_int(c.get("ID")), _int(v)))
        return out

    def player_roles(self, pid: int) -> dict:
        """Current leader, spouse, courtiers, council for a player."""
        pe = None
        for p in self.root.findall("Player"):
            if _int(p.get("ID")) == pid:
                pe = p
                break
        leaders = [_int(c.text) for c in pe.find("Leaders")] if pe is not None and pe.find("Leaders") is not None else []
        alive = lambda cid: cid in self.characters and self.characters[cid]["death_turn"] < 0
        leader = next((c for c in reversed(leaders) if alive(c)), None)
        spouse = None
        if leader is not None:
            s = self.characters[leader].get("spouse_id")
            if s is not None and alive(s):
                spouse = s
            else:  # link may be stored on the spouse's side
                for cid, c in self.characters.items():
                    if c.get("spouse_id") == leader and alive(cid):
                        spouse = cid
                        break
        council = {}
        if pe is not None and pe.find("CouncilCharacter") is not None:
            council = {c.tag: _int(c.text) for c in pe.find("CouncilCharacter")}
        heir = _int(pe.findtext("ChosenHeirID"), -1) if pe is not None else -1
        if heir < 0 and leader is not None:
            # default heir: eldest living child of the leader (primogeniture,
            # absolute cognatic — this game's succession settings)
            kids = [(c["birth_turn"], cid) for cid, c in self.characters.items()
                    if alive(cid) and leader in (c.get("father_id"), c.get("mother_id"))]
            if kids:
                heir = min(kids)[1]
        courtiers = [cid for cid, c in self.characters.items()
                     if c["player"] == pid and c["courtier"] and alive(cid)
                     and cid != leader and cid not in council.values()]
        laws = {}
        if pe is not None and pe.find("ActiveLaw") is not None:
            laws = {c.tag: (c.text or "").strip() for c in pe.find("ActiveLaw")}
        state_rel = (pe.findtext("StateReligion") or "").strip() if pe is not None else ""
        return {"leader": leader, "spouse": spouse, "heir": heir if heir >= 0 else None,
                "courtiers": courtiers, "council": council, "laws": laws,
                "state_religion": state_rel or None}

    def theologies(self) -> dict[str, list[str]]:
        """religion → established theologies (Game/ReligionTheology)."""
        out = {}
        rt = self.root.find("Game/ReligionTheology")
        if rt is not None:
            for rel in rt:
                out[rel.tag] = [c.tag for c in rel] or ([rel.text.strip()] if rel.text and rel.text.strip() else [])
        return out

    def religion_founders(self) -> dict[str, int]:
        """religion → founding player id (Game/ReligionFounder)."""
        out = {}
        rf = self.root.find("Game/ReligionFounder")
        if rf is not None:
            for rel in rf:
                v = _int(rel.text, -1)
                if v >= 0:
                    out[rel.tag] = v
        return out

    # ── convenience ─────────────────────────────────────────────────
    def player_units(self, pid: int) -> list[Unit]:
        return sorted((u for u in self.units.values() if u.player == pid),
                      key=lambda u: u.id)

    def player_cities(self, pid: int) -> list[City]:
        return sorted((c for c in self.cities.values() if c.player == pid),
                      key=lambda c: c.id)

    def city_of_tile(self, tile_id: int):
        t = self.tiles.get(tile_id)
        if t is None or t.city_territory is None:
            return None
        return self.cities.get(t.city_territory)

    def reveals_by_turn(self, team: int) -> dict[int, list[int]]:
        """turn → [tile ids] first revealed to `team` on that turn."""
        out: dict[int, list[int]] = {}
        for t in self.tiles.values():
            rt = t.revealed_turn.get(team)
            if rt is not None:
                out.setdefault(rt, []).append(t.id)
        return out
