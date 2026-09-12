"""
job_finder — Autonomous career agent, ATS resume tailor & job search copilot.
"""

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("job-finder-ai")
    except PackageNotFoundError:
        __version__ = "1.0.0"
except ImportError:
    __version__ = "1.0.0"

__author__ = "Akhil Baja"
