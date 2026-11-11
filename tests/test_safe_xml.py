"""LandXML files that declare a DOCTYPE or entities are refused before parsing."""
import io

import pytest

from rfd.alignment import landxml_crs, parse_landxml
from rfd.safe_xml import UnsafeXmlError, check
from examples.make_demo_road import build, to_landxml

GOOD = to_landxml(build())
BOMB = ('<?xml version="1.0"?>\n<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>\n'
        '<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2"><Alignments>&lol2;</Alignments></LandXML>')
XXE = ('<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY ext SYSTEM "file:///etc/passwd">]>\n'
       '<LandXML><Project name="&ext;"/></LandXML>')


def test_real_files_pass(tmp_path):
    check(GOOD)
    p = tmp_path / "road.xml"
    p.write_text(GOOD)
    check(str(p))
    assert parse_landxml(str(p)) and parse_landxml(GOOD)
    commented = GOOD.replace("<LandXML", "<!-- exported by Civil 3D; no <!DOCTYPE here --><LandXML", 1)
    assert parse_landxml(commented)


@pytest.mark.parametrize("bad", [BOMB, XXE, '<?xml version="1.0"?><!doctype LandXML><LandXML/>'])
def test_doctype_and_entities_refused(bad, tmp_path):
    with pytest.raises(UnsafeXmlError):
        parse_landxml(bad)
    p = tmp_path / "bad.xml"
    p.write_text(bad)
    with pytest.raises(UnsafeXmlError):
        parse_landxml(str(p))
    with pytest.raises(UnsafeXmlError):
        landxml_crs(str(p))


def test_stream_position_kept():
    b = io.BytesIO(GOOD.encode())
    b.read(10)
    check(b)
    assert b.tell() == 10
