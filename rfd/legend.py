"""Editable sign legends.

Directional signs (RDM 6.2 chapter 5) and text plates have legends that change
from job to job - a sign near Nakuru reads "Nakuru / Eldoret", not the manual's "Mombasa".
The legend is plain text, one line per destination:

    ^ Nakuru A104 18        ahead, route A104, 18 km
    < Eldoret A104 140      left
    > Molo 9                right (route and distance optional)

Arrow tokens: ^ or A (ahead), < or L (left), > or R (right). A line with no
arrow is just text (used for plates: "FOR 5 KM", "Safe height 5.0 m").

Directional faces follow RDM 6.2 Table 2.6 colour schemes by road class and the
5.2 ordering rule (ahead, then left, then right; furthest destination first).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


def escape(s: str) -> str:
    """Text for the generated SVG faces."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# RDM 6.2 Table 2.6 (Table 5.1 lists UC under both green and white; Table 2.6 is followed)
SCHEMES = {
    "EXP": {"bg": "#1f5fae", "fg": "#ffffff", "route": "#ffffff", "label": "Expressway (blue)"},
    "A":   {"bg": "#0b7a3b", "fg": "#ffffff", "route": "#ffd200", "label": "Class A, B, UA (green)"},
    "C":   {"bg": "#ffffff", "fg": "#111111", "route": "#111111", "label": "Class C, D, UC (white)"},
    "L":   {"bg": "#ffffff", "fg": "#111111", "route": "#111111", "label": "Class E–W, UL (white)"},
}
PLATE_COLOURS = {"white": "#ffffff", "black": "#111111", "green": "#0b7a3b",
                 "yellow": "#ffd200", "blue": "#1f5fae", "brown": "#7a4a1e"}
ROUTE_RE = re.compile(r"^(?:[A-Z]{1,2}\d{1,4}[A-Z]?)$")


@dataclass
class LegendLine:
    arrow: Optional[str]      # "ahead" | "left" | "right" | None
    place: str
    route: str = ""
    distance: str = ""


def parse(text: str) -> List[LegendLine]:
    out = []
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            continue
        arrow = None
        m = re.match(r"^(\^|<|>|[ALR](?=\s))\s*(.*)$", s)
        if m:
            arrow = {"^": "ahead", "A": "ahead", "<": "left", "L": "left", ">": "right", "R": "right"}[m.group(1)]
            s = m.group(2).strip()
        toks = s.split()
        dist = route = ""
        if arrow and toks and re.match(r"^\d+(\.\d+)?$", toks[-1]):
            dist = toks.pop()
        if arrow and toks and ROUTE_RE.match(toks[-1]):
            route = toks.pop()
        out.append(LegendLine(arrow, " ".join(toks), route, dist))
    return out


def ordered(lines: List[LegendLine]) -> List[LegendLine]:
    """RDM 5.2: group ahead/left/right; within a direction, furthest destination first."""
    rank = {"ahead": 0, "left": 1, "right": 2, None: 3}
    def d(lin):
        try:
            return -float(lin.distance)
        except ValueError:
            return 0.0
    return sorted(lines, key=lambda lin: (rank[lin.arrow], d(lin)))


def summary(text: str) -> str:
    """One-line form for inventory cells and CAD attributes."""
    sym = {"ahead": "^", "left": "<", "right": ">", None: ""}
    parts = []
    for lin in parse(text):
        p = " ".join(x for x in (sym[lin.arrow], lin.place, lin.route, (lin.distance + " km") if lin.distance else "") if x)
        parts.append(p)
    return " / ".join(parts)


def _arrow(kind, x, y, h, colour):
    """Arrow glyph in a h x h box with top-left (x, y)."""
    c = h / 2
    if kind == "ahead":
        pts = [(c, 0), (h, c * 0.9), (c * 1.3, c * 0.9), (c * 1.3, h), (c * 0.7, h), (c * 0.7, c * 0.9), (0, c * 0.9)]
    elif kind == "left":
        pts = [(0, c), (c * 0.9, 0), (c * 0.9, c * 0.7), (h, c * 0.7), (h, c * 1.3), (c * 0.9, c * 1.3), (c * 0.9, h)]
    else:
        pts = [(h, c), (c * 1.1, 0), (c * 1.1, c * 0.7), (0, c * 0.7), (0, c * 1.3), (c * 1.1, c * 1.3), (c * 1.1, h)]
    d = " ".join(f"{x + px:.1f},{y + py:.1f}" for px, py in pts)
    return f'<polygon points="{d}" fill="{colour}"/>'


def directional_svg(text: str, road_class: str = "A") -> str:
    sc = SCHEMES.get(road_class or "A", SCHEMES["A"])
    lines = ordered(parse(text)) or [LegendLine(None, "(legend)")]
    rh, pad, cw = 34, 10, 15.5                      # row height, padding, char width
    name_w = max(len(lin.place) for lin in lines) * cw
    route_w = max((len(lin.route) for lin in lines), default=0) * cw + (18 if any(lin.route for lin in lines) else 0)
    dist_w = max((len(lin.distance) for lin in lines), default=0) * cw + (12 if any(lin.distance for lin in lines) else 0)
    arrow_w = 34 if any(lin.arrow for lin in lines) else 0
    W = pad * 2 + arrow_w * 2 + name_w + route_w + dist_w
    H = pad * 2 + rh * len(lines)
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">',
         f'<rect x="1.5" y="1.5" width="{W - 3:.0f}" height="{H - 3:.0f}" rx="8" fill="{sc["bg"]}" '
         f'stroke="{sc["fg"]}" stroke-width="3"/>']
    font = 'font-family="Helvetica, Arial, sans-serif" font-weight="bold"'
    for i, lin in enumerate(lines):
        y = pad + i * rh
        base = y + rh * 0.72
        x = pad
        if lin.arrow in ("ahead", "left"):
            p.append(_arrow(lin.arrow, x, y + 5, rh - 10, sc["fg"]))
        x += arrow_w
        p.append(f'<text x="{x:.0f}" y="{base:.0f}" {font} font-size="25" fill="{sc["fg"]}">{escape(lin.place)}</text>')
        x += name_w + 12
        if lin.route:
            rw = len(lin.route) * cw + 8
            if road_class == "A":
                p.append(f'<text x="{x:.0f}" y="{base:.0f}" {font} font-size="22" fill="{sc["route"]}">{escape(lin.route)}</text>')
            else:
                p.append(f'<rect x="{x - 3:.0f}" y="{y + 5:.0f}" width="{rw:.0f}" height="{rh - 10:.0f}" '
                         f'fill="none" stroke="{sc["route"]}" stroke-width="2"/>'
                         f'<text x="{x + 1:.0f}" y="{base:.0f}" {font} font-size="20" fill="{sc["route"]}">{escape(lin.route)}</text>')
        x += route_w
        if lin.distance:
            p.append(f'<text x="{x + dist_w - 12:.0f}" y="{base:.0f}" text-anchor="end" {font} font-size="22" '
                     f'fill="{sc["fg"]}">{escape(lin.distance)}</text>')
        if lin.arrow == "right":
            p.append(_arrow("right", W - pad - (rh - 10), y + 5, rh - 10, sc["fg"]))
    p.append("</svg>")
    return "\n".join(p)


def plate_svg(text: str, style=("white", "black")) -> str:
    bg = PLATE_COLOURS.get(style[0], style[0])
    fg = PLATE_COLOURS.get(style[1], style[1])
    lines = [lin.strip() for lin in (text or "").splitlines() if lin.strip()] or ["(legend)"]
    rh, pad = 32, 12
    W = pad * 2 + max(len(lin) for lin in lines) * 15.5
    H = pad * 2 + rh * len(lines)
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">',
         f'<rect x="2" y="2" width="{W - 4:.0f}" height="{H - 4:.0f}" rx="7" fill="{bg}" stroke="{fg}" stroke-width="3"/>']
    for i, lin in enumerate(lines):
        p.append(f'<text x="{W / 2:.0f}" y="{pad + i * rh + rh * 0.74:.0f}" text-anchor="middle" '
                 f'font-family="Helvetica, Arial, sans-serif" font-weight="bold" font-size="25" fill="{fg}">'
                 f'{escape(lin)}</text>')
    p.append("</svg>")
    return "\n".join(p)


_TEXT_RE = re.compile(r"(<text\b[^>]*>)([^<]*)(</text>)")


def label_lines(sign, text: str):
    """Legend lines for a 'label' sign when they map one-to-one onto the artwork's text, else None."""
    lines = [lin.strip() for lin in (text or "").splitlines() if lin.strip()]
    return lines if lines and len(lines) == len(getattr(sign, "label_texts", None) or ()) else None


def label_svg(svg: str, lines) -> str:
    it = iter(lines)
    return _TEXT_RE.sub(lambda m: m.group(1) + escape(next(it, m.group(2))) + m.group(3), svg)


def face_svg(sign, text: str, road_class: str = "A") -> Optional[str]:
    """SVG for a sign whose face depends on its legend, or None to use the catalogue artwork."""
    if not sign.legend or not (text or "").strip():
        return None
    if sign.legend == "directional":
        return directional_svg(text, road_class)
    if sign.legend == "plate":
        return plate_svg(text, sign.plate_style)
    if sign.legend == "label":
        lines = label_lines(sign, text)
        if lines:
            try:
                with open(sign.svg(), encoding="utf-8") as fh:
                    return label_svg(fh.read(), lines)
            except OSError:
                return None
    return None
