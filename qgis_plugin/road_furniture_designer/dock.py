"""Road Furniture Designer dock: project, sign palette, placement options, live inventory, exports."""
from __future__ import annotations

import os

from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFileDialog,
    QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)
from qgis.core import QgsCoordinateReferenceSystem, QgsProject

from .compat import MSG_INFO, MSG_LEVELS, MSG_SUCCESS, MSG_WARNING
from .maptool import PlaceJunctionTool, PlaceSignTool
from .rfd.alignment import alignment_names, format_station
from .rfd.legend import SCHEMES, summary as legend_summary
from .store import SignStore

SETTINGS_KEY = "road_furniture_designer/last_project"


class _busy:
    """Wait cursor while a LandXML is read, so a short pause never looks like a hang."""
    def __enter__(self):
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor if hasattr(Qt, "CursorShape") else Qt.WaitCursor)

    def __exit__(self, *a):
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.restoreOverrideCursor()
        return False


class RsdDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("Road Furniture Designer", parent)
        self.iface = iface
        self.store = None
        self.setObjectName("RoadFurnitureDesignerDock")
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
        self.btn_report = QPushButton("Road furniture report (PDF + PNG sheets + Excel)…")
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
        self.cmb_crit = QComboBox()
        self.btn_crit = QPushButton("Add…")
        self.btn_crit.setToolTip("Add a criteria file (JSON) for another manual; see docs/criteria in the repository")
        self._load_criteria_list()
        self.chk_psd_red = QCheckBox("Reduced PSD for no-overtaking (RDM 1.3 Table 3.20)")
        self.chk_psd_red.setChecked(True)
        cr = QHBoxLayout(); cr.addWidget(self.cmb_crit, 1); cr.addWidget(self.btn_crit)
        af.addRow("Design criteria", cr)
        af.addRow("", self.chk_psd_red)
        self.spn_msight = QDoubleSpinBox(); self.spn_msight.setRange(0, 30); self.spn_msight.setDecimals(1)
        self.spn_msight.setSuffix(" m"); self.spn_msight.setSpecialValueText("Off (crests only)")
        self.spn_msight.setToolTip("Distance from the centreline to whatever blocks the view on the inside of bends "
                                   "(cut face, wall, vegetation), for the no-overtaking signs and centre line. "
                                   "0 checks visibility over crests only.")
        af.addRow("Sight obstruction on bends", self.spn_msight)
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

        # ---------------- Linear tab (markings, road studs, barriers)
        lw = QWidget(); ll_ = QVBoxLayout(lw)
        lf = QFormLayout()
        self.cmb_litem = QComboBox()
        self.spn_lfrom = QDoubleSpinBox(); self.spn_lto = QDoubleSpinBox()
        for sp in (self.spn_lfrom, self.spn_lto):
            sp.setRange(-1e6, 1e6); sp.setDecimals(1); sp.setSuffix(" m"); sp.setSingleStep(10)
        self.cmb_lside = QComboBox()
        for lab, v in (("From click (map)", "click"), ("Centre", "C"), ("Left", "L"), ("Right", "R")):
            self.cmb_lside.addItem(lab, v)
        self.cmb_lref = QComboBox()
        self.spn_loff = QDoubleSpinBox(); self.spn_loff.setRange(-50, 50); self.spn_loff.setDecimals(2)
        self.spn_loff.setSuffix(" m"); self.spn_loff.setSingleStep(0.05)
        self.chk_lfix = QCheckBox("Fixed offset (else taken from the click)")
        self.chk_lnoot = QCheckBox("No-overtaking section (closer stud interval)")
        self.chk_lflip = QCheckBox("Combined line prohibits traffic against chainage")
        lr = QHBoxLayout(); lr.addWidget(self.spn_lfrom); lr.addWidget(QLabel("to")); lr.addWidget(self.spn_lto)
        lf.addRow("Item", self.cmb_litem)
        lf.addRow("Chainage (internal)", lr)
        lf.addRow("Side", self.cmb_lside)
        lf.addRow("Offset from", self.cmb_lref)
        lf.addRow("Offset", self.spn_loff)
        lf.addRow("", self.chk_lfix)
        lf.addRow("", self.chk_lnoot)
        lf.addRow("", self.chk_lflip)
        ll_.addLayout(lf)
        lb0 = QHBoxLayout()
        self.btn_ldraw = QPushButton("Draw on map (start, end; one click for crossings and humps)")
        self.btn_ldraw.setCheckable(True)
        self.btn_ladd = QPushButton("Add run at chainages")
        lb0.addWidget(self.btn_ldraw); lb0.addWidget(self.btn_ladd)
        ll_.addLayout(lb0)
        self.lbl_lhover = QLabel("")
        ll_.addWidget(self.lbl_lhover)
        mg = QGroupBox("Propose markings and studs (RDM 6.1)")
        mf = QFormLayout(mg)
        self.cmb_mclass = QComboBox()
        self.cmb_mclass.addItem("By design speed", "")
        for c in ("A", "B", "C", "D", "E", "UA", "UC", "UL"):
            self.cmb_mclass.addItem(f"Class {c}", c)
        self.cmb_mstuds = QComboBox()
        for lab, v in (("Auto (all on class A, else no-overtaking sections)", "auto"),
                       ("No-overtaking sections only", "no_overtaking"), ("Everywhere", "all"), ("None", "none")):
            self.cmb_mstuds.addItem(lab, v)
        mf.addRow("Road class", self.cmb_mclass)
        mf.addRow("Road studs", self.cmb_mstuds)
        self.spn_mwidth = QDoubleSpinBox(); self.spn_mwidth.setRange(0, 30); self.spn_mwidth.setDecimals(2)
        self.spn_mwidth.setSuffix(" m"); self.spn_mwidth.setSingleStep(0.5)
        self.spn_mwidth.setSpecialValueText("From the corridor (ETW)")
        self.spn_mwidth.setToolTip("Carriageway width between edge lines. Needed when the LandXML has no corridor "
                                   "edges; otherwise it overrides the measured width for the 5.5 m check.")
        mf.addRow("Carriageway width", self.spn_mwidth)
        self.btn_mprop = QPushButton("Propose markings")
        mf.addRow(self.btn_mprop)
        note = QLabel("The continuous centre line follows the no-overtaking zones of the Auto tab "
                      "(criteria, PSD, sight obstruction, chainage range), so it agrees with the signs.")
        note.setWordWrap(True)
        mf.addRow(note)
        ll_.addWidget(mg)
        bg = QGroupBox("Propose barriers (RDM 1.3 Fig 12.4)")
        bf = QFormLayout(bg)
        self.cmb_bground = QComboBox()
        self.chk_bjudge = QCheckBox("Also where the warrant leaves it to judgement")
        self.spn_baadt = QDoubleSpinBox(); self.spn_baadt.setRange(0, 500000); self.spn_baadt.setDecimals(0)
        self.spn_baadt.setSingleStep(1000); self.spn_baadt.setSpecialValueText("Not given")
        self.spn_baadt.setToolTip("AADT of 12,000 or more with a speed over 80 km/h gives a 0.75 m set-back "
                                  "instead of 0.5 m (RDM 1.3 12.6.6)")
        bf.addRow("Original ground", self.cmb_bground)
        bf.addRow("AADT", self.spn_baadt)
        bf.addRow("", self.chk_bjudge)
        self.btn_bprop = QPushButton("Propose barriers")
        bf.addRow(self.btn_bprop)
        ll_.addWidget(bg)
        self.tbl_lines = QTableWidget(0, 6)
        self.tbl_lines.setHorizontalHeaderLabels(["Item", "From", "To", "Side", "Qty", "Status"])
        hl = self.tbl_lines.horizontalHeader()
        for c in range(6):
            hl.setSectionResizeMode(c, QHeaderView.Stretch if c == 0 else QHeaderView.ResizeToContents)
        self.tbl_lines.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_lines.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_lines.verticalHeader().setVisible(False)
        ll_.addWidget(QLabel("Double-click a run to zoom to it. Edit stations, side or offset in the "
                             "attribute table; the run is redrawn."))
        ll_.addWidget(self.tbl_lines, 1)
        lb = QHBoxLayout()
        self.btn_ldel = QPushButton("Delete selected")
        self.btn_laccept = QPushButton("Accept proposed")
        self.btn_lreject = QPushButton("Remove proposed")
        lb.addWidget(self.btn_ldel); lb.addWidget(self.btn_laccept); lb.addWidget(self.btn_lreject)
        ll_.addLayout(lb)
        tabs.addTab(lw, "Linear")

        # ---------------- Calming tab (humps, tables, bumps, bar markings, crossings)
        cw_ = QWidget(); cl_ = QVBoxLayout(cw_)
        cf = QFormLayout()
        from .rfd.features import KINDS
        self.cmb_fkind = QComboBox()
        for k, lab in KINDS.items():
            self.cmb_fkind.addItem(lab, k)
        self.spn_fspeed = QDoubleSpinBox(); self.spn_fspeed.setRange(20, 50); self.spn_fspeed.setSingleStep(5)
        self.spn_fspeed.setDecimals(0); self.spn_fspeed.setValue(30); self.spn_fspeed.setSuffix(" km/h")
        self.spn_fwidth = QDoubleSpinBox(); self.spn_fwidth.setRange(1, 6); self.spn_fwidth.setSingleStep(0.5)
        self.spn_fwidth.setValue(3.0); self.spn_fwidth.setSuffix(" m")
        self.chk_fbars = QCheckBox("Bar markings on the approaches (Table 2.3)"); self.chk_fbars.setChecked(True)
        self.chk_fsigns = QCheckBox("Warning signs on both approaches"); self.chk_fsigns.setChecked(True)
        self.cmb_fdir = QComboBox()
        for lab, v in (("Both directions", "both"), ("Forward traffic only", "forward"), ("Backward traffic only", "backward")):
            self.cmb_fdir.addItem(lab, v)
        self.spn_fsta = QDoubleSpinBox(); self.spn_fsta.setRange(-1e6, 1e6); self.spn_fsta.setDecimals(1)
        self.spn_fsta.setSuffix(" m")
        cf.addRow("Feature", self.cmb_fkind)
        cf.addRow("Hump crossing speed", self.spn_fspeed)
        cf.addRow("Crossing width", self.spn_fwidth)
        self.spn_frefuge = QDoubleSpinBox(); self.spn_frefuge.setRange(0, 30); self.spn_frefuge.setSingleStep(0.5)
        self.spn_frefuge.setSuffix(" m"); self.spn_frefuge.setSpecialValueText("None")
        self.spn_frefuge.setToolTip("Refuge island or median width. The crossing is split into two zebras with "
                                    "the refuge between them, on the centreline when the crossing spans it.")
        self.chk_fspan = QCheckBox("Crossing ends by two clicks")
        self.chk_fspan.setToolTip("Click one kerb, then the other: the crossing runs exactly between them "
                                  "(part of the road, a dual carriageway, a road without corridor edges)")
        cf.addRow("Refuge / median", self.spn_frefuge)
        cf.addRow("", self.chk_fspan)
        cf.addRow("Bar markings for", self.cmb_fdir)
        cf.addRow("", self.chk_fbars)
        cf.addRow("", self.chk_fsigns)
        cl_.addLayout(cf)
        fb = QHBoxLayout()
        self.btn_fplace = QPushButton("Place on map"); self.btn_fplace.setCheckable(True)
        self.btn_fadd = QPushButton("Add at chainage")
        fb.addWidget(self.btn_fplace); fb.addWidget(self.spn_fsta); fb.addWidget(self.btn_fadd)
        cl_.addLayout(fb)
        self.lbl_fhover = QLabel("Signs, hump markings and bar sets are added as proposals with the feature.")
        self.lbl_fhover.setWordWrap(True)
        cl_.addWidget(self.lbl_fhover)
        self.lst_features = QListWidget()
        cl_.addWidget(self.lst_features, 1)
        self.btn_fdel = QPushButton("Remove selected feature (with its signs and markings)")
        cl_.addWidget(self.btn_fdel)
        tabs.addTab(cw_, "Calming")

        # ---------------- Speed limits tab (RDM 6.2 3.5): zones chosen by the designer, signed by RFD
        zw = QWidget(); zl = QVBoxLayout(zw)
        zf = QFormLayout()
        self.cmb_zlimit = QComboBox()
        from .rfd.speedzones import LIMIT_SIGNS, LIMIT_TEXT
        for v, code in LIMIT_SIGNS.items():
            self.cmb_zlimit.addItem(f"{code}  {LIMIT_TEXT[v]}", v)
        self.spn_zfrom = QDoubleSpinBox(); self.spn_zto = QDoubleSpinBox()
        for sp in (self.spn_zfrom, self.spn_zto):
            sp.setRange(-1e6, 1e6); sp.setDecimals(1); sp.setSuffix(" m"); sp.setSingleStep(100)
        self.spn_zrep = QDoubleSpinBox(); self.spn_zrep.setRange(0, 5000); self.spn_zrep.setSingleStep(250)
        self.spn_zrep.setDecimals(0); self.spn_zrep.setSuffix(" m"); self.spn_zrep.setSpecialValueText("Middle only")
        zf.addRow("Limit", self.cmb_zlimit)
        zf.addRow("From chainage", self.spn_zfrom)
        zf.addRow("To chainage", self.spn_zto)
        zf.addRow("Repeaters every", self.spn_zrep)
        zl.addLayout(zf)
        zb = QHBoxLayout()
        self.btn_zadd = QPushButton("Add zone")
        self.btn_zsuggest = QPushButton("Propose from design speed")
        self.btn_zsuggest.setToolTip("50 km/h (built-up area) zones where the design speed is 50 km/h. The posted "
                                     "limit is your decision: check each before accepting the signs.")
        zb.addWidget(self.btn_zadd); zb.addWidget(self.btn_zsuggest)
        zl.addLayout(zb)
        self.lbl_zinfo = QLabel("Limit signs at both ends of the zone for each direction, repeaters at the middle "
                                "(RDM 6.2 3.5) and P9 where traffic leaves the zone. Signs are added as proposals.")
        self.lbl_zinfo.setWordWrap(True)
        zl.addWidget(self.lbl_zinfo)
        self.lst_zones = QListWidget()
        zl.addWidget(self.lst_zones, 1)
        self.btn_zdel = QPushButton("Remove selected zone (with its signs)")
        zl.addWidget(self.btn_zdel)
        tabs.addTab(zw, "Speed limits")

        # ---------------- Junctions tab: islands and markings from the standard drawings, placed by the user
        jw = QWidget(); jl = QVBoxLayout(jw)
        jf = QFormLayout()
        self.cmb_jtype = QComboBox()
        self.cmb_jpiece = QComboBox()
        self.spn_jscale = QDoubleSpinBox(); self.spn_jscale.setRange(0.5, 2.0); self.spn_jscale.setSingleStep(0.05)
        self.spn_jscale.setValue(1.0)
        self.chk_jguides = QCheckBox("Guide lines (edges, kerb returns, Rc arcs)"); self.chk_jguides.setChecked(True)
        self.cmb_jrole = QComboBox()
        self.cmb_jrole.addItem("Our road is the main road", "main")
        self.cmb_jrole.addItem("Our road joins another road", "minor")
        self.cmb_jmajor = QComboBox()
        jf.addRow("Junction", self.cmb_jrole)
        jf.addRow("Main road", self.cmb_jmajor)
        jf.addRow("Type", self.cmb_jtype)
        jf.addRow("Place", self.cmb_jpiece)
        jf.addRow("Scale", self.spn_jscale)
        jf.addRow("", self.chk_jguides)
        self.chk_jsplays = QCheckBox("Visibility splays (RDM 1.3 9.5.4)"); self.chk_jsplays.setChecked(True)
        self.chk_jsplays.setToolTip("Approach (give way, Figure 9.11) and stop (Figure 9.12) sight triangles on both "
                                    "sides, from Tables 9.7 and 9.8 at the main road's design speed")
        self.spn_jspeed = QDoubleSpinBox(); self.spn_jspeed.setRange(0, 140); self.spn_jspeed.setSingleStep(10)
        self.spn_jspeed.setDecimals(0); self.spn_jspeed.setSuffix(" km/h")
        self.spn_jspeed.setSpecialValueText("From the alignment")
        self.spn_jspeed.setToolTip("Design speed of the main road for the visibility splays. 'From the alignment' "
                                   "uses its speed stations; without them 80 km/h is assumed and flagged.")
        jf.addRow("", self.chk_jsplays)
        jf.addRow("Main road speed", self.spn_jspeed)
        self.spn_awidth = QDoubleSpinBox(); self.spn_awidth.setRange(2.0, 15.0); self.spn_awidth.setSingleStep(0.5)
        self.spn_awidth.setValue(3.0); self.spn_awidth.setSuffix(" m")
        self.spn_aradius = QDoubleSpinBox(); self.spn_aradius.setRange(3.0, 25.0); self.spn_aradius.setSingleStep(1.0)
        self.spn_aradius.setValue(6.0); self.spn_aradius.setSuffix(" m")
        self.spn_aradius.setToolTip("Entry and exit radius: 6 m or more, for the turning traffic (RDM 1.3 9.11.16)")
        self.spn_alength = QDoubleSpinBox(); self.spn_alength.setRange(3.0, 60.0); self.spn_alength.setSingleStep(1.0)
        self.spn_alength.setValue(10.0); self.spn_alength.setSuffix(" m")
        self.spn_alength.setToolTip("From the road edge to the fence or boundary line: at least 10 m (Figure 9.33)")
        self.spn_rbisland = QDoubleSpinBox(); self.spn_rbisland.setRange(1.0, 60.0); self.spn_rbisland.setSingleStep(2.0)
        self.spn_rbisland.setValue(10.0); self.spn_rbisland.setSuffix(" m")
        self.spn_rbisland.setToolTip("Central island diameter (RDM 1.3 Table 10.1: 4-18 m; at least 4 m kerbed)")
        self.spn_rbicd = QDoubleSpinBox(); self.spn_rbicd.setRange(0.0, 150.0); self.spn_rbicd.setSingleStep(2.0)
        self.spn_rbicd.setSuffix(" m"); self.spn_rbicd.setSpecialValueText("Table 10.1 minimum")
        self.spn_rbicd.setToolTip("Inscribed circle diameter; the Table 10.1 minimum for the island and the 15.5 m "
                                  "articulated vehicle by default; not over 100 m")
        self.spn_rbentry = QDoubleSpinBox(); self.spn_rbentry.setRange(5.0, 60.0); self.spn_rbentry.setValue(15.0)
        self.spn_rbentry.setSuffix(" m"); self.spn_rbentry.setToolTip("Entry kerb return radius")
        self.spn_rbexit = QDoubleSpinBox(); self.spn_rbexit.setRange(5.0, 80.0); self.spn_rbexit.setValue(20.0)
        self.spn_rbexit.setSuffix(" m"); self.spn_rbexit.setToolTip("Exit kerb return radius")
        self._rbt_rows = []
        for cap, spn in (("Central island", self.spn_rbisland), ("Inscribed circle", self.spn_rbicd),
                         ("Entry radius", self.spn_rbentry), ("Exit radius", self.spn_rbexit)):
            jf.addRow(cap, spn)
            self._rbt_rows.append((jf.labelForField(spn), spn))
        self._access_rows = []
        for cap, spn in (("Access width", self.spn_awidth), ("Return radius", self.spn_aradius),
                         ("To the boundary", self.spn_alength)):
            jf.addRow(cap, spn)
            self._access_rows.append((jf.labelForField(spn), spn))
        jl.addLayout(jf)
        self.btn_jplace = QPushButton("Place on map"); self.btn_jplace.setCheckable(True)
        jl.addWidget(self.btn_jplace)
        self.spn_jaadt = QDoubleSpinBox(); self.spn_jaadt.setRange(0, 200000); self.spn_jaadt.setDecimals(0)
        self.spn_jaadt.setSingleStep(500); self.spn_jaadt.setSpecialValueText("AADT not given")
        self.spn_jaadt.setSuffix(" pcu (year 10)")
        self.btn_jclimb = QPushButton("Propose climbing lanes from the profile")
        jl.addWidget(self.spn_jaadt); jl.addWidget(self.btn_jclimb)
        self.lbl_jhover = QLabel("Click the junction point on the main road, then a point up the minor road.")
        self.lbl_jhover.setWordWrap(True)
        jl.addWidget(self.lbl_jhover)
        self.lst_junctions = QListWidget()
        jl.addWidget(self.lst_junctions, 1)
        from qgis.gui import QgsCheckableComboBox
        self.cmb_jobst = QgsCheckableComboBox()
        self.cmb_jobst.setDefaultText("Obstruction layers")
        self.cmb_jobst.setToolTip("Layers with buildings, trees, fences, walls, kiosks ... to check against the splays")
        self.btn_jobst = QPushButton("Check splays")
        self.btn_jobst.setToolTip("Find features of the ticked layers inside the visibility splays; they are listed "
                                  "here and in the report's furniture checks")
        jo = QHBoxLayout(); jo.addWidget(self.cmb_jobst, 1); jo.addWidget(self.btn_jobst)
        jl.addLayout(jo)
        jb = QHBoxLayout()
        self.btn_jscale = QPushButton("Apply scale to selected")
        self.btn_jdel = QPushButton("Remove selected junction")
        jb.addWidget(self.btn_jscale); jb.addWidget(self.btn_jdel)
        jl.addLayout(jb)
        tabs.addTab(jw, "Junctions + bays")
        self.tabs = tabs
        self._scroll_tabs(tabs)
        lay.setContentsMargins(4, 4, 4, 4)
        self.setWidget(w)

        from .maptool import PlaceRunTool
        self.run_tool = PlaceRunTool(iface.mapCanvas(), lambda: self.store, self.run_settings)
        self.run_tool.hover.connect(self._run_hover)
        self.run_tool.placed.connect(self._run_placed)
        self.run_tool.failed.connect(lambda t: self.iface.messageBar().pushMessage("Road Furniture Designer", t, MSG_WARNING, 5))
        self.jn_tool = PlaceJunctionTool(iface.mapCanvas(), lambda: self.store, self.junction_settings)
        self.jn_tool.hover.connect(self.lbl_jhover.setText)
        self.jn_tool.placed.connect(lambda t: (self.lbl_jhover.setText(t), self.refresh()))
        iface.mapCanvas().mapToolSet.connect(
            lambda new, old: self.btn_jplace.setChecked(False) if old is self.jn_tool and new is not self.jn_tool else None)
        self.jn_tool.failed.connect(lambda t: self.iface.messageBar().pushMessage("Road Furniture Designer", t, MSG_WARNING, 5))
        self.run_tool.deactivated.connect(lambda: (self.btn_ldraw.setChecked(False), self.btn_fplace.setChecked(False)))
        self.tool = PlaceSignTool(iface.mapCanvas(), lambda: self.store, self.settings)
        self.tool.hover.connect(self.lbl_hover.setText)
        self.tool.placed.connect(lambda t: self.lbl_last.setText("Placed: " + t))
        self.tool.failed.connect(lambda t: self.iface.messageBar().pushMessage("Road Furniture Designer", t, MSG_WARNING, 4))
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
        self.btn_crit.clicked.connect(self.add_criteria_file)
        self.btn_report.clicked.connect(self.export_report)
        self.btn_accept.clicked.connect(lambda: self.store and self.store.accept_proposals())
        self.btn_reject.clicked.connect(lambda: self.store and self.store.remove_proposals())
        self.lst_findings.itemDoubleClicked.connect(self._zoom_finding)
        self.btn_legend.clicked.connect(self.edit_legend)
        self.cmb_cat.currentIndexChanged.connect(lambda _: self._filter(self.search.text()))
        self.tbl_signs.cellDoubleClicked.connect(self._zoom_to)
        self.tbl_lines.cellDoubleClicked.connect(self._zoom_line)
        self.btn_ladd.clicked.connect(self.add_line_run)
        self.btn_ldel.clicked.connect(self.delete_line_runs)
        self.btn_laccept.clicked.connect(lambda: self.store and self.store.lines.accept_proposals())
        self.cmb_lside.currentIndexChanged.connect(self._line_side_changed)
        self.btn_lreject.clicked.connect(lambda: self.store and self.store.lines.remove_proposals())
        self.btn_mprop.clicked.connect(self.propose_markings)
        self.btn_bprop.clicked.connect(self.propose_barriers)
        self.btn_ldraw.toggled.connect(lambda on: self._toggle_run_tool(on, "run"))
        self.btn_fplace.toggled.connect(lambda on: self._toggle_run_tool(on, "feature"))
        self.btn_fadd.clicked.connect(self.add_feature_at)
        self.btn_fdel.clicked.connect(self.remove_feature)
        self.lst_features.itemDoubleClicked.connect(self._zoom_feature)
        self.btn_jplace.toggled.connect(self._toggle_junction_tool)
        self.btn_jclimb.clicked.connect(self.propose_climbing_lanes)
        self.btn_jobst.clicked.connect(self.check_splays)
        self.tabs.currentChanged.connect(
            lambda i: self.tabs.tabText(i) == "Junctions + bays" and self._fill_obstruction_layers())
        self.cmb_jrole.currentIndexChanged.connect(self._junction_role_changed)
        self._junction_role_changed()
        self.cmb_jtype.currentIndexChanged.connect(self._fill_junction_pieces)
        self.btn_jdel.clicked.connect(self.remove_junction)
        self.btn_jscale.clicked.connect(self.rescale_junction)
        self.lst_junctions.itemDoubleClicked.connect(self._zoom_junction)
        self._fill_junction_types()
        self.btn_zadd.clicked.connect(self.add_speed_zone)
        self.btn_zsuggest.clicked.connect(self.suggest_speed_zones)
        self.btn_zdel.clicked.connect(self.remove_speed_zone)
        self.chk_lfix.toggled.connect(self.spn_loff.setEnabled)
        self.spn_loff.setEnabled(False)
        self._set_enabled(False)

    @staticmethod
    def _scroll_tabs(tabs):
        """Each tab scrolls inside the dock, so the dock never needs more height than the screen gives it.

        Without this the dock's minimum height is the tallest tab's (the Auto tab is over 900 px), the
        bottom buttons fall off a 1080p screen and Qt may squeeze the dock out when a neighbouring
        panel is resized."""
        for i in range(tabs.count()):
            page, label = tabs.widget(i), tabs.tabText(i)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            tabs.removeTab(i)
            sa.setWidget(page)
            tabs.insertTab(i, sa, label)
        for lw in tabs.findChildren(QListWidget) + tabs.findChildren(QTableWidget):
            lw.setMinimumHeight(90)             # lists keep a usable height when the tab scrolls
        RsdDock._narrow(tabs)
        tabs.setUsesScrollButtons(True)
        tabs.setCurrentIndex(0)

    # captions too long for a narrow dock: short text on the widget, the full one as its tooltip
    SHORT = {
        "Keep inside the corridor (RDM 0.6–3.0 m beyond the edge)": "Keep inside the corridor (RDM 2.4)",
        "Add to an existing post (click on it)": "Add to an existing post",
        "Curves: bend / sharp-turn warnings, series + distance plate, chevrons": "Curves: warnings, plates, chevrons",
        "Steep grades: W30 descent > 5 %, W31 ascent > 10 % (RDM 4.6.4)": "Steep grades: W30 / W31",
        "No overtaking where crest sight distance < passing sight distance": "No overtaking where sight < PSD",
        "Reduced PSD for no-overtaking (RDM 1.3 Table 3.20)": "Reduced PSD (RDM 1.3 Table 3.20)",
        "Combined line prohibits traffic against chainage": "CLS: against chainage",
        "Also where the warrant leaves it to judgement": "Also where left to judgement",
        "No-overtaking section (closer stud interval)": "Closer studs (no overtaking)",
        "Fixed offset (else taken from the click)": "Fixed offset",
        "Bar markings on the approaches (Table 2.3)": "Bar markings on the approaches",
        "Guide lines (edges, kerb returns, Rc arcs)": "Guide lines",
        "Road furniture report (PDF + PNG sheets + Excel)…": "Road furniture report…",
        "Export to Civil 3D (package + DXF)…": "Export to Civil 3D…",
        "Remove selected feature (with its signs and markings)": "Remove selected feature",
        "Remove selected zone (with its signs)": "Remove selected zone",
        "Draw on map (start, end; one click for crossings and humps)": "Draw on map",
        "Propose markings and studs (RDM 6.1)": "Propose markings (RDM 6.1)",
        "Propose barriers (RDM 1.3 Fig 12.4)": "Propose barriers (RDM 1.3)",
    }

    @staticmethod
    def _narrow(root):
        """Let every tab shrink to about 360 px wide: combos, captions, form rows and labels."""
        from qgis.PyQt.QtWidgets import QAbstractButton

        for cb in root.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)
            cb.setMinimumWidth(120)             # Qt keeps the old minimum size hint after a policy change
            cb.currentTextChanged.connect(cb.setToolTip)
            cb.setToolTip(cb.currentText())
        for b in root.findChildren(QAbstractButton):
            full = b.text()
            if full in RsdDock.SHORT:
                b.setText(RsdDock.SHORT[full])
                b.setToolTip(full + (("\n" + b.toolTip()) if b.toolTip() else ""))
        for gb in root.findChildren(QGroupBox):    # a group box is never narrower than its title
            full = gb.title()
            if full in RsdDock.SHORT:
                gb.setTitle(RsdDock.SHORT[full])
                gb.setToolTip(full)
        for lab in root.findChildren(QLabel):
            lab.setWordWrap(True)               # hover read-outs and results arrive later, often long
        for fl in root.findChildren(QFormLayout):
            fl.setRowWrapPolicy(QFormLayout.WrapLongRows)
        from qgis.PyQt.QtWidgets import QBoxLayout, QLayout

        def refresh():                          # drop minimum sizes cached before the changes
            for lay in root.findChildren(QLayout):
                lay.invalidate()
            for w in root.findChildren(QWidget):
                w.updateGeometry()
        refresh()
        for row in root.findChildren(QHBoxLayout):
            if row.minimumSize().width() > RsdDock.ROW_MAX:
                row.setDirection(QBoxLayout.TopToBottom)    # side-by-side buttons stack when too wide
        refresh()

    ROW_MAX = 340

    def page(self, label):
        """The content widget of a tab (inside its scroll area)."""
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == label:
                return self.tabs.widget(i).widget()
        return None

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
        self._fill_linear_controls()
        self._fill_ground_choices()
        self._fill_junction_majors()
        self._fill_obstruction_layers()
        crit = store.meta.get("criteria")
        if crit:
            i = self.cmb_crit.findData(crit)
            if i >= 0:
                self.cmb_crit.setCurrentIndex(i)
            else:
                self.iface.messageBar().pushMessage(
                    "Road Furniture Designer", f"This project uses criteria '{crit}', which is not available here; "
                    f"add its file on the Auto tab.", MSG_WARNING, 8)
        store.message.connect(lambda t, l: self.iface.messageBar().pushMessage("Road Furniture Designer", t,
                                                                            MSG_LEVELS.get(l, MSG_INFO), 5))
        al = store.al
        sp = ", ".join(f"{v:.0f} km/h from {format_station(al.display_station(s), 0)}" for s, v in al.speeds) \
            or "<span style='color:#c0392b'>none in LandXML (80 km/h assumed; check the Civil 3D design criteria)</span>"
        self.lbl_project.setText(
            f"<b>{os.path.basename(store.gpkg)}</b><br>Alignment {al.name}: "
            f"{al.sta_start:.0f}–{al.sta_end:.0f} m<br>Design speed: {sp}"
            + (f"<br>Road edges: {', '.join(al.edges.codes())}" if al.edges
               else "<br>Road edges: <span style='color:#c0392b'>none in LandXML (offsets from the centreline)</span>")
            + (f"<br>Vertical profile: {len(al.profile.curves)} curves" if al.profile
               else "<br>Vertical profile: <span style='color:#c0392b'>none in LandXML (no grade or sight checks)</span>")
            + (f"<br>Superelevation: {len(al.superelevation)} curves" if getattr(al, "superelevation", None)
               else "<br>Superelevation: <span style='color:#c0392b'>none in LandXML (4 % assumed)</span>")
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
        QgsProject.instance().writeEntry("RoadFurnitureDesigner", "gpkg", store.gpkg)
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
        self._refresh_lines()
        self._refresh_features()
        self._refresh_zones()
        self._refresh_junctions()
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

    # ------------------------------------------------------------------ linear furniture
    def _fill_linear_controls(self):
        lc = self.store.lines.cat
        self.cmb_litem.clear()
        for c in lc.categories():
            for it in lc.by_category(c):
                self.cmb_litem.addItem(f"{it.code}  {it.name}", it.code)
        self.cmb_lref.clear()
        self.cmb_lref.addItem("Centreline", None)
        for code in (self.store.al.edges.codes() if self.store.al.edges else []):
            self.cmb_lref.addItem(code, code)
        al = self.store.al
        for sp in (self.spn_lfrom, self.spn_lto, self.spn_fsta, self.spn_zfrom, self.spn_zto):
            sp.setRange(al.sta_start, al.sta_end)
        self.spn_zfrom.setValue(al.sta_start); self.spn_zto.setValue(al.sta_end)
        self.spn_lfrom.setValue(al.sta_start); self.spn_lto.setValue(al.sta_end)
        self._line_side_changed()

    def _line_side_changed(self, *_):
        centre = self.cmb_lside.currentData() == "C"
        self.cmb_lref.setEnabled(not centre)
        if centre:
            self.cmb_lref.setCurrentIndex(0)

    def add_line_run(self):
        from .rfd.linear import Run
        if self.store is None:
            return
        side = self.cmb_lside.currentData()
        if side == "click":
            self.iface.messageBar().pushMessage("Road Furniture Designer",
                                                "Choose Centre, Left or Right to add a run by chainage", MSG_WARNING, 5)
            return
        try:
            self.store.lines.add_run(Run(self.cmb_litem.currentData(), self.spn_lfrom.value(), self.spn_lto.value(),
                                         side=side, offset=self.spn_loff.value(),
                                         edge_ref=self.cmb_lref.currentData() if side != "C" else None,
                                         no_overtaking=self.chk_lnoot.isChecked(), flip=self.chk_lflip.isChecked()))
        except ValueError as e:
            self.iface.messageBar().pushMessage("Road Furniture Designer", str(e), MSG_WARNING, 6)
        self.store.lines.layer.triggerRepaint()

    def marking_config(self):
        """Markings take their no-overtaking zones from the Auto tab settings, so they match the signs."""
        from .rfd.markings import MarkingConfig
        return MarkingConfig.from_auto(self.auto_config(), road_class=self.cmb_mclass.currentData(),
                                       studs=self.cmb_mstuds.currentData(),
                                       carriageway=self.spn_mwidth.value() or None)

    def _fill_ground_choices(self):
        from .rfd import terrain as T
        self.cmb_bground.clear()
        self.cmb_bground.addItem("Automatic (by name: OGL, EG, existing...)", None)
        names = list(self.store.al.sections.surface_names()) if getattr(self.store.al, "sections", None) else []
        try:
            names += [n for n in T.surface_names(self.store.landxml_path) if n not in names]
        except OSError:
            pass
        for n in names:
            self.cmb_bground.addItem(n, n)

    def barrier_config(self):
        from .rfd.barriers import BarrierConfig
        a = self.auto_config()
        return BarrierConfig(criteria=a.criteria, include_judgement=self.chk_bjudge.isChecked(),
                             aadt=self.spn_baadt.value() or None, ground_surface=self.cmb_bground.currentData(),
                             landxml=self.store.landxml_path, start=a.start, end=a.end)

    def propose_barriers(self):
        if self.store is None:
            return
        with _busy():
            n, findings, skipped = self.store.lines.auto_propose_barriers(self.barrier_config())
        bars = [f for f in findings if f.kind == "barrier"]
        jud = [f for f in findings if f.kind == "barrier_judgement"]
        notes = [f.text for f in findings if f.kind == "barrier_note"] + skipped
        msg = (f"{len(bars)} barrier runs proposed, {sum(f.end - f.start for f in bars):.0f} m"
               + (f"; {len(jud)} fill sections left to judgement" if jud else "") + ".")
        if notes:
            msg += " " + "; ".join(notes)
        self.iface.messageBar().pushMessage("Road Furniture Designer", msg, MSG_INFO, 12)

    def propose_markings(self):
        if self.store is None:
            return
        with _busy():
            n, findings, skipped = self.store.lines.auto_propose_markings(self.marking_config())
            self.store.trim_for_roundabouts()
        cls = [f for f in findings if f.kind == "marking_cls"]
        notes = [f.text for f in findings if f.kind == "marking_note"] + skipped
        msg = (f"{n} marking and stud runs proposed; continuous centre line over "
               f"{sum(f.end - f.start for f in cls):.0f} m in {len(cls)} sections.")
        if notes:
            msg += " Note: " + "; ".join(notes)
        self.iface.messageBar().pushMessage("Road Furniture Designer", msg, MSG_WARNING if notes else MSG_INFO, 10)

    # ------------------------------------------------------------------ map tool for runs and features
    def run_settings(self):
        mode = getattr(self, "_run_mode", "run")
        return {"mode": mode, "code": self.cmb_litem.currentData(), "side": self.cmb_lside.currentData(),
                "edge_ref": self.cmb_lref.currentData(),
                "lock_offset": self.spn_loff.value() if self.chk_lfix.isChecked() else None,
                "no_overtaking": self.chk_lnoot.isChecked(), "flip": self.chk_lflip.isChecked(),
                "kind": self.cmb_fkind.currentData(), "feature_cfg": self.feature_config(),
                "span": self.chk_fspan.isChecked() and self.cmb_fkind.currentData() == "crossing",
                "auto_cfg": self.auto_config()}

    def feature_config(self):
        from .rfd.features import FeatureConfig
        return FeatureConfig(criteria=self.cmb_crit.currentData(), desired_speed=self.spn_fspeed.value(),
                             crossing_width=self.spn_fwidth.value(), bar_markings=self.chk_fbars.isChecked(),
                             signs=self.chk_fsigns.isChecked(), road_class=self.cmb_mclass.currentData(),
                             carriageway=self.spn_mwidth.value() or None, directions=self.cmb_fdir.currentData(),
                             refuge=self.spn_frefuge.value())

    def _toggle_run_tool(self, on, mode):
        canvas = self.iface.mapCanvas()
        if on:
            if self.store is None:
                (self.btn_ldraw if mode == "run" else self.btn_fplace).setChecked(False)
                return
            other = self.btn_fplace if mode == "run" else self.btn_ldraw
            other.blockSignals(True); other.setChecked(False); other.blockSignals(False)
            self.btn_place.setChecked(False)
            self._run_mode = mode
            self.run_tool.cancel()
            canvas.setMapTool(self.run_tool)
        elif canvas.mapTool() is self.run_tool and getattr(self, "_run_mode", None) == mode:
            canvas.unsetMapTool(self.run_tool)

    def _run_hover(self, text):
        (self.lbl_lhover if getattr(self, "_run_mode", "run") == "run" else self.lbl_fhover).setText(text)

    def _run_placed(self, text):
        self._run_hover(text)
        self.refresh()

    def add_feature_at(self):
        if self.store is None:
            return
        try:
            d = self.store.add_feature(self.cmb_fkind.currentData(), self.spn_fsta.value(), self.feature_config(),
                                       self.auto_config())
        except ValueError as e:
            self.iface.messageBar().pushMessage("Road Furniture Designer", str(e), MSG_WARNING, 6)
            return
        notes = [f.text for f in d.findings]
        self.lbl_fhover.setText((d.summary or "") + (" - " + "; ".join(notes) if notes else ""))
        self.refresh()

    def _refresh_features(self):
        from .rfd.alignment import format_station
        self.lst_features.clear()
        feats = sorted(self.store.features().items(), key=lambda kv: kv[1]["station"] or 0)
        for gid, g in feats:
            main = next((c for c in g["codes"] if c not in ("BAR-SET", "BM04")), (g["codes"] or ["signs"])[0])
            it = QListWidgetItem(f"{format_station(self.store.al.display_station(g['station'] or 0), 0)}  {main}  "
                                 f"({g['runs']} items, {g['signs']} signs)")
            it.setData(Qt.UserRole, gid)
            self.lst_features.addItem(it)

    # ------------------------------------------------------------------ junction templates
    def _fill_junction_types(self):
        from .rfd.junctions import load_templates
        self._jt = load_templates()
        self.cmb_jtype.clear()
        for k, t in self._jt["types"].items():
            self.cmb_jtype.addItem(f"{k}  {t['name']}", k)
        self._fill_junction_pieces()

    def _fill_junction_pieces(self, *_):
        k = self.cmb_jtype.currentData()
        self.cmb_jpiece.clear()
        if not k:
            return
        bus = k in ("BUS", "TRUCK", "CLIMB")
        acc = k == "ACCESS"
        rbt = k == "RBT"
        for lab, w in self._rbt_rows:
            lab.setVisible(rbt); w.setVisible(rbt)
        for w in (self.cmb_jrole, self.chk_jguides, self.spn_jscale, self.chk_jsplays, self.spn_jspeed):
            w.setEnabled(not bus)
        for w in (self.cmb_jrole, self.cmb_jmajor, self.chk_jguides, self.spn_jscale):
            w.setEnabled(w.isEnabled() and not acc and not rbt)
        for w in (self.chk_jsplays, self.spn_jspeed):
            w.setEnabled(w.isEnabled() and not rbt)
        if rbt:
            self.cmb_jpiece.addItem("Roundabout with its islands, markings and signs", "")
            self.lbl_jhover.setText("Click the centre on our road: its arms and those of other alignments crossing the "
                                    "circle are found. Click any other arm's direction, then right-click or press "
                                    "Enter to place (RDM 1.3 Chapter 10).")
            return
        for lab, w in self._access_rows:
            lab.setVisible(acc); w.setVisible(acc)
        if acc:
            self.cmb_jpiece.addItem("Private access with its stop splays", "")
            self.lbl_jhover.setText("Click the access point on our road, then a point up the access. Figure 9.33: "
                                    "returns from the shoulder edge, paved to the boundary with a 3 m taper, a pipe "
                                    "across the mouth; stop splays (RDM 1.3 9.11.16).")
            return
        self.cmb_jmajor.setEnabled(not bus and self.cmb_jrole.currentData() == "minor")
        self.btn_jclimb.setVisible(k == "CLIMB"); self.spn_jaadt.setVisible(k == "CLIMB")
        if k == "CLIMB":
            self.cmb_jpiece.addItem("Climbing lane with its tapers, lines and signs", "")
            self.lbl_jhover.setText("Propose from the profile (RDM 1.3 Table 6.6), or click where the full-width "
                                    "lane starts on the uphill traffic's side, then where it ends. 100 m tapers are "
                                    "added; WSCM-I1 / I2 signs are proposed.")
            return
        if k == "TRUCK":
            self.cmb_jpiece.addItem("Truck parking bay with its tapers, line and signs", "")
            self.lbl_jhover.setText("Click where the bay (full width) starts on the side of the road it serves, then "
                                    "where it ends (70 m takes four to five trucks). The 15 m and 10 m tapers "
                                    "(RDM/1/3/3/03) are added in the direction of travel; I15 and I14 are proposed.")
            return
        if bus:
            self.cmb_jpiece.addItem("Bus bay with its tapers, platform and sign", "")
            self.lbl_jhover.setText("Click where the bay starts on the side of the road it serves, then where it "
                                    "ends. Tapers (RDM/1/3/3/01) are added before and after it in the direction "
                                    "of travel; the Bus Stop sign is proposed.")
            return
        self._junction_role_changed()
        self.cmb_jpiece.addItem(f"Whole type {k} kit", "")
        for pid in [it["piece"] for it in self._jt["kits"][k]]:
            if self.cmb_jpiece.findData(pid) < 0:
                self.cmb_jpiece.addItem(self._jt["pieces"][pid]["name"], pid)
        rem = self._jt["types"][k].get("remark")
        self.cmb_jtype.setToolTip(rem or self._jt["types"][k]["drawing"])

    def junction_settings(self):
        return {"kit": self.cmb_jtype.currentData(), "piece": self.cmb_jpiece.currentData() or "",
                "scale": self.spn_jscale.value(), "guides": self.chk_jguides.isChecked(),
                "role": self.cmb_jrole.currentData() or "main", "major": self.cmb_jmajor.currentData() or "",
                "splays": self.chk_jsplays.isChecked(),
                "rbt": {"island": self.spn_rbisland.value(), "icd": self.spn_rbicd.value() or None,
                        "entry_r": self.spn_rbentry.value(), "exit_r": self.spn_rbexit.value(),
                        "criteria": self.cmb_crit.currentData()},
                "access": {"width": self.spn_awidth.value(), "radius": self.spn_aradius.value(),
                           "length": self.spn_alength.value(), "road_class": self.cmb_mclass.currentData() or None},
                "splay": {"speed": self.spn_jspeed.value() or None, "criteria": self.cmb_crit.currentData()}}

    def _fill_junction_majors(self):
        self.cmb_jmajor.clear()
        self.cmb_jmajor.addItem("Click its direction", "")
        for a in (self.store.junctions.others() if self.store else []):
            self.cmb_jmajor.addItem(f"Alignment {a.name}", a.name)
        self._junction_role_changed()

    def _junction_role_changed(self, *_):
        minor = self.cmb_jrole.currentData() == "minor"
        self.cmb_jmajor.setEnabled(minor)
        self.lbl_jhover.setText(
            "Click our road where it meets the main road, then a point along the main road (or click again "
            "when the main road is an alignment). Give Way markings and an R2 sign go on our approach."
            if minor else "Click the junction point on the main road, then a point up the minor road.")

    def _toggle_junction_tool(self, on):
        canvas = self.iface.mapCanvas()
        if on:
            if self.store is None:
                self.btn_jplace.setChecked(False)
                return
            self.btn_place.setChecked(False)
            self.btn_ldraw.setChecked(False); self.btn_fplace.setChecked(False)
            self.jn_tool.cancel()
            canvas.setMapTool(self.jn_tool)
        elif canvas.mapTool() is self.jn_tool:
            canvas.unsetMapTool(self.jn_tool)

    def _refresh_junctions(self):
        cur = self.lst_junctions.currentItem()
        keep = cur.data(Qt.UserRole) if cur else None
        self.lst_junctions.clear()
        for j in self.store.junctions.junctions():
            paint = sum(v[1] for v in j["paint"].values())
            where = ("joins " + (j["main_ref"][4:] if j["main_ref"].startswith("alg:") else "main road")
                     if j.get("role") == "minor" else ("left" if j["side"] == "L" else "right"))
            if j.get("rbt"):
                r = j["rbt"]
                it = QListWidgetItem(f"{j['ch']}  roundabout ICD {r['quantities']['icd']:g} m, island {r['island']:g} m, "
                                     f"{r['n_arms']} arms  (kerb {j['kerb_m']:.0f} m)")
                it.setData(Qt.UserRole, j["id"]); it.setData(Qt.UserRole + 1, j["sta"])
                self.lst_junctions.addItem(it)
                if j["id"] == keep:
                    self.lst_junctions.setCurrentItem(it)
                continue
            if j.get("access"):
                a = j["access"]
                it = QListWidgetItem(f"{j['ch']}  access {a['width']:g} m  {'left' if j['side'] == 'L' else 'right'}  "
                                     f"{j['crossing_deg']:.0f} deg  (area {a['quantities'].get('area_m2', 0):.0f} m2)"
                                     + (f"  - {len(j['sight']['obstructions'])} obstruction(s) in the splays"
                                        if j.get("sight") and j["sight"].get("obstructions") else ""))
                it.setData(Qt.UserRole, j["id"]); it.setData(Qt.UserRole + 1, j["sta"])
                self.lst_junctions.addItem(it)
                if j["id"] == keep:
                    self.lst_junctions.setCurrentItem(it)
                continue
            if j.get("bay"):
                b = j["bay"]
                kerb = f", kerb {j['kerb_m']:.0f} m" if j["kerb_m"] else ""
                it = QListWidgetItem(f"{j['ch']}  {b.get('kind', 'bus bay')} {abs(b['stations'][2] - b['stations'][1]):.0f} m  {where}  "
                                     f"(widening {j['widen_m2']:.0f} m2{kerb})")
                it.setData(Qt.UserRole, j["id"]); it.setData(Qt.UserRole + 1, j["sta"])
                self.lst_junctions.addItem(it)
                if j["id"] == keep:
                    self.lst_junctions.setCurrentItem(it)
                continue
            obst = len((j.get("sight") or {}).get("obstructions") or [])
            it = QListWidgetItem(f"{j['ch']}  type {j['kit']}  {where}  "
                                 f"{j['crossing_deg']:.0f} deg  x{j['scale']:g}  "
                                 f"(kerb {j['kerb_m']:.0f} m, islands {j['island_m2']:.0f} m2, paint {paint:.1f} m2)"
                                 + (f"  - {obst} obstruction(s) in the splays" if obst else ""))
            it.setData(Qt.UserRole, j["id"])
            it.setData(Qt.UserRole + 1, j["sta"])
            self.lst_junctions.addItem(it)
            if j["id"] == keep:
                self.lst_junctions.setCurrentItem(it)

    def _fill_obstruction_layers(self):
        """Vector layers of the project, other than RFD's own, as obstruction candidates; ticks are kept."""
        from qgis.core import QgsVectorLayer
        keep = set(self.cmb_jobst.checkedItemsData())
        saved = set(((self.store.meta.get("sight_layers") if self.store else "") or "").split(","))
        self.cmb_jobst.clear()
        gpkg = os.path.normcase(os.path.abspath(self.store.gpkg)) if self.store else None
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue
            src = os.path.normcase(os.path.abspath(lyr.source().split("|")[0])) if lyr.source() else ""
            if gpkg and src == gpkg:
                continue                                   # RFD's own layers
            self.cmb_jobst.addItemWithCheckState(lyr.name(), Qt.Checked if lyr.id() in (keep | saved) else Qt.Unchecked,
                                                 lyr.id())

    def check_splays(self):
        if self.store is None:
            return
        ids = [i for i in self.cmb_jobst.checkedItemsData() if i]
        n, total = self.store.check_sight(ids)
        if not ids:
            self.lbl_jhover.setText("Tick one or more obstruction layers (buildings, trees, fences ...) first.")
        else:
            self.lbl_jhover.setText(f"{total} obstruction(s) inside the visibility splays of {n} junction(s)"
                                    if total else "No obstructions inside the visibility splays.")
        self.refresh()

    def propose_climbing_lanes(self):
        if self.store is None:
            return
        n, notes = self.store.propose_climbing_lanes(self.spn_jaadt.value() or None)
        self.lbl_jhover.setText(f"{n} climbing lane(s) proposed" + (": " + "; ".join(notes) if notes else
                                " - no up-grade is longer than its RDM 1.3 Table 6.6 limit (or no profile)"))
        self.refresh()

    def remove_junction(self):
        it = self.lst_junctions.currentItem()
        if self.store and it:
            self.store.remove_junction(it.data(Qt.UserRole))
            self.refresh()

    def rescale_junction(self):
        it = self.lst_junctions.currentItem()
        if self.store and it:
            self.store.junctions.set_scale(it.data(Qt.UserRole), self.spn_jscale.value())
            self.refresh()

    def _zoom_junction(self, item):
        from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsRectangle
        x, y, _ = self.store.al.point_at(item.data(Qt.UserRole + 1))
        canvas = self.iface.mapCanvas()
        xf = QgsCoordinateTransform(self.store.signs.crs(), canvas.mapSettings().destinationCrs(), QgsProject.instance())
        p = xf.transform(QgsPointXY(x, y))
        canvas.setExtent(QgsRectangle(p.x() - 60, p.y() - 60, p.x() + 60, p.y() + 60))
        canvas.refresh()

    # ------------------------------------------------------------------ speed limit zones
    def add_speed_zone(self):
        if self.store is None:
            return
        try:
            d = self.store.add_speed_zone(self.cmb_zlimit.currentData(), self.spn_zfrom.value(), self.spn_zto.value(),
                                          self.auto_config(), repeat=self.spn_zrep.value() or None)
        except ValueError as e:
            self.iface.messageBar().pushMessage("Road Furniture Designer", str(e), MSG_WARNING, 6)
            return
        notes = [f.text for f in d.findings]
        self.lbl_zinfo.setText(d.summary + (" - " + "; ".join(notes) if notes else ""))
        self.refresh()

    def suggest_speed_zones(self):
        if self.store is None:
            return
        from .rfd.speedzones import zones_from_design_speed
        zones = zones_from_design_speed(self.store.al)
        if not zones:
            self.lbl_zinfo.setText("No 50 km/h design speed sections in the LandXML.")
            return
        notes = []
        with _busy():
            for z in zones:
                d = self.store.add_speed_zone(z.limit, z.start, z.end, self.auto_config(),
                                              repeat=self.spn_zrep.value() or None)
                notes += [f.text for f in d.findings]
        self.lbl_zinfo.setText(f"{len(zones)} zone(s) proposed from the design speed. The posted limit is the "
                               f"designer's decision: review before accepting." + (" " + "; ".join(notes) if notes else ""))
        self.refresh()

    def _refresh_zones(self):
        from .rfd.alignment import format_station
        self.lst_zones.clear()
        for z in self.store.speed_zones():
            ch = lambda s: format_station(self.store.al.display_station(s), 0)
            it = QListWidgetItem(f"{ch(z['start'])} – {ch(z['end'])}  {z['limit'] or '?'} km/h  "
                                 f"({len(z['signs'])} signs, {z['status']})")
            it.setData(Qt.UserRole, z["id"])
            self.lst_zones.addItem(it)

    def remove_speed_zone(self):
        it = self.lst_zones.currentItem()
        if it is not None and self.store is not None:
            self.store.remove_speed_zone(it.data(Qt.UserRole))
            self.refresh()

    def remove_feature(self):
        it = self.lst_features.currentItem()
        if it is not None:
            self.store.remove_feature(it.data(Qt.UserRole))
            self.store.lines.layer.triggerRepaint(); self.store.signs.triggerRepaint()

    def _zoom_feature(self, item):
        gid = item.data(Qt.UserRole)
        ids = [f.id() for f in self.store.lines.layer.getFeatures() if f["rule"] == f"feature:{gid}"]
        if ids:
            from qgis.core import QgsCoordinateTransform
            lyr = self.store.lines.layer
            bb = None
            for f in lyr.getFeatures(ids):
                b = f.geometry().boundingBox()
                bb = b if bb is None else (bb.combineExtentWith(b) or bb)
            xf = QgsCoordinateTransform(lyr.crs(), self.iface.mapCanvas().mapSettings().destinationCrs(),
                                        QgsProject.instance())
            bb = xf.transformBoundingBox(bb); bb.grow(30)
            self.iface.mapCanvas().setExtent(bb); self.iface.mapCanvas().refresh()

    def delete_line_runs(self):
        rows = sorted({i.row() for i in self.tbl_lines.selectedIndexes()})
        ids = [self.tbl_lines.item(r, 0).data(Qt.UserRole) for r in rows]
        if ids:
            self.store.lines._set_status_or_delete(ids)

    def _refresh_lines(self):
        feats = sorted(self.store.lines.layer.getFeatures(), key=lambda f: (f["item_code"] or "", f["sta_from"] or 0))
        self.tbl_lines.setRowCount(len(feats))
        for r, f in enumerate(feats):
            q = f["quantity"]
            for c, v in enumerate([f"{f['item_code']} {f['description'] or ''}", f["ch_from"], f["ch_to"],
                                   (f["side"] or "") + (f" {f['edge_ref']}" if f["edge_ref"] else ""),
                                   f"{q:g} {f['unit'] or ''}" if isinstance(q, (int, float)) else "",
                                   f["status"]]):
                cell = QTableWidgetItem("" if v is None else str(v))
                cell.setData(Qt.UserRole, f.id())
                self.tbl_lines.setItem(r, c, cell)

    def _zoom_line(self, row, _col):
        fid = self.tbl_lines.item(row, 0).data(Qt.UserRole)
        lyr = self.store.lines.layer
        f = lyr.getFeature(fid)
        if not f.isValid() or f.geometry().isEmpty():
            return
        from qgis.core import QgsCoordinateTransform
        xf = QgsCoordinateTransform(lyr.crs(), self.iface.mapCanvas().mapSettings().destinationCrs(),
                                    QgsProject.instance())
        bb = xf.transformBoundingBox(f.geometry().boundingBox())
        bb.grow(20)
        self.iface.mapCanvas().setExtent(bb)
        lyr.selectByIds([fid])
        self.iface.mapCanvas().refresh()

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
            QMessageBox.information(self, "Road Furniture Designer", "Select a sign in the list first.")
            return
        fid = self.tbl_signs.item(rows[0].row(), 0).data(Qt.UserRole)
        f = self.store.signs.getFeature(fid)
        text, ok = QInputDialog.getMultiLineText(
            self, f"Legend: {f['post_ref']} {f['sign_code']}",
            "One line per destination (< left, ^ ahead, > right; route and km optional):", f["legend"] or "")
        if ok:
            self.store.set_fields(fid, {"legend": text.strip() or None})

    CRIT_DIRS_KEY = "RoadFurnitureDesigner/criteria_dirs"

    def _load_criteria_list(self, select=None):
        from qgis.core import QgsSettings
        from .rfd import criteria as C
        dirs = QgsSettings().value(self.CRIT_DIRS_KEY, []) or []
        if isinstance(dirs, str):
            dirs = [dirs]
        for d in dirs:
            C.add_search_dir(d)
        cur = select or self.cmb_crit.currentData()
        self.cmb_crit.clear()
        for cid, cname in C.list_criteria():
            self.cmb_crit.addItem(cname, cid)
        i = self.cmb_crit.findData(cur) if cur else -1
        if i >= 0:
            self.cmb_crit.setCurrentIndex(i)

    def add_criteria_file(self):
        import json
        from qgis.core import QgsSettings
        from .rfd import criteria as C
        p, _ = QFileDialog.getOpenFileName(self, "Add design criteria file", "", "Criteria (*.json)")
        if not p:
            return
        try:
            c = C.Criteria.load(p)
        except (ValueError, OSError, json.JSONDecodeError) as e:
            self.iface.messageBar().pushMessage("Road Furniture Designer", f"Not a valid criteria file: {e}",
                                                MSG_WARNING, 8)
            return
        d = os.path.dirname(os.path.abspath(p))
        s = QgsSettings()
        dirs = s.value(self.CRIT_DIRS_KEY, []) or []
        if isinstance(dirs, str):
            dirs = [dirs]
        if d not in dirs:
            s.setValue(self.CRIT_DIRS_KEY, dirs + [d])
        self._load_criteria_list(select=c.id)
        self.iface.messageBar().pushMessage("Road Furniture Designer",
                                            f"Criteria '{c.name}' added (folder {d} is now searched).", MSG_INFO, 5)

    def auto_config(self):
        from .rfd.autoplace import AutoConfig
        return AutoConfig(curves=self.chk_r_curves.isChecked(), grades=self.chk_r_grades.isChecked(),
                          no_overtaking=self.chk_r_overtake.isChecked(), warn_margin=self.spn_warn.value(),
                          chevron_margin=self.spn_chev.value(), sharp_margin=self.spn_sharp.value(),
                          default_e=self.spn_e.value(), clearance=self.spn_clear.value(),
                          edge_ref=self.cmb_ref.currentData(),
                          criteria=self.cmb_crit.currentData(), psd_reduced=self.chk_psd_red.isChecked(),
                          sight_offset=self.spn_msight.value(),
                          start=self.spn_from.value(), end=self.spn_to.value())

    def run_auto(self):
        if self.store.meta.get("criteria") != self.cmb_crit.currentData():
            self.store.set_meta(criteria=self.cmb_crit.currentData())
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
        self.iface.messageBar().pushMessage("Road Furniture Designer", f"{n} posts renumbered by chainage", MSG_INFO, 4)

    # ------------------------------------------------------------------ project actions
    def new_project(self):
        lx, _ = QFileDialog.getOpenFileName(self, "Road alignment (LandXML)", "", "LandXML (*.xml *.landxml)")
        if not lx:
            return
        try:
            names = list(dict.fromkeys(alignment_names(lx)))     # byte scan of start tags: instant
        except Exception as ex:
            QMessageBox.critical(self, "Road Furniture Designer", f"Could not read LandXML:\n{ex}")
            return
        if not names:
            QMessageBox.warning(self, "Road Furniture Designer", "No horizontal alignments in that file.")
            return
        name = names[0]
        if len(names) > 1:
            name, ok = QInputDialog.getItem(self, "Alignment", "Sign this alignment:", names, 0, False)
            if not ok:
                return
        from .rfd.alignment import landxml_crs
        lxc = landxml_crs(lx)
        crs = QgsCoordinateReferenceSystem(f"EPSG:{lxc['epsg']}") if lxc.get("epsg") else QgsProject.instance().crs()
        if lxc.get("epsg") and crs.isValid():
            pc = QgsProject.instance().crs()
            if pc.isValid() and pc.authid() != crs.authid():
                self.iface.messageBar().pushMessage(
                    "Road Furniture Designer", f"Sign layer uses the LandXML's CRS {crs.authid()} ({lxc.get('name', '')}); "
                    f"the QGIS project is {pc.authid()} and will reproject on the fly.", MSG_INFO, 8)
        if not crs.isValid() or crs.isGeographic():
            from qgis.gui import QgsProjectionSelectionDialog
            dlg = QgsProjectionSelectionDialog(self)
            dlg.setWindowTitle("CRS of the LandXML coordinates (projected, metres)")
            if not dlg.exec_():
                return
            crs = dlg.crs()
        gp, _ = QFileDialog.getSaveFileName(self, "Save Road Furniture Designer project", os.path.splitext(lx)[0] + "_signs.gpkg",
                                            "GeoPackage (*.gpkg)")
        if not gp:
            return
        try:
            with _busy():
                st = SignStore.create(gp, lx, name, crs, QgsProject.instance().title())
        except Exception as ex:
            QMessageBox.critical(self, "Road Furniture Designer", str(ex))
            return
        self.set_store(st)
        self.iface.mapCanvas().setExtent(st.alignment_layer.extent().buffered(50))
        self.iface.mapCanvas().refresh()

    def open_project(self):
        gp, _ = QFileDialog.getOpenFileName(self, "Open Road Furniture Designer project", "", "GeoPackage (*.gpkg)")
        if gp:
            self.open_path(gp)

    def open_path(self, gp):
        try:
            with _busy():
                st = SignStore.open(gp)
        except Exception as ex:
            QMessageBox.critical(self, "Road Furniture Designer", str(ex))
            return
        self.set_store(st)

    def _need_libs(self, ex):
        QMessageBox.warning(self, "Road Furniture Designer",
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
        p, _ = QFileDialog.getSaveFileName(self, "Road furniture report", base + "_Road_Furniture_Report.pdf",
                                           "PDF (*.pdf)")
        if not p:
            return
        from .report import ReportData, write_pdf, write_pngs, write_xlsx
        from .plansheet import auto_scale
        auto = auto_scale(self.store.al)
        opts = [f"Auto (1:{auto})", "1:500", "1:1000", "1:1250", "1:2000", "1:2500", "1:5000", "No plan sheets"]
        sc, ok = QInputDialog.getItem(self, "Road furniture report", "Plan layout sheets (A3) at scale:", opts, 0, False)
        if not ok:
            return
        plan_scale = auto if sc.startswith("Auto") else (None if sc.startswith("No") else float(sc.split(":")[1]))
        if not self._report_signatories():
            return
        proj = self.store.meta.get("project")
        stem = os.path.splitext(p)[0]
        with _busy():
            d = ReportData(self.store, self.auto_config(), title="Road Furniture" + (f" – {proj}" if proj else ""),
                           plan_scale=plan_scale, barrier_cfg=self.barrier_config(), feature_cfg=self.feature_config())
            n = write_pdf(p, d, sheet_len=1000.0)
            pngs = write_pngs(stem + "_sheets", d, sheet_len=1000.0)
        try:
            write_xlsx(stem + ".xlsx", d)
        except ImportError as ex:
            return self._need_libs(ex)
        self.iface.messageBar().pushMessage(
            "Road Furniture Designer", f"Report: {n} PDF pages, {len(pngs)} PNG sheets and an Excel workbook → "
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
            "Road Furniture Designer", f"Inventory: {len(sl.faces)} faces, {len(sl.installations)} posts → {p}",
            MSG_SUCCESS, 6)

    def export_civil3d(self):
        base = os.path.splitext(self.store.gpkg)[0]
        p, _ = QFileDialog.getSaveFileName(self, "Civil 3D placement package", base + "_placement.json",
                                           "JSON (*.json)")
        if not p:
            return
        scales = ["1:500", "1:1000", "1:1250", "1:2000", "1:2500", "1:5000"]
        sc, ok = QInputDialog.getItem(self, "Plan scale", "Drawing scale for sign symbols and text "
                                      "(symbols print ~10 mm, 25 m at 1:2500):", scales, 4, False)
        if not ok:
            return
        plan_scale = float(sc.split(":")[1])
        try:
            with _busy():
                sl = self.store.export_civil3d(p, os.path.splitext(p)[0] + ".dxf", plan_scale=plan_scale)
        except ImportError as ex:
            return self._need_libs(ex)
        except ValueError as ex:
            QMessageBox.warning(self, "Road Furniture Designer", str(ex))
            return
        self.iface.messageBar().pushMessage(
            "Road Furniture Designer", f"{len(sl.faces)} signs at {sc} → {p}. In Dynamo use symbol scale "
            f"{10 * plan_scale / 1000:g} and the exported DXF as the block source.", MSG_SUCCESS, 10)

    def import_readback(self):
        p, _ = QFileDialog.getOpenFileName(self, "Civil 3D read-back", "", "JSON (*.json)")
        if not p:
            return
        moved, notes = self.store.import_readback(p)
        msg = f"{moved} sign(s) updated from the drawing."
        if notes:
            msg += "\n\n" + "\n".join(notes[:30])
        QMessageBox.information(self, "Road Furniture Designer", msg)

    def closeEvent(self, e):
        if self.iface.mapCanvas().mapTool() is self.tool:
            self.iface.mapCanvas().unsetMapTool(self.tool)
        super().closeEvent(e)
