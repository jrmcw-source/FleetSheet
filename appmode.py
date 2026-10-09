#!/usr/bin/env python3
"""FleetSheet app-mode window: open FleetSheet in its own dedicated window.

Instead of a tab in the user's everyday browser, this launches Chrome/Edge
in --app mode with a FleetSheet-only profile: no tabs, no address bar, no
extensions — it looks and feels like a standalone desktop app.

Falls back to the default browser when no Chromium-based browser is found.

Usage:
    python appmode.py [url]      # default http://127.0.0.1:8765
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser

DEFAULT_URL = "http://127.0.0.1:8765"


def profile_dir():
    """Per-OS home for the FleetSheet browser profile (kept separate from
    the user's everyday browser so the app window is truly its own)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "FleetSheet", "app-profile")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", "FleetSheet", "app-profile")
    return os.path.join(os.path.expanduser("~"), ".config",
                        "FleetSheet", "app-profile")


def find_chromium():
    """Locate a Chromium-based browser. Returns an executable path, or on
    macOS the application name for `open -a`. Returns None if not found."""
    if sys.platform.startswith("win"):
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for name in ("chrome", "msedge"):
            hit = shutil.which(name)
            if hit:
                candidates.append(hit)
        for c in candidates:
            if c and os.path.isfile(c):
                return c
        return None
    if sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Chromium"):
            if os.path.isdir("/Applications/%s.app" % app):
                return app
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "microsoft-edge", "microsoft-edge-stable"):
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def wait_for_server(url, timeout=25):
    """Block until url answers or the timeout expires. Returns True/False."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def find_profile_pids(profile):
    """PIDs of processes whose command line mentions the FleetSheet profile
    directory. Used to spot a pre-existing browser on our profile (in which
    case a fresh launch just hands the window off and exits at once, so
    there is no process to watch) and, on macOS, to poll for the app
    window's process. Returns [] when the process list can't be read."""
    pids = []
    try:
        if sys.platform.startswith("win"):
            lines = _windows_process_lines()
        else:
            out = subprocess.run(["ps", "-eo", "pid,args"],
                                 capture_output=True, text=True,
                                 timeout=15).stdout.splitlines()
            lines = out[1:]  # drop the "PID COMMAND" header
        me = os.getpid()
        for line in lines:
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            if pid != me and profile in parts[1]:
                pids.append(pid)
    except Exception:
        return []
    return pids


def _windows_process_lines():
    """ProcessId + CommandLine lines on Windows, 'pid rest...' shaped."""
    cmds = [
        ["wmic", "process", "get", "ProcessId,CommandLine", "/format:csv"],
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | ForEach-Object {"
         " '{0} {1}' -f $_.ProcessId, $_.CommandLine }"],
    ]
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True,
                                 timeout=20).stdout.splitlines()
            lines = [ln for ln in out
                     if ln.strip() and not ln.lstrip().startswith("Node")]
            if lines:
                return lines
        except Exception:
            continue
    return []


def profile_in_use(profile):
    """True when some browser process is already running on the FleetSheet
    profile directory."""
    return bool(find_profile_pids(profile))


def _launch_args(exe, profile, url):
    return ["--app=" + url,
            "--user-data-dir=" + profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,900"]


def _launch_detached(exe, profile, url):
    """Fire-and-forget launch (used when there is no process to watch)."""
    args = _launch_args(exe, profile, url)
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-n", "-a", exe, "--args"] + args,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen([exe] + args,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)


def open_app_window_proc(url=DEFAULT_URL):
    """Open url in FleetSheet's own window. Returns (mode, handle):

    - mode 'appmode': the dedicated Chromium --app window opened.
    - mode 'browser': fell back to the default browser (no window to watch).
    - mode 'none': nothing worked.

    handle is the browser's subprocess.Popen on Windows/Linux when this
    launch owns the app window's process — the caller can wait() on it to
    learn the moment the window closes. It is the string "poll" on macOS
    (``open -n`` gives no handle; poll find_profile_pids instead), and None
    when there is nothing to watch: default-browser fallback, failure, or a
    pre-existing browser already on the FleetSheet profile (the new client
    hands the window off and exits at once, so waiting on it would be an
    instant false "window closed").
    """
    # Never open a dead window: wait for the server to answer first.
    wait_for_server(url)
    exe = find_chromium()
    if exe:
        profile = profile_dir()
        try:
            os.makedirs(profile, exist_ok=True)
        except Exception:
            pass
        try:
            if profile_in_use(profile):
                _launch_detached(exe, profile, url)
                return "appmode", None
            if sys.platform == "darwin":
                _launch_detached(exe, profile, url)
                return "appmode", "poll"
            p = subprocess.Popen([exe] + _launch_args(exe, profile, url),
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL)
            return "appmode", p
        except Exception:
            pass
    try:
        webbrowser.open(url)
        return "browser", None
    except Exception:
        return "none", None


def open_app_window(url=DEFAULT_URL):
    """Open url in FleetSheet's own window. Returns 'appmode', 'browser'
    (fallback), or 'none' (nothing worked)."""
    mode, _handle = open_app_window_proc(url)
    return mode


def main(argv):
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    mode = open_app_window(url)
    print("opened via %s" % mode)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
