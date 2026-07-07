@echo off
REM HBMR.bat | HBMR v2.5.9 AutoName venv launcher | 2026-06-25 PDT

cd /d "%~dp0"

set "HBMRPY=%~dp0hbmr-env\Scripts\python.exe"

echo.
echo HBMR v2.5.9 AutoName
echo Detect -> AutoName -> Review Outputs -> Profiles
echo.

if not exist "%HBMRPY%" (
    echo ERROR: HBMR venv Python not found:
    echo %HBMRPY%
    pause
    exit /b 1
)

if "%~1"=="" (
    echo Drag a video file or folder onto HBMR.bat
    timeout /t 3 >nul
    exit /b
)

echo Step 1: Detecting birds and assigning AutoName identities...
"%HBMRPY%" main.py %*

echo.
echo Step 2: Updating review outputs...
"%HBMRPY%" review.py

echo.
echo Step 3: Building profiles...
"%HBMRPY%" profiles.py

echo.
echo Opening profiles...

echo.
echo HBMR complete.
echo.
pause