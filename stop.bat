@echo off
setlocal
cd /d "%~dp0"

echo Stopping YouDownloader...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop.ps1" %*
if errorlevel 1 (
  echo.
  echo Stop failed. Details are shown above.
  pause
  exit /b 1
)

echo.
echo YouDownloader stop completed.
pause
