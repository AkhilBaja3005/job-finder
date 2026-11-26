"""Keeps background Python processes out of the macOS Dock.

On a Mac, Python.app (the python.org build) is an application bundle. As soon as any library in the process touches AppKit
(PyObjC, a font or screenshot helper, a file dialog ...), macOS registers the process as a regular app and shows a rocket
"Python" icon that bounces in the Dock. A background tool such as the MCP server, the web server or a scan has no window,
so it should be a "UIElement": no Dock icon and no menu bar. This changes only how macOS treats the process.

Never call this from the desktop app's own window process: that one needs its Dock icon."""
from __future__ import annotations

import sys


def hide_dock_icon() -> bool:
    """Returns True when the process was switched to a background (no Dock icon) app. Does nothing off macOS and never raises."""
    if sys.platform != "darwin":
        return False
    try:
        import ctypes
        import ctypes.util

        path = ctypes.util.find_library("ApplicationServices")
        if not path:
            return False
        services = ctypes.cdll.LoadLibrary(path)

        class ProcessSerialNumber(ctypes.Structure):
            _fields_ = [("high", ctypes.c_uint32), ("low", ctypes.c_uint32)]

        services.TransformProcessType.argtypes = [ctypes.POINTER(ProcessSerialNumber), ctypes.c_uint32]
        services.TransformProcessType.restype = ctypes.c_int32
        current = ProcessSerialNumber(0, 2)  # kCurrentProcess
        return services.TransformProcessType(ctypes.byref(current), 4) == 0  # 4 = kProcessTransformToUIElementApplication
    except Exception:
        return False
