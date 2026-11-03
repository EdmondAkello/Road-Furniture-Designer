# RoadSign Designer - READ BACK placed signs from the drawing to a JSON file.
# Paste into a Dynamo "Python Script" node (Civil 3D 2026+, CPython3 / PythonNet3 engine).
#
# Inputs:
#   IN[0]  str  Output path for the read-back JSON (e.g. ...\SignList_readback.json)
# Output:  report lines
#
# Only blocks carrying RSD XDATA are read - nothing else in the drawing is touched.
# Then run on the PC:  python -m rsd reconcile SignList.xlsx readback.json road.xml

import clr, json, math, datetime

clr.AddReference("AcMgd")
clr.AddReference("AcCoreMgd")
clr.AddReference("AcDbMgd")

from Autodesk.AutoCAD.ApplicationServices.Core import Application as AcApp
from Autodesk.AutoCAD.DatabaseServices import BlockTableRecord, OpenMode

APPID = "RSD"
out_path = IN[0]

adoc = AcApp.DocumentManager.MdiActiveDocument
db = adoc.Database
signs = []
with adoc.LockDocument():
    with db.TransactionManager.StartTransaction() as tr:
        bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead)
        ms = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead)
        for oid in ms:
            if oid.ObjectClass.DxfName != "INSERT":
                continue
            br = tr.GetObject(oid, OpenMode.ForRead)
            rb = br.GetXDataForApplication(APPID)
            if rb is None:
                continue
            vals = [tv.Value for tv in rb.AsArray()]
            if len(vals) < 4:
                continue
            attrs = {}
            for aid in br.AttributeCollection:
                ar = tr.GetObject(aid, OpenMode.ForRead)
                attrs[ar.Tag.upper()] = ar.TextString
            btr = tr.GetObject(br.DynamicBlockTableRecord, OpenMode.ForRead)
            signs.append({
                "face_uuid": vals[2], "installation_uuid": vals[3],
                "block_name": btr.Name, "x": br.Position.X, "y": br.Position.Y,
                "rotation_deg": math.degrees(br.Rotation) % 360.0,
                "handle": str(br.Handle), "attributes": attrs})
        tr.Commit()

with open(out_path, "w") as f:
    json.dump({"schema_version": "0.1", "source": "civil3d",
               "drawing": db.Filename,
               "created_utc": datetime.datetime.utcnow().isoformat(timespec="seconds"),
               "signs": signs}, f, indent=2)

OUT = ["Read %d RSD sign block(s) -> %s" % (len(signs), out_path)]
