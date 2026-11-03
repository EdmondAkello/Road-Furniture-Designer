import math
import random

import pytest

from rsd.alignment import (Alignment, Line, Spiral, parse_landxml, format_station,
                           parse_station, StationEquation)
from examples.make_demo_road import build, to_landxml


@pytest.fixture(scope="module")
def road():
    return parse_landxml(to_landxml(build()))[0]


def test_parse_matches_generated(road):
    els = build()
    assert [e.kind for e in road.elements] == ["line", "spiral", "arc", "spiral", "line"]
    assert road.length == pytest.approx(sum(e.length for e in els), abs=1e-6)
    end = road.point_at(road.sta_end)
    assert end[0] == pytest.approx(els[-1].p1[0], abs=1e-4)
    assert end[1] == pytest.approx(els[-1].p1[1], abs=1e-4)


def test_continuity(road):
    # position and heading continuous at every element joint
    acc = road.sta_start
    for e in road.elements[:-1]:
        acc += e.length
        a = road.point_at(acc - 1e-6)
        b = road.point_at(acc + 1e-6)
        assert math.hypot(a[0] - b[0], a[1] - b[1]) < 1e-3
        assert abs(math.remainder(a[2] - b[2], 2 * math.pi)) < 1e-4


def test_spiral_against_series():
    R, L = 300.0, 60.0
    sp = Spiral((0.0, 0.0), 0.0, 0.0, 1 / R, L)
    A2 = R * L
    x = L - L**5 / (40 * A2**2) + L**9 / (3456 * A2**4)
    y = L**3 / (6 * A2) - L**7 / (336 * A2**3)
    px, py = sp.end_point
    assert px == pytest.approx(x, abs=1e-5)
    assert py == pytest.approx(y, abs=1e-5)
    assert sp.end_heading == pytest.approx(L / (2 * R), abs=1e-12)


def test_offset_sign_convention():
    al = Alignment.from_polyline("E", [(0, 0), (100, 0)])
    x, y, _ = al.point_at(50, 3.5)          # +offset = right of eastbound = south
    assert (x, y) == pytest.approx((50, -3.5))
    so = al.station_offset(50, 2.0)          # north of eastbound = left = negative
    assert so.offset == pytest.approx(-2.0)


def test_reversed_digitising_flips_side():
    fwd = Alignment.from_polyline("F", [(0, 0), (100, 0)])
    rev = Alignment.from_polyline("R", [(100, 0), (0, 0)])
    assert fwd.station_offset(30, 5).offset == pytest.approx(-5)
    assert rev.station_offset(30, 5).offset == pytest.approx(5)
    assert rev.station_offset(30, 5).station == pytest.approx(70)


def test_roundtrip_random(road):
    rnd = random.Random(1)
    for _ in range(400):
        sta = rnd.uniform(road.sta_start, road.sta_end)
        off = rnd.uniform(-15, 15)
        x, y, _ = road.point_at(sta, off)
        so = road.station_offset(x, y)
        assert so.station == pytest.approx(sta, abs=1e-4)
        assert so.offset == pytest.approx(off, abs=1e-4)
        assert so.in_range


def test_out_of_range_flag(road):
    x, y, h = road.point_at(road.sta_start)
    so = road.station_offset(x - 50 * math.cos(h), y - 50 * math.sin(h))
    assert not so.in_range
    with pytest.raises(ValueError):
        road.point_at(road.sta_end + 10)


def test_station_equation(road):
    assert road.display_station(700) == pytest.approx(700)
    assert road.display_station(800) == pytest.approx(850)
    assert road.display_station(900) == pytest.approx(950)
    assert road.internal_station(950) == pytest.approx(900)
    assert road.internal_station(700) == pytest.approx(700)


def test_station_equation_gap_overlap():
    # overlap: back 1000 / ahead 950 => display 960..1000 occurs twice
    al = Alignment.from_polyline("O", [(0, 0), (2000, 0)],
                                 equations=[StationEquation(1000, 1000, 950)])
    assert al.internal_station(980, region=0) == pytest.approx(980)
    assert al.internal_station(980, region=1) == pytest.approx(1030)
    assert al.internal_station(980) == pytest.approx(1030)


def test_station_text():
    assert format_station(2450) == "2+450.000"
    assert format_station(12.5, 1) == "0+012.5"
    assert parse_station("2+450.5") == pytest.approx(2450.5)
    assert parse_station("0+012") == 12
    assert parse_station(830) == 830
