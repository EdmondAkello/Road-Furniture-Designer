"""Supplementary signs from the Ministry's standard drawings WSCM/84/2/01 (Jan 2024).

    python tools/extract_wscm_signs.py <WSCM warning sheet.pdf> <WSCM other signs sheet.pdf>

The two A3 sheets (Standard Traffic Signs: Warning Signs, sheet 1/2; Regulatory, Mandatory and
Information Signs, sheet 2/2) number signs differently from RDM 6.2, and many of their numbers are
also live RDM codes for other signs (WSCM W1 is a sharp left turn, RDM W1 is not). Only the signs
with no RDM 6.2 equivalent are extracted (WANTED), always under a ``WSCM-`` code so they can never
be confused with an RDM sign. Every other sign on the sheets is mapped to its RDM 6.2 code in
``rfd/data/wscm_crossref.json``.

Writes ``rfd/data/signs/WSCM-*.svg``, adds ``RSD_WSCM-*`` blocks to ``rfd/data/RSD_SignBlocks.dxf``
(existing blocks are left alone) and ``rfd/data/wscm_signs.json``; then run build_catalogue.py.
"""
import json
import os
import re
import sys

import pymupdf as fitz

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "rfd", "data")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
from extract_rdm_signs import add_block, artwork, to_svg  # noqa: E402

SOURCE = "WSCM/84/2/01 Standard Traffic Signs (Jan 2024), Ministry of Roads and Transport, Kenya"
# WSCM code -> (name, functional category, legend type); the signs with no RDM 6.2 equivalent
WANTED = {
    "I1": ("Start of Climbing Lane", "Information", None),
    "I2": ("End of Climbing Lane", "Information", None),
    "I3": ("Bus Stop", "Information", None),
    "I6": ("Hotel or Motel", "Information", None),
    "I10": ("One Way Traffic", "Information", None),
    "M2": ("Road Closed", "Prohibitory", None),
    "M3": ("No Entry for Pedestrians", "Prohibitory", None),
    "M8": ("End of No Overtaking Section", "Prohibitory", None),
    "M9": ("Overtaking of Goods Vehicles Prohibited", "Prohibitory", None),
    "M14": ("End of All Prohibitions", "Prohibitory", None),
    # M16 / M17: the value (10 m, 70 m) is drawn as shapes on the sheet, so it is fixed artwork
    "M16": ("No Entry for Vehicles Exceeding the Length Shown (10 m as drawn)", "Prohibitory", None),
    "M17": ("Driving Vehicles Less than the Distance Shown Apart Prohibited (70 m as drawn)", "Prohibitory", None),
    "W22": ("River Bed Crossing (Drift)", "Warning", None),
    "W25": ("Section Frequented by Cyclists", "Warning", None),
    "W34": ("Hazard Ahead", "Warning", None),
    "W37": ("Road Surface of Loose Stones Ahead", "Warning", None),
    "W39": ("Soft Verges", "Warning", None),
    "W42": ("Railway Crossing, One Track", "Warning", None),
    "W43": ("Railway Crossing, More than One Track", "Warning", None),
}
COLUMN = 54.0          # half the column pitch on the sheets (pt)
# Drafting slips on the sheets, corrected so the sign matches its series (and noted in the catalogue)
RED_BORDER = {"W22": "the drawing shows the border hatched in black; drawn with the red border of every other "
                     "warning sign on the sheet"}


def red_border(svg):
    """Replace a warning triangle's hatched black border with the series' red band and black outline;
    keep only the symbol strokes inside the band."""
    import re as _re
    w, h = (float(v) for v in _re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    pad, band = 1.6, 0.115 * h
    A, B, C = (pad, h - pad), (w - pad, h - pad), (w / 2, pad)

    def inset(t):
        # triangle shrunk by distance t (equilateral-ish: move each vertex toward the incentre)
        ax, ay = A; bx, by = B; cx, cy = C
        la, lb, lc = (((bx - cx) ** 2 + (by - cy) ** 2) ** .5, ((ax - cx) ** 2 + (ay - cy) ** 2) ** .5,
                      ((ax - bx) ** 2 + (ay - by) ** 2) ** .5)
        ix, iy = (la * ax + lb * bx + lc * cx) / (la + lb + lc), (la * ay + lb * by + lc * cy) / (la + lb + lc)
        area = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2
        r = 2 * area / (la + lb + lc)
        k = (r - t) / r
        return [(ix + (x - ix) * k, iy + (y - iy) * k) for x, y in (A, B, C)]

    paths = []
    for m in _re.finditer(r'<path d="([^"]*)" ([^/]*)/>', svg):
        nums = [float(v) for v in _re.findall(r"-?\d+\.?\d*", m.group(1))]
        paths.append((m.group(0), list(zip(nums[0::2], nums[1::2]))))
    # the drawing's inner border: the largest closed triangle (3 corners + close) clear of the outer edge
    tris = [pts for _, pts in paths if len(pts) == 4 and max(y for _, y in pts) < h - 5]
    if tris:
        t = max(tris, key=lambda q: (max(x for x, _ in q) - min(x for x, _ in q)) * (max(y for _, y in q) - min(y for _, y in q)))
        inner = t[:3]
    else:
        inner = inset(band)

    def inside(x, y, tri):
        (x1, y1), (x2, y2), (x3, y3) = tri
        d = lambda ax, ay, bx, by, cx, cy: (ax - cx) * (by - cy) - (bx - cx) * (ay - cy)
        s1, s2, s3 = d(x, y, x1, y1, x2, y2), d(x, y, x2, y2, x3, y3), d(x, y, x3, y3, x1, y1)
        return not ((s1 < 0 or s2 < 0 or s3 < 0) and (s1 > 0 or s2 > 0 or s3 > 0))

    cx_, cy_ = sum(x for x, _ in inner) / 3, sum(y for _, y in inner) / 3
    grown = [(cx_ + (x - cx_) * 1.03, cy_ + (y - cy_) * 1.03) for x, y in inner]
    keep = [txt for txt, pts in paths if pts and pts[:3] != inner[:3] and all(inside(x, y, grown) for x, y in pts)]
    tri = lambda t: "M" + " L".join(f"{x:.2f} {y:.2f}" for x, y in t) + " Z"
    head = svg[:svg.index(">") + 1]
    # rounded outer corners, as on every other warning sign on the sheet: a triangle shrunk by the corner
    # radius, stroked with round joins, gives the outer shape; black outline under the red band
    rad = 0.05 * h
    core = inset(rad)
    body = [f'<path d="{tri(core)}" fill="#000000" stroke="#000000" stroke-width="{2 * rad + 1.0:.2f}" '
            f'stroke-linejoin="round"/>',
            f'<path d="{tri(core)}" fill="#ff0000" stroke="#ff0000" stroke-width="{2 * rad:.2f}" '
            f'stroke-linejoin="round"/>',
            f'<path d="{tri(inner)}" fill="#ffffff" stroke="#000000" stroke-width="0.4"/>'] + keep
    return head + "\n" + "\n".join(body) + "\n</svg>"


FRAME = {"I1": "the drawn frame stops short of the corners and a stray blue arc sits on it; drawn with a closed, "
                "rounded frame", "I2": "the drawn frame stops short of the corners; drawn with a closed, rounded frame"}


def clean_frame(svg: str) -> str:
    """Replace a frame drawn as four bars short of the corners (and stray blue strokes) with one rounded frame."""
    vb = [float(x) for x in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    W, H = vb[2], vb[3]
    m = 0.06 * min(W, H)
    out = []
    for p in re.findall(r"<path [^>]*/>", svg):
        if re.search(r'stroke="#1d24e2"', p):
            continue                                                       # stray blue strokes
        nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", re.search(r'd="([^"]+)"', p).group(1))]
        xs, ys = nums[0::2], nums[1::2]
        thin = min(max(xs) - min(xs), max(ys) - min(ys)) < 1.5
        on_edge = max(xs) < m or min(xs) > W - m or max(ys) < m or min(ys) > H - m
        if thin and on_edge:
            continue                                                       # a bar of the broken frame
        out.append(p)
    sw, r = 0.012 * min(W, H), 0.05 * min(W, H)
    frame = (f'<rect x="{1.2 + sw / 2:.2f}" y="{1.2 + sw / 2:.2f}" width="{W - 2.4 - sw:.2f}" '
             f'height="{H - 2.4 - sw:.2f}" rx="{r:.2f}" fill="#ffffff" stroke="#000000" stroke-width="{sw:.2f}"/>')
    head = svg[:svg.index(">") + 1]
    return head + "\n" + frame + "\n" + "\n".join(out) + "\n</svg>"


SEAM = re.compile(r'<path d="([^"]+)" fill="(#[0-9a-fA-F]{6})"\s*/>')


def close_seams(svg: str) -> str:
    """The sheets fill colour as meshes of small triangles; antialiased renderers leave hairline seams
    between them, which reads as a scratchy texture. Stroke each piece in its own colour to close them."""
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    w = 0.004 * max(float(vb.group(1)), float(vb.group(2))) if vb else 0.35
    return SEAM.sub(lambda m: f'<path d="{m.group(1)}" fill="{m.group(2)}" stroke="{m.group(2)}" '
                              f'stroke-width="{w:.2f}" stroke-linejoin="round"/>', svg)


def _buffer(poly, r, n=8):
    """Convex polygon grown by r with round corners (what a round-joined stroke of width 2r draws)."""
    import math
    k = len(poly)
    area = sum(poly[i][0] * poly[(i + 1) % k][1] - poly[(i + 1) % k][0] * poly[i][1] for i in range(k))
    sgn = 1.0 if area > 0 else -1.0

    def out_angle(p, q):                                  # outward normal of edge p -> q
        dx, dy = q[0] - p[0], q[1] - p[1]
        return math.atan2(-dx * sgn, dy * sgn)

    pts = []
    for i in range(k):
        a, b, c = poly[i - 1], poly[i], poly[(i + 1) % k]
        a0, a1 = out_angle(a, b), out_angle(b, c)
        d = (a1 - a0) % (2 * math.pi)
        if sgn < 0:
            d -= 2 * math.pi
        pts += [(b[0] + r * math.cos(a0 + d * j / n), b[1] + r * math.sin(a0 + d * j / n)) for j in range(n + 1)]
    return pts


def svg_block(dxf, name, svg, cy=0.95):
    """A CAD block drawn from a corrected icon (straight-segment paths and rects), same convention as
    add_block: larger side 1.0, centred at (0, cy), post at the origin."""
    import math
    vb = [float(x) for x in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    W, H = vb[2], vb[3]
    sc = 1.0 / max(W, H)
    T = lambda x, y: ((x - W / 2) * sc, cy - (y - H / 2) * sc)
    rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    blk = dxf.blocks.new(name, base_point=(0, 0))
    blk.add_circle((0, 0), 0.06, dxfattribs={"layer": "0"})
    blk.add_line((-0.35, 0.12), (0.35, 0.12))
    blk.add_line((0, 0), (0, 0.12))

    def attr(el, k):
        m = re.search(k + r'="([^"]+)"', el)
        return m.group(1) if m else None

    for el in re.findall(r"<(?:path|rect) [^>]*/>", svg):
        fill, stroke = attr(el, "fill"), attr(el, "stroke")
        sw = float(attr(el, "stroke-width") or 0)
        if el.startswith("<rect"):
            x, y, w, h = (float(attr(el, k)) for k in ("x", "y", "width", "height"))
            r = float(attr(el, "rx") or 0)
            pts = []
            for (qx, qy, a0) in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90),
                                 (x + r, y + r, 180)):
                pts += [(qx + r * math.cos(math.radians(a0 + 90 * j / 6)), qy + r * math.sin(math.radians(a0 + 90 * j / 6)))
                        for j in range(7)]
            subs = [pts]
        else:
            subs = []
            for part in re.split(r"(?=M)", attr(el, "d")):
                nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", part)]
                if len(nums) >= 4:
                    subs.append(list(zip(nums[0::2], nums[1::2])))
        grow = fill and stroke == fill and 'stroke-linejoin="round"' in el and sw * sc > 0.01
        if fill and fill != "none":
            hch = blk.add_hatch(dxfattribs={"layer": "0"})
            hch.set_solid_fill()
            hch.rgb = rgb(fill)
            for sp in subs:
                sp = _buffer(sp, sw / 2) if grow else sp
                if len(sp) >= 3:
                    hch.paths.add_polyline_path([T(*q) for q in sp], is_closed=True)
        if stroke and stroke != "none" and not grow and (fill in (None, "none") or stroke != fill):
            for sp in subs:
                pl = blk.add_lwpolyline([T(*q) for q in sp], close=el.startswith("<rect") or "Z" in (attr(el, "d") or ""))
                pl.rgb = rgb(stroke)
    return blk


def labels(pg):
    out = {}
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                t = s["text"].strip()
                if re.fullmatch(r"[RMIW]\s?\d{1,2}", t):
                    out[t.replace(" ", "")] = fitz.Rect(s["bbox"])
    return out


def region(pg, lab):
    """From just below the code label to just above the sign's name, one column wide."""
    cx = (lab.x0 + lab.x1) / 2
    top = lab.y1 + 1.0
    below = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                r = fitz.Rect(s["bbox"])
                if s["text"].strip() and abs((r.x0 + r.x1) / 2 - cx) < COLUMN and r.y0 > top + 30 \
                        and s["size"] < 8.5 and "Arial" in s["font"]:
                    below.append(r.y0)
    bottom = min(below) - 1.0 if below else top + 150
    return fitz.Rect(cx - COLUMN, top, cx + COLUMN, bottom)


def main(*pdfs):
    import ezdxf
    from rfd.dxf_out import APPID, ATTRS, VISIBLE
    lib = os.path.join(DATA, "RSD_SignBlocks.dxf")
    dxf = ezdxf.readfile(lib)
    if APPID not in dxf.appids:
        dxf.appids.new(APPID)
    entries, found = [], set()
    for pdf in pdfs:
        doc = fitz.open(pdf)
        pg = doc[0]
        labs = labels(pg)
        for wcode, (name, cat, legend) in WANTED.items():
            if wcode not in labs or wcode in found:
                continue
            art = artwork(pg, region(pg, labs[wcode]))
            if art is None:
                continue
            found.add(wcode)
            code = "WSCM-" + wcode
            svg = to_svg(art)
            if wcode in RED_BORDER:
                svg = red_border(svg)
            if wcode in FRAME:
                svg = clean_frame(svg)
            svg = close_seams(svg)
            with open(os.path.join(DATA, "signs", code + ".svg"), "w", encoding="utf-8") as fh:
                fh.write(svg)
            corrected = wcode in FRAME or wcode in RED_BORDER
            if corrected and "RSD_" + code in dxf.blocks:
                dxf.blocks.delete_block("RSD_" + code, safe=False)        # rebuilt from the corrected icon
            if "RSD_" + code not in dxf.blocks:
                blk = svg_block(dxf, "RSD_" + code, svg) if corrected else add_block(dxf, "RSD_" + code, art)
                for i, tag in enumerate(ATTRS):
                    a = blk.add_attdef(tag, insert=(0.7, 0.9 - 0.18 * i), height=0.15,
                                       dxfattribs={"layer": "RSD-SIGN-TEXT"})
                    a.is_invisible = tag not in VISIBLE
            b = art["box"]
            shp = {"W": "triangle", "M": "circle", "I": "rectangle"}[wcode[0]]     # by WSCM series
            if wcode in ("W42", "W43"):
                shp = "rectangle"                                                  # railway crosses: no triangle
            entries.append({"code": code, "wscm_code": wcode, "name": name, "category": cat, "shape": shp,
                            "legend": legend, "aspect": round(b.width / b.height, 3),
                            "drawing": "WSCM/84/2/01", "sheet": "1/2" if wcode.startswith("W") else "2/2",
                            "correction": RED_BORDER.get(wcode, FRAME.get(wcode, ""))})
    missing = sorted(set(WANTED) - found)
    dxf.saveas(lib)
    with open(os.path.join(DATA, "wscm_signs.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": SOURCE, "signs": sorted(entries, key=lambda e: (e["code"][5], int(e["code"][6:]))),
                   "missing": missing}, fh, indent=1)
    print(f"{len(entries)} WSCM signs extracted; missing: {missing}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(*sys.argv[1:])
