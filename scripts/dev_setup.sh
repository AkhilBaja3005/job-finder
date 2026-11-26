#!/usr/bin/env bash
# Sets up a local development environment that matches CI: a project virtualenv with the pinned dependencies.
#   scripts/dev_setup.sh          then:   source .venv/bin/activate && pytest backend/tests -q
# Your global Python can have newer packages (for example browser-use 1.x) than this project supports, which makes some
# tests fail on your machine and pass in CI. A virtualenv avoids that.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3.12 python3.11 python3.13 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
echo "Using $($PY --version) at $(command -v "$PY")"

[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r backend/requirements.txt pytest
python -m pip install -q -e . --no-deps
python -c "import browser_use, sys; print('browser-use', getattr(browser_use, '__version__', 'installed'))"
echo
echo "Done. Activate with:  source .venv/bin/activate"
echo "Run the tests with:   pytest backend/tests -q"
