"""SignStore: the RSD GeoPackage project and the live sign layer.

The sign layer is the master record. Users only choose WHAT (sign code, size,
facing) and WHERE (a click). Everything engineering-referenced - chainage,
offset, side, facing azimuth, post number - is derived from the geometry and the
LandXML alignment, and recomputed whenever a sign is moved.
"""
from __future__ import annotations

import json
import math
import os
import uuid

from qgis.PyQt.QtCore import QObject, QPointF, QVariant, pyqtSignal
from qgis.core import (
    QgsCoordinateReferenceSystem, QgsFeature, QgsField, QgsFields, QgsGeometry,
    QgsPointXY, QgsProject, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
    QgsCoordinateTransformContext, QgsFeatureRequest, QgsSpatialIndex, QgsProperty,
    QgsSvgMarkerSymbolLayer, QgsSimpleMarkerSymbolLayer, QgsMarkerSymbol, QgsSymbolLayer,
    QgsSingleSymbolRenderer, QgsLineSymbol, QgsPalLayerSettings, QgsTextFormat,
    QgsVectorLayerSimpleLabeling, Qgis, QgsSimpleMarkerSymbolLayerBase)
from qgis.PyQt.QtGui import QColor

from .compat import (GEOM_CIRCLE, PROP_ENABLED, PROP_OFFSET, FW_CREATE_FILE, FW_CREATE_LAYER, FW_NO_ERROR, LABEL_OVER_POINT, MARKER_ARROWHEAD,
                     PROP_ANGLE, PROP_NAME, PROP_SIZE, QUADRANT_RIGHT, WKB_LINESTRING, WKB_NOGEOM, WKB_POINT)
from .rfd.alignment import format_station, landxml_crs, parse_landxml
from .rfd.catalogue import SIGNS_DIR, Catalogue, size_for_speed
from .rfd.legend import face_svg
from .rfd.records import (auto_facing, build_signlist, face_azimuth_deg, facing_from_rotation)

SVG_DIR = SIGNS_DIR

SIGN_FIELDS = [
    ("face_uuid", QVariant.String), ("install_uuid", QVariant.String), ("post_ref", QVariant.String),
    ("sign_code", QVariant.String), ("description", QVariant.String), ("size", QVariant.String),
    ("facing", QVariant.String), ("facing_auto", QVariant.Int), ("skew", QVariant.Double),
    ("post_type", QVariant.String), ("foundation", QVariant.String), ("remarks", QVariant.String),
    ("legend", QVariant.String), ("road_class", QVariant.String), ("mirror", QVariant.Int),
    ("size_auto", QVariant.Int),
    # derived - never typed by the user
    ("chainage", QVariant.String), ("chainage_m", QVariant.Double), ("station_int", QVariant.Double),
    ("offset_m", QVariant.Double), ("side", QVariant.String), ("face_az", QVariant.Double),
    ("speed_kmh", QVariant.Double), ("face_svg", QVariant.String),
    ("edge_ref", QVariant.String), ("edge_clear", QVariant.Double), ("grade_pct", QVariant.Double),
    ("status", QVariant.String), ("rule", QVariant.String), ("reason", QVariant.String),
    ("stack", QVariant.Int),
]
DERIVED = ("chainage", "chainage_m", "station_int", "offset_m", "side", "face_az", "facing", "description",
           "speed_kmh", "size", "face_svg", "edge_clear", "grade_pct")
TRIGGERS = ("sign_code", "facing", "facing_auto", "skew", "legend", "road_class", "mirror", "size_auto",
            "edge_ref")


def _fields(spec):
    fs = QgsFields()
    for n, t in spec:
        fs.append(QgsField(n, t))
    return fs


def _write_layer(path, name, fields, wkb, crs, first):
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = name
    opts.actionOnExistingFile = (FW_CREATE_FILE if first
                                 else FW_CREATE_LAYER)
    w = QgsVectorFileWriter.create(path, fields, wkb, crs, QgsCoordinateTransformContext(), opts)
    if w.hasError() != FW_NO_ERROR:
        raise RuntimeError(f"Cannot create {name} in {path}: {w.errorMessage()}")
    return w


class SignStore(QObject):
    changed = pyqtSignal()          # inventory-relevant change
    message = pyqtSignal(str, int)  # text, level (0 info, 1 warning, 2 critical)

    def __init__(self, gpkg, meta, cat=None):
        super().__init__()
        self.gpkg = gpkg
        self.meta = meta
        self.cat = cat or Catalogue.load()
        lx = meta["landxml"]
        if not os.path.isabs(lx):
            lx = os.path.normpath(os.path.join(os.path.dirname(gpkg), lx))
        self.landxml_path = lx
        als = [a for a in parse_landxml(lx) if a.name == meta["alignment"]]
        if not als:
            raise ValueError(f"Alignment '{meta['alignment']}' not found in {lx}")
        self.al = als[0]
        self.signs = QgsVectorLayer(f"{gpkg}|layername=rsd_signs", "RFD signs", "ogr")
        self.alignment_layer = QgsVectorLayer(f"{gpkg}|layername=rsd_alignment", "RFD alignment", "ogr")
        self.chainage_layer = QgsVectorLayer(f"{gpkg}|layername=rsd_chainage", "RFD chainage", "ogr")
        self.edges_layer = QgsVectorLayer(f"{gpkg}|layername=rsd_edges", "RFD road edges", "ogr")
        self.vcurve_layer = QgsVectorLayer(f"{gpkg}|layername=rsd_vcurves", "RFD vertical curves", "ogr")
        if not self.signs.isValid():
            raise ValueError(f"{gpkg} is not a Road Furniture Designer project (no rsd_signs layer)")
        self._busy = False
        self._migrate(self.signs)
        self._bind(self.signs)
        from .linestore import LineStore
        self.lines = LineStore(gpkg, self.al, crs=self.signs.crs())
        self.lines.changed.connect(self.changed.emit)
        from .junctionstore import JunctionStore
        self.junctions = JunctionStore(gpkg, self.al, crs=self.signs.crs(), others=self.other_alignments)
        self.junctions.changed.connect(self.changed.emit)

    @staticmethod
    def _migrate(layer):
        """Add fields introduced by newer plugin versions to an older project (data kept)."""
        have = {f.name() for f in layer.fields()}
        missing = [QgsField(n, t) for n, t in SIGN_FIELDS if n not in have]
        if missing:
            layer.dataProvider().addAttributes(missing)
            layer.updateFields()
        return len(missing)

    def _bind(self, layer):
        self.signs = layer
        layer.geometryChanged.connect(self._on_geometry_changed)
        layer.attributeValueChanged.connect(self._on_attribute_changed)
        layer.featureAdded.connect(self._on_feature_added)
        for sig in (layer.featureDeleted, layer.afterCommitChanges, layer.afterRollBack):
            sig.connect(self.changed.emit)
        self._idx = {n: layer.fields().indexOf(n) for n, _ in SIGN_FIELDS}

    # ------------------------------------------------------------------ create / open
    @classmethod
    def create(cls, gpkg, landxml, alignment_name, crs: QgsCoordinateReferenceSystem,
               project_name="", tick=100.0):
        al = [a for a in parse_landxml(landxml) if a.name == alignment_name][0]
        w = _write_layer(gpkg, "rsd_signs", _fields(SIGN_FIELDS), WKB_POINT, crs, True)
        del w
        w = _write_layer(gpkg, "rsd_alignment", _fields([("name", QVariant.String)]),
                         WKB_LINESTRING, crs, False)
        n = max(2, int(al.length / 1.0))
        pts = [QgsPointXY(*al.point_at(al.sta_start + al.length * k / n)[:2]) for k in range(n + 1)]
        f = QgsFeature(); f.setGeometry(QgsGeometry.fromPolylineXY(pts)); f.setAttributes([al.name])
        w.addFeature(f)
        del w
        w = _write_layer(gpkg, "rsd_chainage", _fields([("label", QVariant.String), ("az", QVariant.Double)]),
                         WKB_POINT, crs, False)
        s = math.ceil(al.sta_start / tick) * tick
        while s <= al.sta_end + 1e-6:
            x, y, h = al.point_at(s)
            f = QgsFeature(); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            f.setAttributes([format_station(al.display_station(s), 0), (90 - math.degrees(h)) % 360])
            w.addFeature(f)
            s += tick
        del w
        if al.edges:
            w = _write_layer(gpkg, "rsd_edges", _fields([("code", QVariant.String), ("side", QVariant.String)]),
                             WKB_LINESTRING, crs, False)
            for (code, side), pts in sorted(al.edges.data.items()):
                sg = -1.0 if side == "L" else 1.0
                run = []
                def flush():
                    if len(run) >= 2:
                        f = QgsFeature(); f.setGeometry(QgsGeometry.fromPolylineXY(run)); f.setAttributes([code, side])
                        w.addFeature(f)
                prev = None
                for sta, off in pts:
                    if sta < al.sta_start - 1e-6 or sta > al.sta_end + 1e-6:
                        continue
                    if prev is not None and sta - prev > al.edges._gap[(code, side)]:   # gap (daylight only in cut)
                        flush(); run = []
                    run.append(QgsPointXY(*al.point_at(sta, sg * off)[:2]))
                    prev = sta
                flush()
            del w
        if al.profile is not None and al.profile.curves:
            w = _write_layer(gpkg, "rsd_vcurves", _fields([
                ("kind", QVariant.String), ("chainage", QVariant.String), ("length_m", QVariant.Double),
                ("k_value", QVariant.Double), ("a_pct", QVariant.Double), ("grade_in", QVariant.Double),
                ("grade_out", QVariant.Double), ("label", QVariant.String)]), WKB_POINT, crs, False)
            for c in al.profile.curves:
                if not (al.sta_start - 1e-6 <= c.pvi_station <= al.sta_end + 1e-6):
                    continue
                f = QgsFeature(); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*al.point_at(c.pvi_station)[:2])))
                k = round(c.k, 1) if c.k is not None else None
                f.setAttributes([c.kind, format_station(al.display_station(c.pvi_station), 0), round(c.length, 1), k,
                                 round(c.a, 2), round(c.grade_in, 2), round(c.grade_out, 2),
                                 f"{c.kind.title()} K={k} L={c.length:.0f}"])
                w.addFeature(f)
            del w
        try:
            rel = os.path.relpath(landxml, os.path.dirname(gpkg))
        except ValueError:          # different drive on Windows
            rel = landxml
        lx_crs = landxml_crs(landxml)
        meta = {"landxml": rel, "alignment": alignment_name, "project": project_name,
                "schema": "rsd-gpkg/0.1", "crs_epsg": lx_crs.get("epsg", ""), "crs_name": lx_crs.get("name", ""),
                "crs_map_zone": lx_crs.get("map_zone", ""), "layer_crs": crs.authid()}
        w = _write_layer(gpkg, "rsd_meta", _fields([("key", QVariant.String), ("value", QVariant.String)]),
                         WKB_NOGEOM, crs, False)
        for k, v in meta.items():
            f = QgsFeature(); f.setAttributes([k, v]); w.addFeature(f)
        del w
        return cls(gpkg, meta)

    @classmethod
    def open(cls, gpkg):
        ml = QgsVectorLayer(f"{gpkg}|layername=rsd_meta", "meta", "ogr")
        if not ml.isValid():
            raise ValueError(f"{gpkg} is not a Road Furniture Designer project (no rsd_meta table)")
        meta = {f["key"]: f["value"] for f in ml.getFeatures()}
        return cls(gpkg, meta)

    def add_to_project(self, project=None):
        project = project or QgsProject.instance()
        root = project.layerTreeRoot()

        def existing(lyr):
            src = os.path.normcase(os.path.abspath(lyr.source().split("|")[0]))
            name = lyr.source().split("layername=")[-1]
            for l in project.mapLayers().values():
                s = l.source()
                if (l.providerType() == "ogr" and s.split("layername=")[-1] == name
                        and os.path.normcase(os.path.abspath(s.split("|")[0])) == src):
                    return l
            return None

        found = {k: existing(l) for k, l in (("s", self.signs), ("c", self.chainage_layer),
                                              ("a", self.alignment_layer))}
        ex = existing(self.lines.layer)
        if ex is not None and ex is not self.lines.layer:
            self.lines.bind(ex)
        for attr in ("edges_layer", "vcurve_layer"):
            lyr = getattr(self, attr)
            if lyr.isValid():
                ex = existing(lyr)
                if ex is not None:
                    setattr(self, attr, ex)
        if found["s"] is not None and found["s"] is not self.signs:
            self._migrate(found["s"])
            self._bind(found["s"])          # reopened QGIS project: adopt its layer, keep its style
        if found["c"] is not None:
            self.chainage_layer = found["c"]
        if found["a"] is not None:
            self.alignment_layer = found["a"]
        exj = existing(self.junctions.layer)
        if exj is not None and exj is not self.junctions.layer:
            self.junctions.bind(exj)
        grp = root.findGroup("Road Furniture Designer") or root.insertGroup(0, "Road Furniture Designer")
        if exj is None:                # projects made before the junction layer existed
            project.addMapLayer(self.junctions.layer, False)
            grp.insertLayer(1, self.junctions.layer)
            self.junctions.style()
        if ex is None:                 # projects made before the linear layer existed
            project.addMapLayer(self.lines.layer, False)
            grp.insertLayer(1, self.lines.layer)
            self.lines.style()
        if all(found.values()):
            self.style()               # re-point icon paths (plugin or project may have moved)
            return
        for lyr in (self.signs, self.lines.layer, self.vcurve_layer, self.chainage_layer, self.edges_layer,
                    self.alignment_layer):
            if lyr.isValid() and not project.mapLayer(lyr.id()):
                project.addMapLayer(lyr, False)
                grp.addLayer(lyr)
        self.style()

    def style(self):
        # alignment
        self.alignment_layer.setRenderer(QgsSingleSymbolRenderer(
            QgsLineSymbol.createSimple({"color": "0,150,200", "width": "0.6"})))
        # chainage ticks + labels
        tick = QgsMarkerSymbol.createSimple({"name": "line", "size": "4", "color": "0,150,200",
                                             "outline_color": "0,150,200", "outline_width": "0.4"})
        tick.symbolLayer(0).setDataDefinedProperty(PROP_ANGLE,
                                                   QgsProperty.fromExpression('"az" + 90'))
        self.chainage_layer.setRenderer(QgsSingleSymbolRenderer(tick))
        pal = QgsPalLayerSettings()
        pal.fieldName = "label"
        fmt = QgsTextFormat(); fmt.setSize(8); fmt.setColor(QColor(0, 110, 160))
        pal.setFormat(fmt)
        pal.placement = LABEL_OVER_POINT
        pal.xOffset, pal.yOffset = 0, -3
        self.chainage_layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        self.chainage_layer.setLabelsEnabled(True)
        if self.edges_layer.isValid():
            from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory
            cats = []
            looks = {"ETW": ("90,90,90", "0.35", "solid"), "EPS": ("130,130,130", "0.3", "dash"),
                     "Daylight": ("160,120,60", "0.25", "dot")}
            codes = self.al.edges.codes() if self.al.edges else []
            for code in codes:
                col, wid, style = looks.get(code, ("170,170,170", "0.2", "dot"))
                sym = QgsLineSymbol.createSimple({"color": col, "width": wid, "line_style": style})
                cats.append(QgsRendererCategory(code, sym, code))
            self.edges_layer.setRenderer(QgsCategorizedSymbolRenderer("code", cats))
            self.edges_layer.triggerRepaint()
        if self.vcurve_layer.isValid():
            from qgis.core import QgsRuleBasedRenderer
            crest = QgsMarkerSymbol.createSimple({"name": "triangle", "size": "3.2", "color": "200,60,40",
                                                  "outline_color": "255,255,255"})
            sag = QgsMarkerSymbol.createSimple({"name": "triangle", "size": "3.2", "color": "40,110,200",
                                                "outline_color": "255,255,255", "angle": "180"})
            root = QgsRuleBasedRenderer.Rule(None)
            for sym, expr, lab in ((crest, "\"kind\" = 'crest'", "Crest"), (sag, "\"kind\" = 'sag'", "Sag")):
                root.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, expr, lab))
            self.vcurve_layer.setRenderer(QgsRuleBasedRenderer(root))
            pal = QgsPalLayerSettings()
            pal.fieldName = "label"
            fmt = QgsTextFormat(); fmt.setSize(7); fmt.setColor(QColor(120, 40, 30))
            pal.setFormat(fmt)
            pal.placement = LABEL_OVER_POINT
            pal.yOffset = 3
            self.vcurve_layer.setLabeling(QgsVectorLayerSimpleLabeling(pal))
            self.vcurve_layer.setLabelsEnabled(True)
            self.vcurve_layer.triggerRepaint()
        # signs: icon at the post + arrow showing which way the face points
        svg = QgsSvgMarkerSymbolLayer(os.path.join(SVG_DIR, "P5.svg"), 7.0)
        svg_dir = SVG_DIR.replace("\\", "/")
        faces = (os.path.splitext(self.gpkg)[0] + "_faces").replace("\\", "/")
        mirrored = ",".join(f"'{c}'" for c, sd in self.cat.signs.items() if sd.mirror)
        svg.setDataDefinedProperty(PROP_NAME, QgsProperty.fromExpression(
            f"if(\"face_svg\" is not null, '{faces}/' || \"face_svg\", '{svg_dir}/' || \"sign_code\" || "
            f"if(\"mirror\" = 1 and \"sign_code\" in ({mirrored}), '_M', '') || '.svg')"))
        svg.setDataDefinedProperty(PROP_SIZE, QgsProperty.fromExpression(
            "if(\"face_svg\" is not null, 22, 7)"))     # legend faces are wide: draw them larger
        svg.setDataDefinedProperty(PROP_OFFSET, QgsProperty.fromExpression(
            "'0,' || to_string(-8.5 * coalesce(\"stack\", 0))"))   # faces on one post stack upwards
        arrow = QgsSimpleMarkerSymbolLayer(MARKER_ARROWHEAD, 3.0)
        arrow.setColor(QColor(30, 30, 30)); arrow.setStrokeColor(QColor(30, 30, 30))
        arrow.setOffset(QPointF(0, -5.2))
        arrow.setDataDefinedProperty(PROP_ANGLE, QgsProperty.fromField("face_az"))
        ring = QgsSimpleMarkerSymbolLayer(GEOM_CIRCLE, 10.0)
        ring.setColor(QColor(255, 140, 0, 60)); ring.setStrokeColor(QColor(255, 120, 0)); ring.setStrokeWidth(0.6)
        ring.setDataDefinedProperty(PROP_ENABLED, QgsProperty.fromExpression("\"status\" = 'proposed'"))
        sym = QgsMarkerSymbol([ring, arrow, svg])
        self.signs.setRenderer(QgsSingleSymbolRenderer(sym))
        pal = QgsPalLayerSettings()
        pal.fieldName = "post_ref"
        fmt = QgsTextFormat(); fmt.setSize(7); fmt.setColor(QColor(60, 60, 60))
        pal.setFormat(fmt)
        pal.placement = LABEL_OVER_POINT
        pal.quadOffset = QUADRANT_RIGHT
        pal.xOffset = 4.5
        self.signs.setLabeling(QgsVectorLayerSimpleLabeling(pal))
        self.signs.setLabelsEnabled(True)
        for l in (self.signs, self.alignment_layer, self.chainage_layer):
            l.triggerRepaint()

    # ------------------------------------------------------------------ geometry helpers
    def locate(self, x, y):
        """(station_internal, display_station, signed_offset, side, in_range)."""
        so = self.al.station_offset(x, y)
        side = "R" if so.offset >= 0 else "L"
        return so.station, self.al.display_station(so.station), so.offset, side, so.in_range

    def faces_dir(self):
        d = os.path.splitext(self.gpkg)[0] + "_faces"
        os.makedirs(d, exist_ok=True)
        return d

    def crs_info(self):
        info = {"epsg": self.meta.get("crs_epsg", ""), "name": self.meta.get("crs_name", ""),
                "map_zone": self.meta.get("crs_map_zone", "")}
        if not info["epsg"]:
            try:
                info.update({k: v for k, v in landxml_crs(self.landxml_path).items() if v})
            # LandXML moved or unreadable: the CRS stays as stored.
            except Exception:  # nosec B110
                pass
        return info

    def default_edge_ref(self):
        return self.al.edges.reference() if self.al.edges else None

    def edge_info(self, sta, side, edge_ref=None):
        """(ref code, ref edge offset) at a station/side, or (None, None)."""
        if not self.al.edges:
            return None, None
        ref = edge_ref or self.default_edge_ref()
        o = self.al.edges.offset(ref, side, sta) if ref else None
        return (ref, o) if o is not None else (None, None)

    def derived(self, x, y, facing, facing_auto, skew, code, size=None, size_auto=0,
                legend="", road_class="", face_uuid="", edge_ref=None):
        sta, disp, off, side, in_range = self.locate(x, y)
        if facing_auto:
            facing = auto_facing(side)
        _, _, h = self.al.point_at(sta)
        sd = self.cat.signs.get(code)
        kmh = self.al.speed_at(sta)
        out = {
            "chainage": format_station(disp), "chainage_m": round(disp, 3),
            "station_int": round(sta, 4), "offset_m": round(abs(off), 3), "side": side,
            "facing": facing, "face_az": round(face_azimuth_deg(h, facing, skew or 0.0), 2),
            "description": sd.name if sd else "", "speed_kmh": kmh,
            "grade_pct": (round(self.al.profile.grade(sta), 2)
                          if self.al.profile is not None and self.al.profile.grade(sta) is not None else None),
        }
        ref, ro = self.edge_info(sta, side, edge_ref)
        out["edge_clear"] = round(abs(off) - ro, 3) if ro is not None else None
        if sd is not None and size_auto:
            auto = size_for_speed(sd.size_rule, kmh)
            if auto:
                out["size"] = auto
        # legend-driven face (directional signs, text plates)
        svg = face_svg(sd, legend, road_class or "A") if sd is not None else None
        if svg and face_uuid:
            with open(os.path.join(self.faces_dir(), face_uuid + ".svg"), "w", encoding="utf-8") as fh:
                fh.write(svg)
            out["face_svg"] = face_uuid + ".svg"      # file name only; folder sits next to the GeoPackage
        else:
            out["face_svg"] = None
        return out, in_range

    def next_post_ref(self):
        mx = 0
        for f in self.signs.getFeatures():
            r = f["post_ref"] or ""
            if r.startswith("P") and r[1:].isdigit():
                mx = max(mx, int(r[1:]))
        return f"P{mx + 1:03d}"

    def nearest_post(self, x, y, tol):
        best = None
        for f in self.signs.getFeatures():
            p = f.geometry().asPoint()
            d = math.hypot(p.x() - x, p.y() - y)
            if d <= tol and (best is None or d < best[0]):
                best = (d, f)
        return best[1] if best else None

    # ------------------------------------------------------------------ placement
    def add_sign(self, x, y, code, size=None, facing="Auto", skew=0.0, lock_offset=None,
                 attach_tol=None, remarks="", legend="", road_class="", mirror=False, edge_ref=None,
                 restrict=False, status=None, rule=None, reason=None):
        """Place one sign face at a map click (layer CRS). Returns (fid, info dict)."""
        sd = self.cat.signs[code]
        size_auto = 1 if (size in (None, "", "Auto") and sd.size_rule) else 0
        if size in (None, "", "Auto"):
            size = sd.default_size
        post_ref, install_uuid, post_type, fdn = None, None, self.cat.defaults["post"], self.cat.defaults["foundation"]
        stack = 0
        if attach_tol:
            host = self.nearest_post(x, y, attach_tol)
            if host is not None:
                p = host.geometry().asPoint()
                x, y = p.x(), p.y()
                post_ref, install_uuid = host["post_ref"], host["install_uuid"]
                post_type, fdn = host["post_type"], host["foundation"]
                req = QgsFeatureRequest().setFilterExpression(f"\"install_uuid\" = '{install_uuid}'")
                stack = sum(1 for _ in self.signs.getFeatures(req))
        if install_uuid is None:
            sta, _, off, side, in_range = self.locate(x, y)
            if not in_range:
                raise ValueError("Click is beyond the ends of the alignment")
            total = abs(off)
            if lock_offset is not None:
                _, ro = self.edge_info(sta, side, edge_ref)
                total = abs(lock_offset) + (ro or 0.0)          # offset measured from the chosen edge
            if restrict and self.al.edges:
                from .rfd.corridor import clamp_offset
                total, _note = clamp_offset(self.al.edges, side, sta, total, edge_ref or self.default_edge_ref())
            if lock_offset is not None or restrict:
                x, y, _ = self.al.point_at(sta, total * (1 if side == "R" else -1))
            post_ref, install_uuid = self.next_post_ref(), str(uuid.uuid4())
        fa = 1 if facing == "Auto" else 0
        fu = str(uuid.uuid4())
        edge_ref = edge_ref or self.default_edge_ref()
        der, in_range = self.derived(x, y, facing if not fa else "Forward", fa, skew, code, size,
                                     size_auto, legend, road_class, fu, edge_ref)
        vals = {"face_uuid": fu, "install_uuid": install_uuid, "post_ref": post_ref,
                "sign_code": code, "size": size, "facing_auto": fa, "skew": float(skew),
                "post_type": post_type, "foundation": fdn, "remarks": remarks,
                "legend": legend or None, "road_class": road_class or None,
                "mirror": 1 if (mirror and sd.mirror) else 0, "size_auto": size_auto,
                "edge_ref": edge_ref, "status": status, "rule": rule, "reason": reason, "stack": stack}
        vals.update(der)
        f = QgsFeature(self.signs.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        for k, v in vals.items():
            f[k] = v
        self._busy = True
        try:
            if self.signs.isEditable():
                self.signs.addFeature(f)
                fid = f.id()
            else:
                ok, out = self.signs.dataProvider().addFeatures([f])
                if not ok:
                    raise RuntimeError("Could not write sign to GeoPackage")
                fid = out[0].id()
                self.signs.reload()
        finally:
            self._busy = False
        self.signs.triggerRepaint()
        self.changed.emit()
        return fid, vals

    # ------------------------------------------------------------------ live recompute
    def _apply(self, fid, values):
        """Write derived values to a feature, via the edit buffer if editing."""
        self._busy = True
        try:
            if self.signs.isEditable():
                for k, v in values.items():
                    self.signs.changeAttributeValue(fid, self._idx[k], v)
            else:
                self.signs.dataProvider().changeAttributeValues(
                    {fid: {self._idx[k]: v for k, v in values.items()}})
        finally:
            self._busy = False

    def recompute(self, fid, geom=None):
        f = self.signs.getFeature(fid)
        if not f.isValid():
            return
        p = (geom or f.geometry()).asPoint()
        der, in_range = self.derived(p.x(), p.y(), f["facing"] or "Forward",
                                     int(f["facing_auto"] or 0), f["skew"] or 0.0, f["sign_code"],
                                     f["size"], int(f["size_auto"] or 0), f["legend"] or "",
                                     f["road_class"] or "", f["face_uuid"] or "", f["edge_ref"] or None)
        if not in_range:
            self.message.emit(f"{f['post_ref']} {f['sign_code']} is beyond the alignment ends", 1)
        changes = {k: v for k, v in der.items() if f[k] != v}
        if changes:
            self._apply(fid, changes)

    def _on_geometry_changed(self, fid, geom):
        if self._busy:
            return
        self.recompute(fid, geom)
        # keep every face on the same post together
        f = self.signs.getFeature(fid)
        iu = f["install_uuid"]
        if iu:
            p = geom.asPoint()
            req = QgsFeatureRequest().setFilterExpression(f"\"install_uuid\" = '{iu}'")
            sibs = [s.id() for s in self.signs.getFeatures(req) if s.id() != fid]
            self._busy = True
            try:
                for sid in sibs:
                    self.signs.changeGeometry(sid, QgsGeometry.fromPointXY(p))
            finally:
                self._busy = False
            for sid in sibs:
                self.recompute(sid, QgsGeometry.fromPointXY(p))
        self.changed.emit()

    def _on_attribute_changed(self, fid, idx, value):
        if self._busy:
            return
        name = self.signs.fields().at(idx).name()
        if name == "size":         # a hand-typed size switches auto sizing off
            self._apply(fid, {"size_auto": 0})
        if name in TRIGGERS:
            if name == "facing":   # a hand-picked facing switches auto off
                self._apply(fid, {"facing_auto": 0})
            self.recompute(fid)
        self.changed.emit()

    def _on_feature_added(self, fid):
        if self._busy:
            return
        # feature digitised with QGIS's own tools (or pasted): fill in the blanks
        f = self.signs.getFeature(fid)
        fill = {}
        if not f["face_uuid"]:
            fill["face_uuid"] = str(uuid.uuid4())
        if not f["install_uuid"]:
            fill["install_uuid"] = str(uuid.uuid4())
            fill["post_ref"] = self.next_post_ref()
        if f["facing_auto"] in (None, ""):
            fill["facing_auto"] = 1
        if f["mirror"] in (None, ""):
            fill["mirror"] = 0
        for k, d in (("post_type", "post"), ("foundation", "foundation")):
            if not f[k]:
                fill[k] = self.cat.defaults[d]
        if fill:
            self._apply(fid, fill)
        if f.hasGeometry():
            self.recompute(fid)
        self.changed.emit()

    def set_fields(self, fid, values):
        """User edits from the dock (legend, class, ...): write and recompute derived fields."""
        self._apply(fid, values)
        if not self.signs.isEditable():
            self.signs.reload()
        self.recompute(fid)
        if not self.signs.isEditable():
            self.signs.reload()
        self.signs.triggerRepaint()
        self.changed.emit()

    def renumber_posts(self, prefix="P"):
        """Renumber post refs P001.. in chainage order (left before right at equal chainage)."""
        posts = {}
        for f in self.signs.getFeatures():
            k = f["install_uuid"]
            key = (f["station_int"] or 0.0, 0 if f["side"] == "L" else 1)
            posts[k] = min(posts.get(k, key), key)
        order = sorted(posts, key=lambda k: posts[k])
        new = {k: f"{prefix}{i:03d}" for i, k in enumerate(order, start=1)}
        changes = {f.id(): {self._idx["post_ref"]: new[f["install_uuid"]]}
                   for f in self.signs.getFeatures() if f["post_ref"] != new[f["install_uuid"]]}
        if changes:
            self._busy = True
            try:
                if self.signs.isEditable():
                    for fid, m in changes.items():
                        for i, v in m.items():
                            self.signs.changeAttributeValue(fid, i, v)
                else:
                    self.signs.dataProvider().changeAttributeValues(changes)
                    self.signs.reload()
            finally:
                self._busy = False
            self.signs.triggerRepaint()
        self.changed.emit()
        return len(order)

    def recompute_all(self):
        for f in self.signs.getFeatures():
            self.recompute(f.id())
        self.lines.recompute_all()
        self.junctions.recompute_all()
        self.changed.emit()

    # ------------------------------------------------------------------ inventory / exports
    def records(self):
        out = []
        for f in self.signs.getFeatures():
            out.append({
                "ref": f.id(), "post_ref": f["post_ref"], "station_internal": f["station_int"],
                "offset": f["offset_m"], "side": f["side"], "facing": f["facing"],
                "code": f["sign_code"], "size": f["size"], "post_type": f["post_type"],
                "foundation": f["foundation"], "skew": f["skew"], "remarks": f["remarks"],
                "face_uuid": f["face_uuid"], "install_uuid": f["install_uuid"],
                "mirror": f["mirror"], "legend": f["legend"] or "", "road_class": f["road_class"] or "",
                "edge_ref": f["edge_ref"] or "", "status": f["status"] or "", "rule": f["rule"] or ""})
        return out

    def signlist(self, include_proposed=True):
        recs = self.records()
        if not include_proposed:
            recs = [r for r in recs if r["status"] != "proposed"]
        return build_signlist(recs, self.al, self.cat)

    # ------------------------------------------------------------------ auto placement
    def proposals(self):
        return [f for f in self.signs.getFeatures() if f["status"] == "proposed"]

    def remove_proposals(self, rule_prefix=None, keep_prefix=None):
        ids = [f.id() for f in self.proposals()
               if (rule_prefix is None or (f["rule"] or "").startswith(rule_prefix))
               and not (keep_prefix and (f["rule"] or "").startswith(tuple(keep_prefix) if isinstance(keep_prefix, (list, tuple)) else keep_prefix))]
        if ids:
            if self.signs.isEditable():
                self.signs.deleteFeatures(ids)
            else:
                self.signs.dataProvider().deleteFeatures(ids)
                self.signs.reload()
        self.signs.triggerRepaint()
        self.changed.emit()
        return len(ids)

    def accept_proposals(self, fids=None):
        fids = fids or [f.id() for f in self.proposals()]
        idx = self._idx["status"]
        if self.signs.isEditable():
            for fid in fids:
                self.signs.changeAttributeValue(fid, idx, "approved")
        else:
            self.signs.dataProvider().changeAttributeValues({fid: {idx: "approved"} for fid in fids})
            self.signs.reload()
        self.signs.triggerRepaint()
        self.changed.emit()
        return len(fids)

    def auto_propose(self, cfg=None, restrict=True):
        """Run the RDM rules and add the results as proposed signs (previous proposals replaced)."""
        from .rfd.autoplace import AutoConfig, propose, space_out
        cfg = cfg or AutoConfig()
        self.remove_proposals(keep_prefix=("feature:", "speed:", "junction:"))   # features, speed zones and junctions keep their signs
        props, findings = propose(self.al, cfg)
        existing = [(f["station_int"], f["side"], f["facing"], f["sign_code"]) for f in self.signs.getFeatures()]
        props = space_out(props, existing, self.al.speed_at)
        added = self.place_proposals(props, cfg, restrict)
        self.last_findings = findings
        self.changed.emit()
        return added, findings

    def place_proposals(self, props, cfg=None, restrict=True):
        """Add sign proposals (autoplace.Proposal) at the reference edge plus the clearance."""
        from .rfd.autoplace import AutoConfig
        cfg = cfg or AutoConfig()
        ref = cfg.edge_ref or self.default_edge_ref()
        hosts = {}
        added = 0
        for p in props:
            sg = 1 if p.side == "R" else -1
            ro = self.al.edges.offset(ref, p.side, p.station) if (self.al.edges and ref) else None
            off = (ro + cfg.clearance) if ro is not None else cfg.offset_no_edges
            x, y, _ = self.al.point_at(p.station, sg * off)
            attach = None
            if p.group and p.group in hosts:
                x, y = hosts[p.group]
                attach = 0.05
            try:
                fid, _v = self.add_sign(x, y, p.code, facing=p.facing, mirror=p.mirror, legend=p.legend,
                                        edge_ref=ref, restrict=restrict and attach is None, attach_tol=attach,
                                        status="proposed", rule=p.rule, reason=p.reason)
            except ValueError:
                continue
            if p.group and p.group not in hosts:
                pt = self.signs.getFeature(fid).geometry().asPoint()
                hosts[p.group] = (pt.x(), pt.y())
            added += 1
        return added

    # ------------------------------------------------------------------ traffic calming features
    def add_feature(self, kind, station, cfg=None, auto=None):
        """Design a hump / table / bump / bar markings / crossing at a station and add its runs and signs."""
        from .rfd.features import design_feature
        d = design_feature(self.al, kind, station, cfg)
        if d.runs:
            self.lines.add_runs(d.runs)
        if d.signs:
            self.place_proposals(d.signs, auto)
        self.changed.emit()
        return d

    def features(self):
        """{group id: (kind summary, station, n runs, n signs)} of the features in the project."""
        out = {}
        for f in self.lines.layer.getFeatures():
            r = f["rule"] or ""
            if r.startswith("feature:"):
                g = out.setdefault(r[8:], {"runs": 0, "signs": 0, "station": f["sta_from"], "codes": []})
                g["runs"] += 1
                g["station"] = min(g["station"], f["sta_from"])
                g["codes"].append(f["item_code"])
        for f in self.signs.getFeatures():
            r = f["rule"] or ""
            if r.startswith("feature:"):
                g = out.setdefault(r[8:], {"runs": 0, "signs": 0, "station": f["station_int"], "codes": []})
                g["signs"] += 1
        return out

    # ------------------------------------------------------------------ speed limit zones (RDM 6.2 3.5)
    def _sign_dicts(self):
        return [{"sta": f["station_int"] or 0.0, "code": f["sign_code"], "facing": f["facing"], "side": f["side"],
                 "status": f["status"] or "", "rule": f["rule"] or "", "fid": f.id()} for f in self.signs.getFeatures()]

    def speed_zones(self):
        """Zones in the project: [{id, limit, start, end, signs, status}] by chainage."""
        from .rfd.speedzones import zones_from_signs
        return zones_from_signs(self._sign_dicts(), self.al)

    def add_speed_zone(self, limit, start, end, auto=None, repeat=None):
        """Sign a speed limit zone: limit signs at the start (both directions), repeaters, P9 at the end.

        Where the new zone adjoins an existing one, that zone's P9 at the shared boundary is removed: the
        new zone's limit sign marks the change."""
        from .rfd.speedzones import END_SIGN, SpeedZone, design_zone
        zone = SpeedZone(start, end, limit)
        others = [SpeedZone(z["start"], z["end"], z["limit"], id=z["id"]) for z in self.speed_zones() if z["limit"]]
        d = design_zone(self.al, zone, repeat=repeat, neighbours=others)
        stale = [s["fid"] for s in self._sign_dicts() if s["rule"].startswith("speed:") and s["code"] == END_SIGN
                 and min(abs(s["sta"] - zone.start), abs(s["sta"] - zone.end)) < 1.0]
        self._delete_signs(stale)
        if d.signs:
            self.place_proposals(d.signs, auto)
        self.changed.emit()
        return d

    def remove_speed_zone(self, zid):
        n = self._delete_signs([s["fid"] for s in self._sign_dicts() if s["rule"] == f"speed:{zid}"])
        self.changed.emit()
        return n

    def _delete_signs(self, fids):
        if not fids:
            return 0
        if self.signs.isEditable():
            self.signs.deleteFeatures(fids)
        else:
            self.signs.dataProvider().deleteFeatures(fids)
            self.signs.reload()
        self.signs.triggerRepaint()
        return len(fids)

    def remove_feature(self, group):
        rule = f"feature:{group}"
        lid = [f.id() for f in self.lines.layer.getFeatures() if f["rule"] == rule]
        sid = [f.id() for f in self.signs.getFeatures() if f["rule"] == rule]
        self.lines._set_status_or_delete(lid)
        if sid:
            if self.signs.isEditable():
                self.signs.deleteFeatures(sid)
            else:
                self.signs.dataProvider().deleteFeatures(sid)
                self.signs.reload()
        self.changed.emit()
        return len(lid) + len(sid)

    def summary(self):
        """Live counts for the dock: [(group, item, description, size, count)], issues."""
        sl = self.signlist()
        faces, posts, fdns = {}, {}, {}
        for f in sl.faces:
            k = (f.code, f.size)
            faces[k] = faces.get(k, 0) + 1
        for i in sl.installations:
            posts[i.post_type] = posts.get(i.post_type, 0) + 1
            fdns[i.foundation] = fdns.get(i.foundation, 0) + 1
        rows = [("Sign face", c, self.cat.signs[c].name, s, n) for (c, s), n in sorted(faces.items())]
        rows += [("Post", p, self.cat.posts[p]["description"], "", n) for p, n in sorted(posts.items())]
        rows += [("Foundation", p, self.cat.foundations[p]["description"], "", n) for p, n in sorted(fdns.items())]
        for catg, code, desc, pat, unit, q in self.lines.summary():
            rows.append((catg, code, desc, pat, f"{q:g} {unit}"))
        return rows, sl

    def export_inventory(self, xlsx_path):
        from .rfd.inventory import write_inventory
        sl = self.signlist(include_proposed=False)
        write_inventory(xlsx_path, sl, self.cat, self.meta.get("project", ""),
                        csv_path=os.path.splitext(xlsx_path)[0] + ".csv",
                        linear=(self.lines.runs(include_proposed=False), self.lines.cat, self.al))
        return sl

    def set_meta(self, **values):
        """Update project details (e.g. prepared_by / checked_by / approved_by) in the rsd_meta table."""
        ml = QgsVectorLayer(f"{self.gpkg}|layername=rsd_meta", "meta", "ogr")
        if not ml.isValid():
            return
        have = {f["key"]: f.id() for f in ml.getFeatures()}
        ml.startEditing()
        for k, v in values.items():
            v = "" if v is None else str(v)
            self.meta[k] = v
            if k in have:
                ml.changeAttributeValue(have[k], ml.fields().indexOf("value"), v)
            else:
                f = QgsFeature(ml.fields()); f.setAttributes([None, k, v] if ml.fields().count() == 3 else [k, v])
                ml.addFeature(f)
        ml.commitChanges()

    def add_junction(self, pl, kit, piece="", guides=True, params=None, splays=True, splay=None):
        """Place junction pieces or a bay; where our road is the minor road, also propose its R2 Give
        Way; a bus bay proposes its bus stop sign, a truck parking bay I15 and I14, a climbing lane I1 / I2.
        Returns (pieces, findings, signs proposed)."""
        from .rfd import junctions as J
        n, finds = self.junctions.add(pl, kit, piece, guides, params, splays, splay)
        signs = 0
        if pl.role == "bay":
            j = next((x for x in self.junctions.junctions() if x["id"] == pl.junction_id), None)
            if j and j["bay"]:
                b = j["bay"]
                s0, s1, s2, _s3 = b["stations"]
                kind = b.get("kind")
                lane = kind == "climbing lane"
                if lane:
                    todo = [("WSCM-I1", s0, "Start of climbing lane at the entry taper (RDM/1/3/3/02)", 0.0),
                            ("WSCM-I2", s2, "End of climbing lane where the exit taper starts (RDM/1/3/3/02)", b["depth"])]
                elif kind == "truck parking bay":
                    back = s0 - (s1 - s0) / abs(s1 - s0) * self.TRUCK_I14_AHEAD
                    todo = [("I15", s0, "Lay-by at the start of the entry taper, facing oncoming traffic "
                                        "(RDM 6.2 6.4.1.1)", 0.0)]
                    if self.al.sta_start <= back <= self.al.sta_end:
                        todo.append(("I14", back, f"Lay-by ahead, {self.TRUCK_I14_AHEAD:.0f} m before the bay; "
                                                  "RDM 6.2 6.4.1.1 allows up to 500 m", 0.0))
                else:
                    todo = [("WSCM-I3", s1, "Bus stop at the start of the bay (WSCM/84/2/01; not in RDM 6.2)",
                             b["depth"])]
                for code, at, why, wide in todo:
                    off = (self.al.edges.offset("ETW", b["side"], at) if self.al.edges else None) or 3.5
                    off += wide + 1.5
                    x, y, _ = self.al.point_at(at, off if b["side"] == "R" else -off)
                    try:
                        self.add_sign(x, y, code, facing="Forward" if b["side"] == "L" else "Backward",
                                      status="proposed", rule=f"junction:{pl.junction_id}", reason=why)
                        signs += 1
                    except ValueError:
                        pass
        if pl.role == "roundabout":
            signs += self._roundabout_signs(pl)
        if pl.role == "minor" and (not piece or piece in ("give_way_line", "give_way_triangle")):
            for sg in J.minor_signs(self.al, pl, self.junctions.main_of(pl)):
                x, y, _ = self.al.point_at(sg["station"], (5.0 if sg["side"] == "R" else -5.0))
                try:
                    self.add_sign(x, y, sg["code"], facing=sg["facing"], restrict=True, status="proposed",
                                  rule=f"junction:{pl.junction_id}",
                                  reason="Give Way on the minor approach (RDM 6.2, RDM 6.1 5.3)")
                    signs += 1
                except ValueError:
                    pass
        return n, finds, signs

    def check_sight(self, layer_ids):
        """Check the junction visibility splays against the given layers (ids) and remember them for the
        report. Returns (junctions with obstructions, obstructions)."""
        from qgis.core import QgsProject
        layers = [QgsProject.instance().mapLayer(i) for i in layer_ids]
        layers = [l for l in layers if l is not None and l.isValid()]
        self.set_meta(sight_layers=",".join(l.id() for l in layers))
        found = self.junctions.check_obstructions(layers)
        return len(found), sum(len(v) for v in found.values())

    def recheck_sight(self):
        """Re-run the splay check with the layers saved for this project (those still loaded)."""
        ids = [i for i in (self.meta.get("sight_layers") or "").split(",") if i]
        if ids:
            from qgis.core import QgsProject
            layers = [QgsProject.instance().mapLayer(i) for i in ids]
            self.junctions.check_obstructions([l for l in layers if l is not None and l.isValid()])

    def _sign_facing(self, x, y, phi):
        """(facing, skew) that point a sign face in the map direction phi (radians, counter-clockwise from
        east), whatever the road it stands by."""
        import math
        so = self.al.station_offset(x, y)
        h = self.al.point_at(min(max(so.station, self.al.sta_start), self.al.sta_end))[2]
        d = math.degrees(math.remainder(phi - (h + math.pi), 2 * math.pi))
        if abs(d) <= 90.0:
            return "Forward", round(d, 1)
        return "Backward", round(math.degrees(math.remainder(phi - h, 2 * math.pi)), 1)

    def _roundabout_signs(self, pl):
        """W17 on our approaches, R2 at every entry, M5 on every splitter nose, a W24 chevron on the central
        island facing every entry (RDM 6.2 4.4, 3.3, 4.6.1). All proposals with the roundabout's rule."""
        import math
        j = next((x for x in self.junctions.junctions() if x["id"] == pl.junction_id), None)
        if not j or not j.get("rbt"):
            return 0
        rule, n = f"junction:{pl.junction_id}", 0
        for d in j["rbt"]["detail"]:
            out = d["bearing"]                          # signs face outwards, towards the entering traffic
            todo = [("R2", d["give_way"], "Give way at the roundabout entry (RDM 6.2, RDM 6.1 Figure 7.14)"),
                    ("M5", d["nose"], "Keep left on the splitter island nose (RDM 6.2 3.3)"),
                    ("W24-b", d["island_face"], "Chevron on the central island facing the entry (RDM 6.2 4.6.1)")]
            if d["src"] == "ours" and d.get("station") is not None and d.get("advance"):
                inbound = 1 if d["station"] < pl.station else -1
                sta = d["station"] - inbound * d["advance"]
                if self.al.sta_start <= sta <= self.al.sta_end:
                    side = -1.0 if inbound > 0 else 1.0                       # the left of the approaching traffic
                    off = ((self.al.edges.offset("ETW", "L" if side < 0 else "R", sta) if self.al.edges else None)
                           or 3.5) + 1.5
                    x, y, _ = self.al.point_at(sta, side * off)
                    todo.append(("W17", (x, y), f"Roundabout ahead, {d['advance']:.0f} m before the entry at "
                                                f"{d['speed']:.0f} km/h (RDM 6.2 4.4)"))
            for code, (x, y), why in todo:
                if code == "W17":                           # on our road: faces the traffic coming in
                    facing, skew = ("Forward" if inbound > 0 else "Backward"), 0.0
                else:
                    facing, skew = self._sign_facing(x, y, out)
                try:
                    self.add_sign(x, y, code, facing=facing, skew=skew, status="proposed", rule=rule, reason=why)
                    n += 1
                except (ValueError, KeyError):
                    pass
        return n

    TRUCK_I14_AHEAD = 300.0                 # m before the entry taper (RDM 6.2 6.4.1.1: up to 500 m)

    def propose_climbing_lanes(self, aadt=None):
        """Climbing lanes the profile asks for (RDM 1.3 6.6), placed as proposals. Returns (lanes, notes)."""
        from .rfd import junctions as J
        n, notes = 0, []
        for c in J.climbing_lanes(self.al, aadt):
            pl, L = J.place_lane(self.al, c["start"], c["end"], c["side"])
            self.add_junction(pl, "CLIMB", params={"bay": L})
            n += 1
            notes.append(f"{c['grade']:+.1f} % over {c['length']:.0f} m (limit {c['limit']:.0f} m), "
                         f"{'left' if c['side'] == 'L' else 'right'}: {c['note']}")
        return n, notes

    def remove_junction(self, junction_id):
        """Remove a junction's pieces and the signs proposed with it."""
        rule = f"junction:{junction_id}"
        ids = [f.id() for f in self.signs.getFeatures() if f["rule"] == rule]
        if ids:
            if self.signs.isEditable():
                self.signs.deleteFeatures(ids)
            else:
                self.signs.dataProvider().deleteFeatures(ids)
                self.signs.reload()
            self.signs.triggerRepaint()
        return self.junctions.remove(junction_id) + len(ids)

    def other_alignments(self):
        """The LandXML's other alignments (side roads, link roads) for reference in drawings and sheets."""
        try:
            return [a for a in parse_landxml(self.landxml_path) if a.name != self.al.name]
        except Exception:
            return []

    def export_civil3d(self, json_path, dxf_path=None, plan_scale=2500.0):
        from .rfd.package import build_package, write_package
        sl = self.signlist(include_proposed=False)
        if not sl.ok:
            raise ValueError("Fix the errors in the Checks list before exporting to Civil 3D")
        write_package(json_path, build_package(sl, self.al, self.cat, self.meta.get("project", ""), self.crs_info()))
        if dxf_path:
            from .rfd.dxf_out import write_dxf
            write_dxf(dxf_path, sl, self.al, self.cat, plan_scale=plan_scale, crs=self.crs_info(),
                      source=self.landxml_path, others=self.other_alignments(),
                      linear=(self.lines.runs(include_proposed=False), self.lines.cat),
                      junctions=self.junctions.parts())
        return sl

    def import_readback(self, json_path):
        """Apply sign moves / rotations made in Civil 3D (matched by face UUID)."""
        with open(json_path, encoding="utf-8") as fh:
            rb = json.load(fh)
        by_uuid = {f["face_uuid"]: f for f in self.signs.getFeatures()}
        moved, notes, seen = 0, [], set()
        was_editing = self.signs.isEditable()
        if not was_editing:
            self.signs.startEditing()
        for s in rb["signs"]:
            seen.add(s["face_uuid"])
            f = by_uuid.get(s["face_uuid"])
            if f is None:
                notes.append(f"Drawing block {s['face_uuid'][:8]} ({s.get('block_name')}) has no sign in QGIS")
                continue
            p = f.geometry().asPoint()
            sta, _, _, _, in_range = self.locate(s["x"], s["y"])
            if not in_range:
                notes.append(f"{f['post_ref']} {f['sign_code']}: moved beyond the alignment - skipped")
                continue
            _, _, h = self.al.point_at(sta)
            facing, skew = facing_from_rotation(s["rotation_deg"], h)
            changed = False
            if math.hypot(p.x() - s["x"], p.y() - s["y"]) > 0.02:
                self._busy = True
                self.signs.changeGeometry(f.id(), QgsGeometry.fromPointXY(QgsPointXY(s["x"], s["y"])))
                self._busy = False
                changed = True
            if facing != f["facing"] or abs((f["skew"] or 0) - skew) >= 1.0:
                self._apply(f.id(), {"facing": facing, "facing_auto": 0,
                                     "skew": skew if abs(skew) >= 1.0 else 0.0})
                changed = True
            if changed:
                self.recompute(f.id())
                moved += 1
        for u, f in by_uuid.items():
            if u not in seen:
                notes.append(f"{f['post_ref']} {f['sign_code']} is not in the drawing (deleted there, or not yet placed)")
        if not was_editing:
            self.signs.commitChanges()
        self.changed.emit()
        return moved, notes
