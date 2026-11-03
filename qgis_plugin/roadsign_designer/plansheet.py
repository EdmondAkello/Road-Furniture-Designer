"""Plan layout sheets for the road signage report.

Each sheet shows a stretch of road at a fixed drawing scale (1:1000, 1:2500 ...),
turned so the road runs left to right, with the corridor edges, other LandXML
alignments, chainages, and every sign drawn upright beside the road with a
leader to its post (as in HH plan drawings). Match lines close each sheet; a key
plan, scale bar and north arrow sit under the viewport with the sheet's sign list.

Sheet windows are chosen so the road (and room for the signs either side) fits
the viewport at the chosen scale, so tight curves get shorter sheets.
"""
from __future__ import annotations

import math

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFontMetrics, QPainterPath, QPen, QPolygonF

from .rsd.alignment import format_station
from .rsd.corridor import edge_polylines
from .rsd.plan_layout import SERIES_CODES, SERIES_FACTOR, callouts_by_post, leader_tip

PAPER_W_MM = 420.0                     # A3 landscape; logical page is report.W wide
SYMBOL_MM = 10.0                       # sign symbol on the plan (as the DXF export)
SCALES = (500, 1000, 1250, 2000, 2500, 5000)

EDGE_STYLE = {"ETW": ("#3b4250", 1.4, Qt.PenStyle.SolidLine), "EPS": ("#7d8796", 1.0, Qt.PenStyle.SolidLine),
              "Hinge": ("#a6aebb", 0.8, Qt.PenStyle.DashLine), "Ditch_In": ("#4f86c6", 0.8, Qt.PenStyle.SolidLine),
              "Ditch_Out": ("#4f86c6", 0.8, Qt.PenStyle.SolidLine), "Daylight": ("#6aa84f", 0.8, Qt.PenStyle.DashLine)}


def auto_scale(al) -> int:
    """Drawing scale for the plan sheets: 1:1000 for short roads, else 1:2500 (HH's usual plan scale)."""
    return 1000 if al.length <= 1200 else 2500


class Viewport:
    def __init__(self, rect: QRectF, scale: float, page_w: float):
        self.rect = rect
        self.scale = scale
        self.mpu = PAPER_W_MM / page_w * scale / 1000.0          # metres of ground per logical unit
        self.width_m = rect.width() * self.mpu
        self.height_m = rect.height() * self.mpu


def _rot(x, y, th):
    c, s = math.cos(-th), math.sin(-th)
    return x * c - y * s, x * s + y * c


def sheet_windows(al, vp: Viewport, margin_m: float):
    """[(s0, s1, theta)] covering the alignment; each window fits the viewport with margin_m either side."""
    out, s0 = [], al.sta_start
    usable_w, usable_h = vp.width_m * 0.94, vp.height_m - 2 * margin_m
    while s0 < al.sta_end - 1e-6:
        length = min(usable_w, al.sta_end - s0)
        while True:
            s1 = s0 + length
            xa, ya, _ = al.point_at(s0); xb, yb, _ = al.point_at(s1)
            th = math.atan2(yb - ya, xb - xa)
            us, vs = [], []
            n = max(8, int(length / 10))
            for k in range(n + 1):
                x, y, _ = al.point_at(s0 + length * k / n)
                u, v = _rot(x - xa, y - ya, th)
                us.append(u); vs.append(v)
            if (max(us) - min(us) <= usable_w and max(vs) - min(vs) <= max(usable_h, vp.height_m * 0.3)) \
                    or length <= 50.0:
                break
            length *= 0.9
        if al.sta_end - s1 < 0.15 * usable_w and s1 < al.sta_end:   # avoid a sliver sheet at the end
            if s1 - s0 + (al.sta_end - s1) <= usable_w:
                s1 = al.sta_end
        out.append((s0, s1, th))
        s0 = s1
    return out


def plan_pages(al, scale, page_w, vp_rect):
    vp = Viewport(vp_rect, scale, page_w)
    margin = 4.2 * SYMBOL_MM * scale / 1000.0 + 15.0
    return [(s0, s1, th, scale) for s0, s1, th in sheet_windows(al, vp, margin)]


def draw_plan(p, d, rect: QRectF, s0, s1, th, scale, page_w, font, colours, key_rect=None, list_rect=None,
              sheet_no=1, sheets=1):
    """Draw one plan viewport (and its key plan and sign list) on painter p."""
    al = d.al
    vp = Viewport(rect, scale, page_w)
    # frame centre on the window's road extents
    xa, ya, _ = al.point_at(s0)
    n = max(8, int((s1 - s0) / 5))
    uv = [_rot(al.point_at(s0 + (s1 - s0) * k / n)[0] - xa, al.point_at(s0 + (s1 - s0) * k / n)[1] - ya, th)
          for k in range(n + 1)]
    um = (min(u for u, _ in uv) + max(u for u, _ in uv)) / 2
    vm = (min(v for _, v in uv) + max(v for _, v in uv)) / 2

    def to_uv(x, y):
        return _rot(x - xa, y - ya, th)

    def P(x, y):
        u, v = to_uv(x, y)
        return QPointF(rect.center().x() + (u - um) / vp.mpu, rect.center().y() - (v - vm) / vp.mpu)

    # world box around this viewport: only geometry inside it is transformed and drawn
    rad = 0.5 * (vp.width_m ** 2 + vp.height_m ** 2) ** 0.5 + 20.0
    mx, my = al.point_at(s0 + (s1 - s0) / 2)[:2]
    wb = (mx - rad, my - rad, mx + rad, my + rad)
    inside = lambda q: wb[0] <= q[0] <= wb[2] and wb[1] <= q[1] <= wb[3]

    def poly(pts):
        """Path of the parts of a world polyline that fall inside the viewport's box."""
        path = QPainterPath()
        pen_down = False
        for q in pts:
            if inside(q):
                if pen_down:
                    path.lineTo(P(*q))
                else:
                    path.moveTo(P(*q)); pen_down = True
            else:
                pen_down = False
        return path

    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor("#ffffff"))
    # chainage range this sheet covers (with a little context either side)
    ctx = 0.25 * vp.width_m
    lo, hi = max(al.sta_start, s0 - ctx), min(al.sta_end, s1 + ctx)

    def sample(a, b, step=2.0):
        m = max(2, int((b - a) / step))
        return [al.point_at(a + (b - a) * k / m)[:2] for k in range(m + 1)]

    # other alignments
    p.setFont(font(9, True))
    for o in d.others:
        pts = [o.point_at(o.sta_start + o.length * k / max(2, int(o.length / 3)))[:2]
               for k in range(max(2, int(o.length / 3)) + 1)]
        inside = [q for q in pts if rect.adjusted(-50, -50, 50, 50).contains(P(*q))]
        if not inside:
            continue
        p.setPen(QPen(QColor("#2e8b57"), 1.2, Qt.PenStyle.DashDotLine)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(poly(pts))
        q = inside[len(inside) // 2]
        p.setPen(QColor("#2e8b57")); p.drawText(P(*q) + QPointF(6, -6), o.name)
    # corridor edges of the signed alignment
    for code, side, pts in d.edges:
        col, w, style = EDGE_STYLE.get(code, ("#b9c0cc", 0.7, Qt.PenStyle.SolidLine))
        p.setPen(QPen(QColor(col), w, style)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(poly(pts))
    # centreline
    p.setPen(QPen(QColor("#1f5fbf"), 1.2, Qt.PenStyle.DashDotLine))
    p.drawPath(poly(sample(lo, hi)))
    # chainage ticks
    tick = 25.0 if scale <= 1250 else (50.0 if scale <= 2500 else 100.0)
    p.setFont(font(9))
    s = math.ceil(lo / tick) * tick
    while s <= hi + 1e-6:
        x, y, h = al.point_at(s)
        nx, ny = math.sin(h), -math.cos(h)
        L = 4.0 * vp.mpu
        a, b = P(x - nx * L, y - ny * L), P(x + nx * L, y + ny * L)
        major = abs(s / (tick * 2) - round(s / (tick * 2))) < 1e-6 or tick >= 100
        p.setPen(QPen(QColor("#1f5fbf"), 1.0)); p.drawLine(a, b)
        if major:
            ang = math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x()))      # tick direction on the page
            p.save(); p.translate(b)
            if 90 < ang % 360 < 270:
                p.rotate(ang + 180); p.setPen(QColor("#1f5fbf"))
                p.drawText(QRectF(-64, -6, 60, 12), int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                           format_station(al.display_station(s), 0))
            else:
                p.rotate(ang); p.setPen(QColor("#1f5fbf"))
                p.drawText(QRectF(4, -6, 60, 12), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           format_station(al.display_station(s), 0))
            p.restore()
        s += tick
    # match lines
    for sm, label in ((s0, "start"), (s1, "end")):
        if (label == "start" and sm <= al.sta_start + 1e-6) or (label == "end" and sm >= al.sta_end - 1e-6):
            continue
        x, y, h = al.point_at(sm)
        nx, ny = math.sin(h), -math.cos(h)
        L = 0.22 * vp.height_m
        a, b = P(x - nx * L, y - ny * L), P(x + nx * L, y + ny * L)
        p.setPen(QPen(QColor("#c0392b"), 1.6, Qt.PenStyle.DashLine)); p.drawLine(a, b)
        other = sheet_no - 1 if label == "start" else sheet_no + 1
        p.setFont(font(10, True)); p.setPen(QColor("#c0392b"))
        top = a if a.y() < b.y() else b
        txt = f"MATCH LINE CH {format_station(al.display_station(sm), 0)}  ·  plan sheet {other}"
        tw = QFontMetrics(font(10, True)).horizontalAdvance(txt)
        tx = top.x() + 6 if label == "start" else top.x() - tw - 6
        p.drawText(QRectF(tx, max(top.y(), rect.top() + 4), tw + 4, 14), int(Qt.AlignmentFlag.AlignLeft), txt)

    # signs: upright symbols beside the road, leaders to the posts
    sym = SYMBOL_MM * scale / 1000.0                 # metres
    mine = [s for s in d.signs if s0 - 1e-6 <= s["sta"] <= s1 + 1e-6]
    items, sizes = [], {}
    for i, sg in enumerate(mine):
        rend = d.renderer(sg["svg"])
        sz = rend.defaultSize()
        ar = sz.width() / max(sz.height(), 1)
        if sg["legend_face"]:
            hm = sym * 0.62 * min(1.0, 0.45 + 0.18 * max(1, sg["legend"].count("\n") + 1))
            wm = min(hm * ar, sym * 4.5)
            hm = wm / ar
        else:
            k = SERIES_FACTOR if sg["code"].startswith(SERIES_CODES) else 1.0
            wm, hm = (sym * k, sym * k / ar) if ar >= 1 else (sym * k * ar, sym * k)
        sizes[i] = (wm, hm)
        u, v = to_uv(sg["x"], sg["y"])
        lab_w = QFontMetrics(font(8, True)).horizontalAdvance(f"{sg['post']} {sg['code']}") * vp.mpu + 0.1 * sym
        items.append((i, sg["sta"], u, v, sg["heading"] - th, sg["side"], max(wm, lab_w), hm + 0.32 * sym,
                      sg["post"], sg["facing"]))
    cen = callouts_by_post(items, gap=0.2 * sym)
    p.setFont(font(8, True))
    placed, posts = [], {}
    for i, sg in enumerate(mine):
        wm, hm = sizes[i]
        cu, cv = cen[i]
        cv += 0.16 * sym                                   # label room below the face
        u, v = to_uv(sg["x"], sg["y"])
        px = QPointF(rect.center().x() + (u - um) / vp.mpu, rect.center().y() - (v - vm) / vp.mpu)
        c = QPointF(rect.center().x() + (cu - um) / vp.mpu, rect.center().y() - (cv - vm) / vp.mpu)
        w, h = wm / vp.mpu, hm / vp.mpu
        box = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        placed.append((sg, box, c))
        key = sg["post"] or id(sg)
        full = box.adjusted(0, 0, 0, 0.3 * sym / vp.mpu)
        posts[key] = (px, posts[key][1].united(full)) if key in posts else (px, full)
    # one leader per post, to the group of faces it carries
    for px, gb in posts.values():
        tx, ty = leader_tip(px.x(), px.y(), (gb.left(), gb.top(), gb.right(), gb.bottom()))
        p.setPen(QPen(QColor("#4a5160"), 0.7)); p.drawLine(px, QPointF(tx, ty))
        p.setBrush(QColor("#ffffff")); p.drawEllipse(px, 2.2, 2.2)
    for sg, box, c in placed:
        if sg["status"] == "proposed":
            p.setPen(QPen(QColor(colours["prop"]), 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 3, 3)
        d.renderer(sg["svg"]).render(p, box)
        p.setPen(QColor("#1d2430"))
        p.drawText(QRectF(c.x() - 40, box.bottom() + 1, 80, 11), int(Qt.AlignmentFlag.AlignHCenter),
                   f"{sg['post']} {sg['code']}")
    p.restore()

    # north arrow (top right of the viewport)
    na = QPointF(rect.right() - 34, rect.top() + 40)
    ang = math.pi / 2 - th                               # world north on the page
    dx, dy = math.cos(ang), -math.sin(ang)
    tip = na + QPointF(dx * 22, dy * 22)
    tail = na - QPointF(dx * 16, dy * 16)
    left = na + QPointF(-dy * 8, dx * 8) - QPointF(dx * 6, dy * 6)
    right = na - QPointF(-dy * 8, dx * 8) - QPointF(dx * 6, dy * 6)
    p.setPen(QPen(QColor("#1d2430"), 1.2)); p.setBrush(QColor("#1d2430"))
    p.drawPolygon(QPolygonF([tip, left, na, right]))
    p.drawLine(na, tail)
    p.setFont(font(12, True))
    p.drawText(QRectF(tip.x() - 10 + dx * 10, tip.y() - 8 + dy * 12, 20, 16), int(Qt.AlignmentFlag.AlignCenter), "N")
    p.setPen(QPen(QColor("#c9d0da"), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(rect)

    # scale bar (bottom left of the viewport)
    nice = [10, 20, 25, 50, 100, 200, 250, 500, 1000]
    seg = next((v for v in nice if v / vp.mpu >= 45), 1000)
    x0, y0 = rect.left() + 16, rect.bottom() - 22
    p.setFont(font(9))
    for k in range(4):
        p.setPen(QPen(QColor("#1d2430"), 1))
        p.setBrush(QColor("#1d2430") if k % 2 == 0 else QColor("#ffffff"))
        p.drawRect(QRectF(x0 + k * seg / vp.mpu, y0, seg / vp.mpu, 6))
        p.drawText(QRectF(x0 + k * seg / vp.mpu - 20, y0 + 7, 40, 12), int(Qt.AlignmentFlag.AlignHCenter), f"{k * seg}")
    p.drawText(QRectF(x0 + 4 * seg / vp.mpu - 20, y0 + 7, 70, 12), int(Qt.AlignmentFlag.AlignHCenter),
               f"{4 * seg} m")
    p.setFont(font(10, True))
    p.drawText(QRectF(x0, y0 - 18, 200, 14), int(Qt.AlignmentFlag.AlignLeft), f"Scale 1:{scale:g} (A3)")

    # key plan
    if key_rect is not None:
        _key_plan(p, d, key_rect, s0, s1, font)
    if list_rect is not None:
        _sign_list(p, mine, list_rect, font)
    return len(mine)


def _key_plan(p, d, r, s0, s1, font):
    al = d.al
    pts = [al.point_at(al.sta_start + al.length * k / 400)[:2] for k in range(401)]
    xs, ys = [q[0] for q in pts], [q[1] for q in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    inner = r.adjusted(10, 22, -10, -10)
    sc = min(inner.width() / max(w, 1), inner.height() / max(h, 1))
    ox = inner.center().x() - (min(xs) + w / 2) * sc
    oy = inner.center().y() + (min(ys) + h / 2) * sc
    Q = lambda x, y: QPointF(ox + x * sc, oy - y * sc)
    p.setPen(QPen(QColor("#c9d0da"), 1)); p.setBrush(QColor("#fafbfd")); p.drawRect(r)
    p.setPen(QColor("#1d2430")); p.setFont(font(10, True))
    p.drawText(QRectF(r.left() + 8, r.top() + 4, r.width() - 16, 14), int(Qt.AlignmentFlag.AlignLeft), "Key plan")
    path = QPainterPath(Q(*pts[0]))
    for q in pts[1:]:
        path.lineTo(Q(*q))
    p.setPen(QPen(QColor("#9aa3b2"), 1.6)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
    seg = [al.point_at(s0 + (s1 - s0) * k / 60)[:2] for k in range(61)]
    path = QPainterPath(Q(*seg[0]))
    for q in seg[1:]:
        path.lineTo(Q(*q))
    p.setPen(QPen(QColor("#c0392b"), 3.2)); p.drawPath(path)
    p.setFont(font(8)); p.setPen(QColor("#6b7686"))
    for s in (al.sta_start, al.sta_end):
        p.drawText(Q(*al.point_at(s)[:2]) + QPointF(4, -4), format_station(al.display_station(s), 0))


def _sign_list(p, signs, r, font):
    p.setPen(QPen(QColor("#c9d0da"), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
    p.setPen(QColor("#1d2430")); p.setFont(font(10, True))
    p.drawText(QRectF(r.left() + 8, r.top() + 4, r.width() - 16, 14), int(Qt.AlignmentFlag.AlignLeft),
               f"Signs on this sheet ({len(signs)})")
    rows = [(s["post"], s["chainage"], s["side"], s["code"], s["name"]) for s in signs]
    rh = 13.0
    per_col = max(1, int((r.height() - 26) / rh))
    cols = 3
    cw = (r.width() - 16) / cols
    shown = rows[:per_col * cols]
    p.setFont(font(9))
    for i, (post, ch, side, code, name) in enumerate(shown):
        c, k = divmod(i, per_col)
        x = r.left() + 8 + c * cw
        y = r.top() + 22 + k * rh
        p.setPen(QColor("#1d2430"))
        p.drawText(QRectF(x, y, cw - 6, rh), int(Qt.AlignmentFlag.AlignVCenter),
                   f"{post:<5} {ch:>9} {side}  {code:<6} {name}"[:62])
    if len(rows) > len(shown):
        p.setPen(QColor("#6b7686"))
        p.drawText(QRectF(r.left() + 8, r.bottom() - 14, r.width() - 16, 12), int(Qt.AlignmentFlag.AlignRight),
                   f"+{len(rows) - len(shown)} more - see the sign schedule")
