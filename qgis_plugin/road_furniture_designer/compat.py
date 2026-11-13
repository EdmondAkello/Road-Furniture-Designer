"""QGIS enums and helpers for QGIS 3.34 - 3.44+ (the plugin needs 3.34 or later).

QGIS 3.44 enforces the scoped enums (Qgis.LabelPlacement, Qgis.WkbType, ...), and some old unscoped
aliases (e.g. QgsPalLayerSettings.OverPoint) resolve to the wrong enum there. All the scoped forms below
exist from QGIS 3.30, so they are used directly. QgsSymbolLayer.Property is the exception: it became
scoped in QGIS 3.36 (Property.Name); 3.34 only has the old member names (PropertyName), so prop() tries both.
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



def prop(name):
    """A symbol layer data-defined property key: QgsSymbolLayer.Property.<name> on QGIS 3.36+, and
    QgsSymbolLayer.Property<name> on 3.34."""
    scoped = getattr(QgsSymbolLayer.Property, name, None)
    return scoped if scoped is not None else getattr(QgsSymbolLayer, "Property" + name)


PROP_NAME = prop("Name")
PROP_ANGLE = prop("Angle")
PROP_SIZE = prop("Size")
PROP_OFFSET = prop("Offset")
PROP_ENABLED = prop("LayerEnabled")
PROP_CUSTOM_DASH = prop("CustomDash")

MARKER_ARROWHEAD = Qgis.MarkerShape.ArrowHeadFilled
GEOM_CIRCLE = Qgis.MarkerShape.Circle

FW_CREATE_FILE = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
FW_CREATE_LAYER = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
FW_NO_ERROR = QgsVectorFileWriter.WriterError.NoError

MSG_INFO = Qgis.MessageLevel.Info
MSG_WARNING = Qgis.MessageLevel.Warning
MSG_SUCCESS = Qgis.MessageLevel.Success
MSG_LEVELS = {0: MSG_INFO, 1: MSG_WARNING, 2: Qgis.MessageLevel.Critical}


def make_field(name, qvariant_type):
    """A QgsField from a QVariant type: through QMetaType on QGIS 3.38+, where the QVariant form is
    deprecated, and the old constructor before it."""
    from qgis.core import QgsField
    if Qgis.versionInt() >= 33800:
        from qgis.PyQt.QtCore import QMetaType
        return QgsField(name, QMetaType.Type(int(qvariant_type)))
    return QgsField(name, qvariant_type)
