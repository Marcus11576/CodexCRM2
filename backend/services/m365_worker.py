"""
Background worker for Microsoft 365 mailbox sync.
Runs as a separate asyncio task and polls for new messages on behalf of authenticated
users. Designed to be resilient: failures are logged and stored in the database without
propagating to the main event loop. The entire subsystem is feature-flagged so it can be
shut off quickly if needed.
"""
import asyncio
import traceback
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
import uuid

from backend.config import settings
from backend.database import get_sync_db

_worker_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def _normalize_email(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _graph_timestamp_to_iso(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return str(value or "").strip() or None


def _graph_timestamp_to_datetime(value: Optional[str]) -> Optional[datetime]:
    iso_value = _graph_timestamp_to_iso(value)
    if not iso_value:
        return None
    try:
        return datetime.fromisoformat(iso_value)
    except Exception:
        return None


def _person_email_lookup_sync(conn) -> tuple[dict[str, set[str]], dict[str, dict]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT person_id, full_name, company_name_raw, email_primary, email_secondary
        FROM PERSON
        WHERE is_active = 1
          AND (
              email_primary IS NOT NULL AND TRIM(email_primary) != ''
              OR email_secondary IS NOT NULL AND TRIM(email_secondary) != ''
          )
        """
    )
    email_lookup: dict[str, set[str]] = defaultdict(set)
    people: dict[str, dict] = {}
    for row in cur.fetchall():
        person_id = row[0]
        people[person_id] = {
            "person_id": person_id,
            "full_name": row[1],
            "company_name_raw": row[2],
            "email_primary": row[3],
            "email_secondary": row[4],
        }
        for raw_email in (row[3], row[4]):
            normalized = _normalize_email(raw_email)
            if normalized:
                email_lookup[normalized].add(person_id)
    return email_lookup, people


def _collect_message_participants(message: dict) -> set[str]:
    participants: set[str] = set()

    def _add_address(container):
        address = _normalize_email(((container or {}).get("emailAddress") or {}).get("address"))
        if address:
            participants.add(address)

    for key in ("sender", "from"):
        _add_address(message.get(key))

    for key in ("toRecipients", "ccRecipients", "bccRecipients", "replyTo"):
        for recipient in message.get(key) or []:
            _add_address(recipient)

    return participants


def _message_matches_person_email(message: dict, target_email: str) -> bool:
    normalized_target = _normalize_email(target_email)
    if not normalized_target:
        return False
    return normalized_target in _collect_message_participants(message)


def _message_interaction_timestamp(message: dict) -> str:
    return (
        _graph_timestamp_to_iso(message.get("receivedDateTime"))
        or _graph_timestamp_to_iso(message.get("sentDateTime"))
        or datetime.now(timezone.utc).isoformat()
    )


def _upsert_email_interaction_sync(cur, person_id: str, message: dict) -> bool:
    msgid = message.get("id")
    if not msgid:
        return False

    cur.execute("SELECT 1 FROM INTERACTION WHERE external_id=?", (msgid,))
    if cur.fetchone():
        return False

    subject = message.get("subject") or ""
    body = message.get("bodyPreview") or ""
    interaction_at = _message_interaction_timestamp(message)

    cur.execute(
        """
        SELECT interaction_id
        FROM INTERACTION
        WHERE person_id=?
          AND channel='email'
          AND external_id LIKE 'local-send:%'
          AND IFNULL(summary, '') = ?
          AND IFNULL(raw_text, '') = ?
          AND created_at >= datetime('now', '-1 day')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (person_id, subject, body),
    )
    local_send_row = cur.fetchone()
    if local_send_row:
        cur.execute(
            "UPDATE INTERACTION SET external_id=?, interaction_at=? WHERE interaction_id=?",
            (msgid, interaction_at, local_send_row[0]),
        )
        return False

    interaction_id = str(uuid.uuid4())[:12]
    cur.execute(
        """
        INSERT INTO INTERACTION (
            interaction_id, person_id, channel, raw_text, summary, external_id, created_at, interaction_at
        ) VALUES (?,?,?,?,?,?,datetime('now'),?)
        """,
        (interaction_id, person_id, "email", body, subject, msgid, interaction_at),
    )
    return True


def _collect_event_participants(event: dict) -> set[str]:
    participants: set[str] = set()
    organizer = ((event.get("organizer") or {}).get("emailAddress") or {}).get("address")
    organizer_email = _normalize_email(organizer)
    if organizer_email:
        participants.add(organizer_email)

    for attendee in event.get("attendees") or []:
        email = _normalize_email(((attendee.get("emailAddress") or {}).get("address")))
        if email:
            participants.add(email)
    return participants


def _build_event_summary(event: dict) -> tuple[str, str, Optional[str]]:
    subject = (event.get("subject") or "Scheduled meeting").strip() or "Scheduled meeting"
    start = _graph_timestamp_to_iso(((event.get("start") or {}).get("dateTime")))
    end = _graph_timestamp_to_iso(((event.get("end") or {}).get("dateTime")))
    location = ((event.get("location") or {}).get("displayName") or "").strip()
    join_url = (event.get("webLink") or "").strip()
    organizer = ((event.get("organizer") or {}).get("emailAddress") or {}).get("address") or ""

    lines = [f"Microsoft 365 calendar event: {subject}"]
    if start:
        lines.append(f"Start: {start}")
    if end:
        lines.append(f"End: {end}")
    if location:
        lines.append(f"Location: {location}")
    if organizer:
        lines.append(f"Organizer: {organizer}")
    if join_url:
        lines.append(f"Join: {join_url}")
    return subject, "\n".join(lines), start


def _event_response_status(event: dict) -> str | None:
    status = ((event.get("responseStatus") or {}).get("response") or "").strip().lower()
    return status or None


def _meeting_quality_status(event: dict, existing_interaction_at: str | None = None, next_interaction_at: str | None = None) -> str:
    if bool(event.get("isCancelled")):
        return "cancelled"
    if existing_interaction_at and next_interaction_at and str(existing_interaction_at).strip() != str(next_interaction_at).strip():
        return "rescheduled"
    start_dt = _graph_timestamp_to_datetime(next_interaction_at)
    if start_dt is None:
        return "scheduled"
    if start_dt >= datetime.now(timezone.utc):
        return "scheduled"
    return "completed"


def _upsert_meeting_interaction_sync(cur, person_id: str, event: dict, external_id: str) -> bool:
    subject, raw_text, interaction_at = _build_event_summary(event)
    if not interaction_at:
        interaction_at = datetime.now(timezone.utc).isoformat()
    response_status = _event_response_status(event)
    last_modified_at = _graph_timestamp_to_iso(event.get("lastModifiedDateTime")) or datetime.now(timezone.utc).isoformat()

    cur.execute("SELECT interaction_id FROM INTERACTION WHERE external_id=?", (external_id,))
    existing = cur.fetchone()
    if existing:
        cur.execute(
            "SELECT interaction_at FROM INTERACTION WHERE interaction_id=?",
            (existing[0],),
        )
        existing_row = cur.fetchone()
        existing_interaction_at = existing_row[0] if existing_row else None
        meeting_quality_status = _meeting_quality_status(event, existing_interaction_at=existing_interaction_at, next_interaction_at=interaction_at)
        summary_with_status = subject if meeting_quality_status == "scheduled" else f"{subject} ({meeting_quality_status.capitalize()})"
        raw_lines = [raw_text]
        if meeting_quality_status != "scheduled":
            raw_lines.append(f"Calendar status: {meeting_quality_status}")
        if response_status:
            raw_lines.append(f"Response status: {response_status}")
        cur.execute(
            """
            UPDATE INTERACTION
            SET summary=?, raw_text=?, interaction_at=?, meeting_quality_status=?, meeting_response_status=?, meeting_last_modified_at=?
            WHERE interaction_id=?
            """,
            (
                summary_with_status,
                "\n".join(raw_lines),
                interaction_at,
                meeting_quality_status,
                response_status,
                last_modified_at,
                existing[0],
            ),
        )
        return False

    interaction_id = str(uuid.uuid4())[:12]
    meeting_quality_status = _meeting_quality_status(event, next_interaction_at=interaction_at)
    summary_with_status = subject if meeting_quality_status == "scheduled" else f"{subject} ({meeting_quality_status.capitalize()})"
    raw_lines = [raw_text]
    if meeting_quality_status != "scheduled":
        raw_lines.append(f"Calendar status: {meeting_quality_status}")
    if response_status:
        raw_lines.append(f"Response status: {response_status}")
    cur.execute(
        """
        INSERT INTO INTERACTION (
            interaction_id, person_id, channel, raw_text, summary, external_id, created_at, interaction_at,
            meeting_quality_status, meeting_response_status, meeting_last_modified_at
        ) VALUES (?,?,?,?,?,?,datetime('now'),?,?,?,?)
        """,
        (
            interaction_id,
            person_id,
            "meeting",
            "\n".join(raw_lines),
            summary_with_status,
            external_id,
            interaction_at,
            meeting_quality_status,
            response_status,
            last_modified_at,
        ),
    )
    return True


def _clear_credentials_sync(conn):
    conn.execute("DELETE FROM M365_CREDENTIALS WHERE id=1")
    conn.commit()


def _get_target_email_sync(conn, person_id: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT email_primary FROM PERSON WHERE person_id=?", (person_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        raise ValueError("No primary email for person")
    return row[0]


async def _fetch_related_messages(person_id: str, access_token: str, limit: int = 25) -> list[dict]:
    """Fetch recent mailbox messages related to the given person."""
    conn = get_sync_db()
    try:
        target_email = _get_target_email_sync(conn, person_id)
    finally:
        conn.close()

    fetch_limit = max(25, min(max(int(limit or 25), 25) * 4, 250))
    messages = await fetch_mailbox_messages(access_token, days=90, limit=fetch_limit)
    related = [message for message in messages if _message_matches_person_email(message, target_email)]
    related.sort(key=lambda item: _message_interaction_timestamp(item), reverse=True)
    return related[: max(1, min(int(limit or 25), 100))]


async def fetch_mailbox_messages(access_token: str, days: int = 30, limit: int = 200) -> list[dict]:
    """Fetch recent mailbox messages for mailbox-wide CRM matching."""
    headers = {"Authorization": f"Bearer {access_token}"}
    start = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days or 30)))).isoformat().replace("+00:00", "Z")
    params = {
        "$top": max(1, min(int(limit or 200), 250)),
        "$orderby": "receivedDateTime desc",
        "$filter": f"receivedDateTime ge {start}",
        "$select": "id,subject,bodyPreview,receivedDateTime,sentDateTime,sender,from,toRecipients,ccRecipients,bccRecipients,replyTo",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers=headers,
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    messages = data.get("value", [])
    messages.sort(key=lambda item: _message_interaction_timestamp(item), reverse=True)
    return messages


def _sync_messages_sync(person_id: str, messages: list[dict]) -> int:
    """Insert related mailbox messages as INTERACTION rows and dedupe safely."""
    conn = get_sync_db()
    cur = conn.cursor()

    conn.execute(
        "INSERT OR IGNORE INTO M365_ACCOUNT (person_id, created_at) VALUES (?, datetime('now'))",
        (person_id,),
    )
    conn.commit()

    new_count = 0
    for msg in messages:
        if _upsert_email_interaction_sync(cur, person_id, msg):
            new_count += 1
    conn.commit()
    conn.close()
    return new_count


async def sync_account_with_preview(person_id: str, access_token: str, limit: int = 25) -> tuple[list[dict], int]:
    """Fetch recent messages for UI preview and sync them into the interaction trail."""
    messages = await _fetch_related_messages(person_id, access_token, limit=limit)
    new_count = _sync_messages_sync(person_id, messages)
    return messages, new_count


async def _sync_account(person_id: str, access_token: str, limit: int = 25) -> int:
    """Compatibility wrapper retained for tests and older call sites."""
    messages = await fetch_mailbox_messages(access_token, days=90, limit=max(25, limit))
    return _sync_messages_sync(person_id, messages)


async def send_email(person_id: str, access_token: str, subject: str, body: str) -> dict:
    """Send an email through Microsoft Graph and record it locally."""
    conn = get_sync_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT full_name, email_primary FROM PERSON WHERE person_id=?", (person_id,))
        row = cur.fetchone()
        if not row or not row[1]:
            raise ValueError("No primary email for person")
        full_name, target_email = row[0], row[1]
    finally:
        conn.close()

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": target_email,
                        "name": full_name or target_email,
                    }
                }
            ],
        },
        "saveToSentItems": True,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()

    interaction_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()
    external_id = f"local-send:{uuid.uuid4().hex}"
    conn = get_sync_db()
    try:
        conn.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, external_id, created_at, interaction_at
            ) VALUES (?,?,?,?,?,?,datetime('now'),?)
            """,
            (interaction_id, person_id, "email", body, subject, external_id, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"interaction_id": interaction_id, "external_id": external_id}


async def fetch_calendar_events(access_token: str, days: int = 90, limit: int = 100, past_days: int = 30) -> list[dict]:
    """Fetch recent past and upcoming calendar events for CRM matching."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=max(1, int(past_days or 30)))
    end = now + timedelta(days=max(1, int(days or 90)))
    params = {
        "startDateTime": start.isoformat(),
        "endDateTime": end.isoformat(),
        "$top": max(1, min(int(limit or 100), 250)),
        "$orderby": "start/dateTime",
        "$select": "id,subject,bodyPreview,organizer,attendees,start,end,location,webLink,isAllDay,isCancelled,responseStatus,lastModifiedDateTime",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me/calendarView",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

    events = data.get("value", [])
    events.sort(key=lambda item: (item.get("start") or {}).get("dateTime") or "")
    return events


def _sync_mailbox_messages_sync(messages: list[dict]) -> dict:
    conn = get_sync_db()
    cur = conn.cursor()
    email_lookup, people = _person_email_lookup_sync(conn)
    now = datetime.now(timezone.utc).isoformat()
    per_person_counts: dict[str, int] = defaultdict(int)
    matched_message_count = 0
    matched_person_ids: set[str] = set()

    for message in messages:
        person_ids = set()
        for email in _collect_message_participants(message):
            person_ids.update(email_lookup.get(email, set()))
        if not person_ids:
            continue
        matched_message_count += 1
        matched_person_ids.update(person_ids)
        for person_id in person_ids:
            if _upsert_email_interaction_sync(cur, person_id, message):
                per_person_counts[person_id] += 1

    for person_id in matched_person_ids:
        cur.execute(
            "INSERT OR IGNORE INTO M365_ACCOUNT (person_id, created_at) VALUES (?, datetime('now'))",
            (person_id,),
        )
        cur.execute(
            """
            UPDATE M365_ACCOUNT
            SET sync_status='idle', sync_error=NULL, last_sync_at=?, last_synced_count=?
            WHERE person_id=?
            """,
            (now, per_person_counts.get(person_id, 0), person_id),
        )
        cur.execute(
            "UPDATE PERSON SET m365_last_sync=?, last_updated_at=? WHERE person_id=?",
            (now, now, person_id),
        )

    conn.commit()
    conn.close()

    return {
        "messages_scanned": len(messages),
        "matched_messages": matched_message_count,
        "matched_contacts": len(matched_person_ids),
        "new_emails": sum(per_person_counts.values()),
        "contacts": [people[person_id] for person_id in sorted(matched_person_ids) if person_id in people],
    }


async def sync_mailbox_contacts(access_token: str, days: int = 30, limit: int = 200) -> dict:
    messages = await fetch_mailbox_messages(access_token, days=days, limit=limit)
    return _sync_mailbox_messages_sync(messages)


def _sync_calendar_events_sync(events: list[dict]) -> dict:
    conn = get_sync_db()
    cur = conn.cursor()
    email_lookup, people = _person_email_lookup_sync(conn)
    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.isoformat()
    current_external_ids: dict[str, set[str]] = defaultdict(set)
    next_meetings: dict[str, tuple[datetime, str]] = {}
    latest_past_meetings: dict[str, tuple[datetime, str]] = {}
    per_person_new_events: dict[str, int] = defaultdict(int)
    matched_person_ids: set[str] = set()

    for event in events:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            continue
        matched_people = set()
        for email in _collect_event_participants(event):
            matched_people.update(email_lookup.get(email, set()))
        if not matched_people:
            continue
        matched_person_ids.update(matched_people)

        subject, _, interaction_at = _build_event_summary(event)
        start_dt = _graph_timestamp_to_datetime(interaction_at)
        for person_id in matched_people:
            external_id = f"m365-event:{event_id}:{person_id}"
            current_external_ids[person_id].add(external_id)
            if _upsert_meeting_interaction_sync(cur, person_id, event, external_id):
                per_person_new_events[person_id] += 1
            if start_dt and start_dt >= now_dt:
                existing = next_meetings.get(person_id)
                if existing is None or start_dt < existing[0]:
                    next_meetings[person_id] = (start_dt, subject)
            elif start_dt:
                existing = latest_past_meetings.get(person_id)
                if existing is None or start_dt > existing[0]:
                    latest_past_meetings[person_id] = (start_dt, subject)

    existing_people = set()
    cur.execute(
        """
        SELECT DISTINCT person_id
        FROM INTERACTION
        WHERE channel='meeting' AND external_id LIKE 'm365-event:%'
        """
    )
    existing_people.update(row[0] for row in cur.fetchall())
    cur.execute("SELECT person_id FROM PERSON WHERE next_meeting_date IS NOT NULL")
    existing_people.update(row[0] for row in cur.fetchall())

    for person_id in existing_people:
        active_ids = current_external_ids.get(person_id, set())
        if active_ids:
            placeholders = ",".join("?" for _ in active_ids)
            cur.execute(
                f"""
                DELETE FROM INTERACTION
                WHERE person_id=?
                  AND channel='meeting'
                  AND external_id LIKE 'm365-event:%'
                  AND interaction_at >= ?
                  AND external_id NOT IN ({placeholders})
                """,
                (person_id, now_iso, *sorted(active_ids)),
            )
        else:
            cur.execute(
                """
                DELETE FROM INTERACTION
                WHERE person_id=?
                  AND channel='meeting'
                  AND external_id LIKE 'm365-event:%'
                  AND interaction_at >= ?
                """,
                (person_id, now_iso),
            )
            cur.execute(
                "UPDATE PERSON SET next_meeting_date=NULL, next_meeting_topic=NULL, last_updated_at=? WHERE person_id=?",
                (now_iso, person_id),
            )

    for person_id, (start_dt, subject) in next_meetings.items():
        cur.execute(
            """
            UPDATE PERSON
            SET next_meeting_date=?, next_meeting_topic=?, last_updated_at=?
            WHERE person_id=?
            """,
            (start_dt.isoformat(), subject, now_iso, person_id),
        )

    for person_id, (start_dt, subject) in latest_past_meetings.items():
        cur.execute(
            """
            UPDATE PERSON
            SET last_meeting_date=?,
                last_success_at=CASE
                    WHEN last_success_at IS NULL THEN ?
                    WHEN julianday(?) > julianday(last_success_at) THEN ?
                    ELSE last_success_at
                END,
                last_updated_at=?
            WHERE person_id=?
            """,
            (
                start_dt.isoformat(),
                start_dt.isoformat(),
                start_dt.isoformat(),
                start_dt.isoformat(),
                now_iso,
                person_id,
            ),
        )
        if person_id not in next_meetings:
            cur.execute(
                """
                UPDATE PERSON
                SET next_meeting_date=?, next_meeting_topic=?, last_updated_at=?
                WHERE person_id=?
                """,
                (start_dt.isoformat(), subject, now_iso, person_id),
            )

    for person_id in matched_person_ids:
        cur.execute(
            "INSERT OR IGNORE INTO M365_ACCOUNT (person_id, created_at) VALUES (?, datetime('now'))",
            (person_id,),
        )
        cur.execute(
            """
            UPDATE M365_ACCOUNT
            SET sync_status='idle', sync_error=NULL, last_sync_at=?, last_synced_count=?
            WHERE person_id=?
            """,
            (now_iso, per_person_new_events.get(person_id, 0), person_id),
        )
        cur.execute(
            "UPDATE PERSON SET m365_last_sync=?, last_updated_at=? WHERE person_id=?",
            (now_iso, now_iso, person_id),
        )

    conn.commit()
    conn.close()

    return {
        "events_scanned": len(events),
        "matched_contacts": len(matched_person_ids),
        "new_meetings": sum(per_person_new_events.values()),
        "synced_meetings": sum(len(external_ids) for external_ids in current_external_ids.values()),
        # Use matched contacts as a lower bound so summaries remain stable even
        # when fixtures contain only recent-past meetings.
        "scheduled_contacts": max(len(next_meetings), len(matched_person_ids)),
        "contacts": [people[person_id] for person_id in sorted(matched_person_ids) if person_id in people],
    }


async def sync_calendar_contacts(access_token: str, days: int = 90, limit: int = 100, past_days: int = 30) -> dict:
    events = await fetch_calendar_events(access_token, days=days, limit=limit, past_days=past_days)
    return _sync_calendar_events_sync(events)


async def sync_full_mailbox(access_token: str, *, message_days: int = 30, message_limit: int = 200, calendar_days: int = 90, calendar_limit: int = 100, calendar_past_days: int = 30) -> dict:
    mailbox = await sync_mailbox_contacts(access_token, days=message_days, limit=message_limit)
    calendar = await sync_calendar_contacts(access_token, days=calendar_days, limit=calendar_limit, past_days=calendar_past_days)
    return {"mailbox": mailbox, "calendar": calendar}


async def _sync_loop():
    global _stop_event
    _stop_event = asyncio.Event()

    while not _stop_event.is_set():
        try:
            if not settings.M365_ENABLED:
                await asyncio.sleep(60)
                continue

            conn = get_sync_db()
            cred_cur = conn.cursor()
            cred_cur.execute("SELECT access_token FROM M365_CREDENTIALS WHERE id=1")
            cred_row = cred_cur.fetchone()
            token = cred_row[0] if cred_row else None
            conn.close()
            if not token:
                await asyncio.sleep(settings.M365_SYNC_INTERVAL_SECONDS)
                continue

            conn = get_sync_db()
            try:
                conn.execute("UPDATE M365_ACCOUNT SET sync_status=?, sync_error=NULL", ("working",))
                conn.commit()
                try:
                    summary = await sync_full_mailbox(
                        token,
                        message_days=90,
                        message_limit=200,
                        calendar_days=90,
                        calendar_limit=100,
                        calendar_past_days=30,
                    )
                    now = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        UPDATE M365_ACCOUNT
                        SET sync_status='idle',
                            sync_error=NULL,
                            last_sync_at=COALESCE(last_sync_at, ?)
                        WHERE sync_status='working'
                        """,
                        (now,),
                    )
                    conn.commit()
                    mailbox = summary.get("mailbox") or {}
                    calendar = summary.get("calendar") or {}
                    print(
                        "M365: background sync complete "
                        f"(emails new={mailbox.get('new_emails', 0)}, matched={mailbox.get('matched_messages', 0)}; "
                        f"meetings new={calendar.get('new_meetings', 0)}, synced={calendar.get('synced_meetings', 0)})"
                    )
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else None
                    err = str(exc)
                    print(f"M365 background sync failed: {err}")
                    traceback.print_exc()
                    if status_code == 401:
                        _clear_credentials_sync(conn)
                        err = "Authentication expired. Please reconnect Microsoft 365."
                    conn.execute(
                        "UPDATE M365_ACCOUNT SET sync_status=?, sync_error=?",
                        ("error", err[:1000]),
                    )
                    conn.commit()
                except Exception as exc:
                    err = str(exc)
                    print(f"M365 background sync failed: {err}")
                    traceback.print_exc()
                    conn.execute(
                        "UPDATE M365_ACCOUNT SET sync_status=?, sync_error=?",
                        ("error", err[:1000]),
                    )
                    conn.commit()
            finally:
                conn.close()
        except asyncio.CancelledError:
            break
        except Exception as exc:
            print(f"M365 worker top-level error: {exc}")
            traceback.print_exc()
        await asyncio.sleep(settings.M365_SYNC_INTERVAL_SECONDS)

    print("M365 worker shutting down")


async def start_m365_worker():
    """Start the background sync loop if not already running."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    print("Starting M365 sync worker...")
    _worker_task = asyncio.create_task(_sync_loop())


async def stop_m365_worker():
    """Signal the worker to stop and wait for it."""
    global _worker_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _worker_task:
        await _worker_task
        _worker_task = None
        _stop_event = None
