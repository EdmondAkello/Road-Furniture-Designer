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
            with open(os.path.join(DATA, "signs", code + ".svg"), "w", encoding="utf-8") as fh:
                fh.write(svg)
            if "RSD_" + code not in dxf.blocks:
                blk = add_block(dxf, "RSD_" + code, art)
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
                            "correction": RED_BORDER.get(wcode, "")})
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
