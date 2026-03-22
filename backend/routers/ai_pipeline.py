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
from backend.services.ai_foundation import canonical_business_subtopic, canonical_primary_category
from backend.services.ai_pipeline_service import (
    create_or_update_artifact,
    get_operations_summary,
    load_profile_signals,
    get_review_queue,
    invalidate_briefs_for_profile,
    suggest_matches_for_artifact_text,
)
from backend.services.preference_learning import normalize_feedback_event, record_feedback_event

router = APIRouter(prefix="/api/ai", tags=["ai-pipeline"])

SIGNAL_CATEGORIES = {
    "business_focus",
    "recruitment_talent",
    "family_personal",
    "obe_focus",
}


class ArtifactCreate(BaseModel):
    person_id: Optional[str] = None
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
    business_subtopic: Optional[str] = None
    manual: bool = False


class SignalStatusUpdate(BaseModel):
    status: Optional[str] = None
    text: Optional[str] = None
    category: Optional[str] = None
    business_subtopic: Optional[str] = None
    confidence: Optional[int] = None
    included_in_brief: Optional[bool] = None
    action: Optional[str] = None


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


class ProfileMatchRequest(BaseModel):
    query_text: str


@router.post("/artifacts")
async def create_artifact(req: ArtifactCreate):
    artifact = await create_or_update_artifact(
        person_id=req.person_id,
        channel=req.channel,
        source_interaction_id=req.source_interaction_id,
        raw_content=req.raw_content,
        media_url=req.media_url,
        source_name=(req.metadata or {}).get("source_name"),
        source_type=(req.metadata or {}).get("source_type") or req.channel,
        extracted_metadata=req.metadata or {},
        status="needs_review" if not req.person_id else "queued",
        profile_match_state="needs_review" if not req.person_id else "confirmed",
        requires_confirmation=not bool(req.person_id),
    )
    suggestions = []
    if not req.person_id and req.raw_content:
        suggestions = await suggest_matches_for_artifact_text(req.raw_content[:500])
    return {"artifact_id": artifact["artifact_id"], "artifact": artifact, "suggested_matches": suggestions}


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

    artifact_id = req.artifact_id
    business_subtopic = canonical_business_subtopic(req.business_subtopic) if category == "business_focus" else None
    if not artifact_id:
        artifact = await create_or_update_artifact(
            person_id=req.person_id,
            channel="manual_note",
            raw_content=req.content,
            source_name="manual_signal.txt",
            source_type="manual_signal",
            extracted_metadata={"manual": True},
            status="processed",
            input_type="manual_note",
            input_type_confidence=1.0,
        )
        artifact_id = artifact["artifact_id"]
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category,
                content, signal_text, source_snippet, confidence, confidence_score, status,
                review_state, signal_sentiment, signal_sentiment_confidence, importance_score,
                source_strength, section_hypothesis_fit_score, overall_hypothesis_fit_score,
                business_subtopic, secondary_relevance_json, included_in_brief, created_at, updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sid,
                artifact_id,
                req.person_id,
                req.person_id,
                category,
                category,
                req.content,
                req.content,
                req.source_snippet,
                req.confidence,
                round(max(min(req.confidence / 5.0, 1.0), 0.05), 3),
                "approved",
                "approved",
                "Unclear",
                1.0,
                0.8,
                0.9,
                0.7,
                0.7,
                business_subtopic,
                json.dumps([]),
                1,
                now,
                now,
            ),
        )
        await db.commit()
    await invalidate_briefs_for_profile(req.person_id)

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
    action = normalize_feedback_event(req.action) if req.action else None
    target_is_legacy = signal_id.startswith("legacy:")
    raw_id = signal_id.split(":", 1)[1] if target_is_legacy else signal_id

    async with get_db() as db:
        if target_is_legacy:
            async with db.execute(
                "SELECT person_id, intel_text, topic, business_subtopic, confidence, status FROM TOPIC_INTELLIGENCE WHERE intel_id = ?",
                (raw_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise HTTPException(404, "Signal not found")
            current = dict(row)

            fields = []
            values = []
            feedback_events = []

            if req.text is not None:
                fields.append("intel_text = ?")
                values.append(req.text.strip())
                feedback_events.append(("edit", {"before_text": current.get("intel_text"), "after_text": req.text.strip()}))
            if req.category is not None:
                category = canonical_primary_category(req.category)
                fields.append("topic = ?")
                values.append(category)
                feedback_events.append(("reclassify_category", {"before_category": current.get("topic"), "after_category": category}))
                if category != "business_focus":
                    fields.append("business_subtopic = NULL")
            if req.business_subtopic is not None:
                subtopic = canonical_business_subtopic(req.business_subtopic) if (req.category or current.get("topic")) == "business_focus" else None
                fields.append("business_subtopic = ?")
                values.append(subtopic)
            if req.confidence is not None:
                bounded_confidence = max(1, min(int(req.confidence), 5))
                fields.append("confidence = ?")
                values.append(bounded_confidence)
            if req.status is not None:
                normalized_status = req.status.strip().lower()
                if normalized_status not in {"draft", "approved", "rejected", "archived"}:
                    raise HTTPException(400, "Invalid signal status")
                fields.append("status = ?")
                values.append(normalized_status)
                if normalized_status == "approved":
                    feedback_events.append(("approve", {"reason_code": "status_change"}))
                if normalized_status == "rejected":
                    feedback_events.append(("reject", {"reason_code": "status_change"}))
                if normalized_status == "archived":
                    feedback_events.append(("exclude_from_brief", {"reason_code": "archive"}))

            if fields:
                values.append(raw_id)
                await db.execute(
                    f"UPDATE TOPIC_INTELLIGENCE SET {', '.join(fields)} WHERE intel_id = ?",
                    tuple(values),
                )

            if action == "promote":
                await db.execute(
                    "UPDATE TOPIC_INTELLIGENCE SET confidence = MIN(5, COALESCE(confidence, 3) + 1), status = 'approved' WHERE intel_id = ?",
                    (raw_id,),
                )
                feedback_events.append(("promote", {"reason_code": "manual_review"}))
            elif action == "demote":
                await db.execute(
                    "UPDATE TOPIC_INTELLIGENCE SET confidence = MAX(1, COALESCE(confidence, 3) - 1) WHERE intel_id = ?",
                    (raw_id,),
                )
                feedback_events.append(("demote", {"reason_code": "manual_review"}))
            elif action == "approve":
                await db.execute("UPDATE TOPIC_INTELLIGENCE SET status = 'approved' WHERE intel_id = ?", (raw_id,))
                feedback_events.append(("approve", {"reason_code": "manual_review"}))
            elif action == "reject":
                await db.execute("UPDATE TOPIC_INTELLIGENCE SET status = 'rejected' WHERE intel_id = ?", (raw_id,))
                feedback_events.append(("reject", {"reason_code": "manual_review"}))

            await db.commit()
            profile_id = current["person_id"]
        else:
            async with db.execute(
                """
                SELECT COALESCE(profile_id, person_id) AS profile_id, signal_text, primary_category, confidence,
                       included_in_brief, status, review_state, importance_score, business_subtopic
                FROM AI_SIGNAL WHERE signal_id = ?
                """,
                (raw_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise HTTPException(404, "Signal not found")
            current = dict(row)

            fields = ["updated_at = ?"]
            values = [now]
            feedback_events = []

            if req.text is not None:
                next_text = req.text.strip()
                fields.extend(["signal_text = ?", "content = ?"])
                values.extend([next_text, next_text])
                feedback_events.append(("edit", {"before_text": current.get("signal_text"), "after_text": next_text}))
            if req.category is not None:
                category = canonical_primary_category(req.category)
                fields.extend(["primary_category = ?", "category = ?"])
                values.extend([category, category])
                feedback_events.append(("reclassify_category", {"before_category": current.get("primary_category"), "after_category": category}))
                if category != "business_focus":
                    fields.append("business_subtopic = NULL")
            if req.business_subtopic is not None:
                active_category = req.category or current.get("primary_category")
                subtopic = canonical_business_subtopic(req.business_subtopic) if active_category == "business_focus" else None
                fields.append("business_subtopic = ?")
                values.append(subtopic)
            if req.confidence is not None:
                bounded_confidence = max(1, min(int(req.confidence), 5))
                fields.extend(["confidence = ?", "confidence_score = ?"])
                values.extend([bounded_confidence, round(bounded_confidence / 5.0, 3)])
            if req.included_in_brief is not None:
                included = 1 if req.included_in_brief else 0
                fields.append("included_in_brief = ?")
                values.append(included)
                feedback_events.append((
                    "include_in_brief" if included else "exclude_from_brief",
                    {"reason_code": "manual_review"},
                ))
            if req.status is not None:
                normalized_status = req.status.strip().lower()
                if normalized_status not in {"draft", "approved", "rejected", "archived"}:
                    raise HTTPException(400, "Invalid signal status")
                review_state = "approved" if normalized_status == "approved" else "rejected" if normalized_status == "rejected" else "pending_review"
                fields.extend(["status = ?", "review_state = ?"])
                values.extend([normalized_status, review_state])
                if normalized_status == "archived":
                    fields.append("included_in_brief = 0")
                if normalized_status == "approved":
                    feedback_events.append(("approve", {"reason_code": "status_change"}))
                if normalized_status == "rejected":
                    feedback_events.append(("reject", {"reason_code": "status_change"}))
                if normalized_status == "archived":
                    feedback_events.append(("exclude_from_brief", {"reason_code": "archive"}))

            if action == "promote":
                fields.extend(["importance_score = MIN(1.0, COALESCE(importance_score, 0.5) + 0.12)", "review_state = 'approved'", "status = 'approved'"])
                feedback_events.append(("promote", {"reason_code": "manual_review"}))
            elif action == "demote":
                fields.append("importance_score = MAX(0.05, COALESCE(importance_score, 0.5) - 0.12)")
                feedback_events.append(("demote", {"reason_code": "manual_review"}))
            elif action == "approve":
                fields.extend(["status = 'approved'", "review_state = 'approved'"])
                feedback_events.append(("approve", {"reason_code": "manual_review"}))
            elif action == "reject":
                fields.extend(["status = 'rejected'", "review_state = 'rejected'", "included_in_brief = 0"])
                feedback_events.append(("reject", {"reason_code": "manual_review"}))

            values.append(raw_id)
            await db.execute(
                f"UPDATE AI_SIGNAL SET {', '.join(fields)} WHERE signal_id = ?",
                tuple(values),
            )
            await db.commit()
            profile_id = current["profile_id"]

    if profile_id:
        await invalidate_briefs_for_profile(profile_id)
    for event_type, details in feedback_events:
        await record_feedback_event(
            target_type="signal",
            target_id=raw_id,
            event_type=event_type,
            details={"source": "signal_status_patch", "person_id": profile_id, **details},
        )

    refreshed = await load_profile_signals(profile_id, include_rejected=True)
    updated = next((item for item in refreshed if item["signal_ref"] == signal_id), None)
    return {"status": "updated", "signal": updated}


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
    if req.target_type not in {"signal", "brief", "interaction", "artifact"}:
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


@router.get("/review-queue")
async def review_queue(limit: int = 50):
    return await get_review_queue(limit=limit)


@router.get("/ops/summary")
async def ops_summary():
    return await get_operations_summary()


@router.post("/profile-match/suggest")
async def suggest_profile_match(req: ProfileMatchRequest):
    return {"matches": await suggest_matches_for_artifact_text(req.query_text)}

