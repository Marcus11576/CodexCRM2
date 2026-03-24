"""
Antigravity CRM - Background AI jobs
Durable job queue for transcription, signal extraction, and briefing work.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.config import settings
from backend.database import run_read, run_write
from backend.services.ai_foundation import infer_communication_channel, input_type_for_channel

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_RETRYING = "retrying"

JOB_TYPE_TRANSCRIPTION = "transcription"
JOB_TYPE_SIGNAL_EXTRACTION = "signal_extraction"
JOB_TYPE_BRIEF_GENERATION = "brief_generation"

_ACTIVE_JOBS = set()
_RUNNING_TASKS = {}
_POLLER_TASK = None
_JOB_CONCURRENCY = asyncio.Semaphore(2)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _channel_from_image_context(default_channel: str, result: dict) -> str:
    """Map classified screenshot context to explicit communication channels."""
    if bool(result.get("is_profile_photo")):
        return default_channel

    return infer_communication_channel(
        channel=default_channel,
        summary=result.get("summary"),
        raw_text=result.get("raw_text"),
        extracted_text=result.get("extracted_text"),
        metadata={
            "source_app": result.get("source_app"),
            "screen_context": result.get("screen_context"),
        },
    )


async def _maybe_attach_profile_photo(*, person_id: Optional[str], artifact: Optional[dict], result: dict, media_url: Optional[str]) -> bool:
    """Auto-attach an uploaded headshot when the profile has no active photo yet."""
    if not person_id or not artifact or not media_url:
        return False
    if str(artifact.get("input_type") or "").strip().lower() != "profile_picture":
        return False
    if not bool(result.get("is_profile_photo")):
        return False

    confidence = result.get("image_type_confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = float(artifact.get("input_type_confidence") or 0.0)
    if confidence_value < 0.9:
        return False

    now = _now()

    async def _apply(db):
        async with db.execute("SELECT profile_photo_url FROM PERSON WHERE person_id = ?", (person_id,)) as cursor:
            person_row = await cursor.fetchone()
        if not person_row:
            return False

        current_photo_url = str(person_row["profile_photo_url"] or "").strip()
        if current_photo_url:
            return False

        await db.execute(
            "UPDATE PERSON SET profile_photo_url=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
            (media_url, now, person_id),
        )
        await db.execute(
            "UPDATE AI_ARTIFACT SET requires_confirmation=0, updated_at=?, status='processed' WHERE artifact_id=?",
            (now, artifact["artifact_id"]),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION
            (interaction_id, person_id, channel, raw_text, summary, action_items, topics, sentiment, media_url, created_at, interaction_at, success_rating, engagement_value, is_strategic, metric_tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()),
                person_id,
                "system_audit",
                f"Profile photo auto-attached from uploaded headshot '{artifact.get('source_name') or media_url}'.",
                "Profile photo updated from uploaded headshot.",
                "[]",
                '["profile_photo_auto_attach"]',
                "Neutral",
                media_url,
                now,
                now,
                None,
                None,
                0,
                '["system_audit"]',
            ),
        )
        return True

    return bool(await run_write(_apply, label=f"auto attach profile photo {person_id}"))


async def start_ai_job_worker():
    global _POLLER_TASK
    await recover_jobs()
    if _POLLER_TASK is None or _POLLER_TASK.done():
        _POLLER_TASK = asyncio.create_task(_poll_for_jobs())


async def stop_ai_job_worker():
    global _POLLER_TASK
    if _POLLER_TASK and not _POLLER_TASK.done():
        _POLLER_TASK.cancel()
        try:
            await _POLLER_TASK
        except asyncio.CancelledError:
            pass
    _POLLER_TASK = None


def _track_task(job_id: str, task: asyncio.Task):
    _ACTIVE_JOBS.add(job_id)
    _RUNNING_TASKS[job_id] = task

    def _cleanup(_):
        _ACTIVE_JOBS.discard(job_id)
        _RUNNING_TASKS.pop(job_id, None)

    task.add_done_callback(_cleanup)


async def _poll_for_jobs():
    while True:
        try:
            async def _load_jobs(db):
                async with db.execute(
                    "SELECT job_id FROM AI_JOB WHERE status IN (?, ?) ORDER BY created_at ASC LIMIT 10",
                    (JOB_STATUS_QUEUED, JOB_STATUS_RETRYING),
                ) as cursor:
                    return await cursor.fetchall()

            rows = await run_read(_load_jobs, label="ai job poll")
            for row in rows:
                await kickoff_job(row["job_id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"AI job poller error: {exc}")
        await asyncio.sleep(2)


async def recover_jobs():
    async def _recover(db):
        await db.execute(
            "UPDATE AI_JOB SET status = ?, updated_at = ?, started_at = NULL WHERE status = ?",
            (JOB_STATUS_QUEUED, _now(), JOB_STATUS_RUNNING),
        )

    await run_write(_recover, label="recover ai jobs")


async def enqueue_job(
    job_type: str,
    payload: dict,
    person_id: Optional[str] = None,
    interaction_id: Optional[str] = None,
    parent_job_id: Optional[str] = None,
    max_attempts: int = 3,
    related_artifact_id: Optional[str] = None,
    related_event_id: Optional[str] = None,
    dedupe_key: Optional[str] = None,
) -> dict:
    job_id = str(uuid.uuid4())
    now = _now()

    async def _insert(db):
        if dedupe_key:
            async with db.execute(
                """
                SELECT *
                FROM AI_JOB
                WHERE dedupe_key = ?
                  AND job_type = ?
                  AND status IN (?, ?, ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (dedupe_key, job_type, JOB_STATUS_QUEUED, JOB_STATUS_RUNNING, JOB_STATUS_RETRYING),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing:
                return existing
        await db.execute(
            """
            INSERT INTO AI_JOB (
                job_id, person_id, related_profile_id, interaction_id, parent_job_id, job_type, status, payload_json,
                attempts, retry_count, max_attempts, progress, related_artifact_id, related_event_id, dedupe_key,
                created_at, updated_at, heartbeat_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                person_id,
                person_id,
                interaction_id,
                parent_job_id,
                job_type,
                JOB_STATUS_QUEUED,
                json.dumps(payload or {}),
                max_attempts,
                related_artifact_id,
                related_event_id,
                dedupe_key,
                now,
                now,
                now,
            ),
        )
        async with db.execute("SELECT * FROM AI_JOB WHERE job_id = ?", (job_id,)) as cursor:
            return await cursor.fetchone()

    row = await run_write(_insert, label=f"enqueue ai job {job_type}")
    job = _row_to_job(row)
    await kickoff_job(job["job_id"])
    return job


async def kickoff_job(job_id: str):
    if job_id in _ACTIVE_JOBS:
        return
    task = asyncio.create_task(run_job(job_id))
    _track_task(job_id, task)


async def get_job(job_id: str) -> Optional[dict]:
    async def _load(db):
        async with db.execute("SELECT * FROM AI_JOB WHERE job_id = ?", (job_id,)) as cursor:
            return await cursor.fetchone()

    row = await run_read(_load, label=f"load ai job {job_id}")
    return _row_to_job(row) if row else None


async def list_jobs(person_id: Optional[str] = None, limit: int = 50) -> list:
    sql = "SELECT * FROM AI_JOB"
    params = []
    if person_id:
        sql += " WHERE person_id = ?"
        params.append(person_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    async def _load(db):
        async with db.execute(sql, params) as cursor:
            return await cursor.fetchall()

    rows = await run_read(_load, label="list ai jobs")
    return [_row_to_job(row) for row in rows]


async def retry_job(job_id: str) -> dict:
    job = await get_job(job_id)
    if not job:
        raise ValueError("Job not found")

    async def _retry(db):
        await db.execute(
            """
            UPDATE AI_JOB
            SET status = ?, error_text = NULL, error_message = NULL, result_json = NULL,
                progress = 0, updated_at = ?, started_at = NULL, completed_at = NULL, heartbeat_at = ?
            WHERE job_id = ?
            """,
            (JOB_STATUS_RETRYING, _now(), _now(), job_id),
        )

    await run_write(_retry, label=f"retry ai job {job_id}")
    await kickoff_job(job_id)
    return await get_job(job_id)


def _row_to_job(row) -> dict:
    item = dict(row)
    for field in ("payload_json", "result_json"):
        if item.get(field):
            try:
                item[field] = json.loads(item[field])
            except Exception:
                pass
    item["payload"] = item.pop("payload_json", {}) or {}
    item["result"] = item.pop("result_json", None)
    item["error_message"] = item.get("error_message") or item.get("error_text")
    item["related_profile_id"] = item.get("related_profile_id") or item.get("person_id")
    return item


async def _claim_job(job_id: str) -> Optional[dict]:
    now = _now()

    async def _claim(db):
        cursor = await db.execute(
            """
            UPDATE AI_JOB
            SET status = ?, attempts = attempts + 1,
                retry_count = CASE WHEN attempts > 0 THEN attempts ELSE 0 END,
                progress = 0.1, started_at = ?, updated_at = ?, heartbeat_at = ?
            WHERE job_id = ? AND status IN (?, ?)
            """,
            (JOB_STATUS_RUNNING, now, now, now, job_id, JOB_STATUS_QUEUED, JOB_STATUS_RETRYING),
        )
        if cursor.rowcount == 0:
            return None
        async with db.execute("SELECT * FROM AI_JOB WHERE job_id = ?", (job_id,)) as read_cursor:
            return await read_cursor.fetchone()

    row = await run_write(_claim, label=f"claim ai job {job_id}")
    return _row_to_job(row) if row else None


async def _complete_job(job_id: str, result: dict):
    now = _now()

    async def _complete(db):
        await db.execute(
            """
            UPDATE AI_JOB
            SET status = ?, result_json = ?, error_text = NULL, error_message = NULL,
                progress = 1.0, completed_at = ?, updated_at = ?, heartbeat_at = ?
            WHERE job_id = ?
            """,
            (JOB_STATUS_COMPLETED, json.dumps(result or {}), now, now, now, job_id),
        )

    await run_write(_complete, label=f"complete ai job {job_id}")


async def _fail_job(job_id: str, error_text: str):
    updated = await get_job(job_id)
    attempts = (updated or {}).get("attempts", 1)
    max_attempts = (updated or {}).get("max_attempts", 3)
    status = JOB_STATUS_FAILED if attempts >= max_attempts else JOB_STATUS_RETRYING

    async def _mark_failed(db):
        await db.execute(
            """
            UPDATE AI_JOB
            SET status = ?, error_text = ?, error_message = ?, progress = 0,
                updated_at = ?, heartbeat_at = ?
            WHERE job_id = ?
            """,
            (status, error_text, error_text, _now(), _now(), job_id),
        )

    await run_write(_mark_failed, label=f"fail ai job {job_id}")
    return status


async def run_job(job_id: str):
    async with _JOB_CONCURRENCY:
        job = await _claim_job(job_id)
        if not job:
            return

        try:
            result = await _dispatch_job(job)
            await _complete_job(job_id, result)
        except Exception as exc:
            print(f"AI job {job_id} failed: {exc}")
            status = await _fail_job(job_id, str(exc))
            if status == JOB_STATUS_RETRYING:
                await asyncio.sleep(2)
                await kickoff_job(job_id)


async def _dispatch_job(job: dict) -> dict:
    if job["job_type"] == JOB_TYPE_TRANSCRIPTION:
        return await _handle_transcription(job)
    if job["job_type"] == JOB_TYPE_SIGNAL_EXTRACTION:
        return await _handle_signal_extraction(job)
    if job["job_type"] == JOB_TYPE_BRIEF_GENERATION:
        return await _handle_brief_generation(job)
    raise ValueError(f"Unknown AI job type: {job['job_type']}")


async def _handle_transcription(job: dict) -> dict:
    payload = job["payload"]
    file_path = payload.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError("Audio file for transcription not found")

    from backend.services.ai_service import transcribe_audio
    from backend.services.ai_pipeline_service import update_artifact_state

    text = await transcribe_audio(file_path)
    interaction_id = payload.get("interaction_id")
    person_id = payload.get("person_id")
    artifact_id = payload.get("artifact_id")

    if interaction_id:
        async def _update_interaction(db):
            await db.execute(
                "UPDATE INTERACTION SET raw_text = ?, summary = ? WHERE interaction_id = ?",
                (text or "", (text or "Audio uploaded. Transcription pending details.")[:300], interaction_id),
            )

        await run_write(_update_interaction, label=f"update transcription interaction {interaction_id}")

    if artifact_id:
        await update_artifact_state(
            artifact_id,
            extracted_text=text,
            status="processing",
            input_type="audio_note",
            input_type_confidence=0.98,
        )

    if payload.get("enqueue_signal_job") and interaction_id and person_id:
        await enqueue_job(
            JOB_TYPE_SIGNAL_EXTRACTION,
            {
                "interaction_id": interaction_id,
                "person_id": person_id,
                "channel": payload.get("channel", "audio"),
                "raw_text": text,
                "media_url": payload.get("media_url"),
                "file_path": file_path,
                "source_kind": "audio",
                "artifact_id": artifact_id,
            },
            person_id=person_id,
            interaction_id=interaction_id,
            parent_job_id=job["job_id"],
            related_artifact_id=artifact_id,
            dedupe_key=f"{JOB_TYPE_SIGNAL_EXTRACTION}:{artifact_id or interaction_id}",
        )

    if payload.get("delete_after") and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

    return {"text": text}


async def _handle_signal_extraction(job: dict) -> dict:
    payload = job["payload"]
    interaction_id = payload.get("interaction_id")
    person_id = payload.get("person_id")
    channel = payload.get("channel", "note")
    source_kind = payload.get("source_kind", "text")
    file_path = payload.get("file_path")
    raw_text = payload.get("raw_text") or ""
    media_url = payload.get("media_url")
    artifact_id = payload.get("artifact_id")
    now = _now()

    from backend.services.ai_pipeline_service import (
        create_or_update_artifact,
        get_artifact,
        get_artifact_by_interaction,
        mark_artifact_failed,
        sync_ai_signals_for_artifact,
        update_artifact_state,
    )

    artifact = None
    if artifact_id:
        artifact = await get_artifact(artifact_id)
    elif interaction_id:
        artifact = await get_artifact_by_interaction(interaction_id)
    if not artifact:
        artifact = await create_or_update_artifact(
            person_id=person_id,
            channel=channel,
            source_interaction_id=interaction_id,
            raw_content=raw_text,
            media_url=media_url,
            source_name=os.path.basename(file_path) if file_path else None,
            source_type=source_kind,
            status="processing",
        )
    artifact_id = artifact["artifact_id"]

    if artifact.get("status") == "duplicate" and artifact.get("duplicate_of_artifact_id"):
        if interaction_id:
            async def _mark_duplicate_interaction(db):
                await db.execute(
                    "UPDATE INTERACTION SET summary = ? WHERE interaction_id = ?",
                    ("Duplicate artifact detected. Existing evidence preserved without reprocessing.", interaction_id),
                )

            await run_write(_mark_duplicate_interaction, label=f"mark duplicate interaction {interaction_id}")
        return {"status": "duplicate", "artifact_id": artifact_id, "duplicate_of_artifact_id": artifact.get("duplicate_of_artifact_id")}

    result = {}

    try:
        if source_kind == "image":
            from backend.services.ai_service import process_image

            result = await process_image(file_path, person_id)
            channel = _channel_from_image_context(channel, result)
            image_type = result.get("image_type")
            input_type = "profile_picture" if result.get("is_profile_photo") else (image_type or "general_image")
            raw_text = result.get("extracted_text") or result.get("summary") or raw_text or f"Image uploaded: {os.path.basename(file_path)}"
            if input_type == "profile_picture":
                result["summary"] = result.get("summary") or "Profile image identified. Review manually before using it as the active profile photo."
                result["topics"] = []
                result["action_items"] = []
                result["topic_nuggets"] = []
                result["requires_confirmation"] = True
            artifact = await update_artifact_state(
                artifact_id,
                input_type=input_type,
                input_type_confidence=float(result.get("image_type_confidence") or 0.85),
                extracted_text=result.get("extracted_text") or "",
                artifact_sentiment=result.get("sentiment") or "Unclear",
                artifact_sentiment_confidence=float(result.get("sentiment_confidence") or 0.5),
                metadata_patch={
                    "contact_info": result.get("contact_info") or {},
                    "image_type": image_type,
                    "screen_context": result.get("screen_context"),
                    "source_app": result.get("source_app"),
                    "is_profile_photo": bool(result.get("is_profile_photo")),
                },
                requires_confirmation=bool(result.get("requires_confirmation")),
                status="processed",
            )
        else:
            if source_kind == "document" and file_path:
                from backend.services.ai_service import extract_text_from_file

                raw_text = extract_text_from_file(file_path) or raw_text or f"Document uploaded: {os.path.basename(file_path)}"
            if settings.OPENAI_CONFIGURED:
                from backend.services.ai_service import extract_document_profile, process_text

                result = await process_text(raw_text, channel, person_id)
                if source_kind == "document":
                    profile_result = await extract_document_profile(raw_text)
                    if profile_result.get("career_summary"):
                        result["career_summary"] = profile_result.get("career_summary")
                    if profile_result.get("key_professional_notes"):
                        result["key_professional_notes"] = profile_result.get("key_professional_notes")
                    if isinstance(profile_result.get("employment_history"), list):
                        result["employment_history"] = profile_result.get("employment_history")
                    profile_updates = result.get("profile_updates")
                    if not isinstance(profile_updates, dict):
                        profile_updates = {}
                        result["profile_updates"] = profile_updates
                    for field in ("title_current", "company_name_raw", "email_primary", "phone_primary", "linkedin_url"):
                        value = str(profile_result.get(field) or "").strip()
                        if value and not str(profile_updates.get(field) or "").strip():
                            profile_updates[field] = value
            else:
                result = {
                    "summary": raw_text[:200],
                    "sentiment": "Unclear",
                    "sentiment_confidence": 0.0,
                    "topics": [],
                    "action_items": [],
                    "profile_updates": {},
                    "topic_nuggets": [],
                    "success_metrics": {},
                    "global_insights": [],
                }
            artifact = await update_artifact_state(
                artifact_id,
                input_type={
                    "document": "document",
                    "audio": "audio_note",
                }.get(source_kind, input_type_for_channel(channel, source_kind=source_kind, filename=file_path)[0]),
                input_type_confidence=0.98 if source_kind in {"document", "audio"} else 0.9,
                extracted_text=raw_text,
                artifact_sentiment=result.get("sentiment") or "Unclear",
                artifact_sentiment_confidence=float(result.get("sentiment_confidence") or 0.5),
                metadata_patch={"source_kind": source_kind},
                status="processed",
            )
    except Exception as exc:
        await mark_artifact_failed(artifact_id, str(exc))
        raise

    from backend.routers.interactions import _persist_interaction

    async def _persist(db):
        if interaction_id:
            await db.execute("DELETE FROM TOPIC_INTELLIGENCE WHERE source_interaction_id = ?", (interaction_id,))
            await db.execute("DELETE FROM TASK WHERE source_interaction_id = ? AND status IN ('open', 'in_progress')", (interaction_id,))

        interaction_at = now
        if interaction_id:
            async with db.execute("SELECT interaction_at FROM INTERACTION WHERE interaction_id = ?", (interaction_id,)) as cursor:
                row = await cursor.fetchone()
                if row and row["interaction_at"]:
                    interaction_at = row["interaction_at"]

        return await _persist_interaction(
            db,
            interaction_id or str(uuid.uuid4()),
            person_id,
            channel,
            raw_text,
            result,
            now,
            interaction_at,
            media_url=media_url,
        )

    data = await run_write(_persist, label=f"persist ai signal extraction {interaction_id or person_id}")
    data["artifact_id"] = artifact_id
    signal_sync = await sync_ai_signals_for_artifact(
        artifact_id=artifact_id,
        person_id=person_id,
        interaction_id=interaction_id,
        result=result,
        artifact=artifact,
    )
    data["ai_signal_count"] = signal_sync.get("inserted_count", 0)

    if person_id and signal_sync.get("inserted_count", 0) > 0:
        await enqueue_job(
            JOB_TYPE_BRIEF_GENERATION,
            {"person_id": person_id, "trigger": "new_signals", "artifact_id": artifact_id},
            person_id=person_id,
            interaction_id=interaction_id,
            parent_job_id=job["job_id"],
            related_artifact_id=artifact_id,
            dedupe_key=f"{JOB_TYPE_BRIEF_GENERATION}:{person_id}",
        )
    profile_photo_updated = await _maybe_attach_profile_photo(
        person_id=person_id,
        artifact=artifact,
        result=result,
        media_url=media_url,
    )
    if profile_photo_updated and artifact:
        artifact["requires_confirmation"] = False
    data["profile_photo_updated"] = profile_photo_updated
    data["input_type"] = artifact.get("input_type") if artifact else None
    data["image_review_required"] = bool(artifact.get("requires_confirmation")) if artifact else False
    return data


async def _handle_brief_generation(job: dict) -> dict:
    payload = job["payload"]
    person_id = payload.get("person_id")
    if not person_id:
        raise ValueError("Brief job missing person_id")

    async def _load_context(db):
        async with db.execute("SELECT * FROM PERSON WHERE person_id = ?", (person_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise ValueError("Person not found for brief generation")
        person = dict(row)

        now = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            "SELECT e.event_id, e.event_name, e.event_date, e.topics, pe.status "
            "FROM EVENT e JOIN PERSON_EVENT pe ON e.event_id = pe.event_id "
            "WHERE pe.person_id = ? AND e.event_date >= ? ORDER BY e.event_date ASC",
            (person_id, now),
        ) as cursor:
            events = [dict(r) for r in await cursor.fetchall()]

        return person, events

    person, events = await run_read(_load_context, label=f"load brief context {person_id}")

    from backend.services.ai_pipeline_service import load_signals_for_brief, store_brief
    from backend.services.ai_service import generate_briefing
    from backend.services.preference_learning import compute_preference_profile

    signals = await load_signals_for_brief(person_id)
    preference_profile = await compute_preference_profile(person_id)
    briefing = await generate_briefing(person, signals, events, preference_profile=preference_profile)
    stored = await store_brief(
        person_id=person_id,
        briefing=briefing,
        signals=signals,
        events=events,
    )
    return {
        "briefing": stored["briefing"],
        "person_id": person_id,
        "brief_id": stored["brief_id"],
        "signal_count": len(signals),
    }



