"""Run signs, markings, DXF and inventory over real LandXML files and check the marking invariants.

    python tools/sweep_landxml.py <folder or .xml> [...]

Project LandXMLs stay outside the repository; this only reads them."""
import sys, glob, time, os, tempfile, traceback
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from rfd.alignment import parse_landxml
from rfd.autoplace import AutoConfig, propose
from rfd.markings import MarkingConfig, propose_markings
from rfd.linear import LinearCatalogue, geometry, summarise, run_quantities
from rfd.catalogue import Catalogue
from tests.test_bootstrap import check_markings
from rfd.records import build_signlist
from rfd.dxf_out import write_dxf
from rfd.inventory import write_inventory
cat = LinearCatalogue.load(); sc = Catalogue.load()
files = []
for a in sys.argv[1:]:
    files += sorted(glob.glob(os.path.join(a, "*.xml"))) if os.path.isdir(a) else [a]
if not files:
    sys.exit(__doc__)
bad = 0
for f in files:
    t = time.time()
    try:
        als = parse_landxml(f)
    except Exception as e:
        print("PARSE FAIL", os.path.basename(f), e); bad += 1; continue
    print(f"\n== {os.path.basename(f)}: {len(als)} alignments, parse {time.time()-t:.1f}s")
    for al in als:
        if al.length < 200: continue
        info = f"  {al.name[:38]:38s} L={al.length:7.0f} prof={'y' if al.profile else 'n'} edges={'y' if al.edges else 'n'} v={[v for _, v in al.speeds][:3]}"
        try:
            for crit in ("kenya_rdm_2025", "aashto_2011"):
                props, fnd = propose(al, AutoConfig(criteria=crit))
            res = []
            for cls, off, studs in (("", 0, "auto"), ("A", 0, "auto"), ("C", 6.0, "all"), ("E", 3.0, "none")):
                runs, mf = propose_markings(al, MarkingConfig(road_class=cls, sight_offset=off, studs=studs))
                cfg = MarkingConfig(road_class=cls, sight_offset=off, studs=studs, carriageway=7.0 if not al.edges else None)
                runs, mf = propose_markings(al, cfg)
                check_markings(al, cfg, runs, mf, al.name)
                cls_m = sum(x.end - x.start for x in mf if x.kind == "marking_cls")
                res.append(f"{cls or 'spd'}/{off:g}: {len(runs)} runs, CLS {cls_m:.0f} m")
            runs, _ = propose_markings(al, MarkingConfig(sight_offset=6.0, studs="all"))
            with tempfile.TemporaryDirectory() as d:
                sl = build_signlist([], al, sc)
                write_dxf(os.path.join(d, "o.dxf"), sl, al, sc, linear=(runs, cat))
                write_inventory(os.path.join(d, "o.xlsx"), sl, sc, "t", linear=(runs, cat, al))
            from rfd.barriers import BarrierConfig, propose_barriers
            t1 = time.time()
            bruns, bf = propose_barriers(al, BarrierConfig(landxml=f))
            for r in bruns:
                assert al.sta_start - 1e-6 <= r.sta_start < r.sta_end <= al.sta_end + 1e-6 and r.length >= 30 - 1e-6
            for side in "LR":
                mine = sorted((r for r in bruns if r.side == side), key=lambda r: r.sta_start)
                assert all(b.sta_start - a.sta_end >= 80 - 1e-6 for a, b in zip(mine, mine[1:])), "barrier gap"
            notes = [x.text for x in bf if x.kind == "barrier_note"]
            res.append(f"barriers {len(bruns)} runs {sum(r.length for r in bruns):.0f} m ({time.time() - t1:.1f}s; {'; '.join(notes)[:90]})")
            noot = sum(x.end - x.start for x in fnd if x.kind == "no_overtaking")
            print(info, f"| signs {len(props)} (AASHTO), PSD no-overtaking {noot:.0f} m |", "; ".join(res))
        except Exception:
            bad += 1
            print(info, "FAILED"); traceback.print_exc()
print("\nfailures:", bad)
sys.exit(1 if bad else 0)
