#!/usr/bin/env python3
"""Build the shareable single-file HTML analysis report for a duel.

Charts: inline SVG, 2 series (alcaras #b8862f, Lich #3987e5 — palette
validated for the dark surface with the dataviz six-checks script), hover
crosshair, direct labels. Map figures: <canvas> rendered client-side by a
trimmed copy of the replay-viewer renderer against the embedded DATA (same
inlining as package_viewer.py), cropped to a turn/POV/center/zoom.

Usage: python3 build_report.py   (expects viewer/data.js + viewer/icons)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from owparse.gamedata import GameData
from owparse.save import series_value_at
from owparse.series import Series
from compare import half_snaps, idle_workers

import os
import sys
ARCHIVE = (sys.argv[1] if len(sys.argv) > 1 else
           os.environ.get("OW_ARCHIVE") or
           sys.exit("usage: build_report.py <archive dir>  (this script is the "
                    "alcaras-v-lich instance; copy it per game, see docs/game-report-method.md)"))
OUT = Path("analysis/alcaras-v-lich-report.html")
# Chart palette: nation hues snapped to dark-mode-validated steps
# (Persia red / Babylonia green; CVD ΔE 7.9 = floor band, legal because
# every chart carries direct labels + hover tooltips). Map figures use the
# authentic in-game nation colors from the embedded data.
from owparse.series import Series as _S
_gd = GameData()
_last = _S(ARCHIVE).snapshot(_S(ARCHIVE).turns[-1])
NAME = {pid: pl.name for pid, pl in _last.players.items()}
C0 = _gd.chart_color(_last.players[0].nation)
C1 = _gd.chart_color(_last.players[1].nation)

# ── metrics ──────────────────────────────────────────────────────────

def collect():
    gd = GameData()
    s = Series(ARCHIVE)
    M = {k: {0: {}, 1: {}} for k in
         ("sci", "mil", "gdp", "imps", "specs", "pop", "workers", "idle",
          "orders_left", "laws", "techs", "cities")}
    idle_tot = {0: [0, 0], 1: [0, 0]}
    for pid in (0, 1):
        for t, cur, prev in half_snaps(s, pid):
            p = cur.players[pid]
            cities = cur.player_cities(pid)
            cid = {c.id for c in cities}
            specs = sum(1 for x in cur.tiles.values() if x.city_territory in cid and x.specialist)
            imps = sum(1 for x in cur.tiles.values() if x.city_territory in cid
                       and x.improvement and x.improvement_turns_left == 0)
            idle, wtot = idle_workers(cur, prev, pid)
            idle_tot[pid][0] += idle
            idle_tot[pid][1] += wtot
            money = series_value_at(p.yield_rate_history.get("YIELD_MONEY", {}), t) or 0
            gdp = money / 10
            for y in ("YIELD_FOOD", "YIELD_WOOD", "YIELD_STONE", "YIELD_IRON"):
                r = series_value_at(p.yield_rate_history.get(y, {}), t)
                pr = series_value_at(cur.yield_price_history.get(y, {}), t)
                if r and pr:
                    gdp += (r / 10) * (pr / 10_000)
            M["sci"][pid][t] = (p.science_rate_at(t) or 0) / 10
            M["mil"][pid][t] = series_value_at(p.military_power_history, t) or 0
            M["gdp"][pid][t] = round(gdp)
            M["imps"][pid][t] = imps
            M["specs"][pid][t] = specs
            M["pop"][pid][t] = sum(c.citizens for c in cities) + specs
            M["workers"][pid][t] = sum(1 for u in cur.player_units(pid) if u.type == "UNIT_WORKER")
            M["idle"][pid][t] = idle
            M["orders_left"][pid][t] = p.yield_stockpile.get("YIELD_ORDERS", 0) / 10
            M["laws"][pid][t] = len(cur.player_roles(pid)["laws"])
            M["techs"][pid][t] = len(p.tech_count)
            M["cities"][pid][t] = len(cities)
    return M, idle_tot


# ── SVG chart ────────────────────────────────────────────────────────

def chart(cid: str, title: str, m0: dict, m1: dict, unit=""):
    turns = sorted(set(m0) | set(m1))
    W, H, PL, PR, PT, PB = 460, 210, 40, 62, 26, 24
    xs = lambda t: PL + (t - turns[0]) / max(1, turns[-1] - turns[0]) * (W - PL - PR)
    vmax = max([v for v in m0.values()] + [v for v in m1.values()] + [1])
    ys = lambda v: PT + (1 - v / vmax) * (H - PT - PB)
    def path(m):
        return " ".join(f"{'M' if i == 0 else 'L'}{xs(t):.1f},{ys(m[t]):.1f}"
                        for i, t in enumerate(sorted(m)))
    grid = ""
    for frac in (0, .5, 1):
        v = vmax * frac
        grid += (f'<line x1="{PL}" x2="{W-PR}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" stroke="#2a2d34" stroke-width="1"/>'
                 f'<text x="{PL-6}" y="{ys(v)+4:.1f}" fill="#9aa1ab" font-size="10" text-anchor="end">{v:g}</text>')
    for t in range(10, turns[-1] + 1, 10):
        grid += f'<text x="{xs(t):.1f}" y="{H-8}" fill="#9aa1ab" font-size="10" text-anchor="middle">{t}</text>'
    endlab = ""
    for m, c, n in ((m0, C0, NAME[0]), (m1, C1, NAME[1])):
        lt = sorted(m)[-1]
        endlab += (f'<text x="{W-PR+5}" y="{ys(m[lt])+4:.1f}" fill="{c}" font-size="11" '
                   f'font-weight="600">{n}</text>')
    data = json.dumps({"turns": turns,
                       "a": [m0.get(t) for t in turns],
                       "b": [m1.get(t) for t in turns]})
    return f"""<figure class=chart>
  <figcaption>{title}{f' <span class=u>({unit})</span>' if unit else ''}</figcaption>
  <svg id="{cid}" viewBox="0 0 {W} {H}" data-c='{data}'>
    {grid}
    <path d="{path(m0)}" fill="none" stroke="{C0}" stroke-width="2" stroke-linejoin="round"/>
    <path d="{path(m1)}" fill="none" stroke="{C1}" stroke-width="2" stroke-linejoin="round"/>
    {endlab}
    <line class=xh x1="0" x2="0" y1="{PT}" y2="{H-PB}" stroke="#dfe2e6" stroke-width="1" opacity="0"/>
  </svg>
</figure>"""


def fig(fid, turn, pov, cx, cy, span, caption, w=560, h=430):
    return (f'<figure class=map><canvas id="{fid}" data-t="{turn}" data-pov="{pov}" '
            f'data-cx="{cx}" data-cy="{cy}" data-span="{span}" width="{w}" height="{h}"></canvas>'
            f'<figcaption>{caption}</figcaption></figure>')


def main():
    M, idle_tot = collect()
    vdir = Path("viewer")
    data_js = (vdir / "data.js").read_text()
    icons = {p.stem: "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
             for p in sorted((vdir / "icons").glob("*.png"))}

    i0 = f"{100*idle_tot[0][0]/max(1,idle_tot[0][1]):.0f}"
    i1 = f"{100*idle_tot[1][0]/max(1,idle_tot[1][1]):.0f}"

    charts = {
        "sci": chart("ch-sci", "Science per turn", M["sci"][0], M["sci"][1], "🧪/y"),
        "mil": chart("ch-mil", "Military score", M["mil"][0], M["mil"][1]),
        "gdp": chart("ch-gdp", "GDP", M["gdp"][0], M["gdp"][1], "gold-equivalent/y"),
        "imps": chart("ch-imps", "Finished improvements", M["imps"][0], M["imps"][1]),
        "specs": chart("ch-specs", "Specialists", M["specs"][0], M["specs"][1]),
        "pop": chart("ch-pop", "Population (citizens + specialists)", M["pop"][0], M["pop"][1]),
        "workers": chart("ch-workers", "Workers", M["workers"][0], M["workers"][1]),
        "laws": chart("ch-laws", "Active laws", M["laws"][0], M["laws"][1]),
        "orders": chart("ch-orders", "Orders left at end of turn", M["orders_left"][0], M["orders_left"][1]),
    }

    body = f"""
<header>
 <h1>alcaras v Lich <span class=res>🏆 Lich wins by Conquest, turn 63</span></h1>
 <div class=sub>A turn-by-turn autopsy of a 63-turn Old World duel — Persia (<b class=p0>alcaras</b>)
 vs Babylonia (<b class=p1>Lich</b>) — reconstructed from all 59 cloud saves.
 The war was declared on turn 9; the first blood was drawn on turn 58. The game was decided
 long before either army moved.</div>
</header>

<div class=tiles>
 <div class=tile><div class=n>5 : 1</div><div class=l>wonders (Lich : alcaras)</div></div>
 <div class=tile><div class=n>10 : 4</div><div class=l>law adoptions</div></div>
 <div class=tile><div class=n>35 : 19</div><div class=l>specialists at the end</div></div>
 <div class=tile><div class=n>{i1}% : {i0}%</div><div class=l>idle worker-turns (Lich : alcaras)</div></div>
 <div class=tile><div class=n>2.6×</div><div class=l>Lich's final science lead</div></div>
</div>

<section>
<h2>How the game was won</h2>
<p>Lich never out-fought alcaras until the final two turns — he out-<i>compounded</i> him.
Three engines, all started before turn 20, produced the 2.6× science lead, the 1.6× GDP lead,
and the doubled army that ended the game: <b>more workers working more of the time</b>,
<b>a specialist economy</b>, and <b>a civics engine that never stopped passing laws</b>.
By the time armies mattered, every military unit Lich bought was cheaper relative to his
economy than alcaras's.</p>
<div class=grid3>{charts['sci']}{charts['gdp']}{charts['mil']}</div>
</section>

<section>
<h2>1 · The worker gap — the first divergence</h2>
<p>The earliest measurable difference is the humblest one. Lich had a second worker by
<b>turn 6</b> and seven by turn 20; alcaras stayed on <b>one worker until turn 16</b>.
By turn 20 the improvement count was <b>19 : 5</b>; it never got closer for the rest of
the game.</p>
<p>Usage compounds the count: across the whole game <b>alcaras left workers idle 20% of
worker-turns ({idle_tot[0][0]}/{idle_tot[0][1]}); Lich 4% ({idle_tot[1][0]}/{idle_tot[1][1]})</b>.
(Measured fairly at each player's own end-of-turn: a worker that finished a build in the
post-turn tick isn't counted against Lich, and a worker walking to its next job isn't
counted against anyone.) alcaras's idleness spiked exactly when he could least afford it —
11–15 of his 20 workers stood idle each turn from 58–62 while Lich's stayed at 0.</p>
<div class=grid3>{charts['workers']}{charts['imps']}<figure class=chart><figcaption>Idle workers by turn</figcaption><svg id="ch-idle" viewBox="0 0 460 210" data-c='{json.dumps({"turns": sorted(set(M["idle"][0]) | set(M["idle"][1])), "a": [M["idle"][0].get(t) for t in sorted(set(M["idle"][0]) | set(M["idle"][1]))], "b": [M["idle"][1].get(t) for t in sorted(set(M["idle"][0]) | set(M["idle"][1]))]})}'>{_idlebars(M)}</svg></figure></div>
<div class=maps2>
{fig('f-lich20', 20, 'omni', 5, 36, 14, "Turn 20, Lich's core: 7 workers, 19 finished improvements, the Pyramids under construction, first specialists already staffed.")}
{fig('f-alc20', 20, 'omni', 40, 7, 14, "Turn 20, alcaras's core: 2 workers, 5 improvements. The same 20 turns, half the hands, half the output.")}
</div>
</section>

<section>
<h2>2 · The specialist engine</h2>
<p>Lich staffed his first specialist on <b>turn 15</b>; alcaras on <b>turn 27</b>. From
there the curves never touch: 9 : 0 at T30, 16 : 5 at T40, 35 : 19 at the end. Decomposing
the science model, specialists (tiers + the Sages' +1-science-per-specialist family bonus)
paid Lich <b>+3.4/turn at T40, +5.4 at T50, +8.5 at T60</b> — versus alcaras's +0.9 / +1.3 /
+3.4. That one line item is most of the total science gap. The Sages per-specialist bonus is
exactly why Babylonia + specialists is an engine and not a garnish.</p>
<p>alcaras's early science actually looked fine — but it was <i>court</i> science
(a Wisdom-5 leader and a Wisdom-5 heir paying +1.5/turn), which is capped and mortal.
Lich's was structural.</p>
<div class=grid3>{charts['specs']}{charts['pop']}{charts['laws']}</div>
<div class=maps2>
{fig('f-babylon40', 40, 'omni', 5, 36, 12, "Turn 40, Babylon: shrines with Master Acolytes, Barracks with Officers, the Hanging Gardens (T38), Archives banked. Every tile does double duty.")}
{fig('f-parsa40', 40, 'omni', 40, 7, 12, "Turn 40, Parsa: solid tiles, few specialists — and the court science that papered over the gap.")}
</div>
</section>

<section>
<h2>3 · Laws: the 25-turn freeze</h2>
<p>Lich adopted laws on turns <b>23, 23, 25, 33, 39, 45, 46, 54, 58, 61</b> — including
the Freedom→Slavery double-swap at 45–46 and the war laws (Divine&nbsp;Rule, Volunteers) timed
for the invasion. alcaras adopted <b>Slavery (25), Centralization (29)… and then nothing for
25 turns</b> until Constitution + Exploration on turn 54. Exploration on turn 23 vs turn 54
is the single starkest strategic difference in the game — a whole engine (expeditions,
ambitions) forfeited for the midgame.</p>
</section>

<section>
<h2>4 · The phony war, then the real one</h2>
<p>War was declared on <b>turn 9</b> and produced no combat between the humans for 49 turns.
Both kept milscore parity at 120 : 120 from turn 28–43 — then Lich's economy started buying
soldiers: 240 by T44, 500 by T52, <b>1090 by T61</b> while alcaras sat at 120 until T47.
alcaras's late surge (460→810 by T62) bought units but not tempo.</p>
<p>The finish was fog-craft: by turn 57 Lich had <b>18 military units staged at (18–20, 23–26)</b>,
seven tiles northwest of Shiraz — outside alcaras's vision. alcaras had 5 defenders there.
He saw the wave only as it crested: 15 defenders crammed into Shiraz by T61, Lich struck on
T62 (killing the Onager on the city tile), Shiraz fell on T63, and the game ended in
concession — recorded as Conquest.</p>
<div class=maps2>
{fig('f-fog-pov', 57, 0, 22, 22, 16, "Turn 57 — what alcaras could see. The northwest is quiet; a screen of fog between him and the truth.")}
{fig('f-fog-omni', 57, 'omni', 22, 22, 16, "Turn 57 — what was actually there: Lich's 18-unit army staged just beyond vision range.")}
</div>
<div class=maps2>
{fig('f-fall', 62, 'omni', 27, 18, 13, "Turn 62 — the assault on Shiraz: ⚔ on the city tile, the Onager dead, six attackers in range.")}
{fig('f-end', 63, 'omni', 27, 18, 13, "Turn 63 — Shiraz has fallen; concession. 🏆 Lich by Conquest.")}
</div>
</section>

<section>
<h2>What alcaras did well</h2>
<ul>
<li><b>Scouting.</b> 1,066 tiles revealed by T20 vs Lich's 535 — twice the map knowledge, all game long.</li>
<li><b>The court.</b> A Wisdom-5 leader, a Wisdom-5+ heir, a Great Scientist courtier — his court out-scienced Lich's court the entire game (≈15 : 3 per turn at T20–40).</li>
<li><b>Early expansion tempo.</b> Third city by T11 (Lich T12), six cities by T24 (Lich 5), and city count parity or better until T49.</li>
<li><b>Religion.</b> Founded Judaism (T42) — a real asset that never got the temple/monastery follow-through.</li>
<li><b>Orders discipline.</b> He spent what he had — near 0 left every turn. (The problem was income, not waste: Lich's orders economy was ~1.7× his by T50, letting Lich bank a 25–50 order war chest for the strike.)</li>
</ul>
</section>

<section>
<h2>What to work on</h2>
<ol>
<li><b>Worker count: match cities.</b> One worker until T16 is the root of the whole material gap. Rule of thumb Lich followed: workers ≥ cities from T6 onward, 2+ per city by the midgame.</li>
<li><b>Worker uptime.</b> 20% idle worker-turns vs 4%. Queue the next job the same turn a build finishes; a worker with nothing to do should be walking somewhere.</li>
<li><b>Start the specialist engine by T15.</b> Civics into specialists beats civics idling. At T40
Lich had all 4 shrines staffed with Acolytes and 6 of 8 Barracks with Officers. This — not
wonders — was most of the 2.6× science gap.</li>
<li><b>Never stop legislating.</b> Three laws from T29–T54 means the civics engine was stalled for half the game. Track law-tech prereqs (Aristocracy → Exploration etc.) as first-class tech goals.</li>
<li><b>Deep, then wide.</b> 8 shallow cities (pop 9 at T38) fed settlers from starving cores. Lich's 6 cities carried nearly double the population before he back-filled to 8.</li>
<li><b>React to milscore divergence.</b> The 240 : 120 moment (T44) was the alarm; the response came at T47–57, into the teeth of a 3× economy.</li>
<li><b>Fight the fog.</b> The staging area sat 7 tiles out for several turns. A scout or cheap unit
parked on the approach corridor (vision range 2–4 from unit.xml) would have bought the 3–4 turns
the defense needed.</li>
</ol>
</section>

<section class=method>
<h2>Method</h2>
<p>Reconstructed from 59 per-turn cloud saves (T1–63; T31–34 missing from the archive).
Saves snapshot the moment alcaras ends his turn, so every metric is sampled at each
player's <i>own</i> end-of-turn (Lich's from the following save). Idle-worker counts
exclude workers that moved during their owner's turn and — for Lich only — workers whose
build completed in the tick after his turn (his builds finish after he acts; alcaras's
before, so his idle workers had a full turn to be reassigned). Science attribution uses a
ported version of the game's own yield engine, validated exactly (±0) against the recorded
per-turn totals through T30 and to ~8% mean error over the full game. Map figures are
rendered by the same code as the interactive replay viewer.</p>
</section>
"""
    html = TEMPLATE.replace("__BODY__", body) \
        .replace("__DATAJS__", data_js) \
        .replace("__ICONS__", json.dumps(icons)) \
        .replace("__C0__", C0).replace("__C1__", C1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"Wrote {OUT} ({OUT.stat().st_size//1024} KB)")


def _idlebars(M):
    turns = sorted(set(M["idle"][0]) | set(M["idle"][1]))
    W, H, PL, PR, PT, PB = 460, 210, 40, 62, 26, 24
    vmax = max(list(M["idle"][0].values()) + list(M["idle"][1].values()) + [1])
    xs = lambda t: PL + (t - turns[0]) / max(1, turns[-1] - turns[0]) * (W - PL - PR)
    ys = lambda v: PT + (1 - v / vmax) * (H - PT - PB)
    out = ""
    for frac in (0, .5, 1):
        v = vmax * frac
        out += (f'<line x1="{PL}" x2="{W-PR}" y1="{ys(v):.1f}" y2="{ys(v):.1f}" stroke="#2a2d34"/>'
                f'<text x="{PL-6}" y="{ys(v)+4:.1f}" fill="#9aa1ab" font-size="10" text-anchor="end">{v:g}</text>')
    for t in range(10, turns[-1] + 1, 10):
        out += f'<text x="{xs(t):.1f}" y="{H-8}" fill="#9aa1ab" font-size="10" text-anchor="middle">{t}</text>'
    bw = max(2, (460 - PL - PR) / max(1, len(turns)) / 2 - 1)
    for t in turns:
        a, b = M["idle"][0].get(t, 0), M["idle"][1].get(t, 0)
        if a:
            out += f'<rect x="{xs(t)-bw:.1f}" y="{ys(a):.1f}" width="{bw:.1f}" height="{ys(0)-ys(a):.1f}" fill="{C0}" rx="1.5"/>'
        if b:
            out += f'<rect x="{xs(t)+1:.1f}" y="{ys(b):.1f}" width="{bw:.1f}" height="{ys(0)-ys(b):.1f}" fill="{C1}" rx="1.5"/>'
    out += (f'<text x="{460-PR+5}" y="{PT+10}" fill="{C0}" font-size="11" font-weight="600">alcaras</text>'
            f'<text x="{460-PR+5}" y="{PT+24}" fill="{C1}" font-size="11" font-weight="600">Lich</text>')
    return out


TEMPLATE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>alcaras v Lich — a 63-turn autopsy</title>
<style>
 body{margin:0;background:#0b0c0f;color:#dfe2e6;font:15px/1.6 system-ui;-webkit-font-smoothing:antialiased}
 header{padding:34px 26px 10px;max-width:1060px;margin:0 auto}
 h1{margin:0;font-size:26px;color:#fff}
 h1 .res{display:block;font-size:15px;color:#ffd27a;margin-top:6px}
 .sub{color:#9aa1ab;margin-top:10px;max-width:74ch}
 .p0{color:__C0__}.p1{color:__C1__}
 section{max-width:1060px;margin:0 auto;padding:10px 26px 6px}
 h2{color:#ffd27a;font-size:18px;border-bottom:1px solid #2a2d34;padding-bottom:6px;margin:26px 0 12px}
 p,li{max-width:80ch}
 .tiles{display:flex;gap:10px;flex-wrap:wrap;max-width:1060px;margin:14px auto 0;padding:0 26px}
 .tile{background:#15171c;border:1px solid #2a2d34;border-radius:10px;padding:12px 18px;min-width:130px}
 .tile .n{font-size:22px;font-weight:700;color:#fff}
 .tile .l{font-size:12px;color:#9aa1ab;margin-top:2px}
 .grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin:12px 0}
 figure{margin:0;background:#15171c;border:1px solid #2a2d34;border-radius:10px;padding:10px}
 figure.chart figcaption{font-size:13px;color:#dfe2e6;font-weight:600;margin-bottom:4px}
 figure.chart .u{color:#9aa1ab;font-weight:400}
 svg{width:100%;height:auto;display:block}
 .maps2{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px;margin:12px 0}
 figure.map canvas{width:100%;height:auto;border-radius:6px;background:#0b0c0f;display:block}
 figure.map figcaption{font-size:12.5px;color:#9aa1ab;margin-top:8px;line-height:1.5}
 .method p{color:#9aa1ab;font-size:13px}
 .disclaimer{max-width:1060px;margin:16px auto 0;padding:12px 16px;
   background:#2a1f14;border:1px solid #6b4a1f;border-radius:8px;
   color:#e8c9a0;font-size:13px;line-height:1.55}
 .disclaimer b{color:#ffd27a}
 #tip{position:fixed;display:none;background:#0e1014ee;border:1px solid #3a3d44;border-radius:6px;
   padding:6px 9px;font-size:12px;pointer-events:none;z-index:9}
 #tip b{color:#ffd27a}
</style></head><body>
<div class=disclaimer><b>⚠ Machine-generated analysis — expect errors.</b>
This report was written by Claude (an AI) from data extracted out of the game's
save files. The extraction itself is validated against the game's own recorded
numbers, but the <i>interpretation</i> — what mattered, what caused what, what
either player should have done — is a machine's reading of a spreadsheet, not a
strong player's judgement. Causal claims are inference, some derived numbers are
approximations (noted in Method), and outright mistakes are likely. Treat it as a
prompt for your own analysis, not a verdict.</div>
__BODY__
<div id=tip></div>
<script>const ICON_DATA=__ICONS__;</script>
<script>__DATAJS__</script>
<script>
// ── chart hover (crosshair + tooltip) ────────────────────────────────
const tip=document.getElementById('tip');
document.querySelectorAll('svg[data-c]').forEach(svg=>{
 const d=JSON.parse(svg.dataset.c),xh=svg.querySelector('.xh');
 svg.addEventListener('mousemove',e=>{
  const r=svg.getBoundingClientRect(),W=460,PL=40,PR=62;
  const px=(e.clientX-r.left)/r.width*W;
  const f=(px-PL)/(W-PL-PR);
  const i=Math.max(0,Math.min(d.turns.length-1,Math.round(f*(d.turns.length-1))));
  const t=d.turns[i];
  if(xh){const x=PL+(t-d.turns[0])/(d.turns[d.turns.length-1]-d.turns[0])*(W-PL-PR);
   xh.setAttribute('x1',x);xh.setAttribute('x2',x);xh.setAttribute('opacity',.4);}
  tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+10)+'px';
  tip.innerHTML=`<b>T${t}</b> <span style="color:__C0__">alcaras ${d.a[i]??'–'}</span> · <span style="color:__C1__">Lich ${d.b[i]??'–'}</span>`;});
 svg.addEventListener('mouseleave',()=>{tip.style.display='none';if(xh)xh.setAttribute('opacity',0);});});

// ── map figures: trimmed replay renderer ─────────────────────────────
const D=DATA,W=D.w,H=D.h;
function hex2rgb(h){h=(h||'#888888').replace('#','');
 return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)];}
const PCOL={'-1':[140,132,120]};
for(const pid in D.players)PCOL[pid]=hex2rgb(D.players[pid].color);
const TERR={WATER:[38,71,110],TEMPERATE:[104,138,74],LUSH:[74,110,56],ARID:[170,148,95],
 SAND:[206,184,120],MARSH:[96,110,80],TUNDRA:[200,205,210],URBAN:[150,128,116]};
const S=26,HW=Math.sqrt(3)*S,VS=1.5*S;
function cen(x,y){return [x*HW+(y%2===0?HW/2:0)+HW/2,(H-1-y)*VS+S];}
const DXe=[0,1,1,1,0,-1],DXo=[-1,0,1,0,-1,-1],DY=[1,1,0,-1,-1,0];
function nbIdx(x,y){const o=[];for(let q=0;q<6;q++){const nx=x+(y%2===0?DXe:DXo)[q],ny=y+DY[q];
 if(nx>=0&&ny>=0&&nx<W&&ny<H)o.push([nx,ny,ny*W+nx]);}return o;}
function lum(c){return .299*c[0]+.587*c[1]+.114*c[2];}
// Preload EVERY embedded icon up front; draw once all have decoded (and
// once immediately so text/terrain shows even before). A lazy-load scheme
// here left figures with colored dots when late/failed decodes never
// triggered the redraw.
const icons={};
function icon(n){return icons[n]||null;}
const iconsReady=Promise.all(Object.entries(ICON_DATA).map(([n,src])=>
 new Promise(res=>{const im=new Image();
  im.onload=()=>{icons[n]=im;res();};
  im.onerror=()=>{icons[n]=null;res();};
  im.src=src;})));
function tidx(turn){return D.turns.findIndex(td=>td.t==turn);}
function drawFig(cv){
 const T=+cv.dataset.t,pov=cv.dataset.pov,cx=+cv.dataset.cx,cy=+cv.dataset.cy,span=+cv.dataset.span;
 const TD=D.turns[tidx(T)];if(!TD)return;
 const omni=pov==='omni',pp=omni?0:+pov;
 const ctx=cv.getContext('2d');
 const k=cv.width/(span*HW);
 const c0=cen(cx,cy);
 ctx.setTransform(k,0,0,k,cv.width/2-c0[0]*k,cv.height/2-c0[1]*k);
 ctx.fillStyle='#0b0c0f';ctx.fillRect(c0[0]-cv.width/k,c0[1]-cv.height/k,cv.width*2/k,cv.height*2/k);
 const tiles=TD.tiles,visSet=new Set((TD.vis&&TD.vis[pp])||[]);
 const fogged=i=>{if(omni)return false;const r=D.rev[pp][i];return r<0||r>T;};
 const dim=i=>!omni&&!visSet.has(i);
 function hexp(x,y,r){ctx.beginPath();for(let q=0;q<6;q++){const a=Math.PI/180*(60*q-90);
  const px=x+r*Math.cos(a),py=y+r*Math.sin(a);q?ctx.lineTo(px,py):ctx.moveTo(px,py);}ctx.closePath();}
 for(let i=0;i<W*H;i++){const x=i%W,y=(i/W)|0;
  const tn=D.L.terr[D.terr[i]]||'',hh=D.L.hgt[D.hgt[i]]||'',vg=D.L.veg[D.veg[i]]||'';
  let c,water=false;
  if(tn==='WATER'||hh.indexOf('LAKE')>=0){water=true;c=hh.indexOf('LAKE')>=0?[40,118,124]:[26,52,92];}
  else c=(TERR[tn]||[90,90,90]).slice();
  const fg=fogged(i);
  if(fg){const g=lum(c)*0.3;c=[g,g,g];}
  else if(hh.indexOf('MOUNTAIN')>=0||hh.indexOf('VOLCANO')>=0){const b=lum(c)*0.6+26;c=[b,b,b+3];}
  if(!fg&&dim(i)){const g=lum(c);c=[(c[0]+g)*0.33,(c[1]+g)*0.33,(c[2]+g)*0.33];}
  const ce=cen(x,y);
  ctx.fillStyle=`rgb(${c[0]|0},${c[1]|0},${c[2]|0})`;hexp(ce[0],ce[1],S);ctx.fill();
  if(fg||water)continue;
  if(hh.indexOf('HILL')>=0){ctx.save();hexp(ce[0],ce[1],S);ctx.clip();
   ctx.fillStyle='rgba(255,255,255,.14)';ctx.fillRect(ce[0]-S,ce[1]-S,2*S,S*.85);
   ctx.fillStyle='rgba(0,0,0,.26)';ctx.fillRect(ce[0]-S,ce[1]+S*.05,2*S,S);ctx.restore();}
  const fr=vg.indexOf('TREE')>=0||vg.indexOf('FOREST')>=0||vg.indexOf('JUNGLE')>=0;
  if(fr){const nt=2,tw=S*.26,th=S*.6,yb=ce[1]+S*.22;
   for(let kk=0;kk<nt;kk++){const X=ce[0]+(kk-(nt-1)/2)*tw*1.3;
    ctx.fillStyle='rgba(60,40,20,.9)';ctx.fillRect(X-tw*.15,yb-th*.18,tw*.3,th*.34);
    ctx.fillStyle='rgba(24,68,26,.95)';ctx.beginPath();ctx.moveTo(X,yb-th);
    ctx.lineTo(X-tw,yb);ctx.lineTo(X+tw,yb);ctx.closePath();ctx.fill();}}}
 ctx.strokeStyle='#4696eb';ctx.lineWidth=Math.max(2,S/4);
 const RB={1:5,2:4,4:3};
 for(let i=0;i<W*H;i++){if(!D.riv[i])continue;
  const x=i%W,y=(i/W)|0,ce=cen(x,y);
  for(const bit in RB){if(!(D.riv[i]&bit))continue;
   const di=RB[bit],ox=(y%2===0?DXe:DXo)[di],nx=x+ox,ny=y+DY[di];
   if(nx<0||ny<0||nx>=W||ny>=H)continue;
   if(fogged(i)&&fogged(ny*W+nx))continue;
   const nc=cen(nx,ny),mx=(ce[0]+nc[0])/2,my=(ce[1]+nc[1])/2,
    dx=nc[0]-ce[0],dy=nc[1]-ce[1],L=Math.hypot(dx,dy)||1,hl=S/Math.sqrt(3)*.96;
   ctx.beginPath();ctx.moveTo(mx-(-dy/L)*hl,my-(dx/L)*hl);ctx.lineTo(mx+(-dy/L)*hl,my+(dx/L)*hl);ctx.stroke();}}
 for(const[id,e]of Object.entries(tiles)){const i=+id;
  if(e.o==null||fogged(i))continue;
  const ce=cen(i%W,(i/W)|0),pc=PCOL[e.o]||[120,120,120];
  ctx.fillStyle=`rgba(${pc[0]},${pc[1]},${pc[2]},.16)`;hexp(ce[0],ce[1],S);ctx.fill();
  ctx.strokeStyle=`rgba(${pc[0]},${pc[1]},${pc[2]},.8)`;ctx.lineWidth=1.4;
  for(const[nx,ny,nid]of nbIdx(i%W,(i/W)|0)){const ne=tiles[nid];
   if(ne&&ne.o===e.o)continue;
   const b=cen(nx,ny),mx=(ce[0]+b[0])/2,my=(ce[1]+b[1])/2,
    dx=b[0]-ce[0],dy=b[1]-ce[1],L=Math.hypot(dx,dy)||1,hl=S/Math.sqrt(3);
   ctx.beginPath();ctx.moveTo(mx-(-dy/L)*hl,my-(dx/L)*hl);ctx.lineTo(mx+(-dy/L)*hl,my+(dx/L)*hl);ctx.stroke();}}
 // roads: half-segments from both sides; cities are road nodes
 ctx.strokeStyle='rgba(160,120,70,.9)';ctx.lineWidth=Math.max(2,S/6);ctx.lineCap='round';
 const cityTiles=new Set(TD.cities.map(c=>c.x));
 const isRoad=nid=>{const e=tiles[nid];return (e&&e.r)||cityTiles.has(nid);};
 for(const[id,e]of Object.entries(tiles)){const i=+id;
  if(!isRoad(i)||fogged(i))continue;
  const x=i%W,y=(i/W)|0,ce=cen(x,y);
  for(const[nx,ny,nid]of nbIdx(x,y)){
   if(!isRoad(nid))continue;
   const b=cen(nx,ny);ctx.beginPath();ctx.moveTo(ce[0],ce[1]);
   ctx.lineTo((ce[0]+b[0])/2,(ce[1]+b[1])/2);ctx.stroke();}}
 ctx.lineCap='butt';
 for(const[id,e]of Object.entries(tiles)){const i=+id;
  if(fogged(i))continue;
  const ce=cen(i%W,(i/W)|0);
  if(e.i){const im=icon(e.i);
   if(im&&im.complete&&im.naturalWidth){ctx.globalAlpha=e.b?0.45:1;
    ctx.drawImage(im,ce[0]-S*.55,ce[1]-S*.55,S*1.1,S*1.1);ctx.globalAlpha=1;}}}
 for(const pid in (TD.attacks||{}))for(const a of TD.attacks[pid]){
  if(fogged(a.x))continue;
  const ce=cen(a.x%W,(a.x/W)|0);
  ctx.strokeStyle=a.k?'#ff5040':'#ffb020';ctx.lineWidth=2.6;
  hexp(ce[0],ce[1],S*.92);ctx.stroke();
  ctx.fillStyle=a.k?'#ff5040':'#ffb020';ctx.font=`${S*.9}px system-ui`;ctx.textAlign='center';
  ctx.fillText(a.k?'☠':'⚔',ce[0],ce[1]-S*.55);}
 for(const u of TD.units){
  if(fogged(u.x))continue;
  if(!omni&&u.p!=pp&&!visSet.has(u.x))continue;
  const ce=cen(u.x%W,(u.x/W)|0),pc=PCOL[u.p]||PCOL['-1'];
  ctx.fillStyle=`rgb(${pc[0]},${pc[1]},${pc[2]})`;
  ctx.beginPath();ctx.arc(ce[0],ce[1]+S*.24,S*.52,0,7);ctx.fill();
  ctx.strokeStyle='#0b0c0f';ctx.lineWidth=1.4;ctx.stroke();
  const im=icon(u.t);
  if(im&&im.complete&&im.naturalWidth)ctx.drawImage(im,ce[0]-S*.4,ce[1]-S*.16,S*.8,S*.8);
  if(u.hp<u.mhp){ // OW-style pips: 2 HP per tick, odd HP = half tick
   const mhp=u.mhp,hp=u.hp,ticks=Math.ceil(mhp/2),w=S*1.05,h=S*0.3,tw=w/ticks;
   const cy2=ce[1]+S*.8,frac=hp/mhp,
    col=frac>2/3?'#00cf00':frac>1/3?'#f7ff54':'#ffaa54';
   ctx.fillStyle='#000';ctx.fillRect(ce[0]-w/2-1,cy2-1,w+2,h+2);
   ctx.fillStyle='#353535';ctx.fillRect(ce[0]-w/2,cy2,w,h);
   for(let q=0;q<ticks;q++){
    const tickHP=Math.max(0,Math.min(2,hp-q*2));
    if(!tickHP)continue;
    const x=ce[0]-w/2+q*tw;
    ctx.fillStyle=col;
    if(tickHP>=2)ctx.fillRect(x+0.5,cy2+0.5,tw-1,h-1);
    else ctx.fillRect(x+0.5,cy2+h/2,tw-1,h/2-0.5);}}}
 for(const c of TD.cities){
  if(fogged(c.x))continue;
  const ce=cen(c.x%W,(c.x/W)|0),pc=PCOL[c.p]||PCOL['-1'];
  const im=icon('crest_'+c.crest);
  ctx.fillStyle=`rgb(${pc[0]},${pc[1]},${pc[2]})`;
  ctx.beginPath();ctx.arc(ce[0],ce[1]-S*.28,S*.5,0,7);ctx.fill();
  ctx.strokeStyle='#0b0c0f';ctx.lineWidth=1.4;ctx.stroke();
  if(im&&im.complete&&im.naturalWidth)ctx.drawImage(im,ce[0]-S*.34,ce[1]-S*.62,S*.68,S*.68);
  ctx.font=`bold ${S*.6}px system-ui`;ctx.textAlign='center';
  ctx.lineWidth=3.4;ctx.strokeStyle='#0b0c0fcc';
  ctx.strokeText(c.n,ce[0],ce[1]+S*1.32);
  ctx.fillStyle='#fff';ctx.fillText(c.n,ce[0],ce[1]+S*1.32);}
}
function drawFigs(){document.querySelectorAll('canvas[data-t]').forEach(drawFig);}
drawFigs();
iconsReady.then(drawFigs);
window.addEventListener('load',drawFigs);
</script></body></html>"""


if __name__ == "__main__":
    main()
