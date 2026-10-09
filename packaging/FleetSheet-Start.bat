@echo off
rem FleetSheet-Start.bat — installed Start Menu / desktop target.
rem   1. Stops any stale FleetSheet server on port 8765.
rem   2. Starts the server hidden (pythonw = no console window).
rem   3. Runs FleetSheet-Launcher.py, which waits for the server and opens
rem      the dedicated clean browser window (or falls back gracefully).
rem FLEETSHEET_NO_AUTO_OPEN=1 suppresses app.py's own appmode window so the
rem new launcher is the ONLY window opener (no double windows).
setlocal
cd /d "%~dp0"

set FLEETSHEET_NO_AUTO_OPEN=1

rem Stale server from a previous session/version on our port? Stop it, so
rem the window always shows THIS install's code ("new window, old guts"
rem can never happen).
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%p >nul 2>&1
)
rem Give the port a beat to actually free.
timeout /t 1 /nobreak >nul

if not exist "pythonw.exe" (
  powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $ws.Popup('FleetSheet is damaged: pythonw.exe is missing next to this file.' + \"`n`n\" + 'Reinstall FleetSheet.', 0, 'FleetSheet', 16)"
  exit /b 1
)
if not exist "app\app.py" (
  powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $ws.Popup('FleetSheet is damaged: app\app.py is missing.' + \"`n`n\" + 'Reinstall FleetSheet.', 0, 'FleetSheet', 16)"
  exit /b 1
)

rem Server: hidden, no console. It writes fleetsheet-server.log on failure.
start "FleetSheet server" /min pythonw.exe "app\app.py"

rem Browser window (waits for the server, verifies the clean profile).
pythonw.exe "FleetSheet-Launcher.py"
exit /b 0
