from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.runtime_settings_service import (
    get_runtime_settings,
    save_openai_api_key,
)
from backend.services.system_settings_service import (
    get_intelligence_settings,
    reset_intelligence_settings,
    save_intelligence_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class IntelligenceSettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    merge: bool = True


class OpenAiApiKeyUpdateRequest(BaseModel):
    openai_api_key: str = Field(min_length=1)


@router.get("/intelligence")
async def get_intelligence_settings_endpoint():
    return await get_intelligence_settings()


@router.put("/intelligence")
async def save_intelligence_settings_endpoint(payload: IntelligenceSettingsUpdateRequest):
    return await save_intelligence_settings(payload.settings, merge=bool(payload.merge))


@router.post("/intelligence/reset")
async def reset_intelligence_settings_endpoint():
    return await reset_intelligence_settings()


@router.get("/runtime")
async def get_runtime_settings_endpoint():
    return await get_runtime_settings()


@router.put("/runtime/openai-key")
async def save_openai_key_endpoint(payload: OpenAiApiKeyUpdateRequest):
    try:
        return await save_openai_api_key(payload.openai_api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
