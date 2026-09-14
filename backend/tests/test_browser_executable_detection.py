"""
test_browser_executable_detection.py
Unit test suite verifying cross-platform browser discovery across Windows, macOS, and Linux.
"""

import os
import sys
import pytest
from unittest.mock import patch
from backend.services.browser_use_agent import find_browser_executable


def test_find_browser_executable_env_override(tmp_path, monkeypatch):
    """Ensures CHROME_PATH and BROWSER_PATH environment variable overrides take highest priority."""
    dummy_browser = tmp_path / "custom_chrome.exe"
    dummy_browser.write_text("dummy binary", encoding="utf-8")

    # 1. Test CHROME_PATH
    monkeypatch.setenv("CHROME_PATH", str(dummy_browser))
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    assert find_browser_executable() == str(dummy_browser)

    # 2. Test BROWSER_PATH
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.setenv("BROWSER_PATH", str(dummy_browser))
    assert find_browser_executable() == str(dummy_browser)


def test_find_browser_executable_windows_chrome(monkeypatch, tmp_path):
    """Verifies that on Windows, Google Chrome in Program Files is prioritized."""
    fake_chrome = tmp_path / "Program Files" / "Google" / "Chrome" / "Application" / "chrome.exe"
    fake_chrome.parent.mkdir(parents=True)
    fake_chrome.write_text("dummy chrome", encoding="utf-8")

    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Program Files (x86)"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert find_browser_executable() == str(fake_chrome)


def test_find_browser_executable_windows_edge_fallback(monkeypatch, tmp_path):
    """Verifies that on Windows, if Chrome is absent, Microsoft Edge is discovered as fallback."""
    fake_edge = tmp_path / "Program Files (x86)" / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    fake_edge.parent.mkdir(parents=True)
    fake_edge.write_text("dummy edge", encoding="utf-8")

    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Program Files (x86)"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert find_browser_executable() == str(fake_edge)


def test_find_browser_executable_windows_playwright_fallback(monkeypatch, tmp_path):
    """Verifies that on Windows, if standard browsers are absent, Playwright Chromium is found."""
    fake_pw_chrome = tmp_path / "LocalAppData" / "ms-playwright" / "chromium-1234" / "chrome-win64" / "chrome.exe"
    fake_pw_chrome.parent.mkdir(parents=True)
    fake_pw_chrome.write_text("dummy playwright chrome", encoding="utf-8")

    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "NonexistentPF"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "NonexistentPF86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))

    assert find_browser_executable() == str(fake_pw_chrome)


def test_find_browser_executable_windows_path_fallback(monkeypatch, tmp_path):
    """Verifies that on Windows, if no absolute candidates exist, PATH lookup is performed."""
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Empty"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "Empty"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Empty"))

    with patch("shutil.which", side_effect=lambda cmd: r"C:\Custom\msedge.exe" if "msedge" in cmd else None):
        assert find_browser_executable() == r"C:\Custom\msedge.exe"


def test_find_browser_executable_macos(monkeypatch, tmp_path):
    """Verifies that on macOS, Google Chrome in /Applications is detected."""
    fake_mac_chrome = tmp_path / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    fake_mac_chrome.parent.mkdir(parents=True)
    fake_mac_chrome.write_text("dummy mac chrome", encoding="utf-8")

    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")

    with patch("os.path.exists", side_effect=lambda p: str(p) == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        assert find_browser_executable() == "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def test_find_browser_executable_linux(monkeypatch):
    """Verifies that on Linux, PATH binary lookup resolves chromium or google-chrome."""
    monkeypatch.delenv("CHROME_PATH", raising=False)
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")

    with patch("shutil.which", side_effect=lambda cmd: "/usr/bin/google-chrome-stable" if cmd == "google-chrome-stable" else None):
        assert find_browser_executable() == "/usr/bin/google-chrome-stable"
