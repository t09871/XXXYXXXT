@echo off
REM dinosim.bat | HBMR DINOv2 batch similarity launcher v0.2.0 | 2026-06-18 PDT

cd /d "%~dp0"

echo.
echo HBMR DINOv2 batch similarity probe
echo Drag TWO OR MORE crop images onto this file.
echo.

if "%~2"=="" (
    echo Need at least two image crops.
    echo.
    pause
    exit /b 1
)

python dinosim.py %*

echo.
pause