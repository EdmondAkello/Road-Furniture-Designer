"""Road furniture report: plan and long-section sheets (PDF / PNG), the strip diagram and schedule pages, drawn with QPainter.

One render routine paints every output (as in the LandXML Road & Terrain plugin), so
the PDF pages and the PNG sheets are identical. Each sheet shows, over a chainage window:

  * signs facing up-chainage traffic (left side) and down-chainage traffic (right side)
  * the design profile (and existing ground where the LandXML has it), with
    steep-grade bands, no-overtaking zones, crests / sags and their K values,
    headlight-limited sags and crests short of stopping sight distance
  * the horizontal alignment as a curvature band (curves needing warning highlighted)
  * grades between PVIs

After the sign schedule and the geometry findings come the road furniture pages
(furniture_pages.py): a strip diagram of signs, markings, studs, barriers and features,
the marking, barrier and feature schedules, linear quantities and the furniture checks
against the geometry.
"""
from __future__ import annotations

import datetime as dt
import math
import os

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import (QColor, QFont, QFontMetrics, QImage, QPageLayout, QPageSize, QPainter, QPainterPath,
                             QPdfWriter, QPen, QPolygonF)
from qgis.PyQt.QtSvg import QSvgRenderer

from .rfd.alignment import format_station
from .rfd.autoplace import AutoConfig, analyse, curve_groups

W, H = 1600.0, 1131.0          # logical page (A3 landscape proportions)
M = 30.0
COL = {"ink": "#1d2430", "muted": "#6b7686", "grid": "#e3e7ee", "frl": "#1f5fbf", "ground": "#8c5a2b",
       "steep": "#f2a33a", "noov": "#d64545", "sag": "#7b4fbf", "crest": "#c0392b", "curve": "#2d8f8f",
       "warn": "#d9822b", "prop": "#ff8c00"}
KIND_TEXT = {"curve": "Curve", "grade_descent": "Steep descent", "grade_ascent": "Steep ascent",
             "no_overtaking": "No overtaking", "sag_headlight": "Sag: headlight sight distance",
             "crest_ssd": "Crest: stopping sight distance"}


def _font(px, bold=False):
    f = QFont("Arial")
    f.setStyleHint(QFont.StyleHint.SansSerif if hasattr(QFont, "StyleHint") else QFont.SansSerif)
    f.setPixelSize(int(px))
    f.setBold(bold)
    return f


# --------------------------------------------------------------------------- frame, logo, title block
FRAME_M = 16.0
TB_H = 64.0                    # title block strip at the bottom of every page
TOP = 92.0                     # content starts below the header
BOTTOM = H - FRAME_M - TB_H    # ... and ends above the title block
TITLE_COLOUR = "#2b3a67"


def logo_path():
    """Company logo for the report frame: an image file set in QGIS settings
    (RoadFurnitureDesigner/report_logo). No logo when none is set."""
    try:
        from qgis.core import QgsSettings
        st = QgsSettings()
        path = st.value("RoadFurnitureDesigner/report_logo", "", type=str) or \
            st.value("RoadSignDesigner/report_logo", "", type=str)
    except Exception:
        return ""
    return path if path and os.path.exists(path) else ""


def draw_logo(p, r: QRectF):
    """Draw the configured logo in r (right-aligned). Returns False when no logo is set."""
    path = logo_path()
    if not path:
        return False
    img = QImage(path)
    if img.isNull():
        return False
    sc = min(r.width() / img.width(), r.height() / img.height())
    w, h = img.width() * sc, img.height() * sc
    p.drawImage(QRectF(r.right() - w, r.top() + (r.height() - h) / 2, w, h), img)
    return True


def draw_frame(p, d, heading, drawing, page, pages, scale_text="NTS"):
    """Page border, header (title left, logo top right) and title block. Returns the content rect."""
    p.fillRect(QRectF(0, 0, W, H), QColor("#ffffff"))
    outer = QRectF(FRAME_M, FRAME_M, W - 2 * FRAME_M, H - 2 * FRAME_M)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(COL["ink"]), 2.2)); p.drawRect(outer)
    # header
    p.setPen(QColor(TITLE_COLOUR)); p.setFont(_font(21, True))
    p.drawText(QRectF(FRAME_M + 14, FRAME_M + 10, W - 400, 28), int(Qt.AlignmentFlag.AlignLeft), heading)
    p.setPen(QColor(COL["muted"])); p.setFont(_font(13))
    sub = "  ·  ".join(x for x in (d.project, d.al.name, drawing) if x)
    p.drawText(QRectF(FRAME_M + 14, FRAME_M + 40, W - 400, 20), int(Qt.AlignmentFlag.AlignLeft), sub)
    draw_logo(p, QRectF(W - FRAME_M - 14 - 120, FRAME_M + 8, 120, 46))
    p.setPen(QColor(COL["muted"])); p.setFont(_font(9))
    p.drawText(QRectF(W - FRAME_M - 14 - 400, FRAME_M + 56, 400, 12), int(Qt.AlignmentFlag.AlignRight),
               "Road Furniture Designer · RDM 6.2 (2025) catalogue")
    p.setPen(QPen(QColor(COL["ink"]), 1)); p.drawLine(QPointF(FRAME_M, TOP - 8), QPointF(W - FRAME_M, TOP - 8))
    # title block
    tb = QRectF(FRAME_M, H - FRAME_M - TB_H, W - 2 * FRAME_M, TB_H)
    p.setPen(QPen(QColor(COL["ink"]), 1.4)); p.drawLine(tb.topLeft(), tb.topRight())
    sig = getattr(d, "signatories", {}) or {}
    cells = [("Project", d.project or "-", 2.5), ("Alignment", d.al.name, 2.1), ("Drawing", drawing, 3.2),
             ("Scale (A3)", scale_text, 1.1), ("Prepared by", sig.get("prepared_by") or "", 1.45),
             ("Checked by", sig.get("checked_by") or "", 1.45), ("Approved by", sig.get("approved_by") or "", 1.45),
             ("Date", dt.date.today().strftime("%d %b %Y"), 1.15), ("Sheet", f"{page} of {pages}", 0.95)]
    tot = sum(c[2] for c in cells)
    x = tb.left()
    for i, (lab, val, wt) in enumerate(cells):
        w = tb.width() * wt / tot
        if i:
            p.setPen(QPen(QColor(COL["ink"]), 1)); p.drawLine(QPointF(x, tb.top()), QPointF(x, tb.bottom()))
        p.setPen(QColor(COL["muted"])); p.setFont(_font(10))
        p.drawText(QRectF(x + 8, tb.top() + 6, w - 16, 14), int(Qt.AlignmentFlag.AlignLeft), lab.upper())
        p.setPen(QColor(COL["ink"])); f = _font(14, True)
        while QFontMetrics(f).horizontalAdvance(str(val)) > w - 16 and f.pixelSize() > 9:
            f.setPixelSize(f.pixelSize() - 1)
        p.setFont(f)
        p.drawText(QRectF(x + 8, tb.top() + 24, w - 16, 30), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   str(val))
        x += w
    return QRectF(FRAME_M + 10, TOP, W - 2 * FRAME_M - 20, BOTTOM - TOP - 6)


class ReportData:
    def __init__(self, store, cfg=None, title="Road Furniture", plan_scale=None, barrier_cfg=None, feature_cfg=None,
                 furniture=True):
        self.store = store
        self.plan_scale = plan_scale            # None: no plan sheets; else the drawing scale denominator
        self.signatories = {k: store.meta.get(k, "") for k in ("prepared_by", "checked_by", "approved_by")}
        self.al = store.al
        self.cfg = cfg or AutoConfig()
        self.findings = analyse(self.al, self.cfg)
        self.curves = curve_groups(self.al, self.cfg) if self.cfg.curves else []
        self.title = title
        self.project = store.meta.get("project", "")
        from .rfd.corridor import edge_polylines
        from .rfd.legend import face_svg as _face_svg
        self.edges = edge_polylines(self.al)
        try:
            self.others = store.other_alignments()
        except Exception:
            self.others = []
        self.signs = []
        faces_dir = os.path.splitext(store.gpkg)[0] + "_faces"
        for f in store.signs.getFeatures():
            sd = store.cat.signs.get(f["sign_code"])
            if sd is None:
                continue
            svg = os.path.join(faces_dir, f["face_svg"]) if f["face_svg"] else sd.svg(bool(f["mirror"]))
            if not f["face_svg"] and sd.legend == "label" and f["legend"]:
                # artwork value from the legend (W30 '10%' -> the actual grade); older projects lack the file
                txt = _face_svg(sd, f["legend"])
                if txt:
                    os.makedirs(faces_dir, exist_ok=True)
                    svg = os.path.join(faces_dir, f"{f['face_uuid'] or f.id()}_label.svg")
                    with open(svg, "w", encoding="utf-8") as fh:
                        fh.write(txt)
            pt = f.geometry().asPoint() if f.hasGeometry() else None
            sta_i = f["station_int"] or 0.0
            self.signs.append({
                "sta": f["station_int"] or 0.0, "chainage": f["chainage"], "side": f["side"], "facing": f["facing"],
                "code": f["sign_code"], "name": sd.name, "post": f["post_ref"], "size": f["size"],
                "offset": f["offset_m"], "clear": f["edge_clear"] if isinstance(f["edge_clear"], (int, float)) else None,
                "edge": f["edge_ref"] or "", "grade": f["grade_pct"] if isinstance(f["grade_pct"], (int, float)) else None,
                "legend": f["legend"] or "", "status": f["status"] or "", "reason": f["reason"] or "", "svg": svg,
                "legend_face": bool(f["face_svg"]) and sd.legend in ("directional", "plate"),
                "rule": f["rule"] or "",
                "x": pt.x() if pt else self.al.point_at(sta_i)[0], "y": pt.y() if pt else self.al.point_at(sta_i)[1],
                "heading": self.al.point_at(sta_i)[2]})
        self.signs.sort(key=lambda s: (s["sta"], s["side"]))
        self._svg = {}
        lines = getattr(store, "lines", None)
        self.lcat = lines.cat if lines is not None else None
        self.runs = lines.runs(include_proposed=True) if lines is not None else []
        jn = getattr(store, "junctions", None)
        self.junction_parts = jn.parts() if jn is not None else []
        if jn is not None and hasattr(store, "recheck_sight"):
            store.recheck_sight()                       # obstructions in the visibility splays, as of now
        self.junction_list = jn.junctions() if jn is not None else []
        self.fr = None
        if furniture and self.lcat is not None:
            from .rfd import furniture_report as FR
            self.fr = FR.build(self.al, self.runs, self.lcat, self.signs, self.cfg, barrier_cfg, feature_cfg,
                               vfindings=self.findings, curves=self.curves, junctions=self.junction_list,
                               others=store.other_alignments() if hasattr(store, "other_alignments") else None,
                               footprints=store.junction_blocks() if hasattr(store, "junction_blocks") else None)

    def renderer(self, path):
        r = self._svg.get(path)
        if r is None:
            r = QSvgRenderer(path)
            self._svg[path] = r
        return r


def sheet_windows(al, length):
    s0 = math.floor(al.sta_start / length) * length
    out = []
    while s0 < al.sta_end:
        out.append((max(s0, al.sta_start), min(s0 + length, al.sta_end)))
        s0 += length
    return out


# --------------------------------------------------------------------------- one long-section sheet
def draw_sheet(p: QPainter, d: ReportData, s0: float, s1: float, page: int, pages: int):
    al = d.al
    rng = f"CH {format_station(al.display_station(s0), 0)} – {format_station(al.display_station(s1), 0)}"
    draw_frame(p, d, d.title, f"Signage long section {rng}", page, pages,
               f"H 1:{(s1 - s0) * 1000 / ((W - 2 * M - 130) * 0.2625):,.0f}")
    left, right = M + 120, W - M - 10
    xs = lambda s: left + (s - s0) / max(s1 - s0, 1e-9) * (right - left)

    bands = {"fwd": QRectF(left, TOP, right - left, 140), "prof": QRectF(left, TOP + 150, right - left, 460),
             "bwd": QRectF(left, TOP + 620, right - left, 140), "horz": QRectF(left, TOP + 770, right - left, 90),
             "grade": QRectF(left, TOP + 868, right - left, 30)}
    labels = {"fwd": "Signs facing\nup-chainage\n(left side) →", "prof": "Long section",
              "bwd": "← Signs facing\ndown-chainage\n(right side)", "horz": "Horizontal\nalignment",
              "grade": "Grade"}
    p.setFont(_font(13, True))
    for k, r in bands.items():
        p.setPen(QPen(QColor("#c9d0da"), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
        p.setPen(QColor(COL["ink"]))
        p.drawText(QRectF(M, r.top(), left - M - 8, r.height()), int(Qt.AlignmentFlag.AlignVCenter), labels[k])

    # chainage grid
    step = 100.0 if s1 - s0 > 400 else 50.0
    p.setFont(_font(12))
    s = math.ceil(s0 / step) * step
    while s <= s1 + 1e-6:
        x = xs(s)
        p.setPen(QPen(QColor(COL["grid"]), 1))
        p.drawLine(QPointF(x, bands["fwd"].top()), QPointF(x, bands["grade"].bottom()))
        p.setPen(QColor(COL["muted"]))
        p.drawText(QRectF(x - 40, bands["grade"].bottom() + 4, 80, 16), int(Qt.AlignmentFlag.AlignHCenter),
                   format_station(al.display_station(s), 0))
        s += step

    # ---- profile
    pr = al.profile
    r = bands["prof"]
    zs = []
    n = 300
    if pr is not None:
        for k in range(n + 1):
            st = s0 + (s1 - s0) * k / n
            z = pr.elevation(st)
            if z is not None:
                zs.append((st, z))
    gz = [(st, z) for st, z in al.ground if s0 <= st <= s1]
    allz = [z for _, z in zs] + [z for _, z in gz]
    if allz:
        zmin, zmax = min(allz), max(allz)
        pad = max((zmax - zmin) * 0.15, 2.0)
        zmin, zmax = zmin - pad, zmax + pad
        ys = lambda z: r.bottom() - (z - zmin) / (zmax - zmin) * r.height()
        # findings bands
        for f in d.findings:
            a, b = max(f.start, s0), min(f.end, s1)
            if b <= a:
                continue
            x0, x1 = xs(a), xs(b)
            if f.kind.startswith("grade_"):
                p.fillRect(QRectF(x0, r.top(), x1 - x0, r.height()), QColor(242, 163, 58, 40))
            elif f.kind == "no_overtaking":
                pass                                        # drawn on top, after the sign lines
            elif f.kind in ("sag_headlight", "crest_ssd"):
                col = QColor(COL["sag"] if f.kind == "sag_headlight" else COL["crest"])
                col.setAlpha(45)
                p.fillRect(QRectF(x0, r.top() + 36, x1 - x0, r.height() - 36), col)
        # elevation grid
        p.setFont(_font(11)); p.setPen(QColor(COL["muted"]))
        zstep = max(1.0, 10 ** math.floor(math.log10(max(zmax - zmin, 1))) / 2)
        z = math.ceil(zmin / zstep) * zstep
        while z <= zmax:
            y = ys(z)
            p.setPen(QPen(QColor(COL["grid"]), 1, Qt.PenStyle.DotLine)); p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(COL["muted"])); p.drawText(QRectF(r.left() - 70, y - 8, 64, 16), int(Qt.AlignmentFlag.AlignRight), f"{z:.0f}")
            z += zstep
        # lines
        for pts, col, w in ((gz, COL["ground"], 1.6), (zs, COL["frl"], 2.4)):
            if len(pts) > 1:
                path = QPainterPath(QPointF(xs(pts[0][0]), ys(pts[0][1])))
                for st, z in pts[1:]:
                    path.lineTo(QPointF(xs(st), ys(z)))
                p.setPen(QPen(QColor(col), w)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
        # vertical curves
        if pr is not None:
            p.setFont(_font(11, True))
            for c in pr.curves:
                if not (s0 <= c.pvi_station <= s1):
                    continue
                x = xs(c.pvi_station); y = ys(pr.elevation(c.pvi_station))
                col = QColor(COL["crest"] if c.kind == "crest" else COL["sag"])
                tri = QPolygonF([QPointF(x - 6, y - 16), QPointF(x + 6, y - 16), QPointF(x, y - 6)]) if c.kind == "crest" \
                    else QPolygonF([QPointF(x - 6, y + 16), QPointF(x + 6, y + 16), QPointF(x, y + 6)])
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(col); p.drawPolygon(tri)
                p.setPen(col)
                txt = f"{c.kind.title()} K={c.k:.0f}" if c.k else c.kind.title()
                p.drawText(QRectF(x - 60, y - 36 if c.kind == "crest" else y + 18, 120, 16),
                           int(Qt.AlignmentFlag.AlignHCenter), txt)
        # sign chainages in the profile
        for sgn in d.signs:
            if s0 <= sgn["sta"] <= s1:
                x = xs(sgn["sta"])
                p.setPen(QPen(QColor(150, 160, 175), 0.8, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        # no-overtaking zones: one row per direction, label in a clear box at the start of the bar
        p.setFont(_font(10, True))
        for f in d.findings:
            if f.kind != "no_overtaking":
                continue
            a, b = max(f.start, s0), min(f.end, s1)
            if b <= a:
                continue
            x0, x1 = xs(a), xs(b)
            y = r.top() + (6 if f.direction == "Forward" else 24)
            p.fillRect(QRectF(x0, y, x1 - x0, 12), QColor(COL["noov"]))
            txt = ("→ " if f.direction == "Forward" else "← ") + "No overtaking"
            tw = QFontMetrics(_font(10, True)).horizontalAdvance(txt) + 8
            if x1 - x0 >= tw:
                p.setPen(QColor("#ffffff"))
                p.drawText(QRectF(x0 + 4, y - 1, x1 - x0 - 4, 14), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), txt)

    # ---- sign strips
    for key, facing in (("fwd", "Forward"), ("bwd", "Backward")):
        r = bands[key]
        right_edge = [-1e9, -1e9]                  # right-most occupied x in each row
        fm_b, fm = QFontMetrics(_font(10, True)), QFontMetrics(_font(9))
        for sgn in d.signs:
            if sgn["facing"] != facing or not (s0 <= sgn["sta"] <= s1):
                continue
            x = xs(sgn["sta"])
            rend = d.renderer(sgn["svg"])
            sz = rend.defaultSize()
            h = 36.0
            w = min(h * sz.width() / max(sz.height(), 1), 104.0)
            hh = w * sz.height() / max(sz.width(), 1)
            half = max(w, fm_b.horizontalAdvance(sgn["code"]), fm.horizontalAdvance(sgn["post"] or "")) / 2 + 3
            free = [x - half > right_edge[k] for k in (0, 1)]
            row = 0 if free[0] else (1 if free[1] else (0 if right_edge[0] <= right_edge[1] else 1))
            right_edge[row] = x + half
            top = r.top() + 5 + row * 64
            p.setPen(QPen(QColor(150, 160, 175), 0.8)); p.drawLine(QPointF(x, top + hh), QPointF(x, top + hh + 2))
            if sgn["status"] == "proposed":
                p.setPen(QPen(QColor(COL["prop"]), 2)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(x - w / 2 - 3, top - 3, w + 6, hh + 6), 4, 4)
            rend.render(p, QRectF(x - w / 2, top, w, hh))
            p.setPen(QColor(COL["ink"])); p.setFont(_font(10, True))
            p.drawText(QRectF(x - 50, top + hh + 1, 100, 12), int(Qt.AlignmentFlag.AlignHCenter), sgn["code"])
            p.setPen(QColor(COL["muted"])); p.setFont(_font(9))
            p.drawText(QRectF(x - 50, top + hh + 12, 100, 11), int(Qt.AlignmentFlag.AlignHCenter), sgn["post"] or "")

    # ---- horizontal alignment (curvature band)
    r = bands["horz"]
    mid = r.center().y()
    p.setPen(QPen(QColor(COL["muted"]), 1)); p.drawLine(QPointF(r.left(), mid), QPointF(r.right(), mid))
    acc = al.sta_start
    path = QPainterPath(QPointF(r.left(), mid))
    kmax = 1 / 80.0
    def ky(k):
        return mid - max(-1, min(1, k / kmax)) * (r.height() / 2 - 6)
    pts = []
    for e in al.elements:
        a, b = acc, acc + e.length
        acc = b
        if b < s0 or a > s1:
            continue
        for t in (0.0, 0.5, 1.0):
            s = a + (b - a) * t
            if s0 <= s <= s1:
                if e.kind == "arc":
                    k = (1 if e.ccw else -1) / e.radius
                elif e.kind == "spiral":
                    k = e.k0 + (e.k1 - e.k0) * t
                else:
                    k = 0.0
                pts.append((s, k))
    if pts:
        path = QPainterPath(QPointF(xs(pts[0][0]), ky(pts[0][1])))
        for s, k in pts[1:]:
            path.lineTo(QPointF(xs(s), ky(k)))
        p.setPen(QPen(QColor(COL["curve"]), 2)); p.drawPath(path)
    p.setFont(_font(11, True))
    warned = {round(f.values["group"].arc_start, 1) for f in d.findings if f.kind == "curve"}
    for c in d.curves:
        if not (s0 <= (c.arc_start + c.arc_end) / 2 <= s1):
            continue
        x = xs((c.arc_start + c.arc_end) / 2)
        hot = round(c.arc_start, 1) in warned
        p.setPen(QColor(COL["warn"] if hot else COL["curve"]))
        y = mid + 3 if c.left else mid - 17         # on the side of the axis away from the curve's bump
        p.drawText(QRectF(x - 90, y, 180, 14), int(Qt.AlignmentFlag.AlignHCenter),
                   f"R{c.radius:.0f} {'L' if c.left else 'R'} · {c.v_curve:.0f} km/h" + (" ⚠" if hot else ""))

    # ---- grades
    r = bands["grade"]
    p.setFont(_font(12, True)); p.setPen(QColor(COL["ink"]))
    if pr is not None:
        for (a, _, _), (b, _, _), g in zip(pr.pvis, pr.pvis[1:], pr.grades):
            lo, hi = max(a, s0), min(b, s1)
            if hi - lo < (s1 - s0) * 0.04:
                continue
            col = QColor(COL["warn"]) if abs(g) > d.cfg.descent_pct else QColor(COL["ink"])
            p.setPen(col)
            p.drawText(QRectF(xs(lo), r.top(), xs(hi) - xs(lo), r.height()), int(Qt.AlignmentFlag.AlignCenter),
                       f"{g:+.2f} %")

    # ---- legend + footer
    p.setFont(_font(12))
    items = [(COL["frl"], "Design FRL"), (COL["ground"], "Existing ground"), (COL["steep"], "Grade > 5 %"),
             (COL["noov"], "No-overtaking zone"), (COL["sag"], "Sag: headlight SD short"),
             (COL["crest"], "Crest: stopping SD short"), (COL["prop"], "Proposed sign (not yet accepted)")]
    x = left
    y = bands["grade"].bottom() + 26
    for col, txt in items:
        p.fillRect(QRectF(x, y + 3, 22, 10), QColor(col))
        p.setPen(QColor(COL["ink"])); p.drawText(QRectF(x + 28, y, 220, 16), int(Qt.AlignmentFlag.AlignLeft), txt)
        x += 40 + QFontMetrics(_font(12)).horizontalAdvance(txt)
    p.setPen(QColor(COL["muted"])); p.setFont(_font(10))
    p.drawText(QRectF(left, y + 18, W - left - M, 14), int(Qt.AlignmentFlag.AlignLeft),
               f"Criteria: {d.cfg.crit.name}. Sight distances {d.cfg.crit.ref('ssd')} / {d.cfg.crit.ref('psd')}; "
               f"K {d.cfg.crit.ref('k_crest')} / {d.cfg.crit.ref('k_sag')}.")


# --------------------------------------------------------------------------- tables
def draw_table_page(p, d, title, header, rows, widths, page, pages):
    draw_frame(p, d, d.title, title, page, pages, "NTS")
    y = TOP + 4
    rh = 26.0
    total = sum(widths)
    scale = (W - 2 * M) / total
    def row(vals, bold=False, shade=None):
        nonlocal y
        x = M
        if shade:
            p.fillRect(QRectF(M, y, W - 2 * M, rh), QColor(shade))
        p.setFont(_font(12, bold)); p.setPen(QColor(COL["ink"]))
        for v, w in zip(vals, widths):
            p.drawText(QRectF(x + 4, y, w * scale - 8, rh), int(Qt.AlignmentFlag.AlignVCenter), str(v))
            x += w * scale
        y += rh
    row(header, True, "#e8edf4")
    for i, r in enumerate(rows):
        row(r, False, "#f7f9fc" if i % 2 else None)


ROWS_PER_PAGE = 34


def schedule_rows(d):
    rows = []
    for s in d.signs:
        rows.append([s["post"], s["chainage"], s["side"], f"{s['offset']:.2f}" if s["offset"] is not None else "",
                     (f"{s['clear']:+.2f} {s['edge']}" if s["clear"] is not None else ""), s["facing"], s["code"],
                     s["name"][:38], s["size"], s["legend"].replace("\n", " / ")[:34],
                     (f"{s['grade']:+.1f}" if s["grade"] is not None else ""), s["status"] or "manual"])
    return rows


SCHED_HEAD = ["Post", "Chainage", "Side", "Offset", "Clear of edge", "Facing", "Code", "Description", "Size",
              "Legend", "Grade %", "Status"]
SCHED_W = [6, 9, 4, 6, 9, 7, 6, 24, 6, 20, 6, 8]


def finding_rows(d):
    al = d.al
    return [[format_station(al.display_station(f.start), 0), format_station(al.display_station(f.end), 0),
             KIND_TEXT.get(f.kind, f.kind), f.direction, f.text] for f in sorted(d.findings, key=lambda f: f.start)]


FIND_HEAD = ["From", "To", "Finding", "Direction", "Detail"]
FIND_W = [8, 8, 18, 8, 70]


PLAN_RECT = QRectF(FRAME_M + 10, TOP, W - 2 * FRAME_M - 20, 700)


def pages(d, sheet_len):
    from .plansheet import plan_pages
    wins = sheet_windows(d.al, sheet_len)
    sched = schedule_rows(d)
    finds = finding_rows(d)
    chunks = lambda rows: [rows[i:i + ROWS_PER_PAGE] for i in range(0, max(len(rows), 1), ROWS_PER_PAGE)]
    out = []
    if d.plan_scale:
        plans = plan_pages(d.al, d.plan_scale, W, PLAN_RECT)
        out += [("plan", (k + 1, len(plans)) + w) for k, w in enumerate(plans)]
    out += [("sheet", w) for w in wins]
    out += [("schedule", c) for c in chunks(sched)]
    out += [("findings", c) for c in chunks(finds)]
    from .furniture_pages import furniture_pages
    out += furniture_pages(d)
    return out


def draw_page(p, d, item, i, n):
    kind, payload = item
    if kind == "plan":
        from .plansheet import draw_plan
        k, nk, s0, s1, th, sc = payload
        rng = f"CH {format_station(d.al.display_station(s0), 0)} – {format_station(d.al.display_station(s1), 0)}"
        draw_frame(p, d, d.title, f"Road furniture plan {rng} (plan sheet {k} of {nk})", i, n, f"1:{sc:g}")
        lower = QRectF(PLAN_RECT.left(), PLAN_RECT.bottom() + 8, PLAN_RECT.width(), BOTTOM - PLAN_RECT.bottom() - 14)
        draw_plan(p, d, PLAN_RECT, s0, s1, th, sc, W, _font, COL,
                  key_rect=QRectF(lower.right() - 330, lower.top(), 330, lower.height()),
                  list_rect=QRectF(lower.left(), lower.top(), lower.width() - 340, lower.height()),
                  sheet_no=k, sheets=nk)
    elif kind == "sheet":
        draw_sheet(p, d, payload[0], payload[1], i, n)
    elif kind in ("strip", "ftable"):
        from .furniture_pages import draw_furniture_page
        draw_furniture_page(p, d, kind, payload, i, n)
    elif kind == "schedule":
        draw_table_page(p, d, "Sign schedule", SCHED_HEAD, payload, SCHED_W, i, n)
    else:
        draw_table_page(p, d, "Geometry findings (RDM 6.2 criteria and sight-distance checks)", FIND_HEAD,
                        payload, FIND_W, i, n)


def write_pdf(path, d, sheet_len=1000.0):
    items = pages(d, sheet_len)
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A3 if hasattr(QPageSize, "PageSizeId") else QPageSize.A3))
    writer.setPageOrientation(QPageLayout.Orientation.Landscape if hasattr(QPageLayout, "Orientation")
                              else QPageLayout.Landscape)
    writer.setResolution(200)
    writer.setTitle(d.title)
    writer.setCreator("Road Furniture Designer")
    p = QPainter(writer)
    vp = p.viewport()
    sc = vp.width() / W
    p.scale(sc, sc)
    p.setRenderHint(QPainter.RenderHint.Antialiasing if hasattr(QPainter, "RenderHint") else QPainter.Antialiasing)
    for i, item in enumerate(items, start=1):
        if i > 1:
            writer.newPage()
        draw_page(p, d, item, i, len(items))
    p.end()
    return len(items)


def write_pngs(folder, d, sheet_len=1000.0, scale=1.5, sheets_only=True):
    os.makedirs(folder, exist_ok=True)
    items = pages(d, sheet_len)
    paths = []
    for i, item in enumerate(items, start=1):
        if sheets_only and item[0] not in ("sheet", "plan", "strip"):
            continue
        img = QImage(int(W * scale), int(H * scale), QImage.Format.Format_ARGB32 if hasattr(QImage, "Format")
                     else QImage.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing if hasattr(QPainter, "RenderHint") else QPainter.Antialiasing)
        p.scale(scale, scale)
        draw_page(p, d, item, i, len(items))
        p.end()
        if item[0] == "plan":
            name = f"plan_{item[1][0]:02d}_{format_station(d.al.display_station(item[1][2]), 0).replace('+', '_')}.png"
        elif item[0] == "sheet":
            name = f"section_{format_station(d.al.display_station(item[1][0]), 0).replace('+', '_')}.png"
        elif item[0] == "strip":
            name = f"strip_{format_station(d.al.display_station(item[1][0][0]), 0).replace('+', '_')}.png"
        else:
            name = f"page_{i:02d}.png"
        out = os.path.join(folder, name)
        img.save(out, "PNG")
        paths.append(out)
    return paths


def write_xlsx(path, d):
    """Report workbook: Signs (incl. proposals and why), Findings, Horizontal curves, Vertical curves, and the
    road furniture sheets: Markings, Barriers, Features, Furniture quantities, Furniture checks."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo
    crit = d.cfg.crit
    al = d.al
    wb = Workbook()

    def sheet(ws, name, header, rows, widths):
        ws.append(header)
        for r in rows:
            ws.append(r)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for c in ws[1]:
            c.font = Font(bold=True)
        t = Table(displayName=name, ref=f"A1:{get_column_letter(len(header))}{max(len(rows), 1) + 1}")
        t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        ws.add_table(t)
        ws.freeze_panes = "A2"

    ws = wb.active; ws.title = "Signs"
    sheet(ws, "RSD_Report_Signs",
          ["Post", "Chainage", "Chainage (m)", "Side", "Offset (m)", "Edge", "Clear of edge (m)", "Facing", "Code",
           "Description", "Size", "Legend", "Grade (%)", "Status", "Reason"],
          [[s["post"], s["chainage"], round(al.display_station(s["sta"]), 3), s["side"], s["offset"], s["edge"],
            s["clear"], s["facing"], s["code"], s["name"], s["size"], s["legend"].replace("\n", " / "), s["grade"],
            s["status"] or "manual", s["reason"]] for s in d.signs],
          [7, 11, 11, 5, 9, 6, 10, 9, 8, 34, 7, 30, 9, 10, 60])
    ws = wb.create_sheet("Findings")
    sheet(ws, "RSD_Findings", ["From", "To", "From (m)", "To (m)", "Finding", "Direction", "Detail"],
          [[format_station(al.display_station(f.start), 0), format_station(al.display_station(f.end), 0),
            round(al.display_station(f.start), 1), round(al.display_station(f.end), 1),
            KIND_TEXT.get(f.kind, f.kind), f.direction, f.text] for f in sorted(d.findings, key=lambda f: f.start)],
          [10, 10, 10, 10, 30, 10, 90])
    ws = wb.create_sheet("Horizontal curves")
    sheet(ws, "RSD_HCurves", ["Start", "End", "Radius (m)", "Turn", "Deflection (deg)", "e (%)", "f max",
                              "Curve speed (km/h)", "Design speed (km/h)", "Speed drop", "Warning"],
          [[format_station(al.display_station(c.start), 0), format_station(al.display_station(c.end), 0),
            round(c.radius, 1), "Left" if c.left else "Right", round(c.deflection, 1), c.e_pct,
            round(crit.f_max(c.v_curve), 3), round(c.v_curve, 1), c.v_approach,
            round(c.v_approach - c.v_curve, 1),
            "yes" if c.v_approach - c.v_curve >= d.cfg.warn_margin else ""] for c in d.curves],
          [10, 10, 10, 7, 14, 7, 7, 16, 16, 10, 9])
    ws = wb.create_sheet("Vertical curves")
    rows = []
    if al.profile is not None:
        for c in al.profile.curves:
            v = al.speed_at(c.pvi_station) or 0
            S = crit.ssd(v) if v else None
            rows.append([format_station(al.display_station(c.pvi_station), 0), c.kind, round(c.length, 1),
                         round(c.grade_in, 2), round(c.grade_out, 2), round(c.a, 2),
                         round(c.k, 1) if c.k else None, v or None, S])
    sheet(ws, "RSD_VCurves", ["PVI", "Type", "Length (m)", "Grade in (%)", "Grade out (%)", "A (%)", "K",
                              "Design speed (km/h)", "SSD (m)"], rows, [10, 8, 10, 12, 12, 8, 8, 16, 9])
    if d.fr is not None:
        _furniture_sheets(wb, d, sheet)
    ws = wb.create_sheet("Basis")
    for line in [
        ("Sign catalogue", "RDM 6.2 Traffic Signs (2025), Ministry of Roads and Transport"),
        ("Lateral position", "RDM 6.2 2.4: posts 0.6-3.0 m beyond the carriageway / paved shoulder edge"),
        ("Advance distance", "RDM 6.2 2.4: readable in 6 s -> 6 s of travel at the design speed"),
        ("Sign spacing", "RDM 6.2 2.4: at least 0.6 x V m apart"),
        ("Steep grades", "RDM 6.2 4.6.4: W30 descent > 5 %, W31 ascent > 10 %"),
        ("Chevrons", "RDM 6.2 4.6.1 / Table 4.2 spacing, outside of the curve"),
        ("No overtaking", "RDM 6.2 3.11: both ends, both directions, distance plate, END plate"),
        ("Criteria", crit.name),
        ("Curve speed", f"V^2 = 127 R (e + f); f max from {crit.ref('side_friction')}"),
        ("Stopping sight distance", f"{crit.ref('ssd')}; eye {crit.eye_height:g} m, object {crit.object_height:g} m"),
        ("Passing sight distance", f"{crit.ref('psd')}{' (reduced values)' if d.cfg.psd_reduced and crit.is_kenya else ''}; "
                                   f"eye {crit.eye_height:g} m, object {crit.psd_object_height:g} m"),
        ("Crest / sag K", f"{crit.ref('k_crest')} / {crit.ref('k_sag')}"),
        ("Markings", "RDM 6.1 Road Marking (2025): centre line from the no-overtaking zones (PSD basis)"),
        ("Barriers", f"{crit.ref('barrier_warrant')}; run-out {crit.ref('barrier_runout')}; "
                     f"clear zone {crit.ref('clear_zone')}"),
        ("Traffic calming", "RDM 6.4 Other Traffic Control Devices; crossings RDM 6.1 9.2"),
        ("Generated", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))]:
        ws.append(list(line))
    ws.column_dimensions["A"].width = 18; ws.column_dimensions["B"].width = 110
    wb.save(path)


def _furniture_sheets(wb, d, sheet):
    from .rfd.furniture_report import KIND_TEXT
    al = d.al
    disp = lambda s: round(al.display_station(s), 3)
    ch = lambda s: format_station(al.display_station(s), 0)
    fr = d.fr
    ws = wb.create_sheet("Markings")
    sheet(ws, "RFD_Markings", ["Code", "Description", "Category", "From", "To", "From (m)", "To (m)", "Length (m)",
                               "Side", "Offset (m)", "Edge", "Pattern / interval", "Quantity", "Unit", "Area (m2)",
                               "Status", "Reason", "Run UUID"],
          [[m["code"], m["name"], m["category"], ch(m["from"]), ch(m["to"]), disp(m["from"]), disp(m["to"]),
            round(m["length"], 2), m["side"], round(m["offset"], 2), m["edge"] or None, m["detail"], m["qty"],
            m["unit"], m["area"], m["status"], m["reason"], m["run"].uuid] for m in fr.markings],
          [8, 40, 11, 10, 10, 10, 10, 10, 6, 9, 7, 34, 9, 6, 10, 10, 60, 38])
    ws = wb.create_sheet("Barriers")
    sheet(ws, "RFD_Barriers", ["Item", "From", "To", "From (m)", "To (m)", "Length (m)", "Side", "Offset (m)",
                               "Edge", "Terminals", "Status", "Basis", "Run UUID"],
          [[m["code"], ch(m["from"]), ch(m["to"]), disp(m["from"]), disp(m["to"]), round(m["length"], 2), m["side"],
            round(m["offset"], 2), m["edge"] or None, m["terminals"], m["status"], m["reason"], m["run"].uuid]
           for m in fr.barriers], [8, 10, 10, 10, 10, 10, 6, 9, 7, 9, 10, 100, 38])
    ws = wb.create_sheet("Features")
    rows = []
    for g in fr.features:
        rows.append([ch(g["station"]), disp(g["station"]), g["kind"], g["main"], g["detail"], ", ".join(g["codes"]),
                     ", ".join(g["sign_codes"]), "; ".join(c.text for c in g.get("checks", [])), g["status"],
                     g["id"]])
    sheet(ws, "RFD_Features", ["Chainage", "Chainage (m)", "Kind", "Main item", "Detail", "Items", "Signs",
                               "Checks", "Status", "Feature ID"], rows, [10, 11, 16, 10, 70, 30, 12, 70, 10, 10])
    jl = getattr(d, "junction_list", None) or []
    if jl:
        from .rfd.junctions import load_templates
        codes = load_templates()["codes"]
        rows = []
        for j in jl:
            base = [j["ch"], round(al.display_station(j["sta"]), 3), j["kit"], j["side"], j["crossing_deg"], j["scale"]]
            if j["kerb_m"]:
                raised, flush = j.get("kerb_raised_m", j["kerb_m"]), j.get("kerb_flush_m", 0.0)
                rows.append(base + ["KERB", codes["KERB"]["name"] + (" - raised" if flush else ""),
                                    round(raised, 2), "m", round(j["island_m2"], 2), j["status"], j["id"]])
                if flush:
                    rows.append(base + ["KERB-F", codes["KERB"]["name"] + " - flush (bay tapers)", round(flush, 2),
                                        "m", None, j["status"], j["id"]])
            for c, (ln, area) in sorted(j["paint"].items()):
                rows.append(base + [c, codes[c]["name"], round(ln, 2), "m", round(area, 3), j["status"], j["id"]])
            if j.get("access"):
                aq = j["access"]["quantities"]
                rows.append(base + ["ACCESS", f"Private access {j['access']['width']:g} m, pavement to the boundary "
                                              f"and taper (area m2)", aq.get("edge_m"), "m", aq.get("area_m2"),
                                    j["status"], j["id"]])
                if aq.get("pipe_no"):
                    rows.append(base + ["PIPE", codes["PIPE"]["name"], aq.get("pipe_m"), "m", None, j["status"], j["id"]])
        bays = [j for j in jl if j.get("bay")]
        extra = [(j, w) for j in jl for w in (j.get("widen") or [])]
        if bays or extra:
            from .rfd.junctions import bay_table
            ws = wb.create_sheet("Widenings")
            wrows = []
            for j, t in zip(bays, bay_table(al, [dict(j["bay"]) for j in bays])):
                wrows.append([j["id"], j["bay"].get("kind", "bus bay"), t["side"], round(al.display_station(t["start"]), 3),
                             round(al.display_station(t["full_from"]), 3), round(al.display_station(t["full_to"]), 3),
                             round(al.display_station(t["end"]), 3), t["entry"], t["exit"], t["width"],
                             round(j["widen_m2"], 1), round(j["kerb_m"], 1),
                             round(j.get("kerb_raised_m", j["kerb_m"]), 1), round(j.get("kerb_flush_m", 0.0), 1)])
            # junction widenings: the ghost island's, the bellmouth behind a corner island, the minor road's flare
            for (j, w), t in zip(extra, bay_table(al, [dict(w) for _j, w in extra])):
                area = w["depth"] * (abs(t["full_to"] - t["full_from"]) + (t["entry"] + t["exit"]) / 2)
                wrows.append([j["id"], w["kind"], t["side"], round(al.display_station(t["start"]), 3),
                             round(al.display_station(t["full_from"]), 3), round(al.display_station(t["full_to"]), 3),
                             round(al.display_station(t["end"]), 3), t["entry"], t["exit"], t["width"],
                             round(area, 1), None, None, None])
            sheet(ws, "RFD_Widenings", ["ID", "Kind", "Side", "Widening from (m)", "Full width from (m)",
                                       "Full width to (m)", "Widening to (m)", "Entry taper (m)", "Exit taper (m)",
                                       "Width (m)", "Widening area (m2)", "Kerb (m)", "Raised kerb (m)",
                                       "Flush kerb (m)"],
                  wrows, [10, 14, 6, 14, 14, 14, 14, 11, 11, 9, 12, 9, 10, 10])
        ws = wb.create_sheet("Junctions")
        sheet(ws, "RFD_Junctions", ["Chainage", "Chainage (m)", "Type", "Minor road side", "Crossing angle (deg)",
                                    "Scale", "Item", "Description", "Length", "Unit",
                                    "Area (m2; island or painted)", "Status", "Junction ID"],
              rows, [10, 11, 7, 8, 10, 7, 7, 60, 9, 6, 12, 10, 12])
    ws = wb.create_sheet("Furniture quantities")
    sheet(ws, "RFD_Furniture_Quantities", ["Category", "Item", "Description", "Pattern", "Unit", "Quantity"],
          [list(q) for q in fr.quantities], [16, 10, 44, 30, 6, 10])
    ws = wb.create_sheet("Furniture checks")
    sheet(ws, "RFD_Checks", ["Level", "From", "To", "From (m)", "To (m)", "Side", "Check", "Detail"],
          [[c.level, ch(c.start), ch(c.end), disp(c.start), disp(c.end), c.side, KIND_TEXT.get(c.kind, c.kind), c.text]
           for c in fr.checks] + [["info", "", "", None, None, "", "Note", n] for n in fr.notes],
          [8, 10, 10, 10, 10, 9, 34, 120])
