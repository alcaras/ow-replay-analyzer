"""Character opinion of their player — partial port of
PlayerOpinion.calculateCharacterOpinionRate, for the court-yield modifier
(spouse/heir/courtiers get ±50/100/200% on their yields by opinion tier;
the leader is exempt — the game returns null for them).

Ported components (all save-derivable): memories (linear decay via
memoryLevel), relationships vs the leader, own traits' iOpinion,
iOpinionSame / aiTraitOpinion vs the leader's traits, aiLawOpinion vs
active laws, aiJobOpinion, job opinion (general/governor/agent +20),
council opinion, leader-spouse +20, heir +20, leader's-parent +40.

Also ported: leader-religion (±10, ×2 for religion heads), state-religion
(±20, pagan penalty halved), ethnicity (recursive ancestry blend of the
character's origin nation/tribe, × diplomacy iOpinionEthnicity — war −80
— against every rival nation/tribe), and effect-player leader-opinion for
family/religion heads in all-human games (laws' miLeaderOpinionChange)
plus miLeaderDescendantOpinionChange for leader descendants.

Genuinely court-irrelevant (the game gates them to FOREIGN leaders, i.e.
diplomacy only): proximity/strength/knowledge/generals/explorers/
governors/wonders/laws/cognomen/trades trait terms. See
docs/opinion-system.md for the full write-up. Tier thresholds from
opinionCharacter.xml: ≤−200 Furious(−200%), ≤−100 Angry(−100%),
≤−1 Upset(−50%), ≤99 Cautious(0), ≤199 Pleased(+50%), else
Friendly(+100%).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import cached_property

from .gamedata import GameData
from .save import Snapshot


def _int(x, d=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return d


class OpinionModel:
    def __init__(self, gd: GameData):
        self.gd = gd

    @cached_property
    def memory_levels(self) -> dict[str, tuple[int, int]]:
        return {z: (_int(e.findtext("iValue")), _int(e.findtext("iTurns")))
                for z, e in self.gd._merged("memoryLevel").items()}

    @cached_property
    def memories(self) -> dict[str, tuple[int, int]]:
        """MEMORYCHARACTER_* → (opinion value, duration turns)."""
        out = {}
        for base in ("memory-character",):
            for z, e in self.gd._merged(base).items():
                lvl = e.findtext("MemoryLevel")
                v, t = _int(e.findtext("iValue")), _int(e.findtext("iTurns"))
                if lvl and lvl in self.memory_levels:
                    lv, lt = self.memory_levels[lvl]
                    v, t = v or lv, t or lt
                out[z] = (v, t)
        return out

    @cached_property
    def relationships(self) -> dict[str, int]:
        return {z: _int(e.findtext("iOpinion"))
                for z, e in self.gd._merged("relationship").items()}

    @cached_property
    def traits(self) -> dict[str, dict]:
        out = {}
        for z, e in self.gd._merged("trait").items():
            def pairs(tag):
                d = {}
                el = e.find(tag)
                if el is not None:
                    for p in el.findall("Pair"):
                        k = p.findtext("zIndex")
                        if k:
                            d[k] = _int(p.findtext("iValue"))
                return d
            out[z] = {
                "opinion": _int(e.findtext("iOpinion")),
                "opinion_same": _int(e.findtext("iOpinionSame")),
                "trait_opinion": pairs("aiTraitOpinion"),
                "law_opinion": pairs("aiLawOpinion"),
                "job_opinion": pairs("aiJobOpinion"),
            }
        return out

    @cached_property
    def jobs(self) -> dict[str, int]:
        return {z: _int(e.findtext("iOpinion"))
                for z, e in self.gd._merged("job").items()}

    @cached_property
    def councils(self) -> dict[str, int]:
        return {z: _int(e.findtext("iOpinion"))
                for z, e in self.gd._merged("council").items()}

    @cached_property
    def diplomacy_ethnicity(self) -> dict[str, int]:
        return {z: _int(e.findtext("iOpinionEthnicity"))
                for z, e in self.gd._merged("diplomacy").items()}

    @cached_property
    def effect_player_leader_opinion(self) -> dict[str, tuple[int, int]]:
        """EffectPlayer → (miLeaderOpinionChange, miLeaderDescendantOpinionChange)."""
        return {z: (_int(e.findtext("iLeaderOpinionChange")),
                    _int(e.findtext("iLeaderDescendantOpinionChange")))
                for z, e in self.gd._merged("effectPlayer").items()}

    @cached_property
    def law_effect_players(self) -> dict[str, str | None]:
        return {z: e.findtext("EffectPlayer")
                for z, e in self.gd._merged("law").items()}

    # tier table: (upper threshold, rate modifier %); order matters
    TIERS = [(-200, "Furious", -200), (-100, "Angry", -100), (-1, "Upset", -50),
             (99, "Cautious", 0), (199, "Pleased", 50)]
    TOP = ("Friendly", 100)

    def tier(self, rate: int) -> tuple[str, int]:
        for thr, name, mod in self.TIERS:
            if rate <= thr:
                return name, mod
        return self.TOP

    # ── per-character rate ──────────────────────────────────────────
    def character_jobs(self, snap: Snapshot, cid: int) -> list[str]:
        out = []
        for c in snap.cities.values():
            if c.governor_id == cid:
                out.append("JOB_GOVERNOR")
                break
        for u in snap.units.values():
            if u.general_id == cid:
                out.append("JOB_GENERAL")
                break
        return out

    def opinion_rate(self, snap: Snapshot, pid: int, cid: int, roles: dict) -> int | None:
        """None for the leader (game exempts them)."""
        leader = roles.get("leader")
        if cid == leader:
            return None
        ch = snap.characters.get(cid)
        if ch is None or ch["death_turn"] >= 0:
            return None
        rate = 0
        # memories about this character (player memory list, char-scoped)
        for pe in snap.root.findall("Player"):
            if _int(pe.get("ID")) != pid:
                continue
            for md in pe.findall("MemoryList/MemoryData"):
                if _int(md.findtext("Character"), -1) == cid:
                    mz = md.findtext("Type") or ""
                    v, t = self.memories.get(mz, (0, 0))
                    if v and t > 0:
                        left = t - (snap.turn - _int(md.findtext("Turn")))
                        adj = (left * v) // t
                        rate += adj if adj != 0 else (1 if v > 0 else -1)
        # relationships with the leader
        if leader is not None:
            ce = snap.root.find(f".//Character[@ID='{cid}']")
            if ce is not None:
                for rd in ce.findall("RelationshipList/RelationshipData"):
                    if _int(rd.findtext("CharacterID"), -1) == leader:
                        rate += self.relationships.get(rd.findtext("Type") or "", 0)
        # traits
        my_traits = ch["traits"]
        leader_traits = set(snap.characters[leader]["traits"]) if leader in snap.characters else set()
        laws = set(roles.get("laws", {}).values())
        char_jobs = set(self.character_jobs(snap, cid))
        for tr in my_traits:
            ti = self.traits.get(tr)
            if not ti:
                continue
            rate += ti["opinion"]
            if tr in leader_traits:
                rate += ti["opinion_same"]
            for other, v in ti["trait_opinion"].items():
                if other in leader_traits:
                    rate += v
            for law, v in ti["law_opinion"].items():
                if law in laws:
                    rate += v
            for job, v in ti["job_opinion"].items():
                if job in char_jobs:
                    rate += v
        # roles
        if roles.get("spouse") == cid:
            rate += 20   # LEADER_SPOUSE_OPINION
        if roles.get("heir") == cid:
            rate += 20   # HEIR_OPINION
        if leader in snap.characters:
            lch = snap.characters[leader]
            if cid in (lch.get("father_id"), lch.get("mother_id")):
                rate += 40   # PARENT_OPINION
        # jobs + council
        for j in char_jobs:
            rate += self.jobs.get(j, 0)
        for council, holder in roles.get("council", {}).items():
            if holder == cid:
                rate += self.councils.get(council, 0)
        # leader religion: same +10, world-religion mismatch −10; ×2 for heads
        rel_heads = snap.religion_heads()
        is_rel_head = cid in rel_heads.values()
        char_rel = ch.get("religion")
        if char_rel and leader in snap.characters:
            lrel = snap.characters[leader].get("religion")
            if lrel:
                d = 0
                if lrel == char_rel:
                    d = 10   # LEADER_RELIGION_OPINION_CHARACTER
                elif not char_rel.startswith("RELIGION_PAGAN"):
                    d = -10
                rate += d * (2 if is_rel_head else 1)
        # state religion: same +20, else −20 (−10 if pagan); ×2 for heads
        state_rel = roles.get("state_religion")
        if char_rel and state_rel:
            if state_rel == char_rel:
                d = 20   # STATE_RELIGION_OPINION_CHARACTER
            else:
                d = -(20 // (2 if char_rel.startswith("RELIGION_PAGAN") else 1))
            rate += d * (2 if is_rel_head else 1)
        # ethnicity: character's foreign blood vs current diplomacy states
        rate += self._ethnicity_opinion(snap, pid, cid)
        # effect-player leader opinions: family/religion heads feel laws
        # (all-human games); leader descendants feel descendant changes
        is_fam_head = cid in snap.family_heads(pid)
        is_descendant = self._is_leader_descendant(snap, pid, cid)
        if is_fam_head or is_rel_head or is_descendant:
            for law in roles.get("laws", {}).values():
                ep = self.law_effect_players.get(law)
                if not ep:
                    continue
                lead_ch, desc_ch = self.effect_player_leader_opinion.get(ep, (0, 0))
                if (is_fam_head or is_rel_head) and lead_ch:
                    rate += lead_ch
                if is_descendant and desc_ch:
                    rate += desc_ch
        return rate

    # ── ethnicity (recursive ancestry blend, memoized per snapshot) ──
    def _ethnicity(self, snap: Snapshot, cid: int, key: str, is_tribe: bool,
                   depth: int = 0) -> int:
        """% of `key` (nation or tribe) blood, per Character.getNationEthnicity:
        each parent contributes half their own ethnicity; a missing parent
        side contributes 50 if the character's own origin matches."""
        if depth > 8 or cid not in snap.characters:
            return 0
        ch = snap.characters[cid]
        own = ch.get("tribe") if is_tribe else ch.get("nation")
        total = 0
        for side in ("father_id", "mother_id"):
            p = ch.get(side, -1)
            if p is not None and p >= 0 and p in snap.characters:
                total += self._ethnicity(snap, p, key, is_tribe, depth + 1) // 2
            elif own == key:
                total += 50
        return total

    def _ethnicity_opinion(self, snap: Snapshot, pid: int, cid: int) -> int:
        out = 0
        my_team = pid  # 1:1 player→team in duels
        for opid in snap.players:
            if opid == pid:
                continue
            op = snap.players[opid]
            dip = snap.team_diplomacy(my_team, opid)
            v = self.diplomacy_ethnicity.get(dip, 0)
            if v:
                pct = self._ethnicity(snap, cid, op.nation, is_tribe=False)
                if pct:
                    out += (v * pct) // 100
        for tribe in snap.tribes_alive():
            dip = snap.tribe_diplomacy(tribe, my_team)
            v = self.diplomacy_ethnicity.get(dip, 0)
            if v:
                pct = self._ethnicity(snap, cid, tribe, is_tribe=True)
                if pct:
                    out += (v * pct) // 100
        return out

    def _is_leader_descendant(self, snap: Snapshot, pid: int, cid: int) -> bool:
        """Ancestor chain reaches any of the player's (past) leaders."""
        leaders = set()
        for p in snap.root.findall("Player"):
            if int(p.get("ID")) == pid and p.find("Leaders") is not None:
                leaders = {int(c.text) for c in p.find("Leaders") if c.text}
        seen = set()
        stack = [cid]
        while stack:
            c = stack.pop()
            if c in seen or c not in snap.characters:
                continue
            seen.add(c)
            ch = snap.characters[c]
            for side in ("father_id", "mother_id"):
                p = ch.get(side, -1)
                if p is not None and p >= 0:
                    if p in leaders:
                        return True
                    stack.append(p)
        return False

    def court_modifier(self, snap: Snapshot, pid: int, cid: int, roles: dict,
                       rating_value: int) -> tuple[int, str]:
        """(±% modifier on this character's court yield, tier label)."""
        rate = self.opinion_rate(snap, pid, cid, roles)
        if rate is None:
            return 0, ""
        name, mod = self.tier(rate)
        if mod == 0:
            return 0, name
        # yieldWarning: for science the modifier flips when the rating is
        # negative (a friendly char with negative wisdom hurts more).
        if rating_value < 0:
            mod = -mod
        return mod, name
