"""
Antigravity CRM - Events Router
Core event management for CRM relationship planning.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_db

router = APIRouter(prefix="/api/events", tags=["events"])

EVENT_STATUSES = ["Target", "Invited", "Confirmed", "Registered"]


class EventCreate(BaseModel):
    event_name: str
    location: Optional[str] = None
    event_date: str
    topics: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class EventUpdate(BaseModel):
    event_name: Optional[str] = None
    location: Optional[str] = None
    event_date: Optional[str] = None
    topics: Optional[List[str]] = None
    notes: Optional[str] = None


class EventLinkCreate(BaseModel):
    person_id: Optional[str] = None
    event_id: Optional[str] = None
    status: str


class EventLinkUpdate(BaseModel):
    status: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_topics(raw_value):
    if not raw_value:
        return []
    if isinstance(raw_value, list):
        return raw_value
    try:
        return json.loads(raw_value)
    except Exception:
        return [raw_value]


def _normalize_topics(topics: Optional[List[str]]) -> str:
    clean = []
    for topic in topics or []:
        value = (topic or '').strip()
        if value and value not in clean:
            clean.append(value)
    return json.dumps(clean)


def _validate_status(status: str) -> str:
    if status not in EVENT_STATUSES:
        raise HTTPException(400, f"Invalid event status. Expected one of: {', '.join(EVENT_STATUSES)}")
    return status


def _format_event_row(row) -> dict:
    item = dict(row)
    item['topics'] = _parse_topics(item.get('topics'))
    return item


async def _get_event_detail(db, event_id: str):
    async with db.execute(
        """
        SELECT e.event_id, e.event_name, e.location, e.event_date, e.topics, e.notes,
               e.created_at, e.updated_at,
               COUNT(pe.person_event_id) AS linked_people_count,
               SUM(CASE WHEN pe.status = 'Target' THEN 1 ELSE 0 END) AS target_count,
               SUM(CASE WHEN pe.status = 'Invited' THEN 1 ELSE 0 END) AS invited_count,
               SUM(CASE WHEN pe.status = 'Confirmed' THEN 1 ELSE 0 END) AS confirmed_count,
               SUM(CASE WHEN pe.status = 'Registered' THEN 1 ELSE 0 END) AS registered_count
        FROM EVENT e
        LEFT JOIN PERSON_EVENT pe ON pe.event_id = e.event_id
        WHERE e.event_id = ?
        GROUP BY e.event_id
        """,
        (event_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, 'Event not found')

    event = _format_event_row(row)
    event['linked_people_count'] = event.get('linked_people_count') or 0
    event['status_counts'] = {
        'Target': event.pop('target_count') or 0,
        'Invited': event.pop('invited_count') or 0,
        'Confirmed': event.pop('confirmed_count') or 0,
        'Registered': event.pop('registered_count') or 0,
    }

    async with db.execute(
        """
        SELECT p.person_id, p.full_name, p.title_current, p.company_name_raw, p.profile_photo_url,
               pe.status, pe.created_at, pe.updated_at
        FROM PERSON_EVENT pe
        JOIN PERSON p ON p.person_id = pe.person_id
        WHERE pe.event_id = ? AND p.is_active = 1
        ORDER BY p.full_name COLLATE NOCASE ASC
        """,
        (event_id,),
    ) as cursor:
        rows = await cursor.fetchall()

    grouped = {status: [] for status in EVENT_STATUSES}
    for row in rows:
        grouped[row['status']].append(dict(row))

    event['people_by_status'] = grouped
    return event


@router.get('/status-options')
async def get_event_status_options():
    return {'statuses': EVENT_STATUSES}


@router.get('/dashboard/summary')
async def get_event_dashboard_summary(limit: int = Query(5, ge=1, le=12)):
    async with get_db() as db:
        async with db.execute(
            """
            SELECT e.event_id, e.event_name, e.location, e.event_date, e.topics,
                   COUNT(pe.person_event_id) AS linked_people_count,
                   SUM(CASE WHEN pe.status = 'Confirmed' THEN 1 ELSE 0 END) AS confirmed_count,
                   SUM(CASE WHEN pe.status = 'Registered' THEN 1 ELSE 0 END) AS registered_count
            FROM EVENT e
            LEFT JOIN PERSON_EVENT pe ON pe.event_id = e.event_id
            WHERE date(e.event_date) >= date('now')
            GROUP BY e.event_id
            ORDER BY date(e.event_date) ASC, e.event_name COLLATE NOCASE ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            upcoming_rows = await cursor.fetchall()

        async with db.execute(
            """
            SELECT COUNT(*) AS event_count,
                   COALESCE(SUM(linked_people_count), 0) AS linked_people_total
            FROM (
                SELECT e.event_id, COUNT(pe.person_event_id) AS linked_people_count
                FROM EVENT e
                LEFT JOIN PERSON_EVENT pe ON pe.event_id = e.event_id
                WHERE date(e.event_date) >= date('now')
                GROUP BY e.event_id
            )
            """
        ) as cursor:
            totals = await cursor.fetchone()

    return {
        'upcoming_event_count': totals['event_count'] if totals else 0,
        'upcoming_linked_people': totals['linked_people_total'] if totals else 0,
        'upcoming_events': [
            {
                **_format_event_row(row),
                'linked_people_count': row['linked_people_count'] or 0,
                'confirmed_count': row['confirmed_count'] or 0,
                'registered_count': row['registered_count'] or 0,
            }
            for row in upcoming_rows
        ],
    }


@router.get('')
async def list_events(q: Optional[str] = Query(None), upcoming_only: bool = Query(False)):
    sql = """
        SELECT e.event_id, e.event_name, e.location, e.event_date, e.topics, e.notes,
               e.created_at, e.updated_at,
               COUNT(pe.person_event_id) AS linked_people_count,
               SUM(CASE WHEN pe.status = 'Target' THEN 1 ELSE 0 END) AS target_count,
               SUM(CASE WHEN pe.status = 'Invited' THEN 1 ELSE 0 END) AS invited_count,
               SUM(CASE WHEN pe.status = 'Confirmed' THEN 1 ELSE 0 END) AS confirmed_count,
               SUM(CASE WHEN pe.status = 'Registered' THEN 1 ELSE 0 END) AS registered_count
        FROM EVENT e
        LEFT JOIN PERSON_EVENT pe ON pe.event_id = e.event_id
        WHERE 1 = 1
    """
    params = []
    if q and q.strip():
        sql += ' AND (e.event_name LIKE ? OR e.location LIKE ? OR e.topics LIKE ? OR e.notes LIKE ?)'
        term = f"%{q.strip()}%"
        params.extend([term, term, term, term])
    if upcoming_only:
        sql += " AND date(e.event_date) >= date('now')"
    sql += " GROUP BY e.event_id ORDER BY date(e.event_date) ASC, e.event_name COLLATE NOCASE ASC"

    async with get_db() as db:
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    events = []
    for row in rows:
        event = _format_event_row(row)
        event['linked_people_count'] = event.get('linked_people_count') or 0
        event['status_counts'] = {
            'Target': event.pop('target_count') or 0,
            'Invited': event.pop('invited_count') or 0,
            'Confirmed': event.pop('confirmed_count') or 0,
            'Registered': event.pop('registered_count') or 0,
        }
        events.append(event)

    return {'events': events, 'statuses': EVENT_STATUSES}


@router.post('')
async def create_event(payload: EventCreate):
    now = _now()
    event_id = str(uuid.uuid4())
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO EVENT (event_id, event_name, location, event_date, topics, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                payload.event_name.strip(),
                payload.location,
                payload.event_date,
                _normalize_topics(payload.topics),
                payload.notes,
                now,
                now,
            ),
        )
        await db.commit()
        detail = await _get_event_detail(db, event_id)
    return {'status': 'created', 'event': detail}


@router.get('/{event_id}')
async def get_event(event_id: str):
    async with get_db() as db:
        detail = await _get_event_detail(db, event_id)
    return detail


@router.patch('/{event_id}')
@router.put('/{event_id}')
async def update_event(event_id: str, payload: EventUpdate):
    data = payload.model_dump(exclude_none=True)
    if not data:
        return {'status': 'no_change'}

    fields = []
    values = []
    for field, value in data.items():
        if field == 'topics':
            value = _normalize_topics(value)
        if field == 'event_name' and value is not None:
            value = value.strip()
        fields.append(f"{field} = ?")
        values.append(value)
    fields.append('updated_at = ?')
    values.append(_now())
    values.append(event_id)

    async with get_db() as db:
        async with db.execute('SELECT event_id FROM EVENT WHERE event_id = ?', (event_id,)) as cursor:
            if not await cursor.fetchone():
                raise HTTPException(404, 'Event not found')
        await db.execute(f"UPDATE EVENT SET {', '.join(fields)} WHERE event_id = ?", values)
        await db.commit()
        detail = await _get_event_detail(db, event_id)
    return {'status': 'updated', 'event': detail}


@router.get('/{event_id}/people')
async def get_event_people(event_id: str):
    async with get_db() as db:
        detail = await _get_event_detail(db, event_id)
    return {'event_id': event_id, 'people_by_status': detail['people_by_status'], 'status_counts': detail['status_counts']}


@router.post('/{event_id}/people')
async def add_person_to_event(event_id: str, payload: EventLinkCreate):
    if not payload.person_id:
        raise HTTPException(400, 'person_id is required')
    status = _validate_status(payload.status)
    now = _now()

    async with get_db() as db:
        async with db.execute('SELECT person_id FROM PERSON WHERE person_id = ? AND is_active = 1', (payload.person_id,)) as cursor:
            if not await cursor.fetchone():
                raise HTTPException(404, 'Person not found')
        async with db.execute('SELECT event_id FROM EVENT WHERE event_id = ?', (event_id,)) as cursor:
            if not await cursor.fetchone():
                raise HTTPException(404, 'Event not found')

        await db.execute(
            """
            INSERT INTO PERSON_EVENT (person_event_id, person_id, event_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(person_id, event_id)
            DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
            """,
            (str(uuid.uuid4()), payload.person_id, event_id, status, now, now),
        )
        await db.commit()
        detail = await _get_event_detail(db, event_id)
    return {'status': 'linked', 'event': detail}


@router.patch('/{event_id}/people/{person_id}')
async def update_event_person_status(event_id: str, person_id: str, payload: EventLinkUpdate):
    status = _validate_status(payload.status)
    async with get_db() as db:
        cursor = await db.execute(
            'UPDATE PERSON_EVENT SET status = ?, updated_at = ? WHERE event_id = ? AND person_id = ?',
            (status, _now(), event_id, person_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, 'Person-event link not found')
        detail = await _get_event_detail(db, event_id)
    return {'status': 'updated', 'event': detail}


@router.delete('/{event_id}/people/{person_id}')
async def remove_person_from_event(event_id: str, person_id: str):
    async with get_db() as db:
        cursor = await db.execute('DELETE FROM PERSON_EVENT WHERE event_id = ? AND person_id = ?', (event_id, person_id))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, 'Person-event link not found')
    return {'status': 'removed'}


@router.get('/people/{person_id}/links')
async def get_person_events(person_id: str):
    async with get_db() as db:
        async with db.execute(
            """
            SELECT e.event_id, e.event_name, e.location, e.event_date, e.topics, e.notes,
                   pe.status, pe.created_at, pe.updated_at
            FROM PERSON_EVENT pe
            JOIN EVENT e ON e.event_id = pe.event_id
            WHERE pe.person_id = ?
            ORDER BY date(e.event_date) ASC, e.event_name COLLATE NOCASE ASC
            """,
            (person_id,),
        ) as cursor:
            rows = await cursor.fetchall()
    return {
        'person_id': person_id,
        'statuses': EVENT_STATUSES,
        'events': [{**_format_event_row(row), 'status': row['status']} for row in rows],
    }


@router.post('/people/{person_id}/links')
async def link_event_to_person(person_id: str, payload: EventLinkCreate):
    if not payload.event_id:
        raise HTTPException(400, 'event_id is required')
    return await add_person_to_event(payload.event_id, EventLinkCreate(person_id=person_id, status=payload.status))


@router.patch('/people/{person_id}/links/{event_id}')
async def update_person_event_link(person_id: str, event_id: str, payload: EventLinkUpdate):
    status = _validate_status(payload.status)
    async with get_db() as db:
        cursor = await db.execute(
            'UPDATE PERSON_EVENT SET status = ?, updated_at = ? WHERE person_id = ? AND event_id = ?',
            (status, _now(), person_id, event_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, 'Person-event link not found')
    return {'status': 'updated'}


@router.delete('/people/{person_id}/links/{event_id}')
async def remove_event_from_person(person_id: str, event_id: str):
    async with get_db() as db:
        cursor = await db.execute('DELETE FROM PERSON_EVENT WHERE person_id = ? AND event_id = ?', (person_id, event_id))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, 'Person-event link not found')
    return {'status': 'removed'}
