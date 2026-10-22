"""Synthetic match generator with known ground truth.

Simulates matches at the level of duels, utility and economy and emits exactly
the same tables as the real demo parser. Effects are *planted* in the
simulation (a smoke that helps T win duels, a CT spot with a built-in duel
advantage, armor mattering on eco rounds, ...) and written to
`ground_truth.json`, so every analysis can be tested on whether it recovers
effects we know are real, including when they are confounded by economy the way
they are in real games (full-buy teams also have the utility).

The simulation is deliberately simple and is not a model of real CS2 balance.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from csanalysis import weapons
from csanalysis.config import SCHEMA_VERSION, TICKRATE, Paths
from csanalysis.parsing import rounds as R
from csanalysis.storage import MatchData, write_match

ROUND_TIME_S = 115.0
BOMB_TIME_S = 40.0
FREEZE_S = 20.0
SMOKE_DURATION_S = 18.0

# Effects shared by every synthetic map (logit units on "T wins the duel").
GLOBAL_TRUTH = {
    "weapon_strength": {"pistol": 0.0, "deagle": 0.45, "smg": 0.55, "shotgun": 0.4, "rifle": 1.2,
                        "sniper": 1.35, "knife": -3.0},
    "armor_effect": 0.5,          # per side: duel bonus when you have armor and the opponent doesn't
    "hp_effect": 1.0,             # per 100 HP difference
    "moving_penalty": 0.6,        # shooting while moving faster than 110 u/s
    "flash_effect": 0.35,         # T duel bonus while a T flash has just popped on site
    "eco_rush_effect": 0.4,       # T eco rounds that rush together get this bonus in duels
    "postplant_t_bonus": 0.3,
    "ct_hold_bonus": 0.7,         # defenders holding a site before the plant
}


@dataclass
class Spot:
    id: str
    side: str
    area: str            # 'A', 'B' or 'mid'
    x: float
    y: float
    advantage: float     # planted duel advantage (logit) for a player holding this spot


@dataclass
class Smoke:
    id: str
    side: str
    site: str
    land_x: float
    land_y: float
    throw_x: float
    throw_y: float
    yaw: float
    pitch: float
    effect: float        # planted duel bonus (logit) for the throwing side while it is up


@dataclass
class SynthMap:
    name: str
    t_spawn: tuple[float, float]
    ct_spawn: tuple[float, float]
    sites: dict[str, tuple[float, float]]
    site_t_bias: dict[str, float]     # T duel bonus at each site (site "difficulty")
    p_site_a: float
    places: list[tuple[str, float, float, float, float]]
    spots: list[Spot] = field(default_factory=list)
    smokes: list[Smoke] = field(default_factory=list)

    def place(self, x: float, y: float) -> str:
        for name, x0, y0, x1, y1 in self.places:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return "Middle"

    def truth(self) -> dict:
        return {"site_t_bias": self.site_t_bias, "p_site_a": self.p_site_a,
                "sites": self.sites, "spots": [asdict(s) for s in self.spots],
                "smokes": [asdict(s) for s in self.smokes]}


def build_maps(seed: int = 7) -> dict[str, SynthMap]:
    rng = np.random.default_rng(seed)
    maps = {}
    for i, name in enumerate(["de_synth_alpha", "de_synth_bravo", "de_synth_charlie"]):
        a = (-1300.0 + 100 * i, 900.0)
        b = (1300.0 - 80 * i, 1000.0)
        m = SynthMap(
            name=name, t_spawn=(0.0, -2000.0), ct_spawn=(0.0, 1800.0), sites={"A": a, "B": b},
            site_t_bias={"A": round(float(rng.normal(0, 0.35)), 3), "B": round(float(rng.normal(0, 0.35)), 3)},
            p_site_a=round(float(rng.uniform(0.4, 0.65)), 3),
            places=[
                ("TSpawn", -700, -2400, 700, -1500), ("CTSpawn", -500, 1500, 500, 2200),
                ("BombsiteA", a[0] - 350, a[1] - 300, a[0] + 350, a[1] + 300),
                ("BombsiteB", b[0] - 350, b[1] - 300, b[0] + 350, b[1] + 300),
                ("ARamp", -1700, -1500, -900, 600), ("BTunnels", 900, -1500, 1700, 700),
                ("ConnectorA", -950, 1200, -500, 1500), ("ConnectorB", 500, 1300, 950, 1600),
                ("Mid", -400, -700, 400, 700),
            ],
        )
        for site, (sx, sy) in m.sites.items():
            sgn = -1 if site == "A" else 1
            # Three CT spots per site, two T approach spots, with planted advantages.
            for j, (dx, dy) in enumerate([(-200, 250), (220, 180), (0, 420)]):
                m.spots.append(Spot(f"{name}:{site}:ct{j}", "CT", site, sx + dx, sy + dy,
                                    round(float(rng.normal(0, 0.45)), 3)))
            for j, (dx, dy) in enumerate([(-120, -900), (150, -750)]):
                m.spots.append(Spot(f"{name}:{site}:t{j}", "T", site, sx + dx, sy + dy,
                                    round(float(rng.normal(0, 0.3)), 3)))
            # T smokes: one big, one medium, one useless. One CT smoke.
            effects = rng.permutation([0.7, 0.3, 0.0])
            for j, ((lx, ly), eff) in enumerate(zip([(sx + 250 * -sgn, sy + 450), (sx - 300 * -sgn, sy + 200),
                                                     (sx, sy - 250)], effects, strict=True)):
                tx, ty = sx + 100 * j, sy - 1100
                m.smokes.append(Smoke(f"{name}:{site}:tsmoke{j}", "T", site, lx, ly, tx, ty,
                                      yaw=math.degrees(math.atan2(ly - ty, lx - tx)),
                                      pitch=-round(float(rng.uniform(20, 50)), 1), effect=float(eff)))
            lx, ly = sx, sy - 700
            tx, ty = sx + 80, sy + 450
            m.smokes.append(Smoke(f"{name}:{site}:ctsmoke0", "CT", site, lx, ly, tx, ty,
                                  yaw=math.degrees(math.atan2(ly - ty, lx - tx)), pitch=-10.0, effect=0.4))
        m.spots.append(Spot(f"{name}:mid:ct0", "CT", "mid", 0, 500, round(float(rng.normal(0, 0.45)), 3)))
        m.spots.append(Spot(f"{name}:mid:t0", "T", "mid", 0, -500, round(float(rng.normal(0, 0.3)), 3)))
        maps[name] = m
    return maps


# --------------------------------------------------------------------------- players & economy

@dataclass
class Player:
    steamid: str
    name: str
    money: int = 800
    primary: str | None = None
    pistol: str = "glock"
    armor: int = 0
    helmet: bool = False
    kit: bool = False
    nades: list[str] = field(default_factory=list)
    # per-round state
    alive: bool = True
    hp: int = 100
    side: str = "CT"
    waypoints: list[tuple[float, float, float]] = field(default_factory=list)
    hp_log: list[tuple[float, int]] = field(default_factory=list)
    death_t: float = math.inf
    spot: Spot | None = None

    @property
    def weapon(self) -> str:
        return self.primary or self.pistol

    def equip_value(self) -> int:
        v = weapons.price(self.primary) + weapons.price(self.pistol)
        v += (650 if self.armor else 0) + (350 if self.helmet else 0) + (400 if self.kit else 0)
        return v + sum(weapons.price(n) for n in self.nades)

    def die(self) -> None:
        self.alive = False
        self.primary = None
        self.armor, self.helmet, self.kit, self.nades = 0, False, False, []
        self.pistol = "usp_silencer" if self.side == "CT" else "glock"

    def pos(self, t: float) -> tuple[float, float]:
        wp = sorted(self.waypoints, key=lambda w: w[0])
        ts = [w[0] for w in wp]
        t = min(t, self.death_t)
        return float(np.interp(t, ts, [w[1] for w in wp])), float(np.interp(t, ts, [w[2] for w in wp]))

    def hp_at(self, t: float) -> int:
        hp = 100
        for ti, h in self.hp_log:
            if ti <= t:
                hp = h
        return hp if t < self.death_t else 0


def _buy(p: Player, side: str, mode: str, rng: np.random.Generator, awper: bool) -> None:
    def spend(item: str, cost: int) -> bool:
        if p.money >= cost:
            p.money -= cost
            if item in weapons.GRENADE_TYPES:
                p.nades.append(item)
            return True
        return False

    if mode == "pistol":
        choice = rng.choice(["armor", "p250", "util"])
        if choice == "armor" and spend("armor", 650):
            p.armor = 100
        elif choice == "p250" and spend("p250", 300):
            p.pistol = "p250"
            spend("flashbang", 200)
        else:
            spend("smokegrenade", 300)
            spend("flashbang", 200)
        return
    if mode == "eco":
        if rng.random() < 0.3 and spend("p250", 300):
            p.pistol = "p250"
        if rng.random() < 0.25 and spend("armor", 650):
            p.armor = 100
        return
    # force & full
    if not p.armor and spend("armor", 650):
        p.armor = 100
    if mode == "full" and p.armor and not p.helmet and spend("helmet", 350):
        p.helmet = True
    if p.primary is None:
        if mode == "full":
            options = [("awp", 4750)] if awper else []
            options += [("ak47", 2700)] if side == "T" else [("m4a1_silencer", 2900), ("m4a1", 3100)]
            for item, cost in options:
                if spend(item, cost):
                    p.primary = item
                    break
        else:
            options = [("galilar", 1800), ("mac10", 1050)] if side == "T" else [("famas", 2050), ("mp9", 1250)]
            for item, cost in [*options, ("deagle", 700)]:
                if spend(item, cost):
                    if item == "deagle":
                        p.pistol = item
                    else:
                        p.primary = item
                    break
    if side == "CT" and mode == "full" and not p.kit and rng.random() < 0.5 and spend("kit", 400):
        p.kit = True
    molly = ("molotov", 400) if side == "T" else ("incgrenade", 500)
    for nade, cost in (("smokegrenade", 300), ("flashbang", 200), molly, ("flashbang", 200)):
        already = p.nades.count(nade)
        if already >= (2 if nade == "flashbang" else 1) or len(p.nades) >= 4:
            continue
        if mode == "full" or rng.random() < 0.4:
            spend(nade, cost)


def _strength(w: str) -> float:
    s = GLOBAL_TRUTH["weapon_strength"]
    if w == "deagle":
        return s["deagle"]
    return s.get(weapons.weapon_class(w) or "pistol", 0.0)


# --------------------------------------------------------------------------- simulation

class MatchSim:
    def __init__(self, m: SynthMap, team_a: tuple[str, list[Player]], team_b: tuple[str, list[Player]],
                 rng: np.random.Generator, match_id: str):
        self.m, self.rng, self.match_id = m, rng, match_id
        self.teams = {"A": team_a, "B": team_b}
        self.rows: dict[str, list[dict]] = {k: [] for k in
                                            ("rounds", "kills", "damages", "grenades", "blinds", "bomb", "economy",
                                             "snapshots")}
        self.tick = 1000
        self.loss_streak = {"A": 0, "B": 0}

    def ct_key(self, r: int) -> str:
        half = (r - 1) // 12 if r <= 24 else 2 + (r - 25) // 3
        return "A" if half % 2 == 0 else "B"

    def run(self) -> MatchData:
        score = {"A": 0, "B": 0}
        r = 0
        while True:
            r += 1
            first_of_half = r in (1, 13) or (r > 24 and (r - 25) % 3 == 0)
            if first_of_half:
                start_money = 800 if r <= 24 else 12500
                for _, players in self.teams.values():
                    for p in players:
                        p.money, p.primary, p.armor, p.helmet, p.kit, p.nades = start_money, None, 0, False, False, []
                self.loss_streak = {"A": 0, "B": 0} if r <= 24 else {"A": 1, "B": 1}
            winner_key = self.play_round(r, score, pistol=first_of_half and r <= 24)
            score[winner_key] += 1
            if r <= 24 and max(score.values()) >= 13:
                break
            if r > 24:
                block = (r - 25) // 6
                target = 16 + 3 * block
                if max(score.values()) >= target:
                    break
        return self.to_match(score)

    def play_round(self, r: int, score: dict, pistol: bool) -> str:
        rng = self.rng
        ctk = self.ct_key(r)
        tk = "B" if ctk == "A" else "A"
        ct_name, cts = self.teams[ctk]
        t_name, ts = self.teams[tk]
        for p in cts:
            p.side = "CT"
        for p in ts:
            p.side = "T"
            p.pistol = "glock" if p.pistol == "usp_silencer" else p.pistol
        for p in cts:
            p.pistol = "usp_silencer" if p.pistol == "glock" else p.pistol

        modes = {}
        for side, players in (("CT", cts), ("T", ts)):
            avg = np.mean([p.money + (2700 if p.primary else 0) for p in players])
            if pistol:
                mode = "pistol"
            elif avg >= (4300 if side == "CT" else 3900):
                mode = "full"
            else:
                p_force = 0.55 if avg >= 2600 else (0.3 if avg >= 1800 else 0.12)
                mode = "force" if rng.random() < p_force else "eco"
            modes[side] = mode
            awper = int(rng.integers(0, 5))
            for i, p in enumerate(players):
                p.alive, p.hp, p.death_t, p.hp_log, p.spot = True, 100, math.inf, [], None
                _buy(p, side, mode, rng, awper=(i == awper))

        freeze_end = self.tick + int(FREEZE_S * TICKRATE)
        start_tick = self.tick
        econ = [{"round_num": r, "steamid": p.steamid, "name": p.name, "side": p.side,
                 "team": ct_name if p.side == "CT" else t_name, "balance": p.money,
                 "equip_value": p.equip_value(), "cash_spent": None, "armor": p.armor, "helmet": p.helmet,
                 "defuser": p.kit, "inventory": [w for w in [p.primary, p.pistol, *p.nades] if w]}
                for p in cts + ts]
        self.rows["economy"].extend(econ)

        outcome = self.simulate(r, cts, ts, modes, freeze_end)
        winner_side, reason, end_t, plant_t, site = outcome
        end_tick = freeze_end + int(end_t * TICKRATE)
        self.rows["rounds"].append({
            "round_num": r, "start_tick": start_tick, "freeze_end_tick": freeze_end, "end_tick": end_tick,
            "winner_side": winner_side, "reason": reason, "ct_team": ct_name, "t_team": t_name,
            "ct_score": score[ctk], "t_score": score[tk],
            "bomb_plant_tick": freeze_end + int(plant_t * TICKRATE) if plant_t is not None else None,
            "bomb_site": site if plant_t is not None else None,
        })
        self.snapshots(r, cts + ts, freeze_end, end_t, plant_t)

        # Economy after the round.
        win_key = ctk if winner_side == "CT" else tk
        lose_key = tk if win_key == ctk else ctk
        win_bonus = 3500 if reason in ("bomb_exploded", "bomb_defused") else 3250
        self.loss_streak[lose_key] = min(self.loss_streak[lose_key] + 1, 5)
        self.loss_streak[win_key] = max(self.loss_streak[win_key] - 1, 0)
        loss_bonus = 1400 + 500 * (self.loss_streak[lose_key] - 1)
        for p in self.teams[win_key][1]:
            p.money = min(16000, p.money + win_bonus)
        for p in self.teams[lose_key][1]:
            # Losing T players that survived without the bomb exploding get nothing in CS2.
            survived_t_timeout = p.side == "T" and p.alive and reason == "time_ran_out"
            bonus = 0 if survived_t_timeout else loss_bonus + (800 if p.side == "T" and plant_t is not None else 0)
            p.money = min(16000, p.money + bonus)
        self.tick = end_tick + 7 * TICKRATE
        return win_key

    # -- core round simulation -------------------------------------------------------------
    def simulate(self, r, cts, ts, modes, freeze_end):
        rng, m, G = self.rng, self.m, GLOBAL_TRUTH
        site = "A" if rng.random() < m.p_site_a else "B"
        t_save = modes["T"] == "eco" and rng.random() < 0.3
        rush = modes["T"] == "eco" and not t_save and rng.random() < 0.5
        execute_t = float(rng.uniform(12, 22)) if rush else float(rng.uniform(35, 80))

        ct_spots = {a: [s for s in m.spots if s.side == "CT" and s.area == a] for a in ("A", "B", "mid")}
        t_spots = [s for s in m.spots if s.side == "T" and s.area == site]
        # CT setup: 2 A, 2 B, 1 mid.
        areas = ["A", "A", "B", "B", "mid"]
        rng.shuffle(areas)
        for p, area in zip(cts, areas, strict=True):
            p.spot = ct_spots[area][int(rng.integers(len(ct_spots[area])))]
            p.waypoints = [(0, *m.ct_spawn), (12, p.spot.x, p.spot.y)]
        sx, sy = m.sites[site]
        for p in ts:
            p.spot = t_spots[int(rng.integers(len(t_spots)))]
            if t_save:
                p.waypoints = [(0, *m.t_spawn), (20, m.t_spawn[0] + rng.normal(0, 200), m.t_spawn[1] + 300)]
            else:
                p.waypoints = [(0, *m.t_spawn), (max(execute_t - 5, 6), p.spot.x, p.spot.y),
                               (execute_t + 4, sx + rng.normal(0, 120), sy + rng.normal(0, 120))]
        kills_by: dict[str, int] = {}

        active_smokes: list[tuple[Smoke, float]] = []
        flash_windows: list[float] = []
        if not t_save:
            self.throw_utility(r, ts, cts, site, execute_t, freeze_end, active_smokes, flash_windows)

        def duel(t: float, ct: Player, tp: Player, area: str, postplant: bool = False) -> None:
            ct_w, t_w = ct.weapon, tp.weapon
            ct_speed = 0.0 if rng.random() < 0.8 else float(rng.uniform(150, 250))
            t_speed = 0.0 if rng.random() < 0.55 else float(rng.uniform(150, 250))
            logit = (_strength(t_w) - _strength(ct_w)
                     + G["armor_effect"] * ((tp.armor > 0) - (ct.armor > 0))
                     + G["hp_effect"] * (tp.hp - ct.hp) / 100
                     - G["moving_penalty"] * ((t_speed > 110) - (ct_speed > 110)))
            if area in ("A", "B"):
                logit += m.site_t_bias[area]
            if not postplant and ct.spot is not None and ct.spot.area == area:
                logit -= ct.spot.advantage + G["ct_hold_bonus"]
            if not postplant and tp.spot is not None and area == site:
                logit += tp.spot.advantage
            if postplant:
                logit += G["postplant_t_bonus"]
            for s, land_t in active_smokes:
                if s.site == area and land_t <= t <= land_t + SMOKE_DURATION_S:
                    logit += s.effect if s.side == "T" else -s.effect
            if any(ft <= t <= ft + 2.5 for ft in flash_windows) and area == site:
                logit += G["flash_effect"]
            if rush:
                logit += G["eco_rush_effect"]
            t_wins = rng.random() < 1 / (1 + math.exp(-logit))
            win, lose = (tp, ct) if t_wins else (ct, tp)
            win_speed, lose_speed = (t_speed, ct_speed) if t_wins else (ct_speed, t_speed)
            self.kill(r, t, freeze_end, win, lose, win_speed, lose_speed)
            kills_by[win.steamid] = kills_by.get(win.steamid, 0) + 1

        alive = lambda ps: [p for p in ps if p.alive]  # noqa: E731
        t = 0.0
        # Early-round picks in mid.
        for _ in range(int(rng.poisson(1.0))):
            t = float(rng.uniform(8, max(9, min(execute_t - 4, 30))))
            mids = [p for p in alive(cts) if p.spot and p.spot.area == "mid"] or alive(cts)
            if mids and alive(ts):
                tp = alive(ts)[int(rng.integers(len(alive(ts))))]
                duel(t, mids[0], tp, "mid")
        if t_save:
            t = max(t, 60.0)
            while alive(ts) and alive(cts) and t < ROUND_TIME_S - 5:
                t += float(rng.exponential(12))
                if t >= ROUND_TIME_S - 5 or rng.random() < 0.5:
                    break
                duel(t, alive(cts)[0], alive(ts)[0], "spawn")
            if not alive(ts):
                return "CT", "t_eliminated", t + 0.5, None, site
            if not alive(cts):
                return "T", "ct_eliminated", t + 0.5, None, site
            return "CT", "time_ran_out", ROUND_TIME_S, None, site

        # Execute: fight the CTs on site, rotators join after 12s.
        t = max(t, execute_t)
        plant_t = None
        while alive(ts) and alive(cts):
            t += float(rng.exponential(2.5))
            on_site = [p for p in alive(cts) if p.spot and p.spot.area == site]
            if not on_site and plant_t is None:
                plant_t = t + 3.0
                t = plant_t
                for p in alive(ts):
                    p.waypoints.append((plant_t, sx + rng.normal(0, 200), sy + rng.normal(0, 200)))
                continue
            if plant_t is None:
                ct = on_site[0]
            else:
                if t > plant_t + BOMB_TIME_S:
                    return "T", "bomb_exploded", plant_t + BOMB_TIME_S, plant_t, site
                # Outnumbered CTs often give up the retake and save their weapons.
                if len(alive(cts)) + 1 < len(alive(ts)) and rng.random() < 0.15:
                    return "T", "bomb_exploded", plant_t + BOMB_TIME_S, plant_t, site
                ct = alive(cts)[0]
                if t < execute_t + 12:
                    t = execute_t + 12
            for p in alive(cts):
                if p.spot and p.spot.area != site and len(p.waypoints) < 3 and t >= execute_t:
                    p.waypoints.append((execute_t + 12, sx + rng.normal(0, 150), sy + 400 + rng.normal(0, 150)))
                    p.spot = None if plant_t is not None else p.spot
            tps = alive(ts)
            duel(t, ct, tps[int(rng.integers(len(tps)))], site, postplant=plant_t is not None)
            if plant_t is None and t > ROUND_TIME_S:
                return "CT", "time_ran_out", ROUND_TIME_S, None, site

        if not alive(cts):
            return "T", "ct_eliminated", t + 0.3, plant_t, site
        if plant_t is None:
            return "CT", "t_eliminated", t + 0.3, None, site
        # Ts dead after plant: defuse if there's time.
        kit = any(p.kit for p in alive(cts))
        defuse_s = 5.0 if kit else 10.0
        defuse_start = t + float(rng.uniform(1, 4))
        if defuse_start + defuse_s <= plant_t + BOMB_TIME_S:
            defuser = alive(cts)[0]
            for ev, tt in (("defuse_begin", defuse_start), ("defuse", defuse_start + defuse_s)):
                self.bomb_row(r, freeze_end, tt, ev, defuser.steamid, *defuser.pos(tt), site, kit)
            return "CT", "bomb_defused", defuse_start + defuse_s, plant_t, site
        return "T", "bomb_exploded", plant_t + BOMB_TIME_S, plant_t, site

    def throw_utility(self, r, ts, cts, site, execute_t, freeze_end, active_smokes, flash_windows):
        rng, m = self.rng, self.m
        for s in m.smokes:
            if s.site != site:
                continue
            team = ts if s.side == "T" else cts
            throwers = [p for p in team if "smokegrenade" in p.nades]
            if not throwers or rng.random() > 0.8:
                continue
            p = throwers[int(rng.integers(len(throwers)))]
            p.nades.remove("smokegrenade")
            throw_t = execute_t - 3 if s.side == "T" else execute_t + 1
            land_t = throw_t + 1.8
            active_smokes.append((s, land_t))
            self.grenade_row(r, freeze_end, p, "smoke", throw_t, land_t, s.throw_x, s.throw_y, s.yaw, s.pitch,
                             s.land_x, s.land_y)
        sx, sy = m.sites[site]
        for p in ts:
            if "flashbang" in p.nades and rng.random() < 0.6:
                p.nades.remove("flashbang")
                ft = execute_t + float(rng.uniform(-1, 3))
                flash_windows.append(ft)
                x0, y0 = p.pos(ft)
                self.grenade_row(r, freeze_end, p, "flash", ft - 1, ft, x0, y0, float(rng.uniform(0, 360)),
                                 -30.0, sx + rng.normal(0, 150), sy + rng.normal(0, 150))
                victims = [c for c in cts if c.spot and c.spot.area == site]
                for v in victims[: int(rng.integers(0, 3))]:
                    self.rows["blinds"].append({"round_num": r, "tick": freeze_end + int(ft * TICKRATE),
                                                "time_s": ft, "attacker_steamid": p.steamid, "attacker_side": "T",
                                                "victim_steamid": v.steamid, "victim_side": "CT",
                                                "blind_duration": float(rng.uniform(0.4, 3.5))})
            if "molotov" in p.nades and rng.random() < 0.5:
                p.nades.remove("molotov")
                mt = execute_t + float(rng.uniform(0, 4))
                x0, y0 = p.pos(mt)
                self.grenade_row(r, freeze_end, p, "molotov", mt - 1.2, mt, x0, y0, float(rng.uniform(0, 360)),
                                 -25.0, sx + rng.normal(0, 200), sy + 250 + rng.normal(0, 100))

    # -- row emitters -----------------------------------------------------------------------
    def kill(self, r, t, freeze_end, win: Player, lose: Player, win_speed, lose_speed):
        rng = self.rng
        tick = freeze_end + int(t * TICKRATE)
        lose_hp = lose.hp
        hp_loss = int(rng.integers(0, 70)) if rng.random() < 0.6 else 0
        win.hp = max(1, win.hp - hp_loss)
        win.hp_log.append((t, win.hp))
        if hp_loss:
            self.rows["damages"].append(self._damage(r, t, tick, lose, win, hp_loss, win.hp))
        wx, wy = win.pos(t)
        wx, wy = wx + rng.normal(0, 30), wy + rng.normal(0, 30)
        lx, ly = lose.pos(t)
        dist_dir = rng.uniform(0, 2 * math.pi)
        if math.hypot(lx - wx, ly - wy) < 150:
            lx, ly = wx + 600 * math.cos(dist_dir), wy + 600 * math.sin(dist_dir)
        lose.death_t = t
        lose.waypoints.append((t, lx, ly))
        lose.waypoints.sort(key=lambda w: w[0])
        self.rows["damages"].append(self._damage(r, t, tick, win, lose, lose_hp, 0))
        weapon = win.weapon
        self.rows["kills"].append({
            "round_num": r, "tick": tick, "time_s": t, "post_round": False,
            **self._pstate("attacker", win, wx, wy, lx, ly, win_speed, weapon, win.hp),
            **self._pstate("victim", lose, lx, ly, wx, wy, lose_speed, lose.weapon, 0),
            "assister_steamid": None, "flash_assist": False, "headshot": bool(rng.random() < 0.45),
            "penetrated": bool(rng.random() < 0.05), "through_smoke": bool(rng.random() < 0.04),
            "attacker_blind": False, "noscope": False, "is_teamkill": False,
            "distance": math.hypot(lx - wx, ly - wy),
        })
        lose.die()
        lose.hp = 0
        # Kill reward.
        reward = 100 if weapon == "awp" else 600 if weapons.weapon_class(weapon) == "smg" else 300
        win.money = min(16000, win.money + reward)

    def _pstate(self, prefix, p: Player, x, y, ox, oy, speed, weapon, hp):
        return {f"{prefix}_steamid": p.steamid, f"{prefix}_name": p.name, f"{prefix}_side": p.side,
                f"{prefix}_x": x, f"{prefix}_y": y, f"{prefix}_z": 0.0,
                f"{prefix}_yaw": math.degrees(math.atan2(oy - y, ox - x)),
                f"{prefix}_pitch": float(self.rng.normal(0, 3)),
                f"{prefix}_place": self.m.place(x, y), f"{prefix}_speed": speed, f"{prefix}_hp": hp,
                f"{prefix}_armor": p.armor, f"{prefix}_scoped": weapon == "awp", f"{prefix}_flash_duration": 0.0,
                f"{prefix}_weapon": weapon}

    def _damage(self, r, t, tick, att: Player, vic: Player, dmg, after):
        return {"round_num": r, "tick": tick, "time_s": t, "attacker_steamid": att.steamid, "attacker_side": att.side,
                "victim_steamid": vic.steamid, "victim_side": vic.side, "weapon": att.weapon, "dmg_health": dmg,
                "dmg_armor": 0, "health_after": after, "hitgroup": "chest"}

    def grenade_row(self, r, freeze_end, p: Player, kind, throw_t, land_t, tx, ty, yaw, pitch, lx, ly):
        rng = self.rng
        self.rows["grenades"].append({
            "round_num": r, "grenade_type": kind, "thrower_steamid": p.steamid, "thrower_name": p.name,
            "thrower_side": p.side, "throw_tick": freeze_end + int(throw_t * TICKRATE), "throw_time_s": throw_t,
            "throw_x": tx + rng.normal(0, 2), "throw_y": ty + rng.normal(0, 2), "throw_z": 0.0,
            "throw_yaw": yaw + rng.normal(0, 0.3), "throw_pitch": pitch + rng.normal(0, 0.3),
            "throw_place": self.m.place(tx, ty), "throw_speed": 0.0, "throw_vertical_speed": 0.0,
            "land_tick": freeze_end + int(land_t * TICKRATE), "land_x": lx + rng.normal(0, 25),
            "land_y": ly + rng.normal(0, 25), "land_z": 0.0,
        })

    def bomb_row(self, r, freeze_end, t, event, steamid, x, y, site, kit=None):
        self.rows["bomb"].append({"round_num": r, "tick": freeze_end + int(t * TICKRATE), "time_s": t, "event": event,
                                  "steamid": steamid, "x": x, "y": y, "z": 0.0, "site": site, "has_kit": kit})

    def snapshots(self, r, players, freeze_end, end_t, plant_t):
        if plant_t is not None:
            planter = next((p for p in players if p.side == "T" and p.death_t >= plant_t), None) \
                or next(p for p in players if p.side == "T")
            site = self.rows["rounds"][-1]["bomb_site"]
            self.bomb_row(r, freeze_end, plant_t - 3.2, "plant_begin", planter.steamid, *planter.pos(plant_t), site)
            self.bomb_row(r, freeze_end, plant_t, "plant", planter.steamid, *planter.pos(plant_t), site)
            if self.rows["rounds"][-1]["reason"] == "bomb_exploded":
                self.bomb_row(r, freeze_end, plant_t + BOMB_TIME_S, "explode", None, *self.m.sites[site], site)
        step = 2.0
        for t in np.arange(0.0, end_t + 1e-9, step):
            for p in players:
                x, y = p.pos(t)
                alive = t < p.death_t
                self.rows["snapshots"].append({
                    "round_num": r, "tick": freeze_end + int(t * TICKRATE), "time_s": float(t), "steamid": p.steamid,
                    "side": p.side, "x": x, "y": y, "z": 0.0, "yaw": 0.0, "place": self.m.place(x, y),
                    "hp": p.hp_at(t), "armor": p.armor if alive else 0, "is_alive": alive,
                    "weapon": p.weapon if alive else None, "equip_value": p.equip_value() if alive else 0,
                    "bomb_planted": plant_t is not None and t >= plant_t})

    def to_match(self, score) -> MatchData:
        tables = {k: pd.DataFrame(v) for k, v in self.rows.items()}
        (a_name, _), (b_name, _) = self.teams["A"], self.teams["B"]
        tables["matches"] = pd.DataFrame([{
            "match_id": self.match_id, "source": "synthetic", "demo_file": None, "map_name": self.m.name,
            "team_a": a_name, "team_b": b_name, "score_a": score["A"], "score_b": score["B"],
            "n_rounds": len(self.rows["rounds"]), "tickrate": TICKRATE, "server_name": "synthetic",
            "parsed_at": datetime.now(UTC).isoformat(timespec="seconds"), "schema_version": SCHEMA_VERSION}])
        assert R.final_score(tables["rounds"], a_name) == score["A"]
        return MatchData(self.match_id, tables).finalize()


TEAM_NAMES = ["Aurora", "Basilisk", "Cobalt", "Dynamo", "Ember", "Falcon", "Glacier", "Harbor"]


def generate(paths: Paths, n_matches: int = 50, seed: int = 0) -> dict:
    """Simulate `n_matches` matches into `paths` and write ground_truth.json. Returns the truth."""
    rng = np.random.default_rng(seed)
    maps = build_maps()
    rosters = {name: [Player(steamid=str(76561190000000000 + 10 * i + j), name=f"{name[:3].lower()}_{j}")
                      for j in range(5)] for i, name in enumerate(TEAM_NAMES)}
    paths.ensure()
    for k in range(n_matches):
        a, b = rng.choice(TEAM_NAMES, size=2, replace=False)
        m = maps[list(maps)[k % len(maps)]]
        for p in rosters[a] + rosters[b]:
            p.money, p.primary, p.pistol, p.armor, p.helmet, p.kit, p.nades = 800, None, "glock", 0, False, False, []
        match_id = f"synth{seed:03d}{k:05d}"
        sim = MatchSim(m, (str(a), rosters[a]), (str(b), rosters[b]), np.random.default_rng([seed, k]), match_id)
        write_match(paths, sim.run())
    truth = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "seed": seed,
             "n_matches": n_matches, "global": GLOBAL_TRUTH, "maps": {k: v.truth() for k, v in maps.items()}}
    (paths.root / "ground_truth.json").write_text(json.dumps(truth, indent=2))
    return truth


def load_truth(root: Path) -> dict:
    return json.loads((root / "ground_truth.json").read_text())
