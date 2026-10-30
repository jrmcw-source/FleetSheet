#!/usr/bin/env python3
"""FleetSheet-Launcher.py — open FleetSheet in its own dedicated browser window.

Windows-only. Standalone, stdlib-only (no dependencies).

What it does:
  1. Waits for the FleetSheet server to answer on http://127.0.0.1:8765.
  2. Finds a Chromium browser: Chrome -> Edge -> Brave -> system default.
  3. Uses the dedicated FleetSheet browser profile
     (%LOCALAPPDATA%\\FleetSheet\\profile): created clean on first
     launch — no extensions, no tabs, no synced state — and kept
     afterwards, so the operator's own window state (zoom, size)
     persists between launches. The profile serves FleetSheet only,
     so nothing foreign accumulates in it.
  4. Opens the app in --app mode (chromeless window, own taskbar entry).
  5. Verifies via the process list that the browser is actually running on
     OUR profile dir. If not confirmed within 5 seconds, falls back to the
     system default browser (`start <url>`).

Usage:
    pythonw.exe FleetSheet-Launcher.py [url]

The installer (FleetSheet.iss) ships this next to pythonw.exe; the
FleetSheet-Start.py bootstrap starts the server first, then runs this.
Set FLEETSHEET_NO_AUTO_OPEN=1 when starting app.py so the server does not
open its own (older) window in parallel.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765"
VERIFY_TIMEOUT_S = 5.0


def _fail(msg):
    """Show a message box on failure (pythonw has no console)."""
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "FleetSheet", 0x10)
    except Exception:
        pass


def wait_for_server(url, timeout=30):
    """Block until url answers or the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def profile_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "FleetSheet", "profile")


def find_chromium():
    """Locate a Chromium browser in priority order.

    Returns (exe_path, exe_name) or (None, None).
    """
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    lad = os.environ.get("LocalAppData", "")
    candidates = [
        # 1. Chrome (fastest-ranked 2025-2026, primary pick)
        (os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"), "chrome.exe"),
        (os.path.join(pf86, "Google", "Chrome", "Application", "chrome.exe"), "chrome.exe"),
        (os.path.join(lad, "Google", "Chrome", "Application", "chrome.exe"), "chrome.exe"),
        # 2. Edge (preinstalled on Windows 10/11, near-Chrome speed)
        (os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"), "msedge.exe"),
        (os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"), "msedge.exe"),
        (os.path.join(lad, "Microsoft", "Edge", "Application", "msedge.exe"), "msedge.exe"),
        # 3. Brave
        (os.path.join(pf, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"), "brave.exe"),
        (os.path.join(pf86, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"), "brave.exe"),
        (os.path.join(lad, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"), "brave.exe"),
    ]
    for path, name in candidates:
        if path and os.path.isfile(path):
            return path, name
    # PATH fallback
    for name in ("chrome.exe", "msedge.exe", "brave.exe"):
        hit = shutil.which(name)
        if hit:
            return hit, name
    return None, None


def fresh_profile(profile):
    """Ensure the profile dir exists, and leave its contents alone.

    First launch creates the dir clean — no extensions, no tabs, no
    synced state. Later launches KEEP it: the profile is dedicated to
    FleetSheet, so nothing foreign accumulates in it, and what the
    operator sets in the window (zoom, size) is still set next time.
    If a browser is already running on this profile, the new launch
    hands its window to that process, exactly as before. Returns
    False only if the dir cannot be created.
    """
    if _profile_in_use_by_name(profile):
        # A previous FleetSheet window is still open on our profile.
        # The new launch will hand a window to that process.
        return True
    try:
        os.makedirs(profile, exist_ok=True)
        return True
    except Exception:
        return False


def _profile_in_use_by_name(profile):
    """Cheap pre-check: is our profile string in any process command line?"""
    return bool(_pids_with_profile(profile))


def _pids_with_profile(profile):
    """PIDs of processes whose command line mentions the profile dir."""
    pids = []
    lines = _process_lines()
    me = os.getpid()
    needle = profile.lower()
    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid != me and needle in parts[1].lower():
            pids.append(pid)
    return pids


def _process_lines():
    """ProcessId + CommandLine lines on Windows."""
    cmds = [
        ["wmic", "process", "get", "ProcessId,CommandLine", "/format:csv"],
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | ForEach-Object {"
         " '{0} {1}' -f $_.ProcessId, $_.CommandLine }"],
    ]
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=20,
                                 creationflags=subprocess.CREATE_NO_WINDOW
                                 ).stdout.splitlines()
            lines = [ln for ln in out
                     if ln.strip() and not ln.lstrip().startswith("Node")]
            if lines:
                return lines
        except Exception:
            continue
    return []


def _work_area():
    """(width, height) of the screen's work area, or None when it
    cannot be read."""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        rect = RECT()
        # SPI_GETWORKAREA = 0x0030.
        if not ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0):
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None
        return (width, height)
    except Exception:
        return None


def _window_size():
    """(width, height) for the app window: the standing 1280x900,
    shrunk to the work area when the work area is smaller — a scaled
    or small display never gets a window larger than the screen.
    Falls back to 1280x900 when the work area cannot be read."""
    area = _work_area()
    if area is None:
        return (1280, 900)
    return (min(1280, area[0]), min(900, area[1]))


def launch_app_window(exe, profile, url):
    width, height = _window_size()
    args = ["--app=" + url,
            "--user-data-dir=" + profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=%d,%d" % (width, height)]
    try:
        subprocess.Popen([exe] + args,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def verify_on_profile(profile, timeout=VERIFY_TIMEOUT_S):
    """True if some process command line mentions our profile dir within
    the timeout. This proves the browser honored --user-data-dir (a launch
    that silently handed off to the user's everyday profile would NOT
    match)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _pids_with_profile(profile):
            return True
        time.sleep(0.4)
    return False


def fallback_default_browser(url):
    """Last resort: open in whatever the system default browser is."""
    try:
        os.startfile(url)
        return True
    except Exception:
        try:
            subprocess.run(["cmd", "/c", "start", "", url],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            return True
        except Exception:
            return False


def main(argv):
    if not sys.platform.startswith("win"):
        _fail("FleetSheet-Launcher.py is Windows-only.")
        return 1
    url = argv[1] if len(argv) > 1 else DEFAULT_URL

    if not wait_for_server(url, timeout=30):
        _fail("FleetSheet did not start.\n\nThe server is not answering at "
              + url + ".\nTry starting FleetSheet again; if it persists, "
              "the install may be damaged — reinstall it.")
        return 1

    exe, exe_name = find_chromium()
    profile = profile_dir()

    if exe:
        fresh_profile(profile)
        if launch_app_window(exe, profile, url):
            if verify_on_profile(profile):
                return 0
            # Launched but not on our profile (or died at once) — fall through
            # to the default browser rather than stranding the user.

    if fallback_default_browser(url):
        return 0

    _fail("FleetSheet could not open a browser window.\n\n"
          "The server may be running at " + url + " —\n"
          "open that address in your browser manually.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
