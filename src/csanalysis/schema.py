"""Canonical table schemas.

Every producer of data (the real demo parser and the synthetic generator) emits
tables in exactly this shape, and every analysis consumes them. Keeping the
contract in one place is what lets the analyses be tested on synthetic data with
known ground truth and then run unchanged on real demos.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pyarrow as pa

# Column kinds -> pyarrow types. Everything is nullable at the storage level;
# `required` columns are additionally checked for nulls in `validate`.
_ARROW = {
    "int": pa.int64(),
    "float": pa.float64(),
    "str": pa.string(),
    "bool": pa.bool_(),
    "str_list": pa.list_(pa.string()),
}
_PANDAS = {
    "int": "Int64",
    "float": "float64",
    "str": "string",
    "bool": "boolean",
    "str_list": "object",
}


@dataclass(frozen=True)
class Col:
    name: str
    kind: str
    required: bool = False
    doc: str = ""


def _player(prefix: str, *, weapon_doc: str) -> list[Col]:
    p = prefix
    return [
        Col(f"{p}_steamid", "str", doc="SteamID64 as a string"),
        Col(f"{p}_name", "str"),
        Col(f"{p}_side", "str", doc="'CT' or 'T'"),
        Col(f"{p}_x", "float"),
        Col(f"{p}_y", "float"),
        Col(f"{p}_z", "float"),
        Col(f"{p}_yaw", "float"),
        Col(f"{p}_pitch", "float"),
        Col(f"{p}_place", "str", doc="Map callout from the navmesh, e.g. 'BombsiteA'"),
        Col(f"{p}_speed", "float", doc="Horizontal speed in units/s"),
        Col(f"{p}_hp", "int", doc="Health at the event tick"),
        Col(f"{p}_armor", "int"),
        Col(f"{p}_scoped", "bool"),
        Col(f"{p}_flash_duration", "float", doc="Remaining blind time in seconds"),
        Col(f"{p}_weapon", "str", doc=weapon_doc),
    ]


TABLES: dict[str, list[Col]] = {
    "matches": [
        Col("match_id", "str", True, "sha256 prefix of the demo file"),
        Col("source", "str", True, "'demo' or 'synthetic'"),
        Col("demo_file", "str"),
        Col("map_name", "str", True),
        Col("team_a", "str", True, "Team that started on CT"),
        Col("team_b", "str", True, "Team that started on T"),
        Col("score_a", "int"),
        Col("score_b", "int"),
        Col("n_rounds", "int", True),
        Col("tickrate", "int", True),
        Col("server_name", "str"),
        Col("parsed_at", "str"),
        Col("schema_version", "int", True),
    ],
    "rounds": [
        Col("match_id", "str", True),
        Col("round_num", "int", True, "1-based, in play order"),
        Col("start_tick", "int", True),
        Col("freeze_end_tick", "int", True),
        Col("end_tick", "int", True),
        Col("winner_side", "str", True, "'CT' or 'T'"),
        Col("reason", "str", True,
            "t_eliminated | ct_eliminated | bomb_exploded | bomb_defused | time_ran_out | surrender | other"),
        Col("ct_team", "str", True),
        Col("t_team", "str", True),
        Col("ct_score", "int", True, "CT team's score before the round"),
        Col("t_score", "int", True),
        Col("bomb_plant_tick", "int"),
        Col("bomb_site", "str", doc="'A' or 'B' if planted"),
    ],
    "kills": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("tick", "int", True),
        Col("time_s", "float", True, "Seconds since freeze time ended"),
        Col("post_round", "bool", True, "Kill happened after the round was decided"),
        *_player("attacker", weapon_doc="Weapon that made the kill"),
        *_player("victim", weapon_doc="Weapon the victim was holding"),
        Col("assister_steamid", "str"),
        Col("flash_assist", "bool"),
        Col("headshot", "bool"),
        Col("penetrated", "bool", doc="Wallbang"),
        Col("through_smoke", "bool"),
        Col("attacker_blind", "bool"),
        Col("noscope", "bool"),
        Col("is_teamkill", "bool"),
        Col("distance", "float", doc="3D distance between attacker and victim"),
    ],
    "damages": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("tick", "int", True),
        Col("time_s", "float", True),
        Col("attacker_steamid", "str"),
        Col("attacker_side", "str"),
        Col("victim_steamid", "str", True),
        Col("victim_side", "str"),
        Col("weapon", "str"),
        Col("dmg_health", "int", True),
        Col("dmg_armor", "int"),
        Col("health_after", "int"),
        Col("hitgroup", "str"),
    ],
    "grenades": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("grenade_type", "str", True, "smoke | flash | he | molotov | decoy"),
        Col("thrower_steamid", "str"),
        Col("thrower_name", "str"),
        Col("thrower_side", "str"),
        Col("throw_tick", "int", True),
        Col("throw_time_s", "float", True),
        Col("throw_x", "float", doc="Thrower position at release (setpos)"),
        Col("throw_y", "float"),
        Col("throw_z", "float"),
        Col("throw_yaw", "float", doc="Thrower view angles at release (setang)"),
        Col("throw_pitch", "float"),
        Col("throw_place", "str"),
        Col("throw_speed", "float"),
        Col("throw_vertical_speed", "float", doc="Non-zero for jump throws"),
        Col("land_tick", "int"),
        Col("land_x", "float", True),
        Col("land_y", "float", True),
        Col("land_z", "float", True),
    ],
    "blinds": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("tick", "int", True),
        Col("time_s", "float", True),
        Col("attacker_steamid", "str"),
        Col("attacker_side", "str"),
        Col("victim_steamid", "str", True),
        Col("victim_side", "str"),
        Col("blind_duration", "float", True),
    ],
    "bomb": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("tick", "int", True),
        Col("time_s", "float", True),
        Col("event", "str", True, "plant_begin | plant | defuse_begin | defuse | explode"),
        Col("steamid", "str"),
        Col("x", "float"),
        Col("y", "float"),
        Col("z", "float"),
        Col("site", "str"),
        Col("has_kit", "bool"),
    ],
    "economy": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("steamid", "str", True),
        Col("name", "str"),
        Col("side", "str", True),
        Col("team", "str", True),
        Col("balance", "int", doc="Money left after buying"),
        Col("equip_value", "int", True, "Value of everything the player carries"),
        Col("cash_spent", "int"),
        Col("armor", "int"),
        Col("helmet", "bool"),
        Col("defuser", "bool"),
        Col("inventory", "str_list"),
    ],
    "snapshots": [
        Col("match_id", "str", True),
        Col("round_num", "int", True),
        Col("tick", "int", True),
        Col("time_s", "float", True),
        Col("steamid", "str", True),
        Col("side", "str", True),
        Col("x", "float"),
        Col("y", "float"),
        Col("z", "float"),
        Col("yaw", "float"),
        Col("place", "str"),
        Col("hp", "int", True),
        Col("armor", "int"),
        Col("is_alive", "bool", True),
        Col("weapon", "str"),
        Col("equip_value", "int"),
        Col("bomb_planted", "bool", True),
    ],
}

# Natural key of each table, used for duplicate detection.
KEYS: dict[str, list[str]] = {
    "matches": ["match_id"],
    "rounds": ["match_id", "round_num"],
    "economy": ["match_id", "round_num", "steamid"],
    "snapshots": ["match_id", "round_num", "tick", "steamid"],
}


class SchemaError(ValueError):
    pass


def columns(table: str) -> list[str]:
    return [c.name for c in TABLES[table]]


def arrow_schema(table: str) -> pa.Schema:
    return pa.schema([pa.field(c.name, _ARROW[c.kind]) for c in TABLES[table]])


def empty(table: str) -> pd.DataFrame:
    return coerce(pd.DataFrame(), table)


def coerce(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Return `df` with exactly the schema's columns, order and dtypes.

    Missing columns are added as nulls; unknown columns are dropped.
    """
    out = {}
    n = len(df)
    for col in TABLES[table]:
        s = df[col.name] if col.name in df.columns else pd.Series([None] * n, index=df.index)
        out[col.name] = _coerce_series(s, col)
    return pd.DataFrame(out, index=df.index).reset_index(drop=True)


def _isna(v: object) -> bool:
    return v is None or (pd.api.types.is_scalar(v) and pd.isna(v))


def _coerce_series(s: pd.Series, col: Col) -> pd.Series:
    if col.kind == "str_list":
        return s.map(lambda v: None if _isna(v) else [str(x) for x in v]).astype(object)
    if col.kind == "str":
        # Normalise ints such as steamids to strings without a trailing ".0".
        def to_str(v):
            if _isna(v):
                return None
            if isinstance(v, float) and v.is_integer():
                return str(int(v))
            return str(v)

        return s.map(to_str).astype("string")
    if col.kind == "int":
        return pd.to_numeric(s, errors="coerce").round().astype("Int64")
    if col.kind == "float":
        return pd.to_numeric(s, errors="coerce").astype("float64")
    if col.kind == "bool":
        return s.map(lambda v: None if _isna(v) else bool(v)).astype("boolean")
    raise ValueError(f"unknown column kind {col.kind!r}")


def validate(df: pd.DataFrame, table: str) -> None:
    """Raise SchemaError if `df` does not satisfy the table contract."""
    problems = []
    expected = columns(table)
    if list(df.columns) != expected:
        missing = set(expected) - set(df.columns)
        extra = set(df.columns) - set(expected)
        problems.append(f"columns differ (missing={sorted(missing)}, extra={sorted(extra)})")
    for col in TABLES[table]:
        if col.name not in df.columns:
            continue
        s = df[col.name]
        want = _PANDAS[col.kind]
        if str(s.dtype) != want and not (col.kind == "str" and isinstance(s.dtype, pd.StringDtype)):
            problems.append(f"{col.name}: dtype {s.dtype}, expected {want}")
        if col.required and s.isna().any():
            problems.append(f"{col.name}: {int(s.isna().sum())} nulls in required column")
        if col.name.endswith("side") and s.notna().any():
            bad = set(s.dropna().unique()) - {"CT", "T"}
            if bad:
                problems.append(f"{col.name}: invalid sides {sorted(bad)}")
    key = KEYS.get(table)
    if key and all(k in df.columns for k in key) and df.duplicated(key).any():
        problems.append(f"duplicate rows for key {key}: {int(df.duplicated(key).sum())}")
    if problems:
        raise SchemaError(f"table {table!r}: " + "; ".join(problems))


def markdown() -> str:
    """Render the schema as Markdown (docs/data_schema.md is generated from this)."""
    lines = ["# Data schema", "",
             "Generated from `src/csanalysis/schema.py` — do not edit by hand "
             "(`uv run python -c \"from csanalysis import schema; print(schema.markdown())\" > docs/data_schema.md`).",
             "", "Every table is stored as `processed/<table>/<match_id>.parquet`. "
             "Coordinates are Source 2 world units; times are seconds since freeze time ended.", ""]
    for name, cols in TABLES.items():
        key = f" — key: `{', '.join(KEYS[name])}`" if name in KEYS else ""
        lines += [f"## `{name}`{key}", "", "| column | type | required | description |", "|---|---|---|---|"]
        lines += [f"| `{c.name}` | {c.kind} | {'✓' if c.required else ''} | {c.doc} |" for c in cols]
        lines.append("")
    return "\n".join(lines)
