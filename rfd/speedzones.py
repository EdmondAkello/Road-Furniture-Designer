"""Speed limit zones (RDM 6.2 3.5): the posted limit is the designer's decision; RFD signs it.

RDM 6.2 3.5.1 prescribes four maximum limits: built-up area 50 km/h (P5), special 70 or
80 km/h (P6, P7), the general limit 100 km/h (no sign: it applies where no other limit is
signed) and expressway 120 km/h (P8). The end of a built-up or special limit, and the
return to the general limit, is signed with P9. Signs go at the start, the middle and the
end of the section (3.5), both directions, and repeaters as the engineer decides.

Given a zone (from, to, limit) RFD proposes, for each direction of travel:
  * the limit sign where traffic enters the zone
  * a repeater at the middle (and more at ``repeat`` m intervals when set)
  * P9 where traffic leaves the zone, unless it enters an adjoining zone there (that zone's
    own limit sign then marks the change)
and checks the limit against the design speed of the section. Everything a zone creates
shares the rule "speed:<id>" so it is listed and removed as one.
"""
from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .autoplace import Finding, Proposal

LIMIT_SIGNS = {50: "P5", 70: "P6", 80: "P7", 120: "P8"}
END_SIGN = "P9"
GENERAL_LIMIT = 100
LIMIT_TEXT = {50: "built-up area limit 50 km/h", 70: "special limit 70 km/h", 80: "special limit 80 km/h",
              120: "expressway limit 120 km/h"}


@dataclass
class SpeedZone:
    start: float                    # internal stations
    end: float
    limit: int                      # km/h: 50, 70, 80 or 120
    id: str = field(default_factory=lambda: _uuid.uuid4().hex[:8])

    def __post_init__(self):
        if self.end < self.start:
            self.start, self.end = self.end, self.start
        if int(self.limit) not in LIMIT_SIGNS:
            raise ValueError(f"RDM 6.2 3.5.1 has speed limit signs for {sorted(LIMIT_SIGNS)} km/h, "
                             f"not {self.limit}")
        self.limit = int(self.limit)

    @property
    def rule(self) -> str:
        return f"speed:{self.id}"


@dataclass
class ZoneDesign:
    zone: SpeedZone
    signs: List[Proposal] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    summary: str = ""


def design_zone(al, zone: SpeedZone, repeat: Optional[float] = None, neighbours: Sequence[SpeedZone] = (),
                min_length: float = 100.0) -> ZoneDesign:
    """Signs and checks for one zone. neighbours: other zones on the road (a shared boundary gets the next
    zone's limit sign instead of P9)."""
    lo, hi = max(zone.start, al.sta_start), min(zone.end, al.sta_end)
    if hi - lo < 1e-6:
        raise ValueError("The speed limit zone is outside the alignment")
    out = ZoneDesign(zone)
    code, rule = LIMIT_SIGNS[zone.limit], zone.rule
    joins = lambda s: any(abs(n.start - s) < 1.0 or abs(n.end - s) < 1.0 for n in neighbours if n.id != zone.id)
    at_lo, at_hi = lo <= al.sta_start + 1e-6, hi >= al.sta_end - 1e-6
    why = f"{LIMIT_TEXT[zone.limit]} (RDM 6.2 3.5)"
    # forward traffic enters at lo, leaves at hi (left side); backward enters at hi, leaves at lo (right side)
    for facing, side, enter, leave, enter_open, leave_open, g in (
            ("Forward", "L", lo, hi, at_lo, at_hi, "f"), ("Backward", "R", hi, lo, at_hi, at_lo, "b")):
        if not enter_open:
            out.signs.append(Proposal(code, enter, side, facing, rule, f"start of {why}", group=f"{zone.id}{g}s"))
        else:
            out.findings.append(Finding("speed_note", enter, enter, facing,
                                        f"the {zone.limit} km/h zone starts at the alignment end: sign the start "
                                        f"on the approach road"))
        if leave_open:
            out.findings.append(Finding("speed_note", leave, leave, facing,
                                        f"the {zone.limit} km/h zone runs to the alignment end: sign its end on "
                                        f"the road beyond"))
        elif not joins(leave):
            out.signs.append(Proposal(END_SIGN, leave, side, facing, rule,
                                      f"end of the {zone.limit} km/h limit (RDM 6.2 3.5.1, Figure 3.23)",
                                      group=f"{zone.id}{g}e"))
    # repeaters: the middle of the section (3.5), and every `repeat` m if asked
    reps = []
    if repeat and repeat > 0:
        n = int((hi - lo) // repeat)
        reps = [lo + repeat * k for k in range(1, n + 1) if lo + repeat * k < hi - repeat / 2]
    elif hi - lo >= 2 * min_length:
        reps = [(lo + hi) / 2]
    for k, s in enumerate(reps):
        out.signs.append(Proposal(code, s, "L", "Forward", rule, f"repeater, {why}", group=f"{zone.id}r{k}f"))
        out.signs.append(Proposal(code, s, "R", "Backward", rule, f"repeater, {why}", group=f"{zone.id}r{k}b"))
    # checks
    if hi - lo < min_length:
        out.findings.append(Finding("speed_note", lo, hi, "Both",
                                    f"zone is only {hi - lo:.0f} m long: check it is worth signing"))
    over = _over_design(al, lo, hi, zone.limit)
    if over:
        a, b, v = over
        out.findings.append(Finding("speed_check", a, b, "Both",
                                    f"the {zone.limit} km/h limit is above the {v:.0f} km/h design speed over "
                                    f"{b - a:.0f} m of the zone", {"design_speed": v}))
    out.summary = (f"{LIMIT_SIGNS[zone.limit]} {zone.limit} km/h, {hi - lo:.0f} m: {len(out.signs)} signs "
                   f"({len(reps)} repeater pair{'s' if len(reps) != 1 else ''})")
    return out


def _over_design(al, lo, hi, limit, step=10.0) -> Optional[Tuple[float, float, float]]:
    """The part of [lo, hi] where the design speed is below the limit: (from, to, lowest design speed)."""
    if not getattr(al, "speeds", None):
        return None
    pts, s = [], lo
    while s <= hi + 1e-6:
        v = al.speed_at(min(s, hi))
        if v is not None and v < limit - 1e-6:
            pts.append((s, v))
        s += step
    if not pts:
        return None
    return pts[0][0], min(pts[-1][0] + step, hi), min(v for _, v in pts)


def zones_from_design_speed(al, limits=(50,), min_length: float = 100.0) -> List[SpeedZone]:
    """Suggested zones where the design speed equals a signed limit: by default only the 50 km/h
    (built-up area) sections. A rural design speed of 70 or 80 km/h does not by itself call for a
    special limit; pass ``limits`` to include them. The posted limit is the designer's call."""
    out: List[SpeedZone] = []
    sp = sorted(getattr(al, "speeds", []) or [])
    if not sp:
        return out
    bounds = [max(s, al.sta_start) for s, _ in sp] + [al.sta_end]
    for (s, v), b in zip(sp, bounds[1:]):
        a = max(s, al.sta_start)
        if int(round(v)) in limits and b - a >= min_length:
            if out and out[-1].limit == int(round(v)) and abs(out[-1].end - a) < 1.0:
                out[-1].end = b
            else:
                out.append(SpeedZone(a, b, int(round(v))))
    return out


def zones_from_signs(signs, al=None) -> List[dict]:
    """Zones in a project, from its sign dicts with rule speed:<id>: {id, limit, start, end, signs}."""
    by = {}
    inv = {c: v for v, c in LIMIT_SIGNS.items()}
    for s in signs:
        r = s.get("rule") or ""
        if r.startswith("speed:"):
            by.setdefault(r[6:], []).append(s)
    out = []
    for gid, ss in by.items():
        lim = next((inv[s["code"]] for s in ss if s["code"] in inv), None)
        sts = [s["sta"] for s in ss]
        out.append({"id": gid, "limit": lim, "start": min(sts), "end": max(sts), "signs": ss,
                    "status": "proposed" if any(s.get("status") == "proposed" for s in ss) else "approved"})
    return sorted(out, key=lambda z: z["start"])
