"""Randomised synthetic roads through the whole core pipeline, checked against invariants.

Seeded, so a failure is reproducible: the seed is in the assertion message."""
import math
import random

import pytest

from rfd.alignment import Alignment, Arc, Line
from rfd.autoplace import AutoConfig, propose
from rfd.catalogue import Catalogue
from rfd.corridor import Edges
from rfd.linear import LinearCatalogue, geometry, run_quantities, summarise
from rfd.markings import MIN_CARRIAGEWAY, MarkingConfig, propose_markings
from rfd.profile import VerticalProfile

CENTRE = ("LM01", "LM02", "LM24", "LM28", "LM32")
LCAT = LinearCatalogue.load()
SCAT = Catalogue.load()


def random_road(seed):
    rng = random.Random(seed)
    els, p, h = [], (0.0, 0.0), rng.uniform(0, 2 * math.pi)
    for k in range(rng.randint(2, 7)):
        L = rng.uniform(150, 900)
        q = (p[0] + L * math.cos(h), p[1] + L * math.sin(h))
        els.append(Line(p, q)); p = q
        if rng.random() < 0.8:
            R = rng.choice([40, 80, 150, 300, 600, 1200])
            ccw = rng.random() < 0.5
            sgn = 1 if ccw else -1
            ce = (p[0] - sgn * R * math.sin(h), p[1] + sgn * R * math.cos(h))
            arc = Arc(p, ce, R, ccw, R * rng.uniform(0.2, 1.4))
            els.append(arc); p, h = arc.end_point, arc.end_heading
    sta0 = rng.choice([0.0, 0.0, 1250.0])
    length = sum(e.length for e in els)
    speeds = []
    if rng.random() < 0.85:
        s = sta0
        while s < sta0 + length:
            speeds.append((s, rng.choice([40.0, 50.0, 60.0, 80.0, 100.0, 110.0])))
            s += rng.uniform(600, 4000)
    al = Alignment("BOOT", els, sta0, [], speeds)
    if rng.random() < 0.85:                                   # design profile, sometimes shorter than the alignment
        s, z, pv = sta0, 1500.0, []
        end = sta0 + length * (1.0 if rng.random() < 0.8 else 0.9)
        while s < end:
            pv.append((s, z))
            d = rng.uniform(120, 500)
            z += d * rng.uniform(-0.09, 0.09); s += d
        pv.append((end, z))
        pvis = [(pv[0][0], pv[0][1], 0.0)]
        for i in range(1, len(pv) - 1):
            room = 2 * min(pv[i][0] - pv[i - 1][0], pv[i + 1][0] - pv[i][0]) * 0.45
            pvis.append((pv[i][0], pv[i][1], rng.uniform(0.2, 1.0) * room))
        pvis.append((pv[-1][0], pv[-1][1], 0.0))
        al.profile = VerticalProfile("FRL", pvis)
    if rng.random() < 0.7:                                    # corridor edges, with widening and maybe a gap
        etw = rng.choice([2.5, 3.0, 3.5, 3.65, 7.0])
        gap = (sta0 + length * 0.4, sta0 + length * 0.5) if rng.random() < 0.3 else None
        data = {}
        for side in "LR":
            pts = []
            s = sta0
            while s <= sta0 + length:
                if not (gap and gap[0] < s < gap[1]):
                    pts.append((s, etw + (1.5 if (int(s / 400) % 3 == 0 and side == "L") else 0.0)))
                s += 20.0
            data[("ETW", side)] = pts
            if rng.random() < 0.6:
                data[("EPS", side)] = [(x, o + 1.5) for x, o in pts]
        al.edges = Edges(data)
    return al, rng


def direction_lines(runs, state_codes):
    """Merged continuous lines for one direction from the centre runs."""
    segs = sorted((r.sta_start, r.sta_end) for r in runs if state_codes(r))
    out = []
    for a, b in segs:
        if out and a - out[-1][1] < 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def check_markings(al, cfg, runs, findings, tag=""):
    lo = max(al.sta_start, cfg.start if cfg.start is not None else al.sta_start)
    hi = min(al.sta_end, cfg.end if cfg.end is not None else al.sta_end)
    narrow = any(f"under {MIN_CARRIAGEWAY}" in f.text for f in findings)
    centre = sorted((r.sta_start, r.sta_end, r.code) for r in runs if r.code in CENTRE)
    for a, b in zip(centre, centre[1:]):
        assert a[1] <= b[0] + 1e-6, f"{tag} centre lines overlap {a} {b}"
        if not narrow:
            assert abs(a[1] - b[0]) < 1e-6, f"{tag} centre line gap {a} {b}"
    if centre and not narrow:
        assert abs(centre[0][0] - lo) < 1e-6 and abs(centre[-1][1] - hi) < 1e-6, f"{tag} centre line ends"
    if narrow:
        assert not any(c in ("LM01", "LM02", "LM28", "LM32") for _, _, c in centre), f"{tag} narrow road lines"
    span = hi - lo
    for name, pick in (("F", lambda r: r.code in ("LM32", "LM24") or (r.code == "LM28" and not r.flip)),
                       ("B", lambda r: r.code in ("LM32", "LM24") or (r.code == "LM28" and r.flip))):
        lines = direction_lines(runs, pick)
        for a, b in lines:
            assert b - a >= min(50.0, span) - 1e-6, f"{tag} {name} continuous line of {b - a:.1f} m"
    solid = direction_lines(runs, lambda r: r.code in ("LM24", "LM28", "LM32"))
    v_of = lambda s: al.speed_at(s) or 80.0
    for (a0, a1), (b0, b1) in zip(solid, solid[1:]):
        vis = (cfg.zone_merge_gap if cfg.basis == "psd"
               else cfg.crit.marking_visibility(v_of((a1 + b0) / 2), cfg.road_class)[0])
        assert b0 - a1 >= vis - 1e-6, f"{tag} broken element {b0 - a1:.0f} m shorter than {vis:.0f} m"
    if cfg.basis == "psd" and cfg.centre and not narrow:   # markings and no-overtaking signs agree exactly
        # (a narrow road has one continuous line for both directions, so only the union can agree)
        from rfd.autoplace import analyse
        fnd = [f for f in analyse(al, cfg.auto) if f.kind == "no_overtaking"]
        for d, pick in (("Forward", lambda r: r.code in ("LM32", "LM24") or (r.code == "LM28" and not r.flip)),
                        ("Backward", lambda r: r.code in ("LM32", "LM24") or (r.code == "LM28" and r.flip))):
            want = sorted((f.start, f.end) for f in fnd if f.direction == d)
            got = [tuple(x) for x in direction_lines(runs, pick)]
            merged = []
            for a, b in want:
                if merged and a - merged[-1][1] < 1.0:
                    merged[-1] = (merged[-1][0], b)
                else:
                    merged.append((a, b))
            assert len(got) == len(merged), f"{tag} {d} zones {got} != signs {merged}"
            for g, w in zip(got, merged):
                assert abs(g[0] - w[0]) < 1.0 and abs(g[1] - w[1]) < 1.0, f"{tag} {d} zone {g} != sign zone {w}"
    for r in runs:
        it = LCAT[r.code]
        assert lo - 1e-6 <= r.sta_start < r.sta_end <= hi + 1e-6, f"{tag} run outside range {r}"
        assert r.status == "proposed" and r.rule.startswith("marking") and r.reason
        q = run_quantities(r, it, al.speed_at((r.sta_start + r.sta_end) / 2))
        assert q["length"] > 0
        if it.is_marking:
            assert 0 < q["painted"] <= q["length"] * 2 + 1e-6 and q["area"] > 0
        if it.is_point_series:
            assert q["count"] == int(q["length"] / q["spacing"] + 1e-9) + 1
        if r.side == "C":
            parts = geometry(al, r)
            assert len(parts) == 1 and len(parts[0]) >= 2, f"{tag} centre geometry"
        if r.code == "RRS-CLS":
            assert any(a - 1e-6 <= r.sta_start and r.sta_end <= b + 1e-6 for a, b in solid), f"{tag} CLS studs off CLS"
    if cfg.studs == "none":
        assert not any(r.code.startswith("RRS") for r in runs)
    rows = summarise(runs, LCAT, al)
    total = sum(q for c, code, d, p, u, q in rows if u == "m" and code in CENTRE)
    if centre and not narrow:
        assert total == pytest.approx(span, abs=0.2 * len(centre) + 0.2), f"{tag} centre line total"


@pytest.mark.parametrize("seed", range(60))
def test_random_road(seed, tmp_path):
    al, rng = random_road(seed)
    tag = f"seed {seed}:"
    for crit in ("kenya_rdm_2025", "aashto_2011"):
        props, findings = propose(al, AutoConfig(criteria=crit))
        for p in props:
            assert al.sta_start - 1e-6 <= p.station <= al.sta_end + 1e-6, f"{tag} sign outside alignment {p}"
            assert p.code in SCAT.signs and p.side in "LR"
        for f in findings:
            assert f.start <= f.end
    for _ in range(3):
        cfg = MarkingConfig(road_class=rng.choice(["", "A", "B", "C", "D", "E", "UA", "UL"]),
                            studs=rng.choice(["auto", "none", "all", "no_overtaking"]),
                            sight_offset=rng.choice([0.0, 0.0, 3.0, 6.0, 12.0]),
                            carriageway=rng.choice([None, None, 5.0, 6.5, 7.0]),
                            criteria=rng.choice(["kenya_rdm_2025", "aashto_2011"]),
                            basis=rng.choice(["psd", "psd", "table_4_4"]), psd_reduced=rng.random() < 0.7)
        if rng.random() < 0.3:
            cfg.start = al.sta_start + al.length * 0.2
            cfg.end = al.sta_start + al.length * 0.7
        runs, mf = propose_markings(al, cfg)
        check_markings(al, cfg, runs, mf, tag)
        again, _ = propose_markings(al, cfg)
        assert [(r.code, r.sta_start, r.sta_end, r.side, r.flip) for r in runs] == \
               [(r.code, r.sta_start, r.sta_end, r.side, r.flip) for r in again], f"{tag} not repeatable"
    if seed % 6 == 0:                                         # exports
        import ezdxf
        from openpyxl import load_workbook
        from rfd.dxf_out import write_dxf
        from rfd.inventory import write_inventory
        from rfd.records import build_signlist
        from dataclasses import replace
        # as read back from the GeoPackage: stations to the millimetre, which can round past the end
        runs = [replace(r, sta_start=round(r.sta_start, 3), sta_end=round(r.sta_end, 3) + (0.0004 if r.sta_end >= al.sta_end - 1e-6 else 0))
                for r in runs]
        sl = build_signlist([], al, SCAT)
        dxf, xl = str(tmp_path / "o.dxf"), str(tmp_path / "o.xlsx")
        write_dxf(dxf, sl, al, SCAT, linear=(runs, LCAT))
        write_inventory(xl, sl, SCAT, "boot", linear=(runs, LCAT, al))
        doc = ezdxf.readfile(dxf)
        assert not doc.audit().errors
        n_lines = len(doc.modelspace().query('LWPOLYLINE[layer?"RSD-MARK-.*"]'))
        assert n_lines >= len([r for r in runs if r.side == "C" and LCAT[r.code].is_marking])
        if runs:
            assert load_workbook(xl)["Linear"].max_row == len(runs) + 1


def test_sliver_between_directions_is_absorbed():
    from rfd.markings import _segments
    segs = _segments(0, 1000, [[0, 50]], [[50.007, 105]])
    assert [(a, b, st) for a, b, st in segs] == [(0, 50, "F"), (50, 105, "B"), (105, 1000, "")]


@pytest.mark.parametrize("seed", range(40))
def test_random_barriers(seed):
    """Random fills along random roads: every warranted section is shielded with run-out, runs are long
    enough, no short gaps, everything inside the alignment, repeatable."""
    from rfd import barriers as B
    from rfd.criteria import get as get_crit
    from tests.test_barriers import build
    al, rng = random_road(seed)
    al.profile = VerticalProfile("flat", [(al.sta_start, 100, 0), (al.sta_end, 100, 0)])
    bumps = [(al.sta_start + rng.uniform(0, al.length), rng.uniform(20, 400), rng.uniform(0.5, 14),
              rng.choice([1.5, 2.0, 3.0, 3.5, 4.0, 6.0])) for _ in range(rng.randint(0, 6))]

    def prof(s):
        for c, w, h, n in bumps:
            if abs(s - c) <= w / 2:
                return h, n, rng.random() < 0.3
        return 0.4, 4.0, False
    build(al, prof, step=rng.choice([10.0, 20.0, 25.0]), surfaces=rng.random() < 0.8)
    crit = get_crit()
    cfg = B.BarrierConfig(include_judgement=rng.random() < 0.5, aadt=rng.choice([None, 5000, 20000]))
    runs, findings = B.propose_barriers(al, cfg)
    rows, _ = B.fills(al, cfg)
    tag = f"seed {seed}:"
    for side in "LR":
        mine = sorted((r for r in runs if r.side == side), key=lambda r: r.sta_start)
        for r in mine:
            assert al.sta_start - 1e-6 <= r.sta_start < r.sta_end <= al.sta_end + 1e-6, tag
            assert r.length >= min(30.0, al.length) - 1e-6, f"{tag} barrier {r.length:.1f} m"
            assert r.offset in (0.5, 0.75) and r.edge_ref == "ETW" and r.status == "proposed"
        for a, b in zip(mine, mine[1:]):
            assert b.sta_start - a.sta_end >= 80.0 - 1e-6, f"{tag} gap {b.sta_start - a.sta_end:.1f} m"
        want = {"required"} | ({"judgement"} if cfg.include_judgement else set())
        for f in rows:
            if f.side != side or crit.barrier_warrant(f.height, f.slope_n) not in want:
                continue
            curves = B.curve_extents(al)
            a0, z0 = B._to_tangent(f.station, curves, -1), B._to_tangent(f.station, curves, 1)
            ro_a = crit.barrier_runout(al.speed_at(f.station) or 80.0)     # at least the section's own speed
            ro_z = ro_a
            cover = [r for r in mine if r.sta_start - 1e-6 <= f.station <= r.sta_end + 1e-6]
            assert cover, f"{tag} warranted section {f.station:.0f} {side} not shielded"
            r = cover[0]
            assert (r.sta_start <= a0 - ro_a + 1e-6 or r.sta_start <= al.sta_start + 1e-6) and \
                   (r.sta_end >= z0 + ro_z - 1e-6 or r.sta_end >= al.sta_end - 1e-6), \
                f"{tag} section {f.station:.0f} lacks run-out"
    again, _ = B.propose_barriers(al, cfg)
    assert [(r.side, r.sta_start, r.sta_end) for r in runs] == [(r.side, r.sta_start, r.sta_end) for r in again]


@pytest.mark.parametrize("seed", range(30))
def test_random_features(seed):
    """Random traffic calming features on random roads: every item and sign stays on the road, the hump
    sits centred on its chainage, bar sets never overlap the hump or each other, one rule per feature."""
    from rfd.features import KINDS, FeatureConfig, design_feature
    al, rng = random_road(seed)
    for _ in range(8):
        kind = rng.choice(list(KINDS))
        sta = al.sta_start + rng.uniform(0, al.length)
        cfg = FeatureConfig(desired_speed=rng.choice([20, 25, 30, 42, 50, 60]), crossing_width=rng.choice([2, 3, 4, 5]),
                            bar_markings=rng.random() < 0.8, directions=rng.choice(["both", "forward", "backward"]),
                            road_class=rng.choice(["", "A", "C"]), carriageway=rng.choice([None, 6.0, 11.0]))
        d = design_feature(al, kind, sta, cfg)
        tag = f"seed {seed} {kind} at {sta:.0f}:"
        rules = {r.rule for r in d.runs} | {p.rule for p in d.signs}
        assert len(rules) <= 1, tag
        for r in d.runs:
            assert al.sta_start - 1e-6 <= r.sta_start < r.sta_end <= al.sta_end + 1e-6, tag
            assert r.side == "C" and r.width and r.width > 0 and r.status == "proposed" and r.reason, tag
            assert LCAT[r.code].transverse, tag
        for p in d.signs:
            assert al.sta_start - 1e-6 <= p.station <= al.sta_end + 1e-6, tag
            assert (p.side, p.facing) in (("L", "Forward"), ("R", "Backward")) and p.code in SCAT.signs, tag
            assert (p.station < sta) == (p.facing == "Forward"), tag
        main = [r for r in d.runs if r.code in ("HUMP-C", "HUMP-T", "TABLE", "TABLE-X", "BUMP")]
        if main and main[0].sta_start > al.sta_start and main[0].sta_end < al.sta_end:
            assert (main[0].sta_start + main[0].sta_end) / 2 == pytest.approx(sta), tag
        bars = sorted((r for r in d.runs if r.code == "BAR-SET"), key=lambda r: r.sta_start)
        for a, b in zip(bars, bars[1:]):
            assert b.sta_start >= a.sta_end - 1e-6, f"{tag} bar sets overlap"
        for b in bars:
            for m in main:
                assert b.sta_end <= m.sta_start + 1e-6 or b.sta_start >= m.sta_end - 1e-6, f"{tag} bars on the hump"
        if kind == "speed_bump" and (al.speed_at(sta) or 80) >= 50:
            assert not d.runs and any(f.kind == "feature_error" for f in d.findings), tag
