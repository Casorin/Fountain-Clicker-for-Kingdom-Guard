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

if not exist "runtime" mkdir "runtime"
".venv\Scripts\python.exe" -m app.ui >>"runtime\launcher_stdout.log" 2>>"runtime\launcher_stderr.log"
set "RC=!ERRORLEVEL!"
popd

if not "!RC!"=="0" (
    echo.
    echo Program exited with code !RC!.
    echo Startup error log: runtime\launcher_stderr.log
    type "runtime\launcher_stderr.log"
    pause
)

exit /b !RC!
