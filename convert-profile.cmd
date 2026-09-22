@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 tools\convert_profile.py --gui --lang ru
) else (
    python tools\convert_profile.py --gui --lang ru
)
if errorlevel 1 (
    echo Install Python 3.10+ with tkinter, or see docs/CONVERTER.en.md.
    pause
)
