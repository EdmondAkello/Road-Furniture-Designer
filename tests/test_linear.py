import json

import pytest

from rfd.alignment import Alignment
from rfd import linear as L


@pytest.fixture
def al():
    return Alignment.from_polyline("T", [(0, 0), (1000, 0)])


@pytest.fixture
def cat():
    return L.LinearCatalogue.load()


def test_catalogue_rdm61(cat):
    lm01 = cat["LM01"]
    assert lm01.dims(80)["mark"] == 3.0 and lm01.dims(60)["mark"] == 2.0
    assert lm01.paint_ratio(100) == pytest.approx(0.25)
    assert cat["LM28"].paint_ratio(80) == pytest.approx(1.25)       # continuous + broken
    assert cat["LM32"].paint_ratio(80) == pytest.approx(2.0)
    assert cat["RRS-C"].spacing == 12 and cat["RRS-C"].spacing_no_overtaking == 9
    assert cat["GR-W"].terminal == "GR-TERM"
    assert cat.categories()[:3] == ["Marking", "Road stud", "Barrier"]


def test_run_quantities(cat):
    r = L.Run("LM01", 100, 400)
    q = L.run_quantities(r, cat["LM01"], 80)
    assert q["length"] == 300 and q["painted"] == pytest.approx(75) and q["area"] == pytest.approx(7.5)
    q = L.run_quantities(L.Run("RRS-C", 0, 120), cat["RRS-C"])
    assert q["count"] == 11
    q = L.run_quantities(L.Run("RRS-C", 0, 117, no_overtaking=True), cat["RRS-C"])
    assert q["count"] == 14
    assert L.run_quantities(L.Run("GR-W", 0, 85, side="L", offset=4), cat["GR-W"])["terminals"] == 2


def test_geometry_offsets(al):
    parts = L.geometry(al, L.Run("LM26", 10, 50, side="L", offset=3.5), step=10)
    assert len(parts) == 1 and parts[0][0] == pytest.approx((10, 3.5)) and parts[0][-1] == pytest.approx((50, 3.5))
    parts = L.geometry(al, L.Run("LM26", 10, 50, side="R", offset=3.5), step=10)
    assert parts[0][0][1] == pytest.approx(-3.5)
    assert L.Run("LM01", 50, 10).sta_start == 10
    with pytest.raises(ValueError):
        L.Run("LM01", 0, 1, side="X")


def test_summary(cat, al):
    runs = [L.Run("LM01", 0, 300), L.Run("LM01", 500, 600), L.Run("RRS-C", 0, 120),
            L.Run("GR-W", 0, 100, side="L", offset=4), L.Run("GR-W", 300, 400, side="R", offset=4)]
    rows = {(r[1], r[4]): r[5] for r in L.summarise(runs, cat, al)}
    assert rows[("LM01", "m")] == 400 and rows[("LM01", "m2")] == pytest.approx(10.0)
    assert rows[("RRS-C", "No.")] == 11
    assert rows[("GR-W", "m")] == 200 and rows[("GR-TERM", "No.")] == 4


def test_user_catalogue_overrides(tmp_path, monkeypatch):
    (tmp_path / "tz.json").write_text(json.dumps({"items": [
        {"code": "LM01", "category": "Marking", "name": "Centre line (local)", "rural": {"mark": 4, "gap": 8, "width": 0.15}},
        {"code": "KERB-1", "category": "Kerb", "name": "Precast kerb", "unit": "m"}]}))
    monkeypatch.setenv("RFD_FURNITURE_PATH", str(tmp_path))
    c = L.LinearCatalogue.load()
    assert c["LM01"].dims(100)["mark"] == 4 and "KERB-1" in c and "Kerb" in c.categories()
    assert "LM26" in c


def test_inventory_and_dxf_linear(tmp_path, cat, al):
    import ezdxf
    from openpyxl import load_workbook
    from rfd.catalogue import Catalogue
    from rfd.dxf_out import write_dxf
    from rfd.inventory import write_inventory
    from rfd.records import build_signlist
    runs = [L.Run("LM01", 0, 300), L.Run("LM28", 300, 500), L.Run("RRS-C", 0, 120),
            L.Run("GR-W", 0, 100, side="L", offset=4), L.Run("GR-W", 300, 400, side="R", offset=4)]
    sc = Catalogue.load()
    sl = build_signlist([], al, sc)
    xp = tmp_path / "inv.xlsx"
    write_inventory(str(xp), sl, sc, "T", linear=(runs, cat, al))
    wb = load_workbook(xp)
    assert wb.sheetnames[:4] == ["Signs", "Posts", "Linear", "Quantities"]
    wl = wb["Linear"]
    assert wl.max_row == 6 and "RSD_Linear" in wl.tables
    q = [[c.value for c in r] for r in wb["Quantities"].iter_rows(min_row=2)]
    codes = [(r[1], r[4]) for r in q]
    assert ("LM01", "m") in codes and ("LM01", "m2") in codes and ("GR-TERM", "No.") in codes
    term = [r for r in q if r[1] == "GR-TERM"][0][5]
    assert term.startswith("=SUMIFS(Linear!$Q$2:$Q$6")
    dp = tmp_path / "out.dxf"
    write_dxf(str(dp), sl, al, sc, linear=(runs, cat))
    doc = ezdxf.readfile(str(dp))
    msp = doc.modelspace()
    lm28 = msp.query('LWPOLYLINE[layer=="RSD-MARK-LM28"]')
    assert len(lm28) == 2 and {e.dxf.linetype for e in lm28} == {"BYLAYER", "RSD_3_9"}
    assert len(msp.query('CIRCLE[layer=="RSD-STUD-RRS-C"]')) == 11
    assert len(msp.query('LWPOLYLINE[layer=="RSD-BARRIER-GR-W"]')) == 2
    ys = sorted(e.get_points("xy")[0][1] for e in lm28)     # 0.1 m apart (gap) + 0.1 m line width
    assert ys == pytest.approx([-0.1, 0.1])
