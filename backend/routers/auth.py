"""
Antigravity CRM - Auth Router
POST /api/auth/setup - first-time admin creation
POST /api/auth/login - returns JWT via cookie
GET  /api/auth/me - current user
GET  /api/auth/status - needs_setup and auth mode
"""
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
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
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _dev_user() -> dict:
    return {
        "user_id": "local-dev",
        "email": "local@antigravity.crm",
        "full_name": "Local Developer",
        "role": "admin",
    }


async def current_user(session_token: Annotated[Optional[str], Cookie()] = None) -> dict:
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


@router.get("/status")
async def auth_status():
    count = await count_users()
    return {
        "needs_setup": count == 0,
        "auth_disabled": settings.AUTH_DISABLED,
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
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=settings.TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return {"status": "success", "user": user}


@router.post("/login")
async def login(req: LoginRequest, response: Response):
    if settings.AUTH_DISABLED:
        user = _dev_user()
        response.set_cookie(
            key="session_token",
            value="local-dev-bypass",
            httponly=True,
            max_age=settings.TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            secure=False,
        )
        return {"status": "success", "user": user, "auth_disabled": True}

    user = await get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    async with get_db() as db:
        await db.execute(
            "UPDATE USER SET last_login=? WHERE user_id=?",
            (datetime.now(timezone.utc).isoformat(), user["user_id"]),
        )
        await db.commit()

    token = create_token(user["user_id"], user["email"])
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=settings.TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
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
    response.delete_cookie(key="session_token")
    return {"status": "success", "message": "Logged out"}


@router.get("/me")
async def get_me(user: Annotated[dict, Depends(current_user)]):
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
    }
