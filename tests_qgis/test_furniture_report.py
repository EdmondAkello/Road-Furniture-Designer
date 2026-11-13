"""Road furniture pages of the report: strip diagram, schedules and checks."""
import math
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
    assert n == 9 and finds == []                               # 7 pieces + approach arrows + splays
    n, finds = st.junctions.place(*st.al.point_at(st.al.sta_end - 300.0)[:2],
                                  *(lambda x, y, hh: (x + 30 * math.cos(hh - math.radians(70)),
                                                      y + 30 * math.sin(hh - math.radians(70))))(*st.al.point_at(st.al.sta_end - 300.0)),
                                  kit="C", guides=False)
    assert n == 6 and [l for l, _ in finds] == ["check"]        # 4 pieces + approach arrows + splays
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
    # the corner islands' bellmouths go to Civil 3D as widenings, and the Junctions sheet keeps its items
    wid = list(load_workbook(tmp_path / "j.xlsx")["Widenings"].iter_rows(min_row=2, values_only=True))
    assert "bellmouth behind a corner island" in {r[1] for r in wid}
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
    assert n == 9 and nsigns == 2                  # 6 pieces + arrows + splays + approach splay; R2 and W12
    r2 = [f for f in st.signs.getFeatures() if f["rule"] == f"junction:{pl.junction_id}" and f["sign_code"] == "R2"]
    assert len(r2) == 1 and r2[0]["facing"] == "Forward" and r2[0]["status"] == "proposed"
    w12 = [f for f in st.signs.getFeatures() if f["sign_code"] == "W12"]
    assert len(w12) == 1 and w12[0]["facing"] == "Forward" and w12[0]["station_int"] < r2[0]["station_int"]
    j = st.junctions.junctions()[0]
    assert j["role"] == "minor" and abs(j["sta"] - s_end) < 0.5
    assert j["minor_splay"]["ssd"] > 0 and "SPLAY-M" in {f["code"] for f in st.junctions.layer.getFeatures()}
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


def test_crossroads_with_another_alignment_follows_the_mouse(tmp_path):
    """Trial fix: where our road crosses another alignment, the leg follows the mouse, and both legs can go in."""
    import math
    from road_furniture_designer.maptool import PlaceJunctionTool
    from road_furniture_designer.rfd.alignment import Alignment
    from qgis.core import QgsPointXY
    from qgis.gui import QgsMapCanvas
    st, xml = _fill_road(tmp_path)
    x0, y0, h = st.al.point_at(600.0)
    n = (math.cos(h + math.pi / 2), math.sin(h + math.pi / 2))
    t = (math.cos(h), math.sin(h))
    st.junctions._others = [Alignment.from_polyline("MAJOR", [(x0 - 300 * n[0], y0 - 300 * n[1]),
                                                              (x0 + 300 * n[0], y0 + 300 * n[1])])]
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(CRS)
    cfg = {"kit": "B", "piece": "", "scale": 1.0, "guides": False, "role": "minor", "major": "MAJOR",
           "splays": False, "both": False}
    tool = PlaceJunctionTool(canvas, lambda: st, lambda: cfg)
    for sgn in (1, -1):                                   # mouse ahead of / behind the junction on our road
        tool.click(QgsPointXY(x0, y0))
        jid = tool.click(QgsPointXY(x0 + sgn * 40 * t[0] + 5 * n[0], y0 + sgn * 40 * t[1] + 5 * n[1]))
        f = next(f for f in st.junctions.layer.getFeatures() if f["junction_id"] == jid)
        b = math.radians(f["bearing_deg"])
        assert math.cos(b - h) * sgn > 0.99               # the kit faces the leg the mouse is on
    st.remove_junction(jid)
    cfg["both"] = True
    tool.click(QgsPointXY(x0, y0))
    jid = tool.click(QgsPointXY(x0 + 40 * t[0], y0 + 40 * t[1]))
    js = [j for j in st.junctions.junctions() if j["id"].startswith(jid)]
    assert len(js) == 2
    r2 = [f for f in st.signs.getFeatures() if f["sign_code"] == "R2" and (f["rule"] or "").startswith("junction:")]
    assert len(r2) >= 2 and len({round(f["chainage_m"]) for f in r2}) >= 2


def test_hump_bar_sets_keep_off_junctions(tmp_path):
    """Trial fix: a hump's approach bar sets are left out where they would fall on a junction kit."""
    import math
    from road_furniture_designer.rfd.features import FeatureConfig, design_feature
    st, xml = _fill_road(tmp_path)
    plan = design_feature(st.al, "hump_circular", 900.0, FeatureConfig())
    bars = sorted((r.sta_start, r.sta_end) for r in plan.runs if r.code == "BAR-SET")
    a, b = bars[0]                                          # the set furthest back, before the hump
    x0, y0, h = st.al.point_at((a + b) / 2)
    st.junctions.place(x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2), kit="C")
    d = st.add_feature("hump_circular", 900.0, FeatureConfig())
    kept = sorted((r.sta_start, r.sta_end) for r in d.runs if r.code == "BAR-SET")
    assert len(kept) < len(bars) and (a, b) not in kept
    assert any("omitted" in f.text and "junction" in f.text for f in d.findings)
    # placed the other way round: the junction removes the hump's bar sets under it
    st.remove_junction(st.junctions.junctions()[0]["id"])
    st.add_feature("hump_circular", 900.0, FeatureConfig(bar_markings=True))
    before = sum(1 for f in st.lines.layer.getFeatures() if f["item_code"] == "BAR-SET")
    from road_furniture_designer.rfd import junctions as J
    pj = J.place(st.al, x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2))
    n, finds, _ = st.add_junction(pj, "C")
    after = sum(1 for f in st.lines.layer.getFeatures() if f["item_code"] == "BAR-SET")
    assert after < before and any("bar set" in t for _lvl, t in finds)


def test_junction_ahead_warnings_on_our_road(tmp_path):
    """RDM 6.2 4.2.1: W2 for a side road, W1 once a second side road leaves opposite it; a W2 the designer
    accepted is kept; removing a junction re-proposes the rest."""
    import math
    st, xml = _fill_road(tmp_path)
    x0, y0, h = st.al.point_at(600.0)
    nrm = lambda sg: (x0 + sg * 40 * math.cos(h + math.pi / 2), y0 + sg * 40 * math.sin(h + math.pi / 2))
    warn = lambda: sorted((f["sign_code"], f["facing"], bool(f["mirror"])) for f in st.signs.getFeatures()
                          if f["sign_code"] in ("W1", "W2", "W5"))
    st.junctions.place(x0, y0, *nrm(1), kit="C")
    st.refresh_junction_warnings()
    assert warn() == [("W2", "Backward", False), ("W2", "Forward", True)]     # side road on the left of chainage
    from road_furniture_designer.rfd import junctions as J
    pl = J.place(st.al, x0, y0, *nrm(-1))
    st.add_junction(pl, "C")
    assert warn() == [("W1", "Backward", False), ("W1", "Forward", False)]
    st.remove_junction(pl.junction_id)
    assert [c for c, _f, _m in warn()] == ["W2", "W2"]


def test_move_a_junction_piece(tmp_path):
    """C7: a placed piece moves along the road and is rebuilt there; Shift moves the whole junction."""
    import math
    from road_furniture_designer.maptool import MovePieceTool
    from qgis.core import QgsPointXY
    from qgis.gui import QgsMapCanvas
    st, xml = _fill_road(tmp_path)
    x0, y0, h = st.al.point_at(600.0)
    st.junctions.place(x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2), kit="C")
    split = next(f for f in st.junctions.layer.getFeatures() if f["piece"] == "splitter_teardrop" and f["code"] == "KERB")
    c = split.geometry().centroid().asPoint()
    canvas = QgsMapCanvas(); canvas.setDestinationCrs(CRS)
    tool = MovePieceTool(canvas, lambda: st)
    tool.click(QgsPointXY(c.x(), c.y()))
    x1, y1, _ = st.al.point_at(st.al.station_offset(c.x(), c.y()).station + 12.0)
    assert tool.click(QgsPointXY(x1, y1)) == 1
    stas = {f["piece"]: f["sta"] for f in st.junctions.layer.getFeatures()}
    assert abs(stas["splitter_teardrop"] - 612.0) < 0.5 and abs(stas["give_way_line"] - 600.0) < 1e-6
    pu = next(f["piece_uuid"] for f in st.junctions.layer.getFeatures() if f["piece"] == "give_way_line")
    assert st.junctions.move(pu, -5.0, whole=True) >= 5
    assert all(abs(f["sta"] - (607.0 if f["piece"] == "splitter_teardrop" else 595.0)) < 0.5
               for f in st.junctions.layer.getFeatures())


def test_signalised_crossroads_in_a_project(tmp_path):
    import math
    from road_furniture_designer.rfd import junctions as J
    st, xml = _fill_road(tmp_path)
    x0, y0, h = st.al.point_at(600.0)
    pl = J.place(st.al, x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2))
    n, finds, nsigns = st.add_junction(pl, "SIG")
    assert n == 1 and nsigns == 2
    assert sorted(f["facing"] for f in st.signs.getFeatures() if f["sign_code"] == "W46") == ["Backward", "Forward"]
    codes = {f["code"] for f in st.junctions.layer.getFeatures()}
    assert {"BM02", "TM01", "LM24", "AM07", "GUIDE"} <= codes


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


def test_bus_bay_in_a_project(tmp_path):
    from road_furniture_designer.rfd import junctions as J
    from road_furniture_designer.report import ReportData, write_xlsx
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    pl, B = J.place_bay(st.al, *st.al.point_at(400.0, -6.0)[:2], *st.al.point_at(425.0, -6.0)[:2])
    n, finds, nsigns = st.add_junction(pl, "BUS", params={"bay": B})
    assert n == 1 and nsigns == 1
    j = st.junctions.junctions()[0]
    assert j["bay"]["side"] == "L" and j["widen_m2"] > 150 and j["kerb_m"] > 60
    assert [f["sign_code"] for f in st.signs.getFeatures() if f["rule"] == f"junction:{pl.junction_id}"] == ["WSCM-I3"]
    assert j["kerb_raised_m"] == 25.0 + 2 * 2.0 and abs(j["kerb_raised_m"] + j["kerb_flush_m"] - j["kerb_m"]) < 1e-6
    st.junctions.recompute_all()                                   # rebuilt from its stored parameters
    assert abs(st.junctions.junctions()[0]["widen_m2"] - j["widen_m2"]) < 1e-6
    d = ReportData(st, AutoConfig())
    write_xlsx(str(tmp_path / "b.xlsx"), d)
    from openpyxl import load_workbook
    rows = list(load_workbook(tmp_path / "b.xlsx")["Widenings"].iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1 and rows[0][1] == "bus bay" and rows[0][2] == "L" and rows[0][9] == 4.0
    assert st.remove_junction(pl.junction_id) >= 2


def test_truck_parking_bay_in_a_project(tmp_path):
    from road_furniture_designer.rfd import junctions as J
    from road_furniture_designer.report import ReportData, write_xlsx
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    pl, B = J.place_bay(st.al, *st.al.point_at(500.0, -6.0)[:2], *st.al.point_at(570.0, -6.0)[:2])
    n, finds, nsigns = st.add_junction(pl, "TRUCK", params={"bay": B})
    assert n == 1 and nsigns == 2                                   # I15 at the entry taper, I14 300 m ahead
    j = st.junctions.junctions()[0]
    assert j["bay"]["kind"] == "truck parking bay" and j["bay"]["stations"][:2] == [485, 500] and j["kerb_m"] == 0
    signs = {f["sign_code"]: f["chainage_m"] for f in st.signs.getFeatures() if f["rule"] == f"junction:{pl.junction_id}"}
    assert set(signs) == {"I15", "I14"}
    assert abs((signs["I15"] - signs["I14"]) - 300) < 1
    assert abs(j["paint"]["LM05"][1] - j["paint"]["LM05"][0] * 0.2) < 1e-3
    d = ReportData(st, AutoConfig())
    write_xlsx(str(tmp_path / "t.xlsx"), d)
    from openpyxl import load_workbook
    rows = list(load_workbook(tmp_path / "t.xlsx")["Widenings"].iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1 and rows[0][1] == "truck parking bay" and rows[0][7] == 15 and rows[0][8] == 10
    assert st.remove_junction(pl.junction_id) >= 2


def test_visibility_splays_against_obstruction_layers(tmp_path):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
    from road_furniture_designer.rfd import junctions as J
    from road_furniture_designer.report import ReportData
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    x, y, h = st.al.point_at(600.0)
    nx, ny = -math.sin(h), math.cos(h)                              # left of the chainage
    pl = J.place(st.al, x, y, x + 30 * nx, y + 30 * ny)
    n, finds, nsigns = st.add_junction(pl, "C", splay={"speed": 80})
    j = next(j for j in st.junctions.junctions() if j["id"] == pl.junction_id)
    assert j["sight"]["speed_used"] == 80 and {r["kind"] for r in j["sight"]["splays"]} == {"approach", "stop"}
    codes = {f["code"] for f in st.junctions.layer.getFeatures() if f["junction_id"] == pl.junction_id}
    assert {"SPLAY-A", "SPLAY-S"} <= codes
    # a building 40 m up the chainage, 2 m back from the edge: in both splays on that side; one far away: in none
    lyr = QgsVectorLayer(f"Polygon?crs={st.signs.crs().authid()}", "Buildings", "memory")
    feats = []
    for along, off in ((40.0, 6.0), (40.0, 60.0)):
        bx, by, _ = st.al.point_at(600.0 + along, -off)
        f = QgsFeature(); f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(bx + dx, by + dy) for dx, dy in
                                                                 ((-2, -2), (2, -2), (2, 2), (-2, 2), (-2, -2))]]))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(lyr)
    nj, total = st.check_sight([lyr.id()])
    assert nj == 1 and total == 2                                   # approach and stop splays, up the chainage
    obs = st.junctions.junctions()[0]["sight"]["obstructions"]
    assert {(o["kind"], o["dir"]) for o in obs} == {("approach", "up"), ("stop", "up")}
    d = ReportData(st, AutoConfig())                                # the report re-runs the check
    sight = [c for c in d.fr.checks if c.kind == "junction_sight"]
    assert any(c.level == "issue" and "Buildings feature" in c.text for c in sight)
    st.remove_junction(pl.junction_id)


def test_private_access_in_a_project(tmp_path):
    from road_furniture_designer.rfd import junctions as J
    from road_furniture_designer.report import ReportData, write_xlsx
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    x, y, h = st.al.point_at(700.0)
    pl = J.place(st.al, x, y, x - 30 * math.sin(h), y + 30 * math.cos(h))     # left of the chainage
    n, finds, nsigns = st.add_junction(pl, "ACCESS", params={"width": 3.0, "radius": 6.0, "length": 10.0,
                                                             "road_class": "B"}, splay={"speed": 80})
    assert n == 2 and nsigns == 0
    j = st.junctions.junctions()[0]
    assert j["kit"] == "ACCESS" and j["access"]["quantities"]["pipe_no"] == 1
    assert {r["kind"] for r in j["sight"]["splays"]} == {"stop"}
    codes = {f["code"] for f in st.junctions.layer.getFeatures()}
    assert {"ACCESS", "ACCESS-P", "PIPE", "SPLAY-S"} <= codes and "SPLAY-A" not in codes
    # the returns start on the shoulder edge of the corridor when it has one, else the ETW
    edge = next(f for f in st.junctions.layer.getFeatures() if f["code"] == "ACCESS").geometry().asMultiPolyline()[0][0]
    off = abs(st.al.station_offset(edge.x(), edge.y()).offset)
    assert off >= 3.5 - 1e-6
    d = ReportData(st, AutoConfig())
    assert any(c.kind == "access" and "class B" in c.text for c in d.fr.checks)
    write_xlsx(str(tmp_path / "a.xlsx"), d)
    from openpyxl import load_workbook
    rows = list(load_workbook(tmp_path / "a.xlsx")["Junctions"].iter_rows(min_row=2, values_only=True))
    assert {r[6] for r in rows} >= {"ACCESS", "PIPE"}
    assert st.remove_junction(pl.junction_id) >= 4


def test_widening_round_trip_in_a_project(tmp_path):
    from road_furniture_designer.rfd import junctions as J
    from road_furniture_designer.rfd.corridor import Edges
    from road_furniture_designer.report import ReportData
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    pl, B = J.place_bay(st.al, *st.al.point_at(500.0, -6.0)[:2], *st.al.point_at(570.0, -6.0)[:2])
    st.add_junction(pl, "TRUCK", params={"bay": B})
    widen0 = st.junctions.junctions()[0]["widen_m2"]
    checks = lambda: [c for c in ReportData(st, AutoConfig()).fr.checks if c.kind == "widening"]
    assert "not in the corridor yet" in checks()[0].text
    # Civil 3D widens the corridor as placed; the LandXML comes back and the overlays rebuild
    bay = st.junctions.junctions()[0]["bay"]
    s0, s1, s2, s3 = bay["stations"]
    w = lambda s: J.widen_at(s - s0, bay["entry"], s2 - s1, bay["exit"], bay["depth"], True)
    data = {k: [(s, o + (w(s) if k == ("ETW", "L") else 0.0)) for s, o in v] for k, v in st.al.edges.data.items()}
    st.al.edges = Edges(data)
    st.junctions.recompute_all()
    j = st.junctions.junctions()[0]
    assert abs(j["widen_m2"] - widen0) < 1.0                         # not widened twice
    (c,) = checks()
    assert c.level == "info" and "matches the corridor" in c.text


def test_roundabout_in_a_project(tmp_path):
    from road_furniture_designer.rfd import junctions as J
    from road_furniture_designer.report import ReportData, write_xlsx
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, xml = _fill_road(tmp_path)
    from road_furniture_designer.rfd.markings import MarkingConfig
    st.lines.auto_propose_markings(MarkingConfig())
    before = len(st.lines.runs())
    x, y, h = st.al.point_at(800.0)
    pl = J.place_roundabout(st.al, x, y)
    side = math.degrees(h) + 90.0                                         # a third arm, square on the left
    n, finds, nsigns = st.add_junction(pl, "RBT", "", False, {"island": 12.0, "arms": [
        {"bearing_deg": side, "src": "click", "half": 3.5}]}, False, None)
    j = st.junctions.junctions()[0]
    assert j["kit"] == "RBT" and j["rbt"]["n_arms"] == 3
    # our road's markings stop short of the roundabout and carry on beyond it
    cat = st.lines.cat
    long_runs = [r for r in st.lines.runs() if not cat[r.code].transverse and cat[r.code].category in ("Marking", "Road stud")]
    assert long_runs and not [r for r in long_runs if r.sta_start < 790.0 < r.sta_end or r.sta_start < 810.0 < r.sta_end]
    assert any(r.sta_end <= 770.0 for r in long_runs) and any(r.sta_start >= 830.0 for r in long_runs)
    assert len(st.lines.runs()) >= before - 2 and j["kerb_m"] > 100 and j["island_m2"] > 100
    signs = [f for f in st.signs.getFeatures() if f["rule"] == f"junction:{pl.junction_id}"]
    codes = sorted(f["sign_code"] for f in signs)
    assert codes.count("R2") == 3 and codes.count("M5") == 3 and codes.count("W24-b") == 3 and codes.count("W17") == 2
    # the chevron facing the clicked arm points along it, out of the roundabout
    chev = [f for f in signs if f["sign_code"] == "W24-b"]
    azs = sorted(round(f["face_az"]) % 360 for f in chev)
    want = round((90.0 - side) % 360)
    assert any(abs(math.remainder(a - want, 360)) < 2 for a in azs)
    d = ReportData(st, AutoConfig())
    assert any(c.kind == "roundabout" for c in d.fr.checks)
    write_xlsx(str(tmp_path / "r.xlsx"), d)
    from openpyxl import load_workbook
    rows = list(load_workbook(tmp_path / "r.xlsx")["Junctions"].iter_rows(min_row=2, values_only=True))
    assert {"KERB", "TM07", "TM04", "BM07"} <= {r[6] for r in rows}
    st.junctions.recompute_all()                                          # rebuilt from its stored parameters
    assert st.junctions.junctions()[0]["rbt"]["n_arms"] == 3
    assert st.remove_junction(pl.junction_id) >= 11
    # the same from the map tool: centre, one arm by a click, then place (right-click / Enter)
    from qgis.core import QgsPointXY
    from qgis.gui import QgsMapCanvas
    from road_furniture_designer.maptool import PlaceJunctionTool
    tool = PlaceJunctionTool(QgsMapCanvas(), lambda: st, lambda: {"kit": "RBT", "rbt": {"island": 10.0}})
    assert tool.click(QgsPointXY(x + 1.0, y + 1.0)) is None and tool.p0 is not None   # centre, snapped
    ax, ay = x + 40 * math.cos(math.radians(side)), y + 40 * math.sin(math.radians(side))
    assert tool.click(QgsPointXY(ax, ay)) is None and len(tool._rb_arms) == 1
    jid = tool.place_roundabout()
    jj = next(j for j in st.junctions.junctions() if j["id"] == jid)
    assert jj["rbt"]["n_arms"] == 3 and tool.p0 is None


def test_climbing_lane_proposed_in_a_project(tmp_path):
    from road_furniture_designer.rfd.profile import VerticalProfile
    st, xml = _fill_road(tmp_path)
    L = st.al.sta_end
    st.al.profile = VerticalProfile("P", [(0, 100, 0), (100, 100, 60), (L - 100, 100 + 0.07 * (L - 200), 60), (L, 100 + 0.07 * (L - 200), 0)])
    from road_furniture_designer.rfd.markings import MarkingConfig
    st.lines.auto_propose_markings(MarkingConfig(road_class="B"))
    edges = lambda side: [(f["sta_from"], f["sta_to"]) for f in st.lines.layer.getFeatures()
                          if f["item_code"] in ("LM26", "LM27") and f["side"] == side]
    assert edges("L") and edges("R")
    n, notes = st.propose_climbing_lanes(aadt=7000)
    assert n == 1 and "required" in notes[0]
    j = st.junctions.junctions()[0]
    assert j["bay"]["kind"] == "climbing lane" and j["bay"]["side"] == "L" and j["widen_m2"] > 1000
    codes = sorted(f["sign_code"] for f in st.signs.getFeatures() if f["rule"] == f"junction:{j['id']}")
    assert codes == ["WSCM-I1", "WSCM-I2"]
    # our road's edge line on the lane's side stops at the tapers; the other side is untouched
    s0, s3 = sorted((j["bay"]["stations"][0], j["bay"]["stations"][3]))
    s3 = min(s3, st.al.sta_end)
    assert all(b <= s0 + 1e-6 or a >= s3 - 1e-6 for a, b in edges("L"))
    covered = sum(max(0.0, min(b, s3) - max(a, s0)) for a, b in edges("R"))
    assert covered > 0.95 * (s3 - s0)
    # trial fix: the lane draws its widened edge and lines, and every code has a symbol on the map
    drawn = {f["code"] for f in st.junctions.layer.getFeatures() if f["junction_id"] == j["id"]}
    assert drawn == {"BAYEDGE", "LM26", "LM03"}
    styled = {c.value() for c in st.junctions.layer.renderer().categories()}
    assert set(st.junctions.templates["codes"]) <= styled
    # a layer saved by 0.8.0 without the LM26 / LM03 symbols gets them back when the project is reopened
    r = st.junctions.layer.renderer()
    for code in ("LM26", "LM03"):
        r.deleteCategory(r.categoryIndexForValue(code))
    assert st.junctions.ensure_style() == 2
    assert {"LM26", "LM03"} <= {c.value() for c in st.junctions.layer.renderer().categories()}
