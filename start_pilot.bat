@echo off
setlocal

echo ===========================================
echo Starting Antigravity CRM Pilot
echo ===========================================

if not exist ".env" (
    echo Creating default .env file...
    copy .env.example .env >nul
)

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

if not exist "pilot" mkdir pilot
if not exist "pilot\backups" mkdir pilot\backups
if not exist "pilot\backups_external" mkdir pilot\backups_external
if not exist "pilot\uploads" mkdir pilot\uploads

if not exist "pilot\pilot_crm.db" (
    echo Provisioning isolated pilot database...
    "%PYTHON_EXE%" scripts\provision_pilot_instance.py --force
    if errorlevel 1 goto end
)

set "PORT=8011"
set "DB_PATH=pilot\pilot_crm.db"
set "UPLOADS_DIR=pilot\uploads"
set "BACKUP_DIR=pilot\backups"
set "BACKUP_EXTERNAL_DIR=pilot\backups_external"
set "M365_ENABLED=false"
set "AUTH_DISABLED=true"
set "SESSION_COOKIE_NAME=pilot_session_token"
set "SECRET_KEY=pilot-instance-dev-secret-change-before-sharing"
set "ALLOWED_ORIGINS=http://localhost:8011,http://127.0.0.1:8011"

echo Starting isolated pilot on http://localhost:%PORT%
"%PYTHON_EXE%" -m backend.main

:end
endlocal
pause
