"""Weapon name normalisation, classes and prices.

Demo events name weapons inconsistently: kill events use internal names
("ak47", "weapon_m4a1_silencer") while player props use display names
("AK-47", "M4A1-S"). Everything is mapped to the internal name here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Weapon:
    id: str
    display: str
    cls: str  # pistol | smg | shotgun | heavy | rifle | sniper | grenade | knife | taser | bomb
    price: int


_WEAPONS = [
    Weapon("glock", "Glock-18", "pistol", 200),
    Weapon("usp_silencer", "USP-S", "pistol", 200),
    Weapon("hkp2000", "P2000", "pistol", 200),
    Weapon("p250", "P250", "pistol", 300),
    Weapon("elite", "Dual Berettas", "pistol", 300),
    Weapon("fiveseven", "Five-SeveN", "pistol", 500),
    Weapon("tec9", "Tec-9", "pistol", 500),
    Weapon("cz75a", "CZ75-Auto", "pistol", 500),
    Weapon("deagle", "Desert Eagle", "pistol", 700),
    Weapon("revolver", "R8 Revolver", "pistol", 600),
    Weapon("mac10", "MAC-10", "smg", 1050),
    Weapon("mp9", "MP9", "smg", 1250),
    Weapon("mp7", "MP7", "smg", 1500),
    Weapon("mp5sd", "MP5-SD", "smg", 1500),
    Weapon("ump45", "UMP-45", "smg", 1200),
    Weapon("p90", "P90", "smg", 2350),
    Weapon("bizon", "PP-Bizon", "smg", 1400),
    Weapon("nova", "Nova", "shotgun", 1050),
    Weapon("xm1014", "XM1014", "shotgun", 2000),
    Weapon("sawedoff", "Sawed-Off", "shotgun", 1100),
    Weapon("mag7", "MAG-7", "shotgun", 1300),
    Weapon("m249", "M249", "heavy", 5200),
    Weapon("negev", "Negev", "heavy", 1700),
    Weapon("galilar", "Galil AR", "rifle", 1800),
    Weapon("famas", "FAMAS", "rifle", 2050),
    Weapon("ak47", "AK-47", "rifle", 2700),
    Weapon("m4a1", "M4A4", "rifle", 3100),
    Weapon("m4a1_silencer", "M4A1-S", "rifle", 2900),
    Weapon("sg556", "SG 553", "rifle", 3000),
    Weapon("aug", "AUG", "rifle", 3300),
    Weapon("ssg08", "SSG 08", "sniper", 1700),
    Weapon("awp", "AWP", "sniper", 4750),
    Weapon("g3sg1", "G3SG1", "sniper", 5000),
    Weapon("scar20", "SCAR-20", "sniper", 5000),
    Weapon("hegrenade", "High Explosive Grenade", "grenade", 300),
    Weapon("flashbang", "Flashbang", "grenade", 200),
    Weapon("smokegrenade", "Smoke Grenade", "grenade", 300),
    Weapon("molotov", "Molotov", "grenade", 400),
    Weapon("incgrenade", "Incendiary Grenade", "grenade", 500),
    Weapon("decoy", "Decoy Grenade", "grenade", 50),
    Weapon("taser", "Zeus x27", "taser", 200),
    Weapon("knife", "Knife", "knife", 0),
    Weapon("c4", "C4 Explosive", "bomb", 0),
]

WEAPONS: dict[str, Weapon] = {w.id: w for w in _WEAPONS}

_EXTRA_ALIASES = {
    "usp_silencer_off": "usp_silencer",
    "m4a1_silencer_off": "m4a1_silencer",
    "inferno": "molotov",  # fire damage is attributed to "inferno"
    "planted_c4": "c4",
    "smoke": "smokegrenade",
    "flash": "flashbang",
    "he": "hegrenade",
    "incendiary": "incgrenade",
    "zeus": "taser",
}
_KNIFE_WORDS = ("knife", "bayonet", "karambit", "dagger", "talon", "ursus", "navaja", "stiletto", "kukri")


def _key(name: str) -> str:
    name = name.strip().lower()
    name = name.removeprefix("weapon_")
    return re.sub(r"[\s\-_.]", "", name)


_ALIASES: dict[str, str] = {}
for _w in _WEAPONS:
    _ALIASES[_key(_w.id)] = _w.id
    _ALIASES[_key(_w.display)] = _w.id
for _alias, _id in _EXTRA_ALIASES.items():
    _ALIASES[_key(_alias)] = _id


def normalize(name: object) -> str | None:
    """Map any weapon spelling to its internal id; unknown names are lower-cased."""
    if name is None or not isinstance(name, str) or not name.strip():
        return None
    k = _key(name)
    if k in _ALIASES:
        return _ALIASES[k]
    if any(w in k for w in _KNIFE_WORDS):
        return "knife"
    return name.strip().lower().removeprefix("weapon_")


def weapon_class(name: object) -> str | None:
    wid = normalize(name)
    if wid is None:
        return None
    w = WEAPONS.get(wid)
    return w.cls if w else "other"


def price(name: object) -> int:
    wid = normalize(name)
    w = WEAPONS.get(wid) if wid else None
    return w.price if w else 0


GRENADE_TYPES = {
    "smokegrenade": "smoke",
    "flashbang": "flash",
    "hegrenade": "he",
    "molotov": "molotov",
    "incgrenade": "molotov",
    "decoy": "decoy",
}


def grenade_type(name: object) -> str | None:
    """Map a grenade weapon or projectile class name to smoke|flash|he|molotov|decoy."""
    if not isinstance(name, str):
        return None
    k = _key(name)
    for needle, kind in (("smoke", "smoke"), ("flash", "flash"), ("molotov", "molotov"),
                         ("incendiary", "molotov"), ("incgrenade", "molotov"), ("inferno", "molotov"),
                         ("decoy", "decoy"), ("hegrenade", "he"), ("explosive", "he")):
        if needle in k:
            return kind
    return GRENADE_TYPES.get(normalize(name) or "")
