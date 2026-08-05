#!/usr/bin/env python3
"""alcaras v Vova7let (Rome vs Tamilakam, T50) — hollow cities.

Every number cited comes from analysis/vova-factsheet.json.
"""
import json

import report_lib as R

ARCHIVE = "/Users/dominik/Library/CloudStorage/Dropbox/cc/owsaves/mp-archive/alcaras v Vova7let"
OUT = "analysis/alcaras-v-vova7let-report.html"
# Rome vs Tamilakam — validated dark-mode steps
C0, C1 = "#c94b46", "#3987e5"


def main():
    R.setup(ARCHIVE)   # chart colours come from each nation
    M, idle = R.collect()
    F = json.load(open("analysis/vova-factsheet.json"))
    ch = {k: R.chart(f"ch-{k}", t, M[k][0], M[k][1], u) for k, t, u in [
        ("pop", "Population (citizens + specialists)", ""),
        ("imps", "Finished improvements", ""),
        ("specs", "Specialists", ""),
        ("mil", "Military score", ""),
        ("sci", "Science per turn", "🧪/y"),
        ("gdp", "GDP", "gold-equivalent/y"),
        ("cities", "Cities", ""),
        ("workers", "Workers", ""),
        ("laws", "Active laws", ""),
    ]}
    body = f"""
<header>
 <h1>alcaras v Vova7let <span class=res>🏆 Vova7let wins by Conquest, turn 50</span></h1>
 <div class=sub>Rome (<b class=p0>alcaras</b>) vs Tamilakam (<b class=p1>Vova7let</b>),
 50 turns — the shortest game in this library and the least ambiguous. alcaras built as
 many cities and slightly more improvements than his opponent, and lost anyway, because
 <b>his cities were empty</b>: 13 population against 27 when the army arrived.</div>
</header>

<div class=tiles>
 <div class=tile><div class=n>13 : 27</div><div class=l>population at turn 48</div></div>
 <div class=tile><div class=n>57 : 49</div><div class=l>improvements at turn 48 (ahead!)</div></div>
 <div class=tile><div class=n>9 : 17</div><div class=l>specialists at turn 48</div></div>
 <div class=tile><div class=n>310 : 670</div><div class=l>military score at turn 48</div></div>
 <div class=tile><div class=n>0 : 7</div><div class=l>attacks landed on the enemy</div></div>
</div>

<section>
<h2>The one chart that explains the game</h2>
<p>Seven cities each. Improvements level and then slightly ahead for alcaras
(<b>35 : 34 at turn 40</b>, <b>57 : 49 at turn 48</b>). Yet population diverged the whole
way: <b>10 : 13 at turn 30</b>, <b>11 : 19 at turn 40</b>, <b>11 : 25 at turn 45</b>,
<b>13 : 27 at turn 48</b>. Roman cities stopped growing around turn 30 and never restarted —
his population went up by <i>two</i> in eighteen turns while Tamilakam's went up by
fourteen.</p>
<div class=grid3>{ch['pop']}{ch['imps']}{ch['specs']}</div>
<p>Everything downstream follows from that. Specialists (which need citizens to staff)
ran <b>4 : 11</b> at turn 40 and <b>9 : 17</b> at turn 48; science tracked them at
<b>37.1 : 49.7</b> and <b>49.4 : 61.3</b>. The land was developed; there was nobody on it.</p>
</section>

<section>
<h2>1 · The early economy was already behind</h2>
<p>Unusually, alcaras led on <i>military</i> from turn 10 (110 : 40) while trailing on
everything economic: improvements <b>2 : 6</b> at turn 10 and <b>4 : 13</b> at turn 20,
GDP <b>102 : 162</b> then <b>360 : 602</b>. One worker at turn 10 against two, three
against three at turn 20 — he only reached parity around turn 30 and peaked at 15 workers
(to 8) by turn 45, far too late for those tiles to raise citizens.</p>
<div class=grid3>{ch['gdp']}{ch['workers']}{ch['cities']}</div>
<div class=maps2>
{R.fig('f-roma30', 30, 'omni', 40, 15, 17, "Turn 30, the Roman core: seven cities founded, few of them growing.")}
{R.fig('f-tamil30', 30, 'omni', 17, 18, 17, "Turn 30, Tamilakam: six cities, 25 improvements and 5 specialists already working.")}
</div>
</section>

<section>
<h2>2 · Neither player legislated</h2>
<p>Worth calling out because it is so unlike the other games in this library:
<b>alcaras passed two laws all game</b> (Slavery T19, Centralization T47) and
<b>Vova7let passed one</b> (Centralization T20). The civics engine that decided the Lich
and HazardBringsAxe games barely ran here for either side — this was settled on growth
and army alone.</p>
<div class=grid3>{ch['laws']}{ch['sci']}{ch['mil']}</div>
</section>

<section>
<h2>3 · The collapse, turns 45–50</h2>
<p>War was declared on turn 22 and stayed quiet for two dozen turns — one Roman warrior
killed at (22, 23) on turn 29 and nothing else. Then the military score, which had run
close (350 : 450 at turn 45), came apart: <b>310 : 670 by turn 48</b> as Tamilakam's
economy converted and alcaras's did not.</p>
<p>The end came in three turns. Turn 47: a warrior killed at (27, 20). Turn 48: another at
(29, 21), a third damaged at (28, 22). Turn 49: two more killed at (29, 20) and (30, 21).
<b>Six attacks in three turns, four dead warriors, and not a single attack made by
alcaras in the entire game</b> — all seven recorded strikes belong to Vova7let. Surrender
followed on turn 50.</p>
<div class=maps2>
{R.fig('f-t47', 47, 'omni', 28, 21, 14, "Turn 47 — first blood of the final sequence at (27, 20).")}
{R.fig('f-t49', 49, 'omni', 29, 21, 14, "Turn 49 — the line breaks: two more kills at (29, 20) and (30, 21). Surrender the next turn.")}
</div>
</section>

<section>
<h2>What to work on</h2>
<ol>
<li><b>Found fewer cities, or feed the ones you found.</b> Seven cities holding four
citizens between them (turn 48: 13 population of which 9 were specialists) is the whole
game. Growth per city, not city count, is the number to watch.</li>
<li><b>Workers early, not workers eventually.</b> One worker at turn 10 and three at turn
20 meant the improvement lead only arrived at turn 40 — by which point it could no longer
turn into population before the war ended.</li>
<li><b>Convert an early military lead or don't buy it.</b> He led milscore 110 : 40 at
turn 10 and did nothing with it; that army was still parked when it was overtaken at turn
30 and swamped by turn 48. Either press an early lead or spend those resources on growth.</li>
<li><b>Fight back, or don't stand there.</b> Zero attacks landed in fifty turns while
losing four warriors in three. Units that won't attack should be behind walls or
somewhere else.</li>
<li><b>Idle workers, again: {F['idle_worker_turns']['0']['pct']}%</b>
({idle[0][0]}/{idle[0][1]}) versus {F['idle_worker_turns']['1']['pct']}%. Consistent with
the other games — this is the habit with the widest effect across the whole library.</li>
</ol>
</section>

<section class=method>
<h2>Method</h2>
<p>Reconstructed from 49 per-turn cloud saves (turns 2–50, none missing) including the
final surrender save. Each player is sampled at their own end-of-turn. Idle-worker counts
exclude repositioning workers and post-turn build completions. Science is a validated
port of the game's yield engine; GDP is money income plus food/wood/stone/iron at market
prices. Figures are rendered by the replay engine from the same saves. Full numbers:
<code>analysis/vova-factsheet.json</code>.</p>
</section>
"""
    R.render(ARCHIVE, OUT, body, R.C0, R.C1,
             title="alcaras v Vova7let — hollow cities")


if __name__ == "__main__":
    main()
