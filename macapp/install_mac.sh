#!/usr/bin/env bash
set -euo pipefail

# Installs or updates Job Finder.app from the latest desktop-latest GitHub release
# without browser quarantine attributes.

REPO="AkhilBaja3005/job-finder"
APP_NAME="Job Finder.app"
DEST="/Applications/$APP_NAME"

case "$(uname -m)" in
  arm64)  ASSET="Job-Finder-arm64.dmg" ;;
  x86_64) ASSET="Job-Finder-x86_64.dmg" ;;
  *)
    echo "Unsupported Mac architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

URL="https://github.com/${REPO}/releases/download/desktop-latest/${ASSET}"
TMP="$(mktemp -d)"
MNT="${TMP}/mnt"
DMG="${TMP}/${ASSET}"

cleanup() {
  if mount | grep -q "on ${MNT} "; then
    hdiutil detach "$MNT" -quiet || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

echo "Downloading ${ASSET}..."
curl -fSL --progress-bar "$URL" -o "$DMG"

echo "Mounting installer..."
mkdir -p "$MNT"
hdiutil attach "$DMG" -nobrowse -quiet -mountpoint "$MNT"

if [ ! -d "${MNT}/${APP_NAME}" ]; then
  echo "Could not find ${APP_NAME} inside ${ASSET}." >&2
  exit 1
fi

echo "Installing to /Applications..."
rm -rf "$DEST"
ditto "${MNT}/${APP_NAME}" "$DEST"
xattr -cr "$DEST" 2>/dev/null || true

echo "Installed ${APP_NAME} to ${DEST}."
echo "Run: open -a \"Job Finder\""
