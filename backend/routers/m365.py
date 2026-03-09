"""
M365 integration router. Handles OAuth device-code flow and triggers sync operations.

The implementation is intentionally minimal; the device code flow is performed against
Microsoft's endpoints using httpx. Tokens are stored in the M365_CREDENTIALS table.
Per-contact sync metadata lives in M365_ACCOUNT and is updated by the background worker.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status

from backend.config import settings
from backend.database import run_read, run_write
from backend.services import m365_worker

router = APIRouter(tags=["m365"])

# Temporary in‑memory state for ongoing device flow
_device_flow: Optional[dict] = None
_flow_lock = asyncio.Lock()


async def _store_tokens(access_token: str, refresh_token: str, expires_in: int):
    expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)).isoformat()

    async def op(db):
        # upsert into singleton row id = 1
        await db.execute(
            "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at)"
            " VALUES (1,?,?,?,datetime('now'))",
            (access_token, refresh_token, expires_at),
        )
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
                "scope": "https://graph.microsoft.com/.default offline_access openid",
            },
            timeout=10,
        )
    resp.raise_for_status()
    tok = resp.json()
    await _store_tokens(tok.get("access_token"), tok.get("refresh_token"), tok.get("expires_in", 0))

async def _get_credentials():
    """Fetch credentials and refresh them if expired."""
    async def op(db):
        cur = await db.execute("SELECT access_token, refresh_token, token_expires_at FROM M365_CREDENTIALS WHERE id=1")
        return await cur.fetchone()
    creds = await run_read(op)
    if creds:
        creds = dict(creds)
    if creds and creds.get("access_token"):
        exp = creds.get("token_expires_at")
        if exp and exp <= datetime.utcnow().isoformat():
            # expired, attempt refresh
            if creds.get("refresh_token"):
                try:
                    await _refresh_tokens(creds.get("refresh_token"))
                    # re-read updated creds
                    creds = await run_read(op)
                    if creds:
                        creds = dict(creds)
                except Exception:
                    # refresh failed; fall through and return stale creds
                    pass
    return creds


@router.get("/api/m365/auth/status")
async def auth_status():
    if not settings.M365_ENABLED:
        return {"status": "disabled"}

    creds = await _get_credentials()
    if creds and creds["access_token"]:
        # simple expiration check
        exp = creds.get("token_expires_at")
        if exp and exp > datetime.utcnow().isoformat():
            return {"status": "authenticated"}
        # attempt refresh? omitted for brevity
        return {"status": "authenticated", "note": "token may be expired"}
    # if we have an in-progress device flow, attempt to exchange token
    async with _flow_lock:
        global _device_flow
        if _device_flow:
            # if expired, clear and return error
            if _device_flow.get("expires_at") and _device_flow["expires_at"] < datetime.utcnow().isoformat():
                _device_flow = None
                return {"status": "error", "message": "device code expired"}
            # try token request
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
                await _store_tokens(tok.get("access_token"), tok.get("refresh_token"), tok.get("expires_in",0))
                _device_flow = None
                return {"status": "authenticated"}
            else:
                # still pending or error
                data = resp.json()
                if data.get("error") == "authorization_pending":
                    return {"status": "pending"}
                else:
                    _device_flow = None
                    return {"status": "error", "message": data.get("error_description") or data.get("error")}
    return {"status": "unauthenticated"}


@router.post("/api/m365/auth/start")
async def auth_start():
    if not settings.M365_ENABLED:
        return {"status": "disabled"}

    # start device code flow
    async with _flow_lock:
        global _device_flow
        if _device_flow:
            # already in progress
            return {"status": "pending", **_device_flow}

        # fetch device code
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/devicecode",
                data={
                    "client_id": settings.M365_CLIENT_ID,
                    "scope": "https://graph.microsoft.com/.default offline_access openid",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        # store minimal flow state
        _device_flow = {
            "device_code": data.get("device_code"),
            "user_code": data.get("user_code"),
            "verification_uri": data.get("verification_uri"),
            "expires_at": (datetime.utcnow() + timedelta(seconds=data.get("expires_in", 0))).isoformat(),
            "interval": data.get("interval", 5),
        }
        return {"status": "pending", **_device_flow}


@router.get("/api/m365/emails/{person_id}")
async def fetch_emails(person_id: str):
    if not settings.M365_ENABLED:
        return {"status": "error", "message": "M365 disabled"}

    creds = await _get_credentials()
    if not creds or not creds.get("access_token"):
        return {"status": "error", "message": "authentication required"}

    # call sync logic (worker helper)
    try:
        new_synced = await m365_worker._sync_account(person_id, creds["access_token"])
    except Exception as e:
        return {"status": "error", "message": str(e)}

    # for now we don't return actual email objects, just the new count
    return {"status": "success", "emails": [], "new_synced": new_synced}


@router.get("/api/m365/account/{person_id}")
async def account_status(person_id: str):
    """Return current sync metadata for a contact."""
    if not settings.M365_ENABLED:
        return {"status": "disabled"}
    async def op(db):
        cur = await db.execute(
            "SELECT person_id, last_sync_at, sync_status, sync_error, last_synced_count FROM M365_ACCOUNT WHERE person_id=?",
            (person_id,)
        )
        return await cur.fetchone()
    row = await run_read(op)
    if not row:
        return {"status": "not_found"}
    return {"status": "success", "data": dict(row)}


@router.post("/api/m365/emails/{person_id}/send")
async def send_email(person_id: str, req: dict):
    # not implemented yet
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="send mail not yet implemented")
