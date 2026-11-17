import os
import sys

# Both `backend` (top-level backend/) and the repo root (containing `job_finder` and `backend`)
# must be on sys.path so tests can import from `services...`, `utils...`, `backend...`, and `job_finder...`
# regardless of how pytest or PYTHONPATH is invoked in CI / local dev.
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
repo_root = os.path.dirname(backend_dir)

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)


import pytest

# Tracked template files that no test may ever modify. One of them was once rewritten with real
# personal data during a test run; this names the test that does it and puts the file back.
_PROTECTED = [
    os.path.join(backend_dir, "config", "candidate_profile.example.json"),
]


@pytest.fixture(autouse=True)
def _protect_tracked_config_files(request):
    before = {}
    for path in _PROTECTED:
        try:
            with open(path, "rb") as f:
                before[path] = f.read()
        except OSError:
            before[path] = None
    yield
    changed = []
    for path, content in before.items():
        try:
            with open(path, "rb") as f:
                now = f.read()
        except OSError:
            now = None
        if now != content:
            changed.append(os.path.relpath(path, repo_root))
            if content is not None:
                with open(path, "wb") as f:
                    f.write(content)
    if changed:
        pytest.fail(f"{request.node.nodeid} modified tracked file(s): {', '.join(changed)}", pytrace=False)
