import pandas as pd

from csanalysis.config import Paths
from csanalysis.storage import Dataset, read_table, stored_match_ids, write_match
from csanalysis.synthetic import generate


def test_roundtrip_and_overwrite(tmp_path):
    src = Paths(tmp_path / "src")
    generate(src, n_matches=2, seed=3)
    ds = Dataset(src)
    dst = Paths(tmp_path / "dst")
    from csanalysis.storage import MatchData
    for mid in ds.matches["match_id"]:
        tables = {name: read_table(src, name, [mid]) for name in ("matches", "rounds", "kills", "economy")}
        write_match(dst, MatchData(mid, tables).finalize())
        write_match(dst, MatchData(mid, tables).finalize())  # idempotent
    assert stored_match_ids(dst) == set(ds.matches["match_id"])
    pd.testing.assert_frame_equal(read_table(dst, "kills"), ds.kills)
    pd.testing.assert_frame_equal(read_table(dst, "economy"), ds.economy)


def test_dataset_map_filter(synth_paths):
    ds = Dataset(synth_paths, maps=["de_synth_bravo"])
    assert set(ds.matches["map_name"]) == {"de_synth_bravo"}
    assert set(ds.rounds["match_id"]) == set(ds.matches["match_id"])
    assert len(Dataset(synth_paths, maps=["de_nope"]).kills) == 0
