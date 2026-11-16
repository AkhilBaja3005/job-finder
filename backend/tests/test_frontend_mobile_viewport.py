"""The viewport tag must allow pinch-zoom (accessibility) and the app must keep its phone breakpoints."""

import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_viewport_meta_allows_zoom():
    html = _read("frontend", "index.html")
    content = re.search(r'<meta name="viewport" content="([^"]+)"', html).group(1)
    assert "width=device-width" in content
    assert "user-scalable=no" not in content and "maximum-scale=1" not in content


def test_phone_breakpoints_and_header_classes_exist():
    css = _read("frontend", "src", "index.css")
    assert "@media (max-width: 768px)" in css and "@media (max-width: 480px)" in css
    for cls in (".app-header-tagline", ".app-header-nav", ".app-header-actions", ".footer-shortcuts"):
        assert cls in css, f"missing mobile rule for {cls}"
    jsx = _read("frontend", "src", "App.jsx")
    for cls in ("app-header-tagline", "app-header-nav", "app-header-actions", "footer-shortcuts"):
        assert cls in jsx, f"App.jsx no longer uses {cls}"


def test_inputs_use_16px_font_on_phones_to_avoid_ios_zoom():
    css = _read("frontend", "src", "index.css")
    block = css.split("@media (max-width: 768px)", 1)[1]
    assert re.search(r"input, select, textarea \{[^}]*font-size: 16px", block, re.S)
