# ow-replay-analyzer

Turn-by-turn analysis and replays for **Old World** multiplayer games,
reconstructed from per-turn cloud-save archives — plus a documented,
grounding-first workflow for writing Claude-powered game reports.

Old World's play-by-cloud mode uploads a save every half-turn. Given a
folder of those saves (one zip per turn), this toolkit rebuilds the whole
game: what every city produced, what every worker built, every tech choice
and its alternatives, attacks and damage, laws, events and the options
chosen, per-source science income, exact per-team fog of war — and renders
it as an interactive dual-POV replay and a shareable analysis report.

**Replay library (companion site): https://alcaras.github.io/owreplays/** —
published games, each with its interactive replay and analysis report.

## Examples (from a real 63-turn tournament duel)

- [`examples/alcaras-v-lich-replay.html`](examples/alcaras-v-lich-replay.html)
  — the interactive replay: two synced fog-of-war POVs (or single-POV
  layout), turn slider, three-state fog (unexplored / explored / currently
  visible), units, tribal camps, landmarks, per-turn report sidebars.
  One self-contained file; download and open.
- [`examples/alcaras-v-lich-report.html`](examples/alcaras-v-lich-report.html)
  — the written autopsy: charts, map figures rendered by the replay engine
  (including a "what he saw vs what was there" fog pair), and
  recommendations, every number traced to computed facts.
- [`examples/alcaras-v-lich-factsheet.json`](examples/alcaras-v-lich-factsheet.json)
  — the fact sheet the report cites.
- `examples/turn-*.md` — sample per-turn text reports.

## Requirements

- Python 3.10+ (stdlib only), Node (only for smoke tests)
- **Old World installed** — the parser reads game rules from the install's
  `Reference/` folder (XML infos + the shipped C# source). Default path is
  the macOS Steam location; override with `OW_REFERENCE`.
- For map rendering: a folder of PNG icon dumps from the game's assets
  (improvements/resources/units/specialists/crests); point `OW_IMG` at it.

## Pipeline

```sh
A="/path/to/mp-archive/<game name>"      # folder of per-turn cloud zips

python3 analyze.py "$A"                  # → reports/turn-NNN.md + turns.json
python3 viewer_export.py "$A"            # → viewer/data.js (+ icons)
open viewer/index.html                   # interactive dual-POV replay
python3 package_viewer.py                # → single shareable replay .html

python3 compare.py "$A"                  # head-to-head metrics table
python3 factsheet.py "$A"                # → analysis/factsheet.json
python3 build_report.py "$A"             # → analysis report (per-game script)
```

## The Claude report workflow

The written report is produced by Claude working **from the fact sheet
only** — the method, the save-timing model (every save snapshots at player
0's end-of-turn; fairness rules follow from it), and a grounding protocol
with a catalog of real hallucinations caught during development live in:

**[`docs/game-report-method.md`](docs/game-report-method.md)**

Short version: every number in the report must exist in `factsheet.json`;
quantifiers ("every", "first") are queries; game mechanics cite the
install's XML/C# — not genre memory; proxy counters never support
who-did-what claims; end-of-game map reveal is not scouting.

## What's inside

```
owparse/            the library
  save.py           one save XML → typed Snapshot (cities, units, tiles, logs, fog)
  series.py         archive folder → ordered snapshots (dup turns, gaps)
  gamedata.py       Reference XML loader (names, costs, effect tables)
  diff.py           worker ordinals, build-completion scan, unit deltas
  military.py       attack attribution (cooldowns + RecentAttacks + adjacency)
  science.py        per-source science model — validated exact vs the game's
                    recorded totals through ~T30, ~8% mean error over a full game
  opinion.py        character-opinion model (court yield modifiers)
  report.py         per-turn report assembly + markdown
viewer/index.html   the replay viewer (canvas hex renderer, dual/single POV)
docs/
  game-report-method.md   the Claude report method + grounding protocol
  opinion-system.md       the opinion system, documented from the C# source
```

Notes that make the reconstruction honest: saves snapshot after player 0's
half, so each player is sampled at their *own* end-of-turn; production
completes at the turn roll (which sits between the two halves); vision is
reconstructed geometrically (the save only keeps current-vision flags for
the pending player); science attribution is a ported-and-validated version
of the game's own yield engine, cross-checked against the totals the save
records.
