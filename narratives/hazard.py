#!/usr/bin/env python3
"""alcaras v HazardBringsAxe (Carthage vs Yuezhi, T83) — the mirror image
of the Lich loss: every engine alcaras missed there, he ran here.

Every number cited comes from analysis/hazard-factsheet.json.
Run: python3 -m narratives.hazard   (after viewer_export for this archive)
"""
from pathlib import Path
import json

import report_lib as R

ARCHIVE = "/Users/dominik/Library/CloudStorage/Dropbox/cc/owsaves/mp-archive/alcaras v HazardBringsAxe"
OUT = "analysis/alcaras-v-hazardbringsaxe-report.html"
# Carthage vs Yuezhi — nation hues snapped to dark-validated steps
C0, C1 = "#3987e5", "#c94b46"


def main():
    R.setup(ARCHIVE)   # chart colours come from each nation
    M, idle = R.collect()
    F = json.load(open("analysis/hazard-factsheet.json"))
    ch = {k: R.chart(f"ch-{k}", t, M[k][0], M[k][1], u) for k, t, u in [
        ("sci", "Science per turn", "🧪/y"),
        ("gdp", "GDP", "gold-equivalent/y"),
        ("mil", "Military score", ""),
        ("imps", "Finished improvements", ""),
        ("specs", "Specialists", ""),
        ("workers", "Workers", ""),
        ("laws", "Active laws", ""),
        ("pop", "Population", ""),
        ("orders_left", "Orders left at end of turn", ""),
    ]}
    body = f"""
<header>
 <h1>alcaras v HazardBringsAxe <span class=res>🏆 alcaras wins by Conquest, turn 83</span></h1>
 <div class=sub>Carthage (<b class=p0>alcaras</b>) vs Yuezhi (<b class=p1>HazardBringsAxe</b>),
 83 turns, reconstructed from a complete save series with no missing turns.
 This is the photographic negative of the <a href="alcaras-v-lich-report.html">Lich defeat</a>:
 the same player, the same engines — running the right way round.</div>
</header>

<div class=tiles>
 <div class=tile><div class=n>7 : 1</div><div class=l>GDP ratio at turn 20</div></div>
 <div class=tile><div class=n>T8 / T20</div><div class=l>Centralization / Exploration adopted</div></div>
 <div class=tile><div class=n>154 : 67</div><div class=l>improvements at turn 80</div></div>
 <div class=tile><div class=n>28 : 11</div><div class=l>specialists at turn 80</div></div>
 <div class=tile><div class=n>3.0×</div><div class=l>science rate at turn 80</div></div>
</div>

<section>
<h2>The whole game in one sentence</h2>
<p>alcaras built an economy roughly an order of magnitude larger than his opponent's
by turn 20 and never let the gap close; the conquest at turn 83 was the bill coming due.
GDP was <b>280 : 40</b> at turn 20 — a seven-to-one lead before a single serious battle —
and 4,374 : 283 by turn 80.</p>
<div class=grid3>{ch['gdp']}{ch['sci']}{ch['mil']}</div>
</section>

<section>
<h2>1 · Laws early, laws often</h2>
<p>Compare the law timelines directly. alcaras: <b>Centralization T8, Exploration T20,
Constitution T29, Slavery T40</b> — four laws before his opponent passed his first.
HazardBringsAxe: <b>Centralization T54</b>, then Slavery T69 and the rest crammed into
the last dozen turns. That is a ~45-turn head start on the civics engine, and it shows
in every downstream curve.</p>
<p>Against Lich, alcaras adopted Exploration on turn 54 and lost. Here he adopted it on
turn 20 and won. Same player, same law, 34 turns apart.</p>
<div class=grid3>{ch['laws']}{ch['workers']}{ch['imps']}</div>
</section>

<section>
<h2>2 · Land, then infrastructure</h2>
<p>Seven cities by turn 32 (Carthago T1, Thapsus T5, Cartenna T11, Lilybaeum T15,
Thaenae T22, Saldae T28, Sicca T32) against four for Yuezhi at the same point. But the
decisive number isn't cities, it's what went on them: <b>39 improvements to 13 by turn 40</b>,
<b>154 to 67 by turn 80</b>. Roughly eleven worker-built tiles per city versus nine — on
almost twice the cities.</p>
<div class=maps2>
{R.fig('f-carth40', 40, 'omni', 8, 30, 16, "Turn 40, the Carthaginian core: seven cities, 39 finished improvements, a road network already knitting them together.")}
{R.fig('f-yue40', 40, 'omni', 37, 13, 16, "Turn 40, Yuezhi: four cities, 13 improvements. The same forty turns.")}
</div>
</section>

<section>
<h2>3 · The specialist engine, finally</h2>
<p>Specialists went <b>3 : 2 at turn 40 → 13 : 7 at turn 60 → 28 : 11 at turn 80</b>, and
science followed with a lag: level at turn 60 (62 : 64 — Yuezhi actually ahead), then
<b>150.6 : 50.5</b> by turn 80 as the staffed buildings compounded. That late-game
tripling is exactly the curve Lich ran against alcaras in the other game.</p>
<div class=grid3>{ch['specs']}{ch['pop']}{ch['orders_left']}</div>
</section>

<section>
<h2>4 · A war of attrition he could afford</h2>
<p>War was declared turn 10 and the fighting was constant and small: 16 recorded
strikes between the humans, mostly alcaras hunting Steppe Riders (T50, T52, T53 ×2, T73)
and Hazard raiding back — his one clean early success was killing a worker at (18, 24)
on turn 21. Unit losses ran <b>19 : 16</b>, nearly even.</p>
<p>The difference was replacement cost. Military score crossed for good at turn 50
(490 : 420) and then ran away — <b>1,600 : 920 by turn 80</b> — not because alcaras
fought better but because a 4,374-GDP economy re-buys an army that a 283-GDP economy
cannot.</p>
<div class=maps2>
{R.fig('f-war53', 53, 'omni', 14, 26, 18, "Turn 53: three separate strikes on Steppe Riders in one turn (⚔/☠), the attrition phase at its peak.")}
{R.fig('f-end83', 83, 'omni', 20, 20, 26, "Turn 83: the final position — Conquest.")}
</div>
</section>

<section>
<h2>What to keep doing</h2>
<ul>
<li><b>Laws before turn 30.</b> Centralization T8 and Exploration T20 are the whole
divergence. Every other advantage in this game is downstream of the civics engine
starting early and never stalling.</li>
<li><b>Expand, then improve.</b> Seven cities by T32 and eleven improvements each —
width and depth, not one at the other's expense.</li>
<li><b>Trade attrition when you're richer.</b> Even unit losses (19:16) is a winning
trade at 7× GDP; it wouldn't have been at parity.</li>
</ul>
</section>

<section>
<h2>What still needs work</h2>
<ol>
<li><b>Idle workers — 33% of worker-turns</b> ({idle[0][0]}/{idle[0][1]}), essentially
the same as his opponent's 32% and worse than his own 20% in the Lich game. Winning by
economy while wasting a third of the worker-turns means the ceiling was higher still.</li>
<li><b>The turn-42–47 wobble.</b> Military score flipped back to Yuezhi (390 : 410 at
T42, tied 450 at T47) while the economy was already dominant — a lead of that size should
never allow a military crossover. Buy the deterrent earlier.</li>
<li><b>Science idled mid-game.</b> 48.9 → 62.4 across turns 40–60 while GDP nearly
quadrupled. The specialists that produced the turn-80 spike could have been staffed
fifteen turns sooner.</li>
</ol>
</section>

<section class=method>
<h2>Method</h2>
<p>Reconstructed from the complete per-turn cloud-save series (turns 1–83, no gaps).
Each player is sampled at their own end-of-turn. Idle-worker counts exclude workers that
moved during their owner's turn and builds that completed in the post-turn tick.
Science is a validated port of the game's yield engine; GDP is money income plus
food/wood/stone/iron valued at that turn's market price. Every figure is rendered by
the replay engine from the same saves. Full numbers:
<code>analysis/hazard-factsheet.json</code>.</p>
</section>
"""
    R.render(ARCHIVE, OUT, body, R.C0, R.C1,
             title="alcaras v HazardBringsAxe — an 83-turn win")


if __name__ == "__main__":
    main()
