"""Map tool: hover shows chainage/offset live; left-click places the selected sign."""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsCoordinateTransform, QgsGeometry, QgsPointXY, QgsProject)
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


BAR_KINDS = ("hump_circular", "hump_trapezoidal", "speed_table", "raised_crossing")


def bars_text(d, cfg):
    """How the feature's approach bar markings went, for the placement message."""
    n = sum(1 for r in d.runs if r.code == "BAR-SET")
    if d.kind not in BAR_KINDS:
        return f"{n} bar set(s)" if n else "no bar sets"
    if cfg is not None and not cfg.bar_markings:
        return "no bar sets (Bar markings: None)"
    return f"{n} bar set(s) on the approaches"


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
        if s.get("mode") == "feature" and s.get("span"):          # crossing from kerb to kerb: two clicks
            sta_c, _d, off, _side, ok = st.locate(layer_pt.x(), layer_pt.y())
            if self.start is None:
                self.start = (sta_c, "C", off)
                self.placed.emit(f"First kerb at {format_station(st.al.display_station(sta_c), 1)}, "
                                 f"{off:+.1f} m - click the other kerb")
                return None
            a = self.start
            self.cancel()
            from dataclasses import replace
            cfg = replace(s.get("feature_cfg"), span=(a[2], off))
            try:
                d = st.add_feature("crossing", (a[0] + sta_c) / 2, cfg, s.get("auto_cfg"))
            except ValueError as ex:
                self.failed.emit(str(ex))
                return None
            self.placed.emit(d.summary + "".join(f" - {f.text}" for f in d.findings))
            return d
        if s.get("mode") == "feature":
            try:
                d = st.add_feature(s["kind"], sta, s.get("feature_cfg"), s.get("auto_cfg"))
            except ValueError as ex:
                self.failed.emit(str(ex))
                return None
            notes = [f.text for f in d.findings]
            self.placed.emit(f"{d.summary or s['kind']} at {format_station(st.al.display_station(sta), 1)}: "
                             f"{len(d.runs)} items, {len(d.signs)} signs, {bars_text(d, s.get('feature_cfg'))}"
                             + (" - " + "; ".join(notes) if notes else ""))
            return d
        it = st.lines.cat[s["code"]] if s.get("code") in st.lines.cat else None
        if it is not None and it.transverse:                      # zebra, bar set, hump ...: one click, centred
            from .rfd.features import FeatureConfig, carriageway_width, overlapping
            from .rfd.linear import CLICK_LENGTH, Run
            L = CLICK_LENGTH.get(it.code, 2.0)
            w, _src = carriageway_width(st.al, FeatureConfig(), sta)
            hits = overlapping(sta - L / 2, sta + L / 2, st.furniture_blocks()) \
                if it.code not in ("BAR-SET", "BM04") and hasattr(st, "furniture_blocks") else []
            try:
                fid = st.lines.add_run(Run(it.code, sta - L / 2, sta + L / 2, side="C", width=w))
            except ValueError as ex:
                self.failed.emit(str(ex))
                return None
            f = st.lines.layer.getFeature(fid)
            self.placed.emit(f"{it.code} {it.name} at {f['ch_from']}-{f['ch_to']}, {w:.1f} m across"
                             + "".join(f" - overlaps {h}: move one of them" for h in hits))
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
        self._params = None
        self._legs = []                         # crossroads: the other legs' placements (second_leg)
        self._rb_arms = []                      # roundabout: arms clicked or found on other alignments
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
        sta = so.station
        s = self._settings()
        if s.get("role") == "minor" and s.get("kit") not in ("BUS", "TRUCK", "CLIMB", "ACCESS", "RBT"):
            # our road joining another road usually ends there: near an end, snap to it (as place_minor does)
            from .rfd.junctions import END_SNAP
            if sta - st.al.sta_start < END_SNAP:
                sta = st.al.sta_start
            elif st.al.sta_end - sta < END_SNAP:
                sta = st.al.sta_end
        x, y, _ = st.al.point_at(sta)
        return sta, x, y

    def _rb_params(self, extra=None):
        s = self._settings()
        arms = list(self._rb_arms) + ([extra] if extra else [])
        return dict(s.get("rbt") or {}, arms=arms)

    def _rb_bearing(self, lp):
        import math
        st = self._store()
        x, y, _ = st.al.point_at(self.p0[0])
        return math.degrees(math.atan2(lp.y() - y, lp.x() - x)), math.hypot(lp.x() - x, lp.y() - y)

    def _rb_pieces(self, lp=None):
        from .rfd import junctions as J
        st = self._store()
        x, y, _ = st.al.point_at(self.p0[0])
        pl = J.place_roundabout(st.al, x, y)
        extra = None
        if lp is not None:
            b, d = self._rb_bearing(lp)
            if d > 10.0:
                extra = {"bearing_deg": round(b, 2), "src": "click", "half": 3.5}
        params = self._rb_params(extra)
        return pl, [J.build_piece(st.al, pl, "roundabout", "", params, st.junctions.templates)], params

    def _rb_found(self):
        """Arms of the other alignments of the LandXML crossing the inscribed circle."""
        import math
        from .rfd import roundabouts as RB
        st, s = self._store(), self._settings()
        r = s.get("rbt") or {}
        icd = r.get("icd") or RB.min_icd(r.get("island") or RB.DEFAULTS["island"])
        x, y, _ = st.al.point_at(self.p0[0])
        arms = RB.auto_arms(st.al, x, y, icd / 2, others=st.junctions.others())
        return [{"bearing_deg": round(math.degrees(a["bearing"]), 2), "src": a["src"], "half": round(a["half"], 2)}
                for a in arms if a["src"] != "ours"]

    def place_roundabout(self):
        st = self._store()
        from .rfd import junctions as J
        from .rfd.alignment import format_station
        if self.p0 is None:
            return None
        x, y, _ = st.al.point_at(self.p0[0])
        pl = J.place_roundabout(st.al, x, y)
        try:
            n, finds, nsigns = st.add_junction(pl, "RBT", "", False, self._rb_params(), False, None)
        except ValueError as ex:
            self.failed.emit(str(ex))
            return None
        j = next((j for j in st.junctions.junctions() if j["id"] == pl.junction_id), None)
        notes = [t for lvl, t in (j["rbt"]["notes"] if j and j.get("rbt") else []) if lvl != "info"]
        self.cancel()
        self.placed.emit(f"Roundabout at Ch {format_station(st.al.display_station(pl.station), 1)}, "
                         f"{j['rbt']['n_arms'] if j else '?'} arms, {nsigns} sign(s) proposed"
                         + "".join(f" - {t}" for t in notes))
        return pl.junction_id

    def _placement(self, lp):
        from .rfd import junctions as J
        st, s = self._store(), self._settings()
        if s.get("kit") in ("BUS", "TRUCK", "CLIMB"):
            pl, B = J.place_bay(st.al, self.p0[1], self.p0[2], lp.x(), lp.y())
            self._params = {"bay": B}
            return pl, st.al
        self._params = dict(s["access"]) if s.get("kit") == "ACCESS" and s.get("access") else None
        self._legs = []
        if s.get("role") == "minor" and s.get("kit") != "ACCESS":
            both = bool(s.get("both")) and not s.get("piece")
            pl = st.junctions.placement_minor(self.p0[1], self.p0[2], lp.x(), lp.y(), major=s.get("major") or "",
                                              scale=s.get("scale", 1.0), both=both)
            if both:
                pl, self._legs = pl[0], pl[1:]
        else:
            # the minor road's bearing snaps to another alignment of the LandXML near the cursor
            pl = J.place(st.al, self.p0[1], self.p0[2], lp.x(), lp.y(), others=st.junctions.others(),
                         scale=s.get("scale", 1.0))
        return pl, st.junctions.main_of(pl)

    def _leg_text(self, pl):
        """Which way our road's leg runs from the junction, in chainage terms."""
        import math
        from .rfd.alignment import format_station
        st = self._store()
        s0 = pl.our_station
        _, _, h = st.al.point_at(s0)
        up = math.cos(pl.bearing - h) > 0
        return f"leg towards {'higher' if up else 'lower'} chainage from Ch " \
               f"{format_station(st.al.display_station(s0), 1)}"

    def _pieces(self, lp):
        from .rfd import junctions as J
        st, s = self._store(), self._settings()
        pl, main = self._placement(lp)
        if s.get("piece"):
            kit_items = [it for it in st.junctions.templates["kits"].get(s["kit"], []) if it["piece"] == s["piece"]]
            it = kit_items[0] if kit_items else {"piece": s["piece"], "corner": "left_turn"}
            pcs = [J.build_piece(main, pl, it["piece"], it.get("corner", ""),
                                 dict(it.get("params") or {}, **(self._params or {})), st.junctions.templates)]
        elif self._params:
            pcs = []
            for it in st.junctions.templates["kits"][s["kit"]]:
                prm = dict(it.get("params") or {}, **self._params)
                if it["piece"] == "splays":
                    if not s.get("splays", True):
                        continue
                    prm.update({k: v for k, v in (s.get("splay") or {}).items() if v})
                pcs.append(J.build_piece(main, pl, it["piece"], it.get("corner", ""), prm, st.junctions.templates))
        else:
            pcs = J.build_kit(main, pl, s["kit"], st.junctions.templates, guides=s.get("guides", True),
                              splays=s.get("splays", True), splay=s.get("splay"))
            for leg in self._legs:
                pcs += J.build_kit(main, leg, s["kit"], st.junctions.templates, guides=s.get("guides", True),
                                   splays=s.get("splays", True), splay=s.get("splay"), second_leg=True)
        return pl, pcs

    def canvasMoveEvent(self, e):
        st = self._store()
        if st is None:
            return
        lp = self._xf().transform(e.mapPoint())
        self.mark.reset(GEOM_POINT)
        self.band.reset(GEOM_LINE)
        from .rfd import junctions as J
        from .rfd.alignment import format_station
        if self.p0 is None:
            sn = self._snap(lp)
            if sn is None:
                self.hover.emit("Beyond the alignment ends")
                return
            self.mark.addPoint(self._xf(False).transform(QgsPointXY(sn[1], sn[2])), True)
            what = "Roundabout centre" if self._settings().get("kit") == "RBT" else "Junction point"
            self.hover.emit(f"{what} Ch {format_station(st.al.display_station(sn[0]), 1)} - click")
            return
        try:
            if self._settings().get("kit") == "RBT":
                pl, pcs, params = self._rb_pieces(lp)
                xf = self._xf(False)
                lines = [[xf.transform(QgsPointXY(x, y)) for x, y in (p.pts + ([p.pts[0]] if p.closed else []))]
                         for pc in pcs for p in pc.parts]
                self.band.setToGeometry(QgsGeometry.fromMultiPolylineXY(lines), None)
                self.hover.emit(f"{pcs[0].params['n_arms']} arms with the one at the mouse - click to add it, "
                                f"right-click or Enter to place without it")
                return
            pl, pcs = self._pieces(lp)
        except ValueError as ex:
            self.hover.emit(str(ex))
            return
        xf = self._xf(False)
        lines = [[xf.transform(QgsPointXY(x, y)) for x, y in (part.pts + ([part.pts[0]] if part.closed else []))]
                 for pc in pcs for part in pc.parts]
        self.band.setToGeometry(QgsGeometry.fromMultiPolylineXY(lines), None)
        F = pl.frame(st.junctions.main_of(pl))
        if pl.role == "bay":
            st0, s1, s2, s3 = pcs[0].params["stations"]
            self.hover.emit(f"{pcs[0].params.get('kind', 'bus bay').capitalize()} {abs(s2 - s1):.0f} m on the "
                            f"{'left' if F.side == 'L' else 'right'}, "
                            f"tapers {pcs[0].params['entry']:g} / {pcs[0].params['exit']:g} m - click to place")
            return
        if pl.role == "minor":
            which = ("both legs (crossroads)" if self._legs else self._leg_text(pl)
                     + (" - move the mouse across the main road for the other leg"
                        if pl.main_ref.startswith("alg:") and len(J.minor_legs(st.al, pl.our_station, F.al)) > 1
                        else ""))
            self.hover.emit(f"Our road joins {('alignment ' + pl.main_ref[4:]) if pl.main_ref.startswith('alg:') else 'the main road'}"
                            f" at {F.crossing_angle:.0f} deg, {which} - click to place")
        else:
            self.hover.emit(f"Crossing angle {F.crossing_angle:.0f} deg, minor road on the "
                            f"{'left' if F.side == 'L' else 'right'} - click to place")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.p0 is not None \
                and self._settings().get("kit") == "RBT":
            self.place_roundabout()

    def cancel(self):
        self.p0 = None
        self._legs = []
        self._rb_arms = []
        self.band.reset(GEOM_LINE)

    def canvasReleaseEvent(self, e):
        st = self._store()
        if st is None:
            return
        if e.button() == Qt.RightButton:
            if self.p0 is not None and self._settings().get("kit") == "RBT":
                self.place_roundabout()
            elif self.p0 is not None:
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
            if s.get("kit") == "RBT":
                self._rb_arms = self._rb_found()
                self.placed.emit(f"Roundabout centre Ch {format_station(st.al.display_station(sn[0]), 1)}: our road's arms"
                                 + (f" and {len(self._rb_arms)} on other alignments" if self._rb_arms else "")
                                 + " - click any other arm, then right-click or Enter to place")
                return None
            nxt = ("now click where the bay ends" if s.get("kit") in ("BUS", "TRUCK")
                   else "now click where the full-width lane ends" if s.get("kit") == "CLIMB"
                   else "now click a point along the main road" if s.get("role") == "minor" and not s.get("major")
                   else ("click again to place both legs" if s.get("both") else
                         "move the mouse to the side of our road's leg, then click to place")
                   if s.get("role") == "minor"
                   else "now click a point up the minor road")
            self.placed.emit(f"Junction point Ch {format_station(st.al.display_station(sn[0]), 1)} - {nxt}")
            return None
        if s.get("kit") == "RBT":                       # another arm
            b, d = self._rb_bearing(lp)
            if d <= 10.0:
                self.failed.emit("Click further from the centre to give an arm's direction")
                return None
            self._rb_arms.append({"bearing_deg": round(b, 2), "src": "click", "half": 3.5})
            self.placed.emit(f"Arm added ({len(self._rb_arms)} besides our road's) - another, or right-click / Enter "
                             f"to place")
            return None
        try:
            pl, _ = self._placement(lp)
            n, finds, nsigns = st.add_junction(pl, s["kit"], s.get("piece") or "", s.get("guides", True),
                                               self._params, s.get("splays", True), s.get("splay"))
            for leg in self._legs:
                n2, f2, s2 = st.add_junction(leg, s["kit"], "", s.get("guides", True), self._params,
                                             s.get("splays", True), s.get("splay"), second_leg=True)
                n, nsigns = n + n2, nsigns + s2
                finds = list(finds) + [f for f in f2 if f not in finds]
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


class MovePieceTool(QgsMapToolEmitPoint):
    """Move a placed junction piece along its road: click the piece, then where it should go (the preview
    follows the mouse). Shift moves the whole junction (where our road is the main road). The piece is rebuilt
    from its template at the new chainage, so it keeps its shape, skew and scale. Right-click or Esc cancels."""
    hover = pyqtSignal(str)
    placed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, canvas, store_getter):
        super().__init__(canvas)
        self.canvas = canvas
        self._store = store_getter
        self.sel = None                         # (piece_uuid, junction_id, role, station of the first click, main al)
        self.band = QgsRubberBand(canvas, GEOM_LINE)
        self.band.setColor(QColor(200, 60, 160, 220))
        self.band.setWidth(2)
        self.setCursor(Qt.OpenHandCursor)

    def _xf(self, to_layer=True):
        st = self._store()
        a, b = self.canvas.mapSettings().destinationCrs(), st.junctions.layer.crs()
        return QgsCoordinateTransform(a, b, QgsProject.instance()) if to_layer else \
            QgsCoordinateTransform(b, a, QgsProject.instance())

    def _delta(self, lp):
        so = self.sel[4].station_offset(lp.x(), lp.y())
        return so.station - self.sel[3]

    def canvasMoveEvent(self, e):
        st = self._store()
        if st is None:
            return
        lp = self._xf().transform(e.mapPoint())
        if self.sel is None:
            hit = st.junctions.piece_at(lp.x(), lp.y())
            self.hover.emit("Click a junction piece to move it (Shift: the whole junction)" if hit
                            else "No junction piece here")
            return
        d = self._delta(lp)
        self.band.reset(GEOM_LINE)
        xf = self._xf(False)
        for f in st.junctions.layer.getFeatures():
            if f["piece_uuid"] != self.sel[0]:
                continue
            g = QgsGeometry(f.geometry())
            # preview: the piece shifted along the road at its own station (exact on straights)
            sta = float(f["sta"])
            al = self.sel[4]
            x0, y0, _ = al.point_at(min(max(sta, al.sta_start), al.sta_end))
            x1, y1, _ = al.point_at(min(max(sta + d, al.sta_start), al.sta_end))
            g.translate(x1 - x0, y1 - y0)
            g.transform(xf)
            self.band.addGeometry(g, None)
        from .rfd.alignment import format_station
        self.hover.emit(f"Move {d:+.1f} m along the road - click to place")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel()

    def cancel(self):
        self.sel = None
        self.band.reset(GEOM_LINE)

    def canvasReleaseEvent(self, e):
        st = self._store()
        if st is None:
            return
        if e.button() == Qt.RightButton:
            if self.sel is not None:
                self.cancel()
            else:
                self.canvas.unsetMapTool(self)
            return
        if e.button() != Qt.LeftButton:
            return
        self.click(self._xf().transform(e.mapPoint()), bool(e.modifiers() & Qt.ShiftModifier))

    def click(self, lp, whole=False):
        st = self._store()
        if self.sel is None:
            hit = st.junctions.piece_at(lp.x(), lp.y())
            if hit is None:
                self.failed.emit("No junction piece here")
                return None
            pu, jid, role = hit
            f = st.junctions._group(pu)[0]
            from .rfd import junctions as J
            pl = J.Placement(float(f["sta"]), 0.0, role=role, main_ref=f["main_ref"] or "")
            al = st.junctions.main_of(pl)
            self.sel = (pu, jid, role, al.station_offset(lp.x(), lp.y()).station, al, whole)
            self.placed.emit("Piece picked - click where it should go")
            return None
        d = self._delta(lp)
        pu, whole = self.sel[0], whole or self.sel[5]
        self.cancel()
        try:
            n = st.junctions.move(pu, d, whole=whole)
            if hasattr(st, "refresh_junction_warnings"):
                st.refresh_junction_warnings()          # W1 / W2 / W5 follow the junction
        except ValueError as ex:
            self.failed.emit(str(ex))
            return None
        self.placed.emit(f"{n} piece(s) moved {d:+.1f} m along the road")
        return n

    def deactivate(self):
        self.cancel()
        super().deactivate()
