"""Command line interface: `csa --help`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from csanalysis import ingest as ingest_mod
from csanalysis.config import ParseSettings, Paths, default_data_dir

app = typer.Typer(help="CS2 pro demo analytics: ingest demos, parse them, and analyze how rounds are won.",
                  no_args_is_help=True, add_completion=False)
console = Console()

DataDir = Annotated[Path, typer.Option("--data-dir", "-d", help="Data directory (env: CSA_DATA_DIR).",
                                       default_factory=default_data_dir)]


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(message)s",
                        handlers=[RichHandler(console=console, show_path=False)])


@app.command()
def ingest(
    sources: Annotated[list[Path], typer.Argument(help=".dem files, archives (.rar/.zip/.7z/.dem.gz) or folders")],
    data_dir: DataDir,
    move: Annotated[bool, typer.Option(help="Delete source files after a successful import.")] = False,
) -> None:
    """Import demos into the data directory (deduplicated by content hash)."""
    paths = Paths(data_dir).ensure()
    res = ingest_mod.ingest(paths, sources, move=move)
    console.print(f"[green]added {len(res.added)}[/] demos, skipped {len(res.duplicates)} duplicates")
    for name, err in res.errors:
        console.print(f"[red]error[/] {name}: {err}")
    if res.added:
        console.print("next: [bold]csa parse[/]")


@app.command()
def parse(
    data_dir: DataDir,
    workers: Annotated[int | None, typer.Option("--workers", "-j", help="Parallel parser processes.")] = None,
    retry_failed: Annotated[bool, typer.Option(help="Also retry demos that failed before.")] = False,
    force: Annotated[bool, typer.Option(help="Re-parse everything, including already parsed demos.")] = False,
    snapshot_interval: Annotated[float, typer.Option(help="Seconds between position snapshots.")] = 2.0,
) -> None:
    """Parse ingested demos into analysis tables."""
    from csanalysis.pipeline import parse_pending

    paths = Paths(data_dir).ensure()
    todo = len(ingest_mod.pending(paths, include_failed=retry_failed, force=force))
    if not todo:
        console.print("nothing to parse (use [bold]csa ingest[/] first, or --retry-failed / --force)")
        return
    with Progress(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
                  console=console) as progress:
        task = progress.add_task("parsing", total=todo)

        def report(out):
            if out.ok:
                progress.console.print(f"[green]✓[/] {out.source_name}  {out.map_name}, {out.n_rounds} rounds")
            else:
                progress.console.print(f"[red]✗[/] {out.source_name}  {out.error}")
            progress.advance(task)

        outcomes = parse_pending(paths, workers=workers, retry_failed=retry_failed, force=force,
                                 settings=ParseSettings(snapshot_interval_s=snapshot_interval), on_result=report)
    ok = sum(o.ok for o in outcomes)
    console.print(f"parsed {ok}/{len(outcomes)} demos")
    if ok < len(outcomes):
        raise typer.Exit(1)


@app.command()
def info(data_dir: DataDir) -> None:
    """Summarize what is in the dataset."""
    from csanalysis.storage import read_table

    paths = Paths(data_dir)
    counts = ingest_mod.status_counts(paths)
    if counts:
        console.print("catalog: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    matches = read_table(paths, "matches")
    if matches.empty:
        console.print("no parsed matches yet")
        return
    rounds = read_table(paths, "rounds")
    kills = read_table(paths, "kills")
    grenades = read_table(paths, "grenades")
    t = Table(title=f"Dataset at {paths.root}")
    for col in ("map", "matches", "rounds", "T win %", "kills", "smokes"):
        t.add_column(col, justify="right" if col != "map" else "left")
    r = rounds.merge(matches[["match_id", "map_name"]], on="match_id")
    k = kills.merge(matches[["match_id", "map_name"]], on="match_id")
    g = grenades.merge(matches[["match_id", "map_name"]], on="match_id")
    for map_name, mm in matches.groupby("map_name"):
        rr = r[r["map_name"] == map_name]
        t.add_row(str(map_name), str(len(mm)), str(len(rr)), f"{(rr['winner_side'] == 'T').mean():.1%}",
                  str(int((k["map_name"] == map_name).sum())),
                  str(int(((g["map_name"] == map_name) & (g["grenade_type"] == "smoke")).sum())))
    console.print(t)
    if (fails := ingest_mod.failures(paths)):
        console.print(f"[yellow]{len(fails)} demos failed to parse[/] (see `csa parse --retry-failed -v`)")


@app.command()
def synth(
    data_dir: Annotated[Path, typer.Option("--data-dir", "-d", help="Where to write synthetic data.")] = Path(
        "data/synthetic"),
    matches: Annotated[int, typer.Option("--matches", "-n")] = 60,
    seed: int = 0,
) -> None:
    """Generate synthetic matches with known ground-truth effects (for testing analyses)."""
    from csanalysis.synthetic import generate

    paths = Paths(data_dir.resolve())
    if paths.processed.exists() and any(paths.processed.iterdir()):
        import shutil

        shutil.rmtree(paths.processed)
    generate(paths, n_matches=matches, seed=seed)
    console.print(f"wrote {matches} synthetic matches to {paths.root} (ground truth: ground_truth.json)")


@app.command("inspect-demo")
def inspect_demo(demo: Path) -> None:
    """Parse one .dem file without storing it and print a sanity report."""
    from csanalysis.parsing.parser import parse_demo

    match = parse_demo(demo)
    m = match["matches"].iloc[0]
    console.print(f"[bold]{m['map_name']}[/]  {m['team_a']} {m['score_a']} - {m['score_b']} {m['team_b']}  "
                  f"({m['n_rounds']} rounds)")
    t = Table()
    t.add_column("table")
    t.add_column("rows", justify="right")
    t.add_column("null % (worst column)")
    for name, df in match.tables.items():
        nulls = df.isna().mean().sort_values(ascending=False) if len(df) else None
        worst = f"{nulls.index[0]} {nulls.iloc[0]:.0%}" if nulls is not None and len(nulls) else "-"
        t.add_row(name, str(len(df)), worst)
    console.print(t)
    rounds = match["rounds"]
    console.print(rounds[["round_num", "winner_side", "reason", "ct_team", "ct_score", "t_score", "bomb_site"]]
                  .to_string(index=False))


if __name__ == "__main__":
    app()
