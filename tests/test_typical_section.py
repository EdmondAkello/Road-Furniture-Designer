"""Typical section: edges and simplified sections from user offsets for a centreline-only LandXML."""
import pytest

from rfd import barriers as B
from rfd import typical_section as T
from rfd.alignment import Alignment
from rfd.corridor import Edges
from rfd.profile import VerticalProfile


def road(length=1000.0, ground=None):
    al = Alignment.from_polyline("C", [(0, 0), (length, 0)])
    al.speeds = [(0.0, 80.0)]
    al.profile = VerticalProfile("p", [(0, 100, 0), (al.sta_end, 100, 0)])
    al.ground = ground if ground is not None else [(0.0, 100.0), (length, 100.0)]
    return al


def test_standard_section_gives_corridor_like_edges():
    al = road()
    ts = T.TypicalSection.standard("R5")
    assert T.apply(al, ts)
    assert al.edge_source == T.SOURCE
    assert al.edges.offset("ETW", "L", 500) == pytest.approx(3.50)
    assert al.edges.offset("EPS", "R", 500) == pytest.approx(5.50)
    assert al.edges.reference() == "EPS"
    assert al.edges.codes() == ["ETW", "EPS"]


def test_ranges_with_a_transition_and_checks():
    al = road()
    town = T.SectionRange([("ETW", 3.5), ("EPS", 1.5), ("Walkway", 3.0)], [("ETW", 3.5), ("EPS", 1.5)], 400, None, "U")
    rural = T.SectionRange([("ETW", 3.0), ("EPS", 1.0)], [("ETW", 3.0), ("EPS", 1.0)], None, 400, "R7")
    ts = T.TypicalSection([town, rural], transition=40.0)
    assert ts.check(al) == []
    T.apply(al, ts)
    assert al.edges.offset("ETW", "L", 300) == pytest.approx(3.0)
    assert al.edges.offset("ETW", "L", 420) == pytest.approx(3.25)          # half way through the 40 m change
    assert al.edges.offset("ETW", "L", 500) == pytest.approx(3.5)
    assert al.edges.offset("Walkway", "L", 500) == pytest.approx(8.0)
    assert al.edges.offset("Walkway", "L", 300) is None                       # only in the town range
    gap = T.TypicalSection([T.SectionRange([("ETW", 3)], [("ETW", 3)], 0, 300),
                            T.SectionRange([("ETW", 3)], [("ETW", 3)], 350, None)])
    assert any("no section from 300 to 350" in m for m in gap.check(al))


def test_corridor_kept_unless_asked():
    al = road()
    al.edges = Edges({("ETW", "L"): [(0, 3.65), (1000, 3.65)], ("ETW", "R"): [(0, 3.65), (1000, 3.65)]})
    ts = T.TypicalSection.standard("R7")
    assert not T.apply(al, ts)
    assert al.edge_source == "corridor" and al.edges.offset("ETW", "L", 10) == pytest.approx(3.65)
    ts.use_over_corridor = True
    assert T.apply(al, ts)
    assert al.edges.offset("ETW", "L", 10) == pytest.approx(3.0)
    assert any("ETW left" in m for m in T.compare(al, ts))
    T.apply(al, None)                                                          # switched off: corridor back
    assert al.edge_source == "corridor" and al.edges.offset("ETW", "L", 10) == pytest.approx(3.65)


def test_round_trip_through_json():
    ts = T.TypicalSection([T.SectionRange([("ETW", 3.65), ("EPS", 2.5)], [("ETW", 3.65)], 0, 500, "A")],
                          crossfall=3.0, use_over_corridor=True, others="R6")
    back = T.TypicalSection.from_dict(ts.to_dict())
    assert back == ts


def test_sections_give_fill_heights_for_barriers():
    # design 100 m all along; ground 92 m (8 m fill) from 300 to 500, level with the road elsewhere
    g = [(0, 100.0), (280, 100.0), (300, 92.0), (500, 92.0), (520, 100.0), (1000, 100.0)]
    al = road(ground=g)
    T.apply(al, T.TypicalSection.standard("R5"))
    f = B.side_fill(al, 400.0, "L", None)
    assert f is not None and f.source == "daylight"
    hinge_z = -5.5 * 0.025                                                  # paved shoulder at the crossfall
    assert f.height == pytest.approx(hinge_z + 8.0, abs=1e-3)
    assert f.slope_n == pytest.approx(2.0, abs=1e-3)                          # the fill batter
    assert B.side_fill(al, 100.0, "L", None) is None                          # level ground: no fill
    runs, _ = B.propose_barriers(al, B.BarrierConfig())
    assert runs and {r.side for r in runs} == {"L", "R"} and all(r.sta_start < 400 < r.sta_end for r in runs)


def test_no_ground_profile_no_daylight():
    al = road(ground=[])
    T.apply(al, T.TypicalSection.standard("R5"))
    assert al.edges and al.sections
    assert all(c != "Daylight" for *_, c in al.sections.side(500.0, "L"))


def test_side_roads_get_the_chosen_standard_section():
    ts = T.TypicalSection.standard("R5")
    assert ts.for_others() is None
    ts.others, ts.crossfall = "R7", 3.0
    side = road()
    T.apply(side, ts.for_others())
    assert side.edges.offset("ETW", "R", 10.0) == pytest.approx(3.0)
    assert side.edges.offset("EPS", "R", 10.0) == pytest.approx(4.0)


def test_superelevation_rotates_the_pavement_about_the_centreline():
    from rfd.alignment import Arc, Line
    l1 = Line((0, 0), (300, 0))
    arc = Arc((300, 0), (300, 200), 200, True, 300)       # turns left (centre to the north)
    al = Alignment("S", [l1, arc], 0.0, [], [(0.0, 80.0)])
    al.profile = VerticalProfile("p", [(0, 100, 0), (al.sta_end, 100, 0)])
    # full 6 % from 350 to 550, runoff 49 m, runout 20.4 m (as Civil 3D writes it)
    al.super_runs = [{"e": -6.0, "full": 350.0, "runoff": 550.0, "begin_runout": 280.6, "begin_runoff": 301.0,
                      "start_runout": 599.0, "end_runout": 619.4}]
    assert T.cross_slopes(al, 100.0, 2.5) == {"L": -2.5, "R": -2.5}               # tangent: normal crown
    assert T.cross_slopes(al, 301.0, 2.5) == pytest.approx({"L": -2.5, "R": 0.0})   # outer (right) level
    assert T.cross_slopes(al, 450.0, 2.5) == pytest.approx({"L": -6.0, "R": 6.0})   # full: inner falls, outer rises
    mid = T.cross_slopes(al, 325.5, 2.5)                                            # half way up the runoff
    assert mid["R"] == pytest.approx(3.0) and mid["L"] == pytest.approx(-3.0)
    T.apply(al, T.TypicalSection.standard("R5"))
    pts = {c: z for o, z, c in al.sections.side(450.0, "R")}
    assert pts["ETW"] == pytest.approx(3.5 * 0.06)                                  # outer edge up
    # no detail stations in the file: runoff / runout from a 0.5 % relative gradient
    al.super_runs = [{"e": 6.0, "full": 350.0, "runoff": 550.0}]
    assert T.cross_slopes(al, 350.0 - 42.0, 2.5)["R"] == pytest.approx(0.0)
