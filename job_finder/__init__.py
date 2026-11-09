"""
job_finder — Autonomous career agent, ATS resume tailor & job search copilot.
"""

# Fixed release version for standalone execution & wheel builds
__version__ = "1.4.1"

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        pkg_ver = version("job-finder-ai")
        if pkg_ver:
            __version__ = pkg_ver
    except PackageNotFoundError:
        pass
except ImportError:
    pass

__author__ = "Akhil Baja"
__contributors__ = ["Bhavesh Nivas"]

