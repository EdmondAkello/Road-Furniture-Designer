import json
import os

import pytest
from openpyxl import load_workbook

from rfd.alignment import parse_landxml
from rfd.catalogue import Catalogue
from rfd.cli import main
from rfd.signlist import COLUMNS, FIRST_ROW, block_rotation_deg, make_template, read_signlist
from examples.make_demo_road import build, to_landxml
from examples.make_demo_signlist import ROWS


@pytest.fixture
def setup(tmp_path):
    xml = tmp_path / "road.xml"
    xml.write_text(to_landxml(build()))
    xl = tmp_path / "signs.xlsx"
    cat = Catalogue.load()
    make_template(str(xl), cat, "DEMO-RD")
    return tmp_path, str(xml), str(xl), cat


def _fill(xl, rows):
    wb = load_workbook(xl)
    ws = wb["Signs"]
    for i, row in enumerate(rows):
        for j, v in enumerate(row, start=1):
            ws.cell(FIRST_ROW + i, j, v if v != "" else None)
    wb.save(xl)


def test_uuids_written_back_and_stable(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, ROWS)
    al = parse_landxml(xml)[0]
    a = read_signlist(xl, al, cat)
    assert a.ok and len(a.faces) == len(ROWS)
    b = read_signlist(xl, al, cat)            # second run: same identities
    assert [f.face_uuid for f in a.faces] == [f.face_uuid for f in b.faces]
    assert [i.install_uuid for i in a.installations] == [i.install_uuid for i in b.installations]
    assert len({f.face_uuid for f in a.faces}) == len(ROWS)


def test_shared_post_grouping(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, ROWS)
    sl = read_signlist(xl, parse_landxml(xml)[0], cat)
    p08 = [i for i in sl.installations if i.post_ref == "P08"]
    assert len(p08) == 1 and len(p08[0].faces) == 2
    assert len(sl.installations) == len(ROWS) - 1


def test_copied_row_gets_new_uuid(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, ROWS[:2])
    al = parse_landxml(xml)[0]
    read_signlist(xl, al, cat)
    wb = load_workbook(xl); ws = wb["Signs"]
    for c in range(1, len(COLUMNS) + 1):       # engineer copies row 1 to row 3
        ws.cell(FIRST_ROW + 2, c, ws.cell(FIRST_ROW, c).value)
    ws.cell(FIRST_ROW + 2, 1, "P03"); ws.cell(FIRST_ROW + 2, 2, "0+300")
    wb.save(xl)
    sl = read_signlist(xl, al, cat)
    assert len({f.face_uuid for f in sl.faces}) == 3
    assert any("Duplicate Face UUID" in i.message for i in sl.issues)


def test_errors_reported(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, [
        ("", "0+100", 3, "L", "Forward", "NOPE", "", "", "", 0, "", "", "", ""),
        ("", "9+000", 3, "L", "Forward", "W64", "", "", "", 0, "", "", "", ""),
        ("", "0+100", 3, "X", "Forward", "W64", "", "", "", 0, "", "", "", ""),
        ("", "0+100", 3, "L", "Forward", "W64", "1500", "", "", 0, "", "", "", ""),
        ("Q", "0+100", 3, "L", "Forward", "W64", "", "", "", 0, "", "", "", ""),
        ("Q", "0+140", 3, "L", "Forward", "W64", "", "", "", 0, "", "", "", ""),
    ])
    sl = read_signlist(xl, parse_landxml(xml)[0], cat)
    msgs = " | ".join(i.message for i in sl.issues if i.level == "error")
    for frag in ("Unknown sign code", "outside alignment", "Side must be", "not available", "different positions"):
        assert frag in msgs
    assert not sl.ok


def test_far_side_warning_skips_markers(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, [("", "0+100", 3, "R", "Forward", "W64", "", "", "", 0, "", "", "", ""),
               ("", "0+500", 3, "R", "Forward", "W24-a", "", "", "", 0, "", "", "", "")])
    sl = read_signlist(xl, parse_landxml(xml)[0], cat)
    warns = [i for i in sl.issues if i.level == "warning"]
    assert len(warns) == 1 and "far side" in warns[0].message


def test_rotation_convention():
    import math
    # eastbound road; forward sign faces west-bound view => +Y must point west (180 deg) => rot 90
    assert block_rotation_deg(0.0, "Forward") == pytest.approx(90.0)
    assert block_rotation_deg(0.0, "Backward") == pytest.approx(270.0)
    assert block_rotation_deg(math.pi / 2, "Forward") == pytest.approx(180.0)


def test_cli_end_to_end(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, ROWS)
    out = tmp / "out"
    assert main(["build", xl, xml, "--out", str(out)]) == 0
    pkg = json.loads((out / "signs_placement.json").read_text())
    assert len(pkg["faces"]) == len(ROWS)
    f = [x for x in pkg["faces"] if x["station_display_text"] == "0+950.000"][0]
    assert f["station_internal"] == pytest.approx(900.0)      # station equation applied
    assert os.path.exists(out / "signs_placed.dxf")
    assert os.path.exists(out / "signs_Inventory.xlsx")
    assert os.path.exists(out / "signs_Inventory.csv")
    import ezdxf
    doc = ezdxf.readfile(out / "signs_placed.dxf")
    refs = [e for e in doc.modelspace() if e.dxftype() == "INSERT"]
    assert len(refs) == len(ROWS)
    xd = refs[0].get_xdata("RSD")
    assert xd[1].value in {x["face_uuid"] for x in pkg["faces"]}


def test_cli_blocks_on_errors(setup):
    tmp, xml, xl, cat = setup
    _fill(xl, [("", "0+100", 3, "L", "Forward", "NOPE", "", "", "", 0, "", "", "", "")])
    out = tmp / "out"
    assert main(["build", xl, xml, "--out", str(out)]) == 2
    assert not (out / "signs_placement.json").exists()


def test_roundtrip_move_in_drawing(setup):
    """Place -> move/rotate one block in the 'drawing' -> read back -> reconcile."""
    import ezdxf
    from rfd.dxf_out import readback_dxf
    from rfd.reconcile import reconcile
    tmp, xml, xl, cat = setup
    _fill(xl, ROWS)
    out = tmp / "out"
    assert main(["build", xl, xml, "--out", str(out)]) == 0
    al = parse_landxml(xml)[0]
    dxf = out / "signs_placed.dxf"
    doc = ezdxf.readfile(dxf)
    pkg = json.loads((out / "signs_placement.json").read_text())
    target = [f for f in pkg["faces"] if f["sign_code"] == "W20" and f["mirror"]][0]
    for e in doc.modelspace().query("INSERT"):
        if e.get_xdata("RSD")[1].value == target["face_uuid"]:
            x, y, _ = al.point_at(230.0, -4.0)          # engineer drags it to 0+230, 4.0 m left
            e.dxf.insert = (x, y)
        if e.dxf.name.startswith(("RSD_W64", "RSDC_W64_")):
            e.dxf.rotation = (e.dxf.rotation + 180) % 360   # flipped to face the other way
    doc.saveas(dxf)
    rb = tmp / "rb.json"
    rb.write_text(json.dumps(readback_dxf(str(dxf))))
    changes, notes = reconcile(xl, str(rb), al, cat)
    got = {(c.row, c.field): c.new for c in changes}
    row_curve = FIRST_ROW + 1
    row_hump = FIRST_ROW + 9
    assert got[(row_curve, "station")] == "0+230.000"
    assert got[(row_curve, "offset")] == "4.0"
    assert got[(row_hump, "facing")] == "Backward"
    assert len({r for r, _ in got}) == 2           # nothing else touched
    assert not notes
    # sign list now builds cleanly with the new values and same identities
    sl = read_signlist(xl, al, cat)
    f = [f for f in sl.faces if f.face_uuid == target["face_uuid"]][0]
    assert f.station_display == pytest.approx(230.0) and f.side == "L"
