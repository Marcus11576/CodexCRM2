"""
M365 integration router. Handles OAuth device-code flow and triggers sync operations.

The implementation is intentionally minimal; the device code flow is performed against
Microsoft's endpoints using httpx. Tokens are stored in the M365_CREDENTIALS table.
Per-contact sync metadata lives in M365_ACCOUNT and is updated by the background worker.
"""
import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import settings
from backend.database import run_read, run_write
from backend.services.backup_service import get_latest_backup_metadata
from backend.services import m365_worker

router = APIRouter(tags=["m365"])

# Temporary in-memory state for ongoing device flow
_device_flow: Optional[dict] = None
_flow_lock = asyncio.Lock()


def _m365_scopes() -> list[str]:
    return [scope.strip() for scope in str(settings.M365_SCOPES or "").split() if scope.strip()]


def _m365_scope_string() -> str:
    return " ".join(_m365_scopes())


def _decode_access_token_claims(access_token: str) -> dict:
    if not access_token or access_token.count(".") < 2:
        return {}
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def _feature_flags(claims: Optional[dict] = None) -> dict:
    claims = claims or {}
    scopes = set(str(claims.get("scp") or "").split())
    return {
        "mail_read": bool({"Mail.Read", "Mail.ReadWrite"} & scopes),
        "mail_send": "Mail.Send" in scopes,
        "calendar_read": bool({"Calendars.Read", "Calendars.ReadWrite"} & scopes),
        "calendar_write": "Calendars.ReadWrite" in scopes,
    }


async def _graph_json(access_token: str, path: str, params: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://graph.microsoft.com/v1.0{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            timeout=10,
        )
    resp.raise_for_status()
    return resp.json()


async def _connected_account_summary(access_token: str) -> dict:
    profile = await _graph_json(access_token, "/me", params={"$select": "id,displayName,userPrincipalName,mail"})
    claims = _decode_access_token_claims(access_token)
    return {
        "display_name": profile.get("displayName") or claims.get("name"),
        "email": profile.get("mail") or profile.get("userPrincipalName") or claims.get("upn"),
        "user_principal_name": profile.get("userPrincipalName") or claims.get("upn"),
        "tenant_id": claims.get("tid"),
    }


async def _authenticated_status_payload(access_token: str) -> dict:
    claims = _decode_access_token_claims(access_token)
    payload = {
        "status": "authenticated",
        "scopes": _m365_scopes(),
        "granted_scopes": str(claims.get("scp") or "").split(),
        "features": _feature_flags(claims),
        "auth_mode": "device_code",
        "backup": get_latest_backup_metadata(),
    }
    try:
        payload["account"] = await _connected_account_summary(access_token)
    except Exception:
        payload["account"] = {
            "display_name": claims.get("name"),
            "email": claims.get("upn"),
            "user_principal_name": claims.get("upn"),
            "tenant_id": claims.get("tid"),
        }
    return payload


async def _token_is_valid(access_token: str) -> bool:
    if not access_token:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
        return resp.status_code == 200
    except Exception:
        return False


async def _store_tokens(access_token: str, refresh_token: str, expires_in: int):
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    async def op(db):
        await db.execute(
            "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at)"
            " VALUES (1,?,?,?,datetime('now'))",
            (access_token, refresh_token, expires_at),
        )

    await run_write(op)


async def _clear_credentials():
    async def op(db):
        await db.execute("DELETE FROM M365_CREDENTIALS WHERE id=1")

    await run_write(op)


async def _refresh_tokens(refresh_token: str):
    """Use the refresh token to obtain a new access token and store it."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.M365_CLIENT_ID,
                "refresh_token": refresh_token,
                "scope": _m365_scope_string(),
            },
            timeout=10,
        )
    resp.raise_for_status()
    tok = resp.json()
    await _store_tokens(tok.get("access_token"), tok.get("refresh_token"), tok.get("expires_in", 0))


async def _read_credentials_row():
    async def op(db):
        cur = await db.execute("SELECT access_token, refresh_token, token_expires_at FROM M365_CREDENTIALS WHERE id=1")
        return await cur.fetchone()

    creds = await run_read(op)
    return dict(creds) if creds else None


async def _update_account_sync_state(
    person_id: str,
    *,
    sync_status: str,
    sync_error: Optional[str] = None,
    last_synced_count: Optional[int] = None,
    update_last_sync: bool = False,
):
    now = datetime.now(timezone.utc).isoformat()

    async def op(db):
        await db.execute(
            "INSERT OR IGNORE INTO M365_ACCOUNT (person_id, created_at) VALUES (?, datetime('now'))",
            (person_id,),
        )
        await db.execute(
            """
            UPDATE M365_ACCOUNT
            SET sync_status = ?, sync_error = ?, last_sync_at = CASE WHEN ? THEN ? ELSE last_sync_at END,
                last_synced_count = COALESCE(?, last_synced_count)
            WHERE person_id = ?
            """,
            (sync_status, sync_error, 1 if update_last_sync else 0, now, last_synced_count, person_id),
        )
        if update_last_sync:
            await db.execute("UPDATE PERSON SET m365_last_sync = ? WHERE person_id = ?", (now, person_id))

    await run_write(op)


class SendEmailRequest(BaseModel):
    subject: str
    body: str


async def _get_credentials():
    """Fetch credentials and refresh them if expired."""
    creds = await _read_credentials_row()
    if creds and creds.get("access_token"):
        exp = creds.get("token_expires_at")
        if exp and exp <= datetime.now(timezone.utc).isoformat() and creds.get("refresh_token"):
            try:
                await _refresh_tokens(creds.get("refresh_token"))
                creds = await _read_credentials_row()
            except Exception:
                pass
    return creds


async def _ensure_valid_credentials():
    """Return working credentials, refreshing or clearing stale ones as needed."""
    creds = await _get_credentials()
    if not creds or not creds.get("access_token"):
        return None
    if await _token_is_valid(creds["access_token"]):
        return creds
    refresh_token = creds.get("refresh_token")
    if refresh_token:
        try:
            await _refresh_tokens(refresh_token)
            creds = await _read_credentials_row()
            if creds and creds.get("access_token") and await _token_is_valid(creds["access_token"]):
                return creds
        except Exception:
            pass
    await _clear_credentials()
    return None


@router.get("/api/m365/auth/status")
async def auth_status():
    if not settings.M365_ENABLED:
        return {
            "status": "disabled",
            "scopes": _m365_scopes(),
            "features": _feature_flags(),
            "backup": get_latest_backup_metadata(),
        }

    creds = await _ensure_valid_credentials()
    if creds and creds.get("access_token"):
        return await _authenticated_status_payload(creds["access_token"])

    async with _flow_lock:
        global _device_flow
        if _device_flow:
            if _device_flow.get("expires_at") and _device_flow["expires_at"] < datetime.now(timezone.utc).isoformat():
                _device_flow = None
                return {"status": "error", "message": "device code expired", "backup": get_latest_backup_metadata()}
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "client_id": settings.M365_CLIENT_ID,
                        "device_code": _device_flow["device_code"],
                    },
                    timeout=10,
                )
            if resp.status_code == 200:
                tok = resp.json()
                await _store_tokens(tok.get("access_token"), tok.get("refresh_token"), tok.get("expires_in", 0))
                _device_flow = None
                return await _authenticated_status_payload(tok.get("access_token"))
            data = resp.json()
            if data.get("error") == "authorization_pending":
                return {
                    "status": "pending",
                    "scopes": _m365_scopes(),
                    "features": _feature_flags(),
                    "backup": get_latest_backup_metadata(),
                }
            _device_flow = None
            return {
                "status": "error",
                "message": data.get("error_description") or data.get("error"),
                "backup": get_latest_backup_metadata(),
            }
    return {
        "status": "unauthenticated",
        "scopes": _m365_scopes(),
        "features": _feature_flags(),
        "backup": get_latest_backup_metadata(),
    }


@router.post("/api/m365/auth/start")
async def auth_start():
    if not settings.M365_ENABLED:
        return {"status": "disabled", "scopes": _m365_scopes(), "features": _feature_flags()}

    creds = await _ensure_valid_credentials()
    if creds and creds.get("access_token"):
        return await _authenticated_status_payload(creds["access_token"])

    async with _flow_lock:
        global _device_flow
        if _device_flow:
            return {"status": "pending", **_device_flow}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/devicecode",
                data={
                    "client_id": settings.M365_CLIENT_ID,
                    "scope": _m365_scope_string(),
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        _device_flow = {
            "device_code": data.get("device_code"),
            "user_code": data.get("user_code"),
            "verification_uri": data.get("verification_uri"),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 0))).isoformat(),
            "interval": data.get("interval", 5),
            "scopes": _m365_scopes(),
            "instructions": "Open the Microsoft device login page, enter the code, and approve mail/calendar access.",
        }
        return {"status": "pending", **_device_flow}


@router.post("/api/m365/auth/reset")
async def auth_reset():
    if not settings.M365_ENABLED:
        return {"status": "disabled"}

    global _device_flow
    _device_flow = None
    await _clear_credentials()
    return {"status": "cleared"}


@router.get("/api/m365/emails/{person_id}")
async def fetch_emails(person_id: str):
    if not settings.M365_ENABLED:
        return {"status": "error", "message": "M365 disabled"}

    creds = await _ensure_valid_credentials()
    if not creds or not creds.get("access_token"):
        return {"status": "error", "message": "authentication required"}

    await _update_account_sync_state(person_id, sync_status="working", sync_error=None)
    try:
        emails, new_synced = await m365_worker.sync_account_with_preview(person_id, creds["access_token"])
        await _update_account_sync_state(
            person_id,
            sync_status="idle",
            sync_error=None,
            last_synced_count=new_synced,
            update_last_sync=True,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            await _clear_credentials()
            await _update_account_sync_state(person_id, sync_status="error", sync_error="Authentication expired. Please reconnect Microsoft 365.")
            return {"status": "error", "message": "authentication required"}
        await _update_account_sync_state(person_id, sync_status="error", sync_error=str(exc)[:1000])
        return {"status": "error", "message": str(exc)}
    except ValueError as exc:
        await _update_account_sync_state(person_id, sync_status="error", sync_error=str(exc)[:1000])
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        await _update_account_sync_state(person_id, sync_status="error", sync_error=str(exc)[:1000])
        return {"status": "error", "message": str(exc)}

    return {"status": "success", "emails": emails, "new_synced": new_synced}


@router.get("/api/m365/account/{person_id}")
async def account_status(person_id: str):
    """Return current sync metadata for a contact."""
    if not settings.M365_ENABLED:
        return {"status": "disabled"}

    async def op(db):
        cur = await db.execute(
            "SELECT person_id, last_sync_at, sync_status, sync_error, last_synced_count FROM M365_ACCOUNT WHERE person_id=?",
            (person_id,),
        )
        return await cur.fetchone()

    row = await run_read(op)
    if not row:
        return {"status": "not_found"}
    return {"status": "success", "data": dict(row)}


@router.get("/api/m365/overview")
async def m365_overview():
    if not settings.M365_ENABLED:
        return {"status": "disabled", "scopes": _m365_scopes(), "features": _feature_flags()}

    creds = await _ensure_valid_credentials()
    if not creds or not creds.get("access_token"):
        return {"status": "unauthenticated", "scopes": _m365_scopes(), "features": _feature_flags()}

    return await _authenticated_status_payload(creds["access_token"])


@router.get("/api/m365/calendar/events")
async def calendar_events(days: int = 14, limit: int = 25):
    if not settings.M365_ENABLED:
        return {"status": "error", "message": "M365 disabled"}

    creds = await _ensure_valid_credentials()
    if not creds or not creds.get("access_token"):
        return {"status": "error", "message": "authentication required"}

    try:
        events = await m365_worker.fetch_calendar_events(creds["access_token"], days=days, limit=limit)
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            await _clear_credentials()
            return {"status": "error", "message": "authentication required"}
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    return {"status": "success", "events": events, "days": days}


@router.post("/api/m365/sync/full")
async def full_sync(days: int = 90, limit: int = 200):
    if not settings.M365_ENABLED:
        return {"status": "error", "message": "M365 disabled"}

    creds = await _ensure_valid_credentials()
    if not creds or not creds.get("access_token"):
        return {"status": "error", "message": "authentication required"}

    try:
        summary = await m365_worker.sync_full_mailbox(
            creds["access_token"],
            message_days=days,
            message_limit=limit,
            calendar_days=max(30, min(days, 90)),
            calendar_limit=min(limit, 100),
            calendar_past_days=30,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            await _clear_credentials()
            return {"status": "error", "message": "authentication required"}
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    return {"status": "success", "summary": summary, "days": days, "limit": limit}


@router.post("/api/m365/emails/{person_id}/send")
async def send_email(person_id: str, req: SendEmailRequest):
    if not settings.M365_ENABLED:
        return {"status": "error", "message": "M365 disabled"}

    subject = (req.subject or "").strip()
    body = (req.body or "").strip()
    if not subject:
        return {"status": "error", "message": "Please enter a subject."}
    if not body:
        return {"status": "error", "message": "Please enter a message."}

    creds = await _ensure_valid_credentials()
    if not creds or not creds.get("access_token"):
        return {"status": "error", "message": "authentication required"}

    try:
        result = await m365_worker.send_email(person_id, creds["access_token"], subject, body)
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            await _clear_credentials()
            return {"status": "error", "message": "authentication required"}
        return {"status": "error", "message": str(exc)}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    return {"status": "success", **result}
