"""Static Qt6 / QGIS 4 checks on the plugin's own code (the same kinds of issue plugins.qgis.org's
Qt6 check reports): scoped enums only, exec() not exec_(), PyQt only through qgis.PyQt, no QVariant
field types, and no third-party package in the plugin."""
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


def test_plugin_uses_no_third_party_package():
    """The plugin ships nothing but its own code: every import is the standard library, QGIS / PyQt, or
    the plugin itself (Excel and DXF are written by rfd/xlsx.py and rfd/dxfw.py)."""
    import ast
    import sys
    std = set(getattr(sys, "stdlib_module_names", ())) or {"os", "sys", "math", "re", "json", "csv"}
    allowed = std | {"qgis", "road_furniture_designer", "rfd", "__future__"}
    bad = []
    for base in (PLUG, os.path.join(ROOT, "rfd")):
        for d, _, files in os.walk(base):
            if "__pycache__" in d or os.sep + "rfd" + os.sep + "rfd" in d:
                continue
            for f in files:
                if not f.endswith(".py") or f in ("cli.py", "__main__.py"):
                    continue
                p = os.path.join(d, f)
                tree = ast.parse(open(p, encoding="utf-8").read())
                for n in ast.walk(tree):
                    mods = []
                    if isinstance(n, ast.Import):
                        mods = [a.name for a in n.names]
                    elif isinstance(n, ast.ImportFrom) and not n.level:
                        mods = [n.module or ""]
                    bad += [f"{os.path.relpath(p, ROOT)}: {m}" for m in mods if m.split(".")[0] not in allowed]
    assert not bad, bad


def test_built_plugin_has_no_vendored_libraries(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_plugin", os.path.join(ROOT, "tools", "build_plugin.py"))
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    (tmp_path / "ext_libs" / "old").mkdir(parents=True)          # left by a build before 0.12.1
    monkeypatch.setattr(bp, "PLUG", str(tmp_path))
    bp.clean_vendor()
    assert not (tmp_path / "ext_libs").exists()
