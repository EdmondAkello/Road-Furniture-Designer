"""Synthetic demonstration road for the user guide (and anyone trying the plugin without project data).

    python tools/guide/make_guide_road.py [out.xml]

A 5 km two-lane road written as a Civil 3D style LandXML (Arc 1960 / UTM 37S coordinates, no real
place): a sharp curve, a series of bends, a crest short of the passing sight distance, a steep
descent onto an embankment, a 50 km/h village section, design speeds, superelevation and corridor
cross-sections with coded points (ETW, EPS, Hinge, Daylight) and an existing-ground line, so every
rule in Road Furniture Designer has something to act on.
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from rfd.alignment import Arc, Line, Spiral  # noqa: E402
from rfd.profile import VerticalProfile  # noqa: E402
from examples.make_demo_road import to_landxml  # noqa: E402

NAME = "DEMO-ROAD"
X0, Y0, H0 = 262000.0, 9948000.0, math.radians(20)


def _curve(p, h, R, Ls, Lc, ccw):
    sgn = 1.0 if ccw else -1.0
    s1 = Spiral(p, h, 0.0, sgn / R, Ls)
    q, g = s1.end_point, s1.end_heading
    ce = (q[0] - sgn * R * math.sin(g), q[1] + sgn * R * math.cos(g))
    a = Arc(q, ce, R, ccw, Lc)
    s2 = Spiral(a.end_point, a.end_heading, sgn / R, 0.0, Ls)
    return [s1, a, s2], s2.end_point, s2.end_heading


def _line(p, h, L):
    q = (p[0] + L * math.cos(h), p[1] + L * math.sin(h))
    return Line(p, q), q


def geometry():
    """Elements and the (start, end, R) of each circular arc."""
    els, arcs = [], []
    p, h = (X0, Y0), H0
    for kind, *a in (("L", 650), ("C", 75, 40, 100, False), ("L", 520), ("C", 180, 30, 110, True), ("L", 70),
                     ("C", 180, 30, 110, False), ("L", 980), ("C", 650, 60, 320, True), ("L", 1250)):
        if kind == "L":
            e, p = _line(p, h, a[0])
            els.append(e)
        else:
            R, Ls, Lc, ccw = a
            start = sum(e.length for e in els) + Ls
            cs, p, h = _curve(p, h, R, Ls, Lc, ccw)
            els += cs
            arcs.append((start, start + Lc, R))
    return els, arcs


# design profile: (station, level, curve length)
PVIS = [(0, 1820.0, 0), (700, 1826.3, 160), (1500, 1840.0, 140), (2100, 1822.0, 260), (2900, 1826.0, 200),
        (3550, 1832.5, 160), (4150, 1792.0, 240), (4850, 1788.5, 0)]
SPEEDS = [(0.0, 80.0), (2600.0, 50.0), (3350.0, 80.0)]


def fill_height(s):
    """Embankment height at the toe below the hinge (m): a high fill after the descent, low elsewhere."""
    if 3750 <= s <= 4150:
        return 7.5 - 0.00012 * (s - 3950) ** 2
    return 0.6


def sections(L, prof, step=20.0):
    out, s = [], 0.0
    while s <= L + 1e-6:
        z = prof.elevation(s)
        h = max(fill_height(s), 0.3)
        n = 1.5 if h > 3 else 4.0
        # coded points: level relative to the design profile; surfaces: absolute (as Civil 3D writes them)
        top = [("Crown", 0.0, 0.0), ("ETW", 3.5, -0.088), ("EPS", 5.0, -0.13), ("Hinge", 6.0, -0.2),
               ("Daylight", 6.0 + n * h, -0.2 - h)]
        pts = "".join(f'<CrossSectPnt code="{c}">{-o:.3f} {zz:.3f}</CrossSectPnt>' for c, o, zz in reversed(top[1:]))
        pts += "".join(f'<CrossSectPnt code="{c}">{o:.3f} {zz:.3f}</CrossSectPnt>' for c, o, zz in top)
        g = z - 0.2 - h
        ground = " ".join(f"{o:.1f} {g:.3f}" for o in range(-60, 61, 10))
        out.append(f'<CrossSect sta="{s:.3f}"><DesignCrossSectSurf name="Top">{pts}</DesignCrossSectSurf>'
                   f'<CrossSectSurf name="Existing Ground"><PntList2D>{ground}</PntList2D></CrossSectSurf>'
                   f'</CrossSect>')
        s += step
    return "<CrossSects>" + "".join(out) + "</CrossSects>"


def landxml():
    els, arcs = geometry()
    L = sum(e.length for e in els)
    pv = [p for p in PVIS if p[0] < L] + [(L, PVIS[-1][1], 0)]
    prof = VerticalProfile("FRL", [(s, z, c) for s, z, c in pv])
    pvi = "".join((f'<ParaCurve length="{c:g}">{s:.3f} {z:.3f}</ParaCurve>' if c else f'<PVI>{s:.3f} {z:.3f}</PVI>')
                  for s, z, c in pv)
    extra = f'<Profile name="{NAME}"><ProfAlign name="FRL">{pvi}</ProfAlign></Profile>'
    extra += "".join(f'<Feature name="SpeedStation"><Property label="station" value="{s:g}"/>'
                     f'<Property label="speed" value="{v:g}"/></Feature>' for s, v in SPEEDS)
    e_of = {75: 6.0, 180: 5.0, 650: 3.0}
    extra += "".join(f'<Superelevation staStart="{a:.3f}" staEnd="{b:.3f}"><FullSuperelev>{e_of[R]:g}'
                     f'</FullSuperelev></Superelevation>' for a, b, R in arcs)
    extra += sections(L, prof)
    xml = to_landxml(els, name=NAME, equations=(), extra=extra)
    return xml.replace('<Units>', '<CoordinateSystem epsgCode="21037" desc="Arc 1960 / UTM zone 37S"/><Units>', 1)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "guide_road.xml"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(landxml())
    print("wrote", out)
