"""Linear road furniture: markings, road studs and barriers as runs along the alignment.

A run is the master record: item code, start and end chainage (internal),
side and an offset that is either from the centreline or from a corridor edge
(``edge_ref``), so the run follows the edge when the road widens. Geometry and
quantities are derived from it.

The catalogue (rfd/data/furniture_linear.json) is open: user files with the
same layout in RFD_FURNITURE_PATH or folders registered with add_search_dir()
add items or replace bundled ones by code.
"""
from __future__ import annotations

import json
import math
import os
import uuid as _uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DEFAULT_PATH = os.path.join(DATA_DIR, "furniture_linear.json")
RURAL_SPEED = 80.0          # RDM 6.1 Table 4.2 applies at 80 km/h and above, Table 4.3 below
DEFAULT_SPEED = 80.0
SIDES = ("L", "C", "R")

_USER_DIRS: List[str] = []


def add_search_dir(path: str) -> None:
    if path and os.path.isdir(path) and path not in _USER_DIRS:
        _USER_DIRS.append(path)


def search_files() -> List[str]:
    """Bundled catalogue first; user files after it (later files override by code)."""
    env = [d for d in os.environ.get("RFD_FURNITURE_PATH", "").split(os.pathsep) if d and os.path.isdir(d)]
    out = [DEFAULT_PATH]
    for d in env + [d for d in _USER_DIRS if d not in env]:
        out += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith(".json")]
    return out


@dataclass
class LinearItem:
    code: str
    category: str                 # Marking | Road stud | Barrier | Barrier terminal | user categories
    name: str
    unit: str = "m"               # m | No. | m2
    colour: str = "white"
    ref: str = ""
    rural: dict = field(default_factory=dict)     # {"mark", "gap", "width", "spacing"} at >= 80 km/h
    urban: dict = field(default_factory=dict)     # the same below 80 km/h
    lines: int = 1
    composite: Optional[List[str]] = None         # e.g. ["continuous", "broken"] for the CLS line
    spacing: Optional[float] = None               # road studs: interval (m)
    spacing_no_overtaking: Optional[float] = None
    terminal: Optional[str] = None                # barriers: terminal item counted at each end
    transverse: bool = False                      # laid across the road (humps, bar sets, crossings): counted
                                                  # per run; the run length is its footprint along the road
    area_factor: object = None                    # transverse painted share of footprint x width, or "bars"
    bars: int = 6                                 # "bars": painted area = bars x bar_width x width
    bar_width: float = 0.3

    @property
    def is_marking(self) -> bool:
        return bool(self.rural or self.urban) and not self.transverse

    @property
    def is_point_series(self) -> bool:
        return self.spacing is not None

    def dims(self, speed: Optional[float]) -> dict:
        v = DEFAULT_SPEED if speed is None else speed
        return (self.rural if v >= RURAL_SPEED else self.urban) or self.rural or self.urban

    def paint_ratio(self, speed: Optional[float]) -> float:
        """Painted length per metre of run, all lines of the item together."""
        d = self.dims(speed)
        mark, gap = float(d.get("mark") or 0), float(d.get("gap") or 0)
        broken = mark / (mark + gap) if mark > 0 and gap > 0 else 1.0
        if self.composite:
            return sum(broken if c == "broken" else 1.0 for c in self.composite)
        return broken * max(1, self.lines)

    def pattern(self, speed: Optional[float]) -> str:
        d = self.dims(speed)
        if not d:
            return ""
        w = f"{d.get('width', 0) * 1000:.0f} mm"
        if d.get("mark") and d.get("gap"):
            return f"{d['mark']:g} m mark / {d['gap']:g} m gap, {w}"
        return f"continuous, {w}"


class LinearCatalogue:
    def __init__(self, items: Dict[str, LinearItem], version: str = "", sources: Optional[List[str]] = None):
        self.items = items
        self.version = version
        self.sources = sources or []

    @classmethod
    def load(cls, paths: Optional[List[str]] = None) -> "LinearCatalogue":
        items: Dict[str, LinearItem] = {}
        version, sources = "", []
        for p in (paths or search_files()):
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or "items" not in data:
                continue
            version = version or data.get("catalogue_version", "")
            sources.append(p)
            for d in data["items"]:
                d = dict(d)
                code = d.pop("code")
                known = {k: d[k] for k in LinearItem.__dataclass_fields__ if k in d}
                items[code] = LinearItem(code=code, **known)
        for it in items.values():
            if it.terminal and it.terminal not in items:
                raise ValueError(f"Linear item {it.code}: terminal '{it.terminal}' is not in the catalogue")
        return cls(items, version, sources)

    def __getitem__(self, code: str) -> LinearItem:
        return self.items[code]

    def __contains__(self, code: str) -> bool:
        return code in self.items

    def categories(self) -> List[str]:
        order = ["Marking", "Road stud", "Barrier", "Barrier terminal"]
        present = {i.category for i in self.items.values()}
        return [c for c in order if c in present] + sorted(present - set(order))

    def by_category(self, category: str) -> List[LinearItem]:
        return [i for i in self.items.values() if i.category == category]


@dataclass
class Run:
    code: str
    sta_start: float               # internal stations
    sta_end: float
    side: str = "C"                # L | C | R
    offset: float = 0.0            # m: outward from edge_ref (L/R), or signed from centreline (+ right) when no edge_ref
    edge_ref: Optional[str] = None
    status: str = "approved"       # approved | proposed
    no_overtaking: bool = False    # road studs at the closer no-overtaking interval
    width: Optional[float] = None  # transverse items: width across the road (m)
    flip: bool = False             # composite lines (CLS): continuous line on the right of chainage direction,
                                   # i.e. overtaking prohibited for traffic running against chainage
    rule: str = ""
    reason: str = ""
    remarks: str = ""
    uuid: str = field(default_factory=lambda: str(_uuid.uuid4()))

    def __post_init__(self):
        if self.sta_end < self.sta_start:
            self.sta_start, self.sta_end = self.sta_end, self.sta_start
        if self.side not in SIDES:
            raise ValueError(f"Run side must be one of {SIDES}, not {self.side!r}")

    @property
    def length(self) -> float:
        return self.sta_end - self.sta_start


def signed_offset(al, run: Run, sta: float) -> Optional[float]:
    """Offset of the run from the centreline at a station (+ right). None where its edge is absent."""
    if run.side == "C" or not run.edge_ref:
        if run.side == "L":
            return -abs(run.offset)
        if run.side == "R":
            return abs(run.offset)
        return run.offset
    edges = getattr(al, "edges", None)
    e = edges.offset(run.edge_ref, run.side, sta) if edges else None
    if e is None:
        return None
    o = e + run.offset
    return o if run.side == "R" else -o


def clamp_run(al, run: Run) -> Run:
    """The run limited to the alignment (stations stored to the millimetre can round just past its end)."""
    from dataclasses import replace
    lo, hi = max(run.sta_start, al.sta_start), min(run.sta_end, al.sta_end)
    return run if (lo == run.sta_start and hi == run.sta_end) else replace(run, sta_start=lo, sta_end=max(lo, hi))


def stations(run: Run, step: float = 5.0, extra=()) -> List[float]:
    n = max(1, int(math.ceil(run.length / step)))
    st = {run.sta_start + run.length * k / n for k in range(n + 1)}
    st |= {s for s in extra if run.sta_start < s < run.sta_end}
    return sorted(st)


def geometry(al, run: Run, step: float = 5.0) -> List[List[Tuple[float, float]]]:
    """Polyline parts (split where the reference edge is missing) in map coordinates."""
    run = clamp_run(al, run)
    if run.length <= 0:
        return []
    if getattr(run, "width", None) and run.side == "C":           # transverse item: its footprint outline
        h = run.width / 2.0
        c = run.offset
        ring = [al.point_at(run.sta_start, c - h)[:2], al.point_at(run.sta_end, c - h)[:2],
                al.point_at(run.sta_end, c + h)[:2], al.point_at(run.sta_start, c + h)[:2]]
        return [ring + [ring[0]]]
    joins = [al.sta_start + c for c in getattr(al, "_cum", [])]     # element joins (TS, SC, ...)
    parts, cur = [], []
    for s in stations(run, step, joins):
        o = signed_offset(al, run, s)
        if o is None:
            if len(cur) >= 2:
                parts.append(cur)
            cur = []
            continue
        x, y, _ = al.point_at(s, o)
        cur.append((x, y))
    if len(cur) >= 2:
        parts.append(cur)
    return parts


ZEBRA = {"BM01", "BM02", "BM03"}
CALMING_FILL = {"HUMP-C", "HUMP-T", "TABLE", "BUMP"}
# along-road length of a transverse item placed with one click (m); calming items are sized by the Calming tab
CLICK_LENGTH = {"BM01": 2.0, "BM02": 3.0, "BM03": 4.0, "BAR-SET": 4.8, "BM04": 2.0,
                "HUMP-C": 3.7, "HUMP-T": 6.5, "TABLE": 8.4, "BUMP": 0.6}


def pattern(al, run: Run, bars: int = 6, bar_width: float = 0.3) -> List[List[Tuple[float, float]]]:
    """The painted shapes of a transverse item, as closed rings in map coordinates:
    zebra bars (500 mm bars, 500 mm gaps, along the traffic; RDM 6.1 Figure 9.1), bar sets (bars across
    the road), hump triangles (BM04, pointing up each ramp) or, for humps, tables and bumps, the footprint."""
    run = clamp_run(al, run)
    if run.length <= 0 or not (getattr(run, "width", None) and run.side == "C"):
        return []
    h, c, a, b = run.width / 2.0, run.offset, run.sta_start, run.sta_end
    P = lambda s, o: al.point_at(s, c + o)[:2]
    rect = lambda s0, s1, o0, o1: [P(s0, o0), P(s1, o0), P(s1, o1), P(s0, o1), P(s0, o0)]
    code = run.code
    if code in ZEBRA:
        out, o = [], -h
        while o + 0.5 <= h + 1e-6:
            out.append(rect(a, b, o, o + 0.5))
            o += 1.0
        return out
    if code == "BAR-SET":
        gap = max((run.length - bars * bar_width) / max(bars - 1, 1), 0.0)
        return [rect(a + k * (bar_width + gap), a + k * (bar_width + gap) + bar_width, -h, h) for k in range(bars)]
    if code == "BM04":
        out, o, base, height = [], -h, 0.75, min(1.85, run.length / 2)
        while o + base <= h + 1e-6:
            m = o + base / 2
            out.append([P(a, o), P(a, o + base), P(a + height, m), P(a, o)])          # up the entry ramp
            out.append([P(b, o), P(b, o + base), P(b - height, m), P(b, o)])          # and the exit ramp
            o += base + 1.0
        return out
    return [rect(a, b, -h, h)]                                                         # footprint, filled


def speed_for(al, run: Run) -> Optional[float]:
    return al.speed_at((run.sta_start + run.sta_end) / 2) if al is not None else None


def run_quantities(run: Run, item: LinearItem, speed: Optional[float] = None) -> dict:
    """{'length': m, 'painted': m, 'area': m2, 'count': No., 'terminals': No.} for one run."""
    L = run.length
    q = {"length": L}
    if item.is_marking:
        d = item.dims(speed)
        painted = L * item.paint_ratio(speed)
        q["painted"] = painted
        q["area"] = painted * float(d.get("width") or 0)
    if item.is_point_series:
        sp = item.spacing_no_overtaking if (run.no_overtaking and item.spacing_no_overtaking) else item.spacing
        q["count"] = int(math.floor(L / sp + 1e-9)) + 1 if L > 0 else 0
        q["spacing"] = sp
    if item.transverse:
        q["count"] = 1
        w = float(run.width or 0.0)
        if item.area_factor == "bars":
            q["area"] = item.bars * item.bar_width * w
        elif isinstance(item.area_factor, (int, float)):
            q["area"] = float(item.area_factor) * L * w
    if item.terminal:
        q["terminals"] = 2
    return q


def summarise(runs: List[Run], cat: LinearCatalogue, al=None) -> List[Tuple[str, str, str, str, str, float]]:
    """Quantity rows: (category, code, description, pattern, unit, quantity).

    Markings give the run length (m) and the painted area (m2); studs a count; barriers the
    length and their terminals."""
    acc: Dict[Tuple[str, str, str], dict] = {}
    for r in runs:
        it = cat[r.code]
        v = speed_for(al, r)
        q = run_quantities(r, it, v)
        key = (it.category, it.code, it.pattern(v) if it.is_marking else "")
        a = acc.setdefault(key, {"length": 0.0, "area": 0.0, "count": 0, "terminals": 0})
        a["length"] += q["length"]
        a["area"] += q.get("area", 0.0)
        a["count"] += q.get("count", 0)
        a["terminals"] += q.get("terminals", 0)
    rows = []
    order = {c: i for i, c in enumerate(cat.categories())}
    for (catg, code, pat), a in sorted(acc.items(), key=lambda kv: (order.get(kv[0][0], 99), kv[0][1], kv[0][2])):
        it = cat[code]
        if it.is_point_series or it.transverse:
            rows.append((catg, code, it.name, pat, "No.", a["count"]))
            if it.transverse and a["area"] > 0:
                rows.append((catg, code, it.name + " (painted area)", pat, "m2", round(a["area"], 1)))
            continue
        rows.append((catg, code, it.name, pat, "m", round(a["length"], 1)))
        if it.is_marking:
            rows.append((catg, code, it.name + " (painted area)", pat, "m2", round(a["area"], 1)))
        if it.terminal and a["terminals"]:
            t = cat[it.terminal]
            rows.append((t.category, t.code, t.name, "", t.unit, a["terminals"]))
    # merge terminal rows of the same code
    merged: Dict[Tuple, list] = {}
    for row in rows:
        k = row[:5]
        if k in merged:
            merged[k][5] += row[5]
        else:
            merged[k] = list(row)
    return [tuple(v) for v in merged.values()]
