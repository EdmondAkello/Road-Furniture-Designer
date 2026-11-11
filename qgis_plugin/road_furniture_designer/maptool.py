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


class PlaceRunTool(QgsMapToolEmitPoint):
    """Draw linear furniture by clicking along the road, or place a traffic calming feature.

    Run mode: first click sets the start (chainage, side and offset), second click the end.
    The offset is measured from the chosen corridor edge (or the centreline), or fixed.
    Feature mode: one click places a hump, table, bump, bar markings or crossing at that chainage.
    Right-click or Esc cancels a started run; a second right-click leaves the tool."""
    hover = pyqtSignal(str)
    placed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, canvas, store_getter, settings_getter):
        super().__init__(canvas)
        self.canvas = canvas
        self._store = store_getter
        self._settings = settings_getter
        self.start = None                     # (station, side, offset_from_ref)
        self.band = QgsRubberBand(canvas, GEOM_LINE)
        self.band.setColor(QColor(0, 160, 120, 220))
        self.band.setWidth(3)
        self.mark = QgsRubberBand(canvas, GEOM_POINT)
        self.mark.setColor(QColor(0, 160, 120, 230))
        self.mark.setIconSize(10)
        self.setCursor(Qt.CrossCursor)

    def _xf(self, to_layer=True):
        st = self._store()
        a, b = self.canvas.mapSettings().destinationCrs(), st.signs.crs()
        return QgsCoordinateTransform(a, b, QgsProject.instance()) if to_layer else \
            QgsCoordinateTransform(b, a, QgsProject.instance())

    def resolve(self, layer_pt):
        """(station, side, offset from the reference, signed offset from centreline, text) for a click."""
        st = self._store()
        s = self._settings()
        sta, disp, off, side, in_range = st.locate(layer_pt.x(), layer_pt.y())
        if not in_range:
            return None
        from .rfd.alignment import format_station
        if s.get("mode") == "feature" or s.get("side") == "C":
            o = s.get("lock_offset") or 0.0
            return sta, "C", o, o, f"Ch {format_station(disp, 2)}   centre" + (f" {o:+.2f} m" if o else "")
        if s.get("side") in ("L", "R"):
            side = s["side"]
        ref = s.get("edge_ref")
        ro = st.al.edges.offset(ref, side, sta) if (ref and st.al.edges) else None
        if ref and ro is None:
            return sta, side, None, None, f"Ch {format_station(disp, 2)}   no {ref} edge here"
        base = ro or 0.0
        rel = s["lock_offset"] if s.get("lock_offset") is not None else abs(off) - base
        signed = (base + rel) * (1 if side == "R" else -1)
        return sta, side, rel, signed, (f"Ch {format_station(disp, 2)}   {'Right' if side == 'R' else 'Left'} "
                                        f"{rel:+.2f} m from {ref or 'centreline'}")

    def _preview(self, sta, side, rel):
        st = self._store()
        s = self._settings()
        from .rfd.linear import Run, geometry
        self.band.reset(GEOM_LINE)
        if self.start is None or rel is None:
            return
        a = self.start
        if a[2] is None:
            return
        try:
            r = Run(s.get("code") or "LM01", a[0], sta, side=a[1], offset=a[2],
                    edge_ref=s.get("edge_ref") if a[1] != "C" else None)
            for part in geometry(st.al, r, step=max(2.0, (abs(sta - a[0]) / 200) or 2.0))[:1]:
                xf = self._xf(False)
                for i, (x, y) in enumerate(part):
                    self.band.addPoint(xf.transform(QgsPointXY(x, y)), i == len(part) - 1)
        except ValueError:
            pass

    def canvasMoveEvent(self, e):
        if self._store() is None:
            return
        lp = self._xf().transform(e.mapPoint())
        res = self.resolve(lp)
        self.mark.reset(GEOM_POINT)
        if res is None:
            self.hover.emit("Beyond the alignment ends")
            return
        sta, side, rel, signed, text = res
        if signed is not None:
            x, y, _ = self._store().al.point_at(sta, signed)
            self.mark.addPoint(self._xf(False).transform(QgsPointXY(x, y)), True)
        self._preview(sta, side, rel)
        if self.start is not None:
            text += f"   length {abs(sta - self.start[0]):.1f} m"
        self.hover.emit(text)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel()

    def cancel(self):
        self.start = None
        self.band.reset(GEOM_LINE)

    def canvasReleaseEvent(self, e):
        if self._store() is None:
            return
        if e.button() == Qt.RightButton:
            if self.start is not None:
                self.cancel()
            else:
                self.canvas.unsetMapTool(self)
            return
        if e.button() == Qt.LeftButton:
            self.click(self._xf().transform(e.mapPoint()))

    def click(self, layer_pt):
        st = self._store()
        s = self._settings()
        res = self.resolve(layer_pt)
        if res is None:
            self.failed.emit("Beyond the alignment ends")
            return None
        sta, side, rel, _signed, _ = res
        from .rfd.alignment import format_station
        if s.get("mode") == "feature":
            try:
                d = st.add_feature(s["kind"], sta, s.get("feature_cfg"), s.get("auto_cfg"))
            except ValueError as ex:
                self.failed.emit(str(ex))
                return None
            notes = [f.text for f in d.findings]
            self.placed.emit(f"{d.summary or s['kind']} at {format_station(st.al.display_station(sta), 1)}: "
                             f"{len(d.runs)} items, {len(d.signs)} signs" + (" - " + "; ".join(notes) if notes else ""))
            return d
        it = st.lines.cat[s["code"]] if s.get("code") in st.lines.cat else None
        if it is not None and it.transverse:                      # zebra, bar set, hump ...: one click, centred
            from .rfd.features import FeatureConfig, carriageway_width
            from .rfd.linear import CLICK_LENGTH, Run
            L = CLICK_LENGTH.get(it.code, 2.0)
            w, _src = carriageway_width(st.al, FeatureConfig(), sta)
            try:
                fid = st.lines.add_run(Run(it.code, sta - L / 2, sta + L / 2, side="C", width=w))
            except ValueError as ex:
                self.failed.emit(str(ex))
                return None
            f = st.lines.layer.getFeature(fid)
            self.placed.emit(f"{it.code} at {f['ch_from']}-{f['ch_to']}, {w:.1f} m across")
            st.lines.layer.triggerRepaint()
            return fid
        if rel is None:
            self.failed.emit(f"No {s.get('edge_ref')} edge at this chainage")
            return None
        if self.start is None:
            self.start = (sta, side, rel)
            self.placed.emit(f"Start {format_station(st.al.display_station(sta), 1)} - click the end")
            return None
        from .rfd.linear import Run
        a = self.start
        self.cancel()
        if abs(sta - a[0]) < 0.5:
            self.failed.emit("Start and end are the same chainage")
            return None
        try:
            fid = st.lines.add_run(Run(s["code"], a[0], sta, side=a[1], offset=a[2],
                                       edge_ref=s.get("edge_ref") if a[1] != "C" else None,
                                       no_overtaking=bool(s.get("no_overtaking")), flip=bool(s.get("flip"))))
        except ValueError as ex:
            self.failed.emit(str(ex))
            return None
        f = st.lines.layer.getFeature(fid)
        self.placed.emit(f"{f['item_code']} {f['ch_from']}-{f['ch_to']} {f['side']}: {f['quantity']:g} {f['unit']}")
        st.lines.layer.triggerRepaint()
        return fid

    def deactivate(self):
        self.cancel()
        self.mark.reset(GEOM_POINT)
        super().deactivate()


class PlaceJunctionTool(QgsMapToolEmitPoint):
    """Place junction islands and markings from a template with two clicks.

    First click: the junction point (snapped to the main road centreline). Then move the
    mouse up the minor road - the pieces follow, with the skew shown - and click to place.
    Right-click or Esc cancels; a second right-click leaves the tool."""
    hover = pyqtSignal(str)
    placed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, canvas, store_getter, settings_getter):
        super().__init__(canvas)
        self.canvas = canvas
        self._store = store_getter
        self._settings = settings_getter        # {"kit", "piece", "scale", "guides"}
        self.p0 = None
        self.band = QgsRubberBand(canvas, GEOM_LINE)
        self.band.setColor(QColor(200, 60, 160, 220))
        self.band.setWidth(1)
        self.mark = QgsRubberBand(canvas, GEOM_POINT)
        self.mark.setColor(QColor(200, 60, 160, 230))
        self.mark.setIconSize(10)
        self.setCursor(Qt.CrossCursor)

    def _xf(self, to_layer=True):
        st = self._store()
        a, b = self.canvas.mapSettings().destinationCrs(), st.signs.crs()
        return QgsCoordinateTransform(a, b, QgsProject.instance()) if to_layer else \
            QgsCoordinateTransform(b, a, QgsProject.instance())

    def _snap(self, lp):
        st = self._store()
        so = st.al.station_offset(lp.x(), lp.y())
        if not so.in_range:
            return None
        x, y, _ = st.al.point_at(so.station)
        return so.station, x, y

    def _placement(self, lp):
        from .rfd import junctions as J
        st, s = self._store(), self._settings()
        if s.get("role") == "minor":
            pl = st.junctions.placement_minor(self.p0[1], self.p0[2], lp.x(), lp.y(), major=s.get("major") or "",
                                              scale=s.get("scale", 1.0))
        else:
            pl = J.place(st.al, self.p0[1], self.p0[2], lp.x(), lp.y(), scale=s.get("scale", 1.0))
        return pl, st.junctions.main_of(pl)

    def _pieces(self, lp):
        from .rfd import junctions as J
        st, s = self._store(), self._settings()
        pl, main = self._placement(lp)
        if s.get("piece"):
            kit_items = [it for it in st.junctions.templates["kits"].get(s["kit"], []) if it["piece"] == s["piece"]]
            it = kit_items[0] if kit_items else {"piece": s["piece"], "corner": "left_turn"}
            pcs = [J.build_piece(main, pl, it["piece"], it.get("corner", ""), it.get("params"),
                                 st.junctions.templates)]
        else:
            pcs = J.build_kit(main, pl, s["kit"], st.junctions.templates, guides=s.get("guides", True))
        return pl, pcs

    def canvasMoveEvent(self, e):
        st = self._store()
        if st is None:
            return
        lp = self._xf().transform(e.mapPoint())
        self.mark.reset(GEOM_POINT)
        self.band.reset(GEOM_LINE)
        from .rfd.alignment import format_station
        if self.p0 is None:
            sn = self._snap(lp)
            if sn is None:
                self.hover.emit("Beyond the alignment ends")
                return
            self.mark.addPoint(self._xf(False).transform(QgsPointXY(sn[1], sn[2])), True)
            self.hover.emit(f"Junction point Ch {format_station(st.al.display_station(sn[0]), 1)} - click")
            return
        try:
            pl, pcs = self._pieces(lp)
        except ValueError as ex:
            self.hover.emit(str(ex))
            return
        xf = self._xf(False)
        lines = [[xf.transform(QgsPointXY(x, y)) for x, y in (part.pts + ([part.pts[0]] if part.closed else []))]
                 for pc in pcs for part in pc.parts]
        self.band.setToGeometry(QgsGeometry.fromMultiPolylineXY(lines), None)
        F = pl.frame(st.junctions.main_of(pl))
        if pl.role == "minor":
            self.hover.emit(f"Our road joins {('alignment ' + pl.main_ref[4:]) if pl.main_ref.startswith('alg:') else 'the main road'}"
                            f" at {F.crossing_angle:.0f} deg - click to place")
        else:
            self.hover.emit(f"Crossing angle {F.crossing_angle:.0f} deg, minor road on the "
                            f"{'left' if F.side == 'L' else 'right'} - click to place")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel()

    def cancel(self):
        self.p0 = None
        self.band.reset(GEOM_LINE)

    def canvasReleaseEvent(self, e):
        st = self._store()
        if st is None:
            return
        if e.button() == Qt.RightButton:
            if self.p0 is not None:
                self.cancel()
            else:
                self.canvas.unsetMapTool(self)
            return
        if e.button() != Qt.LeftButton:
            return
        self.click(self._xf().transform(e.mapPoint()))

    def click(self, lp):
        st, s = self._store(), self._settings()
        from .rfd.alignment import format_station
        if self.p0 is None:
            sn = self._snap(lp)
            if sn is None:
                self.failed.emit("Beyond the alignment ends")
                return None
            self.p0 = sn
            nxt = ("now click a point along the main road" if s.get("role") == "minor" and not s.get("major")
                   else "click again to place" if s.get("role") == "minor"
                   else "now click a point up the minor road")
            self.placed.emit(f"Junction point Ch {format_station(st.al.display_station(sn[0]), 1)} - {nxt}")
            return None
        try:
            pl, _ = self._placement(lp)
            n, finds, nsigns = st.add_junction(pl, s["kit"], s.get("piece") or "", s.get("guides", True))
        except ValueError as ex:
            self.failed.emit(str(ex))
            return None
        self.cancel()
        what = s.get("piece") or f"type {s['kit']} kit"
        our = pl.our_station if pl.role == "minor" else pl.station
        self.placed.emit(f"{what}: {n} piece(s) at Ch {format_station(st.al.display_station(our), 1)}"
                         + (f", {nsigns} sign(s) proposed" if nsigns else "")
                         + ("".join(f" - {lvl}: {t}" for lvl, t in finds)))
        return pl.junction_id

    def deactivate(self):
        self.cancel()
        self.mark.reset(GEOM_POINT)
        super().deactivate()
