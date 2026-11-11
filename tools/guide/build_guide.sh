#!/usr/bin/env bash
# Build the user guide (HTML, figures and PDF) from the synthetic guide road.
#   Usage: tools/guide/build_guide.sh <build dir>
# Needs the QGIS Python (python3 with qgis; set QGIS_PYTHON otherwise), matplotlib for the DXF figure,
# Node + Playwright (Chromium) and pdfunite (poppler-utils).
# Writes docs/user-guide/user-guide.html, docs/user-guide/figures/ and
# docs/user-guide/Road_Furniture_Designer_<version>_User_Guide.pdf.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$1"
PY="${QGIS_PYTHON:-python3}"
VERSION="$(grep '^version=' "$ROOT/qgis_plugin/road_furniture_designer/metadata.txt" | cut -d= -f2)"
DOCS="$ROOT/docs/user-guide"
mkdir -p "$OUT"
python3 "$ROOT/tools/build_plugin.py" >/dev/null
python3 "$HERE/make_guide_road.py" "$OUT/guide_road.xml"
QT_QPA_PLATFORM=offscreen "$PY" "$HERE/make_figures.py" "$OUT/guide_road.xml" DEMO-ROAD "$OUT/figures" "Demonstration road"
rm -rf "$OUT/figures/_work"
cp "$HERE/guide.css" "$OUT/"
sed -e "s/{{VERSION}}/$VERSION/g" -e "s/{{DATE}}/$(date '+%B %Y')/g" "$HERE/user_guide.html" > "$OUT/user-guide.html"
mkdir -p "$DOCS"
rm -rf "$DOCS/figures"
cp -r "$OUT/figures" "$DOCS/figures"
cp "$OUT/guide.css" "$DOCS/guide.css"
cp "$OUT/user-guide.html" "$DOCS/user-guide.html"
node "$HERE/render_pdf.js" "$OUT/user-guide.html" "$DOCS/Road_Furniture_Designer_${VERSION}_User_Guide.pdf" "$VERSION"
echo "guide: $DOCS"
