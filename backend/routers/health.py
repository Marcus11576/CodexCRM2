from fastapi import APIRouter, Depends, HTTPException
from backend.services.health_service import run_integrity_audit, synthesize_global_memory, get_platinum_score
from backend.services.backup_service import get_latest_backup_metadata, run_backup, get_backup_label
from backend.config import settings
import time

router = APIRouter(prefix="/api/health", tags=["System Health"])

@router.get("/status")
async def get_health_status():
    """Returns the CRM Platinum Score and high-level health metrics."""
    score = await get_platinum_score()
    deployment_checks = {
        "auth_enforced": not settings.AUTH_DISABLED,
        "secure_cookies": bool(settings.COOKIE_SECURE),
        "api_docs_disabled": not settings.API_DOCS_ENABLED,
        "openai_configured": bool(settings.OPENAI_CONFIGURED),
        "m365_enabled": bool(settings.M365_ENABLED),
        "persistent_db_path": str(settings.DB_PATH).lower() not in {"crm.db", "antigravity_crm.db"},
    }
    return {
        "platinum_score": score,
        "status": "Platinum" if score > 90 else "Gold" if score > 75 else "Silver",
        "timestamp": time.time(),
        "deployment_checks": deployment_checks,
    }

@router.post("/trigger")
async def trigger_full_audit():
    """Manually triggers the full integrity and memory synthesis cycle."""
    stats = await run_integrity_audit()
    memory_stats = await synthesize_global_memory()
    score = await get_platinum_score()
    
    return {
        "status": "success",
        "audit_stats": stats,
        "memory_stats": memory_stats,
        "new_platinum_score": score
    }


@router.get("/backups/status")
async def get_backup_status():
    """Returns the latest known backup artifact timestamp."""
    return get_latest_backup_metadata()


@router.post("/backups/run")
async def run_backup_now():
    """Trigger an immediate backup and return the resulting artifact metadata."""
    run_backup(label=get_backup_label())
    return get_latest_backup_metadata()
