@echo off
rem FleetSheet hidden launcher - started by FleetSheet.exe, no window shown.
setlocal
cd /d "%~dp0"

call :findpython
if not defined PYCMD (
  call :getpython
  call :findpython
)
if not defined PYCMD goto nopython

%PYCMD% install.py --launch
exit /b

:findpython
set PYCMD=
for %%p in (python py) do (
  for /f "delims=" %%v in ('%%p --version 2^>^&1') do (
    echo %%v | findstr /b "Python 3.1" >nul && set PYCMD=%%p && goto :eof
  )
)
for %%d in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "C:\Python312\python.exe" "C:\Python313\python.exe" "%ProgramFiles%\Python312\python.exe" "%ProgramFiles%\Python313\python.exe") do (
  if exist %%~d (
    for /f "delims=" %%v in ('"%%~d" --version 2^>^&1') do (
      echo %%v | findstr /b "Python 3.1" >nul && set PYCMD="%%~d" && goto :eof
    )
  )
)
goto :eof

:getpython
where winget >nul 2>&1 || goto :eof
winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
goto :eof

:nopython
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $ws.Popup('FleetSheet could not install Python automatically.' + \"`n`n\" + 'Please install Python 3.10 or newer (free) from https://www.python.org/downloads/ and then double-click FleetSheet again.', 0, 'FleetSheet', 64)"
exit /b 1
