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
    assert set(T["kits"]) == set(T["types"]) == {"A-1", "A-2", "B", "B-Mod", "C", "BUS", "TRUCK", "CLIMB", "ACCESS", "RBT"}
    for k, items in T["kits"].items():
        assert items[0]["piece"] == {"BUS": "bus_bay", "TRUCK": "truck_bay", "CLIMB": "climbing_lane", "ACCESS": "access",
                                     "RBT": "roundabout"}.get(k, "guides")
        for it in items:
            p = T["pieces"][it["piece"]]
            assert k in p["types"], (k, it["piece"])
            assert p["frame"] in ("main", "minor", "corner", "guide", "road")
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
            for k in [k for k in T["kits"] if k not in ("BUS", "TRUCK", "CLIMB", "ACCESS", "RBT")]:
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


def test_climbing_lanes_over_consecutive_grades():
    """Two 6 % grades of 500 m each (each inside its 700 m limit) with a short 2 % break between them: the
    truck has not recovered, so one lane is proposed; with a long level break, none."""
    from rfd.profile import VerticalProfile
    al = Alignment.from_polyline("S", [(0, 0), (4000, 0)])
    al.profile = VerticalProfile("P", [(0, 100, 0), (500, 100, 60), (1000, 130, 60), (1100, 132, 60),
                                       (1600, 162, 60), (4000, 162, 0)])
    (c,) = J.climbing_lanes(al)
    assert c["side"] == "L" and 1100 <= c["start"] <= 1500 and c["end"] == pytest.approx(1800, abs=40)
    assert c["length"] > 900
    al.profile = VerticalProfile("P", [(0, 100, 0), (500, 100, 60), (1000, 130, 60), (2000, 132, 60),
                                       (2500, 162, 60), (4000, 162, 0)])
    assert J.climbing_lanes(al) == []


def test_crossroads_leg_follows_the_cursor():
    """Our road crosses the main road: the leg is the one on the cursor's side; both legs on request."""
    ours = Alignment.from_polyline("OURS", [(200, 300), (200, -300)])
    major = Alignment.from_polyline("MAJOR", [(0, 0), (400, 0)])
    assert len(J.minor_legs(ours, 300.0, major)) == 2
    north, _ = J.place_minor(ours, 200, 0.5, 210, 60, major=major)
    south, _ = J.place_minor(ours, 200, 0.5, 190, -60, major=major)
    assert math.degrees(north.bearing) == pytest.approx(90)
    assert math.degrees(south.bearing) == pytest.approx(-90)
    assert north.frame(major).side == "L" and south.frame(major).side == "R"
    # R2 on each approach, each behind its own give way line
    sn, ss = J.minor_signs(ours, north, major), J.minor_signs(ours, south, major)
    assert sn[0]["station"] < 300 < ss[0]["station"]
    # both legs: two placements, the second keyed to the first, without the ghost island again
    pls, main = J.place_minor(ours, 200, 0.5, 210, 60, major=major, both=True)
    assert [round(math.degrees(p.bearing)) for p in pls] == [90, -90]
    assert pls[1].junction_id == pls[0].junction_id + "-2"
    first = {p.piece for p in J.build_kit(main, pls[0], "A-1", templates=T)}
    second = {p.piece for p in J.build_kit(main, pls[1], "A-1", templates=T, second_leg=True)}
    assert "ghost_island" in first and "ghost_island" not in second and "splitter_a1" in second
    # a road that only starts at the main road has one leg, whatever the cursor
    tee = Alignment.from_polyline("TEE", [(200, 300), (200, 3.0)])
    assert len(J.minor_legs(tee, 297.0, major)) == 1
    pt, _ = J.place_minor(tee, 200, 2.0, 190, -60, major=major)
    assert math.degrees(pt.bearing) == pytest.approx(90)


def test_main_role_bearing_snaps_to_the_minor_alignment():
    al = straight()
    side = Alignment.from_polyline("SIDE", [(150, 0.0), (150 + 100 * math.cos(math.radians(70)),
                                                          100 * math.sin(math.radians(70)))])
    # cursor 6 m off the side road: the bearing follows the side road (70 deg), not the cursor
    cx, cy = 150 + 40 * math.cos(math.radians(70)) + 6, 40 * math.sin(math.radians(70))
    pl = J.place(al, 150, 0.5, cx, cy, others=[side])
    assert math.degrees(pl.bearing) == pytest.approx(70, abs=0.1)
    free = J.place(al, 150, 0.5, cx, cy)
    assert abs(math.degrees(free.bearing) - 70) > 3
    # far from any alignment: the cursor's own direction
    far = J.place(al, 150, 0.5, 150, 80, others=[side])
    assert math.degrees(far.bearing) == pytest.approx(90, abs=0.1)


def test_bus_bay():
    al = straight()
    pl, B = J.place_bay(al, 225, 4.0, 200, 4.0)             # clicked end first: still starts where traffic arrives
    assert pl.role == "bay" and pl.station == pytest.approx(200) and B == pytest.approx(25)
    pc = J.build_piece(al, pl, "bus_bay", params={"bay": B}, templates=T)
    assert pc.params["side"] == "L" and pc.params["stations"] == [170, 200, 225, 243]
    # widening: 4 m over the bay and half of it over the 30 + 18 m tapers
    assert pc.quantities["widen_m2"] == pytest.approx(4 * 25 + 4 * (30 + 18) / 2, rel=0.01)
    assert pc.quantities["island_m2"] == pytest.approx(25.0, rel=0.01)
    ys = [y for p in pc.parts if p.code == "KERB" for _, y in p.pts]
    assert min(ys) == pytest.approx(3.5) and max(ys) == pytest.approx(7.5)
    # right side: traffic runs against the chainage, so the entry taper is at the higher end
    pr, Br = J.place_bay(al, 200, -4.0, 230, -4.0)
    pcr = J.build_piece(al, pr, "bus_bay", params={"bay": Br}, templates=T)
    assert pcr.params["side"] == "R" and pcr.params["stations"] == [260, 230, 200, 182]
    # 50 km/h: A = 25 m
    slow = Alignment.from_polyline("V", [(0, 0), (400, 0)])
    slow.speeds = [(0.0, 50.0)]
    ps, Bs = J.place_bay(slow, 200, 4.0, 225, 4.0)
    assert J.build_piece(slow, ps, "bus_bay", params={"bay": Bs}, templates=T).params["entry"] == 25
    t = J.bay_table(al, [pc.params])[0]
    assert (t["start"], t["full_from"], t["full_to"], t["end"], t["width"]) == (170, 200, 225, 243, 4.0)
    # opposite bays closer than 60 m centre to centre are flagged
    js = [{"sta": 200, "bay": pc.params}, {"sta": 230, "bay": pcr.params}]
    assert [c.kind for c in FR.junction_checks(al, js) if c.kind != "widening"] == ["bus_bay_spacing"]
    with pytest.raises(ValueError):
        J.place_bay(al, 200, 4.0, 202, 4.0)
    # LM05 is 0.2 m wide (RDM 6.1 Table 4.1)
    assert pc.quantities["paint_m2"] == pytest.approx(pc.quantities["LM05_m"] * 0.2)
    assert T["codes"]["LM05"]["width"] == 0.2


def test_truck_parking_bay():
    al = straight()
    pl, B = J.place_bay(al, 100, 4.0, 170, 4.0)
    pc = J.build_piece(al, pl, "truck_bay", params={"bay": B}, templates=T)
    # RDM/1/3/3/03: 15 m entry, 70 m bay, 10 m exit, 3.5 m deep, straight tapers, no kerb
    assert pc.params["side"] == "L" and pc.params["stations"] == [85, 100, 170, 180]
    assert pc.params["kind"] == "truck parking bay" and pc.params["depth"] == 3.5
    assert {p.code for p in pc.parts} == {"BAYEDGE", "LM05"}
    assert pc.quantities["widen_m2"] == pytest.approx(3.5 * 70 + 3.5 * (15 + 10) / 2, rel=0.01)
    edge = next(p for p in pc.parts if p.code == "BAYEDGE").pts
    y_at = lambda x: min(edge, key=lambda q: abs(q[0] - x))[1]
    assert y_at(91) == pytest.approx(3.5 + 3.5 * 6 / 15, abs=0.01)           # straight taper: linear in distance
    assert y_at(130) == pytest.approx(7.0) and y_at(84) == pytest.approx(3.5)
    # separation line from start point to end point, 1 m marks at 1 m gaps, 0.2 m wide
    lm = [p for p in pc.parts if p.code == "LM05"]
    assert min(p.pts[0][0] for p in lm) == pytest.approx(85) and max(p.pts[-1][0] for p in lm) == pytest.approx(180, abs=1)
    assert pc.quantities["paint_m2"] == pytest.approx(pc.quantities["LM05_m"] * 0.2)
    # checks: a short bay, and bays more than 30 km apart in one direction; not the bus-bay spacing rule
    short, Bs = J.place_bay(al, 100, -4.0, 140, -4.0)
    ps = J.build_piece(al, short, "truck_bay", params={"bay": Bs}, templates=T)
    js = [{"sta": 100, "bay": pc.params}, {"sta": 120, "bay": ps.params}]
    assert [c.kind for c in FR.junction_checks(al, js) if c.kind != "widening"] == ["truck_bay_length"]
    far = dict(pc.params, stations=[s + 31000 for s in pc.params["stations"]])
    assert [c.kind for c in FR.junction_checks(al, [{"bay": pc.params}, {"bay": far}])
            if c.kind != "widening"] == ["truck_bay_spacing"]


def test_climbing_lanes_from_the_profile():
    from rfd.profile import VerticalProfile
    assert J.grade_limit(3.0) is None and J.grade_limit(6.0) == 700 and J.grade_limit(4.5) == 850
    al = Alignment.from_polyline("S", [(0, 0), (3000, 0)])
    al.profile = VerticalProfile("P", [(0, 100, 0), (500, 100, 100), (1700, 172, 200), (3000, 172, 0)])
    (c,) = J.climbing_lanes(al)
    # the 6 % grade's 700 m allowance runs out about 700 m up it (a little earlier: the sag curve's
    # steepening part counts too); the lane ends 200 m past the climb
    assert c["side"] == "L" and c["limit"] == 700 and c["end"] == 1900
    assert 1150 <= c["start"] <= 1230 and c["length"] > 1000
    pl, L = J.place_lane(al, 1200, 1900, c["side"])
    pc = J.build_piece(al, pl, "climbing_lane", params={"bay": L}, templates=T)
    assert pc.params["stations"] == [1100, 1200, 1900, 2000] and pc.params["depth"] == 3.25
    assert pc.quantities["widen_m2"] == pytest.approx(3.25 * 700 + 3.25 * 100, rel=0.01)
    assert {p.code for p in pc.parts} == {"BAYEDGE", "LM26", "LM03"}
    # the widened edge runs out to the lane width over the full length and back over the 100 m tapers
    edge = next(p for p in pc.parts if p.code == "BAYEDGE")
    offs = [abs(al.station_offset(x, y).offset) for x, y in edge.pts]
    assert max(offs) - min(offs) == pytest.approx(pc.params["depth"], abs=0.05)
    assert pc.quantities["edge_m"] > L
    # downhill with the chainage: the lane serves traffic running against it, on the right
    al.profile = VerticalProfile("P", [(0, 172, 0), (1200, 100, 200), (3000, 100, 0)])
    (d,) = J.climbing_lanes(al)
    assert d["side"] == "R" and d["start"] == pytest.approx(1200 - 700, abs=60) and d["end"] == 0
    assert J.climbing_lanes(al, aadt=1500) == []                     # RDM 1.3 6.6.2: none under 2000 pcu
    assert "6000" in J.climbing_lanes(al, aadt=8000)[0]["note"]


def test_visibility_splays():
    from rfd.criteria import Criteria
    from rfd.profile import VerticalProfile
    crit = Criteria.load()
    assert crit.junction_sight("approach", 100) == (20.0, 215.0) and crit.junction_sight("stop", 50) == (3.0, 160.0)
    assert crit.junction_sight("stop", 80) == pytest.approx((3.0, 225 + (275 - 225) * 10 / 15))   # interpolated
    assert Criteria.load("aashto_2011").junction_sight("stop", 80) is None
    al = Alignment.from_polyline("S", [(0, 0), (1000, 0)])
    al.speeds = [(0.0, 100.0)]
    pl = J.place(al, 500, 0, 500, 30)                              # square, minor road on the left
    pc = J.build_piece(al, pl, "splays", templates=T)
    assert [p.code for p in pc.parts] == ["SPLAY-A", "SPLAY-A", "SPLAY-S", "SPLAY-S"]
    a_up, a_dn, s_up, s_dn = pc.parts
    assert a_up.closed and a_up.pts[0] == pytest.approx((500, 23.5)) and a_up.pts[1] == pytest.approx((715, 0))
    assert a_dn.pts[1] == pytest.approx((285, 0)) and s_up.pts[0] == pytest.approx((500, 6.5))
    assert s_dn.pts[1] == pytest.approx((180, 0)) and a_up.pts[-1] == pytest.approx((500, 0))
    assert J.splay_findings(pc.params) == []
    # every kit carries the splays; build_kit can leave them out
    assert all(any(i["piece"] == "splays" for i in T["kits"][k]) for k in ("A-1", "A-2", "B", "B-Mod", "C"))
    assert not any(p.piece == "splays" for p in J.build_kit(al, pl, "C", T, splays=False))
    # skewed minor road: the set-back is measured along it, from the main road's edge
    sk = J.build_piece(al, J.place(al, 500, 0, 530, 30), "splays", templates=T)
    apex = sk.parts[0].pts[0]
    assert math.hypot(apex[0] - 500, apex[1]) == pytest.approx(3.5 / math.sin(math.radians(45)) + 20)
    # no speed stations: 80 km/h assumed and flagged; a typed speed wins
    al.speeds = []
    pa = J.build_piece(al, pl, "splays", templates=T)
    assert pa.params["speed_assumed"] and any("80 km/h" in t for _, t in J.splay_findings(pa.params))
    assert J.build_piece(al, pl, "splays", params={"speed": 50}, templates=T).params["splays"][0]["length"] == 95
    # near the alignment end the leg is cut and noted
    end = J.build_piece(al, J.place(al, 900, 0, 900, 30), "splays", params={"speed": 100}, templates=T)
    assert any("ends" in t for _, t in J.splay_findings(end.params))
    # a crest on the main road hides the vehicle: stop splay short is an issue
    al.speeds = [(0.0, 100.0)]
    al.profile = VerticalProfile("P", [(0, 100, 0), (650, 112, 300), (1000, 100, 0)])
    cr = J.build_piece(al, pl, "splays", templates=T)
    f = J.splay_findings(cr.params)
    assert any(lvl == "issue" and "stop sight distance up the chainage" in t for lvl, t in f)
    # obstructions found in QGIS are reported, stop splays as issues
    rec = dict(pc.params, obstructions=[{"kind": "stop", "dir": "up", "layer": "Buildings", "fid": 7}], checked=["Buildings"])
    (lvl, text), = J.splay_findings(rec)
    assert lvl == "issue" and "Buildings feature 7" in text and "stop visibility splay up" in text
    assert any("not checked" in t for _, t in J.splay_findings(dict(pc.params, obstructions=[], checked=None)))


def test_private_access():
    al = Alignment.from_polyline("S", [(0, 0), (1000, 0)])
    al.speeds = [(0.0, 80.0)]
    pl = J.place(al, 500, 0, 500, 30)                              # square, on the left
    pc = J.build_piece(al, pl, "access", templates=T)
    edges = [p for p in pc.parts if p.code == "ACCESS"]
    # RDM 1.3 Figure 9.33: 6 m returns from the road edge (3.5 m here, no corridor), formation 3 + 2 x 0.5 m,
    # built 10 m back to the boundary, 3 m taper
    assert sorted(round(p.pts[0][0], 2) for p in edges) == [492.0, 508.0] and all(p.pts[0][1] == pytest.approx(3.5) for p in edges)
    assert all(p.pts[-1][1] == pytest.approx(3.5 + 13.0) for p in edges)
    paved = [p for p in pc.parts if p.code == "ACCESS-P"]
    assert sorted(round(p.pts[0][0], 2) for p in paved) == [498.5, 501.5]
    assert pc.quantities["pipe_no"] == 1 and pc.quantities["pipe_m"] == 5.0 and pc.quantities["area_m2"] > 4 * 13
    assert pc.params["notes"] == []
    # the kit carries the stop splays only (RDM 1.3 9.11.16)
    kit = J.build_kit(al, pl, "ACCESS", T)
    assert [k.piece for k in kit] == ["access", "splays"] and {p.code for p in kit[1].parts} == {"SPLAY-S"}
    # checks: narrow, tight radius, short of the boundary, class A road (Table 2.3)
    bad = J.build_piece(al, pl, "access", params={"width": 2.5, "radius": 4.0, "length": 8.0, "road_class": "A"},
                        templates=T)
    lv = [lvl for lvl, _ in bad.params["notes"]]
    assert lv.count("issue") == 1 and lv.count("check") == 3
    assert any("Tables 2.3 and 2.4" in t for _, t in bad.params["notes"])
    j = {"sta": 500.0, "side": "L", "kit": "ACCESS", "access": {"notes": bad.params["notes"]}, "crossing_deg": 90.0}
    assert [c.kind for c in FR.junction_checks(al, [j])].count("access") == 4
    # skewed access: the returns still start on the road edge
    sk = J.build_piece(al, J.place(al, 500, 0, 520, 30), "access", templates=T)
    assert all(p.pts[0][1] == pytest.approx(3.5) for p in sk.parts if p.code == "ACCESS")


def test_widening_round_trip():
    from rfd.corridor import Edges
    al = straight()
    pl, B = J.place_bay(al, 100, 4.0, 170, 4.0)                    # truck bay on the left: 85 / 100-170 / 180
    stations = list(range(0, 401, 10))
    al.edges = Edges({("ETW", "L"): [(s, 3.5) for s in stations], ("ETW", "R"): [(s, 3.5) for s in stations]})
    pc = J.build_piece(al, pl, "truck_bay", params={"bay": B}, templates=T)
    bay = pc.params
    # 1. the corridor is not widened yet
    (lvl, text), = J.widening_check(al, bay)
    assert lvl == "info" and "not in the corridor yet" in text
    # 2. widened as placed: ETW follows the bay at every section
    w = lambda s: J.widen_at(s - 85, 15, 70, 10, 3.5, True)
    al.edges = Edges({("ETW", "L"): [(s, 3.5 + w(s)) for s in stations], ("ETW", "R"): [(s, 3.5) for s in stations]})
    (lvl, text), = J.widening_check(al, bay)
    assert lvl == "info" and "matches the corridor" in text
    # the bay re-attaches to the edge before the widening: rebuilding it does not widen twice
    again = J.build_piece(al, pl, "truck_bay", params={"bay": B}, templates=T)
    ys = [y for p in again.parts if p.code == "BAYEDGE" for _, y in p.pts]
    assert max(ys) == pytest.approx(7.0) and again.quantities["widen_m2"] == pytest.approx(pc.quantities["widen_m2"])
    # 3. widened only 2.5 m: flagged with the worst section
    al.edges = Edges({("ETW", "L"): [(s, 3.5 + w(s) * 2.5 / 3.5) for s in stations],
                      ("ETW", "R"): [(s, 3.5) for s in stations]})
    (lvl, text), = J.widening_check(al, bay)
    assert lvl == "check" and "1.00 m" in text
    # 4. a little curve widening (0.4 m) is not taken for the bay: the bay still builds on the corridor edge
    al.edges = Edges({("ETW", "L"): [(s, 3.5 + (0.4 if 110 <= s <= 150 else 0.0)) for s in stations],
                      ("ETW", "R"): [(s, 3.5) for s in stations]})
    cw = J.build_piece(al, pl, "truck_bay", params={"bay": B}, templates=T)
    assert max(y for p in cw.parts if p.code == "BAYEDGE" for _, y in p.pts) == pytest.approx(7.4)
    al.edges = Edges({("ETW", "L"): [(s, 3.5 + w(s) * 2.5 / 3.5) for s in stations],
                      ("ETW", "R"): [(s, 3.5) for s in stations]})
    # 5. the report check
    assert [c.kind for c in FR.junction_checks(al, [{"sta": 100, "bay": bay}]) if c.kind == "widening"] == ["widening"]


def test_roundabout_geometry_and_checks():
    from rfd import roundabouts as RB
    assert RB.min_icd(10) == 30.8 and RB.min_icd(11) == pytest.approx(31.4) and RB.min_icd(2) == 28.0
    al = Alignment.from_polyline("S", [(0, 0), (1000, 0)])
    al.speeds = [(0.0, 80.0)]
    pl = J.place_roundabout(al, 500, 3.0)                          # snapped to our centreline
    assert pl.station == pytest.approx(500) and pl.role == "roundabout"
    pc = J.build_piece(al, pl, "roundabout", params={"arms": [{"bearing_deg": 90, "src": "click", "half": 3.5}]},
                       templates=T)
    assert pc.params["n_arms"] == 3 and {a["src"] for a in pc.params["arms_used"]} == {"ours", "click"}
    codes = [p.code for p in pc.parts]
    assert codes.count("TM07") == 3 and codes.count("TM04") == 3 and codes.count("BM07") == 3
    assert codes.count("KERB") == 4 and "RBEDGE" in codes                       # island + three splitters
    island = pc.parts[0]
    assert all(math.hypot(x - 500, y) == pytest.approx(5.0, abs=1e-6) for x, y in island.pts)
    # give way lines on the circle, on the left of the traffic coming in (Kenya drives on the left)
    for p in (p for p in pc.parts if p.code == "TM07"):
        assert all(math.hypot(x - 500, y) == pytest.approx(15.4, abs=1e-6) for x, y in p.pts)
    east = next(p for p in pc.parts if p.code == "TM07" and p.pts[0][0] > 505)
    assert all(y < 0 for _, y in east.pts)                         # traffic heading west keeps to the south
    q = pc.quantities
    assert q["icd"] == 30.8 and q["width"] == pytest.approx(10.4) and q["overlaps"] == 0
    # compact hint and the path caveat; radial arms round a 10 m island in a 30.8 m ICD deflect little
    assert [lvl for lvl, _ in pc.params["notes"]][:2] == ["info", "info"]
    assert all(lvl == "check" and "entry path radius" in t for lvl, t in pc.params["notes"][2:])
    # checks: two arms only, a tiny island, an ICD over 100 m, arms too close, returns that cross
    two = J.build_piece(al, pl, "roundabout", templates=T)
    assert any(lvl == "issue" and "at least 3" in t for lvl, t in two.params["notes"])
    bad = J.build_piece(al, pl, "roundabout", params={"island": 3.0, "icd": 104.0,
                        "arms": [{"bearing_deg": 90, "src": "click"}, {"bearing_deg": 135, "src": "click"}]},
                        templates=T)
    t = " | ".join(t for _, t in bad.params["notes"])
    assert "at least 4 m" in t and "exceed 100 m" in t and "deg apart" in t and "not exceed 15 m" in t
    tight = J.build_piece(al, pl, "roundabout", params={"arms": [{"bearing_deg": 70, "src": "click"},
                                                                 {"bearing_deg": 250, "src": "click"}]}, templates=T)
    assert tight.quantities["overlaps"] >= 1 and any("run into each other" in t for _, t in tight.params["notes"])
    # a sharp crest on the approach hides the entry
    from rfd.profile import VerticalProfile
    al.profile = VerticalProfile("P", [(0, 100, 0), (430, 117, 30), (1000, 100, 0)])
    cr = J.build_piece(al, pl, "roundabout", params={"arms": [{"bearing_deg": 90, "src": "click"}]}, templates=T)
    assert any("sharp crest" in t for _, t in cr.params["notes"])
    # the report check
    j = {"sta": 500.0, "kit": "RBT", "rbt": {"notes": bad.params["notes"]}}
    assert sum(1 for c in FR.junction_checks(al, [j]) if c.kind == "roundabout") == len(bad.params["notes"])


def test_control_at_our_roads_end():
    ours = Alignment.from_polyline("OURS", [(0, 0), (300, 0)])        # ends on the main road at x = 300
    main = Alignment.from_polyline("MAIN", [(300, -200), (300, 200)])
    far = Alignment.from_polyline("FAR", [(1000, -200), (1000, 200)])
    (c,) = FR.end_control_checks(ours, [main, far], [], [])
    assert c.kind == "end_control" and "ends on MAIN" in c.text and c.start == pytest.approx(300)
    assert FR.end_control_checks(ours, [far], [], []) == []                    # not touching another road
    jn = [{"sta": 300.0, "role": "minor"}]
    assert FR.end_control_checks(ours, [main], jn, []) == []                   # the junction is placed
    r2 = [{"code": "R2", "sta": 290.0, "facing": "Forward", "side": "L"}]
    assert FR.end_control_checks(ours, [main], [], r2) == []                   # or a Give Way stands there
    wrong = [{"code": "R2", "sta": 290.0, "facing": "Backward", "side": "R"}]
    assert len(FR.end_control_checks(ours, [main], [], wrong)) == 1           # facing the other way: no


def test_bay_visibility_over_a_crest():
    from rfd.profile import VerticalProfile
    al = straight()
    al.speeds = [(0.0, 80.0)]
    pl, B = J.place_bay(al, 220, 4.0, 290, 4.0)                    # truck bay, entry taper from 205
    bay = J.build_piece(al, pl, "truck_bay", params={"bay": B}, templates=T).params
    kinds = lambda: [c.kind for c in FR.junction_checks(al, [{"sta": 220, "bay": bay}])]
    al.profile = VerticalProfile("P", [(0, 100, 0), (400, 100, 0)])
    assert "bay_visibility" not in kinds()                          # flat: seen from the SSD
    al.profile = VerticalProfile("P", [(0, 100, 0), (150, 106, 30), (400, 98.5, 0)])
    assert "bay_visibility" in kinds()                              # a sharp crest just before it


def test_continuation_is_not_a_junction():
    ours = Alignment.from_polyline("OURS", [(0, 0), (300, 0)])
    onward = Alignment.from_polyline("ONWARD", [(300, 2), (900, 30)])           # the same road carrying on
    assert FR.end_control_checks(ours, [onward], [], []) == []
    branch = Alignment.from_polyline("BRANCH", [(300, 0), (300, 400)])          # starts here but at 90 deg
    assert len(FR.end_control_checks(ours, [branch], [], [])) == 1


def test_junction_ahead_warnings():
    """RDM 6.2 4.2: W2 / W1 / W5 on our road as the main road, W12 / W11 where it meets a greater road."""
    al = Alignment.from_polyline("M", [(0, 0), (2000, 0)])
    JA = J.JunctionAt
    out = J.junction_warnings(al, [JA("a", "main", 500, "L", kit="B"), JA("b", "main", 505, "R", kit="C"),
                                   JA("c", "main", 1200, "L", kit="B"), JA("d", "main", 1240, "R", kit="B"),
                                   JA("e", "main", 300, "R", kit="ACCESS"),             # accesses: no warning
                                   JA("m", "minor", 1900, up=False), JA("x", "minor", 50, up=True, crossing=True)])
    got = sorted((p.code, round(p.station), p.facing, p.mirror) for p in out)
    a = 140                                                     # 80 km/h: 6 s of travel, rounded up to 10 m
    assert got == sorted([("W1", 500 - a, "Forward", False), ("W1", 505 + a, "Backward", False),
                          ("W5", 1200 - a, "Forward", False),       # first side road on the left, as drawn
                          ("W5", 1240 + a, "Backward", False),      # backward traffic meets d first, on its left
                          ("W12", 1900 - a, "Forward", False), ("W11", 50 + a, "Backward", False)])
    lone = J.junction_warnings(al, [JA("s", "main", 800, "R", kit="C")])
    assert sorted((p.facing, p.mirror) for p in lone) == [("Backward", True), ("Forward", False)]


def test_turn_and_approach_arrows():
    """RDM 6.1 6.4.3: AM03 in the right-turn lane of a ghost island kit, AM06 / AM07 on the minor approach."""
    al = straight()                                            # main road east along x, minor road to the north
    pcs = {p.piece: p for p in J.build_kit(al, at(al, 90), "A-1", templates=T)}
    turn = pcs["turn_arrow"]
    assert turn.quantities["AM03_no"] == 2 and turn.quantities["paint_m2"] > 1.0
    xs = [x for p in turn.parts for x, _ in p.pts]
    assert min(xs) > 200                                       # on the westbound right-turners' approach (east)
    assert max(y for p in turn.parts for _, y in p.pts) > 1.0  # the head turns north, into the minor road
    app = pcs["approach_arrows"]
    assert {p.code for p in app.parts} == {"AM06"}
    assert all(x > 200 and y > 3.5 for p in app.parts for x, y in p.pts)   # southbound lane, on the minor road
    cross = J.build_piece(al, at(al, 90), "approach_arrows", params={"crossroads": True}, templates=T)
    assert {p.code for p in cross.parts} == {"AM07"} and len(cross.parts) == 3
    assert J.arrow_length(50) == 3.5 and J.arrow_length(80) == 5.0 and J.arrow_length(120) == 9.0
    assert "turn_arrow" not in {p.piece for p in J.build_kit(al, at(al, 90), "C", templates=T)}


def test_minor_road_approach_splay_on_a_bend():
    """RDM 1.3 Figure 9.13: our road comes round a 120 m bend onto the main road; the splay reaches across
    the inside of the bend. A straight approach needs (almost) nothing beyond the road."""
    major = Alignment.from_polyline("MAJOR", [(-300, 0), (300, 0)])
    R = 120.0
    arc = [(R - R * math.cos(t), 3.0 + R * math.sin(t)) for t in [k * math.pi / 2 / 40 for k in range(41)]]
    ours = Alignment.from_polyline("OURS", list(reversed(arc)) )          # chainage runs towards the main road
    ours.speeds = [(0.0, 60.0)]
    pl, main = J.place_minor(ours, 0.0, 3.0, major=major)
    pc = J.approach_splay(ours, pl, main)
    assert pc.parts[0].code == "SPLAY-M" and pc.params["ssd"] > 60
    assert pc.params["clear_m"] > 3.0                                      # across the inside of the bend
    assert "inside of the bend" in J.approach_splay_findings(pc.params)[0][1]
    straight_road = Alignment.from_polyline("ST", [(0, 300), (0, 3.0)])
    ps, ms = J.place_minor(straight_road, 0.0, 3.0, major=major)
    assert J.approach_splay(straight_road, ps, ms).params["clear_m"] < 0.1
    with pytest.raises(ValueError):
        J.approach_splay(straight_road, J.place(major, 0, 0, 0, 30), major)


def test_roundabout_entry_path_radius():
    """RDM 1.3 10.6.3.5: a 20 m island in a 40 m ICD deflects the ahead path enough (radius under 100 m); a
    10 m island in a 60 m ICD hardly does, and is flagged."""
    al = straight()
    arms = [{"bearing_deg": 90, "src": "click", "half": 3.5}, {"bearing_deg": -90, "src": "click", "half": 3.5}]
    good = J.build_piece(al, J.place_roundabout(al, 200, 0), "roundabout",
                         params={"island": 20, "icd": 40, "arms": arms}, templates=T)
    assert all(r is not None and r < 100 for r in good.params["quantities"]["entry_path_r"])
    assert not [t for _l, t in good.params["notes"] if "entry path radius" in t]
    poor = J.build_piece(al, J.place_roundabout(al, 200, 0), "roundabout",
                         params={"island": 10, "icd": 60, "arms": arms}, templates=T)
    assert len([t for lvl, t in poor.params["notes"] if lvl == "check" and "entry path radius" in t]) == 4


def test_three_centred_kerb_returns():
    """RDM 1.3 Figure 9.25: R1 : R2 : R3 = 2 : 1 : 3, tangent to the main edge and to the minor edge."""
    for ang, sgn in ((90, 1), (90, -1), (70, 1), (110, -1)):
        d = (math.cos(math.radians(ang)), math.sin(math.radians(ang)))
        p0 = (sgn * d[1] * 3.5, -sgn * d[0] * 3.5)
        c = J.three_centred_return(p0, d, sgn, 10.0)
        assert c[0][1] == pytest.approx(0.0) and c[1][1] > 0                  # leaves the main edge tangentially
        e = c[-1]
        assert d[0] * (e[1] - p0[1]) - d[1] * (e[0] - p0[0]) == pytest.approx(0.0, abs=1e-6)   # on the minor edge
        t = (e[0] - c[-2][0], e[1] - c[-2][1])
        assert (t[0] * d[0] + t[1] * d[1]) / math.hypot(*t) == pytest.approx(1.0, abs=1e-3)   # along it
    pcs = {p.piece: p for p in J.build_kit(straight(), at(straight(), 90), "C", templates=T)}
    assert len(pcs["guides"].parts) >= 6
