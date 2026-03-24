@echo off
setlocal

echo ===========================================
echo Starting Antigravity CRM (MAIN)
echo ===========================================

:: Ensure .env exists
if not exist ".env" (
    echo Creating default .env file...
    copy .env.example .env >nul
)

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

echo Starting main server on http://localhost:8009
"%PYTHON_EXE%" -m backend.main

endlocal
pause
