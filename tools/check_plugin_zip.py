"""Check a built plugin ZIP before it is published: the layout QGIS's Install from ZIP needs.

    python tools/check_plugin_zip.py road_furniture_designer-0.9.0.zip

Fails (exit 1) when:
  * the ZIP does not hold exactly one top folder, road_furniture_designer/
  * metadata.txt, __init__.py with classFactory, the core (rfd/) or the export libraries (ext_libs/) are missing
  * metadata.txt lacks name, version, qgisMinimumVersion or author
  * compiled files, caches, project data or archives are inside
"""
from __future__ import annotations

import configparser
import sys
import zipfile

TOP = "road_furniture_designer"
REQUIRED = ("metadata.txt", "__init__.py", "plugin.py", "dock.py", "rfd/__init__.py", "rfd/data/catalogue.json",
            "rfd/data/junction_templates.json", "ext_libs/")
FORBIDDEN = (".pyc", "__pycache__/", ".gpkg", ".zip", ".pytest_cache/", "_faces/")


def check(path: str) -> list:
    problems = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        tops = {n.split("/", 1)[0] for n in names}
        if tops != {TOP}:
            problems.append(f"top-level entries must be only {TOP}/, found {sorted(tops)}")
        for r in REQUIRED:
            p = f"{TOP}/{r}"
            if not any(n == p or n.startswith(p) for n in names):
                problems.append(f"missing {p}")
        for n in names:
            if any(f in n for f in FORBIDDEN):
                problems.append(f"should not be packaged: {n}")
        if f"{TOP}/__init__.py" in names and b"def classFactory" not in z.read(f"{TOP}/__init__.py"):
            problems.append("__init__.py has no classFactory")
        if f"{TOP}/metadata.txt" in names:
            cp = configparser.ConfigParser(interpolation=None)
            cp.read_string(z.read(f"{TOP}/metadata.txt").decode("utf-8"))
            for k in ("name", "version", "qgisMinimumVersion", "author"):
                if not cp.has_option("general", k):
                    problems.append(f"metadata.txt has no {k}")
    return problems


def version() -> str:
    import os
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(os.path.dirname(__file__), "..", "qgis_plugin", TOP, "metadata.txt"), encoding="utf-8")
    return cp.get("general", "version")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--version":
        print(version())
        sys.exit(0)
    bad = check(sys.argv[1])
    for b in bad:
        print("ERROR:", b)
    print(f"{sys.argv[1]}: {'OK' if not bad else f'{len(bad)} problem(s)'}")
    sys.exit(1 if bad else 0)
