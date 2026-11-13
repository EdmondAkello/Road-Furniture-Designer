"""rfd/dxfw.py against ezdxf (a development dependency): the drawings it writes audit clean and read back
as written, attributes land where ezdxf puts them, and the read-back reads DXF saved by other programs."""
import math
import os

import pytest

from rfd import dxfw
from rfd.dxf_out import TEMPLATE, readback_dxf

ezdxf = pytest.importorskip("ezdxf")


def _drawing():
    d = dxfw.Drawing(TEMPLATE)
    d.add_layer("RSD-SIGN", 1)
    d.add_layer("RSD-REF", 8, plot=False)
    d.add_linetype("RSD_3_9", [12, 3, -9], "RSD 3 m mark / 9 m gap")
    b = d.new_block("B1")
    b.add_circle((0, 0), 0.06)
    b.add_solid_hatch([(0, 0), (1, 0), (1, 1)], rgb=(200, 16, 46))
    b.add_text("AB", (0.1, 0.2), 0.3, style="RSD_LEGEND", rgb=(1, 2, 3))
    b.add_attdef("SIGN_CODE", (0.7, 0.9), 0.15, layer="RSD-SIGN", invisible=False)
    b.add_attdef("HIDDEN", (1.0, 2.0), 2.0, rotation=-30, align="TOP_CENTER", invisible=True)
    return d


@pytest.mark.parametrize("rot,scale", [(0, 1), (30, 2), (197.5, 0.4), (271, 25)])
def test_attributes_match_ezdxf(tmp_path, rot, scale):
    d = _drawing()
    r = d.modelspace.add_blockref("B1", (100.0, 200.0), layer="RSD-SIGN", rotation=rot, scale=scale)
    d.add_attribs(r, {"SIGN_CODE": "W1", "HIDDEN": "x"})
    r.set_xdata("RSD", [(1000, "rsd/0.1"), (1040, "2.5")])
    p = str(tmp_path / "a.dxf")
    d.saveas(p)
    doc = ezdxf.readfile(p)
    assert not doc.audit().errors
    mine = doc.modelspace().query("INSERT")[0]
    # the same block reference made by ezdxf
    ref = doc.modelspace().add_blockref("B1", (100.0, 200.0), dxfattribs={
        "rotation": rot, "xscale": scale, "yscale": scale, "zscale": scale})
    ref.add_auto_attribs({"SIGN_CODE": "W1", "HIDDEN": "x"})
    for a, b in zip(mine.attribs, ref.attribs):
        assert (a.dxf.tag, a.dxf.text, a.is_invisible) == (b.dxf.tag, b.dxf.text, b.is_invisible)
        assert a.dxf.insert.isclose(b.dxf.insert, abs_tol=1e-6)
        assert a.dxf.height == pytest.approx(b.dxf.height)
        assert a.dxf.get("rotation", 0) % 360 == pytest.approx(b.dxf.get("rotation", 0) % 360, abs=1e-9)
        assert a.dxf.get("halign", 0) == b.dxf.get("halign", 0) and a.dxf.get("valign", 0) == b.dxf.get("valign", 0)
        if a.dxf.get("halign", 0):
            assert a.dxf.align_point.isclose(b.dxf.align_point, abs_tol=1e-6)
    assert [t.value for t in mine.get_xdata("RSD")] == ["rsd/0.1", 2.5]


def test_drawing_audits_clean_and_reads_back(tmp_path):
    d = _drawing()
    m = d.modelspace
    m.add_lwpolyline([(0, 0), (1, 1), (2, 0)], close=True, layer="RSD-SIGN", linetype="RSD_3_9", const_width=0.15)
    m.add_text("1+000", (5, 6), 4.5, layer="RSD-REF", rotation=10, align="MIDDLE_RIGHT")
    m.add_mtext("A\\PB" * 100, (1, 2), 4.5, layer="RSD-REF")            # longer than one 250-character chunk
    m.add_point((1, 2), layer="RSD-REF")
    m.add_line((0, 0), (1, 1))
    m.add_solid_hatch([(0, 0), (3, 0), (3, 1)], layer="RSD-SIGN")
    d.set_header("$INSUNITS", (70, "6"))
    d.custom.append(("RSD_CRS", "EPSG:21037"))
    p = str(tmp_path / "d.dxf")
    d.saveas(p)
    from ezdxf import recover
    doc, auditor = recover.readfile(p)
    assert not auditor.has_errors and not auditor.has_fixes and not doc.audit().errors
    msp = doc.modelspace()
    pl = msp.query("LWPOLYLINE")[0]
    assert pl.closed and pl.dxf.const_width == 0.15 and pl.dxf.linetype == "RSD_3_9"
    assert pl.dxf.flags & 128                       # linetype generation: dashes run on across vertices
    assert msp.query("MTEXT")[0].text == "A\\PB" * 100
    t = msp.query("TEXT")[0]
    assert t.dxf.halign == 2 and t.dxf.valign == 2 and t.dxf.rotation == 10
    assert doc.header["$INSUNITS"] == 6 and doc.header.custom_vars.get("RSD_CRS") == "EPSG:21037"
    assert doc.layers.get("RSD-REF").dxf.plot == 0 and doc.layers.get("RSD-SIGN").dxf.color == 1
    blk = doc.blocks.get("B1")
    assert [e.dxftype() for e in blk] == ["CIRCLE", "HATCH", "TEXT", "ATTDEF", "ATTDEF"]
    assert blk.query("HATCH")[0].rgb == (200, 16, 46) and blk.block.dxf.flags & 2
    tags = dxfw.read_tags(p)
    hdr = len(dxfw.sections(tags)["HEADER"])
    used = [int(v, 16) for c, v in tags[hdr:] if c in (5, 105)]
    assert len(used) == len(set(used))                                  # handles unique
    assert int(doc.header["$HANDSEED"], 16) > max(used)                  # the seed is the next free handle


def test_readback_of_a_drawing_saved_elsewhere(tmp_path):
    """A DXF made by another program (ezdxf here, as Civil 3D would save it): model space sign blocks with
    RSD XDATA and attributes are read; paper space and blocks without XDATA are not."""
    doc = ezdxf.new("R2018")
    doc.appids.new("RSD")
    face = doc.blocks.new("RSD_W1")
    face.add_circle((0, 0), 0.5)
    call = doc.blocks.new("RSDC_W1_1234abcd")
    call.add_blockref("RSD_W1_F", (3, 4), dxfattribs={"xscale": 25, "yscale": 25})
    call.add_attdef("SIGN_CODE", (0, 0))
    doc.blocks.new("RSD_W1_F")
    msp = doc.modelspace()
    r = msp.add_blockref("RSDC_W1_1234abcd", (260000.5, 9950000.25), dxfattribs={"rotation": 375.0})
    r.add_auto_attribs({"SIGN_CODE": "W1"})
    r.set_xdata("RSD", [(1000, "rsd/0.1"), (1000, "face-1"), (1000, "inst-1")])
    msp.add_blockref("RSD_W1", (1, 1))                                    # no XDATA: not one of ours
    ps = doc.layout("Layout1").add_blockref("RSD_W1", (5, 5))
    ps.set_xdata("RSD", [(1000, "rsd/0.1"), (1000, "face-2"), (1000, "inst-2")])
    p = str(tmp_path / "c3d.dxf")
    doc.saveas(p)
    rb = readback_dxf(p)
    assert len(rb["signs"]) == 1
    s = rb["signs"][0]
    assert (s["face_uuid"], s["installation_uuid"], s["block_name"]) == ("face-1", "inst-1", "RSD_W1")
    assert (s["x"], s["y"]) == (260000.5, 9950000.25) and s["rotation_deg"] == pytest.approx(15.0)
    assert s["attributes"] == {"SIGN_CODE": "W1"} and s["handle"] == r.dxf.handle


def test_template_is_current():
    """data/RSD_template.dxf holds the RSD app id, the legend style and the library's text styles."""
    tags = dxfw.read_tags(TEMPLATE)
    names = {dxfw.value(e, 2) for e in dxfw.split_entities(dxfw.sections(tags)["TABLES"])}
    assert {"RSD", "RSD_LEGEND", "DASHED", "OpenSans"} <= names
    assert os.path.getsize(TEMPLATE) < 200_000
