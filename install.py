#!/usr/bin/env python3
"""FleetSheet one-click setup.

Lives in app/ and is called by launcher.bat (Windows, hidden, via
FleetSheet.exe) or FleetSheet.command (Mac). No internet needed - every
package ships in the packages/ folder.

Modes:
  install.py --quiet            install packages + seed demo DB, minimal output
  install.py --launch           full one-click flow: setup, start the app
                                hidden in the background, open the app window
  install.py --open-when-ready  wait for http://127.0.0.1:8765 then open it
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))  # the app/ folder
URL = "http://127.0.0.1:8765"
SERVER_LOG = os.path.join(ROOT, "fleetsheet-server.log")
LAUNCH_LOG = os.path.join(ROOT, "fleetsheet-launch.log")

QUIET = "--quiet" in sys.argv or "--launch" in sys.argv


def trace(msg):
    """Timestamped stage marker so a silent run still leaves footprints."""
    try:
        import datetime
        with open(LAUNCH_LOG, "a") as f:
            f.write("%s %s\n" % (datetime.datetime.now().isoformat(
                sep=" ", timespec="seconds"), msg))
    except Exception:
        pass


_splash = None
_splash_label = None


def splash_show():
    """A small 'starting...' window with a moving bar, so a hidden launch
    doesn't look dead. Purely cosmetic: any failure here is ignored."""
    global _splash, _splash_label
    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        root.title("FleetSheet")
        root.resizable(False, False)
        root.configure(bg="#021639")
        root.geometry("360x130")
        try:
            root.eval("tk::PlaceWindow . center")
        except Exception:
            pass
        lbl = tk.Label(root, text="Starting FleetSheet...",
                       bg="#021639", fg="white",
                       font=("Segoe UI", 11))
        lbl.pack(pady=(24, 12))
        bar = ttk.Progressbar(root, mode="indeterminate", length=280)
        bar.pack(pady=(0, 24))
        bar.start(12)
        root.update()
        _splash, _splash_label = root, lbl
    except Exception:
        _splash = None


def splash_say(msg):
    try:
        if _splash_label is not None:
            _splash_label.config(text=msg)
        if _splash is not None:
            _splash.update()
    except Exception:
        pass


def splash_hide():
    global _splash, _splash_label
    try:
        if _splash is not None:
            _splash.destroy()
    except Exception:
        pass
    _splash = _splash_label = None


def alert(msg):
    """Show a visible error dialog on Windows (the launcher runs hidden)."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "FleetSheet", 0x10)
    except Exception:
        pass


def fail(msg):
    print("ERROR: " + msg)
    trace("FAIL: " + msg)
    splash_hide()
    alert("FleetSheet setup failed:\n\n" + msg)
    sys.exit(1)


def log(msg):
    print(msg)


def server_is_up():
    import urllib.request
    try:
        urllib.request.urlopen(URL, timeout=2)
        return True
    except Exception:
        return False


def app_version():
    """This build's stamp, from the VERSION file next to install.py."""
    try:
        with open(os.path.join(ROOT, "VERSION"), "r", encoding="ascii") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


def server_version():
    """Stamp of the server answering on :8765.

    None = nothing answering. "unknown" = answering but predates the
    /version endpoint (an old build) — always treated as a mismatch.
    """
    import urllib.request
    import json
    try:
        with urllib.request.urlopen(URL + "/version", timeout=2) as r:
            return json.loads(r.read().decode("ascii")).get("version") or "unknown"
    except Exception:
        pass
    return "unknown" if server_is_up() else None


def stop_server_on_port():
    """Kill whatever owns :8765 (a stale FleetSheet server from another
    build), then wait for the port to free. Best effort — the caller
    re-checks before starting a fresh server."""
    import subprocess
    import time
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True,
                timeout=10).stdout
            pids = set()
            for line in out.splitlines():
                if ":8765" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit() and parts[-1] != "0":
                        pids.add(parts[-1])
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid],
                               capture_output=True, timeout=10)
        else:
            pid = None
            try:
                out = subprocess.run(
                    ["lsof", "-ti", ":8765"], capture_output=True, text=True,
                    timeout=10).stdout
                pid = (out.split() or [None])[0]
            except Exception:
                pid = None
            if pid and pid.isdigit():
                import signal
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except OSError:
                    pass
        for _ in range(30):
            if server_version() is None:
                return True
            time.sleep(0.5)
    except Exception as e:
        trace("stop_server_on_port: %s" % e)
    return server_version() is None


def open_browser():
    splash_hide()
    mode = "none"
    try:
        import appmode
        mode = appmode.open_app_window(URL)
        trace("app window opened via appmode")
    except Exception as e:
        trace("appmode open failed: %r - trying default browser" % e)
        try:
            import webbrowser
            ok = webbrowser.open(URL)
            trace("webbrowser.open returned %r" % ok)
            mode = "browser" if ok else "none"
        except Exception as e2:
            trace("webbrowser.open failed: %r" % e2)
    if mode == "none":
        # The server IS running - only the window failed. Say so loudly
        # instead of leaving the user staring at nothing. (2026-10-06)
        trace("no window could be opened - server is up, showing URL")
        alert("FleetSheet is running, but no window could be opened.\n\n"
              "Open your browser and go to:\n" + URL)


def open_when_ready(timeout=60):
    import time
    import urllib.request
    ready = False
    trace("waiting for server at %s" % URL)
    for _ in range(timeout):
        try:
            urllib.request.urlopen(URL, timeout=2)
            ready = True
            break
        except Exception:
            splash_say("Waiting for FleetSheet to answer...")
            time.sleep(1)
    if ready:
        trace("server answered - opening app window")
        open_browser()
    else:
        # Never open a dead window: say so instead, and point at the log.
        fail("The FleetSheet server did not start (no answer at %s).\n\n"
             "A startup log was saved to:\n%s" % (URL, SERVER_LOG))


def do_install():
    # 1. Python version check.
    if sys.version_info < (3, 10):
        fail("FleetSheet needs Python 3.10 or newer (you have %s)."
             % sys.version.split()[0])

    # 2. Pick the package folder for this computer.
    if sys.platform.startswith("win"):
        osdir = "windows"
    elif sys.platform.startswith("darwin"):
        osdir = "macos"
    else:
        osdir = "linux"
    pkgdirs = [os.path.join(ROOT, "packages", "common"),
               os.path.join(ROOT, "packages", osdir)]
    for d in pkgdirs:
        if not os.path.isdir(d):
            fail("Missing packages folder: %s" % d)
    log("Setting up FleetSheet for this computer...")
    trace("installing helper packages from local folders")
    splash_say("Setting up components...")

    # 3. Install the helper packages from the local folders.
    def pip_install(extra=()):
        cmd = [sys.executable, "-m", "pip", "install", "--no-index"]
        for d in pkgdirs:
            cmd += ["--find-links", d]
        cmd += list(extra)
        cmd += ["segno", "pypdf", "reportlab"]
        return subprocess.run(cmd, capture_output=True, text=True)

    r = pip_install()
    if r.returncode != 0 and "externally-managed-environment" in (r.stderr or ""):
        # Some Linux distros block system-wide pip installs (PEP 668).
        log("System Python is protected - retrying with override...")
        r = pip_install(extra=("--break-system-packages",))
    if r.returncode != 0:
        print(r.stderr[-1500:] if r.stderr else "")
        fail("Package install failed.")

    # 4. Verify the imports.
    try:
        import segno, pypdf, reportlab  # noqa: F401
    except ImportError as e:
        fail("A package did not import correctly: %s" % e)
    log("Components ready.")

    # 5. Seed the sample database on first run (Bayou demo).
    db = os.path.join(ROOT, "fleetsheet.db")
    demo = os.path.join(ROOT, "demo.db")
    seeded = os.path.join(ROOT, ".demo_seeded")
    # Seed the shipped demo only on the very first install.  Once the user
    # deliberately deletes fleetsheet.db to start a real blank yard, do not
    # silently put the demo book back on the next launch.  The marker is
    # created after a successful seed and is intentionally absent from the
    # distributable package.  Copy demo.db over fleetsheet.db remains the
    # explicit way to reset training data.
    if not os.path.exists(db) and os.path.exists(demo) and not os.path.exists(seeded):
        shutil.copy(demo, db)
        try:
            with open(seeded, "w", encoding="ascii") as f:
                f.write("demo seeded\n")
        except OSError:
            pass
        log("Sample database ready (Bayou demo).")


def do_launch():
    """One-click flow: install, run the app hidden, open the app window."""
    splash_show()
    splash_say("Starting FleetSheet...")
    trace("launch started (python %s)" % sys.version.split()[0])
    do_install()
    trace("install stage done")
    v = server_version()
    if v is not None:
        if v == app_version():
            trace("server already up - opening app window")
            log("FleetSheet is already running - opening it.")
            open_browser()
            return
        # A different build's server is on the port ("new window, old guts").
        # Only restart when the running server is OLDER than this build.
        # An older launcher must never kill a newer server - otherwise two
        # installs fight and the last click wins. (2026-10-06)
        mine = app_version()
        if v == "unknown" or v < mine:
            trace("server version %r < build %r - restarting it" % (v, mine))
            log("A different FleetSheet version is running - restarting it.")
            splash_say("Restarting FleetSheet...")
            if not stop_server_on_port():
                fail("Could not stop the running FleetSheet server. "
                     "Close it and try again.")
        else:
            trace("server version %r is newer than build %r - leaving it" % (v, mine))
            log("A newer FleetSheet is already running - opening it.")
            open_browser()
            return
    # Start the server detached with no console window of its own.
    # Its output goes to a log file so a startup crash leaves evidence.
    env = dict(os.environ)
    env["FLEETSHEET_NO_AUTO_OPEN"] = "1"  # the launcher opens the window
    # Windows defaults redirected stdout to cp1252, which chokes on any
    # non-ASCII print (e.g. the -> arrow in app.py's startup line) and
    # kills the server before it binds. Force UTF-8 everywhere.
    env["PYTHONUTF8"] = "1"
    server_log = open(SERVER_LOG, "ab")
    server_log.write(b"--- FleetSheet server start ---\n")
    server_log.flush()
    kwargs = dict(
        cwd=ROOT,
        stdout=server_log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, env=env,
    )
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, os.path.join(ROOT, "app.py")], **kwargs)
    trace("server process started - waiting for it to answer")
    splash_say("Waiting for FleetSheet to answer...")
    log("Starting FleetSheet - opening its window in a moment...")
    open_when_ready()


if "--open-when-ready" in sys.argv:
    open_when_ready()
elif "--launch" in sys.argv:
    do_launch()
else:
    do_install()
    if not QUIET:
        print()
        print("Done.")
