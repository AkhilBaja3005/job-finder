#!/usr/bin/env bash
# Builds "Job Finder.app" and a .dmg on a Mac.   Usage: macapp/build_mac.sh
# Needs Python 3.11 or 3.12, Node 20, and Xcode command line tools (hdiutil, sips, iconutil).
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3.12}"
VENV=".macbuild/venv"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt -r macapp/requirements-app.txt

if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
  (cd frontend && npm ci && npm run build)
fi

# App icon from the web app's icon (optional: skipped if the tools or the file are missing)
if [ ! -f macapp/icon.icns ] && [ -f frontend/public/favicon-192.png ]; then
  ICONSET=".macbuild/icon.iconset"; rm -rf "$ICONSET"; mkdir -p "$ICONSET"
  for s in 16 32 64 128 256 512; do
    sips -z $s $s frontend/public/favicon-192.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1 || true
  done
  iconutil -c icns "$ICONSET" -o macapp/icon.icns 2>/dev/null || true
fi

rm -rf dist-mac
pyinstaller macapp/job_finder.spec --noconfirm --distpath dist-mac --workpath .macbuild/work

VERSION="$(python - <<'PY'
import re
print(re.search(r'^version\s*=\s*"([^"]+)"', open("pyproject.toml").read(), re.M).group(1))
PY
)"
ARCH="$(uname -m)"
DMG="dist-mac/Job-Finder-${VERSION}-${ARCH}.dmg"
hdiutil create -volname "Job Finder" -srcfolder "dist-mac/Job Finder.app" -ov -format UDZO "$DMG" >/dev/null
echo "Built: dist-mac/Job Finder.app and $DMG"
