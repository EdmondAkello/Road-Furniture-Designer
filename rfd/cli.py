"""Command line entry point.

  python -m rsd template  SignList.xlsx  --alignment "DEMO-RD"
  python -m rsd build     SignList.xlsx  road.xml  --out outputs/  [--alignment NAME]
  python -m rsd library   RSD_SignBlocks.dxf
  python -m rsd reconcile SignList.xlsx readback.json road.xml  [--dry-run]
  python -m rsd readback-dxf placed.dxf readback.json
"""
from __future__ import annotations

import argparse
import os
import sys

from .alignment import parse_landxml
from .catalogue import Catalogue, DEFAULT_PATH
import json

from .dxf_out import readback_dxf, write_block_library, write_dxf
from .reconcile import reconcile
from .package import build_package, write_package
from .inventory import write_inventory
from .signlist import make_template, read_signlist


def _pick(als, name):
    if name:
        for a in als:
            if a.name == name:
                return a
        raise SystemExit(f"Alignment '{name}' not found. Available: {', '.join(a.name for a in als)}")
    if len(als) != 1:
        raise SystemExit(f"LandXML has {len(als)} alignments; choose one with --alignment: "
                         f"{', '.join(a.name for a in als)}")
    return als[0]


def main(argv=None):
    p = argparse.ArgumentParser(prog="rfd", description="Road Furniture Designer core")
    p.add_argument("--catalogue", default=DEFAULT_PATH)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template"); t.add_argument("xlsx"); t.add_argument("--alignment", default="")
    t.add_argument("--project", default="")
    b = sub.add_parser("build"); b.add_argument("xlsx"); b.add_argument("landxml")
    b.add_argument("--out", default="rsd_out"); b.add_argument("--alignment", default="")
    b.add_argument("--project", default=""); b.add_argument("--plan-scale", type=float, default=2500.0,
                   help="drawing scale denominator: symbols print ~10 mm (25 m at the default 1:2500)")
    b.add_argument("--no-write-back", action="store_true")
    lb = sub.add_parser("library"); lb.add_argument("dxf")
    rc = sub.add_parser("reconcile"); rc.add_argument("xlsx"); rc.add_argument("readback")
    rc.add_argument("landxml"); rc.add_argument("--alignment", default="")
    rc.add_argument("--dry-run", action="store_true")
    rd = sub.add_parser("readback-dxf"); rd.add_argument("dxf"); rd.add_argument("json")
    a = p.parse_args(argv)
    cat = Catalogue.load(a.catalogue)

    if a.cmd == "template":
        make_template(a.xlsx, cat, a.alignment, a.project)
        print("Template written:", a.xlsx)
        return 0
    if a.cmd == "library":
        write_block_library(a.dxf, cat)
        print("Block library written:", a.dxf)
        return 0

    if a.cmd == "readback-dxf":
        data = readback_dxf(a.dxf)
        with open(a.json, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Read {len(data['signs'])} RSD sign block(s) -> {a.json}")
        return 0
    al = _pick(parse_landxml(a.landxml), a.alignment)
    if a.cmd == "reconcile":
        changes, notes = reconcile(a.xlsx, a.readback, al, cat, apply=not a.dry_run)
        for c in changes:
            print(f"  row {c.row:>4}  {c.field:8} {c.old!r:>14} -> {c.new!r}")
        for n in notes:
            print("  NOTE", n)
        verb = "would change" if a.dry_run else "updated"
        print(f"{len(changes)} field(s) {verb}; {len(notes)} note(s). Re-run `build` to refresh outputs.")
        return 0
    sl = read_signlist(a.xlsx, al, cat, write_back=not a.no_write_back)
    os.makedirs(a.out, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.xlsx))[0]
    write_inventory(os.path.join(a.out, f"{base}_Inventory.xlsx"), sl, cat, a.project,
                    csv_path=os.path.join(a.out, f"{base}_Inventory.csv"))
    errors = [i for i in sl.issues if i.level == "error"]
    for i in sl.issues:
        print(f"  row {i.row:>4}  {i.level.upper():7}  {i.message}")
    if errors:
        print(f"{len(errors)} error(s): placement package NOT written. Fix the sign list and re-run.")
        return 2
    from .alignment import landxml_crs
    crs = landxml_crs(a.landxml)
    write_package(os.path.join(a.out, f"{base}_placement.json"), build_package(sl, al, cat, a.project, crs))
    write_dxf(os.path.join(a.out, f"{base}_placed.dxf"), sl, al, cat, plan_scale=a.plan_scale, crs=crs,
              source=a.landxml, others=[o for o in parse_landxml(a.landxml) if o.name != al.name])
    print(f"OK: {len(sl.faces)} sign faces on {len(sl.installations)} posts -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
