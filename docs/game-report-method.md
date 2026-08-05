# Claude-powered game reports — method & grounding protocol

How to produce an `analysis/<game>-report.html` for any duel archive, and —
more importantly — how to keep the narrative *grounded*. Written for future
sessions doing this on a new save.

## Pipeline (per game)

```sh
# 1. exact per-turn data + viewer assets
python3 viewer_export.py "<archive dir>" --out viewer

# 2. THE FACT SHEET — the only source of truth for the narrative
python3 factsheet.py "<archive dir>"          # → analysis/factsheet.json

# 3. (Claude) read the fact sheet, investigate anomalies with ad-hoc
#    scripts, extend factsheet.py with anything new worth citing

# 4. (Claude) write the narrative into a build script that imports the
#    chart/figure machinery, pulling every number from the fact sheet
python3 build_report.py                       # → analysis/<game>-report.html
```

`build_report.py` is per-game (the narrative is the analysis); the reusable
machinery is: `factsheet.py` + `compare.py` (metrics, fair sampling, idle
rule), the SVG chart helper, the canvas map-figure renderer (a trimmed copy
of the viewer engine reading the same `viewer/data.js`), and the validated
dark palette (`#b8862f` alcaras-slot / `#3987e5` opponent-slot — re-run the
dataviz validator if you change them).

## Timing model (get this wrong and every comparison is unfair)

Every cloud save S_N is snapshotted when **player 0 ends their half of
turn N**. Therefore:

- P0's turn-N state = S_N; P1's turn-N state = S_{N+1}.
- Production completes and cooldowns clear at the turn roll, which sits
  AFTER P1's half and BEFORE P0's.
- Idle workers: a worker is idle only if (a) not on an in-progress build,
  (b) it didn't move during its owner's half, and (c) for P1 only, it isn't
  standing on a build that completed at the post-half roll. P0's builds
  complete *before* his half, so his jobless workers had a full turn to be
  reassigned — the asymmetric rule is what makes the comparison fair.

## Grounding protocol

The failure mode is specific: **the narrative voice keeps going after the
data stops.** Real examples from the first report, all caught only on
review:

| claim | status | lesson |
|---|---|---|
| "a watchtower on the approach corridors" | ✗ no such improvement in Old World | game-rule claims must trace to `Reference/XML` or the C# source |
| "every Barracks an Officer" | ✗ 6 of 8 staffed (shrines were 4/4) | absolute quantifiers ("every", "never", "always") each need their own query |
| "Pyramids already up" at T20 | ✗ 7 build-turns left | figure captions are claims too |
| "you found more landmarks (18 vs 14), his were exclusive firsts" | ✗ per-tile reveal data says first-revealer was 18:16 *Lich* | bonus counts are lossy proxies — the naming branch (Tile.cs ~8356) requires sole-revealer AND no event override, and the event branch pays *neither* bonus |

Rules:

1. **Every number in the report exists in `factsheet.json`** (or in a query
   you ran and then folded into `factsheet.py`). No arithmetic in prose —
   compute ratios in the script.
2. **Proxy metrics don't support identity claims.** `BonusCount` counts
   bonuses, not events; logs record what was logged; if the claim is "who
   did X first/most", derive it from primary state (tiles, units, cities),
   not from reward counters.
3. **Beware end-of-game artifacts.** Game over reveals the whole map:
   `RevealedTurn == final turn` means "saw it at the score screen", not
   scouting. The fact sheet flags these (`end_reveal_artifact`).
4. **Game mechanics come from the install, not from genre memory.** The
   full C# source is at `Reference/Source/Base/Game/GameCore/`; the XML at
   `Reference/XML/Infos/`. If a sentence asserts how the game works, it
   cites a file. (Old World is not Civ: no watchtowers, orders not moves,
   growth builds settlers.)
5. **Quantifiers are queries.** "every/all/none/first/only" → run the
   query, quote the actual fraction.
6. **Separate observation from interpretation.** "18 units staged at
   (18–20, 23–26), outside vision range" is observation. "He was baiting
   the counterattack" is interpretation — either label it as reading, or
   cut it. Interpretation is allowed; disguising it isn't.
7. **The model is not the game.** Recomputed science (etc.) is validated
   but imperfect (exact to ~T30, ~8% mean error late). Cite *recorded*
   totals for totals; use the model for *composition*, with the accuracy
   note in the method section. `science_decomposition` in the fact sheet
   carries both `total` (model) and `recorded` side by side.
8. **Figures are rendered from the same data as the claims** — use the
   viewer engine (turn/POV/center/span), never a mock-up. If the caption
   says an army is outside vision, render the POV variant and check.

## Report structure that worked

hero (result + 4–5 stat tiles) → "how the game was won" (3 curve charts) →
one section per engine/divergence, each with charts + a map figure pair
(the two players' same-region or same-moment contrast) → "what the loser
did well" → numbered recommendations (each tied to a cited metric) →
method note (save timing, idle rule, model accuracy).

The strongest figure type is the **POV pair**: same turn, same center, one
canvas with the player's fog, one omniscient. (T57 Shiraz: 18-unit army
staged 7 tiles out of vision.)

## Checklist before shipping

- [ ] every number appears in factsheet.json (spot-check the tiles/hero)
- [ ] every "every/all/first/only" has a query behind it
- [ ] captions checked against the rendered turn (build states, unit counts)
- [ ] mechanics claims traceable to Reference XML / C#
- [ ] model-derived vs recorded numbers labeled; accuracy note present
- [ ] charts: palette validated, one axis, direct labels, hover works
- [ ] open the HTML and *look* at it (layout, figure crops, label overlap)
