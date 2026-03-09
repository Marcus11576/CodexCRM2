@echo off
echo ===========================================
echo âš¡ Starting Antigravity CRM âš¡
echo ===========================================

:: Check if .env exists, if not copy from example
if not exist ".env" (
    echo Creating default .env file...
    copy .env.example .env
)

:: Start the FastAPI server
echo Starting server on http://localhost:8009
python -m backend.main

pause

