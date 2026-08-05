"""Assemble per-turn, per-player reports (dict for JSON; markdown renderer).

Turn N report:
  - P0 half: state S_N, deltas vs S_{prev} (their turn just played)
  - P1 half: state S_{next}, deltas vs S_N (their half sits between saves)
Halves at archive edges/gaps are flagged with their actual diff window.
"""
from __future__ import annotations

from .diff import BuildStatus, build_status, unit_deltas, worker_ordinals
from .gamedata import GameData
from .military import ACTION_COOLDOWNS, combat_events
from .save import Snapshot, series_value_at
from .series import Series

CIVILIAN = {"UNIT_WORKER", "UNIT_SETTLER", "UNIT_SCOUT"}


def fmt10(v: int | None) -> str:
    return "?" if v is None else f"{v / 10:g}"


class Reporter:
    def __init__(self, series: Series, gd: GameData, science_model=None):
        self.series = series
        self.gd = gd
        if science_model is None:
            from .science import ScienceModel
            science_model = ScienceModel(gd)
        self.science_model = science_model
        self.last = series.snapshot(series.turns[-1])
        self.worker_names = worker_ordinals(series)
        # player → tech → turn discovered (from final permanent log)
        self.tech_discovered: dict[int, dict[str, int]] = {}
        for pid, p in self.last.players.items():
            self.tech_discovered[pid] = {
                e.data[0]: e.turn for e in p.permanent_log
                if e.type == "TECH_DISCOVERED" and e.data[0]
            }
        # team → turn → tiles revealed that turn (exact, from final save)
        self.reveals: dict[int, dict[int, int]] = {
            team: {t: len(ids) for t, ids in self.last.reveals_by_turn(team).items()}
            for team in (0, 1)
        }

    def worker_label(self, pid: int, uid: int) -> str:
        fam, k = self.worker_names.get((pid, uid), ("", 0))
        cls = self.gd.family_class_name(fam) if fam else "?"
        return f"{cls} Worker {k}" if k else f"Worker #{uid}"

    # ── one player half ──────────────────────────────────────────────
    def half(self, turn: int, pid: int) -> dict | None:
        s = self.series
        if pid == 0:
            cur_t, prev_t = turn, s.prev_turn(turn)
        else:
            cur_t, prev_t = s.next_turn(turn), turn
        if cur_t is None or cur_t not in s.zips or (pid == 0 and turn not in s.zips):
            return None
        cur = s.snapshot(cur_t)
        prev = s.snapshot(prev_t) if prev_t is not None else None
        player = cur.players[pid]
        window = f"S{prev_t if prev_t is not None else '-'}→S{cur_t}"
        clean = (pid == 0 and prev_t == turn - 1) or (pid == 1 and cur_t == turn + 1)

        return {
            "turn": turn,
            "player": pid,
            "name": player.name,
            "nation": self.gd.name(player.nation),
            "window": window,
            "clean_window": clean,
            "tech": self._tech(cur, player, turn),
            "science": self._science(cur, player, turn),
            "cities": self._cities(cur, prev, cur_t, pid),
            "workers": self._workers(cur, pid),
            "military": self._military(cur, prev, pid, turn),
            "attacks": self._attacks(cur, prev, pid),
            "scouts": self._scouts(cur, prev, pid),
            "reveals": {
                "this_turn": self.reveals.get(pid, {}).get(turn, 0),
                "total": sum(n for t, n in self.reveals.get(pid, {}).items() if t <= turn),
            },
            "orders": self._orders(cur, prev, pid, turn),
            "laws": self._laws(cur, pid, turn),
            "religion": self._religion(cur, prev, pid, turn),
            "events": self._events(cur, prev, pid, turn),
            "legitimacy": self._legitimacy(cur, pid, turn),
            "stats": self._stats(cur, player, turn),
            "improvement_counts": self._improvement_counts(cur, pid),
        }

    # GDP basket per per-ankh's economy.ts: money is the numéraire (already
    # net of maintenance via SubtractFromYield); commodities valued at that
    # turn's market price (save stores prices ×10,000); orders excluded —
    # they're an action budget, not production.
    GDP_COMMODITIES = ("YIELD_FOOD", "YIELD_WOOD", "YIELD_STONE", "YIELD_IRON")

    def _stats(self, cur: Snapshot, player, turn: int) -> dict:
        def rate(y):
            return series_value_at(player.yield_rate_history.get(y, {}), turn)

        gdp = None
        money = rate("YIELD_MONEY")
        if money is not None:
            gdp = money / 10
            components = [{"yield": "YIELD_MONEY", "amount": money / 10,
                           "value": money / 10, "price": None}]
            for y in self.GDP_COMMODITIES:
                r = rate(y)
                p = series_value_at(cur.yield_price_history.get(y, {}), turn)
                if r is not None and p is not None:
                    v = (r / 10) * (p / 10_000)
                    gdp += v
                    sources = self._yield_sources(cur, player.id, y)
                    base_sum = sum(s["amount"] for s in sources)
                    other = round(r / 10 - base_sum, 1)
                    components.append({"yield": y, "amount": r / 10,
                                       "value": round(v, 1), "price": p / 10_000,
                                       "sources": sources, "other": other})
        return {
            "milscore": series_value_at(player.military_power_history, turn),
            "sci_total10": series_value_at(player.yield_total_history.get("YIELD_SCIENCE", {}), turn),
            "sci_rate10": player.science_rate_at(turn),
            "orders_rate10": series_value_at(player.yield_rate_history.get("YIELD_ORDERS", {}), turn),
            "orders_total10": series_value_at(player.yield_total_history.get("YIELD_ORDERS", {}), turn),
            "gdp": round(gdp, 1) if gdp is not None else None,
            "gdp_components": components if gdp is not None else [],
        }

    def _events(self, cur: Snapshot, prev: Snapshot | None, pid: int, turn: int) -> list[dict]:
        """Event stories that fired for this player at `turn`, with the chosen
        option where the save recorded one (option sets diffed vs prev)."""
        p = cur.players[pid]
        prev_opts = prev.players[pid].event_options if prev else set()
        new_opts = p.event_options - prev_opts
        # map story → newly-chosen option via the XML option→story table
        story_choice = {}
        for scope, opt in new_opts:
            story = self.gd.option_story.get(opt)
            if story:
                story_choice.setdefault(story, opt)
        out = []
        seen = set()
        fired = [(scope, story) for scope, story, t in p.event_turns if t == turn]
        # city-scoped events live on City elements
        for c in cur.player_cities(pid):
            for story_z, t in self._city_event_turns(cur, c.id).items():
                if t == turn:
                    fired.append((f"city {self.gd.name(c.name_token)}", story_z))
        for scope, story in fired:
            if story in seen:
                continue
            seen.add(story)
            info = self.gd.event_stories.get(story, {})
            opt = story_choice.get(story)
            out.append({
                "story": story,
                "title": info.get("title") or self.gd.name(story),
                "scope": scope,
                "option": opt,
                "option_text": self.gd.event_options.get(opt) if opt else None,
            })
        # options chosen this window whose story didn't register a turn
        for scope, opt in sorted(new_opts):
            story = self.gd.option_story.get(opt)
            if story and story not in seen:
                seen.add(story)
                info = self.gd.event_stories.get(story, {})
                out.append({"story": story,
                            "title": info.get("title") or self.gd.name(story),
                            "scope": scope, "option": opt,
                            "option_text": self.gd.event_options.get(opt)})
        return out

    def _city_event_turns(self, snap: Snapshot, city_id: int) -> dict[str, int]:
        c = snap.root.find(f".//City[@ID='{city_id}']")
        out = {}
        if c is not None:
            e = c.find("EventStoryTurn")
            if e is not None:
                for ch in e:
                    out[ch.tag] = int(ch.text or -1)
        return out

    def _legitimacy(self, cur: Snapshot, pid: int, turn: int) -> dict:
        p = cur.players[pid]
        hist = p.legitimacy_history
        val = series_value_at(hist, turn)
        prev_val = series_value_at(hist, turn - 1)
        return {"value": val, "delta": (val - prev_val) if (val is not None and prev_val is not None) else None}

    def _laws(self, cur: Snapshot, pid: int, turn: int) -> dict:
        roles = cur.player_roles(pid)
        adopted = [e.data[0] for e in self.last.players[pid].permanent_log
                   if e.type == "LAW_ADOPTED" and e.turn == turn and e.data[0]]
        return {
            "current": [{"law_class": lc, "law": law, "name": self.gd.name(law)}
                        for lc, law in roles["laws"].items()],
            "adopted_this_turn": [self.gd.name(x) for x in adopted],
        }

    def _religion(self, cur: Snapshot, prev: Snapshot | None, pid: int, turn: int) -> dict:
        roles = cur.player_roles(pid)
        founded = [e for e in self.last.players[pid].permanent_log
                   if e.type == "RELIGION_FOUNDED" and e.turn == turn]
        # state religion adoption: compare with the previous snapshot
        prev_state = prev.player_roles(pid)["state_religion"] if prev else None
        state = roles["state_religion"]
        # theology additions on religions this player founded
        founders = cur.religion_founders()
        theo_now = cur.theologies()
        theo_prev = prev.theologies() if prev else {}
        new_theologies = []
        for rel, owner in founders.items():
            if owner == pid:
                for th in theo_now.get(rel, []):
                    if th not in theo_prev.get(rel, []):
                        new_theologies.append({"religion": self.gd.name(rel),
                                               "theology": self.gd.name(th)})
        return {
            "state_religion": self.gd.name(state) if state else None,
            "state_religion_adopted": bool(state and state != prev_state),
            "founded_this_turn": [e.text[:80] for e in founded],
            "theologies": {self.gd.name(r): [self.gd.name(t) for t in ths]
                           for r, ths in theo_now.items() if founders.get(r) == pid},
            "new_theologies": new_theologies,
        }

    def _tech(self, cur: Snapshot, player, turn: int) -> dict:
        res = player.tech_researching
        discovered_now = [t for t, dt in self.tech_discovered.get(player.id, {}).items()
                          if dt == turn]
        d = {"researching": res, "researching_name": self.gd.name(res or ""),
             "discovered_this_turn": [self.gd.name(t) for t in discovered_now],
             "alternatives": [
                 {"tech": t, "name": self.gd.name(t),
                  "bonus_card": self.gd.techs.get(t, {}).get("trash", False)}
                 for t in player.tech_available if t != res],
             }
        if res:
            prog = player.tech_progress.get(res, 0)
            cost10 = self.gd.techs.get(res, {}).get("cost", 0) * 10
            disc = self.tech_discovered.get(player.id, {}).get(res)
            left = None
            if disc is not None and disc > turn:
                left = disc - turn
            elif cost10:
                rate = player.science_rate_at(turn)
                if rate:
                    left = max(1, -(-(cost10 - prog) // rate))
            d.update(progress10=prog, cost10=cost10, discovered_turn=disc, years_left=left)
        return d

    def _science(self, cur: Snapshot, player, turn: int) -> dict:
        d = {
            "rate10": player.science_rate_at(turn),
            "stockpile10": player.yield_stockpile.get("YIELD_SCIENCE", 0),
        }
        if self.science_model is not None:
            got = self.science_model.player_science(cur, player.id)
            rows = [(lbl, v) for lbl, v in got["rows"]]
            if d["rate10"] is not None:
                resid = d["rate10"] - got["total10"]
                if resid:
                    rows.append(("unattributed", resid))
            d["breakdown"] = rows
            d["cities_detail"] = got["cities"]
        return d

    def _cities(self, cur: Snapshot, prev: Snapshot | None, cur_t: int, pid: int) -> list[dict]:
        out = []
        for c in cur.player_cities(pid):
            pc = prev.cities.get(c.id) if prev else None
            head = c.queue[0] if c.queue else None
            bs: BuildStatus | None = None
            if head:
                prev_head = pc.queue[0] if pc and pc.queue else None
                bs = build_status(self.series, self.gd, cur_t, c.id, head, prev_head)
            spec = sum(1 for t in cur.tiles.values()
                       if t.city_territory == c.id and t.specialist)
            # improvements in territory: built (w/ specialist), under construction
            built: dict[str, dict] = {}
            constructing = []
            for t in cur.tiles.values():
                if t.city_territory != c.id or not t.improvement:
                    continue
                if t.improvement_turns_left > 0:
                    workers = [self.worker_label(pid, uid) for uid in t.unit_ids
                               if cur.units[uid].type == "UNIT_WORKER"
                               and cur.units[uid].player == pid]
                    constructing.append({
                        "name": self.gd.name(t.improvement),
                        "years_left": t.improvement_turns_left,
                        "workers": workers, "xy": cur.xy(t.id),
                    })
                else:
                    b = built.setdefault(self.gd.name(t.improvement),
                                         {"count": 0, "specialists": []})
                    b["count"] += 1
                    if t.specialist:
                        b["specialists"].append(self.gd.name(t.specialist))
            projects = {self.gd.name(pz): n for pz, n in c.project_counts.items() if n > 0}
            # per-city science: model value now vs previous turn, with the
            # itemized diff explaining the change
            sci = self._city_science_delta(cur, prev, c, pid)
            growth = c.yield_progress.get("YIELD_GROWTH", 0)
            # Per-city yield outputs. Growth and the active production yield
            # are OBSERVED (progress deltas = ground truth); culture likewise.
            # Science is modeled (validated). Civics/training have no per-city
            # accumulator in the save, so they only appear when the city is
            # currently producing with that yield.
            yields = {}
            if pc is not None:
                g = growth - pc.yield_progress.get("YIELD_GROWTH", 0)
                if g > 0:
                    yields["YIELD_GROWTH"] = g
                cd = (c.yield_progress.get("YIELD_CULTURE", 0)
                      - pc.yield_progress.get("YIELD_CULTURE", 0))
                if cd > 0:
                    yields["YIELD_CULTURE"] = cd
            if head is not None and bs is not None and bs.rate10:
                py = {"BUILD_UNIT": self.gd.units, "BUILD_PROJECT": self.gd.projects,
                      "BUILD_SPECIALIST": self.gd.specialists}.get(head.build, {})
                pyield = (py.get(head.ztype) or {}).get("prod_yield")
                if pyield:
                    yields[pyield] = max(yields.get(pyield, 0), bs.rate10)
            if sci.get("total10") is not None:
                yields["YIELD_SCIENCE"] = sci["total10"]
            growth_delta = growth - (pc.yield_progress.get("YIELD_GROWTH", 0) if pc else 0) if pc else None
            out.append({
                "id": c.id, "name": self.gd.name(c.name_token),
                "family": self.gd.family_class_name(c.family),
                "capital": c.capital,
                "citizens": c.citizens, "specialists": spec,
                "producing": None if not head else {
                    "build": head.build, "type": head.ztype,
                    "name": self.gd.name(head.ztype),
                    "progress10": head.progress, "cost10": bs.cost10,
                    "rate10": bs.rate10, "years_left": bs.turns_left,
                    "completes_turn": bs.completes_turn,  # verification only
                },
                "also_queued": [
                    {"type": q.ztype, "name": self.gd.name(q.ztype)}
                    for q in c.queue[1:]],
                "growth_progress10": growth,
                "growth_delta10": growth_delta,
                "improvements": built,
                "constructing": constructing,
                "projects": projects,
                "science": sci,
                "yields": yields,
            })
        return out

    def _city_science_delta(self, cur: Snapshot, prev: Snapshot | None, c, pid: int) -> dict:
        from .science import modify
        m = self.science_model
        weps = m.player_wonder_effects(cur, pid)
        items, mod = m.city_science(cur, c, weps)
        total = modify(sum(v for _, v in items), mod)
        d = {"total10": total, "delta10": None, "changes": []}
        pc = prev.cities.get(c.id) if prev else None
        if pc is not None and pc.player == pid:
            pweps = m.player_wonder_effects(prev, pid)
            pitems, pmod = m.city_science(prev, pc, pweps)
            ptotal = modify(sum(v for _, v in pitems), pmod)
            d["delta10"] = total - ptotal
            if d["delta10"]:
                def agg(lst):
                    out = {}
                    for lbl, v in lst:
                        out[lbl] = out.get(lbl, 0) + v
                    return out
                a, b = agg(pitems), agg(items)
                for lbl in sorted(set(a) | set(b)):
                    dv = b.get(lbl, 0) - a.get(lbl, 0)
                    if dv:
                        d["changes"].append(f"{'+' if dv > 0 else ''}{dv / 10:g} {lbl}")
                if mod != pmod:
                    d["changes"].append(f"modifier {pmod:+d}% → {mod:+d}%")
        return d

    def _improvement_counts(self, cur: Snapshot, pid: int) -> dict[str, int]:
        """Player-wide finished improvement counts by display name."""
        out: dict[str, int] = {}
        city_ids = {c.id for c in cur.player_cities(pid)}
        for t in cur.tiles.values():
            if (t.city_territory in city_ids and t.improvement
                    and t.improvement_turns_left == 0):
                n = self.gd.name(t.improvement)
                out[n] = out.get(n, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def _yield_sources(self, cur: Snapshot, pid: int, yield_type: str) -> list[dict]:
        """Base tile-output contributions to a commodity yield, by improvement
        (XML base outputs + resource-sited class outputs; excludes specialists,
        modifiers, city base — the remainder shows as 'other')."""
        agg: dict[str, int] = {}
        city_ids = {c.id for c in cur.player_cities(pid)}
        for t in cur.tiles.values():
            if not (t.city_territory in city_ids and t.improvement
                    and t.improvement_turns_left == 0):
                continue
            v = self.gd.improvement_outputs.get(t.improvement, {}).get(yield_type, 0)
            cls = self.gd.improvement_class_of.get(t.improvement, "")
            if t.resource:
                v += self.gd.class_resource_outputs.get(cls, {}).get(t.resource, {}).get(yield_type, 0)
            if v:
                n = self.gd.name(t.improvement)
                agg[n] = agg.get(n, 0) + v
        # XML outputs are tenths — convert to display units
        return [{"name": n, "amount": round(v / 10, 1)}
                for n, v in sorted(agg.items(), key=lambda kv: -kv[1])]

    def _workers(self, cur: Snapshot, pid: int) -> list[dict]:
        out = []
        for u in cur.player_units(pid):
            if u.type != "UNIT_WORKER":
                continue
            tile = cur.tiles[u.tile_id]
            city = cur.city_of_tile(u.tile_id)
            w = {
                "unit_id": u.id,
                "label": self.worker_label(pid, u.id),
                "city": self.gd.name(city.name_token) if city else None,
                "xy": cur.xy(u.tile_id),
            }
            # A worker on a tile with an unfinished improvement is working it
            # (COOLDOWN_BUILDING only marks the turn a build order was given).
            if tile.improvement and tile.improvement_turns_left > 0:
                w["building"] = self.gd.name(tile.improvement)
                w["years_left"] = tile.improvement_turns_left
            else:
                w["building"] = None
            out.append(w)
        return out

    def _military(self, cur: Snapshot, prev: Snapshot | None, pid: int, turn: int) -> list[dict]:
        out = []
        # cities founded in this window: a vanished settler founded one, it
        # wasn't lost.
        prev_turn = prev.turn if prev else 0
        founded = [(c.tile_id, self.gd.name(c.name_token))
                   for c in cur.player_cities(pid)
                   if prev_turn < c.founded_turn <= cur.turn]
        from .military import neighbors
        for d in unit_deltas(prev, cur, pid):
            u = d.unit
            if u.type == "UNIT_SETTLER" and d.status == "gone" and founded:
                # nearest founded city claims this settler
                near = min(founded, key=lambda f: 0 if f[0] == u.tile_id
                           else 1 if f[0] in neighbors(u.tile_id, cur.map_width) else 2)
                founded.remove(near)
                out.append({"unit_id": u.id, "type": u.type,
                            "name": self.gd.name(u.type), "status": "founded",
                            "founded_city": near[1], "xy": cur.xy(near[0]),
                            "level": u.level, "hp": None})
                continue
            if u.type in CIVILIAN:
                if d.status != "gone":
                    continue  # civilian losses still worth listing
            e = {
                "unit_id": u.id, "type": u.type, "name": self.gd.name(u.type),
                "status": d.status, "xy": cur.xy(u.tile_id) if d.status != "gone" else None,
                "level": u.level, "hp": None,
            }
            if d.status == "gone":
                # last known position = where it died (units can't move after
                # their owner's half in this window; see method notes)
                e["died_xy"] = cur.xy(u.tile_id)
                e["died_tile"] = u.tile_id
                e["last_hp"] = 20 - u.damage if u.damage else None
                if prev is not None:
                    # attribute the kill: did an opponent attack that tile
                    # during this window?
                    for opp in cur.players:
                        if opp == pid:
                            continue
                        for ev in combat_events(prev, cur, opp):
                            if ev.tile_id == u.tile_id:
                                e["killed_by"] = cur.players[opp].name
                                e["killed_by_units"] = [
                                    {"unit_id": a.id, "name": self.gd.name(a.type)}
                                    for a in ev.attacker_units[:3]]
                                e["kill_confidence"] = ev.confidence
                                break
                        if "killed_by" in e:
                            break
            if d.status == "active":
                if d.upgraded_from:
                    e["upgraded_from"] = self.gd.name(d.upgraded_from)
                if d.moved_from is not None:
                    e["moved_from"] = cur.xy(d.moved_from)
                if d.damage_delta:
                    e["damage_delta"] = d.damage_delta
                if u.damage:
                    e["damage_total"] = u.damage
                if d.promotions_gained:
                    e["promotions_gained"] = [self.gd.name(p) for p in d.promotions_gained]
                if u.cooldown:
                    e["cooldown"] = u.cooldown
                if d.moved_from is None and u.turns_since_last_move >= 1:
                    e["held_position"] = True
            out.append(e)
        return out

    def _attacks(self, cur: Snapshot, prev: Snapshot | None, pid: int) -> list[dict]:
        """Attacks made by pid in this half's window (RecentAttacks delta +
        cooldown/adjacency attribution)."""
        out = []
        for ev in combat_events(prev, cur, pid):
            tgt = None
            if ev.target is not None:
                owner = ("tribe " + self.gd.name(ev.target.tribe)
                         if ev.target.player < 0
                         else cur.players[ev.target.player].name
                         if ev.target.player in cur.players else "?")
                tgt = {"type": ev.target.type, "name": self.gd.name(ev.target.type),
                       "unit_id": ev.target.id, "owner": owner,
                       "killed": ev.target_killed, "damage_dealt": ev.target_damage}
            out.append({
                "tile_xy": cur.xy(ev.tile_id), "attacks": ev.attacks,
                "target": tgt,
                "by": [{"unit_id": u.id, "name": self.gd.name(u.type)}
                       for u in ev.attacker_units[:3]],
                "confidence": ev.confidence,
            })
        return out

    def _scouts(self, cur: Snapshot, prev: Snapshot | None, pid: int) -> list[dict]:
        # TurnSteps survives only for P0 (P1's resets at the turn roll before
        # the next archive save) — fall back to observed movement.
        out = []
        for u in cur.player_units(pid):
            if u.type != "UNIT_SCOUT":
                continue
            pu = prev.units.get(u.id) if prev else None
            out.append({
                "unit_id": u.id, "xy": cur.xy(u.tile_id),
                "steps": u.turn_steps if pid == 0 else None,
                "moved_from": cur.xy(pu.tile_id) if pu and pu.tile_id != u.tile_id else None,
                "moved": bool(pu and pu.tile_id != u.tile_id),
            })
        return out

    def _orders(self, cur: Snapshot, prev: Snapshot | None, pid: int, turn: int) -> dict:
        p = cur.players[pid]
        rate = series_value_at(p.yield_rate_history.get("YIELD_ORDERS", {}), turn)
        left = p.yield_stockpile.get("YIELD_ORDERS", 0)
        spent = None
        if prev is not None:
            prev_left = prev.players[pid].yield_stockpile.get("YIELD_ORDERS", 0)
            if rate is not None:
                spent = prev_left + rate - left
        return {"rate10": rate, "left10": left, "spent10_approx": spent}

    # ── whole turn ───────────────────────────────────────────────────
    def turn_report(self, turn: int) -> dict:
        return {
            "turn": turn,
            "halves": [h for h in (self.half(turn, 0), self.half(turn, 1)) if h],
        }


# ── markdown rendering ──────────────────────────────────────────────
def render_markdown(rep: dict) -> str:
    L = [f"# Turn {rep['turn']}"]
    for h in rep["halves"]:
        L.append(f"\n## {h['name']} ({h['nation']}) — turn {h['turn']}"
                 + ("" if h["clean_window"] else f"  ⚠ window {h['window']} (archive gap)"))
        t = h["tech"]
        if t["discovered_this_turn"]:
            L.append(f"**Discovered**: {', '.join(t['discovered_this_turn'])}")
        if t["researching"]:
            eta = f"{t['years_left']}y left" if t.get("years_left") else "?y left"
            frac = f"{fmt10(t.get('progress10'))}/{fmt10(t.get('cost10'))} sci"
            L.append(f"**Tech**: {t['researching_name']} ({eta}; {frac})")
        else:
            L.append("**Tech**: choosing…")
        if t["alternatives"]:
            alts = ", ".join(a["name"] + (" (bonus)" if a["bonus_card"] else "")
                             for a in t["alternatives"])
            L.append(f"  - alternatives: {alts}")
        sci = h["science"]
        L.append(f"**Science**: +{fmt10(sci['rate10'])}/y")
        for lbl, v in sci.get("breakdown", []):
            L.append(f"    - {lbl}: {'+' if v >= 0 else ''}{fmt10(v)}")
        o = h["orders"]
        spent = fmt10(o["spent10_approx"]) if o["spent10_approx"] is not None else "?"
        L.append(f"**Orders**: {fmt10(o['rate10'])}/y, spent ≈{spent}, {fmt10(o['left10'])} left")
        laws = h["laws"]
        SUCCESSION = {"LAWCLASS_ORDER", "LAWCLASS_SUCCESSION"}
        civic = [l for l in laws["current"] if l["law_class"] not in SUCCESSION]
        succ = [l for l in laws["current"] if l["law_class"] in SUCCESSION]
        line = f"**Laws**: {', '.join(l['name'] for l in civic) or 'none'}"
        if laws["adopted_this_turn"]:
            line += f"  ⚡ adopted {', '.join(laws['adopted_this_turn'])}"
        L.append(line)
        rel = h["religion"]
        rel_bits = []
        if rel["state_religion"]:
            rel_bits.append(f"state religion: {rel['state_religion']}"
                            + (" ⚡ adopted this turn" if rel["state_religion_adopted"] else ""))
        for r, ths in rel["theologies"].items():
            if ths:
                rel_bits.append(f"{r} theologies: {', '.join(ths)}")
        for nt in rel["new_theologies"]:
            rel_bits.append(f"⚡ {nt['religion']} established {nt['theology']}")
        for f in rel["founded_this_turn"]:
            rel_bits.append(f"⚡ {f}")
        if rel_bits:
            L.append("**Religion**: " + "; ".join(rel_bits))
        st = h.get("stats", {})
        if st:
            gdp = f" · GDP {st['gdp']}/y" if st.get("gdp") is not None else ""
            L.append(f"**Stats**: milscore {st.get('milscore','?')}"
                     f" · sci total {fmt10(st.get('sci_total10'))} (+{fmt10(st.get('sci_rate10'))}/y)"
                     f" · orders {fmt10(st.get('orders_rate10'))}/y"
                     f" (total {fmt10(st.get('orders_total10'))}){gdp}")
            if st.get("gdp_components"):
                for gc in st["gdp_components"]:
                    yn = gc["yield"].replace("YIELD_", "").lower()
                    if gc["price"] is None:
                        L.append(f"    - {yn}: {gc['amount']:+g}/y")
                        continue
                    srcs = ", ".join(f"+{s['amount']} {s['name']}" for s in gc.get("sources", [])[:6])
                    if gc.get("other"):
                        srcs += (", " if srcs else "") + f"{gc['other']:+g} other"
                    L.append(f"    - {yn}: {gc['amount']:+g}/y @ {gc['price']:g}g = {gc['value']:g}g"
                             + (f" ({srcs})" if srcs else ""))
        lg = h["legitimacy"]
        if lg["value"] is not None:
            d = f" ({'+' if lg['delta'] > 0 else ''}{lg['delta']} this turn)" if lg.get("delta") else ""
            L.append(f"**Legitimacy**: {lg['value']}{d}")
        if succ:
            L.append(f"**Succession**: {', '.join(l['name'] for l in succ)}")
        if h["events"]:
            L.append("\n**Events**")
            for ev in h["events"]:
                choice = f" → chose “{ev['option_text']}”" if ev.get("option_text") else ""
                scope = f" [{ev['scope']}]" if ev["scope"] and not ev["scope"].startswith("P.") else ""
                L.append(f"- {ev['title']}{scope}{choice}")
        rv = h["reveals"]
        L.append(f"**Map**: +{rv['this_turn']} tiles revealed (total {rv['total']})")
        L.append("\n**Cities**")
        for c in h["cities"]:
            pop = c["citizens"] + c["specialists"]
            head = c["producing"]
            if head:
                eta = f"{head['years_left']}y left" if head["years_left"] else "?y left"
                prod = (f"{head['name']} ({eta}; {fmt10(head['progress10'])}"
                        f"/{fmt10(head['cost10'])}"
                        + (f", +{fmt10(head['rate10'])}/y" if head["rate10"] else "") + ")")
            else:
                prod = "(queue empty)"
            growth = ""
            if c["growth_delta10"]:
                d = c["growth_delta10"]
                growth = (f"; {'+' if d > 0 else ''}{fmt10(d)} growth/y"
                          + ("" if d > 0 else " (citizen born / growth diverted)"))
            seat = f", {c['family']}" + (" capital" if c["capital"] else "")
            csci = c.get("science", {})
            sci_s = ""
            if csci.get("total10") is not None:
                sci_s = f"; sci {fmt10(csci['total10'])}"
                if csci.get("delta10"):
                    dd = csci["delta10"]
                    sci_s += f" ({'+' if dd > 0 else ''}{fmt10(dd)})"
            L.append(f"- **{c['name']}** (pop {pop}{seat}): {prod}{growth}{sci_s}")
            if csci.get("changes"):
                L.append(f"    - sci change: {'; '.join(csci['changes'])}")
            if c.get("yields"):
                ICON = {"YIELD_GROWTH": "🌾 growth", "YIELD_CIVICS": "⚖ civics",
                        "YIELD_TRAINING": "⚔ training", "YIELD_SCIENCE": "🧪 science",
                        "YIELD_CULTURE": "🎭 culture", "YIELD_MONEY": "💰 money"}
                L.append("    - yields: " + ", ".join(
                    f"{ICON.get(k, k)} {fmt10(v)}/y" for k, v in c["yields"].items()))
            if c["also_queued"]:
                L.append(f"    - then: {', '.join(q['name'] for q in c['also_queued'])}")
            if c.get("improvements"):
                bits = []
                for nm, b in sorted(c["improvements"].items()):
                    s = nm + (f" ×{b['count']}" if b["count"] > 1 else "")
                    if b["specialists"]:
                        s += f" ({', '.join(b['specialists'])})"
                    bits.append(s)
                L.append(f"    - improvements: {', '.join(bits)}")
            for cx in c.get("constructing", []):
                who = f", {'/'.join(cx['workers'])}" if cx["workers"] else " (no worker!)"
                L.append(f"    - building: {cx['name']} ({cx['years_left']}y{who})")
            if c.get("projects"):
                L.append("    - projects: " + ", ".join(
                    n + (f" ×{k}" if k > 1 else "") for n, k in sorted(c["projects"].items())))
        if h.get("improvement_counts"):
            L.append("\n**Improvements**: " + ", ".join(
                f"{n} ×{k}" if k > 1 else n for n, k in h["improvement_counts"].items()))
        if h["workers"]:
            L.append("\n**Workers**")
            for w in h["workers"]:
                loc = f" in {w['city']}" if w["city"] else f" @{w['xy']}"
                act = (f"building {w['building']} ({w['years_left']}y left)"
                       if w["building"] else "idle/moving")
                L.append(f"- {w['label']}{loc}: {act}")
        mil = [m for m in h["military"]]
        if mil:
            L.append("\n**Military**")
            for m in mil:
                bits = []
                if m["status"] == "new":
                    bits.append("NEW")
                elif m["status"] == "founded":
                    bits.append(f"founded **{m['founded_city']}** @{m['xy']}")
                elif m["status"] == "gone":
                    loc = f" at {m['died_xy']}" if m.get("died_xy") else ""
                    by = ""
                    if m.get("killed_by"):
                        who = "/".join(u["name"] for u in m.get("killed_by_units", [])) or "?"
                        by = f" — killed by {m['killed_by']} ({who})"
                        if m.get("kill_confidence") != "cooldown":
                            by += " [inferred]"
                    hp = f", was at {m['last_hp']}hp" if m.get("last_hp") else ""
                    bits.append(f"LOST{loc}{by}{hp}")
                if m.get("moved_from"):
                    bits.append(f"moved {m['moved_from']}→{m['xy']}")
                elif m.get("held_position"):
                    bits.append("held position")
                if m.get("damage_delta"):
                    dd = m["damage_delta"]
                    bits.append(f"took {dd} dmg" if dd > 0 else f"healed {-dd}")
                if m.get("damage_total"):
                    bits.append(f"at {20 - m['damage_total']}/20 hp")
                if m.get("promotions_gained"):
                    bits.append("promoted: " + ", ".join(m["promotions_gained"]))
                if m.get("upgraded_from"):
                    bits.append(f"upgraded from {m['upgraded_from']}")
                if m.get("cooldown"):
                    bits.append(ACTION_COOLDOWNS.get(m["cooldown"],
                                m["cooldown"].replace("COOLDOWN_", "").lower()))
                lvl = f" (lvl {m['level']})" if m["level"] else ""
                L.append(f"- {m['name']} #{m['unit_id']}{lvl}: " + ("; ".join(bits) or "no visible action"))
        if h["attacks"]:
            L.append("\n**Attacks made**")
            for a in h["attacks"]:
                t = a["target"]
                if t:
                    res = "KILLED" if t["killed"] else (
                        f"dealt {t['damage_dealt']} dmg" if t["damage_dealt"] else "result unknown")
                    tgt = f"{t['name']} #{t['unit_id']} ({t['owner']}) — {res}"
                else:
                    tgt = "empty tile / improvement"
                by = ", ".join(f"{b['name']} #{b['unit_id']}" for b in a["by"]) or "?"
                conf = "" if a["confidence"] == "cooldown" else " (attacker inferred)"
                L.append(f"- @{a['tile_xy']} ×{a['attacks']}: {tgt} — by {by}{conf}")
        if h["scouts"]:
            L.append("\n**Scouts**")
            for sc in h["scouts"]:
                if sc["steps"] is not None:
                    move = f"{sc['steps']} steps"
                elif sc["moved_from"]:
                    move = f"moved {sc['moved_from']}→{sc['xy']}"
                else:
                    move = "did not move"
                L.append(f"- Scout #{sc['unit_id']} @{sc['xy']}: {move}")
    return "\n".join(L) + "\n"
