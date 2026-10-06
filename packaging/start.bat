@echo off
setlocal EnableExtensions
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".python\pythonw.exe" (
    echo ERROR: Extract the complete archive before starting.
    pause
    popd
    exit /b 1
)
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
start "" ".python\pythonw.exe" -I "scripts\launch_portable.py"
popd
exit /b 0
