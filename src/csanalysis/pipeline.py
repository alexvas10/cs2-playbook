"""Parse every pending demo in the catalog, in parallel."""

from __future__ import annotations

import logging
import os
import traceback
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from csanalysis import ingest
from csanalysis.config import ParseSettings, Paths
from csanalysis.storage import write_match

log = logging.getLogger(__name__)


@dataclass
class ParseOutcome:
    match_id: str
    source_name: str
    ok: bool
    n_rounds: int = 0
    map_name: str | None = None
    error: str | None = None


def _parse_one(root: str, match_id: str, rel_path: str, source_name: str, settings: ParseSettings) -> ParseOutcome:
    from csanalysis.parsing.parser import parse_demo

    paths = Paths(Path(root))
    try:
        match = parse_demo(paths.root / rel_path, match_id=match_id, settings=settings)
        write_match(paths, match)
        m = match["matches"].iloc[0]
        return ParseOutcome(match_id, source_name, True, int(m["n_rounds"]), str(m["map_name"]))
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:  # demoparser2 raises pyo3 PanicException (a BaseException) on corrupt demos
        log.debug("parse failed for %s\n%s", source_name, traceback.format_exc())
        return ParseOutcome(match_id, source_name, False, error=f"{type(exc).__name__}: {exc}")


def parse_pending(paths: Paths, workers: int | None = None, retry_failed: bool = False, force: bool = False,
                  settings: ParseSettings | None = None,
                  on_result: Callable[[ParseOutcome], None] | None = None) -> list[ParseOutcome]:
    settings = settings or ParseSettings()
    todo = ingest.pending(paths, include_failed=retry_failed, force=force)
    if not todo:
        return []
    # Parsing a demo holds a few GB of RAM at peak for long matches; cap workers.
    workers = workers or max(1, min(len(todo), (os.cpu_count() or 2) // 2, 8))
    outcomes = []
    args = [(str(paths.root), r["match_id"], r["path"], r["source_name"], settings) for r in todo]
    if workers == 1:
        results = (_parse_one(*a) for a in args)
        iterator = results
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        iterator = (f.result() for f in as_completed([pool.submit(_parse_one, *a) for a in args]))
    try:
        for out in iterator:
            ingest.mark(paths, out.match_id, "parsed" if out.ok else "failed", out.error)
            outcomes.append(out)
            if on_result:
                on_result(out)
    finally:
        if workers != 1:
            pool.shutdown(cancel_futures=True)
    return outcomes
