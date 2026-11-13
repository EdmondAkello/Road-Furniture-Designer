# Contributing to Road Furniture Designer

Bug reports, questions, sign and criteria data, and code are all welcome.

## Reporting a problem

Open an [issue](https://github.com/EdmondAkello/Road-Furniture-Designer/issues) with:
- the QGIS version and operating system;
- the plugin version;
- what you did (tab, button, settings);
- the software that wrote the LandXML file (Civil 3D, OpenRoads, etc.) and its version;
- what you expected and what happened, with any message or Python error.

A LandXML file that reproduces the problem helps most. If the design is confidential, a cut-down or synthetic file with the same structure is enough (`tools/guide/make_guide_road.py` and `examples/make_demo_road.py` show how). Please don't attach files you are not free to share, and keep client and project names out of issues and commits.

## Changing the code

1. Open an issue first for anything beyond a small fix.
2. Work on a branch (`fix/...`, `feat/...`, `docs/...`) and open a pull request against `main` that refers to the issue. CI runs the core tests, the QGIS tests in a headless QGIS container and Bandit.
3. Add the change to `CHANGELOG.md` under **Unreleased**, and update the README and the user guide (`tools/guide/user_guide.html`). Leave version numbers alone; releases are tagged by the maintainer.

### Ground rules

- **The manuals are the source.** Rules cite the clause, table or figure they come from (RDM 6.1, 6.2, 6.4, 1.3 or the criteria file in use).
- **Design values live in data**: criteria in `rfd/data/criteria`, linear items in `rfd/data/furniture_linear.json`, sign pairs in `rfd/data/sign_pairs.json`, signs in the catalogue. Other standards are added as data, not code.
- **Never infer coordinates.** The CRS and axis order come from the file or the user.
- **Automate only what the alignment decides**, and keep a manual way to place or change everything that is automated.
- **On-disk names stay `rsd_*` / `RSD*`** so existing projects and drawings keep working.
- **Every change ships with tests**, using synthetic roads (`tests/test_bootstrap.py` has a random-road generator). Project LandXMLs stay outside the repository.

### Running the tests

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests                                     # core, no QGIS needed
python tools/build_plugin.py                                  # copy the core into the plugin
QT_QPA_PLATFORM=offscreen python -m pytest -q tests_qgis      # with the QGIS Python
bandit -q -r qgis_plugin/road_furniture_designer                 # as plugins.qgis.org scans: no config, no findings
```

`python tools/sweep_landxml.py <folder>` runs the signs, markings and barrier invariants over your own LandXML files without copying them anywhere.

### AI-assisted contributions

If you are contributing from outside the project and an AI tool wrote a substantial part of your change, mention it in the pull request and name the tool. You remain responsible for the change: you have read it, tested it and can explain it.

## Code of conduct

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).

## Maintainer

The plugin is maintained by Edmond Akello. Decisions on scope and design are made in issues and pull requests, in public.
