"""
Antigravity CRM - AI runtime
Centralized OpenAI execution, audit logging, and safe task wrappers.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.config import settings
from backend.database import init_db, run_write

_client = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def reset_openai_client_cache() -> None:
    global _client
    _client = None


def get_client():
    global _client
    if _client is None:
        if not settings.OPENAI_CONFIGURED:
            raise RuntimeError("OpenAI API key not configured")
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _serialize_usage(response: Any) -> Optional[dict]:
    usage = getattr(response, "usage", None)
    if not usage:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    if isinstance(usage, dict):
        return usage
    return {key: getattr(usage, key) for key in dir(usage) if not key.startswith("_") and isinstance(getattr(usage, key), (int, float, str, dict, list, type(None)))}


async def _insert_run_log(*, run_id: str, task_type: str, related_artifact_id: Optional[str], related_signal_id: Optional[str], related_profile_id: Optional[str], model_name: str, prompt_family: str, metadata: Optional[dict]):
    async def _insert(db):
        await db.execute(
            """
            INSERT INTO AI_RUN_LOG (
                id, task_type, related_artifact_id, related_signal_id, related_profile_id,
                model_name, prompt_family, started_at, status, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                task_type,
                related_artifact_id,
                related_signal_id,
                related_profile_id,
                model_name,
                prompt_family,
                _now(),
                "running",
                json.dumps(metadata or {}),
            ),
        )

    await run_write(_insert, label=f"insert ai run log {task_type}")


async def _complete_run_log(*, run_id: str, status: str, response: Any = None, accepted_output: Optional[bool] = None, rejection_reason: Optional[str] = None, started_perf: Optional[float] = None):
    usage_json = _serialize_usage(response)
    latency_ms = int((time.perf_counter() - started_perf) * 1000) if started_perf is not None else None

    async def _update(db):
        await db.execute(
            """
            UPDATE AI_RUN_LOG
            SET completed_at = ?, status = ?, token_usage_json = ?, latency_ms = ?,
                accepted_output_boolean = ?, rejection_reason = ?
            WHERE id = ?
            """,
            (
                _now(),
                status,
                json.dumps(usage_json) if usage_json is not None else None,
                latency_ms,
                None if accepted_output is None else int(bool(accepted_output)),
                rejection_reason,
                run_id,
            ),
        )

    await run_write(_update, label=f"complete ai run log {run_id}")


async def run_json_chat_task(
    *,
    task_type: str,
    prompt_family: str,
    messages: list[dict],
    model: str,
    temperature: float = 0.2,
    response_format: Optional[dict] = None,
    client_getter=None,
    related_artifact_id: Optional[str] = None,
    related_signal_id: Optional[str] = None,
    related_profile_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> tuple[dict, str]:
    if not settings.OPENAI_CONFIGURED:
        raise RuntimeError("OpenAI API key not configured")
    init_db()

    run_id = str(uuid.uuid4())
    started_perf = time.perf_counter()
    await _insert_run_log(
        run_id=run_id,
        task_type=task_type,
        related_artifact_id=related_artifact_id,
        related_signal_id=related_signal_id,
        related_profile_id=related_profile_id,
        model_name=model,
        prompt_family=prompt_family,
        metadata=metadata,
    )

    try:
        client = client_getter() if client_getter else get_client()
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=response_format or {"type": "json_object"},
            temperature=temperature,
        )
        content = response.choices[0].message.content or "{}"
        parsed = json.loads(content)
        await _complete_run_log(
            run_id=run_id,
            status="completed",
            response=response,
            accepted_output=True,
            started_perf=started_perf,
        )
        return parsed, run_id
    except json.JSONDecodeError as exc:
        await _complete_run_log(
            run_id=run_id,
            status="rejected",
            accepted_output=False,
            rejection_reason=f"invalid_json: {exc}",
            started_perf=started_perf,
        )
        raise
    except Exception as exc:
        await _complete_run_log(
            run_id=run_id,
            status="failed",
            accepted_output=False,
            rejection_reason=str(exc),
            started_perf=started_perf,
        )
        raise


async def run_json_responses_task(
    *,
    task_type: str,
    prompt_family: str,
    messages: list[dict],
    model: str,
    temperature: float = 0.2,
    tools: Optional[list[dict]] = None,
    related_artifact_id: Optional[str] = None,
    related_signal_id: Optional[str] = None,
    related_profile_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> tuple[dict, str]:
    if not settings.OPENAI_CONFIGURED:
        raise RuntimeError("OpenAI API key not configured")
    init_db()

    run_id = str(uuid.uuid4())
    started_perf = time.perf_counter()
    await _insert_run_log(
        run_id=run_id,
        task_type=task_type,
        related_artifact_id=related_artifact_id,
        related_signal_id=related_signal_id,
        related_profile_id=related_profile_id,
        model_name=model,
        prompt_family=prompt_family,
        metadata=metadata,
    )

    try:
        client = get_client()
        system_parts = [str(item.get("content") or "").strip() for item in messages if str(item.get("role") or "") == "system"]
        user_parts = [str(item.get("content") or "").strip() for item in messages if str(item.get("role") or "") != "system"]
        input_text = ""
        if system_parts:
            input_text += "SYSTEM INSTRUCTIONS:\n" + "\n\n".join(system_parts).strip()
        if user_parts:
            input_text += ("\n\n" if input_text else "") + "USER INPUT:\n" + "\n\n".join(user_parts).strip()

        request_kwargs = {
            "model": model,
            "input": input_text,
            "temperature": temperature,
        }
        if tools:
            request_kwargs["tools"] = tools

        response = await client.responses.create(**request_kwargs)
        content = getattr(response, "output_text", None) or "{}"
        parsed = json.loads(content)
        await _complete_run_log(
            run_id=run_id,
            status="completed",
            response=response,
            accepted_output=True,
            started_perf=started_perf,
        )
        return parsed, run_id
    except json.JSONDecodeError as exc:
        await _complete_run_log(
            run_id=run_id,
            status="rejected",
            accepted_output=False,
            rejection_reason=f"invalid_json: {exc}",
            started_perf=started_perf,
        )
        raise
    except Exception as exc:
        await _complete_run_log(
            run_id=run_id,
            status="failed",
            accepted_output=False,
            rejection_reason=str(exc),
            started_perf=started_perf,
        )
        raise


async def run_audio_transcription_task(
    *,
    file_handle,
    model: str = "whisper-1",
    client_getter=None,
    related_artifact_id: Optional[str] = None,
    related_profile_id: Optional[str] = None,
) -> tuple[str, str]:
    if not settings.OPENAI_CONFIGURED:
        raise RuntimeError("OpenAI API key not configured")
    init_db()

    run_id = str(uuid.uuid4())
    started_perf = time.perf_counter()
    await _insert_run_log(
        run_id=run_id,
        task_type="audio_transcription",
        related_artifact_id=related_artifact_id,
        related_signal_id=None,
        related_profile_id=related_profile_id,
        model_name=model,
        prompt_family="audio_transcription",
        metadata=None,
    )

    try:
        client = client_getter() if client_getter else get_client()
        response = await client.audio.transcriptions.create(model=model, file=file_handle)
        text = response.text
        await _complete_run_log(
            run_id=run_id,
            status="completed",
            response=response,
            accepted_output=bool(text.strip()),
            started_perf=started_perf,
        )
        return text, run_id
    except Exception as exc:
        await _complete_run_log(
            run_id=run_id,
            status="failed",
            accepted_output=False,
            rejection_reason=str(exc),
            started_perf=started_perf,
        )
        raise


async def run_speech_task(
    *,
    text: str,
    voice: str,
    model: str = "tts-1-hd",
    client_getter=None,
    related_profile_id: Optional[str] = None,
) -> tuple[bytes, str]:
    if not settings.OPENAI_CONFIGURED:
        raise RuntimeError("OpenAI API key not configured")
    init_db()

    run_id = str(uuid.uuid4())
    started_perf = time.perf_counter()
    await _insert_run_log(
        run_id=run_id,
        task_type="speech_generation",
        related_artifact_id=None,
        related_signal_id=None,
        related_profile_id=related_profile_id,
        model_name=model,
        prompt_family="brief_tts",
        metadata={"voice": voice},
    )

    try:
        client = client_getter() if client_getter else get_client()
        response = await client.audio.speech.create(
            model=model,
            voice=voice,
            input=text[:4000],
            response_format="mp3",
        )
        await _complete_run_log(
            run_id=run_id,
            status="completed",
            response=response,
            accepted_output=True,
            started_perf=started_perf,
        )
        return response.content, run_id
    except Exception as exc:
        await _complete_run_log(
            run_id=run_id,
            status="failed",
            accepted_output=False,
            rejection_reason=str(exc),
            started_perf=started_perf,
        )
        raise
