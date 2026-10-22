import json

import numpy as np

from csanalysis import schema
from csanalysis.storage import Dataset


def test_tables_satisfy_schema(synth_paths):
    ds = Dataset(synth_paths)
    for name in schema.TABLES:
        schema.validate(ds.table(name), name)
    assert len(ds.matches) == 6


def test_round_logic_is_consistent(synth_paths):
    ds = Dataset(synth_paths)
    r, k = ds.rounds, ds.kills
    assert (ds.matches.set_index("match_id")["n_rounds"] == r.groupby("match_id").size()).all()
    # Each player dies at most once per round.
    assert not k.duplicated(["match_id", "round_num", "victim_steamid"]).any()
    # Elimination reasons agree with the kill feed.
    deaths = k.groupby(["match_id", "round_num", "victim_side"]).size().unstack(fill_value=0)
    rr = r.set_index(["match_id", "round_num"]).join(deaths)
    assert (rr.loc[rr["reason"] == "t_eliminated", "T"] == 5).all()
    assert (rr.loc[rr["reason"] == "ct_eliminated", "CT"] == 5).all()
    assert (rr.loc[rr["reason"] == "bomb_defused", "winner_side"] == "CT").all()
    assert rr.loc[rr["reason"].isin(["bomb_defused", "bomb_exploded"]), "bomb_plant_tick"].notna().all()


def test_matches_end_with_a_winner(synth_paths):
    m = Dataset(synth_paths).matches
    top = np.maximum(m["score_a"], m["score_b"])
    assert ((top == 13) | (top >= 16)).all()
    assert (m["score_a"] != m["score_b"]).all()


def test_economy_and_snapshots(synth_paths):
    ds = Dataset(synth_paths)
    assert (ds.economy.groupby(["match_id", "round_num"]).size() == 10).all()
    s = ds.snapshots
    first = s[s["time_s"] == 0]
    assert first["is_alive"].all()
    assert (s.loc[~s["is_alive"], "hp"] == 0).all()


def test_ground_truth_written(synth_paths):
    truth = json.loads((synth_paths.root / "ground_truth.json").read_text())
    assert set(truth["maps"]) == set(Dataset(synth_paths).matches["map_name"])
    smokes = truth["maps"]["de_synth_alpha"]["smokes"]
    assert {s["side"] for s in smokes} == {"CT", "T"}
