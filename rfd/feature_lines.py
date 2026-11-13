"""Road edges and widenings as 3D feature lines in a LandXML file for Civil 3D.

Civil 3D imports ``PlanFeatures/PlanFeature`` as feature lines when the PlanFeature carries
``<Feature code="FeatureLine" source="Autodesk Civil 3D">`` (else as 3D polylines), with the site
from its ``site`` Property; coordinates are Northing Easting Elevation. The lines can then be used as
corridor width / offset and elevation targets.

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
SITE = "RFD"
STEP = 5.0                  # m: sampling along the road for straight-line segments
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
def edge_lines(al, step: float = STEP) -> List[Tuple[str, str, List[Pt3]]]:
    """[(name, code, [(x, y, z)])]: each road edge sampled every ``step`` m and at every section, split
    where the edge is missing."""
    edges = getattr(al, "edges", None)
    out = []
    if not edges:
        return out
    stations = set()
    s = al.sta_start
    while s < al.sta_end - 1e-6:
        stations.add(round(s, 3)); s += step
    stations.add(round(al.sta_end, 3))
    if getattr(al, "sections", None):
        stations.update(round(x, 3) for x in al.sections.stations if al.sta_start <= x <= al.sta_end)
    stations = sorted(stations)
    for (code, side) in sorted(edges.data):
        sg = -1.0 if side == "L" else 1.0
        run, k = [], 1
        for s in stations:
            o = edges.offset(code, side, s)
            z = code_level(al, s, side, code, sg * o) if o is not None else None
            if o is None or z is None:
                if len(run) >= 2:
                    out.append((f"RFD {code} {side}{'' if k == 1 else f' {k}'}", code, run)); k += 1
                run = []
                continue
            x, y, _ = al.point_at(s, sg * o)
            run.append((x, y, z))
        if len(run) >= 2:
            out.append((f"RFD {code} {side}{'' if k == 1 else f' {k}'}", code, run))
    return out


def _densify(pts: Sequence[Tuple[float, float]], step: float) -> List[Tuple[float, float]]:
    out = [tuple(pts[0])]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step)))
        out += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(1, n + 1)]
    return out


def draped(al, name: str, code: str, pts: Sequence[Tuple[float, float]], step: float = STEP,
           max_offset: float = 60.0) -> Optional[Tuple[str, str, List[Pt3]]]:
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
    return (name, code, out) if len(out) >= 2 else None


def widening_lines(al, parts: Iterable, codes=WIDENING_CODES) -> List[Tuple[str, str, List[Pt3]]]:
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


def write_landxml(path, lines: Sequence[Tuple[str, str, Sequence[Pt3]]], source_path=None, site=SITE,
                  desc="") -> int:
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
    out.append(f"  <PlanFeatures name={quoteattr(site)}>")
    n = 0
    for name, code, pts in lines:
        if len(pts) < 2:
            continue
        out.append(f"    <PlanFeature name={quoteattr(name)} desc={quoteattr(code)}>")
        out.append("      <CoordGeom>")
        for (x0, y0, z0), (x1, y1, z1) in zip(pts, pts[1:]):
            if math.hypot(x1 - x0, y1 - y0) < 1e-4:
                continue
            out.append(f"        <Line><Start>{y0:.4f} {x0:.4f} {z0:.4f}</Start>"
                       f"<End>{y1:.4f} {x1:.4f} {z1:.4f}</End></Line>")
        out.append("      </CoordGeom>")
        out.append('      <Feature code="FeatureLine" source="Autodesk Civil 3D">')
        out.append(f"        <Property label=\"site\" value={quoteattr(site)}/>")
        out.append(f"        <Property label=\"rfdCode\" value={quoteattr(code)}/>")
        out.append("      </Feature>")
        out.append("    </PlanFeature>")
        n += 1
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
    if src == "typical section":
        notes.append("Levels from the typical section's crown crossfall: superelevation is not applied.")
    lines = edge_lines(al, step) + widening_lines(al, parts)
    desc = f"Road edges ({src}) and widenings of {al.name}" + (" - superelevation not applied"
                                                                if src == "typical section" else "")
    n = write_landxml(path, lines, source_path, desc=desc)
    return n, notes
