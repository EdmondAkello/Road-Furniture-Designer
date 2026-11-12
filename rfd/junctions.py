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


def place(al, x0: float, y0: float, x1: float, y1: float, **kw) -> Placement:
    """Placement from two clicks: the junction point (snapped to the centreline) and a point up the minor road."""
    so = al.station_offset(x0, y0)
    sta = min(max(so.station, al.sta_start), al.sta_end)
    px, py, _ = al.point_at(sta)
    if math.hypot(x1 - px, y1 - py) < 1.0:
        raise ValueError("The second point must be at least 1 m up the minor road")
    return Placement(sta, math.atan2(y1 - py, x1 - px), **kw)


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


def place_minor(al, x0: float, y0: float, x1: Optional[float] = None, y1: Optional[float] = None,
                major=None, **kw) -> Tuple[Placement, object]:
    """Our road joins another road. (x0, y0): a click on our road where it meets the main road (snapped to
    our centreline). The main road is `major` (another alignment) or the direction from that point to
    (x1, y1). Returns the placement and the main road's alignment."""
    so = al.station_offset(x0, y0)
    s0 = min(max(so.station, al.sta_start), al.sta_end)
    px, py, _ = al.point_at(s0)
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
    # our road leaves the main road in the direction that takes it away from the main road's centreline
    step = min(15.0, max(2.0, (al.sta_end - al.sta_start) / 4))
    cand = []
    for sgn in (1, -1):
        s = min(max(s0 + sgn * step, al.sta_start), al.sta_end)
        if abs(s - s0) > 0.5:
            x, y, _ = al.point_at(s)
            cand.append((abs(main.station_offset(x, y).offset), math.atan2(y - jy, x - jx)))
    if not cand:
        raise ValueError("Our road is too short here")
    bearing = max(cand)[1]
    pl = Placement(ms, bearing, role="minor", main_ref=ref, our_station=s0, **kw)
    return pl, main


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
            for code in ("ETW", "EOP", "EP"):
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
        if code not in ("KERB", "GUIDE"):
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
    for sgn in (1, -1):
        n = (sgn * dy, -sgn * dx)                     # unit normal of the minor axis, +x side for sgn = 1
        p0 = (n[0] * w2, n[1] * w2)                   # a point on that minor edge, at the main edge
        # fillet centre: distance R from the main edge (y = R) and R outside the minor edge
        if abs(n[0]) < 1e-9:
            continue
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
        # minor edge from the tangent point outwards
        k = (t2[0] - p0[0]) * dx + (t2[1] - p0[1]) * dy
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
    return Piece(piece, spec["name"], "guide", "", parts, {}, P)


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
        what = "approach (give way)" if o["kind"] == "approach" else "stop"
        lvl = "issue" if o["kind"] == "stop" else "check"
        out.append((lvl, f"{o['layer']} feature {o['fid']} is inside the {what} visibility splay "
                         f"{'up' if o['dir'] == 'up' else 'down'} the chainage ({sight.get('ref', '')})"))
    return out


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


def _bus_bay(F: Frame, spec, P, piece) -> Piece:
    al, sg = F.al, (-1 if F.sigma > 0 else 1)                  # sg: sign of offsets on the bay's side (+ right)
    s0, s1, s2, s3, dirn, A = bay_stations(al, F.pl, P, F.sigma)
    lane, truck = piece == "climbing_lane", piece == "truck_bay"
    straight = P.get("taper") == "straight"
    if lane and not P.get("depth"):                            # as wide as the reduced through lane (6.6.3)
        e0 = F.e
        P = dict(P, depth=round(e0 - 0.25 if e0 >= 3.25 else e0, 2))
    depth, plat, ramp = P["depth"], P.get("platform", 0.0), P.get("ramp", 0.0)

    def edge(s):
        e = getattr(al, "edges", None)
        o = e.offset("ETW", "L" if sg < 0 else "R", s) if e else None
        return abs(o) if o is not None else F.e

    def widen(s):                                              # widening beyond the edge, smooth tapers
        t = (s - s0) * dirn
        if t <= 0:
            return 0.0
        if t < A:
            return depth * t / A if straight else depth * (1 - math.cos(math.pi * t / A)) / 2
        if t <= A + P["bay"]:
            return depth
        u = t - A - P["bay"]
        if u >= P["exit"]:
            return 0.0
        return depth * (1 - u / P["exit"]) if straight else depth * (1 + math.cos(math.pi * u / P["exit"])) / 2

    lo, hi = sorted((s0, s3))
    lo, hi = max(lo, al.sta_start), min(hi, al.sta_end)
    n = max(2, int((hi - lo) / 1.0))
    ss = sorted(set([lo + (hi - lo) * i / n for i in range(n + 1)] + [x for x in (s1, s2) if lo < x < hi]))
    pt = lambda s, o: al.point_at(s, sg * o)[:2]
    kerb = [pt(s, edge(s) + widen(s)) for s in ss]
    if lane:
        # new edge line along the widened edge, broken lane line along the old edge over the full width
        parts = [Part("LM26", kerb)]
        b0, b1 = sorted((s1, s2))
        s = max(b0, al.sta_start)
        while s + 2.0 <= min(b1, al.sta_end):
            parts.append(Part("LM03", [pt(s, edge(s)), pt(s + 2.0, edge(s + 2.0))]))
            s += 8.0
        widen_area = sum((widen(a) + widen(b)) / 2 * (b - a) for a, b in zip(ss, ss[1:]))
        lm = {c: sum(length(p.pts) for p in parts if p.code == c) for c in ("LM26", "LM03")}
        q = {"widen_m2": round(widen_area, 2), "LM26_m": round(lm["LM26"], 2), "LM03_m": round(lm["LM03"], 2),
             "paint_m2": round((lm["LM26"] + lm["LM03"]) * 0.1, 3)}
        P = dict(P, entry=A, stations=[round(x, 3) for x in (s0, s1, s2, s3)], side="L" if sg < 0 else "R",
                 kind="climbing lane")
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
                 kind=BAY_KINDS[piece])
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
    # indicative shelter position behind the platform, mid-bay
    if P.get("shelter"):
        m, L = (b0 + b1) / 2, P["shelter"] / 2
        o0, o1 = edge(m) + depth + plat + 0.5, edge(m) + depth + plat + 2.5
        parts.append(Part("SHELTER", [pt(m - L, o0), pt(m + L, o0), pt(m + L, o1), pt(m - L, o1)], True))
    q = {"kerb_m": round(length(kerb), 2), "raised_kerb_m": round(abs(s2 - s1) + 2 * ramp, 2),
         "island_m2": round(area(plat_ring), 2), "widen_m2": round(widen_area, 2),
         "LM05_m": round(lm05, 2), "paint_m2": round(lm05 * 0.2, 3)}
    P = dict(P, entry=A, stations=[round(x, 3) for x in (s0, s1, s2, s3)], side="L" if sg < 0 else "R",
             kind="bus bay")
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


def climbing_lanes(al, aadt: Optional[float] = None, merge: float = 200.0) -> List[dict]:
    """Climbing lanes the profile asks for (RDM 1.3 6.6): an up-grade longer than its Table 6.6 limit gets a
    lane from where that limit is reached to `merge` m past the end of the grade, on the uphill traffic's
    left (Kenya drives on the left). AADT under 2000 pcu: none (6.6.2)."""
    pr = getattr(al, "profile", None)
    if pr is None or (aadt is not None and aadt < 2000):
        return []
    pv = [(s, z) for s, z, _ in pr.pvis]
    out = []
    for (sa, za), (sb, zb) in zip(pv, pv[1:]):
        L = sb - sa
        if L <= 0:
            continue
        g = (zb - za) / L * 100.0
        lim = grade_limit(g)
        if lim is None or L <= lim:
            continue
        if g > 0:          # uphill with the chainage: traffic on the left of it
            start, end, side = sa + lim, min(sb + merge, al.sta_end), "L"
        else:              # uphill against the chainage: traffic on the right
            start, end, side = sb - lim, max(sa - merge, al.sta_start), "R"
        note = ("consider: AADT 2000-6000 pcu with limited passing" if aadt is not None and aadt <= 6000
                else "normally required above 6000 pcu AADT" if aadt is not None else "AADT not given")
        out.append({"start": start, "end": end, "side": side, "grade": round(g, 2), "length": round(L, 1),
                    "limit": round(lim, 1), "note": note})
    return out


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
              guides: bool = True, splays: bool = True, splay: Optional[dict] = None) -> List[Piece]:
    T = templates or load_templates()
    out = []
    for item in T["kits"][jtype]:
        if (item["piece"] == "guides" and not guides) or (item["piece"] == "splays" and not splays):
            continue
        prm = dict(item.get("params") or {}, **(splay or {})) if item["piece"] == "splays" else item.get("params")
        out.append(build_piece(al, pl, item["piece"], item.get("corner", ""), prm, T))
    return out


def findings(al, pl: Placement) -> List[Tuple[str, str]]:
    """al: the main road's alignment (main_alignment)."""
    """(level, text) about the placement: skew to RDM 1.3 9.2.3, junction near the alignment ends."""
    out = []
    if pl.role == "bay":
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
