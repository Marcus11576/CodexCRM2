"""
Background worker for Microsoft 365 mailbox sync.
Runs as a separate asyncio task and polls for new messages on behalf of authenticated
users. Designed to be resilient: failures are logged and stored in the database without
propagating to the main event loop. The entire subsystem is feature-flagged so it can be
shut off quickly if needed.
"""
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Optional

from backend.config import settings
from backend.database import get_sync_db

_worker_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


import uuid
import httpx


async def _sync_account(person_id: str, access_token: str):
    """Fetch new messages related to the given person and insert as INTERACTION rows.

    Uses the person's primary email address to query Microsoft Graph and
    deduplicates based on message id (stored in INTERACTION.external_id).
    Returns the number of new messages synced.
    """
    conn = get_sync_db()
    cur = conn.cursor()

    # ensure metadata row exists
    conn.execute(
        "INSERT OR IGNORE INTO M365_ACCOUNT (person_id, created_at) VALUES (?, datetime('now'))",
        (person_id,)
    )
    conn.commit()

    # look up primary email
    cur.execute("SELECT email_primary FROM PERSON WHERE person_id=?", (person_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        raise ValueError("No primary email for person")
    target_email = row[0]

    # query Graph for messages sent to/from this address
    url = "https://graph.microsoft.com/v1.0/me/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    filt = (
        f"from/emailAddress/address eq '{target_email}'"
        f" or toRecipients/any(r:r/emailAddress/address eq '{target_email}')"
    )
    params = {"$filter": filt, "$select": "id,subject,bodyPreview,receivedDateTime"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

    new_count = 0
    for msg in data.get("value", []):
        msgid = msg.get("id")
        if not msgid:
            continue
        # deduplicate
        cur.execute("SELECT 1 FROM INTERACTION WHERE external_id=?", (msgid,))
        if cur.fetchone():
            continue
        interaction_id = str(uuid.uuid4())[:12]
        received = msg.get("receivedDateTime")
        subject = msg.get("subject") or ""
        body = msg.get("bodyPreview") or ""
        cur.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, external_id, created_at, interaction_at) VALUES (?,?,?,?,?,?,datetime('now'),?)",
            (interaction_id, person_id, "email", body, subject, msgid, received),
        )
        new_count += 1
    conn.commit()
    return new_count


async def _sync_loop():
    global _stop_event
    _stop_event = asyncio.Event()

    while not _stop_event.is_set():
        try:
            if not settings.M365_ENABLED:
                # if disabled, just sleep and loop
                await asyncio.sleep(60)
                continue

            conn = get_sync_db()
            # fetch one global token from the credentials table
            cred_cur = conn.cursor()
            cred_cur.execute("SELECT access_token FROM M365_CREDENTIALS WHERE id=1")
            cred_row = cred_cur.fetchone()
            token = cred_row[0] if cred_row else None
            if not token:
                # nothing to sync until authentication completes
                await asyncio.sleep(settings.M365_SYNC_INTERVAL_SECONDS)
                continue

            cur = conn.cursor()
            # pick all assigned accounts; token is shared
            cur.execute("SELECT person_id FROM M365_ACCOUNT")
            rows = cur.fetchall()
            for row in rows:
                person_id = row[0]
                # mark working status
                conn.execute(
                    "UPDATE M365_ACCOUNT SET sync_status=?, sync_error=NULL WHERE person_id=?",
                    ("working", person_id),
                )
                try:
                    new_count = await _sync_account(person_id, token)
                    now = datetime.utcnow().isoformat()
                    conn.execute(
                        "UPDATE M365_ACCOUNT SET sync_status=?, last_sync_at=?, sync_error=?, last_synced_count=? WHERE person_id=?",
                        ("idle", now, None, new_count, person_id),
                    )
                    # also update PERSON for quick lookup
                    conn.execute(
                        "UPDATE PERSON SET m365_last_sync=? WHERE person_id=?",
                        (now, person_id),
                    )
                    if new_count:
                        print(f"M365: synced {new_count} new messages for {person_id}")
                except Exception as e:
                    err = str(e)
                    print(f"M365 sync failed for {person_id}: {err}")
                    traceback.print_exc()
                    conn.execute(
                        "UPDATE M365_ACCOUNT SET sync_status=?, sync_error=? WHERE person_id=?",
                        ("error", err[:1000], person_id),
                    )
            conn.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"M365 worker top-level error: {e}")
            traceback.print_exc()
        # scheduling delay
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
