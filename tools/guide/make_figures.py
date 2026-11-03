"""Figures for the user guide and technical manual, from a real LandXML (Olkaria LOT 3 in the demo edition).

Run with the QGIS Python, offscreen, after tools/build_plugin.py:

    QT_QPA_PLATFORM=offscreen python tools/guide/make_figures.py <landxml> <alignment> <out folder> [project name]

Builds a sign project with the auto-placement engine, a directional sign and a
place-name plate, then writes: the map, dock screenshots, report pages (plan,
long section, schedule, findings), a DXF view, the catalogue and legend panels.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsMapRendererParallelJob,  # noqa: E402
                       QgsMapSettings, QgsProject, QgsRectangle)
from qgis.PyQt.QtCore import QRectF, QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402

app = QgsApplication([], True)
app.initQgis()

from roadsign_designer.store import SignStore  # noqa: E402

lx, align, out = sys.argv[1], sys.argv[2], sys.argv[3]
project = sys.argv[4] if len(sys.argv) > 4 else "Demo"
os.makedirs(out, exist_ok=True)
work = os.path.join(out, "_work")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(work)


def save(img, name):
    img.save(os.path.join(out, name), "PNG")
    print("wrote", name)


# ------------------------------------------------------------------ project
from roadsign_designer.rsd.alignment import landxml_crs  # noqa: E402
epsg = landxml_crs(lx).get("epsg") or "21037"
st = SignStore.create(os.path.join(work, "guide.gpkg"), lx, align, QgsCoordinateReferenceSystem(f"EPSG:{epsg}"),
                      project)
st.auto_propose()
st.accept_proposals()
P = lambda s, o: st.al.point_at(s, o)[:2]
st.add_sign(*P(1500, -7.0), "I1-A", legend="^ Olkaria 6\n< Naivasha B3 32\n> Narok B3 120", road_class="A",
            restrict=True)
st.add_sign(*P(1530, -7.0), "I7", legend="Olkaria", restrict=True)
st.auto_propose()                     # leave a few proposals visible (orange) for the figures
st.set_meta(prepared_by="E. Akello", checked_by="", approved_by="")
st.add_to_project()

# ------------------------------------------------------------------ map
def render_map(extent, size, name):
    ms = QgsMapSettings()
    ms.setLayers([l for l in QgsProject.instance().mapLayers().values()])
    order = QgsProject.instance().layerTreeRoot().layerOrder()
    if order:
        ms.setLayers(order)
    ms.setDestinationCrs(st.signs.crs())
    ms.setExtent(extent)
    ms.setOutputSize(QSize(*size))
    ms.setOutputDpi(144)
    ms.setBackgroundColor(QColor("#f7f5ef"))
    job = QgsMapRendererParallelJob(ms)
    job.start(); job.waitForFinished()
    save(job.renderedImage(), name)


x, y = P(2380, 0)
render_map(QgsRectangle(x - 260, y - 170, x + 260, y + 170), (1600, 1050), "fig_map.png")
x, y = P(1515, 0)
render_map(QgsRectangle(x - 70, y - 45, x + 70, y + 45), (1400, 900), "fig_map_legend.png")
x0, y0 = P(st.al.sta_start, 0)
ext = st.alignment_layer.extent() if hasattr(st, "alignment_layer") else QgsRectangle(x0 - 2000, y0 - 2000, x0 + 2000, y0 + 2000)
ext.grow(150)
render_map(ext, (1000, 1300), "fig_map_overview.png")

# ------------------------------------------------------------------ dock
from qgis.gui import QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow, QTabWidget  # noqa: E402
from roadsign_designer.dock import RsdDock  # noqa: E402


class Iface:
    def __init__(self):
        self.win = QMainWindow(); self.canvas = QgsMapCanvas(); self.bar = QgsMessageBar()
    def mapCanvas(self): return self.canvas
    def messageBar(self): return self.bar
    def mainWindow(self): return self.win


iface = Iface()
iface.canvas.setDestinationCrs(st.signs.crs())
dock = RsdDock(iface)
dock.set_store(st)
dock.resize(470, 860)
tabs = dock.findChild(QTabWidget)
for i, name in enumerate(["place", "inventory", "auto", "signs"]):
    tabs.setCurrentIndex(i)
    if name == "auto" and hasattr(dock, "refresh_auto"):
        try:
            dock.refresh_auto()
        except Exception:
            pass
    dock.show(); app.processEvents()
    save(dock.grab().toImage(), f"fig_dock_{name}.png")
dock.hide()

# ------------------------------------------------------------------ report pages
st.accept_proposals()
from roadsign_designer.report import ReportData, pages, write_pngs  # noqa: E402
d = ReportData(st, title=f"Road Signage – {project}", plan_scale=2500)
items = pages(d, 1000.0)
pngs = write_pngs(os.path.join(work, "pages"), d, sheet_len=1000.0, scale=1.6, sheets_only=False)
plans = [p for p in pngs if os.path.basename(p).startswith("plan_")]
secs = [p for p in pngs if os.path.basename(p).startswith("section_")]
others = [p for p in pngs if os.path.basename(p).startswith("page_")]
pick = lambda lst, key: next((p for p in lst if key in os.path.basename(p)), lst[min(2, len(lst) - 1)])
shutil.copy(pick(plans, "_1_910"), os.path.join(out, "fig_report_plan.png"))
shutil.copy(pick(secs, "2_000"), os.path.join(out, "fig_report_section.png"))
if others:
    shutil.copy(others[0], os.path.join(out, "fig_report_schedule.png"))
    kinds = [k for k, _ in items]
    fi = kinds.index("findings") + 1 if "findings" in kinds else None
    if fi:
        fp = [p for p in others if p.endswith(f"page_{fi:02d}.png")]
        if fp:
            shutil.copy(fp[0], os.path.join(out, "fig_report_findings.png"))
print("report pages:", len(items), "plan sheets:", len(plans))

# ------------------------------------------------------------------ DXF view
sl = st.export_civil3d(os.path.join(work, "p.json"), os.path.join(work, "p.dxf"), plan_scale=2500)
try:
    import matplotlib
    matplotlib.use("Agg")
    import ezdxf
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    doc = ezdxf.readfile(os.path.join(work, "p.dxf"))
    for (s, half, name) in ((2380, 230, "fig_dxf.png"), (1515, 90, "fig_dxf_legend.png")):
        fig = plt.figure(figsize=(10, 6.5)); ax = fig.add_axes([0, 0, 1, 1])
        ctx = RenderContext(doc)
        Frontend(ctx, MatplotlibBackend(ax), config=Configuration(background_policy=BackgroundPolicy.CUSTOM,
                                                                  custom_bg_color="#212830")).draw_layout(doc.modelspace())
        cx, cy = P(s, 0)
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(cx - half, cx + half); ax.set_ylim(cy - half * 0.65, cy + half * 0.65)
        fig.set_size_inches(10, 6.5)
        fig.savefig(os.path.join(out, name), dpi=150, facecolor="#212830"); plt.close(fig)
        print("wrote", name)
except Exception as ex:                                   # matplotlib not in this Python
    print("DXF figure skipped:", ex)

# ------------------------------------------------------------------ catalogue and legend panels
from qgis.PyQt.QtSvg import QSvgRenderer  # noqa: E402
from roadsign_designer.rsd.legend import directional_svg, plate_svg  # noqa: E402


def panel(entries, cols, cell, name, title_h=0):
    rows = (len(entries) + cols - 1) // cols
    img = QImage(cols * cell[0], rows * cell[1], QImage.Format.Format_ARGB32)
    img.fill(QColor("#ffffff"))
    p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for i, (svg_or_text, label, sub) in enumerate(entries):
        r, c = divmod(i, cols)
        x, y = c * cell[0], r * cell[1]
        rend = QSvgRenderer(svg_or_text.encode() if svg_or_text.lstrip().startswith("<") else svg_or_text)
        sz = rend.defaultSize()
        box_w, box_h = cell[0] - 24, cell[1] - 52
        sc = min(box_w / max(sz.width(), 1), box_h / max(sz.height(), 1))
        w, h = sz.width() * sc, sz.height() * sc
        rend.render(p, QRectF(x + (cell[0] - w) / 2, y + 8 + (box_h - h) / 2, w, h))
        f = QFont("Arial"); f.setPixelSize(15); f.setBold(True); p.setFont(f); p.setPen(QColor("#1d2430"))
        p.drawText(QRectF(x, y + cell[1] - 42, cell[0], 18), int(Qt.AlignmentFlag.AlignHCenter), label)
        f.setBold(False); f.setPixelSize(12); p.setFont(f); p.setPen(QColor("#5b6575"))
        p.drawText(QRectF(x + 4, y + cell[1] - 24, cell[0] - 8, 18), int(Qt.AlignmentFlag.AlignHCenter), sub[:30])
    p.end()
    save(img, name)


cat = st.cat
want = ["W19", "W20", "W21", "W22", "W24-a", "W30", "W31", "W5", "W1", "W40", "P1", "P32",
        "P23", "P29", "M1", "I7", "RW1", "RW15"]
ents = [(cat.signs[c].svg(), c, cat.signs[c].name) for c in want if c in cat.signs]
panel(ents[:18], 6, (220, 210), "fig_catalogue.png")
panel([(directional_svg("^ Nakuru A104 18\n< Eldoret A104 140\n> Rongai 9", "A"), "Class A road", "green, route in yellow"),
       (directional_svg("^ Mai Mahiu 40\n> Nairobi A104 60", "EXP"), "Expressway", "blue face"),
       (directional_svg("< Olkaria\n> Naivasha 32", "C"), "Class C/D roads", "white face"),
       (plate_svg("FOR 400 M"), "W23 plate", "distance plate"),
       (plate_svg("Olkaria"), "I7", "place name")], 5, (300, 210), "fig_legends.png")
print("done")
