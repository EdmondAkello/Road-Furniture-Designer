"""Headless QGIS tests for the plugin. Run with QGIS's Python:
    QT_QPA_PLATFORM=offscreen python3 -m pytest tests_qgis
"""
import json
import math
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
sys.path.insert(0, ROOT)

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject)

if QgsApplication.instance() is None:          # one application for the whole test session
    _app = QgsApplication([], True)
    _app.initQgis()

from road_furniture_designer.store import SignStore  # noqa: E402
from examples.make_demo_road import build, to_landxml  # noqa: E402

CRS = QgsCoordinateReferenceSystem("EPSG:21037")   # Arc 1960 / UTM 37S


@pytest.fixture
def store(tmp_path):
    QgsProject.instance().clear()
    xml = tmp_path / "road.xml"
    xml.write_text(to_landxml(build()))
    st = SignStore.create(str(tmp_path / "signs.gpkg"), str(xml), "DEMO-RD", CRS, "Test")
    st.add_to_project()
    return st


def click(st, sta, off):
    x, y, _ = st.al.point_at(sta, off)
    return x, y


def test_click_derives_everything(store):
    x, y = click(store, 250.0, -3.7)               # left of the road
    fid, v = store.add_sign(x, y, "W20")
    f = store.signs.getFeature(fid)
    assert f["chainage"] == "0+250.000"
    assert f["offset_m"] == pytest.approx(3.7, abs=1e-3)
    assert f["side"] == "L" and f["facing"] == "Forward" and f["facing_auto"] == 1
    assert f["post_ref"] == "P001" and f["size"] == "750"
    assert f["description"].startswith("Sharp Bend Ahead")
    # forward-facing on a 30 deg road: face points back along 210 deg (math) = azimuth 240
    assert f["face_az"] == pytest.approx(240.0, abs=0.01)


def test_right_side_auto_backward_and_lock_offset(store):
    x, y = click(store, 300.0, 6.2)
    fid, v = store.add_sign(x, y, "W64", lock_offset=3.5)
    f = store.signs.getFeature(fid)
    assert f["side"] == "R" and f["facing"] == "Backward"
    assert f["offset_m"] == pytest.approx(3.5, abs=1e-3)       # snapped to the fixed offset
    assert f["chainage_m"] == pytest.approx(300.0, abs=1e-3)


def test_station_equation_and_post_numbering(store):
    a, _ = store.add_sign(*click(store, 100, -3), "P7")
    b, _ = store.add_sign(*click(store, 900, -3), "P5")   # internal 900 -> display 950
    fb = store.signs.getFeature(b)
    assert fb["chainage"] == "0+950.000" and fb["station_int"] == pytest.approx(900, abs=1e-3)
    assert fb["post_ref"] == "P002"


def test_attach_to_existing_post(store):
    x, y = click(store, 500, -4)
    a, va = store.add_sign(x, y, "P5")
    b, vb = store.add_sign(x + 0.4, y - 0.3, "P32", attach_tol=1.0)
    fa, fb = store.signs.getFeature(a), store.signs.getFeature(b)
    assert fb["install_uuid"] == fa["install_uuid"] and fb["post_ref"] == fa["post_ref"]
    assert fb.geometry().asPoint() == fa.geometry().asPoint()
    rows, sl = store.summary()
    assert len(sl.installations) == 1 and len(sl.faces) == 2 and sl.ok


def test_move_recomputes_and_drags_post_siblings(store):
    x, y = click(store, 500, -4)
    a, _ = store.add_sign(x, y, "P5")
    b, _ = store.add_sign(x, y, "P32", attach_tol=0.5)
    store.signs.startEditing()
    nx, ny = click(store, 560, 5.0)                    # drag across to the right side
    store.signs.changeGeometry(a, QgsGeometry.fromPointXY(QgsPointXY(nx, ny)))
    store.signs.commitChanges()
    fa, fb = store.signs.getFeature(a), store.signs.getFeature(b)
    for f in (fa, fb):
        assert f["chainage"] == "0+560.000"
        assert f["side"] == "R" and f["facing"] == "Backward"      # auto facing flipped
        assert f["offset_m"] == pytest.approx(5.0, abs=1e-3)
    assert fb.geometry().asPoint().distance(fa.geometry().asPoint()) < 1e-6


def test_manual_facing_sticks(store):
    a, _ = store.add_sign(*click(store, 400, 4), "W24-a")
    store.signs.startEditing()
    store.signs.changeAttributeValue(a, store.signs.fields().indexOf("facing"), "Forward")
    store.signs.commitChanges()
    f = store.signs.getFeature(a)
    assert f["facing"] == "Forward" and f["facing_auto"] == 0
    store.signs.startEditing()
    store.signs.changeGeometry(a, QgsGeometry.fromPointXY(QgsPointXY(*click(store, 420, 4))))
    store.signs.commitChanges()
    assert store.signs.getFeature(a)["facing"] == "Forward"


def test_feature_digitised_with_qgis_tools_gets_filled(store):
    from qgis.core import QgsFeature
    store.signs.startEditing()
    f = QgsFeature(store.signs.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*click(store, 700, -3))))
    f["sign_code"] = "W64"; f["size"] = "600"
    store.signs.addFeature(f)
    store.signs.commitChanges()
    g = [x for x in store.signs.getFeatures()][0]
    assert g["face_uuid"] and g["install_uuid"] and g["post_ref"] == "P001"
    assert g["chainage"] == "0+700.000" and g["side"] == "L" and g["facing"] == "Forward"


def test_beyond_ends_rejected(store):
    x, y, h = store.al.point_at(0.0)
    with pytest.raises(ValueError):
        store.add_sign(x - 40 * math.cos(h), y - 40 * math.sin(h), "W64")


def test_exports_and_readback(store, tmp_path):
    pytest.importorskip("openpyxl"); pytest.importorskip("ezdxf")
    ids = [store.add_sign(*click(store, s, o), c)[0]
           for s, o, c in [(250, -3.5, "W20"), (480, 4, "W24-a"), (1000, -3.5, "P5")]]
    sl = store.export_inventory(str(tmp_path / "inv.xlsx"))
    assert len(sl.faces) == 3 and (tmp_path / "inv.csv").exists()
    store.export_civil3d(str(tmp_path / "pkg.json"), str(tmp_path / "pkg.dxf"))
    pkg = json.loads((tmp_path / "pkg.json").read_text())
    assert {f["sign_code"] for f in pkg["faces"]} == {"W20", "W24-a", "P5"}
    # simulate the engineer moving the curve sign in Civil 3D and rotating the speed sign
    from road_furniture_designer.rfd.dxf_out import readback_dxf
    rb = readback_dxf(str(tmp_path / "pkg.dxf"))
    target = store.signs.getFeature(ids[0])["face_uuid"]
    for s in rb["signs"]:
        if s["face_uuid"] == target:
            s["x"], s["y"], _ = store.al.point_at(230.0, -4.0)
        if s["block_name"] == "RSD_P5":
            s["rotation_deg"] = (s["rotation_deg"] + 180) % 360
    (tmp_path / "rb.json").write_text(json.dumps(rb))
    moved, notes = store.import_readback(str(tmp_path / "rb.json"))
    assert moved == 2 and not notes
    f0, f2 = store.signs.getFeature(ids[0]), store.signs.getFeature(ids[2])
    assert f0["chainage"] == "0+230.000" and f0["offset_m"] == pytest.approx(4.0, abs=1e-3)
    assert f2["facing"] == "Backward" and f2["facing_auto"] == 0


def test_reopen_adopts_layers(store):
    store.add_sign(*click(store, 250, -3.5), "W20")
    n = len(QgsProject.instance().mapLayers())
    again = SignStore.open(store.gpkg)
    again.add_to_project()
    assert len(QgsProject.instance().mapLayers()) == n
    assert again.signs is store.signs


def test_dock_place_via_tool(store, tmp_path):
    from qgis.gui import QgsMapCanvas, QgsMessageBar
    from qgis.PyQt.QtWidgets import QMainWindow
    from road_furniture_designer.dock import RsdDock

    class Iface:
        def __init__(self):
            self.win = QMainWindow(); self.canvas = QgsMapCanvas(); self.bar = QgsMessageBar()
        def mapCanvas(self): return self.canvas
        def messageBar(self): return self.bar
        def mainWindow(self): return self.win

    iface = Iface()
    iface.canvas.setDestinationCrs(CRS)
    dock = RsdDock(iface)
    dock.set_store(store)
    # pick "Road hump ahead" in the palette
    for i in range(dock.palette.count()):
        if dock.palette.item(i).data(0x0100) == "W64":
            dock.palette.setCurrentRow(i)
    assert dock.cmb_size.currentText() == "750"
    dock.cmb_size.setCurrentText("600")
    dock.chk_lock.setChecked(True); dock.spn_offset.setValue(3.0)
    land, centre, text = dock.tool.preview(QgsPointXY(*click(store, 650, -7.0)))
    assert text.startswith("Ch 0+650.00") and "3.00 m Left" in text
    fid = dock.tool.place_at(QgsPointXY(*click(store, 650, -7.0)))
    f = store.signs.getFeature(fid)
    assert f["sign_code"] == "W64" and f["size"] == "600" and f["offset_m"] == pytest.approx(3.0, abs=1e-3)
    assert dock.lbl_totals.text().startswith("<b>1</b> sign faces")
    assert dock.tbl.rowCount() == 3          # 1 face type + 1 post type + 1 foundation type


def test_renumber_posts_by_chainage(store):
    store.add_sign(*click(store, 600, -3.5), "W64")         # P001
    store.add_sign(*click(store, 100, -3.5), "P7")     # P002
    x, y = click(store, 300, 3.5)
    store.add_sign(x, y, "P5")                          # P003
    store.add_sign(x, y, "P32", attach_tol=0.5)      # P003 (same post)
    assert store.renumber_posts() == 3
    got = sorted((f["chainage"], f["post_ref"]) for f in store.signs.getFeatures())
    assert got == [("0+100.000", "P001"), ("0+300.000", "P002"), ("0+300.000", "P002"), ("0+600.000", "P003")]



def test_auto_size_from_design_speed(store):
    store.al.speeds = [(0.0, 70.0), (600.0, 50.0)]          # as Civil 3D SpeedStation features
    a, va = store.add_sign(*click(store, 300, -3.5), "W64")   # warning, 70 km/h -> 900 (Table 4.1)
    b, vb = store.add_sign(*click(store, 800, -3.5), "W64")   # 50 km/h -> 750
    c, vc = store.add_sign(*click(store, 100, -3.5), "R1")    # stop, 70 km/h -> 750 (Table 3.1)
    d, vd = store.add_sign(*click(store, 100, 3.5), "W64", size="600")   # explicit size wins
    sz = lambda fid: store.signs.getFeature(fid)["size"]
    assert (sz(a), sz(b), sz(c), sz(d)) == ("900", "750", "750", "600")
    assert store.signs.getFeature(a)["speed_kmh"] == 70
    store.signs.startEditing()                                # drag the 900 sign into the 50 zone
    store.signs.changeGeometry(a, QgsGeometry.fromPointXY(QgsPointXY(*click(store, 900, -3.5))))
    store.signs.commitChanges()
    assert sz(a) == "750"


def test_directional_legend_face(store):
    fid, v = store.add_sign(*click(store, 700, -4.5), "I1-A",
                            legend="< Nakuru A104 18\n> Eldoret A104 140", road_class="A")
    f = store.signs.getFeature(fid)
    path = os.path.join(os.path.splitext(store.gpkg)[0] + "_faces", f["face_svg"])
    with open(path, encoding="utf-8") as fh:
        svg = fh.read()
    assert "Nakuru" in svg and "Eldoret" in svg and "#0b7a3b" in svg      # green: class A
    store.set_fields(fid, {"legend": "^ Molo 2", "road_class": "C"})
    with open(path, encoding="utf-8") as fh:
        svg = fh.read()
    assert "Molo" in svg and "Nakuru" not in svg and "#0b7a3b" not in svg
    rows, sl = store.summary()
    assert not [i for i in sl.issues if "legend" in i.message]


def test_missing_legend_flagged_and_mirror(store):
    store.add_sign(*click(store, 300, -3.5), "I7")             # town sign without a name
    store.add_sign(*click(store, 400, -3.5), "W20", mirror=True)
    rows, sl = store.summary()
    assert any("needs a legend" in i.message for i in sl.issues)
    assert [f.mirror for f in sl.faces if f.code == "W20"] == [True]


def test_exports_include_legend(store, tmp_path):
    pytest.importorskip("openpyxl"); pytest.importorskip("ezdxf")
    store.add_sign(*click(store, 700, -4.5), "I1-A", legend="< Nakuru A104 18", road_class="A")
    store.add_sign(*click(store, 400, -3.5), "W20", mirror=True)
    store.export_civil3d(str(tmp_path / "p.json"), str(tmp_path / "p.dxf"))
    pkg = json.loads((tmp_path / "p.json").read_text())
    by = {f["sign_code"]: f for f in pkg["faces"]}
    assert by["I1-A"]["legend_text"] == "< Nakuru A104 18 km" and by["W20"]["block_name"] == "RSD_W20_M"
    assert by["I1-A"]["block_name"].startswith("RSD_I1-A_")             # own block with the legend text
    import ezdxf
    doc = ezdxf.readfile(tmp_path / "p.dxf")
    from road_furniture_designer.rfd import dxfw
    from road_furniture_designer.rfd.dxf_out import sign_block_of
    blocks = dxfw.blocks_of(dxfw.read_tags(str(tmp_path / "p.dxf")))
    names = {sign_block_of(blocks, e.dxf.name)[0] for e in doc.modelspace().query("INSERT")}
    assert names == {by["I1-A"]["block_name"], "RSD_W20_M"}
    assert len(doc.blocks.get("RSD_W20_M").query("HATCH")) > 0          # real artwork, not a placeholder
    from openpyxl import load_workbook
    store.export_inventory(str(tmp_path / "inv.xlsx"))
    ws = load_workbook(tmp_path / "inv.xlsx")["Signs"]
    hdr = [c.value for c in ws[1]]
    legends = [r[hdr.index("Legend")] for r in ws.iter_rows(min_row=2, values_only=True)]
    assert "< Nakuru A104 18 km" in legends


@pytest.fixture
def corridor_store(tmp_path):
    from examples.make_demo_road import PROFILE_XML, corridor_xml
    QgsProject.instance().clear()
    els = build()
    L = sum(e.length for e in els)
    xml = tmp_path / "road_corridor.xml"
    xml.write_text(to_landxml(els, extra=PROFILE_XML + corridor_xml(L, widen_from=600.0)))
    st = SignStore.create(str(tmp_path / "c.gpkg"), str(xml), "DEMO-RD", CRS, "Corridor")
    st.add_to_project()
    return st


def test_edge_and_profile_layers(corridor_store):
    st = corridor_store
    assert st.edges_layer.isValid() and st.vcurve_layer.isValid()
    assert {f["code"] for f in st.edges_layer.getFeatures()} == {"ETW", "EPS"}
    assert st.edges_layer.featureCount() == 4                      # code x side
    kinds = sorted(f["kind"] for f in st.vcurve_layer.getFeatures())
    assert kinds == ["crest", "sag"]
    crest = [f for f in st.vcurve_layer.getFeatures() if f["kind"] == "crest"][0]
    assert crest["k_value"] == pytest.approx(20.0)


def test_offset_from_edge(corridor_store):
    st = corridor_store
    # click anywhere beside the road; fixed 1.0 m beyond EPS (EPS = 5.0 m before 600, 6.0 m after)
    a, _ = st.add_sign(*click(st, 300, -9.0), "W64", lock_offset=1.0, edge_ref="EPS")
    b, _ = st.add_sign(*click(st, 700, 2.0), "W64", lock_offset=1.0, edge_ref="EPS")
    c, _ = st.add_sign(*click(st, 400, -3.0), "W64", lock_offset=0.5, edge_ref="ETW")
    fa, fb, fc = (st.signs.getFeature(x) for x in (a, b, c))
    assert fa["offset_m"] == pytest.approx(6.0, abs=1e-3) and fa["edge_clear"] == pytest.approx(1.0, abs=1e-3)
    assert fb["offset_m"] == pytest.approx(7.0, abs=1e-3) and fb["side"] == "R"
    assert fc["offset_m"] == pytest.approx(4.0, abs=1e-3) and fc["edge_ref"] == "ETW"
    assert fa["grade_pct"] == pytest.approx(-0.5, abs=1e-6)          # PVI of the crest: mid-curve grade
    rows, sl = st.summary()
    msgs = [i.message for i in sl.issues]
    assert any("on the shoulder" in m for m in msgs)               # c: 4.0 m < EPS 5.0 m
    assert not any("travelled way" in m for m in msgs)


def test_moving_updates_clearance(corridor_store):
    st = corridor_store
    a, _ = st.add_sign(*click(st, 300, -6.0), "W64")              # default reference: EPS
    assert st.signs.getFeature(a)["edge_ref"] == "EPS"
    st.signs.startEditing()
    st.signs.changeGeometry(a, QgsGeometry.fromPointXY(QgsPointXY(*click(st, 300, -8.5))))
    st.signs.commitChanges()
    assert st.signs.getFeature(a)["edge_clear"] == pytest.approx(3.5, abs=1e-3)


def test_dock_offset_from_edge(corridor_store):
    from qgis.gui import QgsMapCanvas, QgsMessageBar
    from qgis.PyQt.QtWidgets import QMainWindow
    from road_furniture_designer.dock import RsdDock

    class Iface:
        def __init__(self):
            self.win = QMainWindow(); self.canvas = QgsMapCanvas(); self.bar = QgsMessageBar()
        def mapCanvas(self): return self.canvas
        def messageBar(self): return self.bar
        def mainWindow(self): return self.win

    i = Iface(); i.canvas.setDestinationCrs(CRS)
    dock = RsdDock(i); dock.set_store(corridor_store)
    assert dock.cmb_ref.currentData() == "EPS" and dock.spn_offset.value() == 1.0
    dock.chk_lock.setChecked(True)
    land, centre, text = dock.tool.preview(QgsPointXY(*click(corridor_store, 300, -12.0)))
    assert "6.00 m Left" in text and "+1.00 m from EPS" in text and "grade -0.5%" in text


def _sharp_road_store(tmp_path):
    """Synthetic 80 km/h road with a 100 m right-hand curve, 6 % super, corridor edges and a profile."""
    from examples.make_demo_road import corridor_xml
    QgsProject.instance().clear()
    import math as _m
    from rfd.alignment import Line, Arc
    l1 = Line((260000.0, 9950000.0), (260600.0, 9950000.0))
    arc = Arc(l1.p1, (260600.0, 9949900.0), 100.0, False, 100.0 * _m.pi / 2)
    p, h = arc.end_point, arc.end_heading
    l2 = Line(p, (p[0] + 600 * _m.cos(h), p[1] + 600 * _m.sin(h)))
    els = [l1, arc, l2]
    L = sum(e.length for e in els)
    extra = (corridor_xml(L) + '<Superelevation staStart="600" staEnd="757"><FullSuperelev>-6</FullSuperelev>'
             '</Superelevation><Feature name="SpeedStation"><Property label="station" value="0"/>'
             '<Property label="speed" value="80"/></Feature>')
    xml = tmp_path / "sharp.xml"
    xml.write_text(to_landxml(els, name="SHARP", equations=(), extra=extra))
    st = SignStore.create(str(tmp_path / "s.gpkg"), str(xml), "SHARP", CRS, "Sharp")
    st.add_to_project()
    return st


def test_auto_propose_accept_and_exports(tmp_path):
    st = _sharp_road_store(tmp_path)
    from rfd.autoplace import AutoConfig
    n, findings = st.auto_propose(AutoConfig(grades=False, no_overtaking=False))
    assert n > 0 and any(f.kind == "curve" for f in findings)
    props = st.proposals()
    assert all(f["status"] == "proposed" and f["rule"] == "curve" for f in props)
    codes = {f["sign_code"] for f in props}
    assert "W20" in codes and "W24-a" in codes
    # chevrons pair on posts and sit 1.0 m beyond EPS on the outside (left of a right-hand curve)
    chev = [f for f in props if f["sign_code"] == "W24-a"]
    assert all(f["side"] == "L" and f["edge_clear"] == pytest.approx(1.0, abs=1e-3) for f in chev)
    assert len({f["install_uuid"] for f in chev}) * 2 == len(chev)
    assert sorted({f["stack"] for f in chev}) == [0, 1]
    # proposals are not exported until accepted
    st.export_civil3d(str(tmp_path / "p0.json"))
    assert json.loads((tmp_path / "p0.json").read_text())["faces"] == []
    assert st.accept_proposals() == n
    st.export_civil3d(str(tmp_path / "p1.json"), str(tmp_path / "p1.dxf"), plan_scale=1000)
    pkg = json.loads((tmp_path / "p1.json").read_text())
    assert len(pkg["faces"]) == n
    import ezdxf
    doc = ezdxf.readfile(tmp_path / "p1.dxf")
    ins = [e for e in doc.modelspace().query("INSERT")]
    from road_furniture_designer.rfd import dxfw
    from road_furniture_designer.rfd.dxf_out import sign_block_of
    blocks = dxfw.blocks_of(dxfw.read_tags(str(tmp_path / "p1.dxf")))
    sc = [sign_block_of(blocks, e.dxf.name, e.dxf.xscale)[1] for e in ins]
    assert all(v in (pytest.approx(10.0), pytest.approx(6.0), pytest.approx(7.0)) for v in sc)   # 10 mm at 1:1000 (legends 0.6x)
    # re-running the rules does not duplicate accepted signs
    n2, _ = st.auto_propose(AutoConfig(grades=False, no_overtaking=False))
    assert {f["sign_code"] for f in st.proposals()} <= {"W24-a"}         # warnings already there


def test_remove_proposals(tmp_path):
    st = _sharp_road_store(tmp_path)
    n, _ = st.auto_propose()
    assert st.remove_proposals() == n and not st.proposals()


def test_restrict_snaps_into_corridor(corridor_store):
    st = corridor_store
    a, _ = st.add_sign(*click(st, 300, -4.0), "W64", restrict=True)     # on the shoulder -> pushed out
    b, _ = st.add_sign(*click(st, 400, -20.0), "W64", restrict=True)    # far out -> pulled to EPS + 3.0
    fa, fb = st.signs.getFeature(a), st.signs.getFeature(b)
    assert fa["edge_clear"] == pytest.approx(0.6, abs=1e-3)
    assert fb["edge_clear"] == pytest.approx(3.0, abs=1e-3)


def test_legend_block_and_old_project_migration(tmp_path, corridor_store):
    st = corridor_store
    st.add_sign(*click(st, 500, -6.5), "I1-A", legend="< Nakuru A104 18\n> Eldoret A104 140", road_class="A")
    st.export_civil3d(str(tmp_path / "l.json"), str(tmp_path / "l.dxf"))
    import ezdxf
    doc = ezdxf.readfile(tmp_path / "l.dxf")
    from road_furniture_designer.rfd import dxfw
    from road_furniture_designer.rfd.dxf_out import sign_block_of
    blocks = dxfw.blocks_of(dxfw.read_tags(str(tmp_path / "l.dxf")))
    name = [sign_block_of(blocks, e.dxf.name)[0] for e in doc.modelspace().query("INSERT")
            if sign_block_of(blocks, e.dxf.name)[0].startswith("RSD_I1-A_")][0]
    texts = [t.dxf.text for t in doc.blocks.get(name).query("TEXT")]
    assert "Nakuru" in texts and "Eldoret" in texts and "A104" in texts
    # an older project without the newer fields opens and gains them
    from qgis.core import QgsVectorLayer
    lyr = QgsVectorLayer(f"{st.gpkg}|layername=rsd_signs", "x", "ogr")
    idx = lyr.fields().indexOf("stack")
    lyr.dataProvider().deleteAttributes([idx]); lyr.updateFields()
    assert QgsVectorLayer(f"{st.gpkg}|layername=rsd_signs", "y", "ogr").fields().indexOf("stack") < 0
    QgsProject.instance().clear()
    again = SignStore.open(st.gpkg)
    assert again.signs.fields().indexOf("stack") >= 0


def test_report_outputs(tmp_path):
    st = _sharp_road_store(tmp_path)
    st.auto_propose()
    from road_furniture_designer.report import ReportData, write_pdf, write_pngs, write_xlsx
    d = ReportData(st, title="Test report")
    n = write_pdf(str(tmp_path / "r.pdf"), d, sheet_len=500)
    pngs = write_pngs(str(tmp_path / "sheets"), d, sheet_len=500)
    write_xlsx(str(tmp_path / "r.xlsx"), d)
    assert n >= 4 and len(pngs) == 4 and (tmp_path / "r.pdf").stat().st_size > 10000
    assert sum(os.path.basename(p).startswith("strip_") for p in pngs) == 1
    from openpyxl import load_workbook
    wb = load_workbook(tmp_path / "r.xlsx")
    assert wb.sheetnames == ["Signs", "Findings", "Horizontal curves", "Vertical curves", "Markings", "Barriers",
                             "Features", "Furniture quantities", "Furniture checks", "Basis"]
    hc = list(wb["Horizontal curves"].iter_rows(min_row=2, values_only=True))
    assert hc and hc[0][2] == 100.0 and hc[0][-1] == "yes"


def test_report_plan_sheets_and_title_block(tmp_path):
    st = _sharp_road_store(tmp_path)
    st.auto_propose(); st.accept_proposals()
    st.set_meta(prepared_by="EA", checked_by="XY", approved_by="")
    from road_furniture_designer.store import SignStore
    st2 = SignStore.open(st.gpkg)
    assert st2.meta["prepared_by"] == "EA" and st2.meta["checked_by"] == "XY"
    from road_furniture_designer.report import ReportData, pages, write_pngs
    d = ReportData(st2, title="Road Furniture", plan_scale=1000)
    items = pages(d, 500)
    plans = [i for i in items if i[0] == "plan"]
    assert plans and plans[0][1][1] == len(plans)
    # windows cover the alignment end to end
    assert abs(plans[0][1][2] - st2.al.sta_start) < 1e-6 and abs(plans[-1][1][3] - st2.al.sta_end) < 1e-6
    pngs = write_pngs(str(tmp_path / "s"), d, sheet_len=500)
    assert any(os.path.basename(p).startswith("plan_") for p in pngs)
    # a second alignment in the project is drawn on the plan sheets (it used to break the viewport clip)
    d.others = [st2.al]
    assert write_pngs(str(tmp_path / "s2"), d, sheet_len=500)


def test_dxf_callouts_keep_posts_georeferenced(tmp_path):
    import ezdxf
    st = _sharp_road_store(tmp_path)
    st.auto_propose(); st.accept_proposals()
    sl = st.export_civil3d(str(tmp_path / "p.json"), str(tmp_path / "p.dxf"), plan_scale=2500)
    doc = ezdxf.readfile(str(tmp_path / "p.dxf"))
    ins = [e for e in doc.modelspace().query("INSERT") if e.has_xdata("RSD")]
    assert len(ins) == len(sl.faces)
    by_uuid = {f.face_uuid: f for f in sl.faces}
    for e in ins:
        f = by_uuid[e.get_xdata("RSD")[1].value]
        assert abs(e.dxf.insert.x - f.x) < 1e-6 and abs(e.dxf.insert.y - f.y) < 1e-6
        assert e.dxf.name.startswith("RSDC_")


def test_dock_linear_tab(store):
    from qgis.gui import QgsMapCanvas, QgsMessageBar
    from qgis.PyQt.QtWidgets import QMainWindow
    from road_furniture_designer.dock import RsdDock

    class Iface:
        def __init__(self):
            self.win = QMainWindow(); self.canvas = QgsMapCanvas(); self.bar = QgsMessageBar()
        def mapCanvas(self): return self.canvas
        def messageBar(self): return self.bar
        def mainWindow(self): return self.win

    iface = Iface()
    iface.canvas.setDestinationCrs(CRS)
    dock = RsdDock(iface)
    dock.set_store(store)
    assert dock.cmb_crit.currentData() == "kenya_rdm_2025"
    dock.cmb_litem.setCurrentIndex(dock.cmb_litem.findData("LM01"))
    dock.cmb_lside.setCurrentIndex(dock.cmb_lside.findData("C"))
    dock.spn_lfrom.setValue(100); dock.spn_lto.setValue(400)
    dock.add_line_run()
    assert dock.tbl_lines.rowCount() == 1 and dock.tbl_lines.item(0, 4).text() == "300 m"
    dock._zoom_line(0, 0)
    dock.tbl_lines.selectRow(0)
    dock.delete_line_runs()
    assert dock.tbl_lines.rowCount() == 0


def test_draw_runs_and_place_features_on_map(store):
    from qgis.gui import QgsMapCanvas, QgsMessageBar
    from qgis.PyQt.QtWidgets import QMainWindow
    from road_furniture_designer.dock import RsdDock

    class Iface:
        def __init__(self):
            self.win = QMainWindow(); self.canvas = QgsMapCanvas(); self.bar = QgsMessageBar()
        def mapCanvas(self): return self.canvas
        def messageBar(self): return self.bar
        def mainWindow(self): return self.win

    iface = Iface()
    iface.canvas.setDestinationCrs(CRS)
    dock = RsdDock(iface)
    dock.set_store(store)
    # a continuous line 0.3 m left of the centreline, drawn by two clicks; offset taken from the first click
    dock.cmb_litem.setCurrentIndex(dock.cmb_litem.findData("LM24"))
    dock._run_mode = "run"
    t = dock.run_tool
    assert t.click(QgsPointXY(*click(store, 120.0, -0.3))) is None and t.start is not None
    fid = t.click(QgsPointXY(*click(store, 260.0, -0.6)))
    f = store.lines.layer.getFeature(fid)
    assert f["side"] == "L" and f["offset_m"] == pytest.approx(0.3, abs=1e-3)
    assert f["length_m"] == pytest.approx(140.0, abs=0.01)
    # fixed offset, right side: a dual carriageway's median edge line, 7.3 m right of the centreline
    dock.cmb_lside.setCurrentIndex(dock.cmb_lside.findData("R"))
    dock.chk_lfix.setChecked(True); dock.spn_loff.setValue(7.3)
    t.click(QgsPointXY(*click(store, 300.0, 2.0)))
    fid = t.click(QgsPointXY(*click(store, 500.0, 9.0)))
    f = store.lines.layer.getFeature(fid)
    assert f["side"] == "R" and f["offset_m"] == pytest.approx(7.3) and f["length_m"] == pytest.approx(200.0, abs=0.01)
    # a hump by one click, then removed with its signs and markings
    dock._run_mode = "feature"
    dock.cmb_fkind.setCurrentIndex(dock.cmb_fkind.findData("hump_circular"))
    d = t.click(QgsPointXY(*click(store, 650.0, 1.0)))
    assert d is not None and any(r.code == "HUMP-C" for r in d.runs) and len(d.signs) == 2
    assert dock.lst_features.count() == 1
    assert sum(1 for s in store.signs.getFeatures() if (s["rule"] or "").startswith("feature:")) == 2
    store.auto_propose()                                            # the sign rules keep feature signs
    assert sum(1 for s in store.signs.getFeatures() if (s["rule"] or "").startswith("feature:")) == 2
    dock.lst_features.setCurrentRow(0)
    dock.remove_feature()
    assert dock.lst_features.count() == 0
    assert not [s for s in store.signs.getFeatures() if (s["rule"] or "").startswith("feature:")]
    assert not [x for x in store.lines.layer.getFeatures() if (x["rule"] or "").startswith("feature:")]
