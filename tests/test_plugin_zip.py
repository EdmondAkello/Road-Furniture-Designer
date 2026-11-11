"""The plugin ZIP has the layout QGIS's Install from ZIP needs."""
import os
import subprocess  # nosec B404 - runs the repo's own build script
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_plugin_zip as C  # noqa: E402


def test_built_zip_passes_the_check(tmp_path):
    z = tmp_path / "rfd.zip"
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_plugin.py"), str(z)],  # nosec B603
                   check=True, capture_output=True)
    assert C.check(str(z)) == []
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
    assert "road_furniture_designer/rfd/junctions.py" in names
    assert not [n for n in names if n.endswith(".pyc") or "/tests" in n]


def test_check_catches_a_repository_zip(tmp_path):
    z = tmp_path / "repo.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Road-Furniture-Designer-main/qgis_plugin/road_furniture_designer/__init__.py", "")
        f.writestr("Road-Furniture-Designer-main/README.md", "")
    bad = C.check(str(z))
    assert any("top-level" in b for b in bad) and any("missing" in b for b in bad)


def test_version_matches_metadata():
    assert C.version().count(".") == 2
