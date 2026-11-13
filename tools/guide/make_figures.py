"""Figures for the user guide and technical manual, from the synthetic guide road.

Run with the QGIS Python, offscreen, after tools/build_plugin.py:

    python tools/guide/make_guide_road.py guide_road.xml
    QT_QPA_PLATFORM=offscreen python tools/guide/make_figures.py guide_road.xml DEMO-ROAD <out folder> [project name]

Builds a project on the guide road (tools/guide/make_guide_road.py): auto-placed signs, markings and
studs, barriers on the embankment, a crossing and a hump in the 50 km/h village with its speed limit
zone, a directional sign and a place-name plate. Then writes: map views, dock screenshots, report
pages (plan, long section, strip diagram, schedules, checks), a DXF view and the catalogue and legend
panels. The chainages below refer to the guide road.
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

from road_furniture_designer.store import SignStore  # noqa: E402

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
from road_furniture_designer.rfd.alignment import landxml_crs  # noqa: E402
epsg = landxml_crs(lx).get("epsg") or "21037"
st = SignStore.create(os.path.join(work, "guide.gpkg"), lx, align, QgsCoordinateReferenceSystem(f"EPSG:{epsg}"),
                      project)
st.auto_propose()
st.accept_proposals()
P = lambda s, o: st.al.point_at(s, o)[:2]
from road_furniture_designer.rfd.autoplace import AutoConfig  # noqa: E402
from road_furniture_designer.rfd.barriers import BarrierConfig  # noqa: E402
from road_furniture_designer.rfd.features import FeatureConfig  # noqa: E402
from road_furniture_designer.rfd.markings import MarkingConfig  # noqa: E402
from road_furniture_designer.rfd.speedzones import zones_from_design_speed  # noqa: E402
auto = AutoConfig()
st.lines.auto_propose_markings(MarkingConfig.from_auto(auto, road_class="B"))
st.lines.auto_propose_barriers(BarrierConfig(landxml=lx))
for z in zones_from_design_speed(st.al):                              # the 50 km/h village
    st.add_speed_zone(z.limit, z.start, z.end, auto)
st.add_feature("crossing", 2950.0, FeatureConfig(), auto)
st.add_feature("hump_circular", 3150.0, FeatureConfig(), auto)
st.add_sign(*P(2560, -7.0), "I1-A", legend="^ Nakuru 6\n< Molo B4 32\n> Eldoret A104 120", road_class="A",
            restrict=True)
st.add_sign(*P(2590, -7.0), "I7", legend="Nakuru", restrict=True)
import math  # noqa: E402
jx, jy, jh = st.al.point_at(2300.0)                                   # a skewed type A-1 junction on the straight
st.junctions.place(jx, jy, jx + 30 * math.cos(jh + math.radians(80)), jy + 30 * math.sin(jh + math.radians(80)),
                   kit="A-1")
st.add_sign(*P(2330, -7.0), "WSCM-W37", restrict=True)               # a supplementary sign (loose stones)
from road_furniture_designer.rfd import junctions as J  # noqa: E402
for a, b, off in ((2700.0, 2725.0, -5.0), (2765.0, 2790.0, 5.0)):     # bus bays, one each way, 65 m apart
    pl, B = J.place_bay(st.al, *P(a, off), *P(b, off))
    st.add_junction(pl, "BUS", params={"bay": B})
_ax, _ay, _ah = st.al.point_at(2080.0)                               # a private access on the right
st.add_junction(J.place(st.al, _ax, _ay, _ax + 30 * math.sin(_ah), _ay - 30 * math.cos(_ah)), "ACCESS",
                params={"road_class": "B"})
_rx, _ry, _rh = st.al.point_at(4320.0)                               # a roundabout near the end, third arm left
st.add_junction(J.place_roundabout(st.al, _rx, _ry), "RBT", "", False,
                {"island": 12.0, "arms": [{"bearing_deg": math.degrees(_rh) + 90.0, "src": "click", "half": 3.5}]},
                False, None)
pl, B = J.place_bay(st.al, *P(2420.0, -5.0), *P(2490.0, -5.0))       # a truck parking bay on the straight
st.add_junction(pl, "TRUCK", params={"bay": B})
_sx, _sy, _sh = st.al.point_at(3290.0)                               # a signalised crossroads in the village
st.add_junction(J.place(st.al, _sx, _sy, _sx + 40 * math.cos(_sh + math.pi / 2), _sy + 40 * math.sin(_sh + math.pi / 2)),
                "SIG")
from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer  # noqa: E402
blds = QgsVectorLayer(f"Polygon?crs={st.signs.crs().authid()}", "Buildings (sample)", "memory")
_bf = []
for along, off, w in ((-70.0, 14.0, 6.0), (-150.0, 30.0, 8.0), (60.0, 40.0, 7.0)):   # left of the chainage
    _bx, _by, _bh = st.al.point_at(2300.0 + along, -off)
    _c, _s = math.cos(_bh), math.sin(_bh)
    _bf.append(QgsFeature())
    _bf[-1].setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(_bx + u * _c - v * _s, _by + u * _s + v * _c)
                                                    for u, v in ((-w, -3), (w, -3), (w, 3), (-w, 3), (-w, -3))]]))
blds.dataProvider().addFeatures(_bf)
blds.renderer().symbol().setColor(QColor("#c8b49b"))
QgsProject.instance().addMapLayer(blds)
st.check_sight([blds.id()])
st.accept_proposals(); st.lines.accept_proposals()
st.auto_propose(auto)                 # leave a few proposals visible (orange) for the figures
st.set_meta(prepared_by="E. Akello", checked_by="", approved_by="")
st.add_to_project()

# ------------------------------------------------------------------ map
def render_map(extent, size, name, rotation=0.0):
    ms = QgsMapSettings()
    ms.setLayers([l for l in QgsProject.instance().mapLayers().values()])
    order = QgsProject.instance().layerTreeRoot().layerOrder()
    if order:
        ms.setLayers(order)
    ms.setDestinationCrs(st.signs.crs())
    ms.setExtent(extent)
    ms.setOutputSize(QSize(*size))
    ms.setOutputDpi(144)
    ms.setRotation(rotation)
    ms.setBackgroundColor(QColor("#f7f5ef"))
    job = QgsMapRendererParallelJob(ms)
    job.start(); job.waitForFinished()
    save(job.renderedImage(), name)


x, y = P(740, 0)                                                      # the sharp curve
render_map(QgsRectangle(x - 260, y - 170, x + 260, y + 170), (1600, 1050), "fig_map.png")
x, y = P(2575, 0)                                                     # village entry: directional and place name
render_map(QgsRectangle(x - 70, y - 45, x + 70, y + 45), (1400, 900), "fig_map_legend.png")
x, y = P(3950, 0)                                                     # embankment barriers
render_map(QgsRectangle(x - 300, y - 195, x + 300, y + 195), (1600, 1050), "fig_map_barrier.png")
x, y = P(3050, 0)                                                     # crossing and hump in the village
render_map(QgsRectangle(x - 160, y - 105, x + 160, y + 105), (1600, 1050), "fig_map_calming.png")
x, y = P(2742, 0)                                                     # the two bus bays in the village
render_map(QgsRectangle(x - 50, y - 70, x + 50, y + 70), (1000, 1400), "fig_map_busbay.png")
x, y = P(4320, -12)                                                   # the roundabout
render_map(QgsRectangle(x - 62, y - 48, x + 62, y + 48), (1500, 1160), "fig_map_roundabout.png")
x, y = P(2080, 11)                                                    # the private access
render_map(QgsRectangle(x - 27, y - 18, x + 27, y + 18), (1500, 1000), "fig_map_access.png")
x, y = P(2452, 0)                                                     # the truck parking bay
render_map(QgsRectangle(x - 75, y - 50, x + 75, y + 50), (1500, 1000), "fig_map_truckbay.png")
x, y = P(3290, 0)                                                     # the signalised crossroads
render_map(QgsRectangle(x - 60, y - 40, x + 60, y + 40), (1500, 1000), "fig_map_signals.png")
cx, cy, ch = st.al.point_at(2300.0, -14.0)                           # type A-1 junction with its widening,
az = 90.0 - math.degrees(ch)                                          # road turned to run across the figure
jw = 150.0
render_map(QgsRectangle(cx - jw / 2, cy - jw * 1050 / 3200, cx + jw / 2, cy + jw * 1050 / 3200), (1600, 1050),
           "fig_map_junction.png", rotation=-(az - 90.0))
cx, cy, ch = st.al.point_at(2300.0, -22.0)                           # the A-1 junction's visibility splays,
az = 90.0 - math.degrees(ch)                                          # road turned to run across the figure
sw = 2 * 270.0
render_map(QgsRectangle(cx - sw / 2, cy - sw * 460 / 3200, cx + sw / 2, cy + sw * 460 / 3200), (1600, 460),
           "fig_map_splays.png", rotation=-(az - 90.0))
x0, y0 = P(st.al.sta_start, 0)
ext = st.alignment_layer.extent() if hasattr(st, "alignment_layer") else QgsRectangle(x0 - 2000, y0 - 2000, x0 + 2000, y0 + 2000)
ext.grow(150)
render_map(ext, (1000, 1300), "fig_map_overview.png")

# ------------------------------------------------------------------ dock
from qgis.gui import QgsMapCanvas, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow, QTabWidget, QTableWidgetItem  # noqa: E402
from road_furniture_designer.dock import RsdDock  # noqa: E402


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
names = {"Outputs": "outputs", "Auto": "auto", "Section": "section", "Signs": "signs",
         "Linear": "linear",
         "Calming": "calming", "Speed limits": "speed", "Junctions + bays": "junctions"}
for i in range(tabs.count()):
    name = names.get(tabs.tabText(i))
    if not name:
        continue
    tabs.setCurrentIndex(i)
    if name == "auto" and hasattr(dock, "refresh_auto"):
        try:
            dock.refresh_auto()
        # Figure script: an empty Auto list is acceptable.
        except Exception:  # nosec B110
            pass
    if name == "section":            # the guide road has a corridor: show a section as it would be typed
        dock._ts_use_standard()
        dock.tbl_ts.setItem(0, 1, QTableWidgetItem("2600"))
        dock.tbl_ts.insertRow(1)
        for c, v in enumerate(("2600", "3350", "ETW 3.5, EPS 1.5, Walkway 3", "ETW 3.5, EPS 1.5, Walkway 3")):
            dock.tbl_ts.setItem(1, c, QTableWidgetItem(v))
        dock.tbl_ts.insertRow(2)
        for c, v in enumerate(("3350", "", "ETW 3.5, EPS 2", "ETW 3.5, EPS 2")):
            dock.tbl_ts.setItem(2, c, QTableWidgetItem(v))
    dock.show(); app.processEvents()
    save(dock.grab().toImage(), f"fig_dock_{name}.png")
dock.hide()

# ------------------------------------------------------------------ report pages
st.accept_proposals()
from road_furniture_designer.report import ReportData, pages, write_pngs  # noqa: E402
d = ReportData(st, auto, title=f"Road Furniture – {project}", plan_scale=2500,
               barrier_cfg=BarrierConfig(landxml=lx), feature_cfg=FeatureConfig())
items = pages(d, 1000.0)
pngs = write_pngs(os.path.join(work, "pages"), d, sheet_len=1000.0, scale=1.6, sheets_only=False)
plans = [p for p in pngs if os.path.basename(p).startswith("plan_")]
secs = [p for p in pngs if os.path.basename(p).startswith("section_")]
strips = [p for p in pngs if os.path.basename(p).startswith("strip_")]
pick = lambda lst, key: next((p for p in lst if key in os.path.basename(p)), lst[min(1, len(lst) - 1)])
shutil.copy(pick(plans, "plan_01"), os.path.join(out, "fig_report_plan.png"))
shutil.copy(pick(secs, "1_000"), os.path.join(out, "fig_report_section.png"))
shutil.copy(pick(strips, "strip_3_000"), os.path.join(out, "fig_report_strip.png"))
kinds = [(k, p[0] if k == "ftable" else None) for k, p in items]


def first_page(kind, key=None):
    for i, (k, t) in enumerate(kinds, start=1):
        if k == kind and (key is None or t == key):
            fp = [p for p in pngs if p.endswith(f"page_{i:02d}.png")]
            return fp[0] if fp else None


for kind, key, name in (("schedule", None, "fig_report_schedule.png"), ("findings", None, "fig_report_findings.png"),
                        ("ftable", "markings", "fig_report_markings.png"), ("ftable", "features", "fig_report_features.png"),
                        ("ftable", "checks", "fig_report_checks.png"),
                        ("ftable", "junctions", "fig_report_junctions.png")):
    fp = first_page(kind, key)
    if fp:
        shutil.copy(fp, os.path.join(out, name))
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
    for (s, half, name) in ((740, 230, "fig_dxf.png"), (2575, 90, "fig_dxf_legend.png")):
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
from road_furniture_designer.rfd.legend import directional_svg, plate_svg  # noqa: E402


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
want = ["W19", "W20", "W21", "W22", "W24-a", "W30", "W31", "W55", "W64", "P5", "P9", "P32",
        "END", "W23", "M1", "I7", "RW1", "RW15"]
ents = [(cat.signs[c].svg(), c, cat.signs[c].name) for c in want if c in cat.signs]
panel(ents[:18], 6, (220, 210), "fig_catalogue.png")
wscm = sorted((c for c in cat.signs if c.startswith("WSCM-")), key=lambda c: (c[5], int("".join(ch for ch in c[6:] if ch.isdigit()))))
panel([(cat.signs[c].svg(), c, cat.signs[c].name) for c in wscm], 5, (240, 210), "fig_wscm.png")
panel([(directional_svg("^ Nakuru A104 18\n< Eldoret A104 140\n> Molo 9", "A"), "Class A road", "green, route in yellow"),
       (directional_svg("^ Thika 40\n> Nairobi A2 60", "EXP"), "Expressway", "blue face"),
       (directional_svg("< Molo\n> Nakuru 32", "C"), "Class C/D roads", "white face"),
       (plate_svg("FOR 400 M"), "W23 plate", "distance plate"),
       (plate_svg("Nakuru"), "I7", "place name")], 5, (300, 210), "fig_legends.png")
print("done")
