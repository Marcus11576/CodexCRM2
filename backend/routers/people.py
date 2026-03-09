"""
Antigravity CRM — People Router
All contact CRUD, search, pipeline, meeting management.
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from backend.database import get_db, run_write

router = APIRouter(prefix="/api/people", tags=["people"])


# ── Pydantic Models ──────────────────────────────────────────────────────────

class PersonCreate(BaseModel):
    full_name: str
    title_current: Optional[str] = None
    company_name_raw: Optional[str] = None
    email_primary: Optional[str] = None
    email_secondary: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    linkedin_url: Optional[str] = None
    cat: Optional[str] = "GEN"
    env: Optional[str] = None
    disc: Optional[str] = None
    contact_value: Optional[str] = None
    career_summary: Optional[str] = None
    key_professional_notes: Optional[str] = None
    key_personal_notes: Optional[str] = None
    profile_photo_url: Optional[str] = None


class PersonUpdate(BaseModel):
    full_name: Optional[str] = None
    title_current: Optional[str] = None
    company_name_raw: Optional[str] = None
    email_primary: Optional[str] = None
    email_secondary: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    linkedin_url: Optional[str] = None
    cat: Optional[str] = None
    env: Optional[str] = None
    disc: Optional[str] = None
    contact_value: Optional[str] = None
    engagement_status: Optional[str] = None
    is_ts_advisory_candidate: Optional[bool] = None
    career_summary: Optional[str] = None
    key_professional_notes: Optional[str] = None
    key_personal_notes: Optional[str] = None
    key_gossip_notes: Optional[str] = None
    intel_notes: Optional[str] = None
    employment_history: Optional[str] = None   # JSON string
    personal_data: Optional[str] = None        # JSON string
    profile_photo_url: Optional[str] = None
    next_contact_due_date: Optional[str] = None
    meeting_status: Optional[str] = None


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    """Convert aiosqlite Row to dict and parse JSON fields."""
    d = dict(row)
    for field in ("employment_history", "personal_data", "cached_briefing", "action_items", "topics"):
        if field in d and isinstance(d[field], str) and d[field]:
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_people(
    q: Optional[str] = Query(None),
    cat: Optional[str] = Query(None),
    env: Optional[str] = Query(None),
    disc: Optional[str] = Query(None),
    meeting_status: Optional[str] = Query(None),
    contact_value: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
    offset: int = Query(0),
):
    """Search and filter contacts. All parameters are optional and combinable."""
    sql = """
        SELECT person_id, full_name, title_current, company_name_raw,
               email_primary, phone_primary, linkedin_url,
               cat, env, disc, contact_value, engagement_status,
               profile_photo_url, meeting_status, next_contact_due_date,
               last_contact_datetime, is_active, is_ts_advisory_candidate,
               career_summary, key_professional_notes, created_at, last_updated_at
        FROM PERSON WHERE is_active = 1
    """
    params = []

    if q and q.strip():
        sql += " AND (full_name LIKE ? OR company_name_raw LIKE ? OR title_current LIKE ? OR email_primary LIKE ?)"
        t = f"%{q.strip()}%"
        params.extend([t, t, t, t])
    if cat and cat != "All":
        sql += " AND cat = ?"
        params.append(cat)
    if env and env != "All":
        sql += " AND env = ?"
        params.append(env)
    if disc and disc != "All":
        sql += " AND disc = ?"
        params.append(disc)
    if meeting_status and meeting_status != "All":
        sql += " AND meeting_status = ?"
        params.append(meeting_status)
    if contact_value and contact_value != "All":
        sql += " AND contact_value = ?"
        params.append(contact_value)

    sql += " ORDER BY last_updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with get_db() as db:
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        async with db.execute("SELECT COUNT(*) FROM PERSON WHERE is_active=1") as c:
            total = (await c.fetchone())[0]

    return {"total": total, "people": [_row_to_dict(r) for r in rows]}


@router.post("")
async def create_person(person: PersonCreate):
    """Create a new contact. Returns existing person if name+company match found."""
    now = _now()
    pid = str(uuid.uuid4())

    async def _create(db):
        async with db.execute(
            "SELECT person_id FROM PERSON WHERE full_name=? AND company_name_raw=?",
            (person.full_name, person.company_name_raw)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return {"status": "exists", "person_id": existing["person_id"]}

        await db.execute("""
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw,
                email_primary, email_secondary, phone_primary, phone_secondary,
                linkedin_url, cat, env, disc, contact_value,
                career_summary, key_professional_notes, key_personal_notes,
                profile_photo_url, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, person.full_name, person.title_current, person.company_name_raw,
              person.email_primary, person.email_secondary, person.phone_primary,
              person.phone_secondary, person.linkedin_url, person.cat, person.env,
              person.disc, person.contact_value, person.career_summary,
              person.key_professional_notes, person.key_personal_notes,
              person.profile_photo_url, now, now))
        return {"status": "created", "person_id": pid}

    return await run_write(_create, label=f"create person {person.full_name}")

@router.get("/stats")
async def get_stats():
    """Dashboard counters."""
    async with get_db() as db:
        stats = {}
        async with db.execute("SELECT COUNT(*) FROM PERSON WHERE is_active=1") as c:
            stats["total_contacts"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM INTERACTION") as c:
            stats["total_interactions"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM TASK WHERE status='open'") as c:
            stats["open_tasks"] = (await c.fetchone())[0]
        async with db.execute(
            "SELECT meeting_status, COUNT(*) as cnt FROM PERSON WHERE is_active=1 AND meeting_status IS NOT NULL GROUP BY meeting_status"
        ) as c:
            rows = await c.fetchall()
            for row in rows:
                stats[f"meeting_{row['meeting_status']}"] = row["cnt"]
        async with db.execute(
            "SELECT cat, COUNT(*) as cnt FROM PERSON WHERE is_active=1 GROUP BY cat"
        ) as c:
            rows = await c.fetchall()
            stats["by_cat"] = {r["cat"]: r["cnt"] for r in rows if r["cat"]}
    return stats


@router.get("/{person_id}")
async def get_person(person_id: str):
    """Full person profile with interaction history and open tasks."""
    async with get_db() as db:
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as c:
            row = await c.fetchone()
        if not row:
            raise HTTPException(404, "Person not found")
        person = _row_to_dict(row)

        async with db.execute("""
            SELECT interaction_id, channel, raw_text, summary, action_items,
                   topics, sentiment, media_url, created_at, interaction_at
            FROM INTERACTION WHERE person_id=? AND channel != 'system_audit'
            ORDER BY interaction_at DESC LIMIT 50
        """, (person_id,)) as c:
            interactions = [_row_to_dict(r) for r in await c.fetchall()]

        async with db.execute("""
            SELECT task_id, task_text, due_date, due_time, priority, status, created_at
            FROM TASK WHERE person_id=? AND status='open' ORDER BY due_date ASC
        """, (person_id,)) as c:
            tasks = [dict(r) for r in await c.fetchall()]

        async with db.execute("""
            SELECT topic, intel_text, confidence, created_at
            FROM TOPIC_INTELLIGENCE WHERE person_id=? ORDER BY created_at DESC
        """, (person_id,)) as c:
            intel = [dict(r) for r in await c.fetchall()]

    return {"person": person, "history": interactions, "tasks": tasks, "intelligence": intel}


@router.patch("/{person_id}")
@router.put("/{person_id}")
async def update_person(person_id: str, req: PersonUpdate):
    """Partial update — only provided fields are updated."""
    fields, values = [], []
    data = req.model_dump(exclude_none=True)

    for field, value in data.items():
        if field == "is_ts_advisory_candidate":
            value = 1 if value else 0
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        fields.append(f"{field}=?")
        values.append(value)

    if not fields:
        return {"status": "no_change"}

    now = _now()
    fields.append("last_updated_at=?")
    values.append(now)
    values.append(person_id)

    audit_fields = {"cat", "env", "disc", "full_name", "company_name_raw", "title_current"}
    audit_entries = [f for f in data.keys() if f in audit_fields]

    async def _update(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)) as c:
            if not await c.fetchone():
                raise HTTPException(404, "Person not found")

        await db.execute(f"UPDATE PERSON SET {', '.join(fields)} WHERE person_id=?", values)

        for field in audit_entries:
            iid = str(uuid.uuid4())
            msg = f"Manual Update: {field.replace('_',' ').title()} -> '{data[field]}'"
            await db.execute("""
                INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?)
            """, (iid, person_id, "system_audit", msg, msg, now, now))

        await db.execute("UPDATE PERSON SET cached_briefing=NULL WHERE person_id=?", (person_id,))

    await run_write(_update, label=f"update person {person_id}")
    return {"status": "success"}

@router.delete("/{person_id}")
async def deactivate_person(person_id: str):
    """Soft delete — marks as inactive, preserves all data."""
    async def _deactivate(db):
        await db.execute("UPDATE PERSON SET is_active=0, last_updated_at=? WHERE person_id=?",
                         (_now(), person_id))

    await run_write(_deactivate, label=f"deactivate person {person_id}")
    return {"status": "success"}

class IntelligenceUpdate(BaseModel):
    text: Optional[str] = None
    topic: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[int] = None

@router.get("/{person_id}/intelligence")
async def get_intelligence(person_id: str):
    """4-quadrant intelligence databank for a person."""
    topics = ["business_focus", "recruitment_talent", "family_personal", "obe_focus"]
    result = {t: [] for t in topics}
    async with get_db() as db:
        async with db.execute("""
            SELECT t.intel_id, t.topic, t.intel_text, t.confidence, t.created_at, t.status, t.source_snippet, i.channel 
            FROM TOPIC_INTELLIGENCE t
            LEFT JOIN INTERACTION i ON t.source_interaction_id = i.interaction_id
            WHERE t.person_id=? 
            ORDER BY t.created_at DESC
        """, (person_id,)) as c:
            rows = await c.fetchall()
            
    for row in rows:
        t = row["topic"]
        if t in result:
            result[t].append({
                "intel_id": row["intel_id"],
                "text": row["intel_text"], 
                "confidence": row["confidence"], 
                "date": row["created_at"],
                "status": row.get("status"),
                "snippet": row.get("source_snippet"),
                "channel": row["channel"] or "manual override"
            })
    return result

@router.patch("/{person_id}/intelligence/{intel_id}")
async def update_intelligence(person_id: str, intel_id: str, req: IntelligenceUpdate):
    """Edit or change status/category of a single intelligence point."""
    fields = []
    values = []
    if req.text is not None:
        fields.append("intel_text=?")
        values.append(req.text)
    if req.topic is not None:
        fields.append("topic=?")
        values.append(req.topic)
    if req.status is not None:
        fields.append("status=?")
        values.append(req.status)
    if req.confidence is not None:
        fields.append("confidence=?")
        values.append(req.confidence)
    if not fields:
        raise HTTPException(400, "No fields to update")
    values.append(intel_id)

    async def _update(db):
        await db.execute(f"UPDATE TOPIC_INTELLIGENCE SET {', '.join(fields)} WHERE intel_id=?", tuple(values))
    await run_write(_update, label=f"update intelligence {intel_id}")
    return {"status": "updated"}


