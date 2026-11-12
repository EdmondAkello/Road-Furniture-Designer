"""JunctionStore: junction islands and markings placed from templates (layer rsd_junctions).

A placement (junction point station, minor road bearing, scale) builds one or more
pieces; each piece is written as one feature per marking code (kerb outline, hatching,
border, give way line, guide lines ...), all sharing the piece's uuid and the rule
junction:<junction id>. Editing sta, bearing_deg or scale of any of them rebuilds the
whole piece from the template; the geometry is never edited by hand.
"""
from __future__ import annotations

import json
import math
import uuid as _uuid

from qgis.PyQt.QtCore import QObject, QVariant, pyqtSignal
from qgis.core import (QgsCategorizedSymbolRenderer, QgsFeature, QgsFields, QgsGeometry, QgsLineSymbol, QgsPointXY,
                       QgsRendererCategory, QgsVectorLayer)

from .compat import WKB_MULTILINESTRING, make_field
from .rfd import junctions as J
from .rfd.alignment import format_station

LAYER = "rsd_junctions"
FIELDS = [
    ("piece_uuid", QVariant.String), ("junction_id", QVariant.String), ("kit", QVariant.String),
    ("piece", QVariant.String), ("corner", QVariant.String), ("code", QVariant.String),
    ("sta", QVariant.Double), ("bearing_deg", QVariant.Double), ("scale", QVariant.Double),
    ("edge_m", QVariant.Double), ("params", QVariant.String),
    ("role", QVariant.String), ("main_ref", QVariant.String), ("our_sta", QVariant.Double),
    ("status", QVariant.String), ("rule", QVariant.String), ("remarks", QVariant.String),
    # derived
    ("kind", QVariant.String), ("description", QVariant.String), ("ch", QVariant.String),
    ("side", QVariant.String), ("crossing_deg", QVariant.Double),
    ("kerb_m", QVariant.Double), ("island_m2", QVariant.Double), ("line_m", QVariant.Double),
    ("paint_m2", QVariant.Double), ("widen_m2", QVariant.Double), ("bay", QVariant.String),
    ("sight", QVariant.String), ("access", QVariant.String), ("rbt", QVariant.String),
]
TRIGGERS = ("sta", "bearing_deg", "scale", "edge_m")
NO_PAINT = ("KERB", "GUIDE", "BAYEDGE", "SPLAY-A", "SPLAY-S", "ACCESS", "ACCESS-P", "PIPE", "RBEDGE", "APRON")
STYLE = {   # code -> (colour, width mm, dashed)
    "KERB": ("40,40,40", 0.6, False), "GUIDE": ("120,120,120", 0.2, True),
    "HM07": ("230,180,0", 0.25, False), "HM14": ("230,180,0", 0.4, False), "LM24": ("230,180,0", 0.4, False),
    "HM04": ("70,110,170", 0.25, False), "LM27": ("70,110,170", 0.4, False),
    "TM07": ("70,110,170", 0.6, False), "BM07": ("70,110,170", 0.4, False),
    "AM03": ("70,110,170", 0.3, False), "AM06": ("70,110,170", 0.3, False), "AM07": ("70,110,170", 0.3, False),
    "LM05": ("70,110,170", 0.4, False), "LM26": ("70,110,170", 0.4, False), "LM03": ("70,110,170", 0.4, False), "BUSPLAT": ("90,90,90", 0.3, False), "BAYEDGE": ("40,40,40", 0.5, False),
    "SPLAY-A": ("40,150,60", 0.3, True), "SPLAY-S": ("200,40,40", 0.35, True),
    "RBEDGE": ("40,40,40", 0.6, False), "APRON": ("90,90,90", 0.4, True),
    "TM04": ("70,110,170", 0.4, True),
    "ACCESS": ("60,60,60", 0.5, False), "ACCESS-P": ("110,110,110", 0.25, False), "PIPE": ("40,90,200", 0.4, False), "SHELTER": ("120,120,120", 0.3, True),
}


def _fields():
    fs = QgsFields()
    for n, t in FIELDS:
        fs.append(make_field(n, t))
    return fs


class JunctionStore(QObject):
    changed = pyqtSignal()

    def __init__(self, gpkg, al, crs=None, others=None):
        super().__init__()
        self.gpkg, self.al = gpkg, al
        self._others_fn = others or (lambda: [])
        self._others = None
        self.templates = J.load_templates()
        self.layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", "RFD junctions", "ogr")
        if not self.layer.isValid():
            from .store import _write_layer
            w = _write_layer(gpkg, LAYER, _fields(), WKB_MULTILINESTRING, crs, False)
            del w
            self.layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", "RFD junctions", "ogr")
        have = {f.name() for f in self.layer.fields()}
        missing = [make_field(n, t) for n, t in FIELDS if n not in have]
        if missing:
            self.layer.dataProvider().addAttributes(missing)
            self.layer.updateFields()
        self._busy = False
        self.obstructions = {}          # junction_id -> splay obstructions found by check_obstructions()
        self.obstruction_layers = None  # names of the layers last checked (None: not checked)
        self.bind(self.layer)

    def bind(self, layer):
        self.layer = layer
        layer.attributeValueChanged.connect(self._on_attribute_changed)
        for sig in (layer.featureDeleted, layer.afterCommitChanges, layer.afterRollBack):
            sig.connect(self.changed.emit)

    # ------------------------------------------------------------------ build
    def others(self):
        """Other alignments of the LandXML (read once)."""
        if self._others is None:
            self._others = list(self._others_fn() or [])
        return self._others

    def main_of(self, pl: J.Placement):
        return J.main_alignment(self.al, pl, self.others())

    def _features(self, pl: J.Placement, kit: str, piece: str, corner: str, params: dict, puuid: str,
                  status="approved", remarks=""):
        main = self.main_of(pl)
        pc = J.build_piece(main, pl, piece, corner, params, self.templates)
        F = pl.frame(main)
        our = pl.our_station if pl.role == "minor" else pl.station
        by_code = {}
        for part in pc.parts:
            by_code.setdefault(part.code, []).append(part)
        codes = self.templates["codes"]
        out = []
        for i, (code, parts) in enumerate(by_code.items()):
            f = QgsFeature(self.layer.fields())
            f.setGeometry(QgsGeometry.fromMultiPolylineXY(
                [[QgsPointXY(x, y) for x, y in (p.pts + ([p.pts[0]] if p.closed else []))] for p in parts]))
            ln = sum(J.length(p.pts, p.closed) for p in parts)
            vals = {"piece_uuid": puuid, "junction_id": pl.junction_id, "kit": kit, "piece": piece,
                    "corner": corner, "code": code, "sta": round(pl.station, 3),
                    "bearing_deg": round(math.degrees(pl.bearing), 4), "scale": pl.scale,
                    "edge_m": pl.edge, "params": json.dumps(params or {}), "status": status,
                    "role": pl.role, "main_ref": pl.main_ref, "our_sta": round(our, 3),
                    "rule": f"junction:{pl.junction_id}", "remarks": remarks, "kind": pc.kind,
                    "description": f"{pc.name}: {codes[code]['name']}",
                    "ch": format_station(self.al.display_station(our), 1), "side": F.side,
                    "crossing_deg": round(F.crossing_angle, 1),
                    # piece quantities go on its first feature only, so sums over the layer are right
                    "kerb_m": pc.quantities.get("kerb_m") if code == "KERB" else None,
                    "island_m2": pc.quantities.get("island_m2") if code == "KERB" else None,
                    "line_m": round(ln, 2) if code not in NO_PAINT and not codes[code].get("fill") else None,
                    "paint_m2": (round(sum(J.area(p.pts) for p in parts), 3) if codes[code].get("fill")
                                 else round(ln * codes[code]["width"], 3)) if code not in NO_PAINT else None,
                    "widen_m2": pc.quantities.get("widen_m2") if code == next(iter(by_code)) else None,
                    "bay": json.dumps(dict({k: pc.params[k] for k in ("stations", "side", "entry", "exit", "depth", "kind")},
                                           taper=pc.params.get("taper")))
                    if piece in J.BAY_PIECES else None,
                    "sight": json.dumps({k: pc.params[k] for k in ("speed_used", "speed_assumed", "ref", "splays",
                                                                     "criteria_has")})
                    if piece == "splays" and code == next(iter(by_code), code) else None,
                    "access": json.dumps({k: pc.params[k] for k in ("width", "radius", "length", "notes", "quantities",
                                                                      "road_class")})
                    if piece == "access" and code == next(iter(by_code), code) else None,
                    "rbt": json.dumps({k: pc.params[k] for k in ("notes", "quantities", "n_arms", "arms_used", "island",
                                                                   "detail")})
                    if piece == "roundabout" and code == next(iter(by_code), code) else None}
            for n, x in vals.items():
                f.setAttribute(n, x)
            out.append(f)
        return out

    def _write(self, feats):
        if not feats:
            return
        self._busy = True
        try:
            if self.layer.isEditable():
                self.layer.addFeatures(feats)
            else:
                self.layer.dataProvider().addFeatures(feats)
                self.layer.reload()
        finally:
            self._busy = False
        self.layer.triggerRepaint()
        self.changed.emit()

    def add(self, pl: J.Placement, kit: str, piece: str = "", guides: bool = True, params: dict = None,
            splays: bool = True, splay: dict = None, second_leg: bool = False):
        """Place a whole kit (piece '') or one piece. splays: include the visibility splays; splay: their
        settings (main road speed, criteria); second_leg: the other approach of a crossroads (no main-road
        pieces again). Returns (pieces placed, findings)."""
        if piece:
            items = [{"piece": piece, "corner": "left_turn" if self.templates["pieces"][piece]["frame"] == "corner"
                      else ""}]
            # a lone piece takes the kit's own settings for it, if the kit uses it
            for it in self.templates["kits"].get(kit, []):
                if it["piece"] == piece:
                    items = [dict(it)]
                    break
        else:
            items = J.kit_items(self.templates, kit, guides, splays, second_leg)
        if params:
            for it in items:
                it["params"] = dict(it.get("params") or {}, **params)
        if pl.role == "minor" and pl.our_station is not None:
            # our road crossing the main road: the approach arrows also show straight ahead (AM07)
            crosses = len(J.minor_legs(self.al, pl.our_station, self.main_of(pl))) > 1
            for it in items:
                if it["piece"] == "approach_arrows":
                    it["params"] = dict(it.get("params") or {}, crossroads=crosses)
        if splay:
            for it in items:
                if it["piece"] == "splays":
                    it["params"] = dict(it.get("params") or {}, **{k: v for k, v in splay.items() if v})
        feats = []
        for it in items:
            feats += self._features(pl, kit, it["piece"], it.get("corner", ""), it.get("params") or {},
                                    _uuid.uuid4().hex)
        self._write(feats)
        return len(items), J.findings(self.main_of(pl), pl)

    def place(self, x0, y0, x1, y1, kit, piece="", scale=1.0, guides=True):
        return self.add(J.place(self.al, x0, y0, x1, y1, scale=scale), kit, piece, guides)

    def placement_minor(self, x0, y0, x1=None, y1=None, major="", scale=1.0, both=False):
        """Our road joins another road: the main road is the alignment named `major`, or the clicked direction.
        With an alignment, (x1, y1) picks our road's leg nearest the cursor. both: a list, one per leg."""
        m = next((a for a in self.others() if a.name == major), None) if major else None
        if major and m is None:
            raise ValueError(f"No alignment {major!r} in the LandXML")
        pl, _ = J.place_minor(self.al, x0, y0, x1, y1, major=m, scale=scale, both=both)
        return pl

    # ------------------------------------------------------------------ edit / rebuild
    def _group(self, puuid):
        return [f for f in self.layer.getFeatures() if f["piece_uuid"] == puuid]

    def _rebuild(self, puuid, override=None):
        group = self._group(puuid)
        if not group:
            return False
        f0 = group[0]
        v = {n: f0[n] for n in ("sta", "bearing_deg", "scale", "edge_m", "kit", "piece", "corner", "params",
                                "status", "remarks", "junction_id", "role", "main_ref", "our_sta")}
        v.update(override or {})

        def num(x, d=None):
            return d if x is None or (hasattr(x, "isNull") and x.isNull()) else float(x)
        pl = J.Placement(num(v["sta"]), math.radians(num(v["bearing_deg"])), num(v["scale"], 1.0),
                         num(v["edge_m"]), junction_id=v["junction_id"], role=v["role"] or "main",
                         main_ref=v["main_ref"] or "", our_station=num(v["our_sta"]))
        try:
            feats = self._features(pl, v["kit"], v["piece"], v["corner"] or "", json.loads(v["params"] or "{}"),
                                   puuid, v["status"] or "approved", v["remarks"] or "")
        except ValueError:
            return False
        ids = [f.id() for f in group]
        self._busy = True
        try:
            if self.layer.isEditable():
                self.layer.deleteFeatures(ids)
                self.layer.addFeatures(feats)
            else:
                self.layer.dataProvider().deleteFeatures(ids)
                self.layer.dataProvider().addFeatures(feats)
                self.layer.reload()
        finally:
            self._busy = False
        return True

    def _on_attribute_changed(self, fid, idx, value):
        if self._busy:
            return
        name = self.layer.fields().at(idx).name()
        if name in TRIGGERS:
            f = self.layer.getFeature(fid)
            self._rebuild(f["piece_uuid"], {name: value})
            self.changed.emit()

    def set_scale(self, junction_id, scale):
        """Rescale every piece of a junction about its junction point."""
        for pu in {f["piece_uuid"] for f in self.layer.getFeatures() if f["junction_id"] == junction_id}:
            self._rebuild(pu, {"scale": scale})
        self.layer.triggerRepaint()
        self.changed.emit()

    def recompute_all(self):
        for pu in {f["piece_uuid"] for f in self.layer.getFeatures()}:
            self._rebuild(pu)
        self.changed.emit()

    def remove(self, junction_id):
        ids = [f.id() for f in self.layer.getFeatures() if f["junction_id"] == junction_id]
        if ids:
            if self.layer.isEditable():
                self.layer.deleteFeatures(ids)
            else:
                self.layer.dataProvider().deleteFeatures(ids)
                self.layer.reload()
            self.layer.triggerRepaint()
            self.changed.emit()
        return len(ids)

    # ------------------------------------------------------------------ queries
    def junctions(self):
        """One dict per junction: id, kit, station, ch, side, crossing angle, scale, pieces, quantities."""
        out = {}
        for f in self.layer.getFeatures():
            j = out.setdefault(f["junction_id"], {
                "id": f["junction_id"], "kit": f["kit"], "ch": f["ch"], "side": f["side"],
                "sta": f["our_sta"] if f["role"] == "minor" and f["our_sta"] is not None else f["sta"],
                "role": f["role"] or "main", "main_ref": f["main_ref"] or "",
                "crossing_deg": f["crossing_deg"], "scale": f["scale"], "status": f["status"],
                "pieces": set(), "kerb_m": 0.0, "island_m2": 0.0, "widen_m2": 0.0, "paint": {}, "bay": None,
                "sight": None, "access": None, "rbt": None})
            if f["bay"]:
                j["bay"] = json.loads(f["bay"])
            if f["access"]:
                j["access"] = json.loads(f["access"])
            if f["rbt"]:
                j["rbt"] = json.loads(f["rbt"])
            if f["sight"]:
                j["sight"] = json.loads(f["sight"])
                j["sight"]["obstructions"] = self.obstructions.get(f["junction_id"], [])
                j["sight"]["checked"] = self.obstruction_layers
            j["pieces"].add(f["piece"])
            for k in ("kerb_m", "island_m2", "widen_m2"):
                x = f[k]
                if x is not None and not (hasattr(x, "isNull") and x.isNull()):
                    j[k] += float(x)
            if f["paint_m2"] is not None and not (hasattr(f["paint_m2"], "isNull") and f["paint_m2"].isNull()):
                p = j["paint"].setdefault(f["code"], [0.0, 0.0])
                p[0] += float(f["line_m"] or 0.0)
                p[1] += float(f["paint_m2"])
        return sorted(out.values(), key=lambda j: j["sta"] or 0.0)

    def warning_inputs(self):
        """One junctions.JunctionAt per placed junction kit, for the Junction Ahead warning signs."""
        seen = {}
        for f in self.layer.getFeatures():
            jid = f["junction_id"]
            if jid in seen or f["kit"] not in J.JUNCTION_KITS:
                continue
            role = f["role"] or "main"
            pl = J.Placement(float(f["sta"]), math.radians(float(f["bearing_deg"])), junction_id=jid, role=role,
                             main_ref=f["main_ref"] or "",
                             our_station=None if f["our_sta"] is None or (hasattr(f["our_sta"], "isNull")
                                                                          and f["our_sta"].isNull())
                             else float(f["our_sta"]))
            if role == "minor" and pl.our_station is not None:
                try:
                    main = self.main_of(pl)
                except ValueError:
                    continue
                _, _, h = self.al.point_at(pl.our_station)
                seen[jid] = J.JunctionAt(jid, "minor", pl.our_station, up=math.cos(pl.bearing - h) > 0,
                                         crossing=len(J.minor_legs(self.al, pl.our_station, main)) > 1,
                                         kit=f["kit"])
            elif role == "main":
                seen[jid] = J.JunctionAt(jid, "main", pl.station, side=f["side"] or "L", kit=f["kit"])
        return list(seen.values())

    FOOTPRINT_SKIP = ("GUIDE", "SPLAY-A", "SPLAY-S")

    def footprints(self, al=None, reach=15.0):
        """Chainage range on our road of each junction's islands and markings (or bay, roundabout), from
        the vertices within `reach` m of our centreline: [(lo, hi, junction id, kit)]. Guides and splays,
        which run well beyond the junction, don't count."""
        al = al or self.al
        rng = {}
        for f in self.layer.getFeatures():
            if f["code"] in self.FOOTPRINT_SKIP:
                continue
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            for v in g.vertices():
                so = al.station_offset(v.x(), v.y())
                if so.in_range and abs(so.offset) <= reach:
                    lo, hi, _ = rng.get(f["junction_id"], (so.station, so.station, f["kit"]))
                    rng[f["junction_id"]] = (min(lo, so.station), max(hi, so.station), f["kit"])
        return [(lo, hi, jid, kit) for jid, (lo, hi, kit) in rng.items()]

    def parts(self):
        """(code, [polyline]) for drawing: plan sheets and DXF."""
        out = []
        for f in self.layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            lines = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
            sta = f["our_sta"] if f["role"] == "minor" and f["our_sta"] is not None else f["sta"]
            out.append((f["code"], sta, [[(p.x(), p.y()) for p in ln] for ln in lines]))
        return out

    def check_obstructions(self, layers):
        """Features of the given vector layers (buildings, trees, fences ...) inside a visibility splay.
        Returns {junction_id: [{kind, dir, layer, fid}]} and keeps it for the junction list and the report."""
        from qgis.core import QgsCoordinateTransform, QgsFeatureRequest, QgsProject, QgsWkbTypes
        found = {}
        for f in self.layer.getFeatures():
            if f["code"] not in ("SPLAY-A", "SPLAY-S"):
                continue
            kind = "approach" if f["code"] == "SPLAY-A" else "stop"
            g = f.geometry()
            rings = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
            for i, ring in enumerate(rings):
                poly = QgsGeometry.fromPolygonXY([ring])
                for lyr in layers:
                    pg = QgsGeometry(poly)
                    if lyr.crs() != self.layer.crs():
                        pg.transform(QgsCoordinateTransform(self.layer.crs(), lyr.crs(), QgsProject.instance()))
                    eng = QgsGeometry.createGeometryEngine(pg.constGet())
                    eng.prepareGeometry()
                    for o in lyr.getFeatures(QgsFeatureRequest().setFilterRect(pg.boundingBox())):
                        og = o.geometry()
                        if og.isEmpty() or not eng.intersects(og.constGet()):
                            continue
                        if (QgsWkbTypes.geometryType(og.wkbType()) != QgsWkbTypes.PointGeometry
                                and eng.touches(og.constGet())):
                            continue                                    # only along the edge
                        found.setdefault(f["junction_id"], []).append(
                            {"kind": kind, "dir": "up" if i == 0 else "down", "layer": lyr.name(), "fid": o.id()})
        self.obstructions = found
        self.obstruction_layers = [l.name() for l in layers]
        return found

    def _symbol(self, code):
        rgb, w, dashed = STYLE.get(code, ("110,110,110", 0.3, False))
        props = {"line_color": rgb, "line_width": str(w), "line_width_unit": "MM"}
        if dashed:
            props.update({"line_style": "dash"})
        return QgsLineSymbol.createSimple(props)

    def ensure_style(self):
        """A layer adopted from an older project keeps its saved style: add the codes it has no symbol for
        (else a categorised renderer leaves them undrawn)."""
        r = self.layer.renderer()
        if not isinstance(r, QgsCategorizedSymbolRenderer) or r.classAttribute() != "code":
            return 0
        have = {c.value() for c in r.categories()}
        n = 0
        for code in list(STYLE) + list(self.templates["codes"]):
            if code not in have:
                r.addCategory(QgsRendererCategory(code, self._symbol(code), self.templates["codes"]
                                                  .get(code, {}).get("name", code)))
                have.add(code)
                n += 1
        if n:
            self.layer.triggerRepaint()
        return n

    def style(self):
        cats = []
        # every code of the templates gets a symbol: a categorised renderer draws nothing for a missing one
        styles = dict(STYLE)
        for code in self.templates["codes"]:
            styles.setdefault(code, ("110,110,110", 0.3, False))
        for code, (rgb, w, dashed) in styles.items():
            props = {"line_color": rgb, "line_width": str(w), "line_width_unit": "MM"}
            if dashed:
                props.update({"line_style": "dash"})
            sym = QgsLineSymbol.createSimple(props)
            cats.append(QgsRendererCategory(code, sym, self.templates["codes"][code]["name"]))
        self.layer.setRenderer(QgsCategorizedSymbolRenderer("code", cats))
        self.layer.triggerRepaint()
