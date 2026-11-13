"""Road edges and widenings as Civil 3D feature lines (LandXML PlanFeatures)."""
import xml.etree.ElementTree as ET  # nosec B405 - parses a file the test itself wrote

import pytest

from rfd import feature_lines as FL
from rfd import typical_section as T
from rfd.alignment import Alignment
from rfd.profile import VerticalProfile

NS = {"x": "http://www.landxml.org/schema/LandXML-1.2"}


def road():
    al = Alignment.from_polyline("C", [(1000.0, 5000.0), (1400.0, 5000.0)])
    al.profile = VerticalProfile("p", [(0, 100, 0), (al.sta_end, 104, 0)])         # 1 % up
    al.ground = [(0.0, 100.0), (al.sta_end, 104.0)]
    T.apply(al, T.TypicalSection.standard("R5"))
    return al


def test_levels_follow_profile_and_crossfall():
    al = road()
    assert FL.level_at(al, 200.0, 0.0) == pytest.approx(102.0)
    assert FL.level_at(al, 200.0, -3.5) == pytest.approx(102.0 - 3.5 * 0.025)
    assert FL.level_at(al, 200.0, 5.5) == pytest.approx(102.0 - 5.5 * 0.025)
    assert FL.level_at(al, 200.0, 8.0) == pytest.approx(102.0 - 8.0 * 0.025)        # widening: crossfall carried on


def test_export_writes_feature_lines_civil3d_reads(tmp_path):
    al = road()
    bay = [(1100.0, 5000.0 - 5.5), (1115.0, 5000.0 - 9.0), (1145.0, 5000.0 - 9.0), (1160.0, 5000.0 - 5.5)]
    p = tmp_path / "fl.xml"
    n, notes = FL.export(str(p), al, parts=[("BAYEDGE", 120.0, [bay]), ("KERB", 0.0, [bay])])
    assert n == 5 and any("superelevation" in m for m in notes)                     # 4 edges + 1 bay edge; no super
    assert any("PIs" in m for m in notes)
    root = ET.parse(p).getroot()  # nosec B314 - the test's own output
    pf = root.findall("x:PlanFeatures/x:PlanFeature", NS)
    assert sorted(f.get("name") for f in pf) == ["RFD BAYEDGE 1", "RFD EPS L", "RFD EPS R", "RFD ETW L", "RFD ETW R"]
    for f in pf:
        feat = f.find("x:Feature", NS)
        assert feat.get("code") == "FeatureLine" and feat.get("source") == "Autodesk Civil 3D"
        assert {p.get("label"): p.get("value") for p in feat.findall("x:Property", NS)}["site"] == "RFD"
    etw_r = next(f for f in pf if f.get("name") == "RFD ETW R")
    first = etw_r.find("x:CoordGeom/x:Line/x:Start", NS).text.split()
    # northing easting elevation; the right edge is south of an eastward road
    assert [float(v) for v in first] == pytest.approx([5000.0 - 3.5, 1000.0, 100.0 - 3.5 * 0.025], abs=1e-3)
    assert root.find("x:Units/x:Metric", NS).get("linearUnit") == "meter"


def test_no_profile_or_edges_refused(tmp_path):
    al = Alignment.from_polyline("C", [(0, 0), (100, 0)])
    with pytest.raises(ValueError):
        FL.export(str(tmp_path / "a.xml"), al)
    al.profile = VerticalProfile("p", [(0, 100, 0), (100, 100, 0)])
    with pytest.raises(ValueError, match="no road edges"):
        FL.export(str(tmp_path / "a.xml"), al)


def test_verge_elements_take_their_own_fall():
    al = road()
    ts = T.TypicalSection([T.SectionRange([("ETW", 3.5), ("EPS", 1.5), ("Walkway", 3.0)],
                                          [("ETW", 3.5), ("EPS", 1.5)])])
    T.apply(al, ts)
    lines = {fl.name: fl for fl in FL.edge_lines(al)}
    z = lines["RFD Walkway L"].pis[0][2]
    assert z == pytest.approx(100.0 - 5.0 * 0.025 - 3.0 * 0.04)


def test_thinning_keeps_tolerance():
    import math
    straight = [(x, 0.0, 100 + 0.01 * x) for x in range(0, 1001, 5)]
    assert FL.simplify(straight) == [straight[0], straight[-1]]
    fl = FL.build("s", "ETW", straight)
    assert len(fl.pis) == 2 and fl.elev == []                    # a straight grade: two PIs, nothing between
    crest = [(x, 0.0, 100 - (x - 500) ** 2 / 50000) for x in range(0, 1001, 5)]
    fl = FL.build("c", "ETW", crest)
    assert len(fl.pis) == 2 and len(fl.elev) > 5                 # a vertical curve: levels as elevation points
    for x, _, z in crest:                                        # every sample within 5 mm of the kept levels
        pts = sorted([(p[0], p[2]) for p in fl.pis + fl.elev])
        k = next(i for i in range(len(pts) - 1) if pts[i][0] <= x <= pts[i + 1][0])
        (x0, z0), (x1, z1) = pts[k], pts[k + 1]
        assert abs(z - (z0 + (z1 - z0) * (x - x0) / (x1 - x0))) <= 0.005 + 1e-9


def test_edges_on_alignment_arcs_are_written_as_curves(tmp_path):
    import math
    from rfd.alignment import Arc, Line
    l1 = Line((1000.0, 5000.0), (1300.0, 5000.0))
    arc = Arc((1300.0, 5000.0), (1300.0, 5200.0), 200, True, 300)          # left turn, centre to the north
    al = Alignment("A", [l1, arc], 0.0, [], [(0.0, 80.0)])
    al.profile = VerticalProfile("p", [(0, 100, 0), (al.sta_end, 100, 0)])
    T.apply(al, T.TypicalSection.standard("R5"))
    lines = {fl.name: fl for fl in FL.edge_lines(al)}
    etw_l = lines["RFD ETW L"]
    assert len(etw_l.arcs) == 1 and len(etw_l.pis) == 3                     # tangent + one curve
    (cx, cy, r, rot), = etw_l.arcs.values()
    assert (cx, cy, rot) == (1300.0, 5200.0, "ccw") and r == pytest.approx(200 - 3.5)
    p = tmp_path / "a.xml"
    FL.write_landxml(str(p), list(lines.values()))
    root = ET.parse(p).getroot()  # nosec B314 - the test's own output
    pf = next(f for f in root.findall("x:PlanFeatures/x:PlanFeature", NS) if f.get("name") == "RFD ETW L")
    curve = pf.find("x:CoordGeom/x:Curve", NS)
    assert curve.get("rot") == "ccw" and float(curve.get("radius")) == pytest.approx(196.5, abs=1e-3)
    assert float(curve.get("length")) == pytest.approx(196.5 * 300 / 200, abs=1e-2)
    assert [float(v) for v in curve.find("x:Center", NS).text.split()] == [5200.0, 1300.0]   # northing easting
