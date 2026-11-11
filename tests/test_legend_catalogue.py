from rfd import legend
from rfd.catalogue import Catalogue, size_for_speed


def test_catalogue_is_rdm():
    cat = Catalogue.load()
    assert len(cat.signs) >= 240
    assert cat.signs["R1"].name == "Stop" and cat.signs["R1"].shape == "octagon"
    assert cat.signs["W1"].name == "Crossroads" and cat.signs["W1"].shape == "triangle"
    assert cat.signs["P5"].shape == "circle" and cat.signs["W20"].mirror
    assert {"W24-a", "W24-b", "W24-c", "W24-d"} <= set(cat.signs)
    assert cat.signs["I1-A"].legend == "directional" and cat.signs["W23"].legend == "plate"
    import os
    assert all(os.path.exists(s.svg()) for s in cat.signs.values())


def test_size_rules():
    assert size_for_speed("warning", 70) == "900"      # RDM Table 4.1: > 65
    assert size_for_speed("warning", 65) == "750"
    assert size_for_speed("warning", 49) == "600"
    assert size_for_speed("stop_giveway", 85) == "900"  # Table 3.1: > 80
    assert size_for_speed("stop_giveway", 70) == "750"
    assert size_for_speed("stop_giveway", 50) == "600"
    assert size_for_speed("expressway", None) == "1200"
    assert size_for_speed(None, 80) is None


def test_legend_parse_and_order():
    ls = legend.ordered(legend.parse("> Eldoret A104 140\n< Nakuru A104 18\n< Molo B4 60\n^ Salgaa 2"))
    assert [l.place for l in ls] == ["Salgaa", "Molo", "Nakuru", "Eldoret"]   # ahead, left (furthest first), right
    assert ls[1].route == "B4" and ls[1].distance == "60"
    assert legend.summary("< Nakuru A104 18") == "< Nakuru A104 18 km"
    assert legend.parse("FOR 2 KM")[0].arrow is None


def test_face_svg():
    cat = Catalogue.load()
    a = legend.face_svg(cat.signs["I1-A"], "< Nakuru A104 18", "A")
    c = legend.face_svg(cat.signs["I1-A"], "< Nakuru A104 18", "C")
    assert "#0b7a3b" in a and "#ffd200" in a and "#0b7a3b" not in c
    assert legend.face_svg(cat.signs["W1"], "anything") is None
    assert "Salgaa" in legend.face_svg(cat.signs["I7"], "Salgaa")
