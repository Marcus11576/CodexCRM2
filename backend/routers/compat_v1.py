"""
Antigravity CRM â€” Legacy API Compatibility Router
Bridges the old V1 frontend requests to the new V2 backend services.
"""
import os
import re
import uuid
import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Query, Request, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional
from backend.database import get_db, run_read, run_write
from backend.config import settings

router = APIRouter()

# â”€â”€ Dashboard Compatibility â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/dashboard/task-pipeline")
async def compat_task_pipeline(days: int = Query(30)):
    from backend.routers.tasks import get_pipeline
    return await get_pipeline(days=days)


@router.get("/api/dashboard/meeting-feed")
async def compat_meeting_feed():
    """Returns the Phase 1 queue-led dashboard feed with legacy aliases."""
    from backend.services.network_orchestration_service import build_network_feed

    return await build_network_feed()


@router.get("/api/dashboard/network-feed")
async def compat_network_feed():
    """Explicit queue-led dashboard feed used by the upgraded network dashboard."""
    from backend.services.network_orchestration_service import build_network_feed

    return await build_network_feed()


@router.get("/api/network/queues")
async def list_network_queues():
    """Primary queue endpoint for network orchestration consumers."""
    from backend.services.network_orchestration_service import build_network_feed

    return await build_network_feed()


# â”€â”€ People Detail Compatibility â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/api/people/{person_id}/meeting-brief")
async def compat_meeting_brief(person_id: str):
    from backend.routers.intelligence import get_brief
    return await get_brief(person_id=person_id, force_refresh=True)


@router.post("/api/people/{person_id}/media")
async def compat_upload_photo(person_id: str, file: UploadFile = File(...)):
    """Upload profile photo â€” saves locally and updates person record."""
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


# â”€â”€ Taxonomy & Config Compatibility â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/config/taxonomy")
async def compat_taxonomy():
    """Alias /api/config/taxonomy -> /api/taxonomy for old frontend compatibility."""
    from backend.routers.taxonomy import get_taxonomy
    return await get_taxonomy()

@router.get("/api/config/ai")
async def get_ai_config():
    """Expose frozen AI display settings without leaking runtime secrets."""
    return {
        "mode": "frozen",
        "message": "AI configuration is frozen during baseline cleanup.",
        "hypothesis_questions": settings.BRIEF_HYPOTHESIS_QUESTIONS,
        "tts_voice": settings.BRIEF_TTS_VOICE,
        "recruitment_label": settings.BRIEF_LABEL_RECRUITMENT,
        "obe_label": settings.BRIEF_LABEL_OBE,
    }


@router.post("/api/config/ai")
async def update_ai_config():
    raise HTTPException(status_code=409, detail="AI configuration is frozen during the baseline cleanup phase.")

# â”€â”€ [STUB] Twin Chat (EXPERIMENTAL / NON-FUNCTIONAL) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TwinChatReq(BaseModel):
    message: str
    history: list = []


def _clean_twin_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip())[:2000]


def _parse_due_date(message: str) -> Optional[str]:
    lowered = (message or "").lower()
    today = datetime.now(timezone.utc).date()
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", message or "")
    if iso_match:
        return iso_match.group(1)
    weekday_tokens = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for token, weekday in weekday_tokens.items():
        if token in lowered:
            day_delta = (weekday - today.weekday()) % 7
            if day_delta == 0:
                day_delta = 7
            return (today + timedelta(days=day_delta)).isoformat()
    if "tomorrow" in lowered:
        return (today + timedelta(days=1)).isoformat()
    if "today" in lowered:
        return today.isoformat()
    if "next week" in lowered:
        return (today + timedelta(days=7)).isoformat()
    return None


def _parse_due_time(message: str) -> Optional[str]:
    lowered = (message or "").lower()
    if "afternoon" in lowered:
        return "13:00"
    if "morning" in lowered:
        return "09:00"
    return "09:00"


async def _twin_search_people(query: str = "", limit: int = 12):
    search = (query or "").strip()

    async def _load(db):
        sql = """
            SELECT person_id, full_name, title_current, company_name_raw, cat, env
            FROM PERSON
            WHERE is_active = 1
        """
        params = []
        if search:
            sql += " AND (full_name LIKE ? OR company_name_raw LIKE ? OR title_current LIKE ? OR email_primary LIKE ?)"
            token = f"%{search}%"
            params.extend([token, token, token, token])
        sql += " ORDER BY last_updated_at DESC LIMIT ?"
        params.append(limit)
        async with db.execute(sql, params) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    return await run_read(_load, label=f"twin search people {search or 'recent'}")


async def _resolve_person_for_task(person_ref: Optional[str]):
    if not person_ref:
        return None
    lookup = person_ref.strip()

    async def _load(db):
        async with db.execute(
            "SELECT person_id, full_name FROM PERSON WHERE is_active = 1 AND (full_name = ? OR full_name LIKE ?) ORDER BY CASE WHEN full_name = ? THEN 0 ELSE 1 END, last_updated_at DESC LIMIT 5",
            (lookup, f"%{lookup}%", lookup),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    matches = await run_read(_load, label=f"resolve twin task person {lookup}")
    if len(matches) == 1:
        return matches[0]
    return None


def _infer_twin_action(message: str) -> dict:
    lowered = message.lower()
    search_prefixes = ("find ", "search ", "show ", "list ", "who is ", "look up ")
    if any(lowered.startswith(prefix) for prefix in search_prefixes) or "contacts" in lowered or "people" in lowered:
        query = re.sub(r"^(find|search|show|list|look up|who is)\s+", "", message, flags=re.IGNORECASE).strip(" ?.!" )
        query = re.sub(r"\b(contacts|people|for me|please)\b", "", query, flags=re.IGNORECASE).strip(" ,")
        return {"type": "search", "params": {"query": query}}

    if any(token in lowered for token in ["remind", "reminder", "follow up", "follow-up", "create task", "task for"]):
        title = message
        for prefix in ["remind me to", "remind me", "create task", "create a task", "task for", "follow up on", "follow-up on"]:
            title = re.sub(prefix, "", title, flags=re.IGNORECASE).strip(" .")
        person_match = re.search(r"\b(?:for|with)\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})", message)
        return {"type": "create_task", "params": {"title": title[:200] or "Follow up", "due_date": _parse_due_date(message), "due_time": _parse_due_time(message), "person_ref": person_match.group(1).strip() if person_match else None}}

    if any(token in lowered for token in ["add contact", "create contact", "new contact", "add person", "create person"]):
        tail = re.sub(r"^(add|create|new)\s+(contact|person)\s*", "", message, flags=re.IGNORECASE).strip()
        person_match = re.match(r"(?P<name>[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3})(?:\s+(?:at|from)\s+(?P<company>[^,]+))?(?:,\s*(?P<title>.+))?", tail)
        if person_match:
            params = {k: (v.strip() if isinstance(v, str) and v.strip() else None) for k, v in person_match.groupdict().items()}
        else:
            params = {"name": tail or None, "company": None, "title": None}
        return {"type": "create_person", "params": params}

    return {"type": "reply", "params": {}}


@router.post("/api/intelligence/twin/chat", tags=["compat"])
async def compat_twin_chat(req: TwinChatReq):
    message = _clean_twin_message(req.message)
    if not message:
        raise HTTPException(400, "Please enter a message.")
    intent = _infer_twin_action(message)
    if intent["type"] == "search":
        query = intent["params"].get("query", "")
        preview = await _twin_search_people(query=query, limit=8)
        reply = f"I found {len(preview)} matching contact{'s' if len(preview) != 1 else ''}." if query else "Here are the most recently updated contacts."
        return {"reply": reply, "data": preview, "pending_action": intent}
    if intent["type"] == "create_task":
        title = intent["params"].get("title") or "Follow up"
        person_ref = intent["params"].get("person_ref")
        due_date = intent["params"].get("due_date")
        due_time = intent["params"].get("due_time")
        reply = f"I can create this task: {title}."
        if person_ref:
            reply += f" I will try to link it to {person_ref}."
        if due_date:
            reply += f" Due date: {due_date}."
        if due_time:
            reply += f" Time block: {'Morning' if due_time < '12:00' else 'Afternoon'}."
        return {"reply": reply, "data": None, "pending_action": intent}
    if intent["type"] == "create_person":
        name = intent["params"].get("name") or "this contact"
        return {"reply": f"I can create a new contact record for {name}. Please confirm the details.", "data": None, "pending_action": intent}
    preview = await _twin_search_people(query=message, limit=5)
    if preview:
        return {"reply": "I found close contact matches. You can open one directly or ask me to refine the search.", "data": preview, "pending_action": None}
    return {"reply": "I can find contacts, create tasks, add contacts, and process PDF contact documents. Try 'find Marcus', 'create task follow up with John tomorrow', or 'add contact Jane Doe at Acme'.", "data": None, "pending_action": None}


@router.post("/api/intelligence/twin/execute", tags=["compat"])
async def compat_twin_execute(req: dict):
    action_type = (req or {}).get("action_type")
    params = (req or {}).get("params") or {}
    if action_type == "search":
        results = await _twin_search_people(query=(params.get("query") or ""), limit=25)
        return {"status": "success", "message": f"Found {len(results)} contact{'s' if len(results) != 1 else '' }.", "data": results}
    if action_type == "create_task":
        title = (params.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "Task title is required")
        person_ref = params.get("person_ref")
        person = await _resolve_person_for_task(person_ref)
        if person_ref and not person:
            raise HTTPException(400, f"I could not uniquely match '{person_ref}' to a single contact.")
        due_time = params.get("due_time") or "09:00"
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        due_date = params.get("due_date")
        async def _create(db):
            await db.execute(
                "INSERT INTO TASK (task_id, person_id, task_text, due_date, due_time, priority, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, person["person_id"] if person else None, title[:200], due_date, due_time, params.get("priority") or "medium", "open", now),
            )
            if person and due_date:
                meeting_status = _calc_meeting_status(due_date)
                await db.execute(
                    """
                    UPDATE PERSON SET next_contact_due_date = (
                        SELECT MIN(due_date)
                        FROM TASK
                        WHERE person_id=? AND status IN ('open', 'in_progress') AND due_date IS NOT NULL
                    ), meeting_status=?, last_updated_at=?
                    WHERE person_id=?
                    """,
                    (person["person_id"], meeting_status, now, person["person_id"]),
                )
        await run_write(_create, label=f"twin create task {title[:40]}")
        target_name = person["full_name"] if person else "the general task list"
        return {"status": "success", "message": f"Task created for {target_name}.", "data": {"task_id": task_id}}
    if action_type == "create_person":
        name = (params.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Contact name is required")
        company = (params.get("company") or "").strip() or None
        title = (params.get("title") or "").strip() or None
        person_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async def _create(db):
            async with db.execute("SELECT person_id, full_name FROM PERSON WHERE full_name = ? AND IFNULL(company_name_raw, '') = IFNULL(?, '') LIMIT 1", (name, company)) as cursor:
                existing = await cursor.fetchone()
            if existing:
                return {"status": "exists", "person_id": existing["person_id"], "full_name": existing["full_name"]}
            await db.execute("INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at) VALUES (?,?,?,?,?,?,?)", (person_id, name, title, company, "GEN", now, now))
            return {"status": "created", "person_id": person_id, "full_name": name}
        result = await run_write(_create, label=f"twin create person {name}")
        return {"status": "success", "message": f"Contact ready: {result['full_name']}", "data": result}
    raise HTTPException(400, "Unsupported Twin action")


@router.post("/api/twin/upload_pdf", tags=["compat"])
async def twin_upload_pdf(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext != ".pdf":
        raise HTTPException(400, "Please upload a PDF file.")
    intake_dir = os.path.join(settings.UPLOADS_DIR, "twin_intake")
    os.makedirs(intake_dir, exist_ok=True)
    temp_name = f"{uuid.uuid4().hex[:10]}_{os.path.basename(file.filename)}"
    file_path = os.path.join(intake_dir, temp_name)
    with open(file_path, "wb") as handle:
        handle.write(await file.read())
    from backend.services.ai_service import extract_text_from_file
    extracted_text = extract_text_from_file(file_path) or ""
    if not extracted_text.strip():
        raise HTTPException(400, "I could not extract readable text from that PDF.")
    name = None
    company = None
    title = None
    for line in [line.strip() for line in extracted_text.splitlines() if line.strip()][:8]:
        if not name and re.match(r"^[A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){1,3}$", line):
            name = line
            continue
        if not title and any(token in line.lower() for token in ["manager", "director", "engineer", "head", "lead", "consultant", "partner", "specialist"]):
            title = line
            continue
        if not company and line not in {name, title} and len(line.split()) <= 6:
            company = line
    if not name:
        raise HTTPException(400, "I could not confidently identify a contact name from that PDF.")
    person_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    async def _create(db):
        async with db.execute("SELECT person_id, full_name FROM PERSON WHERE full_name = ? AND IFNULL(company_name_raw, '') = IFNULL(?, '') LIMIT 1", (name, company)) as cursor:
            existing = await cursor.fetchone()
        if existing:
            return {"status": "exists", "person_id": existing["person_id"], "full_name": existing["full_name"]}
        await db.execute("INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, cat, career_summary, created_at, last_updated_at) VALUES (?,?,?,?,?,?,?,?)", (person_id, name, title, company, "GEN", extracted_text[:1200], now, now))
        return {"status": "created", "person_id": person_id, "full_name": name}
    result = await run_write(_create, label=f"twin pdf create person {name}")
    return {"status": result["status"], "reply": f"Contact ready: {result['full_name']}", "data": result}


# End of file



