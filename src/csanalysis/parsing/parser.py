"""Turn a CS2 .dem file into the canonical tables defined in `csanalysis.schema`.

Uses demoparser2 (Rust, fast). The demo is read in two passes: one for all game
events, one for player state at selected ticks (economy at the start of each
round plus periodic position snapshots), and a third for grenade trajectories.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from csanalysis import weapons
from csanalysis.config import SCHEMA_VERSION, TICKRATE, ParseSettings
from csanalysis.parsing import rounds as R
from csanalysis.storage import MatchData

log = logging.getLogger(__name__)

EVENTS = [
    "round_start", "round_freeze_end", "round_end", "begin_new_match",
    "player_death", "player_hurt", "player_blind", "weapon_fire",
    "bomb_beginplant", "bomb_planted", "bomb_begindefuse", "bomb_defused", "bomb_exploded",
]
# Player state attached to every event participant (user_*, attacker_*, assister_*).
EVENT_PLAYER_PROPS = [
    "X", "Y", "Z", "yaw", "pitch", "team_num", "last_place_name", "health", "armor_value",
    "is_scoped", "flash_duration", "active_weapon_name", "velocity_X", "velocity_Y", "velocity_Z",
]
EVENT_OTHER_PROPS = ["total_rounds_played", "is_warmup_period"]
TICK_PROPS = [
    "X", "Y", "Z", "yaw", "team_num", "team_clan_name", "last_place_name", "health", "armor_value",
    "is_alive", "active_weapon_name", "current_equip_value", "balance", "cash_spent_this_round",
    "has_helmet", "has_defuser", "inventory",
]
# Props the parse cannot do without; the rest are dropped (with a warning) if
# the installed demoparser2 version does not know them.
REQUIRED_PROPS = {"X", "Y", "Z", "team_num", "health"}


def file_hash(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:n]


def parse_demo(path: Path, match_id: str | None = None, settings: ParseSettings | None = None) -> MatchData:
    from demoparser2 import DemoParser  # imported lazily: heavy native module

    settings = settings or ParseSettings()
    path = Path(path)
    match_id = match_id or file_hash(path)
    parser = DemoParser(str(path))
    header = parser.parse_header()
    tickrate = TICKRATE

    ev = _parse_events(parser)
    rounds = R.reconstruct_rounds(ev.get("round_end"), ev.get("round_freeze_end", _empty_ticks()),
                                  ev.get("round_start"), ev.get("begin_new_match"))
    if rounds.empty:
        raise ValueError("no completed rounds found in demo")

    kills = _kills(ev.get("player_death"), rounds, tickrate)

    # One tick pass for both the economy read and position snapshots.
    econ_ticks = _economy_ticks(rounds, kills, settings, tickrate)
    snap_ticks = _snapshot_ticks(rounds, settings, tickrate)
    ticks_df = _parse_ticks(parser, sorted(set(econ_ticks["tick"]) | set(snap_ticks["tick"])))

    economy_raw = econ_ticks.merge(ticks_df, on="tick", how="inner")
    economy_raw["side"] = economy_raw["team_num"].map(R.normalize_side)
    economy_raw = economy_raw[economy_raw["side"].notna()]
    team_rounds, team_names = R.assign_teams(
        economy_raw.rename(columns={"team_clan_name": "clan_name"})[["round_num", "steamid", "side", "clan_name"]]
        if "team_clan_name" in economy_raw else economy_raw[["round_num", "steamid", "side"]])

    rounds = rounds.merge(team_rounds, on="round_num", how="left")
    rounds["ct_team"] = rounds["ct_key"].map(team_names)
    rounds["t_team"] = rounds["t_key"].map(team_names)

    bomb = _bomb(ev, rounds, tickrate)
    plants = bomb[bomb["event"] == "plant"].drop_duplicates("round_num", keep="first")
    rounds = rounds.merge(plants[["round_num", "tick", "site"]].rename(
        columns={"tick": "bomb_plant_tick", "site": "bomb_site"}), on="round_num", how="left")
    rounds = R.add_scores(rounds)

    economy = _economy(economy_raw, rounds)
    snapshots = _snapshots(snap_ticks.merge(ticks_df, on="tick", how="inner"), rounds)
    grenades = _grenades(parser, ev.get("weapon_fire"), rounds, tickrate)

    matches = pd.DataFrame([{
        "match_id": match_id,
        "source": "demo",
        "demo_file": path.name,
        "map_name": header.get("map_name", "unknown"),
        "team_a": team_names["A"],
        "team_b": team_names["B"],
        "score_a": R.final_score(rounds, team_names["A"]),
        "score_b": R.final_score(rounds, team_names["B"]),
        "n_rounds": len(rounds),
        "tickrate": tickrate,
        "server_name": header.get("server_name"),
        "parsed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema_version": SCHEMA_VERSION,
    }])

    return MatchData(match_id, {
        "matches": matches,
        "rounds": rounds,
        "kills": kills,
        "damages": _damages(ev.get("player_hurt"), rounds, tickrate),
        "grenades": grenades,
        "blinds": _blinds(ev.get("player_blind"), rounds, tickrate),
        "bomb": bomb,
        "economy": economy,
        "snapshots": snapshots,
    }).finalize()


# --------------------------------------------------------------------------- raw parsing

def _empty_ticks() -> pd.DataFrame:
    return pd.DataFrame({"tick": pd.Series(dtype="int64")})


def _parse_events(parser) -> dict[str, pd.DataFrame]:
    available = set(parser.list_game_events())
    wanted = [e for e in EVENTS if e in available]
    player = list(EVENT_PLAYER_PROPS)
    other = list(EVENT_OTHER_PROPS)
    try:
        result = parser.parse_events(wanted, player=player, other=other)
    except Exception as exc:  # unknown prop in this parser version -> retry with required props only
        log.warning("event parse with optional props failed (%s); retrying with required props", exc)
        result = parser.parse_events(wanted, player=sorted(REQUIRED_PROPS), other=[])
    return {name: _int64_ticks(df) for name, df in result}


def _int64_ticks(df: pd.DataFrame) -> pd.DataFrame:
    # demoparser2 returns int32 ticks; joins against our int64 ticks need one dtype.
    if "tick" in df.columns:
        df = df.assign(tick=pd.to_numeric(df["tick"], errors="coerce").astype("Int64"))
        df = df[df["tick"].notna()].astype({"tick": "int64"})
    return df


def _parse_ticks(parser, ticks: list[int]) -> pd.DataFrame:
    try:
        df = parser.parse_ticks(TICK_PROPS, ticks=ticks)
    except Exception as exc:
        log.warning("tick parse with optional props failed (%s); retrying with required props", exc)
        df = parser.parse_ticks(sorted(REQUIRED_PROPS), ticks=ticks)
    return _int64_ticks(df)


def _get(df: pd.DataFrame | None, col: str, default=np.nan) -> pd.Series:
    if df is None:
        return pd.Series(dtype=object)
    if col in df.columns:
        return df[col]
    return pd.Series([default] * len(df), index=df.index)


def _steamid(s: pd.Series) -> pd.Series:
    # SteamID64s exceed float precision; demoparser2 returns them as ints or
    # strings, which are kept exact. 0 means "no player" (e.g. world damage).
    def conv(v):
        if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
            return None
        sv = str(int(v)) if isinstance(v, (int, np.integer)) else str(v)
        return None if sv in {"0", "", "None"} else sv
    return s.map(conv)


def _speed(df: pd.DataFrame, prefix: str) -> pd.Series:
    vx = pd.to_numeric(_get(df, f"{prefix}velocity_X"), errors="coerce")
    vy = pd.to_numeric(_get(df, f"{prefix}velocity_Y"), errors="coerce")
    return np.hypot(vx, vy)


def _player_cols(df: pd.DataFrame, src: str, dst: str, weapon: pd.Series | None = None) -> dict[str, pd.Series]:
    """Map demoparser2's `<src>_<prop>` columns onto the schema's `<dst>_<field>` columns."""
    s = f"{src}_"
    return {
        f"{dst}_steamid": _steamid(_get(df, f"{s}steamid")),
        f"{dst}_name": _get(df, f"{s}name", None),
        f"{dst}_side": _get(df, f"{s}team_num").map(R.normalize_side),
        f"{dst}_x": _get(df, f"{s}X"),
        f"{dst}_y": _get(df, f"{s}Y"),
        f"{dst}_z": _get(df, f"{s}Z"),
        f"{dst}_yaw": _get(df, f"{s}yaw"),
        f"{dst}_pitch": _get(df, f"{s}pitch"),
        f"{dst}_place": _get(df, f"{s}last_place_name", None),
        f"{dst}_speed": _speed(df, s),
        f"{dst}_hp": _get(df, f"{s}health"),
        f"{dst}_armor": _get(df, f"{s}armor_value"),
        f"{dst}_scoped": _get(df, f"{s}is_scoped", None),
        f"{dst}_flash_duration": _get(df, f"{s}flash_duration"),
        f"{dst}_weapon": (weapon if weapon is not None else _get(df, f"{s}active_weapon_name", None))
        .map(weapons.normalize),
    }


# --------------------------------------------------------------------------- tables

def _kills(df: pd.DataFrame | None, rounds: pd.DataFrame, tickrate: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = R.assign_rounds(df, rounds, tickrate)
    out = pd.DataFrame({
        "round_num": df["round_num"], "tick": df["tick"], "time_s": df["time_s"], "post_round": df["post_round"],
        **_player_cols(df, "attacker", "attacker", weapon=_get(df, "weapon", None)),
        **_player_cols(df, "user", "victim"),
        "assister_steamid": _steamid(_get(df, "assister_steamid")),
        "flash_assist": _get(df, "assistedflash", None),
        "headshot": _get(df, "headshot", None),
        "penetrated": pd.to_numeric(_get(df, "penetrated"), errors="coerce") > 0,
        "through_smoke": _get(df, "thrusmoke", None),
        "attacker_blind": _get(df, "attackerblind", None),
        "noscope": _get(df, "noscope", None),
    })
    out["is_teamkill"] = out["attacker_side"].notna() & (out["attacker_side"] == out["victim_side"])
    out["distance"] = np.sqrt(
        (out["attacker_x"] - out["victim_x"]) ** 2 + (out["attacker_y"] - out["victim_y"]) ** 2
        + (out["attacker_z"] - out["victim_z"]) ** 2)
    # The victim's HP at the death tick is 0; the attacker fields are what matter.
    return out


def _damages(df: pd.DataFrame | None, rounds: pd.DataFrame, tickrate: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = R.assign_rounds(df, rounds, tickrate)
    return pd.DataFrame({
        "round_num": df["round_num"], "tick": df["tick"], "time_s": df["time_s"],
        "attacker_steamid": _steamid(_get(df, "attacker_steamid")),
        "attacker_side": _get(df, "attacker_team_num").map(R.normalize_side),
        "victim_steamid": _steamid(_get(df, "user_steamid")),
        "victim_side": _get(df, "user_team_num").map(R.normalize_side),
        "weapon": _get(df, "weapon", None).map(weapons.normalize),
        "dmg_health": _get(df, "dmg_health"),
        "dmg_armor": _get(df, "dmg_armor"),
        "health_after": _get(df, "health"),
        "hitgroup": _get(df, "hitgroup", None),
    }).dropna(subset=["victim_steamid"])


def _blinds(df: pd.DataFrame | None, rounds: pd.DataFrame, tickrate: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = R.assign_rounds(df, rounds, tickrate)
    return pd.DataFrame({
        "round_num": df["round_num"], "tick": df["tick"], "time_s": df["time_s"],
        "attacker_steamid": _steamid(_get(df, "attacker_steamid")),
        "attacker_side": _get(df, "attacker_team_num").map(R.normalize_side),
        "victim_steamid": _steamid(_get(df, "user_steamid")),
        "victim_side": _get(df, "user_team_num").map(R.normalize_side),
        "blind_duration": _get(df, "blind_duration"),
    }).dropna(subset=["victim_steamid", "blind_duration"])


_BOMB_EVENTS = {
    "bomb_beginplant": "plant_begin", "bomb_planted": "plant", "bomb_begindefuse": "defuse_begin",
    "bomb_defused": "defuse", "bomb_exploded": "explode",
}


def _site_from_place(place: object) -> str | None:
    if not isinstance(place, str):
        return None
    p = place.lower()
    if "bombsitea" in p or p in {"a", "asite", "a_site"}:
        return "A"
    if "bombsiteb" in p or p in {"b", "bsite", "b_site"}:
        return "B"
    return None


def _bomb(ev: dict[str, pd.DataFrame], rounds: pd.DataFrame, tickrate: int) -> pd.DataFrame:
    frames = []
    for name, label in _BOMB_EVENTS.items():
        df = ev.get(name)
        if df is None or df.empty:
            continue
        frames.append(pd.DataFrame({
            "tick": df["tick"], "event": label,
            "steamid": _steamid(_get(df, "user_steamid")),
            "x": _get(df, "user_X"), "y": _get(df, "user_Y"), "z": _get(df, "user_Z"),
            "place_site": _get(df, "user_last_place_name", None).map(_site_from_place),
            "site_entity": _get(df, "site"),
            "has_kit": _get(df, "haskit", None),
        }))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # The event's `site` is an entity index, not a letter. Learn index -> letter from
    # events whose player stood inside a named bombsite, then fill in the rest.
    known = df.dropna(subset=["place_site", "site_entity"]).groupby("site_entity")["place_site"].agg(
        lambda s: s.mode().iat[0])
    df["site"] = df["place_site"].fillna(df["site_entity"].map(known))
    df = R.assign_rounds(df, rounds, tickrate)
    # Defuse / explode events don't always carry a position; inherit the round's plant site.
    plant_site = df[df["event"] == "plant"].groupby("round_num")["site"].first()
    df["site"] = df["site"].fillna(df["round_num"].map(plant_site))
    return df.sort_values("tick")


def _economy_ticks(rounds: pd.DataFrame, kills: pd.DataFrame, settings: ParseSettings, tickrate: int) -> pd.DataFrame:
    t = rounds[["round_num", "freeze_end_tick", "end_tick"]].copy()
    t["tick"] = t["freeze_end_tick"] + int(settings.economy_offset_s * tickrate)
    if not kills.empty:
        first_kill = kills[~kills["post_round"]].groupby("round_num")["tick"].min()
        t["tick"] = np.minimum(t["tick"], t["round_num"].map(first_kill).fillna(np.inf) - 1)
    t["tick"] = np.minimum(np.maximum(t["tick"], t["freeze_end_tick"]), t["end_tick"]).astype("int64")
    return t[["round_num", "tick"]]


def _snapshot_ticks(rounds: pd.DataFrame, settings: ParseSettings, tickrate: int) -> pd.DataFrame:
    step = max(1, int(settings.snapshot_interval_s * tickrate))
    rows = [(r.round_num, tick) for r in rounds.itertuples()
            for tick in range(int(r.freeze_end_tick), int(r.end_tick) + 1, step)]
    return pd.DataFrame(rows, columns=["round_num", "tick"])


def _economy(df: pd.DataFrame, rounds: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.merge(rounds[["round_num", "ct_team", "t_team"]], on="round_num", how="left")
    df = df.drop_duplicates(["round_num", "steamid"])
    inv = _get(df, "inventory", None).map(
        lambda v: [w for w in (weapons.normalize(x) for x in v) if w] if isinstance(v, (list, np.ndarray)) else None)
    return pd.DataFrame({
        "round_num": df["round_num"],
        "steamid": _steamid(df["steamid"]),
        "name": _get(df, "name", None),
        "side": df["side"],
        "team": np.where(df["side"] == "CT", df["ct_team"], df["t_team"]),
        "balance": _get(df, "balance"),
        "equip_value": _get(df, "current_equip_value", 0),
        "cash_spent": _get(df, "cash_spent_this_round"),
        "armor": _get(df, "armor_value"),
        "helmet": _get(df, "has_helmet", None),
        "defuser": _get(df, "has_defuser", None),
        "inventory": inv,
    })


def _snapshots(df: pd.DataFrame, rounds: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.merge(rounds[["round_num", "freeze_end_tick", "bomb_plant_tick"]], on="round_num", how="left")
    side = df["team_num"].map(R.normalize_side)
    df = df[side.notna()].assign(side=side)
    df = df.drop_duplicates(["round_num", "tick", "steamid"])
    hp = pd.to_numeric(_get(df, "health"), errors="coerce").fillna(0)
    alive = _get(df, "is_alive", None)
    alive = alive.where(alive.notna(), hp > 0).astype(bool)
    return pd.DataFrame({
        "round_num": df["round_num"],
        "tick": df["tick"],
        "time_s": (df["tick"] - df["freeze_end_tick"]) / TICKRATE,
        "steamid": _steamid(df["steamid"]),
        "side": df["side"],
        "x": _get(df, "X"), "y": _get(df, "Y"), "z": _get(df, "Z"),
        "yaw": _get(df, "yaw"),
        "place": _get(df, "last_place_name", None),
        "hp": hp,
        "armor": _get(df, "armor_value"),
        "is_alive": alive,
        "weapon": _get(df, "active_weapon_name", None).map(weapons.normalize),
        "equip_value": _get(df, "current_equip_value"),
        "bomb_planted": df["bomb_plant_tick"].notna() & (df["tick"] >= df["bomb_plant_tick"].fillna(np.inf)),
    })


def _grenades(parser, weapon_fire: pd.DataFrame | None, rounds: pd.DataFrame, tickrate: int) -> pd.DataFrame:
    """One row per thrown grenade: who threw it, from where/how, and where it landed.

    Landing points come from projectile trajectories. Throw position and view
    angles come from the thrower's `weapon_fire` event, which is what makes a
    lineup reproducible with setpos/setang.
    """
    try:
        traj = parser.parse_grenades()
    except Exception as exc:
        log.warning("grenade trajectory parse failed: %s", exc)
        return pd.DataFrame()
    if traj is None or traj.empty:
        return pd.DataFrame()

    # The output also tracks grenades still held in hands (CSmokeGrenade) and other
    # weapons; only *Projectile entities are thrown grenades.
    traj = traj[traj["grenade_type"].astype(str).str.contains("Projectile", na=False)]
    traj = _int64_ticks(traj).rename(columns={"grenade_entity_id": "entity", "steamid": "thrower"})
    traj = traj.dropna(subset=["x", "y", "z", "tick"]).sort_values(["entity", "tick"])
    traj["thrower"] = _steamid(traj["thrower"])
    traj["kind"] = traj["grenade_type"].map(weapons.grenade_type)
    # Entity ids are reused across the match; split each id into separate flights.
    # A projectile moves < 20 units/tick, so a bigger jump means a new grenade.
    step = np.sqrt(traj["x"].diff() ** 2 + traj["y"].diff() ** 2 + traj["z"].diff() ** 2)
    jump = step / traj["tick"].diff().clip(lower=1) > 50
    new = (traj["entity"] != traj["entity"].shift()) | jump | (traj["tick"].diff() > 30 * tickrate) \
        | (traj["thrower"] != traj["thrower"].shift()) | (traj["kind"] != traj["kind"].shift())
    traj["flight"] = new.cumsum()

    def summarize(g: pd.DataFrame) -> pd.Series:
        last = g.iloc[-1]
        # Landing tick = first tick at which the projectile reached its resting place.
        d = np.sqrt((g["x"] - last["x"]) ** 2 + (g["y"] - last["y"]) ** 2 + (g["z"] - last["z"]) ** 2)
        land_tick = g.loc[d < 2.0, "tick"].iloc[0]
        return pd.Series({"throw_tick": g["tick"].iloc[0], "land_tick": land_tick, "kind": last["kind"],
                          "thrower": last["thrower"], "thrower_name": last.get("name"),
                          "land_x": last["x"], "land_y": last["y"], "land_z": last["z"],
                          "start_x": g["x"].iloc[0], "start_y": g["y"].iloc[0], "start_z": g["z"].iloc[0]})

    flights = traj.groupby("flight", sort=False).apply(summarize, include_groups=False).reset_index(drop=True)
    flights = flights[flights["kind"].notna()]

    # Attach thrower state at release from weapon_fire.
    if weapon_fire is not None and not weapon_fire.empty:
        wf = weapon_fire.copy()
        wf["kind"] = _get(wf, "weapon", None).map(weapons.grenade_type)
        wf = wf[wf["kind"].notna()]
        wf = pd.DataFrame({
            "fire_tick": wf["tick"].astype("int64"), "kind": wf["kind"],
            "thrower": _steamid(_get(wf, "user_steamid")),
            "throw_x": _get(wf, "user_X"), "throw_y": _get(wf, "user_Y"), "throw_z": _get(wf, "user_Z"),
            "throw_yaw": _get(wf, "user_yaw"), "throw_pitch": _get(wf, "user_pitch"),
            "throw_place": _get(wf, "user_last_place_name", None),
            "throw_speed": _speed(wf, "user_"),
            "throw_vertical_speed": _get(wf, "user_velocity_Z"),
            "thrower_side": _get(wf, "user_team_num").map(R.normalize_side),
        }).dropna(subset=["thrower"]).sort_values("fire_tick")
        flights = pd.merge_asof(flights.astype({"throw_tick": "int64"}).sort_values("throw_tick"), wf,
                                left_on="throw_tick", right_on="fire_tick", by=["thrower", "kind"],
                                direction="backward", tolerance=tickrate)
    for col, src in (("throw_x", "start_x"), ("throw_y", "start_y"), ("throw_z", "start_z")):
        if col not in flights:
            flights[col] = np.nan
        flights[col] = flights[col].fillna(flights[src])

    flights = R.assign_rounds(flights, rounds, tickrate, tick_col="throw_tick")
    return flights.rename(columns={"kind": "grenade_type", "thrower": "thrower_steamid",
                                   "time_s": "throw_time_s"})
