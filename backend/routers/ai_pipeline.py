"""
Antigravity CRM - AI Pipeline Router
Data foundation for artifacts, signals, briefs, and structured feedback.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database import get_db
from backend.services.ai_jobs import get_job, list_jobs, retry_job
from backend.services.preference_learning import normalize_feedback_event, record_feedback_event

router = APIRouter(prefix="/api/ai", tags=["ai-pipeline"])

SIGNAL_CATEGORIES = {
    "business_focus",
    "recruitment_talent",
    "family_personal",
    "obe_focus",
}


class ArtifactCreate(BaseModel):
    person_id: str
    channel: str
    raw_content: Optional[str] = None
    media_url: Optional[str] = None
    source_interaction_id: Optional[str] = None
    metadata: Optional[dict] = None


class SignalCreate(BaseModel):
    artifact_id: Optional[str] = None
    person_id: str
    category: str
    content: str
    source_snippet: str
    confidence: int = 3
    manual: bool = False


class SignalStatusUpdate(BaseModel):
    status: str


class BriefCreate(BaseModel):
    person_id: str
    content_json: dict
    source_signal_ids: List[str]


class FeedbackCreate(BaseModel):
    target_type: str
    target_id: str
    event_type: str
    details: Optional[dict] = None
    user_id: Optional[str] = None


@router.post("/artifacts")
async def create_artifact(req: ArtifactCreate):
    aid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (artifact_id, person_id, source_interaction_id, channel, raw_content, media_url, metadata, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (aid, req.person_id, req.source_interaction_id, req.channel, req.raw_content, req.media_url, json.dumps(req.metadata or {}), now),
        )
        await db.commit()
    return {"artifact_id": aid}


@router.get("/signals/{person_id}")
async def get_signals(person_id: str):
    async with get_db() as db:
        async with db.execute("SELECT * FROM AI_SIGNAL WHERE person_id=? ORDER BY created_at DESC", (person_id,)) as cursor:
            rows = await cursor.fetchall()
    return [dict(row) for row in rows]


@router.post("/signals")
async def create_signal(req: SignalCreate):
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    category = (req.category or "").strip().lower()
    if category not in SIGNAL_CATEGORIES:
        raise HTTPException(400, "Invalid category")

    artifact_id = req.artifact_id or str(uuid.uuid4())
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (signal_id, artifact_id, person_id, category, content, source_snippet, confidence, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (sid, artifact_id, req.person_id, category, req.content, req.source_snippet, req.confidence, "draft", now, now),
        )
        await db.commit()

    if req.manual:
        await record_feedback_event(
            target_type="signal",
            target_id=sid,
            event_type="manual_add",
            details={
                "text": req.content,
                "category": category,
                "source": "manual_signal_create",
            },
        )
    return {"signal_id": sid}


@router.patch("/signals/{signal_id}/status")
async def update_signal_status(signal_id: str, req: SignalStatusUpdate):
    now = datetime.now(timezone.utc).isoformat()
    async with get_db() as db:
        await db.execute(
            "UPDATE AI_SIGNAL SET status=?, updated_at=? WHERE signal_id=?",
            (req.status, now, signal_id),
        )
        await db.commit()
    return {"status": "updated"}


@router.post("/briefs/{person_id}")
async def store_brief(person_id: str, req: BriefCreate):
    bid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    payload = dict(req.content_json or {})
    payload.setdefault("brief_id", bid)
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO AI_BRIEF (brief_id, person_id, content_json, source_signal_ids, created_at)
            VALUES (?,?,?,?,?)
            """,
            (bid, person_id, json.dumps(payload), json.dumps(req.source_signal_ids), now),
        )
        await db.commit()
    return {"brief_id": bid}


@router.post("/feedback")
async def log_feedback(req: FeedbackCreate):
    if req.target_type not in {"signal", "brief"}:
        raise HTTPException(400, "Invalid feedback target type")

    try:
        event_type = normalize_feedback_event(req.event_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    result = await record_feedback_event(
        target_type=req.target_type,
        target_id=req.target_id,
        event_type=event_type,
        details=req.details or {},
        user_id=req.user_id,
    )
    return result


@router.get("/jobs/{job_id}")
async def get_ai_job(job_id: str):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs/person/{person_id}")
async def list_person_ai_jobs(person_id: str, limit: int = 25):
    return {"jobs": await list_jobs(person_id=person_id, limit=limit)}


@router.post("/jobs/{job_id}/retry")
async def retry_ai_job(job_id: str):
    try:
        job = await retry_job(job_id)
    except ValueError:
        raise HTTPException(404, "Job not found")
    return job
