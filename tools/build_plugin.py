"""Copy the core into the plugin folder and zip it for QGIS (Plugins > Install from ZIP)."""
import os, shutil, sys, zipfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PLUG = os.path.join(ROOT, "qgis_plugin", "road_furniture_designer")


def sync_core():
    dst = os.path.join(PLUG, "rfd")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "rfd"), dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "cli.py", "__main__.py"))


def clean_vendor():
    """Up to 0.12.0 the plugin bundled openpyxl and ezdxf in ext_libs/; it now writes Excel and DXF itself.
    Remove a copy left in the plugin folder by an older build so it is not packaged."""
    shutil.rmtree(os.path.join(PLUG, "ext_libs"), ignore_errors=True)


def sync_license():
    """plugins.qgis.org refuses a ZIP without a LICENSE file in the plugin folder."""
    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(PLUG, "LICENSE"))


def sync_guide():
    """The user guide PDF for this version, so the dock's Guide button opens it without a connection."""
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(PLUG, "metadata.txt"), encoding="utf-8")
    v = cp.get("general", "version")
    name = f"Road_Furniture_Designer_{v}_User_Guide.pdf"
    dst = os.path.join(PLUG, "doc")
    shutil.rmtree(dst, ignore_errors=True)
    src = os.path.join(ROOT, "docs", "user-guide", name)
    if os.path.exists(src):
        os.makedirs(dst)
        shutil.copyfile(src, os.path.join(dst, name))
    else:
        print(f"warning: {name} not found; the Guide button will open GitHub")


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
    clean_vendor()
    sync_license()
    sync_guide()
    if len(sys.argv) > 1:
        make_zip(sys.argv[1])
        print("wrote", sys.argv[1])
    else:
        print("core synced into plugin")
