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
    lines = {n: pts for n, _, pts in FL.edge_lines(al)}
    z = lines["RFD Walkway L"][0][2]
    assert z == pytest.approx(100.0 - 5.0 * 0.025 - 3.0 * 0.04)


def test_thinning_keeps_tolerance_and_long_lines_are_split():
    import math
    # a straight constant grade collapses to its ends; an arc keeps enough vertices for 20 mm
    straight = [(x, 0.0, 100 + 0.01 * x) for x in range(0, 1001, 5)]
    assert FL.simplify(straight) == [straight[0], straight[-1]]
    arc = [(1000 * math.sin(a / 1000), 1000 * (1 - math.cos(a / 1000)), 100.0) for a in range(0, 301, 5)]
    kept = FL.simplify(arc)
    assert 2 < len(kept) < len(arc)
    for x, y, _ in arc:                                     # every sample within 20 mm of the thinned line
        d = min(abs(math.hypot(x - a[0], y - a[1]) + math.hypot(x - b[0], y - b[1]) - math.hypot(b[0] - a[0], b[1] - a[1]))
                for a, b in zip(kept, kept[1:]))
        assert d < 0.05
    pieces = FL.split("RFD ETW L", "ETW", [(float(i), 0.0, 0.0) for i in range(1200)], max_vertices=500)
    assert [p[0] for p in pieces] == ["RFD ETW L", "RFD ETW L-2", "RFD ETW L-3"]
    assert pieces[0][2][-1] == pieces[1][2][0] and sum(len(p[2]) for p in pieces) == 1200 + 2
