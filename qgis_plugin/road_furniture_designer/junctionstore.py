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
from qgis.core import (QgsCategorizedSymbolRenderer, QgsFeature, QgsField, QgsFields, QgsGeometry, QgsLineSymbol,
                       QgsPointXY, QgsRendererCategory, QgsVectorLayer)

from .compat import WKB_MULTILINESTRING
from .rfd import junctions as J
from .rfd.alignment import format_station

LAYER = "rsd_junctions"
FIELDS = [
    ("piece_uuid", QVariant.String), ("junction_id", QVariant.String), ("kit", QVariant.String),
    ("piece", QVariant.String), ("corner", QVariant.String), ("code", QVariant.String),
    ("sta", QVariant.Double), ("bearing_deg", QVariant.Double), ("scale", QVariant.Double),
    ("edge_m", QVariant.Double), ("params", QVariant.String),
    ("status", QVariant.String), ("rule", QVariant.String), ("remarks", QVariant.String),
    # derived
    ("kind", QVariant.String), ("description", QVariant.String), ("ch", QVariant.String),
    ("side", QVariant.String), ("crossing_deg", QVariant.Double),
    ("kerb_m", QVariant.Double), ("island_m2", QVariant.Double), ("line_m", QVariant.Double),
    ("paint_m2", QVariant.Double),
]
TRIGGERS = ("sta", "bearing_deg", "scale", "edge_m")
STYLE = {   # code -> (colour, width mm, dashed)
    "KERB": ("40,40,40", 0.6, False), "GUIDE": ("120,120,120", 0.2, True),
    "HM07": ("230,180,0", 0.25, False), "HM14": ("230,180,0", 0.4, False), "LM24": ("230,180,0", 0.4, False),
    "HM04": ("70,110,170", 0.25, False), "LM27": ("70,110,170", 0.4, False),
    "TM07": ("70,110,170", 0.6, False), "BM07": ("70,110,170", 0.4, False),
}


def _fields():
    fs = QgsFields()
    for n, t in FIELDS:
        fs.append(QgsField(n, t))
    return fs


class JunctionStore(QObject):
    changed = pyqtSignal()

    def __init__(self, gpkg, al, crs=None):
        super().__init__()
        self.gpkg, self.al = gpkg, al
        self.templates = J.load_templates()
        self.layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", "RFD junctions", "ogr")
        if not self.layer.isValid():
            from .store import _write_layer
            w = _write_layer(gpkg, LAYER, _fields(), WKB_MULTILINESTRING, crs, False)
            del w
            self.layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", "RFD junctions", "ogr")
        have = {f.name() for f in self.layer.fields()}
        missing = [QgsField(n, t) for n, t in FIELDS if n not in have]
        if missing:
            self.layer.dataProvider().addAttributes(missing)
            self.layer.updateFields()
        self._busy = False
        self.bind(self.layer)

    def bind(self, layer):
        self.layer = layer
        layer.attributeValueChanged.connect(self._on_attribute_changed)
        for sig in (layer.featureDeleted, layer.afterCommitChanges, layer.afterRollBack):
            sig.connect(self.changed.emit)

    # ------------------------------------------------------------------ build
    def _features(self, pl: J.Placement, kit: str, piece: str, corner: str, params: dict, puuid: str,
                  status="approved", remarks=""):
        pc = J.build_piece(self.al, pl, piece, corner, params, self.templates)
        F = pl.frame(self.al)
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
                    "rule": f"junction:{pl.junction_id}", "remarks": remarks, "kind": pc.kind,
                    "description": f"{pc.name}: {codes[code]['name']}",
                    "ch": format_station(self.al.display_station(pl.station), 1), "side": F.side,
                    "crossing_deg": round(F.crossing_angle, 1),
                    # piece quantities go on its first feature only, so sums over the layer are right
                    "kerb_m": pc.quantities.get("kerb_m") if code == "KERB" else None,
                    "island_m2": pc.quantities.get("island_m2") if code == "KERB" else None,
                    "line_m": round(ln, 2) if code not in ("KERB", "GUIDE") else None,
                    "paint_m2": round(ln * codes[code]["width"], 3) if code not in ("KERB", "GUIDE") else None}
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

    def add(self, pl: J.Placement, kit: str, piece: str = "", guides: bool = True):
        """Place a whole kit (piece '') or one piece. Returns (pieces placed, findings)."""
        if piece:
            items = [{"piece": piece, "corner": "left_turn" if self.templates["pieces"][piece]["frame"] == "corner"
                      else ""}]
            # a lone piece takes the kit's own settings for it, if the kit uses it
            for it in self.templates["kits"].get(kit, []):
                if it["piece"] == piece:
                    items = [dict(it)]
                    break
        else:
            items = [it for it in self.templates["kits"][kit] if guides or it["piece"] != "guides"]
        feats = []
        for it in items:
            feats += self._features(pl, kit, it["piece"], it.get("corner", ""), it.get("params") or {},
                                    _uuid.uuid4().hex)
        self._write(feats)
        return len(items), J.findings(self.al, pl)

    def place(self, x0, y0, x1, y1, kit, piece="", scale=1.0, guides=True):
        return self.add(J.place(self.al, x0, y0, x1, y1, scale=scale), kit, piece, guides)

    # ------------------------------------------------------------------ edit / rebuild
    def _group(self, puuid):
        return [f for f in self.layer.getFeatures() if f["piece_uuid"] == puuid]

    def _rebuild(self, puuid, override=None):
        group = self._group(puuid)
        if not group:
            return False
        f0 = group[0]
        v = {n: f0[n] for n in ("sta", "bearing_deg", "scale", "edge_m", "kit", "piece", "corner", "params",
                                "status", "remarks", "junction_id")}
        v.update(override or {})

        def num(x, d=None):
            return d if x is None or (hasattr(x, "isNull") and x.isNull()) else float(x)
        pl = J.Placement(num(v["sta"]), math.radians(num(v["bearing_deg"])), num(v["scale"], 1.0),
                         num(v["edge_m"]), junction_id=v["junction_id"])
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
                "id": f["junction_id"], "kit": f["kit"], "sta": f["sta"], "ch": f["ch"], "side": f["side"],
                "crossing_deg": f["crossing_deg"], "scale": f["scale"], "status": f["status"],
                "pieces": set(), "kerb_m": 0.0, "island_m2": 0.0, "paint": {}})
            j["pieces"].add(f["piece"])
            for k in ("kerb_m", "island_m2"):
                x = f[k]
                if x is not None and not (hasattr(x, "isNull") and x.isNull()):
                    j[k] += float(x)
            if f["paint_m2"] is not None and not (hasattr(f["paint_m2"], "isNull") and f["paint_m2"].isNull()):
                p = j["paint"].setdefault(f["code"], [0.0, 0.0])
                p[0] += float(f["line_m"] or 0.0)
                p[1] += float(f["paint_m2"])
        return sorted(out.values(), key=lambda j: j["sta"] or 0.0)

    def parts(self):
        """(code, [polyline]) for drawing: plan sheets and DXF."""
        out = []
        for f in self.layer.getFeatures():
            g = f.geometry()
            if g is None or g.isEmpty():
                continue
            lines = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
            out.append((f["code"], f["sta"], [[(p.x(), p.y()) for p in ln] for ln in lines]))
        return out

    def style(self):
        cats = []
        for code, (rgb, w, dashed) in STYLE.items():
            props = {"line_color": rgb, "line_width": str(w), "line_width_unit": "MM"}
            if dashed:
                props.update({"line_style": "dash"})
            sym = QgsLineSymbol.createSimple(props)
            cats.append(QgsRendererCategory(code, sym, self.templates["codes"][code]["name"]))
        self.layer.setRenderer(QgsCategorizedSymbolRenderer("code", cats))
        self.layer.triggerRepaint()
