"""Horizontal alignment geometry: LandXML parsing, station/offset in both directions.

Conventions (match Civil 3D):
- Coordinates are (x=easting, y=northing). LandXML stores points as "N E [Z]".
- Headings are math angles in radians, measured counter-clockwise from +X (east).
- Offset is POSITIVE to the RIGHT of the alignment, looking in the direction of
  increasing station. Negative = left.
- "Internal" station = staStart + distance along the geometry. "Display" station
  applies station equations. Geometry always works in internal station.

Pure Python (stdlib only) so it can run in QGIS, CPython, or Dynamo's CPython3.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

TWO_PI = 2.0 * math.pi


def _norm_angle(a: float) -> float:
    return (a + math.pi) % TWO_PI - math.pi


# --------------------------------------------------------------------------- elements
class Element:
    kind = "element"
    length: float

    def point(self, s: float) -> Tuple[float, float]:
        raise NotImplementedError

    def heading(self, s: float) -> float:
        raise NotImplementedError

    @property
    def end_point(self):
        return self.point(self.length)

    @property
    def end_heading(self):
        return self.heading(self.length)


@dataclass
class Line(Element):
    p0: Tuple[float, float]
    p1: Tuple[float, float]
    kind = "line"

    def __post_init__(self):
        dx, dy = self.p1[0] - self.p0[0], self.p1[1] - self.p0[1]
        self.length = math.hypot(dx, dy)
        self._h = math.atan2(dy, dx)

    def point(self, s):
        return (self.p0[0] + s * math.cos(self._h), self.p0[1] + s * math.sin(self._h))

    def heading(self, s):
        return self._h


@dataclass
class Arc(Element):
    start: Tuple[float, float]
    center: Tuple[float, float]
    radius: float
    ccw: bool
    length: float = 0.0
    kind = "arc"

    def __post_init__(self):
        self._a0 = math.atan2(self.start[1] - self.center[1], self.start[0] - self.center[0])
        self._sgn = 1.0 if self.ccw else -1.0

    def point(self, s):
        a = self._a0 + self._sgn * s / self.radius
        return (self.center[0] + self.radius * math.cos(a), self.center[1] + self.radius * math.sin(a))

    def heading(self, s):
        a = self._a0 + self._sgn * s / self.radius
        return _norm_angle(a + self._sgn * math.pi / 2.0)


@dataclass
class Spiral(Element):
    """Clothoid: curvature varies linearly from k0 to k1 (signed, +ve = left/ccw)."""
    start: Tuple[float, float]
    h0: float
    k0: float
    k1: float
    length: float
    kind = "spiral"

    def heading(self, s):
        return _norm_angle(self.h0 + self.k0 * s + (self.k1 - self.k0) * s * s / (2.0 * self.length))

    def _raw_heading(self, s):
        return self.h0 + self.k0 * s + (self.k1 - self.k0) * s * s / (2.0 * self.length)

    def point(self, s):
        # Composite Simpson on cos/sin of heading; plenty accurate for road spirals.
        if s <= 0:
            return self.start
        n = max(16, int(s / 0.5) * 2)
        if n % 2:
            n += 1
        h = s / n
        sx = sy = 0.0
        for i in range(n + 1):
            w = 1 if i in (0, n) else (4 if i % 2 else 2)
            th = self._raw_heading(i * h)
            sx += w * math.cos(th)
            sy += w * math.sin(th)
        return (self.start[0] + sx * h / 3.0, self.start[1] + sy * h / 3.0)


# --------------------------------------------------------------------------- alignment
@dataclass
class StationEquation:
    internal: float   # internal station where the equation applies
    back: float       # displayed station on the back side
    ahead: float      # displayed station on the ahead side


@dataclass
class StationOffset:
    station: float        # internal station
    offset: float         # +right / -left
    in_range: bool        # projection falls within the alignment
    distance: float       # |offset| (for convenience / ambiguity checks)


@dataclass
class Alignment:
    name: str
    elements: List[Element]
    sta_start: float = 0.0
    equations: List[StationEquation] = field(default_factory=list)
    speeds: List[Tuple[float, float]] = field(default_factory=list)   # (internal station, km/h)
    profile: Optional["VerticalProfile"] = None                         # design ProfAlign
    edges: Optional["Edges"] = None                                     # corridor edges (ETW, EPS, ...)
    superelevation: List[Tuple[float, float, float]] = field(default_factory=list)  # (start, end, full e %)
    ground: List[Tuple[float, float]] = field(default_factory=list)   # existing ground (station, z) from ProfSurf

    def speed_at(self, internal: float) -> Optional[float]:
        """Design speed from the Civil 3D SpeedStation features, if the LandXML has them."""
        v = None
        for sta, kmh in self.speeds:
            if internal >= sta - 1e-6:
                v = kmh
        return v

    def __post_init__(self):
        self._cum = []
        acc = 0.0
        for e in self.elements:
            self._cum.append(acc)
            acc += e.length
        self.length = acc
        self.equations.sort(key=lambda q: q.internal)
        self._dense = None

    # ---- station handling
    @property
    def sta_end(self) -> float:
        return self.sta_start + self.length

    def display_station(self, internal: float) -> float:
        disp = internal
        for q in self.equations:
            if internal >= q.internal:
                disp = q.ahead + (internal - q.internal)
        return disp

    def internal_station(self, display: float, region: Optional[int] = None) -> float:
        """Convert a displayed station to internal.

        region: index of the station-equation region (0 = before the first
        equation). If None and the display value is ambiguous, the LAST matching
        region is used and a ValueError is raised only if nothing matches.
        """
        bounds = [self.sta_start] + [q.internal for q in self.equations] + [self.sta_end]
        candidates = []
        for r in range(len(bounds) - 1):
            lo, hi = bounds[r], bounds[r + 1]
            disp0 = self.display_station(lo) if r else lo
            if r:
                disp0 = self.equations[r - 1].ahead
            cand = lo + (display - disp0)
            if lo - 1e-6 <= cand <= hi + 1e-6:
                candidates.append((r, cand))
        if region is not None:
            for r, c in candidates:
                if r == region:
                    return c
            raise ValueError(f"Station {display} not found in equation region {region}")
        if not candidates:
            raise ValueError(f"Station {display} is outside alignment '{self.name}'")
        return candidates[-1][1]

    # ---- forward
    def _locate(self, internal: float):
        d = internal - self.sta_start
        if d < -1e-6 or d > self.length + 1e-6:
            raise ValueError(
                f"Station {internal:.3f} outside alignment '{self.name}' "
                f"({self.sta_start:.3f}–{self.sta_end:.3f})")
        d = min(max(d, 0.0), self.length)
        i = len(self.elements) - 1
        for j, c in enumerate(self._cum):
            if c + self.elements[j].length >= d:
                i = j
                break
        return self.elements[i], d - self._cum[i]

    def point_at(self, internal: float, offset: float = 0.0) -> Tuple[float, float, float]:
        """Return (x, y, heading) at an internal station and offset (+right)."""
        e, s = self._locate(internal)
        x, y = e.point(s)
        h = e.heading(s)
        # right normal = (sin h, -cos h)
        return (x + offset * math.sin(h), y - offset * math.cos(h), h)

    # ---- inverse
    def _densify(self):
        if self._dense is None:
            pts = []
            for i, e in enumerate(self.elements):
                n = max(8, int(math.ceil(e.length / 1.0)))
                for k in range(n + (1 if i == len(self.elements) - 1 else 0)):
                    s = e.length * k / n
                    pts.append((self._cum[i] + s, e.point(s)))
            self._dense = pts
        return self._dense

    def station_offset(self, x: float, y: float) -> StationOffset:
        pts = self._densify()
        best = None
        for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
            vx, vy = p1[0] - p0[0], p1[1] - p0[1]
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 == 0 else ((x - p0[0]) * vx + (y - p0[1]) * vy) / L2
            tc = min(max(t, 0.0), 1.0)
            qx, qy = p0[0] + tc * vx, p0[1] + tc * vy
            dist = math.hypot(x - qx, y - qy)
            if best is None or dist < best[0]:
                best = (dist, d0 + tc * (d1 - d0), t)
        d = best[1]
        # Newton refinement on the true geometry: (P - C(d)) . t(d) = 0
        for _ in range(8):
            d = min(max(d, 0.0), self.length)
            cx, cy, h = self.point_at(self.sta_start + d)
            step = (x - cx) * math.cos(h) + (y - cy) * math.sin(h)
            d_new = min(max(d + step, 0.0), self.length)
            if abs(d_new - d) < 1e-7:
                d = d_new
                break
            d = d_new
        cx, cy, h = self.point_at(self.sta_start + d)
        along = (x - cx) * math.cos(h) + (y - cy) * math.sin(h)
        offset = (x - cx) * math.sin(h) - (y - cy) * math.cos(h)
        in_range = abs(along) < 1e-3
        return StationOffset(self.sta_start + d, offset, in_range, abs(offset))

    # ---- constructors
    @classmethod
    def from_polyline(cls, name, pts, sta_start=0.0, equations=None):
        els = [Line(tuple(a), tuple(b)) for a, b in zip(pts, pts[1:]) if a != b]
        return cls(name, els, sta_start, list(equations or []))


# --------------------------------------------------------------------------- LandXML
def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _pt(el):
    v = [float(t) for t in el.text.split()]
    return (v[1], v[0])  # LandXML "N E" -> (x=E, y=N)


def _radius(v):
    if v is None:
        return math.inf
    v = v.strip().upper()
    if v in ("INF", "INFINITY", "", "0"):
        return math.inf
    return float(v)


def _build_geometry(cg) -> List[Element]:
    els: List[Element] = []
    for g in cg:
        k = _local(g.tag)
        if k == "Line":
            els.append(Line(_pt(_child(g, "Start")), _pt(_child(g, "End"))))
        elif k == "Curve":
            st, ce, en = (_pt(_child(g, n)) for n in ("Start", "Center", "End"))
            ccw = (g.get("rot", "ccw").lower() == "ccw")
            R = float(g.get("radius") or math.hypot(st[0] - ce[0], st[1] - ce[1]))
            a0 = math.atan2(st[1] - ce[1], st[0] - ce[0])
            a1 = math.atan2(en[1] - ce[1], en[0] - ce[0])
            da = (a1 - a0) % TWO_PI if ccw else (a0 - a1) % TWO_PI
            L = float(g.get("length")) if g.get("length") else R * da
            els.append(Arc(st, ce, R, ccw, L))
        elif k == "Spiral":
            st = _pt(_child(g, "Start"))
            pi = _pt(_child(g, "PI"))
            h0 = math.atan2(pi[1] - st[1], pi[0] - st[0])
            sgn = 1.0 if g.get("rot", "ccw").lower() == "ccw" else -1.0
            rs, re_ = _radius(g.get("radiusStart")), _radius(g.get("radiusEnd"))
            k0 = 0.0 if math.isinf(rs) else sgn / rs
            k1 = 0.0 if math.isinf(re_) else sgn / re_
            spi = (g.get("spiType") or "clothoid").lower()
            if spi != "clothoid":
                raise NotImplementedError(f"Spiral type '{spi}' not supported yet")
            els.append(Spiral(st, h0, k0, k1, float(g.get("length"))))
    return els


def _profile(al_el):
    from .profile import VerticalProfile
    for prof in al_el:
        if _local(prof.tag) != "Profile":
            continue
        for pa in prof:
            if _local(pa.tag) != "ProfAlign":
                continue
            pvis = []
            for n in pa:
                t = _local(n.tag)
                if t in ("PVI", "ParaCurve", "CircCurve", "UnsymParaCurve") and n.text:
                    v = n.text.split()
                    L = float(n.get("length") or 0.0)
                    if t == "UnsymParaCurve":
                        L = float(n.get("lengthIn") or 0) + float(n.get("lengthOut") or 0)
                    pvis.append((float(v[0]), float(v[1]), L if t != "PVI" else 0.0))
            if len(pvis) >= 2:
                return VerticalProfile(pa.get("name", ""), pvis)
    return None


def _ground(al_el):
    for prof in al_el:
        if _local(prof.tag) != "Profile":
            continue
        for ps in prof:
            if _local(ps.tag) == "ProfSurf" and (ps.get("state") or "existing") == "existing":
                pl = _child(ps, "PntList2D")
                if pl is not None and pl.text:
                    v = [float(t) for t in pl.text.split()]
                    return sorted(zip(v[0::2], v[1::2]))
    return []


def parse_landxml(path_or_text, corridor: bool = True) -> List[Alignment]:
    """Parse all horizontal alignments in a LandXML file (path or XML string).

    Streams the file, so large exports with TIN surfaces and thousands of
    corridor sections load quickly. Also reads, when present: station
    equations, design speeds (SpeedStation features or Roadway/Speeds), the
    design vertical profile (ProfAlign) and corridor edges (CrossSect codes).
    """
    import io
    from .corridor import Edges, collect_section
    src = path_or_text
    if isinstance(path_or_text, str) and path_or_text.lstrip().startswith("<"):
        src = io.BytesIO(path_or_text.encode("utf-8"))
    out, roadway_speeds = [], {}
    edge_acc = None
    for ev, el in ET.iterparse(src, events=("start", "end")):
        t = _local(el.tag)
        if ev == "start":
            if t == "Alignment":
                edge_acc = {}
            continue
        if t == "CrossSect" and edge_acc is not None:
            if corridor:
                try:
                    collect_section(edge_acc, float(el.get("sta")), el, _local)
                except (TypeError, ValueError):
                    pass
            el.clear()
        elif t in ("Surface", "CgPoints", "PlanFeature"):
            el.clear()
        elif t == "Roadway":
            for sp in el.iter():
                if _local(sp.tag) == "DesignSpeed":
                    for ref in (el.get("alignmentRefs") or "").split():
                        roadway_speeds.setdefault(ref, []).append(
                            (float(sp.get("staStart", 0)), float(sp.get("speed"))))
            el.clear()
        elif t == "Alignment":
            cg = _child(el, "CoordGeom")
            if cg is not None:
                eqs = [StationEquation(float(q.get("staInternal")), float(q.get("staBack")),
                                       float(q.get("staAhead")))
                       for q in el if _local(q.tag) == "StaEquation"]
                speeds = []
                for f in el.iter():
                    if _local(f.tag) == "Feature" and f.get("name") == "SpeedStation":
                        props = {p.get("label"): p.get("value") for p in f if _local(p.tag) == "Property"}
                        try:
                            speeds.append((float(props["station"]), float(props["speed"])))
                        except (KeyError, TypeError, ValueError):
                            pass
                speeds.sort()
                al = Alignment(el.get("name", "Alignment"), _build_geometry(cg),
                               float(el.get("staStart", 0.0)), eqs, speeds)
                al.profile = _profile(el)
                al.ground = _ground(el)
                for se in el.iter():
                    if _local(se.tag) == "Superelevation":
                        full = _child(se, "FullSuperelev")
                        try:
                            if full is not None and full.text:
                                al.superelevation.append((float(se.get("staStart")), float(se.get("staEnd")),
                                                          float(full.text)))
                        except (TypeError, ValueError):
                            pass
                al.edges = Edges(edge_acc or {}) or None
                out.append(al)
            edge_acc = None
            el.clear()
    for al in out:
        if not al.speeds and al.name in roadway_speeds:
            al.speeds = sorted(roadway_speeds[al.name])
    return out


def landxml_crs(path_or_text) -> dict:
    """CoordinateSystem of a LandXML file: {'epsg': '21037', 'name': 'Arc 1960 / UTM zone 37S', ...}.
    Reads only the file header (stops at the first Alignments / Surfaces element)."""
    import io
    src = path_or_text
    if isinstance(path_or_text, str) and path_or_text.lstrip().startswith("<"):
        src = io.BytesIO(path_or_text.encode("utf-8"))
    out = {}
    for ev, el in ET.iterparse(src, events=("start",)):
        t = _local(el.tag)
        if t == "CoordinateSystem":
            out = {"epsg": el.get("epsgCode") or "", "name": el.get("desc") or el.get("name") or "",
                   "map_zone": el.get("horizontalCoordinateSystemName") or "",
                   "datum": el.get("horizontalDatum") or ""}
            break
        if t in ("Alignments", "Surfaces", "CgPoints"):
            break
    return out


def format_station(v: float, decimals: int = 3) -> str:
    sign = "-" if v < 0 else ""
    v = abs(v)
    km = int(v // 1000)
    m = v - km * 1000
    w = 4 + decimals if decimals else 3
    return f"{sign}{km}+{m:0{w}.{decimals}f}"


def parse_station(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace(" ", "")
    if "+" in s:
        km, m = s.split("+", 1)
        neg = km.startswith("-")
        val = abs(float(km or 0)) * 1000 + float(m)
        return -val if neg else val
    return float(s)
