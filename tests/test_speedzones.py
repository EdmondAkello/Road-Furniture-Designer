"""Speed limit zones (RDM 6.2 3.5): limit signs both ways at the start, repeaters, P9 at the end."""
import pytest

from rfd.alignment import Alignment, Line
from rfd.catalogue import Catalogue
from rfd.speedzones import LIMIT_SIGNS, SpeedZone, design_zone, zones_from_design_speed, zones_from_signs
from tests.test_bootstrap import random_road

CAT = Catalogue.load()


def road(length=3000.0, speeds=((0.0, 80.0),)):
    return Alignment("T", [Line((0, 0), (length, 0))], 0.0, [], list(speeds))


def test_signs_in_the_catalogue():
    for code in list(LIMIT_SIGNS.values()) + ["P9", "P32", "END"]:
        assert code in CAT.signs


def test_zone_signs_both_directions():
    al = road()
    d = design_zone(al, SpeedZone(1000, 2000, 50))
    start = {(p.code, p.facing, p.side, p.station) for p in d.signs if "start" in p.reason}
    assert start == {("P5", "Forward", "L", 1000), ("P5", "Backward", "R", 2000)}
    ends = {(p.facing, p.side, p.station) for p in d.signs if p.code == "P9"}
    assert ends == {("Forward", "L", 2000), ("Backward", "R", 1000)}
    reps = [p for p in d.signs if "repeater" in p.reason]
    assert {(p.facing, p.station) for p in reps} == {("Forward", 1500), ("Backward", 1500)}
    assert len({p.rule for p in d.signs}) == 1


def test_repeat_interval_and_short_zone():
    al = road(5000)
    d = design_zone(al, SpeedZone(500, 3500, 70), repeat=1000)
    assert sorted({p.station for p in d.signs if "repeater" in p.reason}) == [1500, 2500]
    short = design_zone(al, SpeedZone(100, 150, 50))
    assert not [p for p in short.signs if "repeater" in p.reason]
    assert any(f.kind == "speed_note" for f in short.findings)


def test_zone_at_alignment_end_and_neighbour():
    al = road()
    d = design_zone(al, SpeedZone(0, 1000, 50))
    assert not [p for p in d.signs if p.facing == "Forward" and "start" in p.reason]      # starts off the road
    assert any(f.kind == "speed_note" for f in d.findings)
    nb = SpeedZone(1000, 2000, 80)
    d2 = design_zone(al, SpeedZone(0, 1000, 50), neighbours=[nb])
    assert not [p for p in d2.signs if p.code == "P9" and p.station == 1000]              # the 80 sign marks it


def test_limit_above_design_speed_and_bad_limit():
    al = road(speeds=((0.0, 80.0), (1200.0, 60.0), (1600.0, 80.0)))
    d = design_zone(al, SpeedZone(1000, 2000, 70))
    chk = [f for f in d.findings if f.kind == "speed_check"]
    assert chk and chk[0].values["design_speed"] == 60
    with pytest.raises(ValueError):
        SpeedZone(0, 100, 60)


def test_zones_from_design_speed():
    al = road(5000, speeds=((0.0, 100.0), (1000.0, 50.0), (2000.0, 50.0), (2500.0, 60.0), (3000.0, 80.0)))
    z = zones_from_design_speed(al)                                    # built-up 50 km/h sections only
    assert [(a.start, a.end, a.limit) for a in z] == [(1000.0, 2500.0, 50)]
    z = zones_from_design_speed(al, limits=(50, 70, 80))
    assert [(a.start, a.end, a.limit) for a in z] == [(1000.0, 2500.0, 50), (3000.0, 5000.0, 80)]


@pytest.mark.parametrize("seed", range(30))
def test_random_zones(seed):
    """Random zones on random roads: every sign on the road and in the catalogue, limit signs facing into
    the zone, P9 facing out of it, and the zone recovered from its signs."""
    al, rng = random_road(seed)
    for _ in range(4):
        a = al.sta_start + rng.uniform(0, al.length)
        b = al.sta_start + rng.uniform(0, al.length)
        lim = rng.choice(sorted(LIMIT_SIGNS))
        z = SpeedZone(a, b, lim)
        if z.end - z.start < 1:
            continue
        d = design_zone(al, z, repeat=rng.choice([None, 300.0, 1000.0]))
        for p in d.signs:
            assert al.sta_start - 1e-6 <= p.station <= al.sta_end + 1e-6
            assert p.code in CAT.signs and (p.side, p.facing) in (("L", "Forward"), ("R", "Backward"))
            assert z.start - 1e-6 <= p.station <= z.end + 1e-6
        got = zones_from_signs([{"sta": p.station, "code": p.code, "facing": p.facing, "rule": p.rule,
                                 "status": "proposed"} for p in d.signs])
        if any(p.code == LIMIT_SIGNS[lim] for p in d.signs):
            assert len(got) == 1 and got[0]["limit"] == lim
