@echo off
rem autorefineGUI.bat | HBMR / Birdbill AutoRefine Probe v0.1.0 | 2026-06-25 PDT
setlocal
cd /d "%~dp0"

set "OPENMMLAB_PYTHON=C:\Users\autom\miniconda3\envs\openmmlab\python.exe"

if not exist "%OPENMMLAB_PYTHON%" (
    echo ERROR: OpenMMLab Python interpreter not found:
    echo %OPENMMLAB_PYTHON%
    echo.
    echo Edit autorefineGUI.bat and set OPENMMLAB_PYTHON to your validated MMPose environment.
    pause
    exit /b 1
)

if not exist "autorefineGUI.py" (
    echo ERROR: autorefineGUI.py not found in:
    cd
    echo.
    echo Put autorefineGUI.py in the same folder as this BAT file.
    pause
    exit /b 1
)

"%OPENMMLAB_PYTHON%" "autorefineGUI.py" %*

if errorlevel 1 (
    echo.
    echo AutoRefine GUI exited with an error.
    pause
)
