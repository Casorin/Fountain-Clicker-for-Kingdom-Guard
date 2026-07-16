@echo off
setlocal EnableExtensions EnableDelayedExpansion

pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Cannot open project directory.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Dependencies are not installed.
    echo Run the dependency installer BAT first.
    popd
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m app.ui
set "RC=!ERRORLEVEL!"
popd

if not "!RC!"=="0" (
    echo.
    echo Program exited with code !RC!.
    pause
)

exit /b !RC!
