"""Reconcile a Civil 3D read-back (moved / edited sign blocks) into the sign list.

Matching is by FACE UUID only. Positions are re-referenced with the same LandXML
alignment used to build the sign list, so chainage/offset stay consistent.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from typing import List

from .xlsx import load_workbook

from .alignment import Alignment, format_station
from .catalogue import Catalogue
from .records import facing_from_rotation
from .signlist import COLUMNS, FIRST_ROW

POS_TOL = 0.02     # m
ROT_TOL = 1.0      # deg


@dataclass
class Change:
    row: int
    face_uuid: str
    field: str
    old: str
    new: str


def reconcile(signlist_path: str, readback_path: str, al: Alignment, cat: Catalogue,
              apply: bool = True):
    with open(readback_path, encoding="utf-8") as f:
        rb = json.load(f)
    wb = load_workbook(signlist_path)
    ws = wb["Signs"]
    col = {k: i + 1 for i, (_, k, _) in enumerate(COLUMNS)}
    rows = {}
    for r in range(FIRST_ROW, ws.max_row + 1):
        u = ws.cell(r, col["face_uuid"]).value
        if u:
            rows[str(u).strip()] = r
    by_block = {}
    for code, sd in cat.signs.items():
        by_block[sd.block(False)] = code
        if sd.mirror:
            by_block[sd.block(True)] = code

    changes: List[Change] = []
    notes: List[str] = []
    seen = set()
    for s in rb["signs"]:
        u = s["face_uuid"]
        seen.add(u)
        r = rows.get(u)
        if r is None:
            notes.append(f"Block {u[:8]} ({s.get('block_name')}) at "
                         f"{s['x']:.2f},{s['y']:.2f} has no row in the sign list (row deleted?)")
            continue
        so = al.station_offset(s["x"], s["y"])
        if not so.in_range:
            notes.append(f"Row {r}: block {u[:8]} now lies beyond the alignment ends - not updated")
            continue
        _, _, h = al.point_at(so.station)
        facing, skew = facing_from_rotation(s["rotation_deg"], h)
        new = {
            "station": format_station(al.display_station(so.station)),
            "offset": round(abs(so.offset), 2),
            "side": "R" if so.offset >= 0 else "L",
            "facing": facing,
            "skew": skew if abs(skew) >= ROT_TOL else 0,
        }
        code = by_block.get(s.get("block_name"))
        if code and code != ws.cell(r, col["code"]).value:
            new["code"] = code
        # compare with current row
        from .alignment import parse_station
        try:
            old_sta = parse_station(ws.cell(r, col["station"]).value)
            old_off = abs(float(ws.cell(r, col["offset"]).value))
        except (TypeError, ValueError):
            old_sta, old_off = None, None
        moved = (old_sta is None or abs(old_sta - al.display_station(so.station)) > POS_TOL
                 or abs(old_off - abs(so.offset)) > POS_TOL
                 or str(ws.cell(r, col["side"]).value).upper()[:1] != new["side"])
        for k, v in new.items():
            if k in ("station", "offset", "side") and not moved:
                continue
            cur = ws.cell(r, col[k]).value
            if k == "skew":
                if abs(float(cur or 0) - float(v)) < ROT_TOL:
                    continue
            elif str(cur if cur is not None else "").strip() == str(v):
                continue
            changes.append(Change(r, u, k, "" if cur is None else str(cur), str(v)))
            if apply:
                ws.cell(r, col[k], v)
    for u, r in rows.items():
        if u not in seen:
            notes.append(f"Row {r}: sign {u[:8]} ({ws.cell(r, col['code']).value}) "
                         f"not found in the drawing (deleted in Civil 3D, or not yet placed)")
    if apply and changes:
        shutil.copyfile(signlist_path, signlist_path + ".bak")
        wb.save(signlist_path)
    return changes, notes
