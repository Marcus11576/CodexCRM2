"""
Antigravity CRM — Authentication Service
JWT-based auth with bcrypt password hashing.
"""
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import bcrypt

from backend.config import settings
from backend.database import get_db

def hash_password(password: str) -> str:
    # bcrypt limits passwords to 72 bytes. Wait, we can just use bcrypt directly.
    truncated = password.encode('utf-8')[:72]
    # Generate salt and hash
    hashed = bcrypt.hashpw(truncated, bcrypt.gensalt())
    return hashed.decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    truncated = plain.encode('utf-8')[:72]
    try:
        return bcrypt.checkpw(truncated, hashed.encode('utf-8'))
    except Exception:
        return False


def create_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_user_by_email(email: str) -> Optional[dict]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM USER WHERE email = ? AND is_active = 1", (email,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_by_external_subject(external_subject: str) -> Optional[dict]:
    if not external_subject:
        return None
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM USER WHERE external_subject = ? AND is_active = 1",
            (external_subject,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_by_id(user_id: str) -> Optional[dict]:
    async with get_db() as db:
        async with db.execute("SELECT * FROM USER WHERE user_id = ? AND is_active = 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_user(email: str, full_name: str, password: str, role: str = "member") -> dict:
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    password_hash = hash_password(password)
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO USER (user_id, email, full_name, password_hash, role, auth_provider, created_at)
            VALUES (?,?,?,?,?, 'local', ?)
            """,
            (user_id, email.lower().strip(), full_name, password_hash, role, now)
        )
        await db.commit()
    return {"user_id": user_id, "email": email, "full_name": full_name, "role": role}


async def create_sso_user(
    *,
    email: str,
    full_name: str,
    auth_provider: str,
    external_subject: str,
    role: str = "member",
) -> dict:
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    password_hash = hash_password(secrets.token_urlsafe(32))
    normalized_email = email.lower().strip()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO USER (
                user_id, email, full_name, password_hash, role, auth_provider, external_subject, created_at, last_login
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (user_id, normalized_email, full_name, password_hash, role, auth_provider, external_subject, now, now),
        )
        await db.commit()
    return {
        "user_id": user_id,
        "email": normalized_email,
        "full_name": full_name,
        "role": role,
        "auth_provider": auth_provider,
    }


async def update_user_login(user_id: str, *, auth_provider: Optional[str] = None, external_subject: Optional[str] = None):
    fields = ["last_login=?"]
    values = [datetime.now(timezone.utc).isoformat()]
    if auth_provider:
        fields.append("auth_provider=?")
        values.append(auth_provider)
    if external_subject:
        fields.append("external_subject=?")
        values.append(external_subject)
    values.append(user_id)

    async with get_db() as db:
        await db.execute(f"UPDATE USER SET {', '.join(fields)} WHERE user_id=?", values)
        await db.commit()


async def get_or_create_microsoft_user(*, email: str, full_name: str, external_subject: str) -> dict:
    existing = await get_user_by_external_subject(external_subject)
    if existing:
        await update_user_login(existing["user_id"], auth_provider="microsoft", external_subject=external_subject)
        return existing

    by_email = await get_user_by_email(email)
    if by_email:
        await update_user_login(by_email["user_id"], auth_provider="microsoft", external_subject=external_subject)
        refreshed = await get_user_by_id(by_email["user_id"])
        return refreshed or by_email

    role = "admin" if await count_users() == 0 else "member"
    return await create_sso_user(
        email=email,
        full_name=full_name or email.split("@")[0],
        auth_provider="microsoft",
        external_subject=external_subject,
        role=role,
    )


async def count_users() -> int:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM USER") as cursor:
            row = await cursor.fetchone()
            return row[0]
