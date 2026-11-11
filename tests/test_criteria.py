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
