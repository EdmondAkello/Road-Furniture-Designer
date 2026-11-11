"""Create a filled demo sign list on the synthetic road (RDM 6.2 codes). Usage: python make_demo_signlist.py out.xlsx"""
import sys

from openpyxl import load_workbook

from rfd.catalogue import Catalogue
from rfd.signlist import COLUMNS, FIRST_ROW, make_template

# post_ref, chainage, offset, side, facing, code, size, post, fdn, skew, mirror, legend, road_class, remarks
ROWS = [
    ("P01", "0+020", 3.5, "L", "Forward", "P7", "750", "", "", 0, "", "", "", "Speed limit 80"),
    ("P02", "0+250", 3.5, "L", "Forward", "W20", "750", "", "", 0, "Y", "", "", "Sharp bend left (mirrored W20)"),
    ("", "0+480", 4.0, "R", "Forward", "W24-a", "", "", "", 0, "", "", "", "Chevron, outside of curve"),
    ("", "0+520", 4.0, "R", "Forward", "W24-a", "", "", "", 0, "", "", "", "Chevron, outside of curve"),
    ("", "0+560", 4.0, "R", "Forward", "W24-a", "", "", "", 0, "", "", "", "Chevron, outside of curve"),
    ("", "0+600", 4.0, "R", "Forward", "W24-a", "", "", "", 0, "", "", "", "Chevron, outside of curve"),
    ("P07", "0+950", 3.5, "R", "Backward", "W20", "750", "", "", 0, "", "", "", "After station equation (internal 900)"),
    ("P08", "1+000", 3.5, "L", "Forward", "P5", "750", "", "", 0, "", "", "", "Two faces, one post"),
    ("P08", "1+000", 3.5, "L", "Forward", "P32", "750", "", "", 0, "", "", "", ""),
    ("P09", "1+150", 3.5, "L", "Forward", "W64", "600", "", "", 0, "", "", "", ""),
    ("P10", "1+200", 3.0, "L", "Forward", "W55", "600", "", "", 0, "", "", "", ""),
    ("P11", "1+200", 3.0, "R", "Backward", "W55", "600", "", "", 0, "", "", "", ""),
    ("P12", "0+700", 4.5, "L", "Forward", "I1-A", "", "POST-DBL", "FDN-LRG", 0, "",
     "< Nakuru A104 18\n> Eldoret A104 140", "A", "Junction ahead"),
]

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "Demo_SignList.xlsx"
    make_template(out, Catalogue.load(), "DEMO-RD", "Demo road (synthetic)")
    wb = load_workbook(out)
    ws = wb["Signs"]
    for i, row in enumerate(ROWS):
        for j, v in enumerate(row, start=1):
            ws.cell(FIRST_ROW + i, j, v if v != "" else None)
    wb.save(out)
    print("wrote", out)
