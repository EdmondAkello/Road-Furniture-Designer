"""Headless QGIS tests for the linear furniture layer (rsd_lines)."""
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
sys.path.insert(0, ROOT)

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsVectorLayer  # noqa: E402

if QgsApplication.instance() is None:          # one application for the whole test session
    _app = QgsApplication([], True)
    _app.initQgis()

from road_furniture_designer.store import SignStore  # noqa: E402
from road_furniture_designer.rfd.linear import Run  # noqa: E402
from examples.make_demo_road import build, to_landxml  # noqa: E402

CRS = QgsCoordinateReferenceSystem("EPSG:21037")


@pytest.fixture
def store(tmp_path):
    QgsProject.instance().clear()
    xml = tmp_path / "road.xml"
    xml.write_text(to_landxml(build()))
    st = SignStore.create(str(tmp_path / "signs.gpkg"), str(xml), "DEMO-RD", CRS, "Test")
    st.add_to_project()
    return st


def test_lines_layer_created_and_in_project(store):
    lyr = store.lines.layer
    assert lyr.isValid() and lyr.name() == "RFD linear furniture"
    assert QgsProject.instance().mapLayer(lyr.id()) is not None
    assert lyr.fields().indexOf("item_code") >= 0


def test_add_run_derives_geometry_and_quantity(store):
    ref = store.default_edge_ref()
    side_off = dict(side="L", offset=0.0, edge_ref=ref) if ref else dict(side="L", offset=3.5)
    fid = store.lines.add_run(Run("LM26", 100, 400, **side_off))
    f = store.lines.layer.getFeature(fid)
    assert f["ch_from"] == "0+100" and f["ch_to"] == "0+400"
    assert f["length_m"] == pytest.approx(300) and f["unit"] == "m"
    assert f["description"].startswith("Continuous edge line")
    assert not f.geometry().isEmpty() and f.geometry().length() == pytest.approx(300, rel=0.05)
    sfid = store.lines.add_run(Run("RRS-C", 0, 120))
    assert store.lines.layer.getFeature(sfid)["quantity"] == 11
    rows = {(r[1], r[4]): r[5] for r in store.lines.summary()}
    assert rows[("LM26", "m")] == pytest.approx(300) and rows[("RRS-C", "No.")] == 11


def test_edit_attribute_recomputes(store):
    fid = store.lines.add_run(Run("LM01", 100, 200))
    lyr = store.lines.layer
    lyr.startEditing()
    lyr.changeAttributeValue(fid, lyr.fields().indexOf("sta_to"), 350.0)
    f = lyr.getFeature(fid)
    assert f["length_m"] == pytest.approx(250) and f["ch_to"] == "0+350"
    assert f.geometry().length() == pytest.approx(250, rel=0.05)
    lyr.commitChanges()


def test_proposals_and_exports(store, tmp_path):
    store.lines.add_run(Run("GR-W", 50, 150, side="R", offset=4.0, status="proposed", rule="barrier"))
    store.lines.add_run(Run("LM01", 0, 500))
    assert len(store.lines.proposals()) == 1
    xp = str(tmp_path / "inv.xlsx")
    store.export_inventory(xp)
    from openpyxl import load_workbook
    wb = load_workbook(xp)
    assert wb["Linear"].max_row == 2            # proposals are not in the inventory
    assert store.lines.accept_proposals() == 1
    store.export_inventory(xp)
    assert load_workbook(xp)["Linear"].max_row == 3
    assert store.lines.remove_proposals() == 0
    rows, _ = store.summary()
    assert any(r[1] == "GR-TERM" and r[4] == "2 No." for r in rows)


def test_old_project_gets_lines_layer(store):
    gpkg = store.gpkg
    QgsProject.instance().clear()
    from osgeo import ogr
    ds = ogr.Open(gpkg, 1)
    ds.DeleteLayer("rsd_lines")
    ds = None
    assert not QgsVectorLayer(f"{gpkg}|layername=rsd_lines", "x", "ogr").isValid()
    st = SignStore.open(gpkg)
    st.add_to_project()
    assert st.lines.layer.isValid()
    assert QgsProject.instance().mapLayer(st.lines.layer.id()) is not None


def test_propose_markings_roundtrip(tmp_path):
    from examples.make_demo_road import PROFILE_XML, corridor_xml
    from road_furniture_designer.rfd.markings import MarkingConfig
    QgsProject.instance().clear()
    els = build()
    xml = tmp_path / "road.xml"
    xml.write_text(to_landxml(els, extra=PROFILE_XML + corridor_xml(sum(e.length for e in els))))
    store = SignStore.create(str(tmp_path / "signs.gpkg"), str(xml), "DEMO-RD", CRS, "Test")
    store.add_to_project()
    store.lines.add_run(Run("GR-W", 50, 150, side="R", offset=4.0, status="proposed", rule="barrier"))
    n, findings, skipped = store.lines.auto_propose_markings(MarkingConfig(road_class="B"))
    assert n >= 3 and not skipped
    codes = {f["item_code"] for f in store.lines.layer.getFeatures()}
    assert {"LM02", "LM27", "GR-W"} <= codes
    n2, _, _ = store.lines.auto_propose_markings(MarkingConfig(road_class="B"))       # replaces, not duplicates
    assert n2 == n and store.lines.layer.featureCount() == n + 1
    assert all(not f.geometry().isEmpty() for f in store.lines.layer.getFeatures())
    store.lines.accept_proposals()
    dxf = str(tmp_path / "o.dxf")
    store.export_civil3d(str(tmp_path / "o.json"), dxf)
    import ezdxf
    msp = ezdxf.readfile(dxf).modelspace()
    assert len(msp.query('LWPOLYLINE[layer=="RSD-MARK-LM27"]')) >= 2
