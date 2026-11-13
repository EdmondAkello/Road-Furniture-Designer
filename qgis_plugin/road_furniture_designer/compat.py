"""QGIS enums and helpers for QGIS 3.44 - 4.x (Qt5 and Qt6; the plugin needs 3.44 or later).

QGIS 4 (Qt6 / PyQt6) only has the scoped enums (Qgis.LabelPlacement, Qgis.WkbType, Qt.ItemDataRole.UserRole,
...), and some old unscoped aliases (e.g. QgsPalLayerSettings.OverPoint) resolve to the wrong enum on
3.44. The scoped forms below exist on every supported version, so they are used directly.
"""
from qgis.core import Qgis, QgsSimpleMarkerSymbolLayerBase, QgsSymbolLayer, QgsVectorFileWriter  # noqa: F401

LABEL_OVER_POINT = Qgis.LabelPlacement.OverPoint
QUADRANT_RIGHT = Qgis.LabelQuadrantPosition.Right

WKB_POINT = Qgis.WkbType.Point
WKB_LINESTRING = Qgis.WkbType.LineString
WKB_MULTILINESTRING = Qgis.WkbType.MultiLineString
WKB_NOGEOM = Qgis.WkbType.NoGeometry
GEOM_LINE = Qgis.GeometryType.Line
GEOM_POINT = Qgis.GeometryType.Point



PROP_NAME = QgsSymbolLayer.Property.Name
PROP_ANGLE = QgsSymbolLayer.Property.Angle
PROP_SIZE = QgsSymbolLayer.Property.Size
PROP_OFFSET = QgsSymbolLayer.Property.Offset
PROP_ENABLED = QgsSymbolLayer.Property.LayerEnabled
PROP_CUSTOM_DASH = QgsSymbolLayer.Property.CustomDash

MARKER_ARROWHEAD = Qgis.MarkerShape.ArrowHeadFilled
GEOM_CIRCLE = Qgis.MarkerShape.Circle

FW_CREATE_FILE = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
FW_CREATE_LAYER = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
FW_NO_ERROR = QgsVectorFileWriter.WriterError.NoError

MSG_INFO = Qgis.MessageLevel.Info
MSG_WARNING = Qgis.MessageLevel.Warning
MSG_SUCCESS = Qgis.MessageLevel.Success
MSG_LEVELS = {0: MSG_INFO, 1: MSG_WARNING, 2: Qgis.MessageLevel.Critical}


def make_field(name, meta_type):
    """A QgsField from a QMetaType.Type (QMetaType.Type.QString, .Double, .Int); the QVariant type
    form is deprecated on QGIS 3.x and gone with PyQt6."""
    from qgis.core import QgsField
    return QgsField(name, meta_type)



class one_change:
    """Hold a store's signals for a batch of edits and emit its changed signal once at the end, so the dock
    rebuilds the inventory once rather than once per feature (a GeoPackage commit signals every feature).
    Nested uses emit only at the outermost exit."""

    def __init__(self, store):
        self.store = store

    def __enter__(self):
        self.was = self.store.blockSignals(True)
        return self.store

    def __exit__(self, *exc):
        self.store.blockSignals(self.was)
        if not self.was:
            self.store.changed.emit()
        return False


try:                                    # Qt6 moved QAction from QtWidgets to QtGui
    from qgis.PyQt.QtGui import QAction  # noqa: F401
except ImportError:
    from qgis.PyQt.QtWidgets import QAction  # noqa: F401
