"""Long descents: descending lanes, brake check areas, runaway speed and escape ramps (RDM 1.3 6.6.4, 12.5, 12.7)."""
import pytest

from rfd import descents as D
from rfd.alignment import Alignment, Arc, Line
from rfd.profile import VerticalProfile


def straight(length=3000.0, pvis=((0, 400.0), (3000, 400.0))):
    al = Alignment.from_polyline("D", [(0, 0), (length, 0)])
    al.speeds = [(0.0, 80.0)]
    al.profile = VerticalProfile("p", [(s, z, 0) for s, z in pvis])
    return al


def test_rdm_worked_example_ramp_length():
    # RDM 1.3 12.7.3: 140 km/h, 10 % ascending ramp, loose gravel (R = 10 %): "about 385 m"
    assert D.ramp_length(140, 10.0, D.MATERIALS["Gravel, loose"]) == pytest.approx(385.8, abs=0.1)
    assert D.ramp_length(100, -15.0, 10.0) is None                     # a ramp that cannot stop the truck


def test_descents_found_for_each_direction():
    al = straight(pvis=((0, 400.0), (500, 400.0), (2500, 300.0), (3000, 300.0)))    # 5 % down over 2 km
    ds = D.descents(al)
    with_ch = [d for d in ds if d.side == "L"]
    against = [d for d in ds if d.side == "R"]
    assert len(with_ch) == 1 and not against                            # uphill for the other traffic
    d = with_ch[0]
    assert d.start == pytest.approx(500, abs=10) and d.end == pytest.approx(2500, abs=10)
    assert d.drop == pytest.approx(100, abs=1) and d.mean_grade == pytest.approx(5.0, abs=0.1)


def test_runaway_speed_grows_and_is_capped():
    al = straight(pvis=((0, 400.0), (3000, 160.0)))                    # 8 % for 3 km
    d = D.descents(al)[0]
    sp = D.runaway_speeds(al, d)
    assert sp[0][1] == D.RUNAWAY_START
    assert all(b[1] >= a[1] - 1e-9 for a, b in zip(sp, sp[1:]))
    assert max(v for _, v in sp) == D.RUNAWAY_CAP
    # v^2 = v0^2 + 2 g (0.08 - 0.01) s: 40 km/h -> 100 km/h after about 465 m
    s100 = next(s for s, v in sp if v >= 100.0)
    assert s100 == pytest.approx(465, abs=10)


def test_descending_lane_needs_an_opposite_climbing_lane_over_1000_m():
    long_ = straight(pvis=((0, 400.0), (3000, 250.0)))                  # 5 %, 3 km
    lanes = D.descending_lanes(long_, aadt=5000)
    assert len(lanes) == 1 and lanes[0]["side"] == "L"
    short = straight(pvis=((0, 400.0), (800, 360.0), (3000, 360.0)))    # 5 % but only 800 m
    assert D.descending_lanes(short, aadt=5000) == []
    assert D.descending_lanes(long_, aadt=1000) == []                   # no climbing lane under 2000 pcu


def test_brake_check_before_a_long_steep_descent():
    al = straight(pvis=((0, 400.0), (600, 400.0), (2600, 280.0), (3000, 280.0)))  # 6 %, 120 m drop
    b, = D.brake_check_sites(al, trucks=600)
    assert b["side"] == "L" and b["end"] == pytest.approx(600 - 100, abs=10)
    assert b["note"].startswith("recommended")
    assert D.brake_check_sites(al, trucks=200)[0]["note"].startswith("consider")


def test_escape_ramp_before_a_curve_the_runaway_cannot_take():
    # 1.6 km tangent falling 10 %, then a 150 m radius curve: the truck is far too fast for it
    l1 = Line((0, 0), (1600, 0))
    arc = Arc((1600, 0), (1600, -150), 150, False, 200)
    al = Alignment("E", [l1, arc], 0.0, [], [(0.0, 80.0)])
    al.profile = VerticalProfile("p", [(0, 400.0, 0), (1600, 240.0, 0), (al.sta_end, 240.0, 0)])
    sites = D.escape_ramp_sites(al)
    r, = [s for s in sites if s["side"] == "L"]
    assert r["station"] is not None and 1300 < r["station"] < 1600       # on the tangent, before the curve
    assert "curve R 150" in r["reason"]
    assert r["lengths"]["Ascending grade"] == pytest.approx(D.ramp_length(r["speed"], 10.0, 10.0), abs=1)
    # no 130 m drop: no ramp
    al.profile = VerticalProfile("p", [(0, 400.0, 0), (1600, 300.0, 0), (al.sta_end, 300.0, 0)])
    assert [s for s in D.escape_ramp_sites(al) if s["side"] == "L"] == []
