# Changelog

## Unreleased

### Added
- **Centreline-only LandXML** (new **Section** tab): with only the alignment and its design and existing ground profiles in the LandXML, a typical section gives the road edges. Elements per side from the centreline outwards (ETW, EPS, NMT, Walkway, Parking or any code, with widths), by chainage range, with linear width changes between ranges; standard sections R4-R9, U5 and U6 from RDM 1.3 Tables 4.23 / 4.24. It produces the same edge table a corridor gives, so signs, clearances, markings, barriers, calming, bays and junctions use it unchanged, and the `RFD road edges` layer carries it for snapping (ETW dashed: assumed). Stored with the project.
- Embankment barriers without a corridor: a simplified section (crossfall, verge fall, hinge at the outer edge, fill or cut batter to the existing ground level at the centreline) gives the fill heights; the report notes that edges and fills are assumed.
- A corridor and a typical section side by side: tick **Use it even where the LandXML has a corridor** to use the section; applying it lists where the corridor's ETW / EPS differ from it by more than 0.3 m.
- **Feature lines for Civil 3D** (Section tab): the road edges and the widened edges of bays, climbing lanes and junctions as 3D feature lines in a LandXML (`PlanFeatures`, site `RFD`, Northing Easting Elevation), to import into Civil 3D and use as corridor targets. Levels from the design profile and the section: the corridor's (superelevation included) or the typical section's coded points (crown crossfall; superelevation not applied, noted in the file); beyond the pavement edge a widening carries the last crossfall on. The source file's Units and CoordinateSystem are copied.
- **Side roads** (Section tab): the LandXML's other alignments without a corridor get a standard section, so a junction where our road joins one sits at its edge (3.5 m was assumed).
- Typical sections saved to and loaded from a file, for use in other projects.
- When a project with a typical section is reopened and the LandXML now has a corridor, the corridor is used and the differences from the section are listed.
- Edges from a typical section are dashed on the plan sheets and go to `RSD-EDGE-TS-<code>` layers in the DXF.
- User guide: the Section tab (section 5), with a figure.

## 0.9.0 — 2026-11-13

### Changed
- **QGIS 3.34 or later** is needed (was 3.28).
- **Markings look as painted**: broken lines are dashed at their real mark and gap in metres (rural or urban by speed) on the map and the plan sheets, instead of a screen dash that read as dots; double lines and the combined line show both lines (kept apart on screen at any scale), the CLS's continuous side following "flip".
- **Climbing lanes over the speed profile**: the proposal follows the trucks along the design profile, vertical curves included, so consecutive steep grades count together, and close lanes are joined.
- Bays, climbing lanes and the widening round trip use the corridor's carriageway edge whatever it is coded (ETW, EOP, EP, EOTW, EdgeOfPavement, Edge).
- Junctions: where our road joins or crosses another alignment, the kit faces the leg of our road on the mouse's side, and the preview flips as the mouse moves across the main road. The hover text names the leg. **Both legs** (Junctions tab) places a crossroads: islands, Give Way markings and an R2 on each approach, with the main-road pieces drawn once.
- Junctions on our road: the minor road's direction follows another alignment of the LandXML when the mouse is within 15 m of it, so it doesn't have to be aimed by hand.
- Calming tab: **Bar markings on the approaches** sits under the feature type. The placement message says how many bar sets went in, or how to switch them on.
- Raised crossings have their own item, `TABLE-X` (Raised pedestrian crossing), with its own legend entry and fill, so they are counted apart from speed tables. Raised crossings placed before keep the `TABLE` code and are still reported as raised crossings.
- Where a bus bay, truck parking bay or climbing lane widens the road, our road's edge line and edge studs on that side are cut from the start of the entry taper to the end of the exit taper (its own lines take over), on placing it and on every markings proposal, as at roundabouts.
- The pre-3.34 enum fallbacks are gone (`compat.py` uses the scoped enums, and `compat.prop()` for the symbol layer property keys, scoped only from QGIS 3.36), and CI runs the QGIS tests on 3.34 as well as 3.44.
- CI: `actions/upload-artifact` and `download-artifact` v6 (Node.js 24).
- Map tools belong to their tab. Leaving the Linear, Calming or Junctions tab switches its tool off. The hover read-out starts with what a click places (`Linear - BM03:` / `Calming - Circular road hump:`), and the Calming tool has its own cursor.

### Added
- **Signalised crossroads** (new type SIG, outside the RDM 1.3 templates; RDM 6.1 7.8, Figure 7.12): four arms of single carriageways without islands — kerb returns (R 12 m) on all corners, a BM02 crossing on every arm where the kerb runs straight, the TM01 stop line 1.5 m behind it across the approach half, 30 m of LM24 and an AM07 arrow on each approach; W46 Traffic Signals Ahead proposed on our approaches. Signals, lanes and phasing stay with the signals design.
- **Junction Ahead warning signs** (RDM 6.2 4.2) proposed with every junction kit: W2 Side Road on both approaches where our road is the main road (mirrored to the side road's side), W1 Crossroads where side roads leave on both sides within 10 m, W5 Staggered Crossroads within 60 m, and W12 / W11 on our approach where our road meets a road of greater importance. Re-proposed together when a junction is placed, moved or removed; accepted ones are kept.
- **Arrow markings at junctions** (RDM 6.1 6.4.3, Table A.5): AM06 (AM07 at a crossroads) on the minor approach, AM03 right-turn arrows in the right-turn lane of A-1 and B-Mod kits, 3.5 / 5 / 9 m by speed (Table 6.1); painted area from the outline, solid hatches in the DXF.
- **Minor road approach visibility splay** (RDM 1.3 Figure 9.13) where our road is the minor road: drawn with the splays, checked against the obstruction layers, and reported with how far it reaches inside a bend.
- **Roundabout entry path radius** (RDM 1.3 10.6.3.5): checked at every entry on a simplified fastest ahead path, against 100 m (70 m at compact urban roundabouts).
- **BUS STOP word marking** in bus bays (RDM 6.1 10.3), in each 15 m box, letters by speed (Table 6.2).
- **Move a piece** (Junctions tab): move a placed junction piece, or with Shift the whole junction, along the road; it is rebuilt from its template there.
- Kerb returns in the guide lines are three-centred curves, R1 : R2 : R3 = 2 : 1 : 3 (RDM 1.3 Figure 9.25).
- Bus bay kerbs are split into raised (platform and ramps) and flush (tapers) in the Junctions and Widenings sheets.
- Climbing lanes draw their widened pavement edge with the 100 m tapers (`BAYEDGE`, as for truck parking bays), with its length in the quantities.
- A hump's or table's approach bar sets are left out where they would fall on a junction kit, a roundabout, an access, a crossing or another hump, with a note for each. Placing a junction over proposed bar sets removes them.
- Overlap checks: a hump, table, bump or zebra that overlaps another one, or a junction or roundabout, is flagged on placing it and in the furniture checks ("Transverse items overlapping"). A bar set on a junction is a check there.
- User guide 0.9.0: islands with their widenings, the signalised crossroads (new figure), Junction Ahead signs and arrows, bar markings per approach and raised crossings; the A-1 figure redrawn with the widened main road.

### Fixed
- Joining a road given by its clicked direction (Olkaria trial): a click a few metres into our road could take the stub behind it as the leg and build the kit off the end of our road. A click within 30 m of our road's end now snaps to the end, a stub under 30 m is never a leg, and where the alignment runs on past the junction the longer leg (our road) is taken, not the tail.
- Climbing lanes were proposed along most of a rolling road: the truck's speed loss now stops at its crawl speed, ground of 3 % or less gives the allowance back, and each lane ends 200 m past its climb.
- Calming tab: **Bar markings** is one list (Both approaches / Forward / Backward / None), so humps can go in without bar sets.
- **Islands no longer narrow the existing lanes** (Edmond's trial): every island comes with its widening, as on the standard drawings. Ghost-island kits (A-1, B-Mod) widen the main road on both sides by half the island's width (new piece `main_widening`, drawn as `WIDEN`), and their other pieces stand off the widened edge; corner islands (A-1, A-2, B) get a bellmouth behind them with the turning roadway (4.9 m; 5.5 m W2 in A-2) and the kerb return drawn from it; the minor road flares around its splitter. The widenings on our road go to the Widenings sheet for Civil 3D and into the round-trip check.
- The Excel Junctions sheet was written with the Widenings rows when the project had a bus or truck bay.
- B-Mod no longer gets right-turn arrows (they sat on its hatched wedge).
- Climbing lanes showed only their I1 / I2 signs: the map style had no symbol for their LM26 / LM03 lines, so they were not drawn. Every template code now has a symbol, and a project saved with the old style gets the missing ones when reopened.
- A zebra placed from the Linear tab came out as a hump when the Calming tab's tool had been left on.
- QGIS 3.34: closing or clearing a project could crash QGIS (the sign symbol's layers were freed twice); the plugin also failed to load on 3.34 (symbol layer property keys).

## 0.8.0 — 2026-11-12

### Added
- **Roundabouts** (RDM 1.3 Chapter 10, RDM 6.1 Figures 7.14-7.16), type RBT: centre on our road; arms from our road and other alignments crossing the circle, plus clicked arms (right-click / Enter to place). Central island, outer kerb with entry / exit returns, kerbed splitter islands with hatched lead-ins, TM07 + BM07 on entries, TM04 on exits, LM24; R2, M5, W24 chevrons and W17 proposed. Checks: 3-5 arms at least 60 deg apart, island at least 4 m, ICD at least the Table 10.1 minimum and not over 100 m, circulatory width 6.5-15 m, crossing returns, compact-roundabout hint, entry visible from the SSD over the profile.
- Our road's markings and studs are cut back at a roundabout (centre lines beyond the splitter lead-in, edge lines and studs at the end of the flare), on placing it and on every markings proposal.
- Checks: control at our road's end where it starts or ends on another alignment (a junction or an R1 / R2 within 60 m); bus and truck bay entries seen from the stopping sight distance (RDM 1.3 13.2).
- **Supplementary signs from the standard drawings WSCM/84/2/01** (Jan 2024): 19 signs with no RDM 6.2 equivalent, coded `WSCM-` so they never collide with RDM numbers (catalogue now 270 signs). `tools/extract_wscm_signs.py`, `rfd/data/wscm_signs.json`, and `rfd/data/wscm_crossref.json` mapping all 75 WSCM codes to RDM 6.2. WSCM-M14 (End of All Prohibitions) ends speed limits, no-overtaking zones and clearways in the pairing checks; WSCM-M9 is ended by WSCM-M8 or M14. The furniture checks list the WSCM signs used.
- **Junction islands and markings as templates** (Junctions tab) from RDM/1/3/2/01-02: kits for types A-1, A-2, B, B-Mod and C, or single pieces, placed with two clicks (junction point, then a point up the minor road) so they take the skew; optional scale; guide lines (edges, kerb returns, Rc arcs) for sketching. Layer `rsd_junctions`, open data `rfd/data/junction_templates.json`, report schedule and Excel sheet, crossing angle check (RDM 1.3 9.2.3), plan sheets and DXF layers `RSD-JN-*`.
- **Our road joining another road** (Junctions tab): the main road is another alignment of the LandXML or a clicked direction; markings on our approach, R2 Give Way proposed (kept when auto-placement is re-run, removed with the junction).
- **Crossings and humps drawn as painted**: zebra bars, bar sets, BM04 triangles and filled hump footprints on the map, plan sheets and DXF; transverse items go in with one click from the Linear tab.
- **Bus bays** (RDM/1/3/3/01) placed with two clicks: tapers in the direction of travel, kerb, platform, separation line, shelter position and Bus Stop sign; 60 m spacing check for opposite bays.
- **Climbing lanes** (RDM 1.3 6.6, RDM/1/3/3/02): proposed from the profile against Table 6.6 (with the AADT rule) or placed by two clicks; 100 m tapers, lane width per 6.6.3, LM26 / LM03 lines, WSCM-I1 / I2 signs.
- **Truck parking bays** (RDM/1/3/3/03) placed with two clicks: straight 15 m entry and 10 m exit tapers, 3.5 m deep, widened pavement edge and LM05 separation line; I15 at the entry taper and I14 300 m ahead proposed (RDM 6.2 6.4.1.1); checks for a bay under 70 m (four to five heavy vehicles) and bays over 30 km apart (RDM 1.3 13.2).
- **Visibility splays at junctions** (RDM 1.3 9.5.4): every junction kit draws the approach / give way splays (20 m back, Table 9.7) and the stop splays (3 m back, Table 9.8) on both sides, at the main road's design speed (from its alignment, typed, or 80 km/h assumed and flagged). Checked on the main road's profile (eye 1.05 m, vehicle 0.6 m, Table 3.13) and against QGIS layers the designer ticks (buildings, trees, fences ...): obstructions in a stop splay are issues, in an approach splay checks; the report re-runs the check. Tables in the criteria file (`junction_sight`); DXF layers `RSD-JN-SPLAY-A` / `-S`.
- **Private accesses** (RDM 1.3 9.11.16, Figure 9.33), type ACCESS: two clicks; returns (6 m default) from the shoulder edge, paved width (3 m default) with 0.5 m shoulders back to the boundary (10 m default) and a 3 m taper, an indicative pipe across the mouth, stop splays. Checks: width under 3 m, radius under 6 m, under 10 m to the boundary, and private accesses on class A / B / UA / UC roads (RDM 1.3 Tables 2.3-2.4).
- **Round trip with Civil 3D**: after the LandXML is exported again with the widenings built, the furniture checks compare each bus bay, truck bay and climbing lane with the corridor's ETW at every section inside it (not in the corridor yet / matches within 0.3 m / differs, with the worst section). Bays and lanes now build from the edge before the widening, so a widened corridor does not widen them twice.
- Excel sheet **Widenings**: the widening table for Civil 3D (bus bays, truck parking bays and climbing lanes).
- **Crossing extent and refuges**: crossings run between the ETW edges or between two clicked kerbs; a refuge / median width splits them into two zebras with a kerbed refuge island (new item `REFUGE`), with leg-length and refuge-width checks.
- **Installable plugin ZIP from CI** (`.github/workflows/plugin-zip.yml`): built, checked (`tools/check_plugin_zip.py`), installed into QGIS 3.44 and loaded on every push; attached to a draft release for `v*` tags. The README explains where to download it.
- User guide: Junctions tab, supplementary signs, installing from the plugin ZIP; minor-road junctions, bus bays, climbing lanes, the Widenings table and crossing extent and refuges (section 16 renamed "Junctions, bus bays and climbing lanes").
- Crossings: a refuge on a crossing of 10.5 m or less is flagged as not needed, with the lane widths it leaves (on a single carriageway it only narrows the lanes).
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
- **Faster sign placement**: auto-placement and other batches of signs are written in one edit session and committed once (850 signs on a 36 km road: about 16 s down to 2 s); post numbers are counted on and the nearest post is found by a box query instead of scanning the layer.
- **Faster DXF export**: the 8 MB sign-block library is read once per session, and the drawing extents use the sign insertion points instead of every block's geometry.
- Fields are created through QMetaType on QGIS 3.38+ (the QVariant constructor is deprecated); the QGIS test run went from about 4,700 warnings to one (GDAL's).
- Housekeeping: unused imports and variables removed; an unclosed file in a test.
- The report is the **Road furniture report**; the plan sheets are road furniture plans.
- The end of a no-overtaking zone is P32 with the END plate instead of an END legend on the P32 (the legend never showed on the face). Older projects' END legends still count as ends in the checks.

### Fixed
- The control-at-the-road's-end check took the same road carrying on (another alignment starting where ours ends, in line) for a junction.
- Installing from GitHub's "Download ZIP" failed (`ModuleNotFoundError`): that is the source repository; the README and guide now point to the plugin ZIP.
- The dock needed at least 1166 x 1048 px, so its bottom buttons were out of reach on a 1080p screen, and it disappeared when a neighbouring panel was resized. Every tab now scrolls and shrinks to a 380 px panel, and the toolbar button only reacts to clicks (show, bring to front, re-dock).
- WSCM sign artwork: no seams in the colour fills; closed frames on WSCM-I1 and I2 (drafting slips on the sheet).
- Core tests pass flat sequences to `pytest.approx` (pytest 9).
- The Linear tab was still wider than a 380 px dock on QGIS 3.44 (CI failure): the two group titles and two checkbox captions are shortened, with the full wording kept as the tooltip.
- LM05 (bay separation line) is 0.2 m wide (RDM 6.1 Table 4.1); bus bays counted half its painted area.
- The dock-width test uses a fixed font (DejaVu Sans 9), installed in the QGIS CI image, so it no longer depends on the machine's default font.
- CI uses `actions/checkout@v5` and `actions/setup-python@v6` (Node.js 24).
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
