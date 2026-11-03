"""Copy the core into the plugin folder and zip it for QGIS (Plugins > Install from ZIP)."""
import os, shutil, sys, zipfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUG = os.path.join(ROOT, "qgis_plugin", "roadsign_designer")


def sync_core():
    dst = os.path.join(PLUG, "rsd")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "rsd"), dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "cli.py", "__main__.py"))


def sync_vendor():
    src = os.path.join(ROOT, "vendor", "ext_libs")
    dst = os.path.join(PLUG, "ext_libs")
    shutil.rmtree(dst, ignore_errors=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyx"))


def make_zip(out):
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d, _, files in os.walk(PLUG):
            if "__pycache__" in d:
                continue
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(d, f)
                z.write(full, os.path.relpath(full, os.path.dirname(PLUG)))


if __name__ == "__main__":
    sync_core()
    sync_vendor()
    if len(sys.argv) > 1:
        make_zip(sys.argv[1])
        print("wrote", sys.argv[1])
    else:
        print("core synced into plugin")
