"""Bring demo files into the data directory and track them in a catalog.

Accepts .dem files, compressed demos (.dem.gz / .dem.bz2 / .dem.zst*) and
archives (.zip, and .rar / .7z via the `7z` or `bsdtar` command, which is how
HLTV distributes GOTV demos). Every demo is content-hashed, so the same match
downloaded twice is only stored and parsed once.
"""

from __future__ import annotations

import bz2
import gzip
import logging
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from csanalysis.config import Paths
from csanalysis.parsing.parser import file_hash

log = logging.getLogger(__name__)

ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
COMPRESSED = {".gz": gzip.open, ".bz2": bz2.open}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS demos (
    match_id    TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    source_name TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    added_at    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | parsed | failed
    error       TEXT,
    parsed_at   TEXT
);
"""


@dataclass
class IngestResult:
    added: list[str]
    duplicates: list[str]
    errors: list[tuple[str, str]]


@contextmanager
def catalog(paths: Paths) -> Iterator[sqlite3.Connection]:
    paths.ensure()
    con = sqlite3.connect(paths.catalog)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def ingest(paths: Paths, sources: Iterable[Path], move: bool = False) -> IngestResult:
    """Ingest files or directories (searched recursively)."""
    result = IngestResult([], [], [])
    files = []
    for src in sources:
        src = Path(src)
        files.extend(sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else [src])

    with catalog(paths) as con:
        for f in files:
            if not _is_candidate(f):
                continue
            try:
                with tempfile.TemporaryDirectory(dir=paths.root) as tmp:
                    for dem in _extract(f, Path(tmp)):
                        _add_demo(paths, con, dem, source_name=_source_name(f, dem), result=result)
                if move:
                    f.unlink()
            except Exception as exc:  # one bad archive must not stop a bulk import
                log.warning("failed to ingest %s: %s", f, exc)
                result.errors.append((str(f), str(exc)))
    return result


def _is_candidate(p: Path) -> bool:
    name = p.name.lower()
    return name.endswith(".dem") or p.suffix.lower() in ARCHIVE_SUFFIXES or any(
        name.endswith(".dem" + s) for s in COMPRESSED)


def _source_name(archive: Path, dem: Path) -> str:
    return archive.name if archive.name == dem.name else f"{archive.name}/{dem.name}"


def _extract(f: Path, tmp: Path) -> list[Path]:
    """Return the .dem files contained in `f`, extracted under `tmp` when needed."""
    name = f.name.lower()
    if name.endswith(".dem"):
        return [f]
    for suffix, opener in COMPRESSED.items():
        if name.endswith(".dem" + suffix):
            out = tmp / f.name[: -len(suffix)]
            with opener(f, "rb") as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
            return [out]
    if f.suffix.lower() == ".zip":
        found = []
        with zipfile.ZipFile(f) as z:
            for i, info in enumerate(z.infolist()):
                if info.is_dir() or not info.filename.lower().endswith(".dem"):
                    continue
                # Flatten paths: archive member names are untrusted (path traversal).
                out = tmp / f"{i}_{Path(info.filename).name}"
                with z.open(info) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                found.append(out)
        return found
    return _extract_external(f, tmp)


def _extract_external(f: Path, tmp: Path) -> list[Path]:
    out = tmp / "x"
    out.mkdir()
    if shutil.which("7z"):
        cmd = ["7z", "x", "-y", f"-o{out}", str(f)]
    elif shutil.which("bsdtar"):
        cmd = ["bsdtar", "-xf", str(f), "-C", str(out)]
    elif shutil.which("unrar"):
        cmd = ["unrar", "x", "-y", str(f), str(out) + "/"]
    else:
        raise RuntimeError(f"cannot extract {f.suffix}: install 7z (p7zip), bsdtar or unrar")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    out_resolved = out.resolve()
    return sorted(p for p in out.rglob("*.dem")
                  if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(out_resolved))


def _add_demo(paths: Paths, con: sqlite3.Connection, dem: Path, source_name: str, result: IngestResult) -> None:
    match_id = file_hash(dem)
    if con.execute("SELECT 1 FROM demos WHERE match_id = ?", (match_id,)).fetchone():
        result.duplicates.append(source_name)
        return
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in dem.stem)[:80]
    dest = paths.demos / f"{stem}__{match_id}.dem"
    shutil.copyfile(dem, dest)
    con.execute(
        "INSERT INTO demos (match_id, path, source_name, size_bytes, added_at) VALUES (?, ?, ?, ?, ?)",
        (match_id, str(dest.relative_to(paths.root)), source_name, dest.stat().st_size, _now()))
    result.added.append(source_name)


def pending(paths: Paths, include_failed: bool = False, force: bool = False) -> list[sqlite3.Row]:
    statuses = ("pending", "failed", "parsed") if force else (("pending", "failed") if include_failed else ("pending",))
    with catalog(paths) as con:
        q = f"SELECT * FROM demos WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY added_at"
        return con.execute(q, statuses).fetchall()


def mark(paths: Paths, match_id: str, status: str, error: str | None = None) -> None:
    with catalog(paths) as con:
        con.execute("UPDATE demos SET status = ?, error = ?, parsed_at = ? WHERE match_id = ?",
                    (status, error, _now() if status == "parsed" else None, match_id))


def status_counts(paths: Paths) -> dict[str, int]:
    if not paths.catalog.exists():
        return {}
    with catalog(paths) as con:
        return {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) AS n FROM demos GROUP BY status")}


def failures(paths: Paths) -> list[sqlite3.Row]:
    with catalog(paths) as con:
        return con.execute("SELECT source_name, error FROM demos WHERE status = 'failed'").fetchall()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
