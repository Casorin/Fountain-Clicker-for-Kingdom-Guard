@echo off
setlocal EnableExtensions EnableDelayedExpansion

pushd "%~dp0"
if errorlevel 1 (
    echo ERROR: Cannot open project directory.
    pause
    exit /b 1
)

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher was not found.
    echo Install 64-bit Python 3 from python.org and try again.
    popd
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 goto install_error
)

echo Updating pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto install_error

echo Installing pinned dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto install_error

echo Preparing OCR models...
".venv\Scripts\python.exe" scripts\prepare_ocr_models.py
if errorlevel 1 goto install_error

echo.
echo Installation completed successfully.
echo You can now run the monitor launcher BAT.
popd
pause
exit /b 0

:install_error
set "RC=!ERRORLEVEL!"
echo.
echo ERROR: Installation failed with code !RC!.
popd
pause
exit /b !RC!
