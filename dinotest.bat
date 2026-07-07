@echo off
REM dinotest.bat | HBMR DINOv2 probe launcher v0.1.0 | 2026-06-18 PDT

cd /d "%~dp0"

echo.
echo HBMR DINOv2 probe
echo Drag one crop image onto this file.
echo.

if "%~1"=="" (
    echo No image provided.
    echo.
    pause
    exit /b 1
)

python dinotest.py %*

echo.
pause