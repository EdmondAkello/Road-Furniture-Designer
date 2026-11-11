"""Road furniture pages of the report: strip diagram, schedules and checks.

The data comes from rfd.furniture_report (ReportData.fr); this
module only paginates and paints it with the frame and fonts of report.py.
"""
from __future__ import annotations

import math

from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFontMetrics, QPen, QPolygonF

from .report import BOTTOM, COL, M, TOP, W, _font, draw_frame, sheet_windows
from .rfd.alignment import format_station

STRIP_LEN = 1000.0              # m of road per strip
STRIPS_PER_PAGE = 3
LANE_H = {"ticks": 34.0, "bars": 18.0}
MARK_COL = {"white": "#4f5a69", "yellow": "#d9a400"}
LEVEL_TEXT = {"issue": "Issue", "check": "Check", "info": "Info"}
WRAP = int(Qt.TextFlag.TextWordWrap) if hasattr(Qt, "TextFlag") else int(Qt.TextWordWrap)
AL_LEFT = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)


# --------------------------------------------------------------------------- strip diagram
def strip_windows(al):
    return sheet_windows(al, STRIP_LEN)


def strip_pages(al):
    w = strip_windows(al)
    return [w[i:i + STRIPS_PER_PAGE] for i in range(0, len(w), STRIPS_PER_PAGE)]


def _colour(d, code):
    it = d.lcat.items.get(code) if d.lcat is not None else None
    return MARK_COL.get(getattr(it, "colour", "white"), MARK_COL["white"])


def draw_strip_page(p, d, windows, page, pages):
    al = d.al
    a, b = windows[0][0], windows[-1][1]
    rng = f"CH {format_station(al.display_station(a), 0)} – {format_station(al.display_station(b), 0)}"
    draw_frame(p, d, d.title, f"Road furniture strip diagram {rng}", page, pages, "NTS")
    lanes = d.fr.lanes
    body = sum(LANE_H[ln.kind] for ln in lanes) + 22
    gap = (BOTTOM - TOP - 40 - STRIPS_PER_PAGE * body) / max(STRIPS_PER_PAGE, 1)
    y = TOP + 4
    for s0, s1 in windows:
        _draw_strip(p, d, lanes, s0, s1, y)
        y += body + gap
    _strip_legend(p, BOTTOM - 30)


def _draw_strip(p, d, lanes, s0, s1, top):
    al = d.al
    left, right = M + 130, W - M - 10
    xs = lambda s: left + (s - s0) / STRIP_LEN * (right - left)
    end_x = xs(s1)
    y = top
    rows = []
    for ln in lanes:
        h = LANE_H[ln.kind]
        rows.append((ln, QRectF(left, y, end_x - left, h)))
        y += h
    # lane frames and labels
    for i, (ln, r) in enumerate(rows):
        if i % 2:
            p.fillRect(r, QColor("#f7f9fc"))
        p.setPen(QColor(COL["ink"])); p.setFont(_font(10, ln.kind == "ticks"))
        p.drawText(QRectF(M, r.top(), left - M - 6, r.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), ln.name)
    box = QRectF(left, top, end_x - left, y - top)
    p.setPen(QPen(QColor("#c9d0da"), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(box)
    # chainage grid and axis
    p.setFont(_font(10))
    s = math.ceil(s0 / 100.0) * 100.0
    while s <= s1 + 1e-6:
        x = xs(s)
        p.setPen(QPen(QColor(COL["grid"]), 1)); p.drawLine(QPointF(x, top), QPointF(x, y))
        p.setPen(QColor(COL["muted"]))
        p.drawText(QRectF(x - 40, y + 3, 80, 14), int(Qt.AlignmentFlag.AlignHCenter),
                   format_station(al.display_station(s), 0))
        s += 100.0
    for ln, r in rows:
        if ln.kind == "bars":
            for a, b, style, label, prop in ln.items:
                a, b = max(a, s0), min(b, s1)
                if b <= a:
                    continue
                _bar(p, d, r, xs(a), xs(b), style, label, prop)
        else:
            _ticks(p, r, [t for t in ln.items if s0 <= t[0] <= s1], xs)


def _bar(p, d, r, x0, x1, style, label, prop):
    cy = r.center().y()
    if prop:                                          # proposed, not accepted: light orange band behind the item
        band = QColor(COL["prop"]); band.setAlpha(45)
        p.fillRect(QRectF(x0, r.top() + 1, x1 - x0, r.height() - 2), band)
    if style == "noov":
        p.fillRect(QRectF(x0, cy - 4, x1 - x0, 8), QColor(COL["noov"]))
        return
    if style == "speed":
        p.setPen(QPen(QColor("#c0392b"), 1.2)); p.setBrush(QColor("#fdecea"))
        p.drawRect(QRectF(x0, cy - 6, x1 - x0, 12)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor("#c0392b")); p.setFont(_font(9, True))
        p.drawText(QRectF(x0 + 4, cy - 6, max(x1 - x0 - 8, 10), 12),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        return
    if style == "barrier":
        p.setPen(QPen(QColor("#2b2f36"), 3.2)); p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
        p.setPen(QPen(QColor("#2b2f36"), 1))
        step = max(6.0, (x1 - x0) / max(1, int((x1 - x0) / 8)))
        x = x0
        while x <= x1 + 1e-6:
            p.drawLine(QPointF(x, cy - 4), QPointF(x, cy + 4)); x += step
        p.setBrush(QColor("#2b2f36")); p.setPen(Qt.PenStyle.NoPen)
        for x, sg in ((x0, -1), (x1, 1)):
            p.drawPolygon(QPolygonF([QPointF(x, cy - 6), QPointF(x, cy + 6), QPointF(x + sg * 7, cy)]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        return
    col = QColor(_colour(d, label.split()[0]) if label else COL["ink"])
    solid = QPen(col, 2.4)
    dash = QPen(col, 2.4, Qt.PenStyle.DashLine)
    if style == "stud":
        p.setPen(QPen(col, 2.6, Qt.PenStyle.DotLine)); p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
    elif style in ("continuous", "broken"):
        p.setPen(solid if style == "continuous" else dash); p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
    else:                                             # two lines: upper = left of the chainage direction
        up, lo = {"double": (solid, solid), "cls_fwd": (solid, dash), "cls_bwd": (dash, solid)}[style]
        p.setPen(up); p.drawLine(QPointF(x0, cy - 3), QPointF(x1, cy - 3))
        p.setPen(lo); p.drawLine(QPointF(x0, cy + 3), QPointF(x1, cy + 3))
    if label and x1 - x0 > 60 and style != "stud":
        p.setPen(QColor(COL["muted"])); p.setFont(_font(8))
        p.drawText(QRectF(x0 + 2, r.top() - 1, min(x1 - x0, 120), 9), int(Qt.AlignmentFlag.AlignLeft), label)


def _ticks(p, r, items, xs):
    fm = QFontMetrics(_font(9, True))
    right_edge = [-1e9, -1e9]
    for s, style, label, prop in items:
        x = xs(s)
        col = QColor(COL["prop"] if prop else (COL["curve"] if style == "feature" else COL["ink"]))
        half = fm.horizontalAdvance(label) / 2 + 2
        row = 0 if x - half > right_edge[0] else (1 if x - half > right_edge[1] else
                                                  (0 if right_edge[0] <= right_edge[1] else 1))
        right_edge[row] = x + half
        ty = r.top() + 2 + row * 15
        p.setPen(QPen(col, 1.2)); p.drawLine(QPointF(x, ty + 12), QPointF(x, r.bottom() - 1))
        if style == "feature":
            p.setBrush(col); p.setPen(Qt.PenStyle.NoPen)
            cy = r.bottom() - 6
            p.drawPolygon(QPolygonF([QPointF(x, cy - 5), QPointF(x + 5, cy), QPointF(x, cy + 5), QPointF(x - 5, cy)]))
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(col); p.setFont(_font(9, True))
        p.drawText(QRectF(x - 50, ty, 100, 12), int(Qt.AlignmentFlag.AlignHCenter), label)


def _strip_legend(p, y):
    p.setFont(_font(11))
    x = M + 130
    items = [("solid", MARK_COL["yellow"], "Continuous line"), ("dash", MARK_COL["yellow"], "Broken line"),
             ("pair", MARK_COL["yellow"], "Combined line: continuous line on the side it binds"),
             ("dot", MARK_COL["white"], "Road studs"), ("bar", "#2b2f36", "Barrier with terminals"),
             ("fill", COL["noov"], "No-overtaking zone (PSD basis)"), ("prop", COL["prop"], "Proposed, not accepted")]
    for kind, col, txt in items:
        c = QColor(col)
        if kind == "fill":
            p.fillRect(QRectF(x, y + 4, 24, 6), c)
        elif kind == "prop":
            c.setAlpha(60); p.fillRect(QRectF(x, y + 1, 24, 14), c)
        else:
            pen = QPen(c, 3.0 if kind == "bar" else 2.4,
                       {"dash": Qt.PenStyle.DashLine, "dot": Qt.PenStyle.DotLine}.get(kind, Qt.PenStyle.SolidLine))
            p.setPen(pen)
            if kind == "pair":
                p.drawLine(QPointF(x, y + 4), QPointF(x + 24, y + 4))
                p.setPen(QPen(c, 2.4, Qt.PenStyle.DashLine)); p.drawLine(QPointF(x, y + 10), QPointF(x + 24, y + 10))
            else:
                p.drawLine(QPointF(x, y + 7), QPointF(x + 24, y + 7))
        p.setPen(QColor(COL["ink"])); p.drawText(QRectF(x + 30, y, 400, 16), int(Qt.AlignmentFlag.AlignLeft), txt)
        x += 46 + QFontMetrics(_font(11)).horizontalAdvance(txt)
    p.setPen(QColor(COL["muted"])); p.setFont(_font(10))
    p.drawText(QRectF(M + 130, y + 16, W - 2 * M - 130, 14), int(Qt.AlignmentFlag.AlignLeft),
               "Top of each strip: left side of the road, traffic travelling up-chainage. Signs and features: "
               "code at the post chainage. Calming items, bar sets and crossings are listed in the features schedule.")


# --------------------------------------------------------------------------- wrapped tables
FONT_PX = 11
PAD = 4.0


def _row_height(vals, widths, scale, bold=False):
    fm = QFontMetrics(_font(FONT_PX, bold))
    h = 0.0
    for v, w in zip(vals, widths):
        r = fm.boundingRect(QRectF(0, 0, w * scale - 2 * PAD, 10000).toRect(), WRAP, str(v))
        h = max(h, r.height())
    return h + 2 * PAD


def paginate(header, rows, widths, note=""):
    """Split rows into pages by their wrapped heights."""
    scale = (W - 2 * M) / sum(widths)
    avail = BOTTOM - TOP - 10 - _row_height(header, widths, scale, True) - (_note_h(note) if note else 0)
    out, cur, used = [], [], 0.0
    for r in rows:
        h = _row_height(r, widths, scale)
        if cur and used + h > avail:
            out.append(cur); cur, used = [], 0.0
            avail = BOTTOM - TOP - 10 - _row_height(header, widths, scale, True)
        cur.append(r); used += h
    out.append(cur)
    return out


def _note_h(note):
    fm = QFontMetrics(_font(11))
    return fm.boundingRect(QRectF(0, 0, W - 2 * M, 1000).toRect(), WRAP, note).height() + 10


def draw_wrapped_table(p, d, title, header, rows, widths, page, pages, note="", shade=None, boxes=()):
    """shade: (column index, {value: colour}) to tint a cell by its value; boxes: columns drawn as boxes to fill in."""
    draw_frame(p, d, d.title, title, page, pages, "NTS")
    scale = (W - 2 * M) / sum(widths)
    y = TOP + 4
    if note:
        p.setPen(QColor(COL["muted"])); p.setFont(_font(11))
        h = _note_h(note)
        p.drawText(QRectF(M, y, W - 2 * M, h), WRAP | AL_LEFT, note)
        y += h

    def row(vals, bold=False, bg=None):
        nonlocal y
        h = _row_height(vals, widths, scale, bold)
        if bg:
            p.fillRect(QRectF(M, y, W - 2 * M, h), QColor(bg))
        x = M
        for i, (v, w) in enumerate(zip(vals, widths)):
            if shade and i == shade[0] and str(v) in shade[1] and not bold:
                p.fillRect(QRectF(x, y, w * scale, h), QColor(shade[1][str(v)]))
            if i in boxes and not bold:
                p.setPen(QPen(QColor("#9aa3b2"), 0.8)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(x + 2, y + 2, w * scale - 4, h - 4))
            p.setPen(QColor(COL["ink"])); p.setFont(_font(FONT_PX, bold))
            p.drawText(QRectF(x + PAD, y + PAD, w * scale - 2 * PAD, h - 2 * PAD), WRAP | AL_LEFT, str(v))
            x += w * scale
        p.setPen(QPen(QColor(COL["grid"]), 0.8)); p.drawLine(QPointF(M, y + h), QPointF(W - M, y + h))
        y += h

    row(header, True, "#e8edf4")
    for r in rows:
        row(r)


# --------------------------------------------------------------------------- the tables
def _ch(d, s):
    return format_station(d.al.display_station(s), 0)


MARK_HEAD = ["Code", "Description", "From", "To", "Length (m)", "Side", "Offset (m)", "Pattern / interval",
             "Quantity", "Unit", "Area (m²)", "Status"]
MARK_W = [6, 22, 7, 7, 7, 4, 8, 24, 7, 4, 7, 7]
BAR_HEAD = ["Item", "From", "To", "Length (m)", "Side", "Offset (m)", "Terminals", "Status", "Basis"]
BAR_W = [6, 7, 7, 7, 4, 9, 6, 7, 58]
FEAT_HEAD = ["Chainage", "Feature", "Detail", "Items", "Signs", "Checks", "Status"]
FEAT_W = [7, 15, 34, 14, 8, 30, 7]
QTY_HEAD = ["Category", "Item", "Description", "Pattern", "Unit", "Quantity"]
QTY_W = [14, 9, 38, 28, 6, 9]
CHK_HEAD = ["Level", "From", "To", "Side", "Check", "Detail"]
CHK_W = [6, 7, 7, 7, 18, 70]
FEATURE_TEXT = {"hump_circular": "Circular hump", "hump_trapezoidal": "Trapezoidal hump", "speed_table": "Speed table",
                "raised_crossing": "Raised crossing", "speed_bump": "Speed bump", "bar_marking": "Bar markings",
                "crossing": "Zebra crossing", "other": "Feature"}


def marking_rows(d):
    return [[m["code"], m["name"], _ch(d, m["from"]), _ch(d, m["to"]), f"{m['length']:.1f}", m["side"],
             (f"{m['offset']:.2f} {m['edge']}".strip() if m["side"] != "C" else ""), m["detail"],
             m["qty"], m["unit"], (f"{m['area']:.1f}" if m["area"] is not None else ""), m["status"]]
            for m in d.fr.markings]


def barrier_rows(d):
    return [[m["code"], _ch(d, m["from"]), _ch(d, m["to"]), f"{m['length']:.1f}", m["side"],
             f"{m['offset']:.2f} {('from ' + m['edge']) if m['edge'] else 'from CL'}", m["terminals"] or "",
             m["status"], m["reason"]] for m in d.fr.barriers]


def feature_rows(d):
    out = []
    for g in d.fr.features:
        items = {}
        for c in g["codes"]:
            items[c] = items.get(c, 0) + 1
        checks = "; ".join(c.text.split(": ", 1)[-1] for c in g.get("checks", [])) or "none"
        out.append([_ch(d, g["station"]), FEATURE_TEXT.get(g["kind"], g["kind"]), g["detail"],
                    ", ".join(f"{n} x {c}" if n > 1 else c for c, n in items.items()),
                    ", ".join(g["sign_codes"]) or "-", checks, g["status"]])
    return out


JN_HEAD = ["Chainage", "Type", "Minor road", "Angle", "Scale", "Islands", "Kerb (m)", "Island area (m²)",
           "Markings: length (m) / area (m²)", "Status"]
JN_W = [7, 6, 7, 6, 5, 22, 7, 8, 35, 7]


def junction_rows(d):
    out = []
    for j in getattr(d, "junction_list", []) or []:
        isl = sorted(p for p in j["pieces"] if "island" in p or "splitter" in p)
        marks = ", ".join(f"{c} {v[0]:.0f} / {v[1]:.1f}" for c, v in sorted(j["paint"].items()))
        side = ("Joins " + (j["main_ref"][4:] if j.get("main_ref", "").startswith("alg:") else "main road")
                if j.get("role") == "minor" else ("Left" if j["side"] == "L" else "Right"))
        out.append([j["ch"], j["kit"], side, f"{j['crossing_deg']:.0f}°",
                    f"{j['scale']:g}", ", ".join(i.replace("_", " ") for i in isl) or "-",
                    f"{j['kerb_m']:.1f}", f"{j['island_m2']:.1f}", marks or "-", j["status"] or ""])
    return out


def junction_note(d):
    return ("Islands and markings placed from the standard drawings RDM/1/3/2/01-02 as templates and fitted by "
            "the designer; kerb lines, control radii and entry widths come from the junction design. Areas are "
            "painted areas (line length x line width).")


def quantity_rows(d):
    return [[c, code, name, pat, unit, q] for c, code, name, pat, unit, q in d.fr.quantities]


def check_rows(d):
    from .rfd.furniture_report import KIND_TEXT
    side = {"L": "Left", "R": "Right", "C": "Centre"}
    return [[LEVEL_TEXT[c.level], _ch(d, c.start), _ch(d, c.end), side.get(c.side, c.side),
             KIND_TEXT.get(c.kind, c.kind), c.text] for c in d.fr.checks] + \
           [["Info", "", "", "", "Note", n] for n in d.fr.notes]


TABLES = [
    ("markings", "Markings and road studs schedule (RDM 6.1)", MARK_HEAD, MARK_W, marking_rows, None),
    ("barriers", "Safety barrier schedule (RDM 1.3 Chapter 12)", BAR_HEAD, BAR_W, barrier_rows, None),
    ("features", "Traffic calming and crossings (RDM 6.4 / 6.1)", FEAT_HEAD, FEAT_W, feature_rows, None),
    ("junctions", "Junction islands and markings (RDM/1/3/2/01-02, RDM 6.1)", JN_HEAD, JN_W, junction_rows,
     junction_note),
    ("fquantities", "Road furniture quantities (linear items)", QTY_HEAD, QTY_W, quantity_rows, None),
    ("checks", "Road furniture checks against the geometry", CHK_HEAD, CHK_W, check_rows, None),
]


def furniture_pages(d):
    """[(kind, payload)] for report.pages()."""
    if d.fr is None:
        return []
    out = [("strip", w) for w in strip_pages(d.al)]
    for key, title, head, widths, rows_fn, note_fn in TABLES:
        rows = rows_fn(d)
        if not rows:
            continue
        note = note_fn(d) if note_fn else ""
        for k, chunk in enumerate(paginate(head, rows, widths, note)):
            out.append(("ftable", (key, chunk, note if k == 0 else "")))
    return out


def draw_furniture_page(p, d, kind, payload, i, n):
    if kind == "strip":
        draw_strip_page(p, d, payload, i, n)
        return
    key, chunk, note = payload
    _, title, head, widths, _, _ = next(t for t in TABLES if t[0] == key)
    shade = (0, {"Issue": "#fde2e1", "Check": "#fff4d6"}) if key == "checks" else None
    draw_wrapped_table(p, d, title, head, chunk, widths, i, n, note, shade)
