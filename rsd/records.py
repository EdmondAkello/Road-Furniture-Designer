"""Sign records -> validated faces and installations. Front-end neutral (stdlib only).

Both the QGIS plugin and the Excel sign list feed plain dict records into
build_signlist(). Record keys:
    ref, post_ref, station (display chainage, text or number) or station_internal
    (geometric station - takes precedence, avoids station-equation ambiguity), offset (abs, m),
    side ("L"/"R"), facing ("Forward"/"Backward"), code, size, post_type,
    foundation, skew (deg), remarks, face_uuid, install_uuid
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .alignment import Alignment, parse_station
from .catalogue import Catalogue

SCHEMA_VERSION = "0.1"
FACING = ("Forward", "Backward")   # Forward = faces traffic travelling with increasing chainage


@dataclass
class Issue:
    row: int          # Excel row or QGIS feature id
    level: str        # "error" | "warning"
    message: str


@dataclass
class Face:
    row: int
    post_ref: str
    station_display: float
    offset_abs: float
    side: str
    facing: str
    code: str
    size: str
    post_type: str
    foundation: str
    skew: float
    remarks: str
    face_uuid: str
    install_uuid: str
    mirror: bool = False
    legend: str = ""
    road_class: str = ""
    edge_ref: str = ""                 # corridor edge the clearance is measured from (EPS, ETW, ...)
    edge_clear: Optional[float] = None  # lateral distance beyond that edge, m (negative = inside it)
    grade: Optional[float] = None      # design vertical grade at the sign, %
    speed: Optional[float] = None      # design speed at the sign, km/h
    uuid_assigned: bool = False
    station_internal: float = 0.0
    x: float = 0.0
    y: float = 0.0
    road_heading: float = 0.0
    rotation_deg: float = 0.0

    @property
    def offset_signed(self) -> float:
        return self.offset_abs if self.side == "R" else -self.offset_abs


@dataclass
class Installation:
    install_uuid: str
    post_ref: str
    post_type: str
    foundation: str
    faces: List[Face] = field(default_factory=list)

    @property
    def lead(self) -> Face:
        return self.faces[0]


@dataclass
class SignList:
    alignment_name: str
    faces: List[Face]
    installations: List[Installation]
    issues: List[Issue]

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)


# --------------------------------------------------------------------------- conventions
def block_rotation_deg(road_heading: float, facing: str, skew: float = 0.0) -> float:
    """CAD block rotation (deg CCW from +X). Block local +Y points toward the traffic
    the sign faces; forward-facing signs point back along -heading."""
    face_dir = road_heading + (math.pi if facing == "Forward" else 0.0)
    return (math.degrees(face_dir) - 90.0 + skew) % 360.0


def face_azimuth_deg(road_heading: float, facing: str, skew: float = 0.0) -> float:
    """Direction the sign face points, as a map azimuth (deg clockwise from north)."""
    face_dir = math.degrees(road_heading) + (180.0 if facing == "Forward" else 0.0) + skew
    return (90.0 - face_dir) % 360.0


def facing_from_rotation(rot_deg: float, road_heading: float):
    """Inverse of signlist.block_rotation_deg -> (facing, skew_deg)."""
    face_dir = math.radians(rot_deg + 90.0)
    d_fwd = math.degrees(math.remainder(face_dir - (road_heading + math.pi), 2 * math.pi))
    if abs(d_fwd) <= 90.0:
        return "Forward", round(d_fwd, 1)
    d_bwd = math.degrees(math.remainder(face_dir - road_heading, 2 * math.pi))
    return "Backward", round(d_bwd, 1)


def auto_facing(side: str) -> str:
    """Kenya drives on the left: a left-side sign normally faces forward traffic."""
    return "Forward" if side == "L" else "Backward"


# --------------------------------------------------------------------------- validation
def _s(v) -> str:
    return "" if v is None else str(v).strip()


def make_face(rec: dict, al: Alignment, cat: Catalogue, issues: List[Issue]) -> Optional[Face]:
    r = rec.get("ref", 0)
    code = _s(rec.get("code"))
    sd = cat.signs.get(code)
    if not sd:
        issues.append(Issue(r, "error", f"Unknown sign code '{code}'"))
        return None
    internal = rec.get("station_internal")
    try:
        disp = (al.display_station(float(internal)) if internal is not None
                else parse_station(rec.get("station")))
    except (TypeError, ValueError):
        issues.append(Issue(r, "error", f"Bad chainage '{rec.get('station')}'"))
        return None
    try:
        off = abs(float(rec.get("offset")))
    except (TypeError, ValueError):
        issues.append(Issue(r, "error", "Offset missing or not a number"))
        return None
    side = _s(rec.get("side")).upper()[:1]
    if side not in ("L", "R"):
        issues.append(Issue(r, "error", "Side must be L or R"))
        return None
    facing = _s(rec.get("facing")).capitalize() or "Forward"
    if facing not in FACING:
        issues.append(Issue(r, "error", "Facing must be Forward or Backward"))
        return None
    size = _s(rec.get("size")) or sd.default_size
    if size.endswith(".0"):
        size = size[:-2]
    if size not in sd.sizes:
        issues.append(Issue(r, "error", f"Size '{size}' not available for {code} ({', '.join(sd.sizes)})"))
        return None
    post = _s(rec.get("post_type")) or cat.defaults.get("post", "")
    fdn = _s(rec.get("foundation")) or cat.defaults.get("foundation", "")
    if post not in cat.posts:
        issues.append(Issue(r, "error", f"Unknown post type '{post}'"))
        return None
    if fdn not in cat.foundations:
        issues.append(Issue(r, "error", f"Unknown foundation '{fdn}'"))
        return None
    try:
        skew = float(rec.get("skew") or 0.0)
    except (TypeError, ValueError):
        issues.append(Issue(r, "error", "Skew must be a number (degrees)"))
        return None

    mirror = str(rec.get("mirror") or "").strip().lower() in ("1", "true", "yes", "y", "m")
    if mirror and not sd.mirror:
        issues.append(Issue(r, "warning", f"{code} has no mirrored version; shown as in the manual"))
        mirror = False
    legend = (rec.get("legend") or "").strip()
    if sd.legend in ("directional", "plate") and not legend:
        issues.append(Issue(r, "warning", f"{code} ({sd.name}) needs a legend - destinations / plate text"))
    f = Face(r, _s(rec.get("post_ref")), disp, off, side, facing, code, size, post, fdn,
             skew, _s(rec.get("remarks")), _s(rec.get("face_uuid")), _s(rec.get("install_uuid")),
             mirror, legend, _s(rec.get("road_class")))
    try:
        f.station_internal = float(internal) if internal is not None else al.internal_station(disp)
        f.x, f.y, f.road_heading = al.point_at(f.station_internal, f.offset_signed)
    except ValueError as e:
        issues.append(Issue(r, "error", str(e)))
        return None
    f.rotation_deg = block_rotation_deg(f.road_heading, facing, skew)
    f.speed = al.speed_at(f.station_internal)
    if al.profile is not None:
        g = al.profile.grade(f.station_internal)
        f.grade = round(g, 2) if g is not None else None
    if al.edges:
        from .corridor import SHOULDER, TRAVELLED_WAY
        tw, tw_off = al.edges.first(TRAVELLED_WAY, side, f.station_internal)
        sh, sh_off = al.edges.first(SHOULDER, side, f.station_internal)
        if tw_off is not None and off < tw_off - 0.05:
            issues.append(Issue(r, "error", f"{code} is inside the travelled way ({off:.2f} m; {tw} at {tw_off:.2f} m)"))
        elif sh_off is not None and off < sh_off - 0.05:
            issues.append(Issue(r, "warning", f"{code} is on the shoulder ({off:.2f} m; {sh} at {sh_off:.2f} m)"))
        ref = _s(rec.get("edge_ref")) or al.edges.reference() or ""
        ro = al.edges.offset(ref, side, f.station_internal) if ref else None
        if ro is not None:
            f.edge_ref, f.edge_clear = ref, round(off - ro, 3)
        from .corridor import RDM_MAX_CLEAR, RDM_MIN_CLEAR, outer_limit
        if ro is not None and ref in SHOULDER + TRAVELLED_WAY and off >= ro - 0.05 and \
                not (RDM_MIN_CLEAR - 0.01 <= off - ro <= RDM_MAX_CLEAR + 0.01):
            issues.append(Issue(r, "warning", f"{code} is {off - ro:.2f} m beyond {ref}; RDM 6.2 2.4 asks for "
                                              f"{RDM_MIN_CLEAR:.1f}-{RDM_MAX_CLEAR:.1f} m"))
        lim = outer_limit(al.edges, side, f.station_internal)
        if lim is not None and off > lim + 0.05 and (ro is None or lim >= ro + RDM_MIN_CLEAR):
            issues.append(Issue(r, "warning", f"{code} is outside the road corridor ({off:.2f} m; corridor "
                                              f"edge at {lim:.2f} m)"))
    far_side = facing != auto_facing(side)
    # chevrons and hazard markers go on the outside of curves / at the hazard, either side
    if far_side and not code.startswith(("W24", "W68", "W69", "W70", "RW24")):
        issues.append(Issue(r, "warning",
                            f"{code} faces {facing.lower()} traffic but sits on the far side "
                            f"(side {side}) - check (median / one-way / repeater?)"))
    if off < 0.5:
        issues.append(Issue(r, "warning", f"Offset {off} m is very close to the centreline"))
    return f


def group_installations(faces: List[Face], issues: List[Issue]) -> List[Installation]:
    """Faces sharing a Post Ref (or, failing that, an install UUID) share one post."""
    groups: Dict[str, Installation] = {}
    out: List[Installation] = []
    for f in faces:
        key = ("ref:" + f.post_ref) if f.post_ref else (("uuid:" + f.install_uuid) if f.install_uuid
                                                        else f"__row{f.row}")
        inst = groups.get(key)
        if inst is None:
            inst = Installation(f.install_uuid or str(uuid.uuid4()), f.post_ref, f.post_type, f.foundation)
            groups[key] = inst
            out.append(inst)
        else:
            lead = inst.lead
            if math.hypot(f.x - lead.x, f.y - lead.y) > 0.05:
                issues.append(Issue(f.row, "error",
                                    f"Post '{f.post_ref or inst.install_uuid[:8]}' faces are at different "
                                    f"positions (#{lead.row} vs #{f.row}); one post needs one position"))
            if (f.post_type, f.foundation) != (inst.post_type, inst.foundation):
                issues.append(Issue(f.row, "warning",
                                    f"Post '{f.post_ref}': post/foundation differs from #{lead.row}; "
                                    f"#{lead.row} values used"))
        f.install_uuid = inst.install_uuid
        inst.faces.append(f)
    return out


def build_signlist(records: List[dict], al: Alignment, cat: Catalogue,
                   alignment_name: str = "") -> SignList:
    issues: List[Issue] = []
    faces: List[Face] = []
    seen = set()
    for rec in records:
        f = make_face(rec, al, cat, issues)
        if f is None:
            continue
        if not f.face_uuid or f.face_uuid in seen:
            if f.face_uuid in seen:
                issues.append(Issue(f.row, "warning", "Duplicate Face UUID (copied?) - new UUID assigned"))
            f.face_uuid = str(uuid.uuid4())
            f.uuid_assigned = True
        seen.add(f.face_uuid)
        faces.append(f)
    insts = group_installations(faces, issues)
    spacing_check(insts, al, issues)
    return SignList(alignment_name or al.name, faces, insts, issues)


def spacing_check(insts, al, issues):
    """RDM 6.2 2.4: signs at least 0.6 x V m apart (same side, same direction).
    Chevrons (own spacing, Table 4.2) and plates are not counted."""
    posts = []
    for i in insts:
        faces = [f for f in i.faces if not f.code.startswith(("W24", "W23", "RW24"))]
        if faces:
            posts.append((i.lead.station_internal, i.lead.side, faces[0].facing, i, faces[0]))
    posts.sort(key=lambda p: p[0])
    for k, (s, side, facing, inst, f) in enumerate(posts):
        v = al.speed_at(s)
        if not v:
            continue
        for s2, side2, facing2, inst2, f2 in posts[k + 1:]:
            if s2 - s >= 0.6 * v:
                break
            if side2 == side and facing2 == facing:
                issues.append(Issue(f2.row, "warning",
                                    f"{f2.code} is {s2 - s:.0f} m from {f.code} ({inst.post_ref or 'post'}); "
                                    f"RDM 6.2 2.4 minimum spacing 0.6 x {v:.0f} = {0.6 * v:.0f} m"))
