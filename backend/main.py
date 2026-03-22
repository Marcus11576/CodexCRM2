"""
Antigravity CRM — Application Entry Point
Single file that wires everything together.
"""
import os
import asyncio
import uuid
import traceback
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Annotated, Awaitable, Callable, Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Cookie, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
except Exception:  # pragma: no cover - optional import for runtime compatibility
    ProxyHeadersMiddleware = None

from backend.config import settings
from backend.database import init_db
from backend.services.ai_jobs import start_ai_job_worker, stop_ai_job_worker
from backend.services.m365_worker import start_m365_worker, stop_m365_worker


def _assert_secure_configuration() -> None:
    if settings.ENV_LOWER == "development":
        return
    if settings.AUTH_DISABLED:
        raise RuntimeError("AUTH_DISABLED must be false outside development")
    if not settings.COOKIE_SECURE:
        raise RuntimeError("COOKIE_SECURE must be true outside development")
    if settings.SECRET_KEY == "dev-only-insecure-key-change-in-production":
        raise RuntimeError("SECRET_KEY must be replaced outside development")


async def nightly_heartbeat():
    """Background task that runs the backup + deep audit on the configured daily schedule."""
    while True:
        try:
            from backend.services.backup_service import get_next_backup_run

            next_run = get_next_backup_run()
            wait_seconds = max((next_run - datetime.now(timezone.utc)).total_seconds(), 1)
            print(f"HEALTH: Next scheduled heartbeat at {next_run.isoformat()} UTC")
            await asyncio.sleep(wait_seconds)
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


async def _run_optional_startup(name: str, starter: Callable[[], Awaitable[None]], started_services: set[str]):
    """Start non-critical services without letting them take down the app."""
    try:
        await starter()
        started_services.add(name)
        print(f"STARTUP: {name} ready.")
    except Exception as exc:
        print(f"STARTUP: {name} failed and has been disabled: {exc}")
        traceback.print_exc()


async def _run_optional_shutdown(name: str, stopper: Callable[[], Awaitable[None]], started_services: set[str]):
    if name not in started_services:
        return
    try:
        await stopper()
        print(f"SHUTDOWN: {name} stopped.")
    except Exception as exc:
        print(f"SHUTDOWN: {name} stop failed: {exc}")
        traceback.print_exc()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, create upload dirs. Shutdown: clean up."""
    print("Antigravity CRM starting...")
    _assert_secure_configuration()
    init_db()
    os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
    os.makedirs(os.path.join(settings.UPLOADS_DIR, "audio_briefs"), exist_ok=True)
    import sys
    import backend.routers.intelligence
    print(f"PYTHONPATH: {sys.path}")
    print(f"INTELLIGENCE MODULE: {backend.routers.intelligence.__file__}")
    print(f"Ready — http://{settings.HOST}:{settings.PORT}")

    # Start the Nightly Heartbeat and optional workers.
    started_services: set[str] = set()
    heartbeat_task = asyncio.create_task(nightly_heartbeat(), name="nightly-heartbeat")
    await _run_optional_startup("AI job worker", start_ai_job_worker, started_services)
    if settings.M365_ENABLED and not settings.CHATBOT_ONLY_MODE:
        await _run_optional_startup("M365 sync worker", start_m365_worker, started_services)

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
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await _run_optional_shutdown("M365 sync worker", stop_m365_worker, started_services)
    await _run_optional_shutdown("AI job worker", stop_ai_job_worker, started_services)


app = FastAPI(
    title="Antigravity CRM API",
    version="2.0.0",
    description="Relationship Intelligence Platform",
    lifespan=lifespan,
    docs_url="/docs" if settings.API_DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.API_DOCS_ENABLED else None,
)

if ProxyHeadersMiddleware is not None:
    # Respect X-Forwarded-* headers from the deployment edge so redirect URIs,
    # secure cookies, and generated absolute URLs match the public origin.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Allow first-party in-app embedding (profile page embeds lab profile via iframe).
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
        if settings.ENV_LOWER != "development":
            response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
            response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
            if request.url.scheme == "https":
                response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


app.add_middleware(SecurityHeadersMiddleware)

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
    return await current_user(request.cookies.get(settings.SESSION_COOKIE_NAME))


async def page_auth_dependency(request: Request):
    if settings.AUTH_DISABLED:
        return None
    if request.url.path in {
        "/login",
        "/login.html",
        "/api/auth/login",
        "/api/auth/setup",
        "/api/auth/status",
        "/api/auth/microsoft/start",
        "/api/auth/microsoft/callback",
    }:
        return None
    from backend.routers.auth import current_user
    try:
        await current_user(request.cookies.get(settings.SESSION_COOKIE_NAME))
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise AuthRequiredException() from exc
        raise
    return None


# API Routers
from backend.routers import auth, people, interactions, tasks, taxonomy, intelligence, intelligence_v2, analytics, analytics_v2, compat_v1, health, ai_pipeline, events, m365, standalone_tool, network_lab, settings as system_settings

app.include_router(auth.router)

API_DEPS = [] if settings.AUTH_DISABLED else [Depends(api_auth_dependency)]
app.include_router(people.router, dependencies=API_DEPS)
app.include_router(interactions.router, dependencies=API_DEPS)
app.include_router(tasks.router, dependencies=API_DEPS)
app.include_router(events.router, dependencies=API_DEPS)
app.include_router(taxonomy.router, dependencies=API_DEPS)
app.include_router(system_settings.router, dependencies=API_DEPS)
app.include_router(intelligence.router, dependencies=API_DEPS)
app.include_router(intelligence_v2.router, dependencies=API_DEPS)
app.include_router(analytics.router, dependencies=API_DEPS)
app.include_router(analytics_v2.router, dependencies=API_DEPS)
app.include_router(health.router, dependencies=API_DEPS)
app.include_router(ai_pipeline.router, dependencies=API_DEPS)
app.include_router(m365.router, dependencies=API_DEPS)
app.include_router(compat_v1.router, dependencies=API_DEPS)
app.include_router(network_lab.router, dependencies=API_DEPS)
app.include_router(standalone_tool.router)


@app.get("/uploads/{path:path}")
async def protected_uploads(path: str, auth: Annotated[dict | None, Depends(api_auth_dependency)] = None):
    """Serve uploaded files only to authenticated users unless auth is explicitly disabled."""
    file_path = os.path.join(settings.UPLOADS_DIR, path)
    if not os.path.exists(file_path) or os.path.isdir(file_path):
        if os.path.splitext(path)[1].lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp'}: return FileResponse(os.path.join(settings.FRONTEND_DIR, 'static', 'avatar-placeholder.svg'))
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
    if settings.AUTH_DISABLED:
        return RedirectResponse(url="/")
    return FileResponse(os.path.join(FRONTEND, "login.html"), headers={"Cache-Control": "no-cache"})

@app.get("/profile")
@app.get("/profile.html")
@app.get("/person/{person_id}")
async def serve_profile(person_id: Optional[str] = None, auth: Annotated[None, Depends(page_auth_dependency)] = None):
    return FileResponse(os.path.join(FRONTEND, "profile.html"), headers={"Cache-Control": "no-cache"})

@app.get("/profile-layout-options")
@app.get("/profile-layout-options.html")
async def serve_profile_layout_options(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "profile-layout-options.html"), headers={"Cache-Control": "no-cache"})

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


@app.get("/network-lab")
@app.get("/network-lab.html")
async def serve_network_lab(auth: Annotated[None, Depends(page_auth_dependency)]):
    return FileResponse(os.path.join(FRONTEND, "network-lab.html"), headers={"Cache-Control": "no-cache"})


@app.get("/network-lab/profile/{person_id}")
@app.get("/network-lab-profile.html")
async def serve_network_lab_profile(person_id: Optional[str] = None, auth: Annotated[None, Depends(page_auth_dependency)] = None):
    return FileResponse(os.path.join(FRONTEND, "network-lab-profile.html"), headers={"Cache-Control": "no-cache"})


@app.get("/network-lab/databank")
@app.get("/network-lab-databank.html")
async def serve_network_lab_databank(auth: Annotated[None, Depends(page_auth_dependency)] = None):
    return FileResponse(os.path.join(FRONTEND, "network-lab-databank.html"), headers={"Cache-Control": "no-cache"})


@app.get("/network-lab/review")
@app.get("/network-lab-review.html")
async def serve_network_lab_review(auth: Annotated[None, Depends(page_auth_dependency)] = None):
    return FileResponse(os.path.join(FRONTEND, "network-lab-review.html"), headers={"Cache-Control": "no-cache"})

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
    uvicorn.run("backend.main:app", host=settings.HOST, port=settings.PORT, reload=False)







@app.get("/favicon.ico")
async def serve_favicon():
    return FileResponse(os.path.join(settings.FRONTEND_DIR, "static", "avatar-placeholder.svg"))

@app.get("/api/proxy/image")
async def proxy_image(url: str, auth: Annotated[dict | None, Depends(api_auth_dependency)] = None):
    normalized = (url or "").split("?", 1)[0]
    if normalized.startswith("/uploads/"):
        file_path = os.path.join(settings.UPLOADS_DIR, normalized.replace("/uploads/", "", 1))
        if os.path.exists(file_path) and not os.path.isdir(file_path):
            return FileResponse(file_path)
    if normalized.startswith("/static/"):
        static_path = os.path.join(settings.FRONTEND_DIR, normalized.replace("/", os.sep).lstrip(os.sep))
        if os.path.exists(static_path) and not os.path.isdir(static_path):
            return FileResponse(static_path)
    return FileResponse(os.path.join(settings.FRONTEND_DIR, "static", "avatar-placeholder.svg"))






