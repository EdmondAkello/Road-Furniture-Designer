"""RoadSign Designer dock: project, sign palette, placement options, live inventory, exports."""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsProject

from .compat import MSG_INFO, MSG_LEVELS, MSG_SUCCESS, MSG_WARNING
from .maptool import PlaceSignTool
from .rsd.alignment import format_station, parse_landxml
from .rsd.legend import SCHEMES, summary as legend_summary
from .store import SVG_DIR, SignStore

SETTINGS_KEY = "roadsign_designer/last_project"


class RsdDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("RoadSign Designer", parent)
        self.iface = iface
        self.store = None
        self.setObjectName("RoadSignDesignerDock")
        w = QWidget()
        lay = QVBoxLayout(w)

        # project row
        row = QHBoxLayout()
        self.btn_new = QPushButton("New project…")
        self.btn_open = QPushButton("Open…")
        row.addWidget(self.btn_new); row.addWidget(self.btn_open)
        lay.addLayout(row)
        self.lbl_project = QLabel("No project open")
        self.lbl_project.setWordWrap(True)
        lay.addWidget(self.lbl_project)

        tabs = QTabWidget()
        lay.addWidget(tabs)

        # ---------------- Place tab
        pw = QWidget(); pl = QVBoxLayout(pw)
        frow = QHBoxLayout()
        self.cmb_cat = QComboBox(); self.cmb_cat.addItem("All categories")
        self.search = QLineEdit(); self.search.setPlaceholderText("Search code or name…")
        frow.addWidget(self.cmb_cat); frow.addWidget(self.search, 1)
        pl.addLayout(frow)
        self.palette = QListWidget()
        self.palette.setViewMode(QListWidget.IconMode)
        self.palette.setIconSize(QSize(44, 44))
        self.palette.setGridSize(QSize(112, 90))
        self.palette.setResizeMode(QListWidget.Adjust)
        self.palette.setWordWrap(True)
        self.palette.setMovement(QListWidget.Static)
        pl.addWidget(self.palette, 1)
        form = QFormLayout()
        self.cmb_size = QComboBox()
        self.cmb_facing = QComboBox(); self.cmb_facing.addItems(["Auto (by side)", "Forward", "Backward"])
        self.cmb_ref = QComboBox()
        self.cmb_ref.addItem("Centreline", None)
        self.chk_lock = QCheckBox("Fix offset at")
        self.spn_offset = QDoubleSpinBox(); self.spn_offset.setRange(0.0, 100.0)
        self.spn_offset.setSingleStep(0.5); self.spn_offset.setValue(3.5); self.spn_offset.setSuffix(" m")
        orow = QHBoxLayout(); orow.addWidget(self.chk_lock); orow.addWidget(self.spn_offset)
        self.spn_skew = QDoubleSpinBox(); self.spn_skew.setRange(-180, 180); self.spn_skew.setSuffix("°")
        self.chk_attach = QCheckBox("Add to an existing post (click on it)")
        self.chk_restrict = QCheckBox("Keep inside the corridor (RDM 0.6–3.0 m beyond the edge)")
        self.chk_mirror = QCheckBox("Mirrored (left/right version)")
        form.addRow("Size", self.cmb_size)
        form.addRow("", self.chk_mirror)
        form.addRow("Facing", self.cmb_facing)
        form.addRow("Offset from", self.cmb_ref)
        form.addRow("Offset", orow)
        form.addRow("Skew", self.spn_skew)
        form.addRow("", self.chk_attach)
        form.addRow("", self.chk_restrict)
        pl.addLayout(form)
        self.grp_legend = QGroupBox("Legend")
        gl = QVBoxLayout(self.grp_legend)
        self.txt_legend = QPlainTextEdit()
        self.txt_legend.setPlaceholderText("One destination per line, e.g.\n< Nakuru A104 18\n> Eldoret A104 140\n"
                                           "(^ ahead, < left, > right; route and km optional)")
        self.txt_legend.setFixedHeight(76)
        self.cmb_class = QComboBox()
        for k, v in SCHEMES.items():
            self.cmb_class.addItem(v["label"], k)
        self.cmb_class.setCurrentIndex(1)
        gl.addWidget(self.txt_legend); gl.addWidget(self.cmb_class)
        pl.addWidget(self.grp_legend)
        self.btn_place = QPushButton("Place signs on map")
        self.btn_place.setCheckable(True)
        pl.addWidget(self.btn_place)
        self.lbl_hover = QLabel("—"); self.lbl_hover.setStyleSheet("font-weight: bold;")
        self.lbl_last = QLabel(""); self.lbl_last.setWordWrap(True)
        pl.addWidget(self.lbl_hover); pl.addWidget(self.lbl_last)
        tabs.addTab(pw, "Place")

        # ---------------- Inventory tab
        iw = QWidget(); il = QVBoxLayout(iw)
        self.lbl_totals = QLabel("")
        il.addWidget(self.lbl_totals)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["Item", "Size", "No."])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.verticalHeader().setVisible(False)
        il.addWidget(self.tbl, 2)
        il.addWidget(QLabel("Checks"))
        self.lst_issues = QListWidget()
        il.addWidget(self.lst_issues, 1)
        self.btn_inv = QPushButton("Export inventory (Excel + CSV)…")
        self.btn_c3d = QPushButton("Export to Civil 3D (package + DXF)…")
        self.btn_rb = QPushButton("Import Civil 3D read-back…")
        self.btn_recalc = QPushButton("Recompute all chainages")
        self.btn_report = QPushButton("Road signage report (PDF + PNG sheets + Excel)…")
        for b in (self.btn_report, self.btn_inv, self.btn_c3d, self.btn_rb, self.btn_recalc):
            il.addWidget(b)
        tabs.addTab(iw, "Inventory")

        # ---------------- Auto tab (rule-based proposals)
        aw = QWidget(); al_ = QVBoxLayout(aw)
        self.chk_r_curves = QCheckBox("Curves: bend / sharp-turn warnings, series + distance plate, chevrons")
        self.chk_r_grades = QCheckBox("Steep grades: W30 descent > 5 %, W31 ascent > 10 % (RDM 4.6.4)")
        self.chk_r_overtake = QCheckBox("No overtaking where crest sight distance < passing sight distance")
        for c in (self.chk_r_curves, self.chk_r_grades, self.chk_r_overtake):
            c.setChecked(True); al_.addWidget(c)
        af = QFormLayout()
        def spin(lo, hi, val, suffix, step=1.0):
            w = QDoubleSpinBox(); w.setRange(lo, hi); w.setValue(val); w.setSuffix(suffix); w.setSingleStep(step)
            return w
        self.spn_warn = spin(0, 60, 10, " km/h")
        self.spn_chev = spin(0, 80, 20, " km/h")
        self.spn_sharp = spin(0, 80, 30, " km/h")
        self.spn_e = spin(0, 12, 4, " %", 0.5)
        self.spn_clear = spin(0.6, 3.0, 1.0, " m", 0.1)
        self.spn_from = spin(-1e6, 1e6, 0, " m", 100); self.spn_to = spin(-1e6, 1e6, 0, " m", 100)
        af.addRow("Warn if curve speed below design by", self.spn_warn)
        af.addRow("Chevrons if below by", self.spn_chev)
        af.addRow("Sharp turn (W19/W21) if below by", self.spn_sharp)
        af.addRow("Superelevation if not in LandXML", self.spn_e)
        af.addRow("Post clearance beyond edge", self.spn_clear)
        rr = QHBoxLayout(); rr.addWidget(self.spn_from); rr.addWidget(QLabel("to")); rr.addWidget(self.spn_to)
        af.addRow("Chainage (internal) from", rr)
        al_.addLayout(af)
        self.btn_propose = QPushButton("Propose signs")
        al_.addWidget(self.btn_propose)
        self.lbl_auto = QLabel("Proposals appear with an orange ring. Review them, then accept or remove.")
        self.lbl_auto.setWordWrap(True)
        al_.addWidget(self.lbl_auto)
        self.lst_findings = QListWidget()
        al_.addWidget(self.lst_findings, 1)
        ar = QHBoxLayout()
        self.btn_accept = QPushButton("Accept all proposals")
        self.btn_reject = QPushButton("Remove proposals")
        ar.addWidget(self.btn_accept); ar.addWidget(self.btn_reject)
        al_.addLayout(ar)
        tabs.addTab(aw, "Auto")

        # ---------------- Signs tab (by chainage)
        sw = QWidget(); sl_ = QVBoxLayout(sw)
        self.tbl_signs = QTableWidget(0, 7)
        self.tbl_signs.setHorizontalHeaderLabels(["Post", "Chainage", "Side", "Clear", "Sign", "Size", "Legend"])
        hh = self.tbl_signs.horizontalHeader()
        for c in range(7):
            hh.setSectionResizeMode(c, QHeaderView.Stretch if c == 4 else QHeaderView.ResizeToContents)
        self.tbl_signs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_signs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_signs.verticalHeader().setVisible(False)
        sl_.addWidget(QLabel("Double-click a sign to zoom to it."))
        sl_.addWidget(self.tbl_signs, 1)
        brow = QHBoxLayout()
        self.btn_legend = QPushButton("Edit legend…")
        self.btn_renum = QPushButton("Renumber posts by chainage")
        brow.addWidget(self.btn_legend); brow.addWidget(self.btn_renum)
        sl_.addLayout(brow)
        tabs.addTab(sw, "Signs")
        self.tabs = tabs
        self.setWidget(w)

        self.tool = PlaceSignTool(iface.mapCanvas(), lambda: self.store, self.settings)
        self.tool.hover.connect(self.lbl_hover.setText)
        self.tool.placed.connect(lambda t: self.lbl_last.setText("Placed: " + t))
        self.tool.failed.connect(lambda t: self.iface.messageBar().pushMessage("RoadSign Designer", t, MSG_WARNING, 4))
        self.tool.deactivated.connect(lambda: self.btn_place.setChecked(False))

        self.btn_new.clicked.connect(self.new_project)
        self.btn_open.clicked.connect(self.open_project)
        self.search.textChanged.connect(self._filter)
        self.palette.currentItemChanged.connect(self._sign_selected)
        self.btn_place.toggled.connect(self._toggle_place)
        self.btn_inv.clicked.connect(self.export_inventory)
        self.btn_c3d.clicked.connect(self.export_civil3d)
        self.btn_rb.clicked.connect(self.import_readback)
        self.btn_recalc.clicked.connect(lambda: self.store and self.store.recompute_all())
        self.btn_renum.clicked.connect(self.renumber)
        self.btn_propose.clicked.connect(self.run_auto)
        self.btn_report.clicked.connect(self.export_report)
        self.btn_accept.clicked.connect(lambda: self.store and self.store.accept_proposals())
        self.btn_reject.clicked.connect(lambda: self.store and self.store.remove_proposals())
        self.lst_findings.itemDoubleClicked.connect(self._zoom_finding)
        self.btn_legend.clicked.connect(self.edit_legend)
        self.cmb_cat.currentIndexChanged.connect(lambda _: self._filter(self.search.text()))
        self.tbl_signs.cellDoubleClicked.connect(self._zoom_to)
        self._set_enabled(False)

    # ------------------------------------------------------------------ state
    def _set_enabled(self, on):
        for wdg in (self.btn_place, self.palette, self.btn_inv, self.btn_c3d, self.btn_rb, self.btn_recalc,
                    self.btn_renum, self.btn_legend, self.btn_propose, self.btn_accept, self.btn_reject,
                    self.btn_report):
            wdg.setEnabled(on)

    def settings(self):
        it = self.palette.currentItem()
        facing = ["Auto", "Forward", "Backward"][self.cmb_facing.currentIndex()]
        size = self.cmb_size.currentData() or self.cmb_size.currentText() or None
        sd = self.store.cat.signs.get(it.data(Qt.UserRole)) if (it and self.store) else None
        legend = self.txt_legend.toPlainText().strip() if (sd and sd.legend) else ""
        return {"code": it.data(Qt.UserRole) if it else None, "size": size,
                "legend": legend, "road_class": self.cmb_class.currentData() if legend else "",
                "mirror": self.chk_mirror.isChecked() and self.chk_mirror.isEnabled(),
                "facing": facing, "skew": self.spn_skew.value(),
                "lock_offset": self.spn_offset.value() if self.chk_lock.isChecked() else None,
                "edge_ref": self.cmb_ref.currentData(),
                "restrict": self.chk_restrict.isChecked() and self.chk_restrict.isEnabled(),
                "attach": self.chk_attach.isChecked()}

    def set_store(self, store):
        self.store = store
        store.add_to_project()
        store.changed.connect(self.refresh)
        store.message.connect(lambda t, l: self.iface.messageBar().pushMessage("RoadSign Designer", t,
                                                                            MSG_LEVELS.get(l, MSG_INFO), 5))
        al = store.al
        sp = ", ".join(f"{v:.0f} km/h from {format_station(al.display_station(s), 0)}" for s, v in al.speeds) \
            or "none in LandXML (sizes chosen manually)"
        self.lbl_project.setText(
            f"<b>{os.path.basename(store.gpkg)}</b><br>Alignment {al.name}: "
            f"{al.sta_start:.0f}–{al.sta_end:.0f} m<br>Design speed: {sp}"
            + (f"<br>Road edges: {', '.join(al.edges.codes())}" if al.edges else "")
            + (f"<br>Vertical profile: {len(al.profile.curves)} curves" if al.profile else "")
            + f"<br>Catalogue {store.cat.version}")
        self._fill_palette()
        self.cmb_ref.clear()
        self.cmb_ref.addItem("Centreline", None)
        if al.edges:
            for c in al.edges.codes():
                self.cmb_ref.addItem(f"{c} (road edge)", c)
            ref = store.default_edge_ref()
            if ref:
                self.cmb_ref.setCurrentIndex(self.cmb_ref.findData(ref))
                self.spn_offset.setValue(1.0)
        self.spn_from.setValue(al.sta_start); self.spn_to.setValue(al.sta_end)
        self.chk_restrict.setEnabled(bool(al.edges))
        self.chk_restrict.setChecked(bool(al.edges))
        self._set_enabled(True)
        QgsProject.instance().writeEntry("RoadSignDesigner", "gpkg", store.gpkg)
        self.refresh()

    def _fill_palette(self):
        self.palette.clear()
        cats = self.store.cat.categories()
        self.cmb_cat.blockSignals(True)
        self.cmb_cat.clear(); self.cmb_cat.addItem("All categories"); self.cmb_cat.addItems(cats)
        self.cmb_cat.blockSignals(False)
        import re
        key = lambda c: [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", c)]
        for sd in sorted(self.store.cat.signs.values(), key=lambda s: (cats.index(s.category), key(s.code))):
            it = QListWidgetItem(QIcon(sd.svg()), f"{sd.code}\n{sd.name}")
            it.setData(Qt.UserRole, sd.code)
            it.setData(Qt.UserRole + 1, sd.category)
            it.setToolTip(f"{sd.code}: {sd.name}\n{sd.category}  ·  RDM 6.2 Fig. {sd.figure} (p. {sd.page})"
                          + (f"\n{sd.note}" if sd.note else ""))
            self.palette.addItem(it)
        if self.palette.count():
            self.palette.setCurrentRow(0)

    def _filter(self, text):
        t = text.lower()
        cat = self.cmb_cat.currentText() if self.cmb_cat.currentIndex() > 0 else None
        for i in range(self.palette.count()):
            it = self.palette.item(i)
            hit = t in it.text().lower().replace("\n", " ")
            it.setHidden(not hit or (cat is not None and it.data(Qt.UserRole + 1) != cat))

    def _sign_selected(self, cur, _prev=None):
        self.cmb_size.clear()
        if cur is None or self.store is None:
            return
        sd = self.store.cat.signs[cur.data(Qt.UserRole)]
        if sd.size_rule and self.store.al.speeds or sd.size_rule == "expressway":
            self.cmb_size.addItem("Auto (RDM, by design speed)", "Auto")
        for z in sd.sizes:
            self.cmb_size.addItem(z, z)
        if self.cmb_size.findData("Auto") < 0:
            self.cmb_size.setCurrentIndex(max(0, self.cmb_size.findData(sd.default_size)))
        self.chk_mirror.setEnabled(sd.mirror)
        if not sd.mirror:
            self.chk_mirror.setChecked(False)
        self.grp_legend.setEnabled(bool(sd.legend))
        self.grp_legend.setTitle("Legend" + {"directional": " (destinations)", "plate": " (plate text)",
                                             "label": " (optional text)"}.get(sd.legend or "", " (not used)"))
        self.cmb_class.setEnabled(sd.legend == "directional")

    def _toggle_place(self, on):
        canvas = self.iface.mapCanvas()
        if on:
            canvas.setMapTool(self.tool)
        elif canvas.mapTool() is self.tool:
            canvas.unsetMapTool(self.tool)

    def refresh(self):
        if self.store is None:
            return
        rows, sl = self.store.summary()
        self.tbl.setRowCount(len(rows))
        for r, (grp, item, desc, size, n) in enumerate(rows):
            label = desc if grp == "Sign face" else f"{grp}: {desc}"
            for c, v in enumerate([label, size, str(n)]):
                cell = QTableWidgetItem(v)
                cell.setToolTip(f"{item}\n{desc}")
                if c == 2:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tbl.setItem(r, c, cell)
        faces = sorted(self.store.signs.getFeatures(), key=lambda f: (f["station_int"] or 0, f["side"] or "", f.id()))
        self.tbl_signs.setRowCount(len(faces))
        for r, f in enumerate(faces):
            leg = legend_summary(f["legend"]) if f["legend"] else ""
            ec = f["edge_clear"]
            clr = f"{ec:+.2f} {f['edge_ref'] or ''}".strip() if isinstance(ec, (int, float)) else ""
            for c, v in enumerate([f["post_ref"], f["chainage"], f["side"], clr,
                                   f"{f['sign_code']} {f['description']}", f["size"], leg]):
                cell = QTableWidgetItem("" if v is None else str(v))
                cell.setData(Qt.UserRole, f.id())
                self.tbl_signs.setItem(r, c, cell)
        nprop = len(self.store.proposals())
        self.lbl_totals.setText(f"<b>{len(sl.faces)}</b> sign faces on <b>{len(sl.installations)}</b> posts"
                                + (f" (<b>{nprop}</b> proposed, not yet accepted; exports include accepted "
                                   f"and manual signs only)" if nprop else ""))
        self.lst_issues.clear()
        for i in sorted(sl.issues, key=lambda i: (i.level != "error", i.row)):
            f = self.store.signs.getFeature(i.row)
            tag = f"{f['post_ref']} {f['sign_code']}" if f.isValid() else f"#{i.row}"
            self.lst_issues.addItem(f"{i.level.upper()}  {tag}: {i.message}")
        if not sl.issues:
            self.lst_issues.addItem("No issues.")

    def _zoom_to(self, row, _col):
        fid = self.tbl_signs.item(row, 0).data(Qt.UserRole)
        f = self.store.signs.getFeature(fid)
        if not f.isValid():
            return
        from qgis.core import QgsCoordinateTransform, QgsRectangle
        xf = QgsCoordinateTransform(self.store.signs.crs(), self.iface.mapCanvas().mapSettings().destinationCrs(),
                                    QgsProject.instance())
        p = xf.transform(f.geometry().asPoint())
        self.iface.mapCanvas().setExtent(QgsRectangle(p.x() - 40, p.y() - 40, p.x() + 40, p.y() + 40))
        self.store.signs.selectByIds([fid])
        self.iface.mapCanvas().refresh()

    def edit_legend(self):
        rows = self.tbl_signs.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "RoadSign Designer", "Select a sign in the list first.")
            return
        fid = self.tbl_signs.item(rows[0].row(), 0).data(Qt.UserRole)
        f = self.store.signs.getFeature(fid)
        text, ok = QInputDialog.getMultiLineText(
            self, f"Legend: {f['post_ref']} {f['sign_code']}",
            "One line per destination (< left, ^ ahead, > right; route and km optional):", f["legend"] or "")
        if ok:
            self.store.set_fields(fid, {"legend": text.strip() or None})

    def auto_config(self):
        from .rsd.autoplace import AutoConfig
        return AutoConfig(curves=self.chk_r_curves.isChecked(), grades=self.chk_r_grades.isChecked(),
                          no_overtaking=self.chk_r_overtake.isChecked(), warn_margin=self.spn_warn.value(),
                          chevron_margin=self.spn_chev.value(), sharp_margin=self.spn_sharp.value(),
                          default_e=self.spn_e.value(), clearance=self.spn_clear.value(),
                          edge_ref=self.cmb_ref.currentData(),
                          start=self.spn_from.value(), end=self.spn_to.value())

    def run_auto(self):
        n, findings = self.store.auto_propose(self.auto_config(), restrict=self.chk_restrict.isChecked())
        self.lst_findings.clear()
        names = {"curve": "Curve", "grade_descent": "Steep descent", "grade_ascent": "Steep ascent",
                 "no_overtaking": "No overtaking", "sag_headlight": "Sag (headlights)",
                 "crest_ssd": "Crest (stopping sight)"}
        for f in sorted(findings, key=lambda f: f.start):
            it = QListWidgetItem(f"{format_station(self.store.al.display_station(f.start), 0)}–"
                                 f"{format_station(self.store.al.display_station(f.end), 0)}  "
                                 f"{names.get(f.kind, f.kind)} ({f.direction.lower()}): {f.text}")
            it.setData(Qt.UserRole, (f.start + f.end) / 2)
            self.lst_findings.addItem(it)
        self.lbl_auto.setText(f"<b>{n}</b> signs proposed from <b>{len(findings)}</b> findings. "
                              "Sag/crest sight-distance findings are for the designer (no sign proposed).")

    def _zoom_finding(self, item):
        sta = item.data(Qt.UserRole)
        x, y, _ = self.store.al.point_at(sta)
        from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsRectangle
        xf = QgsCoordinateTransform(self.store.signs.crs(), self.iface.mapCanvas().mapSettings().destinationCrs(),
                                    QgsProject.instance())
        p = xf.transform(QgsPointXY(x, y))
        self.iface.mapCanvas().setExtent(QgsRectangle(p.x() - 250, p.y() - 250, p.x() + 250, p.y() + 250))
        self.iface.mapCanvas().refresh()

    def renumber(self):
        n = self.store.renumber_posts()
        self.iface.messageBar().pushMessage("RoadSign Designer", f"{n} posts renumbered by chainage", MSG_INFO, 4)

    # ------------------------------------------------------------------ project actions
    def new_project(self):
        lx, _ = QFileDialog.getOpenFileName(self, "Road alignment (LandXML)", "", "LandXML (*.xml *.landxml)")
        if not lx:
            return
        try:
            names = [a.name for a in parse_landxml(lx)]
        except Exception as ex:
            QMessageBox.critical(self, "RoadSign Designer", f"Could not read LandXML:\n{ex}")
            return
        if not names:
            QMessageBox.warning(self, "RoadSign Designer", "No horizontal alignments in that file.")
            return
        name = names[0]
        if len(names) > 1:
            name, ok = QInputDialog.getItem(self, "Alignment", "Sign this alignment:", names, 0, False)
            if not ok:
                return
        from .rsd.alignment import landxml_crs
        lxc = landxml_crs(lx)
        crs = QgsCoordinateReferenceSystem(f"EPSG:{lxc['epsg']}") if lxc.get("epsg") else QgsProject.instance().crs()
        if lxc.get("epsg") and crs.isValid():
            pc = QgsProject.instance().crs()
            if pc.isValid() and pc.authid() != crs.authid():
                self.iface.messageBar().pushMessage(
                    "RoadSign Designer", f"Sign layer uses the LandXML's CRS {crs.authid()} ({lxc.get('name', '')}); "
                    f"the QGIS project is {pc.authid()} and will reproject on the fly.", MSG_INFO, 8)
        if not crs.isValid() or crs.isGeographic():
            from qgis.gui import QgsProjectionSelectionDialog
            dlg = QgsProjectionSelectionDialog(self)
            dlg.setWindowTitle("CRS of the LandXML coordinates (projected, metres)")
            if not dlg.exec_():
                return
            crs = dlg.crs()
        gp, _ = QFileDialog.getSaveFileName(self, "Save RSD project", os.path.splitext(lx)[0] + "_signs.gpkg",
                                            "GeoPackage (*.gpkg)")
        if not gp:
            return
        try:
            st = SignStore.create(gp, lx, name, crs, QgsProject.instance().title())
        except Exception as ex:
            QMessageBox.critical(self, "RoadSign Designer", str(ex))
            return
        self.set_store(st)
        self.iface.mapCanvas().setExtent(st.alignment_layer.extent().buffered(50))
        self.iface.mapCanvas().refresh()

    def open_project(self):
        gp, _ = QFileDialog.getOpenFileName(self, "Open RSD project", "", "GeoPackage (*.gpkg)")
        if gp:
            self.open_path(gp)

    def open_path(self, gp):
        try:
            st = SignStore.open(gp)
        except Exception as ex:
            QMessageBox.critical(self, "RoadSign Designer", str(ex))
            return
        self.set_store(st)

    def _need_libs(self, ex):
        QMessageBox.warning(self, "RoadSign Designer",
                            f"{ex}\n\nThe plugin bundles openpyxl and ezdxf in its ext_libs folder; "
                            "reinstall the plugin from the ZIP if that folder is missing.")

    def _report_signatories(self):
        """Prepared / checked / approved by for the title blocks; kept with the project."""
        from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Title block")
        form = QFormLayout(dlg)
        edits = {}
        for key, label in (("prepared_by", "Prepared by"), ("checked_by", "Checked by"), ("approved_by", "Approved by")):
            e = QLineEdit(self.store.meta.get(key, "") or "")
            e.setPlaceholderText("Name or initials")
            form.addRow(label, e)
            edits[key] = e
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                              if hasattr(QDialogButtonBox, "StandardButton") else QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return False
        self.store.set_meta(**{k: e.text().strip() for k, e in edits.items()})
        return True

    def export_report(self):
        base = os.path.splitext(self.store.gpkg)[0]
        p, _ = QFileDialog.getSaveFileName(self, "Road signage report", base + "_Road_Signage_Report.pdf", "PDF (*.pdf)")
        if not p:
            return
        from .report import ReportData, write_pdf, write_pngs, write_xlsx
        from .plansheet import auto_scale
        auto = auto_scale(self.store.al)
        opts = [f"Auto (1:{auto})", "1:500", "1:1000", "1:1250", "1:2000", "1:2500", "1:5000", "No plan sheets"]
        sc, ok = QInputDialog.getItem(self, "Road signage report", "Plan layout sheets (A3) at scale:", opts, 0, False)
        if not ok:
            return
        plan_scale = auto if sc.startswith("Auto") else (None if sc.startswith("No") else float(sc.split(":")[1]))
        if not self._report_signatories():
            return
        proj = self.store.meta.get("project")
        d = ReportData(self.store, self.auto_config(), title="Road Signage" + (f" – {proj}" if proj else ""),
                       plan_scale=plan_scale)
        stem = os.path.splitext(p)[0]
        n = write_pdf(p, d, sheet_len=1000.0)
        pngs = write_pngs(stem + "_sheets", d, sheet_len=1000.0)
        try:
            write_xlsx(stem + ".xlsx", d)
        except ImportError as ex:
            return self._need_libs(ex)
        self.iface.messageBar().pushMessage(
            "RoadSign Designer", f"Report: {n} PDF pages, {len(pngs)} PNG sheets and an Excel workbook → "
            f"{os.path.dirname(p)}", MSG_SUCCESS, 8)

    def export_inventory(self):
        base = os.path.splitext(self.store.gpkg)[0]
        p, _ = QFileDialog.getSaveFileName(self, "Export inventory", base + "_Inventory.xlsx", "Excel (*.xlsx)")
        if not p:
            return
        try:
            sl = self.store.export_inventory(p)
        except ImportError as ex:
            return self._need_libs(ex)
        self.iface.messageBar().pushMessage(
            "RoadSign Designer", f"Inventory: {len(sl.faces)} faces, {len(sl.installations)} posts → {p}",
            MSG_SUCCESS, 6)

    def export_civil3d(self):
        base = os.path.splitext(self.store.gpkg)[0]
        p, _ = QFileDialog.getSaveFileName(self, "Civil 3D placement package", base + "_placement.json",
                                           "JSON (*.json)")
        if not p:
            return
        scales = ["1:500", "1:1000", "1:1250", "1:2000", "1:2500", "1:5000"]
        sc, ok = QInputDialog.getItem(self, "Plan scale", "Drawing scale for sign symbols and text "
                                      "(symbols print ~10 mm, as in HH drawings):", scales, 4, False)
        if not ok:
            return
        plan_scale = float(sc.split(":")[1])
        try:
            sl = self.store.export_civil3d(p, os.path.splitext(p)[0] + ".dxf", plan_scale=plan_scale)
        except ImportError as ex:
            return self._need_libs(ex)
        except ValueError as ex:
            QMessageBox.warning(self, "RoadSign Designer", str(ex))
            return
        self.iface.messageBar().pushMessage(
            "RoadSign Designer", f"{len(sl.faces)} signs at {sc} → {p}. In Dynamo use symbol scale "
            f"{10 * plan_scale / 1000:g} and the exported DXF as the block source.", MSG_SUCCESS, 10)

    def import_readback(self):
        p, _ = QFileDialog.getOpenFileName(self, "Civil 3D read-back", "", "JSON (*.json)")
        if not p:
            return
        moved, notes = self.store.import_readback(p)
        msg = f"{moved} sign(s) updated from the drawing."
        if notes:
            msg += "\n\n" + "\n".join(notes[:30])
        QMessageBox.information(self, "RoadSign Designer", msg)

    def closeEvent(self, e):
        if self.iface.mapCanvas().mapTool() is self.tool:
            self.iface.mapCanvas().unsetMapTool(self.tool)
        super().closeEvent(e)
