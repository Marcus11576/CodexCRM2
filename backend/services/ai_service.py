"""
Antigravity CRM â€” AI Service
All OpenAI calls live here. Clean, testable, no side effects.
"""
import json
import base64
import os
import re
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from backend.config import settings
from backend.database import get_sync_db, run_write
from backend.services.ai_runtime import (
    run_audio_transcription_task,
    run_json_chat_task,
    run_speech_task,
)
from backend.services.preference_learning import (
    EVENT_WEIGHTS,
    compute_preference_profile,
    normalize_feedback_event,
    preference_guidance_lines,
)
from backend.services.pilot_cohort_service import is_person_in_pilot_cohort
from backend.services.standalone_transcript_tool import summarize_transcript_intelligence
from backend.services.ai_foundation import (
    business_subtopic_label,
    canonical_business_subtopic,
    infer_business_subtopic,
    strip_speculative_filler,
)
from backend.services.relationship_intelligence_pipeline import (
    STAGE2_OPPORTUNITY_STAGE_DETAILS,
    STAGE2_RELATIONSHIP_STAGE_DETAILS,
)
from backend.services.transcript_guardrails import looks_like_stage_command

# --- PLATINUM PROTECTION WHITEMAP ---
# These are the ONLY fields AI is allowed to update directly on a Person record.
# Manual notes, gossip, and intel_notes are EXCLUDED to prevent data pollution.
ALLOWED_PROFILE_FIELDS = {
    "cat", "env", "disc", "contact_value", "title_current", 
    "company_name_raw", "email_primary", "phone_primary", "linkedin_url",
    "is_ts_advisory_candidate"
}

# Lazy-init client â€” only created when first needed
_client = None

def _get_client():
    global _client
    if _client is None:
        if not settings.OPENAI_CONFIGURED:
            raise RuntimeError("OpenAI API key not configured")
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def reset_openai_client_cache() -> None:
    global _client
    _client = None


def _get_taxonomy_block() -> str:
    """Load live taxonomy from DB for AI context."""
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute("SELECT category_type, label, value FROM CONFIG_TAXONOMY WHERE is_active=1 ORDER BY category_type, display_order")
        rows = c.fetchall()
        conn.close()
        tax = {}
        for cat_type, label, value in rows:
            tax.setdefault(cat_type, []).append(f"{label} ({value})")
        lines = []
        for k, vals in tax.items():
            lines.append(f"{k.upper()}: {', '.join(vals)}")
        return "\n".join(lines)
    except Exception:
        return "CAT: OBE Member (OBE M), OBE Target (OBE T), TGT, EXT, HPC, TSA, GEN\nENV: Consultant, Developer - Gov, Developer - Semi-Gov, Developer - Private, Main Contractor\nDISC: Commercial, Delivery, Design, Corporate, Support Services"


def _get_latest_profile_photo_candidate(person_id: str, preferred_media_url: Optional[str] = None) -> Optional[dict]:
    """Return the latest uploaded headshot candidate for explicit approval flows."""
    conn = None
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        params = [person_id]
        sql = """
            SELECT artifact_id, media_url, source_name, created_at, requires_confirmation,
                   status, input_type, source_interaction_id
            FROM AI_ARTIFACT
            WHERE COALESCE(profile_id_nullable, person_id) = ?
              AND input_type = 'profile_picture'
              AND COALESCE(media_url, '') != ''
              AND COALESCE(status, 'processed') NOT IN ('failed', 'duplicate')
        """
        if preferred_media_url:
            sql += " AND media_url = ?"
            params.append(preferred_media_url)
        sql += " ORDER BY created_at DESC LIMIT 1"
        c.execute(sql, params)
        row = c.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"Profile photo candidate lookup error: {e}")
        return None
    finally:
        if conn is not None:
            conn.close()


def _get_success_calibration_block() -> str:
    """Load top 3 highest-rated interactions to calibrate AI success scoring."""
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute("""
            SELECT summary, metric_tags 
            FROM INTERACTION 
            WHERE is_strategic=1 AND success_rating=5 
            ORDER BY created_at DESC LIMIT 3
        """)
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return ""
            
        lines = ["HISTORICAL 'GAME-CHANGING WINS' FOR CALIBRATION:"]
        for summary, tags in rows:
            lines.append(f"- Summary: {summary} | Tags: {tags}")
        return "\n".join(lines) + "\n"
    except Exception as e:
        print(f"Calibration load error: {e}")
        return ""


def _resolve_relative_due_date(text: str, today) -> Optional[str]:
    lowered = str(text or "").strip().lower()

    if "tomorrow" in lowered:
        return (today + timedelta(days=1)).isoformat()
    if "today" in lowered:
        return today.isoformat()
    if "next week" in lowered:
        return (today + timedelta(days=7)).isoformat()

    weekday_tokens = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for token, weekday in weekday_tokens.items():
        if token in lowered:
            day_delta = (weekday - today.weekday()) % 7
            if day_delta == 0:
                day_delta = 7
            return (today + timedelta(days=day_delta)).isoformat()
    return None


def _message_has_explicit_date(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if re.search(r"\b20\d{2}-\d{2}-\d{2}\b", lowered):
        return True
    if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", lowered):
        return True
    if re.search(
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
        lowered,
    ):
        return True
    return False


def _normalize_due_date_for_message(message: str, due_date: Optional[str]) -> Optional[str]:
    """Normalize model-produced due dates so relative reminders never become stale historical dates."""
    text = str(message or "").strip()
    today = datetime.now(timezone.utc).date()

    relative_due = _resolve_relative_due_date(text, today)
    if relative_due:
        return relative_due

    candidate = str(due_date or "").strip()
    if not candidate:
        return None

    try:
        parsed = datetime.strptime(candidate, "%Y-%m-%d").date()
    except Exception:
        return candidate

    if parsed >= today:
        return candidate
    if _message_has_explicit_date(text):
        return candidate

    # Guardrail: if the model invents an old date for a non-dated prompt, anchor to today.
    return today.isoformat()


def _clean_role_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_role_lookup(value: Any) -> str:
    text = _clean_role_value(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _coerce_employment_history(value: Any) -> list[dict]:
    parsed = value
    if isinstance(parsed, str):
        raw = parsed.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []

    normalized: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": _clean_role_value(item.get("title")),
                "company": _clean_role_value(item.get("company")),
                "start_date": _clean_role_value(item.get("start_date")),
                "end_date": _clean_role_value(item.get("end_date")),
                "location": _clean_role_value(item.get("location")),
                "description": _clean_role_value(item.get("description")),
            }
        )
    return normalized


def _pick_employment_role_index(
    history: list[dict],
    *,
    title: str,
    company: str,
    start_date: str,
) -> tuple[int, str]:
    if not history:
        return -1, "no_history"

    title_q = _normalize_role_lookup(title)
    company_q = _normalize_role_lookup(company)
    start_q = _clean_role_value(start_date)
    selectors_present = any((title_q, company_q, start_q))

    if not selectors_present:
        for idx, role in enumerate(history):
            if not _clean_role_value(role.get("end_date")):
                return idx, "latest_open_role"
        return 0, "latest_role"

    best_index = -1
    best_score = 0
    best_indexes: list[int] = []
    for idx, role in enumerate(history):
        score = 0
        role_title = _normalize_role_lookup(role.get("title"))
        role_company = _normalize_role_lookup(role.get("company"))
        role_start = _clean_role_value(role.get("start_date"))

        if title_q:
            if role_title and role_title == title_q:
                score += 6
            elif role_title and (title_q in role_title or role_title in title_q):
                score += 3

        if company_q:
            if role_company and role_company == company_q:
                score += 6
            elif role_company and (company_q in role_company or role_company in company_q):
                score += 3

        if start_q:
            if role_start == start_q:
                score += 4
            elif role_start and (role_start.startswith(start_q) or start_q.startswith(role_start)):
                score += 2

        if score > best_score:
            best_score = score
            best_index = idx
            best_indexes = [idx]
        elif score > 0 and score == best_score:
            best_indexes.append(idx)

    if best_score <= 0:
        return -1, "no_match"
    if len(best_indexes) > 1:
        return min(best_indexes), "selector_match_latest"
    return best_index, "selector_match"


def _extract_iso_date_from_text(text: str) -> Optional[str]:
    raw = str(text or "")
    full_date = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", raw)
    if full_date:
        return full_date.group(1)
    month_date = re.search(r"\b(20\d{2}-\d{2})\b", raw)
    if month_date:
        return month_date.group(1)
    return None


def _infer_chat_topic_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    if any(
        token in lowered
        for token in (
            "family",
            "wife",
            "husband",
            "kids",
            "children",
            "personal",
            "daughter",
            "son",
            "back pain",
            "his back",
            "her back",
            "health issue",
            "health issues",
            "surgery",
            "medical leave",
            "hospitalized",
            "hospitalised",
        )
    ):
        return "family_personal"
    if any(token in lowered for token in ("hiring", "recruit", "talent", "candidate", "staffing", "team build", "headcount")):
        return "recruitment_talent"
    if any(token in lowered for token in ("obe", "order of business excellence", "network event", "member event", "obe network")):
        return "obe_focus"
    return "business_focus"


def _looks_like_profile_photo_intent(text: str) -> bool:
    lowered = str(text or "").lower()
    photo_terms = ("profile photo", "profile picture", "headshot", "photo")
    action_terms = ("set", "use", "apply", "make", "update", "change")
    source_terms = ("uploaded", "upload", "this image", "latest image")
    has_photo_term = any(term in lowered for term in photo_terms)
    has_action_term = any(term in lowered for term in action_terms)
    has_source_term = any(term in lowered for term in source_terms)
    return has_photo_term and (has_action_term or has_source_term)


def _is_openai_quota_or_rate_error(error: Exception) -> bool:
    if error is None:
        return False
    status_code = getattr(error, "status_code", None) or getattr(error, "http_status", None)
    if status_code == 429:
        return True
    text = str(error or "").lower()
    markers = (
        "429",
        "insufficient_quota",
        "quota",
        "rate limit",
        "rate_limit",
        "too many requests",
    )
    return any(marker in text for marker in markers)


def _assistant_storyline_refusal(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "can't update the relationship storyline",
        "cannot update the relationship storyline",
        "can not update the relationship storyline",
        "can't update the storyline",
        "cannot update the storyline",
    )
    return any(marker in lowered for marker in markers)


def _looks_like_factual_profile_update_text(text: str) -> bool:
    normalized = str(text or "").strip()
    if len(normalized) < 40:
        return False
    if normalized.endswith("?"):
        return False
    lowered = normalized.lower()
    strong_markers = (
        "had a good chat",
        "had a chat",
        "spoke with",
        "met with",
        "discussed",
        "he is concerned",
        "she is concerned",
        "he believes",
        "she believes",
        "relationship remains",
    )
    if any(marker in lowered for marker in strong_markers):
        return True
    if normalized.count(".") >= 2 and not any(q in lowered for q in ("what", "how", "why", "should i", "can you")):
        return True
    return False


async def _profile_chat_rule_fallback(person_id: str, person: dict, message: str, root_error: Optional[Exception] = None) -> dict:
    operations: list[dict] = []
    normalized_message = str(message or "").strip()
    lowered_message = normalized_message.lower()
    now = datetime.now(timezone.utc).isoformat()

    capture_prefixes = (
        "capture this update for the profile:",
        "capture this update:",
        "capture update:",
        "capture update",
    )
    capture_intent = any(lowered_message.startswith(prefix) for prefix in capture_prefixes)
    capture_text = normalized_message
    for prefix in capture_prefixes:
        if lowered_message.startswith(prefix):
            capture_text = normalized_message[len(prefix):].strip(" \n\t:-")
            break

    if capture_intent:
        if not capture_text:
            return {
                "response": "Please add the update details after 'Capture update:' and I will save it to this profile.",
                "operations": operations,
            }

        topic = _infer_chat_topic_from_text(capture_text)
        intel_id = str(uuid.uuid4())[:12]

        async def _log_fallback_intelligence(db):
            await db.execute(
                "INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at, status, source_snippet) VALUES (?,?,?,?,?,?,?,?)",
                (intel_id, person_id, topic, capture_text, 4, now, "approved", capture_text),
            )
            await db.execute(
                "UPDATE PERSON SET last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                (now, person_id),
            )

        await run_write(_log_fallback_intelligence, label=f"chat fallback log intelligence {person_id}")
        operations.append({"type": "log_intelligence", "status": "completed", "intel_id": intel_id, "topic": topic})
        return {
            "response": "Done. Applied: log intelligence.",
            "operations": operations,
        }

    task_prefixes = (
        "create a follow-up task with this title:",
        "create follow-up task:",
        "create task:",
        "create a task:",
    )
    task_intent = any(lowered_message.startswith(prefix) for prefix in task_prefixes)
    task_title = ""
    for prefix in task_prefixes:
        if lowered_message.startswith(prefix):
            task_title = normalized_message[len(prefix):].strip()
            break
    if task_intent:
        if not task_title:
            return {
                "response": "Please add a task title after 'Create task:' and I will save it.",
                "operations": operations,
            }

        task_id = str(uuid.uuid4())
        due_candidate = _extract_iso_date_from_text(normalized_message)
        due_date = _normalize_due_date_for_message(normalized_message, due_candidate)
        due_time = "09:00"

        async def _create_fallback_task(db):
            await db.execute(
                "INSERT INTO TASK (task_id, person_id, task_text, due_date, due_time, priority, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, person_id, task_title, due_date, due_time, "medium", "open", now),
            )
            await db.execute(
                """
                UPDATE PERSON
                SET next_contact_due_date = (
                    SELECT MIN(due_date)
                    FROM TASK
                    WHERE person_id=? AND status IN ('open', 'in_progress') AND due_date IS NOT NULL
                ),
                last_updated_at=?,
                cached_briefing=NULL
                WHERE person_id=?
                """,
                (person_id, now, person_id),
            )

        await run_write(_create_fallback_task, label=f"chat fallback create task {person_id}")
        operations.append(
            {
                "type": "create_task",
                "status": "completed",
                "task_id": task_id,
                "title": task_title,
                "due_date": due_date,
                "due_time": due_time,
            }
        )
        return {"response": "Done. Applied: create task.", "operations": operations}

    employment_intent = "end date" in lowered_message and any(
        token in lowered_message for token in ("add", "set", "update", "change", "just")
    )
    if employment_intent:
        end_date = _extract_iso_date_from_text(normalized_message)
        if not end_date:
            if "today" in lowered_message:
                end_date = datetime.now(timezone.utc).date().isoformat()
            else:
                end_date = datetime.now(timezone.utc).date().isoformat()

        history_roles = _coerce_employment_history(person.get("employment_history"))
        company_hint = "wsp" if "wsp" in lowered_message else ""
        target_idx, match_mode = _pick_employment_role_index(
            history_roles,
            title="",
            company=company_hint,
            start_date="",
        )
        if target_idx < 0 and history_roles and company_hint:
            target_idx, match_mode = _pick_employment_role_index(
                history_roles,
                title="",
                company="",
                start_date="",
            )

        if target_idx < 0:
            operations.append({"type": "update_employment_history", "status": "failed", "reason": match_mode})
            return {
                "response": "I could not find a role to update. Please open Employment History and set the end date manually.",
                "operations": operations,
            }

        role_before = dict(history_roles[target_idx])
        role_after = dict(role_before)
        role_after["end_date"] = end_date
        history_roles[target_idx] = role_after
        payload = json.dumps(history_roles, ensure_ascii=False)

        async def _update_fallback_employment(db):
            await db.execute(
                "UPDATE PERSON SET employment_history=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                (payload, now, person_id),
            )

        await run_write(_update_fallback_employment, label=f"chat fallback employment update {person_id}")
        person["employment_history"] = history_roles
        operations.append(
            {
                "type": "update_employment_history",
                "status": "completed",
                "matched_index": target_idx,
                "matched_by": match_mode,
                "before": role_before,
                "after": role_after,
            }
        )
        return {"response": "Done. Applied: update employment history.", "operations": operations}

    if _looks_like_profile_photo_intent(normalized_message):
        candidate = _get_latest_profile_photo_candidate(person_id)
        current_photo_url = person.get("profile_photo_url")
        if not candidate:
            operations.append({"type": "apply_profile_photo", "status": "failed", "reason": "no_candidate"})
            return {
                "response": "No uploaded headshot candidate is available yet. Please upload a profile photo first.",
                "operations": operations,
            }

        media_url = candidate["media_url"]
        already_active = current_photo_url == media_url

        async def _apply_fallback_profile_photo(db):
            await db.execute(
                "UPDATE PERSON SET profile_photo_url=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                (media_url, now, person_id),
            )
            await db.execute(
                "UPDATE AI_ARTIFACT SET requires_confirmation=0, updated_at=?, status='processed' WHERE artifact_id=?",
                (now, candidate["artifact_id"]),
            )

        await run_write(_apply_fallback_profile_photo, label=f"chat fallback apply profile photo {person_id}")
        person["profile_photo_url"] = media_url
        operations.append(
            {
                "type": "apply_profile_photo",
                "status": "completed",
                "artifact_id": candidate["artifact_id"],
                "media_url": media_url,
                "source_name": candidate.get("source_name"),
                "applied": True,
            }
        )
        return {
            "response": "That headshot is already active." if already_active else "Done. Applied: apply profile photo.",
            "operations": operations,
        }

    if _is_openai_quota_or_rate_error(root_error):
        return {
            "response": (
                "AI is temporarily rate-limited or out of quota. "
                "You can still use direct commands now: "
                "'Capture update: ...', 'Create task: ...', or 'Add end date YYYY-MM-DD ...'."
            ),
            "operations": operations,
        }

    return {
        "response": "Assistant hit a temporary issue. Please retry, or use direct commands like 'Capture update:' or 'Create task:'.",
        "operations": operations,
    }


def _looks_like_transcript_text(text: str) -> bool:
    sample = str(text or "")
    if len(sample) < 240:
        return False
    transcript_markers = ["[", "]", ":", "\n", "whatsapp", "last seen", "sent from my iphone", "from:", "subject:"]
    marker_hits = sum(1 for marker in transcript_markers if marker in sample.lower())
    return marker_hits >= 2 or sample.count("\n") >= 3


_PROFILE_DOC_SECTION_MARKERS = (
    "curriculum vitae",
    "resume",
    "professional summary",
    "summary",
    "experience",
    "work experience",
    "employment history",
    "career history",
    "education",
    "skills",
    "certifications",
    "achievements",
)

_PROFILE_DOC_CONTEXT_MARKERS = (
    "linkedin.com/in/",
    "professional experience",
    "present",
    "current role",
)

_PROFILE_DOC_DATE_RANGE_RE = re.compile(
    r"\b(?:19|20)\d{2}\s*(?:-|to|–|—)\s*(?:present|current|(?:19|20)\d{2})\b",
    flags=re.IGNORECASE,
)


def _looks_like_profile_document_text(text: str) -> bool:
    sample = str(text or "")
    if len(sample) < 180:
        return False
    lowered = sample.lower()
    section_hits = sum(1 for marker in _PROFILE_DOC_SECTION_MARKERS if marker in lowered)
    context_hits = sum(1 for marker in _PROFILE_DOC_CONTEXT_MARKERS if marker in lowered)
    date_range_hits = len(_PROFILE_DOC_DATE_RANGE_RE.findall(sample))
    bullet_lines = sum(
        1
        for line in sample.splitlines()
        if line.strip().startswith(("-", "*", "•"))
    )
    return (
        section_hits >= 2
        and (
            date_range_hits >= 1
            or context_hits >= 1
            or bullet_lines >= 2
        )
    )


def _should_run_transcript_enrichment(source_type: str, text: str) -> bool:
    normalized = str(source_type or "").strip().lower()
    if len(str(text or "").strip()) < 240:
        return False
    if normalized in {"document", "pdf", "cv", "resume", "document_capture"} and _looks_like_profile_document_text(text):
        return False
    if normalized in {
        "whatsapp",
        "chat",
        "email",
        "outlook",
        "gmail",
        "teams",
        "screenshot",
        "transcript",
        "meeting",
        "call",
        "voice_note",
        "audio_note",
    }:
        return True
    return _looks_like_transcript_text(text)


def _section_id_to_topic(section_id: str) -> Optional[str]:
    normalized = str(section_id or "").strip().lower()
    if normalized in {"business_focus", "recruitment_talent", "family_personal", "obe_focus"}:
        return normalized
    return None


def _topic_from_other_topic(label: str, summary: str, points: list[dict]) -> Optional[str]:
    haystack = " ".join(
        part for part in (
            str(label or "").strip(),
            str(summary or "").strip(),
            " ".join(
                str(point.get("text") or point.get("evidence") or "").strip()
                for point in (points or [])
                if isinstance(point, dict)
            ),
        )
        if str(part or "").strip()
    ).lower()
    if not haystack:
        return None
    if any(term in haystack for term in ("obe", "order of business excellence", "roundtable", "member event")):
        return "obe_focus"
    if any(
        term in haystack
        for term in (
            "coffee",
            "breakfast",
            "lunch",
            "dinner",
            "drink",
            "catch up",
            "catch-up",
            "meet up",
            "meet-up",
            "grab a coffee",
            "after eid",
            "after ramadan",
            "social follow-up",
            "personal follow-up",
        )
    ):
        return "family_personal"
    return None


def _trim_supporting_evidence(evidence: str, limit: int = 720) -> str:
    cleaned = " ".join(strip_speculative_filler(evidence).split())
    if len(cleaned) <= limit:
        return cleaned
    sentence_break = cleaned.rfind(". ", 0, limit)
    if sentence_break >= int(limit * 0.6):
        return cleaned[: sentence_break + 1].strip()
    word_break = cleaned.rfind(" ", 0, limit)
    if word_break >= int(limit * 0.6):
        return cleaned[:word_break].strip()
    return cleaned[:limit].rstrip()


def _rich_section_text(summary: str, points: list[dict]) -> str:
    base = strip_speculative_filler(summary)
    additions = []
    base_key = " ".join(base.lower().split())
    for point in points[:3]:
        point_text = strip_speculative_filler(point.get("text"))
        if not point_text:
            continue
        point_key = " ".join(point_text.lower().split())
        if point_key and point_key in base_key:
            continue
        additions.append(point_text)
    combined = base
    for addition in additions:
        combined = f"{combined} {addition}".strip() if combined else addition
    return _trim_supporting_evidence(combined, limit=900)


def _topic_nuggets_from_transcript_view(transcript_view: dict) -> list[dict]:
    nuggets = []
    seen_keys = set()
    for section in transcript_view.get("sections") or []:
        if not isinstance(section, dict):
            continue
        topic = _section_id_to_topic(section.get("id"))
        if not topic:
            continue
        summary = str(section.get("summary") or "").strip()
        points = [point for point in (section.get("points") or []) if isinstance(point, dict)]
        if not summary and not points:
            continue
        if topic == "business_focus":
            for point in points[:3]:
                point_text = strip_speculative_filler(point.get("text"))
                evidence = str(point.get("evidence") or "").strip()
                subtopic = canonical_business_subtopic(point.get("subtopic")) or infer_business_subtopic(point_text, evidence)
                if not point_text:
                    continue
                nugget_text = _rich_section_text(summary, [point])
                nugget_key = (topic, nugget_text.lower())
                if nugget_text and nugget_key not in seen_keys:
                    seen_keys.add(nugget_key)
                    nuggets.append(
                        {
                            "topic": topic,
                            "business_subtopic": subtopic,
                            "text": nugget_text,
                            "snippet": _trim_supporting_evidence(evidence or point_text),
                            "confidence": round(float(point.get("confidence") or section.get("confidence") or 0.72), 3),
                            "sentiment": "Unclear",
                        }
                    )
            continue
        evidence_parts = []
        for point in points[:2]:
            evidence = str(point.get("evidence") or point.get("text") or "").strip()
            if evidence and evidence not in evidence_parts:
                evidence_parts.append(evidence)
        text = _rich_section_text(summary, points) or str(points[0].get("text") or "").strip()
        if not text:
            continue
        section_confidence = section.get("confidence")
        point_confidences = [
            float(point.get("confidence"))
            for point in points
            if point.get("confidence") is not None
        ]
        confidences = [
            value for value in ([float(section_confidence)] if section_confidence is not None else []) + point_confidences
        ]
        confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.72
        nugget_key = (topic, text.lower())
        if nugget_key not in seen_keys:
            seen_keys.add(nugget_key)
            nuggets.append(
                {
                    "topic": topic,
                    "text": text,
                    "snippet": _trim_supporting_evidence(" ".join(evidence_parts) or text),
                    "confidence": confidence,
                    "sentiment": "Unclear",
                }
            )
    for item in transcript_view.get("other_topics") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        summary = str(item.get("summary") or "").strip()
        points = [point for point in (item.get("points") or []) if isinstance(point, dict)]
        topic = _topic_from_other_topic(label, summary, points)
        if not topic:
            continue
        evidence_parts = []
        for point in points[:2]:
            evidence = str(point.get("evidence") or point.get("text") or "").strip()
            if evidence and evidence not in evidence_parts:
                evidence_parts.append(evidence)
        text = _rich_section_text(summary, points) or " ".join(
            str(point.get("text") or "").strip()
            for point in points[:2]
            if str(point.get("text") or "").strip()
        ).strip()
        if not text:
            continue
        nugget_key = (topic, text.lower())
        if nugget_key in seen_keys:
            continue
        seen_keys.add(nugget_key)
        confidences = [
            float(point.get("confidence"))
            for point in points
            if point.get("confidence") is not None
        ]
        confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.68
        nuggets.append(
            {
                "topic": topic,
                "text": text,
                "snippet": _trim_supporting_evidence(" ".join(evidence_parts) or text),
                "confidence": confidence,
                "sentiment": "Unclear",
            }
        )
    return nuggets


def _dedupe_action_items(items: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for item in items or []:
        text = " ".join(str(item or "").split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _action_items_from_transcript_view(transcript_view: dict) -> list[str]:
    suggestions: list[str] = []
    for item in transcript_view.get("other_topics") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        summary = str(item.get("summary") or "").strip()
        points = [point for point in (item.get("points") or []) if isinstance(point, dict)]
        haystack = " ".join(
            part for part in (
                label,
                summary,
                " ".join(
                    str(point.get("text") or point.get("evidence") or "").strip()
                    for point in points
                ),
            )
            if str(part or "").strip()
        ).lower()
        if not haystack:
            continue
        if "coffee" in haystack and "eid" in haystack:
            suggestions.append("Call Brian after Eid to arrange coffee.")
        elif any(term in haystack for term in ("coffee", "lunch", "breakfast", "dinner", "catch up", "catch-up")):
            suggestions.append("Arrange a social catch-up with the contact.")
        elif "call" in haystack and any(term in haystack for term in ("after eid", "next week", "tomorrow")):
            suggestions.append("Call the contact at the agreed follow-up time.")
    return _dedupe_action_items(suggestions)


async def _enrich_transcript_result(*, text: str, source_type: str, title: Optional[str] = None) -> Optional[dict]:
    if not _should_run_transcript_enrichment(source_type, text):
        return None
    transcript_view = await summarize_transcript_intelligence(
        transcript=text,
        title=title,
        source_type=source_type,
        guidance=(
            "Preserve full relevant commercial or relationship context, separate mixed topics cleanly, "
            "and drop banter or throwaway lines."
        ),
        max_points_per_section=3,
    )
    nuggets = _topic_nuggets_from_transcript_view(transcript_view)
    if not nuggets:
        return None
    return {
        "summary": transcript_view.get("executive_summary") or "",
        "topic_nuggets": nuggets,
        "action_items": _action_items_from_transcript_view(transcript_view),
        "transcript_view": transcript_view,
    }


def _message_requests_stage_list(message: str) -> bool:
    return looks_like_stage_command(message)


def _message_requests_contact_schedule(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    patterns = (
        r"\bwhen\s+should\s+i\s+(?:next\s+)?(?:interact|contact|reach\s*out|follow\s*up)\b",
        r"\bnext\s+(?:interaction|contact|follow[-\s]?up)\b",
        r"\bhow\s+often\s+should\s+i\s+(?:contact|follow\s*up|interact)\b",
        r"\btime\s+schedule\b.*\b(?:interact|contact|relationship)\b",
        r"\bkeep\s+the\s+relationship\s+alive\b",
        r"\bcadence\b.*\b(?:contact|interaction|follow[-\s]?up|relationship)\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stage_cadence_days(relationship_code: str, opportunity_code: str) -> int:
    relationship = str(relationship_code or "").strip().upper()
    opportunity = str(opportunity_code or "").strip().upper()
    days = 14
    if relationship == "S1":
        days = 30
    elif relationship == "S2":
        days = 21
    elif relationship == "S3":
        days = 14
    elif relationship == "S4":
        days = 10
    elif relationship == "S5":
        days = 7
    elif relationship == "S6":
        days = 5
    elif relationship in {"S7", "S8", "S9"}:
        days = 4
    if opportunity in {"O2", "O3", "O5", "O6", "O7"}:
        days = min(days, 4)
    elif opportunity in {"O1", "O4"}:
        days = min(days, 7)
    return max(3, int(days))


def _load_contact_schedule_snapshot(person_id: str, person: dict) -> dict:
    stage2 = _load_latest_stage2_flow(person_id)
    relationship_stage = stage2.get("relationship_stage") if isinstance(stage2.get("relationship_stage"), dict) else {}
    opportunity_stage = stage2.get("opportunity_stage") if isinstance(stage2.get("opportunity_stage"), dict) else {}
    relationship_code = str(relationship_stage.get("code") or "").strip().upper()
    opportunity_code = str(opportunity_stage.get("code") or "").strip().upper()
    cadence_days = _stage_cadence_days(relationship_code, opportunity_code)
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()

    last_interaction_at = None
    next_task_due_date = None
    next_task_title = ""

    conn = None
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT interaction_at
            FROM INTERACTION
            WHERE person_id = ?
              AND COALESCE(channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(summary, raw_text, '')) != ''
            ORDER BY datetime(interaction_at) DESC, interaction_id DESC
            LIMIT 1
            """,
            (person_id,),
        )
        interaction_row = c.fetchone()
        if interaction_row:
            last_interaction_at = _parse_iso_datetime(interaction_row["interaction_at"])

        c.execute(
            """
            SELECT task_text, due_date
            FROM TASK
            WHERE person_id = ?
              AND status IN ('open', 'in_progress')
              AND COALESCE(due_date, '') != ''
            ORDER BY due_date ASC, COALESCE(due_time, '23:59') ASC, created_at ASC
            LIMIT 1
            """,
            (person_id,),
        )
        task_row = c.fetchone()
        if task_row:
            next_task_title = str(task_row["task_text"] or "").strip()
            due_raw = str(task_row["due_date"] or "").strip()
            try:
                next_task_due_date = datetime.strptime(due_raw, "%Y-%m-%d").date()
            except Exception:
                next_task_due_date = None
    except Exception:
        pass
    finally:
        if conn is not None:
            conn.close()

    if last_interaction_at:
        days_since_contact = max(0, (today - last_interaction_at.date()).days)
        next_due_date = last_interaction_at.date() + timedelta(days=cadence_days)
    else:
        days_since_contact = None
        next_due_date = today + timedelta(days=cadence_days)

    overdue_days = max(0, (today - next_due_date).days)
    return {
        "person_name": str(person.get("full_name") or "This contact").strip() or "This contact",
        "relationship_code": relationship_code or "S?",
        "relationship_label": str(relationship_stage.get("label") or relationship_code or "Relationship stage").strip(),
        "opportunity_code": opportunity_code or "",
        "cadence_days": cadence_days,
        "today": today,
        "last_interaction_at": last_interaction_at,
        "days_since_contact": days_since_contact,
        "next_due_date": next_due_date,
        "overdue_days": overdue_days,
        "next_task_due_date": next_task_due_date,
        "next_task_title": next_task_title,
    }


def _format_date_label(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%A, %d %b %Y")
    if hasattr(value, "strftime"):
        return value.strftime("%A, %d %b %Y")
    return str(value or "")


def _render_contact_schedule_response(snapshot: dict) -> str:
    name = str(snapshot.get("person_name") or "This contact")
    cadence_days = int(snapshot.get("cadence_days") or 14)
    relationship_label = str(snapshot.get("relationship_label") or "Relationship stage").strip()
    next_due_date = snapshot.get("next_due_date")
    days_since_contact = snapshot.get("days_since_contact")
    last_interaction_at = snapshot.get("last_interaction_at")
    overdue_days = int(snapshot.get("overdue_days") or 0)
    next_task_due_date = snapshot.get("next_task_due_date")
    next_task_title = str(snapshot.get("next_task_title") or "").strip()

    lines = [
        f"Yes. We track a contact cadence for relationship health.",
        f"For {name}:",
        f"- Target cadence: every {cadence_days} days ({relationship_label}).",
    ]
    if last_interaction_at:
        lines.append(
            f"- Last meaningful interaction: {_format_date_label(last_interaction_at)}"
            + (f" ({int(days_since_contact)} days ago)." if days_since_contact is not None else ".")
        )
    else:
        lines.append("- Last meaningful interaction: not recorded yet.")

    if overdue_days > 0:
        lines.append(
            f"- Next interaction due: {_format_date_label(next_due_date)} (overdue by {overdue_days} days)."
        )
        lines.append(f"Recommended action: contact today ({_format_date_label(snapshot.get('today'))}).")
    else:
        lines.append(f"- Next interaction due by: {_format_date_label(next_due_date)}.")

    if next_task_due_date:
        task_line = f"- Earliest open follow-up task: {_format_date_label(next_task_due_date)}"
        if next_task_title:
            task_line += f" | {next_task_title}"
        lines.append(task_line + ".")

    lines.append("If you want, I can create the follow-up task now with that due date.")
    return "\n".join(lines)


def _contact_schedule_context_block(snapshot: dict) -> str:
    cadence_days = int(snapshot.get("cadence_days") or 14)
    relationship_label = str(snapshot.get("relationship_label") or "Relationship stage").strip()
    next_due_date = snapshot.get("next_due_date")
    today = snapshot.get("today")
    overdue_days = int(snapshot.get("overdue_days") or 0)
    last_interaction_at = snapshot.get("last_interaction_at")
    last_contact_line = _format_date_label(last_interaction_at) if last_interaction_at else "Not recorded"
    due_line = _format_date_label(next_due_date) if next_due_date else _format_date_label(today)
    overdue_line = f"Overdue by {overdue_days} days" if overdue_days > 0 else "Within cadence"
    return (
        "Contact cadence context:\n"
        f"- Cadence target: every {cadence_days} days ({relationship_label})\n"
        f"- Last meaningful interaction: {last_contact_line}\n"
        f"- Next interaction due: {due_line} ({overdue_line})"
    )


def _contact_schedule_sources(snapshot: dict) -> list[dict]:
    relationship_label = str(snapshot.get("relationship_label") or "").strip()
    relationship_code = str(snapshot.get("relationship_code") or "").strip()
    cadence_days = int(snapshot.get("cadence_days") or 14)
    last_interaction_at = snapshot.get("last_interaction_at")
    next_due_date = snapshot.get("next_due_date")
    return [
        {
            "label": "Relationship stage",
            "detail": f"{relationship_code} {relationship_label}".strip(),
            "origin": "REL_INTEL_RUN.briefing_json.relationship_business_flow_stage2.relationship_stage",
        },
        {
            "label": "Cadence target",
            "detail": f"{cadence_days} days",
            "origin": "Stage cadence rule map",
        },
        {
            "label": "Last meaningful interaction",
            "detail": _format_date_label(last_interaction_at) if last_interaction_at else "Not recorded",
            "origin": "INTERACTION.interaction_at",
        },
        {
            "label": "Next interaction due",
            "detail": _format_date_label(next_due_date),
            "origin": "Derived from last interaction + cadence target",
        },
    ]


def _contact_schedule_quick_actions(snapshot: dict) -> list[dict]:
    due_date = snapshot.get("next_due_date")
    if due_date is None:
        return []
    person_name = str(snapshot.get("person_name") or "this contact").strip()
    due_label = _format_date_label(due_date)
    return [
        {
            "kind": "create_task",
            "label": f"Create Follow-Up Task ({due_label})",
            "title": f"Follow up with {person_name}",
            "due_date": str(due_date),
            "due_time": "09:00",
            "priority": "medium",
        }
    ]


def _message_requests_db_query_help(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    return any(
        token in lowered
        for token in (
            "db question",
            "database question",
            "other db",
            "other database",
            "what can i ask the db",
            "what can i ask the database",
        )
    )


def _extract_company_query_term(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    patterns = (
        r"\b(?:show|list|find|get)?\s*(?:me\s+)?(?:everyone|all(?:\s+contacts|\s+people)?|who(?:\s+else)?)\s+(?:who\s+)?(?:works?|work)\s+for\s+(.+)$",
        r"\b(?:show|list|find|get)?\s*(?:me\s+)?(?:everyone|all(?:\s+contacts|\s+people)?|who(?:\s+else)?)\s+at\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        term = str(match.group(1) or "").strip()
        term = re.split(r"\b(?:in\s+the\s+db|in\s+database|database|db)\b", term, maxsplit=1, flags=re.IGNORECASE)[0]
        term = term.strip(" \t\n\r.,!?;:\"'()[]{}")
        if len(term) < 2:
            return ""
        lowered = term.lower()
        if any(noise in lowered for noise in ("other db", "other database", "question", "etc")):
            return ""
        return term
    return ""


def _message_requests_overdue_contacts(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    patterns = (
        r"\boverdue\s+contacts?\b",
        r"\boutside\s+cadence\b",
        r"\bwho\s+is\s+overdue\b",
        r"\bcontacts?\s+(?:past|outside)\s+(?:their\s+)?cadence\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _message_requests_missing_career_history(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    patterns = (
        r"\bno\s+career\s+history\b",
        r"\bmissing\s+career\s+history\b",
        r"\bno\s+career\s+background\b",
        r"\bmissing\s+career\s+background\b",
        r"\bwithout\s+career\s+history\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def _query_contacts_by_company(company_term: str, limit: int = 30) -> dict:
    term = str(company_term or "").strip()
    if not term:
        return {}
    conn = None
    rows: list[dict] = []
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT person_id, full_name, title_current, company_name_raw
            FROM PERSON
            WHERE is_active = 1
              AND LOWER(COALESCE(company_name_raw, '')) LIKE ?
            ORDER BY LOWER(COALESCE(full_name, '')) ASC
            LIMIT ?
            """,
            (f"%{term.lower()}%", int(limit)),
        )
        rows = [dict(row) for row in c.fetchall()]
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        response = f"No active contacts found for company match '{term}'."
    else:
        lines = [f"Found {len(rows)} active contact(s) matching company '{term}':"]
        for row in rows[:20]:
            full_name = str(row.get("full_name") or "Unknown").strip()
            title = str(row.get("title_current") or "").strip()
            company = str(row.get("company_name_raw") or "").strip()
            if title and company:
                lines.append(f"- {full_name} | {title} | {company}")
            elif title:
                lines.append(f"- {full_name} | {title}")
            else:
                lines.append(f"- {full_name}")
        if len(rows) > 20:
            lines.append(f"...and {len(rows) - 20} more.")
        response = "\n".join(lines)

    return {
        "response": response,
        "result_type": "db_query",
        "sources": [
            {
                "label": "Database query",
                "detail": f"PERSON company_name_raw LIKE '%{term}%' (active contacts only)",
                "origin": "PERSON table",
            },
            {
                "label": "Rows returned",
                "detail": str(len(rows)),
                "origin": "SQLite query result",
            },
        ],
        "quick_actions": [],
    }


def _query_overdue_contacts(limit: int = 30) -> dict:
    today = datetime.now(timezone.utc).date()
    conn = None
    rows: list[dict] = []
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT person_id, full_name, title_current, company_name_raw, next_contact_due_date
            FROM PERSON
            WHERE is_active = 1
              AND COALESCE(next_contact_due_date, '') != ''
              AND DATE(next_contact_due_date) < DATE(?)
            ORDER BY DATE(next_contact_due_date) ASC, LOWER(COALESCE(full_name, '')) ASC
            LIMIT ?
            """,
            (str(today), int(limit)),
        )
        rows = [dict(row) for row in c.fetchall()]
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        response = f"No active contacts are currently overdue against next_contact_due_date as of {today.isoformat()}."
    else:
        lines = [f"Overdue contacts ({len(rows)}) as of {today.isoformat()}:"]
        for row in rows[:20]:
            name = str(row.get("full_name") or "Unknown").strip()
            title = str(row.get("title_current") or "").strip()
            due_raw = str(row.get("next_contact_due_date") or "").strip()
            try:
                due_date = datetime.strptime(due_raw, "%Y-%m-%d").date()
                overdue_days = max(0, (today - due_date).days)
                due_line = f"{due_raw} ({overdue_days}d overdue)"
            except Exception:
                due_line = due_raw or "Unknown"
            if title:
                lines.append(f"- {name} | {title} | due {due_line}")
            else:
                lines.append(f"- {name} | due {due_line}")
        if len(rows) > 20:
            lines.append(f"...and {len(rows) - 20} more.")
        response = "\n".join(lines)

    return {
        "response": response,
        "result_type": "db_query",
        "sources": [
            {
                "label": "Database query",
                "detail": "PERSON next_contact_due_date < today (active contacts only)",
                "origin": "PERSON table",
            },
            {
                "label": "As of date",
                "detail": str(today),
                "origin": "UTC system date",
            },
            {
                "label": "Rows returned",
                "detail": str(len(rows)),
                "origin": "SQLite query result",
            },
        ],
        "quick_actions": [],
    }


def _query_missing_career_history(limit: int = 30) -> dict:
    conn = None
    rows: list[dict] = []
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT person_id, full_name, title_current, company_name_raw
            FROM PERSON
            WHERE is_active = 1
              AND (
                    COALESCE(TRIM(employment_history), '') = ''
                 OR TRIM(employment_history) = '[]'
                 OR (
                        COALESCE(TRIM(career_summary), '') = ''
                    AND COALESCE(TRIM(title_current), '') = ''
                 )
              )
            ORDER BY LOWER(COALESCE(full_name, '')) ASC
            LIMIT ?
            """,
            (int(limit),),
        )
        rows = [dict(row) for row in c.fetchall()]
    finally:
        if conn is not None:
            conn.close()

    if not rows:
        response = "No active contacts are currently missing career history/background."
    else:
        lines = [f"Contacts missing career history/background ({len(rows)}):"]
        for row in rows[:20]:
            name = str(row.get("full_name") or "Unknown").strip()
            title = str(row.get("title_current") or "").strip()
            company = str(row.get("company_name_raw") or "").strip()
            if title and company:
                lines.append(f"- {name} | {title} | {company}")
            elif company:
                lines.append(f"- {name} | {company}")
            else:
                lines.append(f"- {name}")
        if len(rows) > 20:
            lines.append(f"...and {len(rows) - 20} more.")
        response = "\n".join(lines)

    return {
        "response": response,
        "result_type": "db_query",
        "sources": [
            {
                "label": "Database query",
                "detail": "PERSON missing employment_history/career_summary fields (active contacts only)",
                "origin": "PERSON table",
            },
            {
                "label": "Rows returned",
                "detail": str(len(rows)),
                "origin": "SQLite query result",
            },
        ],
        "quick_actions": [],
    }


def _run_profile_chat_db_query(message: str) -> Optional[dict]:
    text = str(message or "").strip()
    if not text:
        return None
    if _message_requests_db_query_help(text):
        return {
            "response": (
                "Yes. You can ask DB questions like:\n"
                "- show everyone who works for AtkinsRealis\n"
                "- show overdue contacts\n"
                "- who has no career history"
            ),
            "result_type": "db_query_help",
            "sources": [
                {
                    "label": "Query mode",
                    "detail": "Supported contact DB query templates",
                    "origin": "Profile assistant deterministic query handler",
                }
            ],
            "quick_actions": [],
        }

    company_term = _extract_company_query_term(text)
    if company_term:
        return _query_contacts_by_company(company_term)
    if _message_requests_overdue_contacts(text):
        return _query_overdue_contacts()
    if _message_requests_missing_career_history(text):
        return _query_missing_career_history()
    return None


def _load_latest_stage2_flow(person_id: str) -> dict:
    conn = None
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT briefing_json
            FROM REL_INTEL_RUN
            WHERE person_id = ?
              AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (person_id,),
        )
        row = c.fetchone()
        if row:
            payload = json.loads(row["briefing_json"] or "{}")
            stage2 = payload.get("relationship_business_flow_stage2")
            stage2 = stage2 if isinstance(stage2, dict) else {}
        else:
            stage2 = {}
        c.execute(
            """
            SELECT relationship_stage_override, stage_override_source_interaction_id, stage_override_updated_at
            FROM PERSON
            WHERE person_id = ?
            """,
            (person_id,),
        )
        person_row = c.fetchone()
        if not person_row:
            return stage2

        override_code = str(person_row["relationship_stage_override"] or "").strip().upper()
        if not override_code:
            stage2["override"] = {
                "active": False,
                "relationship_stage_override": None,
                "source_interaction_id": None,
                "updated_at": str(person_row["stage_override_updated_at"] or "").strip() or None,
                "inferred_relationship_stage_code": str(((stage2.get("relationship_stage") or {}).get("code")) or "").strip().upper() or None,
            }
            return stage2

        inferred_code = str(((stage2.get("relationship_stage") or {}).get("code")) or "").strip().upper() or None
        detail = STAGE2_RELATIONSHIP_STAGE_DETAILS.get(override_code) or {}
        current = stage2.get("relationship_stage") if isinstance(stage2.get("relationship_stage"), dict) else {}
        stage2["relationship_stage"] = {
            "code": override_code,
            "label": str(detail.get("label") or current.get("label") or override_code),
            "summary": str(detail.get("summary") or current.get("summary") or ""),
            "confidence_pct": max(80, int(current.get("confidence_pct") or 0)),
            "reasons": [
                "Manual override set from transcript review.",
                *(
                    current.get("reasons")
                    if isinstance(current.get("reasons"), list)
                    else []
                ),
            ][:8],
            "override": True,
        }
        stage2["override"] = {
            "active": True,
            "relationship_stage_override": override_code,
            "source_interaction_id": str(person_row["stage_override_source_interaction_id"] or "").strip() or None,
            "updated_at": str(person_row["stage_override_updated_at"] or "").strip() or None,
            "inferred_relationship_stage_code": inferred_code,
        }
        if override_code not in {"S8", "S9"}:
            stage2["opportunity_stage"] = None
        return stage2
    except Exception:
        return {}
    finally:
        if conn is not None:
            conn.close()


def _render_stage_list_response(stage2_flow: dict) -> str:
    relationship_order = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
    opportunity_order = ["O1", "O2", "O3", "O4", "O5", "O6", "O7"]
    opportunity_legacy_map = {
        "S5": "O1",
        "S6": "O2",
        "S7": "O3",
        "S5M": "O4",
        "S6M": "O5",
        "S7M": "O6",
        "S8": "O7",
        "R1": "O1",
        "R2": "O2",
        "R3": "O3",
        "R4": "O4",
        "R5": "O5",
        "R6": "O6",
        "R7": "O7",
    }

    current_relationship = str(((stage2_flow.get("relationship_stage") or {}).get("code")) or "")
    current_opportunity = str(((stage2_flow.get("opportunity_stage") or {}).get("code")) or "").strip().upper()
    current_opportunity = opportunity_legacy_map.get(current_opportunity, current_opportunity)

    relationship_lines = []
    for code in relationship_order:
        label = str((STAGE2_RELATIONSHIP_STAGE_DETAILS.get(code) or {}).get("label") or code)
        marker = " [CURRENT]" if code == current_relationship else ""
        relationship_lines.append(f"- {label}{marker}")

    opportunity_lines = []
    for code in opportunity_order:
        label = str((STAGE2_OPPORTUNITY_STAGE_DETAILS.get(code) or {}).get("label") or code)
        marker = " [CURRENT]" if code == current_opportunity else ""
        opportunity_lines.append(f"- {label}{marker}")

    if not current_relationship:
        relationship_lines.append("- No relationship stage retained yet.")
    if not current_opportunity:
        opportunity_lines.append("- No opportunity stage retained yet.")

    return (
        "Relationship Stages\n"
        + "\n".join(relationship_lines)
        + "\n\nOpportunity Stages\n"
        + "\n".join(opportunity_lines)
    )



async def process_text(text: str, channel: str, person_id: Optional[str] = None) -> dict:
    """
    Process raw interaction text with GPT-4o.
    Raises on model failure so the caller can preserve the artifact and retry safely.
    """
    tax_block = _get_taxonomy_block()
    calibration_block = _get_success_calibration_block()

    prompt = f"""Analyze this CRM interaction and return a JSON object.

TAXONOMY (use ONLY these exact values for profile_updates):
{tax_block}

{calibration_block}
CHANNEL: {channel}
INTERACTION TEXT:
"{text[:8000]}"

Return JSON with these exact keys:
- summary: 1 sentence factual summary
- summary should preserve the useful substance in 1-2 sentences, not a vague headline
- sentiment: Positive | Negative | Neutral | Mixed | Unclear
- sentiment_confidence: number 0..1
- topics: array of up to 3 keyword strings
- action_items: array of follow-up task strings (empty if none)
- profile_updates: dict of fieldâ†’value to update on the person's profile.
  Allowed fields: {', '.join(sorted(ALLOWED_PROFILE_FIELDS))}.
  (IMPORTANT: NEVER include manual notes or gossip here. Facts go to topic_nuggets.)
- topic_nuggets: array of intelligence objects with keys:
    - topic: one of business_focus | recruitment_talent | family_personal | obe_focus
    - business_subtopic: one of business_interests | market_pulse | leadership_view | commercial_position | operational_pressure when topic is business_focus, otherwise empty
    - text: briefing-grade signal text that preserves the real decision logic, commercial caveats, or relationship substance; not a raw quote, not banter, not gossip, not profanity, and not a conversational fragment
    - snippet: evidence excerpt from the source with enough surrounding context to retain meaning, trimmed to remove fluff
    - confidence: number 0..1
    - sentiment: Positive | Negative | Neutral | Mixed | Unclear
- For transcript, chat, email, and screenshot-derived text, prefer one strong context-rich nugget per real topic over several thin generic abstractions.
- When the source contains a concrete next step, invitation, or date-linked follow-up, include a specific action_item.
- Social and relationship follow-ups count when they are explicit, for example coffee after Eid, a promised call next week, or an agreed catch-up.
- Never write speculative filler such as "could be a rapport-building point", "may suggest", or similar language.
- Skip topic_nuggets entirely when the source only contains chatter, jokes, insults, vague opinions, or project-specific detail that is not broadly useful for future relationship intelligence.
- Do not create Recruitment & Talent nuggets unless the source explicitly discusses hiring, team build, retention, staffing pressure, or a specific role.
- Do not create OBE Focus nuggets unless OBE, a network event, membership activity, or a clearly OBE-relevant initiative is explicitly mentioned.
- success_metrics: object with:
    - rating: 1-5 (1=low/admin, 3=meaningful, 5=game-changing win for TS/OBE)
    - engagement_value: 0-100 (weighted by depth/trust)
    - is_strategic: 0 or 1 (1 if moves the needle on recruitment, brand, or OBE network)
    - tags: array (e.g. "brand_win", "recruitment_lead", "obe_engagement")
- global_insights: array of knowledge items for the PLATFORM level (not just this person).
    - e.g. {{"type": "market_trend", "text": "Data centers in KSA are expanding", "entity": "KSA Data Centers"}}
    - e.g. {{"type": "company_shift", "text": "Stantec is shifting to BIM-first", "entity": "Stantec"}}
"""
    data, _run_id = await run_json_chat_task(
        task_type="text_extraction",
        prompt_family="interaction_extraction_v2",
        messages=[
            {"role": "system", "content": "You are a precise CRM data extraction engine. Return only valid JSON and never invent facts."},
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o",
        temperature=0.2,
        client_getter=_get_client,
        related_profile_id=person_id,
        metadata={"channel": channel},
    )
    data.setdefault("summary", "")
    data.setdefault("sentiment", "Unclear")
    data.setdefault("sentiment_confidence", 0.5)
    data.setdefault("topics", [])
    data.setdefault("action_items", [])
    data.setdefault("profile_updates", {})
    data.setdefault("topic_nuggets", [])
    data.setdefault("success_metrics", {})
    data.setdefault("global_insights", [])
    for nugget in data["topic_nuggets"]:
        if not isinstance(nugget, dict):
            continue
        nugget["text"] = strip_speculative_filler(nugget.get("text"))
        nugget["snippet"] = _trim_supporting_evidence(nugget.get("snippet") or nugget.get("text"))
        if (nugget.get("topic") or "").strip().lower() == "business_focus":
            nugget["business_subtopic"] = canonical_business_subtopic(nugget.get("business_subtopic")) or infer_business_subtopic(
                nugget.get("text"),
                nugget.get("snippet"),
            )
        else:
            nugget["business_subtopic"] = None
    data["summary"] = strip_speculative_filler(data.get("summary"))
    try:
        transcript_enrichment = await _enrich_transcript_result(
            text=text,
            source_type=channel,
            title=f"{channel.title()} interaction",
        )
        if transcript_enrichment:
            if transcript_enrichment.get("summary"):
                data["summary"] = transcript_enrichment["summary"]
            if transcript_enrichment.get("topic_nuggets"):
                data["topic_nuggets"] = transcript_enrichment["topic_nuggets"]
            if transcript_enrichment.get("action_items"):
                data["action_items"] = _dedupe_action_items(
                    list(data.get("action_items") or []) + list(transcript_enrichment.get("action_items") or [])
                )
    except Exception as e:
        print(f"Transcript enrichment error: {e}")
    return data



async def extract_document_profile(text: str) -> dict:
    """
    Extract profile facts and employment history from a CV/profile PDF.
    """
    prompt = f"""Extract structured CRM profile data from this profile or CV text.

DOCUMENT TEXT:
\"{text[:16000]}\"

Return JSON with these exact keys:
- full_name: best-contact full name if clearly present, else empty string
- title_current: current role title if clearly present, else empty string
- company_name_raw: current company/employer if clearly present, else empty string
- email_primary: primary email if clearly present, else empty string
- phone_primary: primary phone number if clearly present, else empty string
- linkedin_url: linkedin profile URL if clearly present, else empty string
- career_summary: short factual summary of the person's career
- key_professional_notes: short practical notes about skills, sectors, or strengths
- employment_history: array of roles in reverse-chronological order

Each employment_history item must be an object with:
- title
- company
- start_date
- end_date
- location
- description

Rules:
- Use empty string if a field is unknown.
- Do not invent employers, dates, or roles.
- Prefer YYYY-MM when month is known, otherwise YYYY.
- Leave end_date empty for current roles.
- Return only valid JSON.
"""
    data, _run_id = await run_json_chat_task(
        task_type="document_profile_extraction",
        prompt_family="document_profile_v2",
        messages=[
            {"role": "system", "content": "You extract structured career history from CVs. Return only valid JSON and do not guess unknown facts."},
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o",
        temperature=0.1,
        client_getter=_get_client,
    )
    roles = data.get("employment_history")
    if not isinstance(roles, list):
        data["employment_history"] = []
    else:
        cleaned = []
        for role in roles:
            if not isinstance(role, dict):
                continue
            cleaned.append({
                "title": str(role.get("title") or "").strip(),
                "company": str(role.get("company") or "").strip(),
                "start_date": str(role.get("start_date") or "").strip(),
                "end_date": str(role.get("end_date") or "").strip(),
                "location": str(role.get("location") or "").strip(),
                "description": str(role.get("description") or "").strip(),
            })
        data["employment_history"] = cleaned
    data["full_name"] = str(data.get("full_name") or "").strip()
    data["title_current"] = str(data.get("title_current") or "").strip()
    data["company_name_raw"] = str(data.get("company_name_raw") or "").strip()
    data["email_primary"] = str(data.get("email_primary") or "").strip()
    data["phone_primary"] = str(data.get("phone_primary") or "").strip()
    data["linkedin_url"] = str(data.get("linkedin_url") or "").strip()
    data.setdefault("career_summary", "")
    data.setdefault("key_professional_notes", "")
    return data
async def realign_interaction(text: str, channel: str, feedback: str, person_id: Optional[str] = None) -> dict:
    """
    Re-processes raw interaction text incorporating explicit user feedback to correct hallucinations.
    """
    tax_block = _get_taxonomy_block()
    calibration_block = _get_success_calibration_block()

    prompt = f"""You are a precise CRM data extraction engine.
You previously analyzed the following interaction, but the user provided the following CORRECTIVE FEEDBACK:
"{feedback}"

You MUST re-analyze the text, strictly incorporating the user's feedback to correct any previous errors, hallucinations, or misdirections.

TAXONOMY (use ONLY these exact values for profile_updates):
{tax_block}

{calibration_block}
CHANNEL: {channel}
INTERACTION TEXT:
"{text[:8000]}"

Return JSON with these exact keys:
- summary: 1 sentence factual summary (adjusted by feedback)
- summary should preserve the useful substance in 1-2 sentences, not a vague headline
- sentiment: Positive | Negative | Neutral | Mixed | Unclear
- sentiment_confidence: number 0..1
- topics: array of up to 3 keyword strings
- action_items: array of follow-up strings (adjusted by feedback)
- profile_updates: object mapping taxonomy categories (cat, env, disc) to their STRICT exact value strings.
- topic_nuggets: array of {{topic, text, snippet, confidence, sentiment}} for business_focus, recruitment_talent, family_personal, obe_focus
- topic_nuggets business items may also include business_subtopic using the approved business subtopic list
- topic_nuggets should preserve meaningful commercial, relationship, or event context rather than reducing everything to thin labels
- If the interaction contains an explicit social or commercial follow-up, keep it in action_items as a concrete next step.
- Never use speculative filler such as "could be a rapport-building point" or "may suggest".
- success_metrics: object with rating (1-5), engagement_value (0-100), is_strategic (0/1), tags (array)
- global_insights: array of {{type, text, entity}} for platform-wide learning"""
    data, _run_id = await run_json_chat_task(
        task_type="text_realign",
        prompt_family="interaction_realign_v2",
        messages=[{"role": "user", "content": prompt}],
        model="gpt-4o",
        temperature=0.2,
        client_getter=_get_client,
        related_profile_id=person_id,
        metadata={"channel": channel},
    )
    data.setdefault("summary", "")
    data.setdefault("sentiment", "Unclear")
    data.setdefault("sentiment_confidence", 0.5)
    data.setdefault("topics", [])
    data.setdefault("action_items", [])
    data.setdefault("profile_updates", {})
    data.setdefault("topic_nuggets", [])
    data.setdefault("success_metrics", {})
    data.setdefault("global_insights", [])
    for nugget in data["topic_nuggets"]:
        if not isinstance(nugget, dict):
            continue
        nugget["text"] = strip_speculative_filler(nugget.get("text"))
        nugget["snippet"] = _trim_supporting_evidence(nugget.get("snippet") or nugget.get("text"))
        if (nugget.get("topic") or "").strip().lower() == "business_focus":
            nugget["business_subtopic"] = canonical_business_subtopic(nugget.get("business_subtopic")) or infer_business_subtopic(
                nugget.get("text"),
                nugget.get("snippet"),
            )
        else:
            nugget["business_subtopic"] = None
    data["summary"] = strip_speculative_filler(data.get("summary"))
    try:
        transcript_enrichment = await _enrich_transcript_result(
            text=text,
            source_type=channel,
            title=f"{channel.title()} interaction",
        )
        if transcript_enrichment:
            if transcript_enrichment.get("summary"):
                data["summary"] = transcript_enrichment["summary"]
            if transcript_enrichment.get("topic_nuggets"):
                data["topic_nuggets"] = transcript_enrichment["topic_nuggets"]
            if transcript_enrichment.get("action_items"):
                data["action_items"] = _dedupe_action_items(
                    list(data.get("action_items") or []) + list(transcript_enrichment.get("action_items") or [])
                )
    except Exception as e:
        print(f"Transcript enrichment error: {e}")
    return data


def _normalize_image_analysis_payload(payload: Any) -> dict:
    data = dict(payload) if isinstance(payload, dict) else {}

    photo_val = data.get("is_profile_photo", False)
    if isinstance(photo_val, str):
        is_profile_photo = photo_val.strip().lower() == "true"
    else:
        is_profile_photo = bool(photo_val)

    image_type = str(data.get("image_type") or "").strip().lower()
    if image_type not in {"screenshot", "profile_picture", "general_image", "uncertain"}:
        image_type = "profile_picture" if is_profile_photo else "general_image"

    try:
        image_confidence = float(data.get("image_type_confidence") or 0.75)
    except (TypeError, ValueError):
        image_confidence = 0.75
    image_confidence = max(min(image_confidence, 1.0), 0.0)

    screen_context = str(data.get("screen_context") or "uncertain").strip().lower() or "uncertain"
    source_app = str(data.get("source_app") or "unknown").strip().lower() or "unknown"
    extracted_text = str(data.get("extracted_text") or "").strip()
    summary = str(data.get("summary") or "").strip()
    summary_lower = summary.lower()
    screenshot_contexts = {"whatsapp_chat", "email", "browser_ui", "application_ui", "document_capture", "other_screen_content"}

    if screen_context in screenshot_contexts:
        is_profile_photo = False
    elif image_type == "profile_picture" and image_confidence >= 0.55:
        is_profile_photo = True
    elif (
        any(token in summary_lower for token in ("headshot", "portrait", "profile photo", "profile picture"))
        and image_type != "screenshot"
        and len(extracted_text) < 80
    ):
        is_profile_photo = True

    if len(extracted_text) >= 120 and image_type != "profile_picture":
        is_profile_photo = False

    if is_profile_photo:
        if image_type in {"uncertain", "general_image"}:
            image_type = "profile_picture"
            image_confidence = max(image_confidence, 0.8)
    else:
        if image_type == "profile_picture" and screen_context in screenshot_contexts:
            image_type = "screenshot"
            image_confidence = max(image_confidence, 0.7)

    data["is_profile_photo"] = bool(is_profile_photo)
    data["image_type"] = image_type
    data["image_type_confidence"] = image_confidence
    data["screen_context"] = screen_context
    data["source_app"] = source_app
    data["summary"] = summary
    data["extracted_text"] = extracted_text
    data["topics"] = data.get("topics") if isinstance(data.get("topics"), list) else []
    data["action_items"] = data.get("action_items") if isinstance(data.get("action_items"), list) else []
    data["topic_nuggets"] = data.get("topic_nuggets") if isinstance(data.get("topic_nuggets"), list) else []
    data["contact_info"] = data.get("contact_info") if isinstance(data.get("contact_info"), dict) else {}
    data["sentiment"] = str(data.get("sentiment") or "Unclear")
    try:
        data["sentiment_confidence"] = float(data.get("sentiment_confidence") or 0.5)
    except (TypeError, ValueError):
        data["sentiment_confidence"] = 0.5
    data["success_metrics"] = data.get("success_metrics") if isinstance(data.get("success_metrics"), dict) else {}
    data["global_insights"] = data.get("global_insights") if isinstance(data.get("global_insights"), list) else []
    return data


async def process_image(image_path: str, person_id: Optional[str] = None) -> dict:
    """Extract intelligence from a screenshot or photo using GPT-4o Vision."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    ext = os.path.splitext(image_path)[1].lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

    calibration_block = _get_success_calibration_block()
    data, _run_id = await run_json_chat_task(
        task_type="image_extraction",
        prompt_family="vision_image_intake_v2",
        model="gpt-4o",
        client_getter=_get_client,
        related_profile_id=person_id,
        metadata={"image_path": image_path},
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"""Analyze this image and return valid JSON only.

{calibration_block}
Rules:
- Distinguish screenshots from profile pictures/headshots and general images.
- If this is a profile picture or headshot, identify it only. Do not infer relationship facts from it.
- If readable text is present, extract it faithfully and keep ambiguity visible.
- If the screenshot is clearly WhatsApp, email, browser UI, app UI, or a document capture, identify that explicitly.

Return JSON with:
- image_type: screenshot | profile_picture | general_image | uncertain
- image_type_confidence: number 0..1
- screen_context: whatsapp_chat | email | browser_ui | application_ui | document_capture | other_screen_content | uncertain
- source_app: whatsapp | outlook | gmail | teams | linkedin | browser | unknown
- summary: What this image shows
- extracted_text: readable text visible in the image, empty if none
- sentiment: Positive | Negative | Neutral | Mixed | Unclear
- sentiment_confidence: number 0..1
- topics: key topics
- action_items: any follow-ups visible
- topic_nuggets: array of {{topic, text, snippet, confidence, sentiment}} for business_focus, recruitment_talent, family_personal, obe_focus
- Each topic_nugget text must be a clean CRM-ready intelligence statement, not a verbatim chat fragment, not profanity, and not throwaway banter.
- If the screenshot shows an explicit invitation or agreed follow-up, include a concrete action_item rather than leaving it implicit.
- If the screenshot is only loosely relevant or too project-specific to reuse later, return an empty topic_nuggets array.
- contact_info: {{name, email, phone, company, title, linkedin}} if visible
- is_profile_photo: true if the image contains a person's face, portrait, or headshot
- success_metrics: object with rating (1-5), engagement_value (0-100), is_strategic (0/1), tags (array)
- global_insights: array of {{type, text, entity}} for platform-wide learning"""},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
    )
    data = _normalize_image_analysis_payload(data)
    data["summary"] = strip_speculative_filler(data.get("summary"))
    for nugget in data["topic_nuggets"]:
        if not isinstance(nugget, dict):
            continue
        nugget["text"] = strip_speculative_filler(nugget.get("text"))
        nugget["snippet"] = _trim_supporting_evidence(nugget.get("snippet") or nugget.get("text"))
        if (nugget.get("topic") or "").strip().lower() == "business_focus":
            nugget["business_subtopic"] = canonical_business_subtopic(nugget.get("business_subtopic")) or infer_business_subtopic(
                nugget.get("text"),
                nugget.get("snippet"),
            )
        else:
            nugget["business_subtopic"] = None
    try:
        transcript_enrichment = await _enrich_transcript_result(
            text=data.get("extracted_text") or "",
            source_type=data.get("source_app") or data.get("screen_context") or data.get("image_type") or "image",
            title=os.path.basename(image_path),
        )
        if transcript_enrichment and data.get("image_type") != "profile_picture":
            if transcript_enrichment.get("summary"):
                data["summary"] = transcript_enrichment["summary"]
            if transcript_enrichment.get("topic_nuggets"):
                data["topic_nuggets"] = transcript_enrichment["topic_nuggets"]
            if transcript_enrichment.get("action_items"):
                data["action_items"] = _dedupe_action_items(
                    list(data.get("action_items") or []) + list(transcript_enrichment.get("action_items") or [])
                )
    except Exception as e:
        print(f"Image transcript enrichment error: {e}")
    return data


async def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file using OpenAI Whisper."""
    with open(audio_path, "rb") as f:
        transcript, _run_id = await run_audio_transcription_task(
            file_handle=f,
            client_getter=_get_client,
        )
    return transcript


async def generate_tts(text: str, voice: str = "shimmer") -> bytes:
    """Generate MP3 audio from text using OpenAI TTS."""
    audio_bytes, _run_id = await run_speech_task(
        text=text,
        voice=voice,
        model="tts-1-hd",
        client_getter=_get_client,
    )
    return audio_bytes



async def compute_signal_scores(person_id: str) -> dict:
    """Compute a numeric score for each signal using explicit structured feedback plus learned preference weights."""
    scores = {}
    try:
        preference_profile = await compute_preference_profile(person_id)
        preference_scores = preference_profile.get("scores", {})
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT intel_id AS signal_id, topic AS category, intel_text AS content, created_at, 'topic_intelligence' AS source_kind
            FROM TOPIC_INTELLIGENCE
            WHERE person_id=?
            UNION ALL
            SELECT signal_id AS signal_id, category, content, created_at, 'ai_signal' AS source_kind
            FROM AI_SIGNAL
            WHERE person_id=?
            """,
            (person_id, person_id),
        )
        for signal_id, category, content, created_at, source_kind in c.fetchall():
            text = str(content or "")
            word_count = len(text.split())
            score = 0.0
            category_key = str(category or "").strip().lower()
            if category_key in {"business_focus", "recruitment_talent", "business focus", "recruitment & talent"}:
                score += preference_scores.get("commercially_useful_content", 0.0)
                score += preference_scores.get("practical_meeting_preparation", 0.0) * 0.5
            if category_key in {"family_personal", "obe_focus", "family & personal", "obe focus"}:
                score += preference_scores.get("relationship_relevant_content", 0.0)
            if word_count and word_count <= 35:
                score += preference_scores.get("concise_summaries", 0.0)
                score += preference_scores.get("minimal_fluff", 0.0)
            elif word_count >= 80:
                score -= abs(preference_scores.get("minimal_fluff", 0.0))
            scores[signal_id] = score

        c.execute(
            """
            SELECT target_id, event_type
            FROM AI_FEEDBACK
            WHERE target_type='signal' AND target_id IN (
                SELECT intel_id FROM TOPIC_INTELLIGENCE WHERE person_id=?
                UNION
                SELECT signal_id FROM AI_SIGNAL WHERE person_id=?
            )
            """,
            (person_id, person_id),
        )
        for target_id, event_type in c.fetchall():
            normalized = normalize_feedback_event(event_type)
            scores[target_id] = scores.get(target_id, 0.0) + EVENT_WEIGHTS.get(normalized, 0.0)
        conn.close()
    except Exception as e:
        print(f"Score computation error: {e}")
    return scores


def _coerce_brief_text(value) -> str:
    if isinstance(value, str):
        return strip_speculative_filler(value)
    if isinstance(value, dict):
        for key in ("summary", "text", "content"):
            candidate = _coerce_brief_text(value.get(key))
            if candidate:
                return candidate
        return " ".join(
            part for part in (_coerce_brief_text(item) for item in value.values()) if part
        ).strip()
    if isinstance(value, list):
        return " ".join(part for part in (_coerce_brief_text(item) for item in value) if part).strip()
    return ""


def _fallback_brief_from_signals(person: dict, signals: list, events: list, preference_profile: dict) -> dict:
    grouped = {
        "business_focus": [],
        "recruitment_talent": [],
        "family_personal": [],
        "obe_focus": [],
    }
    for signal in signals:
        category = signal.get("primary_category") or signal.get("category")
        if category in grouped:
            grouped[category].append(signal)

    def _section_text(category: str, empty_text: str) -> str:
        items = grouped.get(category) or []
        if not items:
            return empty_text
        return " ".join(
            str(item.get("signal_text") or item.get("text") or item.get("content") or "").strip()
            for item in items[:3]
            if str(item.get("signal_text") or item.get("text") or item.get("content") or "").strip()
        )[:1200] or empty_text

    event_line = ""
    if events:
        event_line = " Upcoming events: " + "; ".join(
            f"{event.get('event_name')} on {str(event.get('event_date') or '')[:10]} ({event.get('status') or ''})"
            for event in events[:3]
        )
    business = _section_text("business_focus", "No business focus signals confirmed yet.")
    recruitment = _section_text("recruitment_talent", "No recruitment or talent signals confirmed yet.")
    personal = _section_text("family_personal", "No family or personal rapport signals confirmed yet.")
    obe = _section_text("obe_focus", "No OBE focus signals confirmed yet.")
    overall = " ".join(part for part in (business, recruitment, personal, obe) if part).strip()
    return {
        "business_focus": business,
        "recruitment_talent": recruitment,
        "personal_rapport": personal,
        "obe_focus": obe,
        "overall_brief_summary": overall[:1800],
        "strategic_hypotheses": [
            "Validate the most recent business signal and test whether it remains active.",
            "Confirm whether current talent pressure is acute, background noise, or resolved.",
            "Use the strongest rapport hook only if it is well-supported by source evidence.",
        ],
        "audio_script": f"{person.get('full_name') or 'This contact'}: {overall[:450]}{event_line}".strip(),
        "voice": settings.BRIEF_TTS_VOICE,
        "label_recruitment": settings.BRIEF_LABEL_RECRUITMENT,
        "label_obe": settings.BRIEF_LABEL_OBE,
        "preference_profile": preference_profile or {"scores": {}},
    }


async def review_signals(person: dict, signals: list, events: list) -> dict:
    """Review and summarise existing intelligence signals without changing source facts."""
    person_id = person.get("person_id")
    preference_profile = await compute_preference_profile(person_id) if person_id else {"scores": {}}
    if person_id:
        scores = await compute_signal_scores(person_id)
        signals = sorted(
            signals,
            key=lambda signal: (scores.get(signal.get("intel_id") or signal.get("signal_id"), 0), signal.get("date") or ""),
            reverse=True,
        )

    guidance = "\n".join(preference_guidance_lines(preference_profile))
    prompt = f"""You are an intelligence assistant reviewing stored CRM signals for a contact.
You may reorder, label, and compress the signals, but you must not silently change facts.
Hard rules:
- Preserve factual meaning from the stored signal text and source snippet.
- Do not invent names, dates, intent, deals, family details, or commitments.
- If a category is wrong, only correct the category, not the fact itself.
- If the source is ambiguous, keep the ambiguity visible.
- User edits, promotions, demotions, and manual additions override the AI and should stay visible.

Learned user preferences from behaviour:
{guidance}

For each signal, return:
- intel_id
- category
- text
- snippet
- concise_summary
- priority_reason

Then create a meeting brief using only confirmed source facts. Return valid JSON with EXACT keys 'signals' and 'brief'.
The brief must contain EXACT keys:
- business_focus
- recruitment_talent
- personal_rapport
- obe_focus
- strategic_hypotheses
- audio_script
"""
    try:
        result, _run_id = await run_json_chat_task(
            task_type="signal_review",
            prompt_family="signal_review_v2",
            messages=[
                {"role": "system", "content": "You are an elite relationship intelligence system. Return valid JSON only and never fabricate facts."},
                {"role": "user", "content": prompt},
                {"role": "user", "content": f"PERSON:\n{json.dumps(person)}"},
                {"role": "user", "content": f"SIGNALS:\n{json.dumps(signals)}"},
                {"role": "user", "content": f"EVENTS:\n{json.dumps(events)}"},
            ],
            model="gpt-4o",
            temperature=0.2,
            client_getter=_get_client,
            related_profile_id=person_id,
        )
        result.setdefault("preference_profile", preference_profile)
        return result
    except Exception as e:
        print(f"Review signals error: {e}")
        return {
            "signals": signals,
            "brief": _fallback_brief_from_signals(person, signals, events, preference_profile),
            "preference_profile": preference_profile,
        }


async def generate_briefing(person: dict, signals: list, events: list = None, preference_profile: dict = None) -> dict:
    """
    Generate a world-class meeting brief from signals only.
    """
    signals = signals or []
    events = events or []
    intel_text = ""
    for item in signals[:20]:
        category = (item.get("primary_category") or item.get("category") or "unknown").upper()
        signal_text = strip_speculative_filler(item.get("signal_text") or item.get("text") or item.get("content") or "Fact missing")
        snippet = item.get("source_snippet") or item.get("snippet") or ""
        if (item.get("primary_category") or item.get("category")) == "business_focus" and item.get("business_subtopic_label"):
            category = f"{category}:{item['business_subtopic_label'].upper()}"
        intel_text += f"\n[{category}] {signal_text}"
        if snippet:
            intel_text += f"\nEvidence: {snippet}"

    events_text = ""
    if events:
        events_text = "\nUPCOMING EVENTS:\n" + "\n".join(
            f"- [{e['event_date'][:10]}] {e['event_name']} (status: {e.get('status', '')}) topics: {e.get('topics', '[]')}"
            for e in events
        )

    guidance = "\n".join(preference_guidance_lines(preference_profile or {"scores": {}}))
    prompt = f"""You are an elite personal assistant preparing a meeting brief.
Your goal is to provide a high-density strategic overview and test specific hypotheses.
You must not silently change facts. Only prioritise, compress, and organise what the stored signals, event context, and task context support.
If data is ambiguous, keep the ambiguity visible instead of filling gaps.
User edits, manual additions, promotions, and demotions override the AI ranking.
Never use speculative filler such as "could be a rapport-building point", "may suggest", or similar soft phrasing.

CONTACT: {person.get('full_name') or 'Unknown'} | {person.get('title_current') or 'Contact'} @ {person.get('company_name_raw') or 'Unknown'}
PROFILE: Cat={person.get('cat') or 'GEN'} | Env={person.get('env') or 'Other'} | Disc={person.get('disc') or 'Other'}

LEARNED USER PREFERENCES FROM BEHAVIOUR:
{guidance}

INTELLIGENCE DATABANK:
{intel_text or 'No intel recorded yet.'}

{events_text}

CORE HYPOTHESIS QUESTIONS TO ANSWER:
{settings.BRIEF_HYPOTHESIS_QUESTIONS}

Generate a structured meeting brief as JSON with these EXACT keys:
- business_focus: Strategic priorities, company wins, commercial remit and pipeline focus.
- recruitment_talent: Specific challenges and needs for "{settings.BRIEF_LABEL_RECRUITMENT}".
- personal_rapport: Family, hobbies, travel, values, lifestyle hooks that matter for the relationship.
- obe_focus: Relevant intelligence and opportunities regarding "{settings.BRIEF_LABEL_OBE}".
- strategic_hypotheses: Based on the Core Hypothesis Questions and databank, provide 3 testable theories or follow-up questions for this specific meeting.
- audio_script: A polished 60-second spoken brief for voice playback.

Prioritise concise summaries, commercially useful content, relationship-relevant context, minimal fluff, and practical meeting preparation."""

    try:
        data, _run_id = await run_json_chat_task(
            task_type="brief_generation",
            prompt_family="signal_brief_v2",
            messages=[
                {"role": "system", "content": "You are a precise, elite relationship intelligence system. Return valid JSON only. Never fabricate facts or silently overwrite user intent."},
                {"role": "user", "content": prompt},
            ],
            model="gpt-4o",
            temperature=0.2,
            client_getter=_get_client,
            related_profile_id=person.get("person_id"),
        )
        category_presence = {
            "business_focus": any((item.get("primary_category") or item.get("category")) == "business_focus" for item in signals),
            "recruitment_talent": any((item.get("primary_category") or item.get("category")) == "recruitment_talent" for item in signals),
            "family_personal": any((item.get("primary_category") or item.get("category")) == "family_personal" for item in signals),
            "obe_focus": any((item.get("primary_category") or item.get("category")) == "obe_focus" for item in signals),
        }
        for key in ("business_focus", "recruitment_talent", "personal_rapport", "obe_focus", "audio_script"):
            data[key] = _coerce_brief_text(data.get(key))
        if not category_presence["business_focus"]:
            data["business_focus"] = ""
        if not category_presence["recruitment_talent"]:
            data["recruitment_talent"] = ""
        if not category_presence["family_personal"]:
            data["personal_rapport"] = ""
        if not category_presence["obe_focus"]:
            data["obe_focus"] = ""
        hypotheses = data.get("strategic_hypotheses")
        if not isinstance(hypotheses, list):
            hypotheses = []
        filtered_hypotheses = []
        blocked_fragments = []
        if not category_presence["recruitment_talent"]:
            blocked_fragments.extend(["talent", "recruit", "hiring", "staff"])
        if not category_presence["family_personal"]:
            blocked_fragments.extend(["family", "rapport", "travel", "children", "personal"])
        if not category_presence["obe_focus"]:
            blocked_fragments.extend(["obe", "network", "membership"])
        for hypothesis in hypotheses:
            text = _coerce_brief_text(hypothesis)
            lowered = text.lower()
            if blocked_fragments and any(fragment in lowered for fragment in blocked_fragments):
                continue
            if text:
                filtered_hypotheses.append(text)
        if not filtered_hypotheses:
            filtered_hypotheses = [
                "How is Brian prioritising cost-sharing decisions to keep projects moving toward handover?",
                "Which project stages are most exposed to imported-material delays and double-cost risk?",
                "What commercial flexibility is realistic when contract terms and developer cashflow are under pressure?",
            ]
        data["strategic_hypotheses"] = filtered_hypotheses[:3]
        data["voice"] = settings.BRIEF_TTS_VOICE
        data["label_recruitment"] = settings.BRIEF_LABEL_RECRUITMENT
        data["label_obe"] = settings.BRIEF_LABEL_OBE
        data["overall_brief_summary"] = " ".join(
            part for part in [
                data.get("business_focus"),
                data.get("recruitment_talent"),
                data.get("personal_rapport"),
                data.get("obe_focus"),
            ]
            if part
        ).strip()
        audio_script = _coerce_brief_text(data.get("audio_script"))
        audio_lower = audio_script.lower()
        if data["overall_brief_summary"] and (
            not audio_script
            or (blocked_fragments and any(fragment in audio_lower for fragment in blocked_fragments))
        ):
            data["audio_script"] = data["overall_brief_summary"]
        else:
            data["audio_script"] = audio_script
        data["preference_profile"] = preference_profile or {"scores": {}}
        return data
    except Exception as e:
        print(f"Briefing generation error: {e}")
        return _fallback_brief_from_signals(person, signals, events, preference_profile or {"scores": {}})
def _topic_resolution_context_block(assistant_context: Optional[dict]) -> str:
    context = assistant_context or {}
    if str(context.get("type") or "").strip().lower() != "relationship_topic_resolution":
        return ""
    evidence = context.get("evidence") or []
    evidence_lines = "\n".join(f"- {str(item).strip()}" for item in evidence[:3] if str(item).strip()) or "- No evidence supplied"
    evidence_details = context.get("evidence_details") or []
    evidence_detail_lines = "\n".join(
        "- " + " | ".join(
            part for part in (
                str(detail.get("channel") or "").strip(),
                str(detail.get("date_label") or "").strip(),
                str(detail.get("preview") or "").strip(),
            )
            if part
        )
        for detail in evidence_details[:3]
        if isinstance(detail, dict)
    ) or "- No detailed context supplied"
    return (
        "Active relationship topic in focus:\n"
        f"- situation_record_id: {str(context.get('situation_record_id') or '').strip()}\n"
        f"- situation_id: {str(context.get('situation_id') or '').strip()}\n"
        f"- title: {str(context.get('title') or '').strip()}\n"
        f"- type: {str(context.get('topic_type_label') or context.get('topic_type') or '').strip()}\n"
        f"- tracking_status: {str(context.get('tracking_status_label') or context.get('tracking_status') or '').strip()}\n"
        f"- stage: {str(context.get('stage') or '').strip()}\n"
        f"- momentum: {str(context.get('momentum') or '').strip()}\n"
        f"- current_read: {str(context.get('current_read') or '').strip()}\n"
        f"- why_it_matters: {str(context.get('why_it_matters') or '').strip()}\n"
        f"- recommended_action: {str(context.get('recommended_action') or '').strip()}\n"
        f"- question: {str(context.get('question') or '').strip()}\n"
        "Evidence:\n"
        f"{evidence_lines}\n"
        "Detailed context:\n"
        f"{evidence_detail_lines}"
    )


async def _analyze_relationship_topic_resolution(*, person: dict, assistant_context: dict, update_text: str) -> dict:
    context = assistant_context or {}
    prompt = f"""You are analyzing a manually reviewed CRM relationship topic update.

Contact:
- Name: {str(person.get("full_name") or "").strip()}
- Company: {str(person.get("company_name_raw") or "").strip()}

Current topic context:
- Title: {str(context.get("title") or "").strip()}
- Tracking status: {str(context.get("tracking_status_label") or context.get("tracking_status") or "").strip()}
- Stage: {str(context.get("stage") or "").strip()}
- Momentum: {str(context.get("momentum") or "").strip()}
- Current read: {str(context.get("current_read") or "").strip()}
- Why it matters: {str(context.get("why_it_matters") or "").strip()}
- Recommended action: {str(context.get("recommended_action") or "").strip()}
- Clarification question: {str(context.get("question") or "").strip()}
- Evidence: {' | '.join(str(item).strip() for item in (context.get("evidence") or []) if str(item).strip())}
- Detailed context: {' || '.join(' | '.join(part for part in (str(detail.get("channel") or "").strip(), str(detail.get("date_label") or "").strip(), str(detail.get("preview") or "").strip()) if part) for detail in (context.get("evidence_details") or []) if isinstance(detail, dict))}

User update:
\"\"\"{str(update_text or '').strip()[:4000]}\"\"\"

Return JSON with exactly these keys:
- headline: concise topic headline
- current_read: briefing-grade current state summary
- why_it_matters: direct factual significance
- stage: short stage label
- status: one of open | watching | stalled | closed
- momentum: short momentum label
- recommended_action: next step, or empty string if none remains
- resolution_note: direct resolution context, especially if the topic is now closed
- resolution_type: one of none | resolved | abandoned | superseded | stale | transitioned | declined
- key_points: array of up to 4 direct factual points
- confidence_score: integer 0-100
- summary: one sentence describing what changed

Rules:
- Be factual and concise. Do not use speculative filler.
- If the update clearly closes the topic, set status to closed.
- If resolution_type is not none, the topic should normally be closed.
- Keep recommended_action empty when the topic is truly closed and no next step remains.
- Preserve the commercial substance from the user's update instead of abstracting it away.
"""
    data, _run_id = await run_json_chat_task(
        task_type="relationship_topic_resolution",
        prompt_family="relationship_topic_resolution_v1",
        messages=[
            {"role": "system", "content": "You turn grounded user updates into CRM relationship topic state. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        model="gpt-4o",
        temperature=0.1,
        client_getter=_get_client,
        related_profile_id=str(person.get("person_id") or ""),
        metadata={"assistant_context_type": "relationship_topic_resolution"},
    )
    data["headline"] = str(data.get("headline") or context.get("title") or "Relationship topic").strip()
    data["current_read"] = str(data.get("current_read") or data["headline"]).strip()
    data["why_it_matters"] = str(data.get("why_it_matters") or context.get("why_it_matters") or "").strip()
    data["stage"] = str(data.get("stage") or context.get("stage") or "Relationship Update").strip()
    status = str(data.get("status") or context.get("tracking_status") or "watching").strip().lower()
    if status not in {"open", "watching", "stalled", "closed"}:
        status = str(context.get("tracking_status") or "watching").strip().lower() or "watching"
    resolution_type = str(data.get("resolution_type") or "none").strip().lower()
    if resolution_type not in {"none", "resolved", "abandoned", "superseded", "stale", "transitioned", "declined"}:
        resolution_type = "none"
    if resolution_type != "none":
        status = "closed"
    data["status"] = status
    data["momentum"] = str(data.get("momentum") or context.get("momentum") or "steady").strip()
    data["recommended_action"] = str(data.get("recommended_action") or "").strip()
    data["resolution_note"] = str(data.get("resolution_note") or "").strip()
    data["resolution_type"] = resolution_type
    key_points = []
    for value in data.get("key_points") or []:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in key_points:
            key_points.append(text)
    data["key_points"] = key_points[:4]
    try:
        data["confidence_score"] = max(0, min(100, int(data.get("confidence_score") or 0)))
    except Exception:
        data["confidence_score"] = 0
    data["summary"] = str(data.get("summary") or data["current_read"]).strip()
    return data


def _clean_story_thread_text(text: str) -> str:
    cleaned = strip_speculative_filler(str(text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^(re:|fw:|fwd:)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(summary:)\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _story_thread_section_catalog() -> list[dict]:
    return [
        {"key": "family", "label": "Family"},
        {"key": "interests_life", "label": "Interests & Life"},
        {"key": "active", "label": "Active"},
        {"key": "market_business", "label": "Market & Business"},
        {"key": "track_record", "label": "Track Record"},
    ]


def _fallback_story_thread(person: dict, relationship_story: Optional[dict] = None) -> dict:
    story = relationship_story or {}
    sections = story.get("sections") or {}
    master_thread = []
    thread_sections = []

    def _section_threads(items: list[dict], *, title_fallback: str) -> list[dict]:
        threads = []
        for item in items[:4]:
            points = [str(item.get("summary") or item.get("title") or "").strip()]
            for point in item.get("supporting_points") or []:
                text = str(point or "").strip()
                if text and text not in points:
                    points.append(text)
            points = [point for point in points if point][:4]
            if not points:
                continue
            evidence = str(item.get("evidence_anchor") or "").strip()
            threads.append(
                {
                    "title": str(item.get("title") or title_fallback or "Thread").strip(),
                    "date_window": str(item.get("last_updated_label") or "").strip(),
                    "points": points,
                    "evidence": [evidence] if evidence else [],
                }
            )
        return threads

    personal_groups = (sections.get("personal") or {}).get("groups") or []
    personal_map = {
        "family": next((group for group in personal_groups if str(group.get("label") or "").lower() == "family"), {}),
        "interests_life": next((group for group in personal_groups if "interest" in str(group.get("label") or "").lower()), {}),
    }
    section_source = {
        "family": personal_map["family"].get("items") or [],
        "interests_life": personal_map["interests_life"].get("items") or [],
        "active": (sections.get("active") or {}).get("items") or [],
        "market_business": (sections.get("market_business") or {}).get("items") or [],
        "track_record": (sections.get("track_record") or {}).get("items") or [],
    }
    for config in _story_thread_section_catalog():
        items = section_source.get(config["key"]) or []
        for item in items[:4]:
            text = str(item.get("summary") or item.get("title") or "").strip()
            if not text:
                continue
            master_thread.append(
                {
                    "entry_id": f"{config['key']}-{len(master_thread) + 1}",
                    "section_key": config["key"],
                    "section_label": config["label"],
                    "date_label": str(item.get("last_updated_label") or "").strip(),
                    "channel": "",
                    "text": text,
                }
            )
        thread_sections.append(
            {
                "key": config["key"],
                "label": config["label"],
                "threads": _section_threads(items, title_fallback=config["label"]),
            }
        )
    return {
        "source": "fallback",
        "model": "fallback",
        "summary": str(story.get("summary") or f"No clean story thread is ready for {person.get('full_name') or 'this contact'} yet.").strip(),
        "master_thread": master_thread,
        "sections": thread_sections,
    }


RELATIONSHIP_INTELLIGENCE_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "relationship_intelligence_v1",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "contact_name",
                "company",
                "title",
                "overall_relationship_health",
                "overall_commercial_priority",
                "current_read",
                "what_is_true_now",
                "what_changed_recently",
                "uncertainties",
                "relationship_gaps",
                "risks_or_watchouts",
                "next_conversation_priorities",
                "lenses",
                "personal_hooks_worth_remembering",
                "commercial_signals_worth_tracking",
                "market_signals_worth_tracking",
                "disproved_or_retired_claims",
            ],
            "properties": {
                "contact_name": {"type": "string"},
                "company": {"type": "string"},
                "title": {"type": "string"},
                "overall_relationship_health": {"type": "integer", "minimum": 0, "maximum": 100},
                "overall_commercial_priority": {"type": "integer", "minimum": 0, "maximum": 100},
                "current_read": {"type": "string"},
                "what_is_true_now": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "what_changed_recently": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "uncertainties": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "relationship_gaps": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "risks_or_watchouts": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "next_conversation_priorities": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "lenses": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "Family & Personal",
                        "Interests & Lifestyle",
                        "Active Opportunity",
                        "Market & Business",
                        "Track Record & Strategic Value",
                    ],
                    "properties": {
                        "Family & Personal": {"$ref": "#/$defs/lensView"},
                        "Interests & Lifestyle": {"$ref": "#/$defs/lensView"},
                        "Active Opportunity": {"$ref": "#/$defs/lensView"},
                        "Market & Business": {"$ref": "#/$defs/lensView"},
                        "Track Record & Strategic Value": {"$ref": "#/$defs/lensView"},
                    },
                },
                "personal_hooks_worth_remembering": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "commercial_signals_worth_tracking": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "market_signals_worth_tracking": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
                "disproved_or_retired_claims": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
            },
            "$defs": {
                "lensView": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "current_signal",
                        "why_it_matters",
                        "confidence",
                        "best_use_in_next_interaction",
                    ],
                    "properties": {
                        "current_signal": {"type": "string"},
                        "why_it_matters": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["High", "Medium", "Low"]},
                        "best_use_in_next_interaction": {"type": "string"},
                    },
                }
            },
        },
    },
}


def _relationship_lens_confidence_from_old_lens(lens: dict) -> str:
    score = max(
        int(lens.get("health_score") or 0),
        int(lens.get("priority_score") or 0),
    )
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def _relationship_current_signal_from_old_lens(lens: dict) -> str:
    top_points = [str(item or "").strip() for item in (lens.get("top_points") or []) if str(item or "").strip()]
    if top_points:
        return " ".join(top_points[:2]).strip()
    return str(lens.get("why_this_lens_matters_now") or "").strip()


def _normalize_relationship_intelligence_output(data: dict, person: dict) -> dict:
    if not isinstance(data, dict):
        return {}

    if "lenses" in data and "current_read" in data and "what_is_true_now" in data:
        normalized = dict(data)
        normalized.setdefault("contact_name", str(person.get("full_name") or ""))
        normalized.setdefault("company", str(person.get("company_name_raw") or person.get("company_name") or ""))
        normalized.setdefault("title", str(person.get("title_current") or ""))
        return normalized

    overall = data.get("overall") if isinstance(data.get("overall"), dict) else {}
    old_lenses = data.get("lens_views") if isinstance(data.get("lens_views"), dict) else {}
    lens_map = {
        "Family & Personal": "Relationship & Family",
        "Interests & Lifestyle": "Interests & Lifestyle",
        "Active Opportunity": "Live Opportunity",
        "Market & Business": "Market & Business Intelligence",
        "Track Record & Strategic Value": "Strategic Value / Track Record",
    }
    normalized_lenses = {}
    for new_key, old_key in lens_map.items():
        old_lens = old_lenses.get(old_key) if isinstance(old_lenses.get(old_key), dict) else {}
        normalized_lenses[new_key] = {
            "current_signal": _relationship_current_signal_from_old_lens(old_lens),
            "why_it_matters": str(old_lens.get("why_this_lens_matters_now") or "").strip(),
            "confidence": _relationship_lens_confidence_from_old_lens(old_lens),
            "best_use_in_next_interaction": str(old_lens.get("best_use_of_this_lens") or "").strip(),
        }

    return {
        "contact_name": str(data.get("contact_name") or person.get("full_name") or ""),
        "company": str(data.get("company") or person.get("company_name_raw") or person.get("company_name") or ""),
        "title": str(data.get("title") or person.get("title_current") or ""),
        "overall_relationship_health": int(data.get("overall_relationship_health") or overall.get("relationship_health_score") or 0),
        "overall_commercial_priority": int(data.get("overall_commercial_priority") or overall.get("commercial_priority_score") or 0),
        "current_read": str(data.get("current_read") or overall.get("overall_summary") or "").strip(),
        "what_is_true_now": list(data.get("what_is_true_now") or data.get("active_truths") or []),
        "what_changed_recently": list(data.get("what_changed_recently") or data.get("changed_recently") or []),
        "uncertainties": list(data.get("uncertainties") or []),
        "relationship_gaps": list(data.get("relationship_gaps") or []),
        "risks_or_watchouts": list(data.get("risks_or_watchouts") or []),
        "next_conversation_priorities": list(data.get("next_conversation_priorities") or data.get("commercial_signals") or []),
        "lenses": normalized_lenses,
        "personal_hooks_worth_remembering": list(data.get("personal_hooks_worth_remembering") or data.get("personal_hooks") or []),
        "commercial_signals_worth_tracking": list(data.get("commercial_signals_worth_tracking") or data.get("commercial_signals") or []),
        "market_signals_worth_tracking": list(data.get("market_signals_worth_tracking") or data.get("market_signals") or []),
        "disproved_or_retired_claims": list(data.get("disproved_or_retired_claims") or data.get("disproved_or_retired") or []),
    }


async def generate_relationship_story_thread(
    *,
    person: dict,
    raw_interactions: list[dict],
    tracked_situations: Optional[list[dict]] = None,
    promoted_memory: Optional[dict] = None,
    relationship_story: Optional[dict] = None,
) -> dict:
    if not settings.OPENAI_CONFIGURED:
        return _fallback_story_thread(person, relationship_story)

    section_catalog = _story_thread_section_catalog()
    raw_items = sorted(
        [dict(item) for item in (raw_interactions or []) if isinstance(item, dict)],
        key=lambda item: str(item.get("interaction_at") or ""),
    )
    evidence_items = []
    seen_evidence = set()
    for row in raw_items:
        text = _clean_story_thread_text(row.get("raw_text") or row.get("summary") or "")
        if not text or len(text) < 8:
            continue
        evidence_id = str(row.get("interaction_id") or "").strip() or f"interaction-{len(evidence_items) + 1}"
        if evidence_id in seen_evidence:
            continue
        seen_evidence.add(evidence_id)
        evidence_items.append(
            {
                "id": evidence_id,
                "date": str(row.get("interaction_at") or "").strip(),
                "channel": str(row.get("channel") or "Interaction").strip() or "Interaction",
                "date_label": str(row.get("interaction_at") or "").strip()[:10],
                "text": _trim_supporting_evidence(text, limit=320),
            }
        )
        if len(evidence_items) >= 28:
            break

    for situation in tracked_situations or []:
        for event in situation.get("recent_events") or []:
            if not isinstance(event, dict):
                continue
            if str(event.get("event_type") or "").strip().lower() not in {"manual_update", "manual_resolution"}:
                continue
            details_json = event.get("details_json")
            if not details_json:
                continue
            try:
                details = json.loads(details_json) if isinstance(details_json, str) else details_json
            except json.JSONDecodeError:
                continue
            if not isinstance(details, dict):
                continue
            analysis = details.get("analysis") if isinstance(details.get("analysis"), dict) else {}
            manual_bits = [
                details.get("update_text"),
                analysis.get("current_read"),
                analysis.get("resolution_note"),
                " ".join(analysis.get("key_points") or []),
            ]
            text = _clean_story_thread_text(" ".join(str(bit or "").strip() for bit in manual_bits if str(bit or "").strip()))
            if not text:
                continue
            evidence_id = f"manual-{str(situation.get('situation_record_id') or '')}-{str(event.get('created_at') or '')}"
            if evidence_id in seen_evidence:
                continue
            seen_evidence.add(evidence_id)
            evidence_items.append(
                {
                    "id": evidence_id,
                    "date": str(event.get("created_at") or "").strip(),
                    "channel": "Topic resolution",
                    "date_label": str(event.get("created_at") or "").strip()[:10],
                    "text": _trim_supporting_evidence(text, limit=320),
                }
            )
            if len(evidence_items) >= 36:
                break
        if len(evidence_items) >= 36:
            break

    memory_items = []
    for memory in (promoted_memory or {}).get("enduring_memory") or []:
        if not isinstance(memory, dict):
            continue
        memory_text = _clean_story_thread_text(memory.get("memory_text") or "")
        if not memory_text:
            continue
        memory_items.append(
            {
                "date": str(memory.get("interaction_at") or memory.get("updated_at") or "").strip(),
                "domain": str(memory.get("memory_domain") or "").strip(),
                "text": _trim_supporting_evidence(memory_text, limit=200),
            }
        )
        if len(memory_items) >= 10:
            break

    situation_truths = []
    for situation in tracked_situations or []:
        if not isinstance(situation, dict):
            continue
        situation_truths.append(
            {
                "headline": _clean_story_thread_text(situation.get("headline") or situation.get("topic") or ""),
                "status": str(situation.get("tracking_status") or "").strip(),
                "stage": str(situation.get("stage") or "").strip(),
                "current_read": _clean_story_thread_text(situation.get("headline") or situation.get("topic") or ""),
                "resolution_note": _clean_story_thread_text(situation.get("resolution_note") or ""),
                "key_points": [
                    _clean_story_thread_text(value)
                    for value in (situation.get("key_points") or [])
                    if _clean_story_thread_text(value)
                ][:4],
                "date_window": str(situation.get("window_label") or "").strip(),
            }
        )
    situation_truths = situation_truths[:14]

    if not evidence_items and not memory_items and not situation_truths:
        return _fallback_story_thread(person, relationship_story)

    prompt = f"""You are creating a clean relationship story thread for a CRM operator.

Contact:
{json.dumps({
    "person_id": person.get("person_id"),
    "full_name": person.get("full_name"),
    "company_name": person.get("company_name_raw") or person.get("company_name"),
    "title_current": person.get("title_current"),
}, ensure_ascii=False)}

Five allowed section keys:
{json.dumps(section_catalog, ensure_ascii=False)}

Raw evidence pack:
{json.dumps(evidence_items, ensure_ascii=False)}

Approved enduring memory:
{json.dumps(memory_items, ensure_ascii=False)}

Current tracked situation truth:
{json.dumps(situation_truths, ensure_ascii=False)}

Return JSON with exactly these keys:
- summary: one short operator-grade sentence
- master_thread: array of chronological entries, max 18
- sections: array of 5 section objects, one for each allowed key

Each master_thread entry must have:
- entry_id
- section_key
- section_label
- date_label
- channel
- text

Each section object must have:
- key
- label
- threads

Each thread must have:
- title
- date_window
- points
- evidence

Rules:
- Use only the evidence provided. Do not invent facts.
- Write like an operator note, not an AI explanation.
- Never say things like "the interaction indicates", "the contact is signaling", "meaningful context", or similar generic interpretation filler.
- Convert raw email/WhatsApp/calendar phrasing into clean factual story wording when possible.
- Treat current tracked situation truth and manual resolutions as higher priority than older raw evidence if they conflict.
- If a claim was later corrected or explicitly closed out as false, do not keep repeating the old claim in the story.
- Personal continuity must be split between Family and Interests & Life.
- If a point involves daughter, son, children, wife, husband, or family members, it belongs in Family even if it also reflects an interest or activity.
- Active should contain what is currently moving or still live.
- Market & Business should contain commercial, hiring, market, project, or business perspective.
- Track Record should contain past wins, failures, placements, starts, misses, and closed outcomes.
- If one thread contains multiple concrete business points, keep them together in one section thread with multiple bullet points.
- Keep each point concise and direct.
- Prefer grounded specifics like names, projects, roles, and outcomes when they are present in the evidence.
- Avoid repeating the contact's full name and company in every line unless it is needed for clarity.
"""

    model_candidates = [
        str(settings.RELATIONSHIP_STORY_MODEL or "").strip(),
        str(settings.STANDALONE_TOOL_MODEL or "").strip(),
        "gpt-4o",
    ]
    model_candidates = [model for model in model_candidates if model]
    last_error = None
    for model_name in dict.fromkeys(model_candidates):
        try:
            data, _run_id = await run_json_chat_task(
                task_type="relationship_story_thread",
                prompt_family="relationship_story_thread_v2",
                messages=[
                    {
                        "role": "system",
                        "content": "You are an elite relationship-story extraction engine. Return only valid JSON and do not fabricate facts.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=model_name,
                temperature=0.1,
                client_getter=_get_client,
                related_profile_id=str(person.get("person_id") or ""),
                metadata={"surface": "network_lab_profile"},
            )
            master_thread = data.get("master_thread") if isinstance(data.get("master_thread"), list) else []
            sections = data.get("sections") if isinstance(data.get("sections"), list) else []
            normalized_sections = []
            sections_by_key = {
                str(section.get("key") or "").strip(): section
                for section in sections
                if isinstance(section, dict)
            }
            for config in section_catalog:
                source = sections_by_key.get(config["key"]) or {}
                raw_threads = source.get("threads") if isinstance(source.get("threads"), list) else []
                threads = []
                for raw_thread in raw_threads[:6]:
                    if not isinstance(raw_thread, dict):
                        continue
                    points = []
                    for point in raw_thread.get("points") or []:
                        text = _clean_story_thread_text(point)
                        if text and text not in points:
                            points.append(text)
                    evidence = []
                    for value in raw_thread.get("evidence") or []:
                        text = _clean_story_thread_text(value)
                        if text and text not in evidence:
                            evidence.append(text)
                    if not points and not evidence:
                        continue
                    threads.append(
                        {
                            "title": _clean_story_thread_text(raw_thread.get("title") or config["label"] or "Thread") or config["label"],
                            "date_window": _clean_story_thread_text(raw_thread.get("date_window") or ""),
                            "points": points[:4],
                            "evidence": evidence[:3],
                        }
                    )
                normalized_sections.append(
                    {
                        "key": config["key"],
                        "label": config["label"],
                        "threads": threads,
                    }
                )

            normalized_master = []
            for index, item in enumerate(master_thread[:18]):
                if not isinstance(item, dict):
                    continue
                section_key = str(item.get("section_key") or "").strip()
                section = next((cfg for cfg in section_catalog if cfg["key"] == section_key), None)
                if not section:
                    continue
                text = _clean_story_thread_text(item.get("text") or "")
                if not text:
                    continue
                normalized_master.append(
                    {
                        "entry_id": str(item.get("entry_id") or f"thread-{index + 1}").strip(),
                        "section_key": section_key,
                        "section_label": section["label"],
                        "date_label": _clean_story_thread_text(item.get("date_label") or ""),
                        "channel": _clean_story_thread_text(item.get("channel") or ""),
                        "text": text,
                    }
                )

            if not normalized_master and not any(section["threads"] for section in normalized_sections):
                return _fallback_story_thread(person, relationship_story)

            return {
                "source": "llm",
                "model": model_name,
                "summary": _clean_story_thread_text(data.get("summary") or ""),
                "master_thread": normalized_master,
                "sections": normalized_sections,
            }
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        print(f"Relationship story thread generation failed: {last_error}")
    return _fallback_story_thread(person, relationship_story)


async def generate_relationship_intelligence(
    *,
    person: dict,
    evidence_inputs: list[dict],
) -> dict:
    if not settings.OPENAI_CONFIGURED:
        raise RuntimeError("OpenAI API key not configured")

    evidence_pack = []
    for item in (evidence_inputs or [])[:36]:
        if not isinstance(item, dict):
            continue
        content = _clean_story_thread_text(item.get("content") or item.get("preview") or "")
        if not content:
            continue
        evidence_pack.append(
            {
                "date": str(item.get("date_at") or item.get("date_label") or "").strip(),
                "source_type": str(item.get("source_type") or item.get("source_kind") or "Interaction").strip(),
                "source_kind": str(item.get("source_kind") or "interaction").strip(),
                "title": _clean_story_thread_text(item.get("title") or ""),
                "topic": _clean_story_thread_text(item.get("topic") or ""),
                "content": _trim_supporting_evidence(content, limit=700),
            }
        )

    if not evidence_pack:
        raise ValueError("No evidence inputs available for relationship intelligence")

    prompt = f"""You are the Taylor Sterling Relationship Intelligence Engine.

Your job is to turn messy CRM interaction history into a clean executive briefing for Marcus before the next conversation.

You are not writing a diary.
You are not writing a biography.
You are not trying to sound clever.
You are extracting current relationship intelligence.

PRIMARY OBJECTIVE
Produce a concise, commercially useful relationship read across these five lenses:

1. Family & Personal
2. Interests & Lifestyle
3. Active Opportunity
4. Market & Business
5. Track Record & Strategic Value

CORE RULES

1. Work from current truth, not from the most attractive story.
2. Newer direct evidence overrides older notes.
3. Manual resolution overrides all older notes.
4. Do not let disproved or superseded claims survive in active truth.
5. Suppress admin noise:
   - calendar wrappers
   - sent invites
   - accepted invites
   - duplicated reminders
   - repeated paraphrases
6. Do not reward repetition.
7. If evidence is mixed, state uncertainty plainly.
8. Use concise executive UK English.
9. Do not use em dashes.
10. Do not output filler such as:
   - No uncertainties listed
   - Nothing to ignore
   - No gaps
   unless that is genuinely defensible from the evidence.
11. If family is present, Family & Personal takes precedence over Interests & Lifestyle.
12. Active Opportunity must only include what appears commercially live now.
13. Track Record & Strategic Value is about long-term account importance, not generic praise.
14. Market & Business is about business conditions, company direction, sector pain, and capability need.
15. The final report must help Marcus decide:
   - what is true now
   - what matters before the next conversation
   - what to raise
   - what not to rely on

REASONING PROCESS

Step 1. Extract atomic evidence from the interaction chain.
Step 2. Reconcile contradictions and recency.
Step 3. Separate:
- active truth
- historical but useful context
- disproved / retired claims
- uncertainties
Step 4. Map only the reconciled truth into the five lenses.
Step 5. Produce the final report.

LENS TEMPLATE

For each lens, output only:
1. Current signal
2. Why it matters
3. Confidence
4. Best use in next interaction

SOURCE HANDLING RULES

When assessing evidence quality, use this order:
1. Manual resolution
2. Manual input from Marcus
3. Direct transcript, WhatsApp, email, or explicit meeting note
4. Calendar metadata
5. Older summaries or inferred storyline

SCORING RULES

Relationship health score should reflect:
- recency of real interaction
- openness / candour
- warmth / rapport depth
- continuity of contact
- access quality
- ease or difficulty of building the relationship
- any corrections that reduce assumed closeness

Commercial priority score should reflect:
- live roles or active opportunity
- account relevance to Taylor Sterling
- strategic market value
- timing and urgency
- quality of access to decision-making
- whether opportunities are active, narrowed, or already lost

FAIL CONDITIONS

The output is wrong if:
- a disproved claim appears in active truth
- an old filled role remains in Active Opportunity
- family content is placed only in Interests & Lifestyle
- the report says there are no uncertainties when evidence is mixed
- the report repeats admin noise
- the report sounds polished but does not help Marcus decide what to do next

Contact:
{json.dumps({
    "contact_name": person.get("full_name"),
    "company": person.get("company_name_raw") or person.get("company_name"),
    "title": person.get("title_current"),
}, ensure_ascii=False)}

Evidence pack:
{json.dumps(evidence_pack, ensure_ascii=False)}
"""

    model_candidates = [
        str(settings.RELATIONSHIP_STORY_MODEL or "").strip(),
        str(settings.STANDALONE_TOOL_MODEL or "").strip(),
        "gpt-4o",
    ]
    model_candidates = [model for model in model_candidates if model]
    last_error = None
    for model_name in dict.fromkeys(model_candidates):
        try:
            data, _run_id = await run_json_chat_task(
                task_type="relationship_intelligence",
                prompt_family="relationship_intelligence_v1",
                messages=[
                    {
                        "role": "system",
                        "content": "Return only valid JSON matching the provided schema. Work only from the evidence supplied.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=model_name,
                temperature=0.1,
                response_format=RELATIONSHIP_INTELLIGENCE_RESPONSE_FORMAT,
                client_getter=_get_client,
                related_profile_id=str(person.get("person_id") or ""),
                metadata={"surface": "network_lab_profile"},
            )
            if isinstance(data, dict):
                normalized = _normalize_relationship_intelligence_output(data, person)
                normalized["source"] = "llm"
                normalized["model"] = model_name
                return normalized
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    raise RuntimeError("Relationship intelligence generation failed")


async def profile_chat(person_id: str, person: dict, message: str, history: list, assistant_context: Optional[dict] = None) -> dict:
    """
    Agentic profile assistant with function calling.
    Can update profile fields, create tasks, and answer questions about the contact.
    Returns the assistant response plus any executed operations.
    """
    import uuid
    from datetime import datetime, timezone

    tax_block = _get_taxonomy_block()
    operations = []
    if _message_requests_stage_list(message):
        stage2_flow = _load_latest_stage2_flow(person_id)
        return {
            "response": _render_stage_list_response(stage2_flow),
            "operations": operations,
            "result_type": "stage_list",
            "sources": [
                {
                    "label": "Stage data source",
                    "detail": "Latest relationship stage flow for this profile",
                    "origin": "REL_INTEL_RUN.briefing_json.relationship_business_flow_stage2",
                }
            ],
            "quick_actions": [],
        }
    if _message_requests_contact_schedule(message):
        schedule_snapshot = _load_contact_schedule_snapshot(person_id, person)
        return {
            "response": _render_contact_schedule_response(schedule_snapshot),
            "operations": operations,
            "result_type": "contact_schedule",
            "sources": _contact_schedule_sources(schedule_snapshot),
            "quick_actions": _contact_schedule_quick_actions(schedule_snapshot),
        }
    db_query_result = _run_profile_chat_db_query(message)
    if isinstance(db_query_result, dict):
        return {
            "response": str(db_query_result.get("response") or ""),
            "operations": operations,
            "result_type": str(db_query_result.get("result_type") or "db_query"),
            "sources": db_query_result.get("sources") if isinstance(db_query_result.get("sources"), list) else [],
            "quick_actions": db_query_result.get("quick_actions") if isinstance(db_query_result.get("quick_actions"), list) else [],
        }

    latest_photo_candidate = _get_latest_profile_photo_candidate(person_id)
    schedule_snapshot = _load_contact_schedule_snapshot(person_id, person)
    cadence_context_block = _contact_schedule_context_block(schedule_snapshot)
    topic_resolution_context = assistant_context if isinstance(assistant_context, dict) else {}
    topic_resolution_requested = (
        str(topic_resolution_context.get("type") or "").strip().lower() == "relationship_topic_resolution"
        and str(topic_resolution_context.get("situation_record_id") or "").strip() != ""
    )
    pilot_resolution_note = ""
    topic_resolution_allowed = False
    if topic_resolution_requested:
        topic_resolution_allowed, pilot_summary = await is_person_in_pilot_cohort(person_id)
        if not topic_resolution_allowed:
            cohort_mode = str(pilot_summary.get("mode") or "recommended").strip()
            pilot_resolution_note = (
                "Relationship topic resolution is pilot-only and this profile is outside the explicit pilot cohort."
                if cohort_mode == "explicit"
                else "Relationship topic resolution is pilot-only and this profile is outside the current pilot cohort."
            )
    topic_resolution_available = (
        topic_resolution_requested
        and topic_resolution_allowed
    )

    tools = [
        {
            "type": "function",
            "function": {
                "name": "update_profile",
                "description": "Update a field on this person's profile in the database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": list(ALLOWED_PROFILE_FIELDS)},
                        "value": {"type": "string"}
                    },
                    "required": ["field", "value"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "apply_profile_photo",
                "description": "Set the active profile photo from the latest uploaded headshot candidate for this profile. Use only when the user explicitly instructs you to use or set the uploaded image as the profile photo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "media_url": {"type": "string", "description": "Optional media URL of the approved headshot candidate. Leave empty to use the latest eligible candidate."}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_task",
                "description": "Create a follow-up task linked to this person.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "due_date": {"type": "string"},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                        "due_time": {"type": "string", "description": "Use 09:00 for morning and 13:00 for afternoon unless the user gives a more exact time."},
                    },
                    "required": ["title"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "log_intelligence",
                "description": "Save structured intelligence to the profile.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "enum": ["business_focus", "recruitment_talent", "family_personal", "obe_focus"]},
                        "text": {"type": "string"}
                    },
                    "required": ["topic", "text"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_employment_history",
                "description": "Update one role in employment history (for example add or change an end date).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "match": {
                            "type": "object",
                            "description": "Optional role selector. Leave empty to target the most recent open role.",
                            "properties": {
                                "title": {"type": "string"},
                                "company": {"type": "string"},
                                "start_date": {"type": "string"},
                            },
                        },
                        "set": {
                            "type": "object",
                            "description": "Fields to set on the matched role.",
                            "properties": {
                                "title": {"type": "string"},
                                "company": {"type": "string"},
                                "start_date": {"type": "string"},
                                "end_date": {"type": "string", "description": "Use YYYY-MM or YYYY-MM-DD. Use empty string to clear end_date."},
                                "location": {"type": "string"},
                                "description": {"type": "string"},
                            },
                        },
                    },
                    "required": ["set"],
                },
            },
        },
    ]
    if topic_resolution_available:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "resolve_relationship_topic",
                    "description": "Update the active relationship topic with the user's latest grounded detail. Use only once the user has provided enough concrete information to update the topic state.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "situation_record_id": {
                                "type": "string",
                                "description": f"Use the active topic situation_record_id from context: {str(topic_resolution_context.get('situation_record_id') or '').strip()}",
                            },
                            "update_text": {
                                "type": "string",
                                "description": "The user's factual update that should be analyzed and stored on the topic.",
                            },
                        },
                        "required": ["situation_record_id", "update_text"],
                    },
                },
            }
        )

    photo_candidate_block = "No uploaded headshot candidate is currently available for profile-photo approval."
    if latest_photo_candidate:
        photo_candidate_block = (
            "Latest uploaded headshot candidate available for explicit approval:\n"
            f"- media_url: {latest_photo_candidate.get('media_url')}\n"
            f"- source_name: {latest_photo_candidate.get('source_name') or 'uploaded image'}\n"
            f"- created_at: {latest_photo_candidate.get('created_at')}\n"
            f"- requires_confirmation: {'yes' if latest_photo_candidate.get('requires_confirmation') else 'no'}\n"
            "Use apply_profile_photo only if the user clearly asks you to use or set this image as the active profile photo."
        )

    system = f"""You are the Antigravity CRM Profile Assistant.
You are chatting about this contact:
Name: {person.get('full_name')}
Company: {person.get('company_name_raw')}
Title: {person.get('title_current')}
Category: {person.get('cat')}
Environment: {person.get('env')}
Discipline: {person.get('disc')}
Career Summary: {person.get('career_summary')}
Professional Notes: {person.get('key_professional_notes')}
Personal Notes: {person.get('key_personal_notes')}
Taxonomy:
{tax_block}

Profile photo approval context:
{photo_candidate_block}

{cadence_context_block}

{_topic_resolution_context_block(topic_resolution_context) if topic_resolution_available else ""}
{pilot_resolution_note}

When there is a clear next step in the user's message or the stored relationship context, proactively suggest a concrete task or follow-up in plain language.
When the user asks about timing, cadence, or next interaction, answer with a specific calendar date (not vague phrases like "next few weeks").
Only use create_task after the user explicitly asks for it or clearly confirms your suggestion.
Use tools when the user explicitly asks for profile updates, task creation, or intelligence logging.
If the user shares concrete factual relationship or business updates (even without saying "save"), treat that as capture intent and use tools to log the update.
Use update_employment_history for role-level timeline edits (example: "add end date", "change company on previous role", "update employment period").
If the user asks to add an end date but does not give a date, set today's date in YYYY-MM-DD format.
When a relationship topic is already in active context, help the user resolve that exact topic. Ask a short follow-up question if the update is still too vague to change the topic state. Once the user gives concrete detail, use resolve_relationship_topic so the storyline is updated.
If relationship topic resolution is unavailable for this profile, say that plainly and do not imply the topic state was updated. Still capture concrete updates via log_intelligence and any relevant profile/task tools.
Never claim you cannot inspect an uploaded image if a recent upload result is already in context.
If the user explicitly says to use or set the uploaded headshot as the profile photo, use apply_profile_photo.
Do not apply screenshots, documents, or ambiguous images as profile photos.
If the context suggests something like coffee after Eid, say so directly, for example: "We should set a task to call Brian after Eid and lock in coffee."
Otherwise answer conversationally and succinctly."""

    def _tool_call_to_wire(tool_call: Any) -> dict:
        if isinstance(tool_call, dict):
            call = dict(tool_call)
            fn = call.get("function") if isinstance(call.get("function"), dict) else {}
            return {
                "id": str(call.get("id") or ""),
                "type": str(call.get("type") or "function"),
                "function": {
                    "name": str(fn.get("name") or ""),
                    "arguments": str(fn.get("arguments") or "{}"),
                },
            }
        fn_obj = getattr(tool_call, "function", None)
        return {
            "id": str(getattr(tool_call, "id", "") or ""),
            "type": str(getattr(tool_call, "type", "function") or "function"),
            "function": {
                "name": str(getattr(fn_obj, "name", "") or ""),
                "arguments": str(getattr(fn_obj, "arguments", "{}") or "{}"),
            },
        }

    def _assistant_message_to_wire(msg_obj: Any) -> dict:
        tool_calls = getattr(msg_obj, "tool_calls", None) or []
        return {
            "role": "assistant",
            "content": getattr(msg_obj, "content", None) or "",
            "tool_calls": [_tool_call_to_wire(call) for call in tool_calls],
        }

    msgs = [{"role": "system", "content": system}]
    msgs.extend(history or [])
    msgs.append({"role": "user", "content": message})

    try:
        client = _get_client()
        response = await client.chat.completions.create(model="gpt-4o", messages=msgs, tools=tools)
        msg = response.choices[0].message

        if msg.tool_calls:
            msgs.append(_assistant_message_to_wire(msg))
            for tc in msg.tool_calls:
                fn = tc.function.name
                args = json.loads(tc.function.arguments)
                result = "Error"
                operation = {"type": fn, "status": "completed"}

                if fn == "update_profile":
                    field, value = args["field"], args["value"]

                    async def _update_profile(db):
                        await db.execute(
                            f"UPDATE PERSON SET {field}=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                            (value, datetime.now(timezone.utc).isoformat(), person_id)
                        )

                    await run_write(_update_profile, label=f"chat update profile {person_id}")
                    result = f"Updated {field}"
                    operation.update({"field": field, "value": value})

                elif fn == "apply_profile_photo":
                    preferred_media_url = args.get("media_url")
                    candidate = _get_latest_profile_photo_candidate(person_id, preferred_media_url)
                    current_photo_url = person.get("profile_photo_url")

                    if not candidate:
                        result = "No eligible uploaded headshot is available to apply as the profile photo."
                        operation.update({"status": "failed"})
                    else:
                        media_url = candidate["media_url"]
                        now = datetime.now(timezone.utc).isoformat()
                        already_active = current_photo_url == media_url

                        async def _apply_profile_photo(db):
                            await db.execute(
                                "UPDATE PERSON SET profile_photo_url=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                                (media_url, now, person_id),
                            )
                            await db.execute(
                                "UPDATE AI_ARTIFACT SET requires_confirmation=0, updated_at=?, status='processed' WHERE artifact_id=?",
                                (now, candidate["artifact_id"]),
                            )
                            await db.execute(
                                """
                                INSERT INTO INTERACTION
                                (interaction_id, person_id, channel, raw_text, summary, action_items, topics, sentiment, media_url, created_at, interaction_at, success_rating, engagement_value, is_strategic, metric_tags)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    str(uuid.uuid4()),
                                    person_id,
                                    "system_audit",
                                    f"Profile photo approved from uploaded headshot candidate '{candidate.get('source_name') or media_url}'.",
                                    "Profile photo updated from explicit assistant approval.",
                                    "[]",
                                    '[\"profile_photo_approval\"]',
                                    "Neutral",
                                    media_url,
                                    now,
                                    now,
                                    None,
                                    None,
                                    0,
                                    '[\"system_audit\"]',
                                ),
                            )

                        await run_write(_apply_profile_photo, label=f"chat apply profile photo {person_id}")
                        person["profile_photo_url"] = media_url
                        result = "That headshot is already the active profile photo." if already_active else "Profile photo updated from the approved headshot candidate."
                        operation.update({
                            "artifact_id": candidate["artifact_id"],
                            "media_url": media_url,
                            "source_name": candidate.get("source_name"),
                            "applied": True,
                        })

                elif fn == "create_task":
                    tid = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()
                    due_date = _normalize_due_date_for_message(message, args.get("due_date"))

                    async def _create_task(db):
                        await db.execute(
                            "INSERT INTO TASK (task_id, person_id, task_text, due_date, due_time, priority, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                            (tid, person_id, args["title"], due_date, args.get("due_time") or "09:00", args.get("priority", "medium"), "open", now)
                        )
                        if due_date:
                            meeting_status = None
                            try:
                                task_date = datetime.strptime(due_date, "%Y-%m-%d").date()
                                today = datetime.now(timezone.utc).date()
                                day_delta = (task_date - today).days
                                if day_delta < 0:
                                    meeting_status = "overdue"
                                elif day_delta <= 7:
                                    meeting_status = "soon"
                                else:
                                    meeting_status = "on_track"
                            except Exception:
                                meeting_status = None

                            await db.execute(
                                """
                                UPDATE PERSON SET next_contact_due_date = (
                                    SELECT MIN(due_date)
                                    FROM TASK
                                    WHERE person_id=? AND status IN ('open', 'in_progress') AND due_date IS NOT NULL
                                ), meeting_status=?, last_updated_at=?, cached_briefing=NULL
                                WHERE person_id=?
                                """,
                                (person_id, meeting_status, now, person_id),
                            )

                    await run_write(_create_task, label=f"chat create task {person_id}")
                    result = f"Task created: {args['title']}"
                    operation.update({"task_id": tid, "title": args["title"], "due_date": due_date, "due_time": args.get("due_time") or "09:00"})

                elif fn == "log_intelligence":
                    from backend.services.transcript_guardrails import looks_like_low_signal_chat_input

                    intel_text = str(args.get("text") or "").strip()
                    if looks_like_low_signal_chat_input(intel_text):
                        result = "Ignored low-signal logging instruction."
                        operation.update({"status": "ignored", "reason": "low_signal"})
                    else:
                        tid = str(uuid.uuid4())[:12]
                        now = datetime.now(timezone.utc).isoformat()

                        async def _log_intel(db):
                            await db.execute(
                                "INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at, status, source_snippet) VALUES (?,?,?,?,?,?,?,?)",
                                (tid, person_id, args["topic"], intel_text, 5, now, "approved", intel_text)
                            )

                        await run_write(_log_intel, label=f"chat log intelligence {person_id}")
                        result = f"Logged {args['topic']}: {intel_text}"
                        operation.update({"intel_id": tid, "topic": args["topic"]})

                elif fn == "update_employment_history":
                    match = args.get("match") if isinstance(args.get("match"), dict) else {}
                    updates_in = args.get("set") if isinstance(args.get("set"), dict) else {}
                    allowed_role_fields = {"title", "company", "start_date", "end_date", "location", "description"}
                    updates = {
                        field: _clean_role_value(value)
                        for field, value in updates_in.items()
                        if field in allowed_role_fields and value is not None
                    }

                    if not updates and re.search(r"\b(end date|employment period)\b", str(message or "").lower()):
                        updates["end_date"] = datetime.now(timezone.utc).date().isoformat()

                    if not updates:
                        result = "No valid employment fields were supplied for update."
                        operation.update({"status": "failed", "reason": "no_valid_fields"})
                    else:
                        if "end_date" in updates and str(updates["end_date"]).strip().lower() in {"present", "current", "ongoing", "now"}:
                            updates["end_date"] = ""

                        history_roles = _coerce_employment_history(person.get("employment_history"))
                        target_idx, match_mode = _pick_employment_role_index(
                            history_roles,
                            title=str(match.get("title") or ""),
                            company=str(match.get("company") or ""),
                            start_date=str(match.get("start_date") or ""),
                        )

                        if target_idx < 0:
                            result = "Could not find a unique employment role to update."
                            operation.update({"status": "failed", "reason": match_mode})
                        else:
                            role_before = dict(history_roles[target_idx])
                            role_after = dict(role_before)
                            for field, value in updates.items():
                                role_after[field] = value
                            history_roles[target_idx] = role_after
                            payload = json.dumps(history_roles, ensure_ascii=False)
                            now = datetime.now(timezone.utc).isoformat()

                            async def _update_employment_history(db):
                                await db.execute(
                                    "UPDATE PERSON SET employment_history=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                                    (payload, now, person_id),
                                )

                            await run_write(_update_employment_history, label=f"chat update employment history {person_id}")
                            person["employment_history"] = history_roles
                            result = "Employment history updated."
                            operation.update(
                                {
                                    "matched_index": target_idx,
                                    "matched_by": match_mode,
                                    "before": role_before,
                                    "after": role_after,
                                }
                            )

                elif fn == "resolve_relationship_topic":
                    from backend.services.correspondence_intelligence_service import apply_manual_relationship_topic_resolution

                    situation_record_id = str(args.get("situation_record_id") or topic_resolution_context.get("situation_record_id") or "").strip()
                    update_text = str(args.get("update_text") or message).strip()
                    if not situation_record_id:
                        result = json.dumps({"status": "failed", "error": "No relationship topic was supplied for resolution."})
                        operation.update({"status": "failed"})
                    else:
                        analysis = await _analyze_relationship_topic_resolution(
                            person=person,
                            assistant_context=topic_resolution_context,
                            update_text=update_text,
                        )
                        resolved = await apply_manual_relationship_topic_resolution(
                            person_id=person_id,
                            situation_record_id=situation_record_id,
                            update_text=update_text,
                            analysis=analysis,
                            source="profile_assistant",
                        )
                        result = json.dumps(
                            {
                                "status": "completed",
                                "title": resolved.get("title"),
                                "status_label": resolved.get("status_label"),
                                "current_read": resolved.get("current_read"),
                                "recommended_action": resolved.get("recommended_action"),
                                "resolution_note": resolved.get("resolution_note"),
                            },
                            ensure_ascii=False,
                        )
                        operation.update(resolved)

                operations.append(operation)
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            completed = [op for op in operations if str(op.get("status") or "").lower() == "completed"]
            failed = [op for op in operations if str(op.get("status") or "").lower() not in {"", "completed"}]
            response_parts: list[str] = []
            if completed:
                labels = ", ".join(str(op.get("type") or "update").replace("_", " ") for op in completed[:3])
                response_parts.append(f"Done. Applied: {labels}.")
            if failed:
                labels = ", ".join(str(op.get("type") or "update").replace("_", " ") for op in failed[:3])
                response_parts.append(f"Some actions need attention: {labels}.")
            if not response_parts:
                response_parts.append("Done.")
            return {"response": " ".join(response_parts), "operations": operations}

        assistant_text = msg.content or ""
        if (
            not operations
            and _assistant_storyline_refusal(assistant_text)
            and _looks_like_factual_profile_update_text(message)
        ):
            capture_fallback = await _profile_chat_rule_fallback(
                person_id,
                person,
                f"Capture update: {message}",
            )
            fallback_ops = capture_fallback.get("operations", []) if isinstance(capture_fallback, dict) else []
            if any(
                str(op.get("type") or "").lower() == "log_intelligence"
                and str(op.get("status") or "").lower() == "completed"
                for op in fallback_ops
            ):
                return capture_fallback

        return {"response": assistant_text, "operations": operations}
    except Exception as e:
        print(f"Chatbot AI error: {e}")
        print(traceback.format_exc())
        try:
            fallback = await _profile_chat_rule_fallback(person_id, person, message, root_error=e)
            if isinstance(fallback, dict):
                return fallback
        except Exception as fallback_error:
            print(f"Chatbot fallback error: {fallback_error}")
            print(traceback.format_exc())
        return {
            "response": "Assistant is temporarily unavailable. Please retry in a moment.",
            "operations": operations,
        }

def extract_text_from_file(file_path: str) -> Optional[str]:
    """Extract text from PDF or TXT files."""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(file_path)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            return text.strip()
        elif ext == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
    except Exception as e:
        print(f"File extraction error: {e}")
    return None











