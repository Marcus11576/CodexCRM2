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
) -> dict:
    job_id = str(uuid.uuid4())
    now = _now()

    async def _insert(db):
        await db.execute(
            """
            INSERT INTO AI_JOB (job_id, person_id, interaction_id, parent_job_id, job_type, status, payload_json,
                                attempts, max_attempts, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                job_id,
                person_id,
                interaction_id,
                parent_job_id,
                job_type,
                JOB_STATUS_QUEUED,
                json.dumps(payload or {}),
                max_attempts,
                now,
                now,
            ),
        )

    await run_write(_insert, label=f"enqueue ai job {job_type}")
    await kickoff_job(job_id)
    return await get_job(job_id)


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
            "UPDATE AI_JOB SET status = ?, error_text = NULL, result_json = NULL, updated_at = ?, started_at = NULL, completed_at = NULL WHERE job_id = ?",
            (JOB_STATUS_RETRYING, _now(), job_id),
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
    return item


async def _claim_job(job_id: str) -> Optional[dict]:
    now = _now()

    async def _claim(db):
        cursor = await db.execute(
            "UPDATE AI_JOB SET status = ?, attempts = attempts + 1, started_at = ?, updated_at = ? WHERE job_id = ? AND status IN (?, ?)",
            (JOB_STATUS_RUNNING, now, now, job_id, JOB_STATUS_QUEUED, JOB_STATUS_RETRYING),
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
            "UPDATE AI_JOB SET status = ?, result_json = ?, error_text = NULL, completed_at = ?, updated_at = ? WHERE job_id = ?",
            (JOB_STATUS_COMPLETED, json.dumps(result or {}), now, now, job_id),
        )

    await run_write(_complete, label=f"complete ai job {job_id}")


async def _fail_job(job_id: str, error_text: str):
    updated = await get_job(job_id)
    attempts = (updated or {}).get("attempts", 1)
    max_attempts = (updated or {}).get("max_attempts", 3)
    status = JOB_STATUS_FAILED if attempts >= max_attempts else JOB_STATUS_RETRYING

    async def _mark_failed(db):
        await db.execute(
            "UPDATE AI_JOB SET status = ?, error_text = ?, updated_at = ? WHERE job_id = ?",
            (status, error_text, _now(), job_id),
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

    text = await transcribe_audio(file_path)
    interaction_id = payload.get("interaction_id")
    person_id = payload.get("person_id")

    if interaction_id:
        async def _update_interaction(db):
            await db.execute(
                "UPDATE INTERACTION SET raw_text = ?, summary = ? WHERE interaction_id = ?",
                (text or "", (text or "Audio uploaded. Transcription pending details.")[:300], interaction_id),
            )

        await run_write(_update_interaction, label=f"update transcription interaction {interaction_id}")

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
            },
            person_id=person_id,
            interaction_id=interaction_id,
            parent_job_id=job["job_id"],
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
    now = _now()

    result = {}
    profile_photo_updated = False

    if source_kind == "image":
        from backend.services.ai_service import process_image

        result = await process_image(file_path, person_id)
        raw_text = result.get("summary") or raw_text or f"Image uploaded: {os.path.basename(file_path)}"
        if result.get("is_profile_photo") and media_url:
            async def _update_photo(db):
                await db.execute(
                    "UPDATE PERSON SET profile_photo_url = ?, last_updated_at = ? WHERE person_id = ?",
                    (media_url, now, person_id),
                )

            await run_write(_update_photo, label=f"update profile photo {person_id}")
            profile_photo_updated = True
    else:
        if source_kind == "document" and file_path:
            from backend.services.ai_service import extract_text_from_file

            raw_text = extract_text_from_file(file_path) or raw_text or f"Document uploaded: {os.path.basename(file_path)}"
        if settings.OPENAI_API_KEY:
            from backend.services.ai_service import process_text

            result = await process_text(raw_text, channel, person_id)

    from backend.routers.interactions import _persist_interaction

    async def _persist(db):
        if interaction_id:
            await db.execute("DELETE FROM TOPIC_INTELLIGENCE WHERE source_interaction_id = ?", (interaction_id,))
            await db.execute("DELETE FROM TASK WHERE source_interaction_id = ? AND status = 'open'", (interaction_id,))

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
    data["profile_photo_updated"] = profile_photo_updated
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

        async with db.execute(
            """
            SELECT channel, raw_text, summary, interaction_at, created_at
            FROM INTERACTION WHERE person_id = ? AND channel != 'system_audit'
            ORDER BY interaction_at DESC LIMIT 20
            """,
            (person_id,),
        ) as cursor:
            interactions = [dict(r) for r in await cursor.fetchall()]

        async with db.execute(
            "SELECT task_text, due_date FROM TASK WHERE person_id = ? AND status = 'open'",
            (person_id,),
        ) as cursor:
            tasks = [dict(r) for r in await cursor.fetchall()]

        async with db.execute(
            "SELECT intel_id, topic, intel_text, confidence, created_at FROM TOPIC_INTELLIGENCE WHERE person_id = ? ORDER BY created_at DESC",
            (person_id,),
        ) as cursor:
            intel_rows = [dict(r) for r in await cursor.fetchall()]

        now = datetime.now(timezone.utc).isoformat()
        async with db.execute(
            "SELECT e.event_id, e.event_name, e.event_date, e.topics, pe.status "
            "FROM EVENT e JOIN PERSON_EVENT pe ON e.event_id = pe.event_id "
            "WHERE pe.person_id = ? AND e.event_date >= ? ORDER BY e.event_date ASC",
            (person_id, now),
        ) as cursor:
            events = [dict(r) for r in await cursor.fetchall()]

        return person, interactions, tasks, intel_rows, events

    person, interactions, tasks, intel_rows, events = await run_read(_load_context, label=f"load brief context {person_id}")

    from backend.services.ai_service import compute_signal_scores, generate_briefing
    from backend.services.preference_learning import compute_preference_profile

    scores = await compute_signal_scores(person_id)
    preference_profile = await compute_preference_profile(person_id)
    intel_rows.sort(key=lambda row: (scores.get(row.get("intel_id"), 0), row.get("created_at")), reverse=True)

    intel = {"business_focus": [], "recruitment_talent": [], "family_personal": [], "obe_focus": []}
    for item in intel_rows:
        topic = item.get("topic")
        if topic in intel:
            intel[topic].append(item)

    briefing = await generate_briefing(person, interactions, tasks, intel, events, preference_profile=preference_profile)
    now = _now()
    brief_id = str(uuid.uuid4())
    source_signal_ids = [item["intel_id"] for item in intel_rows[:12] if item.get("intel_id")]
    briefing["brief_id"] = brief_id

    async def _save_brief(db):
        await db.execute(
            "UPDATE PERSON SET cached_briefing = ?, briefing_last_updated = ? WHERE person_id = ?",
            (json.dumps(briefing), now, person_id),
        )
        await db.execute(
            "INSERT INTO AI_BRIEF (brief_id, person_id, content_json, source_signal_ids, created_at) VALUES (?, ?, ?, ?, ?)",
            (brief_id, person_id, json.dumps(briefing), json.dumps(source_signal_ids), now),
        )

    await run_write(_save_brief, label=f"save brief {person_id}")
    return {"briefing": briefing, "person_id": person_id, "brief_id": brief_id}
