# Design criteria files

Road Furniture Designer reads its design values (side friction, sight distances,
K values, clear zones, barrier rules, marking visibility) from JSON files. The
default is the Kenya Road Design Manual 2025 (`kenya_rdm_2025`). An AASHTO 2011
set (`aashto_2011`) is bundled as well. You can add your own set for another
manual or for project-specific values.

## Where the files go

RFD looks for criteria in this order. A set found earlier in the list replaces a
bundled set that has the same `id`.

1. Folders listed in the environment variable `RFD_CRITERIA_PATH` (separated by `;` on Windows, `:` elsewhere).
2. Folders added in the plugin: **Auto tab → Design criteria → Add…**. They are remembered in the QGIS setting `RoadFurnitureDesigner/criteria_dirs`.
3. The bundled folder `rfd/data/criteria`.

## Smallest useful file: extend a bundled set

Start from an existing set with `extends`, then give only the tables that differ.
Top-level keys replace the base set's keys; `references` are merged.

```json
{
  "schema": "rfd-criteria/1",
  "id": "tanzania_rgm_2011",
  "name": "Tanzania Road Geometric Design Manual (2011)",
  "extends": "kenya_rdm_2025",
  "ssd": {"50": 65, "60": 85, "70": 110, "80": 140, "100": 205},
  "psd": {"50": 345, "60": 410, "70": 485, "80": 540, "100": 670},
  "references": {"ssd": "TZ RGDM Table 3-x", "psd": "TZ RGDM Table 3-y"}
}
```

The numbers above only show the format. Take the real values from your manual.

## Keys

Speed-keyed tables are objects `{"speed km/h": value}`. Values are interpolated
linearly and held constant beyond the first and last keys.

| Key | Required | Meaning | Kenya source |
|---|---|---|---|
| `id`, `name` | yes | Identifier (used in project settings) and display name | |
| `schema` | recommended | `"rfd-criteria/1"` | |
| `extends` | no | `id` of a set to inherit from | |
| `references` | no | `{key: "Table x.y"}`, printed in the report Basis sheet and footer | |
| `side_friction` | yes | Maximum side friction f by design speed | RDM 1.3 Table 5.1 |
| `ssd` | yes | Stopping sight distance (m) on level grade | RDM 1.3 Table 3.16 |
| `ssd_by_grade` | no | `{"grades": [9, 6, …, -9], "speed": [d at each grade]}` | RDM 1.3 Table 3.16 |
| `psd` | yes | Passing sight distance (m) | RDM 1.3 Table 3.20 (normal) |
| `psd_reduced` | no | Reduced PSD; used for no-overtaking when the Auto tab option is on | RDM 1.3 Table 3.20 |
| `eye_height`, `object_height` | no | Driver eye and SSD object height (m). Defaults 1.05 / 0.20 | RDM 1.3 Table 3.13 |
| `psd_object_height` | no | Overtaking target height (m). Default 1.3 | RDM 1.3 Table 3.20 |
| `headlight_height`, `headlight_angle_degrees` | no | Sag headlight check. Defaults 0.6 m / 1° | RDM 1.3 S3.13.8 |
| `k_crest`, `k_sag` | no | Minimum K by speed. Without them K is computed from SSD and the heights | RDM 1.3 Tables 6.1, 6.4 |
| `clear_zone` | no | `{"medium_traffic"\|"low_traffic": {"fill"\|"cut": {speed: m}}}` | RDM 1.3 Table 12.1 |
| `barrier` | no | `runout` {speed: m}, `min_length`, `setback`, `setback_high`, `group_gap`, and optionally `simple` {`height`, `slope_n`} | RDM 1.3 Chapter 12 |
| `barrier_warrant` | no | Embankment warrant curve: a file name (relative to the criteria file) or an inline object, see below | RDM 1.3 Figure 12.4 |
| `marking_visibility` | no | `{"rows": [{"classes": [...], "speed", "visibility", "critical"}]}` for the combined line system | RDM 6.1 Table 4.4 |

### Barrier warrant curve

```json
"barrier_warrant": {
  "heights": [1, 2, 4, 6, 10],
  "required_below": [1.0, 1.5, 2.4, 3.0, 3.8],
  "not_required_above": [1.0, 1.8, 3.0, 3.8, 4.0]
}
```

For a fill of height h (m) and batter 1:n, a barrier is required when n is less
than `required_below(h)` and not required when n is at least
`not_required_above(h)`. In between, it is left to the engineer's judgement. If
`not_required_above` is left out there is no judgement band. A set with no curve
uses `barrier.simple`: a barrier is required when h ≥ `height` and n <
`slope_n`. The default simple rule is 6 m and 1:4.

## Checks on load

A set without `side_friction`, `ssd` or `psd` (after `extends` is applied) is
rejected with a message naming the missing tables. Any table that is missing
falls back to the computed value, or the check that needs it is skipped. The
report cites the table used for each check.
