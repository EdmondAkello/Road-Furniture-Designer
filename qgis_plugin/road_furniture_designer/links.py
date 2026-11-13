"""Where the User Guide and Technical Manual lives, for the dock's Guide button and the plugin menu:
the PDF bundled in the plugin (doc/), else the copy on GitHub at the version's tag."""
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


def local_guide() -> str:
    """The PDF bundled in the plugin for this version, or '' when it is not there."""
    p = os.path.join(os.path.dirname(__file__), "doc", f"Road_Furniture_Designer_{version()}_User_Guide.pdf")
    return p if os.path.exists(p) else ""


def open_guide():
    """Open the bundled PDF in the system's PDF viewer; the copy on GitHub when it is missing."""
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices
    p = local_guide()
    return QDesktopServices.openUrl(QUrl.fromLocalFile(p) if p else QUrl(guide_url()))
