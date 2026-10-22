# Data schema

Generated from `src/csanalysis/schema.py` — do not edit by hand (`uv run python -c "from csanalysis import schema; print(schema.markdown())" > docs/data_schema.md`).

Every table is stored as `processed/<table>/<match_id>.parquet`. Coordinates are Source 2 world units; times are seconds since freeze time ended.

## `matches` — key: `match_id`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ | sha256 prefix of the demo file |
| `source` | str | ✓ | 'demo' or 'synthetic' |
| `demo_file` | str |  |  |
| `map_name` | str | ✓ |  |
| `team_a` | str | ✓ | Team that started on CT |
| `team_b` | str | ✓ | Team that started on T |
| `score_a` | int |  |  |
| `score_b` | int |  |  |
| `n_rounds` | int | ✓ |  |
| `tickrate` | int | ✓ |  |
| `server_name` | str |  |  |
| `parsed_at` | str |  |  |
| `schema_version` | int | ✓ |  |

## `rounds` — key: `match_id, round_num`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ | 1-based, in play order |
| `start_tick` | int | ✓ |  |
| `freeze_end_tick` | int | ✓ |  |
| `end_tick` | int | ✓ |  |
| `winner_side` | str | ✓ | 'CT' or 'T' |
| `reason` | str | ✓ | t_eliminated | ct_eliminated | bomb_exploded | bomb_defused | time_ran_out | surrender | other |
| `ct_team` | str | ✓ |  |
| `t_team` | str | ✓ |  |
| `ct_score` | int | ✓ | CT team's score before the round |
| `t_score` | int | ✓ |  |
| `bomb_plant_tick` | int |  |  |
| `bomb_site` | str |  | 'A' or 'B' if planted |

## `kills`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `tick` | int | ✓ |  |
| `time_s` | float | ✓ | Seconds since freeze time ended |
| `post_round` | bool | ✓ | Kill happened after the round was decided |
| `attacker_steamid` | str |  | SteamID64 as a string |
| `attacker_name` | str |  |  |
| `attacker_side` | str |  | 'CT' or 'T' |
| `attacker_x` | float |  |  |
| `attacker_y` | float |  |  |
| `attacker_z` | float |  |  |
| `attacker_yaw` | float |  |  |
| `attacker_pitch` | float |  |  |
| `attacker_place` | str |  | Map callout from the navmesh, e.g. 'BombsiteA' |
| `attacker_speed` | float |  | Horizontal speed in units/s |
| `attacker_hp` | int |  | Health at the event tick |
| `attacker_armor` | int |  |  |
| `attacker_scoped` | bool |  |  |
| `attacker_flash_duration` | float |  | Remaining blind time in seconds |
| `attacker_weapon` | str |  | Weapon that made the kill |
| `victim_steamid` | str |  | SteamID64 as a string |
| `victim_name` | str |  |  |
| `victim_side` | str |  | 'CT' or 'T' |
| `victim_x` | float |  |  |
| `victim_y` | float |  |  |
| `victim_z` | float |  |  |
| `victim_yaw` | float |  |  |
| `victim_pitch` | float |  |  |
| `victim_place` | str |  | Map callout from the navmesh, e.g. 'BombsiteA' |
| `victim_speed` | float |  | Horizontal speed in units/s |
| `victim_hp` | int |  | Health at the event tick |
| `victim_armor` | int |  |  |
| `victim_scoped` | bool |  |  |
| `victim_flash_duration` | float |  | Remaining blind time in seconds |
| `victim_weapon` | str |  | Weapon the victim was holding |
| `assister_steamid` | str |  |  |
| `flash_assist` | bool |  |  |
| `headshot` | bool |  |  |
| `penetrated` | bool |  | Wallbang |
| `through_smoke` | bool |  |  |
| `attacker_blind` | bool |  |  |
| `noscope` | bool |  |  |
| `is_teamkill` | bool |  |  |
| `distance` | float |  | 3D distance between attacker and victim |

## `damages`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `tick` | int | ✓ |  |
| `time_s` | float | ✓ |  |
| `attacker_steamid` | str |  |  |
| `attacker_side` | str |  |  |
| `victim_steamid` | str | ✓ |  |
| `victim_side` | str |  |  |
| `weapon` | str |  |  |
| `dmg_health` | int | ✓ |  |
| `dmg_armor` | int |  |  |
| `health_after` | int |  |  |
| `hitgroup` | str |  |  |

## `grenades`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `grenade_type` | str | ✓ | smoke | flash | he | molotov | decoy |
| `thrower_steamid` | str |  |  |
| `thrower_name` | str |  |  |
| `thrower_side` | str |  |  |
| `throw_tick` | int | ✓ |  |
| `throw_time_s` | float | ✓ |  |
| `throw_x` | float |  | Thrower position at release (setpos) |
| `throw_y` | float |  |  |
| `throw_z` | float |  |  |
| `throw_yaw` | float |  | Thrower view angles at release (setang) |
| `throw_pitch` | float |  |  |
| `throw_place` | str |  |  |
| `throw_speed` | float |  |  |
| `throw_vertical_speed` | float |  | Non-zero for jump throws |
| `land_tick` | int |  |  |
| `land_x` | float | ✓ |  |
| `land_y` | float | ✓ |  |
| `land_z` | float | ✓ |  |

## `blinds`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `tick` | int | ✓ |  |
| `time_s` | float | ✓ |  |
| `attacker_steamid` | str |  |  |
| `attacker_side` | str |  |  |
| `victim_steamid` | str | ✓ |  |
| `victim_side` | str |  |  |
| `blind_duration` | float | ✓ |  |

## `bomb`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `tick` | int | ✓ |  |
| `time_s` | float | ✓ |  |
| `event` | str | ✓ | plant_begin | plant | defuse_begin | defuse | explode |
| `steamid` | str |  |  |
| `x` | float |  |  |
| `y` | float |  |  |
| `z` | float |  |  |
| `site` | str |  |  |
| `has_kit` | bool |  |  |

## `economy` — key: `match_id, round_num, steamid`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `steamid` | str | ✓ |  |
| `name` | str |  |  |
| `side` | str | ✓ |  |
| `team` | str | ✓ |  |
| `balance` | int |  | Money left after buying |
| `equip_value` | int | ✓ | Value of everything the player carries |
| `cash_spent` | int |  |  |
| `armor` | int |  |  |
| `helmet` | bool |  |  |
| `defuser` | bool |  |  |
| `inventory` | str_list |  |  |

## `snapshots` — key: `match_id, round_num, tick, steamid`

| column | type | required | description |
|---|---|---|---|
| `match_id` | str | ✓ |  |
| `round_num` | int | ✓ |  |
| `tick` | int | ✓ |  |
| `time_s` | float | ✓ |  |
| `steamid` | str | ✓ |  |
| `side` | str | ✓ |  |
| `x` | float |  |  |
| `y` | float |  |  |
| `z` | float |  |  |
| `yaw` | float |  |  |
| `place` | str |  |  |
| `hp` | int | ✓ |  |
| `armor` | int |  |  |
| `is_alive` | bool | ✓ |  |
| `weapon` | str |  |  |
| `equip_value` | int |  |  |
| `bomb_planted` | bool | ✓ |  |

