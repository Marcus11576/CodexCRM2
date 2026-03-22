from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.config import settings
from backend.services.standalone_transcript_tool import summarize_transcript_intelligence

router = APIRouter(prefix="/api/toolkit", tags=["toolkit"])


class TranscriptStyleExample(BaseModel):
    transcript: str = Field(..., min_length=1)
    preferred_summary: Optional[str] = None
    preferred_sections: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class TranscriptSummarizeRequest(BaseModel):
    transcript: str = Field(..., min_length=1)
    title: Optional[str] = None
    source_type: str = "transcript"
    guidance: Optional[str] = None
    custom_sections: list[str] = Field(default_factory=list)
    examples: list[TranscriptStyleExample] = Field(default_factory=list)
    max_points_per_section: int = Field(default=4, ge=1, le=8)


async def toolkit_auth_dependency(
    request: Request,
    x_tool_api_key: Annotated[Optional[str], Header()] = None,
):
    if settings.STANDALONE_TOOL_API_KEY:
        if x_tool_api_key == settings.STANDALONE_TOOL_API_KEY:
            return {"auth_mode": "tool_api_key"}
    from backend.routers.auth import current_user

    try:
        user = await current_user(request.cookies.get(settings.SESSION_COOKIE_NAME))
        return {"auth_mode": "session", "user": user}
    except HTTPException as exc:
        if settings.STANDALONE_TOOL_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid session or X-Tool-Api-Key required",
            ) from exc
        raise


@router.get("/health")
async def toolkit_health(auth: Annotated[dict, Depends(toolkit_auth_dependency)]):
    return {"status": "ok", "tool": "standalone_transcript_intelligence"}


@router.post("/transcripts/summarize")
async def summarize_transcript(
    req: TranscriptSummarizeRequest,
    auth: Annotated[dict, Depends(toolkit_auth_dependency)],
):
    return await summarize_transcript_intelligence(
        transcript=req.transcript,
        title=req.title,
        source_type=req.source_type,
        guidance=req.guidance,
        custom_sections=req.custom_sections,
        examples=[item.model_dump() for item in req.examples],
        max_points_per_section=req.max_points_per_section,
    )
