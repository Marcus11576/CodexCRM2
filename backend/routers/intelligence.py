"""
Antigravity CRM - Intelligence Router
Briefings, AI chat, audio TTS, transcription jobs, and WhatsApp imports.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from backend.config import settings
from backend.database import run_read, run_write
from backend.services.ai_jobs import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RETRYING,
    JOB_STATUS_RUNNING,
    JOB_TYPE_BRIEF_GENERATION,
    JOB_TYPE_SIGNAL_EXTRACTION,
    JOB_TYPE_TRANSCRIPTION,
    enqueue_job,
    list_jobs,
)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []


class TtsRequest(BaseModel):
    text: str
    voice: str = "shimmer"


class WhatsAppImport(BaseModel):
    person_id: str
    conversation_text: str


async def _get_cached_brief_state(person_id: str):
    async def _load_person_and_brief(db):
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            person_row = await cursor.fetchone()
        async with db.execute(
            "SELECT brief_id, content_json FROM AI_BRIEF WHERE person_id=? ORDER BY created_at DESC LIMIT 1",
            (person_id,),
        ) as cursor:
            brief_row = await cursor.fetchone()
        return person_row, brief_row

    row, brief_row = await run_read(_load_person_and_brief, label=f"load person {person_id} for brief")
    if not row:
        raise HTTPException(404, "Person not found")
    person = dict(row)

    cached = None
    if person.get("cached_briefing"):
        try:
            cached = json.loads(person["cached_briefing"])
        except Exception:
            cached = None
    if cached and brief_row and not cached.get("brief_id"):
        cached["brief_id"] = brief_row["brief_id"]
    return person, cached

async def _latest_brief_job(person_id: str):
    jobs = await list_jobs(person_id=person_id, limit=20)
    for job in jobs:
        if job["job_type"] == JOB_TYPE_BRIEF_GENERATION:
            return job
    return None


@router.get("/brief/{person_id}")
@router.post("/brief/{person_id}")
async def get_brief(person_id: str, force_refresh: bool = False, request: Request = None):
    if request and request.method == "POST":
        force_refresh = True

    _person, cached = await _get_cached_brief_state(person_id)
    if cached and not force_refresh:
        return {"status": "completed", "briefing": cached, "cached": True}

    existing_job = await _latest_brief_job(person_id)
    if existing_job and existing_job["status"] in {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_RETRYING}:
        return {"status": existing_job["status"], "job_id": existing_job["job_id"], "cached": False}

    if existing_job and existing_job["status"] == JOB_STATUS_COMPLETED and cached:
        return {"status": "completed", "briefing": cached, "cached": True}

    if force_refresh or not existing_job or existing_job["status"] == JOB_STATUS_FAILED:
        job = await enqueue_job(
            JOB_TYPE_BRIEF_GENERATION,
            {"person_id": person_id, "force_refresh": force_refresh},
            person_id=person_id,
        )
        return {"status": job["status"], "job_id": job["job_id"], "cached": False}

    return {"status": "processing", "job_id": existing_job["job_id"], "cached": False}


@router.post("/chat/{person_id}")
async def chat_with_profile(person_id: str, req: ChatRequest):
    async def _load_person(db):
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            return await cursor.fetchone()

    row = await run_read(_load_person, label=f"load person {person_id} for chat")
    if not row:
        raise HTTPException(404, "Person not found")
    person = dict(row)

    from backend.services.ai_service import profile_chat

    response = await profile_chat(person_id, person, req.message, req.history)

    iid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async def _log_chat(db):
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, action_items, topics, created_at, interaction_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (iid, person_id, "chat", req.message, req.message[:200], "[]", "[]", now, now),
        )
        await db.execute("UPDATE PERSON SET cached_briefing=NULL, last_updated_at=? WHERE person_id=?", (now, person_id))

    await run_write(_log_chat, label=f"log profile chat {person_id}")
    return {"response": response, "interaction_id": iid}


@router.post("/tts/{person_id}")
async def generate_audio_brief(person_id: str, req: TtsRequest):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, "OpenAI API key not configured")

    from backend.services.ai_service import generate_tts

    audio_bytes = await generate_tts(req.text, req.voice)

    audio_dir = os.path.join(settings.UPLOADS_DIR, "audio_briefs")
    os.makedirs(audio_dir, exist_ok=True)
    filename = f"brief_{person_id}_{req.voice}.mp3"
    filepath = os.path.join(audio_dir, filename)
    with open(filepath, "wb") as handle:
        handle.write(audio_bytes)

    return {"audio_url": f"/uploads/audio_briefs/{filename}?t={uuid.uuid4().hex[:6]}"}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, "OpenAI API key not configured")

    transcription_dir = os.path.join(settings.UPLOADS_DIR, "transcriptions")
    os.makedirs(transcription_dir, exist_ok=True)
    temp_path = os.path.join(transcription_dir, f"temp_{uuid.uuid4().hex[:8]}{os.path.splitext(file.filename)[1]}")
    with open(temp_path, "wb") as handle:
        handle.write(await file.read())

    job = await enqueue_job(
        JOB_TYPE_TRANSCRIPTION,
        {
            "file_path": temp_path,
            "delete_after": True,
            "channel": "audio",
            "enqueue_signal_job": False,
        },
    )
    return {"status": job["status"], "job_id": job["job_id"]}


@router.post("/whatsapp-import")
async def import_whatsapp(req: WhatsAppImport):
    now = datetime.now(timezone.utc).isoformat()
    interaction_id = str(uuid.uuid4())

    async def _create_placeholder(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (req.person_id,)) as cursor:
            if not await cursor.fetchone():
                raise HTTPException(404, "Person not found")
        await db.execute(
            """
            INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, action_items, topics, sentiment, created_at, interaction_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (interaction_id, req.person_id, "whatsapp", req.conversation_text[:5000], "AI processing queued...", "[]", "[]", "neutral", now, now),
        )
        await db.execute("UPDATE PERSON SET cached_briefing=NULL, last_contact_datetime=?, last_updated_at=? WHERE person_id=?", (now, now, req.person_id))

    await run_write(_create_placeholder, label=f"queue whatsapp import {req.person_id}")

    job = await enqueue_job(
        JOB_TYPE_SIGNAL_EXTRACTION,
        {
            "interaction_id": interaction_id,
            "person_id": req.person_id,
            "channel": "whatsapp",
            "raw_text": req.conversation_text,
            "source_kind": "text",
        },
        person_id=req.person_id,
        interaction_id=interaction_id,
    )
    return {"status": "queued", "interaction_id": interaction_id, "job": job}


@router.post("/assistant/{person_id}/review")
async def intelligence_review(person_id: str):
    """Run the intelligence assistant over existing stored signals and upcoming events."""
    # load person and signals
    async def _load(db):
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as c:
            person = await c.fetchone()
        if not person:
            raise HTTPException(404, "Person not found")
        async with db.execute(
            "SELECT intel_id, topic AS category, intel_text AS text, confidence, created_at AS date, status, source_snippet AS snippet "
            "FROM TOPIC_INTELLIGENCE WHERE person_id=? ORDER BY created_at DESC",
            (person_id,),
        ) as c:
            signals = [dict(r) for r in await c.fetchall()]
        # upcoming events
        today = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            "SELECT e.event_id, e.event_name, e.event_date, e.topics, pe.status "
            "FROM EVENT e JOIN PERSON_EVENT pe ON e.event_id=pe.event_id "
            "WHERE pe.person_id=? AND e.event_date >= ? ORDER BY e.event_date ASC",
            (person_id, today),
        ) as c:
            events = [dict(r) for r in await c.fetchall()]
        return dict(person=dict(person), signals=signals, events=events)

    data = await run_read(_load, label=f"load intel review context {person_id}")
    from backend.services.ai_service import review_signals

    result = await review_signals(data["person"], data["signals"], data["events"])
    return result

@router.post("/backfill/{person_id}")
async def admin_backfill_person(person_id: str):
    async def _load_interactions(db):
        async with db.execute(
            "SELECT interaction_id, channel, raw_text FROM INTERACTION WHERE person_id=? AND channel != 'system_audit' AND raw_text IS NOT NULL ORDER BY interaction_at ASC",
            (person_id,),
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

    interactions = await run_read(_load_interactions, label=f"load backfill interactions {person_id}")
    jobs = []
    for interaction in interactions:
        jobs.append(await enqueue_job(
            JOB_TYPE_SIGNAL_EXTRACTION,
            {
                "interaction_id": interaction["interaction_id"],
                "person_id": person_id,
                "channel": interaction["channel"],
                "raw_text": interaction["raw_text"],
                "source_kind": "text",
            },
            person_id=person_id,
            interaction_id=interaction["interaction_id"],
        ))
    return {"status": "queued", "jobs": jobs, "count": len(jobs)}



