"""Road furniture report core: schedules, consistency checks and strip lanes."""
import pytest

from rfd import furniture_report as FR
from rfd.autoplace import AutoConfig, Finding, Proposal, no_overtaking_zones, propose
from rfd.features import KINDS, FeatureConfig, design_feature
from rfd.linear import LinearCatalogue, Run
from rfd.markings import MarkingConfig, propose_markings
from tests.test_bootstrap import random_road

LCAT = LinearCatalogue.load()


def sign(sta, code, facing="Forward", side="L", status="approved", post=None, rule=""):
    return {"sta": sta, "code": code, "facing": facing, "side": side, "status": status,
            "post": post or f"P{sta:.0f}{code}", "rule": rule}


def test_union_and_uncovered():
    assert FR.union([(5, 10), (0, 6), (20, 30)]) == [(0, 10), (20, 30)]
    assert FR.uncovered(0, 100, [(10, 40), (60, 100)]) == [(0, 10), (40, 60)]
    assert FR.uncovered(0, 100, [(3, 98)]) == []                      # slivers under 5 m are ignored


def test_centre_line_directions():
    assert FR.prohibits(Run("LM32", 0, 10)) == {"Forward", "Backward"}
    assert FR.prohibits(Run("LM28", 0, 10)) == {"Forward"}
    assert FR.prohibits(Run("LM28", 0, 10, flip=True)) == {"Backward"}
    assert FR.prohibits(Run("LM02", 0, 10)) == set()


def test_centre_line_gaps_found():
    al, _ = random_road(3)
    a = al.sta_start
    zones = {"Forward": [(a + 100, a + 300)], "Backward": [(a + 500, a + 600)]}
    runs = [Run("LM02", a, a + 100), Run("LM28", a + 100, a + 250), Run("LM02", a + 250, a + 500),
            Run("LM28", a + 500, a + 600, flip=True)]
    out = FR.centre_line_checks(al, runs, zones)
    assert len(out) == 1 and out[0].side == "Forward" and out[0].values["length"] == pytest.approx(50)
    # a CLS the wrong way round does not cover the zone
    runs[-1].flip = False
    assert {c.side for c in FR.centre_line_checks(al, runs, zones)} == {"Forward", "Backward"}
    assert FR.centre_line_checks(al, [], zones)[0].kind == "no_centre_line"


def test_barrier_coverage():
    al, _ = random_road(5)
    a = al.sta_start
    want = [Finding("barrier", a + 100, a + 400, "L", "w", {"height": 6.0}),
            Finding("barrier", a + 100, a + 400, "R", "w", {"height": 6.0})]
    runs = [Run("GR-W", a + 100, a + 300, side="L"), Run("GR-W", a + 800, a + 900, side="R")]
    out = FR.barrier_checks(al, runs, LCAT, want)
    kinds = {(c.kind, c.side) for c in out}
    assert ("barrier_short", "L") in kinds and ("barrier_missing", "R") in kinds
    assert ("barrier_unwarranted", "R") in kinds
    short = next(c for c in out if c.kind == "barrier_short")
    assert short.values["length"] == pytest.approx(100)


def test_sign_spacing_and_missing():
    al, _ = random_road(1)
    a = al.sta_start
    v = al.speed_at(a + 100) or 80.0
    signs = [sign(a + 100, "W20"), sign(a + 100 + 0.3 * v, "W30"),          # too close
             sign(a + 300, "W24-a"), sign(a + 310, "W24-a"),                  # chevron series: own spacing
             sign(a + 500, "P32"), sign(a + 505, "W23"),                      # plate on the P32
             sign(a + 100, "W20", facing="Backward", side="R")]
    wanted = [Proposal("W20", a + 100 + 1.1 * v, "L", "Forward", "curve", ""),     # moved along by placement
              Proposal("W19", a + 700, "L", "Forward", "curve", "")]
    out = FR.sign_checks(al, signs, wanted)
    sp = next(c for c in out if c.kind == "sign_spacing")
    assert sp.values["count"] == 1
    miss = next(c for c in out if c.kind == "sign_missing")
    assert miss.values["count"] == 1 and "W19" in miss.text and miss.level == "issue"


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_feature_kind_round_trip(kind):
    al, _ = random_road(11)
    sta = al.sta_start + al.length / 2
    v = al.speed_at(sta) or 80.0
    d = design_feature(al, kind, sta, FeatureConfig(carriageway=7.0))
    if not d.runs:
        assert kind == "speed_bump" and v >= 50
        return
    signs = [sign(p.station, p.code, p.facing, p.side, "proposed", rule=p.rule) for p in d.signs]
    groups = FR.feature_groups(d.runs, signs)
    assert len(groups) == 1
    g = groups[0]
    assert g["kind"] == kind and g["station"] == pytest.approx(sta, abs=0.01)
    assert len(g["signs"]) == len(d.signs)


@pytest.mark.parametrize("seed", range(30))
def test_random_report(seed):
    """Random roads with RFD's own proposals: markings agree with the PSD zones, every sign the geometry asks
    for is found, features round-trip and every lane item is on the road."""
    al, rng = random_road(seed)
    tag = f"seed {seed}:"
    auto = AutoConfig()
    wanted, _ = propose(al, auto)
    signs = [sign(p.station, p.code, p.facing, p.side, rule=p.rule) for p in wanted]
    cw = None if al.edges else rng.choice([6.0, 7.0, 7.3])
    runs, _ = propose_markings(al, MarkingConfig.from_auto(auto, carriageway=cw))
    kinds = []
    for _ in range(rng.randint(0, 3)):
        k = rng.choice(sorted(KINDS))
        d = design_feature(al, k, al.sta_start + rng.uniform(0.1, 0.9) * al.length, FeatureConfig(carriageway=7.0))
        if d.runs:
            runs += d.runs
            signs += [sign(p.station, p.code, p.facing, p.side, "proposed", rule=p.rule) for p in d.signs]
            kinds.append(k)
    fr = FR.build(al, runs, LCAT, signs, auto, None, FeatureConfig(carriageway=7.0), wanted=wanted)
    assert not fr.checks_of("centre_line"), f"{tag} " + "; ".join(c.text for c in fr.checks_of("centre_line"))
    centre = [r for r in runs if r.side == "C" and r.code in ("LM01", "LM02", "LM24", "LM28", "LM32")]
    if centre:
        assert not fr.checks_of("no_centre_line"), tag
    assert not fr.checks_of("sign_missing"), tag
    # RFD's own signs close everything they open, except a no-overtaking zone running off the alignment end
    for c in fr.checks_of("sign_unclosed"):
        assert c.values["what"] == "No overtaking", f"{tag} {c.text}"
        z = no_overtaking_zones(al, auto)[c.side]
        assert any(abs((a if c.side == "Forward" else b) - c.start) < 1 and
                   (b >= al.sta_end - 1 if c.side == "Forward" else a <= al.sta_start + 1) for a, b in z), f"{tag} {c.text}"
    assert not fr.checks_of("sign_plate", "sign_orphan_end") or all(
        c.level == "info" for c in fr.checks_of("sign_plate", "sign_orphan_end")), tag
    assert sorted(g["kind"] for g in fr.features) == sorted(kinds), tag
    names = [ln.name for ln in fr.lanes]                                 # the centre line midway between the edges
    i = names.index("Centre line")
    assert names[i - 1] == "Edge line, left" and names[i + 1] == "Edge line, right", tag
    for ln in fr.lanes:
        for it in ln.items:
            a = it[0]
            b = it[1] if ln.kind == "bars" else a
            assert al.sta_start - 1e-6 <= a <= b <= al.sta_end + 1e-6, f"{tag} {ln.name}"
    assert any("not rechecked" in n for n in fr.notes), tag              # no barrier config given
    # take away the continuous line over one zone: the report must say so
    zones = no_overtaking_zones(al, auto)
    zf = zones["Forward"]
    if centre and zf:
        a, b = zf[0]
        cut = [r for r in runs if not (r.side == "C" and FR.prohibits(r) and r.sta_start < b and r.sta_end > a)]
        fr2 = FR.build(al, cut, LCAT, signs, auto, None, wanted=wanted)
        if b - a > FR.TOL:
            assert fr2.checks_of("centre_line")[0].level == "issue", tag


def _pair_checks(signs, **kw):
    al, _ = random_road(2)
    return al, FR.pairing_checks(al, signs, **kw)


def test_no_overtaking_needs_end_plate():
    al, _ = random_road(2)
    a = al.sta_start
    start = [sign(a + 100, "P32", post="A"), sign(a + 100, "W23", post="A")]
    out = FR.pairing_checks(al, start)
    assert [c.kind for c in out] == ["sign_unclosed"] and out[0].level == "check"
    ok = start + [sign(a + 600, "P32", post="B"), sign(a + 600, "END", post="B")]
    assert not FR.pairing_checks(al, ok)
    legacy = start + [dict(sign(a + 600, "P32", post="B"), legend="END")]        # older projects
    assert not FR.pairing_checks(al, legacy)
    noplate = [sign(a + 100, "P32", post="A")] + ok[2:]
    assert [c.kind for c in FR.pairing_checks(al, noplate)] == ["sign_plate"]


def test_backward_traffic_reads_down_chainage():
    al, _ = random_road(2)
    a = al.sta_start
    # backward traffic meets the start at the higher chainage and the end at the lower one
    s = [sign(a + 600, "P32", "Backward", "R", post="A"), sign(a + 600, "W23", "Backward", "R", post="A"),
         sign(a + 100, "P32", "Backward", "R", post="B"), sign(a + 100, "END", "Backward", "R", post="B")]
    assert not FR.pairing_checks(al, s)
    flipped = [dict(x, facing="Forward", side="L") for x in s]                     # wrong way round
    kinds = sorted(c.kind for c in FR.pairing_checks(al, flipped))
    assert kinds == ["sign_orphan_end", "sign_unclosed"]


def test_speed_limits_switch_and_end():
    al, _ = random_road(2)
    a = al.sta_start
    s = [sign(a + 100, "P5"), sign(a + 300, "P5"), sign(a + 500, "P7"), sign(a + 900, "P9")]
    assert not FR.pairing_checks(al, s)                                            # repeater, change, end
    out = FR.pairing_checks(al, s[:3])
    assert len(out) == 1 and "P7" in out[0].text
    orphan = FR.pairing_checks(al, [sign(a + 900, "P9")])
    assert [c.kind for c in orphan] == ["sign_orphan_end"] and orphan[0].level == "info"


def test_series_plate_and_other_pairs():
    al, _ = random_road(2)
    a = al.sta_start
    out = FR.pairing_checks(al, [sign(a + 100, "W22")])
    assert [(c.kind, c.level) for c in out] == [("sign_plate", "info")]
    assert not FR.pairing_checks(al, [sign(a + 100, "W27"), sign(a + 800, "W28")])
    assert [c.kind for c in FR.pairing_checks(al, [sign(a + 100, "P17")])] == ["sign_unclosed"]
    for r in FR.load_pairs():                                                      # every code is in the catalogue
        from rfd.catalogue import Catalogue
        cat = Catalogue.load()
        assert all(c in cat.signs for c in r["start"] + r.get("plate", []) + [x for e in r.get("end", []) for x in e])
