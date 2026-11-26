#!/usr/bin/env bash
# Builds "Job Finder.app" and a .dmg on a Mac.   Usage: macapp/build_mac.sh
# Needs Python 3.11 or 3.12 and the Xcode command line tools (hdiutil). No Node needed.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3.12}"
VENV=".macbuild/venv"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt -r macapp/requirements-app.txt

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
