"""Batch operations signal the dock once, not once per feature: a GeoPackage commit signals every feature
written, and each signal used to rebuild the whole inventory (152 signs: 156 rebuilds, 13 s on a 17 km road)."""
import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "qgis_plugin"))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from qgis.core import QgsApplication  # noqa: E402

if QgsApplication.instance() is None:
    _app = QgsApplication([], True)
    _app.initQgis()

from test_furniture_report import _fill_road  # noqa: E402


def _props(st, n=40):
    from road_furniture_designer.rfd.autoplace import Proposal
    L = st.al.sta_end - st.al.sta_start
    return [Proposal("W1", st.al.sta_start + 20 + k * (L - 40) / n, "LR"[k % 2], "Forward", "test", "batch")
            for k in range(n)]


def _count(st):
    n = [0]
    st.changed.connect(lambda: n.__setitem__(0, n[0] + 1))
    return n


def test_sign_batches_signal_once(tmp_path):
    from road_furniture_designer.rfd.autoplace import AutoConfig
    st, _ = _fill_road(tmp_path)
    n = _count(st)
    assert st.place_proposals(_props(st)) == 40      # 40 signs, one edit session, one commit
    assert n[0] == 1
    n[0] = 0
    st.auto_propose(AutoConfig())                    # removes the 40 proposals, runs the rules, commits
    assert n[0] == 1
    n[0] = 0
    st.accept_proposals()
    assert n[0] == 1
    n[0] = 0
    st.remove_proposals()
    assert n[0] == 1


def test_linear_proposals_signal_once(tmp_path):
    from road_furniture_designer.rfd.autoplace import AutoConfig
    from road_furniture_designer.rfd.barriers import BarrierConfig
    from road_furniture_designer.rfd.markings import MarkingConfig
    st, xml = _fill_road(tmp_path)
    n = _count(st)
    k, _f, _s = st.lines.auto_propose_markings(MarkingConfig.from_auto(AutoConfig(), road_class="B"))
    assert k > 1 and n[0] == 1
    n[0] = 0
    k, _f, _s = st.lines.auto_propose_barriers(BarrierConfig(landxml=xml))
    assert k >= 1 and n[0] == 1


def test_journaled_operation_and_undo_signal_once(tmp_path):
    st, _ = _fill_road(tmp_path)
    x0, y0, h = st.al.point_at(600.0)
    n = _count(st)
    from road_furniture_designer.rfd import junctions as J
    pl = J.place(st.al, x0, y0, x0 + 40 * math.cos(h + math.pi / 2), y0 + 40 * math.sin(h + math.pi / 2))
    st.add_junction(pl, "C")
    assert n[0] == 1
    n[0] = 0
    assert st.undo()
    assert n[0] == 1 and not st.junctions.junctions()
    n[0] = 0
    assert st.redo()
    assert n[0] == 1 and st.junctions.junctions()


def test_editing_the_layer_by_hand_still_signals(tmp_path):
    """QGIS's own edit tools: deleting a sign and saving the layer still refresh the dock."""
    st, _ = _fill_road(tmp_path)
    st.place_proposals(_props(st, 4))
    n = _count(st)
    st.signs.startEditing()
    fid = next(st.signs.getFeatures()).id()
    st.signs.deleteFeature(fid)
    assert n[0] >= 1
    n[0] = 0
    assert st.signs.commitChanges()
    assert n[0] >= 1
