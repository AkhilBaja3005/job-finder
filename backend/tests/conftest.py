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
