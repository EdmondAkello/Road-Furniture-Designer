"""Enum compatibility across QGIS 3.28 - 3.44+.

QGIS 3.44 enforces the scoped enums (Qgis.LabelPlacement, Qgis.WkbType, ...), and
some old unscoped aliases (e.g. QgsPalLayerSettings.OverPoint) resolve to the
wrong enum there. Always prefer the scoped form when it exists.
"""
from qgis.core import Qgis, QgsPalLayerSettings, QgsSymbolLayer, QgsVectorFileWriter, QgsWkbTypes


def _pick(*getters):
    for g in getters:
        try:
            return g()
        except AttributeError:
            continue
    raise AttributeError("no compatible enum value")


LABEL_OVER_POINT = _pick(lambda: Qgis.LabelPlacement.OverPoint, lambda: QgsPalLayerSettings.OverPoint)
QUADRANT_RIGHT = _pick(lambda: Qgis.LabelQuadrantPosition.Right, lambda: QgsPalLayerSettings.QuadrantRight)

WKB_POINT = _pick(lambda: Qgis.WkbType.Point, lambda: QgsWkbTypes.Point)
WKB_LINESTRING = _pick(lambda: Qgis.WkbType.LineString, lambda: QgsWkbTypes.LineString)
WKB_NOGEOM = _pick(lambda: Qgis.WkbType.NoGeometry, lambda: QgsWkbTypes.NoGeometry)
GEOM_LINE = _pick(lambda: Qgis.GeometryType.Line, lambda: QgsWkbTypes.LineGeometry)
GEOM_POINT = _pick(lambda: Qgis.GeometryType.Point, lambda: QgsWkbTypes.PointGeometry)

PROP_NAME = _pick(lambda: QgsSymbolLayer.Property.Name, lambda: QgsSymbolLayer.PropertyName)
PROP_ANGLE = _pick(lambda: QgsSymbolLayer.Property.Angle, lambda: QgsSymbolLayer.PropertyAngle)
PROP_SIZE = _pick(lambda: QgsSymbolLayer.Property.Size, lambda: QgsSymbolLayer.PropertySize)

MARKER_ARROWHEAD = _pick(lambda: Qgis.MarkerShape.ArrowHeadFilled,
                         lambda: __import__("qgis.core", fromlist=["x"]).QgsSimpleMarkerSymbolLayerBase.ArrowHeadFilled)

FW_CREATE_FILE = _pick(lambda: QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile,
                       lambda: QgsVectorFileWriter.CreateOrOverwriteFile)
FW_CREATE_LAYER = _pick(lambda: QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer,
                        lambda: QgsVectorFileWriter.CreateOrOverwriteLayer)
FW_NO_ERROR = _pick(lambda: QgsVectorFileWriter.WriterError.NoError, lambda: QgsVectorFileWriter.NoError)

MSG_INFO = _pick(lambda: Qgis.MessageLevel.Info, lambda: Qgis.Info)
MSG_WARNING = _pick(lambda: Qgis.MessageLevel.Warning, lambda: Qgis.Warning)
MSG_SUCCESS = _pick(lambda: Qgis.MessageLevel.Success, lambda: Qgis.Success)
MSG_LEVELS = {0: MSG_INFO, 1: MSG_WARNING, 2: _pick(lambda: Qgis.MessageLevel.Critical, lambda: Qgis.Critical)}
PROP_ENABLED = _pick(lambda: QgsSymbolLayer.Property.LayerEnabled, lambda: QgsSymbolLayer.PropertyLayerEnabled)
GEOM_CIRCLE = _pick(lambda: Qgis.MarkerShape.Circle,
                    lambda: __import__("qgis.core", fromlist=["x"]).QgsSimpleMarkerSymbolLayerBase.Circle)
PROP_OFFSET = _pick(lambda: QgsSymbolLayer.Property.Offset, lambda: QgsSymbolLayer.PropertyOffset)
WKB_MULTILINESTRING = _pick(lambda: Qgis.WkbType.MultiLineString, lambda: QgsWkbTypes.MultiLineString)


def make_field(name, qvariant_type):
    """A QgsField from a QVariant type: through QMetaType on QGIS 3.38+, where the QVariant form is
    deprecated, and the old constructor before it."""
    from qgis.core import QgsField
    if Qgis.versionInt() >= 33800:
        from qgis.PyQt.QtCore import QMetaType
        return QgsField(name, QMetaType.Type(int(qvariant_type)))
    return QgsField(name, qvariant_type)
