import pytest

from rfd import barriers as B
from rfd.alignment import Alignment, Arc, Line
from rfd.corridor import Edges, Sections
from rfd.profile import VerticalProfile

GROUND = "OGL"
TOP = "TOP"


def road(length=2000.0, speed=80.0, curve=False):
    if curve:
        l1 = Line((0, 0), (800, 0))
        arc = Arc((800, 0), (800, -300), 300, False, 300)
        p, h = arc.end_point, arc.end_heading
        import math
        l2 = Line(p, (p[0] + 900 * math.cos(h), p[1] + 900 * math.sin(h)))
        al = Alignment("B", [l1, arc, l2], 0.0, [], [(0.0, speed)])
    else:
        al = Alignment.from_polyline("B", [(0, 0), (length, 0)])
        al.speeds = [(0.0, speed)]
    al.profile = VerticalProfile("p", [(0, 100, 0), (al.sta_end, 100, 0)])
    return al


def section(fill_h, n, toe_drain=False, platform=6.5):
    """Coded points (rel. z), TOP and OGL lines (absolute) for a symmetric fill of height fill_h at 1:n."""
    zc = 100.0
    coded, top = [], [(0.0, zc)]
    for off, z, code in ((3.5, -0.07, "ETW"), (5.0, -0.1, "EPS"), (platform, -0.13, "Hinge")):
        coded.append((off, z, code)); top.append((off, zc + z))
    zh = zc - 0.13
    if fill_h <= 0:                              # cut: ground above the platform
        ground = [(0.0, zc + 2), (40.0, zc + 3)]
        coded.append((platform + 4, 1.0, "Daylight")); top.append((platform + 4, zc + 1.0))
        return coded, top, ground
    gz = zh - fill_h
    xt = platform + n * fill_h
    if toe_drain:                                # slope runs 0.6 m below ground into a drain, out to daylight
        xd = xt + 0.6 * n
        for off, z, code in ((xd, gz - 0.6 - zc, "Ditch_In"), (xd + 1.0, gz - 0.6 - zc, "Ditch_Out"),
                             (xd + 2.2, gz + 0.0 - zc, "Daylight")):
            coded.append((off, z, code)); top.append((off, zc + z))
    else:
        coded.append((xt, gz - zc, "Daylight")); top.append((xt, gz))
    ground = [(0.0, gz), (60.0, gz)]
    return coded, top, ground


def build(al, profile_fn, step=20.0, surfaces=True):
    """profile_fn(sta) -> (fill_h, n, toe_drain) for both sides."""
    data, edges = {}, {("ETW", s): [] for s in "LR"}
    s = al.sta_start
    while s <= al.sta_end + 1e-6:
        h, n, drain = profile_fn(s)
        coded, top, ground = section(h, n, drain)
        d = {"L": coded, "R": coded}
        if surfaces:
            d["_surf"] = {TOP: [(-o, z) for o, z in reversed(top)] + top[1:],
                          GROUND: [(-o, z) for o, z in reversed(ground)] + ground[1:]}
        data[s] = d
        for sd in "LR":
            edges[("ETW", sd)].append((s, 3.5))
        s += step
    al.sections = Sections(data)
    al.edges = Edges(edges)
    return al


def by_side(runs, side):
    return sorted((r for r in runs if r.side == side), key=lambda r: r.sta_start)


def test_side_fill_uses_ground_not_daylight():
    al = build(road(), lambda s: (6.0, 2.0, True))
    f = B.fills(al, B.BarrierConfig())[0]
    assert f and all(x.source == "section ground" for x in f)
    x = f[0]
    assert x.height == pytest.approx(6.0, abs=1e-6) and x.slope_n == pytest.approx(2.0, abs=1e-6)
    # the same corridor without ground: hinge to daylight gives the wrong height (daylight sits above the drain)
    al2 = build(road(), lambda s: (6.0, 2.0, True), surfaces=False)
    y = B.fills(al2, B.BarrierConfig())[0][0]
    assert y.source == "daylight" and abs(y.height - 6.0) < 0.05 and y.slope_n > 2.0
    al3 = build(road(), lambda s: (0.0, 2.0, False))
    assert B.fills(al3, B.BarrierConfig())[0] == []                    # cut


def test_warrant_runout_minimum_and_setback():
    al = build(road(), lambda s: (8.0, 1.5, False) if 900 <= s <= 1000 else (1.0, 4.0, False))
    runs, findings = B.propose_barriers(al, B.BarrierConfig())
    for side in "LR":
        r, = by_side(runs, side)
        assert r.sta_start == pytest.approx(900 - 85) and r.sta_end == pytest.approx(1000 + 85)   # Table 12.6 at 80
        assert r.edge_ref == "ETW" and r.offset == 0.5 and r.code == "GR-W" and r.status == "proposed"
        assert "Fig" in r.reason and "run-out 85 m" in r.reason
    runs, _ = B.propose_barriers(al, B.BarrierConfig(aadt=15000))
    assert all(r.offset == 0.5 for r in runs)                          # 80 km/h is not > 80
    al.speeds = [(0.0, 100.0)]
    runs, _ = B.propose_barriers(al, B.BarrierConfig(aadt=15000))
    assert all(r.offset == 0.75 for r in runs) and runs[0].length == pytest.approx(100 + 2 * 105)


def test_judgement_band_and_gap_closing():
    # 6 m: steeper than 1:3 required, 1:3.5 judgement, 1:5 not required (RDM 1.3 Fig 12.4 example)
    al = build(road(), lambda s: (6.0, 3.5, False) if 400 <= s <= 600 else (1.0, 4.0, False))
    runs, findings = B.propose_barriers(al, B.BarrierConfig())
    assert runs == [] and {f.kind for f in findings} >= {"barrier_judgement"}
    runs, _ = B.propose_barriers(al, B.BarrierConfig(include_judgement=True))
    assert len(by_side(runs, "L")) == 1 and "judgement" in runs[0].reason
    al = build(road(), lambda s: (6.0, 5.0, False))
    assert B.propose_barriers(al, B.BarrierConfig())[0] == []
    # two warranted lengths whose run-outs leave a 60 m gap are joined (12.6.14: no gaps under 80 m)
    al = build(road(length=3000),
               lambda s: (8.0, 1.5, False) if (500 <= s <= 600 or 830 <= s <= 900) else (1.0, 4.0, False))
    r = by_side(B.propose_barriers(al, B.BarrierConfig())[0], "L")
    assert len(r) == 1 and r[0].sta_start == pytest.approx(415) and r[0].sta_end == pytest.approx(985)
    assert "gap under 80 m closed" in r[0].reason


def test_end_on_a_bend_carried_to_tangent_point():
    al = build(road(curve=True), lambda s: (8.0, 1.5, False) if 900 <= s <= 1000 else (1.0, 4.0, False))
    r = by_side(B.propose_barriers(al, B.BarrierConfig())[0], "L")[0]
    assert r.sta_end == pytest.approx(1100 + 85) and r.sta_start == pytest.approx(800 - 85)
    assert "tangent point" in r.reason


def test_clipped_at_alignment_ends_and_no_sections():
    al = build(road(length=400), lambda s: (8.0, 1.5, False))
    r = by_side(B.propose_barriers(al, B.BarrierConfig())[0], "R")[0]
    assert r.sta_start == 0 and r.sta_end == pytest.approx(400)
    al = road()
    runs, findings = B.propose_barriers(al, B.BarrierConfig())
    assert runs == [] and "no corridor sections" in findings[0].text


def test_tin_ground(monkeypatch):
    from rfd import terrain as T
    pts = {"1": (-10, -100, 92.0), "2": (3000, -100, 92.0), "3": (3000, 100, 92.0), "4": (-10, 100, 92.0)}
    tin = T.Tin("EG", pts, [("1", "2", "3"), ("1", "3", "4")])
    assert tin.z(100, 0) == pytest.approx(92.0) and tin.z(5000, 0) is None
    monkeypatch.setattr(T, "ground_tin", lambda path, name=None: tin)
    al = build(road(), lambda s: (99.87 - 92.0, 2.0, False), surfaces=False)
    f, note = B.fills(al, B.BarrierConfig(landxml="x.xml"))
    assert f[0].source == "TIN EG" and f[0].height == pytest.approx(7.87, abs=0.01) and "TIN" in note
    assert T.is_ground_name("OGL-LOT_24.07.2026_REV 0") and T.is_ground_name("EG") and T.is_ground_name("Terrain")
    assert not T.is_ground_name("BOTTOM") and not T.is_ground_name("OLKARIA LOT 3 TOP")
    assert T.is_design_name("OLKARIA LOT 3 TOP")
