"""
Antigravity CRM - Auth Router
POST /api/auth/setup - first-time admin creation
POST /api/auth/login - returns JWT via cookie
GET  /api/auth/me - current user
GET  /api/auth/status - needs_setup and auth mode
"""
import secrets
from datetime import timedelta
from datetime import datetime, timezone
from typing import Annotated, Optional

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from backend.config import settings
from backend.database import get_db
from backend.services.auth_service import (
    count_users,
    create_token,
    create_user,
    decode_token,
    get_user_by_email,
    get_user_by_id,
    get_or_create_microsoft_user,
    update_user_login,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_microsoft_states: dict[str, dict] = {}


def _dev_user() -> dict:
    return {
        "user_id": "local-dev",
        "email": "local@antigravity.crm",
        "full_name": "Local Developer",
        "role": "admin",
    }


async def current_user(
    session_token: Annotated[Optional[str], Cookie(alias=settings.SESSION_COOKIE_NAME)] = None
) -> dict:
    if settings.AUTH_DISABLED:
        return _dev_user()
    if not session_token:
        raise HTTPException(401, "Authentication required")
    payload = decode_token(session_token)
    if not payload or not payload.get("sub"):
        raise HTTPException(401, "Invalid session")
    user = await get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    return user


class SetupRequest(BaseModel):
    email: str
    full_name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        path="/",
        httponly=True,
        max_age=settings.TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )


def _microsoft_redirect_uri(request: Request) -> str:
    if settings.M365_AUTH_REDIRECT_URI:
        return settings.M365_AUTH_REDIRECT_URI.strip()
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/auth/microsoft/callback"


def _microsoft_oauth_ready() -> bool:
    return bool(settings.M365_ENABLED and settings.M365_CLIENT_ID and settings.M365_TENANT_ID and settings.M365_CLIENT_SECRET)


def _microsoft_scope_string() -> str:
    return " ".join(scope.strip() for scope in str(settings.M365_SCOPES or "").split() if scope.strip())


def _prune_microsoft_states() -> None:
    now = datetime.now(timezone.utc)
    expired = [key for key, value in _microsoft_states.items() if value.get("expires_at") and value["expires_at"] <= now]
    for key in expired:
        _microsoft_states.pop(key, None)


@router.get("/status")
async def auth_status():
    count = await count_users()
    return {
        "needs_setup": count == 0,
        "auth_disabled": settings.AUTH_DISABLED,
        "microsoft_oauth_enabled": _microsoft_oauth_ready(),
        "microsoft_device_enabled": bool(settings.M365_ENABLED and settings.M365_CLIENT_ID and settings.M365_TENANT_ID),
    }


@router.post("/setup")
async def setup_first_admin(req: SetupRequest, response: Response):
    if settings.AUTH_DISABLED:
        return {"status": "success", "user": _dev_user(), "auth_disabled": True}
    if await count_users() > 0:
        raise HTTPException(403, "Setup already complete - use /login")
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    user = await create_user(req.email, req.full_name, req.password, role="admin")
    token = create_token(user["user_id"], user["email"])
    _set_session_cookie(response, token)
    return {"status": "success", "user": user}


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    if settings.AUTH_DISABLED:
        user = _dev_user()
        response.set_cookie(
            key=settings.SESSION_COOKIE_NAME,
            value="local-dev-bypass",
            path="/",
            httponly=True,
            max_age=settings.TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            secure=False,
        )
        return {"status": "success", "user": user, "auth_disabled": True}

    user = await get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    await update_user_login(user["user_id"], auth_provider=user.get("auth_provider") or "local")

    token = create_token(user["user_id"], user["email"])
    _set_session_cookie(response, token)
    return {
        "status": "success",
        "user": {
            "user_id": user["user_id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        },
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return {"status": "success", "message": "Logged out"}


@router.get("/microsoft/start")
async def microsoft_start(request: Request):
    if settings.AUTH_DISABLED:
        return RedirectResponse(url="/")
    if not _microsoft_oauth_ready():
        raise HTTPException(400, "Microsoft OAuth is not configured. Add M365 client credentials and redirect URI.")

    _prune_microsoft_states()
    state = secrets.token_urlsafe(32)
    _microsoft_states[state] = {
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "next": request.query_params.get("next") or "/",
    }

    params = {
        "client_id": settings.M365_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _microsoft_redirect_uri(request),
        "response_mode": "query",
        "scope": _microsoft_scope_string(),
        "state": state,
        "prompt": "select_account",
    }
    auth_url = httpx.URL(f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/authorize", params=params)
    return RedirectResponse(url=str(auth_url), status_code=302)


@router.get("/microsoft/callback")
async def microsoft_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    if settings.AUTH_DISABLED:
        return RedirectResponse(url="/")
    if error:
        return RedirectResponse(url=f"/login?error={error}", status_code=302)
    if not code or not state:
        return RedirectResponse(url="/login?error=missing_microsoft_code", status_code=302)

    _prune_microsoft_states()
    state_payload = _microsoft_states.pop(state, None)
    if not state_payload:
        return RedirectResponse(url="/login?error=invalid_microsoft_state", status_code=302)

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/token",
            data={
                "client_id": settings.M365_CLIENT_ID,
                "client_secret": settings.M365_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _microsoft_redirect_uri(request),
                "scope": _microsoft_scope_string(),
            },
            timeout=20,
        )
        if token_res.status_code >= 400:
            return RedirectResponse(url="/login?error=microsoft_token_exchange_failed", status_code=302)
        token_data = token_res.json()

        profile_res = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token_data.get('access_token', '')}"},
            params={"$select": "id,displayName,mail,userPrincipalName"},
            timeout=20,
        )
        if profile_res.status_code >= 400:
            return RedirectResponse(url="/login?error=microsoft_profile_failed", status_code=302)
        profile = profile_res.json()

    email = (profile.get("mail") or profile.get("userPrincipalName") or "").strip().lower()
    subject = str(profile.get("id") or "").strip()
    if not email or not subject:
        return RedirectResponse(url="/login?error=microsoft_account_missing_email", status_code=302)

    user = await get_or_create_microsoft_user(
        email=email,
        full_name=(profile.get("displayName") or email.split("@")[0]).strip(),
        external_subject=subject,
    )

    response = RedirectResponse(url=state_payload.get("next") or "/", status_code=302)
    token = create_token(user["user_id"], user["email"])
    _set_session_cookie(response, token)
    return response


@router.get("/me")
async def get_me(user: Annotated[dict, Depends(current_user)]):
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
    }
