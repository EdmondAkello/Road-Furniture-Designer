"""Ground (OGL) for fill heights: LandXML TIN surfaces and section surfaces.

The barrier warrant needs the fill height from the top of the corridor to original
ground. RFD takes the ground, in order of preference, from:
  1. the section's own ground line (CrossSectSurf, e.g. Civil 3D sample-line sections),
  2. a TIN surface in the LandXML (Surfaces/Surface), sampled under the section,
and otherwise falls back to the corridor's daylight point.

Surfaces are read by a byte scan on demand, so opening a project stays fast.
"""
from __future__ import annotations

import math
import mmap
import os
import re
from typing import Dict, List, Optional, Tuple

EXISTING_HINTS = ("ogl", "o.g.l", "egl", "eg", "existing", "ground", "natural", "survey", "topo", "terrain", "dtm")
DESIGN_HINTS = ("top", "frl", "finished", "design", "corridor", "proposed", "fg")
NOT_GROUND = ("bottom", "datum", "subgrade", "formation", "pave", "base")

_SURF_RE = re.compile(rb"""<(?:[A-Za-z_][\w.-]*:)?Surface\b[^>]*?\bname\s*=\s*["']([^"']*)["'][^>]*>""")
_P_RE = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?P\b[^>]*?\bid\s*=\s*[\"']([^\"']+)[\"'][^>]*>([^<]*)<")
_F_RE = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?F\b([^>]*)>([^<]*)<")
_END_RE = re.compile(rb"</(?:[A-Za-z_][\w.-]*:)?Surface>")
_CACHE: Dict[tuple, object] = {}


def _words(name: str):
    return [w for w in re.split(r"[^a-z0-9.]+", name.lower()) if w]


def is_ground_name(name: str) -> bool:
    n = name.lower()
    ws = _words(name)
    if any(h in ws or (len(h) > 3 and h in n) for h in NOT_GROUND):
        return False
    return any(h in ws or (len(h) > 2 and h in n) for h in EXISTING_HINTS)


def is_design_name(name: str) -> bool:
    n = name.lower()
    ws = _words(name)
    return not is_ground_name(name) and any(h in ws or (len(h) > 2 and h in n) for h in DESIGN_HINTS)


def pick(names: List[str], test) -> Optional[str]:
    return next((n for n in names if test(n)), None)


class Tin:
    """A TIN with a bucket grid for point queries (pure Python)."""

    def __init__(self, name: str, pts: Dict[str, Tuple[float, float, float]], faces: List[Tuple[str, str, str]],
                 cell: float = 0.0):
        self.name = name
        self.tris = []
        for a, b, c in faces:
            if a in pts and b in pts and c in pts:
                p, q, r = pts[a], pts[b], pts[c]
                det = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
                if abs(det) > 1e-9:
                    self.tris.append((p, q, r, det))
        if not self.tris:
            raise ValueError(f"Surface '{name}' has no triangles")
        xs = [v[0] for t in self.tris for v in t[:3]]
        ys = [v[1] for t in self.tris for v in t[:3]]
        self.x0, self.y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        area = max((x1 - self.x0) * (y1 - self.y0), 1.0)
        self.cell = cell or max(2.0, math.sqrt(area / len(self.tris)) * 2.0)
        self.grid: Dict[Tuple[int, int], List[int]] = {}
        for i, (p, q, r, _) in enumerate(self.tris):
            for gx in range(self._ix(min(p[0], q[0], r[0])), self._ix(max(p[0], q[0], r[0])) + 1):
                for gy in range(self._iy(min(p[1], q[1], r[1])), self._iy(max(p[1], q[1], r[1])) + 1):
                    self.grid.setdefault((gx, gy), []).append(i)

    def _ix(self, x):
        return int((x - self.x0) // self.cell)

    def _iy(self, y):
        return int((y - self.y0) // self.cell)

    def z(self, x: float, y: float) -> Optional[float]:
        for i in self.grid.get((self._ix(x), self._iy(y)), ()):
            p, q, r, det = self.tris[i]
            l1 = ((q[1] - r[1]) * (x - r[0]) + (r[0] - q[0]) * (y - r[1])) / det
            l2 = ((r[1] - p[1]) * (x - r[0]) + (p[0] - r[0]) * (y - r[1])) / det
            l3 = 1.0 - l1 - l2
            if l1 >= -1e-9 and l2 >= -1e-9 and l3 >= -1e-9:
                return l1 * p[2] + l2 * q[2] + l3 * r[2]
        return None


def surface_names(path: str) -> List[str]:
    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as d:
        return [m.group(1).decode("utf-8", "replace") for m in _SURF_RE.finditer(d)]


def load_tin(path: str, name: str) -> Tin:
    """Read one TIN surface. LandXML points are "northing easting elevation"."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns, name)
    if key in _CACHE:
        return _CACHE[key]
    with open(path, "rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as d:
        for m in _SURF_RE.finditer(d):
            if m.group(1).decode("utf-8", "replace") != name:
                continue
            e = _END_RE.search(d, m.end())
            buf = d[m.end():e.start() if e else len(d)]
            pts = {}
            for pm in _P_RE.finditer(buf):
                v = pm.group(2).split()
                if len(v) >= 3:
                    pts[pm.group(1).decode()] = (float(v[1]), float(v[0]), float(v[2]))
            faces = []
            for fm in _F_RE.finditer(buf):
                if b'i="1"' in fm.group(1) or b"i='1'" in fm.group(1):     # invisible (hole) faces
                    continue
                v = fm.group(2).split()
                if len(v) >= 3:
                    faces.append((v[0].decode(), v[1].decode(), v[2].decode()))
            tin = Tin(name, pts, faces)
            if len(_CACHE) > 6:
                _CACHE.clear()
            _CACHE[key] = tin
            return tin
    raise ValueError(f"Surface '{name}' not found in {path}")


def ground_tin(path: str, name: Optional[str] = None) -> Optional[Tin]:
    """The named TIN, or the first surface whose name reads as original ground; None if there is none."""
    try:
        names = surface_names(path)
    except OSError:
        return None
    name = name or pick(names, is_ground_name)
    return load_tin(path, name) if name in names else None
