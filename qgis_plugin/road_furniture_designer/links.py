"""Where the User Guide and Technical Manual lives, for the dock's Guide button and the plugin menu."""
import configparser
import os

REPO = "https://github.com/EdmondAkello/Road-Furniture-Designer"
GUIDE_FOLDER = REPO + "/tree/main/docs/user-guide"


def version() -> str:
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(os.path.join(os.path.dirname(__file__), "metadata.txt"), encoding="utf-8")
    return cp.get("general", "version", fallback="")


def guide_url() -> str:
    """The PDF edition for the installed version (at its release tag), else the guide folder."""
    v = version()
    if not v:
        return GUIDE_FOLDER
    return f"{REPO}/blob/v{v}/docs/user-guide/Road_Furniture_Designer_{v}_User_Guide.pdf"


def open_guide():
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    return QDesktopServices.openUrl(QUrl(guide_url()))
