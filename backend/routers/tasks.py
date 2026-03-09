"""
Antigravity CRM — Tasks Router
Full task management: create, list, update, complete, delete.
"""
import uuid
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from backend.database import get_db

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _calc_meeting_status(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days = (dt - datetime.now()).days
        if days < 0:
            return "overdue"
        elif days <= 7:
            return "soon"
        return "on_track"
    except Exception:
        return None


class TaskCreate(BaseModel):
    person_id: Optional[str] = None
    task_text: str
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: str = "medium"  # high | medium | low
    recurrence_rule: Optional[str] = None


class TaskUpdate(BaseModel):
    task_text: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None   # open | done | cancelled
    recurrence_rule: Optional[str] = None


@router.get("")
async def list_tasks(
    status: str = Query("open"),         # open | done | all
    person_id: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    days: Optional[int] = Query(None),   # tasks due within N days
):
    sql = """
        SELECT t.*, p.full_name as person_name, p.company_name_raw, p.cat, p.profile_photo_url
        FROM TASK t
        LEFT JOIN PERSON p ON t.person_id = p.person_id
        WHERE 1=1
    """
    params = []
    if status != "all":
        sql += " AND t.status=?"
        params.append(status)
    if person_id:
        sql += " AND t.person_id=?"
        params.append(person_id)
    if priority:
        sql += " AND t.priority=?"
        params.append(priority)
    if days is not None:
        limit_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        sql += " AND t.due_date <= ?"
        params.append(limit_date)

    sql += " ORDER BY t.due_date ASC NULLS LAST, t.created_at DESC"

    async with get_db() as db:
        async with db.execute(sql, params) as c:
            rows = await c.fetchall()

    return [dict(r) for r in rows]


@router.post("")
async def create_task(task: TaskCreate):
    tid = str(uuid.uuid4())
    now = _now()

    async with get_db() as db:
        await db.execute("""
            INSERT INTO TASK (task_id, person_id, task_text, due_date, due_time,
                              priority, status, recurrence_rule, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (tid, task.person_id, task.task_text, task.due_date, task.due_time,
              task.priority, "open", task.recurrence_rule, now))

        # Update person's next_contact_due_date if linked
        if task.person_id and task.due_date:
            await db.execute("""
                UPDATE PERSON SET next_contact_due_date = (
                    SELECT MIN(due_date) FROM TASK
                    WHERE person_id=? AND status='open' AND due_date IS NOT NULL
                ), meeting_status=?, last_updated_at=?
                WHERE person_id=?
            """, (task.person_id, _calc_meeting_status(task.due_date), now, task.person_id))

        await db.commit()

    return {"status": "created", "task_id": tid}


@router.patch("/{task_id}")
async def update_task(task_id: str, req: TaskUpdate):
    async with get_db() as db:
        async with db.execute("SELECT * FROM TASK WHERE task_id=?", (task_id,)) as c:
            row = await c.fetchone()
        if not row:
            raise HTTPException(404, "Task not found")

        fields, values = [], []
        data = req.model_dump(exclude_none=True)
        for k, v in data.items():
            fields.append(f"{k}=?")
            values.append(v)

        if data.get("status") == "done":
            fields.append("completed_at=?")
            values.append(_now())

        if not fields:
            return {"status": "no_change"}

        values.append(task_id)
        await db.execute(f"UPDATE TASK SET {', '.join(fields)} WHERE task_id=?", values)

        # Recalculate person meeting status if date changed
        person_id = row["person_id"]
        if person_id and (data.get("due_date") or data.get("status")):
            await db.execute("""
                UPDATE PERSON SET next_contact_due_date = (
                    SELECT MIN(due_date) FROM TASK WHERE person_id=? AND status='open'
                ), last_updated_at=? WHERE person_id=?
            """, (person_id, _now(), person_id))

        await db.commit()

    return {"status": "updated"}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM TASK WHERE task_id=?", (task_id,))
        await db.commit()
    return {"status": "deleted"}


@router.get("/pipeline")
async def get_pipeline(days: int = Query(30)):
    """Dashboard pipeline — upcoming tasks + contacts with no scheduled touchpoint."""
    from datetime import timedelta
    limit_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d")

    async with get_db() as db:
        # Contacts with upcoming tasks
        async with db.execute("""
            SELECT p.person_id, p.full_name, p.title_current, p.company_name_raw,
                   p.cat, p.env, p.disc, p.profile_photo_url, p.contact_value,
                   MIN(t.due_date) as next_due, t.task_text, t.priority
            FROM PERSON p JOIN TASK t ON p.person_id = t.person_id
            WHERE p.is_active=1 AND t.status='open' AND t.due_date <= ?
            GROUP BY p.person_id ORDER BY MIN(t.due_date) ASC
        """, (limit_date,)) as c:
            pipeline = [dict(r) for r in await c.fetchall()]

        # High-value contacts with no upcoming tasks (gaps)
        async with db.execute("""
            SELECT person_id, full_name, title_current, company_name_raw,
                   cat, env, next_contact_due_date
            FROM PERSON
            WHERE is_active=1 AND cat IN ('OBE M','OBE T')
              AND person_id NOT IN (
                  SELECT DISTINCT person_id FROM TASK WHERE status='open'
              )
            ORDER BY full_name LIMIT 50
        """) as c:
            gaps = [dict(r) for r in await c.fetchall()]

    return {"pipeline": pipeline, "action_gaps": gaps, "days": days}
