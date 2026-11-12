import pytest

from rfd.alignment import parse_landxml
from examples.make_demo_road import PROFILE_XML, build, corridor_xml, to_landxml


@pytest.fixture(scope="module")
def road():
    els = build()
    L = sum(e.length for e in els)
    return parse_landxml(to_landxml(els, extra=PROFILE_XML + corridor_xml(L, widen_from=600.0)))[0]


def test_profile_curves(road):
    pr = road.profile
    assert [c.kind for c in pr.curves] == ["crest", "sag"]
    crest, sag = pr.curves
    assert crest.grade_in == pytest.approx(2.0) and crest.grade_out == pytest.approx(-3.0)
    assert crest.k == pytest.approx(20.0) and sag.k == pytest.approx(37.5)


def test_profile_elevation_grade(road):
    pr = road.profile
    assert pr.elevation(100) == pytest.approx(102.0)                 # tangent
    assert pr.grade(100) == pytest.approx(2.0)
    assert pr.grade(300) == pytest.approx(-0.5)                      # mid-curve: average of +2/-3
    assert pr.elevation(300) == pytest.approx(106 - 5 / 100 * 100 / 8)   # PVI elev minus A*L/8
    # continuity at the curve ends
    for s in (250, 350, 625, 775):
        assert pr.elevation(s - 1e-6) == pytest.approx(pr.elevation(s + 1e-6), abs=1e-6)
    assert pr.elevation(5000) is None


def test_corridor_edges(road):
    e = road.edges
    assert e.codes() == ["ETW", "EPS"]                   # layer codes and Crown dropped
    assert e.reference() == "EPS"
    assert e.offset("ETW", "L", 333.0) == pytest.approx(3.5)
    assert e.offset("EPS", "R", 570.0) == pytest.approx(5.0)
    assert e.offset("EPS", "R", 590.0) == pytest.approx(5.5)   # widening interpolated 580-600
    assert e.offset("EPS", "R", 610.0) == pytest.approx(6.0)
    assert e.offset("EPS", "R", 9999.0) is None


def test_no_corridor_is_none():
    al = parse_landxml(to_landxml(build()))[0]
    assert al.edges is None and al.profile is None


def test_sign_checks_and_clearance(road):
    from rfd.catalogue import Catalogue
    from rfd.records import build_signlist
    cat = Catalogue.load()
    recs = [   # spread along the road so the RDM 0.6V spacing check stays quiet
        {"ref": 1, "station": 100, "offset": 2.0, "side": "L", "facing": "Forward", "code": "W64"},  # in lane
        {"ref": 2, "station": 200, "offset": 4.2, "side": "L", "facing": "Forward", "code": "W64"},  # shoulder
        {"ref": 3, "station": 300, "offset": 6.0, "side": "L", "facing": "Forward", "code": "W64"},  # fine
        {"ref": 4, "station": 400, "offset": 6.0, "side": "L", "facing": "Forward", "code": "W64", "edge_ref": "ETW"},
    ]
    sl = build_signlist(recs, road, cat)
    msgs = {i.row: (i.level, i.message) for i in sl.issues}
    assert msgs[1][0] == "error" and "travelled way" in msgs[1][1]
    assert msgs[2][0] == "warning" and "shoulder" in msgs[2][1]
    assert 3 not in msgs
    f3 = [f for f in sl.faces if f.row == 3][0]
    f4 = [f for f in sl.faces if f.row == 4][0]
    assert (f3.edge_ref, f3.edge_clear) == ("EPS", pytest.approx(1.0))
    assert (f4.edge_ref, f4.edge_clear) == ("ETW", pytest.approx(2.5))
    assert f3.grade == pytest.approx(-0.5)      # 300 = crest PVI
    # an overlay's sign (a chevron on a roundabout island) is not judged against our road's edges
    isl = build_signlist([{"ref": 9, "station": 100, "offset": 2.0, "side": "L", "facing": "Backward",
                           "code": "W24-b", "rule": "junction:abc"}], road, cat)
    assert not [i for i in isl.issues if i.row == 9]
    assert [f for f in isl.faces if f.row == 9][0].edge_clear is not None
