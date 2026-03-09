from fastapi import APIRouter, Depends, HTTPException
from backend.services.health_service import run_integrity_audit, synthesize_global_memory, get_platinum_score
import time

router = APIRouter(prefix="/api/health", tags=["System Health"])

@router.get("/status")
async def get_health_status():
    """Returns the CRM Platinum Score and high-level health metrics."""
    score = await get_platinum_score()
    return {
        "platinum_score": score,
        "status": "Platinum" if score > 90 else "Gold" if score > 75 else "Silver",
        "timestamp": time.time()
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
