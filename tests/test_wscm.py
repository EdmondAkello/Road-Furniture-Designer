"""Supplementary signs from the Ministry's standard drawings WSCM/84/2/01 (not in RDM 6.2)."""
import json
from pathlib import Path

from rfd import furniture_report as FR
from rfd.catalogue import Catalogue
from tests.test_bootstrap import random_road
from tests.test_furniture_report import sign

DATA = Path(__file__).resolve().parents[1] / "rfd" / "data"


def _json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_wscm_codes_never_collide_with_rdm():
    cat = Catalogue.load()
    rdm = {s["code"] for s in _json("rdm_signs.json")["signs"]} if (DATA / "rdm_signs.json").exists() else set()
    wscm = _json("wscm_signs.json")["signs"]
    assert len(wscm) == 19
    for s in wscm:
        assert s["code"] == "WSCM-" + s["wscm_code"]
        assert s["code"] not in rdm
        assert s["code"] in cat.signs
        assert (DATA / "signs" / f"{s['code']}.svg").exists()
    sup = [c for c, s in cat.signs.items() if c.startswith("WSCM-")]
    assert len(sup) == 19
    assert not [c for c in cat.signs if c.startswith("WSCM") and not c.startswith("WSCM-")]


def test_wscm_blocks_in_library():
    ezdxf = __import__("pytest").importorskip("ezdxf")
    doc = ezdxf.readfile(DATA / "RSD_SignBlocks.dxf")
    names = {b.name for b in doc.blocks}
    for s in _json("wscm_signs.json")["signs"]:
        assert f"RSD_{s['code']}" in names


def test_crossref_covers_every_wscm_code():
    cat = Catalogue.load()
    xr = _json("wscm_crossref.json")["signs"]
    assert len(xr) == 75
    for code, row in xr.items():
        assert row["match"] in ("same", "similar", "none")
        if row.get("rfd"):
            assert row["rfd"] in cat.signs, code
        if row["match"] == "none":
            assert row["rfd"] == "WSCM-" + code, code


def test_end_of_all_prohibitions_closes_speed_and_overtaking():
    al, _ = random_road(2)
    a = al.sta_start
    for start in ("P5", "P32", "P14"):
        s = [sign(a + 100, start), sign(a + 600, "WSCM-M14")]
        kinds = [c.kind for c in FR.pairing_checks(al, s) if c.kind == "sign_unclosed"]
        assert not kinds, start
    assert not [c for c in FR.pairing_checks(al, [sign(a + 100, "WSCM-M9"), sign(a + 500, "WSCM-M8")])
                if c.kind == "sign_unclosed"]
    assert [c.kind for c in FR.pairing_checks(al, [sign(a + 100, "WSCM-M9")])] == ["sign_unclosed"]


def test_supplementary_signs_listed_for_the_reviewer():
    al, _ = random_road(2)
    a = al.sta_start
    assert not FR.supplementary_checks(al, [sign(a + 100, "W37")])
    out = FR.supplementary_checks(al, [sign(a + 300, "WSCM-W22"), sign(a + 100, "WSCM-I3"), sign(a + 200, "W37")])
    assert len(out) == 1 and out[0].level == "info" and out[0].kind == "sign_supplementary"
    assert out[0].values["codes"] == ["WSCM-I3", "WSCM-W22"]
    assert out[0].start == a + 100 and out[0].end == a + 300
