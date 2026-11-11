import os
import sys

# Bundled pure-Python export libraries (openpyxl, ezdxf + deps) for machines where pip is
# blocked. Appended, not prepended: a copy already installed in QGIS's Python wins.
_EXT = os.path.join(os.path.dirname(__file__), "ext_libs")
if os.path.isdir(_EXT) and _EXT not in sys.path:
    sys.path.append(_EXT)


def classFactory(iface):
    from .plugin import RoadFurnitureDesignerPlugin
    return RoadFurnitureDesignerPlugin(iface)
