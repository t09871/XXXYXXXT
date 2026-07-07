@echo off
rem lightgluetest.bat | HBMR / Birdbill LightGlue probe v0.2.0 | 2026-06-23 PDT
rem Drag exactly two crop images onto this file.
rem This launcher does not modify the HBMR database.

cd /d "%~dp0"

echo HBMR / Birdbill LightGlue pair probe
echo ====================================
echo.

if "%~1"=="" (
    echo Drag exactly two crop images onto this BAT file.
    echo.
    pause
    exit /b 1
)

if "%~2"=="" (
    echo Only one image was supplied.
    echo Drag exactly two crop images onto this BAT file.
    echo.
    pause
    exit /b 1
)

if not "%~3"=="" (
    echo More than two files were supplied.
    echo Drag exactly two crop images only.
    echo.
    pause
    exit /b 1
)

python lightgluetest.py "%~1" "%~2"

echo.
pause
