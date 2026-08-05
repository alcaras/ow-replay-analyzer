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
