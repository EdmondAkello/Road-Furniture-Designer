import pytest

from rfd.alignment import Alignment
from rfd.corridor import Edges
from rfd.features import FeatureConfig, design_feature
from rfd.linear import LinearCatalogue, run_quantities, summarise
from rfd.profile import VerticalProfile

CAT = LinearCatalogue.load()


def road(speed=50.0, profile=None, etw=3.5, length=1000.0):
    al = Alignment.from_polyline("F", [(0, 0), (length, 0)])
    al.speeds = [(0.0, speed)]
    al.profile = profile or VerticalProfile("p", [(0, 100, 0), (length, 100, 0)])
    if etw:
        al.edges = Edges({("ETW", s): [(x, etw) for x in range(0, int(length) + 1, 20)] for s in "LR"})
    return al


def codes(d):
    return sorted(r.code for r in d.runs)


def test_circular_hump_table_2_1_signs_bars():
    d = design_feature(road(50), "hump_circular", 500, FeatureConfig(desired_speed=30))
    hump = next(r for r in d.runs if r.code == "HUMP-C")
    assert hump.length == pytest.approx(4.0) and hump.width == pytest.approx(7.0)      # 30 km/h: R 20 m, chord 4 m
    assert "R 20 m" in hump.reason and "buses about 15" in hump.reason
    assert "BM04" in codes(d)
    bars = sorted((r for r in d.runs if r.code == "BAR-SET"), key=lambda r: r.sta_start)
    assert len(bars) == 2                                                               # <= 50 km/h: one set each way
    assert bars[0].sta_end == pytest.approx(498 - 50) and bars[1].sta_start == pytest.approx(502 + 50)
    assert bars[0].length == pytest.approx(6 * 0.3 + 5 * 0.6)
    w64 = sorted((p.station, p.side, p.facing) for p in d.signs)
    assert w64 == [(pytest.approx(498 - 90), "L", "Forward"), (pytest.approx(502 + 90), "R", "Backward")]
    assert all(p.code == "W64" for p in d.signs)
    assert len({r.rule for r in d.runs} | {p.rule for p in d.signs}) == 1
    q = run_quantities(bars[0], CAT["BAR-SET"])
    assert q["count"] == 1 and q["area"] == pytest.approx(6 * 0.3 * 7.0)
    # desired speed between rows takes the lower row; above the table, the top row
    assert next(r for r in design_feature(road(50), "hump_circular", 500, FeatureConfig(desired_speed=42)).runs
                if r.code == "HUMP-C").length == pytest.approx(6.5)
    # 80 km/h approach: three bar sets each way at 50, 80, 120 m, 1 m gaps
    d = design_feature(road(80), "hump_trapezoidal", 500, FeatureConfig(desired_speed=40))
    t = next(r for r in d.runs if r.code == "HUMP-T")
    assert t.length == pytest.approx(2 * 1.7 + 2.5)
    assert sum(r.code == "BAR-SET" for r in d.runs) == 6
    assert next(r for r in d.runs if r.code == "BAR-SET").length == pytest.approx(1.8 + 5.0)


def test_bump_speed_limit_and_tables_and_crossings():
    d = design_feature(road(60), "speed_bump", 500)
    assert not d.runs and not d.signs and any(f.kind == "feature_error" for f in d.findings)
    d = design_feature(road(40), "speed_bump", 500)
    assert codes(d) == ["BUMP"] and [p.code for p in d.signs] == ["W64", "W64"]
    d = design_feature(road(50), "speed_table", 500)
    assert next(r for r in d.runs if r.code == "TABLE").length == pytest.approx(8.4)
    d = design_feature(road(50), "raised_crossing", 500, FeatureConfig(crossing_width=4.0))
    assert {"TABLE", "BM03", "BM04"} <= set(codes(d)) and {p.code for p in d.signs} == {"W55"}
    d = design_feature(road(50), "crossing", 500, FeatureConfig(crossing_width=3.0))
    z = next(r for r in d.runs if r.code == "BM02")
    assert z.length == pytest.approx(3.0) and run_quantities(z, CAT["BM02"])["area"] == pytest.approx(0.5 * 3 * 7)
    assert {p.code for p in d.signs} == {"W55"} and not any(r.code == "BAR-SET" for r in d.runs)
    d = design_feature(road(50, etw=6.0), "crossing", 500)
    assert any("refuge" in f.text for f in d.findings)
    d = design_feature(road(50), "crossing", 500, FeatureConfig(crossing_width=5.0))
    assert any("outside 2-4 m" in f.text for f in d.findings)
    d = design_feature(road(50, etw=None), "crossing", 500)
    assert any("assumed" in f.text or "7.0 m" in f.text for f in d.findings)


def test_visibility_over_a_crest_and_ends():
    crest = VerticalProfile("p", [(0, 100, 0), (500, 120, 60), (1000, 100, 0)])        # 4 % / -4 %, K = 7.5
    d = design_feature(road(80, profile=crest), "crossing", 560)
    vis = [f for f in d.findings if f.kind == "feature_visibility"]
    assert [f.direction for f in vis] == ["Forward"]                                     # hidden behind the crest
    d = design_feature(road(80), "crossing", 560)
    assert not [f for f in d.findings if f.kind == "feature_visibility"]
    d = design_feature(road(80), "hump_circular", 30)
    assert len(d.signs) == 1 and any("beyond the alignment end" in f.text for f in d.findings)
    with pytest.raises(ValueError):
        design_feature(road(), "bus_bay", 100)
    with pytest.raises(ValueError):
        design_feature(road(), "crossing", 2000)


def test_summary_counts_transverse():
    d = design_feature(road(50), "hump_circular", 500)
    rows = {(r[1], r[4]): r[5] for r in summarise(d.runs, CAT)}
    assert rows[("HUMP-C", "No.")] == 1 and rows[("BAR-SET", "No.")] == 2
    assert rows[("BAR-SET", "m2")] == pytest.approx(2 * 6 * 0.3 * 7, abs=0.1)
