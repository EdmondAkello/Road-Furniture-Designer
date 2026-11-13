"""Excel sign list (optional import/export; the QGIS layer is the normal master record).

Engineers can fill in the Excel template (one row per sign FACE). Rows that share a
Post Ref are carried on the same post (one installation). The tool assigns UUIDs
and writes them back so identity survives edits and re-runs.
"""
from __future__ import annotations

from .alignment import Alignment
from .catalogue import Catalogue
from .records import (FACING, SCHEMA_VERSION, Face, Installation, Issue, SignList,  # noqa: F401
                      block_rotation_deg, build_signlist)

COLUMNS = [
    # (header, key, width)
    ("Post Ref", "post_ref", 10),
    ("Chainage", "station", 12),
    ("Offset (m)", "offset", 10),
    ("Side (L/R)", "side", 9),
    ("Facing", "facing", 11),
    ("Sign Code", "code", 16),
    ("Size", "size", 10),
    ("Post Type", "post_type", 11),
    ("Foundation", "foundation", 11),
    ("Skew (deg)", "skew", 9),
    ("Mirror (Y/N)", "mirror", 8),
    ("Legend", "legend", 30),
    ("Road Class", "road_class", 8),
    ("Remarks", "remarks", 28),
    ("Face UUID", "face_uuid", 38),
    ("Install UUID", "install_uuid", 38),
]
HEADER_ROW = 4
FIRST_ROW = HEADER_ROW + 1
# --------------------------------------------------------------------------- template
def make_template(path: str, cat: Catalogue, alignment_name: str = "", project: str = ""):
    from .xlsx import Alignment as XAlign, DataValidation, Font, PatternFill, Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Signs"
    ws["A1"] = "Road Furniture Designer - Sign List"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Alignment"
    ws["B2"] = alignment_name
    ws["D2"] = "Project"
    ws["E2"] = project
    for c in ("A2", "D2"):
        ws[c].font = Font(bold=True)
    for c in ("B2", "E2"):
        ws[c].fill = PatternFill("solid", fgColor="FFF2CC")
    ws["G2"] = "One row per sign face. Same Post Ref = same post. UUID columns are filled by the tool - do not edit."
    ws["G2"].font = Font(italic=True, color="666666")

    hdr_fill = PatternFill("solid", fgColor="1F3864")
    for i, (h, _, w) in enumerate(COLUMNS, start=1):
        c = ws.cell(HEADER_ROW, i, h)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = hdr_fill
        c.alignment = XAlign(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[c.column_letter].width = w
    ws.freeze_panes = ws.cell(FIRST_ROW, 1)

    # lookup sheet for dropdowns
    lk = wb.create_sheet("Lists")
    lk["A1"], lk["B1"], lk["C1"], lk["D1"], lk["E1"], lk["F1"] = (
        "Sign Code", "Name", "Shape", "Sizes", "Post Types", "Foundations")
    for r, s in enumerate(cat.signs.values(), start=2):
        lk.cell(r, 1, s.code); lk.cell(r, 2, s.name); lk.cell(r, 3, s.shape)
        lk.cell(r, 4, ", ".join(s.sizes))
    for r, p in enumerate(cat.posts, start=2):
        lk.cell(r, 5, p)
    for r, f in enumerate(cat.foundations, start=2):
        lk.cell(r, 6, f)
    lk.column_dimensions["A"].width = 16
    lk.column_dimensions["B"].width = 30
    n = len(cat.signs) + 1
    last = FIRST_ROW + 999

    def col(key):
        return [i for i, (_, k, _) in enumerate(COLUMNS, 1) if k == key][0]

    def letter(key):
        return ws.cell(1, col(key)).column_letter

    dvs = [
        (DataValidation(type="list", formula1=f"=Lists!$A$2:$A${n}", allow_blank=True), "code"),
        (DataValidation(type="list", formula1='"L,R"', allow_blank=True), "side"),
        (DataValidation(type="list", formula1='"Forward,Backward"', allow_blank=True), "facing"),
        (DataValidation(type="list", formula1=f"=Lists!$E$2:$E${len(cat.posts) + 1}", allow_blank=True), "post_type"),
        (DataValidation(type="list", formula1=f"=Lists!$F$2:$F${len(cat.foundations) + 1}", allow_blank=True), "foundation"),
    ]
    for dv, key in dvs:
        ws.add_data_validation(dv)
        dv.add(f"{letter(key)}{FIRST_ROW}:{letter(key)}{last}")
    grey = PatternFill("solid", fgColor="EDEDED")
    for key in ("face_uuid", "install_uuid"):
        for r in range(FIRST_ROW, FIRST_ROW + 200):
            ws.cell(r, col(key)).fill = grey
    wb.save(path)


# --------------------------------------------------------------------------- reading
def read_signlist(path: str, al: Alignment, cat: Catalogue, write_back: bool = True) -> SignList:
    import shutil
    from .xlsx import load_workbook
    wb = load_workbook(path)
    ws = wb["Signs"]
    keys = [k for _, k, _ in COLUMNS]
    records = []
    for r in range(FIRST_ROW, ws.max_row + 1):
        vals = [ws.cell(r, i + 1).value for i in range(len(keys))]
        if all(v in (None, "") for v in vals[:keys.index("remarks")]):
            continue
        rec = dict(zip(keys, vals))
        rec["ref"] = r
        records.append(rec)
    al_name = str(ws["B2"].value or "").strip() or al.name
    sl = build_signlist(records, al, cat, al_name)
    col = {k: i + 1 for i, k in enumerate(keys)}
    changed = False
    for f in sl.faces:
        for k, v in (("face_uuid", f.face_uuid), ("install_uuid", f.install_uuid)):
            if str(ws.cell(f.row, col[k]).value or "").strip() != v:
                ws.cell(f.row, col[k], v)
                changed = True
    if write_back and changed:
        shutil.copyfile(path, path + ".bak")
        wb.save(path)
    return sl
