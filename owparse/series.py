"""Load an mp-archive game folder (per-turn zips) into an ordered series.

Archive naming: `<game> · T00NN · YYYY-MM-DD HHMM · [hash].zip`, one save
XML inside. Multiple zips for the same turn = re-uploads; the latest
timestamp wins. Missing turns (gaps) are allowed and surfaced.
"""
from __future__ import annotations

import re
import tempfile
import zipfile
from pathlib import Path

from .save import Snapshot

_ZIPRE = re.compile(r"T(\d{4}) · (\d{4}-\d{2}-\d{2} \d{4}) · \[([0-9a-f]{8})\]\.zip$")


class Series:
    def __init__(self, archive_dir: Path | str, cache_dir: Path | str | None = None):
        self.archive_dir = Path(archive_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "owparse-cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        best: dict[int, tuple[str, Path]] = {}
        for z in sorted(self.archive_dir.glob("*.zip")):
            m = _ZIPRE.search(z.name)
            if not m:
                continue
            turn, ts = int(m.group(1)), m.group(2)
            if turn not in best or ts > best[turn][0]:
                best[turn] = (ts, z)
        self.zips: dict[int, Path] = {t: p for t, (_, p) in sorted(best.items())}
        self._snaps: dict[int, Snapshot] = {}

    @property
    def turns(self) -> list[int]:
        return list(self.zips)

    @property
    def gaps(self) -> list[int]:
        ts = self.turns
        return [t for t in range(ts[0], ts[-1] + 1) if t not in self.zips] if ts else []

    def snapshot(self, turn: int) -> Snapshot:
        if turn not in self._snaps:
            zpath = self.zips[turn]
            dest = self.cache_dir / f"{zpath.stem}"
            xmls = list(dest.glob("*.xml"))
            if not xmls:
                dest.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zpath) as zf:
                    zf.extractall(dest)
                xmls = list(dest.glob("*.xml"))
            self._snaps[turn] = Snapshot(xmls[0])
        return self._snaps[turn]

    def prev_turn(self, turn: int) -> int | None:
        prior = [t for t in self.turns if t < turn]
        return prior[-1] if prior else None

    def next_turn(self, turn: int) -> int | None:
        later = [t for t in self.turns if t > turn]
        return later[0] if later else None
