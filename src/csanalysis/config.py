"""Project-wide settings and filesystem layout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# CS2 GOTV demos record at 64 ticks per second.
TICKRATE = 64

# Bumped whenever the processed table layout changes, so stale data can be detected.
SCHEMA_VERSION = 1


def default_data_dir() -> Path:
    return Path(os.environ.get("CSA_DATA_DIR", "data")).resolve()


@dataclass(frozen=True)
class Paths:
    """Filesystem layout rooted at a single data directory.

    data/
      demos/                 extracted .dem files (one per map played)
      processed/<table>/     one parquet file per match for each table
      catalog.sqlite         ingestion + parsing status of every demo
    """

    root: Path

    @property
    def demos(self) -> Path:
        return self.root / "demos"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def catalog(self) -> Path:
        return self.root / "catalog.sqlite"

    def table_dir(self, table: str) -> Path:
        return self.processed / table

    def ensure(self) -> Paths:
        self.demos.mkdir(parents=True, exist_ok=True)
        self.processed.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class ParseSettings:
    # Seconds between position snapshots inside a round.
    snapshot_interval_s: float = 2.0
    # Economy is read this long after freeze time ends (players finish buying / dropping),
    # or just before the first death of the round, whichever comes first.
    economy_offset_s: float = 5.0
