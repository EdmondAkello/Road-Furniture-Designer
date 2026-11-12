# Changelog

## Unreleased

### Added
- **Supplementary signs from the standard drawings WSCM/84/2/01** (Jan 2024): 19 signs with no RDM 6.2 equivalent, coded `WSCM-` so they never collide with RDM numbers (catalogue now 270 signs). `tools/extract_wscm_signs.py`, `rfd/data/wscm_signs.json`, and `rfd/data/wscm_crossref.json` mapping all 75 WSCM codes to RDM 6.2. WSCM-M14 (End of All Prohibitions) ends speed limits, no-overtaking zones and clearways in the pairing checks; WSCM-M9 is ended by WSCM-M8 or M14. The furniture checks list the WSCM signs used.
- **Junction islands and markings as templates** (Junctions tab) from RDM/1/3/2/01-02: kits for types A-1, A-2, B, B-Mod and C, or single pieces, placed with two clicks (junction point, then a point up the minor road) so they take the skew; optional scale; guide lines (edges, kerb returns, Rc arcs) for sketching. Layer `rsd_junctions`, open data `rfd/data/junction_templates.json`, report schedule and Excel sheet, crossing angle check (RDM 1.3 9.2.3), plan sheets and DXF layers `RSD-JN-*`.

- **Our road joining another road** (Junctions tab): the main road is another alignment of the LandXML or a clicked direction; markings on our approach, R2 Give Way proposed (kept when auto-placement is re-run, removed with the junction).
- **Crossings and humps drawn as painted**: zebra bars, bar sets, BM04 triangles and filled hump footprints on the map, plan sheets and DXF; transverse items go in with one click from the Linear tab.
- **Bus bays** (RDM/1/3/3/01) placed with two clicks: tapers in the direction of travel, kerb, platform, separation line, shelter position and Bus Stop sign; 60 m spacing check for opposite bays.
- **Climbing lanes** (RDM 1.3 6.6, RDM/1/3/3/02): proposed from the profile against Table 6.6 (with the AADT rule) or placed by two clicks; 100 m tapers, lane width per 6.6.3, LM26 / LM03 lines, WSCM-I1 / I2 signs.
- Excel sheet **Widenings**: the widening table for Civil 3D (bus bays and climbing lanes).
- **Crossing extent and refuges**: crossings run between the ETW edges or between two clicked kerbs; a refuge / median width splits them into two zebras with a kerbed refuge island (new item `REFUGE`), with leg-length and refuge-width checks.
- **Installable plugin ZIP from CI** (`.github/workflows/plugin-zip.yml`): built, checked (`tools/check_plugin_zip.py`), installed into QGIS 3.44 and loaded on every push; attached to a draft release for `v*` tags. The README explains where to download it.
- User guide: Junctions tab, supplementary signs, installing from the plugin ZIP.

### Fixed
- Installing from GitHub's "Download ZIP" failed (`ModuleNotFoundError`): that is the source repository; the README and guide now point to the plugin ZIP.
- The dock needed at least 1166 x 1048 px, so its bottom buttons were out of reach on a 1080p screen, and it disappeared when a neighbouring panel was resized. Every tab now scrolls and shrinks to a 380 px panel, and the toolbar button only reacts to clicks (show, bring to front, re-dock).
- WSCM sign artwork: no seams in the colour fills; closed frames on WSCM-I1 and I2 (drafting slips on the sheet).
- Core tests pass flat sequences to `pytest.approx` (pytest 9).
- The Linear tab was still wider than a 380 px dock on QGIS 3.44 (CI failure): the two group titles and two checkbox captions are shortened, with the full wording kept as the tooltip.
- CI uses `actions/checkout@v5` and `actions/setup-python@v6` (Node.js 24).

## 0.8.0 — 2026-11-11

### Added
- **Linear furniture layer** (`rsd_lines`): markings, road studs, barriers and transverse items as runs with an item code, chainages, side and an offset from a corridor edge or the centreline; geometry, length and quantities rebuilt on every edit. Open catalogue `rfd/data/furniture_linear.json` (`RFD_FURNITURE_PATH`). Inventory `Linear` sheet and quantities; DXF layers `RSD-MARK-*`, `RSD-STUD-*`, `RSD-BARRIER-*`.
- **Markings and road studs** (RDM 6.1): broken, combined (LM28) and double continuous (LM32) centre lines from the no-overtaking zones, LM24 on narrow roads, LM26/LM27 edge lines, studs at 6, 9 and 12 m. The passing sight distance is the one basis for the P32 signs and the continuous line.
- **Embankment barriers** (RDM 1.3 Chapter 12): fill height from the hinge to original ground at the toe (section ground line, else a TIN, else the daylight point), Figure 12.4 warrant, Table 12.6 run-out carried to the tangent point, 30 m minimum, gaps under 80 m closed, set-back, terminals, clear-zone findings.
- **Drawing linear furniture by hand** on the map or by chainage, with offsets from an edge, the centreline or a fixed value.
- **Traffic calming and crossings** (RDM 6.4, RDM 6.1 §9.2): circular and trapezoidal humps, speed tables and raised crossings, speed bumps, bar markings and zebra crossings, each with its markings, W64/W55 signs and a visibility check.
- **Speed limit zones** (RDM 6.2 §3.5): limit signs where traffic enters, repeaters, P9 where it leaves; flags a limit above the design speed; optional 50 km/h zones from the design speed.
- **Report**: strip diagram; marking, barrier and feature schedules; linear quantities; furniture checks rerun from the geometry (centre line against the no-overtaking zones, barrier coverage, missing signs, 0.6 V spacing, alignment combinations, feature visibility, speed limits, and start/end sign pairs from `rfd/data/sign_pairs.json`); plan sheets draw the linear furniture. Excel sheets Markings, Barriers, Features, Furniture quantities, Furniture checks.
- **Design criteria from RDM 1.3 (2025)** as open criteria files (`rfd/data/criteria`, `RFD_CRITERIA_PATH`, `extends`), replacing the AASHTO defaults; AASHTO 2011 stays available.
- **Catalogue** (251 signs): the supplementary `END` plate (RDM 6.2 §3.11, §3.6), now placed with P32 at the end of a no-overtaking zone; P22, IM16–IM18 and RW41.
- Synthetic guide road (`tools/guide/make_guide_road.py`); user guide rebuilt from it, with HTML, figures and PDF in `docs/user-guide`.
- CI (core tests, QGIS tests in the official QGIS container, Bandit), citation, contributing guide and templates.

### Changed
- The report is the **Road furniture report**; the plan sheets are road furniture plans.
- The end of a no-overtaking zone is P32 with the END plate instead of an END legend on the P32 (the legend never showed on the face). Older projects' END legends still count as ends in the checks.

### Fixed
- Running auto-placement again over accepted signs duplicated chevrons and distance plates.
- Plan sheets failed when the LandXML held a second alignment.

## 0.7.0 — 2026-11-11

### Changed
- Renamed **Road Furniture Designer** (from RoadSign Designer) and prepared for open source under GPL-2.0-or-later. Packages `qgis_plugin/road_furniture_designer` and core `rfd`. On-disk identifiers (GeoPackage `rsd_*`, DXF `RSD-*` layers and `RSD_*` blocks, `RSD` XDATA) are unchanged, and projects saved under the old name reopen.
- No built-in company logo; an optional report logo from the `RoadFurnitureDesigner/report_logo` setting.

### Added
- RDM 1.3 Figure 12.4 barrier warrant curves, digitised.

## 0.6.2 — 2026-11-03
- Faster LandXML loading (TIN surfaces skipped, corridor sections read by a byte scan, results cached) and station/offset lookup through a grid index.
- Plan sheets draw only the geometry inside each viewport.
- The dock summary shows missing design speeds, profile, superelevation and road edges with the default used.

## 0.6.1 — 2026-11-03
- DXF legend and plate text in Arial (`RSD_LEGEND` style), so plate text fits in Civil 3D.
- DXF copy and paste (COPYBASE 0,0 and PASTEORIG) confirmed in a Civil 3D project drawing.

## 0.6.0 — 2026-11-03
- DXF signs at 10 mm on paper, one block per sign at its post with a leader to the upright face; reference layers for every alignment and the corridor edges.
- Report plan layout sheets at a chosen scale, drawing frame and title block with Prepared / Checked / Approved by.
- Grade signs show the actual grade; RDM 6.2 sign codes on drawings and schedules.
- First user guide and technical manual.

## Earlier
Development versions: RDM 6.2 sign catalogue extracted from the manual's figures; QGIS placement with live chainage, offset, side and facing; auto-placement of curve, grade and no-overtaking signs; inventory for the QTO; signage report; Civil 3D placement package and DXF.
