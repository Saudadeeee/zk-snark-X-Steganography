@echo off
chcp 65001 >nul
REM Setup script for ZK-Schnorr Verifier Package (Windows)

echo ================================================================
echo   ZK-Schnorr Verifier Package - Auto Setup
echo ================================================================
echo.

REM Find Python with pip
echo [1/4] Finding Python with pip...

set PYTHON_CMD=
set FOUND_PYTHON=0

REM Try common Python locations
for %%p in (
    "C:\Users\%USERNAME%\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python310\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "python"
) do (
    %%~p -m pip --version >nul 2>&1
    if not errorlevel 1 (
        set PYTHON_CMD=%%~p
        set FOUND_PYTHON=1
        goto :python_found
    )
)

:python_found
if %FOUND_PYTHON%==0 (
    echo [ERROR] No Python with pip found!
    echo Please install Python 3.8+ from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('%PYTHON_CMD% --version') do set PYTHON_VERSION=%%i
echo [OK] %PYTHON_VERSION% found with pip
echo     Using: %PYTHON_CMD%
echo.

REM Install Python dependencies automatically
echo [2/4] Installing dependencies (numpy, Pillow)...
echo This may take a few minutes...
%PYTHON_CMD% -m pip install --quiet --upgrade pip
%PYTHON_CMD% -m pip install --quiet -r requirements.txt

if errorlevel 1 (
    echo [ERROR] Failed to install dependencies
    echo Please check your internet connection and try again
    echo.
    pause
    exit /b 1
)

echo [OK] Dependencies installed successfully
echo.

REM Test verification script
echo [3/4] Testing verification script...
%PYTHON_CMD% scripts\verify_schnorr.py --help >nul 2>&1

if errorlevel 1 (
    echo [ERROR] Verification script test failed
    echo Please check the error messages above
    echo.
    pause
    exit /b 1
)

echo [OK] Verification script working
echo.

echo ================================================================
echo   Setup Complete!
echo ================================================================
echo.
echo Python command: %PYTHON_CMD%
echo.
echo Quick Start:
echo   1. Verify an image:
echo      %PYTHON_CMD% scripts\verify_schnorr.py your_image.png -v
echo.
echo   2. Extract message (with chaos key):
echo      %PYTHON_CMD% scripts\verify_schnorr.py your_image.png --extract --chaos-key YOUR_KEY -v
echo.
echo   3. Get help:
echo      %PYTHON_CMD% scripts\verify_schnorr.py --help
echo.
echo ================================================================
pause
