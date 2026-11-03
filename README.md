# RoadSign Designer (RSD), v0.6

Place traffic signs by clicking along a road alignment in QGIS. For every sign, the tool works out the chainage, offset, side, facing and post number from the LandXML alignment, and recomputes them whenever the sign is moved. The inventory updates live as you work. Signs go to Civil 3D as a georeferenced DXF that pastes into the project drawing at the true coordinates.

```
 QGIS: pick sign / auto-place ─► rsd_signs (GeoPackage) ─► live inventory and checks (dock)
                                                     ─► Inventory (Excel Tables + CSV) ─► QTO / Bill
                                                     ─► Road signage report (PDF / PNG / Excel)
                                                     ─► Georeferenced DXF ─► COPYBASE 0,0 + PASTEORIG into the project DWG
 (Dynamo route: parked)
```

**Status:**
- **Core:** 37 tests passing.
- **QGIS plugin:** 27 headless tests passing on QGIS 3.34. Also checked on the Nessuit–Salgaa preliminary design LandXML (Arc 1960 / UTM 36S, 4 alignments, 26 spirals) and on Olkaria LOT 3 (UTM 37S, 59 MB with TIN surfaces and 3,569 corridor sections; loads in about 1.3 s).
- **Dynamo scripts:** parked for now (kept in `dynamo/`, not run in Civil 3D).
- **Catalogue:** RDM 6.2 (2025). 245 signs, with codes, names and artwork taken from the manual's figures (see "Sign catalogue"). Post and foundation types are generic and still project-defined.

## Sign catalogue (RDM 6.2, 2025)

`tools/extract_rdm_signs.py` reads the manual and does three things:
- Matches every "Figure x.y …, Sign CODE" caption to its framed artwork.
- Keeps only the sign itself, dropping dimension lines and notes.
- Writes a vector SVG icon per sign, plus a colour CAD block library (`rsd/data/RSD_SignBlocks.dxf`, hatched faces, one block `RSD_<code>` per sign).

`tools/build_catalogue.py` then adds the sizing and legend rules. Re-run both when a new edition of the manual comes out.

**Coverage:** R, M, P, W, I, E, PD, IM and RW signs.
- W24 chevrons are split into W24-a (single), W24-b (single, large), W24-c (double) and W24-d (triple).
- Signs the manual shows one way round but which are used both ways (bends, side roads, chevrons and so on) have a **mirrored** version (`_M` icon and block).

**Numbering clashes in the manual itself.** These are resolved as follows and noted in the catalogue:
- Fig 7.1 is captioned P1, which clashes with No Entry, so it becomes PD1.
- I10 is used for both Tourist Facility and County Boundary, so County Boundary becomes I10B.
- IM4 is used twice, so the expressway symbol becomes IM4S.
- The directional examples "incorporating the X symbol" become I20-D, I21-D and I22-D.

The Ministry's standard drawings WSCM/84/2/01 (Jan 2024) use a **different numbering** (W1 = Sharp left turn there, Crossroads in RDM 6.2). RSD uses RDM 6.2 codes on drawings and schedules (agreed with HH, Nov 2026).

**Sizes.** RDM 2.9 allows 600, 750 or 900 mm, and 1200 mm on expressways. For Stop and Give Way (Tables 3.1 and 3.3), warning signs (Table 4.1) and circular regulatory signs, choose **Auto**. The size then follows the design speed at the sign's chainage, taken from the Civil 3D SpeedStation data in the LandXML, and is recomputed if the sign is moved. The design speed stands in for the manual's 85th-percentile approach speed. Typing a size by hand turns Auto off for that sign. Plates and information signs are "custom" (designed size).

## Legends (destinations, plate text)

Directional signs, town and county signs, and text plates carry text that changes from job to job. Type it in the **Legend** box before placing, or select the sign on the Signs tab and use **Edit legend…**.

```
< Nakuru A104 18        left, route A104, 18 km
> Eldoret A104 140      right
^ Salgaa 1              ahead (route and km are optional)
```

- **Directional faces:** drawn in the RDM Table 2.6 colour scheme for the chosen class:
  - Class A, B and UA: green background with yellow route numbers.
  - Class C, D, UC, E–W and UL: white background.
  - Expressway: blue background.
- **Destination order:** RDM 5.2 (ahead, then left, then right; furthest destination first).
- **Plates:** re-drawn with your text (W23 distance, W35 safe height, I7 town, P35/P38 information plates, …).

The legend goes into the inventory (`Legend` column), the Civil 3D package and the visible `LEGEND` block attribute. Generated faces are saved next to the GeoPackage in `<project>_faces/`. Signs that need a legend are flagged in Checks until one is entered.

## Install the QGIS plugin

In QGIS, open **Plugins → Manage and Install Plugins → Install from ZIP** and choose `roadsign_designer.zip`. Restart QGIS if you are replacing an older version.

No pip is needed. The export libraries are bundled in the plugin's `ext_libs` folder as pure Python (openpyxl, ezdxf, fontTools, pyparsing, typing_extensions, et_xmlfile). If QGIS's own Python already has any of them, those copies are used instead.

## Auto-placement (Auto tab)

**Propose signs** reads the alignment, superelevation, design speeds, profile and corridor edges, and adds the signs the rules call for as **proposed** signs. They show with an orange ring on the map and the report. Review them, move or delete any you disagree with, then **Accept all proposals**. Proposals are left out of the inventory and the Civil 3D export until they are accepted. Re-running replaces the open proposals and never duplicates a sign that is already there.

| Rule | Trigger | Signs | Source |
|---|---|---|---|
| Curves | curve speed below the design speed by ≥ 10 km/h. Curve speed from V² = 127 R (e + f), with e from the LandXML superelevation | W20 bend, or W19 sharp turn if ≥ 30 km/h below. Placed 6 s of travel ahead, both directions, mirrored for left/right | RDM 6.2 4.5, 2.4 |
| Curve series | warned curves within 150 m of each other | W22 / W21 plus a W23 distance plate ("FOR 350 M") | RDM 6.2 4.5 |
| Chevrons | curve speed ≥ 20 km/h below design | W24-a on the outside of the curve, back to back for both directions, spaced per Table 4.2 | RDM 6.2 4.6.1 |
| Steep grades | descent > 5 %, ascent > 10 % | W30 / W31 with the actual grade as the legend | RDM 6.2 4.6.4 |
| No overtaking | crest sight distance < passing sight distance | P32 plus a W23 distance plate at the start, and P32 "END", for each direction | RDM 6.2 3.11 |

**Placement rules:**
- Posts go 1.0 m beyond the paved-shoulder edge (adjustable; RDM 2.4 allows 0.6–3.0 m).
- Signs are kept at least 0.6 × V m apart; a crowded sign is moved back from the hazard.

**Report-only findings** (no sign is proposed):
- sags short of headlight sight distance
- crests short of stopping sight distance

**Thresholds and defaults:** every threshold is on the Auto tab. Side friction and the sight distances (SSD, PSD) are AASHTO 2011 defaults, because RDM 6.2 doesn't give them; check them against RDM 1.3. RDM 6.2 leaves sharp turn versus bend to the Engineer's discretion; the speed-drop margins are that judgement, made explicit.

## Corridor restriction

When the LandXML has corridor edges, **Keep inside the corridor** (Place tab, on by default) snaps every sign into RDM 2.4's band, 0.6–3.0 m beyond the reference edge. A sign is never placed past the corridor's outer limit (ditch or daylight). If the corridor stops at the shoulder, no outer limit applies.

The Checks list flags:
- signs outside that band
- signs outside the corridor
- signs on the shoulder or in the travelled way
- signs closer together than 0.6 × V

## Road signage report

**Inventory → Road signage report** asks for the plan scale (Auto, 1:500 to 1:5000, or no plan sheets) and the title-block names (Prepared by, Checked by, Approved by; kept with the project). It writes, next to each other:
- **PDF:** A3 landscape, every page in the same drawing frame: the plan layout sheets, one long-section sheet per kilometre, then the sign schedule and the findings.
- **PNG:** one image per plan and long-section sheet (`plan_NN_<chainage>.png`, `section_<chainage>.png`).
- **Excel workbook:** Signs (including proposals and the reason for each), Findings, Horizontal curves (R, e, f, curve speed against design speed), Vertical curves (K, A, SSD) and Basis.

**Frame and title block.** Border, title and logo top right, and a title block with Project, Alignment, Drawing, Scale, Prepared / Checked / Approved by, Date and Sheet. The logo is the Howard Humphreys mark by default; to use another, set the QGIS setting `RoadSignDesigner/report_logo` to an image file.

**Plan layout sheets.** Each sheet is turned so the road runs left to right and drawn at the chosen scale (Auto = 1:2500, or 1:1000 for roads under 1.2 km). Sheet lengths adapt so that tight curves still fit with room for the signs. Each sheet shows:
- the corridor edges (ETW, EPS, hinge, ditches, daylight) and the centreline with chainages
- the LandXML's other alignments (side and link roads), named
- every sign upright beside the road at 10 mm, with a leader to its post; a sign and its plate stack, back-to-back faces sit side by side, and symbols are moved clear of one another
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

The pages are drawn with QPainter, the same way the LandXML Road & Terrain plugin draws its exports.

## DXF for plan drawings

On **Export to Civil 3D**, choose the plan scale (1:500 to 1:5000; default 1:2500):
- **Symbols** print at 10 mm, matching HH plan drawings: 25 m in model space at 1:2500, 10 m at 1:1000.
- **Callouts.** Each sign is one block inserted at its post (true coordinates). The block holds a post marker, a leader and the sign face upright beside the road, clear of the carriageway and of the neighbouring signs, with the code underneath. A sign and its plate stack; back-to-back faces sit side by side.
- **Text** (codes, legends, chainages) prints at 1.8 mm. Chainage labels read the right way up on either side.
- **Text-bearing signs:** directional signs and plates get their own block with the real legend (coloured background, arrows, place names, route numbers, distances), drawn at 0.6 of the symbol size.
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

The reference alignment, the chainage ticks and an **RSD CHECK POINT** go on non-plotting layers (`RSD-ALIGN`, `RSD-REF-NOTES`). The check point is a cross at the alignment start, labelled with its own E/N. Paste it once to confirm everything lines up with the Civil 3D alignment, then delete it.

Pasted signs keep their attributes and their RSD identity (XDATA), so a later read-back still matches them to the sign list. On Olkaria LOT 3, every exported sign back-computes to its chainage and offset with zero difference, and the reference alignment starts exactly at the LandXML's first `<Start>` point.

## Road edges and vertical profile from the LandXML

When the LandXML includes Civil 3D corridor sections (`CrossSect` / `DesignCrossSectSurf`) or a design profile (`ProfAlign`), the new project picks them up automatically.

**Road edges.** Every coded corridor point becomes an edge line in the `RSD road edges` layer, with an offset that varies by station: ETW (edge of travelled way), EPS (edge of paved shoulder), Hinge, Ditch_In / Ditch_Out, Daylight. Pavement layer codes (`*_Base`, `*_Pave2`, …) and Crown are skipped. Daylight is drawn only where it exists (it isn't interpolated across gaps of more than 30 m).
- **Offset from:** on the Place tab, choose an edge here. With **Fix offset at 1.0 m**, every sign lands 1.0 m beyond that edge at the chainage you click, even where the road widens.
- **Hover readout:** shows the clearance from the edge and the grade, e.g. `Ch 1+150.00  6.00 m Left  (+1.00 m from EPS)  grade +2.5%`.
- **Stored on each sign:** its reference edge and its clearance from it, recomputed when the sign is moved. The default reference is EPS, or ETW if the file has no EPS.
- **Checks:** a sign inside the travelled way is an **error**; a sign on the shoulder is a **warning**.

**Vertical profile.** The `RSD vertical curves` layer marks every crest and sag at its PVI, labelled with its K-value and length (e.g. `Crest K=10 L=141`). Each sign stores the design grade at its chainage. Use these to place W30/W31 (steep descent/ascent), W41/W42 (sharp rise/dip) and no-overtaking signs.

The inventory gains the columns **Edge Ref**, **Clear of Edge (m)**, **Grade (%)** and **Design Speed (km/h)**, and the Civil 3D package carries the same values.

## Using it

1. **New project…**
   1. Pick the LandXML file and the alignment.
   2. Choose the CRS of the LandXML coordinates if the QGIS project doesn't already have a projected one.
   3. Save the RSD GeoPackage.
   The plugin adds three layers: the alignment, chainage ticks every 100 m, and the sign layer.
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

- **Block library:** `rsd/data/RSD_SignBlocks.dxf` holds the RDM artwork as colour hatches, including `_M` mirrored blocks. Open it in Civil 3D and save it as DWG (or run `python -m rsd library RSD_SignBlocks.dxf` for a copy). Raster-only figures in the manual (a few information signs) become a labelled outline block.
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

If the first run fails, send me the error. The two places most likely to need adjusting are how the Python engine returns `ref` arguments from `Alignment.PointLocation`, and the internal-versus-displayed station when station equations are present.

## Command line (optional)

The command line covers working without QGIS, from an Excel sign list:

```
set PYTHONPATH=vendor\ext_libs        (or: python -m pip install openpyxl ezdxf)
python -m rsd template SignList.xlsx --alignment NAME
python -m rsd build SignList.xlsx road.xml --out outputs
python -m rsd reconcile SignList.xlsx readback.json road.xml
python -m rsd readback-dxf edited.dxf readback.json
python -m rsd library RSD_SignBlocks.dxf
```

## Conventions

- **Coordinates:** x = easting, y = northing. LandXML points are read as N E. The LandXML coordinates must be in the sign layer's CRS, which must be projected and in metres.
- **Offset:** positive to the **right** looking up-chainage (the Civil 3D convention). The inventory shows the offset as a positive number plus a side, L or R.
- **Stations:** the internal station is the geometric one (staStart + distance along). Displayed chainage applies station equations. QGIS stores both, so overlapping station equations can't put a sign at the wrong chainage.
- **Geometry supported:** lines, circular curves and clothoid spirals.

## Layout

```
rsd/                      core (stdlib; openpyxl/ezdxf only for exports)
  alignment.py            LandXML, station/offset both ways, station equations
  records.py              records -> validated faces & installations (shared by QGIS and Excel)
  catalogue.py, data/     catalogue.json (RDM 6.2), signs/ SVG icons, RSD_SignBlocks.dxf
  legend.py               legend parsing, directional faces (RDM colour schemes), plates
  corridor.py, profile.py road edges from corridor codes, corridor clamp; vertical profile (grade, crests, sags, K)
  autoplace.py            RDM 6.2 rules -> proposed signs; geometry findings (curve speed, grades, sight distance)
  inventory.py            Excel Tables + CSV for QTO
  plan_layout.py          where sign symbols go on a plan (callouts clear of the road and each other)
  package.py, dxf_out.py  Civil 3D package, placed DXF (georeferenced, callouts), block library, DXF read-back
  signlist.py, reconcile.py, cli.py   Excel route
qgis_plugin/roadsign_designer/   plugin (store.py, maptool.py, dock.py, report.py, plansheet.py, compat.py); core and vendor/ext_libs copied in by tools/build_plugin.py
vendor/ext_libs/          bundled pure-Python export libraries
dynamo/                   rsd_place.py, rsd_readback.py
tools/                    extract_rdm_signs.py, build_catalogue.py, build_plugin.py
tools/guide/              user guide and technical manual (HTML -> PDF; figures from Olkaria LOT 3)
docs/user-guide/          RoadSign_Designer_<version>_User_Guide.pdf
tests/ (core), tests_qgis/ (run with QGIS Python, QT_QPA_PLATFORM=offscreen)
```

Build the plugin zip: `python tools/build_plugin.py roadsign_designer.zip`

## Next

- First paste of the DXF into a project drawing (PASTEORIG).
- Dynamo route: parked.
- Junction signing (advance direction / direction signs per RDM Table A1-1) once junction locations are available (a point layer or the LandXML's intersecting alignments).
