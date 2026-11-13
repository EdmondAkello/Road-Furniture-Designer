"""rfd/xlsx.py against openpyxl (a development dependency): what RFD writes reads back with the same
values and formatting, and workbooks saved by other programs read and edit cleanly."""
import pytest

from rfd.xlsx import (Alignment, DataValidation, Font, PatternFill, Table, TableStyleInfo, Workbook,
                      get_column_letter, load_workbook)

openpyxl = pytest.importorskip("openpyxl")


def _book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Signs"
    ws.append(["Code", "Chainage (m)", "Count", "Note", "Flag"])
    ws.append(["W1", 1234.5, 3, "a & b <c> \"d\"", True])
    ws.append(["W2", 10.0, 0, "", False])
    ws.append(["=", 2.25, "=SUM(C2:C3)", "x\x01y", None])            # "=" alone is text; control chars dropped
    for c in ws[1]:
        c.font = Font(bold=True)
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions[get_column_letter(4)].width = 40
    t = Table(displayName="RSD_Signs", ref="A1:E4")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    ws.freeze_panes = "A2"
    w2 = wb.create_sheet("Lists")
    w2["A1"] = "Title"
    w2["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    w2["A1"].fill = PatternFill("solid", fgColor="1F3864")
    w2["A1"].alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    w2["B2"].font = Font(italic=True, color="666666")
    dv = DataValidation(type="list", formula1='"L,R"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add("E2:E100")
    w2.freeze_panes = w2.cell(5, 1)
    wb.create_sheet("First", 0)
    wb.save(path)


def test_written_workbook_reads_in_openpyxl(tmp_path):
    p = tmp_path / "w.xlsx"
    _book(p)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["First", "Signs", "Lists"]
    ws = wb["Signs"]
    assert [c.value for c in ws[1]] == ["Code", "Chainage (m)", "Count", "Note", "Flag"]
    assert [c.value for c in ws[2]] == ["W1", 1234.5, 3, 'a & b <c> "d"', True]
    assert ws["E3"].value is False and ws["D3"].value in (None, "")
    assert ws["A4"].value == "=" and ws["C4"].value == "=SUM(C2:C3)" and ws["D4"].value == "xy"
    assert ws["A1"].font.b and not ws["A2"].font.b
    assert ws.column_dimensions["A"].width == 12 and ws.column_dimensions["D"].width == 40
    assert ws.freeze_panes == "A2"
    t = ws.tables["RSD_Signs"]
    assert t.ref == "A1:E4" and t.tableStyleInfo.name == "TableStyleMedium2"
    dvs = ws.data_validations.dataValidation
    assert len(dvs) == 1 and dvs[0].formula1 == '"L,R"' and str(dvs[0].sqref) == "E2:E100"
    a1 = wb["Lists"]["A1"]
    assert a1.font.b and a1.font.sz == 14 and a1.font.color.rgb == "FFFFFFFF"
    assert a1.fill.fgColor.rgb == "FF1F3864" and a1.alignment.wrap_text and a1.alignment.horizontal == "center"
    assert wb["Lists"]["B2"].font.i and wb["Lists"].freeze_panes == "A5"


def test_own_round_trip(tmp_path):
    p = tmp_path / "w.xlsx"
    _book(p)
    wb = load_workbook(p)
    ws = wb["Signs"]
    assert ws.cell(2, 1).value == "W1" and ws.cell(2, 2).value == 1234.5 and ws.cell(2, 3).value == 3
    assert ws["D2"].value == 'a & b <c> "d"' and ws["E2"].value is True and ws.max_row == 4
    assert list(ws.iter_rows(min_row=3, values_only=True))[0][:3] == ("W2", 10, 0)


def test_edit_a_workbook_another_program_saved(tmp_path):
    """Read and write back cells of a workbook made elsewhere (here openpyxl, as Excel would: shared
    strings, styles, a table): edited cells change, everything else stays."""
    p = tmp_path / "ext.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Signs"
    ws.append(["Code", "Station", "UUID"])
    ws.append(["W1", "0+100", None])
    ws.append(["W2", "0+200", "keep"])
    ws["A1"].font = openpyxl.styles.Font(bold=True)
    ws["B2"].fill = openpyxl.styles.PatternFill("solid", fgColor="FFF2CC")
    ws.column_dimensions["C"].width = 38
    t = openpyxl.worksheet.table.Table(displayName="T1", ref="A1:C3")
    ws.add_table(t)
    wb.create_sheet("Other")["A1"] = "untouched"
    wb.save(p)

    mine = load_workbook(p)
    s = mine["Signs"]
    assert s["A2"].value == "W1" and s.cell(3, 3).value == "keep" and s.cell(2, 3).value is None
    s.cell(2, 3, "uuid-1")                  # an empty cell in an existing row
    s.cell(2, 2, "0+105")                   # replace a styled shared string
    s.cell(3, 2, 205.5)                     # a number
    s.cell(7, 2, "new row")                 # a row that does not exist yet
    mine.save(str(p))

    back = openpyxl.load_workbook(p)
    b = back["Signs"]
    assert [b.cell(2, c).value for c in (1, 2, 3)] == ["W1", "0+105", "uuid-1"]
    assert b["B3"].value == 205.5 and b["C3"].value == "keep" and b["B7"].value == "new row"
    assert b["B2"].fill.fgColor.rgb == "00FFF2CC" or b["B2"].fill.fgColor.rgb.endswith("FFF2CC")
    assert b["A1"].font.b and b.column_dimensions["C"].width == 38 and "T1" in b.tables
    assert back["Other"]["A1"].value == "untouched"
    assert load_workbook(p)["Signs"].cell(2, 3).value == "uuid-1"
