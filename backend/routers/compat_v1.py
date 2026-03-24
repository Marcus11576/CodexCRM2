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
from backend.services.profile_background_backfill import backfill_missing_profile_background

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


async def _twin_search_people(query: str = "", limit: int = 12, company_filter: str = ""):
    search = (query or "").strip()
    company_scope = (company_filter or "").strip()

    async def _load(db):
        sql = """
            SELECT person_id, full_name, title_current, company_name_raw, cat, env
            FROM PERSON
            WHERE is_active = 1
        """
        params = []
        if company_scope:
            sql += " AND IFNULL(company_name_raw, '') LIKE ?"
            params.append(f"%{company_scope}%")
        if search:
            sql += " AND (full_name LIKE ? OR company_name_raw LIKE ? OR title_current LIKE ? OR email_primary LIKE ?)"
            token = f"%{search}%"
            params.extend([token, token, token, token])
        sql += " ORDER BY last_updated_at DESC LIMIT ?"
        params.append(limit)
        async with db.execute(sql, params) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    search_label = company_scope or search or "recent"
    return await run_read(_load, label=f"twin search people {search_label}")


def _tag_twin_people_results(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["result_type"] = "person"
    return rows


async def _twin_search_companies(query: str = "", limit: int = 12):
    from backend.routers.companies import (
        _enrich_company_rollup,
        _load_company_list_rows,
        _load_people_for_company_keys,
    )

    _total, company_rows = await _load_company_list_rows(query=query, limit=limit, offset=0)
    employees_by_key = await _load_people_for_company_keys([row.get("company_key") for row in company_rows])
    companies = _enrich_company_rollup(company_rows, employees_by_key, preview_count=3)
    for item in companies:
        item["result_type"] = "company"
    return companies


async def _twin_search_combined(query: str, *, people_limit: int = 8, company_limit: int = 8) -> tuple[list[dict], list[dict], list[dict]]:
    people = _tag_twin_people_results(await _twin_search_people(query=query, limit=people_limit))
    companies = await _twin_search_companies(query=query, limit=company_limit)
    combined = companies + people
    return people, companies, combined


def _extract_company_people_target(message: str) -> Optional[str]:
    text = str(message or "").strip()
    if not text:
        return None
    patterns = [
        r"\b(?:show|list|find)\s+(?:me\s+)?(?:everyone|all|people|contacts)\s+(?:who\s+)?(?:work|works|working)\s+(?:for|at|in)\s+(?P<company>.+)$",
        r"\b(?:everyone|all|people|contacts)\s+(?:who\s+)?(?:work|works|working)\s+(?:for|at|in)\s+(?P<company>.+)$",
        r"\bwho\s+(?:works|is working|work)\s+(?:for|at|in)\s+(?P<company>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        company = re.sub(r"\b(?:please|now)\b", "", str(match.group("company") or ""), flags=re.IGNORECASE)
        company = company.strip(" .,!?:;")
        if len(company) >= 2:
            return company
    return None


def _extract_company_lookup_target(message: str) -> Optional[str]:
    text = str(message or "").strip()
    if not text:
        return None

    patterns = [
        r"\b(?:find|search|lookup|look up|show|open)\s+(?:the\s+)?(?:company|companies|employer|employers)\s*(?:for|named|called|about)?\s*(?P<query>.+)?$",
        r"\b(?:tell me about|details for|details on)\s+(?P<query>.+?)\s+(?:company|employer)\b",
        r"\b(?:parent company|holding company)\s+(?:for|of)\s+(?P<query>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = str(match.groupdict().get("query") or "").strip(" .,!?:;")
        return query

    if re.search(r"\b(show|list|top)\b.*\b(companies|employers)\b", text, flags=re.IGNORECASE):
        return ""
    return None


async def _twin_db_snapshot() -> dict:
    async def _load(db):
        async with db.execute("SELECT COUNT(*) AS count FROM PERSON WHERE is_active = 1") as cursor:
            people_count = int((await cursor.fetchone())["count"])
        async with db.execute(
            """
            SELECT IFNULL(TRIM(company_name_raw), '') AS company_name, COUNT(*) AS people_count
            FROM PERSON
            WHERE is_active = 1 AND IFNULL(TRIM(company_name_raw), '') <> ''
            GROUP BY IFNULL(TRIM(company_name_raw), '')
            ORDER BY people_count DESC, company_name ASC
            LIMIT 10
            """
        ) as cursor:
            top_companies = [dict(row) for row in await cursor.fetchall()]
        return {"people_count": people_count, "top_companies": top_companies}

    return await run_read(_load, label="twin db snapshot")


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
    company_target = _extract_company_people_target(message)
    if company_target:
        return {"type": "search_company_people", "params": {"company": company_target}}

    company_lookup_target = _extract_company_lookup_target(message)
    if company_lookup_target is not None:
        return {"type": "search_companies", "params": {"query": company_lookup_target}}

    if re.search(r"\b(how many|count|total)\b.*\b(contacts|people|profiles)\b", lowered):
        return {"type": "db_summary", "params": {"scope": "counts"}}
    if re.search(r"\b(show|list|top)\b.*\b(companies|employers)\b", lowered):
        return {"type": "search_companies", "params": {"query": ""}}

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
    if intent["type"] == "search_company_people":
        company = intent["params"].get("company", "")
        preview = await _twin_search_people(limit=25, company_filter=company)
        reply = f"I found {len(preview)} contact{'s' if len(preview) != 1 else ''} at {company}."
        return {"reply": reply, "data": preview, "pending_action": None}
    if intent["type"] == "search_companies":
        query = intent["params"].get("query", "")
        companies = await _twin_search_companies(query=query, limit=20)
        if query:
            reply = f"I found {len(companies)} compan{'ies' if len(companies) != 1 else 'y'} matching '{query}'."
        else:
            reply = f"I found {len(companies)} companies with active coverage."
        return {"reply": reply, "data": companies, "pending_action": None}
    if intent["type"] == "db_summary":
        snapshot = await _twin_db_snapshot()
        scope = str(intent["params"].get("scope") or "")
        if scope == "companies":
            companies = snapshot.get("top_companies") or []
            if not companies:
                return {"reply": "No company data is available yet.", "data": [], "pending_action": None}
            top_line = ", ".join(
                f"{row.get('company_name')}: {row.get('people_count')}"
                for row in companies[:5]
            )
            return {
                "reply": f"Top companies by active contacts: {top_line}.",
                "data": companies,
                "pending_action": None,
            }
        total_people = int(snapshot.get("people_count") or 0)
        return {
            "reply": f"You currently have {total_people} active contacts in the database.",
            "data": snapshot,
            "pending_action": None,
        }
    if intent["type"] == "search":
        query = intent["params"].get("query", "")
        if query:
            people_preview, company_preview, combined_preview = await _twin_search_combined(query=query, people_limit=8, company_limit=8)
            reply = (
                f"I found {len(people_preview)} contact{'s' if len(people_preview) != 1 else ''} and "
                f"{len(company_preview)} compan{'ies' if len(company_preview) != 1 else 'y'} matching '{query}'."
            )
            return {"reply": reply, "data": combined_preview, "pending_action": intent}
        preview = _tag_twin_people_results(await _twin_search_people(query=query, limit=8))
        return {"reply": "Here are the most recently updated contacts.", "data": preview, "pending_action": intent}
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
    return {"reply": "I can find contacts, search employers and parent companies, answer basic DB counts, create tasks, add contacts, and process PDF contact documents. Try 'show companies', 'find company AECOM', 'show me everyone who works for WSP', or 'find Marcus'.", "data": None, "pending_action": None}


@router.post("/api/intelligence/twin/execute", tags=["compat"])
async def compat_twin_execute(req: dict):
    action_type = (req or {}).get("action_type")
    params = (req or {}).get("params") or {}
    if action_type == "search_company_people":
        results = await _twin_search_people(
            query=(params.get("query") or ""),
            company_filter=(params.get("company") or ""),
            limit=25,
        )
        tagged = _tag_twin_people_results(results)
        return {"status": "success", "message": f"Found {len(tagged)} contact{'s' if len(tagged) != 1 else '' }.", "data": tagged}
    if action_type == "search":
        query = (params.get("query") or "").strip()
        if query:
            people_results, company_results, combined = await _twin_search_combined(query=query, people_limit=25, company_limit=25)
            return {
                "status": "success",
                "message": (
                    f"Found {len(people_results)} contact{'s' if len(people_results) != 1 else ''} and "
                    f"{len(company_results)} compan{'ies' if len(company_results) != 1 else 'y'}."
                ),
                "data": combined,
            }
        recent_people = _tag_twin_people_results(await _twin_search_people(limit=25))
        return {"status": "success", "message": f"Found {len(recent_people)} contact{'s' if len(recent_people) != 1 else '' }.", "data": recent_people}
    if action_type == "search_companies":
        results = await _twin_search_companies(query=(params.get("query") or ""), limit=25)
        return {"status": "success", "message": f"Found {len(results)} compan{'ies' if len(results) != 1 else 'y'}.", "data": results}
    if action_type == "db_summary":
        snapshot = await _twin_db_snapshot()
        return {"status": "success", "message": "Database snapshot ready.", "data": snapshot}
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
        if result.get("status") == "created":
            try:
                await backfill_missing_profile_background(person_ids=[result.get("person_id")], limit=1, dry_run=False)
            except Exception as exc:
                print(f"Twin create backfill skipped for {result.get('person_id')}: {exc}")
        return {"status": "success", "message": f"Contact ready: {result['full_name']}", "data": result}
    raise HTTPException(400, "Unsupported Twin action")


def _extract_primary_email(text: str) -> Optional[str]:
    match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text or "", flags=re.IGNORECASE)
    return match.group(0).strip().lower() if match else None


def _normalize_phone_candidate(value: str) -> Optional[str]:
    raw = str(value or "").strip()
    if not raw:
        return None
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D+", "", raw)
    if len(digits) < 8:
        return None
    return f"+{digits}" if has_plus else digits


def _extract_primary_phone(text: str) -> Optional[str]:
    for match in re.finditer(r"(?:\+?\d[\d\-\s().]{7,}\d)", text or ""):
        normalized = _normalize_phone_candidate(match.group(0))
        if normalized:
            return normalized
    return None


def _extract_primary_linkedin(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(https?://(?:www\.)?linkedin\.com/[^\s)]+)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip().rstrip(".,;")
    match = re.search(r"(linkedin\.com/[^\s)]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return f"https://{match.group(1).strip().rstrip('.,;')}"


_PROFILE_HEADING_TOKENS = {
    "contact",
    "top skills",
    "skills",
    "summary",
    "experience",
    "certifications",
    "certification",
    "education",
    "projects",
    "languages",
    "publications",
    "interests",
    "about",
    "profile",
    "curriculum vitae",
    "resume",
}

_PROFILE_ROLE_TOKENS = (
    "manager",
    "director",
    "engineer",
    "head",
    "lead",
    "consultant",
    "partner",
    "specialist",
    "executive",
    "chief",
    "officer",
    "founder",
    "owner",
    "president",
    "vice president",
)

_NAME_CONNECTORS = {
    "al",
    "bin",
    "bint",
    "da",
    "de",
    "del",
    "den",
    "der",
    "di",
    "dos",
    "du",
    "el",
    "ibn",
    "la",
    "le",
    "st",
    "van",
    "von",
}

_NON_NAME_TERMS = {
    "accounting",
    "analysis",
    "analytics",
    "architecture",
    "asset",
    "business",
    "capital",
    "commercial",
    "construction",
    "consumer",
    "corporate",
    "delivery",
    "design",
    "development",
    "digital",
    "engineering",
    "execution",
    "finance",
    "financial",
    "growth",
    "implementation",
    "innovation",
    "intelligence",
    "investment",
    "leadership",
    "management",
    "market",
    "marketing",
    "operations",
    "performance",
    "portfolio",
    "procurement",
    "program",
    "project",
    "real",
    "risk",
    "skills",
    "strategy",
    "supply",
    "systems",
    "talent",
    "technology",
    "transformation",
    "valuation",
    "value",
}


def _normalize_heading_candidate(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z]+", " ", str(value or "").lower())).strip()


def _is_profile_heading(value: str) -> bool:
    normalized = _normalize_heading_candidate(value)
    if not normalized:
        return False
    if normalized in _PROFILE_HEADING_TOKENS:
        return True
    return any(normalized.startswith(f"{token} ") for token in _PROFILE_HEADING_TOKENS)


def _strip_name_suffixes(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text).strip(" ,")
    if "," in text:
        parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(parts) > 1 and all(re.fullmatch(r"[A-Z]{2,8}", part) for part in parts[1:]):
            text = parts[0]
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_person_name(value: str) -> bool:
    candidate = _strip_name_suffixes(value)
    if not candidate or _is_profile_heading(candidate):
        return False
    lowered = candidate.lower()
    if any(marker in lowered for marker in ("@", "http://", "https://", "linkedin.com")):
        return False
    if any(ch.isdigit() for ch in candidate):
        return False
    words = [word.strip(".,;:") for word in candidate.split() if word.strip(".,;:")]
    if len(words) < 2 or len(words) > 4:
        return False
    lowered_words = {word.lower() for word in words}
    if any(word in _NON_NAME_TERMS for word in lowered_words):
        return False
    heading_words = {token for token in " ".join(_PROFILE_HEADING_TOKENS).split()}
    if lowered_words & heading_words:
        return False
    role_words = set(" ".join(_PROFILE_ROLE_TOKENS).split())
    if lowered_words & role_words:
        return False
    first_word = words[0].lower()
    last_word = words[-1].lower()
    if first_word in _NAME_CONNECTORS or last_word in _NAME_CONNECTORS:
        return False
    for word in words:
        lowered = word.lower()
        if lowered in _NAME_CONNECTORS:
            continue
        if re.fullmatch(r"[A-Z]{2,}", word):
            continue
        if re.fullmatch(r"[A-Z][A-Za-z'\-]+", word):
            continue
        return False
    return True


def _candidate_line_is_heading_context(candidate: str, lines: list[str]) -> bool:
    candidate_clean = _strip_name_suffixes(candidate)
    if not candidate_clean:
        return False
    for idx, line in enumerate(lines[:80]):
        if _strip_name_suffixes(line).lower() != candidate_clean.lower():
            continue
        for offset in (1, 2):
            if idx - offset < 0:
                break
            if _is_profile_heading(lines[idx - offset]):
                return True
    return False


def _extract_name_from_profile_lines(lines: list[str]) -> Optional[str]:
    candidates: list[tuple[int, str]] = []
    for idx, line in enumerate(lines[:40]):
        previous_line = lines[idx - 1] if idx > 0 else ""
        if _is_profile_heading(previous_line):
            continue
        candidate = _strip_name_suffixes(line)
        if not _looks_like_person_name(candidate):
            continue
        score = 100 - idx
        if "," in line:
            score += 8
        if idx + 1 < len(lines):
            next_line = lines[idx + 1].lower()
            if any(token in next_line for token in _PROFILE_ROLE_TOKENS):
                score += 20
        candidates.append((score, candidate))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _sanitize_employment_history(raw_value) -> list[dict]:
    if not isinstance(raw_value, list):
        return []
    cleaned = []
    for item in raw_value:
        if not isinstance(item, dict):
            continue
        role = {
            "title": str(item.get("title") or "").strip(),
            "company": str(item.get("company") or "").strip(),
            "start_date": str(item.get("start_date") or "").strip(),
            "end_date": str(item.get("end_date") or "").strip(),
            "location": str(item.get("location") or "").strip(),
            "description": str(item.get("description") or "").strip(),
        }
        if any(role.values()):
            cleaned.append(role)
    return cleaned


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
    from backend.services.ai_service import extract_document_profile, extract_text_from_file
    extracted_text = extract_text_from_file(file_path) or ""
    if not extracted_text.strip():
        raise HTTPException(400, "I could not extract readable text from that PDF.")

    profile_result = {}
    if settings.OPENAI_CONFIGURED:
        try:
            profile_result = await extract_document_profile(extracted_text)
        except Exception as exc:
            print(f"twin upload pdf profile extraction error: {exc}")

    lines = [line.strip() for line in extracted_text.splitlines() if line.strip()]
    name = str((profile_result or {}).get("full_name") or "").strip() or None
    if name and (not _looks_like_person_name(name) or _candidate_line_is_heading_context(name, lines)):
        name = None
    title = str((profile_result or {}).get("title_current") or "").strip() or None
    company = str((profile_result or {}).get("company_name_raw") or "").strip() or None

    if not name:
        name = _extract_name_from_profile_lines(lines)
    for line in lines[:18]:
        if not title and any(token in line.lower() for token in _PROFILE_ROLE_TOKENS):
            title = line
            continue
        if (
            not company
            and line not in {name, title}
            and len(line.split()) <= 6
            and not _is_profile_heading(line)
            and "linkedin" not in line.lower()
        ):
            company = line

    email_primary = str((profile_result or {}).get("email_primary") or "").strip().lower() or _extract_primary_email(extracted_text)
    phone_primary = _normalize_phone_candidate(str((profile_result or {}).get("phone_primary") or "")) or _extract_primary_phone(extracted_text)
    linkedin_url = str((profile_result or {}).get("linkedin_url") or "").strip() or _extract_primary_linkedin(extracted_text)
    career_summary = str((profile_result or {}).get("career_summary") or "").strip() or extracted_text[:1200]
    key_professional_notes = str((profile_result or {}).get("key_professional_notes") or "").strip() or None
    employment_history = _sanitize_employment_history((profile_result or {}).get("employment_history"))
    if not title and employment_history:
        title = str(employment_history[0].get("title") or "").strip() or title
    if not company and employment_history:
        company = str(employment_history[0].get("company") or "").strip() or company
    employment_history_json = json.dumps(employment_history, ensure_ascii=False) if employment_history else None

    if not name:
        raise HTTPException(400, "I could not confidently identify a contact name from that PDF.")
    person_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async def _create(db):
        async with db.execute(
            """
            SELECT person_id, full_name, title_current, company_name_raw, email_primary, phone_primary,
                   linkedin_url, career_summary, key_professional_notes, employment_history
            FROM PERSON
            WHERE full_name = ? AND IFNULL(company_name_raw, '') = IFNULL(?, '')
            LIMIT 1
            """,
            (name, company),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing:
            existing = dict(existing)
            updates = []
            values = []
            for field, value in (
                ("title_current", title),
                ("company_name_raw", company),
                ("email_primary", email_primary),
                ("phone_primary", phone_primary),
                ("linkedin_url", linkedin_url),
                ("career_summary", career_summary),
                ("key_professional_notes", key_professional_notes),
            ):
                if value and not str(existing.get(field) or "").strip():
                    updates.append(f"{field}=?")
                    values.append(value)
            if employment_history_json and not str(existing.get("employment_history") or "").strip():
                updates.append("employment_history=?")
                values.append(employment_history_json)
            if updates:
                updates.append("last_updated_at=?")
                values.append(now)
                values.append(existing["person_id"])
                await db.execute(f"UPDATE PERSON SET {', '.join(updates)} WHERE person_id=?", values)
                return {"status": "updated", "person_id": existing["person_id"], "full_name": existing["full_name"]}
            return {"status": "exists", "person_id": existing["person_id"], "full_name": existing["full_name"]}
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, email_primary, phone_primary, linkedin_url,
                cat, career_summary, key_professional_notes, employment_history, created_at, last_updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                name,
                title,
                company,
                email_primary,
                phone_primary,
                linkedin_url,
                "GEN",
                career_summary,
                key_professional_notes,
                employment_history_json,
                now,
                now,
            ),
        )
        return {"status": "created", "person_id": person_id, "full_name": name}
    result = await run_write(_create, label=f"twin pdf create person {name}")
    return {"status": result["status"], "reply": f"Contact ready: {result['full_name']}", "data": result}


# End of file



