@echo off
REM mmpose.bat | HBMR / Birdbill MMPose Probe v0.1.1 | 2026-06-25 PDT
cd /d "%~dp0"
call "C:\Users\autom\miniconda3\condabin\conda.bat" activate openmmlab
python mmposeGUI.py
