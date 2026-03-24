"""
Antigravity CRM - Interactions Router
Creates lightweight interaction records and offloads AI enrichment into background jobs.
"""
import json
import imghdr
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from backend.config import settings
from backend.database import run_read, run_write
from backend.services.ai_foundation import compute_duplicate_hash
from backend.services.ai_jobs import (
    JOB_TYPE_SIGNAL_EXTRACTION,
    JOB_TYPE_TRANSCRIPTION,
    enqueue_job,
)
from backend.services.ai_pipeline_service import create_or_update_artifact, get_artifact
from backend.services.transcript_guardrails import is_non_transcript_chat_input

router = APIRouter(prefix="/api/interactions", tags=["interactions"])

CHATBOT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CHATBOT_AUDIO_EXTENSIONS = {".webm", ".mp3", ".m4a", ".wav", ".ogg"}
CHATBOT_DOCUMENT_EXTENSIONS = {".pdf", ".txt"}
RELATIONSHIP_STAGE_CODES = {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_channel(value: str | None) -> str:
    return str(value or "").strip().lower()


def _enforce_chatbot_channel(channel: str) -> str:
    normalized = _normalize_channel(channel)
    if not normalized:
        normalized = "note"
    if settings.CHATBOT_ONLY_MODE and normalized not in set(settings.CHATBOT_ALLOWED_TEXT_CHANNELS):
        raise HTTPException(
            status_code=422,
            detail=(
                "Only chatbot-sourced text channels are allowed in chatbot-only mode: "
                + ", ".join(settings.CHATBOT_ALLOWED_TEXT_CHANNELS)
            ),
        )
    return normalized


def _recover_mojibake_filename(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = text.strip("\"'")
    if any(marker in candidate for marker in ("Ã", "Â", "Ð", "Ñ")):
        try:
            repaired = candidate.encode("latin-1").decode("utf-8")
            if repaired and "\ufffd" not in repaired:
                candidate = repaired
        except Exception:
            pass
    return candidate


def _safe_upload_filename(filename: Optional[str]) -> str:
    recovered = _recover_mojibake_filename(str(filename or ""))
    base = os.path.basename(recovered.replace("\\", "/")).strip()
    if not base:
        base = "upload.bin"
    base = "".join(ch for ch in base if ch >= " " and ch != "\x7f")
    base = re.sub(r"\s+", " ", base).strip()
    base = re.sub(r"[<>:\"/\\\\|?*]+", "_", base)
    base = base.strip(" .")
    if not base:
        base = "upload.bin"
    stem, ext = os.path.splitext(base)
    stem = stem[:120].strip() or "upload"
    ext = ext[:20]
    return f"{stem}{ext}"


def _normalized_profile_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _has_structured_employment_history(raw_value: Any) -> bool:
    if isinstance(raw_value, list):
        rows = raw_value
    else:
        text = str(raw_value or "").strip()
        if not text:
            return False
        try:
            decoded = json.loads(text)
        except Exception:
            return False
        if not isinstance(decoded, list):
            return False
        rows = decoded

    for item in rows:
        if not isinstance(item, dict):
            continue
        if any(str(item.get(key) or "").strip() for key in ("title", "company", "start_date", "end_date", "location", "description")):
            return True
    return False


def _coerce_employment_history_rows(raw_value: Any) -> list[dict]:
    parsed = raw_value
    if isinstance(parsed, str):
        text = parsed.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []

    cleaned: list[dict] = []
    for role in parsed:
        if not isinstance(role, dict):
            continue
        normalized = {
            "title": str(role.get("title") or "").strip(),
            "company": str(role.get("company") or "").strip(),
            "start_date": str(role.get("start_date") or "").strip(),
            "end_date": str(role.get("end_date") or "").strip(),
            "location": str(role.get("location") or "").strip(),
            "description": str(role.get("description") or "").strip(),
        }
        if any(normalized.values()):
            cleaned.append(normalized)
    return cleaned


def _employment_role_identity(role: dict[str, Any]) -> tuple[str, str]:
    return (
        _normalized_profile_value(role.get("title")),
        _normalized_profile_value(role.get("company")),
    )


def _merge_document_employment_history(existing_raw: Any, incoming_roles: list[dict]) -> tuple[list[dict], bool]:
    merged_rows = _coerce_employment_history_rows(existing_raw)
    changed = False

    if not merged_rows and incoming_roles:
        return list(incoming_roles), True

    index_by_identity: dict[tuple[str, str], int] = {}
    for idx, role in enumerate(merged_rows):
        identity = _employment_role_identity(role)
        if identity == ("", ""):
            continue
        index_by_identity.setdefault(identity, idx)

    for incoming in incoming_roles:
        identity = _employment_role_identity(incoming)
        existing_idx = index_by_identity.get(identity) if identity != ("", "") else None
        if existing_idx is None:
            merged_rows.append(incoming)
            changed = True
            if identity != ("", ""):
                index_by_identity[identity] = len(merged_rows) - 1
            continue

        existing = merged_rows[existing_idx]
        for field in ("title", "company", "start_date", "end_date", "location", "description"):
            current = str(existing.get(field) or "").strip()
            incoming_value = str(incoming.get(field) or "").strip()
            if incoming_value and not current:
                existing[field] = incoming_value
                changed = True

    return merged_rows, changed


def _seeded_career_summary(full_name: str, title_current: str, company_name_raw: str) -> str:
    person_name = str(full_name or "").strip() or "This contact"
    title = str(title_current or "").strip()
    company = str(company_name_raw or "").strip()
    if title and company:
        return f"{person_name} is currently {title} at {company}."
    if title:
        return f"{person_name} currently works as {title}."
    if company:
        return f"{person_name} is currently associated with {company}."
    return ""


def _looks_seeded_career_summary(current_summary: str, existing_person: dict[str, Any]) -> bool:
    current = str(current_summary or "").strip()
    if not current:
        return False
    canonical = _seeded_career_summary(
        str(existing_person.get("full_name") or ""),
        str(existing_person.get("title_current") or ""),
        str(existing_person.get("company_name_raw") or ""),
    )
    if canonical and _normalized_profile_value(current) == _normalized_profile_value(canonical):
        return True
    lowered = _normalized_profile_value(current)
    return " is currently " in lowered and lowered.endswith(".")


async def _resolve_canonical_artifact(artifact_id: str, *, max_hops: int = 6) -> Optional[dict]:
    current_id = str(artifact_id or "").strip()
    visited: set[str] = set()
    for _ in range(max_hops):
        if not current_id or current_id in visited:
            break
        visited.add(current_id)
        artifact = await get_artifact(current_id)
        if not artifact:
            return None
        if str(artifact.get("status") or "").strip().lower() != "duplicate":
            return artifact
        next_id = str(artifact.get("duplicate_of_artifact_id") or "").strip()
        if not next_id:
            return artifact
        current_id = next_id
    return None


class InteractionCreate(BaseModel):
    person_id: str
    channel: str = "note"
    raw_text: str
    interaction_at: Optional[str] = None
    process_with_ai: bool = True
    direction: Optional[str] = None
    meaningful_flag: bool = False
    outcome_type: Optional[str] = None
    response_flag: bool = False
    follow_up_committed_flag: bool = False


class InteractionUpdate(BaseModel):
    raw_text: str


class InteractionRealign(BaseModel):
    feedback: str


class InteractionStageOverrideUpdate(BaseModel):
    relationship_stage_code: Optional[str] = None
    clear_override: bool = False


def _normalize_stage_code(value: Optional[str]) -> Optional[str]:
    code = str(value or "").strip().upper()
    return code or None


async def _persist_interaction(
    db,
    iid,
    person_id,
    channel,
    raw_text,
    result,
    now,
    interaction_at,
    media_url=None,
    direction=None,
    meaningful_flag: bool = False,
    outcome_type=None,
    response_flag: bool = False,
    follow_up_committed_flag: bool = False,
):
    summary = result.get("summary", raw_text[:300])
    action_items = result.get("action_items", [])
    topics = result.get("topics", [])
    sentiment = result.get("sentiment", "neutral")
    success = result.get("success_metrics", {})

    await db.execute(
        """
        INSERT INTO INTERACTION
        (interaction_id, person_id, channel, raw_text, summary, media_url,
         action_items, topics, sentiment, created_at, interaction_at,
         success_rating, engagement_value, is_strategic, metric_tags,
         direction, meaningful_flag, outcome_type, response_flag, follow_up_committed_flag)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(interaction_id) DO UPDATE SET
            channel = excluded.channel,
            raw_text = excluded.raw_text,
            summary = excluded.summary,
            media_url = excluded.media_url,
            action_items = excluded.action_items,
            topics = excluded.topics,
            sentiment = excluded.sentiment,
            interaction_at = excluded.interaction_at,
            success_rating = excluded.success_rating,
            engagement_value = excluded.engagement_value,
            is_strategic = excluded.is_strategic,
            metric_tags = excluded.metric_tags,
            direction = excluded.direction,
            meaningful_flag = excluded.meaningful_flag,
            outcome_type = excluded.outcome_type,
            response_flag = excluded.response_flag,
            follow_up_committed_flag = excluded.follow_up_committed_flag
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
            direction,
            1 if meaningful_flag else 0,
            outcome_type,
            1 if response_flag else 0,
            1 if follow_up_committed_flag else 0,
        ),
    )

    for item in action_items:
        await db.execute(
            "INSERT INTO TASK (task_id, person_id, task_text, status, source_interaction_id, created_at) VALUES (?,?,?,'open',?,?)",
            (str(uuid.uuid4())[:12], person_id, item, iid, now),
        )

    from backend.services.ai_service import ALLOWED_PROFILE_FIELDS

    profile_updates = result.get("profile_updates")
    if not isinstance(profile_updates, dict):
        profile_updates = {}

    is_document_channel = _normalize_channel(channel) == "document"
    existing_person = {}
    if is_document_channel:
        async with db.execute(
            """
            SELECT full_name, title_current, company_name_raw, email_primary, phone_primary, linkedin_url,
                   cat, env, disc, contact_value, career_summary, key_professional_notes, employment_history
            FROM PERSON WHERE person_id=?
            """,
            (person_id,),
        ) as cursor:
            existing_row = await cursor.fetchone()
        if existing_row:
            existing_person = dict(existing_row)

    merged_updates: dict[str, Any] = {}
    if is_document_channel:
        # Document enrichments should be additive-safe. We only fill missing profile
        # attributes, except role/company in the profile head which should refresh when changed.
        for field in ("email_primary", "phone_primary", "linkedin_url"):
            incoming = str(profile_updates.get(field) or "").strip()
            if incoming and not str(existing_person.get(field) or "").strip():
                merged_updates[field] = incoming
        for field in ("title_current", "company_name_raw"):
            incoming = str(profile_updates.get(field) or "").strip()
            current = str(existing_person.get(field) or "").strip()
            if incoming and _normalized_profile_value(incoming) != _normalized_profile_value(current):
                merged_updates[field] = incoming
    else:
        for field, value in profile_updates.items():
            if field in ALLOWED_PROFILE_FIELDS and value:
                merged_updates[field] = value

    employment_history = result.get("employment_history")
    if isinstance(employment_history, list):
        cleaned_history = []
        for role in employment_history:
            if not isinstance(role, dict):
                continue
            cleaned_history.append({
                "title": str(role.get("title") or "").strip(),
                "company": str(role.get("company") or "").strip(),
                "start_date": str(role.get("start_date") or "").strip(),
                "end_date": str(role.get("end_date") or "").strip(),
                "location": str(role.get("location") or "").strip(),
                "description": str(role.get("description") or "").strip(),
            })
        if cleaned_history:
            if is_document_channel:
                merged_history, history_changed = _merge_document_employment_history(
                    existing_person.get("employment_history"),
                    cleaned_history,
                )
                if history_changed:
                    merged_updates["employment_history"] = json.dumps(merged_history, ensure_ascii=False)
            else:
                merged_updates["employment_history"] = json.dumps(cleaned_history, ensure_ascii=False)

    career_summary = str(result.get("career_summary") or "").strip()
    if career_summary:
        if (
            not is_document_channel
            or not str(existing_person.get("career_summary") or "").strip()
            or _looks_seeded_career_summary(str(existing_person.get("career_summary") or ""), existing_person)
        ):
            merged_updates["career_summary"] = career_summary

    key_professional_notes = str(result.get("key_professional_notes") or "").strip()
    if key_professional_notes:
        if not is_document_channel or not str(existing_person.get("key_professional_notes") or "").strip():
            merged_updates["key_professional_notes"] = key_professional_notes

    update_fields = [f"{field}=?" for field in merged_updates.keys()]
    update_values = list(merged_updates.values())
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


async def _create_pending_interaction(
    person_id: str,
    channel: str,
    raw_text: str,
    interaction_at: Optional[str],
    media_url: Optional[str] = None,
    direction: Optional[str] = None,
    meaningful_flag: bool = False,
    outcome_type: Optional[str] = None,
    response_flag: bool = False,
    follow_up_committed_flag: bool = False,
):
    iid = str(uuid.uuid4())
    now = _now()
    interaction_at = interaction_at or now

    async def _insert_pending(db):
        await db.execute(
            """
            INSERT INTO INTERACTION
            (interaction_id, person_id, channel, raw_text, summary, media_url, action_items, topics, sentiment, created_at, interaction_at,
             direction, meaningful_flag, outcome_type, response_flag, follow_up_committed_flag)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                iid, person_id, channel, raw_text, "AI processing queued...", media_url, "[]", "[]", "neutral", now, interaction_at,
                direction, 1 if meaningful_flag else 0, outcome_type, 1 if response_flag else 0, 1 if follow_up_committed_flag else 0,
            ),
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

    channel = _enforce_chatbot_channel(req.channel)
    if is_non_transcript_chat_input(req.raw_text, channel=channel):
        return {
            "status": "ignored",
            "interaction_id": None,
            "artifact_id": None,
            "message": "Control prompt ignored. Transcript evidence was not created.",
        }

    interaction_id = await _create_pending_interaction(
        req.person_id,
        channel,
        req.raw_text,
        req.interaction_at,
        direction=req.direction,
        meaningful_flag=req.meaningful_flag,
        outcome_type=req.outcome_type,
        response_flag=req.response_flag,
        follow_up_committed_flag=req.follow_up_committed_flag,
    )
    duplicate_hash = compute_duplicate_hash(req.person_id, channel, req.raw_text)
    artifact = await create_or_update_artifact(
        person_id=req.person_id,
        channel=channel,
        source_interaction_id=interaction_id,
        raw_content=req.raw_text,
        source_name=f"{channel}_note.txt",
        source_type="text",
        extracted_metadata={"interaction_at": req.interaction_at, "channel": channel},
        duplicate_hash=duplicate_hash,
        status="queued",
    )
    response = {"status": "queued", "interaction_id": interaction_id, "message": "Interaction saved. AI processing is running in the background."}
    response["artifact_id"] = artifact["artifact_id"]
    if artifact.get("status") == "duplicate":
        response["message"] = "Interaction saved. Duplicate evidence was detected, so downstream AI processing was skipped."
        return response

    if req.process_with_ai and settings.OPENAI_CONFIGURED:
        job = await enqueue_job(
            JOB_TYPE_SIGNAL_EXTRACTION,
            {
                "interaction_id": interaction_id,
                "person_id": req.person_id,
                "channel": channel,
                "raw_text": req.raw_text,
                "source_kind": "text",
                "artifact_id": artifact["artifact_id"],
            },
            person_id=req.person_id,
            interaction_id=interaction_id,
            related_artifact_id=artifact["artifact_id"],
            dedupe_key=f"{JOB_TYPE_SIGNAL_EXTRACTION}:{artifact['artifact_id']}",
        )
        response["job"] = job
    if req.process_with_ai and not settings.OPENAI_CONFIGURED:
        response["message"] = "Interaction saved, but AI processing is unavailable until a valid OpenAI API key is configured."
    return response


@router.post("/upload/{person_id}")
async def upload_media(person_id: str, file: UploadFile = File(...)):
    async def _load_person(db):
        async with db.execute("SELECT full_name FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            return await cursor.fetchone()

    row = await run_read(_load_person, label=f"load person {person_id} for upload")
    if not row:
        raise HTTPException(404, "Person not found")

    original_filename = str(file.filename or "upload.bin")
    safe_filename = _safe_upload_filename(original_filename)
    upload_dir = os.path.join(settings.UPLOADS_DIR, person_id)
    os.makedirs(upload_dir, exist_ok=True)
    stored_filename = f"{uuid.uuid4().hex[:8]}_{safe_filename}"
    file_path = os.path.join(upload_dir, stored_filename)
    content = await file.read()
    with open(file_path, "wb") as handle:
        handle.write(content)

    ext = os.path.splitext(safe_filename)[1].lower()
    media_url = f"/uploads/{person_id}/{stored_filename}"
    channel = "upload"
    source_kind = "text"
    raw_text = f"Uploaded file: {safe_filename}"
    job = None

    if ext in CHATBOT_IMAGE_EXTENSIONS:
        detected_format = imghdr.what(None, h=content)
        if detected_format not in {"jpeg", "png", "webp"}:
            try:
                os.remove(file_path)
            except OSError:
                pass
            raise HTTPException(
                status_code=415,
                detail="Uploaded file is not a valid image. Please upload a real PNG, JPG, or WEBP image.",
            )
        channel = "screenshot"
        source_kind = "image"
        raw_text = f"Image uploaded: {safe_filename}"
    elif ext in CHATBOT_AUDIO_EXTENSIONS:
        channel = "voice"
        source_kind = "audio"
        raw_text = f"Audio uploaded: {safe_filename}. Transcription pending."
    elif ext in CHATBOT_DOCUMENT_EXTENSIONS:
        channel = "document"
        source_kind = "document"
        raw_text = f"Document uploaded: {safe_filename}. Extraction pending."
    elif settings.CHATBOT_ONLY_MODE:
        raise HTTPException(
            status_code=415,
            detail="Only image, audio, PDF, and TXT uploads are allowed in chatbot-only mode.",
        )

    interaction_id = await _create_pending_interaction(person_id, channel, raw_text, None, media_url=media_url)
    artifact = await create_or_update_artifact(
        person_id=person_id,
        channel=channel,
        source_interaction_id=interaction_id,
        raw_content=raw_text,
        media_url=media_url,
        source_name=safe_filename,
        source_type=source_kind,
        extracted_metadata={
            "filename": safe_filename,
            "original_filename": original_filename,
            "content_type": file.content_type,
            "size_bytes": len(content),
        },
        duplicate_hash=compute_duplicate_hash(person_id, channel, source_kind, str(len(content)), raw_bytes=content),
        status="queued",
    )

    if settings.OPENAI_CONFIGURED:
        if artifact.get("status") == "duplicate":
            duplicate_of_artifact_id = str(artifact.get("duplicate_of_artifact_id") or "").strip()
            if source_kind == "document" and duplicate_of_artifact_id:
                canonical_artifact = await _resolve_canonical_artifact(duplicate_of_artifact_id)
                canonical_text = str((canonical_artifact or {}).get("extracted_text") or "").strip()
                if canonical_text:
                    canonical_artifact_id = str(canonical_artifact.get("artifact_id") or duplicate_of_artifact_id).strip()
                    job = await enqueue_job(
                        JOB_TYPE_SIGNAL_EXTRACTION,
                        {
                            "interaction_id": interaction_id,
                            "person_id": person_id,
                            "channel": channel,
                            "raw_text": canonical_text,
                            "file_path": None,
                            "media_url": media_url,
                            "source_kind": "document",
                            "artifact_id": canonical_artifact_id,
                            "replayed_from_duplicate": True,
                        },
                        person_id=person_id,
                        interaction_id=interaction_id,
                        related_artifact_id=canonical_artifact_id,
                        dedupe_key=f"{JOB_TYPE_SIGNAL_EXTRACTION}:duplicate-replay:{interaction_id}",
                    )

                    async def _mark_duplicate_replay_interaction(db):
                        await db.execute(
                            "UPDATE INTERACTION SET summary=? WHERE interaction_id=?",
                            (
                                "Duplicate upload detected. Re-using existing parsed artifact to refresh profile details.",
                                interaction_id,
                            ),
                        )

                    await run_write(
                        _mark_duplicate_replay_interaction,
                        label=f"mark duplicate replay interaction {interaction_id}",
                    )
                    return {
                        "status": "queued",
                        "interaction_id": interaction_id,
                        "artifact_id": artifact["artifact_id"],
                        "media_url": media_url,
                        "channel": channel,
                        "filename": safe_filename,
                        "job": job,
                        "message": "Duplicate upload detected. Existing parsed document is being re-used to refresh this profile.",
                    }

            async def _mark_duplicate_upload_interaction(db):
                await db.execute(
                    "UPDATE INTERACTION SET summary=? WHERE interaction_id=?",
                    (
                        "Duplicate upload detected. Existing parsed artifact is already available, so no reprocessing was queued.",
                        interaction_id,
                    ),
                )

            await run_write(
                _mark_duplicate_upload_interaction,
                label=f"mark duplicate upload interaction {interaction_id}",
            )
            return {
                "status": "duplicate",
                "interaction_id": interaction_id,
                "artifact_id": artifact["artifact_id"],
                "media_url": media_url,
                "channel": channel,
                "filename": safe_filename,
                "message": "Upload received, but the file matches an existing artifact so no duplicate AI processing was queued.",
            }
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
                    "artifact_id": artifact["artifact_id"],
                },
                person_id=person_id,
                interaction_id=interaction_id,
                related_artifact_id=artifact["artifact_id"],
                dedupe_key=f"{JOB_TYPE_TRANSCRIPTION}:{artifact['artifact_id']}",
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
                    "artifact_id": artifact["artifact_id"],
                },
                person_id=person_id,
                interaction_id=interaction_id,
                related_artifact_id=artifact["artifact_id"],
                dedupe_key=f"{JOB_TYPE_SIGNAL_EXTRACTION}:{artifact['artifact_id']}",
            )

    return {
        "status": "queued" if settings.OPENAI_CONFIGURED else "stored",
        "interaction_id": interaction_id,
        "artifact_id": artifact["artifact_id"],
        "media_url": media_url,
        "channel": channel,
        "filename": safe_filename,
        "job": job,
        "message": "Upload received. AI processing is running in the background." if settings.OPENAI_CONFIGURED else "Upload received, but AI processing is unavailable until a valid OpenAI API key is configured.",
    }


@router.post("/{interaction_id}/realign")
async def realign_interaction_api(interaction_id: str, req: InteractionRealign):
    if not settings.LEGACY_SCORING_ENABLED:
        raise HTTPException(410, "Legacy realign flow is disabled while the new scoring intelligence is being implemented.")
    async def _prepare_realign(db):
        async with db.execute("SELECT person_id, channel, raw_text FROM INTERACTION WHERE interaction_id=?", (interaction_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Interaction not found")
        await db.execute("DELETE FROM TOPIC_INTELLIGENCE WHERE source_interaction_id=?", (interaction_id,))
        await db.execute("DELETE FROM TASK WHERE source_interaction_id=? AND status IN ('open', 'in_progress')", (interaction_id,))
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


@router.put("/{interaction_id}/stage-override")
async def update_interaction_stage_override(interaction_id: str, req: InteractionStageOverrideUpdate):
    relationship_stage_code = _normalize_stage_code(req.relationship_stage_code)
    if not req.clear_override and relationship_stage_code and relationship_stage_code not in RELATIONSHIP_STAGE_CODES:
        raise HTTPException(422, f"Invalid relationship stage code: {relationship_stage_code}")

    now = _now()

    async def _update(db):
        async with db.execute(
            "SELECT person_id FROM INTERACTION WHERE interaction_id=?",
            (interaction_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Interaction not found")

        person_id = str(row["person_id"])
        if req.clear_override:
            await db.execute(
                """
                UPDATE PERSON
                SET relationship_stage_override=NULL,
                    stage_override_source_interaction_id=NULL,
                    stage_override_updated_at=?,
                    cached_briefing=NULL,
                    last_updated_at=?
                WHERE person_id=?
                """,
                (now, now, person_id),
            )
            return {
                "person_id": person_id,
                "relationship_stage_override": None,
                "stage_override_source_interaction_id": None,
                "stage_override_updated_at": now,
            }

        if not relationship_stage_code:
            raise HTTPException(422, "relationship_stage_code is required unless clear_override=true")

        await db.execute(
            """
            UPDATE PERSON
            SET relationship_stage_override=?,
                stage_override_source_interaction_id=?,
                stage_override_updated_at=?,
                cached_briefing=NULL,
                last_updated_at=?
            WHERE person_id=?
            """,
            (relationship_stage_code, interaction_id, now, now, person_id),
        )
        return {
            "person_id": person_id,
            "relationship_stage_override": relationship_stage_code,
            "stage_override_source_interaction_id": interaction_id,
            "stage_override_updated_at": now,
        }

    payload = await run_write(_update, label=f"update stage override {interaction_id}")
    return {"status": "success", **payload}


@router.delete("/{interaction_id}")
async def delete_interaction(interaction_id: str):
    async def _delete(db):
        async with db.execute(
            "SELECT person_id FROM INTERACTION WHERE interaction_id=?",
            (interaction_id,),
        ) as cursor:
            interaction_row = await cursor.fetchone()

        async with db.execute(
            "SELECT artifact_id FROM AI_ARTIFACT WHERE source_interaction_id=?",
            (interaction_id,),
        ) as cursor:
            artifact_rows = await cursor.fetchall()
        artifact_ids = [row["artifact_id"] for row in artifact_rows or [] if row and row["artifact_id"]]

        signal_ids: set[str] = set()
        if artifact_ids:
            placeholders = ",".join("?" for _ in artifact_ids)
            async with db.execute(
                f"SELECT signal_id FROM AI_SIGNAL WHERE artifact_id IN ({placeholders})",
                artifact_ids,
            ) as cursor:
                signal_rows = await cursor.fetchall()
            signal_ids.update(row["signal_id"] for row in signal_rows or [] if row and row["signal_id"])
        async with db.execute(
            "SELECT signal_id FROM AI_SIGNAL WHERE source_interaction_id=?",
            (interaction_id,),
        ) as cursor:
            direct_signal_rows = await cursor.fetchall()
        signal_ids.update(row["signal_id"] for row in direct_signal_rows or [] if row and row["signal_id"])

        async with db.execute(
            "SELECT job_id FROM AI_JOB WHERE interaction_id=?",
            (interaction_id,),
        ) as cursor:
            job_rows = await cursor.fetchall()
        job_ids = [row["job_id"] for row in job_rows or [] if row and row["job_id"]]

        await db.execute("DELETE FROM TOPIC_INTELLIGENCE WHERE source_interaction_id=?", (interaction_id,))
        await db.execute("DELETE FROM TASK WHERE source_interaction_id=?", (interaction_id,))

        if job_ids:
            job_placeholders = ",".join("?" for _ in job_ids)
            await db.execute(
                f"UPDATE AI_JOB SET parent_job_id = NULL WHERE parent_job_id IN ({job_placeholders})",
                job_ids,
            )
            await db.execute(
                f"DELETE FROM AI_JOB WHERE job_id IN ({job_placeholders})",
                job_ids,
            )

        if signal_ids:
            signal_id_list = list(signal_ids)
            signal_placeholders = ",".join("?" for _ in signal_id_list)
            await db.execute(
                f"DELETE FROM AI_FEEDBACK WHERE target_type='signal' AND target_id IN ({signal_placeholders})",
                signal_id_list,
            )
            await db.execute(
                f"DELETE FROM AI_SIGNAL WHERE signal_id IN ({signal_placeholders})",
                signal_id_list,
            )

        if artifact_ids:
            artifact_placeholders = ",".join("?" for _ in artifact_ids)
            await db.execute(
                f"DELETE FROM AI_ARTIFACT WHERE artifact_id IN ({artifact_placeholders})",
                artifact_ids,
            )

        if interaction_row:
            await db.execute(
                """
                UPDATE PERSON
                SET relationship_stage_override=NULL,
                    stage_override_source_interaction_id=NULL,
                    stage_override_updated_at=?,
                    cached_briefing=NULL,
                    last_updated_at=?
                WHERE stage_override_source_interaction_id=?
                """,
                (_now(), _now(), interaction_id),
            )

        await db.execute("DELETE FROM INTERACTION WHERE interaction_id=?", (interaction_id,))

    await run_write(_delete, label=f"delete interaction {interaction_id}")
    return {"status": "success"}



