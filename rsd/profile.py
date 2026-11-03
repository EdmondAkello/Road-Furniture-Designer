"""Design vertical profile (LandXML ProfAlign): elevation, grade, crests and sags."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class VerticalCurve:
    kind: str            # "crest" | "sag"
    pvi_station: float
    pvi_elevation: float
    length: float
    grade_in: float      # %
    grade_out: float     # %

    @property
    def a(self) -> float:            # algebraic grade difference, %
        return self.grade_out - self.grade_in

    @property
    def k(self) -> Optional[float]:  # m per % (RDM 1.3 / AASHTO K)
        return self.length / abs(self.a) if abs(self.a) > 1e-9 else None

    @property
    def start(self) -> float:
        return self.pvi_station - self.length / 2.0

    @property
    def end(self) -> float:
        return self.pvi_station + self.length / 2.0


class VerticalProfile:
    """PVIs with symmetric parabolic curves: [(station, elevation, curve_length)]."""

    def __init__(self, name: str, pvis: List[Tuple[float, float, float]]):
        self.name = name
        self.pvis = sorted(pvis)
        self.grades = []   # % between consecutive PVIs
        for (s0, z0, _), (s1, z1, _) in zip(self.pvis, self.pvis[1:]):
            self.grades.append(100.0 * (z1 - z0) / (s1 - s0) if s1 > s0 else 0.0)
        self.curves: List[VerticalCurve] = []
        for i in range(1, len(self.pvis) - 1):
            s, z, L = self.pvis[i]
            gi, go = self.grades[i - 1], self.grades[i]
            if L > 0:
                self.curves.append(VerticalCurve("crest" if go < gi else "sag", s, z, L, gi, go))

    @property
    def start(self) -> float:
        return self.pvis[0][0]

    @property
    def end(self) -> float:
        return self.pvis[-1][0]

    def _tangent(self, s):
        """(index of the tangent segment, elevation on tangent) for station s."""
        i = 0
        while i < len(self.pvis) - 2 and s > self.pvis[i + 1][0]:
            i += 1
        s0, z0, _ = self.pvis[i]
        return i, z0 + self.grades[i] / 100.0 * (s - s0)

    def elevation(self, s: float) -> Optional[float]:
        if not self.pvis or s < self.start - 1e-6 or s > self.end + 1e-6:
            return None
        for c in self.curves:
            if c.start <= s <= c.end:
                x = s - c.start
                z_bvc = c.pvi_elevation - c.grade_in / 100.0 * c.length / 2.0
                return z_bvc + c.grade_in / 100.0 * x + (c.a / 100.0) * x * x / (2.0 * c.length)
        return self._tangent(s)[1]

    def grade(self, s: float) -> Optional[float]:
        """Instantaneous grade in % at station s."""
        if not self.pvis or s < self.start - 1e-6 or s > self.end + 1e-6:
            return None
        for c in self.curves:
            if c.start <= s <= c.end:
                return c.grade_in + c.a * (s - c.start) / c.length
        return self.grades[self._tangent(s)[0]] if self.grades else 0.0

    def curve_at(self, s: float) -> Optional[VerticalCurve]:
        for c in self.curves:
            if c.start <= s <= c.end:
                return c
        return None
