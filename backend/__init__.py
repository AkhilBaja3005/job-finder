"""
Job Finder backend package initialization.
Ensures backend directory is dynamically added to sys.path so subpackages
(services, routes, utils, mcp) can resolve cleanly across all environments.
"""
import sys
import os

_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
