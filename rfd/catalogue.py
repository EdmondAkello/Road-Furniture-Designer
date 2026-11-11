"""Sign catalogue (RDM 6.2): codes, names, sizes, legend behaviour, artwork paths."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DEFAULT_PATH = os.path.join(DATA_DIR, "catalogue.json")
SIGNS_DIR = os.path.join(DATA_DIR, "signs")
BLOCK_LIBRARY = os.path.join(DATA_DIR, "RSD_SignBlocks.dxf")

# RDM 6.2 sign size by approach speed (design speed used as the proxy)
#   Tables 3.1 / 3.3 (Stop, Give Way) and Table 4.1 (warning signs; RDM 2.9 general rule)
def size_for_speed(rule: Optional[str], kmh: Optional[float]) -> Optional[str]:
    if rule is None:
        return None
    if rule == "expressway":
        return "1200"
    if kmh is None:
        return None
    if rule == "stop_giveway":
        return "900" if kmh > 80 else ("750" if kmh > 50 else "600")
    if rule == "warning":
        return "900" if kmh > 65 else ("750" if kmh >= 50 else "600")
    return None


@dataclass
class SignDef:
    code: str
    name: str
    category: str
    shape: str
    sizes: List[str]
    default_size: str
    size_rule: Optional[str] = None
    legend: Optional[str] = None          # None | "label" | "plate" | "directional"
    mirror: bool = False                  # a mirrored (left/right) version exists
    figure: str = ""
    page: int = 0
    plate_style: List[str] = field(default_factory=lambda: ["white", "black"])
    note: str = ""

    def block(self, mirrored: bool = False) -> str:
        return f"RSD_{self.code}" + ("_M" if mirrored and self.mirror else "")

    @property
    def block_name(self) -> str:
        return self.block(False)

    def svg(self, mirrored: bool = False) -> str:
        return os.path.join(SIGNS_DIR, self.code + ("_M" if mirrored and self.mirror else "") + ".svg")

    @property
    def label_texts(self) -> List[str]:
        """Text strings printed in the artwork (e.g. W30 '10%'), which a 'label' legend replaces."""
        if not hasattr(self, "_label_texts"):
            import re
            try:
                with open(self.svg(), encoding="utf-8") as fh:
                    self._label_texts = re.findall(r"<text\b[^>]*>([^<]*)</text>", fh.read())
            except OSError:
                self._label_texts = []
        return self._label_texts


class Catalogue:
    def __init__(self, data: dict):
        self.raw = data
        self.version = data.get("catalogue_version", "")
        self.standard = data.get("standard", {})
        self.shapes: Dict[str, dict] = data["shapes"]
        self.signs: Dict[str, SignDef] = {}
        for s in data["signs"]:
            sd = SignDef(s["code"], s["name"], s["category"], s["shape"],
                         [str(z) for z in s["sizes"]], str(s["default_size"]),
                         s.get("size_rule"), s.get("legend"), bool(s.get("mirror")),
                         s.get("figure", ""), s.get("page", 0),
                         s.get("plate_style") or ["white", "black"], s.get("note", ""))
            if sd.shape not in self.shapes:
                raise ValueError(f"Sign {sd.code}: unknown shape '{sd.shape}'")
            if sd.code in self.signs:
                raise ValueError(f"Duplicate sign code {sd.code}")
            self.signs[sd.code] = sd
        self.posts: Dict[str, dict] = data["posts"]
        self.foundations: Dict[str, dict] = data["foundations"]
        self.defaults = data.get("defaults", {})

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Catalogue":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def categories(self) -> List[str]:
        order = ["Regulatory", "Mandatory", "Prohibitory", "Warning", "Information", "Directional",
                 "Disabled Persons", "Expressway", "Road Works"]
        present = {s.category for s in self.signs.values()}
        return [c for c in order if c in present] + sorted(present - set(order))
