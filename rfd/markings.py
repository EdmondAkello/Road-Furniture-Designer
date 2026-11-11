"""Longitudinal markings and road studs proposed from RDM 6.1 (2025).

Centre line (sections 4.2, 4.5): broken line where overtaking is allowed; where the
visibility for a direction falls below the critical value of Table 4.4 that direction
gets a continuous line - combined line (LM28) for one direction, double continuous
(LM32) for both. Visibility is scanned along the design profile from an eye 1.05 m high
to a target of the same height, and optionally round bends against a sight obstruction
at a given offset from the centreline.

  - a continuous line needed over 20-50 m is laid as 50 m; shorter needs are dropped
  - continuous lines for one direction closer together than the critical value are joined
  - a gap between continuous sections shorter than the visibility distance is closed
    (4.5.2), so no broken element is shorter than the visibility distance
  - carriageway under 5.5 m: no centre line; a single continuous line (LM24) where
    visibility is restricted (4.5.5)

Edge lines (4.2.3): continuous at the edge of the travelled way, both sides.
Road studs (13.3, Table 13.2, 4.5.1): 6 m on the combined line system, 9 m on edge lines
through no-overtaking sections, 12 m elsewhere.

Not covered: interruption through junctions, splayed/hatched double lines on sharp
bends (Figure 4.6), lane lines on multi-lane roads.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from . import criteria as _crit
from .autoplace import Finding, sight_distances, sight_profile
from .linear import RURAL_SPEED, Run

HIGHER_CLASSES = ("A", "B", "UA")
MIN_CARRIAGEWAY = 5.5       # m, RDM 6.1 sections 4.2.1 and 4.5.5
DROP_BELOW = 20.0           # m, a continuous line needed over less than this is not laid (4.5)


@dataclass
class MarkingConfig:
    road_class: str = ""                # A, B, C, D, E, UA, UC, UL; "" -> Table 4.4 row by design speed
    centre: bool = True
    edges: bool = True
    studs: str = "auto"                 # none | no_overtaking | all | auto (all on class A, else no-overtaking)
    edge_code: str = "ETW"              # corridor edge carrying the edge line
    carriageway: Optional[float] = None # m; None -> from the corridor edge (both sides), else assumed wide enough
    sight_offset: float = 0.0           # m from centreline to the sight obstruction inside bends; 0 = profile only
    stud_setback: float = 0.15          # m outside the edge line where there is a paved shoulder (13.3)
    start: Optional[float] = None
    end: Optional[float] = None
    step: float = 5.0
    criteria: str = _crit.DEFAULT_ID

    @property
    def crit(self):
        return _crit.get(self.criteria)

    @property
    def higher(self) -> Optional[bool]:
        return (self.road_class.upper() in HIGHER_CLASSES) if self.road_class else None


# --------------------------------------------------------------------------- visibility
def horizontal_sight(pts, stations, direction, offset, max_d):
    """Sight distance round bends: the chord from the eye may not pass more than
    ``offset`` m inside the centreline (checked at its quarter points)."""
    n = len(stations)
    out = []
    for i in range(n):
        seen = max_d
        j = i + 2 * direction
        xi, yi = pts[i]
        while 0 <= j < n:
            d = abs(stations[j] - stations[i])
            if d > max_d:
                break
            xj, yj = pts[j]
            L = math.hypot(xj - xi, yj - yi) or 1e-9
            blocked = False
            for q in (0.25, 0.5, 0.75):
                k = i + int(round((j - i) * q))
                xk, yk = pts[k]
                if abs((xj - xi) * (yk - yi) - (yj - yi) * (xk - xi)) / L > offset:
                    blocked = True
                    break
            if blocked:
                seen = d
                break
            j += direction
        out.append(seen)
    return out


def _flag_runs(st, flags):
    runs, cur = [], None
    for s, f in zip(st, flags):
        if f:
            cur = [s, s] if cur is None else [cur[0], s]
        elif cur is not None:
            runs.append(cur); cur = None
    if cur is not None:
        runs.append(cur)
    return runs


def _clean(runs, lo, hi, critical_at, min_line, step):
    """Table 4.4 notes: drop needs under 20 m, lay 20-50 m as 50 m, join lines closer than the critical value."""
    out = []
    for a, b in runs:
        need = b - a + step
        if need < DROP_BELOW:
            continue
        if need < min_line:
            mid = (a + b) / 2
            a, b = mid - min_line / 2, mid + min_line / 2
            if a < lo:
                a, b = lo, min(hi, lo + min_line)
            if b > hi:
                a, b = max(lo, hi - min_line), hi
        if out and a - out[-1][1] < critical_at((a + out[-1][1]) / 2):
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _segments(lo, hi, fwd, bwd):
    """[(start, end, state)] with state '' | 'F' | 'B' | 'FB' from the two directions' continuous lines."""
    cuts = sorted({lo, hi} | {x for r in fwd + bwd for x in r if lo < x < hi})
    segs = []
    for a, b in zip(cuts, cuts[1:]):
        m = (a + b) / 2
        state = ("F" if any(x <= m <= y for x, y in fwd) else "") + ("B" if any(x <= m <= y for x, y in bwd) else "")
        if segs and segs[-1][2] == state:
            segs[-1][1] = b
        else:
            segs.append([a, b, state])
    return segs


def _close_gaps(segs, visibility_at):
    """4.5.2: a gap between continuous sections shorter than the visibility distance is closed (double line)."""
    changed = True
    while changed:
        changed = False
        for i in range(1, len(segs) - 1):
            a, b, state = segs[i]
            if state == "" and segs[i - 1][2] and segs[i + 1][2] and b - a < visibility_at((a + b) / 2):
                segs[i][2] = "FB"
                changed = True
        merged = []
        for s in segs:
            if merged and merged[-1][2] == s[2]:
                merged[-1][1] = s[1]
            else:
                merged.append(list(s))
        segs = merged
    return segs


def _split_at_speed_class(al, a, b):
    """Split a run where the design speed crosses 80 km/h (Table 4.2 / 4.3 dimensions change)."""
    cuts = [a]
    prev = None
    for sta, kmh in sorted(getattr(al, "speeds", []) or []):
        rural = kmh >= RURAL_SPEED
        if prev is not None and rural != prev and a < sta < b:
            cuts.append(sta)
        prev = rural
    cuts.append(b)
    return list(zip(cuts, cuts[1:]))


# --------------------------------------------------------------------------- proposals
def centre_states(al, cfg: MarkingConfig):
    """([(start, end, state)], lo, hi, note) for the centre line; state '' | 'F' | 'B' | 'FB'."""
    lo = max(al.sta_start, cfg.start if cfg.start is not None else al.sta_start)
    hi = min(al.sta_end, cfg.end if cfg.end is not None else al.sta_end)
    crit = cfg.crit
    v_of = lambda s: al.speed_at(s) or 80.0
    vis_at = lambda s: crit.marking_visibility(v_of(s), cfg.road_class)[0]
    crt_at = lambda s: crit.marking_visibility(v_of(s), cfg.road_class)[1]
    mv = crit.data.get("marking_visibility") or {}
    h_eye = float(mv.get("eye_height", crit.eye_height))
    h_tgt = float(mv.get("target_height", h_eye))
    min_line = float(mv.get("min_line", 50.0))
    n = max(1, int(round((hi - lo) / cfg.step)))
    st = [lo + (hi - lo) * k / n for k in range(n + 1)]
    max_d = max(crt_at(s) for s in st) + cfg.step
    pr = al.profile
    note = ""
    if pr is None:
        note = "no design profile in the LandXML: visibility over crests not checked"
    z = [pr.elevation(s) if pr is not None and pr.start <= s <= pr.end else None for s in st]
    pts = [al.point_at(s)[:2] for s in st] if cfg.sight_offset > 0 else None
    cont = {}
    for name, sign in (("F", 1), ("B", -1)):
        sd = sight_distances(st, z, sign, h_eye, h_tgt, max_d) if pr is not None else [max_d] * len(st)
        if pts:
            hs = horizontal_sight(pts, st, sign, cfg.sight_offset, max_d)
            sd = [min(a, b) for a, b in zip(sd, hs)]
        flags = [d < crt_at(s) for s, d in zip(st, sd)]
        cont[name] = _clean(_flag_runs(st, flags), lo, hi, crt_at, min_line, cfg.step)
    segs = _close_gaps(_segments(lo, hi, cont["F"], cont["B"]), vis_at)
    return segs, lo, hi, note


def carriageway_width(al, cfg: MarkingConfig, sta: float) -> Optional[float]:
    if cfg.carriageway:
        return cfg.carriageway
    e = getattr(al, "edges", None)
    if not e:
        return None
    l, r = e.offset(cfg.edge_code, "L", sta), e.offset(cfg.edge_code, "R", sta)
    return (l + r) if l is not None and r is not None else None


def propose_markings(al, cfg: MarkingConfig = None) -> Tuple[List[Run], List[Finding]]:
    cfg = cfg or MarkingConfig()
    crit = cfg.crit
    runs: List[Run] = []
    findings: List[Finding] = []
    segs, lo, hi, note = centre_states(al, cfg)
    if note:
        findings.append(Finding("marking_note", lo, hi, "Both", note))
    v_mid = al.speed_at((lo + hi) / 2) or 80.0
    higher = cfg.higher if cfg.higher is not None else v_mid >= 80.0
    studs = cfg.studs
    if studs == "auto":
        cls = cfg.road_class.upper()
        studs = "all" if (cls == "A" or (not cls and v_mid > 90)) else "no_overtaking"
    ref = crit.ref("marking_visibility")
    width = carriageway_width(al, cfg, (lo + hi) / 2)
    narrow = width is not None and width < MIN_CARRIAGEWAY
    if narrow:
        findings.append(Finding("marking_note", lo, hi, "Both",
                                f"carriageway {width:.1f} m is under {MIN_CARRIAGEWAY} m: no broken centre line or "
                                f"double lines; single continuous line where visibility is restricted "
                                f"(RDM 6.1 4.2.1, 4.5.5)"))

    def add(code, a, b, rule, reason, **kw):
        for x, y in _split_at_speed_class(al, a, b):
            if y - x > 0.01:
                runs.append(Run(code, x, y, status="proposed", rule=rule, reason=reason, **kw))

    # ---- centre line
    if cfg.centre:
        broken = "LM02" if higher else "LM01"
        for a, b, state in segs:
            vis, crt = crit.marking_visibility(al.speed_at((a + b) / 2) or 80.0, cfg.road_class)
            if not state:
                if not narrow:
                    add(broken, a, b, "marking_centre", "Broken centre line (RDM 6.1 4.2.1)")
                if studs == "all" and not narrow:
                    add("RRS-C", a, b, "marking_studs", "Centre line studs at 12 m (RDM 6.1 Table 13.2)")
                continue
            who = {"F": "forward traffic", "B": "backward traffic", "FB": "both directions"}[state]
            why = f"Visibility under the critical value of {crt:.0f} m for {who} ({ref})"
            if narrow:
                add("LM24", a, b, "marking_cls", why + "; single line, carriageway under 5.5 m (4.5.5)")
            elif state == "FB":
                add("LM32", a, b, "marking_cls", why)
            else:
                add("LM28", a, b, "marking_cls", why, flip=(state == "B"))
            if studs != "none":
                add("RRS-CLS", a, b, "marking_studs", "Studs at 6 m on the combined line system (RDM 6.1 4.5.1)")
            findings.append(Finding("marking_cls", a, b, {"F": "Forward", "B": "Backward", "FB": "Both"}[state],
                                    f"continuous centre line over {b - a:.0f} m: visibility < {crt:.0f} m ({ref})",
                                    {"critical": crt, "visibility": vis}))

    # ---- edge lines and their studs
    if cfg.edges:
        e = getattr(al, "edges", None)
        if not e or not any((cfg.edge_code, s) in e.data for s in "LR"):
            findings.append(Finding("marking_note", lo, hi, "Both",
                                    f"no '{cfg.edge_code}' corridor edge in the LandXML: edge lines not proposed"))
        else:
            edge = "LM27" if higher else "LM26"
            shoulder = any(c in ("EPS", "EOS", "ESH", "Shoulder") for c, _ in e.data)
            setback = cfg.stud_setback if shoulder else 0.0
            solid = [(a, b) for a, b, s in segs if s]
            for side in "LR":
                if (cfg.edge_code, side) not in e.data:
                    continue
                add(edge, lo, hi, "marking_edge", "Continuous edge line (RDM 6.1 4.2.3)",
                    side=side, edge_ref=cfg.edge_code, offset=0.0)
                if studs == "none":
                    continue
                for a, b in solid:
                    add("RRS-E", a, b, "marking_studs", "Edge studs at 9 m through a no-overtaking section "
                        "(RDM 6.1 Table 13.2)", side=side, edge_ref=cfg.edge_code, offset=setback, no_overtaking=True)
                if studs == "all":
                    for a, b, s in segs:
                        if not s:
                            add("RRS-E", a, b, "marking_studs", "Edge studs at 12 m (RDM 6.1 Table 13.2)",
                                side=side, edge_ref=cfg.edge_code, offset=setback)
    return runs, findings
