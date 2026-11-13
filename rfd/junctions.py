"""Junction islands and markings as templates the user places (no junction design).

The templates (rfd/data/junction_templates.json) are taken from the standard drawings
RDM/1/3/2/01 and /02 and RDM 6.1. A junction is placed with two points: the junction
point on the main road (snapped to its centreline) and a point along the minor road,
which gives the minor road's bearing and so the skew. Each piece is drawn in one of
four frames:

  main    (X, Y): X along the main road, positive towards the side the right-turn
          traffic leaves by (the ghost island tail), Y offset towards the minor road;
          mapped through the alignment so it follows curves
  minor   (u, v): u along the minor road measured from the main-road edge, v to the
          left looking up the minor road (Kenya drives on the left: the approach lane is v < 0)
  corner  (a, b): a along the main-road edge away from the minor road, b along the minor
          road; a sheared frame, so corner islands follow the skew
  guide   construction lines: main edge, minor centreline and edges, kerb returns, Rc arcs

Pure Python (no QGIS) so the plugin and the tests share it.
"""
from __future__ import annotations

import json
import math
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DATA = Path(__file__).resolve().parent / "data" / "junction_templates.json"
Pt = Tuple[float, float]

SKEW_PREFERRED = (75.0, 120.0)      # RDM 1.3 9.2.3: crossing angle preferably 75-120 degrees
SKEW_MINIMUM = 60.0                 # absolute minimum


def load_templates(path=None) -> dict:
    return json.loads(Path(path or DATA).read_text(encoding="utf-8"))


def pieces_for(templates: dict, jtype: Optional[str] = None) -> List[str]:
    """Piece ids for a junction type (all pieces when None)."""
    return [k for k, p in templates["pieces"].items() if jtype is None or jtype in p["types"]]


# --------------------------------------------------------------------------- placement
@dataclass
class Placement:
    station: float                  # internal station of the junction point on the main road
    bearing: float                  # radians: direction of the minor road away from the main road
    scale: float = 1.0
    edge: Optional[float] = None    # main-road edge offset on the minor side (m); None: ETW or 3.5 m
    junction_id: str = field(default_factory=lambda: _uuid.uuid4().hex[:8])
    role: str = "main"              # main: our road is the main road; minor: our road joins another road
    main_ref: str = ""              # minor role: "alg:<name>" (another alignment) or "line:x,y,heading_rad"
    our_station: Optional[float] = None   # minor role: where our road meets the main road (our chainage)

    def frame(self, al) -> "Frame":
        return Frame(al, self)


def place(al, x0: float, y0: float, x1: float, y1: float, others=(), snap: float = 15.0, **kw) -> Placement:
    """Placement from two clicks: the junction point (snapped to the centreline) and a point up the minor road.
    When the second point is within `snap` m of another alignment that passes near the junction point, the
    bearing follows that alignment (the minor road), so the user doesn't have to aim along it by hand."""
    so = al.station_offset(x0, y0)
    sta = min(max(so.station, al.sta_start), al.sta_end)
    px, py, _ = al.point_at(sta)
    if math.hypot(x1 - px, y1 - py) < 1.0:
        raise ValueError("The second point must be at least 1 m up the minor road")
    b = snap_bearing(px, py, x1, y1, others, snap)
    return Placement(sta, math.atan2(y1 - py, x1 - px) if b is None else b, **kw)


def snap_bearing(px: float, py: float, x1: float, y1: float, others=(), snap: float = 15.0,
                 reach: float = 25.0, step: float = 15.0) -> Optional[float]:
    """Bearing from the junction point (px, py) along another alignment towards the cursor (x1, y1): the
    alignment must pass within `reach` m of the junction point and the cursor within `snap` m of it.
    None when no alignment qualifies (the nearest to the cursor wins)."""
    best = None
    for a in others or ():
        c, j = a.station_offset(x1, y1), a.station_offset(px, py)
        if not (c.in_range and abs(c.offset) <= snap and abs(j.offset) <= reach):
            continue
        d = c.station - j.station
        if abs(d) < 0.5:
            continue
        s = min(max(j.station + math.copysign(min(step, abs(d)), d), a.sta_start), a.sta_end)
        x, y, _ = a.point_at(s)
        if math.hypot(x - px, y - py) < 1.0:
            continue
        if best is None or abs(c.offset) < best[0]:
            best = (abs(c.offset), math.atan2(y - py, x - px))
    return None if best is None else best[1]


def straight_road(x: float, y: float, heading: float, half: float = 400.0):
    """A straight main road through (x, y): the junction point is at its station `half`."""
    from .alignment import Alignment
    dx, dy = math.cos(heading), math.sin(heading)
    return Alignment.from_polyline("MAJOR", [(x - half * dx, y - half * dy), (x + half * dx, y + half * dy)])


def main_alignment(al, pl: Placement, others=()):
    """The alignment the main-road pieces follow: ours, another one of the LandXML, or a straight line."""
    if pl.role != "minor":
        return al
    if pl.main_ref.startswith("alg:"):
        name = pl.main_ref[4:]
        for a in others:
            if a.name == name:
                return a
        raise ValueError(f"Main road alignment {name!r} is not in the LandXML")
    if pl.main_ref.startswith("line:"):
        x, y, h = (float(v) for v in pl.main_ref[5:].split(","))
        return straight_road(x, y, h)
    raise ValueError("A junction on another road needs that road (an alignment or a clicked direction)")


def place_bay(al, x0: float, y0: float, x1: float, y1: float, **kw) -> Placement:
    """Bus bay from two clicks: where the bay (the stopping length) starts and where it ends, on the side
    clicked. The tapers are added before and after it in the direction of travel."""
    a, b = al.station_offset(x0, y0), al.station_offset(x1, y1)
    if not (a.in_range and b.in_range):
        raise ValueError("Beyond the alignment ends")
    if abs(b.station - a.station) < 5.0:
        raise ValueError("The bay must be at least 5 m long")
    side = "R" if a.offset >= 0 else "L"
    left = side == "L"
    if (b.station > a.station) != left:            # the bay starts where traffic reaches it first
        a, b = b, a
    _, _, h = al.point_at(a.station)
    bearing = h + (math.pi / 2 if left else -math.pi / 2)
    pl = Placement(a.station, bearing, role="bay", **kw)
    return pl, abs(b.station - a.station)


MIN_LEG = 30.0                      # m: shorter than this, our road behind the junction point is a stub, not a leg
END_SNAP = 30.0                     # m: a junction this close to our road's end is placed at the end


def minor_legs(al, s0: float, main) -> List[float]:
    """Bearings of our road's legs leaving the main road at our station s0, the one moving away from the
    main road's centreline fastest first. One leg where our road starts or ends at the main road, two where it
    crosses it (crossroads); a leg that runs along the main road (moves away by less than a fifth of the
    sampled length) is left out unless it is the only one."""
    step = min(15.0, max(2.0, (al.sta_end - al.sta_start) / 4))
    mo = main.station_offset(*al.point_at(s0)[:2])
    jx, jy, _ = main.point_at(mo.station)
    cand = []
    for sgn in (1, -1):
        rest = (al.sta_end - s0) if sgn > 0 else (s0 - al.sta_start)    # how much of our road that way
        s = min(max(s0 + sgn * step, al.sta_start), al.sta_end)
        if abs(s - s0) > 0.5:
            x, y, _ = al.point_at(s)
            rate = abs(main.station_offset(x, y).offset) / abs(s - s0)  # how fast it leaves the main road
            cand.append((rate, rest, math.atan2(y - jy, x - jx)))
    # a stub of our road shorter than MIN_LEG behind the junction point is not a leg
    real = [c for c in cand if c[1] >= MIN_LEG] or sorted(cand, key=lambda c: -c[1])[:1]
    real.sort(key=lambda c: -c[1])                      # the longer leg first: where our road lies
    keep = [c for c in real if c[0] >= 0.2]
    return [c[2] for c in (keep or real[:1])]


def _angle_between(a: float, b: float) -> float:
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def place_minor(al, x0: float, y0: float, x1: Optional[float] = None, y1: Optional[float] = None,
                major=None, both: bool = False, **kw):
    """Our road joins another road. (x0, y0): a click on our road where it meets the main road (snapped to
    our centreline). The main road is `major` (another alignment) or the direction from that point to
    (x1, y1). With `major`, (x1, y1), when given, picks our road's leg nearest the cursor, so where our road
    crosses the main road the user chooses the approach by moving the mouse across.
    Returns (placement, main road alignment); with both=True, (list of placements, one per leg, main)."""
    so = al.station_offset(x0, y0)
    s0 = min(max(so.station, al.sta_start), al.sta_end)
    # our road joining another road usually ends there: a click near an end goes to the end
    if s0 - al.sta_start < END_SNAP:
        s0 = al.sta_start
    elif al.sta_end - s0 < END_SNAP:
        s0 = al.sta_end
    px, py, _ = al.point_at(s0)
    cursor = major is not None and x1 is not None and y1 is not None
    if major is not None:
        main, ref = major, f"alg:{major.name}"
    else:
        if x1 is None or math.hypot(x1 - px, y1 - py) < 1.0:
            raise ValueError("Click a point along the main road, at least 1 m from the junction")
        h = math.atan2(y1 - py, x1 - px)
        main, ref = straight_road(px, py, h), f"line:{px:.3f},{py:.3f},{h:.6f}"
    mo = main.station_offset(px, py)
    if not mo.in_range:
        raise ValueError(f"Our road at this point is beyond the ends of {getattr(main, 'name', 'the main road')}")
    ms = mo.station
    jx, jy, _ = main.point_at(ms)
    legs = minor_legs(al, s0, main)
    if not legs:
        raise ValueError("Our road is too short here")
    if cursor and len(legs) > 1 and math.hypot(x1 - jx, y1 - jy) > 1.0:
        cb = math.atan2(y1 - jy, x1 - jx)
        legs.sort(key=lambda b: _angle_between(b, cb))          # the leg on the cursor's side first
    if both:
        jid = kw.pop("junction_id", None) or _uuid.uuid4().hex[:8]
        out = [Placement(ms, b, role="minor", main_ref=ref, our_station=s0,
                         junction_id=jid if i == 0 else f"{jid}-{i + 1}", **kw) for i, b in enumerate(legs)]
        return out, main
    return Placement(ms, legs[0], role="minor", main_ref=ref, our_station=s0, **kw), main


def minor_signs(al, pl: Placement, main) -> List[dict]:
    """Signs for our approach when our road is the minor road: R2 Give Way on the left of the approaching
    traffic (Kenya drives on the left), a little behind the give way line."""
    if pl.role != "minor" or pl.our_station is None:
        return []
    F = pl.frame(main)
    s0 = pl.our_station
    ahead = al.point_at(min(s0 + 1.0, al.sta_end))[:2]
    here = al.point_at(s0)[:2]
    up = (ahead[0] - here[0]) * F.d[0] + (ahead[1] - here[1]) * F.d[1] > 0   # chainage runs away from the main road
    back = F.u_edge + 2.5 * F.s                                               # give way line + 1.8 m
    sta = s0 + back if up else s0 - back
    if not (al.sta_start <= sta <= al.sta_end):
        return []
    facing = "Backward" if up else "Forward"                                  # traffic heading for the main road
    side = "R" if up else "L"                                                 # its left
    return [{"code": "R2", "station": sta, "side": side, "facing": facing}]


class Frame:
    """The junction's coordinate frames, worked out once per placement."""

    def __init__(self, al, pl: Placement):
        self.al, self.pl = al, pl
        x, y, h = al.point_at(pl.station)
        self.p0, self.h = (x, y), h
        self.t = (math.cos(h), math.sin(h))
        self.d = (math.cos(pl.bearing), math.sin(pl.bearing))
        cross = self.t[0] * self.d[1] - self.t[1] * self.d[0]
        if abs(cross) < math.sin(math.radians(10)):
            raise ValueError("The minor road runs almost along the main road (skew under 10 degrees)")
        self.sigma = 1 if cross > 0 else -1             # +1: minor road on the left of the chainage direction
        self.side = "L" if self.sigma > 0 else "R"
        self.l = (-self.d[1], self.d[0])                 # left of the minor road direction
        self.sin = abs(cross)
        self.e = pl.edge if pl.edge is not None else self._edge()
        self.u_edge = self.e / self.sin                  # junction point to the main edge, along the minor road
        # angle from the main road (chainage direction) to the minor road, 0-180
        self.angle = math.degrees(math.acos(max(-1.0, min(1.0, self.t[0] * self.d[0] + self.t[1] * self.d[1]))))
        self.s = pl.scale

    def _edge(self) -> float:
        edges = getattr(self.al, "edges", None)
        if edges:
            for code in EDGE_CODES:
                o = edges.offset(code, self.side, self.pl.station)
                if o is not None:
                    return abs(o)
        return 3.5

    # world points
    def minor(self, u: float, v: float) -> Pt:
        """u from the main edge along the minor road, v left of it (scaled)."""
        uu = self.u_edge + u * self.s
        return (self.p0[0] + uu * self.d[0] + v * self.s * self.l[0],
                self.p0[1] + uu * self.d[1] + v * self.s * self.l[1])

    def corner_dir(self, corner: str) -> Tuple[float, float]:
        """Unit vector along the main edge, away from the minor road, on the given corner."""
        lt = (-self.sigma * self.t[0], -self.sigma * self.t[1])     # left-turn corner (see main())
        return lt if corner == "left_turn" else (-lt[0], -lt[1])

    def corner(self, corner: str, a: float, b: float) -> Pt:
        c = self.minor(0.0, 0.0)
        ad = self.corner_dir(corner)
        # the edge point where the minor road's side meets the main edge is skewed: shear along the minor road
        return (c[0] + a * self.s * ad[0] + b * self.s * self.d[0], c[1] + a * self.s * ad[1] + b * self.s * self.d[1])

    def main(self, X: float, Y: float) -> Pt:
        """X towards the ghost-island tail (against the right-turning stream), Y towards the minor road."""
        sta = self.pl.station - self.sigma * X * self.s
        sta = min(max(sta, self.al.sta_start), self.al.sta_end)
        x, y, _ = self.al.point_at(sta, -self.sigma * Y * self.s)
        return (x, y)

    @property
    def crossing_angle(self) -> float:
        """Acute angle between the roads, degrees (90 = square)."""
        return min(self.angle, 180.0 - self.angle)


# --------------------------------------------------------------------------- local geometry
def clip_halfplane(poly: Sequence[Pt], keep) -> List[Pt]:
    """Sutherland-Hodgman against one half-plane given as f(p) >= 0 (f linear)."""
    out: List[Pt] = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        fa, fb = keep(a), keep(b)
        if fa >= 0:
            out.append(a)
        if (fa >= 0) != (fb >= 0):
            t = fa / (fa - fb)
            out.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return out


def hatch(poly: Sequence[Pt], angle_deg: float, spacing: float) -> List[List[Pt]]:
    """Parallel hatch lines inside a polygon (local coordinates)."""
    if len(poly) < 3:
        return []
    th = math.radians(angle_deg)
    c, s = math.cos(th), math.sin(th)
    rot = [(x * c + y * s, -x * s + y * c) for x, y in poly]         # hatch direction -> +x
    ys = [p[1] for p in rot]
    out = []
    k = math.floor(min(ys) / spacing) + 1
    while k * spacing < max(ys):
        yy = k * spacing
        xs = []
        for i in range(len(rot)):
            (x1, y1), (x2, y2) = rot[i], rot[(i + 1) % len(rot)]
            if (y1 <= yy < y2) or (y2 <= yy < y1):
                xs.append(x1 + (yy - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for a, b in zip(xs[0::2], xs[1::2]):
            if b - a > 0.05:
                out.append([(a * c - yy * s, a * s + yy * c), (b * c - yy * s, b * s + yy * c)])
        k += 1
    return out


def teardrop(start, widest, end, width, head) -> List[Pt]:
    """Teardrop outline (u along the axis, v across), rounded head at start, point at end."""
    n, pts_r = 48, []
    for i in range(n + 1):
        u = start + (end - start) * i / n
        if u <= widest:
            t = (u - start) / (widest - start)
            w = width / 2 * math.sin(math.pi / 2 * t) ** 0.55
        else:
            t = (u - widest) / (end - widest)
            w = width / 2 * (1 - t) ** 1.15
        pts_r.append((u, -w))
    w0 = min(head, width / 2)
    pts_r[0] = (start, 0.0)
    pts_r[1] = (pts_r[1][0], -max(abs(pts_r[1][1]), min(w0, width / 2) * 0.8))
    left = [(u, -v) for u, v in reversed(pts_r[1:-1])]
    return pts_r + left


def stadium(start, length, width) -> List[Pt]:
    r = width / 2
    pts = [(start + r + r * math.cos(math.pi / 2 + math.pi * i / 12), r * math.sin(math.pi / 2 + math.pi * i / 12))
           for i in range(13)]                                       # head cap, left to right
    pts += [(start + length - r + r * math.cos(-math.pi / 2 + math.pi * i / 12),
             r * math.sin(-math.pi / 2 + math.pi * i / 12)) for i in range(13)]
    return pts


def concave_triangle(pts, sag, n=12) -> List[Pt]:
    """Triangle whose last side (pts[1] -> pts[2]) is bowed inwards by sag (kerb curve)."""
    a, b, c = pts
    mx, my = (b[0] + c[0]) / 2, (b[1] + c[1]) / 2
    cx, cy = (a[0] + b[0] + c[0]) / 3, (a[1] + b[1] + c[1]) / 3
    dx, dy = cx - mx, cy - my
    L = math.hypot(dx, dy) or 1.0
    out = [tuple(a), tuple(b)]
    for i in range(1, n):
        t = i / n
        bow = sag * 4 * t * (1 - t)
        out.append((b[0] + t * (c[0] - b[0]) + bow * dx / L, b[1] + t * (c[1] - b[1]) + bow * dy / L))
    out.append(tuple(c))
    return out


def area(poly: Sequence[Pt]) -> float:
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


def length(pts: Sequence[Pt], closed=False) -> float:
    seq = list(pts) + ([pts[0]] if closed else [])
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(seq, seq[1:]))


def densify(pts: Sequence[Pt], step: float, closed=False) -> List[Pt]:
    seq = list(pts) + ([pts[0]] if closed else [])
    out = [seq[0]]
    for a, b in zip(seq, seq[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / step))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)]
    return out


# --------------------------------------------------------------------------- arrow markings
def arrow_length(speed: float) -> float:
    """Lane indication arrow length for the approach speed (RDM 6.1 Table 6.1)."""
    return 3.5 if speed <= 50 else 5.0 if speed <= 100 else 9.0


def _offset_line(pts, d):
    """A polyline offset by d to its left, mitred at the bends."""
    out = []
    for i, p in enumerate(pts):
        normals = []
        for a, b in ((pts[i - 1], p) if i > 0 else (None, None), (p, pts[i + 1]) if i < len(pts) - 1 else (None, None)):
            if a is None:
                continue
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            normals.append((-(b[1] - a[1]) / L, (b[0] - a[0]) / L))
        nx, ny = (normals[0][0] + normals[-1][0]) / 2, (normals[0][1] + normals[-1][1]) / 2
        k = nx * normals[0][0] + ny * normals[0][1] or 1.0
        out.append((p[0] + d * nx / k, p[1] + d * ny / k))
    return out


def _arrow_outline(axis, half_stem, head_len, half_head) -> List[Pt]:
    """Closed outline of an arrow along the polyline axis (tail first), with a triangular head at the end."""
    ax = list(axis)
    (x1, y1), (x0, y0) = ax[-1], ax[-2]
    L = math.hypot(x1 - x0, y1 - y0)
    u = ((x1 - x0) / L, (y1 - y0) / L)
    n = (-u[1], u[0])
    base = (x1 - head_len * u[0], y1 - head_len * u[1])
    shaft = ax[:-1] + [base]
    left, right = _offset_line(shaft, half_stem), _offset_line(shaft, -half_stem)
    head = [(base[0] + half_head * n[0], base[1] + half_head * n[1]), (x1, y1),
            (base[0] - half_head * n[0], base[1] - half_head * n[1])]
    return left + head + right[::-1]


def arrow_shapes(kind: str, L: float) -> List[List[Pt]]:
    """Arrow markings (RDM 6.1 Table A.5, Figure 6.3) as closed outlines in a local frame: the axis along +x
    from the tail at x = 0 to the tip at x = L; a turning branch leaves at 45 deg towards +y ('turn'), -y,
    or both. kind: straight (AM01), turn (AM03 / AM02 by side), both_turns (AM06), all (AM07)."""
    k = L / 3.5
    hs, hl = 0.075 * k, 1.0 * k                         # 150 mm stem, 1.0 m head at 3.5 m
    bend = 0.55 * L
    c, sn = math.cos(math.radians(45)), math.sin(math.radians(45))
    branch = lambda sg: [(0.0, 0.0), (bend, 0.0), (bend + 0.45 * L * c, sg * 0.45 * L * sn)]
    turn = lambda sg, from_bend: _arrow_outline(branch(sg)[1 if from_bend else 0:], hs, hl * 0.85, 0.35 * k)
    straight = lambda w: _arrow_outline([(0.0, 0.0), (L, 0.0)], hs, hl, w * k)
    return {"straight": lambda: [straight(0.25)],
            "turn": lambda: [turn(1, False)],
            "both_turns": lambda: [turn(1, False), turn(-1, True)],
            "all": lambda: [straight(0.3), turn(1, True), turn(-1, True)]}[kind]()


# --------------------------------------------------------------------------- pieces
@dataclass
class Part:
    code: str                       # marking code (HM07, TM07 ...), KERB or GUIDE
    pts: List[Pt]                   # world coordinates
    closed: bool = False


@dataclass
class Piece:
    piece: str
    name: str
    kind: str                       # island | marking | guide
    corner: str
    parts: List[Part]
    quantities: Dict[str, float]    # kerb_m, island_m2, <code>_m (painted line length), paint_m2
    params: Dict

    def rule(self, junction_id: str) -> str:
        return f"junction:{junction_id}"


def build_piece(al, pl: Placement, piece: str, corner: str = "", params: Optional[dict] = None,
                templates: Optional[dict] = None) -> Piece:
    T = templates or load_templates()
    spec = T["pieces"][piece]
    P = dict(spec.get("params", {}), **(params or {}))
    F = pl.frame(al)
    if P.get("edge_add"):
        # the main road is widened on the minor road's side (a ghost island kit): pieces off the main road
        # stand off the widened edge
        F.e += float(P["edge_add"])
        F.u_edge = F.e / F.sin
    loc: List[Tuple[str, List[Pt], bool, str]] = []          # (code, local pts, closed, frame)
    q: Dict[str, float] = {}
    fr = spec["frame"]
    s2 = F.s * F.s

    def marked(code, poly, hatch_code, angle, spacing=2.0):
        loc.append((code, poly, True, fr))
        for h in hatch(poly, angle, spacing / F.s):
            loc.append((hatch_code, h, False, fr))

    if piece == "ghost_island":
        n, f, tp, w, y = P["nose"], P["full"], P["taper"], P["width"], P["y"]
        r = w / 2                                     # rounded nose facing the junction
        cap = [(n + r - r * math.sin(math.pi * i / 12), y - r * math.cos(math.pi * i / 12)) for i in range(13)]
        marked("HM14", cap + [(n + f, y + r), (n + f + tp, y), (n + f, y - r)], "HM07", 45.0)
    elif piece == "ghost_lead":
        a, L, w, y = P["start"], P["length"], P["width"], P["y"]
        r = w / 2                                     # rounded end at X = start, strip running away from the junction
        cap = [(a - r + r * math.sin(math.pi * i / 12), y + r * math.cos(math.pi * i / 12)) for i in range(13)]
        marked("HM14", cap + [(a - L, y - r), (a - L, y + r)], "HM07", 45.0)
    elif piece == "ghost_wedge":
        a, rise, full, w, y = P["start"], P["rise"], P["full"], P["width"], P["y"]
        pts = [(a + rise * i / 10, y - w / 2 * (1 - math.cos(math.pi * i / 10)) / 2) for i in range(11)]
        poly = [(a, y)] + pts[1:] + [(a + rise + full, y - w / 2), (a + rise + full, y + w / 2)] + \
               [(x, 2 * y - yy) for x, yy in reversed(pts[1:])]
        marked("HM14", poly, "HM07", 45.0)
    elif piece == "splitter_a1":
        st, rl, w, tail = P["start"], P["raised"], P["width"], P["tail"]
        raised = stadium(st, rl, w)
        loc.append(("KERB", raised, True, fr))
        q["kerb_m"] = length(raised, True) * F.s
        q["island_m2"] = area(raised) * s2
        poly = [(st + rl, w / 2), (st + rl + tail, 0.0), (st + rl, -w / 2)]
        marked("HM14", poly, "HM07", 45.0)
    elif piece in ("splitter_a2", "splitter_teardrop"):
        drop = teardrop(P["start"], P["widest"], P["end"], P["width"], P["head"])
        cut = P["raised_to"]
        raised = clip_halfplane(drop, lambda p: cut - p[0])
        painted = clip_halfplane(drop, lambda p: p[0] - cut)
        loc.append(("KERB", raised, True, fr))
        q["kerb_m"] = length(raised, True) * F.s
        q["island_m2"] = area(raised) * s2
        if len(painted) >= 3:
            marked("HM14", painted, "HM07", 45.0, 1.0)
    elif piece == "corner_island":
        poly = concave_triangle(P["pts"], P.get("sag", 0.0))
        loc.append(("KERB", poly, True, fr))
        q["kerb_m"] = _sheared_len(F, corner, poly)
        q["island_m2"] = area(poly) * s2 * F.sin
    elif piece == "corner_hatch":
        poly = [tuple(p) for p in P["pts"]]
        loc.append(("LM27", poly, True, fr))
        for h in hatch(poly, 135.0, 2.0 / F.s):
            loc.append(("HM04", h, False, fr))
    elif piece == "give_way_line":
        at, lane, inner = P["at"], P["lane"], P.get("inner", 0.0)
        dash, gap = T["codes"]["TM07"]["dash"]
        v = 0.0
        while v < lane - 1e-6:
            loc.append(("TM07", [(at + 0.2, -inner - v), (at + 0.2, -inner - min(v + dash, lane))], False, fr))
            v += dash + gap
    elif piece == "give_way_triangle":
        at, lane, gap, L, b = P["at"], P["lane"], P["gap"], P["length"], P["base"]
        apex = at + 0.4 + gap
        vc = -P.get("inner", 0.0) - lane / 2
        tri = [(apex, vc), (apex + L, vc - b / 2), (apex + L, vc + b / 2)]
        loc.append(("BM07", tri, True, fr))
    elif piece == "main_widening":
        # the main road widened on both sides by half the ghost island's width, so the through lanes keep
        # their width: full width from X0 to X1 (junction frame), tapering out over t0 / t1 beyond
        w, X0, X1, t0, t1 = P["width"], P["from"], P["to"], P["taper_from"], P["taper_to"]
        stations = [X0 - t0, X0, X1, X1 + t1]
        for ys in (1, -1):
            pts = []
            for i in range(0, int((stations[-1] - stations[0]) / 2.0) + 1):
                X = stations[0] + 2.0 * i
                f = 1.0 if X0 <= X <= X1 else max(0.0, 1 - (X0 - X) / t0) if X < X0 else max(0.0, 1 - (X - X1) / t1)
                pts.append((X, ys * (F.e / F.s + w / 2 * f)))
            loc.append(("WIDEN", pts, False, fr))
        area_side = w / 2 * ((X1 - X0) + (t0 + t1) / 2) * F.s
        q["widen_m2"] = round(2 * area_side, 2)
        sta = lambda X: pl.station - F.sigma * X * F.s
        rows = []
        for ys, side in ((1, F.side), (-1, "R" if F.side == "L" else "L")):
            st4 = sorted(sta(X) for X in stations)
            rows.append({"road": "main", "side": side, "stations": [round(v, 3) for v in st4],
                         "entry": round(t0 * F.s, 1), "exit": round(t1 * F.s, 1), "depth": round(w / 2, 2),
                         "kind": "main road widening for the ghost island", "taper": "straight"})
        P = dict(P, rows=rows)
    elif piece == "turn_arrow":
        # right-turn arrows in the right-turn lane: the right-turners come from -X towards the junction and
        # turn towards +Y (the minor road); RDM 6.1 6.4.2-6.4.3
        L = P.get("length") or arrow_length(al.speed_at(pl.station) or 80.0)
        for i in range(int(P.get("count", 2))):
            tip = P["at"] - i * P["spacing"]
            for poly in arrow_shapes("turn", L):
                loc.append(("AM03", [(tip - L + x, P["y"] + y) for x, y in poly], True, fr))
    elif piece == "approach_arrows":
        # on the minor road's approach lane, pointing at the main road (RDM 6.1 6.4.3: "on a side road
        # approach to a main road, arrows are marked on the side road"): AM06 at a T, AM07 at a crossroads
        L = P.get("length") or 5.0
        kind, code = ("all", "AM07") if P.get("crossroads") else ("both_turns", "AM06")
        vc = -P.get("inner", 0.0) - P["lane"] / 2
        for poly in arrow_shapes(kind, L):
            # local x (tail -> tip) runs down the minor road towards the main road (-u)
            loc.append((code, [(P["at"] + L - x, vc - y) for x, y in poly], True, fr))
    elif piece == "minor_centre_line":
        loc.append(("LM24", [(P["start"], 0.0), (P["start"] + P["length"], 0.0)], False, fr))
    elif piece == "guides":
        return _guides(F, spec, P, piece)
    elif piece in BAY_PIECES:
        return _bus_bay(F, spec, P, piece)
    elif piece == "splays":
        return _splays(F, spec, P, piece)
    elif piece == "access":
        return _access(F, spec, P, piece)
    elif piece == "roundabout":
        return _roundabout(F, spec, P, piece)
    elif piece == "signal_crossroads":
        return _signal_crossroads(F, spec, P, piece, T)
    else:
        raise ValueError(f"Unknown junction piece {piece!r}")

    parts = []
    codes = T["codes"]
    for code, pts, closed, frame in loc:
        if frame == "main":
            world = [F.main(x, y) for x, y in densify(pts, 2.0 / F.s, closed)]
            closed_w = False
        elif frame == "corner":
            world = [F.corner(corner, a, b) for a, b in pts]
            closed_w = closed
        else:
            world = [F.minor(u, v) for u, v in pts]
            closed_w = closed
        parts.append(Part(code, world, closed_w))
        if codes[code].get("fill"):                      # arrows: the painted area of the outline
            q[f"{code}_no"] = q.get(f"{code}_no", 0) + 1
            q["paint_m2"] = round(q.get("paint_m2", 0.0) + area(world), 3)
        elif code not in ("KERB", "GUIDE", "WIDEN"):
            ln = length(world, closed_w)
            q[f"{code}_m"] = round(q.get(f"{code}_m", 0.0) + ln, 3)
            q["paint_m2"] = round(q.get("paint_m2", 0.0) + ln * codes[code]["width"], 3)
    for k in ("kerb_m", "island_m2"):
        if k in q:
            q[k] = round(q[k], 2)
    return Piece(piece, spec["name"], spec["kind"], corner, parts, q, P)


def _sheared_len(F, corner, poly):
    world = [F.corner(corner, a, b) for a, b in poly]
    return length(world, True)


def _arc(c, r, a0, a1, n=24) -> List[Pt]:
    return [(c[0] + r * math.cos(a0 + (a1 - a0) * i / n), c[1] + r * math.sin(a0 + (a1 - a0) * i / n))
            for i in range(n + 1)]


THREE_CENTRED = ((2.0, 0.2), (1.0, 0.6), (3.0, 0.2))     # (radius / R2, share of the turn): RDM 1.3 Fig 9.25


def _return_behind_island(F, corner, p0, d, sgn, r2, slip, W, step=0.25, most=20.0):
    """The three-centred return on a corner with an island, pushed out (both edges widened by the same
    amount) until the island lies inside it with `slip` m of turning roadway between. Returns (curve in the
    guide frame, widening)."""
    T = load_templates()
    pc = T["pieces"]["corner_island"]["params"]
    isl = [F.corner(corner, a, b) for a, b in concave_triangle(pc["pts"], pc.get("sag", 0.0))]
    ox, oy = W(0.0, 0.0)
    ex = (W(1.0, 0.0)[0] - ox, W(1.0, 0.0)[1] - oy)
    ey = (W(0.0, 1.0)[0] - ox, W(0.0, 1.0)[1] - oy)
    loc = [((x - ox) * ex[0] + (y - oy) * ex[1], (x - ox) * ey[0] + (y - oy) * ey[1]) for x, y in isl]
    n = (p0[0] / max(math.hypot(*p0), 1e-9), p0[1] / max(math.hypot(*p0), 1e-9))     # outward from the minor axis
    th = math.atan2(0.0, -sgn)
    st = 1.0 if math.remainder(math.atan2(d[1], d[0]) - th, 2 * math.pi) > 0 else -1.0
    curve = None
    k = 0.0
    while k <= most:
        q = (p0[0] + n[0] * k, p0[1] + n[1] * k - k)          # minor edge widened by k, main edge raised by k
        c = [(x, y + k) for x, y in three_centred_return(q, d, sgn, r2)]
        ok = True
        for v in loc:
            best, side = math.inf, 0.0
            for a, b in zip(c, c[1:]):
                L2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 or 1e-9
                t = max(0.0, min(1.0, ((v[0] - a[0]) * (b[0] - a[0]) + (v[1] - a[1]) * (b[1] - a[1])) / L2))
                dist = math.hypot(v[0] - a[0] - t * (b[0] - a[0]), v[1] - a[1] - t * (b[1] - a[1]))
                if dist < best:
                    best = dist
                    side = (b[0] - a[0]) * (v[1] - a[1]) - (b[1] - a[1]) * (v[0] - a[0])
            if side * st >= 0 or best < slip:                 # beyond the return (verge side), or too close
                ok = False
                break
        curve = c
        if ok:
            return c, k
        k += step
    return curve, most


def three_centred_return(p0: Pt, d: Pt, sgn: int, r2: float, step: float = 0.5) -> List[Pt]:
    """A kerb return in the guide frame (main edge along y = 0, minor road towards +y): a compound curve of
    radii 2 R2, R2 and 3 R2 (RDM 1.3 Figure 9.25) turning from the main edge into the minor edge through p0
    (direction d, away from the main road). sgn: the corner on the +x side (1) or the -x side (-1). The curve
    starts tangent to the main edge and ends tangent to the minor edge."""
    th = math.atan2(0.0, -sgn)                          # along the main edge, towards the corner
    turn = math.remainder(math.atan2(d[1], d[0]) - th, 2 * math.pi)
    st = 1.0 if turn > 0 else -1.0
    pts, pos = [(0.0, 0.0)], (0.0, 0.0)
    nl = lambda a: (-math.sin(a), math.cos(a))
    for k, share in THREE_CENTRED:
        R, dl = k * r2, abs(turn) * share
        c = (pos[0] + st * R * nl(th)[0], pos[1] + st * R * nl(th)[1])
        n = max(2, int(R * dl / step))
        for i in range(1, n + 1):
            ph = th + st * dl * i / n
            pts.append((c[0] - st * R * nl(ph)[0], c[1] - st * R * nl(ph)[1]))
        th += st * dl
        pos = pts[-1]
    # slide along the main edge so the end lies on the minor edge
    E = pts[-1]
    xs = (d[0] * (E[1] - p0[1]) - d[1] * (E[0] - p0[0])) / d[1]
    return [(x + xs, y) for x, y in pts]


def _guides(F: Frame, spec, P, piece) -> Piece:
    """Construction lines in a frame with the main edge as the x-axis (x along the chainage, y to the minor road)."""
    s = F.s
    w2, R, rc, reach, nose = P["minor_width"] / 2 * s, P["return_radius"] * s, P["rc"] * s, P["reach"] * s, P["nose"]
    # local edge frame: origin on the main edge at the minor axis, x along the chainage, y towards the minor road
    ex, ey = F.t, (-F.t[1] * F.sigma, F.t[0] * F.sigma)
    o = F.minor(0.0, 0.0)

    def W(x, y):
        return (o[0] + x * ex[0] + y * ey[0], o[1] + x * ex[1] + y * ey[1])

    dx, dy = F.d[0] * ex[0] + F.d[1] * ex[1], F.d[0] * ey[0] + F.d[1] * ey[1]      # minor direction, local
    parts = []
    # minor centreline and edges
    parts.append(Part("GUIDE", [W(-F.e * dx / dy, -F.e), W(reach * dx * 2, reach * dy * 2)]))
    # the minor road flared around its splitter island, so its lanes keep their width
    fl = P.get("minor_flare") or {}
    fh, f_to, f_taper = float(fl.get("half", 0.0)) * s, float(fl.get("to", 0.0)) * s, float(fl.get("taper", 15.0)) * s
    rows = []
    if fh > 0:
        for side in ("L", "R"):                       # along the minor road from the main edge (u)
            rows.append({"road": "minor", "side": side, "u": [0.0, 0.0, f_to, f_to + f_taper], "entry": 0.0,
                         "exit": round(f_taper, 1), "depth": round(fh, 2), "kind": "minor road flare at the splitter",
                         "taper": "straight"})
    for sgn in (1, -1):
        n = (sgn * dy, -sgn * dx)                     # unit normal of the minor axis, +x side for sgn = 1
        p_n = (n[0] * w2, n[1] * w2)                  # the normal minor edge at the main edge
        p0 = (n[0] * (w2 + fh), n[1] * (w2 + fh))     # the (flared) minor edge at the main edge
        # fillet centre: distance R from the main edge (y = R) and R outside the minor edge
        if abs(n[0]) < 1e-9:
            continue
        corner = "left_turn" if sgn == -F.sigma else "other"
        slip = (P.get("slip") or {}).get(corner)
        if P.get("three_centred", True) and slip:
            # a corner island: the turning roadway (slip) runs behind it, so the bellmouth is widened and the
            # return starts from the widened edges, clear of the island by the slip width (RDM/1/3/2/01)
            r2 = P.get("r2") or min(max(P["return_radius"] / 2.0, 8.0), 12.0)
            curve, wid = _return_behind_island(F, corner, p0, (dx, dy), sgn, r2 * s, slip * s, W)
            parts.append(Part("GUIDE", [W(*p) for p in curve]))
            # the widened edges and their tapers back to the road edges
            taper = float(P.get("slip_taper", 30.0)) * s
            x0 = curve[0][0]
            st_ = lambda x: F.al.station_offset(*W(x, 0.0)).station
            ss = sorted((st_(x0 + sgn * taper), st_(x0), st_(0.0)))
            rows.append({"road": "main", "side": F.side, "stations": [ss[0], ss[1], ss[2], ss[2]] if sgn < 0 else
                         [ss[0], ss[0], ss[1], ss[2]], "entry": round(taper, 1), "exit": 0.0, "depth": round(wid, 2),
                         "kind": "bellmouth behind a corner island", "taper": "straight"})
            parts.append(Part("GUIDE", [W(x0, wid), W(x0 + sgn * taper, 0.0)]))
            q_end = curve[-1]
            back = (q_end[0] + taper * dx - n[0] * wid, q_end[1] + taper * dy - n[1] * wid)
            parts.append(Part("GUIDE", [W(*q_end), W(*back)]))
            t2 = back
        elif P.get("three_centred", True):
            # RDM 1.3 Figure 9.25: three-centred return R1 : R2 : R3 = 2 : 1 : 3, R2 8-12 m
            r2 = P.get("r2") or min(max(P["return_radius"] / 2.0, 8.0), 12.0)
            curve = three_centred_return(p0, (dx, dy), sgn, r2 * s)
            parts.append(Part("GUIDE", [W(*p) for p in curve]))
            t2 = curve[-1]
        else:
            cx = p0[0] + (R - (R - p0[1]) * n[1]) / n[0]
            c = (cx, R)
            t1 = (cx, 0.0)                                 # tangent on the main edge
            t2 = (cx - R * n[0], R - R * n[1])             # tangent on the minor edge
            a0, a1 = math.atan2(t1[1] - R, t1[0] - cx), math.atan2(t2[1] - R, t2[0] - cx)
            while a1 - a0 > math.pi:
                a1 -= 2 * math.pi
            while a0 - a1 > math.pi:
                a1 += 2 * math.pi
            parts.append(Part("GUIDE", [W(*p) for p in _arc(c, R, a0, a1)]))
        # minor edge from the tangent point outwards (flared, then tapering back to its normal line)
        k = (t2[0] - p0[0]) * dx + (t2[1] - p0[1]) * dy
        if fh > 0 and f_to > k:
            a_ = (p0[0] + f_to * dx, p0[1] + f_to * dy)
            b_ = (p_n[0] + (f_to + f_taper) * dx, p_n[1] + (f_to + f_taper) * dy)
            far = max(reach, f_to + f_taper + 5.0)
            parts.append(Part("GUIDE", [W(t2[0], t2[1]), W(*a_), W(*b_),
                                        W(p_n[0] + far * dx, p_n[1] + far * dy)]))
        else:
            parts.append(Part("GUIDE", [W(t2[0], t2[1]), W(p0[0] + (k + reach) * dx, p0[1] + (k + reach) * dy)]))
        # Rc arc: tangent to the main-road centreline (y = -e), through the splitter nose N
        N = (nose * s * dx, nose * s * dy)
        h = rc - (N[1] + F.e)
        if 0 < N[1] + F.e < 2 * rc and rc * rc - h * h > 0:
            cx = N[0] + sgn * math.sqrt(rc * rc - h * h)
            cc = (cx, -F.e + rc)
            a0 = -math.pi / 2                          # tangent point on the centreline
            a1 = math.atan2(N[1] - cc[1], N[0] - cc[0])
            while a1 - a0 > math.pi:
                a1 -= 2 * math.pi
            while a0 - a1 > math.pi:
                a1 += 2 * math.pi
            a1 += (a1 - a0) * 0.15                     # run on a little past the nose, as drawn
            parts.append(Part("GUIDE", [W(*p) for p in _arc(cc, rc, a0, a1)]))
    # main edge on the minor side, following the alignment
    parts.append(Part("GUIDE", [_main_edge(F, k / 2.0) for k in range(int(-reach * 2 / s), int(reach * 2 / s) + 1)]))
    return Piece(piece, spec["name"], "guide", "", parts, {}, dict(P, rows=rows))


def _signal_crossroads(F: Frame, spec, P, piece, T) -> Piece:
    """A four-arm signal-controlled crossroads without islands (RDM 6.1 7.8, Figure 7.12), single
    carriageways: kerb returns on the four corners (guides), and on every arm a pedestrian crossing in BM02
    blocks where the kerb runs straight, the TM01 stop line across the approach half behind it, an LM24 centre
    line leading in and an AM07 arrow in the approach lane. Not scaled; the signals are designed separately."""
    O, t, d = F.p0, F.t, F.d
    e = F.e                                   # main road half-width (edge offset)
    w = float(P.get("minor_half", 3.5))       # minor road half-width
    R = float(P.get("return_radius", 12.0))
    cw = float(P.get("crossing", 3.0))        # BM02: 3 m blocks along the road
    gap = float(P.get("stop_gap", 1.5))       # stop line this far behind the crossing
    L_cl = float(P.get("centre_line", 30.0))
    nl = lambda u: (-u[1], u[0])
    add = lambda a, b, k=1.0: (a[0] + k * b[0], a[1] + k * b[1])
    cross2 = lambda a, b: a[0] * b[1] - a[1] * b[0]
    nm, nd = nl(t), nl(d)
    parts: List[Part] = []
    reach = {}                               # arm -> distance of the furthest kerb tangent from O along it
    for sm in (1, -1):
        for sd in (1, -1):
            # fillet centre: R outside both edges of the corner (main edge sm, minor edge sd)
            A = add(O, nm, sm * (e + R))
            B = add(O, nd, sd * (w + R))
            den = cross2(t, d)
            lam = cross2((B[0] - A[0], B[1] - A[1]), d) / den
            C = add(A, t, lam)
            T1 = add(C, nm, -sm * R)          # on the main edge
            T2 = add(C, nd, -sd * R)          # on the minor edge
            a0 = math.atan2(T1[1] - C[1], T1[0] - C[0])
            a1 = math.atan2(T2[1] - C[1], T2[0] - C[0])
            da = math.remainder(a1 - a0, 2 * math.pi)
            parts.append(Part("GUIDE", [(C[0] + R * math.cos(a0 + da * k / 24), C[1] + R * math.sin(a0 + da * k / 24))
                                        for k in range(25)]))
            # this corner's road edges, on from its tangent points
            parts.append(Part("GUIDE", [T1, add(T1, t, (1 if (T1[0] - O[0]) * t[0] + (T1[1] - O[1]) * t[1] > 0 else -1) * 40.0)]))
            parts.append(Part("GUIDE", [T2, add(T2, d, (1 if (T2[0] - O[0]) * d[0] + (T2[1] - O[1]) * d[1] > 0 else -1) * 40.0)]))
            km = (T1[0] - O[0]) * t[0] + (T1[1] - O[1]) * t[1]
            kd = (T2[0] - O[0]) * d[0] + (T2[1] - O[1]) * d[1]
            for arm, k in ((("m", 1 if km > 0 else -1), abs(km)), (("d", 1 if kd > 0 else -1), abs(kd))):
                reach[arm] = max(reach.get(arm, 0.0), k)
    L_arrow = arrow_length(F.al.speed_at(F.pl.station) or 50.0)
    for (ax, sg), k in reach.items():
        u, n_, half = (t, nm, e) if ax == "m" else (d, nd, w)
        x0 = k + 0.5                                                     # crossing's near edge
        # BM02 blocks across the full width, 0.5 m wide, 0.5 m apart
        o = -half + 0.25
        while o + 0.5 <= half - 0.25 + 1e-6:
            q = [add(add(O, u, sg * x0), n_, o), add(add(O, u, sg * (x0 + cw)), n_, o),
                 add(add(O, u, sg * (x0 + cw)), n_, o + 0.5), add(add(O, u, sg * x0), n_, o + 0.5)]
            parts.append(Part("BM02", q, True))
            o += 1.0
        # traffic arriving on this arm heads -sg*u and keeps left: its lane is on the -sg side of n_
        xs = x0 + cw + gap
        side = -sg
        parts.append(Part("TM01", [add(add(O, u, sg * xs), n_, 0.0), add(add(O, u, sg * xs), n_, side * half)]))
        parts.append(Part("LM24", [add(O, u, sg * xs), add(O, u, sg * (xs + L_cl))]))
        lane_c = side * half / 2
        for poly in arrow_shapes("all", L_arrow):
            # arrow x runs tail -> tip towards the junction
            parts.append(Part("AM07", [add(add(O, u, sg * (xs + 2.0 + L_arrow - x)), n_, lane_c - sg * y)
                                       for x, y in poly], True))
    q: Dict[str, float] = {}
    codes = T["codes"]
    for pt in parts:
        if pt.code == "GUIDE":
            continue
        if codes[pt.code].get("fill"):
            q[f"{pt.code}_no"] = q.get(f"{pt.code}_no", 0) + 1
            q["paint_m2"] = round(q.get("paint_m2", 0.0) + area(pt.pts), 3)
        else:
            ln = length(pt.pts)
            q[f"{pt.code}_m"] = round(q.get(f"{pt.code}_m", 0.0) + ln, 3)
            q["paint_m2"] = round(q.get("paint_m2", 0.0) + ln * codes[pt.code]["width"], 3)
    return Piece(piece, spec["name"], "marking", "", parts, q, dict(P, arms=len(reach)))


SPLAY_KINDS = (("approach", "SPLAY-A"), ("stop", "SPLAY-S"))
SPLAY_DEFAULT_SPEED = 80.0


def _splays(F: Frame, spec, P, piece) -> Piece:
    """Visibility splays (RDM 1.3 9.5.4, Figures 9.11-9.12): for each control (approach / give way, stop) and each
    direction along the main road, the area between the minor road's centreline from the junction point to the
    apex (set-back from the main road's lane edge), the sight line from the apex to the main road's centreline
    at the sight distance, and that centreline back to the junction point. Not scaled with the kit."""
    from .criteria import DEFAULT_ID, Criteria
    from .features import visible_from
    al, pl = F.al, F.pl
    crit = Criteria.load(P.get("criteria") or DEFAULT_ID)
    v, assumed = P.get("speed"), False
    if not v:
        v = al.speed_at(pl.station)
    if not v:
        v, assumed = SPLAY_DEFAULT_SPEED, True
    parts, out = [], []
    kinds = P.get("kinds") or [k for k, _ in SPLAY_KINDS]
    for kind, code in SPLAY_KINDS:
        if kind not in kinds:
            continue
        t = crit.junction_sight(kind, v)
        if t is None:
            continue
        setback, L = t
        u = F.e / F.sin + setback                  # along the minor road from the junction point
        apex = (F.p0[0] + u * F.d[0], F.p0[1] + u * F.d[1])
        for sg in (1, -1):                         # +1: the leg up the chainage of the main road
            far = pl.station + sg * L
            short = not (al.sta_start <= far <= al.sta_end)
            far = min(max(far, al.sta_start), al.sta_end)
            n = max(2, int(abs(far - pl.station) / 2.0) + 1)
            cl = [al.point_at(far + (pl.station - far) * k / (n - 1))[:2] for k in range(n)]
            parts.append(Part(code, [apex] + cl, True))
            # vertical: the vehicle on the main road seen over the profile from the junction (Table 3.13 heights)
            seen = visible_from(al, pl.station, L, sg * -1, crit.eye_height,
                                float(crit.data.get("vehicle_object_height", 0.6)))
            out.append({"kind": kind, "dir": "up" if sg > 0 else "down", "setback": setback, "length": round(L, 1),
                        "available": round(abs(far - pl.station), 1), "short": short,
                        "profile": None if seen is None else round(seen, 1)})
    P = dict(P, speed_used=v, speed_assumed=assumed, ref=crit.ref("junction_sight"), splays=out,
             criteria_has=bool(out))
    return Piece(piece, spec["name"], "splay", "", parts, {}, P)


def approach_splay(our, pl: Placement, main, speed: Optional[float] = None, criteria: Optional[str] = None,
                   lane: float = 1.75, edge_add: float = 0.0) -> Piece:
    """The minor road approach visibility splay of RDM 1.3 Figure 9.13, where our road is the minor road: the
    area between our approach lane and the sight lines from drivers up to one stopping sight distance (at
    our road's design speed) back from the give way line to the line and its sign. On a bend it lies across
    the inside of the curve and must be kept clear; params['clear_m'] is how far it reaches beyond the lane
    centre, measured square to the road."""
    from .criteria import DEFAULT_ID, Criteria
    if pl.role != "minor" or pl.our_station is None:
        raise ValueError("The approach splay is for a junction where our road is the minor road")
    T = load_templates()
    spec = T["pieces"]["approach_splay"]
    crit = Criteria.load(criteria or DEFAULT_ID)
    F = pl.frame(main)
    if edge_add:
        F.e += edge_add
        F.u_edge = F.e / F.sin
    s0 = pl.our_station
    _, _, h = our.point_at(s0)
    dirn = 1 if math.cos(pl.bearing - h) > 0 else -1          # our leg runs this way in chainage
    sg = min(max(s0 + dirn * (F.u_edge + 0.5), our.sta_start), our.sta_end)       # the give way line
    v = speed or our.speed_at(sg) or 50.0
    ssd = crit.ssd(v)
    off = lane * dirn                                           # the approaching traffic keeps left
    far = min(max(sg + dirn * ssd, our.sta_start), our.sta_end)
    n = max(2, int(abs(far - sg) / 2.0) + 1)
    path = [our.point_at(sg + (far - sg) * k / (n - 1), off)[:2] for k in range(n)]
    target = path[0]
    # how far the sight lines reach from the lane, square to the road
    clear = 0.0
    for e in path[1:]:
        ex, ey = e[0] - target[0], e[1] - target[1]
        L = math.hypot(ex, ey) or 1.0
        for q in path[1:]:
            st_q = our.station_offset(*q).station
            if (st_q - sg) * dirn > (our.station_offset(*e).station - sg) * dirn:
                break
            d = abs((q[0] - target[0]) * ey - (q[1] - target[1]) * ex) / L
            clear = max(clear, d)
    ring = [target] + path[1:]
    parts = [Part("SPLAY-M", ring, True)]
    P = {"speed": round(v, 1), "ssd": round(ssd, 1), "clear_m": round(clear, 2), "give_way": round(sg, 3),
         "far": round(far, 3), "short": abs(far - sg) < ssd - 1e-6, "ref": "RDM 1.3 9.5.4, Figure 9.13"}
    return Piece("approach_splay", spec["name"], "splay", "", parts, {"splay_m2": round(area(ring), 1)}, P)


def approach_splay_findings(ms: dict) -> List[Tuple[str, str]]:
    """(level, text) from a minor-approach splay record (approach_splay params + obstructions)."""
    out = []
    if not ms:
        return out
    if ms.get("clear_m", 0) > 1.5:
        out.append(("info", f"our approach curves: keep the inside of the bend clear for {ms['clear_m']:.1f} m from "
                            f"the lane centre over the {ms['ssd']:.0f} m stopping sight distance at "
                            f"{ms['speed']:.0f} km/h, and the Give Way sign inside the splay ({ms['ref']})"))
    if ms.get("short"):
        out.append(("info", f"our road ends within the {ms['ssd']:.0f} m stopping sight distance of the give way "
                            f"line: check the approach beyond it ({ms['ref']})"))
    for o in ms.get("obstructions", []):
        out.append(("check", f"{o['layer']} feature {o['fid']} is inside the minor road approach visibility splay "
                             f"({ms['ref']})"))
    return out


def splay_findings(sight: dict) -> List[Tuple[str, str]]:
    """(level, text) from a junction's splay record (Piece.params of 'splays', plus 'obstructions' if checked)."""
    out = []
    if not sight:
        return out
    if not sight.get("criteria_has"):
        return [("info", "the design criteria have no junction sight table: no visibility splays drawn")]
    v = sight.get("speed_used")
    if sight.get("speed_assumed"):
        out.append(("info", f"main road design speed not known: splays drawn for {v:.0f} km/h; set it on the tab"))
    for r in sight.get("splays", []):
        what = "approach (give way)" if r["kind"] == "approach" else "stop"
        way = "up the chainage" if r["dir"] == "up" else "down the chainage"
        lvl = "issue" if r["kind"] == "stop" else "check"
        if r["short"]:
            out.append(("info", f"{what} splay {way}: the main road ends {r['available']:.0f} m from the junction, "
                                f"short of {r['length']:.0f} m; check the sight line beyond it on site"))
        if r["profile"] is not None and r["profile"] < r["length"] - 1e-6:
            out.append((lvl, f"{what} sight distance {way} is about {r['profile']:.0f} m on the main road's profile, "
                             f"under {r['length']:.0f} m at {v:.0f} km/h ({sight.get('ref', '')})"))
    if "checked" in sight and not sight["checked"]:
        out.append(("info", "visibility splays not checked against obstruction layers (buildings, trees, fences); "
                            "tick them on the Junctions + bays tab and press Check splays"))
    for o in sight.get("obstructions", []):
        if o["kind"] == "minor":
            continue                                   # reported with the approach splay
        what = "approach (give way)" if o["kind"] == "approach" else "stop"
        lvl = "issue" if o["kind"] == "stop" else "check"
        out.append((lvl, f"{o['layer']} feature {o['fid']} is inside the {what} visibility splay "
                         f"{'up' if o['dir'] == 'up' else 'down'} the chainage ({sight.get('ref', '')})"))
    return out


def place_roundabout(al, x: float, y: float, **kw) -> Placement:
    """Placement of a roundabout centred on our road at the point nearest (x, y)."""
    so = al.station_offset(x, y)
    if not so.in_range:
        raise ValueError("Beyond the alignment ends")
    _, _, h = al.point_at(so.station)
    return Placement(so.station, h + math.pi / 2, role="roundabout", **kw)


def roundabout_arms(al, pl: Placement, P: dict) -> List[dict]:
    """Our road's arms (recomputed from the alignment, so they follow a redesign) plus the stored ones."""
    from . import roundabouts as RB
    icd = float(P.get("icd") or RB.min_icd(float(P.get("island") or RB.DEFAULTS["island"])))
    x, y, _ = al.point_at(pl.station)
    ours = RB.auto_arms(al, x, y, icd / 2)
    stored = [dict(a, bearing=math.radians(a["bearing_deg"])) for a in (P.get("arms") or [])]
    return RB.merge_arms(ours + stored)


def _roundabout(F: Frame, spec, P, piece) -> Piece:
    from . import roundabouts as RB
    from .autoplace import advance_distance
    from .criteria import DEFAULT_ID, Criteria
    from .features import visible_from
    al, pl = F.al, F.pl
    arms = roundabout_arms(al, pl, P)
    O = F.p0
    raw, q, detail, PP = RB.build(O, arms, P)
    parts = [Part(code, pts, closed) for code, pts, closed in raw]
    notes = RB.checks(arms, PP, q)
    paths = RB.entry_paths(O, arms, PP, q)
    v_here = al.speed_at(pl.station) or 80.0
    compact = RB.COMPACT_ICD[0] <= q["icd"] <= RB.COMPACT_ICD[1] and v_here <= 70.0
    notes += RB.entry_path_checks(paths, q, compact)
    q["entry_path_r"] = [round(p["radius"], 1) if p["radius"] != math.inf else None for p in paths]
    crit = Criteria.load(P.get("criteria") or DEFAULT_ID)
    for d in detail:                                   # our approaches: the entry seen from the SSD (10.4.4)
        if d["src"] != "ours" or d["station"] is None:
            continue
        inbound = 1 if d["station"] < pl.station else -1
        v = al.speed_at(d["station"] - inbound * 50.0) or 80.0
        need = crit.ssd(v)
        seen = visible_from(al, d["station"], need, inbound, crit.eye_height, crit.object_height)
        d["speed"], d["advance"] = v, advance_distance(v)
        if seen is not None and seen < need - 1e-6:
            notes.append(("check", f"the entry from {'behind' if inbound > 0 else 'ahead along'} the chainage is seen "
                                   f"from about {seen:.0f} m on the profile, under the stopping sight distance of "
                                   f"{need:.0f} m at {v:.0f} km/h; a roundabout should not sit on a sharp crest "
                                   f"(RDM 1.3 10.4.4)"))
    P = dict(PP, kind="roundabout", notes=notes, quantities=q, detail=detail, n_arms=len(arms),
             arms_used=[{"bearing_deg": round(math.degrees(a["bearing"]), 2), "src": a["src"]} for a in arms])
    return Piece(piece, spec["name"], "roundabout", "", parts, q, P)


ACCESS_CONTROL_FULL = ("A", "B", "UA", "UC")      # RDM 1.3 Tables 2.3 and 2.4: desirable full access control


def _shoulder_edge(F: Frame) -> float:
    """Offset of the outer shoulder edge on the minor road's side (the access starts there), else the ETW."""
    from .corridor import SHOULDER
    e = getattr(F.al, "edges", None)
    if e:
        for code in SHOULDER:
            o = e.offset(code, F.side, F.pl.station)
            if o is not None:
                return abs(o)
    return F.e


def _access(F: Frame, spec, P, piece) -> Piece:
    """Private access to RDM 1.3 Figure 9.33: formation (paved width + shoulders) with kerb-line returns of the
    given radius from the shoulder edge, paved edges, the run to the boundary and a taper to the existing
    access, and an indicative pipe across its mouth. Not scaled. Local frame: x along the chainage on the road
    edge, y away from the road towards the access."""
    W, sh, R = float(P["width"]), float(P["shoulder"]), float(P["radius"])
    Lb, tp = float(P["length"]), float(P.get("taper") or 0.0)
    ex_w = float(P.get("existing") or W)
    e = _shoulder_edge(F)
    o = (F.p0[0] + e / F.sin * F.d[0], F.p0[1] + e / F.sin * F.d[1])
    ex_, ey_ = F.t, (-F.t[1] * F.sigma, F.t[0] * F.sigma)

    def Wd(x, y):
        return (o[0] + x * ex_[0] + y * ey_[0], o[1] + x * ex_[1] + y * ey_[1])

    dx, dy = F.d[0] * ex_[0] + F.d[1] * ex_[1], F.d[0] * ey_[0] + F.d[1] * ey_[1]
    w2, we2 = W / 2 + sh, ex_w / 2 + sh
    sides, notes, mouth = {}, [], []
    for sgn in (1, -1):
        n = (sgn * dy, -sgn * dx)
        p0 = (n[0] * w2, n[1] * w2)
        cx = p0[0] + (R - (R - p0[1]) * n[1]) / n[0]
        c, t1, t2 = (cx, R), (cx, 0.0), (cx - R * n[0], R - R * n[1])
        a0, a1 = math.atan2(t1[1] - R, t1[0] - cx), math.atan2(t2[1] - R, t2[0] - cx)
        while a1 - a0 > math.pi:
            a1 -= 2 * math.pi
        while a0 - a1 > math.pi:
            a1 += 2 * math.pi
        arc = _arc(c, R, a0, a1, 16)
        k2 = (t2[0] - p0[0]) * dx + (t2[1] - p0[1]) * dy
        s_end = (Lb - p0[1]) / dy                        # the formation edge reaches the boundary line
        if s_end <= k2:
            notes.append(("check", f"the returns (R {R:g} m) run past the boundary line {Lb:g} m from the road edge"))
            s_end = k2
        pts = arc + [(p0[0] + s_end * dx, p0[1] + s_end * dy)]
        if tp > 0:
            q = (n[0] * we2, n[1] * we2)
            pts.append((q[0] + (s_end + tp / dy) * dx, q[1] + (s_end + tp / dy) * dy))
        sides[sgn] = pts
        mouth.append((k2, n))
    parts = [Part("ACCESS", [Wd(*p) for p in sides[sgn]]) for sgn in (1, -1)]
    k0 = max(k for k, _ in mouth)
    for sgn in (1, -1):                                  # paved edges, from the mouth to the end of the taper
        n = (sgn * dy, -sgn * dx)
        s_end = (Lb - n[1] * W / 2) / dy
        pv = [(n[0] * W / 2 + k0 * dx, n[1] * W / 2 + k0 * dy), (n[0] * W / 2 + s_end * dx, n[1] * W / 2 + s_end * dy)]
        if tp > 0:
            pv.append((n[0] * ex_w / 2 + (s_end + tp / dy) * dx, n[1] * ex_w / 2 + (s_end + tp / dy) * dy))
        parts.append(Part("ACCESS-P", [Wd(*p) for p in pv]))
    q = {}
    if P.get("pipe", True):                              # across the mouth, formation width plus 0.5 m each end
        hl, t0 = w2 + 0.5, 0.6
        nn = (dy, -dx)
        ring = [(nn[0] * a + (k0 + b) * dx, nn[1] * a + (k0 + b) * dy) for a, b in ((-hl, 0), (hl, 0), (hl, t0), (-hl, t0))]
        parts.append(Part("PIPE", [Wd(*p) for p in ring], True))
        q.update(pipe_no=1, pipe_m=round(2 * hl, 2))
    outline = sides[1] + list(reversed(sides[-1]))
    q.update(area_m2=round(area(outline), 1), edge_m=round(sum(length(p.pts) for p in parts if p.code == "ACCESS"), 1))
    if W < 3.0 - 1e-9:
        notes.append(("issue", f"access {W:g} m wide; at least 3 m (RDM 1.3 9.11.16)"))
    if R < 6.0 - 1e-9:
        notes.append(("check", f"entry / exit radius {R:g} m; 6 m or more for the turning traffic (RDM 1.3 9.11.16)"))
    if Lb < 10.0 - 1e-9:
        notes.append(("check", f"access built {Lb:g} m back from the road edge; at least 10 m to the fence or boundary "
                               f"line (RDM 1.3 Figure 9.33)"))
    rc = (P.get("road_class") or "").upper()
    if rc in ACCESS_CONTROL_FULL:
        notes.append(("check", f"private access on a class {rc} road: desirable full access control, no direct private "
                               f"accesses (RDM 1.3 Tables 2.3 and 2.4); group accesses or use a service road where "
                               f"possible"))
    P = dict(P, kind="access", edge_offset=round(e, 3), notes=notes, quantities=q)
    return Piece(piece, spec["name"], "access", "", parts, q, P)


BAY_PIECES = ("bus_bay", "truck_bay", "climbing_lane")
BAY_KINDS = {"bus_bay": "bus bay", "truck_bay": "truck parking bay", "climbing_lane": "climbing lane"}


def bay_stations(al, pl: Placement, P: dict, sigma: int):
    """(entry start, bay start, bay end, exit end, travel direction) in chainage. Kenya drives on the left:
    traffic on the left of the chainage direction travels with it, so its entry taper comes first."""
    dirn = 1 if sigma > 0 else -1
    v = al.speed_at(pl.station) or 80.0
    A = P.get("entry") or (25.0 if v <= 50 else 30.0)
    s1 = pl.station
    s2 = s1 + dirn * P["bay"]
    return s1 - dirn * A, s1, s2, s2 + dirn * P["exit"], dirn, A


WIDEN_TOL = 0.3          # m: corridor edge vs planned widening (round-trip check); also "the corridor is widened"
BASE_REACH = 60.0        # m: how far outside a bay to look for the corridor section that gives the base edge


def widen_at(t: float, A: float, B: float, C: float, depth: float, straight: bool = False) -> float:
    """Widening beyond the base edge, t metres into the bay in the direction of travel from the start of the
    entry taper: entry taper A, full width B, exit taper C (cosine tapers, or straight ones)."""
    if t <= 0:
        return 0.0
    if t < A:
        return depth * t / A if straight else depth * (1 - math.cos(math.pi * t / A)) / 2
    if t <= A + B:
        return depth
    u = t - A - B
    if u >= C:
        return 0.0
    return depth * (1 - u / C) if straight else depth * (1 + math.cos(math.pi * u / C)) / 2


EDGE_CODES = ("ETW", "EOP", "EP", "EOTW", "EdgeOfPavement", "Edge")     # carriageway edge, in order of preference


def edge_code(al, side: str, prefer: Optional[str] = None) -> Optional[str]:
    """The corridor's carriageway edge code on a side: `prefer` if the corridor has it, else the first of
    EDGE_CODES it has (Civil 3D subassemblies name the edge differently); None without edges."""
    e = getattr(al, "edges", None)
    if not e:
        return None
    for code in ((prefer,) if prefer else ()) + EDGE_CODES:
        if e.data.get((code, side)):
            return code
    return None


def base_edge(al, side: str, lo: float, hi: float, code: str = "ETW", threshold: float = WIDEN_TOL):
    """The corridor edge before a widening between stations lo and hi: (f(station) -> offset or None, widened).
    Where the corridor's sections inside lo..hi stand out from the line between the nearest sections outside
    them (by more than `threshold`), the widening is already in the corridor and that line is the base edge;
    otherwise the corridor edge itself is used (curve widening and the like stay as they are)."""
    e = getattr(al, "edges", None)
    pts = (e.data.get((code, side)) if e else None) or []
    if not pts:
        return (lambda s: None), False
    before = [p for p in pts if lo - BASE_REACH <= p[0] < lo - 1e-6]
    after = [p for p in pts if hi + 1e-6 < p[0] <= hi + BASE_REACH]
    inside = [p for p in pts if lo - 1e-6 <= p[0] <= hi + 1e-6]
    a, b = (before[-1] if before else None), (after[0] if after else None)
    if a is None and b is None:
        return (lambda s: e.offset(code, side, s)), False
    if a is None or b is None:
        c = (a or b)[1]
        line = lambda s: c
    else:
        line = lambda s: a[1] + (b[1] - a[1]) * (s - a[0]) / (b[0] - a[0])
    widened = any(o - line(st) > threshold for st, o in inside)
    if widened:
        return line, True
    return (lambda s: e.offset(code, side, s)), False


def _disp(al, sta: float) -> str:
    from .alignment import format_station
    return format_station(al.display_station(sta), 1)


def widening_check(al, bay: dict) -> List[Tuple[str, str]]:
    """Round trip: the corridor (re-imported from Civil 3D) against a placed bus bay, truck bay or climbing lane.
    bay: the stored record (stations, side, depth, entry, exit, taper, kind)."""
    e = getattr(al, "edges", None)
    kind = bay.get("kind", "bus bay")
    code = edge_code(al, bay["side"], bay.get("edge_code"))
    pts = (e.data.get((code, bay["side"])) if e and code else None) or []
    if not pts:
        return [("info", f"{kind}: the corridor has no carriageway edge ({', '.join(EDGE_CODES)}) on that side, so "
                         f"the widening cannot be compared")]
    s0, s1, s2, s3 = bay["stations"]
    dirn = 1 if s3 >= s0 else -1
    A, C, depth = float(bay["entry"]), float(bay["exit"]), float(bay["depth"])
    B = abs(s2 - s1)
    lo, hi = sorted((s0, s3))
    base, widened = base_edge(al, bay["side"], lo, hi, code)
    inside = [(st, o) for st, o in pts if lo - 1e-6 <= st <= hi + 1e-6]
    if not inside:
        return [("info", f"{kind}: no corridor section inside it, so the widening cannot be compared")]
    if not widened:
        return [("info", f"{kind}: not in the corridor yet; build the widening in Civil 3D from the Widenings table "
                         f"and re-import the LandXML to check it")]
    devs = []
    for st, o in inside:
        b = base(st)
        if b is None:
            continue
        want = b + widen_at((st - s0) * dirn, A, B, C, depth, bay.get("taper") == "straight")
        devs.append((abs(o - want), st, o - b, want - b))
    if not devs:
        return []
    worst = max(devs)
    if worst[0] > WIDEN_TOL:
        return [("check", f"{kind}: the corridor's widening differs from the placed one by up to {worst[0]:.2f} m "
                          f"(corridor {worst[2]:.2f} m, placed {worst[3]:.2f} m at the section at {_disp(al, worst[1])}); "
                          f"adjust the corridor or the {kind}")]
    return [("info", f"{kind}: matches the corridor within {WIDEN_TOL:g} m at {len(devs)} section(s)")]


# a plain stroke font for the word markings (unit box: x across 0-1, y along the road 0-1, elongated letters)
GLYPHS = {
    "B": [[(0, 0), (0, 1), (0.7, 1), (1, 0.85), (1, 0.62), (0.7, 0.5), (0, 0.5)],
          [(0.7, 0.5), (1, 0.38), (1, 0.15), (0.7, 0), (0, 0)]],
    "U": [[(0, 1), (0, 0.2), (0.25, 0), (0.75, 0), (1, 0.2), (1, 1)]],
    "S": [[(1, 0.85), (0.75, 1), (0.25, 1), (0, 0.85), (0, 0.62), (0.25, 0.5), (0.75, 0.5), (1, 0.38), (1, 0.15),
           (0.75, 0), (0.25, 0), (0, 0.15)]],
    "T": [[(0, 1), (1, 1)], [(0.5, 1), (0.5, 0)]],
    "O": [[(0.25, 0), (0.75, 0), (1, 0.2), (1, 0.8), (0.75, 1), (0.25, 1), (0, 0.8), (0, 0.2), (0.25, 0)]],
    "P": [[(0, 0), (0, 1), (0.75, 1), (1, 0.85), (1, 0.62), (0.75, 0.5), (0, 0.5)]],
}
WORD_STROKE = 0.2                   # m: painted stroke of a 2.5 m letter (indicative, for the painted area)


def word_strokes(word: str, h: float) -> List[List[Pt]]:
    """A word marking as stroke polylines, centred on x = 0 (across the lane), y from 0 to h (along the road)."""
    w, gap = 0.15 + 0.16 * h, 0.15 * h / 2.5 + 0.05
    total = len(word) * w + (len(word) - 1) * gap
    out = []
    for i, ch in enumerate(word):
        x0 = -total / 2 + i * (w + gap)
        for stroke in GLYPHS[ch]:
            out.append([(x0 + x * w, y * h) for x, y in stroke])
    return out


def _bus_bay(F: Frame, spec, P, piece) -> Piece:
    al, sg = F.al, (-1 if F.sigma > 0 else 1)                  # sg: sign of offsets on the bay's side (+ right)
    s0, s1, s2, s3, dirn, A = bay_stations(al, F.pl, P, F.sigma)
    lane, truck = piece == "climbing_lane", piece == "truck_bay"
    straight = P.get("taper") == "straight"
    # the edge before the widening: the corridor's ETW, or the line under it where the re-imported corridor
    # already carries the widening (so the bay does not widen twice)
    ecode = edge_code(al, "L" if sg < 0 else "R", P.get("edge_code")) or "ETW"
    base, _ = base_edge(al, "L" if sg < 0 else "R", *sorted((s0, s3)), ecode,
                        threshold=max(WIDEN_TOL, 0.5 * float(P.get("depth") or 3.0)))
    if lane and not P.get("depth"):                            # as wide as the reduced through lane (6.6.3)
        e0 = base(s1)
        e0 = abs(e0) if e0 is not None else F.e
        P = dict(P, depth=round(e0 - 0.25 if e0 >= 3.25 else e0, 2))
    depth, plat, ramp = P["depth"], P.get("platform", 0.0), P.get("ramp", 0.0)

    def edge(s):
        o = base(s)
        return abs(o) if o is not None else F.e

    def widen(s):                                              # widening beyond the edge
        return widen_at((s - s0) * dirn, A, P["bay"], P["exit"], depth, straight)

    lo, hi = sorted((s0, s3))
    lo, hi = max(lo, al.sta_start), min(hi, al.sta_end)
    n = max(2, int((hi - lo) / 1.0))
    ss = sorted(set([lo + (hi - lo) * i / n for i in range(n + 1)] + [x for x in (s1, s2) if lo < x < hi]))
    pt = lambda s, o: al.point_at(s, sg * o)[:2]
    kerb = [pt(s, edge(s) + widen(s)) for s in ss]
    if lane:
        # RDM/1/3/3/02: the widened pavement edge with its tapers, the edge line along it, and the broken
        # lane line along the old edge over the full width
        parts = [Part("BAYEDGE", kerb), Part("LM26", kerb)]
        b0, b1 = sorted((s1, s2))
        s = max(b0, al.sta_start)
        while s + 2.0 <= min(b1, al.sta_end):
            parts.append(Part("LM03", [pt(s, edge(s)), pt(s + 2.0, edge(s + 2.0))]))
            s += 8.0
        widen_area = sum((widen(a) + widen(b)) / 2 * (b - a) for a, b in zip(ss, ss[1:]))
        lm = {c: sum(length(p.pts) for p in parts if p.code == c) for c in ("LM26", "LM03")}
        q = {"edge_m": round(length(kerb), 2), "widen_m2": round(widen_area, 2), "LM26_m": round(lm["LM26"], 2),
             "LM03_m": round(lm["LM03"], 2),
             "paint_m2": round((lm["LM26"] + lm["LM03"]) * 0.1, 3)}
        P = dict(P, entry=A, stations=[round(x, 3) for x in (s0, s1, s2, s3)], side="L" if sg < 0 else "R",
                 kind="climbing lane", edge_code=ecode)
        return Piece(piece, spec["name"], "lane", "", parts, q, P)
    widen_area = sum((widen(a) + widen(b)) / 2 * (b - a) for a, b in zip(ss, ss[1:]))
    sep = []                                   # separation line along the carriageway edge, 1 m marks, 1 m gaps
    s = lo
    while s + 1.0 <= hi:
        sep.append(Part("LM05", [pt(s, edge(s)), pt(s + 1.0, edge(s + 1.0))]))
        s += 2.0
    lm05 = sum(length(p.pts) for p in sep)
    if truck:
        # RDM/1/3/3/03: widened pavement, no kerb shown; the separation line from start point to end point
        parts = [Part("BAYEDGE", kerb)] + sep
        q = {"edge_m": round(length(kerb), 2), "widen_m2": round(widen_area, 2), "LM05_m": round(lm05, 2),
             "paint_m2": round(lm05 * 0.2, 3)}
        P = dict(P, entry=A, stations=[round(x, 3) for x in (s0, s1, s2, s3)], side="L" if sg < 0 else "R",
                 kind=BAY_KINDS[piece], taper=P.get("taper"), edge_code=ecode)
        return Piece(piece, spec["name"], "bay", "", parts, q, P)
    parts = [Part("KERB", kerb)]
    # loading platform behind the kerb along the bay, hatched
    b0, b1 = sorted((s1, s2))
    bs = [b0 + (b1 - b0) * i / 20 for i in range(21)]
    plat_ring = [pt(s, edge(s) + depth) for s in bs] + [pt(s, edge(s) + depth + plat) for s in reversed(bs)]
    parts.append(Part("BUSPLAT", plat_ring, True))
    for k in range(1, int((b1 - b0) / 1.0)):
        s = b0 + k * 1.0
        parts.append(Part("BUSPLAT", [pt(s - 0.5, edge(s) + depth), pt(s + 0.5, edge(s) + depth + plat)]))
    parts += sep
    # BUS STOP word marking in each 15 m box of the bay (RDM 6.1 10.3, letters per Table 6.2), read in the
    # direction of travel: BUS nearer the approaching driver, STOP beyond it
    if P.get("word", True) and abs(b1 - b0) >= 10.0:
        v = al.speed_at((b0 + b1) / 2) or 50.0
        h = 1.25 if v <= 50 else 2.5
        boxes = max(1, int(abs(b1 - b0) // 15.0))
        box = abs(b1 - b0) / boxes
        o_mid = lambda st: edge(st) + depth / 2
        first = b0 if dirn > 0 else b1
        for k in range(boxes):
            centre = first + dirn * box * (k + 0.5)
            for word, back in (("BUS", -(h + 0.5)), ("STOP", 0.5)):
                for stroke in word_strokes(word, h):
                    # glyph x to the reader's right (dirn sign on the right-positive offset), y up = travel
                    parts.append(Part("WM-BUSSTOP", [al.point_at(centre + dirn * (back + y), sg * o_mid(centre)
                                                                 + dirn * x)[:2] for x, y in stroke]))
    # indicative shelter position behind the platform, mid-bay
    if P.get("shelter"):
        m, L = (b0 + b1) / 2, P["shelter"] / 2
        o0, o1 = edge(m) + depth + plat + 0.5, edge(m) + depth + plat + 2.5
        parts.append(Part("SHELTER", [pt(m - L, o0), pt(m + L, o0), pt(m + L, o1), pt(m - L, o1)], True))
    wm = sum(length(p.pts) for p in parts if p.code == "WM-BUSSTOP")
    q = {"kerb_m": round(length(kerb), 2), "raised_kerb_m": round(abs(s2 - s1) + 2 * ramp, 2),
         "WM-BUSSTOP_m": round(wm, 2), "WM-BUSSTOP_no": max(1, int(abs(s2 - s1) // 15.0)) if wm else 0,
         "island_m2": round(area(plat_ring), 2), "widen_m2": round(widen_area, 2),
         "LM05_m": round(lm05, 2), "paint_m2": round(lm05 * 0.2 + wm * WORD_STROKE, 3)}
    P = dict(P, entry=A, stations=[round(x, 3) for x in (s0, s1, s2, s3)], side="L" if sg < 0 else "R",
             kind="bus bay", edge_code=ecode)
    return Piece(piece, spec["name"], "bay", "", parts, q, P)


GRADE_LIMITS = [(4.0, 900.0), (5.0, 800.0), (6.0, 700.0), (7.0, 600.0), (8.0, 500.0)]   # RDM 1.3 Table 6.6


def grade_limit(g: float) -> Optional[float]:
    """Maximum length of an up-grade before trucks slow by more than 15 km/h (RDM 1.3 Table 6.6); None: no limit."""
    g = abs(g)
    if g <= 3.0:
        return None
    if g <= 4.0:
        return 900.0 + (4.0 - g) * 1000.0         # towards "no limit" at 3 %: indicative
    for (g0, l0), (g1, l1) in zip(GRADE_LIMITS, GRADE_LIMITS[1:]):
        if g <= g1:
            return l0 + (g - g0) / (g1 - g0) * (l1 - l0)
    return 500.0 * 8.0 / g


RECOVERY = 300.0                    # m: a truck regains its speed over about this much level road (indicative)


def climbing_lanes(al, aadt: Optional[float] = None, merge: float = 200.0, step: float = 5.0,
                   join: float = 150.0) -> List[dict]:
    """Climbing lanes the profile asks for (RDM 1.3 6.6), on the uphill traffic's left (Kenya drives on the
    left). AADT under 2000 pcu: none (6.6.2).

    The truck's speed loss is followed along the design profile, vertical curves included, rather than
    grade by grade: every metre on an up-grade over 3 % uses 1 / (its Table 6.6 length) of the allowance,
    and ground of 3 % or less (no limit in Table 6.6) gives it back over RECOVERY m.
    A lane starts where the allowance runs out and ends `merge` m past the end of that climb (the allowance
    cannot run below the truck's crawl speed); consecutive steep grades therefore count together, and lanes
    less than `join` m apart are joined into one."""
    pr = getattr(al, "profile", None)
    if pr is None or not pr.pvis or (aadt is not None and aadt < 2000):
        return []
    lo, hi = max(al.sta_start, pr.start), min(al.sta_end, pr.end)
    if hi - lo < step:
        return []
    n = int((hi - lo) / step)
    ss = [lo + (hi - lo) * k / n for k in range(n + 1)]
    note = ("consider: AADT 2000-6000 pcu with limited passing" if aadt is not None and aadt <= 6000
            else "normally required above 6000 pcu AADT" if aadt is not None else "AADT not given")
    out = []
    for d, side in ((1, "L"), (-1, "R")):                  # traffic with the chainage, then against it
        seq = ss if d > 0 else ss[::-1]
        use, lanes, cur, climb = 0.0, [], None, 0.0
        for a, b in zip(seq, seq[1:]):
            g = (pr.grade((a + b) / 2) or 0.0) * d
            ds = abs(b - a)
            lim = grade_limit(g) if g > 0 else None
            if lim is not None:
                use = min(1.0, use + ds / lim)               # at most: the truck down to its crawl speed
                climb += ds                                  # steep metres since the truck last recovered
            else:
                use = max(0.0, use - ds / RECOVERY)          # 3 % or less: no limit in Table 6.6
                if use == 0.0:
                    climb = 0.0
            if use >= 1.0 and cur is None:
                cur = {"start": b, "climb_end": b, "gmax": g, "steep": climb - (ds if lim is not None else 0.0)}
            if cur is not None:
                if lim is not None:
                    cur["climb_end"] = b
                    cur["gmax"] = max(cur["gmax"], g)
                    cur["steep"] += ds
                elif abs(b - cur["climb_end"]) >= merge:     # the lane ends `merge` m past its climb
                    lanes.append(cur)
                    cur = None
        if cur is not None:
            lanes.append(cur)
        joined = []
        for ln in lanes:
            if joined and abs(ln["start"] - joined[-1]["climb_end"]) - merge < join:
                joined[-1].update(climb_end=ln["climb_end"], gmax=max(joined[-1]["gmax"], ln["gmax"]),
                                  steep=joined[-1]["steep"] + ln["steep"], joined=True)
            else:
                joined.append(dict(ln))
        for ln in joined:
            end = ln["climb_end"] + d * merge
            end = min(max(end, al.sta_start), al.sta_end)
            out.append({"start": round(ln["start"] / 10.0) * 10.0, "end": round(end / 10.0) * 10.0, "side": side,
                        "grade": round(ln["gmax"] * d, 2), "length": round(ln["steep"], 1),
                        "limit": round(grade_limit(ln["gmax"]), 1), "note": note
                        + ("; consecutive steep grades taken together" if ln.get("joined") else "")})
    return sorted(out, key=lambda c: min(c["start"], c["end"]))


def place_lane(al, start: float, end: float, side: str, **kw):
    """A climbing lane between two stations (full width) on a side, as a placement plus its length."""
    s = min(max(start, al.sta_start), al.sta_end)
    _, _, h = al.point_at(s)
    bearing = h + (math.pi / 2 if side == "L" else -math.pi / 2)
    return Placement(s, bearing, role="bay", **kw), abs(end - start)


def bay_table(al, rows) -> List[dict]:
    """Widening table for Civil 3D, one row per bay or lane: (entry start, bay start, bay end, exit end, side, width)."""
    out = []
    for r in rows:
        s0, s1, s2, s3 = r["stations"]
        a, b = sorted((s0, s3))
        out.append({"side": r["side"], "start": a, "end": b, "full_from": min(s1, s2), "full_to": max(s1, s2),
                    "entry": r["entry"], "exit": r["exit"], "width": r["depth"]})
    return out


def _main_edge(F: Frame, X: float) -> Pt:
    sta = min(max(F.pl.station + X * F.s, F.al.sta_start), F.al.sta_end)
    x, y, _ = F.al.point_at(sta, -F.sigma * F.e)
    return (x, y)


def build_kit(al, pl: Placement, jtype: str, templates: Optional[dict] = None,
              guides: bool = True, splays: bool = True, splay: Optional[dict] = None,
              second_leg: bool = False) -> List[Piece]:
    """second_leg: the other approach of a crossroads, so the main-road pieces (ghost islands), already
    drawn for the first leg, are left out."""
    T = templates or load_templates()
    out = []
    for item in kit_items(T, jtype, guides, splays, second_leg):
        prm = dict(item.get("params") or {}, **(splay or {})) if item["piece"] == "splays" else item.get("params")
        out.append(build_piece(al, pl, item["piece"], item.get("corner", ""), prm, T))
    return out


def kit_edge_add(T: dict, jtype: str) -> float:
    """How far a kit's main-road widening moves the edge on the minor road's side (half its width)."""
    for it in T["kits"].get(jtype, []):
        if it["piece"] == "main_widening":
            return float(dict(T["pieces"]["main_widening"]["params"], **(it.get("params") or {}))["width"]) / 2
    return 0.0


def with_edge_add(T: dict, jtype: str, item: dict) -> dict:
    """The kit item with the kit's edge widening passed to pieces off the main road."""
    item = dict(item)
    ea = kit_edge_add(T, jtype)
    if ea and T["pieces"][item["piece"]]["frame"] != "main" and item["piece"] != "main_widening":
        item["params"] = dict(item.get("params") or {}, edge_add=ea)
    return item


def kit_items(T: dict, jtype: str, guides: bool = True, splays: bool = True, second_leg: bool = False) -> List[dict]:
    """The kit's items as placed: without guides / splays when switched off, without the main-road pieces
    on the second leg of a crossroads, and with the kit's main-road widening passed to the others."""
    return [with_edge_add(T, jtype, it) for it in T["kits"][jtype]
            if (guides or it["piece"] != "guides") and (splays or it["piece"] != "splays")
            and not (second_leg and T["pieces"][it["piece"]]["frame"] in ("main",) )]


def findings(al, pl: Placement) -> List[Tuple[str, str]]:
    """al: the main road's alignment (main_alignment)."""
    """(level, text) about the placement: skew to RDM 1.3 9.2.3, junction near the alignment ends."""
    out = []
    if pl.role in ("bay", "roundabout"):
        return out
    F = pl.frame(al)
    ang = F.crossing_angle
    if ang < SKEW_MINIMUM:
        out.append(("issue", f"crossing angle {ang:.0f} deg is beyond the absolute minimum of {SKEW_MINIMUM:.0f} deg "
                             f"(RDM 1.3 9.2.3); realign the minor road"))
    elif ang < SKEW_PREFERRED[0]:
        out.append(("check", f"crossing angle {ang:.0f} deg: preferably 75-120 deg; the designer should justify "
                             f"a skew under 75 deg (RDM 1.3 9.2.3)"))
    if pl.role == "bay":
        return out
    if min(pl.station - al.sta_start, al.sta_end - pl.station) < 60:
        out.append(("info", "junction within 60 m of the alignment end: main-road pieces are cut at the end"))
    return out


def skew_degrees(al, pl: Placement) -> float:
    """Departure from square, degrees (0 = square, positive when the minor road leans along the chainage)."""
    return round(90.0 - pl.frame(al).angle, 1)


# --------------------------------------------------------------------------- junction warning signs
JUNCTION_KITS = ("A-1", "A-2", "B", "B-Mod", "C")
SIGNAL_KITS = ("SIG",)
WARN_CODES = ("W1", "W2", "W5", "W11", "W12", "W46")
CROSS_TOL = 10.0                    # m: side roads on opposite sides closer than this make a crossroads
STAGGER = 60.0                      # m: RDM 6.2 4.2.1 - staggered crossroads sign where junctions are this close


@dataclass
class JunctionAt:
    """What the warning signs need to know of a placed junction (see JunctionStore.warning_inputs)."""
    id: str
    role: str                       # main: a side road on our road; minor: our road meets a greater road
    station: float                  # on our road
    side: str = "L"                 # main role: side of the side road (L / R of the chainage direction)
    up: bool = True                 # minor role: our leg runs towards higher chainage from the junction
    crossing: bool = False          # minor role: our road crosses the main road (crossroads)
    kit: str = ""


def junction_warnings(al, junctions: Sequence[JunctionAt], speed=None) -> List["object"]:
    """Junction Ahead warning signs (RDM 6.2 4.2) for the junctions on our road, as autoplace Proposals
    with the rule junction:<id>:

    - our road is the main road (4.2.1): W2 Side Road for a side road (mirrored for one on the traveller's
      left), W1 Crossroads where side roads leave on both sides within 10 m, W5 Staggered Crossroads where
      they are on opposite sides within 60 m;
    - our road meets a road of greater importance (4.2.3): W12 T Junction, or W11 Crossroads where our road
      crosses it, on our approach.
    Each sign stands the RDM 6.2 2.4 advance distance before the junction, on the left of the traffic."""
    from .autoplace import Proposal, advance_distance
    out = []
    v_at = speed or (lambda s: al.speed_at(s) or 80.0)
    for j in junctions:                                     # signals: W46 on our approaches (RDM 6.2)
        if j.kit not in SIGNAL_KITS:
            continue
        dirs = (1, -1) if j.role == "main" or j.crossing else ((-1,) if j.up else (1,))
        a = advance_distance(v_at(j.station))
        for d in dirs:
            s = j.station - d * a
            if al.sta_start <= s <= al.sta_end:
                out.append(Proposal("W46", s, "L" if d > 0 else "R", "Forward" if d > 0 else "Backward",
                                    f"junction:{j.id}", f"Traffic signals {a:.0f} m ahead (RDM 6.2)"))
    junctions = [j for j in junctions if j.kit not in SIGNAL_KITS]
    main = sorted([j for j in junctions if j.role == "main" and j.kit in JUNCTION_KITS], key=lambda j: j.station)
    for d in (1, -1):                                       # 1: traffic in the chainage direction
        seq = main if d > 0 else main[::-1]
        used = set()
        for i, j in enumerate(seq):
            if j.id in used:
                continue
            nxt = next((k for k in seq[i + 1:] if abs(k.station - j.station) <= STAGGER), None)
            group = [j]
            if nxt is not None and nxt.side != j.side:
                group.append(nxt)
            used.update(k.id for k in group)
            # side as the traveller sees it: L of the chainage direction is the left of forward traffic
            left = (j.side == "L") == (d > 0)
            if len(group) == 2 and abs(group[1].station - j.station) <= CROSS_TOL:
                code, mirror, what = "W1", False, "Crossroads"
            elif len(group) == 2:
                code, mirror, what = "W5", not left, "Staggered crossroads (first side road on the " \
                                                     f"{'left' if left else 'right'})"
            else:
                code, mirror, what = "W2", left, f"Side road on the {'left' if left else 'right'}"
            sta0 = j.station
            a = advance_distance(v_at(sta0))
            s = sta0 - d * a
            if not (al.sta_start <= s <= al.sta_end):
                continue
            out.append(Proposal(code, s, "L" if d > 0 else "R", "Forward" if d > 0 else "Backward",
                                f"junction:{j.id}", f"{what} {a:.0f} m ahead (RDM 6.2 4.2.1)", mirror))
    for j in junctions:
        if j.role != "minor":
            continue
        a = advance_distance(v_at(j.station))
        # traffic heading for the main road travels against the leg's direction
        s = j.station + a if j.up else j.station - a
        if not (al.sta_start <= s <= al.sta_end):
            continue
        code, what = ("W11", "Crossroads with a road of greater importance") if j.crossing else \
            ("W12", "T junction with a road of greater importance")
        out.append(Proposal(code, s, "R" if j.up else "L", "Backward" if j.up else "Forward",
                            f"junction:{j.id}", f"{what} {a:.0f} m ahead (RDM 6.2 4.2.3)"))
    return out
