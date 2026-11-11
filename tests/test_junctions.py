"""Junction islands and markings placed from the templates of RDM/1/3/2/01-02."""
import math

import pytest

from rfd import furniture_report as FR
from rfd import junctions as J
from rfd.alignment import Alignment

T = J.load_templates()


def straight():
    return Alignment.from_polyline("M", [(0, 0), (400, 0)])


def at(al, angle, side=1, sta=200.0, **kw):
    b = math.radians(angle) * side
    return J.place(al, sta, 0.4, sta + 30 * math.cos(b), 30 * math.sin(b), **kw)


def test_templates_are_consistent():
    assert set(T["kits"]) == set(T["types"]) == {"A-1", "A-2", "B", "B-Mod", "C"}
    for k, items in T["kits"].items():
        assert items[0]["piece"] == "guides"
        for it in items:
            p = T["pieces"][it["piece"]]
            assert k in p["types"], (k, it["piece"])
            assert p["frame"] in ("main", "minor", "corner", "guide")
            if p["frame"] == "corner":
                assert it["corner"] in ("left_turn", "other")
    assert "D" not in T["types"]                             # the sheet labels no panel D
    assert "no panel D" in T["types"]["B-Mod"]["remark"]
    assert set(J.pieces_for(T, "C")) >= {"splitter_teardrop", "give_way_line", "guides"}


def test_every_kit_builds_square_and_skewed_on_both_sides():
    al = straight()
    for side in (1, -1):
        for ang in (90, 70):
            pl = at(al, ang, side)
            for k in T["kits"]:
                pcs = J.build_kit(al, pl, k)
                assert len(pcs) == len(T["kits"][k])
                for pc in pcs:
                    for part in pc.parts:
                        assert part.pts and all(math.isfinite(x) and math.isfinite(y) for x, y in part.pts)
                    if pc.kind == "guide":
                        assert pc.quantities == {}
                assert not [p for p in J.build_kit(al, pl, k, guides=False) if p.piece == "guides"]


def test_frames_follow_the_drawings():
    al = straight()
    pl = at(al, 90, 1)                                       # minor road on the left (north), as type A-1 is drawn
    F = pl.frame(al)
    assert F.side == "L" and F.sigma == 1 and F.e == pytest.approx(3.5) and F.crossing_angle == pytest.approx(90)
    # the ghost island tail and the left-turn corner are both west of the junction, as on the sheet
    gi = J.build_piece(al, pl, "ghost_island", templates=T)
    assert max(x for p in gi.parts for x, _ in p.pts) < 200
    ci = J.build_piece(al, pl, "corner_island", "left_turn", templates=T)
    assert max(x for x, _ in ci.parts[0].pts) < 200 and min(y for _, y in ci.parts[0].pts) >= 3.5
    # minor road on the right: everything mirrors (type B is drawn so, its corner island east)
    pr = at(al, 90, -1)
    ci = J.build_piece(al, pr, "corner_island", "left_turn", templates=T)
    assert min(x for x, _ in ci.parts[0].pts) > 200 and max(y for _, y in ci.parts[0].pts) <= -3.5
    # Kenya drives on the left: the give way line crosses the approach lane, on the right looking up the minor road
    gw = J.build_piece(al, pl, "give_way_line", templates=T)
    assert all(x >= 200 for p in gw.parts for x, _ in p.pts)
    gw = J.build_piece(al, pr, "give_way_line", templates=T)
    assert all(x <= 200 for p in gw.parts for x, _ in p.pts)


def test_quantities_and_scale():
    al = straight()
    pl = at(al, 90)
    pc = J.build_piece(al, pl, "splitter_a1", templates=T)
    # raised 7.5 x 3.0 m stadium: area 3 x 4.5 + pi 1.5^2, kerb 2 x 4.5 + 2 pi 1.5
    assert pc.quantities["island_m2"] == pytest.approx(3 * 4.5 + math.pi * 1.5 ** 2, rel=0.02)
    assert pc.quantities["kerb_m"] == pytest.approx(9 + 3 * math.pi, rel=0.02)
    assert pc.quantities["paint_m2"] > 0 and "HM07_m" in pc.quantities and "HM14_m" in pc.quantities
    big = J.build_piece(al, at(al, 90, scale=1.2), "splitter_a1", templates=T)
    assert big.quantities["island_m2"] == pytest.approx(pc.quantities["island_m2"] * 1.44, rel=0.02)
    assert big.quantities["kerb_m"] == pytest.approx(pc.quantities["kerb_m"] * 1.2, rel=0.02)
    gw = J.build_piece(al, pl, "give_way_line", templates=T)        # TM07: 600 / 300 mm, 400 mm wide over 3.5 m
    assert len(gw.parts) == 4 and gw.quantities["paint_m2"] == pytest.approx(4 * 0.6 * 0.4, abs=0.01)
    # the splitter's give way markings start at the island's edge
    inner = next(it for it in T["kits"]["C"] if it["piece"] == "give_way_line")["params"]["inner"]
    gw = J.build_piece(al, pl, "give_way_line", params={"inner": inner}, templates=T)
    assert min(abs(x - 200) for p in gw.parts for x, _ in p.pts) == pytest.approx(inner, abs=0.01)


def test_corner_islands_follow_the_skew_and_stay_clear_of_the_kerb_return():
    al = straight()
    for ang in (90, 75):
        pl = at(al, ang)
        F = pl.frame(al)
        ci = J.build_piece(al, pl, "corner_island", "left_turn", templates=T)
        # kerb return of the A-2 guides (30 m fillet): the island lies outside the fillet circle, on the paved side
        g = J.build_piece(al, pl, "guides", params={"return_radius": 30.0}, templates=T)
        assert len(g.parts) >= 6
        assert ci.quantities["island_m2"] > 20


def test_curved_main_road_and_findings():
    pts = [(200 * math.sin(t / 100), 200 * (1 - math.cos(t / 100))) for t in range(0, 315, 5)]
    al = Alignment.from_polyline("C", pts)
    pl = J.place(al, *al.point_at(150)[:2], *(lambda x, y, h: (x - 30 * math.sin(h), y + 30 * math.cos(h)))(*al.point_at(150)))
    pcs = J.build_kit(al, pl, "A-1")
    gi = next(p for p in pcs if p.piece == "ghost_island")
    # the ghost island follows the curve: every point stays within 2 m of the centreline
    for part in gi.parts:
        for x, y in part.pts:
            assert abs(al.station_offset(x, y).offset) < 2.0
    assert J.findings(al, pl) == []
    al = straight()
    assert [l for l, _ in J.findings(al, at(al, 70))] == ["check"]
    assert [l for l, _ in J.findings(al, at(al, 55))] == ["issue"]
    assert [l for l, _ in J.findings(al, at(al, 90, sta=30))] == ["info"]
    assert J.skew_degrees(al, at(al, 70)) == pytest.approx(20)
    with pytest.raises(ValueError):
        J.place(al, 200, 0, 200.3, 0.2)
    with pytest.raises(ValueError):
        J.build_piece(al, at(al, 5), "guides", templates=T)


def test_junction_checks_in_the_furniture_report():
    al = straight()
    js = [{"sta": 100, "crossing_deg": 90, "kit": "B", "side": "L"},
          {"sta": 200, "crossing_deg": 70, "kit": "C", "side": "R"},
          {"sta": 300, "crossing_deg": 50, "kit": "A-2", "side": "L"}]
    out = FR.junction_checks(al, js)
    assert [(c.level, c.start) for c in out] == [("check", 200), ("issue", 300)]
    assert all(c.kind == "junction_skew" for c in out)


def test_our_road_joins_a_main_road():
    ours = Alignment.from_polyline("OURS", [(200, 300), (200, 3.0)])            # runs south onto the main road
    major = Alignment.from_polyline("MAJOR", [(0, 0), (400, 0)])
    pl, main = J.place_minor(ours, 200, 2.0, major=major)
    assert pl.role == "minor" and pl.main_ref == "alg:MAJOR" and pl.our_station == pytest.approx(297.0)
    assert J.main_alignment(ours, pl, [major]) is major
    F = pl.frame(main)
    assert F.side == "L" and math.degrees(pl.bearing) == pytest.approx(90)    # minor road leaves northwards
    # the kit is drawn on the main road: the ghost island lies along it, the splitter up our road
    pcs = {p.piece: p for p in J.build_kit(main, pl, "A-1", templates=T)}
    assert all(abs(y) < 2.0 for p in pcs["ghost_island"].parts for _, y in p.pts)
    assert all(198.4 < x < 201.6 and y > 3.5 for p in pcs["splitter_a1"].parts for x, y in p.pts)
    # R2 Give Way on our approach: on the left of the southbound traffic (east, our L), behind the give way line
    sg = J.minor_signs(ours, pl, main)
    assert sg == [{"code": "R2", "station": pytest.approx(297.0 - 6.0), "side": "L", "facing": "Forward"}]
    # our chainage running the other way: the sign mirrors
    rev = Alignment.from_polyline("REV", [(200, 3.0), (200, 300)])
    pr, mr = J.place_minor(rev, 200, 2.0, major=major)
    assert J.minor_signs(rev, pr, mr) == [{"code": "R2", "station": pytest.approx(6.0), "side": "R",
                                          "facing": "Backward"}]
    # no main road alignment: a clicked direction gives a straight one
    pc, mc = J.place_minor(ours, 200, 2.0, 380, 2.0)
    assert pc.main_ref.startswith("line:") and J.main_alignment(ours, pc).name == "MAJOR"
    assert pc.frame(mc).crossing_angle == pytest.approx(90, abs=0.5)
    with pytest.raises(ValueError):
        J.main_alignment(ours, pl, [])                                           # alignment gone from the LandXML
    with pytest.raises(ValueError):
        J.place_minor(ours, 200, 2.0)                                            # neither alignment nor click
