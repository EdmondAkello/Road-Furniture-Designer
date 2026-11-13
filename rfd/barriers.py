"""Embankment safety barriers proposed from RDM 1.3 (2025) Chapter 12.

Fill height and batter at each corridor section, per side, as in the LandXML plugin's
section views (top-of-corridor line against original ground):

  hinge   the Hinge coded point, else the first point beyond the pavement where the
          design line drops outward by more than 1:10
  toe     where the design line beyond the hinge meets original ground (OGL); with a
          toe drain, bench or wall the crossing is still the toe
  height  hinge elevation minus ground at the toe
  batter  1:n with n = horizontal run / height, hinge to toe

Ground comes from the section's own ground line (CrossSectSurf), else a TIN surface
in the LandXML sampled under the section, else - flagged in the reason - the
corridor's daylight point (hinge to daylight).

Warrant: the criteria's barrier warrant curve (RDM 1.3 Figure 12.4, digitised):
'required', 'judgement' (between the curves; engineer's discretion) or not required.

Length (12.6.6, 12.6.14, Table 12.6):
  - the warranted length plus the run-out length at both ends (two-way roads), at the highest
    design speed along the hazard and its approaches
  - an end inside a horizontal curve is first carried to the curve's end (tangent point)
  - at least 30 m; gaps under 80 m between barriers on one side are closed
  - set-back 0.5 m from the edge line (0.75 m where AADT >= 12,000 and speed > 80 km/h)
  - leading and trailing terminals at every run (counted with the barrier)

Not covered: roadside obstacles (Table 12.4), structures and parapets (on hold),
median barriers.
"""
from __future__ import annotations

import math

from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import criteria as _crit
from . import terrain as _ter
from .autoplace import Finding
from .linear import Run

GEOMETRIC_DROP = 0.1         # outward drop / run beyond which the design line is on the side slope (as LandXML plugin)
MIN_HEIGHT = 0.5             # m: lower fills are not assessed
ROAD_CODES = ("ETW", "EOP", "EP", "EPS", "EOS", "ESH", "Shoulder", "Crown")


@dataclass
class BarrierConfig:
    criteria: str = _crit.DEFAULT_ID
    include_judgement: bool = False     # also propose barriers where the warrant leaves it to judgement
    aadt: Optional[float] = None        # for the 0.75 m set-back (AADT >= 12,000 and speed > 80 km/h)
    edge_ref: str = "ETW"               # edge line the set-back is measured from
    item: str = "GR-W"
    ground_surface: Optional[str] = None  # TIN / section surface name; None -> by name (OGL, EG, existing, ...)
    landxml: Optional[str] = None       # path, for TIN surfaces
    start: Optional[float] = None
    end: Optional[float] = None
    low_traffic: bool = False           # Table 12.1 column for the clear zone note

    @property
    def crit(self):
        return _crit.get(self.criteria)


@dataclass
class SideFill:
    station: float
    side: str
    height: float
    slope_n: float
    hinge: float          # abs offset
    toe: float            # abs offset
    source: str           # "section ground" | "TIN <name>" | "daylight"
    warrant: str = ""


# --------------------------------------------------------------------------- section geometry
def _interp(line, x):
    """z on an (offset, z) polyline sorted by offset; None outside."""
    if not line or x < line[0][0] - 1e-9 or x > line[-1][0] + 1e-9:
        return None
    for (x0, z0), (x1, z1) in zip(line, line[1:]):
        if x0 - 1e-9 <= x <= x1 + 1e-9:
            return z0 if x1 - x0 < 1e-12 else z0 + (z1 - z0) * (x - x0) / (x1 - x0)
    return line[-1][1]


def _design_side(al, sta, side, design_name):
    """[(abs offset, absolute z)] outward from the centreline, and the coded points {code: (off, z)}."""
    sec = al.sections
    coded = {}
    pts = sec.side(sta, side)
    zc = al.profile.elevation(sta) if al.profile is not None else None
    for off, z, code in pts:
        if code not in coded or off > coded[code][0]:
            coded[code] = (off, (zc + z) if zc is not None else z)
    line = None
    if design_name:
        surf = sec.surface(sta, design_name)
        if surf:
            sg = -1 if side == "L" else 1
            line = sorted((sg * o, z) for o, z in surf if sg * o >= -1e-9)
    if not line:
        line = sorted({(off, (zc + z) if zc is not None else z) for off, z, _ in pts})
        if line and line[0][0] > 1e-6:
            line = [(0.0, zc if zc is not None else 0.0)] + line
    return line, coded, zc is not None


def _hinge(line, coded):
    if "Hinge" in coded:
        return coded["Hinge"]
    road = max((coded[c][0] for c in ROAD_CODES if c in coded), default=0.0)
    for (x0, z0), (x1, z1) in zip(line, line[1:]):
        if x0 + 1e-6 < road:
            continue
        if x1 - x0 > 1e-6 and (z0 - z1) / (x1 - x0) > GEOMETRIC_DROP:
            return x0, z0
    return None


def side_fill(al, sta, side, ground_line: Optional[List[Tuple[float, float]]], design_name=None,
              ground_label="") -> Optional[SideFill]:
    line, coded, absolute = _design_side(al, sta, side, design_name)
    if len(line) < 2:
        return None
    h = _hinge(line, coded)
    if h is None:
        return None
    xh, zh = h
    out = [(x, z) for x, z in line if x >= xh - 1e-9]
    if ground_line and absolute:
        g0 = _interp(ground_line, xh)
        if g0 is None or zh - g0 < MIN_HEIGHT:           # hinge at or below ground: cut, or a low fill
            return None
        xs = sorted({x for x, _ in out} | {x for x, _ in ground_line if out[0][0] < x < out[-1][0]})
        prev = None
        toe = None
        for x in xs:
            zd, zg = _interp(out, x), _interp(ground_line, x)
            if zd is None or zg is None:
                continue
            d = zd - zg
            if d <= 1e-6:
                if prev is None:
                    toe = (x, zg)
                else:
                    px, pd = prev
                    t = pd / (pd - d) if pd - d > 1e-12 else 1.0
                    tx = px + t * (x - px)
                    toe = (tx, _interp(ground_line, tx))
                break
            prev = (x, d)
        if toe is None:                                   # design ends above ground: use its last point
            x = out[-1][0]
            zg = _interp(ground_line, x)
            if zg is None:
                return None
            toe = (x, zg)
        height = zh - toe[1]
        run = toe[0] - xh
        source = ground_label
    else:
        dl = coded.get("Daylight")
        if dl is None or dl[0] <= xh:
            return None
        height, run, toe = zh - dl[1], dl[0] - xh, dl
        source = "daylight"
    if height < MIN_HEIGHT or run <= 1e-6:
        return None
    return SideFill(sta, side, height, run / height, xh, toe[0], source)


def fills(al, cfg: BarrierConfig) -> Tuple[List[SideFill], str]:
    """SideFill for every section and side that is in fill; and a note on the ground used."""
    sec = getattr(al, "sections", None)
    if not sec:
        return [], "no corridor sections in the LandXML: embankment barriers not assessed"
    names = sec.surface_names()
    gname = cfg.ground_surface if cfg.ground_surface in names else _ter.pick(names, _ter.is_ground_name)
    dname = _ter.pick(names, _ter.is_design_name)
    tin = None
    if cfg.landxml:
        try:
            tin = _ter.ground_tin(cfg.landxml, cfg.ground_surface if cfg.ground_surface not in names else None)
        except (OSError, ValueError):
            tin = None
    lo = max(al.sta_start, cfg.start if cfg.start is not None else al.sta_start)
    hi = min(al.sta_end, cfg.end if cfg.end is not None else al.sta_end)
    out, used = [], {"section": 0, "tin": 0, "daylight": 0}
    for sta in sec.stations:
        if not lo - 1e-6 <= sta <= hi + 1e-6:
            continue
        for side in "LR":
            sg = -1 if side == "L" else 1
            ground, label = None, ""
            g = sec.surface(sta, gname) if gname else None
            if g:
                ground = sorted((sg * o, z) for o, z in g if sg * o >= -1e-9)
                label = "section ground"
            elif tin is not None:
                line, _, _ = _design_side(al, sta, side, dname)
                if line:
                    far = line[-1][0] + 20.0
                    n = max(2, int(far / 0.5) + 1)
                    ground = []
                    # the samples lie on the section's normal: the centre point and heading once per station
                    # (al.point_at per sample recomputed them, integrating spirals, ~30 times per side)
                    cx, cy, h = al.point_at(sta)
                    nx, ny = math.sin(h) * sg, -math.cos(h) * sg
                    for k in range(n):
                        o = far * k / (n - 1)
                        x, y = cx + o * nx, cy + o * ny
                        z = tin.z(x, y)
                        if z is not None:
                            ground.append((o, z))
                    ground = ground if len(ground) >= 2 else None
                    label = f"TIN {tin.name}"
            f = side_fill(al, sta, side, ground, dname, label)
            if f is not None:
                used["section" if f.source == "section ground" else ("tin" if f.source.startswith("TIN") else "daylight")] += 1
                out.append(f)
    parts = []
    if used["section"]:
        parts.append(f"{used['section']} from the section ground line '{gname}'")
    if used["tin"]:
        parts.append(f"{used['tin']} from TIN surface '{tin.name}'")
    if used["daylight"]:
        parts.append(f"{used['daylight']} from the daylight point (no ground surface there)")
    return out, ("fill heights: " + "; ".join(parts)) if parts else ""


# --------------------------------------------------------------------------- lengths
def curve_extents(al) -> List[Tuple[float, float]]:
    """(start, end) internal stations of each run of curved elements (arcs and spirals)."""
    out, s, cur = [], al.sta_start, None
    for e in al.elements:
        a, b = s, s + e.length
        if getattr(e, "kind", "line") != "line":
            cur = [cur[0], b] if cur else [a, b]
        elif cur:
            out.append(tuple(cur)); cur = None
        s = b
    if cur:
        out.append(tuple(cur))
    return out


def _to_tangent(x, curves, outward):
    for a, b in curves:
        if a < x < b:
            return a if outward < 0 else b
    return x


def _group(stations, gap):
    groups = []
    for s in stations:
        if groups and s - groups[-1][-1] <= gap:
            groups[-1].append(s)
        else:
            groups.append([s])
    return groups


def propose_barriers(al, cfg: BarrierConfig = None) -> Tuple[List[Run], List[Finding]]:
    cfg = cfg or BarrierConfig()
    crit = cfg.crit
    b = crit.barrier()
    min_len = float(b.get("min_length", 30.0))
    close_gap = float(b.get("group_gap", 80.0))
    findings: List[Finding] = []
    rows, note = fills(al, cfg)
    lo, hi = al.sta_start, al.sta_end
    if note:
        findings.append(Finding("barrier_note", lo, hi, "Both", note))
    for f in rows:
        f.warrant = crit.barrier_warrant(f.height, f.slope_n)
    curves = curve_extents(al)
    def v_of(s):
        return al.speed_at(s) or 80.0
    ref = crit.ref("barrier_warrant")
    runs: List[Run] = []
    spacing = sorted({f.station for f in rows})
    step = (sorted(b2 - a for a, b2 in zip(spacing, spacing[1:]))[len(spacing) // 2]
            if len(spacing) > 2 else 20.0)
    for side in "LR":
        mine = sorted((f for f in rows if f.side == side), key=lambda f: f.station)
        want = {"required"} | ({"judgement"} if cfg.include_judgement else set())
        flagged = [f for f in mine if f.warrant in want]
        spans = []
        for g in _group([f.station for f in flagged], 2 * step + 1e-6):
            grp = [f for f in flagged if g[0] <= f.station <= g[-1]]
            a, z = g[0], g[-1]
            a0, z0 = _to_tangent(a, curves, -1), _to_tangent(z, curves, 1)
            # run-out at the highest design speed along the hazard and the approaches to it (both directions)
            far = 130.0
            vs = [v_of(min(max(x, lo), hi)) for x in (a0 - far, a0, z0, z0 + far)] + [v_of(f.station) for f in grp]
            ro = crit.barrier_runout(max(vs)) or 0.0
            s, e = a0 - ro, z0 + ro
            if e - s < min_len:
                m = (s + e) / 2
                s, e = m - min_len / 2, m + min_len / 2
            spans.append([max(lo, s), min(hi, e), grp, ro, (a0 != a) or (z0 != z)])
        merged = []
        for sp in spans:
            if merged and sp[0] - merged[-1][1] < close_gap:
                m = merged[-1]
                m[1] = max(m[1], sp[1]); m[2] = m[2] + sp[2]; m[3] = max(m[3], sp[3]); m[4] = m[4] or sp[4]
                m.append("joined")
            else:
                merged.append(sp)
        for sp in merged:
            s, e, grp, ro, tangent = sp[:5]
            worst = max(grp, key=lambda f: f.height)
            v = v_of((s + e) / 2)
            high = (cfg.aadt or 0) >= 12000 and v > 80
            setback = float(b.get("setback_high" if high else "setback", 0.75 if high else 0.5))
            req = any(f.warrant == "required" for f in grp)
            srcs = sorted({f.source for f in grp})
            reason = (f"Fill up to {worst.height:.1f} m at 1:{worst.slope_n:.1f} "
                      f"({'warranted' if req else 'judgement'}, {ref}); run-out {ro:.0f} m each end "
                      f"({crit.ref('barrier_runout')})"
                      + ("; carried to the tangent point" if tangent else "")
                      + ("; gap under 80 m closed (RDM 1.3 12.6.14)" if "joined" in sp[5:] else "")
                      + f"; set-back {setback:.2f} m from {cfg.edge_ref}"
                      + (f"; heights from {', '.join(srcs)}" if srcs else ""))
            has_edge = bool(al.edges) and (cfg.edge_ref, side) in al.edges.data
            run = Run(cfg.item, s, e, side=side, offset=setback, edge_ref=cfg.edge_ref if has_edge else None,
                      status="proposed", rule="barrier", reason=reason)
            if not has_edge:
                run.offset = worst.hinge - 0.5
            runs.append(run)
            narrow = [f for f in grp if f.hinge - (al.edges.offset(cfg.edge_ref, side, f.station) or 0.0) < setback + 0.5]
            if has_edge and narrow:
                findings.append(Finding("barrier_note", s, e, side,
                                        f"verge narrower than set-back + post width at {len(narrow)} section(s): "
                                        f"check the working width (RDM 1.3 Table 4.17)"))
            findings.append(Finding("barrier", s, e, side, reason,
                                    {"height": worst.height, "slope_n": worst.slope_n, "runout": ro}))
        def covered(st):
            return any(r.side == side and r.sta_start <= st <= r.sta_end for r in runs)
        if not cfg.include_judgement:
            for g in _group([f.station for f in mine if f.warrant == "judgement" and not covered(f.station)],
                            max(close_gap, 2 * step)):
                worst = max((f for f in mine if g[0] <= f.station <= g[-1]), key=lambda f: f.height)
                findings.append(Finding("barrier_judgement", g[0], g[-1], side,
                                        f"{'Left' if side == 'L' else 'Right'} fill up to {worst.height:.1f} m at "
                                        f"1:{worst.slope_n:.1f}: barrier at the engineer's discretion ({ref})",
                                        {"height": worst.height, "slope_n": worst.slope_n}))
        # clear zone note: non-recoverable batter (steeper than 1:3) not covered by a barrier
        cz_side = []
        for f in mine:
            if f.slope_n < 3.0 and not any(r.side == side and r.sta_start <= f.station <= r.sta_end for r in runs):
                cz = crit.clear_zone(v_of(f.station), fill=True, low_traffic=cfg.low_traffic)
                etw = al.edges.offset("ETW", side, f.station) if al.edges else None
                if cz is not None and etw is not None and f.hinge - etw < cz:
                    cz_side.append(f.station)
        for g in _group(cz_side, max(close_gap, 2 * step)):
            cz = crit.clear_zone(v_of(g[0]), fill=True, low_traffic=cfg.low_traffic)
            findings.append(Finding("clear_zone", g[0], g[-1], side,
                                    f"batter steeper than 1:3 starts inside the {cz:.1f} m clear zone "
                                    f"({crit.ref('clear_zone')}); flatten or check the warrant"))
    return runs, findings
