"""
Antigravity CRM - Interactions Router
Creates lightweight interaction records and offloads AI enrichment into background jobs.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.config import settings
from backend.database import run_read, run_write
from backend.services.ai_jobs import (
    JOB_TYPE_SIGNAL_EXTRACTION,
    JOB_TYPE_TRANSCRIPTION,
    enqueue_job,
)

router = APIRouter(prefix="/api/interactions", tags=["interactions"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class InteractionCreate(BaseModel):
    person_id: str
    channel: str = "note"
    raw_text: str
    interaction_at: Optional[str] = None
    process_with_ai: bool = True


class InteractionUpdate(BaseModel):
    raw_text: str


class InteractionRealign(BaseModel):
    feedback: str


async def _persist_interaction(db, iid, person_id, channel, raw_text, result, now, interaction_at, media_url=None):
    summary = result.get("summary", raw_text[:300])
    action_items = result.get("action_items", [])
    topics = result.get("topics", [])
    sentiment = result.get("sentiment", "neutral")
    intel_nuggets = result.get("topic_nuggets", [])
    success = result.get("success_metrics", {})

    await db.execute(
        """
        INSERT INTO INTERACTION
        (interaction_id, person_id, channel, raw_text, summary, media_url,
         action_items, topics, sentiment, created_at, interaction_at,
         success_rating, engagement_value, is_strategic, metric_tags)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(interaction_id) DO UPDATE SET
            raw_text = excluded.raw_text,
            summary = excluded.summary,
            media_url = excluded.media_url,
            action_items = excluded.action_items,
            topics = excluded.topics,
            sentiment = excluded.sentiment,
            success_rating = excluded.success_rating,
            engagement_value = excluded.engagement_value,
            is_strategic = excluded.is_strategic,
            metric_tags = excluded.metric_tags
        """,
        (
            iid,
            person_id,
            channel,
            raw_text,
            summary,
            media_url,
            json.dumps(action_items),
            json.dumps(topics),
            sentiment,
            now,
            interaction_at,
            success.get("rating"),
            success.get("engagement_value"),
            success.get("is_strategic", 0),
            json.dumps(success.get("tags", [])),
        ),
    )

    for nug in intel_nuggets:
        if not isinstance(nug, dict):
            continue
        topic = nug.get("topic")
        text = nug.get("text")
        snippet = nug.get("snippet") or text
        if topic and text and topic in {"business_focus", "recruitment_talent", "family_personal", "obe_focus"}:
            await db.execute(
                """
                INSERT INTO TOPIC_INTELLIGENCE
                (intel_id, person_id, topic, intel_text, confidence, source_interaction_id, status, source_snippet, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (str(uuid.uuid4())[:12], person_id, topic, text, nug.get("confidence", 3), iid, "draft", snippet, now),
            )

    for item in action_items:
        await db.execute(
            "INSERT INTO TASK (task_id, person_id, task_text, status, source_interaction_id, created_at) VALUES (?,?,?,'open',?,?)",
            (str(uuid.uuid4())[:12], person_id, item, iid, now),
        )

    from backend.services.ai_service import ALLOWED_PROFILE_FIELDS

    profile_updates = result.get("profile_updates", {})
    update_fields = []
    update_values = []
    for field, value in profile_updates.items():
        if field in ALLOWED_PROFILE_FIELDS and value:
            update_fields.append(f"{field}=?")
            update_values.append(value)

    if update_fields:
        query = f"UPDATE PERSON SET {', '.join(update_fields)}, last_contact_datetime=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?"
        update_values.extend([now, now, person_id])
        await db.execute(query, update_values)
    else:
        await db.execute(
            "UPDATE PERSON SET last_contact_datetime=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
            (now, now, person_id),
        )

    return {
        "status": "success",
        "interaction_id": iid,
        "summary": summary,
        "action_items": action_items,
        "topics": topics,
    }


async def _create_pending_interaction(person_id: str, channel: str, raw_text: str, interaction_at: Optional[str], media_url: Optional[str] = None):
    iid = str(uuid.uuid4())
    now = _now()
    interaction_at = interaction_at or now

    async def _insert_pending(db):
        await db.execute(
            """
            INSERT INTO INTERACTION
            (interaction_id, person_id, channel, raw_text, summary, media_url, action_items, topics, sentiment, created_at, interaction_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (iid, person_id, channel, raw_text, "AI processing queued...", media_url, "[]", "[]", "neutral", now, interaction_at),
        )
        await db.execute(
            "UPDATE PERSON SET last_contact_datetime=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
            (now, now, person_id),
        )

    await run_write(_insert_pending, label=f"create pending interaction {person_id}")
    return iid


@router.post("")
async def create_interaction(req: InteractionCreate):
    async def _person_exists(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (req.person_id,)) as cursor:
            return await cursor.fetchone()

    if not await run_read(_person_exists, label=f"check person {req.person_id}"):
        raise HTTPException(404, "Person not found")

    interaction_id = await _create_pending_interaction(req.person_id, req.channel, req.raw_text, req.interaction_at)
    response = {"status": "queued", "interaction_id": interaction_id, "message": "Interaction saved. AI processing is running in the background."}

    if req.process_with_ai and settings.OPENAI_API_KEY:
        job = await enqueue_job(
            JOB_TYPE_SIGNAL_EXTRACTION,
            {
                "interaction_id": interaction_id,
                "person_id": req.person_id,
                "channel": req.channel,
                "raw_text": req.raw_text,
                "source_kind": "text",
            },
            person_id=req.person_id,
            interaction_id=interaction_id,
        )
        response["job"] = job
    return response


@router.post("/upload/{person_id}")
async def upload_media(person_id: str, file: UploadFile = File(...)):
    async def _load_person(db):
        async with db.execute("SELECT full_name FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            return await cursor.fetchone()

    row = await run_read(_load_person, label=f"load person {person_id} for upload")
    if not row:
        raise HTTPException(404, "Person not found")

    upload_dir = os.path.join(settings.UPLOADS_DIR, person_id)
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(upload_dir, filename)
    content = await file.read()
    with open(file_path, "wb") as handle:
        handle.write(content)

    ext = os.path.splitext(filename)[1].lower()
    media_url = f"/uploads/{person_id}/{filename}"
    channel = "upload"
    source_kind = "text"
    raw_text = f"Uploaded file: {file.filename}"
    job = None

    if ext in (".jpg", ".jpeg", ".png", ".webp"):
        channel = "screenshot"
        source_kind = "image"
        raw_text = f"Image uploaded: {file.filename}"
    elif ext in (".webm", ".mp3", ".m4a", ".wav", ".ogg"):
        channel = "audio"
        source_kind = "audio"
        raw_text = f"Audio uploaded: {file.filename}. Transcription pending."
    elif ext in (".pdf", ".txt"):
        channel = "document"
        source_kind = "document"
        raw_text = f"Document uploaded: {file.filename}. Extraction pending."

    interaction_id = await _create_pending_interaction(person_id, channel, raw_text, None, media_url=media_url)

    if settings.OPENAI_API_KEY:
        if source_kind == "audio":
            job = await enqueue_job(
                JOB_TYPE_TRANSCRIPTION,
                {
                    "interaction_id": interaction_id,
                    "person_id": person_id,
                    "channel": channel,
                    "file_path": file_path,
                    "media_url": media_url,
                    "enqueue_signal_job": True,
                    "source_kind": source_kind,
                },
                person_id=person_id,
                interaction_id=interaction_id,
            )
        else:
            job = await enqueue_job(
                JOB_TYPE_SIGNAL_EXTRACTION,
                {
                    "interaction_id": interaction_id,
                    "person_id": person_id,
                    "channel": channel,
                    "raw_text": raw_text,
                    "file_path": file_path,
                    "media_url": media_url,
                    "source_kind": source_kind,
                },
                person_id=person_id,
                interaction_id=interaction_id,
            )

    return {
        "status": "queued",
        "interaction_id": interaction_id,
        "media_url": media_url,
        "channel": channel,
        "job": job,
        "message": "Upload received. AI processing is running in the background.",
    }


@router.post("/{interaction_id}/realign")
async def realign_interaction_api(interaction_id: str, req: InteractionRealign):
    async def _prepare_realign(db):
        async with db.execute("SELECT person_id, channel, raw_text FROM INTERACTION WHERE interaction_id=?", (interaction_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Interaction not found")
        await db.execute("DELETE FROM TOPIC_INTELLIGENCE WHERE source_interaction_id=?", (interaction_id,))
        await db.execute("DELETE FROM TASK WHERE source_interaction_id=? AND status='open'", (interaction_id,))
        return dict(row)

    row = await run_write(_prepare_realign, label=f"prepare realign {interaction_id}")

    job = await enqueue_job(
        JOB_TYPE_SIGNAL_EXTRACTION,
        {
            "interaction_id": interaction_id,
            "person_id": row["person_id"],
            "channel": row["channel"],
            "raw_text": row["raw_text"],
            "source_kind": "text",
        },
        person_id=row["person_id"],
        interaction_id=interaction_id,
    )
    return {"status": "queued", "interaction_id": interaction_id, "job": job}


@router.put("/{interaction_id}")
async def update_interaction(interaction_id: str, req: InteractionUpdate):
    async def _update(db):
        async with db.execute("SELECT interaction_id FROM INTERACTION WHERE interaction_id=?", (interaction_id,)) as cursor:
            if not await cursor.fetchone():
                raise HTTPException(404, "Interaction not found")
        await db.execute("UPDATE INTERACTION SET raw_text=?, summary=? WHERE interaction_id=?", (req.raw_text, req.raw_text[:300], interaction_id))

    await run_write(_update, label=f"update interaction {interaction_id}")
    return {"status": "success"}


@router.delete("/{interaction_id}")
async def delete_interaction(interaction_id: str):
    async def _delete(db):
        await db.execute("DELETE FROM INTERACTION WHERE interaction_id=?", (interaction_id,))
        await db.execute("DELETE FROM AI_JOB WHERE interaction_id=?", (interaction_id,))

    await run_write(_delete, label=f"delete interaction {interaction_id}")
    return {"status": "success"}
