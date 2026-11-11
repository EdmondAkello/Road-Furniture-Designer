"""Road furniture pages of the report: strip diagram, schedules and checks."""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
sys.path.insert(0, ROOT)

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject  # noqa: E402

if QgsApplication.instance() is None:
    _app = QgsApplication([], True)
    _app.initQgis()

from road_furniture_designer.store import SignStore  # noqa: E402
from examples.make_demo_road import build, corridor_xml, to_landxml  # noqa: E402

CRS = QgsCoordinateReferenceSystem("EPSG:21037")


def _fill_road(tmp_path):
    """Demo road with a corridor and an 8 m embankment between 300 and 500 (1:1.5 batters)."""
    QgsProject.instance().clear()
    els = build()
    L = sum(e.length for e in els)
    prof = ('<Profile name="DEMO"><ProfAlign name="FRL"><PVI>0 100</PVI><PVI>%.3f 100</PVI></ProfAlign></Profile>' % L)

    def fill(m):
        body = m.group(0)
        if 300 <= float(m.group(1)) <= 500:
            for side in (-1, 1):
                body = body.replace("</DesignCrossSectSurf>",
                                    '<CrossSectPnt code="Hinge">%.1f -0.2</CrossSectPnt>'
                                    '<CrossSectPnt code="Daylight">%.1f -8.2</CrossSectPnt></DesignCrossSectSurf>'
                                    % (side * 6.0, side * 18.0), 1)
        return body
    sec = re.sub(r'<CrossSect sta="([^"]+)".*?</CrossSect>', fill, corridor_xml(L), flags=re.S)
    xml = tmp_path / "road.xml"
    xml.write_text(to_landxml(els, extra=prof + sec))
    st = SignStore.create(str(tmp_path / "signs.gpkg"), str(xml), "DEMO-RD", CRS, "Test")
    st.add_to_project()
    return st, str(xml)


def _project(tmp_path):
    from road_furniture_designer.rfd.autoplace import AutoConfig
    from road_furniture_designer.rfd.barriers import BarrierConfig
    from road_furniture_designer.rfd.features import FeatureConfig
    from road_furniture_designer.rfd.markings import MarkingConfig
    st, xml = _fill_road(tmp_path)
    auto = AutoConfig()
    st.auto_propose(auto)
    st.lines.auto_propose_markings(MarkingConfig.from_auto(auto, road_class="B"))
    st.lines.auto_propose_barriers(BarrierConfig(landxml=xml))
    st.add_feature("crossing", 700.0, FeatureConfig(), auto)
    st.add_feature("hump_circular", 900.0, FeatureConfig(), auto)
    return st, xml, auto


def test_furniture_pages_and_workbook(tmp_path):
    from road_furniture_designer.rfd.barriers import BarrierConfig
    from road_furniture_designer.rfd.features import FeatureConfig
    from road_furniture_designer.report import ReportData, pages, write_pdf, write_pngs, write_xlsx
    st, xml, auto = _project(tmp_path)
    d = ReportData(st, auto, title="Road Furniture", barrier_cfg=BarrierConfig(landxml=xml),
                   feature_cfg=FeatureConfig())
    kinds = [k for k, _ in pages(d, 500)]
    assert "strip" in kinds
    tables = [p[0] for k, p in pages(d, 500) if k == "ftable"]
    assert {"markings", "barriers", "features", "fquantities", "checks"} <= set(tables)
    # the warranted barrier is in the project, so K1 finds nothing missing
    assert not d.fr.checks_of("barrier_missing")
    kinds_g = {g["kind"] for g in d.fr.features}
    assert kinds_g == {"crossing", "hump_circular"}
    n = write_pdf(str(tmp_path / "r.pdf"), d, sheet_len=500)
    assert n == len(kinds)
    pngs = write_pngs(str(tmp_path / "s"), d, sheet_len=500)
    assert any(os.path.basename(p).startswith("strip_") for p in pngs)
    write_xlsx(str(tmp_path / "r.xlsx"), d)
    from openpyxl import load_workbook
    wb = load_workbook(tmp_path / "r.xlsx")
    assert "RSA Stage 2" not in wb.sheetnames
    chk = list(wb["Furniture checks"].iter_rows(min_row=2, values_only=True))
    assert len(chk) == len(d.fr.checks) + len(d.fr.notes)
    bars = list(wb["Barriers"].iter_rows(min_row=2, values_only=True))
    assert bars and all(b[0] == "GR-W" for b in bars)
    feats = list(wb["Features"].iter_rows(min_row=2, values_only=True))
    assert {f[2] for f in feats} == {"crossing", "hump_circular"}


def test_removed_barrier_and_centre_line_are_reported(tmp_path):
    from road_furniture_designer.rfd.barriers import BarrierConfig
    from road_furniture_designer.report import ReportData
    st, xml, auto = _project(tmp_path)
    lyr = st.lines.layer
    bars = [f.id() for f in lyr.getFeatures() if f["item_code"] == "GR-W"]
    centre = [f.id() for f in lyr.getFeatures() if f["side"] == "C" and f["item_code"].startswith("LM")]
    st.lines._set_status_or_delete(bars + centre)
    d = ReportData(st, auto, barrier_cfg=BarrierConfig(landxml=xml))
    assert d.fr.checks_of("barrier_missing")[0].level == "issue"
    zones = sum(len(v) for v in d.fr.zones.values())
    if zones:
        assert d.fr.checks_of("no_centre_line")[0].level == "issue"


def test_report_without_barrier_recheck(tmp_path):
    from road_furniture_designer.report import ReportData
    st, xml, auto = _project(tmp_path)
    d = ReportData(st, auto)
    assert not d.fr.checks_of("barrier_missing", "barrier_short") and not d.fr.barrier_findings
    assert any("not rechecked" in n for n in d.fr.notes)


def test_speed_zones_in_a_project(tmp_path):
    from road_furniture_designer.rfd.autoplace import AutoConfig
    from road_furniture_designer.report import ReportData
    st, xml = _fill_road(tmp_path)
    auto = AutoConfig()
    a = st.al.sta_start
    d = st.add_speed_zone(50, a + 200, a + 700, auto)
    assert d.signs
    zones = st.speed_zones()
    assert len(zones) == 1 and zones[0]["limit"] == 50
    codes = sorted(f["sign_code"] for f in st.signs.getFeatures())
    assert codes.count("P5") == 4 and codes.count("P9") == 2                      # start + middle each way, P9 out
    st.auto_propose(auto)                                                          # re-proposing keeps the zone
    assert len(st.speed_zones()) == 1
    st.add_speed_zone(80, a + 700, a + 1000, auto)                                 # adjoining: its P7 replaces P9 there
    p9 = [f for f in st.signs.getFeatures() if f["sign_code"] == "P9"]
    assert all(abs(f["station_int"] - (a + 700)) > 1 for f in p9)
    rep = ReportData(st, auto)
    lane = next(ln for ln in rep.fr.lanes if ln.name == "Speed limit zones")
    assert len(lane.items) == 2
    assert not rep.fr.checks_of("sign_unclosed") or all(c.values["what"] == "No overtaking"
                                                        for c in rep.fr.checks_of("sign_unclosed"))
    st.remove_speed_zone(st.speed_zones()[0]["id"])
    assert len(st.speed_zones()) == 1
