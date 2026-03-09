"""
Antigravity CRM — Legacy API Compatibility Router
Bridges the old V1 frontend requests to the new V2 backend services.
"""
import os
import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Query, Request, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.database import get_db
from backend.config import settings

router = APIRouter()

# ── Dashboard Compatibility ──────────────────────────────────────────────────

@router.get("/api/dashboard/task-pipeline")
async def compat_task_pipeline(days: int = Query(30)):
    from backend.routers.tasks import get_pipeline
    return await get_pipeline(days=days)


@router.get("/api/dashboard/meeting-feed")
async def compat_meeting_feed():
    """Returns contacts grouped by meeting_status for the dashboard tiles."""
    async with get_db() as db:
        async with db.execute("""
            SELECT person_id, full_name, title_current, company_name_raw,
                   cat, env, disc, contact_value, engagement_status,
                   profile_photo_url, meeting_status, next_contact_due_date,
                   is_ts_advisory_candidate
            FROM PERSON WHERE is_active = 1
            ORDER BY next_contact_due_date ASC NULLS LAST
        """) as c:
            rows = await c.fetchall()

    feed = {
        "overdue": [],
        "soon": [],
        "on_track": [],
        "not_scheduled": []
    }

    for r in rows:
        d = dict(r)
        st = d.get("meeting_status")
        if st == "overdue":
            feed["overdue"].append(d)
        elif st == "soon":
            feed["soon"].append(d)
        elif st == "on_track":
            feed["on_track"].append(d)
        else:
            feed["not_scheduled"].append(d)

    return feed


# ── People Detail Compatibility ──────────────────────────────────────────────

@router.post("/api/people/{person_id}/meeting-brief")
async def compat_meeting_brief(person_id: str):
    from backend.routers.intelligence import get_brief
    return await get_brief(person_id=person_id, force_refresh=True)


@router.post("/api/people/{person_id}/media")
async def compat_upload_photo(person_id: str, file: UploadFile = File(...)):
    """Upload profile photo — saves locally and updates person record."""
    uploads_dir = os.path.join(settings.UPLOADS_DIR, "photos")
    os.makedirs(uploads_dir, exist_ok=True)

    ext = os.path.splitext(file.filename)[1] or ".jpg"
    filename = f"{person_id}{ext}"
    filepath = os.path.join(uploads_dir, filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    photo_url = f"/uploads/photos/{filename}"

    async with get_db() as db:
        await db.execute(
            "UPDATE PERSON SET profile_photo_url=?, last_updated_at=? WHERE person_id=?",
            (photo_url, datetime.now(timezone.utc).isoformat(), person_id)
        )
        await db.commit()

    return {"status": "success", "url": photo_url}


# ── Taxonomy & Config Compatibility ──────────────────────────────────────────

@router.get("/api/config/taxonomy")
async def compat_taxonomy():
    """Alias /api/config/taxonomy -> /api/taxonomy for old frontend compatibility."""
    from backend.routers.taxonomy import get_taxonomy
    return await get_taxonomy()

class AIConfigInput(BaseModel):
    openai_key: Optional[str] = None
    gemini_key: Optional[str] = None
    auto_enrich: Optional[bool] = None
    auto_task: Optional[bool] = None
    brief_prompt: Optional[str] = None
    hypothesis_questions: Optional[str] = None
    tts_voice: Optional[str] = None
    recruitment_label: Optional[str] = None
    obe_label: Optional[str] = None

@router.get("/api/config/ai")
async def get_ai_config():
    """Get the current AI configuration."""
    return {
        "openai_key": settings.OPENAI_API_KEY,
        "gemini_key": settings.GEMINI_API_KEY,
        "hypothesis_questions": settings.BRIEF_HYPOTHESIS_QUESTIONS,
        "tts_voice": settings.BRIEF_TTS_VOICE,
        "recruitment_label": settings.BRIEF_LABEL_RECRUITMENT,
        "obe_label": settings.BRIEF_LABEL_OBE
    }

@router.post("/api/config/ai")
async def update_ai_config(payload: AIConfigInput):
    """Save AI configuration to the .env file and memory."""
    env_path = os.path.join(settings.BASE_DIR, ".env")
    
    # Read existing
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    def update_or_add(key_name, new_val):
        for i, line in enumerate(lines):
            if line.startswith(f"{key_name}="):
                lines[i] = f"{key_name}={new_val}\n"
                return
        lines.append(f"{key_name}={new_val}\n")

    # Update memory and file if provided
    if payload.openai_key is not None:
        settings.OPENAI_API_KEY = payload.openai_key
        update_or_add("OPENAI_API_KEY", payload.openai_key)
        
    if payload.gemini_key is not None:
        settings.GEMINI_API_KEY = payload.gemini_key
        update_or_add("GEMINI_API_KEY", payload.gemini_key)

    if payload.hypothesis_questions is not None:
        settings.BRIEF_HYPOTHESIS_QUESTIONS = payload.hypothesis_questions
        update_or_add("BRIEF_HYPOTHESIS_QUESTIONS", payload.hypothesis_questions)

    if payload.tts_voice is not None:
        settings.BRIEF_TTS_VOICE = payload.tts_voice
        update_or_add("BRIEF_TTS_VOICE", payload.tts_voice)
    
    if payload.recruitment_label is not None:
        settings.BRIEF_LABEL_RECRUITMENT = payload.recruitment_label
        update_or_add("BRIEF_LABEL_RECRUITMENT", payload.recruitment_label)
        
    if payload.obe_label is not None:
        settings.BRIEF_LABEL_OBE = payload.obe_label
        update_or_add("BRIEF_LABEL_OBE", payload.obe_label)
        
    # Write back
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    return {"status": "success", "message": "AI configuration updated"}


# ── [STUB] M365 Subsystem (NOT PRODUCTION READY) ───────────────────────────
# WARNING: These routes exist for legacy clients but will forward to the new
# implementation when the feature flag is active.  They are intentionally
# tolerant so that older builds continue to receive the same response shape.
from backend.config import settings
from backend.routers import m365 as _m365

@router.get("/api/m365/auth/status", tags=["stubs"])
async def compat_m365_status():
    """Forwarding wrapper that falls back to a static response if disabled."""
    if settings.M365_ENABLED:
        return await _m365.auth_status()
    return {"status": "unauthenticated", "note": "Feature currently disabled in baseline-v2.0.0"}


@router.post("/api/m365/auth/start", tags=["stubs"])
async def compat_m365_start():
    if settings.M365_ENABLED:
        return await _m365.auth_start()
    return {"status": "authenticated", "note": "Simulation only"}


@router.get("/api/m365/emails/{person_id}", tags=["stubs"])
async def compat_m365_emails(person_id: str):
    if settings.M365_ENABLED:
        return await _m365.fetch_emails(person_id)
    return {"status": "success", "emails": [], "new_synced": 0}


@router.post("/api/m365/emails/{person_id}/send", tags=["stubs"])
async def compat_m365_send(person_id: str, req: dict):
    if settings.M365_ENABLED:
        return await _m365.send_email(person_id, req)
    return {"status": "error", "message": "M365 integration is not active in this build."}


# ── [STUB] Twin Chat (EXPERIMENTAL / NON-FUNCTIONAL) ──────────────────────

class TwinChatReq(BaseModel):
    message: str
    history: list = []


@router.post("/api/intelligence/twin/chat", tags=["stubs"])
async def compat_twin_chat(req: TwinChatReq):
    """STUB: Echo-only response for UI testing."""
    return {
        "reply": "AI Twin is a placeholder in this build. Your message was: " + req.message[:50],
        "data": None,
        "pending_action": None
    }


@router.post("/api/intelligence/twin/execute", tags=["stubs"])
async def compat_twin_execute(req: dict):
    """STUB: no-op."""
    return {"status": "success", "message": "Mock action executed.", "is_stub": True}


# End of file

