@echo off
REM =============================================================================
REM IACS On-Demand Chills x Oddball Study - Session launcher
REM
REM Double-click to start a session. Opens the GUI at the Intake screen.
REM Make sure LabRecorder is running and recording before clicking "Begin Session".
REM =============================================================================

setlocal
cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>&1
    if errorlevel 1 (
        echo ERROR: uv not found. Run INSTALL.bat first.
        pause
        exit /b 1
    )
)

uv run python -m chills_oddball.app
if errorlevel 1 (
    echo.
    echo The app exited with an error. See messages above.
    pause
    exit /b 1
)

endlocal
