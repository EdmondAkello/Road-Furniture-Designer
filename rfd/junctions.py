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


def _main_edge(F: Frame, X: float) -> Pt:
    sta = min(max(F.pl.station + X * F.s, F.al.sta_start), F.al.sta_end)
    x, y, _ = F.al.point_at(sta, -F.sigma * F.e)
    return (x, y)


def build_kit(al, pl: Placement, jtype: str, templates: Optional[dict] = None,
              guides: bool = True) -> List[Piece]:
    T = templates or load_templates()
    out = []
    for item in T["kits"][jtype]:
        if item["piece"] == "guides" and not guides:
            continue
        out.append(build_piece(al, pl, item["piece"], item.get("corner", ""), item.get("params"), T))
    return out


def findings(al, pl: Placement) -> List[Tuple[str, str]]:
    """(level, text) about the placement: skew to RDM 1.3 9.2.3, junction near the alignment ends."""
    F = pl.frame(al)
    out = []
    ang = F.crossing_angle
    if ang < SKEW_MINIMUM:
        out.append(("issue", f"crossing angle {ang:.0f} deg is beyond the absolute minimum of {SKEW_MINIMUM:.0f} deg "
                             f"(RDM 1.3 9.2.3); realign the minor road"))
    elif ang < SKEW_PREFERRED[0]:
        out.append(("check", f"crossing angle {ang:.0f} deg: preferably 75-120 deg; the designer should justify "
                             f"a skew under 75 deg (RDM 1.3 9.2.3)"))
    if min(pl.station - al.sta_start, al.sta_end - pl.station) < 60:
        out.append(("info", "junction within 60 m of the alignment end: main-road pieces are cut at the end"))
    return out


def skew_degrees(al, pl: Placement) -> float:
    """Departure from square, degrees (0 = square, positive when the minor road leans along the chainage)."""
    return round(90.0 - pl.frame(al).angle, 1)
