"""Traffic calming and crossing features placed by the designer, detailed to RDM 6.4 / RDM 6.1.

Where a hump or a crossing goes is the designer's decision (settlements, schools,
crossing desire lines are not in the LandXML). Given the chainage, RFD works out
the standard detail and everything that comes with it:

  circular hump      Table 2.1: radius and chord for the desired speed (100 mm rise)
  trapezoidal hump   Table 2.2: ramp length and gradient; flat top 2.5 m minimum
  speed table        Figure 2.4: 1.7 + 5.0 + 1.7 m, 100 mm; optionally a raised crossing
  speed bump         2.4.2: only where the approach speed is under 50 km/h
  bar markings       2.7, Table 2.3: sets of 6 x 300 mm bars ahead of a hazard (or a hump)
  zebra crossing     RDM 6.1 9.2: BM01/BM02/BM03 for 2/3/4 m; refuge island over 10.5 m

Each feature brings its warning signs (W64 speed breaker, W55 pedestrian crossing)
on both approaches at the RDM 6.2 advance distance, its markings (hump markings
BM04, bar sets on the approaches) and checks: the feature is visible from the
stopping sight distance on the design profile, the bump speed limit, the crossing
width and refuge.

Everything a feature creates shares the rule "feature:<id>" so it can be accepted
or removed as one.

Not covered (left to the designer): bus bays and lay-bys, vulnerable-section
zigzag marking, stop lines and kerb details at crossings.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import criteria as _crit
from .autoplace import Finding, Proposal, advance_distance, sight_distances
from .linear import Run

KINDS = {
    "hump_circular": "Circular road hump",
    "hump_trapezoidal": "Trapezoidal road hump",
    "speed_table": "Speed table",
    "raised_crossing": "Raised pedestrian crossing (speed table)",
    "speed_bump": "Speed bump",
    "bar_marking": "Transverse bar markings ahead of a hazard",
    "crossing": "Pedestrian crossing (zebra)",
}
DEFAULT_WIDTH = 7.0


@dataclass
class FeatureConfig:
    criteria: str = _crit.DEFAULT_ID
    desired_speed: float = 30.0           # humps: crossing speed aimed for (Tables 2.1 / 2.2)
    crossing_width: float = 3.0           # m along the road (2-4 m)
    bar_markings: bool = True             # humps and speed tables: bar sets on the approaches (Table 2.3)
    signs: bool = True
    road_class: str = ""                  # A/B: yellow bars
    carriageway: Optional[float] = None   # m; None -> from the ETW edges
    edge_code: str = "ETW"
    directions: str = "both"              # bar markings: both | forward | backward
    refuge: float = 0.0                   # crossings: refuge / median width (m); 0 = one zebra across the road
    span: Optional[Tuple[float, float]] = None   # crossings: signed offsets kerb to kerb (+ right); None = ETW edges

    @property
    def crit(self):
        return _crit.get(self.criteria)

    def table(self, key):
        tc = self.crit.data.get("traffic_calming") or _crit.get(_crit.DEFAULT_ID).data["traffic_calming"]
        return tc[key]

    def ref(self, key):
        c = self.crit
        return c.refs.get(key) or _crit.get(_crit.DEFAULT_ID).ref(key)


@dataclass
class FeatureDesign:
    kind: str
    station: float
    group: str
    runs: List[Run] = field(default_factory=list)
    signs: List[Proposal] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""


def overlapping(a: float, b: float, blocks, margin: float = 0.0) -> List[str]:
    """What of blocks ((lo, hi, what) chainage ranges) the span a-b overlaps."""
    lo, hi = min(a, b), max(a, b)
    return [w for x0, x1, w in blocks if lo < max(x0, x1) + margin and hi > min(x0, x1) - margin]


def flag_overlaps(design: FeatureDesign, blocks) -> List[str]:
    """Note where the feature itself (hump, table, bump, zebra; not its bar sets) overlaps other furniture."""
    main = [r for r in design.runs if r.code not in ("BAR-SET",)]
    if not main:
        return []
    a, b = min(r.sta_start for r in main), max(r.sta_end for r in main)
    hits = overlapping(a, b, blocks)
    for w in hits:
        design.findings.append(Finding("feature_note", a, b, "Both", f"overlaps {w}: move one of them"))
    return hits


def omit_bars(design: FeatureDesign, blocks, margin: float = 1.0, display=None) -> int:
    """Drop the feature's approach bar sets that fall on another piece of furniture: blocks are
    (lo, hi, what) chainage ranges (a junction's islands and markings, a roundabout, a crossing, another
    hump). Each dropped set is reported as a note. Returns how many were dropped."""
    keep, n = [], 0
    for r in design.runs:
        hit = None
        if r.code == "BAR-SET":
            hit = next((w for lo, hi, w in blocks if r.sta_start < hi + margin and r.sta_end > lo - margin), None)
        if hit is None:
            keep.append(r)
            continue
        n += 1
        ch = display(r.sta_start) if display else f"{r.sta_start:.0f}"
        design.findings.append(Finding("feature_note", r.sta_start, r.sta_end, "Both",
                                       f"bar set at {ch} omitted: it falls on {hit}"))
    design.runs = keep
    return n


def _row(rows, speed):
    """Table row for the desired speed: the highest tabulated speed not above it (clamped)."""
    rows = sorted(rows, key=lambda r: r["speed"])
    pick = rows[0]
    for r in rows:
        if r["speed"] <= speed + 1e-9:
            pick = r
    return pick


def carriageway_width(al, cfg: FeatureConfig, sta: float) -> Tuple[float, str]:
    if cfg.carriageway:
        return cfg.carriageway, "given"
    e = getattr(al, "edges", None)
    if e:
        l, r = e.offset(cfg.edge_code, "L", sta), e.offset(cfg.edge_code, "R", sta)
        if l is not None and r is not None:
            return l + r, f"{cfg.edge_code} edges"
    return DEFAULT_WIDTH, "assumed"


def visible_from(al, sta, distance, direction, h_eye, h_obj) -> Optional[float]:
    """Sight distance on the design profile from the point ``distance`` before ``sta`` (None: no profile)."""
    pr = getattr(al, "profile", None)
    if pr is None:
        return None
    s0 = sta - direction * distance
    lo, hi = sorted((s0, sta))
    lo, hi = max(lo, al.sta_start, pr.start), min(hi, al.sta_end, pr.end)
    if hi - lo < 1.0:
        return None
    n = max(2, int((hi - lo) / 2.0) + 1)
    st = [lo + (hi - lo) * k / (n - 1) for k in range(n)]
    z = [pr.elevation(s) for s in st]
    sd = sight_distances(st, z, direction, h_eye, h_obj, distance + 5.0)
    return sd[0] if direction > 0 else sd[-1]


def design_feature(al, kind: str, station: float, cfg: FeatureConfig = None, group: str = None) -> FeatureDesign:
    cfg = cfg or FeatureConfig()
    if kind not in KINDS:
        raise ValueError(f"Unknown feature '{kind}'")
    if not (al.sta_start <= station <= al.sta_end):
        raise ValueError("The feature is beyond the alignment ends")
    gid = group or _uuid.uuid4().hex[:8]
    rule = f"feature:{gid}"
    out = FeatureDesign(kind, station, gid)
    crit = cfg.crit
    v = al.speed_at(station) or 80.0
    width, wsrc = carriageway_width(al, cfg, station)
    if wsrc == "assumed":
        out.findings.append(Finding("feature_note", station, station, "Both",
                                    f"no corridor edges: carriageway taken as {width:.1f} m wide"))

    def run(code, a, b, reason, **kw):
        a, b = max(a, al.sta_start), min(b, al.sta_end)
        if b - a > 1e-6:
            out.runs.append(Run(code, a, b, side="C", width=width, status="proposed", rule=rule, reason=reason, **kw))

    def bars_around(hazard_a, hazard_b, why):
        t = cfg.table("bar_marking")
        sets = next((s for s in t["sets"] if v <= s["max_speed"] + 1e-9), t["sets"][-1])
        if v > t["sets"][-1]["max_speed"]:
            out.findings.append(Finding("feature_note", station, station, "Both",
                                        f"approach speed {v:.0f} km/h is above Table 2.3 (100 km/h): "
                                        f"bar marking distances for 81-100 km/h used"))
        gap = t["gap_low"] if v <= t["gap_speed"] else t["gap_high"]
        foot = t["bars"] * t["bar_width"] + (t["bars"] - 1) * gap
        colour = "yellow" if cfg.road_class.upper() in t.get("yellow_classes", []) else "white"
        dirs = {"both": (1, -1), "forward": (1,), "backward": (-1,)}[cfg.directions]
        for d in sets["distances"]:
            for sg in dirs:
                edge = hazard_a if sg > 0 else hazard_b
                near = edge - sg * d
                a, b = sorted((near, near - sg * foot))
                if a < al.sta_start or b > al.sta_end:
                    out.findings.append(Finding("feature_note", station, station, "Both",
                                                f"bar set {d:.0f} m before the {why} is beyond the alignment end"))
                    continue
                run("BAR-SET", a, b, f"Bar set {d:.0f} m before the {why} ({cfg.ref('bar_marking')}; "
                                     f"{t['bars']} x {t['bar_width'] * 1000:.0f} mm at {gap * 1000:.0f} mm, {colour})")

    def warning_signs(code, a, b, what):
        if not cfg.signs:
            return
        d = advance_distance(v)
        for side, facing, sta, sg in (("L", "Forward", a - d, 1), ("R", "Backward", b + d, -1)):
            if not (al.sta_start <= sta <= al.sta_end):
                out.findings.append(Finding("feature_note", station, station, facing,
                                            f"{code} for {facing.lower()} traffic would fall beyond the alignment end"))
                continue
            out.signs.append(Proposal(code, sta, side, facing, rule,
                                      f"{what} {d:.0f} m ahead (RDM 6.2 advance distance at {v:.0f} km/h)"))

    def visibility(a, b, what):
        ssd = crit.ssd(v)
        for sg, name, edge in ((1, "forward", a), (-1, "backward", b)):
            seen = visible_from(al, edge, ssd, sg, crit.eye_height, crit.object_height)
            if seen is not None and seen < ssd - 1e-6:
                out.findings.append(Finding("feature_visibility", edge, edge, name.title(),
                                            f"{what} is not visible from the stopping sight distance ({ssd:.0f} m) "
                                            f"for {name} traffic: about {seen:.0f} m on the design profile "
                                            f"({crit.ref('ssd')})", {"ssd": ssd, "seen": seen}))

    if kind in ("hump_circular", "hump_trapezoidal", "speed_table", "raised_crossing", "speed_bump"):
        if kind == "hump_circular":
            t = cfg.table("circular_hump")
            r = _row(t["rows"], cfg.desired_speed)
            foot, what = r["chord"], "road hump"
            detail = (f"circular hump R {r['radius']} m, chord {r['chord']} m, rise {t['rise_mm']} mm for "
                      f"{r['speed']} km/h (buses about {r['bus_speed']} km/h; {cfg.ref('circular_hump')})")
            code = "HUMP-C"
        elif kind == "hump_trapezoidal":
            t = cfg.table("trapezoidal_hump")
            r = _row(t["rows"], cfg.desired_speed)
            foot, what = 2 * r["ramp"] + t["flat_min"], "road hump"
            detail = (f"trapezoidal hump, ramps {r['ramp']} m at {r['gradient_pct']}%, flat top {t['flat_min']} m, "
                      f"rise {t['rise_mm'][0]}-{t['rise_mm'][1]} mm for {r['speed']} km/h "
                      f"(buses about {r['bus_speed']} km/h; {cfg.ref('trapezoidal_hump')})")
            code = "HUMP-T"
        elif kind == "speed_bump":
            t = cfg.table("speed_bump")
            if v >= t["max_approach_speed"]:
                out.findings.append(Finding("feature_error", station, station, "Both",
                                            f"speed bumps are for approach speeds under {t['max_approach_speed']} km/h; "
                                            f"the design speed here is {v:.0f} km/h ({cfg.ref('speed_bump')}): "
                                            f"use a hump instead"))
                out.summary = "Speed bump not permitted at this speed"
                return out
            foot, what, code = t["width_min"], "speed bump", "BUMP"
            detail = f"speed bump {t['width_min']} m min., {t['rise_mm'][0]}-{t['rise_mm'][1]} mm ({cfg.ref('speed_bump')})"
        else:
            t = cfg.table("speed_table")
            foot = 2 * t["ramp"] + t["flat"]
            what = "raised crossing" if kind == "raised_crossing" else "speed table"
            detail = (f"{what} {t['ramp']} + {t['flat']} + {t['ramp']} m, {t['rise_mm']} mm "
                      f"({cfg.ref('speed_table')})")
            code = "TABLE-X" if kind == "raised_crossing" else "TABLE"
        a, b = station - foot / 2, station + foot / 2
        run(code, a, b, detail[0].upper() + detail[1:])
        if code != "BUMP":
            run("BM04", a, b, "Hump markings (RDM 6.4 Figure 2.1)")
        if kind == "raised_crossing":
            cw = min(cfg.crossing_width, cfg.table("speed_table")["flat"])
            crossing_marking(out, al, cfg, station, cw, width, rule)
            warning_signs("W55", a, b, "Pedestrian crossing")
        else:
            warning_signs("W64", a, b, what.title())
        if cfg.bar_markings and code != "BUMP":
            bars_around(a, b, what)
        visibility(a, b, what.title())
        out.summary = detail
    elif kind == "bar_marking":
        bars_around(station, station, "hazard")
        out.summary = f"Bar markings ahead of the hazard at {v:.0f} km/h ({cfg.ref('bar_marking')})"
    elif kind == "crossing":
        a, b = crossing_marking(out, al, cfg, station, cfg.crossing_width, width, rule)
        warning_signs("W55", a, b, "Pedestrian crossing")
        visibility(a, b, "Pedestrian crossing")
        lo, hi = crossing_span(al, cfg, station, width)
        legs, refuge = crossing_legs(lo, hi, cfg.refuge)
        out.summary = (f"Zebra crossing {cfg.crossing_width:g} m wide, {hi - lo:.1f} m across"
                       + (f" in two legs with a {refuge[1] - refuge[0]:.1f} m refuge" if refuge else "")
                       + f" ({cfg.ref('crossing')})")
    return out


def crossing_span(al, cfg, station, width):
    """(left, right) signed offsets of the crossing: the clicked kerbs, else the ETW edges, else the width
    either side of the centreline."""
    if cfg.span:
        lo, hi = sorted(cfg.span)
        return lo, hi
    e = getattr(al, "edges", None)
    if e and not cfg.carriageway:
        l, r = e.offset(cfg.edge_code, "L", station), e.offset(cfg.edge_code, "R", station)
        if l is not None and r is not None:
            return -l, r
    return -width / 2, width / 2


def crossing_legs(lo, hi, refuge):
    """Zebra legs and the refuge between them: the refuge sits on the centreline when the crossing spans it
    (a median), else in the middle of the crossing. Returns ([(lo, hi) per leg], (lo, hi) of the refuge or None)."""
    if refuge <= 0 or hi - lo <= refuge + 1.0:
        return [(lo, hi)], None
    mid = 0.0 if lo + refuge / 2 < 0 < hi - refuge / 2 else (lo + hi) / 2
    r0, r1 = mid - refuge / 2, mid + refuge / 2
    return [(lo, r0), (r1, hi)], (r0, r1)


def crossing_marking(out, al, cfg, station, cw, width, rule):
    t = cfg.table("crossing")
    if cw < t["width_min"] - 1e-9 or cw > t["width_max"] + 1e-9:
        out.findings.append(Finding("feature_note", station, station, "Both",
                                    f"crossing width {cw:g} m is outside {t['width_min']:g}-{t['width_max']:g} m "
                                    f"({cfg.ref('crossing')})"))
    key = str(int(round(min(max(cw, 2.0), 4.0))))
    code = t["codes"].get(key, "BM02")
    a, b = station - cw / 2, station + cw / 2
    lo, hi = crossing_span(al, cfg, station, width)
    legs, refuge = crossing_legs(lo, hi, cfg.refuge)
    a, b = max(a, al.sta_start), min(b, al.sta_end)
    for l0, l1 in legs:
        out.runs.append(Run(code, a, b, side="C", offset=(l0 + l1) / 2, width=l1 - l0, status="proposed", rule=rule,
                            reason=f"Zebra crossing {cw:g} m, {t['stripe'] * 1000:.0f} mm stripes, "
                                   f"{l1 - l0:.1f} m across ({cfg.ref('crossing')}); provide road studs"))
        if l1 - l0 > t["refuge_over"] + 1e-9:
            out.findings.append(Finding("feature_note", station, station, "Both",
                                        f"crossing length {l1 - l0:.1f} m is over {t['refuge_over']} m: provide a "
                                        f"refuge island at least {t['refuge_width']} m wide ({cfg.ref('crossing')})"))
    if refuge:
        r0, r1 = refuge
        out.runs.append(Run("REFUGE", max(a - 1.0, al.sta_start), min(b + 1.0, al.sta_end), side="C",
                            offset=(r0 + r1) / 2, width=r1 - r0, status="proposed", rule=rule,
                            reason=f"Pedestrian refuge {r1 - r0:.1f} m wide between the zebra legs "
                                   f"({cfg.ref('crossing')})"))
        if hi - lo <= t["refuge_over"] + 1e-9:
            w = " and ".join(f"{l1 - l0:.1f}" for l0, l1 in legs)
            out.findings.append(Finding("feature_note", station, station, "Both",
                                        f"refuge on a {hi - lo:.1f} m crossing, which needs none (only over "
                                        f"{t['refuge_over']} m): it narrows the lanes to {w} m; leave it out on a "
                                        f"single carriageway unless the road is widened for it ({cfg.ref('crossing')})"))
        if r1 - r0 < t["refuge_width"] - 1e-9:
            out.findings.append(Finding("feature_note", station, station, "Both",
                                        f"refuge {r1 - r0:.1f} m wide is under the {t['refuge_width']} m minimum "
                                        f"({cfg.ref('crossing')})"))
    return a, b
