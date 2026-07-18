import os
import sys

# Both `services` and `utils` are treated as top-level packages relative to
# backend/ (mirrors how main.py imports them, e.g. `from services.resume_parser
# import parse_resume`), not as part of an installed package — so tests need
# backend/ on sys.path regardless of the directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
