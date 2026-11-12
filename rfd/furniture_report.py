"""Road furniture for the report: schedules, consistency checks and the strip diagram.

Pure Python (no QGIS), so the plugin's report and the tests share one source.
The inputs are what a project holds:

  runs   linear runs (rfd.linear.Run) from rsd_lines: markings, studs, barriers, features
  signs  sign dicts {"sta", "side", "facing", "code", "status", "post", "rule"}

and what RFD works out again at report time from the geometry with the project's
settings: the no-overtaking zones (autoplace.no_overtaking_zones), the barrier
warrants (barriers.propose_barriers) and the traffic calming checks
(features.design_feature). The checks compare the two:

  * every no-overtaking zone is covered by a centre line that prohibits overtaking
    for that direction (the PSD governs; signs and markings follow it)
  * every warranted barrier span (with its run-out) is covered by a barrier run
  * barrier runs that no fill warrant asks for are listed for the designer
  * signs the geometry asks for are in the project, and signs are 0.6 V apart (RDM 6.2 2.4)
  * features are visible from the stopping sight distance

Findings are information for the designer, not a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .alignment import format_station

CENTRE_BOTH = {"LM24", "LM25", "LM32"}          # continuous: no overtaking in either direction
CENTRE_CLS = {"LM28"}                           # combined line: one direction (Run.flip)
CENTRE_BROKEN = {"LM01", "LM02"}
EDGE_CONT = {"LM26", "LM27"}
EDGE_BROKEN = {"LM07"}
CURVE_WARNINGS = {"W19", "W20", "W21", "W22"}
SERIES = {"W24-a"}                              # chevrons: their own spacing (RDM 6.2 Table 4.2)
PLATES = {"W23", "END"}                     # supplementary plates: on the post of the sign they qualify
CROSSING_CODES = {"BM01", "BM02", "BM03"}
FEATURE_MAIN = ("HUMP-C", "HUMP-T", "TABLE", "BUMP", "BM01", "BM02", "BM03", "BAR-SET")
KIND_OF = {"HUMP-C": "hump_circular", "HUMP-T": "hump_trapezoidal", "BUMP": "speed_bump", "TABLE": "speed_table"}
TOL = 5.0                                       # m: gaps shorter than this are not reported


@dataclass
class Check:
    """One finding of the furniture checks (stations internal)."""
    kind: str               # see KIND_TEXT
    start: float
    end: float
    side: str               # L / R / C / Forward / Backward / Both
    text: str
    level: str = "check"    # issue | check | info
    values: Dict = field(default_factory=dict)


KIND_TEXT = {
    "centre_line": "Centre line vs no-overtaking zone",
    "no_centre_line": "No centre line",
    "barrier_missing": "Warranted barrier not in the project",
    "barrier_short": "Barrier shorter than warranted",
    "barrier_unwarranted": "Barrier without a fill warrant",
    "barrier_judgement": "Barrier at the engineer's discretion",
    "clear_zone": "Clear zone",
    "barrier_note": "Barrier note",
    "sign_missing": "Sign asked for by the geometry is not in the project",
    "sign_spacing": "Signs closer than 0.6 V",
    "sign_proposed": "Proposals not yet accepted",
    "feature_visibility": "Feature not visible from SSD",
    "feature_error": "Feature not permitted",
    "feature_note": "Feature note",
    "combination": "Alignment combination",
    "speed_check": "Speed limit above design speed",
    "sign_unclosed": "Restriction not ended",
    "sign_orphan_end": "End sign without a start",
    "sign_plate": "Plate missing",
    "speed_note": "Speed limit note",
    "sign_supplementary": "Signs outside RDM 6.2",
    "junction_skew": "Junction crossing angle",
    "bus_bay_spacing": "Bus bay spacing",
    "truck_bay_length": "Truck parking bay length",
    "truck_bay_spacing": "Truck parking bay spacing",
}


# --------------------------------------------------------------------------- intervals
def union(spans: Iterable[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out: List[List[float]] = []
    for a, b in sorted((min(a, b), max(a, b)) for a, b in spans):
        if out and a <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def uncovered(a: float, b: float, cover: List[Tuple[float, float]], tol: float = TOL) -> List[Tuple[float, float]]:
    """Parts of [a, b] outside the (unioned) cover, longer than tol."""
    out, cur = [], a
    for c0, c1 in cover:
        if c1 <= cur or c0 >= b:
            continue
        if c0 > cur:
            out.append((cur, c0))
        cur = max(cur, c1)
    if cur < b:
        out.append((cur, b))
    return [(x, y) for x, y in out if y - x > tol]


def _ch(al, s):
    return format_station(al.display_station(s), 0) if al is not None else f"{s:.0f}"


def _spans_text(al, spans, limit=6):
    t = ", ".join(f"{_ch(al, a)}-{_ch(al, b)}" for a, b in spans[:limit])
    return t + (f" and {len(spans) - limit} more" if len(spans) > limit else "")


# --------------------------------------------------------------------------- schedules
def category(lcat, code):
    return lcat[code].category if code in lcat else "Other"


def prohibits(run) -> set:
    """Directions for which a centre-line run prohibits overtaking."""
    if run.code in CENTRE_BOTH:
        return {"Forward", "Backward"}
    if run.code in CENTRE_CLS:
        return {"Backward"} if run.flip else {"Forward"}
    return set()


def centre_style(run) -> str:
    if run.code in CENTRE_BOTH:
        return "double" if run.code == "LM32" else "continuous"
    if run.code in CENTRE_CLS:
        return "cls_bwd" if run.flip else "cls_fwd"
    return "broken"


def run_rows(runs, lcat, al, categories: Tuple[str, ...]) -> List[dict]:
    """Per-run schedule rows of the given catalogue categories, by chainage."""
    from .linear import run_quantities, speed_for
    rows = []
    for r in sorted(runs, key=lambda r: (r.sta_start, r.side, r.code)):
        if r.code not in lcat or lcat[r.code].category not in categories:
            continue
        it = lcat[r.code]
        v = speed_for(al, r)
        q = run_quantities(r, it, v)
        if it.is_marking:
            detail = it.pattern(v)
            if it.composite:
                detail += "; continuous line " + ("right" if r.flip else "left") + " of the chainage direction"
        elif it.is_point_series:
            detail = f"{q['spacing']:g} m interval"
        else:
            detail = ""
        rows.append({"run": r, "code": r.code, "name": it.name, "category": it.category, "from": r.sta_start,
                     "to": r.sta_end, "length": r.length, "side": r.side, "offset": r.offset,
                     "edge": r.edge_ref or "", "detail": detail,
                     "qty": q["count"] if (it.is_point_series or it.transverse) else round(q["length"], 1),
                     "unit": "No." if (it.is_point_series or it.transverse) else it.unit,
                     "area": round(q["area"], 2) if "area" in q else None, "terminals": q.get("terminals"),
                     "status": r.status or "approved", "reason": r.reason or "", "rule": r.rule or ""})
    return rows


def feature_groups(runs, signs, al=None) -> List[dict]:
    """Traffic calming / crossing features (rule feature:<id>) with their kind and station."""
    groups: Dict[str, dict] = {}
    for r in runs:
        if (r.rule or "").startswith("feature:"):
            g = groups.setdefault(r.rule[8:], {"id": r.rule[8:], "runs": [], "signs": []})
            g["runs"].append(r)
    for s in signs:
        rule = s.get("rule") or ""
        if rule.startswith("feature:") and rule[8:] in groups:
            groups[rule[8:]]["signs"].append(s)
    out = []
    for g in groups.values():
        codes = [r.code for r in g["runs"]]
        main = next((c for c in FEATURE_MAIN if c in codes), codes[0])
        mr = [r for r in g["runs"] if r.code == main]
        if main == "TABLE" and any(c in CROSSING_CODES for c in codes):
            kind = "raised_crossing"
        elif main in CROSSING_CODES:
            kind = "crossing"
        elif main == "BAR-SET":
            kind = "bar_marking"
        else:
            kind = KIND_OF.get(main, "other")
        if kind == "bar_marking":
            lo, hi = min(r.sta_start for r in mr), max(r.sta_end for r in mr)
            station = (lo + hi) / 2
        else:
            station = (mr[0].sta_start + mr[0].sta_end) / 2
        width = next((r.width for r in g["runs"] if r.width), None)
        out.append({"id": g["id"], "kind": kind, "main": main, "station": station, "codes": codes,
                    "runs": g["runs"], "signs": g["signs"], "width": width,
                    "detail": mr[0].reason, "status": "proposed" if any(r.status == "proposed" for r in g["runs"])
                    else "approved",
                    "sign_codes": sorted({s["code"] for s in g["signs"]})})
    return sorted(out, key=lambda g: g["station"])


# --------------------------------------------------------------------------- checks
def centre_line_checks(al, runs, zones: Dict[str, List[Tuple[float, float]]]) -> List[Check]:
    """No-overtaking zones (the PSD basis) not covered by a prohibiting centre line."""
    centre = [r for r in runs if r.side == "C" and (r.code in CENTRE_BOTH | CENTRE_CLS | CENTRE_BROKEN)]
    nz = sum(len(v) for v in zones.values())
    if not centre:
        if nz:
            return [Check("no_centre_line", al.sta_start, al.sta_end, "C",
                          f"no centre line in the project; {nz} no-overtaking zone(s) from the passing sight "
                          f"distance need a continuous line (Markings tab, Propose)", "issue")]
        return [Check("no_centre_line", al.sta_start, al.sta_end, "C",
                      "no centre line in the project (Markings tab, Propose)", "check")]
    out = []
    for direction in ("Forward", "Backward"):
        cover = union((r.sta_start, r.sta_end) for r in centre if direction in prohibits(r))
        gaps = []
        for a, b in zones.get(direction, []):
            gaps += uncovered(a, b, cover)
        if gaps:
            L = sum(b - a for a, b in gaps)
            out.append(Check("centre_line", gaps[0][0], gaps[-1][1], direction,
                             f"{L:.0f} m of no-overtaking zone for {direction.lower()} traffic has no continuous "
                             f"centre line on that side: {_spans_text(al, gaps)}. The passing sight distance "
                             f"governs; re-propose the markings or draw the line", "issue",
                             {"length": L, "spans": gaps}))
    return out


def barrier_checks(al, runs, lcat, findings) -> List[Check]:
    """Compare the warranted barrier spans (barriers.propose_barriers) with the barrier runs in the project."""
    out: List[Check] = []
    bars = [r for r in runs if category(lcat, r.code) == "Barrier"]
    warrant = [f for f in findings if f.kind == "barrier"]
    judge = [f for f in findings if f.kind == "barrier_judgement"]
    for f in warrant:
        cover = union((r.sta_start, r.sta_end) for r in bars if r.side == f.direction)
        gaps = uncovered(f.start, f.end, cover)
        if not gaps:
            continue
        L, need = sum(b - a for a, b in gaps), f.end - f.start
        h = f.values.get("height")
        what = f"fill up to {h:.1f} m" if h is not None else "fill"
        if L >= need - TOL:
            out.append(Check("barrier_missing", f.start, f.end, f.direction,
                             f"{'Left' if f.direction == 'L' else 'Right'} {what}: a {need:.0f} m barrier "
                             f"(with run-out) is warranted and none is in the project", "issue", {"length": need}))
        else:
            out.append(Check("barrier_short", gaps[0][0], gaps[-1][1], f.direction,
                             f"{'Left' if f.direction == 'L' else 'Right'} {what}: {L:.0f} m of the warranted "
                             f"{need:.0f} m (with run-out) is not covered: {_spans_text(al, gaps)}", "issue",
                             {"length": L}))
    asked = [(f.start, f.end, f.direction) for f in warrant + judge]
    for r in bars:
        if not any(s == r.side and a < r.sta_end and b > r.sta_start for a, b, s in asked):
            out.append(Check("barrier_unwarranted", r.sta_start, r.sta_end, r.side,
                             f"{r.code} {_ch(al, r.sta_start)}-{_ch(al, r.sta_end)} ({r.side}) has no fill "
                             f"warrant from RFD; fine for obstacles, structures or other hazards RFD does not "
                             f"check (RDM 1.3 Table 12.4)", "info"))
    for f in judge:
        out.append(Check("barrier_judgement", f.start, f.end, f.direction, f.text, "check", f.values))
    for f in findings:
        if f.kind in ("clear_zone", "barrier_note"):
            out.append(Check(f.kind, f.start, f.end, f.direction, f.text,
                             "check" if f.kind == "clear_zone" else "info"))
    return out


def sign_checks(al, signs, wanted, spacing_factor: float = 0.6, near: float = 30.0) -> List[Check]:
    """Signs the geometry asks for (autoplace.propose) that are missing, signs closer than 0.6 V,
    and proposals not yet accepted. wanted: autoplace Proposals; signs: project sign dicts.

    A wanted sign counts as present when a sign of the same code and facing is within ``near`` m, or
    within three sign spacings (3 x 0.6 V): placement (autoplace.space_out) moves a sign back up to three
    times when it crowds another post."""
    out: List[Check] = []
    missing: Dict[str, List] = {}
    for p in wanted:
        v = (al.speed_at(p.station) if al is not None else None) or 80.0
        tol = max(near, 3 * spacing_factor * v)
        if not any(s["code"] == p.code and s["facing"] == p.facing and abs(s["sta"] - p.station) <= tol
                   for s in signs):
            missing.setdefault(p.rule, []).append(p)
    for rule, ps in missing.items():
        txt = ", ".join(f"{p.code} {_ch(al, p.station)} ({p.facing[0]})" for p in ps[:8])
        more = f" and {len(ps) - 8} more" if len(ps) > 8 else ""
        out.append(Check("sign_missing", min(p.station for p in ps), max(p.station for p in ps), "Both",
                         f"{len(ps)} {rule.replace('_', ' ')} sign(s) the geometry asks for are not in the "
                         f"project (none of the same code and facing within 3 x 0.6 V): {txt}{more}",
                         "issue" if rule == "curve" else "check", {"rule": rule, "count": len(ps)}))
    # spacing between consecutive posts seen by the same traffic
    close = []
    for facing in ("Forward", "Backward"):
        mine = sorted((s for s in signs if s["facing"] == facing), key=lambda s: s["sta"])
        for a, b in zip(mine, mine[1:]):
            gap = b["sta"] - a["sta"]
            if gap < 0.5 or (a.get("post") and a.get("post") == b.get("post")):
                continue                                       # same post
            if (a["code"] in SERIES and b["code"] in SERIES) or a["code"] in PLATES or b["code"] in PLATES:
                continue
            v = (al.speed_at((a["sta"] + b["sta"]) / 2) if al is not None else None) or 80.0
            if gap < spacing_factor * v - 1e-6:
                close.append((a, b, gap, spacing_factor * v))
    if close:
        txt = ", ".join(f"{a['code']}/{b['code']} at {_ch(al, a['sta'])} ({g:.0f} m < {m:.0f} m)"
                        for a, b, g, m in close[:8])
        out.append(Check("sign_spacing", close[0][0]["sta"], close[-1][1]["sta"], "Both",
                         f"{len(close)} pair(s) of signs facing the same traffic are closer than "
                         f"{spacing_factor:g} x V (RDM 6.2 2.4): {txt}" + (" ..." if len(close) > 8 else ""),
                         "check", {"count": len(close)}))
    prop = [s for s in signs if s.get("status") == "proposed"]
    if prop:
        out.append(Check("sign_proposed", min(s["sta"] for s in prop), max(s["sta"] for s in prop), "Both",
                         f"{len(prop)} sign proposal(s) are not yet accepted", "check", {"count": len(prop)}))
    return out


def load_pairs(paths=None) -> List[dict]:
    """Start / end sign rules (rfd/data/sign_pairs.json plus files in RFD_SIGN_PAIRS_PATH; later files replace
    rules with the same 'what')."""
    import json
    import os
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sign_pairs.json")
    files = paths or [here] + [os.path.join(d, f) for d in os.environ.get("RFD_SIGN_PAIRS_PATH", "").split(os.pathsep)
                               if d and os.path.isdir(d) for f in sorted(os.listdir(d)) if f.endswith(".json")]
    rules: Dict[str, dict] = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for r in json.load(fh).get("pairs", []):
                rules[r["what"]] = r
    return list(rules.values())


def _posts(signs, facing, near=1.0):
    """Posts seen by traffic travelling in one direction, in travel order: [(station, set of codes)]."""
    mine = sorted((s for s in signs if s["facing"] == facing), key=lambda s: s["sta"])
    posts: List[list] = []
    for s in mine:
        codes = {s["code"]}
        if s["code"] in ("P32", "P14") and (s.get("legend") or "").strip().upper() == "END":
            codes.add("END")                                   # older projects: the END legend on the sign
        key = s.get("post")
        if posts and ((key and key == posts[-1][2]) or s["sta"] - posts[-1][0] <= near):
            posts[-1][1] |= codes
        else:
            posts.append([s["sta"], codes, key])
    out = [(p[0], p[1]) for p in posts]
    return out if facing == "Forward" else out[::-1]


def pairing_checks(al, signs, pairs=None) -> List[Check]:
    """Every restriction a sign opens is closed further on for the same traffic, and plates go with their sign."""
    out: List[Check] = []
    for rule in pairs if pairs is not None else load_pairs():
        starts, ends = set(rule["start"]), [set(e) for e in rule.get("end", [])]
        pure = [e for e in ends if e - starts]                 # sets with an end code (P9, END, P18 ...)
        switch = {next(iter(e)) for e in ends if not (e - starts) and len(e) == 1}   # another start closes it
        plates = set(rule.get("plate", []))
        what, ref = rule["what"], rule.get("ref", "")
        for facing in ("Forward", "Backward"):
            unclosed, orphans, noplate = [], [], []
            open_at = open_code = None
            for sta, codes in _posts(signs, facing):
                here = codes & starts
                closed = any(e <= codes for e in pure)
                if open_at is not None:
                    if closed:
                        open_at = open_code = None
                        here = here - set().union(*[e for e in pure if e <= codes])
                    elif here and (here & switch) - {open_code}:
                        open_code = next(iter((here & switch) - {open_code}))
                        open_at = sta
                        here = set()
                    else:
                        here = set()                           # repeater or a sign within the section
                elif closed and ends:
                    orphans.append(sta)
                    here = here - set().union(*[e for e in pure if e <= codes])
                if here and open_at is None:
                    if ends:
                        open_at, open_code = sta, next(iter(here))
                    if plates and not (codes & plates):
                        noplate.append((sta, next(iter(here))))
            if open_at is not None:
                unclosed.append((open_at, open_code))
            dirn = "up-chainage" if facing == "Forward" else "down-chainage"
            ends_txt = " or ".join("+".join(sorted(e)) for e in ends)
            for sta, code in unclosed:
                out.append(Check("sign_unclosed", sta, sta, facing,
                                 f"{what} ({code} at {_ch(al, sta)}, {dirn} traffic) is not ended by {ends_txt} "
                                 f"before the alignment end ({ref}); fine only if it continues beyond the project",
                                 "check", {"what": what}))
            if orphans:
                out.append(Check("sign_orphan_end", orphans[0], orphans[-1], facing,
                                 f"{what}: {len(orphans)} end sign(s) for {dirn} traffic with no start before them "
                                 f"({', '.join(_ch(al, x) for x in orphans[:6])}); fine where the restriction "
                                 f"starts before the alignment ({ref})", "info", {"what": what}))
            if noplate:
                out.append(Check("sign_plate", noplate[0][0], noplate[-1][0], facing,
                                 f"{what}: {len(noplate)} {'/'.join(sorted(starts))} sign(s) for {dirn} traffic "
                                 f"without a {'/'.join(sorted(plates))} plate on the post "
                                 f"({', '.join(_ch(al, x) for x, _ in noplate[:6])}; {ref})",
                                 rule.get("plate_level", "check"), {"what": what}))
    return out


def combination_checks(al, curves, crit, cfg) -> List[Check]:
    """A sag within a bend that limits the speed, or a warned bend just beyond a crest (within the SSD)."""
    pr = al.profile
    if pr is None:
        return []
    out = []
    warned = [c for c in curves if c.v_approach - c.v_curve >= cfg.warn_margin]
    limiting = [c for c in curves if c.v_curve < c.v_approach + cfg.warn_margin]
    for vc in pr.curves:
        a, b = vc.pvi_station - vc.length / 2, vc.pvi_station + vc.length / 2
        if vc.kind == "sag":
            for c in limiting:
                if a < c.arc_end and b > c.arc_start:
                    out.append(Check("combination", max(a, c.arc_start), min(b, c.arc_end), "Both",
                                     f"sag curve at {_ch(al, vc.pvi_station)} lies within the R{c.radius:.0f} bend ({c.v_curve:.0f} km/h) "
                                     f"{_ch(al, c.arc_start)}-{_ch(al, c.arc_end)}", "check"))
        else:
            v = al.speed_at(vc.pvi_station) or 80.0
            ssd = crit.ssd(v)
            for c in warned:
                if b <= c.arc_start <= b + ssd:
                    out.append(Check("combination", b, c.arc_start, "Forward",
                                     f"bend R{c.radius:.0f} ({c.v_curve:.0f} km/h) starts {c.arc_start - b:.0f} m "
                                     f"beyond the crest at {_ch(al, vc.pvi_station)} (SSD {ssd:.0f} m)", "check"))
                if a - ssd <= c.arc_end <= a:
                    out.append(Check("combination", c.arc_end, a, "Backward",
                                     f"bend R{c.radius:.0f} ({c.v_curve:.0f} km/h) ends {a - c.arc_end:.0f} m "
                                     f"before the crest at {_ch(al, vc.pvi_station)} (SSD {ssd:.0f} m, "
                                     f"backward traffic)", "check"))
    return out


def feature_checks(al, groups, fcfg) -> List[Check]:
    """Re-run each feature's checks (visibility from SSD, bump speed, crossing width) on the current geometry."""
    from .features import design_feature
    out = []
    for g in groups:
        if g["kind"] == "other":
            continue
        cfg = fcfg
        if g["width"]:
            from dataclasses import replace
            cfg = replace(fcfg, carriageway=g["width"])
        try:
            d = design_feature(al, g["kind"], g["station"], cfg, group=g["id"])
        except ValueError as e:
            out.append(Check("feature_error", g["station"], g["station"], "Both", str(e), "issue"))
            continue
        for f in d.findings:
            level = {"feature_visibility": "issue", "feature_error": "issue"}.get(f.kind, "info")
            out.append(Check(f.kind, f.start, f.end, f.direction, f"{g['main']} at {_ch(al, g['station'])}: {f.text}",
                             level, dict(f.values, feature=g["id"])))
        g["checks"] = [c for c in out if c.values.get("feature") == g["id"]]
    return out


def speed_zone_checks(al, signs) -> List[Check]:
    """Speed limit zones (rule speed:<id>) against the design speed, recomputed on the current geometry."""
    from .speedzones import SpeedZone, design_zone, zones_from_signs
    out = []
    for z in zones_from_signs(signs):
        if not z["limit"] or z["end"] - z["start"] < 1e-6:
            continue
        d = design_zone(al, SpeedZone(z["start"], z["end"], z["limit"], id=z["id"]))
        for f in d.findings:
            if f.kind == "speed_check":
                out.append(Check("speed_check", f.start, f.end, "Both",
                                 f"zone {_ch(al, z['start'])}-{_ch(al, z['end'])}: {f.text}", "check", f.values))
    return out


def supplementary_checks(al, signs) -> List[Check]:
    """WSCM- signs come from the Ministry's standard drawings, not RDM 6.2: list them for the reviewer."""
    used = sorted((s for s in signs if str(s.get("code", "")).startswith("WSCM-")), key=lambda s: s["sta"])
    if not used:
        return []
    codes = sorted({s["code"] for s in used}, key=lambda c: (c[5], int("".join(ch for ch in c[6:] if ch.isdigit()) or 0)))
    return [Check("sign_supplementary", used[0]["sta"], used[-1]["sta"], "Both",
                  f"{len(used)} sign(s) from the standard drawings WSCM/84/2/01, not in RDM 6.2 (2025): "
                  f"{', '.join(codes)}; confirm the road authority accepts them", "info", {"codes": codes})]


TRUCK_BAY_LENGTH = 70.0         # RDM/1/3/3/03 (four to five heavy vehicles, RDM 1.3 13.2.4.1)
TRUCK_BAY_SPACING = 30000.0     # RDM 1.3 13.2.3.1


def junction_checks(al, junctions) -> List[Check]:
    """Junctions placed from the templates: crossing angle to RDM 1.3 9.2.3.

    junctions: dicts with sta, crossing_deg, kit, side (JunctionStore.junctions())."""
    from .junctions import SKEW_MINIMUM, SKEW_PREFERRED
    out = []
    bays = [j for j in junctions if j.get("bay") and j["bay"].get("kind", "bus bay") == "bus bay"]
    for i, a in enumerate(bays):                     # standard drawing note 4: opposite bays 60 m apart
        for b in bays[i + 1:]:
            if a["bay"]["side"] != b["bay"]["side"]:
                ca = sum(a["bay"]["stations"][1:3]) / 2
                cb = sum(b["bay"]["stations"][1:3]) / 2
                if abs(ca - cb) < 60.0:
                    out.append(Check("bus_bay_spacing", min(ca, cb), max(ca, cb), "Both",
                                     f"bus bays serving opposite directions {abs(ca - cb):.0f} m apart centre to "
                                     f"centre ({_ch(al, ca)} and {_ch(al, cb)}); at least 60 m (RDM/1/3/3/01 note 4)",
                                     "check", {"distance": abs(ca - cb)}))
    trucks = sorted((j for j in junctions if j.get("bay") and j["bay"].get("kind") == "truck parking bay"),
                    key=lambda j: j["bay"]["stations"][1])
    for j in trucks:                                 # RDM 1.3 13.2.4.1: four to five heavy vehicles
        s1, s2 = j["bay"]["stations"][1:3]
        if abs(s2 - s1) < TRUCK_BAY_LENGTH - 1e-6:
            out.append(Check("truck_bay_length", min(s1, s2), max(s1, s2), j["bay"]["side"],
                             f"truck parking bay at {_ch(al, min(s1, s2))} is {abs(s2 - s1):.0f} m long: room for four "
                             f"to five heavy vehicles needs about {TRUCK_BAY_LENGTH:.0f} m (RDM 1.3 13.2.4.1, "
                             f"RDM/1/3/3/03)", "check", {"length": abs(s2 - s1)}))
    for side in ("L", "R"):                          # RDM 1.3 13.2.3.1: at most 30 km apart in each direction
        own = [j for j in trucks if j["bay"]["side"] == side]
        for a, b in zip(own, own[1:]):
            d = abs(b["bay"]["stations"][1] - a["bay"]["stations"][1])
            if d > TRUCK_BAY_SPACING:
                out.append(Check("truck_bay_spacing", a["bay"]["stations"][1], b["bay"]["stations"][1],
                                 side, f"truck parking bays {d / 1000:.1f} km apart; at most "
                                              f"{TRUCK_BAY_SPACING / 1000:.0f} km (RDM 1.3 13.2.3.1)",
                                 "check", {"distance": d}))
    for j in junctions:
        if j.get("bay"):
            continue
        a, sta = j.get("crossing_deg"), j.get("sta")
        if a is None or sta is None:
            continue
        where = f"type {j.get('kit', '')} junction at {_ch(al, sta)}, minor road on the {'left' if j.get('side') == 'L' else 'right'}"
        if a < SKEW_MINIMUM:
            out.append(Check("junction_skew", sta, sta, "Both", f"{where}: crossing angle {a:.0f} deg is below the "
                             f"absolute minimum of {SKEW_MINIMUM:.0f} deg (RDM 1.3 9.2.3)", "issue", {"angle": a}))
        elif a < SKEW_PREFERRED[0]:
            out.append(Check("junction_skew", sta, sta, "Both", f"{where}: crossing angle {a:.0f} deg; 75-120 deg "
                             f"preferred, a skew under 75 deg to be justified (RDM 1.3 9.2.3)", "check", {"angle": a}))
    return out


# --------------------------------------------------------------------------- strip diagram
@dataclass
class Lane:
    name: str
    kind: str                       # bars | ticks
    items: List[tuple] = field(default_factory=list)   # bars: (a, b, style, label, proposed); ticks: (s, style, label, proposed)


def strip_lanes(al, runs, lcat, signs, zones, groups) -> List[Lane]:
    """Lanes of the straight-line diagram, top (left of the road, up-chainage traffic) to bottom."""
    L = lambda name, kind: Lane(name, kind)
    lanes = {k: L(n, t) for k, n, t in (
        ("sL", "Signs, left (→)", "ticks"), ("bL", "Barrier, left", "bars"), ("eL", "Edge line, left", "bars"),
        ("c", "Centre line", "bars"), ("st", "Road studs", "bars"), ("eR", "Edge line, right", "bars"),
        ("bR", "Barrier, right", "bars"), ("sR", "Signs, right (←)", "ticks"),
        ("f", "Calming / crossings", "ticks"), ("sp", "Speed limit zones", "bars"),
        ("noF", "No overtaking →  (PSD)", "bars"),
        ("noB", "No overtaking ←  (PSD)", "bars"))}
    for r in runs:
        if r.code not in lcat or (r.rule or "").startswith("feature:"):
            continue
        it, prop = lcat[r.code], r.status == "proposed"
        if it.category == "Barrier" and r.side in "LR":
            lanes["b" + r.side].items.append((r.sta_start, r.sta_end, "barrier", r.code, prop))
        elif it.category == "Road stud":
            lanes["st"].items.append((r.sta_start, r.sta_end, "stud", f"{r.code} {it.spacing_no_overtaking if r.no_overtaking and it.spacing_no_overtaking else it.spacing:g} m", prop))
        elif it.category == "Marking" and r.side == "C":
            lanes["c"].items.append((r.sta_start, r.sta_end, centre_style(r), r.code, prop))
        elif it.category == "Marking" and r.side in "LR":
            style = "continuous" if r.code in EDGE_CONT else "broken"
            lanes["e" + r.side].items.append((r.sta_start, r.sta_end, style, r.code, prop))
    for s in signs:
        key = "sL" if s["facing"] == "Forward" else "sR"
        lanes[key].items.append((s["sta"], "sign", s["code"], s.get("status") == "proposed"))
    for g in groups:
        lanes["f"].items.append((g["station"], "feature", g["main"], g["status"] == "proposed"))
    from .speedzones import zones_from_signs
    for z in zones_from_signs(signs):
        if z["end"] > z["start"]:
            lanes["sp"].items.append((z["start"], z["end"], "speed", f"{z['limit'] or '?'} km/h",
                                      z["status"] == "proposed"))
    for a, b in zones.get("Forward", []):
        lanes["noF"].items.append((a, b, "noov", "", False))
    for a, b in zones.get("Backward", []):
        lanes["noB"].items.append((a, b, "noov", "", False))
    for ln in lanes.values():
        ln.items.sort(key=lambda t: t[0])
    return list(lanes.values())


# --------------------------------------------------------------------------- everything together
@dataclass
class FurnitureReport:
    markings: List[dict]
    barriers: List[dict]
    features: List[dict]
    quantities: List[tuple]
    checks: List[Check]
    lanes: List[Lane]
    zones: Dict[str, List[Tuple[float, float]]]
    notes: List[str] = field(default_factory=list)
    barrier_findings: list = field(default_factory=list)
    curves: list = field(default_factory=list)
    vfindings: list = field(default_factory=list)       # autoplace geometry findings
    wanted: list = field(default_factory=list)          # sign proposals from the geometry

    def checks_of(self, *kinds) -> List[Check]:
        return [c for c in self.checks if c.kind in kinds]


def build(al, runs, lcat, signs, auto_cfg, barrier_cfg=None, feature_cfg=None, wanted=None,
          vfindings=None, curves=None, junctions=None) -> FurnitureReport:
    """barrier_cfg None: barrier warrants are not rechecked (noted). wanted / vfindings / curves: the
    autoplace proposals, findings and curve groups if the caller already has them."""
    from .autoplace import analyse, curve_groups, no_overtaking_zones, propose
    from .features import FeatureConfig
    from .linear import summarise
    notes = []
    zones = no_overtaking_zones(al, auto_cfg)
    if vfindings is None:
        vfindings = analyse(al, auto_cfg)
    if curves is None:
        curves = curve_groups(al, auto_cfg) if auto_cfg.curves else []
    if wanted is None:
        wanted, _ = propose(al, auto_cfg)
    lo = auto_cfg.start if auto_cfg.start is not None else al.sta_start
    hi = auto_cfg.end if auto_cfg.end is not None else al.sta_end
    groups = feature_groups(runs, signs, al)
    checks = centre_line_checks(al, runs, zones)
    bfind = []
    if barrier_cfg is not None:
        from .barriers import propose_barriers
        _, bfind = propose_barriers(al, barrier_cfg)
        checks += barrier_checks(al, runs, lcat, bfind)
    else:
        notes.append("Barrier warrants were not rechecked for this report.")
    checks += sign_checks(al, signs, [p for p in wanted if lo <= p.station <= hi])
    checks += combination_checks(al, curves, auto_cfg.crit, auto_cfg)
    checks += feature_checks(al, groups, feature_cfg or FeatureConfig(criteria=auto_cfg.criteria))
    checks += speed_zone_checks(al, signs)
    checks += pairing_checks(al, signs)
    checks += supplementary_checks(al, signs)
    checks += junction_checks(al, junctions or [])
    checks.sort(key=lambda c: ({"issue": 0, "check": 1, "info": 2}[c.level], c.start))
    real = [r for r in runs if r.code in lcat]
    return FurnitureReport(
        markings=run_rows(real, lcat, al, ("Marking", "Road stud")),
        barriers=run_rows(real, lcat, al, ("Barrier",)),
        features=groups, quantities=summarise(real, lcat, al), checks=checks,
        lanes=strip_lanes(al, real, lcat, signs, zones, groups), zones=zones, notes=notes,
        barrier_findings=bfind, curves=curves, vfindings=vfindings, wanted=wanted)
