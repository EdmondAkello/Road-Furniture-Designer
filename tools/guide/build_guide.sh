#!/usr/bin/env bash
# Build the user guide PDF.  Usage: tools/guide/build_guide.sh <landxml> <alignment> <build dir> [project name]
# Needs the QGIS Python (python3 with qgis), matplotlib for the DXF figure, Node + Playwright, pdfunite.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(cd "$HERE/../.." && pwd)"
LX="$1"; AL="$2"; OUT="$3"; NAME="${4:-Demo}"
VERSION="$(grep '^version=' "$ROOT/qgis_plugin/road_furniture_designer/metadata.txt" | cut -d= -f2)"
python3 "$ROOT/tools/build_plugin.py" >/dev/null
QT_QPA_PLATFORM=offscreen "${QGIS_PYTHON:-python3}" "$HERE/make_figures.py" "$LX" "$AL" "$OUT/figures" "$NAME"
cp "$HERE/guide.css" "$OUT/"
sed -e "s/{{VERSION}}/$VERSION/g" -e "s/{{DATE}}/$(date '+%B %Y')/g" "$HERE/user_guide.html" > "$OUT/user_guide.html"
mkdir -p "$ROOT/docs/user-guide"
node "$HERE/render_pdf.js" "$OUT/user_guide.html" "$ROOT/docs/user-guide/Road_Furniture_Designer_${VERSION}_User_Guide.pdf" "$VERSION"
