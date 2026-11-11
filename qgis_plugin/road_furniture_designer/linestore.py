"""LineStore: the linear road furniture layer (markings, road studs, barriers).

Each feature is a run along the alignment. The user sets WHAT (item code) and
WHERE (start and end station, side, offset from a corridor edge or from the
centreline); the geometry, chainage text, length and quantities are derived
and rebuilt whenever one of those fields changes.
"""
from __future__ import annotations

from qgis.PyQt.QtCore import QObject, QVariant, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.core import (QgsCategorizedSymbolRenderer, QgsFeature, QgsField, QgsFields, QgsGeometry, QgsLineSymbol,
                       QgsPointXY, QgsRendererCategory, QgsVectorLayer)

from .compat import WKB_MULTILINESTRING
from .rfd.alignment import format_station
from .rfd.linear import LinearCatalogue, Run, geometry, run_quantities, summarise

LAYER = "rsd_lines"
LINE_FIELDS = [
    ("line_uuid", QVariant.String), ("item_code", QVariant.String),
    ("sta_from", QVariant.Double), ("sta_to", QVariant.Double), ("side", QVariant.String),
    ("offset_m", QVariant.Double), ("edge_ref", QVariant.String), ("no_overtaking", QVariant.Int),
    ("status", QVariant.String), ("rule", QVariant.String), ("reason", QVariant.String),
    ("remarks", QVariant.String),
    # derived
    ("description", QVariant.String), ("category", QVariant.String), ("colour", QVariant.String),
    ("pattern", QVariant.String), ("ch_from", QVariant.String), ("ch_to", QVariant.String),
    ("length_m", QVariant.Double), ("quantity", QVariant.Double), ("unit", QVariant.String),
    ("speed_kmh", QVariant.Double),
]
TRIGGERS = ("item_code", "sta_from", "sta_to", "side", "offset_m", "edge_ref", "no_overtaking")


def _fields():
    fs = QgsFields()
    for n, t in LINE_FIELDS:
        fs.append(QgsField(n, t))
    return fs


class LineStore(QObject):
    changed = pyqtSignal()

    def __init__(self, gpkg, al, crs=None, cat=None):
        super().__init__()
        self.gpkg, self.al = gpkg, al
        self.cat = cat or LinearCatalogue.load()
        self.layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", "RFD linear furniture", "ogr")
        if not self.layer.isValid():
            self._create(crs)
            self.layer = QgsVectorLayer(f"{gpkg}|layername={LAYER}", "RFD linear furniture", "ogr")
        self._busy = False
        self._migrate()
        self.bind(self.layer)

    def _create(self, crs):
        from .store import _write_layer
        w = _write_layer(self.gpkg, LAYER, _fields(), WKB_MULTILINESTRING, crs, False)
        del w

    def _migrate(self):
        have = {f.name() for f in self.layer.fields()}
        missing = [QgsField(n, t) for n, t in LINE_FIELDS if n not in have]
        if missing:
            self.layer.dataProvider().addAttributes(missing)
            self.layer.updateFields()

    def bind(self, layer):
        self.layer = layer
        layer.attributeValueChanged.connect(self._on_attribute_changed)
        for sig in (layer.featureDeleted, layer.afterCommitChanges, layer.afterRollBack):
            sig.connect(self.changed.emit)
        self._idx = {n: layer.fields().indexOf(n) for n, _ in LINE_FIELDS}

    # ------------------------------------------------------------------ run <-> feature
    def run_of(self, f) -> Run:
        def val(n, d=None):
            v = f[n]
            return d if v is None or (hasattr(v, "isNull") and v.isNull()) else v
        return Run(val("item_code", ""), float(val("sta_from", 0.0)), float(val("sta_to", 0.0)),
                   side=val("side", "C") or "C", offset=float(val("offset_m", 0.0)),
                   edge_ref=val("edge_ref") or None, status=val("status", "approved") or "approved",
                   no_overtaking=bool(val("no_overtaking", 0)), rule=val("rule", "") or "",
                   reason=val("reason", "") or "", remarks=val("remarks", "") or "",
                   uuid=val("line_uuid") or Run("x", 0, 0).uuid)

    def derive(self, run: Run):
        """(geometry, {field: value}) for a run; ValueError for an unknown item."""
        if run.code not in self.cat:
            raise ValueError(f"Unknown linear item '{run.code}'")
        it = self.cat[run.code]
        lo = max(run.sta_start, self.al.sta_start)
        hi = min(run.sta_end, self.al.sta_end)
        if hi - lo < 0.01:
            raise ValueError(f"{run.code}: {run.sta_start:.1f}-{run.sta_end:.1f} is outside the alignment")
        run.sta_start, run.sta_end = lo, hi
        parts = geometry(self.al, run)
        geom = QgsGeometry.fromMultiPolylineXY([[QgsPointXY(x, y) for x, y in p] for p in parts]) if parts \
            else QgsGeometry()
        v = self.al.speed_at((lo + hi) / 2)
        q = run_quantities(run, it, v)
        qty = q.get("count", q["length"])
        vals = {"line_uuid": run.uuid, "item_code": run.code, "sta_from": round(lo, 3), "sta_to": round(hi, 3),
                "side": run.side, "offset_m": run.offset, "edge_ref": run.edge_ref, "no_overtaking": int(run.no_overtaking),
                "status": run.status, "rule": run.rule, "reason": run.reason, "remarks": run.remarks,
                "description": it.name, "category": it.category, "colour": it.colour,
                "pattern": it.pattern(v) if it.is_marking else (f"{q['spacing']:g} m interval" if "spacing" in q else ""),
                "ch_from": format_station(self.al.display_station(lo), 0),
                "ch_to": format_station(self.al.display_station(hi), 0),
                "length_m": round(q["length"], 2), "quantity": round(qty, 2),
                "unit": "No." if it.is_point_series else it.unit, "speed_kmh": v}
        return geom, vals

    def add_run(self, run: Run) -> int:
        geom, vals = self.derive(run)
        f = QgsFeature(self.layer.fields())
        f.setGeometry(geom)
        for n, x in vals.items():
            f.setAttribute(n, x)
        if self.layer.isEditable():
            self._busy = True
            self.layer.addFeature(f)
            self._busy = False
            fid = f.id()
        else:
            ok, out = self.layer.dataProvider().addFeatures([f])
            if not ok:
                raise RuntimeError("Could not add the run to the GeoPackage")
            fid = out[0].id()
            self.layer.reload()
        self.changed.emit()
        return fid

    def add_runs(self, runs):
        n, skipped = 0, []
        for r in runs:
            try:
                self.add_run(r)
                n += 1
            except ValueError as e:
                skipped.append(str(e))
        return n, skipped

    def recompute(self, fid):
        f = self.layer.getFeature(fid)
        try:
            geom, vals = self.derive(self.run_of(f))
        except ValueError:
            return False
        self._busy = True
        try:
            if self.layer.isEditable():
                self.layer.changeGeometry(fid, geom)
                for n, x in vals.items():
                    if f[n] != x:
                        self.layer.changeAttributeValue(fid, self._idx[n], x)
            else:
                dp = self.layer.dataProvider()
                dp.changeGeometryValues({fid: geom})
                dp.changeAttributeValues({fid: {self._idx[n]: x for n, x in vals.items()}})
                self.layer.reload()
        finally:
            self._busy = False
        return True

    def recompute_all(self):
        for f in list(self.layer.getFeatures()):
            self.recompute(f.id())
        self.changed.emit()

    def _on_attribute_changed(self, fid, idx, value):
        if self._busy:
            return
        name = self.layer.fields().at(idx).name()
        if name in TRIGGERS:
            self.recompute(fid)
            self.changed.emit()

    # ------------------------------------------------------------------ queries
    def runs(self, include_proposed=True):
        out = []
        for f in self.layer.getFeatures():
            if f["status"] == "proposed" and not include_proposed:
                continue
            if f["item_code"] in self.cat:
                out.append(self.run_of(f))
        return sorted(out, key=lambda r: (r.code, r.sta_start))

    def summary(self, include_proposed=True):
        return summarise(self.runs(include_proposed), self.cat, self.al)

    def _set_status_or_delete(self, ids, status=None):
        if not ids:
            return 0
        if status is None:
            if self.layer.isEditable():
                self.layer.deleteFeatures(ids)
            else:
                self.layer.dataProvider().deleteFeatures(ids)
        else:
            idx = self._idx["status"]
            if self.layer.isEditable():
                for fid in ids:
                    self.layer.changeAttributeValue(fid, idx, status)
            else:
                self.layer.dataProvider().changeAttributeValues({fid: {idx: status} for fid in ids})
        self.layer.reload()
        self.layer.triggerRepaint()
        self.changed.emit()
        return len(ids)

    def proposals(self):
        return [f.id() for f in self.layer.getFeatures() if f["status"] == "proposed"]

    def remove_proposals(self, rule_prefix=None):
        ids = [f.id() for f in self.layer.getFeatures() if f["status"] == "proposed"
               and (rule_prefix is None or (f["rule"] or "").startswith(rule_prefix))]
        return self._set_status_or_delete(ids)

    def accept_proposals(self, fids=None):
        return self._set_status_or_delete(fids or self.proposals(), "approved")

    # ------------------------------------------------------------------ style
    def style(self):
        cats = []
        colours = {"yellow": "230,180,0", "white": "245,245,245", "grey": "90,90,90"}
        for c in self.cat.categories():
            for it in self.cat.by_category(c):
                rgb = colours.get(it.colour, "200,0,200")
                if it.category == "Barrier":
                    sym = QgsLineSymbol.createSimple({"color": rgb, "width": "1.0", "capstyle": "flat"})
                elif it.is_point_series:
                    sym = QgsLineSymbol.createSimple({"color": rgb, "width": "0.8", "line_style": "dot"})
                else:
                    casing = QgsLineSymbol.createSimple({"color": "60,60,60", "width": "0.9"})
                    sym = casing
                    core = QgsLineSymbol.createSimple({
                        "color": rgb, "width": "0.5",
                        "line_style": "dash" if (it.dims(80).get("gap")) else "solid"})
                    sym.appendSymbolLayer(core.symbolLayer(0).clone())
                cats.append(QgsRendererCategory(it.code, sym, f"{it.code} {it.name}"))
        r = QgsCategorizedSymbolRenderer("item_code", cats)
        self.layer.setRenderer(r)
        self.layer.triggerRepaint()
