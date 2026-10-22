"""Round boundaries, sides and team identity, reconstructed from raw demo events.

Pro demos are messy: they can contain warmup, knife rounds, `mp_restartgame`
restarts and backup restores that replay rounds. These functions are pure
(DataFrames in, DataFrames out) so the edge cases are unit-testable without a demo.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

# Grace period after round_end in which kills/damage still belong to the round
# (the round restart delay is 7s in competitive).
POST_ROUND_GRACE_S = 10.0


def normalize_side(v: object) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA:
        return None
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        v = int(v)  # team numbers become floats when the column has nulls
    s = str(v).strip().upper()
    if s in {"2", "T", "TERRORIST", "TERRORISTS"}:
        return "T"
    if s in {"3", "CT", "COUNTERTERRORIST", "COUNTER-TERRORIST", "CTS"}:
        return "CT"
    return None


# RoundEndReason ids from the game, plus the string forms emitted by parsers.
_REASONS = {
    "1": "bomb_exploded", "target_bombed": "bomb_exploded", "bomb_exploded": "bomb_exploded",
    "7": "bomb_defused", "bomb_defused": "bomb_defused",
    "8": "t_eliminated", "ct_win": "t_eliminated", "cts_win": "t_eliminated", "t_killed": "t_eliminated",
    "terrorists_killed": "t_eliminated", "t_eliminated": "t_eliminated",
    "9": "ct_eliminated", "t_win": "ct_eliminated", "terrorists_win": "ct_eliminated", "ct_killed": "ct_eliminated",
    "ct_eliminated": "ct_eliminated",
    "12": "time_ran_out", "target_saved": "time_ran_out", "time_ran_out": "time_ran_out",
    "17": "surrender", "18": "surrender", "t_surrender": "surrender", "ct_surrender": "surrender",
    "terrorists_surrender": "surrender", "cts_surrender": "surrender",
}


def normalize_reason(v: object) -> str:
    if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
        return "other"
    s = str(v).strip().lower()
    if s.endswith(".0"):
        s = s[:-2]
    return _REASONS.get(s, "other")


def reconstruct_rounds(
    round_end: pd.DataFrame,
    freeze_end: pd.DataFrame,
    round_start: pd.DataFrame | None = None,
    match_start: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one row per real round.

    Inputs are event frames with at least a `tick` column; `round_end` also needs
    `winner` and `reason` and may carry `is_warmup_period` / `total_rounds_played`.
    Returns columns round_num, start_tick, freeze_end_tick, end_tick, winner_side, reason.
    """
    cols = ["round_num", "start_tick", "freeze_end_tick", "end_tick", "winner_side", "reason"]
    if round_end is None or round_end.empty:
        return pd.DataFrame(columns=cols)

    re = round_end.copy().sort_values("tick", kind="stable")
    re["winner_side"] = re["winner"].map(normalize_side) if "winner" in re else None
    re["reason"] = re["reason"].map(normalize_reason) if "reason" in re else "other"
    re = re[re["winner_side"].notna()]
    if "is_warmup_period" in re:
        re = re[re["is_warmup_period"].fillna(False).astype(bool) == False]  # noqa: E712

    if "total_rounds_played" in re and re["total_rounds_played"].notna().all() and len(re):
        # A replayed round (restart / backup restore) reuses its round counter;
        # the last time a counter value ends is the version that counts.
        re = re.drop_duplicates("total_rounds_played", keep="last")
        re = re.sort_values("total_rounds_played", kind="stable")
        # Counter resets (e.g. knife round, then restart) can leave an earlier-ticked
        # round after a later one; keep only rounds that are monotonic in time.
        re = re[re["tick"] >= re["tick"].cummax()]
    elif match_start is not None and not match_start.empty:
        re = re[re["tick"] > match_start["tick"].max()]

    re = re[["tick", "winner_side", "reason"]].rename(columns={"tick": "end_tick"}).reset_index(drop=True)
    if re.empty:
        return pd.DataFrame(columns=cols)

    fe = _ticks(freeze_end).rename("freeze_end_tick")
    re = pd.merge_asof(re, fe.to_frame(), left_on="end_tick", right_on="freeze_end_tick", direction="backward",
                       allow_exact_matches=False)
    prev_end = re["end_tick"].shift(1)
    # No freeze end since the previous round ended (shouldn't happen) -> use that end.
    bad = re["freeze_end_tick"].isna() | (prev_end.notna() & (re["freeze_end_tick"] <= prev_end))
    re.loc[bad, "freeze_end_tick"] = prev_end[bad].fillna(0)

    if round_start is not None and not round_start.empty:
        rs = _ticks(round_start).rename("start_tick")
        re = pd.merge_asof(re.sort_values("freeze_end_tick"), rs.to_frame(), left_on="freeze_end_tick",
                           right_on="start_tick", direction="backward")
        re = re.sort_values("end_tick").reset_index(drop=True)
        prev_end = re["end_tick"].shift(1)
        bad = re["start_tick"].isna() | (prev_end.notna() & (re["start_tick"] < prev_end))
        re.loc[bad, "start_tick"] = re.loc[bad, "freeze_end_tick"]
    else:
        re["start_tick"] = re["freeze_end_tick"]

    re["round_num"] = np.arange(1, len(re) + 1)
    for c in ("start_tick", "freeze_end_tick", "end_tick"):
        re[c] = re[c].astype("int64")
    return re[cols]


def _ticks(df: pd.DataFrame) -> pd.Series:
    return df["tick"].dropna().astype("int64").drop_duplicates().sort_values().reset_index(drop=True)


def assign_rounds(df: pd.DataFrame, rounds: pd.DataFrame, tickrate: int, tick_col: str = "tick") -> pd.DataFrame:
    """Attach round_num, time_s and post_round to tick-stamped rows.

    Rows that fall outside every round (warmup, discarded replayed rounds,
    halftime) are dropped.
    """
    if df.empty or rounds.empty:
        return df.assign(round_num=pd.Series(dtype="Int64"), time_s=pd.Series(dtype=float),
                         post_round=pd.Series(dtype=bool)).iloc[0:0]
    r = rounds[["round_num", "start_tick", "freeze_end_tick", "end_tick"]].sort_values("start_tick")
    d = df.copy()
    d["_tick"] = pd.to_numeric(d[tick_col], errors="coerce")
    d = d[d["_tick"].notna()].astype({"_tick": "int64"}).sort_values("_tick", kind="stable")
    d = pd.merge_asof(d, r, left_on="_tick", right_on="start_tick", direction="backward")
    grace = int(POST_ROUND_GRACE_S * tickrate)
    d = d[d["round_num"].notna() & (d["_tick"] <= d["end_tick"] + grace)]
    d["time_s"] = (d["_tick"] - d["freeze_end_tick"]) / tickrate
    d["post_round"] = d["_tick"] > d["end_tick"]
    return d.drop(columns=["_tick", "start_tick", "freeze_end_tick", "end_tick"]).reset_index(drop=True)


def assign_teams(players: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Work out which team is CT in every round.

    `players` has one row per (round_num, steamid) with `side` and optional
    `clan_name`. Teams are identified by their roster rather than by clan name,
    because clan names are missing in some demos. The team that starts on CT is
    "A"; a round's CT team is whichever roster overlaps the CT players most, which
    is robust to halftime, overtime side swaps and substitutes.

    Returns (per-round frame with round_num, ct_key, t_key) and {key: display name}.
    """
    members = {"A": set(), "B": set()}
    names: dict[str, Counter] = {"A": Counter(), "B": Counter()}
    rows = []
    for rnd, grp in players.sort_values("round_num").groupby("round_num", sort=True):
        ct = set(grp.loc[grp["side"] == "CT", "steamid"])
        t = set(grp.loc[grp["side"] == "T", "steamid"])
        if not members["A"] and not members["B"]:
            ct_key = "A"
        else:
            a_is_ct = len(ct & members["A"]) + len(t & members["B"])
            b_is_ct = len(ct & members["B"]) + len(t & members["A"])
            ct_key = "A" if a_is_ct >= b_is_ct else "B"
        t_key = "B" if ct_key == "A" else "A"
        members[ct_key] |= ct
        members[t_key] |= t
        if "clan_name" in grp:
            for side, key in (("CT", ct_key), ("T", t_key)):
                clan = grp.loc[grp["side"] == side, "clan_name"].dropna().astype(str)
                names[key].update(c for c in clan if c.strip())
        rows.append({"round_num": rnd, "ct_key": ct_key, "t_key": t_key})

    display = {}
    for key in ("A", "B"):
        display[key] = names[key].most_common(1)[0][0] if names[key] else f"Team {key}"
    if display["A"] == display["B"]:
        display = {"A": f"{display['A']} (A)", "B": f"{display['B']} (B)"}
    return pd.DataFrame(rows, columns=["round_num", "ct_key", "t_key"]), display


def add_scores(rounds: pd.DataFrame) -> pd.DataFrame:
    """Add ct_score / t_score (score *before* the round) given ct_team, t_team, winner_side."""
    score: Counter = Counter()
    ct_s, t_s = [], []
    for row in rounds.sort_values("round_num").itertuples():
        ct_s.append(score[row.ct_team])
        t_s.append(score[row.t_team])
        score[row.ct_team if row.winner_side == "CT" else row.t_team] += 1
    out = rounds.sort_values("round_num").copy()
    out["ct_score"] = ct_s
    out["t_score"] = t_s
    return out


def final_score(rounds: pd.DataFrame, team: str) -> int:
    won = ((rounds["ct_team"] == team) & (rounds["winner_side"] == "CT")) | (
        (rounds["t_team"] == team) & (rounds["winner_side"] == "T"))
    return int(won.sum())
