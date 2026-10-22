import pytest

from csanalysis import weapons


@pytest.mark.parametrize("raw,wid", [("AK-47", "ak47"), ("weapon_ak47", "ak47"), ("M4A1-S", "m4a1_silencer"),
                                     ("m4a1_silencer_off", "m4a1_silencer"), ("M4A4", "m4a1"),
                                     ("Desert Eagle", "deagle"), ("knife_karambit", "knife"), ("inferno", "molotov"),
                                     ("Smoke Grenade", "smokegrenade"), ("", None), (None, None)])
def test_normalize(raw, wid):
    assert weapons.normalize(raw) == wid


def test_classes_and_prices():
    assert weapons.weapon_class("AWP") == "sniper"
    assert weapons.price("ak47") == 2700
    assert weapons.price(None) == 0


@pytest.mark.parametrize("raw,kind", [("CSmokeGrenadeProjectile", "smoke"), ("smokegrenade", "smoke"),
                                      ("Flashbang", "flash"), ("HE Grenade", "he"), ("hegrenade", "he"),
                                      ("Incendiary Grenade", "molotov"), ("molotov", "molotov"), ("decoy", "decoy")])
def test_grenade_type(raw, kind):
    assert weapons.grenade_type(raw) == kind
