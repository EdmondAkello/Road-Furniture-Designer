# Road Furniture Designer (RFD)

[![tests](https://github.com/EdmondAkello/Road-Furniture-Designer/actions/workflows/tests.yml/badge.svg)](https://github.com/EdmondAkello/Road-Furniture-Designer/actions/workflows/tests.yml) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24162212.svg)](https://doi.org/10.5281/zenodo.24162212)

A QGIS plugin for designing road furniture along a Civil 3D LandXML alignment to the Kenya Road Design Manual (2025): traffic signs, road markings and studs, safety barriers, traffic calming, pedestrian crossings, speed limit zones, junction islands and markings with visibility splays, roundabouts, private accesses, bus and truck bays and climbing lanes. Written by **Edmond Akello**. Licensed under GPL-2.0-or-later. **Experimental:** treat its proposals as a first draft for an engineer to review.

The **[User Guide and Technical Manual](docs/user-guide/user-guide.html)** for version **0.9.0** covers installation, every tab, the report and its checks, and the methods, with figures from a synthetic demonstration road. A [PDF edition (0.9.0)](docs/user-guide/Road_Furniture_Designer_0.9.0_User_Guide.pdf) is included. Source and figure scripts are in `tools/guide`.

```
 Civil 3D LandXML ─► QGIS: signs, markings, barriers, calming, speed zones, junctions, roundabouts, bays (by hand or proposed)
                       ─► rsd_signs / rsd_lines (GeoPackage) ─► live inventory and checks (dock)
                       ─► Inventory (Excel Tables + CSV) ─► QTO / Bill
                       ─► Road furniture report (PDF / PNG / Excel): plans, long sections, strip diagram, schedules, checks
                       ─► Georeferenced DXF ─► COPYBASE 0,0 + PASTEORIG into the project DWG
```

For every item, the tool works out the chainage, offset, side and facing from the alignment and recomputes them whenever it moves. What the alignment decides (curve and grade warnings, no-overtaking signs and lines, edge lines, studs, embankment barriers) is proposed from the manuals; where a hump, a crossing, a speed limit, a junction, a roundabout or a bay goes is the designer's decision, and RFD details, signs and checks it. Everything can also be placed or drawn by hand.

**Input quality.** The results are only as good as the Civil 3D model and the LandXML export. Before relying on them, check these in Civil 3D, then confirm the LandXML export includes them. Without them the tool falls back to defaults:
- **Design speeds** defined along the alignment; otherwise 80 km/h is assumed throughout.
- **Superelevation** applied to the alignment; otherwise curve speeds use 4 %.
- **Final design profile** attached to the alignment; otherwise there are no grade, crest, sag or no-overtaking checks.
- **Corridor with coded points and cross-sections**, with the existing ground, sampled along the whole road; otherwise signs are offset from the centreline, edge lines need a carriageway width, and barriers cannot be proposed.

The dock's project summary shows which of these were found.

## Compatibility and validation

- **QGIS 3.34+:** 326 core tests pass, including randomly generated roads run through signs and markings (60), embankments and barriers (40), traffic calming (30), speed limit zones (30) and the report checks (30), and a check that refuses LandXML files declaring a DOCTYPE or entities. 58 headless QGIS tests pass on QGIS 3.34 and 3.44 (offscreen). Bandit passes. Nine alignments from private Civil 3D exports (Arc 1960 / UTM 36S and 37S; up to 59 MB with TIN surfaces and corridor sections, loading in about 0.6 s; project names withheld) were run through signs, markings, barriers, features, speed zones, the report (up to 97 pages for a 36 km road in about 2 s), the inventory and the DXF with no failures, and RFD's own proposals pass its furniture checks. Junctions, accesses, bays, climbing lanes and roundabouts were placed on three of them and run through the report, inventory and DXF. Auto-placement of 850 signs on a 36 km road takes about 2 s. `tools/sweep_landxml.py <folder>` runs the same invariants over your own files.
- **Civil 3D:** the georeferenced DXF pasted with COPYBASE 0,0 and PASTEORIG lands on the alignment in a project drawing. The Dynamo route is parked (kept in `dynamo/`, not run in Civil 3D).
- **Catalogue:** RDM 6.2 (2025), 251 signs with codes, names and artwork taken from the manual's figures, plus 19 supplementary signs from the Ministry's standard drawings WSCM/84/2/01 (see "Sign catalogue" and "Supplementary signs"). Post and foundation types are generic and project-defined.

## Sign catalogue (RDM 6.2, 2025)

`tools/extract_rdm_signs.py` reads the manual and does three things:
- Matches every "Figure x.y …, Sign CODE" caption to its framed artwork.
- Keeps only the sign itself, dropping dimension lines and notes.
- Writes a vector SVG icon per sign, plus a colour CAD block library (`rfd/data/RSD_SignBlocks.dxf`, hatched faces, one block `RSD_<code>` per sign).

`tools/build_catalogue.py` then adds the sizing and legend rules. Re-run both when a new edition of the manual comes out.

**Coverage:** R, M, P, W, I, E, PD, IM and RW signs.
- W24 chevrons are split into W24-a (single), W24-b (single, large), W24-c (double) and W24-d (triple).
- Signs the manual shows one way round but which are used both ways (bends, side roads, chevrons and so on) have a **mirrored** version (`_M` icon and block).
- A few figures whose list-of-figures entry the parser cannot read are added explicitly (`LOF_EXTRA`): P22 Pedestrianised Street, IM16–IM18 countdown markers, RW41 End of Construction.
- **END** is the supplementary plate "END" that ends a restriction with its own sign: P32 + END ends a no-overtaking zone (RDM 6.2 3.11), P14 + END a clearway (3.6). The manual gives the plate no code; its artwork is the identical END plate of Figure 10.43 (RW41). `build_catalogue.py` derives it (`DERIVED`).
- Still without artwork (design drawings or layouts only): I1-C, I2-b, I5-a, IM7, IM14, IM15, IM20, IM28.
- RDM 6.2 has no pedestrian-crossing information sign and no bus-stop sign; crossings are signed with W55 and the zebra marking.

**Numbering clashes in the manual itself.** These are resolved as follows and noted in the catalogue:
- Fig 7.1 is captioned P1, which clashes with No Entry, so it becomes PD1.
- I10 is used for both Tourist Facility and County Boundary, so County Boundary becomes I10B.
- IM4 is used twice, so the expressway symbol becomes IM4S.
- The directional examples "incorporating the X symbol" become I20-D, I21-D and I22-D.

The Ministry's standard drawings WSCM/84/2/01 (Jan 2024) use a **different numbering** (W1 = Sharp left turn there, Crossroads in RDM 6.2). RFD uses RDM 6.2 codes on drawings and schedules.

### Supplementary signs (WSCM/84/2/01)

Signs on the standard drawings with no RDM 6.2 equivalent are in the catalogue group **Supplementary (WSCM)**, always with a `WSCM-` prefix so they can never be read as an RDM code (WSCM W22 is River Bed Crossing; RDM W22 is a series of bends):
- Information: WSCM-I1 / I2 Start / End of Climbing Lane, I3 Bus Stop, I6 Hotel or Motel, I10 One Way Traffic
- Regulatory: WSCM-M2 Road Closed, M3 No Entry for Pedestrians, M8 End of No Overtaking Section, M9 Overtaking of Goods Vehicles Prohibited, M14 End of All Prohibitions, M16 / M17 length and distance-apart restrictions
- Warning: WSCM-W22 River Bed Crossing (Drift), W25 Cyclists, W34 Hazard Ahead, W37 Loose Stones, W39 Soft Verges, W42 / W43 Railway Crossing crosses

`tools/extract_wscm_signs.py` extracts them from the two sheets. W22 is drawn with the red border of the other warning signs (the sheet hatches its border black, a drafting slip). `rfd/data/wscm_crossref.json` maps all 75 WSCM codes to RDM 6.2 (same, similar or none). In the checks, WSCM-M14 ends a speed limit, a no-overtaking zone and a clearway; WSCM-M8 or M14 ends WSCM-M9. The furniture checks list every WSCM sign used, so a reviewer sees which signs are outside RDM 6.2.

**Sizes.** RDM 2.9 allows 600, 750 or 900 mm, and 1200 mm on expressways. For Stop and Give Way (Tables 3.1 and 3.3), warning signs (Table 4.1) and circular regulatory signs, choose **Auto**. The size then follows the design speed at the sign's chainage, taken from the Civil 3D SpeedStation data in the LandXML, and is recomputed if the sign is moved. The design speed stands in for the manual's 85th-percentile approach speed. Typing a size by hand turns Auto off for that sign. Plates and information signs are "custom" (designed size).

## Legends (destinations, plate text)

Directional signs, town and county signs, and text plates carry text that changes from job to job. Type it in the **Legend** box before placing, or select the sign on the Signs tab and use **Edit legend…**.

```
< Nakuru A104 18        left, route A104, 18 km
> Eldoret A104 140      right
^ Molo 1                 ahead (route and km are optional)
```

- **Directional faces:** drawn in the RDM Table 2.6 colour scheme for the chosen class:
  - Class A, B and UA: green background with yellow route numbers.
  - Class C, D, UC, E–W and UL: white background.
  - Expressway: blue background.
- **Destination order:** RDM 5.2 (ahead, then left, then right; furthest destination first).
- **Plates:** re-drawn with your text (W23 distance, W35 safe height, I7 town, P35/P38 information plates, …).

The legend goes into the inventory (`Legend` column), the Civil 3D package and the visible `LEGEND` block attribute. Generated faces are saved next to the GeoPackage in `<project>_faces/`. Signs that need a legend are flagged in Checks until one is entered.

## Install the QGIS plugin

Download the plugin ZIP, `road_furniture_designer-<version>.zip`:
- a release: the ZIP attached under **Assets** on the [Releases](https://github.com/EdmondAkello/Road-Furniture-Designer/releases) page
- the latest main: **Actions → plugin zip →** the newest run on `main` **→ Artifacts → road_furniture_designer-plugin** (GitHub delivers the artifact zipped once more: unzip that outer layer to get the plugin ZIP)

In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP** and choose that ZIP. Restart QGIS if you are replacing an older version.

Do **not** use GitHub's green **Code → Download ZIP**, or the **Source code (zip)** and **Source code (tar.gz)** links that GitHub adds under every release's Assets: they are the source repository, with the plugin two folders down and without its core and libraries, which `tools/build_plugin.py` copies in. QGIS fails on them with `ModuleNotFoundError: No module named 'Road-Furniture-Designer-...'`. To build the ZIP yourself: `python tools/build_plugin.py road_furniture_designer.zip`, then `python tools/check_plugin_zip.py road_furniture_designer.zip`.

No pip is needed. The export libraries are bundled in the plugin's `ext_libs` folder as pure Python (openpyxl, ezdxf, fontTools, pyparsing, typing_extensions, et_xmlfile). If QGIS's own Python already has any of them, those copies are used instead.

## Auto-placement (Auto tab)

**Propose signs** reads the alignment, superelevation, design speeds, profile and corridor edges, and adds the signs the rules call for as **proposed** signs. They show with an orange ring on the map and the report. Review them, move or delete any you disagree with, then **Accept all proposals**. Proposals are left out of the inventory and the Civil 3D export until they are accepted. Re-running replaces the open proposals and never duplicates a sign that is already there.

| Rule | Trigger | Signs | Source |
|---|---|---|---|
| Curves | curve speed below the design speed by ≥ 10 km/h. Curve speed from V² = 127 R (e + f), with e from the LandXML superelevation | W20 bend, or W19 sharp turn if ≥ 30 km/h below. Placed 6 s of travel ahead, both directions, mirrored for left/right | RDM 6.2 4.5, 2.4 |
| Curve series | warned curves within 150 m of each other | W22 / W21 plus a W23 distance plate ("FOR 350 M") | RDM 6.2 4.5 |
| Chevrons | curve speed ≥ 20 km/h below design | W24-a on the outside of the curve, back to back for both directions, spaced per Table 4.2 | RDM 6.2 4.6.1 |
| Steep grades | descent > 5 %, ascent > 10 % | W30 / W31 with the actual grade as the legend | RDM 6.2 4.6.4 |
| No overtaking | crest sight distance < passing sight distance | P32 plus a W23 distance plate at the start; P32 with the END plate at the end; for each direction | RDM 6.2 3.11 |

**Placement rules:**
- Posts go 1.0 m beyond the paved-shoulder edge (adjustable; RDM 2.4 allows 0.6–3.0 m).
- Signs are kept at least 0.6 × V m apart; a crowded sign is moved back from the hazard.

**Report-only findings** (no sign is proposed):
- sags short of headlight sight distance
- crests short of stopping sight distance

**Thresholds and defaults:** every threshold is on the Auto tab. Side friction, stopping and passing sight distance and the crest/sag K values come from RDM 1.3 (2025) Tables 5.1, 3.13, 3.16, 3.20, 6.1 and 6.4 (criteria set `kenya_rdm_2025`, eye 1.05 m, object 0.20 m, overtaking target 1.3 m). No-overtaking uses the reduced PSD (325 m at 80 km/h). The older AASHTO 2011 values remain available as criteria set `aashto_2011`. Other manuals (AASHTO editions, Tanzania, project-specific values) can be added as criteria files without code changes; see [docs/criteria](docs/criteria/README.md). RDM 6.2 leaves sharp turn versus bend to the Engineer's discretion; the speed-drop margins are that judgement, made explicit.

## Linear furniture (Linear tab)

Road markings, road studs and barriers are stored as **runs** in the `rsd_lines` layer. Each run has an item code, a start and end station, a side, and an offset. The offset is measured from a corridor edge (for example ETW) or from the centreline. A run follows its edge where the road widens. Its geometry, chainage, length and quantity are rebuilt whenever one of those fields changes, so you can edit runs in the attribute table.

- **Catalogue** (`rfd/data/furniture_linear.json`): RDM 6.1 line codes with mark, gap and width per Tables 4.1–4.3 (rural at 80 km/h and above, urban below). LM01/LM02 centre, LM03/LM04 lane, LM07 broken edge, LM24/LM25 continuous centre, LM26/LM27 edge, LM28 combined line (CLS), LM30/LM32 double lines. Road studs at the Table 13.2 intervals (12 m normal, 9 m no-overtaking) and at 6 m on the combined line system (section 4.5.1). W-beam guardrail with end terminals. Add or replace items with your own JSON file in a folder listed in `RFD_FURNITURE_PATH`.
- **Quantities:** markings in metres of run and m² painted, studs by number, barriers in metres plus 2 terminals per run. The inventory gains a `Linear` sheet (Excel Table `RSD_Linear`), and its rows feed `RSD_Quantities` through SUMIFS formulas.
- **DXF:** runs are drawn in world coordinates on `RSD-MARK-*`, `RSD-STUD-*` and `RSD-BARRIER-*` layers. Broken lines use metre linetypes (e.g. `RSD_3_9`), and markings are drawn at their painted width. Each entity carries `RSD` XDATA (run UUID, code, stations).
- **Propose markings (RDM 6.1):** the Linear tab proposes the centre line, edge lines and studs for review, in the same proposed/accept/remove way as signs.
  - *Centre line:* broken (LM01, or LM02 on class A/B) where overtaking is allowed. A direction that may not overtake gets a continuous line: the combined line LM28 for one direction, double continuous LM32 for both.
  - *One basis for signs and markings:* the geometric criteria govern. The continuous line covers exactly the no-overtaking zones used for the P32 signs: where the passing sight distance (RDM 1.3 Table 3.20) is not available along the profile and, if "Sight obstruction on bends" is set on the Auto tab, round bends. Zones of opposite directions closer than 100 m are extended to meet, so no short overtaking length is left between them. The RDM 6.1 Table 4.4 critical value gives far shorter zones than the passing sight distance; it remains in the core as `basis="table_4_4"` but is not the default.
  - *Narrow roads:* under 5.5 m of carriageway there is no broken centre line and no double line; a single continuous line LM24 is used where overtaking is prohibited (4.2.1, 4.5.5).
  - *Edge lines:* continuous LM26 (LM27 on class A/B) on the ETW edge, both sides. Where the LandXML has no corridor, give a carriageway width and they are placed at half that width from the centreline.
  - *Studs:* 6 m on the combined line system (4.5.1), 9 m on edge lines through no-overtaking sections and 12 m elsewhere (Table 13.2). By default studs go everywhere on class A and only on no-overtaking sections otherwise.
  - *Not covered yet:* breaks through junctions, splayed and hatched double lines on sharp bends (Figure 4.6), lane lines on multi-lane roads.
- **Propose barriers (RDM 1.3 Chapter 12):** embankment barriers from the corridor sections, proposed for review like markings.
  - *Fill height and batter,* per section and side, as in the LandXML plugin's section views: the hinge (coded point, or where the design line first drops outward more steeply than 1:10), the toe where the design line meets original ground, height = hinge level − ground at the toe, batter 1:n = run / height. A toe drain, bench or wall therefore does not distort the height.
  - *Original ground,* in order: the section's own ground line (CrossSectSurf), a TIN surface in the LandXML sampled under the section (picked by name — OGL, EG, existing, terrain — or chosen in the dock), else the corridor's daylight point. The barrier's reason says which was used.
  - *Warrant:* the criteria's Fig 12.4 curve. Required → barrier; between the curves → listed for judgement (or proposed, if ticked).
  - *Length:* warranted length + Table 12.6 run-out at both ends, at the highest design speed along the hazard and its approaches; an end on a bend is carried to the tangent point first; at least 30 m; gaps under 80 m closed (12.6.14). Two terminals per run.
  - *Set-back:* 0.5 m from the ETW edge line, 0.75 m with AADT ≥ 12,000 and speed > 80 km/h (12.6.6). A verge narrower than set-back + post is flagged.
  - *Clear zone:* batters steeper than 1:3 starting inside the Table 12.1 clear zone and not shielded are listed as findings.
  - *Not covered:* roadside obstacles (Table 12.4), structures and parapets (on hold), median barriers, terminal flares.

## Drawing linear furniture by hand

Crossings, bar sets, hump markings and humps (transverse items) go in with **one click**, centred on the click and across the carriageway (from the ETW edges, else 7 m). The map, plan sheets and DXF draw them as they are painted: zebra bars of 500 mm with 500 mm gaps, the six bars of a bar set, BM04 triangles on the hump ramps, and humps, tables and bumps as a filled brick-red footprint. The **Calming** tab places a crossing or hump with its signs and bar markings in one click as well.

**Crossing length and refuges.** By default a crossing runs between the ETW edges at the click (or across the carriageway width given on the Linear tab, else 7 m). Tick **Crossing ends by two clicks** to click one kerb, then the other: the crossing runs exactly between them, for a dual carriageway, part of the road or a road without corridor edges. **Refuge / median** splits it into two zebras with a kerbed refuge island (`REFUGE`, 1 m longer than the zebra each side) between them: on the centreline when the crossing spans it, else in its middle. A leg over 10.5 m, or a refuge under 1.2 m, is flagged (RDM 6.1 9.2).

Every proposed run can be edited, and any run can be drawn by hand. This covers dual carriageways, slip roads, median edge lines, unusual corridors, and anything else the rules don't propose. On the Linear tab, pick the item and press **Draw on map**:
- Click the start, then click the end. The chainages come from the clicks.
- The side and offset come from the first click. With "Offset from" set to a corridor edge, the offset is measured from that edge and the run follows the edge where the road widens. Otherwise it is measured from the centreline.
- Tick **Fixed offset** to use a typed offset instead, for example 7.3 m right for the median edge of a dual carriageway.
- Choose Centre, Left or Right to force the side.
- **Add run at chainages** does the same from typed chainages.
- Right-click or Esc cancels a run you have started.

## Traffic calming and crossings (Calming tab)

You decide where humps and crossings go; RFD details them to the manuals. Pick a feature, then either click **Place on map** and click the chainage, or type the chainage and press **Add at chainage**. Each feature creates the following, all as proposals:
- **Circular hump:** radius and chord for the chosen crossing speed (RDM 6.4 Table 2.1, 100 mm rise), with the bus speed noted.
- **Trapezoidal hump:** ramp length and gradient (Table 2.2) and a 2.5 m minimum flat top.
- **Speed table:** 1.7 + 5.0 + 1.7 m (Figure 2.4). The raised pedestrian crossing version adds a zebra on the flat top.
- **Speed bump:** refused where the design speed is 50 km/h or more (2.4.2).
- **Hump markings** (BM04) on the hump.
- **Transverse bar markings** on the approaches: 1 to 4 sets of 6 × 300 mm bars at the Table 2.3 distances for the approach speed, with 600 mm or 1 m gaps. They are yellow on class A and B roads. Bar markings can also be placed on their own ahead of any hazard.
- **Zebra crossing:** BM01, BM02 or BM03 for a 2, 3 or 4 m crossing (RDM 6.1 9.2). A refuge island is flagged when the crossing is longer than 10.5 m.
- **Warning signs** on both approaches at the RDM 6.2 advance distance: W64 for humps and bumps, W55 for crossings.
- **Checks:** the feature should be visible from the stopping sight distance on the design profile. The bump speed limit, the crossing width, and items falling beyond the alignment are flagged.

Quantities are counted per item, with painted areas for bars and zebras. Everything a feature creates is listed and removed together, and the sign rules on the Auto tab leave feature signs alone. Bus bays, lay-bys, vulnerable-section zigzags, stop lines and kerb details are left to the designer.

## Speed limit zones (Speed limits tab)

The posted limit is your decision (built-up and special areas); RFD signs it to RDM 6.2 3.5. Pick the limit (P5 50, P6 70, P7 80 or P8 120 km/h; 100 km/h is the general limit and has no sign), type the zone's chainages and press **Add zone**. For each direction RFD proposes:
- the limit sign where traffic enters the zone
- a repeater at the middle, or at the interval you set
- **P9** (end of speed limit) where traffic leaves the zone. Where the zone adjoins another one, that zone's limit sign marks the change instead.

It flags a limit above the design speed, a very short zone, and a zone that runs off the alignment end (sign its start or end on the road beyond). **Propose from design speed** adds 50 km/h (built-up area) zones where the LandXML design speed is 50 km/h; a rural 70 or 80 km/h design speed does not by itself call for a special limit. Check each zone before accepting. A zone and its signs are listed and removed together, and the Auto tab's sign rules leave them alone.

## Junctions, roundabouts, accesses, bays and lanes (Junctions + bays tab)

RFD does not design junctions. The islands and markings of the standard drawings RDM/1/3/2/01 (type A) and RDM/1/3/2/02 (types B, C and D) are **templates you place and fit**, either as a whole kit for a junction type or piece by piece:

| Type | Kit |
|---|---|
| A-1 | ghost island tail (HM07 / HM14), raised splitter 7.5 x 3.0 m with hatched tail, corner island with white hatched lead-in |
| A-2 | raised teardrop splitter (about 25 m), corner islands on both corners |
| B | teardrop splitter (R 0.75), corner island on the left-turn corner |
| B-Mod | hatched strip ahead of the right-turn lane, hatched wedge beyond the junction, teardrop splitter |
| C | teardrop splitter, 10 + 10 m |

Every kit also has the GIVE WAY line across the approach lane (TM07), the triangular GIVE WAY marking 2.5 m back (BM07) and 30 m of continuous centre line on the minor road (LM24), to RDM 6.1 5.3. The sheet titled "types B, C & D" labels no panel D (two panels read "Type B - Modified", drawn alike), so there is one B-Mod template and no D.

**Placing.** Pick the type and the kit or a piece, press **Place on map**, click the junction point on the main road (it snaps to the centreline), then move up the minor road: the pieces follow with the crossing angle shown, and a second click places them. Pieces on the main road follow its curvature; corner islands shear with the skew. Kenya drives on the left, so the approach lane, the left-turn corner and the ghost island tail fall on the right sides for a minor road on either side. **Scale** enlarges or shrinks the pieces about the junction point, before placing or for a selected junction.

**Our road joining another road.** Choose **Our road joins another road** and click our road where it meets the main road. Then either click a point along the main road (a straight main road in that direction), or pick the main road from the LandXML's other alignments, and the main-road pieces follow its curves. The give way line, triangle and centre line go on our approach, and an **R2 Give Way** sign is proposed on its left. It stays when auto-placement is re-run and is removed with the junction.

**Bus bays** (type **BUS**, RDM/1/3/3/01). Click where the bay starts on the side it serves, then where it ends. RFD adds the tapers before and after it in the direction of travel:
- entry taper A = 30 m (25 m where the design speed is 50 km/h or less), exit taper C = 18 m, 4.0 m deep, smooth reverse-curve tapers
- kerb line, the raised 1.0 m loading platform (hatched), the 1 m / 1 m separation line along the carriageway edge and an indicative shelter
- the Bus Stop sign (WSCM-I3) as a proposal

The Excel sheet **Widenings** is the widening table for Civil 3D: widening from, full width from and to, widening to, tapers and width. The checks flag bays serving opposite directions less than 60 m apart, centre to centre (drawing note 4).

**Climbing lanes** (type **CLIMB**, RDM 1.3 6.6, RDM/1/3/3/02).
- **Propose from the profile** finds up-grades longer than their RDM 1.3 Table 6.6 limit (4 % 900 m … 8 % 500 m; none at 3 % or less). It places a lane from where the limit is reached to 200 m past the end of the grade, on the uphill traffic's left.
- With an AADT (design year 10): none under 2000 pcu, "consider" for 2000–6000, "normally required" above.
- Or click the full-width start and end yourself.
- 100 m tapers. The lane is as wide as the adjacent through lane less 0.25 m where that is 3.25 m or more.
- Draws the new edge line (LM26) and the broken lane line (LM03), and proposes WSCM-I1 at the entry taper and WSCM-I2 where the exit taper starts.
- Lanes and bus bays share the Excel sheet **Widenings**, the widening table for Civil 3D.

**Guide lines** (on by default) are construction lines for sketching and fitting: the main-road edge, the minor road centreline and edges, the kerb returns (single-radius fillets, 30 m for A, 25 m for B, 15 m otherwise) and the Rc turning arcs (tangent to the main-road centreline through the splitter nose, Rc 15 m as recommended on RDM/1/3/2/01). They carry no quantities and sit on their own layer category and DXF layer (`RSD-JN-GUIDE`) so you can switch them off.

The pieces live in the layer `rsd_junctions` (one feature per piece and marking code, rule `junction:<id>`). Editing `sta`, `bearing_deg`, `scale` or `edge_m` in the attribute table rebuilds the piece. The templates are open data in `rfd/data/junction_templates.json`. The report lists each junction with its kerb length, island area and painted length and area per code (Excel sheet **Junctions**), and checks the crossing angle against RDM 1.3 9.2.3 (75-120 deg preferred, 60 deg minimum). Plan sheets and the DXF draw them (`RSD-JN-<code>` layers).

**Visibility splays** (RDM 1.3 9.5.4) come with every junction kit: the approach / give way triangles (20 m back, Table 9.7) and the stop triangles (3 m back, Table 9.8), at the main road's design speed. They are checked on the main road's profile and against QGIS layers you tick (buildings, trees, fences: **Check splays**); an obstruction in a stop splay is an issue.

**Truck parking bays** (type **TRUCK**, RDM/1/3/3/03): straight 15 m / 10 m tapers, 70 m bay, 3.5 m deep, separation line, I15 and I14 proposed; checks for length and 30 km spacing (RDM 1.3 13.2).

**Private accesses** (type **ACCESS**, RDM 1.3 9.11.16, Figure 9.33): returns from the shoulder edge, 3 m with shoulders, built 10 m back to the boundary with a taper, a pipe across the mouth, stop splays; checks for width, radius, length and private accesses on class A / B / UA / UC roads (Tables 2.3–2.4).

**Roundabouts** (type **RBT**, RDM 1.3 Chapter 10, RDM 6.1 Figures 7.14–7.16): click the centre on our road (its arms and those of other alignments are found), click any other arm, right-click to place. Island, outer kerb with returns, splitter islands, give way markings, R2 / M5 / W24 / W17 proposed; our road's markings are cut back; checks on arms, island, ICD (Table 10.1, ≤ 100 m), width and the entry over a crest.

**Round trip with Civil 3D.** Build the widenings from the Widenings table, export the LandXML again and press **Recompute all chainages**: bays and lanes keep their place (no double widening) and the report compares each with the corridor's ETW.

The full rules and figures are in section 16 of the User Guide.

## Corridor restriction

When the LandXML has corridor edges, **Keep inside the corridor** (Place tab, on by default) snaps every sign into RDM 2.4's band, 0.6–3.0 m beyond the reference edge. A sign is never placed past the corridor's outer limit (ditch or daylight). If the corridor stops at the shoulder, no outer limit applies.

The Checks list flags:
- signs outside that band
- signs outside the corridor
- signs on the shoulder or in the travelled way
- signs closer together than 0.6 × V

## Road furniture report

**Inventory → Road furniture report** asks for the plan scale (Auto, 1:500 to 1:5000, or no plan sheets) and the title-block names (Prepared by, Checked by, Approved by; kept with the project). It writes, next to each other:
- **PDF:** A3 landscape, every page in the same drawing frame: the plan layout sheets, one long-section sheet per kilometre, the sign schedule and the geometry findings, then the road furniture pages: the strip diagram, the markings, barrier and traffic calming schedules, the linear quantities and the furniture checks.
- **PNG:** one image per plan, long-section and strip sheet (`plan_NN_<chainage>.png`, `section_<chainage>.png`, `strip_<chainage>.png`).
- **Excel workbook:** Signs (including proposals and the reason for each), Findings, Horizontal curves (R, e, f, curve speed against design speed), Vertical curves (K, A, SSD), Markings, Barriers, Features, Furniture quantities, Furniture checks and Basis.

**Frame and title block.** Border, title and logo top right, and a title block with Project, Alignment, Drawing, Scale, Prepared / Checked / Approved by, Date and Sheet. No logo is drawn by default; to add one, set the QGIS setting `RoadFurnitureDesigner/report_logo` to an image file.

**Plan layout sheets.** Each sheet is turned so the road runs left to right and drawn at the chosen scale (Auto = 1:2500, or 1:1000 for roads under 1.2 km). Sheet lengths adapt so that tight curves still fit with room for the signs. Each sheet shows:
- the corridor edges (ETW, EPS, hinge, ditches, daylight) and the centreline with chainages
- the LandXML's other alignments (side and link roads), named
- every sign upright beside the road at 10 mm, with a leader to its post; a sign and its plate stack, back-to-back faces sit side by side, and symbols are moved clear of one another
- the markings, road studs, barriers, humps, bar sets and crossings in their line style and colour (proposed ones with an orange halo)
- match lines with the neighbouring sheet numbers, a north arrow and a scale bar
- underneath: the sheet's sign list and a key plan with the sheet highlighted.

**Long-section sheets** show:
- the signs for up-chainage traffic and for down-chainage traffic, on their own strips (code and post under each face, staggered so labels never overlap)
- the design profile, with existing ground where the LandXML has it
- shaded bands for steep grades, no-overtaking zones in each direction, headlight-limited sags and crests short of stopping sight distance
- crest and sag K-values
- a curvature band with each curve's radius and safe speed (warned curves flagged)
- the grades between PVIs.

Grade signs (W30/W31) and other signs whose artwork carries a value show the real value (e.g. 11 %), in the report and in the DXF.

**Strip diagram.** A straight-line diagram, 1 km per strip and three strips per page: signs for each direction, barriers, edge lines, the centre line (continuous, broken, or the combined line with the continuous line on the side it binds), road studs, calming features and crossings, speed limit zones, and the no-overtaking zones from the passing sight distance, so the signs and markings can be checked against them by eye.

**Furniture checks.** RFD works the following out again from the geometry when the report is made, with the project's settings, and compares it with what is in the project (Issue, Check or Info):
- every no-overtaking zone has a centre line that prohibits overtaking for that direction (the PSD governs)
- every barrier span the fill warrant asks for (with its run-out) has a barrier; barriers without a fill warrant are listed (fine for obstacles and structures RFD does not check); discretionary fills, clear-zone and verge notes
- signs the geometry asks for are in the project, signs facing the same traffic are 0.6 V apart, and proposals not yet accepted
- **every sign that opens a restriction is closed further on for the same traffic, and plates go with their signs** (`rfd/data/sign_pairs.json`, open: add files in `RFD_SIGN_PAIRS_PATH`): P32 → P32 + END and a W23 plate at the start; P5–P8 → P9 or the next limit; P14 → P14 + END; P17 → P18; P30 → P31; W27 → W28; IM12/IM13 → IM4/IM26; W21/W22 with a W23 plate; RW40 → RW40 + RW41; RW38 → RW39; RW30–RW34 → RW35. These apply to signs placed by hand as well as RFD's own.
- sag curves inside bends that limit the speed, and warned bends within the SSD beyond a crest
- calming features and crossings visible from the SSD; speed limits above the design speed.

The pages are drawn with QPainter, the same way the LandXML Road & Terrain plugin draws its exports.

## DXF for plan drawings

On **Export to Civil 3D**, choose the plan scale (1:500 to 1:5000; default 1:2500):
- **Symbols** print at 10 mm: 25 m in model space at 1:2500, 10 m at 1:1000.
- **Callouts.** Each sign is one block inserted at its post (true coordinates). The block holds a post marker, a leader and the sign face upright beside the road, clear of the carriageway and of the neighbouring signs, with the code underneath. A sign and its plate stack; back-to-back faces sit side by side.
- **Text** (codes, legends, chainages) prints at 1.8 mm. Chainage labels read the right way up on either side.
- **Text-bearing signs:** directional signs and plates get their own block with the real legend (coloured background, arrows, place names, route numbers, distances), drawn at 0.6 of the symbol size. Legend text uses the `RSD_LEGEND` style (Arial) so it fits its plate.
- **Reference geometry** (non-plotting): the alignment with chainages, every other alignment in the LandXML (`RSD-ALIGN-OTHER`), and the corridor edges on `RSD-EDGE-<code>` layers.

(Dynamo, when it is picked up again: symbol scale = the value shown after export, block source IN[4] = the exported DXF.)

## Georeferenced DXF: copy signs straight into a Civil 3D drawing

The exported DXF uses the LandXML's own world coordinates: easting and northing in metres, with no local origin, shift, scale or rotation. New projects default to the LandXML's coordinate system (e.g. EPSG:21037 Arc 1960 / UTM 37S), so the sign layer, the DXF and the Civil 3D drawing all agree. The DXF header records units (metres), angle convention (counter-clockwise from east), CRS, source LandXML and alignment (custom header variables `RSD_*`).

To bring the signs into the project DWG:
1. Open `*_placement.dxf` in Civil 3D.
2. Select the signs: `QSELECT` → Layer = `RSD-SIGN`, or isolate that layer.
3. Copy them with `COPYBASE`, using base point `0,0,0`.
4. Switch to the project drawing and run **`PASTEORIG`**. The signs land at their exact coordinates.

Alternatively, `INSERT` or `XREF` the whole DXF at `0,0,0`, scale 1, rotation 0.

Requirements for the target drawing:
- metres
- the same coordinate system
- World UCS when pasting

The reference alignment, the chainage ticks and an **RFD CHECK POINT** go on non-plotting layers (`RSD-ALIGN`, `RSD-REF-NOTES`). The check point is a cross at the alignment start, labelled with its own E/N. Paste it once to confirm everything lines up with the Civil 3D alignment, then delete it.

Pasted signs keep their attributes and their RFD identity (XDATA), so a later read-back still matches them to the sign list. On a real project export, every exported sign back-computes to its chainage and offset with zero difference, and the reference alignment starts exactly at the LandXML's first `<Start>` point.

## Road edges and vertical profile from the LandXML

When the LandXML includes Civil 3D corridor sections (`CrossSect` / `DesignCrossSectSurf`) or a design profile (`ProfAlign`), the new project picks them up automatically.

**Road edges.** Every coded corridor point becomes an edge line in the `RFD road edges` layer, with an offset that varies by station: ETW (edge of travelled way), EPS (edge of paved shoulder), Hinge, Ditch_In / Ditch_Out, Daylight. Pavement layer codes (`*_Base`, `*_Pave2`, …) and Crown are skipped. Daylight is drawn only where it exists (it isn't interpolated across gaps of more than 30 m).
- **Offset from:** on the Place tab, choose an edge here. With **Fix offset at 1.0 m**, every sign lands 1.0 m beyond that edge at the chainage you click, even where the road widens.
- **Hover readout:** shows the clearance from the edge and the grade, e.g. `Ch 1+150.00  6.00 m Left  (+1.00 m from EPS)  grade +2.5%`.
- **Stored on each sign:** its reference edge and its clearance from it, recomputed when the sign is moved. The default reference is EPS, or ETW if the file has no EPS.
- **Checks:** a sign inside the travelled way is an **error**; a sign on the shoulder is a **warning**.

**Vertical profile.** The `RFD vertical curves` layer marks every crest and sag at its PVI, labelled with its K-value and length (e.g. `Crest K=10 L=141`). Each sign stores the design grade at its chainage. Use these to place W30/W31 (steep descent/ascent), W41/W42 (sharp rise/dip) and no-overtaking signs.

The inventory gains the columns **Edge Ref**, **Clear of Edge (m)**, **Grade (%)** and **Design Speed (km/h)**, and the Civil 3D package carries the same values.

## Using it

1. **New project…**
   1. Pick the LandXML file and the alignment.
   2. Choose the CRS of the LandXML coordinates if the QGIS project doesn't already have a projected one.
   3. Save the RFD GeoPackage.
   The plugin adds the sign and linear furniture layers, the alignment, chainage ticks every 100 m, the road edges and the vertical curves.
2. **Place tab**
   1. Pick a sign from the palette (searchable) and choose its size.
   2. Size: *Auto (RDM, by design speed)* where the sign has a size rule. Tick **Mirrored** for the left/right version.
   3. Set **Facing**. *Auto* follows driving on the left: left-side signs face forward (up-chainage) traffic, right-side signs face backward. Pick Forward or Backward to override, e.g. for chevrons or a median.
   4. Optionally tick **Fix offset at** (e.g. 3.5 m). The sign then snaps to that offset at the chainage you click, on whichever side you click.
   5. Tick **Add to an existing post** and click on a sign to put another face on that same post.
   6. Fill in the **Legend** for directional signs and plates.
   7. Press **Place signs on map**. Hovering shows the live chainage and offset; left-click places a sign, right-click stops.
3. **Moving signs:** use QGIS's normal editing tools (Toggle Editing → Move Feature). Chainage, offset, side and auto-facing update immediately, and every face on the same post moves with it. Changing `facing` by hand in the attribute table switches Auto off for that sign.
4. **Signs tab:** every sign in chainage order. Double-click a row to zoom to it. **Renumber posts by chainage** turns the post refs into P001, P002… in road order.
5. **Inventory tab:** live counts of sign faces by type and size, posts by type and foundations by type, plus validation checks. It also holds the export and import buttons:
   - **Export inventory:** `*_Inventory.xlsx` and a CSV. The workbook contains the named Excel Tables `RSD_Signs` (one row per face with chainage), `RSD_Posts` and `RSD_Quantities` (counts), ready to link into the QTO. It has no rates.
   - **Export to Civil 3D:** `*_placement.json` plus a placed-signs `.dxf` for a quick check.
   - **Import Civil 3D read-back:** applies sign moves and rotations made in the drawing, matched by UUID.

The GeoPackage is the master record. Save the QGIS project and the plugin reopens the sign project with it.

## Civil 3D (2026+)

The working route is the georeferenced DXF (above). The Dynamo route below is **parked**: the scripts are kept for later and have not been run in Civil 3D.

- **Block library:** `rfd/data/RSD_SignBlocks.dxf` holds the RDM artwork as colour hatches, including `_M` mirrored blocks. Open it in Civil 3D and save it as DWG (or run `python -m rfd library RSD_SignBlocks.dxf` for a copy). Raster-only figures in the manual (a few information signs) become a labelled outline block.
- **Blocks:** each block is named `RSD_<code>`. The insertion point is the post, and local +Y points toward the traffic the sign faces. Each block carries attributes `SIGN_CODE`, `LEGEND`, `DESCRIPTION`, `SIZE`, `CHAINAGE`, `OFFSET`, `SIDE`, `FACING`, `POST_REF`, `FACE_UUID` and `INSTALL_UUID`. Its identity is also stored in XDATA (app `RSD`), and that copy is authoritative.

### First run in Civil 3D

1. Open **Manage → Visual Programming → Dynamo** and create a new graph.
2. Add a **Python Script** node and set its engine to CPython3 or PythonNet3. Add input ports up to IN[4] and paste in `dynamo/rsd_place.py`.
3. Wire up the inputs:
   - File Path → IN[0] (the placement JSON)
   - String → IN[1] (alignment name; leave blank to use the one in the package)
   - Number → IN[2] (symbol scale, e.g. 3)
   - Boolean → IN[3] (Run)
   - File Path → IN[4] (library DWG, optional)
4. Run with **Run = False** first and read the report:
   - **New / updated counts:** how many blocks would be inserted or moved.
   - **Missing blocks:** sign types with no block definition in the drawing.
   - **CHECK lines:** places where the drawing's alignment and the LandXML disagree by more than 20 mm. Resolve those before placing.
5. Set Run = True. Re-running is safe: signs are matched by UUID, existing blocks are updated, new ones are added, and nothing is deleted.
6. Mark the input nodes "Is Input" and save the graph, so the team can run it from Dynamo Player.
7. For read-back, build a second graph the same way with `dynamo/rsd_readback.py`. It has one input, the output JSON path. Import that JSON from the QGIS Inventory tab.

If the first run fails, open an issue with the error. The two places most likely to need adjusting are how the Python engine returns `ref` arguments from `Alignment.PointLocation`, and the internal-versus-displayed station when station equations are present.

## Command line (optional)

The command line covers working without QGIS, from an Excel sign list:

```
set PYTHONPATH=vendor\ext_libs        (or: python -m pip install openpyxl ezdxf)
python -m rfd template SignList.xlsx --alignment NAME
python -m rfd build SignList.xlsx road.xml --out outputs
python -m rfd reconcile SignList.xlsx readback.json road.xml
python -m rfd readback-dxf edited.dxf readback.json
python -m rfd library RSD_SignBlocks.dxf
```

## Conventions

- **Coordinates:** x = easting, y = northing. LandXML points are read as N E. The LandXML coordinates must be in the sign layer's CRS, which must be projected and in metres.
- **Offset:** positive to the **right** looking up-chainage (the Civil 3D convention). The inventory shows the offset as a positive number plus a side, L or R.
- **Stations:** the internal station is the geometric one (staStart + distance along). Displayed chainage applies station equations. QGIS stores both, so overlapping station equations can't put a sign at the wrong chainage.
- **Geometry supported:** lines, circular curves and clothoid spirals.

## Layout

```
rfd/                      core (stdlib; openpyxl/ezdxf only for exports)
  alignment.py            LandXML, station/offset both ways, station equations
  records.py              records -> validated faces & installations (shared by QGIS and Excel)
  catalogue.py, data/     catalogue.json (RDM 6.2 + WSCM supplementary), signs/ SVG icons, RSD_SignBlocks.dxf,
                          wscm_crossref.json, junction_templates.json
  junctions.py            junction islands and markings from templates: placement frames, pieces, quantities, guides
  legend.py               legend parsing, directional faces (RDM colour schemes), plates
  corridor.py, profile.py road edges from corridor codes, corridor clamp; vertical profile (grade, crests, sags, K)
  autoplace.py            RDM 6.2 rules -> proposed signs; geometry findings (curve speed, grades, sight distance)
  speedzones.py           speed limit zones (RDM 6.2 3.5): limit signs, repeaters, P9
  furniture_report.py     report schedules, strip lanes and the furniture checks (sign pairs: data/sign_pairs.json)
  inventory.py            Excel Tables + CSV for QTO
  plan_layout.py          where sign symbols go on a plan (callouts clear of the road and each other)
  package.py, dxf_out.py  Civil 3D package, placed DXF (georeferenced, callouts), block library, DXF read-back
  signlist.py, reconcile.py, cli.py   Excel route
qgis_plugin/road_furniture_designer/   plugin (store.py, linestore.py, junctionstore.py, maptool.py, dock.py, report.py, furniture_pages.py, plansheet.py, compat.py); core and vendor/ext_libs copied in by tools/build_plugin.py
vendor/ext_libs/          bundled pure-Python export libraries
dynamo/                   rsd_place.py, rsd_readback.py
  safe_xml.py             refuses LandXML files that declare a DOCTYPE or entities, before parsing
tools/                    extract_rdm_signs.py, extract_wscm_signs.py, build_catalogue.py, build_plugin.py, sweep_landxml.py
tools/guide/              make_guide_road.py (synthetic demonstration road), make_figures.py, user_guide.html, build_guide.sh
docs/user-guide/          user-guide.html, figures/, Road_Furniture_Designer_<version>_User_Guide.pdf
docs/criteria/            how to write a criteria file
tests/ (core), tests_qgis/ (run with QGIS Python, QT_QPA_PLATFORM=offscreen)
```

Build the plugin zip: `python tools/build_plugin.py road_furniture_designer.zip`

## Roadmap

Next releases:

- **0.10 Centreline-only mode**: work from a LandXML with only the alignment and its profiles (existing and design), with the carriageway, shoulder and other edges from a typical section the designer sets, so every tool snaps to them as to a corridor.
- **0.11 Descents**: descending lanes, brake check areas and truck escape ramps (horizontal layout for Civil 3D).
- **0.12 Interaction**: handles on placed items, a properties panel, snapping between items and undo.
- **0.13 Civil 3D geometry**: widenings and islands exported as Civil 3D-ready geometry.

Later:

- Markings at junctions (breaks, splayed and hatched double lines, RDM 6.1 Figure 4.6) and lane lines on multi-lane roads.
- Barriers for roadside obstacles (RDM 1.3 Table 12.4), median barriers and terminal flares.
- Junction signing (advance direction and direction signs per RDM Table A1-1); the Junction Ahead warnings (W1 / W2 / W5 / W11 / W12) are in.
- Roundabouts: full fastest-path construction (exit and circulating radii, R1 ≤ R2 ≤ R3), multi-lane entries.
- Dual carriageways.
- Dynamo route: parked.

## Install the development plugin

Run `python tools/build_plugin.py` from the repository root; it copies the core (`rfd`) and the bundled libraries into `qgis_plugin/road_furniture_designer`. Copy or link that folder into your QGIS profile's `python/plugins` folder (**Settings → User Profiles → Open Active Profile Folder**), restart QGIS and enable **Road Furniture Designer**. `python tools/build_plugin.py road_furniture_designer.zip` builds an installable ZIP.

To try it without project data: `python tools/guide/make_guide_road.py guide_road.xml` writes the synthetic demonstration road used for the guide (4.4 km, Arc 1960 / UTM 37S, with a profile, design speeds, superelevation and corridor sections).

## Tests

```sh
pip install -r requirements.txt pytest
python -m pytest -q tests                                  # core; no QGIS needed
python tools/build_plugin.py
QT_QPA_PLATFORM=offscreen python -m pytest -q tests_qgis   # with the QGIS Python
```

GitHub Actions runs the core tests, the core and QGIS tests in the official QGIS 3.34 and 3.44 containers, and Bandit on pull requests and pushes to `main`. Only synthetic LandXML is committed; project exports stay outside the repository. Rebuild the user guide with `tools/guide/build_guide.sh <build folder>` (QGIS Python, Node with Playwright, poppler).

## Contributing

See [CONTRIBUTING](.github/CONTRIBUTING.md) and the [code of conduct](.github/CODE_OF_CONDUCT.md).

## History and licence

See [CHANGELOG.md](CHANGELOG.md). The plugin began in November 2026 as RoadSign Designer and was renamed Road Furniture Designer as its scope grew to markings, barriers and traffic calming. Licensed under the GNU General Public License version 2 or later; see [LICENSE](LICENSE). The sign artwork is drawn from the figures of the Kenya Road Design Manual Part 6.2 (Ministry of Roads and Transport, 2025).

## Citation

If you use the plugin in your work, please cite it: Akello, E. Road Furniture Designer (version 0.9.0) [QGIS plugin]. https://doi.org/10.5281/zenodo.24162212. This DOI covers all versions and resolves to the latest; each version also has its own DOI on Zenodo. Citation metadata is in `CITATION.cff`.
