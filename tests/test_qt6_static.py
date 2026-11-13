"""Static Qt6 / QGIS 4 checks on the plugin's own code (the same kinds of issue plugins.qgis.org's
Qt6 check reports): scoped enums only, exec() not exec_(), PyQt only through qgis.PyQt, no QVariant
field types, and none of the vendored Qt add-ons in the package (a
vendored module may still import Qt inside a function RFD never calls)."""
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUG = os.path.join(ROOT, "qgis_plugin", "road_furniture_designer")
OWN = sorted(os.path.join(PLUG, f) for f in os.listdir(PLUG) if f.endswith(".py"))

# a class whose enum member is written without its enum scope: Qt.UserRole, QHeaderView.Stretch
QT_CLASSES = ("Qt", "QHeaderView", "QAbstractItemView", "QTableWidget", "QTreeWidget", "QListWidget", "QFrame",
              "QSizePolicy", "QMessageBox", "QDialogButtonBox", "QPainter", "QImage", "QFont", "QPageLayout",
              "QPageSize", "QComboBox", "QFormLayout", "QBoxLayout", "QLineEdit", "QToolButton", "QTabWidget",
              "QDockWidget", "QAction", "QKeySequence", "QPalette", "QColor", "QPen", "QBrush", "QIODevice",
              "QFileDialog", "QSlider", "QAbstractSpinBox", "QTextOption", "QPrinter")
UNSCOPED = re.compile(r"\b(" + "|".join(QT_CLASSES) + r")\.([A-Z][A-Za-z0-9_]*)\b(?![.(\w])")
OLD_QGIS = re.compile(r"\bQgsWkbTypes\.(Point|Line|Polygon|Unknown|Null)Geometry\b")


def _code_lines(path):
    with open(path, encoding="utf-8") as fh:
        for no, line in enumerate(fh, 1):
            if not line.lstrip().startswith("#"):
                yield no, line


@pytest.mark.parametrize("path", OWN, ids=os.path.basename)
def test_scoped_enums(path):
    bad = [f"{os.path.basename(path)}:{no}: {m.group(0)}" for no, code in _code_lines(path)
           for m in UNSCOPED.finditer(code)]
    bad += [f"{os.path.basename(path)}:{no}: {m.group(0)} (use Qgis.GeometryType)"
            for no, code in _code_lines(path) for m in OLD_QGIS.finditer(code)]
    assert not bad, "unscoped enums:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", OWN, ids=os.path.basename)
def test_no_qt5_only_api(path):
    bad = []
    for no, code in _code_lines(path):
        if re.search(r"\.exec_\(", code):
            bad.append(f"{no}: exec_() (use exec())")
        if re.search(r"\b(from|import)\s+PyQt[56]\b", code):
            bad.append(f"{no}: import PyQt through qgis.PyQt")
        if re.search(r"\bQVariant\.[A-Z]", code):
            bad.append(f"{no}: QVariant type (use QMetaType.Type; gone in PyQt6)")
        if re.search(r"\bQRegExp\b", code):
            bad.append(f"{no}: QRegExp (gone in Qt6; use QRegularExpression)")
        if re.search(r"QtWidgets import[^\n]*\bQAction\b", code) and not path.endswith("compat.py"):
            bad.append(f"{no}: QAction from QtWidgets (QtGui in Qt6; use compat.QAction)")
    assert not bad, os.path.basename(path) + ":\n" + "\n".join(bad)


def test_metadata_targets_qgis4():
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(PLUG, "metadata.txt"), encoding="utf-8")
    assert cp.get("general", "qgisMinimumVersion") == "3.44"
    assert float(cp.get("general", "qgisMaximumVersion")) >= 4.0
    assert not cp.has_option("general", "supportsQt6")      # removed by QGIS; the maximum version decides


def test_vendored_qt_addons_pruned(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_plugin", os.path.join(ROOT, "tools", "build_plugin.py"))
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    monkeypatch.setattr(bp, "PLUG", str(tmp_path))
    bp.sync_vendor()
    ext = tmp_path / "ext_libs"
    if not ext.is_dir():
        pytest.skip("no vendor/ext_libs in this checkout")
    for rel in bp.QT_ADDONS:
        assert not (ext / rel).exists(), rel
    hits = []
    for d, _, files in os.walk(ext):
        for f in files:
            if f.endswith(".py"):
                with open(os.path.join(d, f), encoding="utf-8", errors="ignore") as fh:
                    src = fh.read()
                if re.search(r"^(from|import)\s+(PyQt[56]|PySide[26])\b", src, re.M):
                    hits.append(os.path.relpath(os.path.join(d, f), ext))
    assert not hits, hits
