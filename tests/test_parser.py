"""Parser mapping tests using demoparser2-shaped frames, plus an opt-in real-demo test."""

import os
from pathlib import Path

import pandas as pd
import pytest

from csanalysis import schema
from csanalysis.parsing import parser as P

ROUNDS = pd.DataFrame({"round_num": [1], "start_tick": [0], "freeze_end_tick": [640], "end_tick": [6400]})


def test_kills_maps_demoparser_columns():
    raw = pd.DataFrame({
        "tick": [1280], "weapon": ["ak47"], "headshot": [True], "penetrated": [0], "thrusmoke": [False],
        "attackerblind": [False], "noscope": [False], "assistedflash": [False], "assister_steamid": [None],
        "attacker_steamid": ["76561198000000001"], "attacker_name": ["s1mple"], "attacker_team_num": [2],
        "attacker_X": [0.0], "attacker_Y": [0.0], "attacker_Z": [0.0], "attacker_yaw": [90.0],
        "attacker_pitch": [1.0], "attacker_last_place_name": ["LongA"], "attacker_health": [87],
        "attacker_velocity_X": [3.0], "attacker_velocity_Y": [4.0], "attacker_active_weapon_name": ["AK-47"],
        "user_steamid": [76561198000000002], "user_name": ["zywoo"], "user_team_num": [3],
        "user_X": [300.0], "user_Y": [400.0], "user_Z": [0.0], "user_active_weapon_name": ["M4A1-S"],
    })
    k = schema.coerce(P._kills(raw, ROUNDS, 64), "kills")
    row = k.iloc[0]
    assert row["attacker_side"] == "T" and row["victim_side"] == "CT"
    assert row["attacker_weapon"] == "ak47" and row["victim_weapon"] == "m4a1_silencer"
    assert row["victim_steamid"] == "76561198000000002"
    assert row["attacker_speed"] == pytest.approx(5.0)
    assert row["distance"] == pytest.approx(500.0)
    assert row["time_s"] == pytest.approx(10.0)
    assert not row["is_teamkill"] and not row["penetrated"]


def test_bomb_site_learned_from_entity_index():
    ev = {
        "bomb_planted": pd.DataFrame({"tick": [1000], "user_steamid": ["1"], "user_last_place_name": ["BombsiteB"],
                                      "site": [412], "user_X": [1.0], "user_Y": [2.0], "user_Z": [3.0]}),
        "bomb_beginplant": pd.DataFrame({"tick": [900], "user_steamid": ["1"], "user_last_place_name": ["Unknown"],
                                         "site": [412]}),
        "bomb_exploded": pd.DataFrame({"tick": [3560], "user_steamid": [0], "site": [None]}),
    }
    bomb = P._bomb(ev, ROUNDS, 64)
    assert bomb["site"].tolist() == ["B", "B", "B"]
    assert bomb["event"].tolist() == ["plant_begin", "plant", "explode"]


class FakeParser:
    def __init__(self, traj):
        self.traj = traj

    def parse_grenades(self):
        return self.traj


def test_grenade_flights_split_and_matched_to_throws():
    # Entity 7 is reused: a smoke at ticks 1000-1100 then a flash at 3000-3030.
    traj = pd.DataFrame({
        "grenade_type": ["CSmokeGrenadeProjectile"] * 4 + ["CFlashbangProjectile"] * 2,
        "grenade_entity_id": [7] * 6,
        "tick": [1000, 1001, 1050, 1100, 3000, 3030],
        "x": [10.0, 20.0, 500.0, 500.0, 0.0, 100.0], "y": [0.0, 0.0, 600.0, 600.0, 0.0, 0.0],
        "z": [64.0, 70.0, 0.0, 0.0, 64.0, 80.0],
        "steamid": [1, 1, 1, 1, 2, 2], "name": ["a"] * 4 + ["b"] * 2,
    })
    fire = pd.DataFrame({"tick": [998, 2999], "weapon": ["weapon_smokegrenade", "weapon_flashbang"],
                         "user_steamid": [1, 2], "user_X": [5.0, -1.0], "user_Y": [0.0, 0.0], "user_Z": [0.0, 0.0],
                         "user_yaw": [45.5, 10.0], "user_pitch": [-30.2, 0.0], "user_team_num": [2, 3]})
    # Grenades still in a player's hand are tracked too and must be ignored.
    held = pd.DataFrame({"grenade_type": ["CSmokeGrenade", "CWeaponGlock"], "grenade_entity_id": [9, 10],
                         "tick": [1000, 1000], "x": [1.0, 1.0], "y": [1.0, 1.0], "z": [1.0, 1.0],
                         "steamid": [3, 3], "name": ["c", "c"]})
    traj = pd.concat([traj, held], ignore_index=True)
    traj["tick"] = traj["tick"].astype("int32")  # what demoparser2 returns
    g = schema.coerce(P._grenades(FakeParser(traj), fire, ROUNDS, 64), "grenades").sort_values("throw_tick")
    assert g["grenade_type"].tolist() == ["smoke", "flash"]
    smoke = g.iloc[0]
    assert (smoke["land_x"], smoke["land_y"], smoke["land_tick"]) == (500.0, 600.0, 1050)
    assert (smoke["throw_x"], smoke["throw_yaw"], smoke["throw_pitch"]) == (5.0, 45.5, -30.2)
    assert smoke["thrower_side"] == "T" and g.iloc[1]["thrower_side"] == "CT"


@pytest.mark.skipif(not os.environ.get("CSA_TEST_DEMO"), reason="set CSA_TEST_DEMO=/path/to/demo.dem")
def test_real_demo_parses():
    match = P.parse_demo(Path(os.environ["CSA_TEST_DEMO"]))
    rounds, kills, econ = match["rounds"], match["kills"], match["economy"]
    assert rounds["round_num"].tolist() == list(range(1, len(rounds) + 1))
    assert set(rounds["winner_side"]) <= {"CT", "T"}
    assert econ.groupby("round_num")["steamid"].nunique().median() == 10
    assert kills["attacker_side"].notna().mean() > 0.9
    assert match["snapshots"]["place"].notna().mean() > 0.9
