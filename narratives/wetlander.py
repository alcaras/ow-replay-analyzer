#!/usr/bin/env python3
"""alcaras v Wetlander (Persia vs Hittite, T103) — winning the war while
losing the science race.

Every number cited comes from analysis/wetlander-factsheet.json.
"""
import json

import report_lib as R

ARCHIVE = "/Users/dominik/Library/CloudStorage/Dropbox/cc/owsaves/mp-archive/alcaras v Wetlander"
OUT = "analysis/alcaras-v-wetlander-report.html"
# Persia vs Hittite — validated dark-mode steps
C0, C1 = "#c94b46", "#69a832"


def main():
    M, idle = R.collect()
    F = json.load(open("analysis/wetlander-factsheet.json"))
    ch = {k: R.chart(f"ch-{k}", t, M[k][0], M[k][1], u) for k, t, u in [
        ("sci", "Science per turn", "🧪/y"),
        ("gdp", "GDP", "gold-equivalent/y"),
        ("mil", "Military score", ""),
        ("imps", "Finished improvements", ""),
        ("specs", "Specialists", ""),
        ("workers", "Workers", ""),
        ("cities", "Cities", ""),
        ("laws", "Active laws", ""),
        ("pop", "Population", ""),
    ]}
    body = f"""
<header>
 <h1>alcaras v Wetlander <span class=res>🏆 alcaras wins by Conquest, turn 103</span></h1>
 <div class=sub>Persia (<b class=p0>alcaras</b>) vs Hittites (<b class=p1>Wetlander</b>),
 103 turns. The most interesting of the three duels in this library, because
 <b>alcaras lost the science race and won anyway</b> — Wetlander was still out-researching
 him 215.6 : 182.3 on turn 100, three turns before his capital fell.</div>
</header>

<div class=tiles>
 <div class=tile><div class=n>247 : 115</div><div class=l>improvements at turn 100</div></div>
 <div class=tile><div class=n>10 : 6</div><div class=l>cities at turn 100</div></div>
 <div class=tile><div class=n>2.0×</div><div class=l>GDP at turn 100</div></div>
 <div class=tile><div class=n>16% : 27%</div><div class=l>idle worker-turns</div></div>
 <div class=tile><div class=n>0.85×</div><div class=l>science at turn 100 (behind)</div></div>
</div>

<section>
<h2>Losing the metric, winning the game</h2>
<p>Science ran level for sixty turns, then Wetlander pulled clear: <b>165.5 : 116.1 at
turn 80</b>, still <b>215.6 : 182.3 at turn 100</b>. On the usual scoreboard that is a
losing position. It didn't matter, because the two things science does not directly buy —
<b>worked land</b> and <b>bodies in the field</b> — were both running two to one the other
way.</p>
<div class=grid3>{ch['sci']}{ch['imps']}{ch['mil']}</div>
<p>The lesson isn't that science is unimportant; it's that a research lead has to be
<i>converted</i> before the map settles the argument. Wetlander's never was.</p>
</section>

<section>
<h2>1 · The improvement engine (and the worker discipline behind it)</h2>
<p>Improvements ran level to turn 40 (30 : 31), then diverged permanently:
<b>101 : 52 at turn 60</b>, <b>196 : 112 at turn 80</b>, <b>247 : 115 at turn 100</b>.
The mechanism is visible in the worker curves — alcaras reached 17 workers by turn 60 and
held them there, while Wetlander sat at 9 and only caught up at turn 80, far too late for
the tiles to mature.</p>
<p>Usage backs the count: <b>alcaras idled {F['idle_worker_turns']['0']['pct']}% of
worker-turns ({idle[0][0]}/{idle[0][1]}), Wetlander {F['idle_worker_turns']['1']['pct']}%
({idle[1][0]}/{idle[1][1]})</b> — the reverse of the Lich game, where alcaras was the
wasteful one at 20%.</p>
<div class=grid3>{ch['workers']}{ch['gdp']}{ch['specs']}</div>
<div class=maps2>
{R.fig('f-persia60', 60, 'omni', 12, 30, 18, "Turn 60, Persia: eight cities, 101 finished improvements, roads linking the core.")}
{R.fig('f-hitt60', 60, 'omni', 34, 14, 18, "Turn 60, the Hittites: eight cities, 52 improvements — half the built-out land on the same city count.")}
</div>
</section>

<section>
<h2>2 · The turn-45 scare</h2>
<p>This game was not a procession. Wetlander led military score for most of the midgame
and peaked at <b>240 : 360 on turn 45</b> — a 1.5× army advantage against a player whose
economy had only just retaken the GDP lead (turn 48). Wetlander also led GDP outright
from turn 35 to 47.</p>
<p>alcaras's answer was not a counter-army but more land: cities at turns 26, 29, 35, 37
and 42 (Teredon, Hyrba, Anshan, Tuwanuwa, Cyreschate) while the front stayed quiet. By
turn 65 the military score had flipped for good (1,080 : 1,020) and never flipped back.</p>
<div class=grid3>{ch['cities']}{ch['pop']}{ch['laws']}</div>
</section>

<section>
<h2>3 · The offensive: turn 84</h2>
<p>Contact was sporadic for eighty turns — a scout killed on turn 50, a Heavy Chariot on
turn 58 — and then, on <b>turn 84, five strikes in a single turn</b>: axemen at (40, 28),
(38, 31) and (38, 32), a slinger at (39, 30), a worker cut down at (37, 31). The next
turn took another worker at (40, 16) and hit a camel archer.</p>
<p>Total losses tell the story of the endgame: <b>33 : 49</b>. alcaras lost a third of an
army; Wetlander lost half of his and his land with it — city count went <b>10 : 6</b> as
Hittite cities changed hands.</p>
<div class=maps2>
{R.fig('f-t84', 84, 'omni', 38, 30, 15, "Turn 84 — the offensive opens: five strikes in one turn along the (37–40, 28–32) front.")}
{R.fig('f-t103', 103, 'omni', 30, 20, 26, "Turn 103 — Conquest. The Hittite position has collapsed from eight cities to six, with the rest taken.")}
</div>
</section>

<section>
<h2>What worked</h2>
<ul>
<li><b>Worker uptime (16% idle).</b> The single biggest improvement over the Lich game,
and it produced the 2× improvement lead that the whole win rests on.</li>
<li><b>Answering an army with expansion.</b> Five cities founded between turns 26 and 42
while trailing on milscore — the land paid for the army that arrived later.</li>
<li><b>Concentration.</b> Eighty turns of near-zero contact, then five strikes in one
turn. Attrition on a single front beats trickling units forward.</li>
</ul>
</section>

<section>
<h2>What to work on</h2>
<ol>
<li><b>Convert the economy into science.</b> Double the GDP and double the improvements
should not mean a losing research rate. The specialist counts were level (34 : 34 at
turn 100) — with twice the land, they shouldn't have been.</li>
<li><b>The turn-35–47 dip.</b> GDP lead lost for twelve turns and milscore down 240 : 360.
It resolved, but it was the one window where a decisive Hittite attack could have ended it.</li>
<li><b>Law tempo, again.</b> Slavery T19 was good; Exploration T32 and Centralization T36
were not. Wetlander matched him law-for-law all game — nothing here was won on civics.</li>
</ol>
</section>

<section class=method>
<h2>Method</h2>
<p>Reconstructed from 99 per-turn cloud saves (turns 1–103, five missing) plus the final
surrender save. Each player is sampled at their own end-of-turn; idle-worker counts
exclude repositioning workers and post-turn build completions. Science is a validated
port of the game's yield engine; GDP is money plus commodity income at market prices.
Figures are rendered by the replay engine from the same saves. Full numbers:
<code>analysis/wetlander-factsheet.json</code>.</p>
</section>
"""
    R.render(ARCHIVE, OUT, body, C0, C1,
             title="alcaras v Wetlander — winning without the science lead")


if __name__ == "__main__":
    main()
