"""Road edges from Civil 3D corridor sections (LandXML CrossSect / DesignCrossSectSurf).

Civil 3D writes, at each sampled station, the corridor links with coded points
(offset, elevation): ETW (edge of travelled way), EPS (edge of paved shoulder),
Hinge, Ditch_In, Ditch_Out, Daylight... Offsets are from the alignment,
negative to the left. Each code/side becomes an edge whose offset varies with
station, so a sign can be placed "1.0 m beyond EPS" and its clearance reported.
"""
from __future__ import annotations

import bisect
from typing import Dict, List, Optional, Tuple

# point codes that describe pavement layers, not edges you would sign from
LAYER_SUFFIXES = ("_Pave", "_Pave1", "_Pave2", "_Base", "_Sub", "_SubBase", "_Datum")
SKIP_PREFIX = ("Crown",)
# preferred reference for clearance, in order
EDGE_PREFERENCE = ("EPS", "EOS", "ESH", "Shoulder", "ETW", "EOP", "EP")
TRAVELLED_WAY = ("ETW", "EOP", "EP")
SHOULDER = ("EPS", "EOS", "ESH", "Shoulder")
MAX_GAP = 30.0   # m: don't interpolate an edge across longer gaps (e.g. Daylight only in cut)


def keep_code(code: str) -> bool:
    if not code or code.startswith(SKIP_PREFIX):
        return False
    return not any(code.endswith(s) for s in LAYER_SUFFIXES)


class Edges:
    """{(code, side): [(station, offset_abs)]} with interpolation."""

    def __init__(self, data: Dict[Tuple[str, str], List[Tuple[float, float]]]):
        self.data = {}
        for k, pts in data.items():
            pts = sorted(pts)
            dedup = []
            for s, o in pts:
                if dedup and abs(dedup[-1][0] - s) < 1e-6:
                    dedup[-1] = (s, max(dedup[-1][1], o))
                else:
                    dedup.append((s, o))
            if len(dedup) >= 2:
                self.data[k] = dedup
        self._st = {k: [p[0] for p in v] for k, v in self.data.items()}
        # gap allowed before an edge is treated as absent: 3x its usual section spacing (at least MAX_GAP)
        self._gap = {}
        for k, st in self._st.items():
            steps = sorted(b - a for a, b in zip(st, st[1:]))
            self._gap[k] = max(MAX_GAP, 3.0 * steps[len(steps) // 2]) if steps else MAX_GAP

    def __bool__(self):
        return bool(self.data)

    def codes(self) -> List[str]:
        """Edge codes ordered from the centreline outwards (by median offset)."""
        med = {}
        for (c, _), pts in self.data.items():
            v = sorted(o for _, o in pts)
            med[c] = min(med.get(c, 1e9), v[len(v) // 2])
        return sorted(med, key=lambda c: med[c])

    def offset(self, code: str, side: str, station: float) -> Optional[float]:
        pts = self.data.get((code, side))
        if not pts:
            return None
        st = self._st[(code, side)]
        if station < st[0] - 1e-6 or station > st[-1] + 1e-6:
            return None
        i = bisect.bisect_left(st, station)
        if i < len(st) and abs(st[i] - station) < 1e-6:
            return pts[i][1]
        if i == 0 or i >= len(st):
            return None
        (s0, o0), (s1, o1) = pts[i - 1], pts[i]
        if s1 - s0 > self._gap[(code, side)]:
            return None
        return o0 + (o1 - o0) * (station - s0) / (s1 - s0)

    def reference(self) -> Optional[str]:
        codes = {c for c, _ in self.data}
        for c in EDGE_PREFERENCE:
            if c in codes:
                return c
        return None

    def first(self, candidates, side, station):
        for c in candidates:
            o = self.offset(c, side, station)
            if o is not None:
                return c, o
        return None, None


def collect_section(acc: Dict, station: float, section_el, local) -> None:
    """Add one CrossSect's coded points to the accumulator {(code, side): [(sta, off)]}."""
    seen = {}
    for item in section_el:
        if local(item.tag) != "DesignCrossSectSurf":
            continue
        for p in item:
            code = p.get("code")
            if not keep_code(code) or not p.text:
                continue
            parts = p.text.split()
            try:
                off = float(parts[0])
            except (IndexError, ValueError):
                continue
            side = "L" if off < 0 else "R"
            if abs(off) < 1e-6:
                continue
            k = (code, side)
            seen[k] = max(seen.get(k, 0.0), abs(off))
    for k, o in seen.items():
        acc.setdefault(k, []).append((station, o))


RDM_MIN_CLEAR, RDM_MAX_CLEAR = 0.6, 3.0     # RDM 6.2 2.4: posts 600 mm to 3 m from carriageway / shoulder edge


def outer_limit(edges, side, station):
    """Outermost corridor offset at a station (ditch / daylight / last coded point)."""
    best = None
    for (code, sd), _ in edges.data.items():
        if sd != side:
            continue
        o = edges.offset(code, side, station)
        if o is not None:
            best = o if best is None else max(best, o)
    return best


def clamp_offset(edges, side, station, offset_abs, ref=None):
    """Keep a sign inside the corridor: RDM band beyond the reference edge, never past the outer limit.

    Returns (offset_abs, note) - note is "" when nothing changed."""
    if not edges:
        return offset_abs, ""
    ref = ref or edges.reference()
    ro = edges.offset(ref, side, station) if ref else None
    lo, hi = None, None
    if ro is not None:
        lo, hi = ro + RDM_MIN_CLEAR, ro + RDM_MAX_CLEAR
    outer = outer_limit(edges, side, station)
    if outer is not None and (ro is None or outer >= ro + RDM_MIN_CLEAR):   # verge is modelled
        hi = outer if hi is None else min(hi, outer)
    new = offset_abs
    if lo is not None and new < lo:
        new = lo
    if hi is not None and new > hi and (lo is None or hi >= lo):
        new = hi
    return new, ("" if abs(new - offset_abs) < 1e-6 else f"snapped {offset_abs:.2f} -> {new:.2f} m")


def edge_polylines(al):
    """[(code, side, [(x, y), ...])] - each modelled edge as world polylines, split where sections are missing."""
    out = []
    edges = getattr(al, "edges", None)
    if not edges:
        return out
    for (code, side), pts in sorted(edges.data.items()):
        sg = -1.0 if side == "L" else 1.0
        run, prev = [], None
        for sta, off in pts:
            if sta < al.sta_start - 1e-6 or sta > al.sta_end + 1e-6:
                continue
            if prev is not None and sta - prev > edges._gap[(code, side)]:
                if len(run) >= 2:
                    out.append((code, side, run))
                run = []
            run.append(al.point_at(sta, sg * off)[:2])
            prev = sta
        if len(run) >= 2:
            out.append((code, side, run))
    return out
