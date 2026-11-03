"""Where to draw sign symbols on a plan so they read at drawing scale.

On a plan a sign symbol is far bigger than the post it stands for (10 mm at 1:2500 is
25 m), so drawings show it beside the road with a leader back to the post, as in HH's
current drawings. The post (block insertion point) stays at its true coordinates.

callouts() places each upright symbol (an axis-aligned box w x h) just outside its post,
on the side away from the road, and moves it further out or along the road until it
clears the boxes already placed.
"""
from __future__ import annotations

import math

_OUT = (0, 1, 2, 3)                    # extra rows outward
_ALONG = (0, 1, -1, 2, -2, 3, -3, 4, -4)  # steps along the road
# prefer sliding along the road (short leaders, order kept) over stacking outward
CANDIDATES = sorted(((o, a) for o in _OUT for a in _ALONG), key=lambda c: c[0] * 2.6 + abs(c[1]) + (0.3 if c[1] < 0 else 0))
SERIES_FACTOR = 0.7                    # repeated narrow signs (chevrons) drawn smaller so a series stays readable
SERIES_CODES = ("W24", "W25")


def outward(heading: float, side: str):
    """Unit vector pointing away from the road on the sign's side (R = right of increasing chainage)."""
    nx, ny = math.sin(heading), -math.cos(heading)
    return (nx, ny) if side == "R" else (-nx, -ny)


def _overlap(a, b, m):
    return not (a[2] + m <= b[0] or b[2] + m <= a[0] or a[3] + m <= b[1] or b[3] + m <= a[1])


def callouts(items, gap: float):
    """items: iterable of (key, station, x, y, heading, side, w, h) with w, h the symbol box in world units.
    gap: clearance between boxes and from the post (world units).

    Returns {key: (cx, cy)} - box centres.
    """
    placed, out = [], {}
    for key, sta, x, y, hd, side, w, h in sorted(items, key=lambda i: i[1]):
        nx, ny = outward(hd, side)
        tx, ty = math.cos(hd), math.sin(hd)
        half_n = (abs(nx) * w + abs(ny) * h) / 2          # box half-extent across / along the road
        half_t = (abs(tx) * w + abs(ty) * h) / 2
        best = None
        for o, a in CANDIDATES:
            dn = half_n + gap + o * (2 * half_n + gap)
            dt = a * (2 * half_t + gap)
            cx, cy = x + nx * dn + tx * dt, y + ny * dn + ty * dt
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if not any(_overlap(box, b, gap * 0.5) for b in placed):
                best = (cx, cy, box)
                break
        if best is None:                                   # very dense: next free row straight out
            o = len(_OUT)
            while True:
                dn = half_n + gap + o * (2 * half_n + gap)
                cx, cy = x + nx * dn, y + ny * dn
                box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                if not any(_overlap(box, b, gap * 0.5) for b in placed) or o > 20:
                    best = (cx, cy, box)
                    break
                o += 1
        placed.append(best[2])
        out[key] = best[:2]
    return out


def callouts_by_post(items, gap: float):
    """Like callouts(), but faces on one post are laid out together.

    items: (key, station, x, y, heading, side, w, h, post, facing). Faces with the same post
    and facing stack top to bottom (sign over its plate); back-to-back faces sit side by side.
    Returns {key: (cx, cy)}.
    """
    groups = {}
    for it in items:
        post = it[8] if len(it) > 8 and it[8] else ("_", it[0])
        groups.setdefault(post, []).append(it)
    gitems, layout = [], {}
    for gk, faces in groups.items():
        cols = {}
        for it in faces:
            cols.setdefault(it[9] if len(it) > 9 else "", []).append(it)
        colspec = []
        for fac, col in cols.items():
            cw = max(it[6] for it in col)
            ch = sum(it[7] for it in col) + gap * 0.4 * (len(col) - 1)
            colspec.append((cw, ch, col))
        gw = sum(c[0] for c in colspec) + gap * 0.4 * (len(colspec) - 1)
        gh = max(c[1] for c in colspec)
        lead = faces[0]
        gitems.append((gk, lead[1], lead[2], lead[3], lead[4], lead[5], gw, gh))
        offs, x = {}, -gw / 2
        for cw, ch, col in colspec:
            y = gh / 2
            for it in col:
                offs[it[0]] = (x + cw / 2, y - it[7] / 2)
                y -= it[7] + gap * 0.4
            x += cw + gap * 0.4
        layout[gk] = offs
    centres = callouts(gitems, gap)
    out = {}
    for gk, offs in layout.items():
        gx, gy = centres[gk]
        for key, (dx, dy) in offs.items():
            out[key] = (gx + dx, gy + dy)
    return out


def leader_tip(px, py, box):
    """Point of the box (x0, y0, x1, y1) nearest the post: where the leader meets the symbol."""
    return min(max(px, box[0]), box[2]), min(max(py, box[1]), box[3])
