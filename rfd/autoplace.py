"""Automatic sign proposals from the design geometry and RDM 6.2 criteria.

Every proposal records the rule and the numbers that triggered it, and is added as
a *proposed* sign for the engineer to accept, move or reject. Sources:

RDM 6.2 (2025)
  2.4   signs on the left; posts 0.6-3.0 m beyond the carriageway / paved shoulder edge;
        readable in 6 s (advance distance = 6 s of travel at the approach speed);
        minimum spacing 0.6 x V m between signs
  4.5   sharp turns / bends: "degree of danger depends on speed of approach, radius,
        superelevation, skid resistance and forward visibility"; W19-W22, W23 plate for series
  4.6.1 chevrons on the outside of the curve, spacing Table 4.2
  4.6.4 W30 where descent > 5 %; W31 where ascent > 10 %
  3.11  P32 both ends of the hazardous length, both directions, distance plate; END plate
RDM 1.3 (2025), through rfd.criteria (default file kenya_rdm_2025.json):
  Table 5.1 side friction; Tables 3.16 / 3.20 stopping and (reduced) passing sight distance;
  Table 3.13 eye 1.05 m, passing object 1.3 m; Tables 6.1 / 6.4 crest and sag K; 3.13.8 headlights
The previous AASHTO 2011 defaults remain available as criteria "aashto_2011".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import criteria as _crit

# RDM 6.2 Table 4.2: chevron spacing on curve / before curve by radius
CHEVRON = [(50, 15, 30), (100, 20, 40), (200, 30, 60), (300, 45, 90), (400, 60, 120),
           (500, 70, 140), (1e9, 80, 150)]


def interp(table, v):
    if v <= table[0][0]:
        return table[0][1]
    for (a, fa), (b, fb) in zip(table, table[1:]):
        if v <= b:
            return fa + (fb - fa) * (v - a) / (b - a)
    return table[-1][1]


def chevron_spacing(radius: float) -> Tuple[float, float]:
    for r, on, before in CHEVRON:
        if radius <= r:
            return on, before
    return CHEVRON[-1][1], CHEVRON[-1][2]


def advance_distance(kmh: float) -> float:
    """RDM 6.2 2.4: read and understood in 6 s -> 6 s of travel, rounded up to 10 m."""
    return math.ceil(kmh / 3.6 * 6.0 / 10.0) * 10.0


def curve_speed(radius: float, e_pct: float, crit=None) -> float:
    """Speed (km/h) at which R, e and f_max(V) balance: V^2 = 127 R (e + f) (RDM 1.3 Eq. 5.1, Table 5.1 f)."""
    crit = crit or _crit.get()
    v = 60.0
    for _ in range(40):
        v_new = math.sqrt(max(127.0 * radius * (e_pct / 100.0 + crit.f_max(v)), 0.0))
        if abs(v_new - v) < 0.01:
            break
        v = v_new
    return v


# --------------------------------------------------------------------------- config / output
@dataclass
class AutoConfig:
    curves: bool = True
    grades: bool = True
    no_overtaking: bool = True
    warn_margin: float = 10.0        # km/h: warn when curve speed is this far below the approach speed
    chevron_margin: float = 20.0     # km/h: chevrons as well
    sharp_margin: float = 30.0       # km/h: sharp turn (W19/W21) rather than bend (W20/W22)
    series_gap: float = 150.0        # m: warned curves closer than this are signed as a series
    default_e: float = 4.0           # %: superelevation where the LandXML has none
    descent_pct: float = 5.0         # RDM 4.6.4
    ascent_pct: float = 10.0         # RDM 4.6.4
    min_grade_length: float = 50.0   # m
    grade_merge_gap: float = 100.0   # m
    zone_merge_gap: float = 100.0    # m (no-overtaking)
    min_zone_length: float = 60.0    # m
    clearance: float = 1.0           # m beyond the reference edge (RDM 2.4: 0.6-3.0 m)
    offset_no_edges: float = 5.5     # m from centreline when the LandXML has no corridor edges
    edge_ref: Optional[str] = None   # None -> preferred edge (EPS, then ETW)
    start: Optional[float] = None    # internal station range
    end: Optional[float] = None
    step: float = 5.0                # m sampling for grades / sight distance
    criteria: str = _crit.DEFAULT_ID # design criteria file (rfd/data/criteria)
    psd_reduced: bool = True         # RDM 1.3 Table 3.20: reduced passing sight distance in constrained cases
    sight_offset: float = 0.0        # m from centreline to the sight obstruction inside bends; 0 = profile only

    @property
    def crit(self):
        return _crit.get(self.criteria)


@dataclass
class Proposal:
    code: str
    station: float                  # internal station of the post
    side: str                       # L / R
    facing: str                     # Forward / Backward
    rule: str
    reason: str
    mirror: bool = False
    legend: str = ""
    group: str = ""                 # proposals sharing a group key go on one post


@dataclass
class Finding:
    kind: str                       # curve / grade / no_overtaking / sag_headlight / crest_ssd
    start: float
    end: float
    direction: str                  # Forward / Backward / Both
    text: str
    values: Dict = field(default_factory=dict)


# --------------------------------------------------------------------------- geometry analysis
@dataclass
class CurveGroup:
    start: float
    end: float
    arc_start: float
    arc_end: float
    radius: float
    left: bool                      # turns left for forward traffic
    deflection: float               # degrees
    e_pct: float
    v_curve: float
    v_approach: float


def superelevation_at(al, s0, s1) -> Optional[float]:
    best = None
    for a, b, e in getattr(al, "superelevation", []) or []:
        if a <= s1 and b >= s0:
            best = max(best or 0.0, abs(e))
    return best


def curve_groups(al, cfg: AutoConfig) -> List[CurveGroup]:
    out = []
    els = al.elements
    starts = []
    acc = al.sta_start
    for e in els:
        starts.append(acc)
        acc += e.length
    for i, e in enumerate(els):
        if e.kind != "arc":
            continue
        s0, s1 = starts[i], starts[i] + e.length
        g0, g1 = s0, s1
        if i > 0 and els[i - 1].kind == "spiral":
            g0 = starts[i - 1]
        if i + 1 < len(els) and els[i + 1].kind == "spiral":
            g1 = starts[i + 1] + els[i + 1].length
        h0 = al.point_at(g0)[2]
        h1 = al.point_at(min(g1, al.sta_end))[2]
        defl = abs(math.degrees(math.remainder(h1 - h0, 2 * math.pi)))
        e_pct = superelevation_at(al, s0, s1)
        if e_pct is None:
            e_pct = cfg.default_e
        mid = (s0 + s1) / 2
        v_app = al.speed_at(mid) or al.speed_at(g0) or 0.0
        out.append(CurveGroup(g0, g1, s0, s1, e.radius, e.ccw, defl, e_pct,
                              curve_speed(e.radius, e_pct, cfg.crit), v_app))
    return out


def _runs(stations, flags, merge_gap, min_len, step):
    """Contiguous runs of True flags -> [(start, end)], merged across small gaps."""
    runs, cur = [], None
    for s, f in zip(stations, flags):
        if f:
            cur = [s, s] if cur is None else [cur[0], s]
        elif cur is not None:
            runs.append(cur); cur = None
    if cur is not None:
        runs.append(cur)
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a + step >= min_len]


def _stations(al, cfg):
    a = max(al.sta_start, cfg.start if cfg.start is not None else al.sta_start)
    b = min(al.sta_end, cfg.end if cfg.end is not None else al.sta_end)
    if al.profile is not None:
        a, b = max(a, al.profile.start), min(b, al.profile.end)
    n = max(1, int((b - a) / cfg.step))
    return [a + (b - a) * k / n for k in range(n + 1)]


def sight_profile(profile, stations):
    return [profile.elevation(x) for x in stations]


def sight_distances(stations, z, direction, h_eye, h_obj, max_d):
    """Vertical sight distance at every sampled station (running max-slope scan).

    The target at distance d is visible when its sight-line slope is at least the
    steepest slope from the eye to any road point in between."""
    n = len(stations)
    out = []
    rng = range(n) if direction > 0 else range(n - 1, -1, -1)
    for i in rng:
        if z[i] is None:
            out.append(max_d); continue
        eye = z[i] + h_eye
        steepest = -1e9
        seen = max_d
        j = i + direction
        while 0 <= j < n:
            d = abs(stations[j] - stations[i])
            if d > max_d or z[j] is None:
                break
            m_target = (z[j] + h_obj - eye) / d
            if m_target < steepest:
                seen = d
                break
            steepest = max(steepest, (z[j] - eye) / d)
            j += direction
        out.append(seen)
    return out if direction > 0 else out[::-1]


def horizontal_sight(pts, stations, direction, offset, max_d):
    """Sight distance round bends: the chord from the eye may not pass more than
    ``offset`` m inside the centreline (checked at its quarter points)."""
    n = len(stations)
    out = []
    for i in range(n):
        seen = max_d
        j = i + 2 * direction
        xi, yi = pts[i]
        while 0 <= j < n:
            d = abs(stations[j] - stations[i])
            if d > max_d:
                break
            xj, yj = pts[j]
            L = math.hypot(xj - xi, yj - yi) or 1e-9
            blocked = False
            for q in (0.25, 0.5, 0.75):
                k = i + int(round((j - i) * q))
                xk, yk = pts[k]
                if abs((xj - xi) * (yk - yi) - (yj - yi) * (xk - xi)) / L > offset:
                    blocked = True
                    break
            if blocked:
                seen = d
                break
            j += direction
        out.append(seen)
    return out


def no_overtaking_zones(al, cfg: AutoConfig):
    """{'Forward': [(start, end)], 'Backward': [...]}: where the passing sight distance is not available.

    The one source for both the no-overtaking signs and the continuous centre line, so they
    always agree. Sight distance is scanned along the design profile (eye to the passing
    target height of the criteria) and, when ``sight_offset`` is set, round bends. Zones of
    one direction closer than ``zone_merge_gap`` are merged; a gap shorter than that between
    zones of opposite directions is closed by extending both to its middle, so no short
    overtaking length is left between two prohibitions."""
    pr = al.profile
    if pr is None and cfg.sight_offset <= 0:
        return {"Forward": [], "Backward": []}
    st = _stations(al, cfg)
    if len(st) < 2:
        return {"Forward": [], "Backward": []}
    crit = cfg.crit
    v_of = lambda s: al.speed_at(s) or 80.0
    psd_of = lambda s: crit.psd(v_of(s), cfg.psd_reduced)
    max_need = max(psd_of(s) for s in st) + cfg.step
    z = sight_profile(pr, st) if pr is not None else None
    pts = [al.point_at(s)[:2] for s in st] if cfg.sight_offset > 0 else None
    zones = {}
    for direction, sign in (("Forward", 1), ("Backward", -1)):
        sd = (sight_distances(st, z, sign, crit.eye_height, crit.psd_object_height, max_need)
              if z is not None else [max_need] * len(st))
        if pts:
            sd = [min(a, b) for a, b in zip(sd, horizontal_sight(pts, st, sign, cfg.sight_offset, max_need))]
        flags = [d < psd_of(s) for s, d in zip(st, sd)]
        zones[direction] = [list(r) for r in _runs(st, flags, cfg.zone_merge_gap, cfg.min_zone_length, cfg.step)]
    # close short gaps between zones of opposite directions
    allz = sorted([(r, "Forward") for r in zones["Forward"]] + [(r, "Backward") for r in zones["Backward"]],
                  key=lambda t: t[0][0])
    reach = None                                  # zone reaching farthest so far
    for r, d in allz:
        if reach is not None and reach[0][1] < r[0] and r[0] - reach[0][1] <= cfg.zone_merge_gap and reach[1] != d:
            mid = (reach[0][1] + r[0]) / 2
            reach[0][1] = mid
            r[0] = mid
        if reach is None or r[1] > reach[0][1]:
            reach = (r, d)
    return {k: [tuple(r) for r in v] for k, v in zones.items()}


def analyse(al, cfg: AutoConfig) -> List[Finding]:
    """Geometry findings used for proposals and for the report."""
    out: List[Finding] = []
    if cfg.curves:
        for c in curve_groups(al, cfg):
            if cfg.start is not None and c.end < cfg.start or cfg.end is not None and c.start > cfg.end:
                continue
            drop = c.v_approach - c.v_curve
            if c.v_approach and drop >= cfg.warn_margin:
                out.append(Finding("curve", c.start, c.end, "Both",
                                   f"R={c.radius:.0f} m, e={c.e_pct:.1f}%: curve speed {c.v_curve:.0f} km/h "
                                   f"vs {c.v_approach:.0f} km/h design (drop {drop:.0f})",
                                   {"group": c, "drop": drop}))
    v_of = lambda s: al.speed_at(s) or 80.0
    crit = cfg.crit
    psd_of = lambda s: crit.psd(v_of(s), cfg.psd_reduced)
    if cfg.no_overtaking:
        for direction, zs in no_overtaking_zones(al, cfg).items():
            for a, b in zs:
                out.append(Finding("no_overtaking", a, b, direction,
                                   f"passing sight distance < {psd_of(a):.0f} m over {b - a:.0f} m "
                                   f"({crit.ref('psd')}{', reduced' if cfg.psd_reduced and crit.is_kenya else ''})",
                                   {"psd": psd_of(a)}))
    if al.profile is None:
        return out
    st = _stations(al, cfg)
    pr = al.profile
    if cfg.grades:
        g = [pr.grade(s) or 0.0 for s in st]
        for direction, sign in (("Forward", 1.0), ("Backward", -1.0)):
            for label, thr, test in (("descent", cfg.descent_pct, lambda x: x < -cfg.descent_pct),
                                     ("ascent", cfg.ascent_pct, lambda x: x > cfg.ascent_pct)):
                runs = _runs(st, [test(sign * x) for x in g], cfg.grade_merge_gap, cfg.min_grade_length, cfg.step)
                for a, b in runs:
                    worst = max(abs(x) for s, x in zip(st, g) if a <= s <= b)
                    out.append(Finding(f"grade_{label}", a, b, direction,
                                       f"{label} steeper than {thr:.0f}% for {b - a:.0f} m (max {worst:.1f}%)",
                                       {"max": worst}))
    v_of = lambda s: al.speed_at(s) or 80.0
    crit = cfg.crit
    psd_of = lambda s: crit.psd(v_of(s), cfg.psd_reduced)
    # report-only checks on the vertical curves: K against the criteria tables where given
    # (RDM 1.3 Tables 6.1 / 6.4), else from the SSD with the headlight / eye-object formulas
    h_eye, h_obj = crit.eye_height, crit.object_height
    hl_h, hl_a = crit.headlight
    for c in pr.curves:
        if cfg.start is not None and c.end < cfg.start or cfg.end is not None and c.start > cfg.end:
            continue
        v = v_of(c.pvi_station)
        S = crit.ssd(v)
        A = abs(c.a)
        if A < 1e-6:
            continue
        if c.kind == "sag":
            k_req = crit.k_sag(v)
            src = crit.ref("k_sag")
            if k_req is None:
                den = 200.0 * (hl_h + S * math.tan(math.radians(hl_a)))
                k_req = S * S / den
                if S > k_req * A:
                    k_req = max(2 * S - den / A, 0.0) / A
                src = crit.ref("headlight")
            if c.k is not None and c.k < k_req:
                out.append(Finding("sag_headlight", c.start, c.end, "Both",
                                   f"sag K={c.k:.1f} < {k_req:.1f} ({src}; {S:.0f} m stopping sight distance "
                                   f"at {v:.0f} km/h)", {"k": c.k, "k_req": k_req}))
        else:
            k_req = crit.k_crest(v)
            src = crit.ref("k_crest")
            if k_req is None:
                den = 200.0 * (math.sqrt(h_eye) + math.sqrt(h_obj)) ** 2
                k_req = S * S / den
                if S > k_req * A:
                    k_req = max(2 * S - den / A, 0.0) / A
                src = crit.ref("ssd")
            if c.k is not None and c.k < k_req:
                out.append(Finding("crest_ssd", c.start, c.end, "Both",
                                   f"crest K={c.k:.1f} < {k_req:.1f} ({src}; {S:.0f} m stopping sight distance "
                                   f"at {v:.0f} km/h)", {"k": c.k, "k_req": k_req}))
    return out


# --------------------------------------------------------------------------- proposals
# Manual orientation of the bend symbols (as drawn in RDM 6.2): W19/W20 turn right;
# W21/W22 begin to the right; W24 chevrons point left.
def _bend_mirror(turns_left: bool) -> bool:
    return turns_left


def propose(al, cfg: AutoConfig) -> Tuple[List[Proposal], List[Finding]]:
    findings = analyse(al, cfg)
    props: List[Proposal] = []
    in_range = lambda s: al.sta_start <= s <= al.sta_end

    # ---- curves: warnings (single or series), chevrons
    curves = [f for f in findings if f.kind == "curve"]
    series, cur = [], []
    for f in curves:
        if cur and f.start - cur[-1].end > cfg.series_gap:
            series.append(cur); cur = []
        cur.append(f)
    if cur:
        series.append(cur)
    for n, grp in enumerate(series):
        first, last = grp[0].values["group"], grp[-1].values["group"]
        sharp = any(f.values["drop"] >= cfg.sharp_margin for f in grp)
        v = first.v_approach or 80.0
        d = advance_distance(v)
        if len(grp) == 1:
            code = "W19" if sharp else "W20"
            why = grp[0].text
            plate = ""
        else:
            code = "W21" if sharp else "W22"
            why = f"{len(grp)} curves within {cfg.series_gap:.0f} m of each other; " + "; ".join(f.text for f in grp)
            length = last.end - first.start
            plate = f"FOR {int(math.ceil(length / 50.0) * 50)} M" if length < 1000 else f"FOR {length / 1000:.0f} KM"
        # forward traffic meets `first`, turning first.left; backward traffic meets `last`, turning the other way
        fwd_s, bwd_s = first.start - d, last.end + d
        if in_range(fwd_s):
            props.append(Proposal(code, fwd_s, "L", "Forward", "curve", why, _bend_mirror(first.left),
                                  group=f"cv{n}f"))
            if plate:
                props.append(Proposal("W23", fwd_s, "L", "Forward", "curve", "distance plate for the series",
                                      legend=plate, group=f"cv{n}f"))
        if in_range(bwd_s):
            props.append(Proposal(code, bwd_s, "R", "Backward", "curve", why, _bend_mirror(not last.left),
                                  group=f"cv{n}b"))
            if plate:
                props.append(Proposal("W23", bwd_s, "R", "Backward", "curve", "distance plate for the series",
                                      legend=plate, group=f"cv{n}b"))
        for f in grp:
            c = f.values["group"]
            if f.values["drop"] < cfg.chevron_margin:
                continue
            on, _before = chevron_spacing(c.radius)
            outside = "R" if c.left else "L"
            s, k = c.arc_start, 0
            while s <= c.arc_end + 1e-6:
                key = f"ch{n}_{c.arc_start:.0f}_{k}"
                why = (f"chevron on the outside of R={c.radius:.0f} m (RDM Table 4.2: {on:.0f} m on curve); "
                       f"curve speed {c.v_curve:.0f} vs {c.v_approach:.0f} km/h")
                # chevrons point the way the road turns: manual W24-a points left
                props.append(Proposal("W24-a", s, outside, "Forward", "curve", why, mirror=not c.left, group=key))
                props.append(Proposal("W24-a", s, outside, "Backward", "curve", why, mirror=c.left, group=key))
                s += on; k += 1

    # ---- steep grades (RDM 4.6.4)
    for f in findings:
        if not f.kind.startswith("grade_"):
            continue
        code = "W30" if f.kind == "grade_descent" else "W31"
        v = al.speed_at(f.start) or 80.0
        d = advance_distance(v)
        legend = f"{math.ceil(f.values['max'])}%"
        if f.direction == "Forward" and in_range(f.start - d):
            props.append(Proposal(code, f.start - d, "L", "Forward", "grade", f.text, legend=legend))
        elif f.direction == "Backward" and in_range(f.end + d):
            props.append(Proposal(code, f.end + d, "R", "Backward", "grade", f.text, legend=legend))

    # ---- no overtaking (RDM 3.11): both ends, distance plate, END
    for i, f in enumerate(x for x in findings if x.kind == "no_overtaking"):
        length = f.end - f.start
        plate = f"FOR {int(math.ceil(length / 50.0) * 50)} M" if length < 1000 else f"FOR {round(length / 1000):.0f} KM"
        if f.direction == "Forward":
            a, b, side = f.start, f.end, "L"
        else:
            a, b, side = f.end, f.start, "R"
        if in_range(a):
            props.append(Proposal("P32", a, side, f.direction, "no_overtaking", f.text, group=f"no{i}s"))
            props.append(Proposal("W23", a, side, f.direction, "no_overtaking", "distance plate",
                                  legend=plate, group=f"no{i}s"))
        if in_range(b):
            props.append(Proposal("P32", b, side, f.direction, "no_overtaking", "end of restriction",
                                  legend="END", group=f"no{i}e"))
    return props, findings


def space_out(props: List[Proposal], existing: List[Tuple[float, str, str]], speed_at) -> List[Proposal]:
    """RDM 2.4 minimum spacing 0.6 V between signs (same side, same direction).

    A proposal that crowds an existing sign of the same code is dropped (already signed);
    one that crowds another sign is moved back, away from the hazard, up to 3 times.
    Chevrons and plates sharing a post are left alone (they have their own spacing).
    """
    taken = list(existing)    # (station, side, facing, code)
    out = []
    for p in sorted(props, key=lambda p: p.station):
        if p.code.startswith("W24") or p.code == "W23":
            out.append(p)
            continue
        gap = 0.6 * (speed_at(p.station) or 80.0)
        if any(c == p.code and sd == p.side and fc == p.facing and abs(s - p.station) < gap
               for s, sd, fc, c in taken):
            continue
        back = -1.0 if p.facing == "Forward" else 1.0
        for _ in range(3):
            clash = [s for s, sd, fc, c in taken if sd == p.side and fc == p.facing and abs(s - p.station) < gap]
            if not clash:
                break
            p.station += back * gap
            p.reason += f" (moved {gap:.0f} m for RDM 0.6V spacing)"
        taken.append((p.station, p.side, p.facing, p.code))
        out.append(p)
    return out
