"""Long descents: descending lanes, brake check areas and truck escape ramps (RDM 1.3 6.6.4, 12.5, 12.7).

Everything here is read from the design profile and the horizontal alignment, per direction of travel
(Kenya drives on the left, so the traffic using the left of the chainage direction travels with it):

* descents  - continuous downgrades steeper than 3 % for the traffic concerned, short easier stretches
  bridged, with their length, vertical drop and grades;
* descending lanes (6.6.4) - where the opposite traffic's upgrade warrants a climbing lane and the grade is
  longer than 1000 m, the downhill side is a candidate for a descending lane;
* brake check areas (12.5) - before long, steep downgrades on routes with heavy truck volumes (about 500 per
  day): a lay-by with tapers at the top of the descent;
* runaway speed - a heavy vehicle whose brakes have failed, from a low-gear speed at the top, gaining speed
  from gravity less rolling resistance; capped at RUNAWAY_CAP (the RDM 12.7.3 example enters at 140 km/h);
* escape ramp sites (12.7) - on a tangent, after a vertical drop of 130 m, in advance of a singular point the
  runaway truck cannot pass safely: a curve whose safe speed is below its speed, a town (a design speed of
  50 km/h or less) or the end of the road;
* ramp length (Equation 12.1): L = V^2 / (254 (R + G) / 100), R the rolling resistance of the bed as an
  equivalent grade (Table 12.7) and G the ramp grade (negative descending).

The thresholds marked "indicative" are not RDM numbers: RDM gives the warrants in words; they are open
here so the designer can change them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

G = 9.81
STEEP = 3.0                 # %: a grade steeper than this counts as descending (as Table 6.6's 'no limit')
BRIDGE = 150.0              # m: easier stretches shorter than this do not end a descent (indicative)
LANE_GRADE_LENGTH = 1000.0  # m: RDM 1.3 6.6.4
DROP_RAMP = 130.0           # m: RDM 1.3 12.7.1, a ramp after a vertical gap of 130 m
BCA_DROP = 100.0            # m: brake check area before a descent of this drop ... (indicative)
BCA_GRADE = 5.0             # %: ... or this mean grade over at least LANE_GRADE_LENGTH (indicative)
TRUCKS_BCA = 500.0          # trucks / day: RDM 1.3 12.5
RUNAWAY_START = 40.0        # km/h: low-gear speed at the top of the descent (indicative)
RUNAWAY_ROLLING = 0.01      # rolling resistance of a heavy vehicle on the road (indicative)
RUNAWAY_CAP = 140.0         # km/h: RDM 1.3 12.7.3 example
TRUCK_FRICTION = 0.10       # side friction a loaded truck can use on a curve (indicative; below cars')
TOWN_SPEED = 50.0           # km/h: a design speed at or below this marks a populated area
MIN_TANGENT = 60.0          # m: a ramp departs from a tangent at least this long (indicative)

# RDM 1.3 Table 12.7: rolling resistance of arrester bed materials as an equivalent grade (%)
MATERIALS: Dict[str, float] = {"Crushed aggregate, loose": 5.0, "Gravel, loose": 10.0, "Sand": 15.0,
                               "Pea gravel": 25.0}
RAMP_TYPES = ("Ascending grade", "Horizontal grade", "Descending grade", "Sand pile")


@dataclass
class Descent:
    side: str                 # traffic side: "L" travels with the chainage, "R" against it
    start: float              # internal station where the descent begins (top), in travel order
    end: float                # ... and ends (bottom)
    length: float             # m along the road
    drop: float               # m vertical
    mean_grade: float         # % (positive = downhill for this traffic)
    max_grade: float
    profile: List[Tuple[float, float]] = field(default_factory=list)   # (station, travel grade %) samples

    @property
    def direction(self) -> int:
        return 1 if self.side == "L" else -1


def _travel_grades(al, step):
    pr = getattr(al, "profile", None)
    if pr is None or not pr.pvis:
        return []
    lo, hi = max(al.sta_start, pr.start), min(al.sta_end, pr.end)
    if hi - lo < step:
        return []
    n = max(1, int((hi - lo) / step))
    return [lo + (hi - lo) * k / n for k in range(n + 1)]


def descents(al, step: float = 5.0, steep: float = STEEP, bridge: float = BRIDGE) -> List[Descent]:
    """Continuous downgrades for each direction of travel (top to bottom), easier stretches shorter than
    `bridge` m bridged."""
    pr = getattr(al, "profile", None)
    ss = _travel_grades(al, step)
    if not ss:
        return []
    out = []
    for d, side in ((1, "L"), (-1, "R")):
        seq = ss if d > 0 else ss[::-1]
        runs, cur, easy = [], None, 0.0
        for a, b in zip(seq, seq[1:]):
            g = -(pr.grade((a + b) / 2) or 0.0) * d             # travel grade, + downhill
            if g > steep:
                if cur is None:
                    cur = {"start": a, "samples": []}
                cur["end"] = b
                cur["samples"].append((b, g))
                easy = 0.0
            elif cur is not None:
                easy += abs(b - a)
                cur["samples"].append((b, g))
                if easy >= bridge:
                    cur["samples"] = cur["samples"][:-int(round(easy / step))] or cur["samples"]
                    runs.append(cur)
                    cur, easy = None, 0.0
        if cur is not None:
            runs.append(cur)
        for r in runs:
            a, b = r["start"], r["end"]
            za, zb = pr.elevation(a), pr.elevation(b)
            if za is None or zb is None:
                continue
            L = abs(b - a)
            gs = [g for _, g in r["samples"]]
            out.append(Descent(side, a, b, L, za - zb, (za - zb) / L * 100.0 if L else 0.0, max(gs),
                               [(s, g) for s, g in r["samples"] if (s - a) * d <= L + 1e-6]))
    return sorted(out, key=lambda x: min(x.start, x.end))


# ------------------------------------------------------------------ descending lanes (6.6.4)
def descending_lanes(al, aadt: Optional[float] = None, merge: float = 200.0) -> List[dict]:
    """Where the opposite traffic's upgrade warrants a climbing lane and the grade is longer than 1000 m:
    a descending lane for the downhill traffic over the descent, ending `merge` m past its foot."""
    from .junctions import climbing_lanes
    climbs = climbing_lanes(al, aadt)
    out = []
    for ds in descents(al):
        if ds.length < LANE_GRADE_LENGTH:
            continue
        other = "R" if ds.side == "L" else "L"
        lo, hi = sorted((ds.start, ds.end))
        hit = [c for c in climbs if c["side"] == other and min(c["start"], c["end"]) < hi
               and max(c["start"], c["end"]) > lo]
        if not hit:
            continue
        d = ds.direction
        end = min(max(ds.end + d * merge, al.sta_start), al.sta_end)
        out.append({"start": round(ds.start / 10.0) * 10.0, "end": round(end / 10.0) * 10.0, "side": ds.side,
                    "grade": round(ds.mean_grade, 2), "length": round(ds.length, 1),
                    "note": f"opposite climb warrants a climbing lane; {ds.length:.0f} m at {ds.mean_grade:.1f} % "
                            "mean (RDM 1.3 6.6.4: candidate where the upgrade is over 1000 m)"})
    return out


# ------------------------------------------------------------------ runaway speed and curves
def runaway_speeds(al, ds: Descent, v0: float = RUNAWAY_START, rolling: float = RUNAWAY_ROLLING,
                   cap: float = RUNAWAY_CAP, step: float = 5.0) -> List[Tuple[float, float]]:
    """(station, km/h) down the descent for a truck whose brakes have failed at the top: v^2 grows by
    2 g (grade - rolling) per metre, never below v0, at most `cap`."""
    pr = al.profile
    d = ds.direction
    v2 = (v0 / 3.6) ** 2
    out = [(ds.start, v0)]
    s = ds.start
    stop = ds.end + d * 2000.0                      # follow it on past the foot (it slows on easier ground)
    stop = min(max(stop, al.sta_start), al.sta_end)
    while (stop - s) * d > step:
        n = s + d * step
        g = -(pr.grade((s + n) / 2) or 0.0) * d / 100.0
        v2 = max((v0 / 3.6) ** 2, v2 + 2 * G * (g - rolling) * step)
        v = min(math.sqrt(v2) * 3.6, cap)
        v2 = (v / 3.6) ** 2
        out.append((n, v))
        s = n
        if v <= v0 + 1e-6 and (s - ds.end) * d > 0:
            break
    return out


def _arc_spans(al):
    """[(start, end, radius)] of the circular arcs (internal stations)."""
    out, acc = [], al.sta_start
    for e in al.elements:
        if getattr(e, "kind", "") == "arc":
            out.append((acc, acc + e.length, e.radius))
        acc += e.length
    return out


def _tangents(al, min_len=MIN_TANGENT):
    out, acc = [], al.sta_start
    for e in al.elements:
        if getattr(e, "kind", "") == "line" and e.length >= min_len:
            out.append((acc, acc + e.length))
        acc += e.length
    return out


def truck_curve_speed(radius: float, e_pct: float, f: float = TRUCK_FRICTION) -> float:
    """km/h a loaded truck can hold on a curve: V^2 = 127 R (e + f), f below cars' (indicative)."""
    return math.sqrt(max(127.0 * radius * (e_pct / 100.0 + f), 0.0))


# ------------------------------------------------------------------ escape ramps (12.7)
def ramp_length(v_kmh: float, grade: float = 0.0, rolling: float = 10.0) -> Optional[float]:
    """Arrester bed length to stop from v_kmh (RDM 1.3 Equation 12.1): V^2 / (254 (R + G) / 100);
    grade in % (+ ascending), rolling resistance as an equivalent grade in % (Table 12.7)."""
    r = (rolling + grade) / 100.0
    if r <= 0:
        return None
    return v_kmh * v_kmh / (254.0 * r)


def _speed_at(speeds, s, d):
    best = None
    for st, v in speeds:
        if (st - s) * d <= 1e-6:
            best = v
    return best


def escape_ramp_sites(al, v0: float = RUNAWAY_START, ramp_grade: float = 10.0,
                      material: str = "Gravel, loose", width: float = 8.0) -> List[dict]:
    """Candidate escape ramp sites: per descent, the singular points a runaway truck reaches after a 130 m
    drop (a curve it cannot take, a town, the end of the road), each served by a ramp departing from the
    last suitable tangent before it."""
    from .autoplace import superelevation_at
    rolling = MATERIALS.get(material, 10.0)
    arcs, tangents = _arc_spans(al), _tangents(al)
    pr = al.profile
    out = []
    for ds in descents(al):
        if ds.drop < DROP_RAMP:
            continue
        d = ds.direction
        speeds = runaway_speeds(al, ds, v0)
        z0 = pr.elevation(ds.start)
        gap_at = None                                    # where the 130 m vertical gap is reached
        for st, _ in speeds:
            z = pr.elevation(st)
            if z is not None and z0 - z >= DROP_RAMP:
                gap_at = st
                break
        if gap_at is None:
            continue
        reach = speeds[-1][0]
        lo, hi = sorted((gap_at, reach))
        singular = []
        for a, b, R in arcs:
            first = a if d > 0 else b                   # where the truck meets the curve
            if not lo <= first <= hi:
                continue
            v = _speed_at(speeds, first, d)
            e = superelevation_at(al, a, b) or 0.0
            vc = truck_curve_speed(R, abs(e))
            if v is not None and vc < v:
                singular.append((first, f"curve R {R:.0f} m (a truck holds {vc:.0f} km/h; runaway {v:.0f} km/h)", v))
        town = None
        st = gap_at
        while (reach - st) * d > 0:
            vd = al.speed_at(st)
            if vd is not None and vd <= TOWN_SPEED:
                town = st
                break
            st += d * 10.0
        if town is not None:
            singular.append((town, f"populated area from the {al.speed_at(town):.0f} km/h design speed",
                             _speed_at(speeds, town, d)))
        end = al.sta_end if d > 0 else al.sta_start
        if lo - 1e-6 <= end <= hi + 10.0 or lo - 10.0 <= end <= hi + 1e-6:
            singular.append((end, "end of the road", _speed_at(speeds, end, d)))
        singular.sort(key=lambda t: t[0] * d)
        if not singular:
            continue
        sp_at, why, _v = singular[0]                     # the first one the truck meets
        site = None
        for a, b in tangents:
            if d > 0:
                seg = (max(a, gap_at), min(b, sp_at))
                if seg[1] - seg[0] >= MIN_TANGENT:
                    site = seg[1] - MIN_TANGENT / 2 if site is None or seg[1] > site else site
            else:
                seg = (max(a, sp_at), min(b, gap_at))
                if seg[1] - seg[0] >= MIN_TANGENT:
                    cand = seg[0] + MIN_TANGENT / 2
                    site = cand if site is None or cand < site else site
        if site is None:
            out.append({"side": ds.side, "station": None, "singular": sp_at, "reason": why,
                        "note": "no tangent of at least {:.0f} m between the 130 m drop and the {}".format(MIN_TANGENT, why)})
            continue
        v = min(_speed_at(speeds, site, d) or v0, RUNAWAY_CAP)
        lengths = {"Ascending grade": ramp_length(v, ramp_grade, rolling), "Horizontal grade": ramp_length(v, 0.0, rolling),
                   "Descending grade": ramp_length(v, -min(ramp_grade, rolling / 2), rolling),
                   "Sand pile": ramp_length(v, 0.0, MATERIALS["Sand"])}
        out.append({"side": ds.side, "station": round(site, 1), "singular": round(sp_at, 1), "reason": why,
                    "speed": round(v, 1), "drop": round(ds.drop, 1), "grade": round(ds.mean_grade, 2),
                    "lengths": {k: (round(x, 0) if x else None) for k, x in lengths.items()},
                    "material": material, "ramp_grade": ramp_grade, "width": width,
                    "note": f"runaway truck at {v:.0f} km/h; ramp before the {why}"})
    return out


# ------------------------------------------------------------------ brake check areas (12.5)
def brake_check_sites(al, trucks: Optional[float] = None, before: float = 100.0) -> List[dict]:
    """Brake check areas at the top of long, steep downgrades, on the downhill traffic's side, the bay
    ending `before` m ahead of the descent. Recommended at about 500 trucks / day (RDM 1.3 12.5)."""
    out = []
    for ds in descents(al):
        if not (ds.drop >= BCA_DROP or (ds.length >= LANE_GRADE_LENGTH and ds.mean_grade >= BCA_GRADE)):
            continue
        d = ds.direction
        bay_end = ds.start - d * before
        if not al.sta_start <= bay_end <= al.sta_end:
            continue
        note = ("recommended: about 500 trucks / day or more" if trucks is not None and trucks >= TRUCKS_BCA
                else "consider: truck volume under 500 / day" if trucks is not None else "truck volume not given")
        on_curve = any(a - 1 <= bay_end <= b + 1 for a, b, _ in _arc_spans(al))
        out.append({"side": ds.side, "end": round(bay_end, 1), "top": round(ds.start, 1), "drop": round(ds.drop, 1),
                    "length": round(ds.length, 1), "grade": round(ds.mean_grade, 2),
                    "note": note + ("; on a curve: move it to where visibility is good" if on_curve else "")})
    return out
