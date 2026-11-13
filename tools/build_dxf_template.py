"""Build rfd/data/RSD_template.dxf: the empty R2018 drawing the plugin's DXF writer (rfd/dxfw.py) starts from.

Standard tables, objects and layouts (ezdxf's setup: linetypes such as DASHED, dimension and text
styles), the RSD application id for XDATA, the RSD_LEGEND text style (Arial, for legend plates)
and every text style the sign block library uses. Run after rebuilding the block library.
Needs ezdxf (a development dependency; the plugin itself does not use it).

    python tools/build_dxf_template.py
"""
import os
import sys

import ezdxf

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "rfd", "data")


def main(out=os.path.join(DATA, "RSD_template.dxf")):
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.M
    doc.appids.new("RSD")
    doc.styles.add("RSD_LEGEND", font="arial.ttf")
    lib = ezdxf.readfile(os.path.join(DATA, "RSD_SignBlocks.dxf"))
    for st in lib.styles:
        if st.dxf.name not in doc.styles:
            doc.styles.add(st.dxf.name, font=st.dxf.get("font", "arial.ttf"))
    for lay in lib.layers:                    # layers the library blocks are drawn on
        if lay.dxf.name not in doc.layers:
            doc.layers.add(lay.dxf.name, color=lay.dxf.get("color", 7))
    doc.saveas(out)
    print("wrote", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main(*sys.argv[1:])
