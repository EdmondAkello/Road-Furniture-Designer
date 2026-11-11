import math
import pytest

from rfd.alignment import Alignment, Arc, Line, parse_landxml
from rfd.autoplace import (AutoConfig, advance_distance, chevron_spacing, curve_speed, propose, space_out,
                           Proposal, sight_distances)
from rfd.corridor import Edges, clamp_offset
from rfd.profile import VerticalProfile


def road(radius=100.0, ccw=False, speed=80.0, e=None, profile=None):
    """Straight - circular curve - straight, heading east."""
    l1 = Line((0.0, 0.0), (500.0, 0.0))
    sgn = 1 if ccw else -1
    ce = (500.0, sgn * radius)
    arc = Arc((500.0, 0.0), ce, radius, ccw, radius * math.pi / 2)
    p = arc.end_point
    h = arc.end_heading
    l2 = Line(p, (p[0] + 500 * math.cos(h), p[1] + 500 * math.sin(h)))
    al = Alignment("T", [l1, arc, l2], 0.0, [], [(0.0, speed)])
    if e is not None:
        al.superelevation = [(500.0, 500.0 + arc.length, e)]
    al.profile = profile
    return al


def test_rdm_tables():
    assert advance_distance(80) == 140            # 6 s at 80 km/h = 133 m -> 140
    assert advance_distance(50) == 90
    assert chevron_spacing(100) == (20, 40) and chevron_spacing(185) == (30, 60)   # Table 4.2
    assert curve_speed(100, 6.0) == pytest.approx(55, abs=1.5)


def test_sharp_right_curve_proposals():
    al = road(100, ccw=False, e=6.0)
    props, findings = propose(al, AutoConfig(grades=False, no_overtaking=False))
    curve = [f for f in findings if f.kind == "curve"]
    assert len(curve) == 1 and curve[0].values["drop"] == pytest.approx(25, abs=2)
    warn = [p for p in props if p.code in ("W19", "W20")]
    assert {(p.side, p.facing) for p in warn} == {("L", "Forward"), ("R", "Backward")}
    fwd = [p for p in warn if p.facing == "Forward"][0]
    assert fwd.code == "W20" and fwd.station == pytest.approx(500 - 140)    # bend; 140 m advance
    assert fwd.mirror is False                                             # right-hand bend = as manual
    bwd = [p for p in warn if p.facing == "Backward"][0]
    assert bwd.mirror is True                                              # backward traffic turns left
    chev = [p for p in props if p.code == "W24-a"]
    assert chev and all(p.side == "L" for p in chev)                       # outside of a right-hand curve
    stations = sorted({round(p.station, 3) for p in chev})
    assert stations[1] - stations[0] == pytest.approx(20)                  # Table 4.2 on-curve spacing


def test_gentle_curve_not_signed():
    al = road(600, e=4.0)
    props, findings = propose(al, AutoConfig(grades=False, no_overtaking=False))
    assert not props and not findings


def test_steep_grade_and_no_overtaking():
    # 0+000 rises 8 % to a sharp crest at 600, then falls 8 %: W31? no (8 < 10); W30 both ways; crest blocks sight
    pr = VerticalProfile("t", [(0, 100, 0), (600, 148, 80), (1600, 68, 0)])
    al = road(5000, e=2.0, profile=pr)
    props, findings = propose(al, AutoConfig(curves=False))
    kinds = {f.kind for f in findings}
    assert "grade_descent" in kinds and "grade_ascent" not in kinds
    w30 = [p for p in props if p.code == "W30"]
    assert {p.facing for p in w30} == {"Forward", "Backward"}
    assert all(p.legend == "8%" for p in w30)
    assert any(f.kind == "no_overtaking" for f in findings)
    p32 = [p for p in props if p.code == "P32"]
    assert any(p.code == "W23" for p in props)
    ends = [p for p in props if p.code == "END"]                   # RDM 6.2 3.11: P32 + supplementary END plate
    assert ends and all(any(q.code == "P32" and q.group == e.group and q.station == e.station for q in p32)
                        for e in ends)
    assert any(f.kind == "crest_ssd" for f in findings)                  # K = 80/16 = 5, far too sharp


def test_sight_distance_scan_flat_and_crest():
    st = [i * 5.0 for i in range(201)]
    flat = sight_distances(st, [100.0] * len(st), 1, 1.08, 1.08, 300)
    assert all(d == 300 for d in flat[:100])
    crest = [100 + 0.08 * s if s < 500 else 140 - 0.08 * (s - 500) for s in st]
    sd = sight_distances(st, crest, 1, 1.08, 1.08, 300)
    i = st.index(450.0)
    assert sd[i] < 120                                                     # blocked over the apex


def test_spacing_moves_or_drops():
    speed = lambda s: 80.0
    props = [Proposal("W20", 1000, "L", "Forward", "curve", "x"), Proposal("W30", 1010, "L", "Forward", "grade", "y")]
    out = space_out(props, [], speed)
    st = sorted(p.station for p in out)
    assert st[1] - st[0] >= 48 - 1e-6                                     # 0.6 x 80
    dup = space_out([Proposal("W20", 1000, "L", "Forward", "curve", "x")], [(1010, "L", "Forward", "W20")], speed)
    assert dup == []                                                       # already signed


def test_clamp_offset():
    e = Edges({("ETW", "L"): [(0, 3.5), (100, 3.5)], ("EPS", "L"): [(0, 5.0), (100, 5.0)],
               ("Ditch_Out", "L"): [(0, 7.0), (100, 7.0)]})
    assert clamp_offset(e, "L", 50, 4.0)[0] == pytest.approx(5.6)          # pushed out to EPS + 0.6
    assert clamp_offset(e, "L", 50, 12.0)[0] == pytest.approx(7.0)         # inside the corridor (ditch)
    assert clamp_offset(e, "L", 50, 6.5) == (6.5, "")


def test_rerun_on_placed_signs_adds_nothing():
    """Auto-propose run again over its own (accepted) signs proposes nothing: no duplicate chevrons or plates."""
    from rfd.autoplace import space_out
    from tests.test_bootstrap import random_road
    for seed in range(20):
        al, _ = random_road(seed)
        props, _ = propose(al, AutoConfig())
        placed = space_out([p for p in props], [], al.speed_at)
        existing = [(p.station, p.side, p.facing, p.code) for p in placed]
        again, _ = propose(al, AutoConfig())
        assert space_out(again, existing, al.speed_at) == [], f"seed {seed}"
