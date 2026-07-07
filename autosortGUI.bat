@echo off
rem autosortGUI.bat | HBMR / Birdbill AutoSort Probe v0.1.2 | 2026-06-25 PDT
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0hbmr-env\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto run

set "PYTHON_EXE=D:\HBMR\hbmr-env\Scripts\python.exe"
if exist "%PYTHON_EXE%" goto run

set "PYTHON_EXE=python"

:run
echo Using Python: %PYTHON_EXE%
"%PYTHON_EXE%" "%~dp0autosortGUI.py"
if errorlevel 1 pause
endlocal
