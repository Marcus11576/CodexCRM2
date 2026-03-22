from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings


def _env_file_path() -> Path:
    return Path(settings.BASE_DIR) / ".env"


def _mask_secret(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 10:
        return "*" * len(text)
    return f"{text[:7]}...{text[-4:]}"


def _upsert_env_value(key: str, value: str) -> None:
    env_path = _env_file_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = original.splitlines()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")

    updated = False
    rewritten: list[str] = []
    for line in lines:
        if pattern.match(line):
            rewritten.append(f"{key}={value}")
            updated = True
        else:
            rewritten.append(line)
    if not updated:
        rewritten.append(f"{key}={value}")

    content = "\n".join(rewritten)
    if original.endswith("\n") or not original:
        content += "\n"
    env_path.write_text(content, encoding="utf-8")


def _clear_openai_client_cache() -> None:
    # Both services cache AsyncOpenAI clients; refresh after key rotation.
    from backend.services import ai_runtime, ai_service

    ai_runtime.reset_openai_client_cache()
    ai_service.reset_openai_client_cache()


async def _validate_openai_api_key(api_key: str) -> None:
    from openai import AsyncOpenAI

    model = str(getattr(settings, "RELATIONSHIP_STORY_MODEL", "") or "gpt-5.2").strip()
    client = AsyncOpenAI(api_key=api_key)
    try:
        await client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {"role": "system", "content": "Return plain text only."},
                {"role": "user", "content": "ping"},
            ],
        )
    except Exception as exc:
        message = str(exc or "").strip()
        if not message:
            raise ValueError("OpenAI key validation failed") from exc
        lower = message.lower()
        if "insufficient_quota" in lower or "quota" in lower:
            raise ValueError("OpenAI key is valid but has insufficient quota for model usage") from exc
        if "invalid_api_key" in lower or "incorrect api key" in lower:
            raise ValueError("OpenAI API key is invalid") from exc
        raise ValueError(f"OpenAI key validation failed: {message[:220]}") from exc


async def get_runtime_settings() -> dict:
    env_path = _env_file_path()
    updated_at = ""
    if env_path.exists():
        updated_at = datetime.fromtimestamp(env_path.stat().st_mtime, tz=timezone.utc).isoformat()

    key = str(getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    return {
        "openai": {
            "configured": bool(settings.OPENAI_CONFIGURED),
            "masked_key": _mask_secret(key),
            "relationship_story_model": str(getattr(settings, "RELATIONSHIP_STORY_MODEL", "") or "").strip(),
            "updated_at": updated_at,
        }
    }


async def save_openai_api_key(api_key: str) -> dict:
    clean = str(api_key or "").strip()
    if not clean:
        raise ValueError("OpenAI API key is required")
    if not clean.startswith("sk-") or len(clean) < 20:
        raise ValueError("OpenAI API key must look like a valid 'sk-...' key")
    await _validate_openai_api_key(clean)

    _upsert_env_value("OPENAI_API_KEY", clean)
    os.environ["OPENAI_API_KEY"] = clean
    settings.OPENAI_API_KEY = clean
    _clear_openai_client_cache()
    return await get_runtime_settings()
