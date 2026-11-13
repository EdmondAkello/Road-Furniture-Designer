"""Typical section: road edges from user-defined offsets when the LandXML has no corridor.

A centreline-only LandXML (the alignment with its design and existing ground profiles) is enough to
run RFD: the designer gives the typical section (lane, shoulder and any other elements on each side,
by chainage range), and it produces the same edge table a Civil 3D corridor gives (``corridor.Edges``,
codes ETW / EPS / ...), so every tool measures from and snaps to it unchanged. A simplified cross-section
shape (``corridor.Sections``: crossfall, hinge at the outer edge, a batter to the existing ground at the
centreline) lets the embankment barrier rule estimate fill heights; it is flagged as approximate.

Default widths are RDM 1.3 Tables 4.23 / 4.24 (one direction of the single-carriageway sections).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .corridor import Edges, Sections

SOURCE = "typical section"

# RDM 1.3 Table 4.23 (inter-urban and rural) and Table 4.24 (urban), single carriageways: elements of
# one side, from the centreline outwards, (code, width m).
STANDARD: Dict[str, dict] = {
    "R4": {"name": "R4 Paved, 2 x 3.65 m lanes, 2.50 m shoulders",
           "side": [("ETW", 3.65), ("EPS", 2.50)]},
    "R5": {"name": "R5 Paved, 2 x 3.50 m lanes, 2.00 m shoulders",
           "side": [("ETW", 3.50), ("EPS", 2.00)]},
    "R6": {"name": "R6 Paved, 2 x 3.25 m lanes, 1.50 m shoulders",
           "side": [("ETW", 3.25), ("EPS", 1.50)]},
    "R7": {"name": "R7 Paved, 2 x 3.00 m lanes, 1.00 m shoulders",
           "side": [("ETW", 3.00), ("EPS", 1.00)]},
    "R8": {"name": "R8 Gravel, 2 x 3.00 m", "side": [("ETW", 3.00)]},
    "R9": {"name": "R9 Earth, 2 x 3.00 m", "side": [("ETW", 3.00)]},
    "U5": {"name": "U5 Paved, 2 x 3.50 m lanes, 1.50 m shoulders, 2.00 m NMT lane, 3.00 m walkway",
           "side": [("ETW", 3.50), ("EPS", 1.50), ("NMT", 2.00), ("Walkway", 3.00)]},
    "U6": {"name": "U6 Paved, 2 x 3.65 m lanes, 3.50 m parking, 3.00 m walkway",
           "side": [("ETW", 3.65), ("Parking", 3.50), ("Walkway", 3.00)]},
}
DEFAULT = "R5"
PAVED = ("ETW", "EPS", "Parking")     # carried at the road's crossfall; anything beyond falls at the verge rate


@dataclass
class SectionRange:
    """A typical section from ``start`` to ``end`` (internal stations; None = the alignment's ends)."""
    left: List[Tuple[str, float]]
    right: List[Tuple[str, float]]
    start: Optional[float] = None
    end: Optional[float] = None
    name: str = ""

    def side(self, side: str) -> List[Tuple[str, float]]:
        return self.left if side == "L" else self.right

    def offsets(self, side: str) -> Dict[str, float]:
        """{code: offset from the centreline} for one side (cumulative widths)."""
        out, acc = {}, 0.0
        for code, w in self.side(side):
            acc += max(0.0, float(w))
            out[code] = acc
        return out

    def to_dict(self):
        return {"name": self.name, "start": self.start, "end": self.end,
                "left": [[c, w] for c, w in self.left], "right": [[c, w] for c, w in self.right]}

    @classmethod
    def from_dict(cls, d):
        return cls([(str(c), float(w)) for c, w in d.get("left", [])],
                   [(str(c), float(w)) for c, w in d.get("right", [])],
                   d.get("start"), d.get("end"), d.get("name", ""))


@dataclass
class TypicalSection:
    ranges: List[SectionRange] = field(default_factory=list)
    transition: float = 30.0       # m: width changes between ranges run linearly over this length
    crossfall: float = 2.5         # % on the carriageway (and parking), falling outwards from the crown
    verge_fall: float = 4.0        # % on the shoulder and beyond
    fill_batter: float = 2.0       # H : 1 V
    cut_batter: float = 1.5        # H : 1 V
    use_over_corridor: bool = False   # use it even where the LandXML has a corridor
    step: float = 10.0             # m: station spacing of the edges and sections

    @classmethod
    def standard(cls, key: str = DEFAULT) -> "TypicalSection":
        s = STANDARD[key]["side"]
        return cls([SectionRange(list(s), list(s), name=key)])

    # ---------------------------------------------------------------- storage (rsd_meta JSON)
    def to_dict(self):
        return {"ranges": [r.to_dict() for r in self.ranges], "transition": self.transition,
                "crossfall": self.crossfall, "verge_fall": self.verge_fall, "fill_batter": self.fill_batter,
                "cut_batter": self.cut_batter, "use_over_corridor": self.use_over_corridor, "step": self.step}

    @classmethod
    def from_dict(cls, d) -> "TypicalSection":
        ts = cls([SectionRange.from_dict(r) for r in d.get("ranges", [])])
        for k in ("transition", "crossfall", "verge_fall", "fill_batter", "cut_batter", "step"):
            if d.get(k) is not None:
                setattr(ts, k, float(d[k]))
        ts.use_over_corridor = bool(d.get("use_over_corridor", False))
        return ts

    # ---------------------------------------------------------------- geometry
    def _ordered(self, al):
        """Ranges with their ends filled in and clipped to the alignment, in chainage order."""
        out = []
        for r in self.ranges:
            a = al.sta_start if r.start is None else max(al.sta_start, float(r.start))
            b = al.sta_end if r.end is None else min(al.sta_end, float(r.end))
            if b > a + 1e-6:
                out.append((a, b, r))
        out.sort(key=lambda t: t[0])
        return out

    def check(self, al) -> List[str]:
        """Problems with the ranges: gaps, overlaps, bad widths. Empty when it is usable."""
        msgs = []
        rs = self._ordered(al)
        if not rs:
            return ["no section range covers the alignment"]
        if rs[0][0] > al.sta_start + 1e-3:
            msgs.append(f"no section from {al.sta_start:.0f} to {rs[0][0]:.0f}")
        if rs[-1][1] < al.sta_end - 1e-3:
            msgs.append(f"no section from {rs[-1][1]:.0f} to {al.sta_end:.0f}")
        for (a0, b0, _), (a1, b1, _) in zip(rs, rs[1:]):
            if a1 > b0 + 1e-3:
                msgs.append(f"no section from {b0:.0f} to {a1:.0f}")
            elif a1 < b0 - 1e-3:
                msgs.append(f"sections overlap from {a1:.0f} to {min(b0, b1):.0f}")
        for _, _, r in rs:
            for sd in "LR":
                if not r.side(sd):
                    msgs.append(f"{r.name or 'section'}: no elements on the {'left' if sd == 'L' else 'right'}")
                if any(w <= 0 for _, w in r.side(sd)):
                    msgs.append(f"{r.name or 'section'}: a width of zero or less")
        return msgs

    def offsets_at(self, al, sta: float, side: str) -> Dict[str, float]:
        """{code: offset} at a station: the range's offsets, blended from the previous range over
        ``transition`` m after a change (codes in both ranges only; others start at the boundary)."""
        rs = self._ordered(al)
        if not rs:
            return {}
        starts = [a for a, _, _ in rs]
        i = max(0, bisect.bisect_right(starts, sta + 1e-9) - 1)
        a, b, r = rs[i]
        if sta > b + 1e-6:                  # in a gap after this range: hold it
            return r.offsets(side)
        cur = r.offsets(side)
        if i > 0 and self.transition > 0 and sta < a + self.transition:
            prev = rs[i - 1][2].offsets(side)
            t = max(0.0, (sta - a) / self.transition)
            return {c: (prev[c] + (o - prev[c]) * t if c in prev else o) for c, o in cur.items()}
        return cur

    def stations(self, al) -> List[float]:
        st = set()
        s = al.sta_start
        while s < al.sta_end - 1e-6:
            st.add(round(s, 3))
            s += self.step
        st.add(round(al.sta_end, 3))
        for a, b, _ in self._ordered(al):
            for v in (a, b, a + self.transition):
                if al.sta_start - 1e-6 <= v <= al.sta_end + 1e-6:
                    st.add(round(v, 3))
        return sorted(st)

    def edges(self, al) -> Optional[Edges]:
        data: Dict[Tuple[str, str], List[Tuple[float, float]]] = {}
        for s in self.stations(al):
            for side in "LR":
                for code, off in self.offsets_at(al, s, side).items():
                    data.setdefault((code, side), []).append((s, off))
        return Edges(data) or None

    def _ground(self, al, sta):
        g = getattr(al, "ground", None) or []
        if len(g) < 2:
            return None
        xs = [p[0] for p in g]
        if sta < xs[0] - 1e-6 or sta > xs[-1] + 1e-6:
            return None
        i = min(len(g) - 1, max(1, bisect.bisect_left(xs, sta)))
        (s0, z0), (s1, z1) = g[i - 1], g[i]
        return z0 if s1 - s0 < 1e-9 else z0 + (z1 - z0) * (sta - s0) / (s1 - s0)

    def sections(self, al) -> Optional[Sections]:
        """Simplified shapes: crown at the centreline, the paved width at the crossfall, the verge at its
        fall, Hinge at the outer edge, then a batter to the existing ground level of the centreline
        (Daylight). Elevations are relative to the design level, as Civil 3D writes them."""
        prof = getattr(al, "profile", None)
        data = {}
        for s in self.stations(al):
            zd = prof.elevation(s) if prof is not None else None
            zg = self._ground(al, s)
            for side in "LR":
                offs = sorted(self.offsets_at(al, s, side).items(), key=lambda t: t[1])
                if not offs:
                    continue
                pts, z, x = [], 0.0, 0.0
                for code, o in offs:
                    rate = self.crossfall if code in PAVED else self.verge_fall
                    z -= (o - x) * rate / 100.0
                    x = o
                    pts.append((round(o, 4), round(z, 4), code))
                pts.append((round(x, 4), round(z, 4), "Hinge"))
                if zd is not None and zg is not None:
                    dz = (zg - zd) - z                     # ground relative to the hinge
                    run = abs(dz) * (self.fill_batter if dz < 0 else self.cut_batter)
                    pts.append((round(x + max(run, 0.01), 4), round(z + dz, 4), "Daylight"))
                data.setdefault(s, {})[side] = pts
        return Sections(data) or None


def apply(al, ts: Optional[TypicalSection], force: bool = False) -> bool:
    """Give the alignment edges and sections from the typical section where it has no corridor
    (or always, with ``use_over_corridor`` / ``force``). Marks ``al.edge_source``. True if applied."""
    if getattr(al, "edge_source", None) is None:
        al.edge_source = "corridor" if al.edges else ""
        al.corridor_edges, al.corridor_sections = al.edges, al.sections
    if ts is None or not ts.ranges:
        if al.edge_source == SOURCE:           # switched off: back to the corridor (or nothing)
            al.edges, al.sections = al.corridor_edges, al.corridor_sections
            al.edge_source = "corridor" if al.edges else ""
        return False
    if al.corridor_edges and not (ts.use_over_corridor or force):
        al.edges, al.sections, al.edge_source = al.corridor_edges, al.corridor_sections, "corridor"
        return False
    al.edges, al.sections = ts.edges(al), ts.sections(al)
    al.edge_source = SOURCE
    return True


def compare(al, ts: TypicalSection, codes=("ETW", "EPS"), tol=0.3) -> List[str]:
    """Where a corridor came back from Civil 3D: how its edges differ from the typical section."""
    ce = getattr(al, "corridor_edges", None)
    if not ce:
        return []
    out = []
    for code in codes:
        for side in "LR":
            worst = None
            for s in ts.stations(al):
                o = ce.offset(code, side, s)
                t = ts.offsets_at(al, s, side).get(code)
                if o is None or t is None:
                    continue
                d = o - t
                if abs(d) > tol and (worst is None or abs(d) > abs(worst[1])):
                    worst = (s, d)
            if worst:
                out.append(f"{code} {'left' if side == 'L' else 'right'}: corridor differs from the typical "
                           f"section by up to {worst[1]:+.2f} m (at {worst[0]:.0f})")
    return out
