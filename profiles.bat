@echo off
REM profiles.bat | MR / HBMR v2.4.0 | 2026-06-18 PDT

cd /d "%~dp0"

echo.
echo MR / HBMR v2.4.0
echo Building profiles...
echo.

python profiles.py

echo.
pause