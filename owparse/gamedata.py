"""Game reference data loaded from the Old World install (Reference/XML/Infos).

Everything here is *rules* data — names, costs, prereqs — keyed by the same
zType tokens the save XML uses (TECH_STONECUTTING, UNIT_SETTLER, ...).
Values keep the game's native units: iCost/iProduction are display units;
save-file progress values are these ×10 (Constants.YIELDS_MULTIPLIER).
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from functools import cached_property
from pathlib import Path

STEAM_REFERENCE = Path.home() / (
    "Library/Application Support/Steam/steamapps/common/Old World/Reference"
)
YIELDS_MULTIPLIER = 10  # Constants.cs: save-file yield values are ×10


def _entries(path: Path):
    """Yield <Entry> elements of an Infos xml file (missing file → nothing)."""
    if not path.exists():
        return
    for e in ET.parse(path).getroot().findall("Entry"):
        if e.findtext("zType"):
            yield e


class GameData:
    def __init__(self, reference: Path | str | None = None):
        self.reference = Path(reference or os.environ.get("OW_REFERENCE", STEAM_REFERENCE))
        self.infos = self.reference / "XML" / "Infos"
        if not self.infos.is_dir():
            raise FileNotFoundError(f"Old World Infos dir not found: {self.infos}")

    def _merged(self, base: str) -> dict[str, ET.Element]:
        """zType→Entry for base.xml plus any base-*.xml DLC overlay files."""
        out: dict[str, ET.Element] = {}
        for p in sorted(self.infos.glob(f"{base}.xml")) + sorted(self.infos.glob(f"{base}-*.xml")):
            for e in _entries(p):
                out[e.findtext("zType")] = e
        return out

    # ── text resolution ──────────────────────────────────────────────
    @cached_property
    def _text(self) -> dict[str, str]:
        """TEXT_* token → en-US display string, from every text*.xml file."""
        out: dict[str, str] = {}
        for p in self.infos.glob("text*.xml"):
            try:
                root = ET.parse(p).getroot()
            except ET.ParseError:
                continue
            for e in root:
                z, v = e.findtext("zType"), e.findtext("en-US")
                if z and v:
                    out[z] = v.strip()
        return out

    _LINKRE = None  # set lazily to avoid import-order noise

    def _first_form(self, s: str) -> str:
        """OW text values pack grammar variants: 'Settler~a Settler~Settlers'
        or gendered 'X|Y', and may embed link(TOKEN) references. Take the
        base form and resolve links to display names."""
        import re
        s = s.split("~")[0].split("|")[0].strip()
        def sub(m):
            inner = m.group(1).split(",")[-1].strip()
            v = self._text.get("TEXT_" + inner) or self._text.get(inner)
            return v.split("~")[0].split("|")[0].strip() if v else inner
        return re.sub(r"link\(([^)]*)\)", sub, s)

    def text(self, token: str) -> str | None:
        v = self._text.get(token)
        return self._first_form(v) if v else None

    def name(self, ztype: str) -> str:
        """Display name for any zType token (tech/unit/improvement/... or
        CITYNAME_/NAME_ tokens). Falls back to a humanized token."""
        if not ztype or ztype == "NONE":
            return ""
        e = self._all_entries.get(ztype)
        if e is not None:
            v = self._text.get(e.findtext("Name") or "")
            if v and "{" not in v:      # skip parameterized templates
                return self._first_form(v)
        v = self._text.get("TEXT_" + ztype)
        if v and "{" not in v:
            return self._first_form(v)
        for pre in ("TECH_", "UNIT_", "IMPROVEMENT_", "PROJECT_", "SPECIALIST_",
                    "FAMILY_", "FAMILYCLASS_", "CITYNAME_", "NAME_", "PROMOTION_",
                    "LAW_", "RESOURCE_", "YIELD_", "TRIBE_", "NATION_"):
            if ztype.startswith(pre):
                ztype = ztype[len(pre):]
                break
        return ztype.replace("_", " ").title()

    # ── typed tables ─────────────────────────────────────────────────
    @cached_property
    def _all_entries(self) -> dict[str, ET.Element]:
        out: dict[str, ET.Element] = {}
        for base in ("tech", "unit", "improvement", "project", "specialist",
                     "family", "familyClass", "promotion", "law", "resource",
                     "yield", "nation", "tribe", "bonus", "cityName"):
            out.update(self._merged(base))
        return out

    @cached_property
    def techs(self) -> dict[str, dict]:
        out = {}
        for z, e in self._merged("tech").items():
            out[z] = {
                "cost": int(e.findtext("iCost") or 0),
                "hide": e.findtext("bHide") == "1",
                "trash": e.findtext("bTrash") == "1",
            }
        return out

    @cached_property
    def units(self) -> dict[str, dict]:
        out = {}
        for z, e in self._merged("unit").items():
            out[z] = {
                "cost": int(e.findtext("iProduction") or 0),
                "prod_per": int(e.findtext("iProductionPer") or 0),      # per unit produced by player this game
                "prod_city": int(e.findtext("iProductionCity") or 0),    # per unit produced by this city
                "prod_yield": e.findtext("ProductionType") or "",
                "movement": int(e.findtext("iMovement") or 0),
                "vision": int(e.findtext("iVision") or 0),
                "fatigue": int(e.findtext("iFatigue") or 0),
                "strength": int(e.findtext("iStrength") or 0),
                "hp": int(e.findtext("iHPMax") or 20),
                "traits": [t.text for t in e.findall("aeUnitTrait/zValue")],
            }
        return out

    @cached_property
    def projects(self) -> dict[str, dict]:
        return {z: {"cost": int(e.findtext("iCost") or 0),
                    "prod_yield": e.findtext("ProductionType") or ""}
                for z, e in self._merged("project").items()}

    @cached_property
    def specialists(self) -> dict[str, dict]:
        # Specialists are trained with civics (iCivics) or training (iTraining).
        out = {}
        for z, e in self._merged("specialist").items():
            civics = int(e.findtext("iCivics") or 0)
            training = int(e.findtext("iTraining") or 0)
            out[z] = {
                "cost": civics or training,
                "prod_yield": "YIELD_CIVICS" if civics else "YIELD_TRAINING",
            }
        return out

    @cached_property
    def improvements(self) -> dict[str, dict]:
        return {z: {"build_turns": int(e.findtext("iBuildTurns") or 0)}
                for z, e in self._merged("improvement").items()}

    @cached_property
    def improvement_outputs(self) -> dict[str, dict[str, int]]:
        """improvement → {yield: base per-turn output} (aiYieldOutput)."""
        out = {}
        for z, e in self._merged("improvement").items():
            d = {}
            el = e.find("aiYieldOutput")
            if el is not None:
                for p in el.findall("Pair"):
                    k, v = p.findtext("zIndex"), int(p.findtext("iValue") or 0)
                    if k and v:
                        d[k] = v
            if d:
                out[z] = d
        return out

    @cached_property
    def improvement_class_of(self) -> dict[str, str]:
        return {z: (e.findtext("ImprovementClass") or "")
                for z, e in self._merged("improvement").items()}

    @cached_property
    def class_resource_outputs(self) -> dict[str, dict[str, dict[str, int]]]:
        """improvement class → resource → {yield: output} (mines on iron etc.)."""
        out = {}
        for z, e in self._merged("improvementClass").items():
            ary = e.find("aaiResourceYieldOutput")
            if ary is None:
                continue
            res = {}
            for p in ary.findall("Pair"):
                r = p.findtext("zIndex")
                d = {}
                for sp in p.findall("SubPair"):
                    k, v = sp.findtext("zSubIndex"), int(sp.findtext("iValue") or 0)
                    if k and v:
                        d[k] = v
                if r and d:
                    res[r] = d
            if res:
                out[z] = res
        return out

    @cached_property
    def families(self) -> dict[str, dict]:
        fc = {z: self.name(z) for z in self._merged("familyClass")}
        out = {}
        for z, e in self._merged("family").items():
            cls = e.findtext("FamilyClass") or ""
            out[z] = {"class": cls, "class_name": fc.get(cls, cls),
                      "name": self.name(z)}
        return out

    @cached_property
    def event_stories(self) -> dict[str, dict]:
        """EVENTSTORY_* → {title, options[]} (title resolved to display text)."""
        out = {}
        for z, e in self._merged("eventStory").items():
            title = self.text(e.findtext("Name") or "") or self.name(z)
            out[z] = {"title": title,
                      "options": [o.text for o in e.findall("aeOptions/zValue") if o.text]}
        return out

    @cached_property
    def event_options(self) -> dict[str, str]:
        """EVENTOPTION_* → display text of the choice (subject placeholders
        like {CHARACTER-2} collapse to …)."""
        import re
        out = {}
        for z, e in self._merged("eventOption").items():
            txt = self.text(e.findtext("Text") or "") or self.name(z)
            out[z] = re.sub(r"\{[^}]*\}", "…", txt)
        return out

    @cached_property
    def option_story(self) -> dict[str, str]:
        """EVENTOPTION_* → its EVENTSTORY_* (from aeOptions lists)."""
        out = {}
        for story, d in self.event_stories.items():
            for o in d["options"]:
                out[o] = story
        return out

    def nation_color(self, nation_ztype: str) -> str | None:
        """Nation's player color hex (border/crest color chain:
        nation → TeamColor → TeamPlayerColor → color.xml)."""
        nat = self._merged("nation").get(nation_ztype)
        if nat is None:
            return None
        tc = self._merged("teamColor").get(nat.findtext("TeamColor") or "")
        if tc is None:
            return None
        p = self._merged("playerColor").get(tc.findtext("TeamPlayerColor") or "")
        if p is None:
            return None
        col = {z: e.findtext("zHexValue") for z, e in self._merged("color").items()}
        return col.get(p.findtext("BorderColor") or p.findtext("CrestColor") or "")

    # ── chart-safe nation colours ───────────────────────────────────
    @staticmethod
    def _srgb_to_oklab(r, g, b):
        def lin(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = lin(r), lin(g), lin(b)
        l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
        m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
        s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
        return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s_,
                1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s_,
                0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s_)

    @staticmethod
    def _oklab_to_srgb(L, a, b):
        l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
        m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
        s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
        r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s_
        g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s_
        bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s_
        def out(c):
            c = max(0.0, min(1.0, c))
            c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
            return max(0, min(255, round(c * 255)))
        return out(r), out(g), out(bb)

    def chart_color(self, nation_ztype: str, lo=0.50, hi=0.65, cmin=0.11) -> str:
        """The nation's own hue, snapped into the dark-surface lightness
        band and chroma floor the dataviz checks require. Keeps identity
        (Hittite reads cyan, Tamil teal) while staying legible on #0b0c0f."""
        import math
        hexv = self.nation_color(nation_ztype) or "#888888"
        h = hexv.lstrip("#")[:6]
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        L, A, B = self._srgb_to_oklab(r, g, b)
        C = math.hypot(A, B)
        H = math.atan2(B, A)
        if C < 0.045:
            # The nation's identity IS neutral (Carthage's off-white, Kush's
            # cream). Forcing it into the chroma floor invents a hue that
            # collides with a real one (Carthage→gold vs Yuezhi's gold, ΔE 3).
            # Keep it achromatic and bright: on a dark surface a near-white
            # line is legible and maximally separated from any hue.
            L = max(0.86, L)
            C = min(C, 0.02)
        else:
            L = max(lo, min(hi, L))
            C = max(cmin, min(C, 0.16))
        return "#%02x%02x%02x" % self._oklab_to_srgb(L, C * math.cos(H), C * math.sin(H))

    def family_class_name(self, family_ztype: str) -> str:
        """FAMILY_MIHRANID → 'Artisans' (its class display name)."""
        f = self.families.get(family_ztype)
        return f["class_name"] if f else self.name(family_ztype)

    def build_cost10(self, build: str, ztype: str) -> int | None:
        """Cost of a queue item in save units (×10), or None if unknown."""
        table = {"BUILD_UNIT": self.units, "BUILD_PROJECT": self.projects,
                 "BUILD_SPECIALIST": self.specialists}.get(build)
        if table and ztype in table:
            return table[ztype]["cost"] * YIELDS_MULTIPLIER
        return None
