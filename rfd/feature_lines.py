"""Road edges and widenings as 3D feature lines in a LandXML file for Civil 3D.

Civil 3D imports ``PlanFeatures/PlanFeature`` as feature lines when the PlanFeature carries
``<Feature code="FeatureLine" source="Autodesk Civil 3D">`` (else as 3D polylines), with the site
from its ``site`` Property; coordinates are Northing Easting Elevation. The lines can then be used as
corridor width / offset and elevation targets.

Written as Civil 3D writes its own feature lines: the plan geometry as PIs (``Line``, and
``Curve`` where an edge runs parallel to an alignment arc), and the levels in between as elevation points
(``<Location desc="FeatureLine Elevation Point">``), which Civil 3D handles far more lightly than PIs.
A feature-line ``Curve`` is Civil 3D's three-point arc: ``Start``, ``Center`` and ``End`` are points ON
the arc (``Center`` its middle point, with its level) and only ``radius`` is given - not the circle's
centre and ``rot`` of an alignment curve.

Elevations: the design profile at the station plus the section's level at the offset. The section is
the corridor's (superelevation included) or the typical section's (crown crossfall only: superelevation
is not applied, flagged in the file description). Beyond the outermost pavement point (a bay or a junction
widening) the pavement's last crossfall is carried on.

Written as plain text in the manner of the LandXML plugin's review export (LandXML 1.2, quoted
attributes, the source file's Units and CoordinateSystem copied).
"""
from __future__ import annotations

import bisect
import math
import re
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple
from html import escape as _escape

from .corridor import SHOULDER, TRAVELLED_WAY

PAVEMENT = tuple(TRAVELLED_WAY) + tuple(SHOULDER) + ("Parking", "Crown")
SITE = "RFD"                # Civil 3D site named in the file ("" writes them siteless); the import dialog can override
LAYER = "C-TOPO-FEAT"       # Civil 3D's default feature-line layer
STEP = 5.0                  # m: sampling along the road
H_TOL = 0.02                # m: plan tolerance for PIs off the arcs (Douglas-Peucker)
V_TOL = 0.005               # m: level tolerance for elevation points (against the grade between kept points)
MAX_LENGTH = 5000.0         # m: a longer feature line is written in pieces
WIDENING_CODES = ("WIDEN", "BAYEDGE")

Pt3 = Tuple[float, float, float]


def quoteattr(v) -> str:
    """An XML attribute value in double quotes (writing only; nothing is parsed here)."""
    return '"' + _escape(str(v), quote=True) + '"'


# ------------------------------------------------------------------ elevations
def _pair(al, sta, side):
    """The two sections around a station and the weight of the second (for interpolation)."""
    sec = getattr(al, "sections", None)
    if not sec or not sec.stations:
        return None
    st = sec.stations
    i = bisect.bisect_left(st, sta)
    if i <= 0:
        return st[0], st[0], 0.0
    if i >= len(st):
        return st[-1], st[-1], 0.0
    a, b = st[i - 1], st[i]
    return a, b, (sta - a) / (b - a) if b > a else 0.0


def _rel_z_one(pts, off: float) -> Optional[float]:
    """Level relative to the crown at an offset on one section side: along the pavement points, then
    on at the last pavement crossfall (widenings beyond the edge)."""
    road = [(0.0, 0.0)] + sorted({(o, z) for o, z, c in pts if c in PAVEMENT})
    if len(road) < 2:
        return None
    for (x0, z0), (x1, z1) in zip(road, road[1:]):
        if x0 - 1e-9 <= off <= x1 + 1e-9:
            return z0 if x1 - x0 < 1e-9 else z0 + (z1 - z0) * (off - x0) / (x1 - x0)
    (x0, z0), (x1, z1) = road[-2], road[-1]
    slope = (z1 - z0) / (x1 - x0) if x1 - x0 > 1e-9 else 0.0
    return z1 + slope * (off - x1)


def level_at(al, sta: float, offset: float) -> Optional[float]:
    """Design level at a station and signed offset (+ right): profile plus the section's crossfall."""
    prof = getattr(al, "profile", None)
    zc = prof.elevation(sta) if prof is not None else None
    if zc is None:
        return None
    if abs(offset) < 1e-6:
        return zc
    side = "R" if offset > 0 else "L"
    pr = _pair(al, sta, side)
    if pr is None:
        return zc
    a, b, t = pr
    za = _rel_z_one(al.sections.side(a, side), abs(offset))
    zb = _rel_z_one(al.sections.side(b, side), abs(offset))
    if za is None and zb is None:
        return zc
    if za is None or zb is None:
        return zc + (za if za is not None else zb)
    return zc + za + (zb - za) * t


def code_level(al, sta: float, side: str, code: str, offset: float) -> Optional[float]:
    """Level of a coded section point (ETW, Daylight, Walkway ...) interpolated between the two sections
    around the station; the offset rule (level_at) where a section lacks the code."""
    prof = getattr(al, "profile", None)
    zc = prof.elevation(sta) if prof is not None else None
    pr = _pair(al, sta, side)
    if zc is None or pr is None:
        return level_at(al, sta, offset)
    a, b, t = pr

    def rel(s):
        pts = [(o, z) for o, z, c in al.sections.side(s, side) if c == code]
        return max(pts)[1] if pts else None
    za, zb = rel(a), rel(b)
    if za is None or zb is None:
        return level_at(al, sta, offset)
    return zc + za + (zb - za) * t


# ------------------------------------------------------------------ lines
class FLine:
    """A feature line: PIs [(x, y, z)], the arcs among its segments {i: (cx, cy, radius, rot)} (segment i
    runs from PI i to PI i + 1) and elevation points [(x, y, z)] between the PIs."""

    def __init__(self, name, code, pis, arcs=None, elev=None):
        self.name, self.code, self.pis = name, code, list(pis)
        self.arcs = dict(arcs or {})
        self.elev = list(elev or [])

    def __len__(self):
        return len(self.pis)


def _dp(n, dev, tol, keep):
    """Iterative Douglas-Peucker over indices 0..n-1: dev(a, b, i) is point i's deviation from the chord a-b."""
    stack = [(0, n - 1)]
    keep.update((0, n - 1))
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        wi, worst = max(((i, dev(a, b, i)) for i in range(a + 1, b)), key=lambda t: t[1])
        if worst > tol:
            keep.add(wi)
            stack += [(a, wi), (wi, b)]
    return keep


def _plan_dev(xy):
    def dev(a, b, i):
        (xa, ya), (xb, yb), (x, y) = xy[a], xy[b], xy[i]
        dx, dy = xb - xa, yb - ya
        L = math.hypot(dx, dy)
        return math.hypot(x - xa, y - ya) if L < 1e-9 else abs((x - xa) * dy - (y - ya) * dx) / L
    return dev


def _level_dev(d, z):
    def dev(a, b, i):
        t = 0.0 if d[b] - d[a] < 1e-9 else (d[i] - d[a]) / (d[b] - d[a])
        return abs(z[i] - (z[a] + (z[b] - z[a]) * t))
    return dev


def simplify(pts: Sequence[Pt3], h_tol: float = H_TOL, v_tol: float = V_TOL) -> List[Pt3]:
    """Thin a 3D line to within h_tol in plan and v_tol in level (both kept). Ends always kept."""
    if len(pts) <= 2:
        return list(pts)
    xy = [(p[0], p[1]) for p in pts]
    d = [0.0]
    for a, b in zip(xy, xy[1:]):
        d.append(d[-1] + math.dist(a, b))
    keep = _dp(len(pts), _plan_dev(xy), h_tol, set())
    keep = _dp(len(pts), _level_dev(d, [p[2] for p in pts]), v_tol, keep)
    return [pts[i] for i in sorted(keep)]


def build(name, code, samples, arcs_of=None, h_tol=H_TOL, v_tol=V_TOL) -> FLine:
    """A feature line from samples [(x, y, z)] along it. arcs_of: [(i0, i1, cx, cy, rot)] sample ranges that
    lie on a circular arc (written as one Curve each); elsewhere PIs are thinned to h_tol in plan. Levels
    between the PIs become elevation points, thinned to v_tol against the grade."""
    n = len(samples)
    xy = [(p[0], p[1]) for p in samples]
    d = [0.0]
    for a, b in zip(xy, xy[1:]):
        d.append(d[-1] + math.dist(a, b))
    z = [p[2] for p in samples]
    pis = {0, n - 1}
    spans = sorted(arcs_of or [])
    for i0, i1, *_ in spans:
        pis.update((i0, i1))
    # plan thinning on the stretches between the arcs
    cuts = sorted(pis)
    on_arc = {(i0, i1) for i0, i1, *_ in spans}
    for a, b in zip(cuts, cuts[1:]):
        if (a, b) in on_arc or b - a < 2:
            continue
        sub = xy[a:b + 1]
        pis.update(a + k for k in _dp(len(sub), _plan_dev(sub), h_tol, set()))
    order = sorted(pis)
    arcs = {}
    for i0, i1, cx, cy, rot in spans:
        k = order.index(i0)
        if k + 1 < len(order) and order[k + 1] == i1:
            arcs[k] = (cx, cy, math.dist((cx, cy), xy[i0]), rot)
    keep = _dp(n, _level_dev(d, z), v_tol, set(order))
    elev = [samples[i] for i in sorted(keep - set(order))]
    return FLine(name, code, [samples[i] for i in order], arcs, elev)


def _stations(al, step):
    st = set()
    s = al.sta_start
    while s < al.sta_end - 1e-6:
        st.add(round(s, 3)); s += step
    st.add(round(al.sta_end, 3))
    if getattr(al, "sections", None):
        st.update(round(x, 3) for x in al.sections.stations if al.sta_start <= x <= al.sta_end)
    acc = al.sta_start
    for e in al.elements:                       # element ends, so arcs start and end on a sample
        st.add(round(acc, 3)); acc += e.length
    return sorted(st)


def _arc_at(al, sta):
    """(Arc element, its start and end stations) at a station, or None."""
    acc = al.sta_start
    for e in al.elements:
        if acc - 1e-6 <= sta <= acc + e.length + 1e-6:
            return (e, acc, acc + e.length) if getattr(e, "kind", "") == "arc" else None
        acc += e.length
    return None


def _split_by_length(rows, max_len):
    """[(sta, ...)] runs cut every max_len m of station (pieces share their end sample)."""
    out, cur = [], []
    for r in rows:
        cur.append(r)
        if r[0] - cur[0][0] >= max_len and len(cur) >= 2:
            out.append(cur); cur = [r]
    if len(cur) >= 2:
        out.append(cur)
    return out


def edge_lines(al, step: float = STEP, max_len: float = MAX_LENGTH) -> List[FLine]:
    """Each road edge as feature lines: sampled every step m and at every section and element end, split
    where the edge is missing and every max_len m; true arcs where it runs parallel to an alignment arc."""
    edges = getattr(al, "edges", None)
    out = []
    if not edges:
        return out
    stations = _stations(al, step)
    for (code, side) in sorted(edges.data):
        sg = -1.0 if side == "L" else 1.0
        runs, run = [], []
        for s in stations:
            o = edges.offset(code, side, s)
            z = code_level(al, s, side, code, sg * o) if o is not None else None
            if o is None or z is None:
                if len(run) >= 2:
                    runs.append(run)
                run = []
                continue
            x, y, _ = al.point_at(s, sg * o)
            run.append((s, o, x, y, z))
        if len(run) >= 2:
            runs.append(run)
        pieces = [p for r in runs for p in _split_by_length(r, max_len)]
        for k, rows in enumerate(pieces, 1):
            spans, i = [], 0
            while i < len(rows) - 1:                     # constant offset on an arc element: one Curve
                hit = _arc_at(al, (rows[i][0] + rows[i + 1][0]) / 2)
                if hit is None:
                    i += 1
                    continue
                arc, a, b = hit
                j = i
                while (j + 1 < len(rows) and rows[j + 1][0] <= b + 1e-6
                       and abs(rows[j + 1][1] - rows[i][1]) < 1e-3):
                    j += 1
                if j > i:
                    spans.append((i, j, arc.center[0], arc.center[1], "ccw" if arc.ccw else "cw"))
                i = max(j, i + 1)
            name = f"RFD {code} {side}" + ("" if len(pieces) == 1 else f"-{k}")
            out.append(build(name, code, [(x, y, z) for _, _, x, y, z in rows], spans))
    return out


def _densify(pts: Sequence[Tuple[float, float]], step: float) -> List[Tuple[float, float]]:
    out = [tuple(pts[0])]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step)))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def draped(al, name: str, code: str, pts: Sequence[Tuple[float, float]], step: float = STEP,
           max_offset: float = 60.0) -> Optional[FLine]:
    """A plan polyline (a bay edge, a junction widening) with levels from the road at each vertex."""
    out = []
    for x, y in _densify(pts, step):
        so = al.station_offset(x, y)
        if not so.in_range or abs(so.offset) > max_offset:
            return None
        z = level_at(al, so.station, so.offset)
        if z is None:
            return None
        out.append((x, y, z))
    return build(name, code, out) if len(out) >= 2 else None


def widening_lines(al, parts: Iterable, codes=WIDENING_CODES) -> List[FLine]:
    """From junction parts [(code, sta, [polyline])]: the widened pavement edges, draped on the road."""
    out, n = [], {}
    for code, _sta, lines in parts:
        if code not in codes:
            continue
        for ln in lines:
            if len(ln) < 2:
                continue
            n[code] = n.get(code, 0) + 1
            d = draped(al, f"RFD {code} {n[code]}", code, ln)
            if d:
                out.append(d)
    return out


# ------------------------------------------------------------------ LandXML
def _header_elements(source_path) -> Tuple[str, str]:
    """The source file's <Units>...</Units> and <CoordinateSystem .../> as text (empty when absent)."""
    if not source_path:
        return "", ""
    try:
        with open(source_path, "rb") as f:
            head = f.read(1 << 16).decode("utf-8", "replace")
    except OSError:
        return "", ""
    head = head.split("<Alignments", 1)[0].split("<Surfaces", 1)[0]
    head = re.sub(r"<(/?)\w+:", r"<\1", head)                  # drop namespace prefixes
    units = re.search(r"<Units\b.*?</Units>|<Units\b[^>]*/>", head, re.S)
    cs = re.search(r"<CoordinateSystem\b.*?</CoordinateSystem>|<CoordinateSystem\b[^>]*/>", head, re.S)
    return (units.group(0) if units else ""), (cs.group(0) if cs else "")


def arc_midpoint(a, b, cx, cy, r, rot):
    """The point half way along the arc from a to b (circle centre cx, cy, radius r, sense rot), with the
    level half way between theirs: Civil 3D's feature-line Curve gives this as its 'Center'."""
    a0, a1 = math.atan2(a[1] - cy, a[0] - cx), math.atan2(b[1] - cy, b[0] - cx)
    sweep = (a1 - a0) % (2 * math.pi) if rot == "ccw" else -((a0 - a1) % (2 * math.pi))
    am = a0 + sweep / 2
    return (cx + r * math.cos(am), cy + r * math.sin(am), (a[2] + b[2]) / 2)


def _ne(p, z=True):
    return f"{p[1]:.4f} {p[0]:.4f} {p[2]:.4f}" if z else f"{p[1]:.4f} {p[0]:.4f}"


def write_landxml(path, lines: Sequence[FLine], source_path=None, site=SITE, desc="") -> int:
    """Write the lines as Civil 3D feature lines (PlanFeatures). Returns the number written."""
    now = datetime.now()
    units, cs = _header_elements(source_path)
    if not units:
        units = ('<Units><Metric linearUnit="meter" areaUnit="squareMeter" volumeUnit="cubicMeter" '
                 'temperatureUnit="celsius" pressureUnit="milliBars" angularUnit="decimal degrees" '
                 'directionUnit="decimal degrees"/></Units>')
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2" '
           f'date="{now:%Y-%m-%d}" time="{now:%H:%M:%S}">',
           "  " + units]
    if cs:
        out.append("  " + cs)
    out.append(f'  <Application name="Road Furniture Designer" desc={quoteattr(desc or "Road edges and widenings")}/>')
    out.append(f"  <PlanFeatures name={quoteattr(f'Site -{site}- FeatureLines' if site else 'Siteless FeatureLines')}>")
    n = 0
    for fl in lines:
        if len(fl.pis) < 2:
            continue
        out.append(f"    <PlanFeature name={quoteattr(fl.name)} desc={quoteattr(fl.code)}>")
        out.append("      <CoordGeom>")
        for i, (a, b) in enumerate(zip(fl.pis, fl.pis[1:])):
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-4:
                continue
            if i in fl.arcs:
                cx, cy, r, rot = fl.arcs[i]
                mid = arc_midpoint(a, b, cx, cy, r, rot)
                out.append(f'        <Curve radius="{r:.6f}"><Start>{_ne(a)}</Start><Center>{_ne(mid)}</Center>'
                           f"<End>{_ne(b)}</End></Curve>")
            else:
                out.append(f"        <Line><Start>{_ne(a)}</Start><End>{_ne(b)}</End></Line>")
        out.append("      </CoordGeom>")
        for p in fl.elev:
            out.append(f'      <Location desc="FeatureLine Elevation Point">{_ne(p)}</Location>')
        out.append('      <Feature code="FeatureLine" source="Autodesk Civil 3D">')
        if site:
            out.append(f'        <Property label="site" value={quoteattr(site)}/>')
        out.append(f'        <Property label="layer" value={quoteattr(LAYER)}/>')
        out.append(f'        <Property label="rfdCode" value={quoteattr(fl.code)}/>')
        out.append("      </Feature>")
        out.append("    </PlanFeature>")
        n += 1
    out.append('    <Feature code="FeatureLines" source="Autodesk Civil 3D">')
    if site:
        out.append(f'      <Property label="site" value={quoteattr(site)}/>')
    out.append("    </Feature>")
    out += ["  </PlanFeatures>", "</LandXML>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return n


def export(path, al, parts=(), source_path=None, step=STEP) -> Tuple[int, List[str]]:
    """Road edges and widenings of an alignment to a feature-line LandXML. Returns (count, notes)."""
    notes = []
    if getattr(al, "profile", None) is None:
        raise ValueError("The alignment has no design profile: feature lines need levels")
    if not getattr(al, "edges", None):
        raise ValueError("The alignment has no road edges: set a typical section (Section tab) or use a corridor")
    src = getattr(al, "edge_source", "") or "corridor"
    no_super = src == "typical section" and not getattr(al, "super_runs", None)
    if no_super:
        notes.append("The LandXML has no superelevation: levels on curves are at the normal crossfall.")
    lines = edge_lines(al, step) + widening_lines(al, parts)
    pis = sum(len(fl.pis) for fl in lines)
    arcs = sum(len(fl.arcs) for fl in lines)
    elev = sum(len(fl.elev) for fl in lines)
    notes.append(f"{pis} PIs ({arcs} arcs) and {elev} elevation points.")
    desc = f"Road edges ({src}) and widenings of {al.name}" + (" - no superelevation in the source"
                                                                if no_super else "")
    n = write_landxml(path, lines, source_path, desc=desc)
    return n, notes
