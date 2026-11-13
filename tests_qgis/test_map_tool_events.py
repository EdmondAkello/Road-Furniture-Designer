"""The map tools driven by real Qt mouse and key events (not their click() helpers), so the button, key and
modifier enums are exercised on Qt5 (QGIS 3.44) and Qt6 (QGIS 4)."""
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from qgis.core import QgsApplication, QgsPointXY, QgsRectangle  # noqa: E402

if QgsApplication.instance() is None:
    _app = QgsApplication([], True)
    _app.initQgis()

from qgis.PyQt.QtCore import QEvent, QPoint, Qt  # noqa: E402
from qgis.PyQt.QtGui import QKeyEvent  # noqa: E402
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent  # noqa: E402

from test_furniture_report import CRS, _fill_road  # noqa: E402


def _canvas(st):
    c = QgsMapCanvas()
    c.setDestinationCrs(CRS)
    c.resize(800, 600)
    ext = st.signs.extent() if st.signs.featureCount() else None
    x, y, _ = st.al.point_at(st.al.sta_start + 0.5 * (st.al.sta_end - st.al.sta_start))
    c.setExtent(ext if ext and not ext.isEmpty() else QgsRectangle(x - 500, y - 500, x + 500, y + 500))
    return c


def _mouse(canvas, kind, pt, button=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    t = {"move": QEvent.Type.MouseMove, "release": QEvent.Type.MouseButtonRelease}[kind]
    btn = Qt.MouseButton.NoButton if kind == "move" else button
    e = QgsMapMouseEvent(canvas, t, QPoint(400, 300), btn, btn, mods)
    e.setMapPoint(QgsPointXY(pt[0], pt[1]))
    return e


def _key(key):
    return QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)


def test_sign_tool_left_click_places_and_right_click_leaves(tmp_path):
    from road_furniture_designer.maptool import PlaceSignTool
    st, _ = _fill_road(tmp_path)
    c = _canvas(st)
    tool = PlaceSignTool(c, lambda: st, lambda: {"code": "W1", "facing": "Auto"})
    c.setMapTool(tool)
    x, y, h = st.al.point_at(400.0)
    p = (x + 6.0 * math.cos(h - math.pi / 2), y + 6.0 * math.sin(h - math.pi / 2))
    msgs = []
    tool.hover.connect(msgs.append)
    tool.canvasMoveEvent(_mouse(c, "move", p))
    assert msgs                                               # the hover text follows the mouse
    n = st.signs.featureCount()
    tool.canvasReleaseEvent(_mouse(c, "release", p, Qt.MouseButton.MiddleButton))
    assert st.signs.featureCount() == n                       # other buttons do nothing
    tool.canvasReleaseEvent(_mouse(c, "release", p))
    assert st.signs.featureCount() == n + 1
    tool.canvasReleaseEvent(_mouse(c, "release", p, Qt.MouseButton.RightButton))
    assert c.mapTool() is not tool


def test_run_tool_escape_and_right_click_cancel_a_run(tmp_path):
    from road_furniture_designer.maptool import PlaceRunTool
    st, _ = _fill_road(tmp_path)
    c = _canvas(st)
    tool = PlaceRunTool(c, lambda: st, lambda: {"mode": "run", "code": "LM01", "side": "C"})
    c.setMapTool(tool)
    a, b = st.al.point_at(300.0)[:2], st.al.point_at(360.0)[:2]
    tool.canvasReleaseEvent(_mouse(c, "release", a))
    assert tool.start is not None
    tool.canvasMoveEvent(_mouse(c, "move", b))
    tool.keyPressEvent(_key(Qt.Key.Key_Escape))
    assert tool.start is None
    tool.canvasReleaseEvent(_mouse(c, "release", a))
    tool.canvasReleaseEvent(_mouse(c, "release", b, Qt.MouseButton.RightButton))
    assert tool.start is None and c.mapTool() is tool           # first right-click cancels, the tool stays
    n = st.lines.layer.featureCount()
    tool.canvasReleaseEvent(_mouse(c, "release", a))
    tool.canvasReleaseEvent(_mouse(c, "release", b))
    assert st.lines.layer.featureCount() == n + 1
    tool.canvasReleaseEvent(_mouse(c, "release", b, Qt.MouseButton.RightButton))
    assert c.mapTool() is not tool


def test_junction_tool_events_and_enter_places_a_roundabout(tmp_path):
    from road_furniture_designer.maptool import PlaceJunctionTool
    st, _ = _fill_road(tmp_path)
    c = _canvas(st)
    x0, y0, h = st.al.point_at(600.0)
    side = (x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2))
    cfg = {"kit": "C", "piece": "", "scale": 1.0, "guides": False, "splays": False, "both": False}
    tool = PlaceJunctionTool(c, lambda: st, lambda: cfg)
    c.setMapTool(tool)
    tool.canvasMoveEvent(_mouse(c, "move", (x0, y0)))
    tool.canvasReleaseEvent(_mouse(c, "release", (x0, y0)))
    assert tool.p0 is not None
    tool.canvasMoveEvent(_mouse(c, "move", side))
    tool.keyPressEvent(_key(Qt.Key.Key_Escape))
    assert tool.p0 is None
    tool.canvasReleaseEvent(_mouse(c, "release", (x0, y0)))
    tool.canvasReleaseEvent(_mouse(c, "release", side))
    assert st.junctions.junctions()
    for j in st.junctions.junctions():
        st.remove_junction(j["id"])
    # roundabout: centre, one arm, then Enter places it
    cfg.clear(); cfg.update({"kit": "RBT", "rbt": {"island": 10.0}})
    tool.cancel()
    tool.canvasReleaseEvent(_mouse(c, "release", (x0, y0)))
    tool.canvasMoveEvent(_mouse(c, "move", side))
    tool.canvasReleaseEvent(_mouse(c, "release", side))
    tool.keyPressEvent(_key(Qt.Key.Key_Return))
    assert any(j["kit"] == "RBT" for j in st.junctions.junctions())


def test_move_tool_shift_click_moves_the_whole_junction(tmp_path):
    from road_furniture_designer.maptool import MovePieceTool
    st, _ = _fill_road(tmp_path)
    x0, y0, h = st.al.point_at(600.0)
    st.junctions.place(x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2), kit="C")
    split = next(f for f in st.junctions.layer.getFeatures() if f["piece"] == "splitter_teardrop" and f["code"] == "KERB")
    cpt = split.geometry().centroid().asPoint()
    c = _canvas(st)
    tool = MovePieceTool(c, lambda: st)
    c.setMapTool(tool)
    tool.canvasReleaseEvent(_mouse(c, "release", (cpt.x(), cpt.y())))
    assert tool.sel is not None
    tool.keyPressEvent(_key(Qt.Key.Key_Escape))
    assert tool.sel is None
    x1, y1, _ = st.al.point_at(st.al.station_offset(cpt.x(), cpt.y()).station + 10.0)
    tool.canvasReleaseEvent(_mouse(c, "release", (cpt.x(), cpt.y())))
    tool.canvasMoveEvent(_mouse(c, "move", (x1, y1)))
    tool.canvasReleaseEvent(_mouse(c, "release", (x1, y1), mods=Qt.KeyboardModifier.ShiftModifier))
    stas = {f["piece"]: f["sta"] for f in st.junctions.layer.getFeatures()}
    assert abs(stas["give_way_line"] - 610.0) < 0.5              # Shift: every piece moved, not just the splitter
