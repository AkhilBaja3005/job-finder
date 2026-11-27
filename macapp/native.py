"""
Mac-specific window behaviour: the menu bar, the title bar, and the window's colour.

Everything here is optional polish. If PyObjC is missing, or a call fails, the window still works, so every
function catches its own errors and logs them.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict

log = logging.getLogger("job_finder_app")

# The page's own background colours, so the window never flashes a different colour while resizing.
BACKGROUND = {"light": (1.0, 1.0, 1.0), "dark": (0x1D / 255, 0x1E / 255, 0x21 / 255)}


def _on_main(fn: Callable[[], None]) -> None:
    from PyObjCTools import AppHelper
    AppHelper.callAfter(fn)


def _ns_window(window: Any) -> Any:
    """pywebview keeps the underlying NSWindow in window.native."""
    return getattr(window, "native", None)


def style_window(window: Any) -> None:
    """Content runs under a transparent title bar, so the sidebar reaches the top and the traffic lights sit on it."""
    def apply() -> None:
        try:
            import AppKit
            ns = _ns_window(window)
            if ns is None:
                return
            ns.setTitlebarAppearsTransparent_(True)
            ns.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            ns.setStyleMask_(ns.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
            ns.setToolbar_(None)
            log.info("Window styled: unified title bar")
        except Exception:
            log.exception("could not style the window")
    try:
        _on_main(apply)
    except Exception:
        log.exception("could not schedule window styling")


def set_titlebar_theme(window: Any, dark: bool) -> None:
    def apply() -> None:
        try:
            import AppKit
            ns = _ns_window(window)
            if ns is None:
                return
            r, g, b = BACKGROUND["dark" if dark else "light"]
            ns.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, 1.0))
            log.info("Window colour set for the %s theme", "dark" if dark else "light")
        except Exception:
            log.exception("could not set the window colour")
    try:
        _on_main(apply)
    except Exception:
        log.exception("could not schedule the window colour")


def install_menu(app_name: str, handlers: Dict[str, Callable[[], None]]) -> None:
    """The standard Mac menu bar: App, Edit (so copy and paste work in every field), Window and Help."""
    def build() -> None:
        try:
            import AppKit
            import objc
            from Foundation import NSObject

            class Target(NSObject):
                def settings_(self, _sender): handlers["settings"]()
                def updates_(self, _sender): handlers["updates"]()
                def folder_(self, _sender): handlers["folder"]()
                def logs_(self, _sender): handlers["logs"]()
                def website_(self, _sender): handlers["website"]()

            target = Target.alloc().init()
            build.target = target  # keep a reference: AppKit does not retain menu targets

            def item(menu, title, action, key="", mods=None, tgt=None):
                it = menu.addItemWithTitle_action_keyEquivalent_(title, action, key)
                if mods is not None:
                    it.setKeyEquivalentModifierMask_(mods)
                if tgt is not None:
                    it.setTarget_(tgt)
                return it

            cmd = AppKit.NSEventModifierFlagCommand
            main = AppKit.NSMenu.alloc().init()

            def submenu(title):
                holder = AppKit.NSMenuItem.alloc().init()
                menu = AppKit.NSMenu.alloc().initWithTitle_(title)
                holder.setSubmenu_(menu)
                main.addItem_(holder)
                return menu

            app = submenu(app_name)
            item(app, f"About {app_name}", "orderFrontStandardAboutPanel:")
            item(app, "Check for Updates…", "updates:", tgt=target)
            app.addItem_(AppKit.NSMenuItem.separatorItem())
            item(app, "Settings…", "settings:", ",", cmd, target)
            app.addItem_(AppKit.NSMenuItem.separatorItem())
            item(app, f"Hide {app_name}", "hide:", "h", cmd)
            item(app, "Hide Others", "hideOtherApplications:", "h", cmd | AppKit.NSEventModifierFlagOption)
            item(app, "Show All", "unhideAllApplications:")
            app.addItem_(AppKit.NSMenuItem.separatorItem())
            item(app, f"Quit {app_name}", "terminate:", "q", cmd)

            edit = submenu("Edit")
            item(edit, "Undo", "undo:", "z", cmd)
            item(edit, "Redo", "redo:", "z", cmd | AppKit.NSEventModifierFlagShift)
            edit.addItem_(AppKit.NSMenuItem.separatorItem())
            item(edit, "Cut", "cut:", "x", cmd)
            item(edit, "Copy", "copy:", "c", cmd)
            item(edit, "Paste", "paste:", "v", cmd)
            item(edit, "Select All", "selectAll:", "a", cmd)

            window = submenu("Window")
            item(window, "Minimize", "performMiniaturize:", "m", cmd)
            item(window, "Zoom", "performZoom:")
            item(window, "Close", "performClose:", "w", cmd)

            help_menu = submenu("Help")
            item(help_menu, "Show Job Finder Folder", "folder:", tgt=target)
            item(help_menu, "Show Log Files", "logs:", tgt=target)
            help_menu.addItem_(AppKit.NSMenuItem.separatorItem())
            item(help_menu, "Job Finder on GitHub", "website:", tgt=target)

            AppKit.NSApp.setMainMenu_(main)
            AppKit.NSApp.setWindowsMenu_(window)
            AppKit.NSApp.setHelpMenu_(help_menu)
            log.info("Menu bar installed: %s", ", ".join(str(i.submenu().title()) for i in main.itemArray()))
        except Exception:
            log.exception("could not build the menu bar")
    try:
        _on_main(build)
    except Exception:
        log.exception("could not schedule the menu bar")


def toggle_zoom(window: Any) -> None:
    """Zooms or restores the window, like a double-click on a title bar."""
    def apply() -> None:
        ns = _ns_window(window)
        if ns is not None:
            ns.performZoom_(None)
    try:
        _on_main(apply)
    except Exception:
        log.exception("could not zoom the window")
