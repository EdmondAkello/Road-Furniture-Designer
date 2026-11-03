import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsProject


class RoadSignDesignerPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        self.action = QAction(QIcon(os.path.join(os.path.dirname(__file__), "icon.svg")),
                              "RoadSign Designer", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.toggled.connect(self.toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("RoadSign Designer", self.action)
        QgsProject.instance().readProject.connect(self._project_loaded)

    def _ensure_dock(self):
        if self.dock is None:
            from .dock import RsdDock
            self.dock = RsdDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(self.action.setChecked)
        return self.dock

    def toggle(self, on):
        if on:
            self._ensure_dock().show()
        elif self.dock:
            self.dock.hide()

    def _project_loaded(self, *_):
        gp, ok = QgsProject.instance().readEntry("RoadSignDesigner", "gpkg", "")
        if ok and gp and os.path.exists(gp):
            d = self._ensure_dock()
            if d.store is None or d.store.gpkg != gp:
                d.open_path(gp)

    def unload(self):
        try:
            QgsProject.instance().readProject.disconnect(self._project_loaded)
        except Exception:
            pass
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.iface.removePluginMenu("RoadSign Designer", self.action)
        self.iface.removeToolBarIcon(self.action)
