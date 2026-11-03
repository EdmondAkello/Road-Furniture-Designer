# RoadSign Designer - PLACE signs in Civil 3D from a placement package (JSON).
# Paste into a Dynamo "Python Script" node (Civil 3D 2026+, CPython3 / PythonNet3 engine).
#
# Inputs:
#   IN[0]  str    Path to *_placement.json produced by `python -m rsd build`
#   IN[1]  str    Civil 3D alignment name ("" = use the name in the package)
#   IN[2]  float  Symbol scale: 10 x plan scale / 1000 (25 at 1:2500, 10 at 1:1000) so symbols print ~10 mm
#   IN[3]  bool   Run = True to write to the drawing; False = dry run (report only)
#   IN[4]  str    Block source: the exported *_placement.dxf (recommended - includes legend blocks)
#                 or the RSD block library DWG. Missing blocks are imported from it.
# Output:  list of report lines
#
# Behaviour:
#   - Signs are matched to existing blocks by FACE UUID (XDATA app "RSD"), never by handle.
#     Existing sign -> updated in place. New sign -> inserted. Nothing is ever deleted;
#     blocks in the drawing that are no longer in the package are reported.
#   - Positions are computed from the DRAWING's alignment (station + offset), and compared
#     with the package's LandXML-derived coordinates. Differences > 0.02 m are reported:
#     that means the drawing alignment and the LandXML used for the sign list differ.
#   - UNTESTED in Civil 3D at time of writing; see README "First run in Civil 3D".

import clr, json, math
import System

clr.AddReference("AcMgd")
clr.AddReference("AcCoreMgd")
clr.AddReference("AcDbMgd")
clr.AddReference("AeccDbMgd")

from Autodesk.AutoCAD.ApplicationServices.Core import Application as AcApp
from Autodesk.AutoCAD.DatabaseServices import (
    BlockReference, BlockTable, BlockTableRecord, AttributeDefinition, AttributeReference,
    OpenMode, ResultBuffer, TypedValue, RegAppTableRecord, Database, DuplicateRecordCloning,
    ObjectIdCollection, IdMapping, LayerTableRecord)
from Autodesk.AutoCAD.Geometry import Point3d, Scale3d
from Autodesk.Civil.ApplicationServices import CivilApplication

APPID = "RSD"
LAYER = "RSD-SIGN"
TOL = 0.02

pkg_path = IN[0]
al_name = IN[1] if len(IN) > 1 and IN[1] else None
scale = float(IN[2]) if len(IN) > 2 and IN[2] else 25.0
run = bool(IN[3]) if len(IN) > 3 else False
lib_path = IN[4] if len(IN) > 4 and IN[4] else None

report = []


def floats(res):
    """PythonNet returns ref/out params as a tuple; keep the numeric values."""
    if isinstance(res, tuple):
        return [v for v in res if isinstance(v, float)]
    return []


def rsd_xdata(ent):
    rb = ent.GetXDataForApplication(APPID)
    if rb is None:
        return None
    vals = [tv.Value for tv in rb.AsArray()]
    return vals[1:] if len(vals) > 1 else None   # [version, face_uuid, install_uuid]


def ensure_regapp(tr, db):
    rat = tr.GetObject(db.RegAppTableId, OpenMode.ForRead)
    if not rat.Has(APPID):
        rat.UpgradeOpen()
        rec = RegAppTableRecord()
        rec.Name = APPID
        rat.Add(rec)
        tr.AddNewlyCreatedDBObject(rec, True)


def ensure_layer(tr, db):
    lt = tr.GetObject(db.LayerTableId, OpenMode.ForRead)
    if not lt.Has(LAYER):
        lt.UpgradeOpen()
        rec = LayerTableRecord()
        rec.Name = LAYER
        lt.Add(rec)
        tr.AddNewlyCreatedDBObject(rec, True)


def import_blocks(db, path, names):
    """Copy block definitions from the RSD library DWG, or from the exported placement DXF
    (which also holds the per-sign legend blocks for directional signs and plates)."""
    side = Database(False, True)
    if path.lower().endswith(".dxf"):
        side.DxfIn(path, None)
    else:
        side.ReadDwgFile(path, System.IO.FileShare.Read, True, "")
    ids = ObjectIdCollection()
    with side.TransactionManager.StartTransaction() as st:
        bt = st.GetObject(side.BlockTableId, OpenMode.ForRead)
        for n in names:
            if bt.Has(n):
                ids.Add(bt[n])
        st.Commit()
    if ids.Count:
        side.WblockCloneObjects(ids, db.BlockTableId, IdMapping(), DuplicateRecordCloning.Ignore, False)
    side.Dispose()
    return ids.Count


def find_alignment(tr, cdoc, name):
    for oid in cdoc.GetAlignmentIds():
        al = tr.GetObject(oid, OpenMode.ForRead)
        if al.Name == name:
            return al
    return None


def set_attributes(tr, br, btr, values, create):
    existing = {}
    if not create:
        for aid in br.AttributeCollection:
            ar = tr.GetObject(aid, OpenMode.ForWrite)
            existing[ar.Tag.upper()] = ar
    for oid in btr:
        obj = tr.GetObject(oid, OpenMode.ForRead)
        if not isinstance(obj, AttributeDefinition) or obj.Constant:
            continue
        tag = obj.Tag.upper()
        val = values.get(tag)
        if val is None:
            continue
        if tag in existing:
            ar = existing[tag]
            ar.SetAttributeFromBlock(obj, br.BlockTransform)
            ar.TextString = str(val)
        else:
            ar = AttributeReference()
            ar.SetAttributeFromBlock(obj, br.BlockTransform)
            ar.TextString = str(val)
            br.AttributeCollection.AppendAttribute(ar)
            tr.AddNewlyCreatedDBObject(ar, True)


with open(pkg_path) as f:
    pkg = json.load(f)
faces = pkg["faces"]
al_name = al_name or pkg["alignment"]["name"]

adoc = AcApp.DocumentManager.MdiActiveDocument
db = adoc.Database
cdoc = CivilApplication.ActiveDocument

with adoc.LockDocument():
    # import missing blocks first (own transaction)
    with db.TransactionManager.StartTransaction() as tr:
        bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead)
        missing = sorted({f["block_name"] for f in faces if not bt.Has(f["block_name"])})
        tr.Commit()
    if missing and lib_path and run:
        n = import_blocks(db, lib_path, missing)
        report.append("Imported %d block definition(s) from library" % n)

    with db.TransactionManager.StartTransaction() as tr:
        bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead)
        missing = sorted({f["block_name"] for f in faces if not bt.Has(f["block_name"])})
        if missing:
            report.append("MISSING BLOCKS (insert the RSD block library first): " + ", ".join(missing))
        al = find_alignment(tr, cdoc, al_name)
        if al is None:
            report.append("ERROR: alignment '%s' not found in drawing" % al_name)
        else:
            if run:
                ensure_regapp(tr, db)
                ensure_layer(tr, db)
            ms = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite if run else OpenMode.ForRead)

            # index existing RSD blocks by face UUID
            existing = {}
            for oid in ms:
                if oid.ObjectClass.DxfName != "INSERT":
                    continue
                ent = tr.GetObject(oid, OpenMode.ForRead)
                xd = rsd_xdata(ent)
                if xd and len(xd) >= 2:
                    existing[xd[1]] = oid

            created = updated = skipped = 0
            seen = set()
            for f in faces:
                if f["block_name"] in missing:
                    skipped += 1
                    continue
                try:
                    xy = floats(al.PointLocation(f["station_internal"], f["offset_m"], 0.0, 0.0))
                    e, n = xy[-2], xy[-1]
                except Exception as ex:   # station outside the drawing alignment, etc.
                    report.append("%s %s: cannot locate on '%s' (%s) - skipped"
                                  % (f["sign_code"], f["station_display_text"], al_name, ex))
                    skipped += 1
                    continue
                d = math.hypot(e - f["x"], n - f["y"])
                if d > TOL:
                    report.append("CHECK %s %s: drawing alignment gives a point %.3f m from the "
                                  "LandXML position" % (f["sign_code"], f["station_display_text"], d))
                # rotation from the drawing alignment's own direction
                s1 = max(f["station_internal"] - 0.05, al.StartingStation)
                s2 = min(f["station_internal"] + 0.05, al.EndingStation)
                e1, n1 = floats(al.PointLocation(s1, 0.0, 0.0, 0.0))[-2:]
                e2, n2 = floats(al.PointLocation(s2, 0.0, 0.0, 0.0))[-2:]
                h = math.atan2(n2 - n1, e2 - e1)
                face_dir = h + (math.pi if f["facing"] == "Forward" else 0.0)
                rot = math.radians(math.degrees(face_dir) - 90.0 + f.get("skew_deg", 0.0))

                attrs = {
                    "SIGN_CODE": f["sign_code"], "LEGEND": f.get("legend_text", ""),
                    "DESCRIPTION": f["description"], "SIZE": f["size"],
                    "CHAINAGE": f["station_display_text"], "OFFSET": "%.2f" % abs(f["offset_m"]),
                    "SIDE": f["side"], "FACING": f["facing"], "POST_REF": f["post_ref"],
                    "FACE_UUID": f["face_uuid"], "INSTALL_UUID": f["installation_uuid"]}
                seen.add(f["face_uuid"])
                if not run:
                    if f["face_uuid"] in existing:
                        updated += 1
                    else:
                        created += 1
                    continue
                btr = tr.GetObject(bt[f["block_name"]], OpenMode.ForRead)
                if f["face_uuid"] in existing:
                    br = tr.GetObject(existing[f["face_uuid"]], OpenMode.ForWrite)
                    if br.BlockTableRecord != btr.ObjectId:
                        report.append("%s: sign code changed - block definition swapped" % f["face_uuid"][:8])
                        br.BlockTableRecord = btr.ObjectId
                    br.Position = Point3d(e, n, 0.0)
                    br.Rotation = rot
                    br.ScaleFactors = Scale3d(scale)
                    set_attributes(tr, br, btr, attrs, create=False)
                    updated += 1
                else:
                    br = BlockReference(Point3d(e, n, 0.0), btr.ObjectId)
                    br.Rotation = rot
                    br.ScaleFactors = Scale3d(scale)
                    br.Layer = LAYER
                    ms.AppendEntity(br)
                    tr.AddNewlyCreatedDBObject(br, True)
                    set_attributes(tr, br, btr, attrs, create=True)
                    br.XData = ResultBuffer(TypedValue(1001, APPID), TypedValue(1000, "rsd/0.1"),
                                            TypedValue(1000, f["face_uuid"]),
                                            TypedValue(1000, f["installation_uuid"]))
                    created += 1

            orphans = [u for u in existing if u not in seen]
            if orphans:
                report.append("%d RSD block(s) in the drawing are not in this package (not deleted): %s"
                              % (len(orphans), ", ".join(u[:8] for u in orphans)))
            report.insert(0, "%s: %d new, %d updated, %d skipped on alignment '%s'"
                          % ("PLACED" if run else "DRY RUN", created, updated, skipped, al_name))
        tr.Commit()

OUT = report
