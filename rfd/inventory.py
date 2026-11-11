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


def write_inventory(path: str, sl: SignList, cat: Catalogue, project: str = "", csv_path: str = None):
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
    _table(wq, "RSD_Quantities", len(QTY_COLS), rows, [12, 15, 40, 9, 6, 10])

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
                 ("Catalogue", cat.version), ("Sign faces", n_s), ("Posts", n_p),
                 ("Note", "Inventory only. Link RSD_Signs / RSD_Posts / RSD_Quantities into the QTO; "
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
