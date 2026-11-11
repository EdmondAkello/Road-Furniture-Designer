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


def test_junction_templates_in_a_project(tmp_path):
    import math
    from road_furniture_designer.report import ReportData, pages, write_pdf, write_xlsx
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    assert st.junctions.layer.isValid()
    x0, y0, h = st.al.point_at(600.0)
    up = lambda ang, side=1: (x0 + 30 * math.cos(h + side * math.radians(ang)),
                              y0 + 30 * math.sin(h + side * math.radians(ang)))
    n, finds = st.junctions.place(x0, y0, *up(90), kit="A-2")
    assert n == 7 and finds == []
    n, finds = st.junctions.place(*st.al.point_at(st.al.sta_end - 300.0)[:2],
                                  *(lambda x, y, hh: (x + 30 * math.cos(hh - math.radians(70)),
                                                      y + 30 * math.sin(hh - math.radians(70))))(*st.al.point_at(st.al.sta_end - 300.0)),
                                  kit="C", guides=False)
    assert n == 4 and [l for l, _ in finds] == ["check"]
    js = st.junctions.junctions()
    assert [j["kit"] for j in js] == ["A-2", "C"]
    a2 = js[0]
    assert a2["side"] == "L" and a2["kerb_m"] > 60 and a2["island_m2"] > 80 and "TM07" in a2["paint"]
    assert "guides" not in js[1]["pieces"] and "guides" in a2["pieces"]
    # every feature carries the junction rule; a piece's features share its uuid
    feats = list(st.junctions.layer.getFeatures())
    assert all(f["rule"] == f"junction:{f['junction_id']}" for f in feats)
    # rescaling rebuilds from the template; editing a trigger field rebuilds the piece
    st.junctions.set_scale(a2["id"], 1.2)
    a2b = st.junctions.junctions()[0]
    assert a2b["island_m2"] == __import__("pytest").approx(a2["island_m2"] * 1.44, rel=0.02)
    f = next(f for f in st.junctions.layer.getFeatures() if f["piece"] == "splitter_a2" and f["code"] == "KERB")
    st.junctions.layer.startEditing()
    st.junctions.layer.changeAttributeValue(f.id(), st.junctions.layer.fields().indexOf("sta"), 650.0)
    st.junctions.layer.commitChanges()
    moved = [g for g in st.junctions.layer.getFeatures() if g["piece"] == "splitter_a2"]
    assert moved and all(abs(g["sta"] - 650.0) < 1e-6 for g in moved)
    # report: schedule table, skew check, plan sheet, workbook, DXF
    d = ReportData(st, AutoConfig(), title="Road Furniture")
    tables = [p[0] for k, p in pages(d, 500) if k == "ftable"]
    assert "junctions" in tables
    assert [c.level for c in d.fr.checks_of("junction_skew")] == ["check"]
    write_pdf(str(tmp_path / "j.pdf"), d, sheet_len=500)
    write_xlsx(str(tmp_path / "j.xlsx"), d)
    from openpyxl import load_workbook
    rows = list(load_workbook(tmp_path / "j.xlsx")["Junctions"].iter_rows(min_row=2, values_only=True))
    assert {r[6] for r in rows} >= {"KERB", "TM07", "BM07", "LM24", "HM07"}
    from road_furniture_designer.rfd.dxf_out import write_junctions
    import ezdxf
    doc = ezdxf.new()
    write_junctions(doc, doc.modelspace(), st.junctions.parts())
    assert {"RSD-JN-KERB", "RSD-JN-GUIDE", "RSD-JN-TM07"} <= {l.dxf.name for l in doc.layers}
    # removing a junction removes all its pieces
    assert st.junctions.remove(js[1]["id"]) > 0
    assert [j["kit"] for j in st.junctions.junctions()] == ["A-2"]


def test_our_road_joins_a_main_road_and_one_click_crossing(tmp_path):
    import math
    from road_furniture_designer.maptool import PlaceRunTool
    from qgis.core import QgsPointXY
    from qgis.gui import QgsMapCanvas
    st, xml = _fill_road(tmp_path)
    # our road ends on a main road we only know by a clicked direction
    s_end = st.al.sta_end
    x0, y0, h = st.al.point_at(s_end)
    pl = st.junctions.placement_minor(x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2))
    n, finds, nsigns = st.add_junction(pl, "B")
    assert n == 6 and nsigns == 1
    r2 = [f for f in st.signs.getFeatures() if f["rule"] == f"junction:{pl.junction_id}"]
    assert [f["sign_code"] for f in r2] == ["R2"] and r2[0]["facing"] == "Forward" and r2[0]["status"] == "proposed"
    j = st.junctions.junctions()[0]
    assert j["role"] == "minor" and abs(j["sta"] - s_end) < 0.5
    # re-running auto-placement keeps the junction's sign
    st.auto_propose()
    assert [f for f in st.signs.getFeatures() if f["rule"] == f"junction:{pl.junction_id}"]
    # editing the scale rebuilds against the same main road
    st.junctions.set_scale(pl.junction_id, 1.1)
    assert st.junctions.junctions()[0]["role"] == "minor"
    assert st.remove_junction(pl.junction_id) > 1
    assert not st.junctions.junctions() and not [f for f in st.signs.getFeatures() if (f["rule"] or "").startswith("junction:")]
    # a zebra from the Linear tab: one click, centred, across the carriageway
    tool = PlaceRunTool(QgsMapCanvas(), lambda: st, lambda: {"mode": "run", "code": "BM02", "side": None})
    x, y, _ = st.al.point_at(500.0)
    fid = tool.click(QgsPointXY(x, y))
    f = st.lines.layer.getFeature(fid)
    assert f["item_code"] == "BM02" and abs(f["sta_to"] - f["sta_from"] - 3.0) < 1e-6
    assert f.geometry().constGet().numGeometries() >= 6          # the bars, not one outline


def test_crossing_kerb_to_kerb_with_refuge(tmp_path):
    from road_furniture_designer.maptool import PlaceRunTool
    from road_furniture_designer.rfd.autoplace import AutoConfig
    from road_furniture_designer.rfd.features import FeatureConfig
    from qgis.core import QgsPointXY
    from qgis.gui import QgsMapCanvas
    st, xml = _fill_road(tmp_path)
    cfg = FeatureConfig(refuge=2.0)
    tool = PlaceRunTool(QgsMapCanvas(), lambda: st, lambda: {"mode": "feature", "kind": "crossing", "span": True,
                                                             "feature_cfg": cfg, "auto_cfg": AutoConfig()})
    assert tool.click(QgsPointXY(*st.al.point_at(600.0, -9.0)[:2])) is None          # first kerb
    d = tool.click(QgsPointXY(*st.al.point_at(601.0, 9.0)[:2]))                       # the other kerb
    codes = sorted(r.code for r in d.runs if r.code in ("BM02", "REFUGE"))
    assert codes == ["BM02", "BM02", "REFUGE"]
    feats = [f for f in st.lines.layer.getFeatures() if f["item_code"] in ("BM02", "REFUGE")]
    assert len(feats) == 3 and all(not f.geometry().isEmpty() for f in feats)
    assert {s.code for s in d.signs} == {"W55"}
