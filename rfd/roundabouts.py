"""Roundabouts as a click-and-fit overlay (RDM 1.3 Chapter 10, RDM 6.1 Figures 7.14-7.16, RDM 6.2 4.4).

RFD does not design the roundabout: the designer gives the centre (on our road), the central island
and inscribed circle diameters and the arms. RFD draws the central island, the outer kerb of the
circulatory carriageway with entry and exit returns, kerbed splitter islands with hatched lead-ins, the
give way markings, and proposes the signs; then checks the sizes and the arms against RDM 1.3.

Geometry is built in a frame centred on the roundabout: each arm has an outward unit vector b (from the
centre along the arm) and n, its left normal (counter-clockwise). Kenya drives on the left: traffic enters
on the -n side of an arm (the left of a driver heading for the centre) and leaves on the +n side, and
circulates clockwise.
"""
import math
from typing import Dict, List, Optional, Sequence, Tuple

Pt = Tuple[float, float]

# RDM 1.3 Table 10.1: central island diameter -> (R1, R2, minimum ICD), for the 15.5 m articulated vehicle
TABLE_10_1 = {4: (3.0, 13.0, 28.0), 6: (4.0, 13.4, 28.8), 8: (5.0, 13.9, 29.8), 10: (6.0, 14.4, 30.8),
              12: (7.0, 15.0, 32.0), 14: (8.0, 15.6, 33.2), 16: (9.0, 16.3, 34.6), 18: (10.0, 17.0, 36.0)}
ICD_MAX = 100.0              # 10.5: a normal roundabout's ICD should not exceed 100 m
ISLAND_MIN = 4.0             # 10.1.2 / 10.5.2.1: central island at least 4 m in diameter
WIDTH_MIN, WIDTH_MAX = 6.5, 15.0   # 10.5.2: about 6.5 m single-lane minimum; not over 15 m
ARMS_MIN, ARMS_MAX, ARM_ANGLE_MIN = 3, 5, 60.0    # 10.4.3
COMPACT_ICD = (28.0, 36.0)   # 10.5: consider a compact roundabout
GIVE_WAY_TRIANGLE_BACK = 2.5  # RDM 6.1 Figure 7.14: BM07 2.5 m behind the TM07 line
LM24_LENGTH = 12.0           # RDM 6.1 Figure 7.14: 1.5 to 12 m (max 15 m)

DEFAULTS = {"island": 10.0, "icd": None, "apron": 0.0, "entry": 4.0, "exit": 4.5, "splitter": 3.0,
            "splitter_len": 15.0, "lead_in": 15.0, "flare": 25.0, "entry_r": 15.0, "exit_r": 20.0}


def min_icd(island: float) -> float:
    """Table 10.1 minimum ICD for a central island diameter (interpolated; beyond the table, the last row
    grown with the island)."""
    ks = sorted(TABLE_10_1)
    if island <= ks[0]:
        return TABLE_10_1[ks[0]][2]
    if island >= ks[-1]:
        return TABLE_10_1[ks[-1]][2] + (island - ks[-1])
    for a, b in zip(ks, ks[1:]):
        if a <= island <= b:
            t = (island - a) / (b - a)
            return TABLE_10_1[a][2] + t * (TABLE_10_1[b][2] - TABLE_10_1[a][2])
    return TABLE_10_1[ks[-1]][2]


def circle_crossings(al, cx: float, cy: float, r: float, step: float = 1.0) -> List[Tuple[float, float]]:
    """(station, bearing outward) where an alignment's centreline crosses a circle about (cx, cy)."""
    out = []
    s, prev = al.sta_start, None
    while s <= al.sta_end + 1e-9:
        x, y, _ = al.point_at(min(s, al.sta_end))
        d = math.hypot(x - cx, y - cy) - r
        if prev is not None and (prev[1] < 0) != (d < 0):
            a, b = prev[0], s
            for _ in range(40):                       # bisection on the crossing
                m = (a + b) / 2
                xm, ym, _ = al.point_at(m)
                dm = math.hypot(xm - cx, ym - cy) - r
                if (dm < 0) == (prev[1] < 0):
                    a = m
                else:
                    b = m
            sm = (a + b) / 2
            xm, ym, _ = al.point_at(sm)
            out.append((sm, math.atan2(ym - cy, xm - cx)))
        prev = (s, d)
        s += step
    return out


def _half_width(al, sta: float) -> float:
    e = getattr(al, "edges", None)
    if e:
        o = [e.offset("ETW", sd, sta) for sd in ("L", "R")]
        o = [abs(v) for v in o if v is not None]
        if o:
            return sum(o) / len(o)
    return 3.5


def auto_arms(al, cx: float, cy: float, r: float, others=()) -> List[dict]:
    """Arms where our road and the other alignments of the LandXML cross the inscribed circle."""
    arms = []
    for s, b in circle_crossings(al, cx, cy, r):
        arms.append({"bearing": b, "src": "ours", "half": _half_width(al, s), "station": s})
    for a in others:
        for s, b in circle_crossings(a, cx, cy, r, step=2.0):
            arms.append({"bearing": b, "src": f"alg:{a.name}", "half": _half_width(a, s)})
    return arms


def merge_arms(arms: List[dict], min_sep_deg: float = 15.0) -> List[dict]:
    """Sorted counter-clockwise; arms closer than min_sep_deg are taken as one (ours first)."""
    out = []
    for a in sorted(arms, key=lambda a: 0 if a["src"] == "ours" else 1):
        if all(abs(math.degrees(math.remainder(a["bearing"] - b["bearing"], 2 * math.pi))) >= min_sep_deg
               for b in out):
            out.append(a)
    return sorted(out, key=lambda a: a["bearing"] % (2 * math.pi))


def _fillet(O: Pt, rc: float, A: Pt, u: Pt, m: Pt, R: float):
    """Return (curb return) of radius R outside both the circle (centre O, radius rc) and the line A + t u,
    on the side of normal m. Returns (tangent point on the line, tangent point on the circle, arc points)."""
    # centre C = A + t u + R m with |C - O| = rc + R
    px, py = A[0] + R * m[0] - O[0], A[1] + R * m[1] - O[1]
    bq = 2 * (px * u[0] + py * u[1])
    cq = px * px + py * py - (rc + R) ** 2
    disc = bq * bq - 4 * cq
    if disc < 0:
        return None
    ts = sorted(((-bq - math.sqrt(disc)) / 2, (-bq + math.sqrt(disc)) / 2))
    t = ts[1] if ts[1] >= 0 else ts[0]
    C = (A[0] + t * u[0] + R * m[0], A[1] + t * u[1] + R * m[1])
    T1 = (A[0] + t * u[0], A[1] + t * u[1])
    d = math.hypot(C[0] - O[0], C[1] - O[1])
    T2 = (O[0] + rc * (C[0] - O[0]) / d, O[1] + rc * (C[1] - O[1]) / d)
    a0 = math.atan2(T1[1] - C[1], T1[0] - C[0])
    a1 = math.atan2(T2[1] - C[1], T2[0] - C[0])
    da = math.remainder(a1 - a0, 2 * math.pi)
    n = max(4, int(abs(da) * R / 1.0))
    arc = [(C[0] + R * math.cos(a0 + da * k / n), C[1] + R * math.sin(a0 + da * k / n)) for k in range(n + 1)]
    return T1, T2, arc


def _circle(O: Pt, r: float, a0: float = 0.0, a1: float = 2 * math.pi, step: float = 1.0) -> List[Pt]:
    n = max(8, int(abs(a1 - a0) * r / step))
    return [(O[0] + r * math.cos(a0 + (a1 - a0) * k / n), O[1] + r * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


def _area(poly: Sequence[Pt]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, list(poly[1:]) + [poly[0]]))) / 2


def _length(pts: Sequence[Pt], closed: bool = False) -> float:
    pp = list(pts) + ([pts[0]] if closed else [])
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pp, pp[1:]))


def build(O: Pt, arms: List[dict], P: dict):
    """Parts [(code, pts, closed)], quantities, arm details (for signs and checks)."""
    P = dict(DEFAULTS, **{k: v for k, v in P.items() if v is not None})
    island, apron = float(P["island"]), float(P["apron"])
    icd = float(P.get("icd") or min_icd(island))
    rc, ri = icd / 2, island / 2
    parts: List[Tuple[str, List[Pt], bool]] = []
    ring = _circle(O, ri)
    parts.append(("KERB", ring, True))                            # central island
    if apron > 0:
        parts.append(("APRON", _circle(O, ri + apron), True))   # mountable apron edge
    detail, mouths = [], []
    ws, we, wx = float(P["splitter"]), float(P["entry"]), float(P["exit"])
    for arm in arms:
        b = (math.cos(arm["bearing"]), math.sin(arm["bearing"]))
        n = (-b[1], b[0])
        h = float(arm.get("half") or 3.5)
        W = lambda s, o: (O[0] + s * b[0] + o * n[0], O[1] + s * b[1] + o * n[1])
        sf = rc + float(P["flare"])                                # end of the flare, back on the approach
        edges = {}
        for side, o_m, R in ((-1, -(ws / 2 + we), float(P["entry_r"])), (1, ws / 2 + wx, float(P["exit_r"]))):
            # edge from the mouth (at the circle) out to the approach half-width at the end of the flare
            A = W(rc, o_m)
            Bp = W(sf, side * h)
            L = math.hypot(Bp[0] - A[0], Bp[1] - A[1])
            u = ((Bp[0] - A[0]) / L, (Bp[1] - A[1]) / L)
            m = (side * n[0], side * n[1])                       # away from the arm's centreline
            f = _fillet(O, rc, A, u, m, R)
            if f is None:
                raise ValueError("A return radius does not fit this arm; reduce it or enlarge the ICD")
            T1, T2, arc = f
            parts.append(("RBEDGE", list(reversed(arc)) + [Bp], False))
            edges[side] = T2
        mouths.append((arm["bearing"], edges))
        # splitter island: kerbed, from 1 m off the circle to the nose, then the hatched lead-in
        s0, s1 = rc + 1.0, rc + float(P["splitter_len"])
        half0, nose = max(ws / 2 - 0.5, 0.5), 0.5
        k = [W(s0, -half0), W(s1, -nose)] + [W(s1 + nose * math.sin(t), nose * -math.cos(t))
                                            for t in [i * math.pi / 8 for i in range(1, 8)]] + [W(s1, nose), W(s0, half0)]
        parts.append(("KERB", k, True))
        s2 = s1 + float(P["lead_in"])
        lead = [W(s1, -nose), W(s2, 0.0), W(s1, nose)]
        parts.append(("HM14", lead + [lead[0]], False))
        for j in range(1, int(float(P["lead_in"]) / 2.0)):
            s = s1 + 2.0 * j
            w = nose * (1 - (s - s1) / float(P["lead_in"]))
            parts.append(("HM07", [W(s, -w), W(s - 0.8, w)], False))
        parts.append(("LM24", [W(s2, 0.0), W(s2 + LM24_LENGTH, 0.0)], False))
        # give way line across the entry lane and the exit line across the exit, on the circle
        on_circle = lambda o: W(math.sqrt(max(rc * rc - o * o, 0.0)), o)
        parts.append(("TM07", [on_circle(-ws / 2), on_circle(-(ws / 2 + we))], False))
        parts.append(("TM04", [on_circle(ws / 2), on_circle(ws / 2 + wx)], False))
        # BM07 triangle centred in the entry lane, apex towards the give way line
        oc, sb = -(ws / 2 + we / 2), math.sqrt(max(rc * rc - (ws / 2 + we / 2) ** 2, 0.0)) + GIVE_WAY_TRIANGLE_BACK
        parts.append(("BM07", [W(sb, oc), W(sb + 3.75, oc - 0.55), W(sb + 3.75, oc + 0.55)], True))
        detail.append({"bearing": arm["bearing"], "src": arm["src"], "station": arm.get("station"),
                       "give_way": W(sb - GIVE_WAY_TRIANGLE_BACK, -(ws / 2 + we + 1.5)),
                       "give_way_s": sb - GIVE_WAY_TRIANGLE_BACK, "nose": W(s2 + 1.0, 0.0),
                       "island_face": W(ri - 0.5 if ri > 1 else ri, 0.0)})
    # outer kerb of the circulatory carriageway between the arms (clockwise traffic; ccw geometry)
    ms = sorted(mouths, key=lambda m: m[0] % (2 * math.pi))
    overlaps = 0
    for i, (bear, e) in enumerate(ms):
        if len(ms) == 1:
            break
        nb, ne = ms[(i + 1) % len(ms)]
        a0 = math.atan2(e[1][1] - O[1], e[1][0] - O[0])          # exit side of this arm (+n, ccw)
        a1 = math.atan2(ne[-1][1] - O[1], ne[-1][0] - O[0])      # entry side of the next arm
        gap = (nb - bear) % (2 * math.pi) or 2 * math.pi         # between the two arms' centrelines
        arc = (a1 - a0) % (2 * math.pi)
        if arc > gap:                                            # the returns cross: nothing left between
            overlaps += 1
            continue
        parts.append(("RBEDGE", _circle(O, rc, a0, a0 + arc), False))
    q = {"icd": round(icd, 2), "width": round(rc - ri - apron, 2), "overlaps": overlaps,
         "kerb_m": round(sum(_length(p, c) for code, p, c in parts if code in ("KERB", "RBEDGE")), 1),
         "island_m2": round(sum(_area(p) for code, p, c in parts if code == "KERB"), 1)}
    return parts, q, detail, P


def checks(arms: List[dict], P: dict, q: dict) -> List[Tuple[str, str]]:
    """(level, text) against RDM 1.3 Chapter 10."""
    out = []
    n = len(arms)
    island, icd, width = float(P["island"]), q["icd"], q["width"]
    if n < ARMS_MIN:
        out.append(("issue", f"{n} arm(s): a roundabout needs at least {ARMS_MIN} (RDM 1.3 10.4.3)"))
    if n > ARMS_MAX:
        out.append(("issue", f"{n} arms: more than {ARMS_MAX} legs should not be considered (RDM 1.3 10.4.3)"))
    bs = sorted(a["bearing"] % (2 * math.pi) for a in arms)
    for a, b in zip(bs, bs[1:] + [bs[0] + 2 * math.pi] if bs else []):
        gap = math.degrees(b - a)
        if n > 1 and gap < ARM_ANGLE_MIN - 1e-6:
            out.append(("check", f"two arms only {gap:.0f} deg apart; at least {ARM_ANGLE_MIN:.0f} deg between "
                                 f"entry roads (RDM 1.3 10.4.3)"))
    if island < ISLAND_MIN - 1e-9:
        out.append(("issue", f"central island {island:g} m across; at least {ISLAND_MIN:g} m for a kerbed island "
                             f"(RDM 1.3 10.5.2.1); smaller is a mini roundabout, not drawn here"))
    if icd > ICD_MAX + 1e-9:
        out.append(("issue", f"ICD {icd:g} m; a normal roundabout should not exceed {ICD_MAX:g} m (RDM 1.3 10.5)"))
    need = min_icd(island)
    if icd < need - 0.05:
        out.append(("check", f"ICD {icd:g} m is under the Table 10.1 minimum of {need:.1f} m for a {island:g} m "
                             f"island and the 15.5 m articulated design vehicle (RDM 1.3 Table 10.1)"))
    if width < WIDTH_MIN - 1e-9:
        out.append(("check", f"circulatory carriageway {width:.1f} m; about {WIDTH_MIN:g} m is the single-lane "
                             f"minimum (RDM 1.3 10.5.2)"))
    if width > WIDTH_MAX + 1e-9:
        out.append(("check", f"circulatory carriageway {width:.1f} m; it should not exceed {WIDTH_MAX:g} m "
                             f"(RDM 1.3 10.5.2)"))
    if q.get("overlaps"):
        out.append(("check", f"the kerb returns of {q['overlaps']} pair(s) of adjacent arms run into each other on "
                             f"the circle: reduce the entry / exit radii or enlarge the ICD"))
    if COMPACT_ICD[0] <= icd <= COMPACT_ICD[1]:
        out.append(("info", f"ICD {icd:g} m is between {COMPACT_ICD[0]:g} and {COMPACT_ICD[1]:g} m: consider a "
                            f"compact roundabout if the flows allow (RDM 1.3 10.5)"))
    out.append(("info", "entry deflection and the fastest path (no path radius over 100 m) are not checked; "
                        "design them with the junction (RDM 1.3 10.4.1, 10.7)"))
    return out
