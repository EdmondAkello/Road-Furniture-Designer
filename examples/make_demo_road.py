"""Generate a synthetic LandXML road for testing: tangent - spiral - curve - spiral - tangent,
with a station equation. Usage: python make_demo_road.py out.xml
"""
import math
import sys

from rfd.alignment import Line, Arc, Spiral


def _isect(p, h1, q, h2):
    # intersection of ray p + t*(cos h1, sin h1) with q + u*(cos h2, sin h2)
    d1 = (math.cos(h1), math.sin(h1))
    d2 = (math.cos(h2), math.sin(h2))
    den = d1[0] * d2[1] - d1[1] * d2[0]
    t = ((q[0] - p[0]) * d2[1] - (q[1] - p[1]) * d2[0]) / den
    return (p[0] + t * d1[0], p[1] + t * d1[1])


def _ne(p):
    return f"{p[1]:.6f} {p[0]:.6f}"


def build(R=300.0, Ls=60.0, Lc=200.0, ccw=True, x0=260000.0, y0=9950000.0, h0=math.radians(30)):
    sgn = 1.0 if ccw else -1.0
    l1 = Line((x0, y0), (x0 + 400 * math.cos(h0), y0 + 400 * math.sin(h0)))
    s1 = Spiral(l1.end_point, h0, 0.0, sgn / R, Ls)
    p, h = s1.end_point, s1.end_heading
    ce = (p[0] - sgn * R * math.sin(h), p[1] + sgn * R * math.cos(h))
    a = Arc(p, ce, R, ccw, Lc)
    s2 = Spiral(a.end_point, a.end_heading, sgn / R, 0.0, Ls)
    p2, h2 = s2.end_point, s2.end_heading
    l2 = Line(p2, (p2[0] + 500 * math.cos(h2), p2[1] + 500 * math.sin(h2)))
    return [l1, s1, a, s2, l2]


def corridor_xml(length, step=20.0, etw=3.5, eps=5.0, widen_from=None):
    """Civil 3D-style CrossSect records with coded points (ETW, EPS, layer codes, Crown)."""
    out, s = [], 0.0
    while s <= length + 1e-6:
        w = eps + (1.0 if widen_from is not None and s >= widen_from else 0.0)
        pts = "".join(
            f'<CrossSectPnt code="{c}">{o:.3f} 0.0</CrossSectPnt>'
            for c, o in (("Crown", 0.0), ("ETW", -etw), ("EPS", -w), ("ETW_Base", -etw), ("ETW", etw), ("EPS", w)))
        out.append(f'<CrossSect sta="{s:.3f}"><DesignCrossSectSurf name="Top">{pts}</DesignCrossSectSurf></CrossSect>')
        s += step
    return "<CrossSects>" + "".join(out) + "</CrossSects>"


PROFILE_XML = ('<Profile name="DEMO"><ProfAlign name="FRL"><PVI>0 100</PVI>'
               '<ParaCurve length="100">300 106</ParaCurve>'      # +2% -> -3%: crest, A=-5, K=20
               '<ParaCurve length="150">700 94</ParaCurve>'       # -3% -> +1%: sag, A=4, K=37.5
               '<PVI>1220 99.2</PVI></ProfAlign></Profile>')


def to_landxml(els, name="DEMO-RD", sta_start=0.0, equations=((800.0, 800.0, 850.0),), extra=""):
    rot = "ccw"
    parts = []
    for e in els:
        if e.kind == "line":
            parts.append(f'<Line length="{e.length:.6f}"><Start>{_ne(e.p0)}</Start><End>{_ne(e.p1)}</End></Line>')
        elif e.kind == "arc":
            rot = "ccw" if e.ccw else "cw"
            parts.append(f'<Curve rot="{rot}" radius="{e.radius:.6f}" length="{e.length:.6f}">'
                         f'<Start>{_ne(e.start)}</Start><Center>{_ne(e.center)}</Center>'
                         f'<End>{_ne(e.end_point)}</End></Curve>')
        elif e.kind == "spiral":
            pi = _isect(e.start, e.h0, e.end_point, e.end_heading + math.pi)
            r0 = "INF" if e.k0 == 0 else f"{abs(1 / e.k0):.6f}"
            r1 = "INF" if e.k1 == 0 else f"{abs(1 / e.k1):.6f}"
            k = e.k0 or e.k1
            srot = "ccw" if k > 0 else "cw"
            parts.append(f'<Spiral length="{e.length:.6f}" radiusStart="{r0}" radiusEnd="{r1}" '
                         f'rot="{srot}" spiType="clothoid"><Start>{_ne(e.start)}</Start>'
                         f'<PI>{_ne(pi)}</PI><End>{_ne(e.end_point)}</End></Spiral>')
    L = sum(e.length for e in els)
    eq = "".join(f'<StaEquation staInternal="{i}" staBack="{b}" staAhead="{a}"/>' for i, b, a in equations)
    return (f'<?xml version="1.0"?>\n<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">'
            f'<Units><Metric linearUnit="meter" angularUnit="decimal degrees"/></Units>'
            f'<Alignments><Alignment name="{name}" length="{L:.6f}" staStart="{sta_start}">'
            f'<CoordGeom>{"".join(parts)}</CoordGeom>{eq}{extra}</Alignment></Alignments></LandXML>\n')


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "demo_road.xml"
    with open(out, "w") as f:
        f.write(to_landxml(build()))
    print("wrote", out)
