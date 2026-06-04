@echo off
REM Doble clic para detener backend + frontend + tunel.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo.
pause
