"""Build rfd/data/catalogue.json from the extracted RDM 6.2 sign list (rdm_signs.json)
plus the RDM sizing rules and legend behaviour. Run after extract_rdm_signs.py.
"""
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA = os.path.join(ROOT, "rfd", "data")

STD = ["600", "750", "900", "1200"]

# Pure-text plates: the face is re-drawn from the user's legend (style = bg, fg)
PLATES = {
    "W23": ("white", "black"), "W35": ("white", "black"), "P12": ("white", "black"),
    "P35": ("white", "black"), "P38": ("white", "black"), "I7": ("green", "white"),
    "I10B": ("white", "black"), "RW30": ("yellow", "black"), "W47": ("white", "black"),
    "W49": ("white", "black"),
}
# Signs whose artwork stays but which carry variable text (shown as legend label / CAD attribute)
LABELLED = {"P32", "W30", "W31", "P15", "P26", "P27", "P28", "I14", "I18", "I23", "I9", "I10", "I11", "IM24", "IM25",
            "W32", "P29", "P23", "P24", "P25", "W40", "RW15"}


EXPRESSWAY_DIRECTIONAL = {"IM5", "IM6", "IM10", "IM13", "IM22", "IM23"}


def legend_type(s):
    c, n, cat = s["code"], s["name"].lower(), s["category"]
    if c in EXPRESSWAY_DIRECTIONAL:
        return "directional"
    if c in PLATES:
        return "plate"
    if cat == "Directional" or c.endswith("-D") or c in ("PD2", "PD3", "PD4", "PD7"):
        return "directional"
    if cat == "Expressway" and re.search(r"direction|confirmation|signing|exit|advance|destination", n):
        return "directional"
    if c in LABELLED:
        return "label"
    return None


def size_rule(s):
    c, cat, shp = s["code"], s["category"], s["shape"]
    if c in ("R1", "R2"):
        return "stop_giveway"                                  # RDM Tables 3.1 / 3.3
    if cat == "Expressway":
        return "expressway"                                    # RDM 8: 1200 mm
    if cat in ("Warning", "Road Works") and shp == "triangle":
        return "warning"                                       # RDM Table 4.1
    if cat in ("Mandatory", "Prohibitory", "Road Works") and shp == "circle":
        return "warning"                                       # RDM 2.9 general rule, same bands
    return None


# Sample faces for signs the manual shows only as dimensioned design drawings
SAMPLES = {
    "I1": "^ Nakuru A104 18\n< Molo B4 40\n> Eldoret A104 140",
    "I2": "< Nakuru A104 18",
    "I3": "^ Nakuru A104 18\n< Molo B4 40\n> Eldoret A104 140",
    "I4": "^ Nakuru A104\n> Eldoret A104",
    "I5": "< Molo C56 12\n> Kericho C56 20",
    "I6": "Nakuru 18\nNairobi 175",
    "IM": "^ Nairobi A2 25\n> Thika A2 12",
    "D": "< Nakuru A104 18",
}
GENERATED_PLATES = {"I10B": ("Nakuru County", ("white", "black")), "I16": ("P", ("blue", "white")),
                    "I17": ("P  Disabled", ("blue", "white")), "IM4S": ("EXPRESSWAY", ("blue", "white"))}


# Signs the manual describes without a figure or code of their own, built from the artwork of an
# identical extracted sign: code -> (artwork source, entry fields)
DERIVED = {
    "END": ("RW41", {
        "name": "Supplementary plate 'END' (end of restriction)", "category": "Prohibitory", "shape": "rectangle",
        "figure": "3.46", "page": 28,
        "note": "RDM 6.2 3.11 (no overtaking, P32) and 3.6 (clearway, P14): the end of the restriction is the same "
                "sign with a supplementary plate reading END, on the same post. The manual gives the plate no code; "
                "the artwork is the identical END plate of Figure 10.43 (RW41)."}),
}


def add_derived(signs):
    """Catalogue entries, icons and CAD blocks for DERIVED signs."""
    import shutil
    import ezdxf
    sd = os.path.join(DATA, "signs")
    dxf_path = os.path.join(DATA, "RSD_SignBlocks.dxf")
    doc = ezdxf.readfile(dxf_path)
    have = {e["code"] for e in signs}
    changed = False
    for code, (src, fields) in DERIVED.items():
        if code in have or src not in have:
            continue
        shutil.copyfile(os.path.join(sd, src + ".svg"), os.path.join(sd, code + ".svg"))
        name = "RSD_" + code
        if name not in doc.blocks:
            blk = doc.blocks.new(name)
            for e in doc.blocks.get("RSD_" + src):
                blk.add_entity(e.copy())
            changed = True
        e = {"code": code, "sizes": ["custom"], "default_size": "custom", "size_rule": None, "legend": None,
             "mirror": False}
        e.update(fields)
        signs.append(e)
    if changed:
        doc.saveas(dxf_path)


def default_class(code):
    if code.startswith("IM"):
        return "EXP"
    if code.startswith("I5"):
        return "C"
    return "A"


def sample_legend(code):
    if code.endswith("-D"):
        return SAMPLES["D"]
    if code.startswith("IM"):
        return SAMPLES["IM"]
    return SAMPLES.get(code.split("-")[0], SAMPLES["I1"])


def regenerate_icons(signs):
    """Replace illegible design-drawing icons with generated sample faces (originals kept as *_design.svg)."""
    import sys
    sys.path.insert(0, ROOT)
    from rfd.legend import directional_svg, plate_svg
    sd = os.path.join(DATA, "signs")
    n = 0
    for e in signs:
        code = e["code"]
        svg = None
        if e["legend"] == "directional" and not code.startswith("PD"):
            e["default_class"] = default_class(code)
            e["sample_legend"] = sample_legend(code)
            svg = directional_svg(e["sample_legend"], e["default_class"])
        elif code in GENERATED_PLATES:
            text, style = GENERATED_PLATES[code]
            svg = plate_svg(text, style)
        if svg:
            src = os.path.join(sd, code + ".svg")
            design = os.path.join(sd, code + "_design.svg")
            if os.path.exists(src) and not os.path.exists(design):
                os.replace(src, design)
            with open(src, "w", encoding="utf-8") as f:
                f.write(svg)
            e["icon"] = "generated sample face (manual figure is a design drawing: see " + code + "_design.svg)"
            n += 1
    return n


def main():
    src = json.load(open(os.path.join(DATA, "rdm_signs.json")))
    signs = []
    for s in src["signs"]:
        rule = size_rule(s)
        e = {"code": s["code"], "name": s["name"], "category": s["category"], "shape": s["shape"],
             "sizes": STD if rule else ["custom"], "default_size": "750" if rule else "custom",
             "size_rule": rule, "legend": legend_type(s), "mirror": s.get("mirror", False),
             "figure": s["figure"], "page": s["page"]}
        if s["code"] in PLATES:
            e["plate_style"] = list(PLATES[s["code"]])
        if s.get("note"):
            e["note"] = s["note"]
        signs.append(e)
    print("regenerated icons:", regenerate_icons(signs))
    add_derived(signs)
    cat = {
        "catalogue_version": "RDM6.2-2025.2",
        "standard": {
            "name": "Road Design Manual Vol. 6 Part 2: Traffic Signs (RDM 6.2)",
            "edition": "2025", "publisher": "Ministry of Roads and Transport, Kenya",
            "note": "Codes, names and artwork extracted from the manual's figures. Sizes: 600/750/900 mm "
                    "(RDM 2.9), 1200 mm on expressways; auto size from design speed per Tables 3.1, 3.3, 4.1.",
        },
        "shapes": {
            "triangle": {"boq_label": "Triangular warning sign"},
            "inv_triangle": {"boq_label": "Inverted triangular sign"},
            "circle": {"boq_label": "Circular regulatory sign"},
            "octagon": {"boq_label": "Octagonal (Stop) sign"},
            "rectangle": {"boq_label": "Rectangular sign / plate"},
        },
        "signs": signs,
        "posts": {
            "POST-SGL": {"description": "Single sign post", "unit": "No."},
            "POST-DBL": {"description": "Double sign posts (large signs)", "unit": "No."},
            "GANTRY": {"description": "Overhead gantry / cantilever", "unit": "No."},
        },
        "foundations": {
            "FDN-STD": {"description": "Foundation to single post"},
            "FDN-LRG": {"description": "Foundation to large sign / double posts"},
            "FDN-GANTRY": {"description": "Gantry foundation"},
        },
        "defaults": {"post": "POST-SGL", "foundation": "FDN-STD"},
    }
    with open(os.path.join(DATA, "catalogue.json"), "w", encoding="utf-8") as f:
        json.dump(cat, f, indent=1)
    from collections import Counter
    print(len(signs), "signs;", Counter(s["legend"] for s in signs), Counter(s["size_rule"] for s in signs))


if __name__ == "__main__":
    main()
