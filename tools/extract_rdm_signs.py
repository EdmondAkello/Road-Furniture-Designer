"""Extract sign artwork and catalogue entries from RDM 6.2 (Traffic Signs, 2025).

    python tools/extract_rdm_signs.py RDM_6.2_Traffic_Signs.pdf [WSCM_warning.pdf WSCM_other.pdf]

Outputs (under rfd/data/):
    signs/<CODE>.svg       vector icon, artwork only (dimension lines and notes removed)
    rdm_signs.json         code, name, figure, page, category, shape, aspect
    RSD_SignBlocks.dxf     CAD block library: one block RSD_<CODE> per sign
Needs PyMuPDF (pip install pymupdf) and ezdxf. Run once per manual edition.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import defaultdict

import pymupdf as fitz

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "rfd", "data")
OUT_SVG = os.path.join(DATA, "signs")
PDF_OFFSET = 24          # pdf page index = printed page + 24 in the 2025 edition
CODE_RE = r"(?:PD|RW|I\s*M|[RMPWIE])\s*\d+(?:\s?-\s?[A-Za-z])?"

# --------------------------------------------------------------------------- list of figures
def list_of_figures(doc):
    lines = []
    for pno in range(10, 30):
        lines += doc[pno].get_text(sort=True).splitlines()
    ents, cur = [], None
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^Figure\s+(\d+\.\d+)\s*(.*)$", s)
        if m:
            if cur:
                ents.append(cur)
            cur = [m.group(1), m.group(2)]
        elif cur is not None and s and not s.startswith(("List of", "Road Design", "Part 2")) \
                and not re.match(r"^[xvi]+$|^\d+$|^[xvi]+ \|", s):
            cur[1] += " " + s
    if cur:
        ents.append(cur)
    out = {}
    for fig, t in ents:
        t = re.sub(r"\s+", " ", t).strip()
        t = re.sub(r"\s+\d+$", "", t)
        m = re.search(r"(?:Sign\s*)?\(?(" + CODE_RE + r")\)?\s*$", t)
        if not m or not (("Sign" in t) or m.group(1).startswith(("PD", "I", "RW"))):
            continue
        code = m.group(1).replace(" ", "")
        name = re.sub(r",?\s*(Sign)?\s*\(?" + re.escape(m.group(1)) + r"\)?\s*$", "", t).strip(" ,")
        if fig not in out:
            out[fig] = (code, name)
    return out


def fix_codes(lof):
    """Resolve the manual's own numbering clashes (documented in the catalogue)."""
    notes = {}
    fixed = {}
    for fig, (code, name) in lof.items():
        ch = int(fig.split(".")[0])
        if ch == 8 and code.startswith("M"):           # expressway signs are IM1..IM28
            code = "I" + code
            name = re.sub(r",?\s*Sign I$", "", name)
        if fig == "7.1":
            code, notes[code if False else "PD1"] = "PD1", "Caption reads P1 (clashes with No Entry); PD1 used"
        if fig == "7.8":
            continue                                    # duplicate of W71
        if fig == "6.6":
            continue                                    # duplicate of I7
        if fig == "6.7":
            code = "I10B"; notes[code] = "Manual numbers both Tourist Facility and County Boundary as I10"
        if fig in ("6.18", "6.20", "6.22"):
            code = code + "-D"; notes[code] = "Directional example incorporating the symbol"
        if fig == "8.5":
            code = "IM4S"; notes[code] = "Manual numbers both End of Expressway and Expressway Symbol as IM4"
        if fig == "10.4":
            name = "Road Narrows (Left/Right)"
        name = name.replace("Maxium", "Maximum")
        fixed[fig] = (code, name)
    return fixed, notes


def category(code, fig):
    ch = int(fig.split(".")[0])
    if code.startswith("RW"):
        return "Road Works"
    if code.startswith("IM"):
        return "Expressway"
    if code.startswith("PD"):
        return "Disabled Persons"
    if code.startswith("W"):
        return "Warning"
    if code.startswith("R"):
        return "Regulatory"
    if code.startswith("M"):
        return "Mandatory"
    if code.startswith("P"):
        return "Prohibitory"
    if code.startswith("I") and ch == 5:
        return "Directional"
    return "Information"


SPLIT = {"W24": ["single", "single, large", "double", "triple"]}
# Signs the manual shows one way round but which are used both ways (left/right versions)
MIRRORABLE = {"W2", "W5", "W7", "W9", "W11", "W15", "W16", "W19", "W20", "W21", "W22", "W24",
              "W25", "W54", "RW4", "RW36", "RW37"}


def mirror_svg(svg):
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    w = float(m.group(1))
    i = svg.index(">", svg.index("<svg")) + 1
    return svg[:i] + f'<g transform="translate({w:.2f},0) scale(-1,1)">' + svg[i:].replace("</svg>", "</g></svg>")


# --------------------------------------------------------------------------- frames
def captions(pg):
    """Caption starts at span level: one text line can hold two side-by-side captions."""
    caps = []
    for b in pg.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            cur = None
            for sp in l["spans"]:
                t = sp["text"]
                for part in re.split(r"(?=Figure\s+\d+\.\d+)", t):
                    if not part:
                        continue
                    m = re.match(r"Figure\s+(\d+\.\d+)\s*(.*)", part)
                    if m:
                        if cur:
                            caps.append(cur)
                        x0 = sp["bbox"][0] if part is t or t.startswith(part) else sp["bbox"][0] + \
                            (sp["bbox"][2] - sp["bbox"][0]) * (t.index(part) / max(len(t), 1))
                        cur = [m.group(1), fitz.Rect(x0, l["bbox"][1], x0 + 1, l["bbox"][3]), m.group(2)]
                    elif cur:
                        cur[2] += part
            if cur:
                caps.append(cur)
    return [tuple(c) for c in caps]


def frames(pg):
    out = []
    for d in pg.get_drawings():
        r = d["rect"]
        if d.get("fill") is None and d.get("color") is not None and (d.get("width") or 0) <= 0.6 \
                and 40 < r.width < 520 and 30 < r.height < 700 and len(d["items"]) <= 4:
            out.append(fitz.Rect(r))
    return out


def find_frames(doc, figs):
    cands = defaultdict(list)
    for pno in range(PDF_OFFSET + 1, len(doc)):
        pg = doc[pno]
        fr = frames(pg)
        for fig, crect, text in captions(pg):
            if fig not in figs:
                continue
            near = [f for f in fr if abs(f.x0 - crect.x0) < 12 and 0 <= f.y0 - crect.y1 < 45]
            near.sort(key=lambda f: f.y0 - crect.y1)
            if near:
                score = len(re.sub(r"[^A-Za-z]", "", text))   # real captions have words
                cands[fig].append((score, pno, near[0]))
    chosen, used = {}, set()
    for fig, lst in sorted(cands.items(), key=lambda kv: -max(c[0] for c in kv[1])):
        for score, pno, f in sorted(lst, key=lambda c: -c[0]):
            key = (pno, round(f.x0), round(f.y0))
            if key not in used:
                used.add(key)
                chosen[fig] = (pno, f)
                break
    return chosen


# --------------------------------------------------------------------------- artwork
def artwork(pg, frame):
    """Filled paths + heavy strokes + sign-font text inside the frame."""
    paths = []
    for d in pg.get_drawings():
        r = d["rect"]
        if not (r in frame) or r == frame:
            continue
        fill = d.get("fill")
        w = d.get("width") or 0
        if fill is None and not (d.get("color") is not None and w >= 0.65):
            continue
        paths.append(d)
    texts = []
    for b in pg.get_text("dict", clip=frame)["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                italic = bool(re.search(r"Italic|Oblique", s["font"]))
                arial = "Arial" in s["font"]
                if not s["text"].strip() or italic or s["size"] < (7.0 if arial else 5.5):
                    continue   # notes (italic) and dimension figures (small Arial) are not artwork
                texts.append({"text": s["text"], "font": s["font"], "size": s["size"],
                              "color": s["color"], "origin": s["origin"], "dir": l["dir"],
                              "bbox": s["bbox"]})
    images = []
    for img in pg.get_images(full=True):
        for ib in pg.get_image_rects(img[0]):
            if ib in frame and ib.width > 3 and ib.height > 3:
                pix = pg.get_pixmap(clip=ib, matrix=fitz.Matrix(4, 4), alpha=False)
                images.append((fitz.Rect(ib), pix.tobytes("png")))
    if not paths and not texts and not images:
        return None
    box = fitz.Rect()
    for d in paths:
        box |= d["rect"]
    for t in texts:
        box |= fitz.Rect(t["bbox"])
    for ib, _ in images:
        box |= ib
    return {"paths": paths, "texts": texts, "box": box, "images": images}


def split_clusters(art, gap=4.0):
    """Split artwork into separate signs by spatial clusters (used for W24 chevron variants)."""
    groups = []
    for d in art["paths"]:
        if d["rect"].width * d["rect"].height <= 40:     # dimension arrowheads / ticks
            continue
        r = fitz.Rect(d["rect"]); r2 = fitz.Rect(r.x0 - gap, r.y0 - gap, r.x1 + gap, r.y1 + gap)
        hit = [g for g in groups if g["box"].intersects(r2)]
        if hit:
            g = hit[0]
            for o in hit[1:]:
                g["paths"] += o["paths"]; g["box"] |= o["box"]; groups.remove(o)
            g["paths"].append(d); g["box"] |= r
        else:
            groups.append({"paths": [d], "box": fitz.Rect(r)})
    groups = [g for g in groups if g["box"].width * g["box"].height > 30]
    groups.sort(key=lambda g: (round(g["box"].y0 / 60), g["box"].x0))
    return [{"paths": g["paths"], "texts": [], "box": g["box"], "images": []} for g in groups]


def _flatten(items, steps=8):
    """PyMuPDF path items -> list of subpaths (lists of points)."""
    subs, cur = [], []
    def add(p):
        nonlocal cur
        if cur and (abs(cur[-1][0] - p[0]) > 1e-6 or abs(cur[-1][1] - p[1]) > 1e-6):
            subs.append(cur); cur = []
        if not cur:
            cur = [p]
    for it in items:
        k = it[0]
        if k == "l":
            a, b = it[1], it[2]
            add((a.x, a.y)); cur.append((b.x, b.y))
        elif k == "c":
            a, c1, c2, b = it[1], it[2], it[3], it[4]
            add((a.x, a.y))
            for i in range(1, steps + 1):
                t = i / steps; u = 1 - t
                cur.append((u**3 * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t**3 * b.x,
                            u**3 * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t**3 * b.y))
        elif k == "re":
            r = it[1]
            if cur:
                subs.append(cur)
            subs.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]); cur = []
        elif k == "qu":
            q = it[1]
            if cur:
                subs.append(cur)
            subs.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]); cur = []
    if cur:
        subs.append(cur)
    return [s for s in subs if len(s) >= 2]


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c)


def _svg_path_d(items, ox, oy):
    d, last = [], None
    f = lambda p: f"{p.x - ox:.2f},{p.y - oy:.2f}"
    for it in items:
        k = it[0]
        if k in ("l", "c"):
            start = it[1]
            if last is None or abs(last.x - start.x) > 1e-6 or abs(last.y - start.y) > 1e-6:
                d.append("M" + f(start))
            if k == "l":
                d.append("L" + f(it[2])); last = it[2]
            else:
                d.append("C" + " ".join(f(p) for p in it[2:5])); last = it[4]
        elif k == "re":
            r = it[1]
            d.append(f"M{r.x0 - ox:.2f},{r.y0 - oy:.2f}h{r.width:.2f}v{r.height:.2f}h{-r.width:.2f}Z"); last = None
        elif k == "qu":
            q = it[1]
            d.append("M" + f(q.ul) + "L" + f(q.ur) + "L" + f(q.lr) + "L" + f(q.ll) + "Z"); last = None
    return "".join(d)


def to_svg(art, pad=1.5):
    b = art["box"]
    ox, oy = b.x0 - pad, b.y0 - pad
    w, h = b.width + 2 * pad, b.height + 2 * pad
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {w:.2f} {h:.2f}" '
             f'width="{w:.2f}" height="{h:.2f}">']
    for d in art["paths"]:
        dd = _svg_path_d(d["items"], ox, oy)
        if d.get("closePath"):
            dd += "Z"
        fill = _hex(d["fill"]) if d.get("fill") else "none"
        attrs = f'fill="{fill}"'
        if d.get("fill") and d.get("even_odd"):
            attrs += ' fill-rule="evenodd"'
        if d.get("color") is not None and d.get("width"):
            attrs += f' stroke="{_hex(d["color"])}" stroke-width="{d["width"]:.2f}"'
        parts.append(f'<path d="{dd}" {attrs}/>')
    import base64
    for ib, png in art.get("images", []):
        b64 = base64.b64encode(png).decode()
        parts.append(f'<image x="{ib.x0 - ox:.2f}" y="{ib.y0 - oy:.2f}" width="{ib.width:.2f}" '
                     f'height="{ib.height:.2f}" preserveAspectRatio="none" xlink:href="data:image/png;base64,{b64}"/>')
    for t in art["texts"]:
        x, y = t["origin"][0] - ox, t["origin"][1] - oy
        col = "#%06x" % t["color"]
        bold = "bold" if re.search(r"Bd|Bold|Black|Heavy", t["font"]) else "normal"
        ang = math.degrees(math.atan2(t["dir"][1], t["dir"][0]))
        rot = f' transform="rotate({ang:.1f} {x:.2f} {y:.2f})"' if abs(ang) > 0.5 else ""
        txt = t["text"].replace("&", "&amp;").replace("<", "&lt;")
        parts.append(f'<text x="{x:.2f}" y="{y:.2f}" font-family="Helvetica, Arial, sans-serif" '
                     f'font-weight="{bold}" font-size="{t["size"]:.2f}" fill="{col}"{rot}>{txt}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def shape_of(art):
    """Classify by the largest filled outline: area ratio to its bounding box."""
    best = None
    for d in art["paths"]:
        if not d.get("fill"):
            continue
        r = d["rect"]
        if best is None or r.width * r.height > best[0]:
            best = (r.width * r.height, d)
    if best is None:
        return "rectangle"   # raster artwork
    d = best[1]
    sub = max(_flatten(d["items"]), key=len)
    a = 0.0
    for (x1, y1), (x2, y2) in zip(sub, sub[1:] + sub[:1]):
        a += x1 * y2 - x2 * y1
    r = d["rect"]
    ratio = abs(a) / 2 / max(r.width * r.height, 1e-9)
    ar = r.width / max(r.height, 1e-9)
    if ratio < 0.62:
        # triangle: apex up or down?
        top = min(p[1] for p in sub); ys = [p[1] for p in sub]
        apex_up = sum(1 for y in ys if y < top + r.height * 0.15) < sum(1 for y in ys if y > top + r.height * 0.85)
        return "triangle" if apex_up else "inv_triangle"
    if 0.72 <= ratio < 0.81 and 0.85 < ar < 1.15:
        return "circle"
    if 0.81 <= ratio < 0.9 and 0.85 < ar < 1.15:
        return "octagon"
    return "rectangle"


def shape_by_rule(code, cat, aspect, geom_guess):
    if code == "R1":
        return "octagon"
    if code == "R2":
        return "inv_triangle"
    squareish = 0.85 < aspect < 1.3
    if cat in ("Warning", "Road Works") and squareish and geom_guess in ("triangle", "inv_triangle"):
        return "triangle"
    if cat in ("Mandatory", "Prohibitory", "Road Works") and 0.9 < aspect < 1.1 and geom_guess != "rectangle":
        return "circle"
    if cat in ("Mandatory", "Prohibitory") and 0.9 < aspect < 1.1:
        return "circle"
    return "rectangle"


# --------------------------------------------------------------------------- DXF blocks
def add_block(doc, name, art, size=1.0, cy=0.95, mirror=False):
    """Block geometry: artwork scaled so its larger side = size, centred at (0, cy);
    post at origin, plate line along X (same convention as the placeholder blocks)."""
    from ezdxf.colors import rgb2int
    b = art["box"]
    s = size / max(b.width, b.height)
    cx0, cy0 = (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2
    sx = -s if mirror else s
    T = lambda p: ((p[0] - cx0) * sx, cy - (p[1] - cy0) * s)   # PDF y down -> CAD y up
    blk = doc.blocks.new(name, base_point=(0, 0))
    blk.add_circle((0, 0), 0.06, dxfattribs={"layer": "0"})
    blk.add_line((-0.35, 0.12), (0.35, 0.12))
    blk.add_line((0, 0), (0, 0.12))
    for d in art["paths"]:
        subs = [[T(p) for p in sp] for sp in _flatten(d["items"])]
        if d.get("fill"):
            h = blk.add_hatch(dxfattribs={"layer": "0"})
            h.set_solid_fill()
            h.rgb = tuple(int(round(v * 255)) for v in d["fill"])
            h.dxf.hatch_style = 0 if d.get("even_odd") else 0
            for sp in subs:
                if len(sp) >= 3:
                    h.paths.add_polyline_path(sp, is_closed=True)
        if d.get("color") is not None and d.get("width"):
            for sp in subs:
                pl = blk.add_lwpolyline(sp, close=bool(d.get("closePath")))
                pl.rgb = tuple(int(round(v * 255)) for v in d["color"])
    if art.get("images") and not art["paths"]:
        hw, hh = b.width * s / 2, b.height * s / 2
        blk.add_lwpolyline([(-hw, cy - hh), (hw, cy - hh), (hw, cy + hh), (-hw, cy + hh)], close=True)
        blk.add_text(name.replace("RSD_", ""), height=0.12, dxfattribs={"insert": (-hw + 0.05, cy - 0.06)})
    for t in art["texts"]:
        x, y = T(t["origin"])
        tx = blk.add_text(t["text"], height=t["size"] * s * 0.72,
                          dxfattribs={"insert": (x, y),
                                      "rotation": -math.degrees(math.atan2(t["dir"][1], t["dir"][0]))})
        tx.rgb = ((t["color"] >> 16) & 255, (t["color"] >> 8) & 255, t["color"] & 255)
    return blk


# --------------------------------------------------------------------------- main
def main(pdf):
    import ezdxf
    sys.path.insert(0, ROOT)
    from rfd.dxf_out import APPID, ATTRS, VISIBLE
    doc = fitz.open(pdf)
    lof, notes = fix_codes(list_of_figures(doc))
    chosen = find_frames(doc, set(lof))
    os.makedirs(OUT_SVG, exist_ok=True)
    for f in os.listdir(OUT_SVG):
        os.remove(os.path.join(OUT_SVG, f))
    dxf = ezdxf.new("R2018", setup=True)
    dxf.units = ezdxf.units.M
    dxf.appids.new(APPID)
    dxf.layers.add("RSD-SIGN-TEXT", color=7)
    entries, missing = [], []
    for fig in sorted(lof, key=lambda f: tuple(int(x) for x in f.split("."))):
        code, name = lof[fig]
        if fig not in chosen:
            missing.append((fig, code, name)); continue
        pno, frame = chosen[fig]
        inner = fitz.Rect(frame.x0 + 0.8, frame.y0 + 0.8, frame.x1 - 0.8, frame.y1 - 0.8)
        art = artwork(doc[pno], inner)
        if art is None:
            missing.append((fig, code, name)); continue
        variants = [(code, name, art)]
        if code in SPLIT:
            parts = split_clusters(art)
            variants = [(f"{code}-{chr(97 + i)}", f"{name} ({lbl})", a)
                        for i, (a, lbl) in enumerate(zip(parts, SPLIT[code]))]
        for vcode, vname, vart in variants:
            with open(os.path.join(OUT_SVG, vcode + ".svg"), "w", encoding="utf-8") as fh:
                fh.write(to_svg(vart))
            mirror = vcode.split("-")[0] in MIRRORABLE
            if mirror:
                with open(os.path.join(OUT_SVG, vcode + "_M.svg"), "w", encoding="utf-8") as fh:
                    fh.write(mirror_svg(to_svg(vart)))
            for blkname, mir in [("RSD_" + vcode, False)] + ([("RSD_" + vcode + "_M", True)] if mirror else []):
                blk = add_block(dxf, blkname, vart, mirror=mir)
                for i, tag in enumerate(ATTRS):
                    a = blk.add_attdef(tag, insert=(0.7, 0.9 - 0.18 * i), height=0.15,
                                       dxfattribs={"layer": "RSD-SIGN-TEXT"})
                    a.is_invisible = tag not in VISIBLE
            cat = category(code, fig)
            b = vart["box"]
            shp = shape_by_rule(code, cat, b.width / b.height, shape_of(vart))
            entries.append({"code": vcode, "name": vname, "category": cat, "shape": shp,
                            "figure": fig, "page": pno - PDF_OFFSET, "aspect": round(b.width / b.height, 3),
                            "mirror": mirror, "note": notes.get(code, "")})
    with open(os.path.join(DATA, "rdm_signs.json"), "w", encoding="utf-8") as fh:
        json.dump({"source": "RDM 6.2 Traffic Signs (2025), Ministry of Roads and Transport, Kenya",
                   "signs": entries, "missing": missing}, fh, indent=1)
    dxf.saveas(os.path.join(DATA, "RSD_SignBlocks.dxf"))
    print(f"{len(entries)} signs extracted, {len(missing)} without artwork: {missing}")


if __name__ == "__main__":
    main(sys.argv[1])
