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

# Signing is optional. With a Developer ID identity in SIGN_IDENTITY the app is signed with the hardened runtime;
# with APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD as well, the .dmg is notarized and stapled so macOS opens it
# without a warning. Without them the build is unsigned (right-click -> Open the first time).
if [ -n "${SIGN_IDENTITY:-}" ]; then
  echo "Signing with: $SIGN_IDENTITY"
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "dist-mac/Job Finder.app"
  codesign --verify --deep --strict "dist-mac/Job Finder.app"
fi

hdiutil create -volname "Job Finder" -srcfolder "dist-mac/Job Finder.app" -ov -format UDZO "$DMG" >/dev/null

if [ -n "${SIGN_IDENTITY:-}" ] && [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ]; then
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$DMG"
  echo "Notarized and stapled."
fi
echo "Built: dist-mac/Job Finder.app and $DMG"
