"""Read and write processed tables.

Layout: ``processed/<table>/<match_id>.parquet``. One file per match keeps parsing
idempotent (re-parsing a demo just overwrites its files) and makes the whole
directory readable as a single dataset by pyarrow, DuckDB or Polars.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from csanalysis import schema
from csanalysis.config import Paths


@dataclass
class MatchData:
    """All tables for a single match (one demo = one map)."""

    match_id: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)

    def __getitem__(self, table: str) -> pd.DataFrame:
        return self.tables[table]

    def finalize(self) -> MatchData:
        """Coerce and validate every table against the canonical schema."""
        for name in schema.TABLES:
            df = self.tables.get(name, schema.empty(name))
            if "match_id" in schema.columns(name):
                df = df.assign(match_id=self.match_id)
            df = schema.coerce(df, name)
            schema.validate(df, name)
            self.tables[name] = df
        return self


def write_match(paths: Paths, match: MatchData) -> None:
    for name, df in match.tables.items():
        out_dir = paths.table_dir(name)
        out_dir.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df, schema=schema.arrow_schema(name), preserve_index=False)
        # Write-then-rename so readers never see a half-written file.
        tmp = out_dir / f".{match.match_id}.parquet.tmp"
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, out_dir / f"{match.match_id}.parquet")


def delete_match(paths: Paths, match_id: str) -> None:
    for name in schema.TABLES:
        (paths.table_dir(name) / f"{match_id}.parquet").unlink(missing_ok=True)


def stored_match_ids(paths: Paths) -> set[str]:
    d = paths.table_dir("matches")
    return {p.stem for p in d.glob("*.parquet")} if d.exists() else set()


def read_table(paths: Paths, table: str, match_ids: Iterable[str] | None = None) -> pd.DataFrame:
    d = paths.table_dir(table)
    files = sorted(d.glob("*.parquet")) if d.exists() else []
    if match_ids is not None:
        wanted = set(match_ids)
        files = [f for f in files if f.stem in wanted]
    if not files:
        return schema.empty(table)
    arrow = pa.concat_tables([pq.read_table(f, schema=schema.arrow_schema(table)) for f in files])
    df = arrow.to_pandas(types_mapper=_types_mapper)
    return schema.coerce(df, table)


def _types_mapper(t: pa.DataType):
    if t == pa.int64():
        return pd.Int64Dtype()
    if t == pa.bool_():
        return pd.BooleanDtype()
    if t == pa.string():
        return pd.StringDtype()
    return None


class Dataset:
    """Lazy, cached access to every processed table, optionally filtered.

    >>> ds = Dataset(Paths(Path("data")), maps=["de_mirage"])
    >>> ds.kills.head()
    """

    def __init__(self, paths: Paths, maps: Iterable[str] | None = None, match_ids: Iterable[str] | None = None):
        self.paths = paths
        self._cache: dict[str, pd.DataFrame] = {}
        ids = set(match_ids) if match_ids is not None else None
        if maps is not None:
            matches = read_table(paths, "matches", ids)
            ids = set(matches.loc[matches["map_name"].isin(list(maps)), "match_id"])
        self.match_ids = ids

    def table(self, name: str) -> pd.DataFrame:
        if name not in self._cache:
            self._cache[name] = read_table(self.paths, name, self.match_ids)
        return self._cache[name]

    def __getattr__(self, name: str) -> pd.DataFrame:
        if name in schema.TABLES:
            return self.table(name)
        raise AttributeError(name)

    @property
    def root(self) -> Path:
        return self.paths.root
