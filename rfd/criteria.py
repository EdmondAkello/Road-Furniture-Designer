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


_USER_DIRS: List[str] = []
REQUIRED = ("side_friction", "ssd", "psd")


def add_search_dir(path: str) -> None:
    """Register a folder of user criteria files (searched before the bundled ones)."""
    if path and os.path.isdir(path) and path not in _USER_DIRS:
        _USER_DIRS.append(path)
        _CACHE.clear()


def search_dirs() -> List[str]:
    """User folders (RFD_CRITERIA_PATH, then registered), then the bundled folder."""
    env = [d for d in os.environ.get("RFD_CRITERIA_PATH", "").split(os.pathsep) if d and os.path.isdir(d)]
    return env + [d for d in _USER_DIRS if d not in env] + [CRITERIA_DIR]


def _files() -> Dict[str, str]:
    """{id: path}; a user file with the same id as a bundled one replaces it."""
    out: Dict[str, str] = {}
    for d in reversed(search_dirs()):            # bundled first, user folders override
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".json"):
                continue
            path = os.path.join(d, fn)
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and (str(data.get("schema", "")).startswith("rfd-criteria") or "ssd" in data):
                out[data.get("id", fn[:-5])] = path
    return out


def list_criteria() -> List[Tuple[str, str]]:
    """[(id, name)] of the available criteria sets, the default first."""
    out = []
    for ident, path in _files().items():
        with open(path, encoding="utf-8") as fh:
            out.append((ident, json.load(fh).get("name", ident)))
    return sorted(out, key=lambda t: (t[0] != DEFAULT_ID, t[1].lower()))


def _resolve(ident: str, seen=()) -> dict:
    """Load a criteria file, applying "extends" (top-level keys override; references merge)."""
    path = ident if os.path.isfile(str(ident)) else _files().get(ident)
    if not path:
        raise ValueError(f"Criteria set '{ident}' not found in {search_dirs()}")
    path = os.path.abspath(path)
    if path in seen:
        raise ValueError(f"Circular 'extends' in criteria: {' -> '.join(seen + (path,))}")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("id", os.path.splitext(os.path.basename(path))[0])
    base_id = data.get("extends")
    if base_id:
        base_path = _files().get(base_id)
        if base_path and os.path.abspath(base_path) == path:   # user file overriding a bundled set of the same id
            base_path = os.path.join(CRITERIA_DIR, f"{base_id}.json")
        base = _resolve(base_path or base_id, seen + (path,))
        refs = dict(base.get("references", {}))
        refs.update(data.get("references", {}))
        if "barrier_warrant" not in data and isinstance(base.get("barrier_warrant"), str):
            data["barrier_warrant"] = _find_warrant(base["barrier_warrant"], base["_path"])
        merged = dict(base)
        merged.update(data)
        merged["references"] = refs
        data = merged
    data["_path"] = path
    return data


class Criteria:
    def __init__(self, data: dict):
        missing = [k for k in REQUIRED if not data.get(k)]
        if missing:
            raise ValueError(f"Criteria '{data.get('id', '?')}' is missing required tables: {', '.join(missing)}")
        self.data = data
        self.id = data.get("id", "custom")
        self.name = data.get("name", self.id)
        self.refs: Dict[str, str] = data.get("references", {})
        self.path = data.get("_path", "")

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, ident: str = DEFAULT_ID) -> "Criteria":
        return cls(_resolve(ident))

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

    def warrant_curve(self) -> Optional[dict]:
        if not hasattr(self, "_warrant"):
            self._warrant = _load_warrant(self.data.get("barrier_warrant"), self.path)
        return self._warrant

    def barrier_warrant(self, height: float, slope_n: float) -> str:
        """'required' / 'judgement' / 'not_required' from the set's warrant curve.

        Without a curve the set's simple rule applies: barrier_simple {height, slope_n}
        (fill higher than height on a batter steeper than 1:slope_n)."""
        w = self.warrant_curve()
        if w:
            return _warrant_class(w, height, slope_n)
        simple = self.barrier().get("simple") or {"height": 6.0, "slope_n": 4.0}
        return "required" if (height >= simple["height"] and slope_n < simple["slope_n"]) else "not_required"


# ---------------------------------------------------------------------- barrier warrant
def _find_warrant(spec: str, base_path: str) -> str:
    """Warrant file path: absolute, or relative to the criteria file, or in the bundled data folder."""
    for d in (os.path.dirname(base_path), os.path.dirname(CRITERIA_DIR)):
        p = spec if os.path.isabs(spec) else os.path.join(d, spec)
        if os.path.isfile(p):
            return p
    raise ValueError(f"Barrier warrant file '{spec}' not found")


def _load_warrant(spec, base_path: str) -> Optional[dict]:
    if not spec:
        return None
    if isinstance(spec, str):
        with open(_find_warrant(spec, base_path), encoding="utf-8") as fh:
            return json.load(fh)
    return spec


def _warrant_class(w: dict, height: float, slope_n: float) -> str:
    hs = w["heights"]
    if height < hs[0] or slope_n <= 0:
        return "not_required"
    req = float(interpolate(dict(zip(map(str, hs), w["required_below"])), height))
    nreq = float(interpolate(dict(zip(map(str, hs), w.get("not_required_above", w["required_below"]))), height))
    if slope_n < req:
        return "required"
    if slope_n < nreq:
        return "judgement"
    return "not_required"


def barrier_warrant(height: float, slope_n: float, crit: "Criteria" = None) -> str:
    """Embankment barrier warrant (default: RDM 1.3 Figure 12.4, digitised).

    height: fill height (m, hinge to toe); slope_n: batter as 1:n (horizontal per vertical).
    Returns 'required', 'judgement' or 'not_required'."""
    return (crit or get()).barrier_warrant(height, slope_n)


_CACHE: Dict[str, Criteria] = {}


def get(ident: str = DEFAULT_ID) -> Criteria:
    if ident not in _CACHE:
        _CACHE[ident] = Criteria.load(ident)
    return _CACHE[ident]
