"""
job_finder — Autonomous career agent, ATS resume tailor & job search copilot.
"""

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("job-finder-ai")
    except PackageNotFoundError:
        __version__ = "1.2.7"
except ImportError:
    __version__ = "1.2.7"

__author__ = "Akhil Baja"
__contributors__ = ["Bhavesh Nivas"]

