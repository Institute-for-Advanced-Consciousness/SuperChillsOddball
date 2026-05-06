@echo off
REM =============================================================================
REM IACS On-Demand Chills x Oddball Study - First-run installer
REM =============================================================================
REM What this does:
REM   1. Verifies uv is installed (or installs it via the official PowerShell
REM      installer from astral.sh).
REM   2. Runs `uv sync` to create .venv and install all dependencies.
REM   3. Generates the .wav stimuli (idempotent - skips if files already exist).
REM   4. Runs the app's --self-check to confirm LSL outlet + audio device open.
REM
REM Run this once per laptop. Re-running is safe.
REM =============================================================================

setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo  Chills x Oddball Study - Installer
echo ========================================
echo.

REM --- Step 1: ensure uv is on PATH -------------------------------------------
where uv >nul 2>&1
if errorlevel 1 (
    echo [1/4] uv not found. Installing uv via official installer...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo.
        echo ERROR: uv installation failed. Install manually from https://astral.sh/uv
        exit /b 1
    )
    REM Refresh PATH for the rest of this session
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo ERROR: uv installed but not found on PATH. Open a new terminal and re-run.
        exit /b 1
    )
) else (
    echo [1/4] uv detected.
)

REM --- Step 2: sync dependencies ----------------------------------------------
echo.
echo [2/4] Resolving and installing dependencies (uv sync)...
uv sync
if errorlevel 1 (
    echo ERROR: uv sync failed.
    exit /b 1
)

REM --- Step 3: generate stimuli ------------------------------------------------
echo.
echo [3/4] Generating tone stimuli...
uv run python scripts\generate_tones.py
if errorlevel 1 (
    echo ERROR: tone generation failed.
    exit /b 1
)

REM --- Step 4: self-check ------------------------------------------------------
echo.
echo [4/4] Running self-check...
uv run python -m chills_oddball.app --self-check
if errorlevel 1 (
    echo.
    echo SELF-CHECK FAILED. See message above.
    exit /b 1
)

echo.
echo ========================================
echo  Install complete. Double-click launch.bat to start a session.
echo ========================================
echo.
endlocal
