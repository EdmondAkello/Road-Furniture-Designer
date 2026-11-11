import pytest

from rfd.alignment import Alignment
from rfd.corridor import Edges
from rfd.autoplace import AutoConfig, analyse, horizontal_sight
from rfd.markings import MarkingConfig as _MC, _clean, _close_gaps, _segments, propose_markings


def MarkingConfig(**kw):            # the Table 4.4 rules, tested here; the default PSD basis is tested below
    kw.setdefault("basis", "table_4_4")
    return _MC(**kw)
from rfd.profile import VerticalProfile
from tests.test_autoplace import road


def straight(length=3000.0, speed=80.0, profile=None, etw=3.5, eps=None):
    al = Alignment.from_polyline("T", [(0, 0), (length, 0)])
    al.speeds = [(0.0, speed)]
    al.profile = profile
    if etw:
        d = {("ETW", s): [(x, etw) for x in range(0, int(length) + 1, 20)] for s in "LR"}
        if eps:
            d.update({("EPS", s): [(x, eps) for x in range(0, int(length) + 1, 20)] for s in "LR"})
        al.edges = Edges(d)
    return al


def by_code(runs):
    out = {}
    for r in runs:
        out.setdefault(r.code, []).append(r)
    return out


def test_flat_road_broken_centre_and_edges():
    al = straight(profile=VerticalProfile("p", [(0, 100, 0), (3000, 100, 0)]), eps=5.0)
    runs, findings = propose_markings(al, MarkingConfig(road_class="B"))
    c = by_code(runs)
    assert set(c) == {"LM02", "LM27"}                      # class B: higher category lines, no studs needed
    assert c["LM02"][0].length == pytest.approx(3000)
    assert {r.side for r in c["LM27"]} == {"L", "R"} and all(r.edge_ref == "ETW" for r in c["LM27"])
    assert all(r.status == "proposed" for r in runs) and not findings
    runs, _ = propose_markings(al, MarkingConfig(road_class="C"))
    assert set(by_code(runs)) == {"LM01", "LM26"}
    runs, _ = propose_markings(al, MarkingConfig(road_class="A"))
    c = by_code(runs)
    assert {"RRS-C", "RRS-E"} <= set(c) and not any(r.no_overtaking for r in c["RRS-E"])


def test_crest_gives_cls_each_way_and_double_over_the_top():
    # 6 % up, sharp crest (K = 100/12 = 8.3), 6 % down
    pr = VerticalProfile("p", [(0, 100, 0), (1500, 190, 100), (3000, 100, 0)])
    al = straight(profile=pr, eps=5.0)
    runs, findings = propose_markings(al, MarkingConfig(road_class="B"))
    c = by_code(runs)
    lm28 = sorted(c["LM28"], key=lambda r: r.sta_start)
    assert len(lm28) == 2 and not lm28[0].flip and lm28[1].flip      # forward prohibited before the crest
    assert lm28[0].sta_end <= 1500 <= lm28[1].sta_start
    dbl = c["LM32"][0]
    assert dbl.sta_start == pytest.approx(lm28[0].sta_end) and dbl.sta_end == pytest.approx(lm28[1].sta_start)
    cover = sorted((r.sta_start, r.sta_end) for code in ("LM02", "LM28", "LM32") for r in c[code])
    assert cover[0][0] == 0 and cover[-1][1] == pytest.approx(3000)
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(cover, cover[1:]))     # no gaps, no overlaps
    assert sum(r.length for r in c["RRS-CLS"]) == pytest.approx(lm28[1].sta_end - lm28[0].sta_start)
    e = [r for r in c["RRS-E"]]
    assert all(r.no_overtaking and r.offset == 0.15 for r in e) and {r.side for r in e} == {"L", "R"}
    assert {f.direction for f in findings if f.kind == "marking_cls"} == {"Forward", "Backward", "Both"}
    runs, _ = propose_markings(al, MarkingConfig(road_class="B", studs="none"))
    assert not any(r.code.startswith("RRS") for r in runs)


def test_table_4_4_rules():
    crt = lambda s: 95.0
    assert _clean([[100, 105]], 0, 1000, crt, 50, 5) == []                       # need 10 m: dropped
    assert _clean([[100, 120]], 0, 1000, crt, 50, 5) == [[85, 135]]             # need 25 m: laid as 50 m
    assert _clean([[0, 20]], 0, 1000, crt, 50, 5) == [[0, 50]]
    assert _clean([[100, 200], [280, 400]], 0, 1000, crt, 50, 5) == [[100, 400]]   # 80 m apart < 95 m: joined
    assert _clean([[100, 200], [300, 400]], 0, 1000, crt, 50, 5) == [[100, 200], [300, 400]]
    segs = _segments(0, 1000, [[100, 300]], [[400, 600]])
    assert [s[2] for s in segs] == ["", "F", "", "B", ""]
    closed = _close_gaps(segs, lambda s: 130.0)                                  # 100 m gap < 130 m visibility
    assert [(s[0], s[1], s[2]) for s in closed] == [(0, 100, ""), (100, 300, "F"), (300, 400, "FB"),
                                                     (400, 600, "B"), (600, 1000, "")]


def test_narrow_road_single_line_and_no_profile_note():
    pr = VerticalProfile("p", [(0, 100, 0), (1500, 190, 40), (3000, 100, 0)])
    al = straight(profile=pr, etw=2.5)
    runs, findings = propose_markings(al, MarkingConfig(road_class="D"))
    c = by_code(runs)
    assert "LM24" in c and not ({"LM01", "LM02", "LM28", "LM32"} & set(c))
    assert any("5.5" in f.text for f in findings)
    al = straight(profile=None, etw=None)
    runs, findings = propose_markings(al, MarkingConfig())
    assert set(by_code(runs)) == {"LM02"}
    assert any("profile" in f.text for f in findings) and any("edge" in f.text for f in findings)


def test_bend_visibility_and_speed_split():
    al = road(radius=100.0)
    al.profile = VerticalProfile("p", [(0, 100, 0), (2000, 100, 0)])
    st = [i * 5.0 for i in range(int(al.length // 5) + 1)]
    pts = [al.point_at(s)[:2] for s in st]
    hs = horizontal_sight(pts, st, 1, 5.0, 200)
    assert hs[st.index(200.0)] == 200 and hs[st.index(520.0)] < 80          # 2*sqrt(2*100*5) = 63 m in the arc
    runs, _ = propose_markings(al, MarkingConfig(road_class="B", sight_offset=5.0))
    assert any(r.code == "LM32" and r.sta_start < 580 < r.sta_end for r in runs)
    runs, _ = propose_markings(al, MarkingConfig(road_class="B"))
    assert not any(r.code in ("LM28", "LM32") for r in runs)
    al = straight(profile=VerticalProfile("p", [(0, 100, 0), (3000, 100, 0)]))
    al.speeds = [(0.0, 100.0), (1200.0, 50.0)]
    runs, _ = propose_markings(al, MarkingConfig(edges=False))
    assert sorted((r.sta_start, r.sta_end) for r in runs) == [(0, 1200), (1200, 3000)]


def zones_of(runs):
    f = sorted((r.sta_start, r.sta_end) for r in runs if r.code in ("LM32", "LM24") or (r.code == "LM28" and not r.flip))
    b = sorted((r.sta_start, r.sta_end) for r in runs if r.code in ("LM32", "LM24") or (r.code == "LM28" and r.flip))
    def merge(x):
        out = []
        for a, c in x:
            if out and a - out[-1][1] < 1e-6:
                out[-1][1] = c
            else:
                out.append([a, c])
        return [tuple(t) for t in out]
    return merge(f), merge(b)


def test_psd_basis_matches_the_no_overtaking_signs():
    pr = VerticalProfile("p", [(0, 100, 0), (1500, 190, 100), (3000, 100, 0), (4500, 130, 300), (6000, 100, 0)])
    al = straight(length=6000.0, profile=pr, eps=5.0)
    auto = AutoConfig(curves=False, grades=False)
    signs = {d: sorted((f.start, f.end) for f in analyse(al, auto) if f.kind == "no_overtaking" and f.direction == d)
             for d in ("Forward", "Backward")}
    assert signs["Forward"] and signs["Backward"]
    runs, findings = propose_markings(al, _MC.from_auto(auto, road_class="B"))
    f, b = zones_of(runs)
    assert f == pytest.approx(signs["Forward"]) and b == pytest.approx(signs["Backward"])
    assert any("Passing sight distance of 325 m" in r.reason for r in runs if r.code in ("LM28", "LM32"))
    # the Table 4.4 basis gives shorter zones on the same road
    t_runs, _ = propose_markings(al, MarkingConfig(road_class="B"))
    solid = lambda rs: sum(r.length for r in rs if r.code in ("LM28", "LM32"))
    assert 0 < solid(t_runs) < solid(runs)
    # normal (not reduced) PSD lengthens both alike
    auto2 = AutoConfig(curves=False, grades=False, psd_reduced=False)
    runs2, _ = propose_markings(al, _MC.from_auto(auto2, road_class="B"))
    assert solid(runs2) > solid(runs)


def test_opposite_zones_closer_than_the_merge_gap_meet():
    from rfd.autoplace import no_overtaking_zones
    pr = VerticalProfile("p", [(0, 100, 0), (1500, 190, 100), (3000, 100, 0)])
    al = straight(profile=pr)
    z = no_overtaking_zones(al, AutoConfig())
    allz = sorted(z["Forward"] + z["Backward"])
    for (a0, a1), (b0, b1) in zip(allz, allz[1:]):
        assert b0 <= a1 + 1e-6 or b0 - a1 > 100          # overlapping/touching, or a real overtaking length
