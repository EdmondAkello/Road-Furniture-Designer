from rfd import criteria
from rfd.autoplace import curve_speed


def test_rdm13_tables():
    c = criteria.get()
    assert c.is_kenya and c.eye_height == 1.05 and c.psd_object_height == 1.3
    assert c.f_max(80) == 0.13 and c.f_max(60) == 0.16             # Table 5.1
    assert c.ssd(80) == 100 and c.ssd(80, -6) == 110 and c.ssd(80, 6) == 95   # Table 3.16
    assert c.psd(80) == 325 and c.psd(80, reduced=False) == 475    # Table 3.20
    assert c.k_crest(80) == 45 and c.k_sag(80) == 32
    assert c.clear_zone(70, fill=True) == 5.5 and c.clear_zone(70, fill=False, low_traffic=True) == 2.5
    assert c.barrier_runout(80) == 85
    assert c.marking_visibility(80) == (130, 95) and c.marking_visibility(50, "A") == (300, 135)


def test_curve_speed_matches_table_5_1():
    # Table 5.1: e = 6 %, 80 km/h -> R min 265 m; 60 km/h -> 130 m
    assert abs(curve_speed(265, 6.0) - 80) < 1.5
    assert abs(curve_speed(130, 6.0) - 60) < 1.5


def test_barrier_warrant_figure_12_4():
    w = criteria.barrier_warrant
    assert w(6.0, 2.5) == "required" and w(6.0, 3.5) == "judgement" and w(6.0, 4.5) == "not_required"
    assert w(0.5, 0.5) == "not_required"
    assert w(13.5, 3.9) == "required"


def test_aashto_alternative():
    a = criteria.get("aashto_2011")
    assert a.f_max(80) == 0.14 and a.ssd(80) == 130 and a.psd(80) == 245


# ---------------------------------------------------------------- user criteria (open schema)
def test_user_criteria_extends_and_overrides(tmp_path, monkeypatch):
    import json
    from rfd import criteria as C
    (tmp_path / "my_tz.json").write_text(json.dumps({
        "schema": "rfd-criteria/1", "id": "tz_test", "name": "Test national manual",
        "extends": "kenya_rdm_2025",
        "ssd": {"60": 80, "80": 120},
        "references": {"ssd": "Test manual Table 1"}}))
    monkeypatch.setenv("RFD_CRITERIA_PATH", str(tmp_path))
    C._CACHE.clear()
    ids = dict(C.list_criteria())
    assert "tz_test" in ids and C.list_criteria()[0][0] == C.DEFAULT_ID
    c = C.get("tz_test")
    assert c.ref("ssd") == "Test manual Table 1"
    assert c.ref("psd") == C.get().ref("psd")                 # inherited reference
    assert c.psd(80, True) == 325                             # inherited table
    assert c.barrier_warrant(6, 2.5) == "required"            # inherited warrant curve
    C._CACHE.clear()


def test_user_criteria_inline_warrant_and_simple_rule(tmp_path):
    import json
    from rfd import criteria as C
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"id": "x", "side_friction": {"80": 0.14}, "ssd": {"80": 130}, "psd": {"80": 245},
                             "barrier_warrant": {"heights": [1, 10], "required_below": [2, 3]}}))
    c = C.Criteria.load(str(p))
    assert c.barrier_warrant(5, 2.0) == "required" and c.barrier_warrant(5, 4.0) == "not_required"
    p.write_text(json.dumps({"id": "y", "side_friction": {"80": 0.14}, "ssd": {"80": 130}, "psd": {"80": 245},
                             "barrier": {"simple": {"height": 3.0, "slope_n": 3.0}}}))
    c = C.Criteria.load(str(p))
    assert c.barrier_warrant(4, 2) == "required" and c.barrier_warrant(2, 2) == "not_required"


def test_user_criteria_missing_tables(tmp_path):
    import json, pytest
    from rfd import criteria as C
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"id": "bad", "ssd": {"80": 1}}))
    with pytest.raises(ValueError, match="side_friction"):
        C.Criteria.load(str(p))
