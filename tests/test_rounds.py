import pandas as pd
import pytest

from csanalysis.parsing import rounds as R

TR = 64


def ev(ticks, **cols):
    return pd.DataFrame({"tick": ticks, **cols})


@pytest.mark.parametrize("raw,side", [(2, "T"), (3, "CT"), ("CT", "CT"), ("TERRORIST", "T"), ("2", "T"),
                                      (None, None), (0, None), (float("nan"), None)])
def test_normalize_side(raw, side):
    assert R.normalize_side(raw) == side


@pytest.mark.parametrize("raw,reason", [(1, "bomb_exploded"), (7.0, "bomb_defused"), (8, "t_eliminated"),
                                        ("ct_killed", "ct_eliminated"), ("target_saved", "time_ran_out"),
                                        ("t_win", "ct_eliminated"), ("weird", "other"), (None, "other")])
def test_normalize_reason(raw, reason):
    assert R.normalize_reason(raw) == reason


def test_reconstruct_basic_rounds():
    rounds = R.reconstruct_rounds(
        ev([1000, 3000], winner=[3, 2], reason=[8, 9]),
        ev([200, 2000]),
        ev([100, 1500]),
    )
    assert rounds["round_num"].tolist() == [1, 2]
    assert rounds["freeze_end_tick"].tolist() == [200, 2000]
    assert rounds["start_tick"].tolist() == [100, 1500]
    assert rounds["winner_side"].tolist() == ["CT", "T"]
    assert rounds["reason"].tolist() == ["t_eliminated", "ct_eliminated"]


def test_reconstruct_drops_warmup_knife_and_replayed_rounds():
    # warmup round, knife round (counter 0), restart, then round 1, 2, backup restore replaying round 2, round 3.
    round_end = ev(
        [500, 1500, 3000, 4000, 5000, 6000],
        winner=["CT", "T", "T", "CT", "T", "CT"],
        reason=[8, 9, 9, 8, 9, 8],
        is_warmup_period=[True, False, False, False, False, False],
        total_rounds_played=[0, 0, 0, 1, 1, 2],
    )
    freeze = ev([100, 1100, 2500, 3500, 4500, 5500])
    rounds = R.reconstruct_rounds(round_end, freeze)
    assert rounds["end_tick"].tolist() == [3000, 5000, 6000]
    assert rounds["winner_side"].tolist() == ["T", "T", "CT"]
    assert rounds["freeze_end_tick"].tolist() == [2500, 4500, 5500]


def test_reconstruct_without_counter_uses_last_match_start():
    rounds = R.reconstruct_rounds(ev([1000, 3000, 4000], winner=[3, 2, 3], reason=[8, 9, 8]),
                                  ev([500, 2500, 3500]), match_start=ev([2000]))
    assert rounds["end_tick"].tolist() == [3000, 4000]


def test_reconstruct_skips_rounds_without_winner():
    rounds = R.reconstruct_rounds(ev([1000, 2000], winner=[None, 3], reason=[10, 8]), ev([500, 1500]))
    assert len(rounds) == 1 and rounds["round_num"].iat[0] == 1


def test_assign_rounds():
    rounds = pd.DataFrame({"round_num": [1, 2], "start_tick": [0, 3000], "freeze_end_tick": [640, 3640],
                           "end_tick": [1500, 5000]})
    df = ev([10, 700, 1600, 1500 + 11 * TR, 3640 + 64, 9999])
    out = R.assign_rounds(df, rounds, TR)
    # 2204 is past round 1's grace period (and before round 2), 9999 is after the match.
    assert out["tick"].tolist() == [10, 700, 1600, 3704]
    assert out["round_num"].tolist() == [1, 1, 1, 2]
    assert out["post_round"].tolist() == [False, False, True, False]
    assert out["time_s"].iloc[-1] == pytest.approx(1.0)


def test_assign_teams_handles_halftime_and_substitutes():
    rows = []
    a, b = ["a1", "a2", "a3", "a4", "a5"], ["b1", "b2", "b3", "b4", "b5"]
    for r in range(1, 5):
        a_side, b_side = ("CT", "T") if r <= 2 else ("T", "CT")
        roster_a = a if r < 4 else ["a1", "a2", "a3", "a4", "sub"]  # substitute in round 4
        rows += [{"round_num": r, "steamid": s, "side": a_side, "clan_name": "Alpha"} for s in roster_a]
        rows += [{"round_num": r, "steamid": s, "side": b_side, "clan_name": "Bravo" if r != 2 else None} for s in b]
    per_round, names = R.assign_teams(pd.DataFrame(rows))
    assert per_round["ct_key"].tolist() == ["A", "A", "B", "B"]
    assert names == {"A": "Alpha", "B": "Bravo"}


def test_assign_teams_without_clan_names():
    rows = [{"round_num": 1, "steamid": f"p{i}", "side": "CT" if i < 5 else "T"} for i in range(10)]
    _, names = R.assign_teams(pd.DataFrame(rows))
    assert names == {"A": "Team A", "B": "Team B"}


def test_scores():
    rounds = pd.DataFrame({"round_num": [1, 2, 3], "ct_team": ["X", "X", "Y"], "t_team": ["Y", "Y", "X"],
                           "winner_side": ["CT", "T", "CT"]})
    out = R.add_scores(rounds)
    assert out["ct_score"].tolist() == [0, 1, 1]
    assert out["t_score"].tolist() == [0, 0, 1]
    assert R.final_score(out, "X") == 1 and R.final_score(out, "Y") == 2
