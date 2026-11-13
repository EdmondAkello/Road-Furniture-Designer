"""The dock fits a 1080p screen next to other panels and does not vanish when it is squeezed."""
import os
import sys
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
sys.path.insert(0, ROOT)

from qgis.core import QgsApplication  # noqa: E402

if QgsApplication.instance() is None:
    _app = QgsApplication([], True)
    _app.initQgis()

from qgis.gui import QgsMapCanvas  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow, QScrollArea  # noqa: E402


def _iface():
    win = QMainWindow()
    iface = mock.MagicMock()
    iface.mapCanvas.return_value = QgsMapCanvas()
    iface.mainWindow.return_value = win
    iface.addDockWidget.side_effect = lambda area, d: win.addDockWidget(area, d)
    return iface, win


def test_every_tab_scrolls_and_the_dock_fits_600_px():
    from qgis.PyQt.QtGui import QFont
    from road_furniture_designer.dock import RsdDock
    # a known font, so the widths do not depend on the machine's default (the QGIS 3.44 CI image differs)
    old = QgsApplication.font()
    QgsApplication.setFont(QFont("DejaVu Sans", 9))
    try:
        _dock_fits(RsdDock)
    finally:
        QgsApplication.setFont(old)


def _dock_fits(RsdDock):
    iface, win = _iface()
    d = RsdDock(iface, win)
    labels = [d.tabs.tabText(i) for i in range(d.tabs.count())]
    assert labels == ["Section", "Signs", "Auto", "Linear", "Calming", "Speed limits", "Junctions + bays", "Outputs"]
    for i in range(d.tabs.count()):
        assert isinstance(d.tabs.widget(i), QScrollArea)
        assert d.page(labels[i]) is d.tabs.widget(i).widget()
    # before the scroll areas the dock asked for 1166 x 1048 px
    assert d.minimumSizeHint().height() <= 600, d.minimumSizeHint()
    assert d.minimumSizeHint().width() <= 420, d.minimumSizeHint()
    # every tab's content fits a 380 px dock without sideways scrolling
    wide = {lab: d.page(lab).minimumSizeHint().width() for lab in labels}
    assert max(wide.values()) <= 365, wide
    # shortened captions keep their full wording as the tooltip
    assert d.chk_restrict.text() == "Keep inside the corridor (RDM 2.4)"
    assert "0.6–3.0 m" in d.chk_restrict.toolTip()
    # the buttons at the bottom of a long tab are still there, reachable by scrolling
    assert d.btn_report.isVisibleTo(d.page("Outputs"))


def test_hidden_by_qt_is_not_hidden_by_the_plugin():
    import road_furniture_designer as P
    iface, win = _iface()
    plugin = P.classFactory(iface)
    plugin.initGui()
    plugin.action.trigger()                               # user clicks: dock shown, button ticked
    d = plugin.dock
    assert plugin.action.isChecked() and not d.isHidden()
    d.visibilityChanged.emit(False)                       # Qt says it is out of view (tabbed / squeezed)
    assert not plugin.action.isChecked()
    assert not d.isHidden()                               # ... but the plugin did not hide it
    plugin.action.trigger()                               # a click brings it back to the front
    assert plugin.action.isChecked() and not d.isHidden()
    plugin.action.trigger()                               # and a second click hides it
    assert d.isHidden()
    d.setFloating(True)
    plugin.action.trigger()
    assert not d.isFloating() and not d.isHidden()
    plugin.unload()


def test_leaving_a_tab_switches_its_map_tool_off():
    """Trial fix: the Calming tool left on while the Linear tab shows a zebra placed a hump."""
    from road_furniture_designer.dock import RsdDock
    iface, win = _iface()
    d = RsdDock(iface, win)
    labels = [d.tabs.tabText(i) for i in range(d.tabs.count())]
    for btn, tab, other in ((d.btn_fplace, "Calming", "Linear"), (d.btn_ldraw, "Linear", "Calming"),
                            (d.btn_jplace, "Junctions + bays", "Signs")):
        d.tabs.setCurrentIndex(labels.index(tab))
        btn.blockSignals(True); btn.setChecked(True); btn.blockSignals(False)   # no project: skip the tool itself
        d.tabs.setCurrentIndex(labels.index(other))
        assert not btn.isChecked(), tab
    # the hover read-out names what a click places
    d._run_mode = "feature"
    d._run_hover("Ch 0+100")
    assert d.lbl_fhover.text().startswith("Calming - ")
    d._run_mode = "run"
    d._run_hover("Ch 0+100")
    assert d.lbl_lhover.text().startswith("Linear - ")


def test_opens_as_a_tab_beside_the_processing_toolbox():
    import road_furniture_designer as P
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QDockWidget
    iface, win = _iface()
    tb = QDockWidget("Processing Toolbox", win); tb.setObjectName("ProcessingToolbox")
    win.addDockWidget(Qt.RightDockWidgetArea, tb)
    win.show(); tb.show()
    plugin = P.classFactory(iface)
    plugin.initGui()
    plugin.action.trigger()
    assert tb in win.tabifiedDockWidgets(plugin.dock)
    assert not plugin.dock.isHidden()
    plugin.unload()
    win.close()
