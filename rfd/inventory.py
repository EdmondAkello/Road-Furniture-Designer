"""Sign inventory: flat, link-friendly tables for a separate QTO / Bill process.

Every data sheet has its header in row 1 and is an Excel Table (RSD_Signs,
RSD_Posts, RSD_Quantities) so a QTO workbook can link to it by name. No rates,
amounts or derived construction quantities - those belong to the QTO.
A CSV of the sign inventory is written alongside for non-Excel use.
"""
from __future__ import annotations

import csv
import datetime as dt
from collections import OrderedDict

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from .alignment import format_station
from .catalogue import Catalogue
from .legend import summary as legend_summary
from .records import SignList

SIGN_COLS = ["Sign No", "Post Ref", "Chainage", "Chainage (m)", "Side", "Offset (m)", "Facing",
             "Sign Code", "Description", "Category", "Shape", "Size", "Variant", "Legend", "Edge Ref",
             "Clear of Edge (m)", "Grade (%)", "Design Speed (km/h)", "Post Type",
             "Foundation", "Easting", "Northing", "Remarks", "Face UUID", "Install UUID"]
POST_COLS = ["Post Ref", "Chainage", "Chainage (m)", "Side", "Offset (m)", "No. of Faces",
             "Signs Carried", "Post Type", "Foundation", "Easting", "Northing", "Install UUID"]
QTY_COLS = ["Group", "Item", "Description", "Size", "Unit", "Quantity"]


def _table(ws, name, ncols, nrows, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for c in ws[1]:
        c.font = Font(bold=True)
    ref = f"A1:{get_column_letter(ncols)}{max(nrows, 1) + 1}"
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    ws.freeze_panes = "A2"


def _post_refs(sl: SignList):
    insts = sorted(sl.installations, key=lambda i: (i.lead.station_internal, i.lead.side))
    return insts, {i.install_uuid: (i.post_ref or f"A{n:02d}") for n, i in enumerate(insts, start=1)}


def sign_rows(sl: SignList, cat: Catalogue):
    _, ref = _post_refs(sl)
    faces = sorted(sl.faces, key=lambda f: (f.station_internal, f.side, f.row))
    rows = []
    for n, f in enumerate(faces, start=1):
        sd = cat.signs[f.code]
        rows.append([n, ref[f.install_uuid], format_station(f.station_display),
                     round(f.station_display, 3), f.side, round(f.offset_abs, 2), f.facing,
                     f.code, sd.name, sd.category, sd.shape, f.size,
                     ("Mirrored" if f.mirror else ("As manual" if sd.mirror else "")),
                     legend_summary(f.legend) if f.legend else "", f.edge_ref or None, f.edge_clear,
                     f.grade, f.speed, f.post_type, f.foundation,
                     round(f.x, 3), round(f.y, 3), f.remarks, f.face_uuid, f.install_uuid])
    return rows


LINE_COLS = ["Run No", "Item Code", "Description", "Category", "Pattern", "From Chainage", "To Chainage",
             "From (m)", "To (m)", "Length (m)", "Side", "Offset (m)", "Edge Ref", "Quantity", "Unit",
             "Painted Area (m2)", "Terminals", "Remarks", "Run UUID"]


def line_rows(runs, lcat, al):
    from .linear import run_quantities
    rows = []
    for n, r in enumerate(sorted(runs, key=lambda r: (lcat[r.code].category, r.code, r.sta_start)), start=1):
        it = lcat[r.code]
        v = al.speed_at((r.sta_start + r.sta_end) / 2) if al is not None else None
        q = run_quantities(r, it, v)
        qty = q["count"] if it.is_point_series else round(q["length"], 2)
        pat = it.pattern(v) if it.is_marking else (f"{q['spacing']:g} m interval" if "spacing" in q else "")
        disp = al.display_station if al is not None else (lambda s: s)
        rows.append([n, r.code, it.name, it.category, pat, format_station(disp(r.sta_start)),
                     format_station(disp(r.sta_end)), round(disp(r.sta_start), 3), round(disp(r.sta_end), 3),
                     round(r.length, 2), r.side, round(r.offset, 2), r.edge_ref or None, qty,
                     "No." if it.is_point_series else it.unit,
                     round(q["area"], 2) if "area" in q else None, q.get("terminals"), r.remarks or None, r.uuid])
    return rows


def write_inventory(path: str, sl: SignList, cat: Catalogue, project: str = "", csv_path: str = None,
                    linear=None):
    """linear: (runs, LinearCatalogue, alignment) for the Linear sheet and its quantities."""
    wb = Workbook()
    srows = sign_rows(sl, cat)
    n_s = len(srows)

    # ---- Signs (one row per face)
    ws = wb.active
    ws.title = "Signs"
    ws.append(SIGN_COLS)
    for r in srows:
        ws.append(r)
    _table(ws, "RSD_Signs", len(SIGN_COLS), n_s,
           [8, 9, 11, 11, 6, 10, 10, 12, 30, 12, 11, 8, 10, 34, 9, 10, 9, 10, 10, 11, 13, 13, 24, 38, 38])

    # ---- Posts (one row per installation)
    wp = wb.create_sheet("Posts")
    wp.append(POST_COLS)
    insts, ref = _post_refs(sl)
    for i in insts:
        L = i.lead
        wp.append([ref[i.install_uuid], format_station(L.station_display), round(L.station_display, 3),
                   L.side, round(L.offset_abs, 2), len(i.faces), ", ".join(f.code for f in i.faces),
                   i.post_type, i.foundation, round(L.x, 3), round(L.y, 3), i.install_uuid])
    n_p = len(insts)
    _table(wp, "RSD_Posts", len(POST_COLS), n_p, [9, 11, 11, 6, 10, 9, 34, 10, 11, 13, 13, 38])

    # ---- Quantities (counts only, live formulas)
    wq = wb.create_sheet("Quantities")
    wq.append(QTY_COLS)
    s_last, p_last = n_s + 1, n_p + 1
    combos = OrderedDict()
    for r in srows:
        combos[(r[7], r[11])] = r[8]
    rows = 0
    for (code, size), name in combos.items():
        rows += 1
        rr = rows + 1
        wq.append(["Sign face", code, name, size, "No.",
                   f"=COUNTIFS(Signs!$H$2:$H${s_last},B{rr},Signs!$L$2:$L${s_last},D{rr})"])
    for pid in sorted({i.post_type for i in insts}):
        rows += 1
        wq.append(["Post", pid, cat.posts[pid]["description"], "", "No.",
                   f"=COUNTIF(Posts!$H$2:$H${p_last},B{rows + 1})"])
    for fid in sorted({i.foundation for i in insts}):
        rows += 1
        wq.append(["Foundation", fid, cat.foundations[fid]["description"], "", "No.",
                   f"=COUNTIF(Posts!$I$2:$I${p_last},B{rows + 1})"])
    n_l = 0
    if linear and linear[0]:
        runs, lcat, lal = linear
        wl = wb.create_sheet("Linear", 2)
        wl.append(LINE_COLS)
        lrows = line_rows(runs, lcat, lal)
        for r in lrows:
            wl.append(r)
        n_l = len(lrows)
        _table(wl, "RSD_Linear", len(LINE_COLS), n_l,
               [7, 9, 40, 12, 26, 11, 11, 10, 10, 10, 6, 9, 9, 9, 6, 11, 9, 24, 38])
        l_last = n_l + 1
        seen = OrderedDict()
        for r in lrows:
            seen.setdefault((r[1], r[4]), (r[2], r[3], r[14], lcat[r[1]]))
        for (code, pat), (name, catg, unit, it) in seen.items():
            rows += 1
            rr = rows + 1
            crit = f"Linear!$B$2:$B${l_last},B{rr},Linear!$E$2:$E${l_last},D{rr}"
            wq.append([catg, code, name, pat, unit, f"=SUMIFS(Linear!$N$2:$N${l_last},{crit})"])
            if it.is_marking:
                rows += 1
                rr = rows + 1
                crit = f"Linear!$B$2:$B${l_last},B{rr},Linear!$E$2:$E${l_last},D{rr}"
                wq.append([catg, code, name + " (painted area)", pat, "m2",
                           f"=SUMIFS(Linear!$P$2:$P${l_last},{crit})"])
        terms = OrderedDict()
        for r in lrows:
            it = lcat[r[1]]
            if it.terminal:
                terms[it.terminal] = terms.get(it.terminal, []) + [r[1]]
        for tcode, codes in terms.items():
            t = lcat[tcode]
            rows += 1
            wq.append([t.category, tcode, t.name, "", t.unit,
                       "=" + "+".join(f'SUMIFS(Linear!$Q$2:$Q${l_last},Linear!$B$2:$B${l_last},"{c}")'
                                      for c in dict.fromkeys(codes))])
    _table(wq, "RSD_Quantities", len(QTY_COLS), rows, [16, 15, 40, 26, 6, 10])

    # ---- Checks
    wc = wb.create_sheet("Checks")
    wc.append(["Sign List Row", "Level", "Message"])
    for iss in sorted(sl.issues, key=lambda i: (i.level != "error", i.row)):
        wc.append([iss.row, iss.level.upper(), iss.message])
    if not sl.issues:
        wc.append(["", "", "No issues found."])
    wc.column_dimensions["C"].width = 100
    wc["A1"].font = wc["B1"].font = wc["C1"].font = Font(bold=True)

    # ---- Info
    wi = wb.create_sheet("Info")
    for k, v in [("Project", project), ("Alignment", sl.alignment_name),
                 ("Generated", dt.datetime.now().strftime("%Y-%m-%d %H:%M")),
                 ("Catalogue", cat.version), ("Sign faces", n_s), ("Posts", n_p), ("Linear runs", n_l),
                 ("Note", "Inventory only. Link RSD_Signs / RSD_Posts / RSD_Linear / RSD_Quantities into the QTO; "
                          "do not edit here - regenerate from the sign list.")]:
        wi.append([k, v])
        wi.cell(wi.max_row, 1).font = Font(bold=True)
    wi.column_dimensions["A"].width = 14
    wi.column_dimensions["B"].width = 60
    wb.save(path)

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(SIGN_COLS)
            w.writerows(srows)
