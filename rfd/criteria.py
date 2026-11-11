"""Design criteria from JSON files (rfd/data/criteria).

The default is the Kenya Road Design Manual (2025): RDM 1.3 for geometry, sight
distance, clear zones and barriers; RDM 6.1 for marking visibility. The previous
built-in AASHTO 2011 values are kept as an alternative file. Speed-keyed tables
are interpolated linearly and clamped at their ends; every value carries the
table it came from (``ref``) so reports can cite it.
"""
from __future__ import annotations

import json
import math
import os
from bisect import bisect_left
from typing import Dict, List, Optional, Tuple

CRITERIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "criteria")
DEFAULT_ID = "kenya_rdm_2025"
WARRANT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rdm13_fig12_4_barrier_warrant.json")


def interpolate(mapping, x: float) -> Optional[float]:
    if not mapping:
        return None
    pairs = sorted((float(k), v) for k, v in mapping.items() if v is not None)
    keys = [p[0] for p in pairs]
    vals = [p[1] for p in pairs]
    if x <= keys[0]:
        return vals[0]
    if x >= keys[-1]:
        return vals[-1]
    i = bisect_left(keys, x)
    if keys[i] == x:
        return vals[i]
    t = (x - keys[i - 1]) / (keys[i] - keys[i - 1])
    return vals[i - 1] + t * (vals[i] - vals[i - 1])


def list_criteria() -> List[Tuple[str, str]]:
    """[(id, name)] of the bundled criteria files, Kenya first."""
    out = []
    for fn in sorted(os.listdir(CRITERIA_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(CRITERIA_DIR, fn), encoding="utf-8") as fh:
                d = json.load(fh)
            out.append((d.get("id", fn[:-5]), d.get("name", fn[:-5])))
    return sorted(out, key=lambda t: t[0] != DEFAULT_ID)


class Criteria:
    def __init__(self, data: dict):
        self.data = data
        self.id = data.get("id", "custom")
        self.name = data.get("name", self.id)
        self.refs: Dict[str, str] = data.get("references", {})

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, ident: str = DEFAULT_ID) -> "Criteria":
        path = ident if os.path.isfile(str(ident)) else os.path.join(CRITERIA_DIR, f"{ident}.json")
        with open(path, encoding="utf-8") as fh:
            return cls(json.load(fh))

    def ref(self, key: str) -> str:
        return self.refs.get(key, self.name)

    @property
    def is_kenya(self) -> bool:
        return self.id.startswith("kenya")

    # ------------------------------------------------------------------ heights
    @property
    def eye_height(self) -> float:
        return float(self.data.get("eye_height", 1.05))

    @property
    def object_height(self) -> float:
        return float(self.data.get("object_height", 0.2))

    @property
    def psd_object_height(self) -> float:
        return float(self.data.get("psd_object_height", 1.3))

    @property
    def headlight(self) -> Tuple[float, float]:
        return float(self.data.get("headlight_height", 0.6)), float(self.data.get("headlight_angle_degrees", 1.0))

    # ------------------------------------------------------------------ speed tables
    def f_max(self, v: float) -> float:
        """Side friction factor at design speed v (RDM 1.3 Table 5.1)."""
        return float(interpolate(self.data["side_friction"], v))

    def ssd(self, v: float, grade_pct: float = 0.0) -> float:
        """Stopping sight distance; corrected for grade where the table gives it (RDM 1.3 Table 3.16)."""
        by = self.data.get("ssd_by_grade")
        base = float(interpolate(self.data["ssd"], v))
        if not by:
            return base
        grades = by["grades"]                         # e.g. [9, 6, 3, 0, -3, -6, -9]
        rows = {float(k): r for k, r in by.items() if k != "grades"}
        speeds = sorted(rows)

        def at_speed(sv):
            r = rows[sv]
            pts = sorted((g, d) for g, d in zip(grades, r) if d is not None)
            gs, ds = [p[0] for p in pts], [p[1] for p in pts]
            g = min(max(grade_pct, gs[0]), gs[-1])
            return float(interpolate(dict(zip(map(str, gs), ds)), g))
        if v <= speeds[0]:
            return at_speed(speeds[0])
        if v >= speeds[-1]:
            return at_speed(speeds[-1])
        i = bisect_left(speeds, v)
        if speeds[i] == v:
            return at_speed(v)
        a, b = speeds[i - 1], speeds[i]
        return at_speed(a) + (v - a) / (b - a) * (at_speed(b) - at_speed(a))

    def psd(self, v: float, reduced: bool = True) -> float:
        """Passing sight distance. Kenya: Table 3.20, reduced value by default (allowed in constrained cases)."""
        key = "psd_reduced" if reduced and "psd_reduced" in self.data else "psd"
        return float(interpolate(self.data[key], v))

    def k_crest(self, v: float) -> Optional[float]:
        t = self.data.get("k_crest")
        return float(interpolate(t, v)) if t else None

    def k_sag(self, v: float) -> Optional[float]:
        t = self.data.get("k_sag")
        return float(interpolate(t, v)) if t else None

    # ------------------------------------------------------------------ roadside
    def clear_zone(self, v: float, fill: bool = True, low_traffic: bool = False) -> Optional[float]:
        cz = self.data.get("clear_zone")
        if not cz:
            return None
        t = cz["low_traffic" if low_traffic else "medium_traffic"]["fill" if fill else "cut"]
        return float(interpolate(t, v))

    def barrier(self) -> dict:
        return self.data.get("barrier") or {}

    def barrier_runout(self, v: float) -> Optional[float]:
        b = self.barrier()
        return float(interpolate(b["runout"], v)) if b.get("runout") else None

    def marking_visibility(self, v: float, road_class: str = "") -> Tuple[float, float]:
        """(visibility distance, critical value) for the combined line system, RDM 6.1 Table 4.4.

        Chosen by road class when given, else by speed (85th percentile, taken as the design speed)."""
        mv = self.data.get("marking_visibility")
        if not mv:
            d = self.psd(v)
            return d, d
        rows = mv["rows"]
        if road_class:
            for r in rows:
                if road_class.upper() in r["classes"]:
                    return float(r["visibility"]), float(r["critical"])
        row = rows[0]
        for r in rows:
            if v >= r["speed"] - 1e-6:
                row = r
        return float(row["visibility"]), float(row["critical"])


# ---------------------------------------------------------------------- barrier warrant
_WARRANT = None


def _warrant():
    global _WARRANT
    if _WARRANT is None:
        with open(WARRANT_FILE, encoding="utf-8") as fh:
            _WARRANT = json.load(fh)
    return _WARRANT


def barrier_warrant(height: float, slope_n: float) -> str:
    """Embankment barrier warrant from RDM 1.3 Figure 12.4 (digitised).

    height: fill height (m, hinge to toe); slope_n: batter as 1:n (horizontal per vertical).
    Returns 'required', 'judgement' or 'not_required'."""
    w = _warrant()
    hs = w["heights"]
    if height < hs[0] or slope_n <= 0:
        return "not_required"
    req = float(interpolate(dict(zip(map(str, hs), w["required_below"])), height))
    nreq = float(interpolate(dict(zip(map(str, hs), w["not_required_above"])), height))
    if slope_n < req:
        return "required"
    if slope_n < nreq:
        return "judgement"
    return "not_required"


_CACHE: Dict[str, Criteria] = {}


def get(ident: str = DEFAULT_ID) -> Criteria:
    if ident not in _CACHE:
        _CACHE[ident] = Criteria.load(ident)
    return _CACHE[ident]
