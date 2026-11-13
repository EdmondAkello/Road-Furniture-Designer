import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProject

from .compat import QAction


class RoadFurnitureDesignerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        self.action = QAction(QIcon(os.path.join(os.path.dirname(__file__), "icon.svg")),
                              "Road Furniture Designer", self.iface.mainWindow())
        self.action.setCheckable(True)
        # triggered (a click), not toggled: the dock reporting itself hidden (tabbed behind another
        # panel, squeezed by a resize) only unticks the button and never hides the dock
        self.action.triggered.connect(self.toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Road Furniture Designer", self.action)
        from .links import open_guide
        self.guide_action = QAction("User Guide and Technical Manual (PDF)", self.iface.mainWindow())
        self.guide_action.triggered.connect(open_guide)
        self.iface.addPluginToMenu("Road Furniture Designer", self.guide_action)
        QgsProject.instance().readProject.connect(self._project_loaded)

    def _ensure_dock(self):
        if self.dock is None:
            from .dock import RsdDock
            self.dock = RsdDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self._tab_with_toolbox()
            self.dock.visibilityChanged.connect(self.action.setChecked)
        return self.dock

    def _tab_with_toolbox(self):
        """Open as a tab beside the Processing Toolbox (or another panel docked on the right), full height,
        rather than squeezed under it. The user can move it anywhere; QGIS remembers where."""
        from qgis.PyQt.QtWidgets import QDockWidget
        win = self.iface.mainWindow()
        if not hasattr(win, "tabifyDockWidget") or not hasattr(win, "findChildren"):
            return
        try:
            docks = [d for d in win.findChildren(QDockWidget)
                     if d is not self.dock and d.isVisible() and not d.isFloating()
                     and win.dockWidgetArea(d) == Qt.DockWidgetArea.RightDockWidgetArea]
        except (TypeError, RuntimeError):
            return
        if not docks:
            return
        toolbox = next((d for d in docks if d.objectName() == "ProcessingToolbox"), docks[0])
        win.tabifyDockWidget(toolbox, self.dock)
        self.dock.show()
        self.dock.raise_()

    def toggle(self, on):
        if on:
            d = self._ensure_dock()
            if d.isFloating() and not d.isVisible():
                d.setFloating(False)          # a lost floating dock comes back docked
            d.show()
            d.raise_()                        # brings it to the front when tabbed behind another panel
            self.action.setChecked(True)
        elif self.dock:
            self.dock.hide()

    def _project_loaded(self, *_):
        gp, ok = QgsProject.instance().readEntry("RoadFurnitureDesigner", "gpkg", "")
        if not gp:                       # projects saved before the rename
            gp, ok = QgsProject.instance().readEntry("RoadSignDesigner", "gpkg", "")
        if ok and gp and os.path.exists(gp):
            d = self._ensure_dock()
            if d.store is None or d.store.gpkg != gp:
                d.open_path(gp)

    def unload(self):
        try:
            QgsProject.instance().readProject.disconnect(self._project_loaded)
        # Not connected (plugin loaded without a project); nothing to undo.
        except Exception:  # nosec B110
            pass
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.iface.removePluginMenu("Road Furniture Designer", self.action)
        if getattr(self, "guide_action", None) is not None:
            self.iface.removePluginMenu("Road Furniture Designer", self.guide_action)
        self.iface.removeToolBarIcon(self.action)
