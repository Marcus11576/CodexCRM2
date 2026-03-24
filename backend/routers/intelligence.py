"""
Antigravity CRM - Intelligence Router
Briefings, AI chat, audio TTS, transcription jobs, and WhatsApp imports.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, List

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
    get_job,
    list_jobs,
)
from backend.services.ai_foundation import compute_duplicate_hash
from backend.services.ai_pipeline_service import create_or_update_artifact
from backend.services.ai_pipeline_service import load_profile_signals
from backend.services.preference_learning import record_feedback_event
from backend.services.transcript_guardrails import is_non_transcript_chat_input

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    assistant_context: dict[str, Any] | None = None


def _infer_chat_feedback_event(message: str) -> tuple[str, dict] | tuple[None, None]:
    text = str(message or "").strip()
    lowered = text.lower()
    correction_markers = (
        "should have",
        "should've",
        "you should",
        "not intuitive",
        "not intuative",
        "missed",
        "failed to suggest",
        "should suggest",
        "make sure it learns",
    )
    if not any(marker in lowered for marker in correction_markers):
        return None, None

    details = {
        "text": text,
        "source": "profile_chat_correction",
        "reason_code": "user_correction",
    }
    if any(term in lowered for term in ("task", "follow up", "follow-up", "call", "coffee", "after eid", "catch up", "catch-up")):
        details["preferred_behavior"] = "proactive_follow_up"
        return "missed_follow_up", details
    return "edit", details


def _build_topic_resolution_evidence_text(message: str, operation: dict) -> str:
    lines = [
        "Manual relationship topic update captured via profile assistant.",
        f"Topic: {str(operation.get('title') or 'Relationship topic').strip()}",
    ]
    if operation.get("situation_id"):
        lines.append(f"Situation ID: {str(operation.get('situation_id')).strip()}")
    state_line = " | ".join(
        part for part in (
            str(operation.get("status_label") or "").strip(),
            str(operation.get("stage") or "").strip(),
            str(operation.get("momentum") or "").strip(),
        )
        if part
    )
    if state_line:
        lines.append(f"Tracked state: {state_line}")
    if operation.get("current_read"):
        lines.append(f"Current read: {str(operation.get('current_read')).strip()}")
    if operation.get("why_it_matters"):
        lines.append(f"Why it matters: {str(operation.get('why_it_matters')).strip()}")
    if operation.get("resolution_note"):
        lines.append(f"Resolution note: {str(operation.get('resolution_note')).strip()}")
    if operation.get("recommended_action"):
        lines.append(f"Recommended action: {str(operation.get('recommended_action')).strip()}")
    lines.append("Operator update:")
    lines.append(str(message or "").strip())
    return "\n".join(line for line in lines if line)


class TtsRequest(BaseModel):
    text: str
    voice: str = "shimmer"


class WhatsAppImport(BaseModel):
    person_id: str
    conversation_text: str


def _brief_section_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip()).strip()
    if isinstance(value, dict):
        return " ".join(str(item).strip() for item in value.values() if str(item).strip()).strip()
    return str(value).strip()


def _normalize_brief_payload(payload: dict | None, brief_id: str | None = None) -> dict | None:
    if not payload:
        return payload
    normalized = dict(payload)
    normalized["business_focus"] = _brief_section_to_text(
        normalized.get("business_focus") or normalized.get("business_focus_summary")
    )
    normalized["recruitment_talent"] = _brief_section_to_text(
        normalized.get("recruitment_talent") or normalized.get("recruitment_talent_summary")
    )
    normalized["personal_rapport"] = _brief_section_to_text(
        normalized.get("personal_rapport") or normalized.get("family_personal_summary")
    )
    normalized["obe_focus"] = _brief_section_to_text(
        normalized.get("obe_focus") or normalized.get("obe_focus_summary")
    )
    normalized["overall_brief_summary"] = _brief_section_to_text(
        normalized.get("overall_brief_summary")
        or " ".join(
            section for section in (
                normalized.get("business_focus"),
                normalized.get("recruitment_talent"),
                normalized.get("personal_rapport"),
                normalized.get("obe_focus"),
            )
            if section
        )
    )
    normalized["audio_script"] = _brief_section_to_text(
        normalized.get("audio_script") or normalized.get("overall_brief_summary")
    )
    if brief_id and not normalized.get("brief_id"):
        normalized["brief_id"] = brief_id
    return normalized


async def _get_cached_brief_state(person_id: str):
    async def _load_person_and_brief(db):
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            person_row = await cursor.fetchone()
        async with db.execute(
            "SELECT brief_id, content_json, is_stale FROM AI_BRIEF WHERE person_id=? ORDER BY created_at DESC LIMIT 1",
            (person_id,),
        ) as cursor:
            brief_row = await cursor.fetchone()
        return person_row, brief_row

    row, brief_row = await run_read(_load_person_and_brief, label=f"load person {person_id} for brief")
    if not row:
        raise HTTPException(404, "Person not found")
    person = dict(row)
    brief_row = dict(brief_row) if brief_row else None

    cached = None
    if person.get("cached_briefing"):
        try:
            cached = json.loads(person["cached_briefing"])
        except Exception:
            cached = None

    if brief_row and brief_row.get("is_stale"):
        cached = None

    if not cached and brief_row and brief_row["content_json"]:
        try:
            cached = json.loads(brief_row["content_json"])
        except Exception:
            cached = None

    cached = _normalize_brief_payload(cached, brief_row["brief_id"] if brief_row else None)
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

    if force_refresh or not existing_job or existing_job["status"] == JOB_STATUS_FAILED:
        job = await enqueue_job(
            JOB_TYPE_BRIEF_GENERATION,
            {"person_id": person_id, "force_refresh": force_refresh},
            person_id=person_id,
            dedupe_key=f"{JOB_TYPE_BRIEF_GENERATION}:{person_id}",
        )
        return {"status": job["status"], "job_id": job["job_id"], "cached": False}

    if existing_job and existing_job["status"] == JOB_STATUS_COMPLETED and cached:
        return {"status": "completed", "briefing": cached, "cached": True}

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

    if req.assistant_context is None:
        chat_result = await profile_chat(person_id, person, req.message, req.history)
    else:
        chat_result = await profile_chat(person_id, person, req.message, req.history, req.assistant_context)
    response_text = chat_result.get('response') if isinstance(chat_result, dict) else str(chat_result)
    operations = chat_result.get('operations', []) if isinstance(chat_result, dict) else []
    sources = chat_result.get('sources', []) if isinstance(chat_result, dict) else []
    quick_actions = chat_result.get('quick_actions', []) if isinstance(chat_result, dict) else []
    result_type = chat_result.get('result_type') if isinstance(chat_result, dict) else None
    active_topic_context = (
        isinstance(req.assistant_context, dict)
        and str(req.assistant_context.get("type") or "").strip().lower() == "relationship_topic_resolution"
        and str(req.assistant_context.get("situation_record_id") or "").strip() != ""
    )

    now = datetime.now(timezone.utc).isoformat()
    resolution_op = next(
        (
            op for op in operations
            if op.get("type") == "resolve_relationship_topic" and op.get("status") == "completed"
        ),
        None,
    )

    logged_interaction_id: str | None = None

    if resolution_op:
        iid = str(uuid.uuid4())
        raw_text = _build_topic_resolution_evidence_text(req.message, resolution_op)
        action_items = []
        if resolution_op.get("recommended_action") and resolution_op.get("status") != "closed":
            action_items.append(str(resolution_op["recommended_action"]).strip())
        topics = ["relationship_topic_resolution"]
        if resolution_op.get("title"):
            topics.append(str(resolution_op["title"]).strip())

        async def _log_topic_resolution(db):
            nonlocal iid
            async with db.execute(
                """
                SELECT interaction_id
                FROM INTERACTION
                WHERE person_id = ?
                  AND channel = 'chat'
                  AND TRIM(COALESCE(raw_text, '')) = TRIM(?)
                ORDER BY datetime(created_at) DESC, interaction_id DESC
                LIMIT 1
                """,
                (person_id, req.message),
            ) as cursor:
                existing_chat = await cursor.fetchone()

            if existing_chat:
                iid = str(existing_chat["interaction_id"])
                await db.execute(
                    """
                    UPDATE INTERACTION
                    SET channel = ?, raw_text = ?, summary = ?, action_items = ?, topics = ?,
                        sentiment = ?, interaction_at = ?, direction = ?, meaningful_flag = ?,
                        outcome_type = ?, response_flag = ?, follow_up_committed_flag = ?
                    WHERE interaction_id = ?
                    """,
                    (
                        "chat_topic_resolution",
                        raw_text,
                        str(resolution_op.get("current_read") or resolution_op.get("title") or req.message[:200]).strip(),
                        json.dumps(action_items),
                        json.dumps(topics),
                        "neutral",
                        now,
                        "inbound",
                        1,
                        str(resolution_op.get("resolution_type") or resolution_op.get("status") or "updated"),
                        1,
                        1 if action_items else 0,
                        iid,
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO INTERACTION (
                        interaction_id, person_id, channel, raw_text, summary, action_items, topics,
                        sentiment, created_at, interaction_at, direction, meaningful_flag, outcome_type,
                        response_flag, follow_up_committed_flag
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        iid,
                        person_id,
                        "chat_topic_resolution",
                        raw_text,
                        str(resolution_op.get("current_read") or resolution_op.get("title") or req.message[:200]).strip(),
                        json.dumps(action_items),
                        json.dumps(topics),
                        "neutral",
                        now,
                        now,
                        "inbound",
                        1,
                        str(resolution_op.get("resolution_type") or resolution_op.get("status") or "updated"),
                        1,
                        1 if action_items else 0,
                    ),
                )
            await db.execute(
                "UPDATE PERSON SET cached_briefing=NULL, last_contact_datetime=?, last_updated_at=? WHERE person_id=?",
                (now, now, person_id),
            )

        await run_write(_log_topic_resolution, label=f"log topic resolution chat {person_id}")
        logged_interaction_id = iid

        duplicate_hash = compute_duplicate_hash(person_id, "chat_topic_resolution", raw_text)
        artifact = await create_or_update_artifact(
            person_id=person_id,
            channel="chat_topic_resolution",
            source_interaction_id=iid,
            raw_content=raw_text,
            source_name="chat_topic_resolution.txt",
            source_type="text",
            extracted_metadata={
                "assistant_context": req.assistant_context or {},
                "situation_record_id": resolution_op.get("situation_record_id"),
                "situation_id": resolution_op.get("situation_id"),
                "tracking_status": resolution_op.get("status"),
                "resolution_type": resolution_op.get("resolution_type"),
            },
            duplicate_hash=duplicate_hash,
            status="queued",
        )
        resolution_op["interaction_id"] = iid
        resolution_op["artifact_id"] = artifact.get("artifact_id")
        if artifact.get("status") != "duplicate" and settings.LEGACY_SCORING_ENABLED:
            job = await enqueue_job(
                JOB_TYPE_SIGNAL_EXTRACTION,
                {
                    "interaction_id": iid,
                    "person_id": person_id,
                    "channel": "chat_topic_resolution",
                    "raw_text": raw_text,
                    "source_kind": "text",
                    "artifact_id": artifact["artifact_id"],
                },
                person_id=person_id,
                interaction_id=iid,
                related_artifact_id=artifact["artifact_id"],
                dedupe_key=f"{JOB_TYPE_SIGNAL_EXTRACTION}:{artifact['artifact_id']}",
            )
            resolution_op["job"] = job
    else:
        control_prompt = (
            not active_topic_context
            and is_non_transcript_chat_input(req.message, channel="chat")
        )
        if not control_prompt:
            iid = str(uuid.uuid4())

            async def _log_chat(db):
                channel = "chat_topic_resolution" if active_topic_context else "chat"
                topics = ["relationship_topic_resolution"] if active_topic_context else []
                summary = (
                    str(req.assistant_context.get("title") or req.message[:200]).strip()
                    if active_topic_context
                    else req.message[:200]
                )
                await db.execute(
                    "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, action_items, topics, created_at, interaction_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (iid, person_id, channel, req.message, summary, "[]", json.dumps(topics), now, now),
                )
                await db.execute(
                    "UPDATE PERSON SET cached_briefing=NULL, last_contact_datetime=?, last_updated_at=? WHERE person_id=?",
                    (now, now, person_id),
                )

            await run_write(_log_chat, label=f"log profile chat {person_id}")
            logged_interaction_id = iid
    feedback_event, feedback_details = _infer_chat_feedback_event(req.message)
    if feedback_event and logged_interaction_id:
        await record_feedback_event(
            target_type="interaction",
            target_id=logged_interaction_id,
            event_type=feedback_event,
            details={"person_id": person_id, **(feedback_details or {})},
        )
    payload = {"response": response_text, "interaction_id": logged_interaction_id, "operations": operations}
    if isinstance(sources, list) and sources:
        payload["sources"] = sources
    if isinstance(quick_actions, list) and quick_actions:
        payload["quick_actions"] = quick_actions
    if isinstance(result_type, str) and result_type.strip():
        payload["result_type"] = result_type.strip()
    return payload


@router.get("/jobs/{job_id}")
async def get_intelligence_job(job_id: str):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/tts/{person_id}")
async def generate_audio_brief(person_id: str, req: TtsRequest):
    if not settings.OPENAI_CONFIGURED:
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
    if not settings.OPENAI_CONFIGURED:
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
    if settings.CHATBOT_ONLY_MODE:
        raise HTTPException(410, "WhatsApp import is disabled in chatbot-only mode. Use chat text, screenshots, or voice uploads.")
    if not settings.OPENAI_CONFIGURED:
        raise HTTPException(503, "AI import is unavailable until a valid OpenAI API key is configured")

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
    artifact = await create_or_update_artifact(
        person_id=req.person_id,
        channel="whatsapp",
        source_interaction_id=interaction_id,
        raw_content=req.conversation_text,
        source_name="whatsapp_import.txt",
        source_type="chat_transcript",
        extracted_metadata={"import_source": "whatsapp"},
        duplicate_hash=compute_duplicate_hash(req.person_id, "whatsapp", req.conversation_text),
        status="queued",
    )
    if artifact.get("status") == "duplicate":
        return {
            "status": "duplicate",
            "interaction_id": interaction_id,
            "artifact_id": artifact["artifact_id"],
        }

    job = await enqueue_job(
        JOB_TYPE_SIGNAL_EXTRACTION,
        {
            "interaction_id": interaction_id,
            "person_id": req.person_id,
            "channel": "whatsapp",
            "raw_text": req.conversation_text,
            "source_kind": "text",
            "artifact_id": artifact["artifact_id"],
        },
        person_id=req.person_id,
        interaction_id=interaction_id,
        related_artifact_id=artifact["artifact_id"],
        dedupe_key=f"{JOB_TYPE_SIGNAL_EXTRACTION}:{artifact['artifact_id']}",
    )
    return {"status": "queued", "interaction_id": interaction_id, "artifact_id": artifact["artifact_id"], "job": job}


@router.post("/assistant/{person_id}/review")
async def intelligence_review(person_id: str):
    """Run the intelligence assistant over existing stored signals and upcoming events."""
    if not settings.OPENAI_CONFIGURED:
        raise HTTPException(503, "AI review is unavailable until a valid OpenAI API key is configured")

    async def _load(db):
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as c:
            person = await c.fetchone()
        if not person:
            raise HTTPException(404, "Person not found")
        # upcoming events
        today = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            "SELECT e.event_id, e.event_name, e.event_date, e.topics, pe.status "
            "FROM EVENT e JOIN PERSON_EVENT pe ON e.event_id=pe.event_id "
            "WHERE pe.person_id=? AND e.event_date >= ? ORDER BY e.event_date ASC",
            (person_id, today),
        ) as c:
            events = [dict(r) for r in await c.fetchall()]
        return dict(person=dict(person), events=events)

    data = await run_read(_load, label=f"load intel review context {person_id}")
    signals = await load_profile_signals(person_id, include_rejected=False, limit=60)
    from backend.services.ai_service import review_signals

    result = await review_signals(data["person"], signals, data["events"])
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





