@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM Work Assistant Agent — Setup Wizard Launcher (Windows)
REM Double-click this file to run the interactive setup wizard.
REM ─────────────────────────────────────────────────────────────────────────────

cd /d "%~dp0"

echo.
echo +--------------------------------------------------------------+
echo ^|       Work Assistant Agent -- Setup Wizard                   ^|
echo +--------------------------------------------------------------+
echo.

REM ── Check Python ────────────────────────────────────────────────────────────
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo.
    echo   Install it from: https://www.python.org/downloads/
    echo   Make sure to tick "Add Python to PATH" during install.
    echo   Then double-click this file again.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do echo [OK] %%i found

REM ── Create virtual environment if missing ────────────────────────────────────
if not exist "venv\" (
    echo [INFO] Creating virtual environment (first time only)...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

REM ── Activate venv ────────────────────────────────────────────────────────────
call venv\Scripts\activate.bat

REM ── Install / update dependencies ────────────────────────────────────────────
echo [INFO] Installing dependencies (this takes ~30 seconds on first run)...
pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo [WARN] pip install had issues. Retrying...
    pip install -r requirements.txt
)
echo [OK] Dependencies ready
echo.

REM ── Run the wizard ────────────────────────────────────────────────────────────
python setup_wizard.py %*

echo.
pause
