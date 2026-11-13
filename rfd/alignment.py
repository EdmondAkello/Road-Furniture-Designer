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
import os
import re
# Every file is checked by safe_xml.check() before it is parsed.
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

if TYPE_CHECKING:                     # annotations only: the modules import this one
    from .corridor import Edges, Sections
    from .profile import VerticalProfile

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
    sections: Optional["Sections"] = None                               # corridor section shapes (offset, rel. z)
    superelevation: List[Tuple[float, float, float]] = field(default_factory=list)  # (start, end, full e %)
    # Civil 3D superelevation stations per curve: begin_runout, begin_runoff, full, runoff, start_runout,
    # end_runout (internal stations; missing ones None) and e (full rate %, as written)
    super_runs: List[dict] = field(default_factory=list)
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
        import bisect
        i = min(max(bisect.bisect_right(self._cum, d) - 1, 0), len(self.elements) - 1)
        while i > 0 and d <= self._cum[i] and self._cum[i - 1] + self.elements[i - 1].length >= d:
            i -= 1                                    # on a joint: keep the earlier element, as before
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

    GRID = 25.0     # m: cell size of the segment index used by station_offset

    def _grid_index(self):
        """Dense segments bucketed by grid cell, so a point only tests the segments near it."""
        g = getattr(self, "_grid", None)
        if g is None:
            pts = self._densify()
            g, c = {}, self.GRID
            for i, ((_, p0), (_, p1)) in enumerate(zip(pts, pts[1:])):
                for ix in range(int(math.floor(min(p0[0], p1[0]) / c)), int(math.floor(max(p0[0], p1[0]) / c)) + 1):
                    for iy in range(int(math.floor(min(p0[1], p1[1]) / c)), int(math.floor(max(p0[1], p1[1]) / c)) + 1):
                        g.setdefault((ix, iy), []).append(i)
            self._grid = g
        return g

    def _nearest_on_dense(self, x, y, seg_ids):
        pts = self._dense
        best = None
        for i in seg_ids:
            (d0, p0), (d1, p1) = pts[i], pts[i + 1]
            vx, vy = p1[0] - p0[0], p1[1] - p0[1]
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 == 0 else ((x - p0[0]) * vx + (y - p0[1]) * vy) / L2
            tc = min(max(t, 0.0), 1.0)
            qx, qy = p0[0] + tc * vx, p0[1] + tc * vy
            dist = math.hypot(x - qx, y - qy)
            if best is None or dist < best[0] or (dist == best[0] and i < best[3]):
                best = (dist, d0 + tc * (d1 - d0), t, i)
        return best

    def station_offset(self, x: float, y: float) -> StationOffset:
        pts = self._densify()
        grid, c = self._grid_index(), self.GRID
        cx0, cy0 = int(math.floor(x / c)), int(math.floor(y / c))
        best, r, seen = None, 0, set()
        while r <= 40:                                   # rings of cells around the point (up to 1 km)
            ids = []
            for ix in range(cx0 - r, cx0 + r + 1):
                for iy in (range(cy0 - r, cy0 + r + 1) if abs(ix - cx0) == r else (cy0 - r, cy0 + r)):
                    for i in grid.get((ix, iy), ()):
                        if i not in seen:
                            seen.add(i); ids.append(i)
            if ids:
                b = self._nearest_on_dense(x, y, ids)
                if best is None or b[0] < best[0] or (b[0] == best[0] and b[3] < best[3]):
                    best = b
            if best is not None and best[0] <= r * c:     # nothing outside this ring can be closer
                break
            r += 1
        if best is None or best[0] > r * c:              # far from the road: test everything
            best = self._nearest_on_dense(x, y, range(len(pts) - 1))
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


# ---- fast paths for large exports (after the LandXML plugin's catalog: byte scans, cached by size and mtime)
_PARSE_CACHE = {}
_BLOCK_OPEN = re.compile(rb"<((?:[A-Za-z_][\w.-]*:)?)(Surfaces|CrossSects)\b[^>]*?(/?)>")
_SEC_RE = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?CrossSect\b([^>]*)>"
                     rb"""|<(?:[A-Za-z_][\w.-]*:)?CrossSectPnt\b[^>]*?\bcode\s*=\s*["']([^"']*)["'][^>]*>([^<]*)<"""
                     rb"""|<(?:[A-Za-z_][\w.-]*:)?CrossSectSurf\b[^>]*?\bname\s*=\s*["']([^"']*)["'][^>]*>\s*"""
                     rb"""<(?:[A-Za-z_][\w.-]*:)?PntList2D\b[^>]*>([^<]*)<""")
_STA_RE = re.compile(rb"""\bsta\s*=\s*["']([^"']+)["']""")
_CODE_RE = re.compile(rb"""\bcode\s*=\s*["']([^"']*)["']""")
_ALIGN_NAME = re.compile(rb"""<(?:[A-Za-z_][\w.-]*:)?Alignment\b[^>]*?\bname\s*=\s*["']([^"']*)["']""")


def _file_key(path, *extra):
    st = os.stat(path)
    return (os.path.abspath(path), st.st_size, st.st_mtime_ns) + extra


def alignment_names(path) -> List[str]:
    """Names of the alignments in a LandXML file, from a byte scan of start tags (no XML tree)."""
    import html
    import mmap
    key = _file_key(path, "names")
    if key in _PARSE_CACHE:
        return list(_PARSE_CACHE[key])
    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as data:
        names = [html.unescape(m.group(1).decode("utf-8", "replace")) for m in _ALIGN_NAME.finditer(data)]
    _PARSE_CACHE[key] = names
    return list(names)


def _scan_sections(acc, buf, keep_code, sec=None) -> None:
    """Corridor sections by regex over the raw bytes: same result as collect_section, far faster than a tree.
    Only coded points matter, so the pattern matches CrossSectPnt elements that carry a code."""
    seen, sta = {}, None
    keep = {}
    for m in _SEC_RE.finditer(buf):
        g1 = m.group(1)
        if g1 is not None:                               # <CrossSect ...>
            if sta is not None:
                for k, o in seen.items():
                    acc.setdefault(k, []).append((sta, o))
            seen = {}
            a = _STA_RE.search(g1)
            try:
                sta = float(a.group(1)) if a else None
            except ValueError:
                sta = None
            continue
        if m.group(4) is not None:                       # <CrossSectSurf name=...><PntList2D> (absolute z)
            if sec is not None and sta is not None:
                try:
                    v = [float(t) for t in m.group(5).split()]
                    name = m.group(4).decode("utf-8", "replace")
                    sec.setdefault(sta, {}).setdefault("_surf", {})[name] = list(zip(v[0::2], v[1::2]))
                except ValueError:
                    pass
            continue
        raw = m.group(2)
        code = keep.get(raw)
        if code is None:
            c = raw.decode("utf-8", "replace")
            code = keep[raw] = c if keep_code(c) else ""
        if not code:
            continue
        sp = m.group(3).split(None, 2)
        try:
            off = float(sp[0])
        except (IndexError, ValueError):
            continue
        if sec is not None and sta is not None and len(sp) > 1 and not (-1e-6 < off < 1e-6):
            try:
                sec.setdefault(sta, {}).setdefault("L" if off < 0 else "R", []).append(
                    (round(-off if off < 0 else off, 4), round(float(sp[1]), 4), code))
            except ValueError:
                pass
        if -1e-6 < off < 1e-6:
            continue
        k = (code, "L" if off < 0 else "R")
        o = -off if off < 0 else off
        if o > seen.get(k, 0.0):
            seen[k] = o
    if sta is not None:
        for k, o in seen.items():
            acc.setdefault(k, []).append((sta, o))


def _block_opens(data):
    """Opening tags of the Surfaces / CrossSects blocks. Unprefixed tags (what Civil 3D writes) are found
    with plain byte searches, which run at memory speed; namespaced files fall back to a regex scan."""
    hits = []
    for tag in (b"<Surfaces", b"<CrossSects"):
        i = data.find(tag)
        while i >= 0:
            m = _BLOCK_OPEN.match(data, i)
            if m:
                hits.append(m)
            i = data.find(tag, i + 1)
    if hits:
        return sorted(hits, key=lambda m: m.start())
    return list(_BLOCK_OPEN.finditer(data))


def _slim_source(path):
    """The file's bytes with the TIN surfaces dropped and each corridor block replaced by a placeholder.

    Returns (bytes, [section block bytes]). The placeholder <RSDSections ref="k"/> keeps the block's
    position inside its Alignment, so its sections are read for the right alignment."""
    import mmap
    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as data:
        parts, blocks, pos = [], [], 0
        for m in _block_opens(data):
            if m.start() < pos:
                continue
            prefix, name, selfclose = m.group(1), m.group(2), m.group(3)
            if selfclose:
                continue
            end_tag = b"</" + prefix + name
            j = data.find(end_tag, m.end())
            if j < 0:
                break
            k = data.find(b">", j)
            parts.append(data[pos:m.start()])
            if name == b"CrossSects":
                parts.append(b'<RSDSections ref="%d"/>' % len(blocks))
                blocks.append(data[m.end():j])
            pos = k + 1
        parts.append(data[pos:])
    return b"".join(parts), blocks


def parse_landxml(path_or_text, corridor: bool = True) -> List[Alignment]:
    """Parse all horizontal alignments in a LandXML file (path or XML string).

    For files: TIN surfaces are skipped and corridor sections are read by a byte scan, so a 60 MB
    export loads in a fraction of a second; the result is cached by file size and modification time.
    Also reads, when present: station equations, design speeds (SpeedStation features or
    Roadway/Speeds), the design vertical profile (ProfAlign) and corridor edges (CrossSect codes).
    """
    import io
    from .corridor import Edges, Sections, collect_section, keep_code
    src = path_or_text
    blocks = None
    key = None
    if isinstance(path_or_text, str) and path_or_text.lstrip().startswith("<"):
        src = io.BytesIO(path_or_text.encode("utf-8"))
    elif isinstance(path_or_text, (str, os.PathLike)) and os.path.isfile(path_or_text):
        key = _file_key(path_or_text, bool(corridor))
        if key in _PARSE_CACHE:
            return list(_PARSE_CACHE[key])
        try:
            slim, blocks = _slim_source(path_or_text)
            src = io.BytesIO(slim)
        except (OSError, ValueError):
            blocks = None
    from .safe_xml import check
    check(path_or_text)
    out, roadway_speeds = [], {}
    edge_acc = sec_acc = None
    # Prolog checked above.
    for ev, el in ET.iterparse(src, events=("start", "end")):  # nosec B314
        t = _local(el.tag)
        if ev == "start":
            if t == "Alignment":
                edge_acc = {}
                sec_acc = {}
            continue
        if t == "RSDSections" and blocks is not None:
            if corridor and edge_acc is not None:
                _scan_sections(edge_acc, blocks[int(el.get("ref"))], keep_code, sec_acc)
            el.clear()
            continue
        if t == "CrossSect" and edge_acc is not None:
            if corridor:
                try:
                    collect_section(edge_acc, float(el.get("sta")), el, _local, sec_acc)
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
                                run = {"e": float(full.text), "full": float(se.get("staStart")),
                                       "runoff": float(se.get("staEnd"))}
                                for key, tag in (("begin_runout", "BeginRunoutSta"),
                                                 ("begin_runoff", "BeginRunoffSta"), ("full", "FullSuperSta"),
                                                 ("runoff", "RunoffSta"), ("start_runout", "StartofRunoutSta"),
                                                 ("end_runout", "EndofRunoutSta")):
                                    c = _child(se, tag)
                                    if c is not None and c.text:
                                        run[key] = float(c.text)
                                al.super_runs.append(run)
                        except (TypeError, ValueError):
                            pass
                al.edges = Edges(edge_acc or {}) or None
                al.sections = Sections(sec_acc or {}) or None
                out.append(al)
            edge_acc = None
            el.clear()
    for al in out:
        if not al.speeds and al.name in roadway_speeds:
            al.speeds = sorted(roadway_speeds[al.name])
    if key is not None:
        if len(_PARSE_CACHE) > 12:
            _PARSE_CACHE.clear()
        _PARSE_CACHE[key] = list(out)
    return out


def landxml_crs(path_or_text) -> dict:
    """CoordinateSystem of a LandXML file: {'epsg': '21037', 'name': 'Arc 1960 / UTM zone 37S', ...}.
    Reads only the file header (stops at the first Alignments / Surfaces element)."""
    import io
    src = path_or_text
    if isinstance(path_or_text, str) and path_or_text.lstrip().startswith("<"):
        src = io.BytesIO(path_or_text.encode("utf-8"))
    from .safe_xml import check
    check(src)
    out = {}
    # Prolog checked above.
    for ev, el in ET.iterparse(src, events=("start",)):  # nosec B314
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
