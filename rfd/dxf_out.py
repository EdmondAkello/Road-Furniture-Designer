"""DXF output: placed-signs drawing (preview / fallback route), block library, DXF read-back.

Sign blocks come from the RDM 6.2 block library (data/RSD_SignBlocks.dxf, built by
tools/extract_rdm_signs.py). Every placed block carries its UUIDs twice: as
attributes (visible to the drawing, editable) and as XDATA under the registered
app "RSD" (authoritative identity).
"""
from __future__ import annotations

import math
import os
import shutil

from . import dxfw
from .alignment import Alignment, format_station
from .catalogue import BLOCK_LIBRARY, Catalogue
from .legend import summary as legend_summary
from .records import SignList

APPID = "RSD"
ATTRS = ["SIGN_CODE", "LEGEND", "DESCRIPTION", "SIZE", "CHAINAGE", "OFFSET", "SIDE", "FACING",
         "POST_REF", "FACE_UUID", "INSTALL_UUID"]
VISIBLE = {"SIGN_CODE", "LEGEND"}


LEGEND_STYLE = "RSD_LEGEND"        # Arial (in the template), so legend text width matches the plate
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "RSD_template.dxf")


def _layers(doc):
    # the RSD application id and the text styles are in the template.
    # Reference geometry is for checking only: it never plots, so pasting it by mistake is harmless.
    for lay, col in (("RSD-SIGN", 1), ("RSD-SIGN-TEXT", 7), ("RSD-SIGN-LEADER", 7), ("RSD-ALIGN", 4),
                     ("RSD-ALIGN-OTHER", 3), ("RSD-REF-NOTES", 8)):
        doc.add_layer(lay, color=col, plot=lay not in REFERENCE_LAYERS)


REFERENCE_LAYERS = ("RSD-ALIGN", "RSD-ALIGN-OTHER", "RSD-REF-NOTES")
EDGE_COLOURS = {"ETW": 7, "EPS": 2, "Hinge": 30, "Ditch_In": 5, "Ditch_Out": 5, "Daylight": 3}


def _edge_layer(doc, code, assumed=False):
    """RSD-EDGE-<code>; RSD-EDGE-TS-<code> for edges from a typical section (assumed, not a corridor)."""
    lay = ("RSD-EDGE-TS-" if assumed else "RSD-EDGE-") + "".join(c if c.isalnum() or c in "-_" else "_" for c in code)
    doc.add_layer(lay, color=EDGE_COLOURS.get(code, 8), plot=False)
    return lay


def _georef_header(doc, crs, source, alignment_name):
    """World coordinates: metres, angles CCW from east, plus the CRS and source recorded in the file."""
    for var, code, v in (("$INSUNITS", 70, "6"),        # metres
                         ("$MEASUREMENT", 70, "1"),     # metric
                         ("$LUNITS", 70, "2"),          # decimal
                         ("$LUPREC", 70, "3"),
                         ("$AUNITS", 70, "0"),          # decimal degrees
                         ("$ANGBASE", 50, "0.0"),       # 0 deg = east
                         ("$ANGDIR", 70, "0")):         # counter-clockwise
        doc.set_header(var, (code, v))
    crs = crs or {}
    label = " ".join(x for x in (f"EPSG:{crs['epsg']}" if crs.get("epsg") else "", crs.get("name", "")) if x)
    for k, v in (("RSD_CRS", label or "as LandXML (not declared)"), ("RSD_MAP_ZONE", crs.get("map_zone", "")),
                 ("RSD_SOURCE_LANDXML", os.path.basename(source or "")), ("RSD_ALIGNMENT", alignment_name),
                 ("RSD_COORDINATES", "World E,N in metres exactly as in the LandXML; paste with PASTEORIG")):
        if v:
            doc.custom.append((k, str(v)))
    return label


_LIBRARY_CACHE = {}


def _library(path):
    """{block name: [entity tags]} of the block library, read once per session (it is 8 MB)."""
    key = (os.path.abspath(path), os.path.getmtime(path))
    blocks = _LIBRARY_CACHE.get(key)
    if blocks is None:
        _LIBRARY_CACHE.clear()
        blocks = _LIBRARY_CACHE[key] = dxfw.blocks_of(dxfw.read_tags(path))
    return blocks


def import_blocks(doc, names, library=BLOCK_LIBRARY):
    """Copy the named sign blocks from the library into doc; returns names not found."""
    names = [n for n in set(names) if not doc.has_block(n)]
    if not names:
        return []
    src = _library(library)
    have = [n for n in names if n in src]
    for n in have:
        blk = doc.new_block(n)
        for e in src[n]:
            blk.add(dxfw.Entity.copy_of(e))
            if e[0][1] == "ATTDEF":
                doc._blocks_with_attdefs.add(n)
    return sorted(set(names) - set(have))


def _fallback_block(doc, name, code):
    blk = doc.new_block(name)
    blk.add_circle((0, 0), 0.06)
    blk.add_line((-0.35, 0.12), (0.35, 0.12))
    blk.add_lwpolyline([(-0.45, 0.5), (0.45, 0.5), (0.45, 1.4), (-0.45, 1.4)], close=True)
    blk.add_text(code, (-0.4, 0.9), 0.15)
    for i, tag in enumerate(ATTRS):
        blk.add_attdef(tag, (0.7, 0.9 - 0.18 * i), 0.15, layer="RSD-SIGN-TEXT", invisible=tag not in VISIBLE)


# ---------------------------------------------------------------- plan sizing
SYMBOL_MM = 10.0      # sign symbol size on the printed plan: 25 m at 1:2500
TEXT_MM = 1.8         # sign code / legend / chainage text on the printed plan
DEFAULT_PLAN_SCALE = 2500.0
LEGEND_FACTOR = 0.6   # directional signs / text plates: legend text ~0.19 x symbol size (4.8 m at 1:2500)


def tick_for(plan_scale: float) -> float:
    """Chainage label interval that stays legible: 25 m up to 1:1250, 50 m to 1:2500, else 100 m."""
    return 25.0 if plan_scale <= 1250 else (50.0 if plan_scale <= 2500 else 100.0)


def symbol_scale_for(plan_scale: float, symbol_mm: float = SYMBOL_MM) -> float:
    """Block scale so a 1-unit sign symbol prints at symbol_mm at 1:plan_scale (model units = metres)."""
    return symbol_mm * plan_scale / 1000.0


def label_block(doc, base: str, sd, face) -> str:
    """Copy of a library block with its artwork text replaced by the face's legend (W30 '10%' -> '11%')."""
    from .legend import label_lines
    lines = label_lines(sd, face.legend) if sd.legend == "label" else None
    src = doc.blocks.get(base)
    if not lines or src is None:
        return base
    name = f"{base}_{'_'.join(lines)}"
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:60]
    if doc.has_block(name):
        return name
    blk = doc.new_block(name)
    it = iter(lines)
    for e in src.entities:
        c = blk.add_entity(e)
        if c.dxftype == "TEXT":
            c.set(1, next(it, c.get(1)))
        elif c.dxftype == "ATTDEF":
            doc._blocks_with_attdefs.add(name)
    return name


def legend_block_name(face) -> str:
    return f"RSD_{face.code}_{face.face_uuid[:8]}"


def _HEX(h):
    return tuple(int(h.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def make_legend_block(doc, name, sd, text, road_class="A"):
    """Directional face / text plate as a block with real text, so it reads on plan drawings.
    Geometry in sign units: face height ~0.32 per line, centred at (0, 0.95) like the sign blocks."""
    from .legend import PLATE_COLOURS, SCHEMES, ordered, parse
    if doc.has_block(name):
        return
    blk = doc.new_block(name)
    blk.add_circle((0, 0), 0.06)
    blk.add_line((-0.35, 0.12), (0.35, 0.12))
    blk.add_line((0, 0), (0, 0.12))
    th = 0.32                                  # text height (sign units): 2.5 mm printed at 8 mm/unit
    cw = th * 0.85         # Arial capitals and digits run ~0.6-0.75 h; leaves a margin for other fonts
    if sd.legend == "directional":
        sc = SCHEMES.get(road_class or "A", SCHEMES["A"])
        bg, fg, rc = _HEX(sc["bg"]), _HEX(sc["fg"]), _HEX(sc["route"])
        lines = ordered(parse(text))
        rows = [(lin.arrow, lin.place, lin.route, lin.distance) for lin in lines]
    else:
        bg = _HEX(PLATE_COLOURS.get(sd.plate_style[0], "#ffffff"))
        fg = _HEX(PLATE_COLOURS.get(sd.plate_style[1], "#111111")); rc = fg
        rows = [(None, lin.strip(), "", "") for lin in text.splitlines() if lin.strip()]
    rows = rows or [(None, sd.code, "", "")]
    name_w = max(len(r[1]) for r in rows) * cw
    route_w = max((len(r[2]) for r in rows), default=0) * cw + (0.25 if any(r[2] for r in rows) else 0)
    dist_w = max((len(r[3]) for r in rows), default=0) * cw + (0.2 if any(r[3] for r in rows) else 0)
    arrow_w = th * 1.5 if any(r[0] for r in rows) else 0.0
    pad, rh = 0.1, th * 1.45
    w = 2 * pad + 2 * arrow_w + name_w + route_w + dist_w
    h = 2 * pad + rh * len(rows)
    x0, y0 = -w / 2, 0.95 - h / 2 + 0.5 * 0       # centred where the sign artwork sits
    y0 = max(y0, 0.2)
    rect = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]
    blk.add_solid_hatch(rect, rgb=bg)
    blk.add_lwpolyline(rect, close=True, rgb=fg)
    for i, (arrow, place, route, dist) in enumerate(rows):
        yb = y0 + h - pad - rh * (i + 1) + (rh - th) / 2
        x = x0 + pad
        def arrow_poly(kind, ax):
            s = th
            if kind == "ahead":
                pts = [(ax + s / 2, yb + s), (ax + s, yb + s / 2), (ax + s * 0.65, yb + s / 2), (ax + s * 0.65, yb),
                       (ax + s * 0.35, yb), (ax + s * 0.35, yb + s / 2), (ax, yb + s / 2)]
            elif kind == "left":
                pts = [(ax, yb + s / 2), (ax + s / 2, yb + s), (ax + s / 2, yb + s * 0.65), (ax + s, yb + s * 0.65),
                       (ax + s, yb + s * 0.35), (ax + s / 2, yb + s * 0.35), (ax + s / 2, yb)]
            else:
                pts = [(ax + s, yb + s / 2), (ax + s / 2, yb + s), (ax + s / 2, yb + s * 0.65), (ax, yb + s * 0.65),
                       (ax, yb + s * 0.35), (ax + s / 2, yb + s * 0.35), (ax + s / 2, yb)]
            blk.add_solid_hatch(pts, rgb=fg)
        if arrow in ("ahead", "left"):
            arrow_poly(arrow, x)
        x += arrow_w
        blk.add_text(place, (x, yb), th, style=LEGEND_STYLE, rgb=fg)
        x += name_w + 0.15
        if route:
            blk.add_text(route, (x, yb), th * 0.9, style=LEGEND_STYLE, rgb=rc)
        x += route_w
        if dist:
            blk.add_text(dist, (x, yb), th * 0.9, style=LEGEND_STYLE, rgb=fg)
        if arrow == "right":
            arrow_poly("right", x0 + w - pad - th)
    for i, tag in enumerate(ATTRS):
        blk.add_attdef(tag, (w / 2 + 0.2, 0.9 - 0.32 * i), 0.3, layer="RSD-SIGN-TEXT", invisible=tag not in VISIBLE)


def _draw_alignment(msp, al, layer, tick, text_h, label_name=False):
    pts = []
    n = max(2, int(al.length / 2.0))
    for k in range(n + 1):
        x, y, _ = al.point_at(al.sta_start + al.length * k / n)
        pts.append((x, y))
    msp.add_lwpolyline(pts, layer=layer)
    s = math.ceil(al.sta_start / tick) * tick
    while s <= al.sta_end + 1e-6:
        x, y, h = al.point_at(s)
        nx, ny = math.sin(h), -math.cos(h)
        tl = text_h * 0.8
        msp.add_line((x - tl * nx, y - tl * ny), (x + tl * nx, y + tl * ny), layer=layer)
        rot = (math.degrees(h) - 90.0) % 360.0             # text runs outward along the tick (right side)
        align = "MIDDLE_LEFT"
        if 90.0 < rot <= 270.0:                            # would read upside down: turn it, keep it on the right
            rot = (rot + 180.0) % 360.0
            align = "MIDDLE_RIGHT"
        msp.add_text(format_station(al.display_station(s), 0), (x + 1.5 * tl * nx, y + 1.5 * tl * ny), text_h,
                     layer=layer, rotation=rot, align=align)
        s += tick
    if label_name:
        x, y, h = al.point_at(al.sta_start + al.length / 2)
        rot = math.degrees(h) % 360.0
        if 90.0 < rot <= 270.0:
            rot = (rot + 180.0) % 360.0
        nx, ny = math.sin(h), -math.cos(h)
        msp.add_text(al.name, (x - nx * text_h * 3, y - ny * text_h * 3), text_h * 1.4, layer=layer,
                     rotation=rot, align="MIDDLE_CENTER")


def write_dxf(path: str, sl: SignList, al: Alignment, cat: Catalogue,
              symbol_scale: float = None, tick: float = None, plan_scale: float = DEFAULT_PLAN_SCALE,
              crs: dict = None, source: str = "", others=None, callout: bool = True, linear=None,
              junctions=None):
    """Placed signs in WORLD coordinates (the LandXML's easting/northing, metres).

    Nothing is shifted or rescaled, so the signs can be copied into any drawing that
    uses the same coordinate system with COPYBASE (base 0,0) + PASTEORIG, or the whole
    file inserted/xref'd at 0,0,0 scale 1 rotation 0.

    callout=True (default, plan-drawing style): each sign is one block inserted at its post.
    The block holds a post marker, a leader and the sign symbol upright beside the road,
    clear of the carriageway and of the other symbols. callout=False puts the sign block
    itself on the post, rotated to face traffic.
    others: further alignments from the LandXML to draw for reference.
    linear: (runs, LinearCatalogue) - markings, studs and barriers drawn as polylines in
    world units (RSD-MARK-*, RSD-STUD-*, RSD-BARRIER-* layers).
    """
    from .corridor import edge_polylines
    from .plan_layout import callouts_by_post
    doc = dxfw.Drawing(TEMPLATE)
    _layers(doc)
    crs_label = _georef_header(doc, crs, source, al.name)
    msp = doc.modelspace
    if symbol_scale is None:
        symbol_scale = symbol_scale_for(plan_scale)
    S = symbol_scale
    tick = tick or tick_for(plan_scale)
    text_h = TEXT_MM * plan_scale / 1000.0          # model units for printed text
    needed = {cat.signs[f.code].block(f.mirror): f.code for f in sl.faces}
    for name in import_blocks(doc, list(needed)):
        _fallback_block(doc, name, needed[name])

    # ---- reference geometry (non-plotting): this alignment, its corridor edges, other alignments
    _draw_alignment(msp, al, "RSD-ALIGN", tick, text_h)
    for other in others or []:
        _draw_alignment(msp, other, "RSD-ALIGN-OTHER", max(tick, 100.0), text_h, label_name=True)
    for a in [al] + list(others or []):
        assumed = getattr(a, "edge_source", "") == "typical section"
        for code, side, pts in edge_polylines(a):
            msp.add_lwpolyline(pts, layer=_edge_layer(doc, code, assumed))

    # coordinate check point at the start of the alignment (non-plotting)
    x0, y0, _ = al.point_at(al.sta_start)
    msp.add_point((x0, y0), layer="RSD-REF-NOTES")
    cross = text_h * 2
    msp.add_line((x0 - cross, y0), (x0 + cross, y0), layer="RSD-REF-NOTES")
    msp.add_line((x0, y0 - cross), (x0, y0 + cross), layer="RSD-REF-NOTES")
    note = (f"RFD CHECK POINT  {al.name} CH {format_station(al.display_station(al.sta_start))}\\P"
            f"E {x0:.3f}  N {y0:.3f}\\P{crs_label or 'CRS as LandXML'}\\P"
            f"World coordinates from {os.path.basename(source) if source else 'the LandXML'} (m). "
            f"Copy layer RSD-SIGN with base point 0,0 and PASTEORIG.")
    msp.add_mtext(note, (x0 + cross * 1.5, y0 - cross * 1.5), text_h, layer="RSD-REF-NOTES")

    def block_box(name):                       # face extents in block units (no post stand, no attributes)
        if name not in boxes:
            blk = doc.blocks.get(name)
            ext = dxfw.extents([[(0, e.dxftype)] + e.tags for e in blk.entities if e.dxftype != "ATTDEF"]) \
                if blk else None
            boxes[name] = ext or (-0.5, 0.5, 0.5, 1.4)
        return boxes[name]

    boxes, prep = {}, []
    for i, f in enumerate(sl.faces):
        sd = cat.signs[f.code]
        bname = sd.block(f.mirror)
        if sd.legend in ("directional", "plate") and f.legend:
            bname = legend_block_name(f)
            make_legend_block(doc, bname, sd, f.legend, f.road_class or "A")
        elif sd.legend == "label" and f.legend:
            bname = label_block(doc, bname, sd, f)
        face_has_text = bname != sd.block(f.mirror)
        from .plan_layout import SERIES_CODES, SERIES_FACTOR
        sc = S * (LEGEND_FACTOR if sd.legend in ("directional", "plate") and face_has_text
                  else (SERIES_FACTOR if f.code.startswith(SERIES_CODES) else 1.0))
        fb = face_only_block(doc, bname) if callout else bname
        prep.append((f, sd, bname, fb, face_has_text, sc))
    centres = {}
    if callout:
        items = []
        for i, (f, sd, bname, fb, fht, sc) in enumerate(prep):
            bx = block_box(fb)
            lab_w = max(len(f.code), len(legend_summary(f.legend)) if (f.legend and not fht) else 0) * 0.8 * text_h
            items.append((i, f.station_internal, f.x, f.y, al.point_at(f.station_internal)[2], f.side,
                          max((bx[2] - bx[0]) * sc, lab_w), (bx[3] - bx[1]) * sc + 2.6 * text_h,   # room for the label
                          f.install_uuid or f.post_ref, f.facing))
        centres = callouts_by_post(items, gap=0.25 * S)

    for i, (f, sd, bname, fb, face_has_text, sc) in enumerate(prep):
        attrs = {
            "SIGN_CODE": f.code,
            "LEGEND": "" if face_has_text else (legend_summary(f.legend) if f.legend else ""),
            "DESCRIPTION": sd.name, "SIZE": f.size,
            "CHAINAGE": format_station(f.station_display), "OFFSET": f"{f.offset_abs:.2f}",
            "SIDE": f.side, "FACING": f.facing, "POST_REF": f.post_ref,
            "FACE_UUID": f.face_uuid, "INSTALL_UUID": f.install_uuid}
        if callout:
            ref = _callout_insert(doc, msp, f, fb, sc, block_box(fb), centres[i], text_h, S)
        else:
            ref = msp.add_blockref(bname, (f.x, f.y), layer="RSD-SIGN", rotation=f.rotation_deg, scale=sc)
        doc.add_attribs(ref, attrs)
        if not callout:
            upside_down = 90.0 < (f.rotation_deg % 360.0) <= 270.0
            for a in ref.attribs:             # readable on the printed plan whatever the block library says
                if a.get_tag() in VISIBLE:
                    a.set(40, repr(float(text_h)))
                    if upside_down:
                        a.set_rotation((float(a.get(50, 0.0)) + 180.0) % 360.0)
        ref.set_xdata(APPID, [(1000, "rsd/0.1"), (1000, f.face_uuid), (1000, f.install_uuid)])
    if linear:
        write_linear(doc, msp, al, *linear)
    if junctions:
        write_junctions(doc, msp, junctions)
    # extents for Zoom Extents: the drawn lines, and the sign blocks by their insertion points
    ext = dxfw.extents([[(0, e.dxftype)] + e.tags for e in msp.entities])
    if ext:
        doc.set_header("$EXTMIN", (10, repr(ext[0])), (20, repr(ext[1])), (30, "0.0"))
        doc.set_header("$EXTMAX", (10, repr(ext[2])), (20, repr(ext[3])), (30, "0.0"))
    doc.saveas(path)


def face_only_block(doc, name: str) -> str:
    """Copy of a sign block without its post stand (circle + stem at the origin), for callouts:
    the callout draws the post where it really is and a leader to the symbol."""
    fname = name + "_F"
    if doc.has_block(fname):
        return fname
    src = doc.blocks.get(name)
    if src is None:
        return name
    blk = doc.new_block(fname)
    for e in src.entities:
        t = e.dxftype
        if t == "ATTDEF":
            continue
        if t == "CIRCLE" and abs(float(e.get(10, 0))) < 1e-6 and abs(float(e.get(20, 0))) < 1e-6 \
                and float(e.get(40, 1)) < 0.1:
            continue
        if t == "LINE" and max(float(e.get(20, 0)), float(e.get(21, 0))) <= 0.13:
            continue
        blk.add_entity(e)
    return fname


def callout_block_name(face) -> str:
    return f"RSDC_{face.code}_{face.face_uuid[:8]}"


def _callout_insert(doc, msp, f, face_block, sc, bx, centre, text_h, S):
    """One block per sign, inserted at the post (true coordinates, rotation = facing as before).

    Inside: a post marker, a leader to the symbol, the sign face upright, and the code (and
    legend) under it. Copy/paste, move and read-back all act on the post.
    centre: world centre of the symbol box (face plus label room underneath).
    """
    from .plan_layout import leader_tip
    r = math.radians(f.rotation_deg)
    cr, sr = math.cos(-r), math.sin(-r)
    def loc(wx, wy):    # world offset -> block coordinates
        return (wx * cr - wy * sr, wx * sr + wy * cr)
    w, h = (bx[2] - bx[0]) * sc, (bx[3] - bx[1]) * sc
    lab = 2.6 * text_h
    cx, cy = centre[0] - f.x, centre[1] - f.y + lab / 2               # face centre relative to the post
    ins = (cx - (bx[0] + bx[2]) / 2 * sc, cy - (bx[1] + bx[3]) / 2 * sc)
    name = callout_block_name(f)
    doc.delete_block(name)
    blk = doc.new_block(name)
    rp = max(0.05 * S, 0.3)
    blk.add_circle((0, 0), rp, layer="RSD-SIGN-LEADER")
    tip = leader_tip(0.0, 0.0, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    d = math.hypot(*tip)
    if d > rp:
        blk.add_line(loc(tip[0] * rp / d, tip[1] * rp / d), loc(*tip), layer="RSD-SIGN-LEADER")
    blk.add_blockref(face_block, loc(*ins), rotation=-f.rotation_deg, scale=sc)
    # attribute definitions: code (and legend) under the face, upright; the rest hidden
    for i, tag in enumerate(ATTRS):
        row = i if tag in VISIBLE else 0
        pos = loc(cx, cy - h / 2 - 0.3 * text_h - 1.25 * text_h * row)
        blk.add_attdef(tag, pos, text_h, layer="RSD-SIGN-TEXT", rotation=-f.rotation_deg,
                       invisible=tag not in VISIBLE, align="TOP_CENTER")
    return msp.add_blockref(name, (f.x, f.y), layer="RSD-SIGN", rotation=f.rotation_deg)


def write_block_library(path: str, cat: Catalogue = None):
    """Copy the RDM block library (open in Civil 3D and save as DWG)."""
    shutil.copyfile(BLOCK_LIBRARY, path)


def sign_block_of(blocks: dict, name: str, scale: float = 1.0):
    """(sign block name, symbol scale) of a placed sign: the nested face of a callout block, or the insert
    itself (with its own scale). blocks: {name: [entity tags]} (dxfw.blocks_of); name: the placed block's name."""
    if name.startswith("RSDC_") and name in blocks:
        for e in blocks[name]:
            if e[0][1] == "INSERT":
                n = dxfw.value(e, 2)
                return (n[:-2] if n.endswith("_F") else n), dxfw.fvalue(e, 41, 1.0)
    return name, scale


def readback_dxf(path: str) -> dict:
    """Read RSD sign blocks from an ASCII DXF (as written here, or saved from Civil 3D) into the same
    structure the Dynamo read-back writes."""
    tags = dxfw.read_tags(path)
    blocks = dxfw.blocks_of(tags)
    ents = dxfw.split_entities(dxfw.sections(tags).get("ENTITIES", []))
    signs = []
    for i, e in enumerate(ents):
        if e[0][1] != "INSERT" or dxfw.value(e, 67) == "1":        # model space inserts only
            continue
        xd = [v for _c, v in dxfw.xdata(e, APPID)]
        if len(xd) < 3:
            continue
        attrs = {}
        for a in ents[i + 1:]:
            if a[0][1] != "ATTRIB":
                break
            attrs[dxfw.Entity.copy_of(a).get_tag()] = dxfw.value(a, 1, "")
        name = dxfw.value(e, 2)
        signs.append({
            "face_uuid": xd[1], "installation_uuid": xd[2], "block_name": sign_block_of(blocks, name)[0],
            "x": dxfw.fvalue(e, 10), "y": dxfw.fvalue(e, 20),
            "rotation_deg": dxfw.fvalue(e, 50) % 360.0, "handle": dxfw.value(e, 5),
            "attributes": attrs})
    return {"schema_version": "0.1", "source": "dxf", "drawing": path, "signs": signs}


LINEAR_COLOURS = {"yellow": 2, "white": 7, "grey": 8}
STUD_RADIUS = 0.1


def _linear_layer(doc, it) -> str:
    kind = {"Marking": "MARK", "Road stud": "STUD", "Barrier": "BARRIER", "Transverse marking": "MARK",
            "Traffic calming": "CALM"}.get(it.category, "LINEAR")
    lay = f"RSD-{kind}-" + "".join(c if c.isalnum() or c in "-_" else "_" for c in it.code)
    doc.add_layer(lay, color=LINEAR_COLOURS.get(it.colour, 6))
    return lay


JUNCTION_COLOURS = {"KERB": 8, "GUIDE": 9}


def write_junctions(doc, msp, parts):
    """Junction islands and markings: (code, station, [polyline]) on layers RSD-JN-<code>.

    Kerb outlines on RSD-JN-KERB, hatching and markings by RDM 6.1 code, construction lines on
    RSD-JN-GUIDE (freeze it for the final drawing)."""
    from .junctions import load_templates
    codes = load_templates()["codes"]
    for code, sta, lines in parts:
        lay = f"RSD-JN-{code}"
        if not doc.has_layer(lay):
            col = JUNCTION_COLOURS.get(code, LINEAR_COLOURS.get(codes.get(code, {}).get("colour"), 6))
            doc.add_layer(lay, color=col,
                          linetype="DASHED" if code == "GUIDE" and doc.has_linetype("DASHED") else "Continuous")
        fill = codes.get(code, {}).get("fill")
        for pts in lines:
            if len(pts) < 2:
                continue
            closed = len(pts) > 2 and pts[0] == pts[-1]
            pl = msp.add_lwpolyline(pts[:-1] if closed else pts, close=closed, layer=lay)
            pl.set_xdata(APPID, [(1000, "rsd-junction/0.1"), (1000, code), (1040, repr(float(sta or 0.0)))])
            if fill and closed:                             # arrows: solid filled, as painted
                msp.add_solid_hatch(pts[:-1], layer=lay)


def _dash_linetype(doc, mark: float, gap: float) -> str:
    """A linetype in world metres (LTSCALE 1) for a broken marking."""
    name = f"RSD_{mark:g}_{gap:g}".replace(".", "p")
    doc.add_linetype(name, [mark + gap, mark, -gap], f"RSD {mark:g} m mark / {gap:g} m gap")
    return name


def write_linear(doc, msp, al, runs, cat):
    """Draw linear furniture runs. Multi-line items (double lines, CLS) are drawn line by line."""
    from .linear import clamp_run, geometry, run_quantities, signed_offset
    for r in runs:
        if r.code not in cat:
            continue
        r = clamp_run(al, r)
        it = cat[r.code]
        lay = _linear_layer(doc, it)
        v = al.speed_at((r.sta_start + r.sta_end) / 2)
        xd = [(1000, "rsd-line/0.1"), (1000, r.uuid), (1000, r.code),
              (1040, repr(float(r.sta_start))), (1040, repr(float(r.sta_end))), (1000, r.side)]
        if it.transverse:
            from .linear import CALMING_FILL, pattern
            for pts in geometry(al, r):                              # footprint
                pl = msp.add_lwpolyline(pts[:-1], close=True, layer=lay)
                pl.set_xdata(APPID, xd)
            for pts in pattern(al, r, it.bars, it.bar_width):         # painted bars / triangles, solid filled
                if r.code in CALMING_FILL:
                    continue
                msp.add_solid_hatch(pts[:-1], layer=lay)
            continue
        if it.is_point_series:
            q = run_quantities(r, it, v)
            n, sp = q["count"], q["spacing"]
            for k in range(n):
                s = min(r.sta_start + k * sp, r.sta_end)
                o = signed_offset(al, r, s)
                if o is None:
                    continue
                x, y, _ = al.point_at(s, o)
                c = msp.add_circle((x, y), STUD_RADIUS, layer=lay)
                c.set_xdata(APPID, xd)
            continue
        from .linear import painted_lines
        for parts, broken, d in painted_lines(al, r, it, step=2.0):
            lt = _dash_linetype(doc, float(d["mark"]), float(d["gap"])) if broken else None
            cw = float(d["width"]) if it.is_marking and d.get("width") else None
            for pts in parts:
                pl = msp.add_lwpolyline(pts, layer=lay, linetype=lt, const_width=cw)
                pl.set_xdata(APPID, xd)
