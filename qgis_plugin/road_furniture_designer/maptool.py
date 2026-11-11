"""Map tool: hover shows chainage/offset live; left-click places the selected sign."""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject,
                       QgsWkbTypes)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand

from .compat import GEOM_LINE, GEOM_POINT


class PlaceSignTool(QgsMapToolEmitPoint):
    hover = pyqtSignal(str)
    placed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, canvas, store_getter, settings_getter):
        super().__init__(canvas)
        self.canvas = canvas
        self._store = store_getter
        self._settings = settings_getter
        self.band = QgsRubberBand(canvas, GEOM_LINE)
        self.band.setColor(QColor(255, 120, 0, 200))
        self.band.setWidth(2)
        self.mark = QgsRubberBand(canvas, GEOM_POINT)
        self.mark.setColor(QColor(255, 120, 0, 220))
        self.mark.setIconSize(10)
        self.setCursor(Qt.CrossCursor)

    # -- coordinates
    def _to_layer(self, pt):
        st = self._store()
        xf = QgsCoordinateTransform(self.canvas.mapSettings().destinationCrs(), st.signs.crs(),
                                    QgsProject.instance())
        return xf.transform(pt)

    def _to_canvas(self, pt):
        st = self._store()
        xf = QgsCoordinateTransform(st.signs.crs(), self.canvas.mapSettings().destinationCrs(),
                                    QgsProject.instance())
        return xf.transform(pt)

    def attach_tolerance(self):
        # ~12 screen pixels, in layer units (assumes a projected CRS in metres)
        return max(0.5, 12 * self.canvas.mapUnitsPerPixel())

    def preview(self, layer_pt):
        """Where a click at layer_pt would land, and the readout text."""
        st = self._store()
        s = self._settings()
        if s.get("attach"):
            host = st.nearest_post(layer_pt.x(), layer_pt.y(), self.attach_tolerance())
            if host is not None:
                p = host.geometry().asPoint()
                return p, p, f"Add face to post {host['post_ref']} ({host['chainage']} {host['side']})"
        sta, disp, off, side, in_range = st.locate(layer_pt.x(), layer_pt.y())
        if not in_range:
            return None, None, "Beyond the alignment ends"
        ref, ro = st.edge_info(sta, side, s.get("edge_ref"))
        if s.get("lock_offset") is not None:
            off = (abs(s["lock_offset"]) + (ro or 0.0)) * (1 if side == "R" else -1)
        if s.get("restrict") and st.al.edges:
            from .rfd.corridor import clamp_offset
            a, _ = clamp_offset(st.al.edges, side, sta, abs(off), ref or st.default_edge_ref())
            off = a * (1 if side == "R" else -1)
        x, y, _ = st.al.point_at(sta, off)
        cx, cy, _ = st.al.point_at(sta, 0.0)
        from .rfd.alignment import format_station
        text = f"Ch {format_station(disp, 2)}   {abs(off):.2f} m {'Right' if side == 'R' else 'Left'}"
        if ro is not None:
            text += f"   ({abs(off) - ro:+.2f} m from {ref})"
        if st.al.profile is not None:
            g = st.al.profile.grade(sta)
            if g is not None:
                text += f"   grade {g:+.1f}%"
        return QgsPointXY(x, y), QgsPointXY(cx, cy), text

    # -- events
    def canvasMoveEvent(self, e):
        if self._store() is None:
            return
        lp = self._to_layer(e.mapPoint())
        land, centre, text = self.preview(lp)
        self.band.reset(GEOM_LINE)
        self.mark.reset(GEOM_POINT)
        if land is not None:
            self.band.addPoint(self._to_canvas(centre), False)
            self.band.addPoint(self._to_canvas(land), True)
            self.mark.addPoint(self._to_canvas(land), True)
        self.hover.emit(text)

    def canvasReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            self.canvas.unsetMapTool(self)
            return
        if e.button() != Qt.LeftButton or self._store() is None:
            return
        self.place_at(self._to_layer(e.mapPoint()))

    def place_at(self, layer_pt):
        st = self._store()
        s = self._settings()
        if not s.get("code"):
            self.failed.emit("Pick a sign type first")
            return None
        try:
            fid, vals = st.add_sign(layer_pt.x(), layer_pt.y(), s["code"], s.get("size"),
                                    s.get("facing", "Auto"), s.get("skew", 0.0),
                                    s.get("lock_offset"),
                                    self.attach_tolerance() if s.get("attach") else None,
                                    legend=s.get("legend", ""), road_class=s.get("road_class", ""),
                                    mirror=s.get("mirror", False), edge_ref=s.get("edge_ref"),
                                    restrict=s.get("restrict", False))
        except ValueError as ex:
            self.failed.emit(str(ex))
            return None
        sd = st.cat.signs[vals["sign_code"]]
        msg = (f"{vals['post_ref']}  {vals['sign_code']}  {vals['chainage']}  {vals['side']}  "
               f"{vals['offset_m']:.2f} m  {vals['facing']}  {vals['size']}"
               + (" (auto)" if vals.get("size_auto") else ""))
        self.placed.emit(msg)
        if sd.legend in ("directional", "plate") and not vals.get("legend"):
            self.failed.emit(f"{sd.code} needs a legend - type it in the Legend box, or use Edit legend… on the Signs tab")
        return fid

    def deactivate(self):
        self.band.reset(GEOM_LINE)
        self.mark.reset(GEOM_POINT)
        super().deactivate()
