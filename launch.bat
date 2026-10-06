@echo off
rem Launch the Python application; this is not a packaged executable.
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo The local environment is missing. See README.md for setup instructions.
    pause
    exit /b 1
)
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m battread_gui
