@echo off
REM cleanup.bat | HBMR v2.5.2 | 2026-06-18 PDT

cd /d "%~dp0"

echo.
echo HBMR cleanup
echo.

python cleanup.py

echo.
echo Cleanup session complete.
echo.

REM Optional:
REM pause