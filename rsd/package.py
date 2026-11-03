"""Placement package: the JSON handed to Civil 3D (Dynamo) or any other client."""
from __future__ import annotations

import datetime as dt
import json

from . import __version__
from .alignment import Alignment, format_station
from .catalogue import Catalogue
from .legend import summary as legend_summary
from .records import SCHEMA_VERSION, SignList


def build_package(sl: SignList, al: Alignment, cat: Catalogue, project: str = "", crs: dict = None) -> dict:
    faces = []
    for f in sorted(sl.faces, key=lambda f: (f.station_internal, f.row)):
        sd = cat.signs[f.code]
        faces.append({
            "face_uuid": f.face_uuid,
            "installation_uuid": f.install_uuid,
            "post_ref": f.post_ref,
            "sign_code": f.code,
            "description": sd.name,
            "size": f.size,
            "block_name": (f"RSD_{f.code}_{f.face_uuid[:8]}" if sd.legend in ("directional", "plate") and f.legend
                           else sd.block(f.mirror)),
            "mirror": f.mirror,
            "legend": f.legend,
            "legend_text": legend_summary(f.legend) if f.legend else "",
            "road_class": f.road_class,
            "edge_ref": f.edge_ref, "edge_clear_m": f.edge_clear,
            "grade_pct": f.grade, "design_speed_kmh": f.speed,
            "station_display": round(f.station_display, 4),
            "station_display_text": format_station(f.station_display),
            "station_internal": round(f.station_internal, 4),
            "offset_m": round(f.offset_signed, 4),
            "side": f.side,
            "facing": f.facing,
            "skew_deg": f.skew,
            "x": round(f.x, 4),
            "y": round(f.y, 4),
            "rotation_deg": round(f.rotation_deg, 4),
            "post_type": f.post_type,
            "foundation": f.foundation,
            "remarks": f.remarks,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": f"rsd {__version__}",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "project": project,
        "catalogue_version": cat.version,
        "alignment": {"name": al.name, "sta_start": al.sta_start, "sta_end": al.sta_end,
                      "length": al.length},
        "crs": crs or {},
        "coordinates": "x = easting, y = northing in metres, exactly as in the source LandXML",
        "conventions": {
            "offset": "positive = right of alignment looking up-chainage",
            "rotation": "block local +Y points toward the traffic the sign faces; degrees CCW from +X",
            "station_internal": "geometric station (staStart + distance), before station equations",
        },
        "faces": faces,
    }


def write_package(path: str, pkg: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2)
