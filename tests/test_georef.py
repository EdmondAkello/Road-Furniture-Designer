"""The DXF must carry the LandXML's own world coordinates, so signs can be pasted at original coordinates."""
import json
import xml.etree.ElementTree as ET

import ezdxf
import pytest

from rsd.alignment import landxml_crs, parse_landxml
from rsd.catalogue import Catalogue
from rsd.dxf_out import write_dxf
from rsd.package import build_package
from rsd.records import build_signlist
from examples.make_demo_road import build, to_landxml

CS = ('<CoordinateSystem desc="Arc 1960 / UTM zone 37S" epsgCode="21037" '
      'horizontalCoordinateSystemName="ARC1960.UTM-37S" horizontalDatum="ARC1960"/>')


def _xml():
    x = to_landxml(build())
    return x.replace("<Units>", CS + "<Units>", 1)


def test_landxml_crs():
    c = landxml_crs(_xml())
    assert c["epsg"] == "21037" and c["map_zone"] == "ARC1960.UTM-37S" and "37S" in c["name"]
    assert landxml_crs(to_landxml(build())) == {}


def test_dxf_world_coordinates(tmp_path):
    xml = _xml()
    al = parse_landxml(xml)[0]
    cat = Catalogue.load()
    recs = [{"ref": 1, "station": 250, "offset": 4.0, "side": "L", "facing": "Forward", "code": "W20"},
            {"ref": 2, "station_internal": 900, "offset": 4.0, "side": "R", "facing": "Backward", "code": "W64"}]
    sl = build_signlist(recs, al, cat)
    out = tmp_path / "g.dxf"
    write_dxf(str(out), sl, al, cat, plan_scale=1000, crs=landxml_crs(xml), source="road.xml")
    doc = ezdxf.readfile(out)
    # header: metres, CCW from east, CRS recorded
    assert doc.header["$INSUNITS"] == 6 and doc.header["$ANGBASE"] == 0 and doc.header["$ANGDIR"] == 0
    cv = dict(doc.header.custom_vars)
    assert cv["RSD_CRS"].startswith("EPSG:21037") and cv["RSD_SOURCE_LANDXML"] == "road.xml"
    # sign inserts sit exactly on the LandXML-derived positions (E, N), no shift
    ins = {e.get_xdata("RSD")[1].value: e for e in doc.modelspace().query("INSERT")}
    for f in sl.faces:
        e = ins[f.face_uuid]
        assert e.dxf.insert.x == pytest.approx(f.x, abs=1e-6) and e.dxf.insert.y == pytest.approx(f.y, abs=1e-6)
        x, y, _ = al.point_at(f.station_internal, f.offset_signed)
        assert (e.dxf.insert.x, e.dxf.insert.y) == pytest.approx((x, y), abs=1e-6)
    # reference alignment starts exactly at the LandXML <Start> (stored N E -> E, N)
    root = ET.fromstring(xml)
    start = [el for el in root.iter() if el.tag.endswith("Start")][0].text.split()
    n0, e0 = float(start[0]), float(start[1])
    pl = [e for e in doc.modelspace().query("LWPOLYLINE") if e.dxf.layer == "RSD-ALIGN"][0]
    assert pl.get_points("xy")[0] == pytest.approx((e0, n0), abs=1e-6)
    # reference layers do not plot; signs do
    assert doc.layers.get("RSD-ALIGN").dxf.plot == 0 and doc.layers.get("RSD-REF-NOTES").dxf.plot == 0
    assert doc.layers.get("RSD-SIGN").dxf.get("plot", 1) == 1
    # check point carries its own coordinates
    mt = [e for e in doc.modelspace().query("MTEXT") if e.dxf.layer == "RSD-REF-NOTES"][0]
    assert f"E {e0:.3f}  N {n0:.3f}" in mt.text
    lo, hi = doc.header["$EXTMIN"], doc.header["$EXTMAX"]
    assert lo[0] <= e0 <= hi[0] and lo[1] <= n0 <= hi[1] and hi[0] - lo[0] < 5000   # real extents for Zoom Extents
    pkg = build_package(sl, al, cat, "t", landxml_crs(xml))
    assert pkg["crs"]["epsg"] == "21037"
