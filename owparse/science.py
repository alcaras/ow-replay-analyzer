"""Per-source science breakdown, ported from GameCore (science yield only).

Model (City.calculateBaseYieldNetGovernor + Player.calculateNonCityYield):
  city science = Σ EffectCity flat rates (base, specialists, improvements,
                 family class, governor traits, laws' city effects, …)
               + Σ tile outputs (improvement outputs, grove resources)
               then × (100 + Σ % modifiers: libraries, Musaeum, happiness) / 100
  player science = Σ cities + court characters (leader / spouse / successor
                 ×0.5, courtiers ×0.33 — Wisdom court rate 1.0 through the
                 triangle curve at offset −2, linearized in competitive mode)
               + EffectPlayer rates (competitive stipend, laws) + trades …

Values are ×10 throughout. `validate()` compares against the save's own
YieldRateHistory[YIELD_SCIENCE] — the ground truth the game recorded —
and reports the residual per player per turn.

Validation status on `alcaras v Lich` (v1.0.84044): EXACT (0.0) through
turn ~30 for both players (41/115 player-turns exact overall); mean abs
error 7-8% of recorded across the whole series; the in-game city tooltip
(Babylon T15 = 3.9) matches to the decimal. The remainder — worst ~15%
in Lich's end-game — is always shown as "unattributed". Sources not yet
ported: temporary event effect-players (Equinox-style buffs), the
opinion components skipped in opinion.py (religion/ethnicity/proximity
etc.), connected-foreign-city yield (moot during war), agent yields,
and the Spymaster council table.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import cached_property

from .gamedata import GameData
from .save import Snapshot

SCI = "YIELD_SCIENCE"


def _pairs(elem) -> dict[str, int]:
    out = {}
    if elem is not None:
        for p in elem.findall("Pair"):
            k, v = p.findtext("zIndex"), p.findtext("iValue")
            if k:
                out[k] = int(v or 0)
    return out


def triangle(n: int) -> int:
    a = abs(n)
    return (1 if n > 0 else -1 if n < 0 else 0) * a * (a + 1) // 2


def triangle_offset(n: int, off: int) -> int:
    v = abs(n) + off
    if v <= 0:
        return n
    return (1 if n > 0 else -1 if n < 0 else 0) * (triangle(v) - off)


def triangle_boost(n: int) -> int:
    if n == 0:
        return 0
    return (1 if n > 0 else -1) * triangle(abs(n) + 1)


def boost_rating(value: int, rating: int, competitive: bool, eq: int = 5) -> int:
    """InfoHelpers.boostRating: competitive linearizes the triangle curve
    around the equivalent rating (5). E.g. governor Wisdom modifier 2 →
    2×1×triangle(6)//5 = +8% at Wisdom 1 (verified vs in-game tooltip)."""
    if competitive:
        return value * rating * triangle_boost(eq) // eq
    return value * triangle_boost(rating)


def modify(value: int, pct: int) -> int:
    return value * (100 + pct) // 100 if pct else value


class ScienceModel:
    def __init__(self, gd: GameData):
        self.gd = gd
        self.infos = gd.infos
        from .opinion import OpinionModel
        self.opinion_model = OpinionModel(gd)

    def _entries(self, base: str) -> dict[str, ET.Element]:
        return self.gd._merged(base)

    # ── baked tables ────────────────────────────────────────────────
    @cached_property
    def effect_city(self) -> dict[str, dict]:
        out = {}
        for z, e in self._entries("effectCity").items():
            cross = {}
            ary = e.find("aaiEffectCityYieldRate")
            if ary is not None:
                for p in ary.findall("Pair"):
                    other = p.findtext("zIndex")
                    for sp in p.findall("SubPair"):
                        k = sp.findtext("zSubIndex")
                        if k:
                            cross.setdefault(other, {})[k] = int(sp.findtext("iValue") or 0)
            out[z] = {
                "rate": _pairs(e.find("aiYieldRate")),
                "modifier": _pairs(e.find("aiYieldModifier")),
                "rate_specialist": _pairs(e.find("aiYieldRateSpecialist")),
                "rate_specialist_urban": _pairs(e.find("aiYieldRateSpecialistUrban")),
                "rate_specialist_rural": _pairs(e.find("aiYieldRateSpecialistRural")),
                "rate_culture": _pairs(e.find("aiYieldRateCulture")),
                "rate_population": _pairs(e.find("aiYieldRatePopulation")),
                "cross": cross,
                "single": e.findtext("bSingle") == "1",
            }
        return out

    @cached_property
    def urban_specialist_classes(self) -> set[str]:
        return {z for z, e in self._entries("specialistClass").items()
                if e.findtext("bUrban") == "1"}

    @cached_property
    def specialist_class_of(self) -> dict[str, str]:
        return {z: (e.findtext("Class") or "")
                for z, e in self._entries("specialist").items()}

    # culture level ordinal, matching getCulture() enum order in culture.xml
    @cached_property
    def culture_ordinal(self) -> dict[str, int]:
        return {z: i for i, z in enumerate(self._entries("culture"))}

    @cached_property
    def improvements(self) -> dict[str, dict]:
        out = {}
        for z, e in self._entries("improvement").items():
            out[z] = {
                "effect_city": e.findtext("EffectCity"),
                "effect_player": e.findtext("EffectPlayer"),  # wonders
                "output": _pairs(e.find("aiYieldOutput")),
                "class": e.findtext("ImprovementClass"),
            }
        return out

    def player_wonder_effects(self, snap: Snapshot, pid: int) -> list[tuple[str, str]]:
        """(wonder name, EffectPlayer) for completed improvements with a
        player effect (wonders) in this player's territory."""
        city_ids = {c.id for c in snap.player_cities(pid)}
        out = []
        for t in snap.tiles.values():
            if (t.city_territory in city_ids and t.improvement
                    and t.improvement_turns_left == 0):
                ep = self.improvements.get(t.improvement, {}).get("effect_player")
                if ep:
                    out.append((self.gd.name(t.improvement), ep))
        return out

    @cached_property
    def improvement_class_resource(self) -> dict[str, dict[str, int]]:
        """improvement class → resource → {yield: output} (groves etc.)."""
        out = {}
        for z, e in self._entries("improvementClass").items():
            res = {}
            ary = e.find("aaiResourceYieldOutput")
            if ary is not None:
                for p in ary.findall("Pair"):
                    r = p.findtext("zIndex")
                    for sp in p.findall("SubPair"):
                        k = sp.findtext("zSubIndex")
                        if k:
                            res.setdefault(r, {})[k] = int(sp.findtext("iValue") or 0)
            if res:
                out[z] = res
        return out

    @cached_property
    def specialists(self) -> dict[str, dict]:
        return {z: {"effect_city": e.findtext("EffectCity"),
                    "effect_city_extra": e.findtext("EffectCityExtra")}
                for z, e in self._entries("specialist").items()}

    @cached_property
    def family_classes(self) -> dict[str, dict]:
        return {z: {"effect_city": e.findtext("EffectCity"),
                    "seat_effect_city": e.findtext("SeatEffectCity")}
                for z, e in self._entries("familyClass").items()}

    @cached_property
    def traits(self) -> dict[str, dict]:
        return {z: {"governor_effect_city": e.findtext("GovernorEffectCity"),
                    "leader_effect_player": e.findtext("LeaderEffectPlayer")}
                for z, e in self._entries("trait").items()}

    @cached_property
    def project_effects(self) -> dict[str, str | None]:
        return {z: e.findtext("EffectCity") for z, e in self._entries("project").items()}

    @cached_property
    def cultures(self) -> dict[str, str | None]:
        return {z: e.findtext("EffectCity") for z, e in self._entries("culture").items()}

    @cached_property
    def nations(self) -> dict[str, str | None]:
        return {z: e.findtext("EffectPlayer") for z, e in self._entries("nation").items()}

    @cached_property
    def difficulties(self) -> dict[str, str | None]:
        return {z: e.findtext("EffectPlayer") for z, e in self._entries("difficulty").items()}

    @cached_property
    def wisdom_governor_mod(self) -> int:
        e = self._entries("rating").get("RATING_WISDOM")
        return _pairs(e.find("aiYieldGovernorModifier")).get(SCI, 0) if e is not None else 0

    @cached_property
    def wisdom_agent_pct(self) -> int:
        e = self._entries("rating").get("RATING_WISDOM")
        return _pairs(e.find("aiYieldAgentPercent")).get(SCI, 0) if e is not None else 0

    @cached_property
    def laws(self) -> dict[str, str | None]:
        return {z: e.findtext("EffectPlayer") for z, e in self._entries("law").items()}

    @cached_property
    def effect_player(self) -> dict[str, dict]:
        out = {}
        for z, e in self._entries("effectPlayer").items():
            out[z] = {
                "rate": _pairs(e.find("aiYieldRate")),
                "effect_city": e.findtext("EffectCity"),
                "effect_city_extra": e.findtext("EffectCityExtra"),
                "capital_effect_city": e.findtext("CapitalEffectCity"),
            }
        return out

    @cached_property
    def wisdom_court_rate(self) -> int:
        e = self._entries("rating").get("RATING_WISDOM")
        return _pairs(e.find("aiYieldCourtRate")).get(SCI, 0) if e is not None else 0

    @cached_property
    def sci_triangle_offset(self) -> int:
        e = self._entries("yield").get(SCI)
        return int(e.findtext("iTriangleOffset") or 0) if e is not None else 0

    def _yield_neg_happiness(self, Y: str) -> int:
        """yield.xml iNegativeHappinessModifier for any yield."""
        e = self._entries("yield").get(Y)
        return int(e.findtext("iNegativeHappinessModifier") or 0) if e is not None else 0

    def city_yields(self, snap: Snapshot, city, yields=("YIELD_GROWTH", "YIELD_CIVICS",
                                                        "YIELD_TRAINING", SCI)) -> dict[str, int]:
        """{yield: rate×10} for a city — the production/economy line the
        in-game city panel shows. Same engine port as the science model, so
        the same accuracy caveats apply."""
        weps = self.player_wonder_effects(snap, city.player)
        out = {}
        for Y in yields:
            items, mod = self.city_science(snap, city, weps, Y)
            out[Y] = modify(sum(v for _, v in items), mod)
        return out

    @cached_property
    def sci_negative_happiness_mod(self) -> int:
        e = self._entries("yield").get(SCI)
        return int(e.findtext("iNegativeHappinessModifier") or 0) if e is not None else 0

    @cached_property
    def sci_per_connected_foreign(self) -> int:
        e = self._entries("yield").get(SCI)
        return int(e.findtext("iPerConnectedForeign") or 0) if e is not None else 0

    @cached_property
    def globals_int(self) -> dict[str, int]:
        return {z: int(e.findtext("iValue") or 0)
                for z, e in self._entries("globalsInt").items()}

    # ── court curve ─────────────────────────────────────────────────
    def court_science(self, rating: int, role_mod: int, competitive: bool) -> int:
        base = modify(self.wisdom_court_rate, role_mod)
        if base == 0 or rating == 0:
            return 0
        off = self.sci_triangle_offset
        if competitive:
            eq = max(1, self.globals_int.get("RATING_EQUIVALENT_LOWER_CHARACTER_YIELDS", 5))
            return base * rating * triangle_offset(eq, off) // eq
        return base * triangle_offset(rating, off)

    # ── per-city breakdown ──────────────────────────────────────────
    def city_science(self, snap: Snapshot, city,
                     wonder_eps: list[tuple[str, str]] | None = None,
                     Y: str = SCI) -> tuple[list[tuple[str, int]], int]:
        """→ ([(source, value10)...], modifier_pct). Flat items pre-modifier."""
        items: list[tuple[str, int]] = []
        mod_pct = 0

        # city context for scaling effect terms
        specs = [t.specialist for t in snap.tiles.values()
                 if t.city_territory == city.id and t.specialist]
        n_spec = len(specs)
        n_urban = sum(1 for s in specs
                      if self.specialist_class_of.get(s, "") in self.urban_specialist_classes)
        # getCulture() + getCultureStep() + 1 (culture.xml enum ordinal)
        culture_val = self.culture_ordinal.get(city.culture, 0) + city.culture_step + 1
        population = city.citizens + n_spec

        def cross_count(other_ez: str) -> int:
            # cross terms reference other effect cities; the ones that carry
            # science reference project effects (Archive/Forum) — count the
            # city's completed projects of that line.
            if other_ez.startswith("EFFECTCITY_PROJECT_"):
                prefix = other_ez.replace("EFFECTCITY_", "")  # PROJECT_ARCHIVE
                return sum(n for pz, n in city.project_counts.items()
                           if pz.startswith(prefix))
            return 0

        def add_effect(label: str, ez: str | None, count: int = 1):
            nonlocal mod_pct
            if not ez or ez == "NONE":
                return
            ec = self.effect_city.get(ez)
            if not ec:
                return
            n = 1 if ec["single"] else count
            g = lambda key: ec[key].get(Y, 0)
            if g("rate"):
                items.append((label, g("rate") * n))
            if g("modifier"):
                mod_pct += g("modifier") * n
            if g("rate_specialist") and n_spec:
                items.append((f"{label} (×{n_spec} specialists)",
                              g("rate_specialist") * n_spec * n))
            if g("rate_specialist_urban") and n_urban:
                items.append((f"{label} (×{n_urban} urban spec.)",
                              g("rate_specialist_urban") * n_urban * n))
            if g("rate_specialist_rural") and (n_spec - n_urban):
                items.append((f"{label} (×{n_spec - n_urban} rural spec.)",
                              g("rate_specialist_rural") * (n_spec - n_urban) * n))
            if g("rate_culture"):
                items.append((f"{label} (×culture {culture_val})",
                              g("rate_culture") * culture_val * n))
            if g("rate_population") and population:
                items.append((f"{label} (×pop {population})",
                              g("rate_population") * population * n))
            for other, sub in ec["cross"].items():
                v = sub.get(Y, 0)
                k = cross_count(other) if v else 0
                if k:
                    items.append((f"{label} (×{k} {other.replace('EFFECTCITY_PROJECT_', '').title()})",
                                  v * k * n))

        add_effect("Base city", "EFFECTCITY_BASE")

        # improvements + tile outputs
        imp_counts: dict[str, int] = {}
        for t in snap.tiles.values():
            if t.city_territory != city.id:
                continue
            if t.improvement and t.improvement_turns_left == 0:
                imp = self.improvements.get(t.improvement, {})
                imp_counts[t.improvement] = imp_counts.get(t.improvement, 0) + 1
                ov = (imp.get("output") or {}).get(Y, 0)
                if ov:
                    items.append((self.gd.name(t.improvement) + " (tile)", ov))
                cls = imp.get("class")
                res_out = self.improvement_class_resource.get(cls or "", {})
                rv = res_out.get(t.resource or "", {}).get(Y, 0)
                if rv:
                    items.append((f"{self.gd.name(t.improvement)} ({self.gd.name(t.resource)})", rv))
            if t.specialist:
                sp = self.specialists.get(t.specialist, {})
                add_effect(self.gd.name(t.specialist), sp.get("effect_city"))
                add_effect(self.gd.name(t.specialist) + " tier", sp.get("effect_city_extra"))
        for iz, n in imp_counts.items():
            add_effect(self.gd.name(iz), self.improvements[iz].get("effect_city"), n)

        # family class (+seat)
        fam = self.gd.families.get(city.family)
        if fam:
            fc = self.family_classes.get(fam["class"], {})
            add_effect(fam["class_name"] + " family", fc.get("effect_city"))

        # nation + difficulty + active-law player effects → per-city effects
        p = snap.players.get(city.player)
        if p is not None:
            ep = self.nations.get(p.nation)
            if ep:
                epi = self.effect_player.get(ep, {})
                add_effect(self.gd.name(p.nation) + " nation", epi.get("effect_city"))
                if getattr(city, "capital", False):
                    add_effect(self.gd.name(p.nation) + " (capital)",
                               epi.get("capital_effect_city"))
            if city.player < len(snap.difficulties):
                dep = self.difficulties.get(snap.difficulties[city.player])
                if dep:
                    add_effect("Difficulty", self.effect_player.get(dep, {}).get("effect_city"))
            for law in snap.player_roles(city.player)["laws"].values():
                lep = self.laws.get(law)
                if lep:
                    lpi = self.effect_player.get(lep, {})
                    add_effect(f"Law {self.gd.name(law)}", lpi.get("effect_city"))
                    add_effect(f"Law {self.gd.name(law)} extra", lpi.get("effect_city_extra"))
                    if getattr(city, "capital", False):
                        add_effect(f"Law {self.gd.name(law)} (capital)",
                                   lpi.get("capital_effect_city"))

        # completed city projects (Archives, Treasuries, …)
        for pz, n in city.project_counts.items():
            if n > 0:
                add_effect(self.gd.name(pz), self.project_effects.get(pz), n)

        # leader traits that apply empire-wide (Intelligent, Scholar…)
        if p is not None:
            roles = snap.player_roles(city.player)
            if roles["leader"] is not None:
                for tr in snap.characters[roles["leader"]]["traits"]:
                    lep = self.traits.get(tr, {}).get("leader_effect_player")
                    if lep:
                        lpi = self.effect_player.get(lep, {})
                        add_effect(f"Leader {self.gd.name(tr)}", lpi.get("effect_city"))
                        if getattr(city, "capital", False):
                            add_effect(f"Leader {self.gd.name(tr)} (capital)",
                                       lpi.get("capital_effect_city"))

        # wonders anywhere in the empire whose EffectPlayer touches cities
        for wname, ep in (wonder_eps or []):
            epi = self.effect_player.get(ep, {})
            add_effect(wname, epi.get("effect_city"))
            add_effect(wname + " extra", epi.get("effect_city_extra"))
            if getattr(city, "capital", False):
                add_effect(wname + " (capital)", epi.get("capital_effect_city"))

        # culture level
        if city.culture:
            add_effect(f"Culture ({self.gd.name(city.culture)})",
                       self.cultures.get(city.culture))

        # governor: trait effect cities + Wisdom % modifier (boostRating curve)
        if city.governor_id is not None and city.governor_id in snap.characters:
            gov = snap.characters[city.governor_id]
            for tr in gov["traits"]:
                add_effect(f"Governor trait {self.gd.name(tr)}",
                           self.traits.get(tr, {}).get("governor_effect_city"))
            wisdom = gov["ratings"].get("RATING_WISDOM", 0)
            if Y == SCI and wisdom and self.wisdom_governor_mod:
                competitive = snap.root.find("GameOptions/GAMEOPTION_COMPETITIVE_MODE") is not None
                mod_pct += boost_rating(self.wisdom_governor_mod, wisdom, competitive)

        # happiness level % modifier
        if city.happiness_level < 0:
            mod_pct += -city.happiness_level * self._yield_neg_happiness(Y)

        return items, mod_pct

    # ── per-player breakdown ────────────────────────────────────────
    def player_science(self, snap: Snapshot, pid: int) -> dict:
        competitive = snap.root.find("GameOptions/GAMEOPTION_COMPETITIVE_MODE") is not None
        rows: list[tuple[str, int]] = []

        wonder_eps = self.player_wonder_effects(snap, pid)
        city_total = 0
        cities = []
        for c in snap.player_cities(pid):
            items, mod_pct = self.city_science(snap, c, wonder_eps)
            flat = sum(v for _, v in items)
            total = modify(flat, mod_pct)
            city_total += total
            cities.append({"city": self.gd.name(c.name_token), "items": items,
                           "modifier_pct": mod_pct, "total10": total})
            rows.append((f"City {self.gd.name(c.name_token)}", total))

        roles = snap.player_roles(pid)
        chars = snap.characters

        def wis(cid):
            return chars[cid]["ratings"].get("RATING_WISDOM", 0) if cid in chars else 0

        def court_row(cid, role, role_mod):
            w = wis(cid)
            v = self.court_science(w, role_mod, competitive)
            if not v:
                return
            op_mod, op_name = self.opinion_model.court_modifier(snap, pid, cid, roles, w)
            if op_mod:
                v = modify(v, op_mod)
            tag = f", {op_name}" if op_name and op_name != "Cautious" else ""
            rows.append((f"{role} {self.gd.name(chars[cid]['first_name'])} (Wis {w}{tag})", v))

        if roles["leader"] is not None:
            court_row(roles["leader"], "Leader", 0)
        if roles["spouse"] is not None:
            court_row(roles["spouse"], "Spouse",
                      self.globals_int.get("LEADER_SPOUSE_YIELD_MODIFIER", -50))
        if roles["heir"] is not None:
            court_row(roles["heir"], "Heir",
                      self.globals_int.get("SUCCESSOR_YIELD_MODIFIER", -50))
        for cid in roles["courtiers"]:
            court_row(cid, "Courtier",
                      self.globals_int.get("COURTIER_YIELD_MODIFIER", -67))

        if competitive:
            stip = self.effect_player.get("EFFECTPLAYER_COMPETITIVE_MODE", {}).get("rate", {}).get(SCI, 0)
            if stip:
                rows.append(("Competitive stipend", stip))

        for wname, ep in wonder_eps:
            v = self.effect_player.get(ep, {}).get("rate", {}).get(SCI, 0)
            if v:
                rows.append((f"Wonder {wname}", v))

        # agents planted in cities: agent Wisdom × 5%/pt (opinion-modified)
        # × host city's BASE science (pre-modifier flat sum)
        agent_pct = self.wisdom_agent_pct
        if agent_pct:
            for city_id, agent_cid in snap.city_agents(pid):
                host = snap.cities.get(city_id)
                if host is None or agent_cid not in chars:
                    continue
                w = chars[agent_cid]["ratings"].get("RATING_WISDOM", 0)
                pct = agent_pct * w
                if not pct:
                    continue
                op_mod, _ = self.opinion_model.court_modifier(snap, pid, agent_cid, roles, w)
                if op_mod:
                    pct = modify(pct, op_mod)
                host_items, _ = self.city_science(snap, host)
                base = sum(v for _, v in host_items)
                v = base * pct // 100
                if v:
                    rows.append((f"Agent {self.gd.name(chars[agent_cid]['first_name'])}"
                                 f" in {self.gd.name(host.name_token)} ({pct}%)", v))

        if pid < len(snap.difficulties):
            dep = self.difficulties.get(snap.difficulties[pid])
            if dep:
                v = self.effect_player.get(dep, {}).get("rate", {}).get(SCI, 0)
                if v:
                    lbl = snap.difficulties[pid].replace("DIFFICULTY_", "").title()
                    rows.append((f"Difficulty ({lbl})", v))

        for lawclass, law in roles["laws"].items():
            ep = self.laws.get(law)
            if ep:
                v = self.effect_player.get(ep, {}).get("rate", {}).get(SCI, 0)
                if v:
                    rows.append((f"Law {self.gd.name(law)}", v))

        if roles["leader"] is not None:
            for tr in chars[roles["leader"]]["traits"]:
                lep = self.traits.get(tr, {}).get("leader_effect_player")
                if lep:
                    v = self.effect_player.get(lep, {}).get("rate", {}).get(SCI, 0)
                    if v:
                        rows.append((f"Leader trait {self.gd.name(tr)}", v))

        total = city_total + sum(v for lbl, v in rows if not lbl.startswith("City "))
        return {"cities": cities, "rows": rows,
                "city_total10": city_total, "total10": total}


def validate(series, gd: GameData, turns=None):
    """Compare computed city-total (and known player adders) with the save's
    recorded science rate; print per-turn residuals."""
    m = ScienceModel(gd)
    print(f"{'turn':>4} {'pid':>3} {'recorded':>9} {'computed':>9} {'cities':>8} {'residual':>9}")
    for t in turns or series.turns:
        snap = series.snapshot(t)
        for pid in snap.players:
            rec = snap.players[pid].science_rate_at(t)
            if rec is None:
                continue
            got = m.player_science(snap, pid)
            resid = rec - got["total10"]
            print(f"{t:>4} {pid:>3} {rec/10:>9.1f} {got['total10']/10:>9.1f}"
                  f" {got['city_total10']/10:>8.1f} {resid/10:>9.1f}")
