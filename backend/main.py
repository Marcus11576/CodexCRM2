"""
Antigravity CRM — Application Entry Point
Single file that wires everything together.
"""
import os
import asyncio
import uuid
import traceback
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Cookie, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from backend.config import settings
from backend.database import init_db
from backend.services.ai_jobs import start_ai_job_worker, stop_ai_job_worker
from backend.services.m365_worker import start_m365_worker, stop_m365_worker


async def nightly_heartbeat():
    """Background task that runs the Platinum Health deep audit every 24 hours."""
    while True:
        try:
            # 86400 seconds = 24 hours
            await asyncio.sleep(86400)
            print("HEALTH: Running Nightly Heartbeat...")
            from backend.services.health_service import run_integrity_audit, synthesize_global_memory
            from backend.services.backup_service import run_backup, get_backup_label
            
            # Run Backup first
            try:
                label = get_backup_label()
                run_backup(label=label)
                print(f"BACKUP: Automated {label} backup complete.")
            except Exception as backup_e:
                print(f"BACKUP: Automated backup failed: {backup_e}")

            await run_integrity_audit()
            await synthesize_global_memory()
            print("HEALTH: Nightly Heartbeat complete.")
        except asyncio.CancelledError:
            print("HEALTH: Nightly Heartbeat stopped.")
            break
        except Exception as e:
            print(f"HEALTH: Error in Nightly Heartbeat: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour if error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, create upload dirs. Shutdown: clean up."""
    print("Antigravity CRM starting...")
    init_db()
    os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.UPLOADS_DIR, "audio_briefs"), exist_ok=True)
    import sys
    import backend.routers.intelligence
    print(f"PYTHONPATH: {sys.path}")
    print(f"INTELLIGENCE MODULE: {backend.routers.intelligence.__file__}")
    print(f"Ready — http://{settings.HOST}:{settings.PORT}")
    
    # Start the Nightly Heartbeat
    heartbeat_task = asyncio.create_task(nightly_heartbeat())
    await start_ai_job_worker()
    # start M365 sync worker if enabled
    if settings.M365_ENABLED:
        await start_m365_worker()
    
    # NEW: Trigger an immediate backup on startup if none exists for today
    try:
        from backend.services.backup_service import run_backup, get_backup_label
        label = get_backup_label()
        # Simple check: does any file with 'daily' or today's label exist in local backups?
        backup_dir = Path(settings.BACKUP_DIR)
        if backup_dir.exists():
            today_str = datetime.now().strftime("%Y%m%d")
            existing = list(backup_dir.glob(f"*{today_str}*"))
            if not existing:
                print("BACKUP: No backup found for today. Running startup backup...")
                run_backup(label=label)
        else:
            print("BACKUP: Initializing first backup...")
            run_backup(label=label)
    except Exception as e:
        print(f"BACKUP: Startup backup failed: {e}")
    
    yield
    
    print("Antigravity CRM shutting down")
    heartbeat_task.cancel()
    await stop_ai_job_worker()
    # ensure worker shutdown
    await stop_m365_worker()


app = FastAPI(
    title="Antigravity CRM API",
    version="2.0.0",
    description="Relationship Intelligence Platform",
    lifespan=lifespan
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global exceptions & Auth ──────────────────────────────────────────────────

class AuthRequiredException(Exception):
    """Custom exception to trigger redirect to login for UI pages."""
    pass

@app.exception_handler(AuthRequiredException)
async def auth_exception_handler(request: Request, exc: AuthRequiredException):
    return RedirectResponse(url="/login")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Sanitized global error handler — hides raw tracebacks from the client."""
    error_id = str(uuid.uuid4())[:8]
    print(f"ERROR [{error_id}] on {request.url.path}:\n{traceback.format_exc()}")
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. Please contact support.",
            "reference": error_id
        }
    )

async def api_auth_dependency(request: Request):
    if settings.AUTH_DISABLED:
        return {"sub": "local-dev", "email": "local@antigravity.crm", "role": "admin"}
    from backend.routers.auth import current_user
    return await current_user(request.cookies.get("session_token"))


async def page_auth_dependency(request: Request):
    if settings.AUTH_DISABLED:
        return None
    if request.url.path in {"/login", "/login.html", "/api/auth/login", "/api/auth/setup", "/api/auth/status"}:
        return None
    from backend.routers.auth import current_user
    await current_user(request.cookies.get("session_token"))
    return None


# API Routers
from backend.routers import auth, people, interactions, tasks, taxonomy, intelligence, intelligence_v2, analytics, analytics_v2, compat_v1, health, ai_pipeline, events, m365

app.include_router(auth.router)

API_DEPS = [] if settings.AUTH_DISABLED else [Depends(api_auth_dependency)]
app.include_router(people.router, dependencies=API_DEPS)
app.include_router(interactions.router, dependencies=API_DEPS)
app.include_router(tasks.router, dependencies=API_DEPS)
app.include_router(events.router, dependencies=API_DEPS)
app.include_router(taxonomy.router, dependencies=API_DEPS)
app.include_router(intelligence.router, dependencies=API_DEPS)
app.include_router(intelligence_v2.router, dependencies=API_DEPS)
app.include_router(analytics.router, dependencies=API_DEPS)
app.include_router(analytics_v2.router, dependencies=API_DEPS)
app.include_router(health.router, dependencies=API_DEPS)
app.include_router(ai_pipeline.router, dependencies=API_DEPS)
app.include_router(m365.router, dependencies=API_DEPS)
app.include_router(compat_v1.router, dependencies=API_DEPS)


@app.get("/uploads/{path:path}")
async def protected_uploads(path: str, auth: Annotated[dict | None, Depends(api_auth_dependency)] = None):
    """Serve uploaded files only to authenticated users unless auth is explicitly disabled."""
    file_path = os.path.join(settings.UPLOADS_DIR, path)
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(file_path)
# Static modules (CSS/JS) public for login ────────────────────────────────
app.mount("/static", StaticFiles(directory=os.path.join(settings.FRONTEND_DIR, "static")), name="static")
app.mount("/js", StaticFiles(directory=os.path.join(settings.FRONTEND_DIR, "js")), name="js")

# ── Frontend HTML routes (Protected) ─────────────────────────────────────────
FRONTEND = settings.FRONTEND_DIR

@app.get("/")
async def serve_index(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "index.html"), headers={"Cache-Control": "no-cache"})

@app.get("/login")
@app.get("/login.html")
async def serve_login():
    return FileResponse(os.path.join(FRONTEND, "login.html"), headers={"Cache-Control": "no-cache"})

@app.get("/profile")
@app.get("/profile.html")
@app.get("/person/{person_id}")
async def serve_profile(person_id: Optional[str] = None, auth: Annotated[None, Depends(page_auth_dependency)] = None):
    return FileResponse(os.path.join(FRONTEND, "profile.html"), headers={"Cache-Control": "no-cache"})

@app.get("/agenda")
@app.get("/agenda.html")
async def serve_agenda(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "agenda.html"), headers={"Cache-Control": "no-cache"})

@app.get("/settings")
@app.get("/settings.html")
async def serve_settings(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "settings.html"), headers={"Cache-Control": "no-cache"})

@app.get("/events")
@app.get("/events.html")
@app.get("/events/{event_id}")
async def serve_events(event_id: Optional[str] = None, auth: Annotated[None, Depends(page_auth_dependency)] = None):
    return FileResponse(os.path.join(FRONTEND, "events.html"), headers={"Cache-Control": "no-cache"})

@app.get("/analytics")
@app.get("/analytics.html")
async def serve_analytics(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "analytics.html"), headers={"Cache-Control": "no-cache"})

@app.get("/activities")
@app.get("/activities.html")
async def serve_activities(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "activities.html"), headers={"Cache-Control": "no-cache"})

# ── Health check (Public) ─────────────────────────────────────────────────────
@app.get("/api/health")
async def health_check_public():
    return {"status": "ok", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8009, reload=False)






