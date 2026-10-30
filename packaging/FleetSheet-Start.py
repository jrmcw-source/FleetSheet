#!/usr/bin/env python3
"""FleetSheet-Start.py — start FleetSheet, with no console window.

Windows-only. Standalone, stdlib-only (no dependencies). This is the
installed Start Menu / desktop target: FleetSheet.iss points the
shortcuts at pythonw.exe running this file, so the whole start runs
silent — no console window at any step. FleetSheet-Start.bat remains
in the install as a manual fallback that does the same work from a
visible console.

What it does, in the order the .bat did it:
  1. Stops any stale FleetSheet server LISTENING on port 8765 (a
     previous session's server would otherwise serve the old code),
     then gives the port a beat to free.
  2. Checks the install is whole (pythonw.exe beside this file,
     app\\app.py present); a failed check shows a message box and
     exits, the same wording the .bat's popups used.
  3. Starts the server: pythonw.exe app\\app.py, with
     FLEETSHEET_NO_AUTO_OPEN=1 in its environment so app.py does
     not open its own window — the launcher is the only opener.
  4. Starts FleetSheet-Launcher.py under pythonw.exe, which waits
     for the server itself and opens the dedicated browser window.

Usage:
    pythonw.exe FleetSheet-Start.py
"""

import ctypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = "8765"


def _fail(msg):
    """Show a message box on failure (pythonw has no console)."""
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "FleetSheet", 0x10)
    except Exception:
        pass


def _stop_stale_server():
    """Kill whatever LISTENs on our port, mirroring the .bat: netstat
    -ano, the LISTENING lines for the port, taskkill on the PID."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout
    except Exception:
        return
    for line in out.splitlines():
        parts = line.split()
        # TCP rows: Proto, Local Address, Foreign Address, State, PID.
        if len(parts) != 5 or parts[3] != "LISTENING":
            continue
        if parts[1].rsplit(":", 1)[-1] != PORT:
            continue
        pid = parts[4]
        if pid and pid != "0":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/PID", pid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
    # Give the port a beat to actually free.
    time.sleep(1)


def main():
    if not sys.platform.startswith("win"):
        _fail("FleetSheet-Start.py is Windows-only.")
        return 1

    pythonw = os.path.join(HERE, "pythonw.exe")
    app_py = os.path.join(HERE, "app", "app.py")
    launcher_py = os.path.join(HERE, "FleetSheet-Launcher.py")

    _stop_stale_server()

    if not os.path.isfile(pythonw):
        _fail("FleetSheet is damaged: pythonw.exe is missing next to "
              "this file.\n\nReinstall FleetSheet.")
        return 1
    if not os.path.isfile(app_py):
        _fail("FleetSheet is damaged: app\\app.py is missing."
              "\n\nReinstall FleetSheet.")
        return 1

    env = dict(os.environ)
    env["FLEETSHEET_NO_AUTO_OPEN"] = "1"

    # Server: hidden, no console. It writes fleetsheet-server.log on
    # failure.
    subprocess.Popen([pythonw, app_py], cwd=HERE, env=env,
                     creationflags=subprocess.CREATE_NO_WINDOW)

    # Browser window (the launcher waits for the server itself, then
    # verifies the window is on the dedicated profile).
    subprocess.Popen([pythonw, launcher_py], cwd=HERE, env=env,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return 0


if __name__ == "__main__":
    sys.exit(main())
