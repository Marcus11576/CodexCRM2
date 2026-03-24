import json
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import settings
from backend.database import get_db, run_write
from backend.services.ai_pipeline_service import load_profile_signals
from backend.services.ai_runtime import run_json_chat_task
from backend.services.ai_service import generate_relationship_story_thread
from backend.services.correspondence_intelligence_service import (
    apply_manual_relationship_topic_resolution,
    build_relationship_topics,
    build_relationship_story,
    build_conversation_prep,
    build_interpreted_memory_summary,
    build_storyline_state,
    _display_channel_label,
    load_related_team_context,
    load_relationship_situations_for_person,
    load_interpreted_databank,
    load_interpreted_interactions,
    load_review_queue,
    load_promoted_memory_for_person,
    promote_interpretation_to_enduring_memory,
    promote_interpretation_to_market_intel,
    refresh_interpreted_interactions_for_person,
    sync_relationship_situations_for_person,
    update_manual_relationship_event,
    update_enduring_memory_status,
    delete_manual_relationship_event,
    update_market_intel_status,
)
from backend.services.network_orchestration_service import build_network_feed, get_network_contact_context
from backend.services.pilot_cohort_service import is_person_in_pilot_cohort, resolve_pilot_cohort
from backend.services.relationship_intelligence_pipeline import (
    STAGE2_SENTENCE_SIGNAL_KEYWORDS,
    build_relationship_intelligence_pipeline,
)
from backend.services.system_settings_service import get_intelligence_settings
from backend.services.transcript_guardrails import (
    is_non_transcript_chat_input as _is_non_transcript_chat_input,
    segment_prefers_positioning_stage as _segment_prefers_positioning_stage,
)

router = APIRouter(prefix="/api/network-lab", tags=["network-lab"])


def _shape_profile_intelligence_item(
    *,
    category: str,
    signal_text: str,
    supporting_context: str,
    business_subtopic_label: Optional[str] = None,
    display_channel: Optional[str] = None,
    source_kind: str,
    sort_score: float = 0.0,
) -> dict:
    return {
        "primary_category": category,
        "business_subtopic_label": business_subtopic_label,
        "display_channel": display_channel,
        "signal_text": signal_text,
        "supporting_context": supporting_context,
        "source_kind": source_kind,
        "_sort_score": sort_score,
    }


def _dedupe_profile_intelligence(items: list[dict], limit: int = 8) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in sorted(items, key=lambda value: (-float(value.get("_sort_score") or 0), str(value.get("signal_text") or "").lower())):
        key = "|".join(
            [
                str(item.get("primary_category") or "").strip().lower(),
                str(item.get("business_subtopic_label") or "").strip().lower(),
                str(item.get("signal_text") or "").strip().lower(),
            ]
        )
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned = dict(item)
        cleaned.pop("_sort_score", None)
        deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped


def _build_profile_intelligence_layers(
    *,
    tracked_situations: list[dict],
    promoted_memory: dict,
    legacy_signals: list[dict],
    interpreted_interactions: list[dict],
) -> tuple[list[dict], list[dict]]:
    surfaced: list[dict] = []
    draft: list[dict] = []

    for item in promoted_memory.get("promoted_market_intel", []):
        status = str(item.get("status") or "").lower()
        shaped = _shape_profile_intelligence_item(
            category="Market Intel",
            signal_text=str(item.get("signal_text") or "Market signal"),
            supporting_context=f"Promoted market signal. Importance {int(item.get('importance_score') or 0)} | Confidence {int(item.get('confidence_score') or 0)}.",
            business_subtopic_label=str(item.get("topic") or "Market Pulse"),
            display_channel=str(item.get("status") or "").title() or None,
            source_kind="promoted_market_intel",
            sort_score=100 + float(item.get("importance_score") or 0),
        )
        if status == "approved":
            surfaced.append(shaped)
        else:
            draft.append(shaped)

    for item in promoted_memory.get("enduring_memory", []):
        status = str(item.get("status") or "").lower()
        domain_label = str(item.get("memory_domain") or "memory").replace("_", " ").title()
        shaped = _shape_profile_intelligence_item(
            category="Enduring Memory",
            signal_text=str(item.get("memory_text") or "Promoted memory"),
            supporting_context=f"Promoted {domain_label.lower()} memory. Importance {int(item.get('importance_score') or 0)} | Confidence {int(item.get('confidence_score') or 0)}.",
            business_subtopic_label=domain_label,
            display_channel=str(item.get("status") or "").title() or None,
            source_kind="enduring_memory",
            sort_score=90 + float(item.get("importance_score") or 0),
        )
        if status == "approved":
            surfaced.append(shaped)
        else:
            draft.append(shaped)

    for item in tracked_situations:
        status = str(item.get("tracking_status") or "").lower()
        shaped = _shape_profile_intelligence_item(
            category="Tracked Situation",
            signal_text=str(item.get("headline") or item.get("topic") or "Tracked situation"),
            supporting_context=str(item.get("why_it_matters") or item.get("timeline_summary") or "Tracked relationship situation."),
            business_subtopic_label=str(item.get("topic_type_label") or "Relationship"),
            display_channel=str(item.get("tracking_status_label") or "Watching"),
            source_kind="relationship_situation",
            sort_score=110 + float(item.get("confidence_score") or 0),
        )
        if status in {"open", "stalled", "watching"}:
            surfaced.append(shaped)

    surfaced_signal_texts = {
        str(item.get("signal_text") or "").strip().lower()
        for item in surfaced
        if str(item.get("signal_text") or "").strip()
    }

    for signal in legacy_signals:
        review_state = str(signal.get("review_state") or "").lower()
        shaped = _shape_profile_intelligence_item(
            category=str(signal.get("primary_category") or signal.get("category") or "Signal").replace("_", " ").title(),
            signal_text=str(signal.get("signal_text") or signal.get("text") or "Legacy signal"),
            supporting_context=str(signal.get("supporting_context") or signal.get("source_snippet") or "Legacy profile signal."),
            business_subtopic_label=signal.get("business_subtopic_label") or signal.get("business_subtopic"),
            display_channel=signal.get("display_channel"),
            source_kind=str(signal.get("source_kind") or "ai_signal"),
            sort_score=60 + float(signal.get("importance_score") or 0),
        )
        if shaped["signal_text"].strip().lower() in surfaced_signal_texts:
            continue
        if review_state == "approved":
            surfaced.append(shaped)
        else:
            draft.append(shaped)

    for item in interpreted_interactions:
        signal_text = str(item.get("what_is_happening") or "").strip()
        if not signal_text or signal_text.lower() in surfaced_signal_texts:
            continue
        draft.append(
            _shape_profile_intelligence_item(
                category="Draft Interpretation",
                signal_text=signal_text,
                supporting_context=str(item.get("why_it_matters") or item.get("recommended_action") or "Interpreted interaction awaiting promotion."),
                business_subtopic_label=str(item.get("stage") or "Relationship Update"),
                display_channel=str(item.get("channel") or "").title() or None,
                source_kind="interpreted_interaction",
                sort_score=40 + float(item.get("confidence_score") or 0),
            )
        )

    return _dedupe_profile_intelligence(surfaced, limit=8), _dedupe_profile_intelligence(draft, limit=8)


def _clarification_keyword_tokens(*values: str) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in str(value or "").lower().replace("/", " ").replace("|", " ").split():
            cleaned = "".join(ch for ch in token if ch.isalnum())
            if len(cleaned) < 4:
                continue
            if cleaned in {"what", "with", "that", "this", "from", "have", "will", "should", "current", "retain", "system", "topic"}:
                continue
            if cleaned not in tokens:
                tokens.append(cleaned)
    return tokens


def _build_clarification_context_fallback(
    item: dict,
    recent_evidence: list[dict],
    legacy_signals: list[dict],
    limit: int = 3,
) -> list[dict]:
    existing = item.get("evidence_details") or []
    if existing:
        return existing

    tokens = _clarification_keyword_tokens(
        item.get("title") or "",
        item.get("question") or "",
        item.get("current_read") or "",
        item.get("why_it_matters") or "",
        " ".join(item.get("evidence") or []),
    )
    if not tokens:
        return []

    matched: list[dict] = []
    seen: set[str] = set()

    for evidence_row in recent_evidence or []:
        evidence_text = " ".join(
            part for part in (
                str(evidence_row.get("summary") or "").strip(),
                str(evidence_row.get("raw_text") or "").strip(),
            )
            if part
        )
        if _is_non_transcript_chat_input(evidence_text, evidence_row.get("channel")):
            continue
        text_blob = " ".join(
            part for part in (
                str(evidence_row.get("summary") or "").strip(),
                str(evidence_row.get("raw_text") or "").strip(),
            )
            if part
        ).lower()
        if not text_blob:
            continue
        score = sum(1 for token in tokens if token in text_blob)
        if score <= 0:
            continue
        preview = str(evidence_row.get("summary") or evidence_row.get("raw_text") or "").strip()
        if not preview:
            continue
        detail = {
            "channel": _display_channel_label(
                evidence_row.get("channel"),
                evidence_row.get("summary"),
                evidence_row.get("raw_text"),
            ),
            "date_label": str(evidence_row.get("interaction_at") or "").strip()[:10],
            "preview": preview[:220],
            "_score": score,
        }
        key = f"{detail['date_label']}|{detail['channel']}|{detail['preview'].lower()}"
        if key in seen:
            continue
        seen.add(key)
        matched.append(detail)

    for signal in legacy_signals or []:
        text_blob = " ".join(
            part for part in (
                str(signal.get("signal_text") or "").strip(),
                str(signal.get("supporting_context") or signal.get("source_snippet") or "").strip(),
            )
            if part
        ).lower()
        if not text_blob:
            continue
        score = sum(1 for token in tokens if token in text_blob)
        if score <= 0:
            continue
        preview = str(signal.get("supporting_context") or signal.get("source_snippet") or signal.get("signal_text") or "").strip()
        if not preview:
            continue
        detail = {
            "channel": str(signal.get("display_channel") or signal.get("primary_category") or "Signal").strip(),
            "date_label": str(signal.get("created_at") or "").strip()[:10],
            "preview": preview[:220],
            "_score": score,
        }
        key = f"{detail['date_label']}|{detail['channel']}|{detail['preview'].lower()}"
        if key in seen:
            continue
        seen.add(key)
        matched.append(detail)

    matched = sorted(matched, key=lambda row: (-int(row.get("_score") or 0), row.get("date_label") or ""), reverse=False)
    return [
        {
            "channel": row["channel"],
            "date_label": row["date_label"],
            "preview": row["preview"],
        }
        for row in matched[:limit]
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_evidence_text(value: str | None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()).strip() for line in text.split("\n")]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def _preview_evidence_text(value: str | None, limit: int = 220) -> str:
    text = _clean_evidence_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _looks_like_profile_photo_interaction(row: dict) -> bool:
    if bool(row.get("is_profile_picture_artifact")):
        return True
    channel = str(row.get("channel") or "").strip().lower()
    if channel not in {"screenshot", "upload"}:
        return False
    text = _clean_evidence_text(
        " ".join(
            part
            for part in (
                str(row.get("summary") or "").strip(),
                str(row.get("raw_text") or "").strip(),
                str(row.get("content") or "").strip(),
            )
            if part
        )
    ).lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "professional headshot",
            "profile image identified",
            "profile photo identified",
            "headshot of an individual",
        )
    )


def _normalize_stage_code_for_segment(segment: str, code: str) -> str:
    normalized = _normalize_stage_tag_code(str(code or "").strip().upper())
    lowered_segment = _normalize_segment_text(segment)
    if normalized in {"S8", "S9"} and _segment_prefers_positioning_stage(segment):
        return "S3"
    if normalized in {"S8", "S9"}:
        if _contains_any_term(lowered_segment, STAGE2_SENTENCE_SIGNAL_KEYWORDS.get("conversion_pending", set())):
            return "S7"
        if _contains_any_term(lowered_segment, STAGE2_SENTENCE_SIGNAL_KEYWORDS.get("active_discussion", set())):
            return "S6"
        if _contains_any_term(lowered_segment, STAGE2_SENTENCE_SIGNAL_KEYWORDS.get("problem_identified", set())):
            return "S5"
    if normalized in {"S8", "S9"} and (
        _contains_any_term(lowered_segment, UNDERSTAND_STAGE_TERMS)
        or re.search(r"\b\d{2,}\s+people\b", lowered_segment)
    ):
        return "S2"
    if normalized == "S9" and not _contains_any_term(lowered_segment, MATURE_NURTURE_MARKERS):
        return "S4"
    return normalized


def _build_profile_evidence_inputs(
    interactions: list[dict],
    tracked_situations: list[dict],
) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    for row in interactions or []:
        if _looks_like_profile_photo_interaction(row):
            continue
        full_text = _clean_evidence_text(row.get("raw_text") or row.get("summary") or "")
        if not full_text:
            continue
        if _is_non_transcript_chat_input(full_text, row.get("channel")):
            continue
        evidence_id = str(row.get("interaction_id") or "").strip()
        if not evidence_id:
            continue
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        summary = _clean_evidence_text(row.get("summary") or "") or _preview_evidence_text(full_text, limit=160)
        items.append(
            {
                "evidence_id": evidence_id,
                "source_kind": "interaction",
                "source_type": _display_channel_label(
                    row.get("channel"),
                    row.get("summary"),
                    row.get("raw_text"),
                ),
                "date_at": str(row.get("interaction_at") or "").strip(),
                "date_label": str(row.get("interaction_at") or "").strip()[:10],
                "title": summary,
                "preview": _preview_evidence_text(full_text),
                "content": full_text,
                "interaction_id": evidence_id,
                "can_edit": True,
                "can_delete": True,
                "edit_kind": "interaction",
            }
        )

    for situation in tracked_situations or []:
        situation_label = str(situation.get("headline") or situation.get("topic") or "Manual input").strip()
        for event in situation.get("recent_events") or []:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type") or "").strip().lower()
            if event_type not in {"manual_update", "manual_resolution"}:
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
            key_points = [
                _clean_evidence_text(value)
                for value in (analysis.get("key_points") or [])
                if _clean_evidence_text(value)
            ]
            text_blocks = []
            update_text = _clean_evidence_text(details.get("update_text") or "")
            current_read = _clean_evidence_text(analysis.get("current_read") or "")
            resolution_note = _clean_evidence_text(analysis.get("resolution_note") or "")
            if update_text:
                text_blocks.append(f"User input:\n{update_text}")
            if current_read:
                text_blocks.append(f"Retained truth:\n{current_read}")
            if resolution_note:
                text_blocks.append(f"Resolution note:\n{resolution_note}")
            if key_points:
                text_blocks.append("Key points:\n- " + "\n- ".join(key_points[:6]))
            full_text = "\n\n".join(block for block in text_blocks if block).strip()
            if not full_text:
                continue
            evidence_id = (
                f"manual-{str(situation.get('situation_record_id') or '').strip()}-"
                f"{str(event.get('created_at') or '').strip()}-{event_type}"
            )
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            source_type = "Manual resolution" if event_type == "manual_resolution" else "Manual input"
            title = update_text or current_read or resolution_note or situation_label
            items.append(
                {
                    "evidence_id": evidence_id,
                    "source_kind": event_type,
                    "source_type": source_type,
                    "date_at": str(event.get("created_at") or "").strip(),
                    "date_label": str(event.get("created_at") or "").strip()[:10],
                    "title": _preview_evidence_text(title, limit=160) or situation_label,
                    "preview": _preview_evidence_text(full_text),
                    "content": full_text,
                    "topic": situation_label,
                    "event_id": str(event.get("event_id") or ""),
                    "situation_record_id": str(situation.get("situation_record_id") or ""),
                    "can_edit": True,
                    "can_delete": True,
                    "edit_kind": "manual_event",
                    "edit_payload": {
                        "update_text": update_text,
                        "headline": str(analysis.get("headline") or "").strip(),
                        "current_read": current_read,
                        "why_it_matters": str(analysis.get("why_it_matters") or "").strip(),
                        "stage": str(analysis.get("stage") or "").strip(),
                        "status": str(analysis.get("status") or "").strip(),
                        "momentum": str(analysis.get("momentum") or "").strip(),
                        "recommended_action": str(analysis.get("recommended_action") or "").strip(),
                        "resolution_note": resolution_note,
                        "resolution_type": str(analysis.get("resolution_type") or "").strip(),
                        "confidence_score": int(analysis.get("confidence_score") or 0) if str(analysis.get("confidence_score") or "").strip() else None,
                        "key_points": key_points[:6],
                    },
                }
            )

    return _dedupe_profile_evidence_inputs(items)


def _evidence_source_priority(item: dict) -> int:
    source_kind = str(item.get("source_kind") or "").strip().lower()
    source_type = str(item.get("source_type") or "").strip().lower()
    if source_kind == "manual_resolution":
        return 400
    if source_kind == "manual_update":
        return 360
    if source_type == "topic resolution":
        return 320
    if "meeting response" in source_type:
        return 180
    if "calendar" in source_type or "meeting" in source_type:
        return 170
    if source_type == "email":
        return 160
    if source_type == "whatsapp":
        return 150
    return 100


def _canonical_evidence_text(value: str | None) -> str:
    text = _clean_evidence_text(value).lower()
    text = " ".join(text.split())
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)


def _evidence_duplicate_score(left: dict, right: dict) -> float:
    left_text = _canonical_evidence_text(left.get("content") or left.get("title") or left.get("preview") or "")
    right_text = _canonical_evidence_text(right.get("content") or right.get("title") or right.get("preview") or "")
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    return SequenceMatcher(None, left_text[:500], right_text[:500]).ratio()


def _prefer_evidence_item(left: dict, right: dict) -> dict:
    left_score = (
        _evidence_source_priority(left),
        len(str(left.get("content") or "")),
        len(str(left.get("title") or "")),
    )
    right_score = (
        _evidence_source_priority(right),
        len(str(right.get("content") or "")),
        len(str(right.get("title") or "")),
    )
    return left if left_score >= right_score else right


def _are_duplicate_evidence_items(left: dict, right: dict) -> bool:
    left_date = str(left.get("date_label") or "").strip()
    right_date = str(right.get("date_label") or "").strip()
    if left_date != right_date:
        return False

    left_type = str(left.get("source_type") or "").strip().lower()
    right_type = str(right.get("source_type") or "").strip().lower()
    similarity = _evidence_duplicate_score(left, right)

    if similarity >= 0.995:
        return True
    if left_type == right_type and similarity >= 0.96:
        return True

    resolution_types = {"manual input", "manual resolution", "topic resolution"}
    if left_type in resolution_types and right_type in resolution_types and similarity >= 0.88:
        return True

    if "calendar meeting" in {left_type, right_type} and similarity >= 0.93:
        return True

    return False


def _dedupe_profile_evidence_inputs(items: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    for item in items:
        matched_index = None
        for index, existing in enumerate(deduped):
            if _are_duplicate_evidence_items(item, existing):
                matched_index = index
                break
        if matched_index is None:
            deduped.append(item)
            continue
        deduped[matched_index] = _prefer_evidence_item(deduped[matched_index], item)

    deduped.sort(key=lambda item: (str(item.get("date_at") or ""), str(item.get("evidence_id") or "")), reverse=True)
    return deduped


LEGACY_OPPORTUNITY_STAGE_CODE_MAP = {
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

DEFAULT_STAGE_RELATIONSHIP = [
    {"code": "S1", "label": "S1 Introduction"},
    {"code": "S2", "label": "S2 Understand"},
    {"code": "S3", "label": "S3 Position"},
    {"code": "S4", "label": "S4 Nurture"},
    {"code": "S5", "label": "S5 Problem Identified"},
    {"code": "S6", "label": "S6 Active Discussion"},
    {"code": "S7", "label": "S7 Conversion Pending"},
    {"code": "S8", "label": "S8 Active Client"},
    {"code": "S9", "label": "S9 Active Nurture"},
]

DEFAULT_STAGE_OPPORTUNITY = [
    {"code": "O1", "label": "O1 Mature Problem Identified"},
    {"code": "O2", "label": "O2 Mature Active Discussion"},
    {"code": "O3", "label": "O3 Mature Conversion Pending"},
    {"code": "O4", "label": "O4 Mature Problem Identified"},
    {"code": "O5", "label": "O5 Mature Active Discussion"},
    {"code": "O6", "label": "O6 Mature Conversion Pending"},
    {"code": "O7", "label": "O7 Mature Active Client"},
]

DEFAULT_KNOWLEDGE_BUCKETS = [
    {"code": "K1", "box_key": "family_status", "box_title": "Family Status"},
    {"code": "K2", "box_key": "family_interests", "box_title": "Family Interests"},
    {"code": "K3", "box_key": "personal_interests", "box_title": "Personal Interests"},
    {"code": "K4", "box_key": "business_understanding", "box_title": "Business Understanding"},
    {"code": "K5", "box_key": "challenges_demands", "box_title": "Challenges and Demands"},
    {"code": "K6", "box_key": "recruitment_signals", "box_title": "Recruitment Signals"},
    {"code": "K7", "box_key": "market_intelligence", "box_title": "Market Intelligence"},
    {"code": "K8", "box_key": "taylor_sterling_positioning", "box_title": "Taylor Sterling Positioning"},
    {"code": "K9", "box_key": "obe_interest", "box_title": "OBE Interest"},
    {"code": "K10", "box_key": "action_follow_up", "box_title": "Action / Follow-Up"},
    {"code": "K11", "box_key": "relationship_signal", "box_title": "Relationship Signal"},
]

TRANSCRIPT_TAGGING_APPROACH_VERSION = "global-block-v2"
_TRANSCRIPT_TAGGING_STATE_READY = False
_TRANSCRIPT_SEGMENT_BLOCK_MAX_LINES = 3
_TRANSCRIPT_SEGMENT_BLOCK_MAX_CHARS = 420
_TRANSCRIPT_SEGMENT_LINE_CHUNK_MAX = 260
_TRANSCRIPT_LEARNING_MAX_ROWS = 600
_TRANSCRIPT_LEARNING_FUZZY_THRESHOLD = 0.72

MATURE_NURTURE_MARKERS: tuple[str, ...] = (
    "trusted relationship",
    "mature trusted relationship",
    "active nurture",
    "between assignments",
    "repeat relationship",
)

UNDERSTAND_STAGE_TERMS: tuple[str, ...] = (
    "in charge",
    "responsible for",
    "team size",
    "people in the region",
    "regional director",
)

PERSONAL_HEALTH_SEGMENT_TERMS: tuple[str, ...] = (
    "his back",
    "her back",
    "back pain",
    "back problem",
    "health issue",
    "health issues",
    "surgery",
    "medical leave",
    "hospitalized",
    "hospitalised",
)

BUSINESS_PRESSURE_SEGMENT_TERMS: tuple[str, ...] = (
    "business",
    "workload",
    "delivery",
    "resource",
    "capacity",
    "hiring",
    "recruitment",
    "project",
    "projects",
    "commercial",
    "client",
    "team",
    "market",
    "role",
    "headcount",
)

MIXED_CONTEXT_STAGE_PERSONAL_TERMS: tuple[str, ...] = (
    *PERSONAL_HEALTH_SEGMENT_TERMS,
    "wife",
    "husband",
    "daughter",
    "son",
    "children",
    "family",
    "safe",
    "relationship remains",
)

MIXED_CONTEXT_STAGE_BUSINESS_TERMS: tuple[str, ...] = (
    *BUSINESS_PRESSURE_SEGMENT_TERMS,
    *UNDERSTAND_STAGE_TERMS,
    "leadership",
    "committee",
    "steering committee",
    "region",
    "people",
)

STAGE_SENTENCE_SPLIT_MARKERS: tuple[str, ...] = (
    "other than that",
    "on the other hand",
    "at the same time",
    "however",
)


def _relationship_model() -> str:
    configured = str(getattr(settings, "RELATIONSHIP_STORY_MODEL", "") or "").strip()
    return configured or "gpt-5.2"


def _is_ai_quota_or_rate_error(error: Exception) -> bool:
    if error is None:
        return False
    status_code = getattr(error, "status_code", None)
    try:
        if int(status_code) == 429:
            return True
    except (TypeError, ValueError):
        pass
    text = str(error).lower()
    return any(
        token in text
        for token in (
            "429",
            "insufficient_quota",
            "quota",
            "rate limit",
            "rate_limit",
            "billing",
        )
    )


def _normalize_opportunity_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    return LEGACY_OPPORTUNITY_STAGE_CODE_MAP.get(normalized, normalized)


def _normalize_stage_tag_code(code: str) -> str:
    normalized = str(code or "").strip().upper()
    if re.fullmatch(r"S[1-9]", normalized):
        return normalized
    return _normalize_opportunity_code(normalized)


def _normalize_knowledge_code(code: str) -> str:
    raw = str(code or "").strip().upper()
    match = re.fullmatch(r"K?\s*(\d{1,2})", raw)
    return f"K{int(match.group(1))}" if match else raw


def _knowledge_code_for_box_key(tagging: dict, box_key: str) -> str:
    wanted_key = re.sub(r"[^a-z0-9_]+", "_", str(box_key or "").strip().lower()).strip("_")
    for row in tagging.get("knowledge_buckets") or []:
        if not isinstance(row, dict):
            continue
        row_key = re.sub(r"[^a-z0-9_]+", "_", str(row.get("box_key") or "").strip().lower()).strip("_")
        if row_key != wanted_key:
            continue
        return _normalize_knowledge_code(str(row.get("code") or ""))
    return ""


def _normalize_segment_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _contains_any_term(text: str, terms: set[str] | tuple[str, ...]) -> bool:
    return any(term in text for term in (terms or []))


def _normalize_knowledge_code_for_segment(segment: str, code: str, tagging: dict) -> str:
    normalized = _normalize_knowledge_code(code)
    if not normalized:
        return normalized
    challenge_code = _knowledge_code_for_box_key(tagging, "challenges_demands")
    family_code = _knowledge_code_for_box_key(tagging, "family_status")
    if not challenge_code or not family_code or normalized != challenge_code:
        return normalized
    lowered = _normalize_segment_text(segment)
    has_personal_health = _contains_any_term(lowered, PERSONAL_HEALTH_SEGMENT_TERMS)
    has_business_context = _contains_any_term(lowered, BUSINESS_PRESSURE_SEGMENT_TERMS)
    if has_personal_health and not has_business_context:
        return family_code
    return normalized


def _stage_class(code: str) -> str:
    value = str(code or "").strip().upper()
    if value in {"S1", "S2"}:
        return "stage-early"
    if value in {"S3", "S4"}:
        return "stage-nurture"
    if value in {"S5", "S5M", "O1", "O4", "R1", "R4"}:
        return "stage-problem"
    if value in {"S6", "S6M", "O2", "O5", "R2", "R5"}:
        return "stage-discussion"
    if value in {"S7", "S7M", "O3", "O6", "R3", "R6"}:
        return "stage-conversion"
    if value in {"S8", "O7", "R7"}:
        return "stage-client"
    if value == "S9":
        return "stage-mature"
    return "stage-unknown"


def _split_transcript_segments(value: str, mode: str = "stage") -> list[str]:
    source = str(value or "").replace("\r", "").strip()
    if not source:
        return []
    normalized_mode = str(mode or "stage").strip().lower()
    sentence_level = normalized_mode == "knowledge"
    lines = [" ".join(line.split()).strip() for line in source.split("\n") if line.strip()]
    if not lines:
        return []

    segmented_lines: list[tuple[str, bool]] = []
    for line in lines:
        sentence_chunks = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+", line)
            if part and part.strip()
        ]
        lowered_line = _normalize_segment_text(line)
        force_sentence_level = sentence_level
        if normalized_mode == "stage" and len(sentence_chunks) > 1:
            has_personal_context = _contains_any_term(lowered_line, MIXED_CONTEXT_STAGE_PERSONAL_TERMS)
            has_business_context = _contains_any_term(lowered_line, MIXED_CONTEXT_STAGE_BUSINESS_TERMS)
            has_transition = _contains_any_term(lowered_line, STAGE_SENTENCE_SPLIT_MARKERS)
            force_sentence_level = bool(
                has_transition
                or (has_personal_context and has_business_context)
                or len(sentence_chunks) >= 4
            )
        if force_sentence_level and sentence_chunks:
            segmented_lines.extend((chunk, True) for chunk in sentence_chunks)
            continue
        if len(line) <= _TRANSCRIPT_SEGMENT_LINE_CHUNK_MAX:
            segmented_lines.append((line, False))
            continue
        if len(sentence_chunks) <= 1:
            segmented_lines.extend(
                (chunk.strip(), False)
                for chunk in (
                    line[idx : idx + _TRANSCRIPT_SEGMENT_LINE_CHUNK_MAX]
                    for idx in range(0, len(line), _TRANSCRIPT_SEGMENT_LINE_CHUNK_MAX)
                )
                if chunk.strip()
            )
            continue

        buffer: list[str] = []
        buffer_len = 0
        for chunk in sentence_chunks:
            projected = buffer_len + len(chunk) + (1 if buffer else 0)
            if buffer and projected > _TRANSCRIPT_SEGMENT_LINE_CHUNK_MAX:
                segmented_lines.append((" ".join(buffer).strip(), False))
                buffer = [chunk]
                buffer_len = len(chunk)
            else:
                buffer.append(chunk)
                buffer_len = projected
        if buffer:
            segmented_lines.append((" ".join(buffer).strip(), False))

    segments: list[str] = []
    current: list[str] = []
    current_len = 0
    block_max_lines = 1 if sentence_level else _TRANSCRIPT_SEGMENT_BLOCK_MAX_LINES
    for line, lock_sentence in segmented_lines:
        if lock_sentence:
            if current:
                segments.append(" ".join(current).strip())
                current = []
                current_len = 0
            segments.append(line)
            continue
        projected = current_len + len(line) + (1 if current else 0)
        if current and (
            projected > _TRANSCRIPT_SEGMENT_BLOCK_MAX_CHARS
            or len(current) >= block_max_lines
        ):
            segments.append(" ".join(current).strip())
            current = [line]
            current_len = len(line)
            continue
        current.append(line)
        current_len = projected
    if current:
        segments.append(" ".join(current).strip())
    return segments


def _normalize_tagging_payload(raw: dict | None) -> dict:
    payload = raw if isinstance(raw, dict) else {}
    stage_relationship = payload.get("stage_relationship") if isinstance(payload.get("stage_relationship"), list) else []
    stage_opportunity = payload.get("stage_opportunity") if isinstance(payload.get("stage_opportunity"), list) else []
    knowledge_buckets = payload.get("knowledge_buckets") if isinstance(payload.get("knowledge_buckets"), list) else []
    return {
        "stage_relationship": stage_relationship or DEFAULT_STAGE_RELATIONSHIP,
        "stage_opportunity": stage_opportunity or DEFAULT_STAGE_OPPORTUNITY,
        "knowledge_buckets": knowledge_buckets or DEFAULT_KNOWLEDGE_BUCKETS,
    }


def _stage_tag_map(tagging: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in (tagging.get("stage_relationship") or []) + (tagging.get("stage_opportunity") or []):
        if not isinstance(row, dict):
            continue
        raw_code = str(row.get("code") or "").strip().upper()
        if not raw_code:
            continue
        code = _normalize_stage_tag_code(raw_code)
        if not code:
            continue
        label = str(row.get("label") or code).strip() or code
        result[code] = {
            "code": code,
            "label": label,
            "class_name": _stage_class(code),
        }
    return result


def _knowledge_tag_map(tagging: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in tagging.get("knowledge_buckets") or []:
        if not isinstance(row, dict):
            continue
        raw_code = str(row.get("code") or "").strip().upper()
        box_key = re.sub(r"[^a-z0-9_]+", "_", str(row.get("box_key") or "").strip().lower()).strip("_")
        if not raw_code or not box_key:
            continue
        match_code = re.fullmatch(r"K?\s*(\d{1,2})", raw_code)
        code = f"K{int(match_code.group(1))}" if match_code else raw_code
        title = str(row.get("box_title") or box_key.replace("_", " ").title()).strip() or box_key
        result[code] = {
            "code": code,
            "label": f"{code} {title}".strip(),
            "class_name": f"kb-{box_key}",
        }
    return result


def _tokenize_words(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) >= 3
    }


def _normalize_learning_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = re.sub(r"[^a-z0-9\s]+", "", text)
    return text.strip()


def _segment_hash(value: str) -> str:
    normalized = _normalize_learning_text(value)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _segment_token_signature(value: str, *, limit: int = 24) -> str:
    tokens = sorted(_tokenize_words(_normalize_learning_text(value)))
    return " ".join(tokens[:limit])


def _default_tag_code(mode: str, tagging: dict, tag_map: dict[str, dict]) -> str:
    if not tag_map:
        return ""
    ordered_rows = (
        list(tagging.get("stage_relationship") or []) + list(tagging.get("stage_opportunity") or [])
        if mode == "stage"
        else list(tagging.get("knowledge_buckets") or [])
    )
    for row in ordered_rows:
        raw_code = str((row or {}).get("code") or "").strip().upper()
        code = _normalize_stage_tag_code(raw_code) if mode == "stage" else raw_code
        if code in tag_map:
            return code
    for code in sorted(tag_map.keys()):
        return code
    return ""


async def _ensure_transcript_tagging_state() -> None:
    global _TRANSCRIPT_TAGGING_STATE_READY
    if _TRANSCRIPT_TAGGING_STATE_READY:
        return

    async def _operation(db):
        # Keep transcript content untouched; only reset older approach-specific learning state.
        try:
            await db.execute(
                "DELETE FROM TRANSCRIPT_TAG_OVERRIDE WHERE COALESCE(approach_version, '') != ?",
                (TRANSCRIPT_TAGGING_APPROACH_VERSION,),
            )
        except Exception:
            pass
        try:
            await db.execute(
                "DELETE FROM TRANSCRIPT_TAG_LEARNING WHERE COALESCE(approach_version, '') != ?",
                (TRANSCRIPT_TAGGING_APPROACH_VERSION,),
            )
        except Exception:
            pass

    await run_write(_operation, label="purge legacy transcript tagging approach data")
    _TRANSCRIPT_TAGGING_STATE_READY = True


async def _load_segment_manual_overrides(
    person_id: str,
    evidence_id: str,
    mode: str,
) -> dict[str, dict]:
    if not person_id or not evidence_id:
        return {}
    async with get_db(read_only=True) as db:
        try:
            async with db.execute(
                """
                SELECT segment_hash, tag_code, tag_label, tag_class, updated_at
                FROM TRANSCRIPT_TAG_OVERRIDE
                WHERE person_id = ?
                  AND evidence_id = ?
                  AND mode = ?
                  AND approach_version = ?
                """,
                (person_id, evidence_id, mode, TRANSCRIPT_TAGGING_APPROACH_VERSION),
            ) as cursor:
                rows = [dict(row) for row in await cursor.fetchall()]
        except Exception:
            return {}
    return {
        str(row.get("segment_hash") or "").strip(): row
        for row in rows
        if str(row.get("segment_hash") or "").strip()
    }


async def _load_global_learning_rows(mode: str) -> list[dict]:
    async with get_db(read_only=True) as db:
        try:
            async with db.execute(
                """
                SELECT segment_hash, normalized_text, token_signature, tag_code, tag_label, tag_class, vote_count
                FROM TRANSCRIPT_TAG_LEARNING
                WHERE mode = ?
                  AND approach_version = ?
                ORDER BY vote_count DESC, updated_at DESC
                LIMIT ?
                """,
                (mode, TRANSCRIPT_TAGGING_APPROACH_VERSION, _TRANSCRIPT_LEARNING_MAX_ROWS),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
        except Exception:
            return []


def _pick_learning_match(segment: str, learning_rows: list[dict]) -> Optional[dict]:
    normalized = _normalize_learning_text(segment)
    if not normalized:
        return None
    segment_hash = _segment_hash(segment)
    if not segment_hash:
        return None

    for row in learning_rows:
        if str(row.get("segment_hash") or "").strip() == segment_hash:
            return {
                "tag_code": str(row.get("tag_code") or "").strip().upper(),
                "tag_label": str(row.get("tag_label") or "").strip(),
                "tag_class": str(row.get("tag_class") or "").strip(),
                "confidence": 1.0,
                "reason": "Global learning exact match",
                "source": "global_learning_exact",
            }

    segment_tokens = _tokenize_words(normalized)
    if not segment_tokens:
        return None

    best_row: Optional[dict] = None
    best_score = 0.0
    for row in learning_rows:
        row_text = str(row.get("normalized_text") or "").strip().lower()
        if not row_text:
            continue
        row_tokens = set(str(row.get("token_signature") or "").split())
        if not row_tokens:
            row_tokens = _tokenize_words(row_text)
        if not row_tokens:
            continue
        overlap = len(segment_tokens.intersection(row_tokens))
        if overlap == 0:
            continue
        union = len(segment_tokens.union(row_tokens))
        token_score = (overlap / union) if union else 0.0
        if token_score < 0.45:
            continue
        sequence_score = SequenceMatcher(None, normalized, row_text).ratio()
        votes = max(1, int(row.get("vote_count") or 1))
        score = (token_score * 0.65) + (sequence_score * 0.35) + min(0.12, (votes - 1) * 0.01)
        if score > best_score:
            best_score = score
            best_row = row

    if not best_row or best_score < _TRANSCRIPT_LEARNING_FUZZY_THRESHOLD:
        return None

    return {
        "tag_code": str(best_row.get("tag_code") or "").strip().upper(),
        "tag_label": str(best_row.get("tag_label") or "").strip(),
        "tag_class": str(best_row.get("tag_class") or "").strip(),
        "confidence": max(0.0, min(1.0, best_score)),
        "reason": "Global learning similarity match",
        "source": "global_learning_fuzzy",
    }


async def _resolve_transcript_tagging_payload(explicit_payload: Optional[dict]) -> dict:
    if isinstance(explicit_payload, dict):
        return explicit_payload
    settings_payload = await get_intelligence_settings()
    settings_root = settings_payload.get("settings") if isinstance(settings_payload, dict) else {}
    if isinstance((settings_root or {}).get("transcript_tagging"), dict):
        return settings_root.get("transcript_tagging") or {}
    if isinstance((settings_payload or {}).get("transcript_tagging"), dict):
        return settings_payload.get("transcript_tagging") or {}
    return {}


async def _persist_manual_segment_override(
    *,
    person_id: str,
    evidence_id: str,
    mode: str,
    segment_text: str,
    tag_code: str,
    tag_label: str,
    tag_class: str,
) -> None:
    segment_hash = _segment_hash(segment_text)
    if not segment_hash:
        return
    normalized_text = _normalize_learning_text(segment_text)
    token_signature = _segment_token_signature(segment_text)
    now = _now()

    async def _operation(db):
        await db.execute(
            """
            INSERT INTO TRANSCRIPT_TAG_OVERRIDE
            (override_id, person_id, evidence_id, mode, segment_hash, segment_text, tag_code, tag_label, tag_class, approach_version, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(person_id, evidence_id, mode, segment_hash, approach_version) DO UPDATE SET
                segment_text = excluded.segment_text,
                tag_code = excluded.tag_code,
                tag_label = excluded.tag_label,
                tag_class = excluded.tag_class,
                updated_at = excluded.updated_at
            """,
            (
                str(uuid.uuid4()),
                person_id,
                evidence_id,
                mode,
                segment_hash,
                str(segment_text or "").strip(),
                tag_code,
                tag_label,
                tag_class,
                TRANSCRIPT_TAGGING_APPROACH_VERSION,
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO TRANSCRIPT_TAG_LEARNING
            (learning_id, mode, segment_hash, normalized_text, token_signature, tag_code, tag_label, tag_class, vote_count, last_person_id, approach_version, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,1,?,?,?,?)
            ON CONFLICT(mode, segment_hash, approach_version) DO UPDATE SET
                normalized_text = excluded.normalized_text,
                token_signature = excluded.token_signature,
                tag_code = excluded.tag_code,
                tag_label = excluded.tag_label,
                tag_class = excluded.tag_class,
                vote_count = COALESCE(TRANSCRIPT_TAG_LEARNING.vote_count, 0) + 1,
                last_person_id = excluded.last_person_id,
                updated_at = excluded.updated_at
            """,
            (
                str(uuid.uuid4()),
                mode,
                segment_hash,
                normalized_text,
                token_signature,
                tag_code,
                tag_label,
                tag_class,
                person_id,
                TRANSCRIPT_TAGGING_APPROACH_VERSION,
                now,
                now,
            ),
        )

    await run_write(_operation, label=f"save transcript tag override {person_id}:{mode}:{evidence_id}")


class TranscriptSegmentTagRequest(BaseModel):
    mode: str = "stage"
    evidence_id: Optional[str] = None
    content: str = ""
    transcript_tagging: Optional[dict] = None


class TranscriptSegmentOverrideRequest(BaseModel):
    mode: str = "stage"
    evidence_id: str
    segment_text: str
    tag_code: str
    transcript_tagging: Optional[dict] = None


class CompanyOpportunityCreate(BaseModel):
    company_name_raw: str
    opportunity_type: Optional[str] = None
    stage: Optional[str] = None
    value_band: Optional[str] = None
    trigger_date: Optional[str] = None
    strategic_importance: int = 50
    status: str = "open"
    owner: Optional[str] = None
    notes: Optional[str] = None


class CompanyOpportunityUpdate(BaseModel):
    company_name_raw: Optional[str] = None
    opportunity_type: Optional[str] = None
    stage: Optional[str] = None
    value_band: Optional[str] = None
    trigger_date: Optional[str] = None
    strategic_importance: Optional[int] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


class BulkUpdateRequest(BaseModel):
    person_ids: list[str]
    network_tier: Optional[str] = None
    maintenance_mode: Optional[str] = None
    relationship_owner: Optional[str] = None
    account_priority: Optional[str] = None
    create_task_text: Optional[str] = None
    create_task_due_date: Optional[str] = None


class ManualSituationEventUpdateRequest(BaseModel):
    update_text: str
    headline: Optional[str] = None
    current_read: Optional[str] = None
    why_it_matters: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    momentum: Optional[str] = None
    recommended_action: Optional[str] = None
    resolution_note: Optional[str] = None
    resolution_type: Optional[str] = None
    confidence_score: Optional[int] = None
    key_points: list[str] = []


class PilotCohortRequest(BaseModel):
    person_ids: list[str] = []


class PromoteMemoryRequest(BaseModel):
    memory_domain: str
    status: str = "approved"


class PromoteMarketIntelRequest(BaseModel):
    status: str = "approved"


class ReviewStatusRequest(BaseModel):
    status: str


class ClaimActionRequest(BaseModel):
    action: str
    claim_text: str
    target_claim_text: Optional[str] = None
    reason: Optional[str] = None


class ManualResolutionRequest(BaseModel):
    text: str
    summary: Optional[str] = None


class ActionUpdateRequest(BaseModel):
    action_text: str
    status: str
    reason: Optional[str] = None
    owner: Optional[str] = "Marcus"
    urgency: Optional[str] = None
    due_window: Optional[str] = None
    action_type: Optional[str] = None
    why_now: Optional[str] = None
    blocker: Optional[str] = None
    consequence_if_missed: Optional[str] = None
    linked_claim_ids: list[str] = []


@router.get("/workspace")
async def get_workspace():
    feed = await build_network_feed()
    review = {
        "missing_tier": [],
        "missing_owner": [],
        "invisible_contacts": [],
        "missing_mode": [],
    }
    for queue_name in ("act_now", "maintain", "preserve", "monitor"):
        for item in feed[queue_name]:
            if not item.get("network_tier"):
                review["missing_tier"].append(item)
            if not item.get("maintenance_mode"):
                review["missing_mode"].append(item)
            if not item.get("relationship_owner"):
                review["missing_owner"].append(item)
            if not item.get("has_relationship_signal") and not item.get("has_future_cover"):
                review["invisible_contacts"].append(item)

    everyone = [
        item
        for queue_name in ("act_now", "maintain", "preserve", "monitor")
        for item in feed[queue_name]
    ]
    pilot_ids, pilot_summary = await resolve_pilot_cohort(feed)

    for item in everyone:
        item["is_pilot_cohort"] = item["person_id"] in pilot_ids

    feed["review"] = review
    feed["pilot_cohort_ids"] = pilot_ids
    feed["pilot_cohort_summary"] = pilot_summary
    feed["pilot_cohort_mode"] = pilot_summary.get("mode") or "recommended"
    return feed


@router.get("/databank")
async def get_network_databank(scope: str = "pilot"):
    feed = await build_network_feed()
    pilot_ids, pilot_summary = await resolve_pilot_cohort(feed)
    if scope == "all":
        person_ids = [
            item["person_id"]
            for queue_name in ("act_now", "maintain", "preserve", "monitor")
            for item in feed[queue_name]
        ]
    else:
        person_ids = pilot_ids

    for person_id in person_ids[:60]:
        await refresh_interpreted_interactions_for_person(person_id)

    databank = await load_interpreted_databank(person_ids)
    databank["scope"] = scope
    databank["pilot_cohort_summary"] = pilot_summary
    databank["pilot_cohort_mode"] = pilot_summary.get("mode") or "recommended"
    return databank


@router.get("/review-queue")
async def get_review_queue(scope: str = "pilot"):
    feed = await build_network_feed()
    pilot_ids, pilot_summary = await resolve_pilot_cohort(feed)
    if scope == "all":
        person_ids = [
            item["person_id"]
            for queue_name in ("act_now", "maintain", "preserve", "monitor")
            for item in feed[queue_name]
        ]
    else:
        person_ids = pilot_ids

    for person_id in person_ids[:60]:
        await refresh_interpreted_interactions_for_person(person_id)

    queue = await load_review_queue(person_ids)
    queue["scope"] = scope
    queue["pilot_cohort_summary"] = pilot_summary
    queue["pilot_cohort_mode"] = pilot_summary.get("mode") or "recommended"
    return queue


@router.get("/owners")
async def list_owners():
    async with get_db() as db:
        async with db.execute(
            "SELECT user_id, full_name, email, role FROM USER WHERE is_active = 1 ORDER BY full_name COLLATE NOCASE"
        ) as cursor:
            owners = [dict(row) for row in await cursor.fetchall()]
    return {"owners": owners}


@router.get("/profile/{person_id}")
async def get_network_profile(person_id: str):
    relevance_cutoff = (datetime.now(timezone.utc) - timedelta(days=365 * 4)).isoformat()
    async with get_db() as db:
        async with db.execute("SELECT * FROM PERSON WHERE person_id=? AND is_active=1", (person_id,)) as cursor:
            person = await cursor.fetchone()
        if not person:
            raise HTTPException(404, "Person not found")

        async with db.execute(
            """
            SELECT opportunity_id, account_name, opportunity_type, stage, value_band, trigger_date,
                   strategic_importance, status, owner, notes, created_at, updated_at
            FROM PERSON_OPPORTUNITY
            WHERE person_id=?
            ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, trigger_date ASC, updated_at DESC
            """,
            (person_id,),
        ) as cursor:
            person_opportunities = [dict(row) for row in await cursor.fetchall()]

        async with db.execute(
            """
            SELECT company_opportunity_id, company_name_raw, opportunity_type, stage, value_band, trigger_date,
                   strategic_importance, status, owner, notes, created_at, updated_at
            FROM COMPANY_OPPORTUNITY
            WHERE LOWER(TRIM(company_name_raw)) = LOWER(TRIM(?))
            ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, trigger_date ASC, updated_at DESC
            """,
            (person["company_name_raw"],),
        ) as cursor:
            company_opportunities = [dict(row) for row in await cursor.fetchall()]

        async with db.execute(
            """
            SELECT COUNT(*) AS interaction_count
            FROM INTERACTION i
            WHERE i.person_id=?
              AND COALESCE(i.channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(i.summary, i.raw_text, '')) != ''
              AND datetime(i.interaction_at) >= datetime(?)
              AND NOT EXISTS (
                  SELECT 1
                  FROM AI_ARTIFACT aa
                  WHERE aa.source_interaction_id = i.interaction_id
                    AND (
                        LOWER(COALESCE(aa.input_type, '')) = 'profile_picture'
                        OR LOWER(COALESCE(aa.extracted_metadata_json, '') || ' ' || COALESCE(aa.metadata, '')) LIKE '%"is_profile_photo"%true%'
                    )
              )
            """,
            (person_id, relevance_cutoff),
        ) as cursor:
            interaction_row = await cursor.fetchone()
            relevant_interaction_count = int(interaction_row["interaction_count"] or 0) if interaction_row else 0

        async with db.execute(
            """
            SELECT i.interaction_id, i.channel, i.interaction_at, i.summary, i.raw_text
            FROM INTERACTION i
            WHERE i.person_id=?
              AND COALESCE(i.channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(i.summary, i.raw_text, '')) != ''
              AND datetime(i.interaction_at) >= datetime(?)
              AND NOT EXISTS (
                  SELECT 1
                  FROM AI_ARTIFACT aa
                  WHERE aa.source_interaction_id = i.interaction_id
                    AND (
                        LOWER(COALESCE(aa.input_type, '')) = 'profile_picture'
                        OR LOWER(COALESCE(aa.extracted_metadata_json, '') || ' ' || COALESCE(aa.metadata, '')) LIKE '%"is_profile_photo"%true%'
                    )
              )
            ORDER BY datetime(i.interaction_at) DESC, i.interaction_id DESC
            LIMIT 12
            """,
            (person_id, relevance_cutoff),
        ) as cursor:
            recent_evidence = [dict(row) for row in await cursor.fetchall()]

        async with db.execute(
            """
            SELECT i.interaction_id, i.channel, i.interaction_at, i.summary, i.raw_text
            FROM INTERACTION i
            WHERE i.person_id=?
              AND COALESCE(i.channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(i.summary, i.raw_text, '')) != ''
              AND datetime(i.interaction_at) >= datetime(?)
              AND NOT EXISTS (
                  SELECT 1
                  FROM AI_ARTIFACT aa
                  WHERE aa.source_interaction_id = i.interaction_id
                    AND (
                        LOWER(COALESCE(aa.input_type, '')) = 'profile_picture'
                        OR LOWER(COALESCE(aa.extracted_metadata_json, '') || ' ' || COALESCE(aa.metadata, '')) LIKE '%"is_profile_photo"%true%'
                    )
              )
            ORDER BY datetime(i.interaction_at) DESC, i.interaction_id DESC
            LIMIT 30
            """,
            (person_id, relevance_cutoff),
        ) as cursor:
            story_raw_interactions = [dict(row) for row in await cursor.fetchall()]

        async with db.execute(
            """
            SELECT i.interaction_id, i.channel, i.interaction_at, i.summary, i.raw_text
            FROM INTERACTION i
            WHERE i.person_id=?
              AND COALESCE(i.channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(i.summary, i.raw_text, '')) != ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM AI_ARTIFACT aa
                  WHERE aa.source_interaction_id = i.interaction_id
                    AND (
                        LOWER(COALESCE(aa.input_type, '')) = 'profile_picture'
                        OR LOWER(COALESCE(aa.extracted_metadata_json, '') || ' ' || COALESCE(aa.metadata, '')) LIKE '%"is_profile_photo"%true%'
                    )
              )
            ORDER BY datetime(i.interaction_at) DESC, i.interaction_id DESC
            LIMIT 250
            """,
            (person_id,),
        ) as cursor:
            all_evidence_interactions = [dict(row) for row in await cursor.fetchall()]

    feed = await build_network_feed()
    is_pilot_profile, pilot_summary = await is_person_in_pilot_cohort(person_id, feed)
    await refresh_interpreted_interactions_for_person(person_id, limit=24)
    interpreted_interactions = await load_interpreted_interactions(person_id, limit=8)
    personal_memory_interpreted_interactions = await load_interpreted_interactions(person_id, limit=24)
    interpretation_summary = build_interpreted_memory_summary(interpreted_interactions)
    storyline = build_storyline_state(interpreted_interactions)
    await sync_relationship_situations_for_person(
        person_id,
        storyline.get("storyline_groups", []),
        relationship_owner=person["relationship_owner"],
        company_name_raw=person["company_name_raw"],
    )
    tracked_situations = await load_relationship_situations_for_person(person_id)
    story_thread_situations = await load_relationship_situations_for_person(person_id, include_closed=True, limit=20)
    storyline["storyline_groups"] = tracked_situations
    storyline["tracked_situations"] = tracked_situations
    promoted_memory = await load_promoted_memory_for_person(person_id)
    related_team_context = await load_related_team_context(
        person_id=person_id,
        company_name_raw=person["company_name_raw"],
    )
    signals = await load_profile_signals(person_id)
    relationship_topics = build_relationship_topics(
        person=dict(person),
        tracked_situations=tracked_situations,
        related_team_context=related_team_context,
    )
    relationship_topics["clarification_prompts"] = [
        {
            **item,
            "evidence_details": _build_clarification_context_fallback(item, recent_evidence, signals),
        }
        for item in relationship_topics.get("clarification_prompts") or []
    ]
    relationship_story = build_relationship_story(
        person=dict(person),
        tracked_situations=tracked_situations,
        relationship_topics=relationship_topics,
        recent_evidence=recent_evidence,
        interpreted_interactions=personal_memory_interpreted_interactions,
        promoted_memory=promoted_memory,
    )
    story_thread = await generate_relationship_story_thread(
        person=dict(person),
        raw_interactions=list(reversed(story_raw_interactions)),
        tracked_situations=story_thread_situations,
        promoted_memory=promoted_memory,
        relationship_story=relationship_story,
    )
    evidence_inputs = _build_profile_evidence_inputs(
        all_evidence_interactions,
        story_thread_situations,
    )
    conversation_prep = build_conversation_prep(
        person=dict(person),
        interpreted_interactions=interpreted_interactions,
        tracked_situations=tracked_situations,
        recent_evidence=recent_evidence,
        person_opportunities=person_opportunities,
        company_opportunities=company_opportunities,
        relevant_interaction_count=relevant_interaction_count,
        related_team_context=related_team_context,
        relationship_topics=relationship_topics,
        relationship_story=relationship_story,
    )

    all_people = {
        item["person_id"]: item
        for bucket in ("act_now", "maintain", "preserve", "monitor")
        for item in feed[bucket]
    }
    queue_context = all_people.get(person_id)
    resolved_queue_context = await get_network_contact_context(person_id)
    if resolved_queue_context:
        queue_context = {**(queue_context or {}), **resolved_queue_context}
    surfaced_signals, draft_signals = _build_profile_intelligence_layers(
        tracked_situations=tracked_situations,
        promoted_memory=promoted_memory,
        legacy_signals=signals,
        interpreted_interactions=interpreted_interactions,
    )
    return {
        "person": dict(person),
        "queue_context": all_people.get(person_id),
        "is_pilot_profile": is_pilot_profile,
        "pilot_cohort_mode": pilot_summary.get("mode") or "recommended",
        "pilot_cohort_summary": pilot_summary,
        "person_opportunities": person_opportunities,
        "company_opportunities": company_opportunities,
        "surfaced_intelligence": surfaced_signals,
        "draft_intelligence": draft_signals,
        "recent_evidence": recent_evidence,
        "evidence_inputs": evidence_inputs,
        "conversation_prep": conversation_prep,
        "relationship_story": relationship_story,
        "story_thread": story_thread,
        "related_team_context": related_team_context,
        "relationship_topics": relationship_topics,
        "interpreted_interactions": interpreted_interactions,
        "network_score_context": queue_context,
        "score": (queue_context or {}).get("network_health_score"),
        "score_band": (queue_context or {}).get("score_band"),
        "queue": (queue_context or {}).get("queue_key"),
        "queue_reason": (queue_context or {}).get("queue_reason"),
        **storyline,
        **promoted_memory,
        **interpretation_summary,
    }


@router.get("/profile/{person_id}/relationship-intelligence")
async def get_profile_relationship_intelligence(person_id: str, force_refresh: bool = False):
    async with get_db() as db:
        async with db.execute(
            """
            SELECT *
            FROM PERSON
            WHERE person_id=?
            """,
            (person_id,),
        ) as cursor:
            person = await cursor.fetchone()
        if not person:
            raise HTTPException(404, "Person not found")

        async with db.execute(
            """
            SELECT i.interaction_id, i.channel, i.interaction_at, i.summary, i.raw_text
            FROM INTERACTION i
            WHERE i.person_id=?
              AND COALESCE(i.channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(i.summary, i.raw_text, '')) != ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM AI_ARTIFACT aa
                  WHERE aa.source_interaction_id = i.interaction_id
                    AND (
                        LOWER(COALESCE(aa.input_type, '')) = 'profile_picture'
                        OR LOWER(COALESCE(aa.extracted_metadata_json, '') || ' ' || COALESCE(aa.metadata, '')) LIKE '%"is_profile_photo"%true%'
                    )
              )
            ORDER BY datetime(i.interaction_at) DESC, i.interaction_id DESC
            LIMIT 250
            """,
            (person_id,),
        ) as cursor:
            all_evidence_interactions = [dict(row) for row in await cursor.fetchall()]

    tracked_situations = await load_relationship_situations_for_person(person_id, include_closed=True, limit=20)
    evidence_inputs = _build_profile_evidence_inputs(
        all_evidence_interactions,
        tracked_situations,
    )
    intelligence = await build_relationship_intelligence_pipeline(
        person=dict(person),
        evidence_inputs=evidence_inputs,
        force_refresh=force_refresh,
    )
    return {
        "person": dict(person),
        **intelligence,
    }


@router.post("/profile/{person_id}/relationship-intelligence/refresh")
async def refresh_profile_relationship_intelligence(person_id: str):
    payload = await get_profile_relationship_intelligence(person_id, force_refresh=True)
    return {"status": "success", **payload}


@router.post("/profile/{person_id}/transcript-segment-tags")
async def tag_profile_transcript_segments(person_id: str, req: TranscriptSegmentTagRequest):
    await _ensure_transcript_tagging_state()
    async with get_db() as db:
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            person = await cursor.fetchone()
        if not person:
            raise HTTPException(404, "Person not found")

    mode = str(req.mode or "stage").strip().lower()
    if mode not in {"stage", "knowledge"}:
        raise HTTPException(400, "mode must be 'stage' or 'knowledge'")

    content = str(req.content or "").strip()
    if not content:
        return {
            "status": "success",
            "person_id": person_id,
            "mode": mode,
            "model_name": _relationship_model(),
            "evidence_id": str(req.evidence_id or "").strip() or None,
            "approach_version": TRANSCRIPT_TAGGING_APPROACH_VERSION,
            "segments": [],
            "totals": {"tagged_segments": 0, "total_segments": 0},
        }

    tagging_payload = await _resolve_transcript_tagging_payload(
        req.transcript_tagging if isinstance(req.transcript_tagging, dict) else None
    )
    tagging = _normalize_tagging_payload(tagging_payload)
    tag_map = _stage_tag_map(tagging) if mode == "stage" else _knowledge_tag_map(tagging)
    if not tag_map:
        raise HTTPException(400, "No configured tags available for this mode")

    evidence_id = str(req.evidence_id or "").strip()
    segments = [
        segment
        for segment in _split_transcript_segments(content, mode=mode)
        if not _is_non_transcript_chat_input(segment)
    ]
    if not segments:
        return {
            "status": "success",
            "person_id": person_id,
            "mode": mode,
            "model_name": _relationship_model(),
            "evidence_id": evidence_id or None,
            "approach_version": TRANSCRIPT_TAGGING_APPROACH_VERSION,
            "segments": [],
            "totals": {"tagged_segments": 0, "total_segments": 0},
        }

    segment_hashes = [_segment_hash(segment) for segment in segments]
    manual_overrides = await _load_segment_manual_overrides(person_id, evidence_id, mode) if evidence_id else {}
    learning_rows = await _load_global_learning_rows(mode)
    learning_by_hash = {
        str(row.get("segment_hash") or "").strip(): row
        for row in learning_rows
        if str(row.get("segment_hash") or "").strip()
    }

    allowed_tags = [
        {"code": str(row["code"]), "label": str(row["label"])}
        for row in tag_map.values()
    ]
    default_code = _default_tag_code(mode, tagging, tag_map)
    by_index: dict[int, dict] = {}
    prefilled_indexes: set[int] = set()
    for index, segment in enumerate(segments):
        segment_hash = segment_hashes[index]
        manual_row = manual_overrides.get(segment_hash)
        if manual_row:
            manual_code = str(manual_row.get("tag_code") or "").strip().upper()
            if mode == "stage":
                manual_code = _normalize_stage_tag_code(manual_code)
            else:
                manual_code = _normalize_knowledge_code(manual_code)
            if manual_code in tag_map:
                by_index[index] = {
                    "code": manual_code,
                    "confidence": 1.0,
                    "reason": "Manual tag override",
                    "source": "manual_override",
                }
                prefilled_indexes.add(index)
                continue
        learning_row = learning_by_hash.get(segment_hash)
        if learning_row:
            learned_code = str(learning_row.get("tag_code") or "").strip().upper()
            if mode == "stage":
                learned_code = _normalize_stage_code_for_segment(segment, learned_code)
            else:
                learned_code = _normalize_knowledge_code_for_segment(segment, learned_code, tagging)
            if learned_code in tag_map:
                by_index[index] = {
                    "code": learned_code,
                    "confidence": 1.0,
                    "reason": "Global learning exact match",
                    "source": "global_learning_exact",
                }
                prefilled_indexes.add(index)

    unresolved_indexes = [index for index in range(len(segments)) if index not in prefilled_indexes]
    model_name = _relationship_model()
    model_degraded = False
    model_error = ""
    if unresolved_indexes:
        knowledge_mode_guidance = []
        if mode == "knowledge":
            knowledge_mode_guidance = [
                "Knowledge mode uses sentence-level blocks; classify the strongest factual signal in each sentence.",
                "Prefer Business Understanding for company services, remit, market footprint, and operating geography.",
                "Prefer Taylor Sterling Positioning for statements about what they know about Taylor Sterling capabilities.",
                "Use Relationship Signal only for trust, rapport, access quality, or relationship-depth statements.",
            ]
        messages = [
            {
                "role": "system",
                "content": (
                    "You classify transcript blocks into strict CRM tags. "
                    "Each block can include multiple related sentences, and the full block context must be used. "
                    "Only use the provided block text; do not infer from external profile history. "
                    "Return JSON only."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Classify each block with exactly one allowed tag code.",
                        "mode": mode,
                        "rules": [
                            "Only use tag codes in allowed_tags.",
                            "Return one result for every block index in blocks.",
                            "Keep confidence between 0 and 1.",
                            *knowledge_mode_guidance,
                        ],
                        "allowed_tags": allowed_tags,
                        "blocks": [
                            {"index": index, "text": segments[index]}
                            for index in unresolved_indexes
                        ],
                        "return_schema": {
                            "blocks": [
                                {
                                    "index": 0,
                                    "tag_code": "K1 or S1 or O1",
                                    "confidence": 0.0,
                                    "reason": "short reason",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            llm_result, _ = await run_json_chat_task(
                task_type="relationship_transcript_segment_tagging",
                prompt_family="relationship_transcript_segment_tagging_v2",
                messages=messages,
                model=model_name,
                temperature=0.0,
                related_profile_id=person_id,
                metadata={
                    "mode": mode,
                    "segment_count": len(unresolved_indexes),
                    "approach_version": TRANSCRIPT_TAGGING_APPROACH_VERSION,
                },
            )
        except Exception as exc:
            if _is_ai_quota_or_rate_error(exc) or "openai api key not configured" in str(exc).lower():
                llm_result = {}
                model_degraded = True
                model_error = str(exc).strip()
            else:
                raise HTTPException(502, f"Transcript tagging failed: {exc}") from exc

        raw_rows = []
        if isinstance(llm_result, dict):
            if isinstance(llm_result.get("blocks"), list):
                raw_rows = llm_result.get("blocks") or []
            elif isinstance(llm_result.get("segments"), list):
                raw_rows = llm_result.get("segments") or []
        for row in raw_rows if isinstance(raw_rows, list) else []:
            if not isinstance(row, dict):
                continue
            try:
                index = int(row.get("index"))
            except (TypeError, ValueError):
                continue
            if index not in unresolved_indexes:
                continue
            raw_code = str(row.get("tag_code") or "").strip().upper()
            if mode == "stage":
                code = _normalize_stage_code_for_segment(segments[index], raw_code)
            else:
                code = _normalize_knowledge_code_for_segment(segments[index], raw_code, tagging)
            confidence_raw = row.get("confidence")
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            by_index[index] = {
                "code": code,
                "confidence": confidence,
                "reason": str(row.get("reason") or "").strip(),
                "source": "model",
            }

    response_rows: list[dict] = []
    tagged_segments = 0
    for index, segment in enumerate(segments):
        tagged = by_index.get(index)
        code = str((tagged or {}).get("code") or "").strip().upper()
        if mode == "stage":
            code = _normalize_stage_code_for_segment(segment, code)
        else:
            code = _normalize_knowledge_code_for_segment(segment, code, tagging)
        mapped = code in tag_map
        if not mapped:
            learning_match = _pick_learning_match(segment, learning_rows)
            if learning_match:
                learned_code = str(learning_match.get("tag_code") or "").strip().upper()
                if mode == "stage":
                    learned_code = _normalize_stage_code_for_segment(segment, learned_code)
                else:
                    learned_code = _normalize_knowledge_code_for_segment(segment, learned_code, tagging)
                if learned_code in tag_map:
                    code = learned_code
                    tagged = {
                        "code": learned_code,
                        "confidence": float(learning_match.get("confidence") or 0.0),
                        "reason": str(learning_match.get("reason") or "").strip(),
                        "source": str(learning_match.get("source") or "global_learning_fuzzy"),
                    }
                    mapped = True
        if not mapped:
            code = default_code
            mapped = code in tag_map
            fallback_reason = "Model unavailable; default tag mapping used" if model_degraded else "Default tag mapping used"
            fallback_source = "default_mapping_model_unavailable" if model_degraded else "default_mapping"
            tagged = {
                "code": code,
                "confidence": float((tagged or {}).get("confidence") or 0.2),
                "reason": str((tagged or {}).get("reason") or fallback_reason),
                "source": str((tagged or {}).get("source") or fallback_source),
            }
        if mapped:
            tagged_segments += 1
        metadata = tag_map.get(code) if mapped else None
        response_rows.append(
            {
                "index": index,
                "segment_hash": segment_hashes[index],
                "text": segment,
                "tag_code": code if mapped else "",
                "tag_label": (metadata or {}).get("label") or "",
                "tag_class": (metadata or {}).get("class_name") or ("kb-unknown" if mode == "knowledge" else "stage-unknown"),
                "mapped": mapped,
                "confidence": float((tagged or {}).get("confidence") or 0.0),
                "reason": str((tagged or {}).get("reason") or ""),
                "source": str((tagged or {}).get("source") or ""),
            }
        )

    return {
        "status": "success",
        "person_id": person_id,
        "mode": mode,
        "model_name": model_name,
        "evidence_id": evidence_id or None,
        "approach_version": TRANSCRIPT_TAGGING_APPROACH_VERSION,
        "model_degraded": model_degraded,
        "model_error": model_error[:220] if model_error else None,
        "segments": response_rows,
        "totals": {
            "tagged_segments": tagged_segments,
            "total_segments": len(segments),
        },
    }


@router.post("/profile/{person_id}/transcript-segment-tags/override")
async def set_profile_transcript_segment_override(person_id: str, req: TranscriptSegmentOverrideRequest):
    await _ensure_transcript_tagging_state()
    async with get_db() as db:
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            person = await cursor.fetchone()
        if not person:
            raise HTTPException(404, "Person not found")

    mode = str(req.mode or "stage").strip().lower()
    if mode not in {"stage", "knowledge"}:
        raise HTTPException(400, "mode must be 'stage' or 'knowledge'")

    evidence_id = str(req.evidence_id or "").strip()
    segment_text = str(req.segment_text or "").strip()
    raw_tag_code = str(req.tag_code or "").strip().upper()
    if not evidence_id:
        raise HTTPException(400, "evidence_id is required")
    if not segment_text:
        raise HTTPException(400, "segment_text is required")
    if not raw_tag_code:
        raise HTTPException(400, "tag_code is required")

    tagging_payload = await _resolve_transcript_tagging_payload(
        req.transcript_tagging if isinstance(req.transcript_tagging, dict) else None
    )
    tagging = _normalize_tagging_payload(tagging_payload)
    tag_map = _stage_tag_map(tagging) if mode == "stage" else _knowledge_tag_map(tagging)
    if not tag_map:
        raise HTTPException(400, "No configured tags available for this mode")

    tag_code = _normalize_stage_tag_code(raw_tag_code) if mode == "stage" else raw_tag_code
    metadata = tag_map.get(tag_code)
    if not metadata:
        raise HTTPException(400, f"Invalid tag code '{raw_tag_code}' for mode '{mode}'")

    await _persist_manual_segment_override(
        person_id=person_id,
        evidence_id=evidence_id,
        mode=mode,
        segment_text=segment_text,
        tag_code=tag_code,
        tag_label=str(metadata.get("label") or tag_code),
        tag_class=str(metadata.get("class_name") or ("kb-unknown" if mode == "knowledge" else "stage-unknown")),
    )

    return {
        "status": "success",
        "person_id": person_id,
        "mode": mode,
        "evidence_id": evidence_id,
        "segment_hash": _segment_hash(segment_text),
        "segment_text": segment_text,
        "tag_code": tag_code,
        "tag_label": str(metadata.get("label") or tag_code),
        "tag_class": str(metadata.get("class_name") or ("kb-unknown" if mode == "knowledge" else "stage-unknown")),
        "source": "manual_override",
        "approach_version": TRANSCRIPT_TAGGING_APPROACH_VERSION,
    }


@router.post("/profile/{person_id}/claims/action")
async def apply_claim_action(person_id: str, req: ClaimActionRequest):
    action = str(req.action or "").strip().lower()
    if action not in {"retire", "promote", "uncertain", "merge_duplicate"}:
        raise HTTPException(400, "Invalid claim action")
    if action == "merge_duplicate" and not str(req.target_claim_text or "").strip():
        raise HTTPException(400, "target_claim_text is required for merge_duplicate")

    async def _person_exists(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            return await cursor.fetchone()

    person = await run_write(_person_exists, label=f"check person for claim action {person_id}")
    if not person:
        raise HTTPException(404, "Person not found")

    now = datetime.now(timezone.utc).isoformat()
    interaction_id = str(uuid.uuid4())
    payload = {
        "action": action,
        "claim_text": str(req.claim_text or "").strip(),
        "target_claim_text": str(req.target_claim_text or "").strip(),
        "reason": str(req.reason or "").strip(),
        "created_at": now,
    }
    summary_action = action.replace("_", " ")
    summary = f"Claim action: {summary_action} | {payload['claim_text'][:140]}"

    async def _insert_claim_override(db):
        await db.execute(
            """
            INSERT INTO INTERACTION
            (interaction_id, person_id, channel, raw_text, summary, action_items, topics, sentiment, created_at, interaction_at)
            VALUES (?,?,?,?,?,'[]','[]','neutral',?,?)
            """,
            (
                interaction_id,
                person_id,
                "manual_resolution",
                f"CLAIM_OVERRIDE::{json.dumps(payload, ensure_ascii=False)}",
                summary,
                now,
                now,
            ),
        )
        await db.execute(
            "UPDATE PERSON SET last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
            (now, person_id),
        )

    await run_write(_insert_claim_override, label=f"apply claim action {person_id}")
    return {"status": "success", "interaction_id": interaction_id, "payload": payload}


@router.post("/profile/{person_id}/manual-resolution")
async def add_manual_resolution(person_id: str, req: ManualResolutionRequest):
    async def _person_exists(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)) as cursor:
            return await cursor.fetchone()

    person = await run_write(_person_exists, label=f"check person for manual resolution {person_id}")
    if not person:
        raise HTTPException(404, "Person not found")

    now = datetime.now(timezone.utc).isoformat()
    interaction_id = str(uuid.uuid4())
    summary = str(req.summary or req.text[:180]).strip()

    async def _insert_manual_resolution(db):
        await db.execute(
            """
            INSERT INTO INTERACTION
            (interaction_id, person_id, channel, raw_text, summary, action_items, topics, sentiment, created_at, interaction_at)
            VALUES (?,?,?,?,?,'[]','[]','neutral',?,?)
            """,
            (
                interaction_id,
                person_id,
                "manual_resolution",
                str(req.text or "").strip(),
                summary,
                now,
                now,
            ),
        )
        await db.execute(
            "UPDATE PERSON SET last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
            (now, person_id),
        )

    await run_write(_insert_manual_resolution, label=f"add manual resolution {person_id}")
    return {"status": "success", "interaction_id": interaction_id}


@router.post("/profile/{person_id}/actions/update")
async def update_action_status(person_id: str, req: ActionUpdateRequest):
    status = str(req.status or "").strip().lower()
    if status not in {"open", "in_progress", "completed", "stale", "missed", "cancelled"}:
        raise HTTPException(400, "Invalid action status")
    person = await _load_person(person_id)
    if not person:
        raise HTTPException(404, "Person not found")

    interaction_id = str(uuid.uuid4())
    now = _now_iso()
    payload = {
        "action_text": str(req.action_text or "").strip(),
        "status": status,
        "reason": str(req.reason or "").strip(),
        "owner": str(req.owner or "Marcus").strip() or "Marcus",
        "urgency": str(req.urgency or "").strip().lower(),
        "due_window": str(req.due_window or "").strip(),
        "action_type": str(req.action_type or "").strip(),
        "why_now": str(req.why_now or "").strip(),
        "blocker": str(req.blocker or "").strip(),
        "consequence_if_missed": str(req.consequence_if_missed or "").strip(),
        "linked_claim_ids": list(req.linked_claim_ids or []),
        "updated_at": now,
    }
    summary = f"Action update: {status.replace('_', ' ')} | {payload['action_text'][:140]}"

    async def _insert_action_override(db):
        await db.execute(
            """
            INSERT INTO INTERACTION
            (interaction_id, person_id, channel, raw_text, summary, action_items, topics, sentiment, created_at, interaction_at)
            VALUES (?,?,?,?,?,'[]','[]','neutral',?,?)
            """,
            (
                interaction_id,
                person_id,
                "manual_resolution",
                f"ACTION_OVERRIDE::{json.dumps(payload, ensure_ascii=False)}",
                summary,
                now,
                now,
            ),
        )

    await run_write(_insert_action_override, label=f"update action status {person_id}")
    return {"status": "success", "interaction_id": interaction_id, "payload": payload}


@router.put("/situation-events/{event_id}")
async def update_situation_event(event_id: str, req: ManualSituationEventUpdateRequest):
    analysis = {
        "headline": req.headline,
        "current_read": req.current_read,
        "why_it_matters": req.why_it_matters,
        "stage": req.stage,
        "status": req.status,
        "momentum": req.momentum,
        "recommended_action": req.recommended_action,
        "resolution_note": req.resolution_note,
        "resolution_type": req.resolution_type,
        "confidence_score": req.confidence_score,
        "key_points": req.key_points or [],
    }
    try:
        result = await update_manual_relationship_event(
            event_id=event_id,
            update_text=req.update_text,
            analysis=analysis,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "success", **result}


@router.delete("/situation-events/{event_id}")
async def delete_situation_event(event_id: str):
    try:
        result = await delete_manual_relationship_event(event_id=event_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "success", **result}


@router.post("/interpretations/{interpretation_id}/promote-memory")
async def promote_memory(interpretation_id: str, req: PromoteMemoryRequest):
    if req.memory_domain not in {"rapport", "opportunity", "influence", "risk", "market"}:
        raise HTTPException(400, "Invalid memory domain")
    try:
        record = await promote_interpretation_to_enduring_memory(
            interpretation_id,
            memory_domain=req.memory_domain,
            status=req.status,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "success", "record": record}


@router.post("/interpretations/{interpretation_id}/promote-market-intel")
async def promote_market_intel(interpretation_id: str, req: PromoteMarketIntelRequest):
    try:
        record = await promote_interpretation_to_market_intel(interpretation_id, status=req.status)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "success", "record": record}


@router.post("/memory/{memory_id}/status")
async def set_memory_status(memory_id: str, req: ReviewStatusRequest):
    if req.status not in {"draft", "approved", "rejected", "archived"}:
        raise HTTPException(400, "Invalid status")
    try:
        record = await update_enduring_memory_status(memory_id, req.status)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "success", "record": record}


@router.post("/market-intel/{market_intel_id}/status")
async def set_market_intel_status(market_intel_id: str, req: ReviewStatusRequest):
    if req.status not in {"draft", "approved", "rejected", "archived"}:
        raise HTTPException(400, "Invalid status")
    try:
        record = await update_market_intel_status(market_intel_id, req.status)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"status": "success", "record": record}


@router.post("/pilot-cohort")
async def set_pilot_cohort(req: PilotCohortRequest):
    requested_ids: list[str] = []
    for person_id in req.person_ids or []:
        normalized = str(person_id or "").strip()
        if normalized and normalized not in requested_ids:
            requested_ids.append(normalized)

    now = _now()

    async def _update(db):
        await db.execute(
            """
            UPDATE PERSON
            SET is_pilot_cohort = 0,
                pilot_cohort_assigned_at = NULL,
                last_updated_at = ?
            WHERE COALESCE(is_pilot_cohort, 0) = 1
            """,
            (now,),
        )
        if not requested_ids:
            return 0

        placeholders = ",".join("?" for _ in requested_ids)
        await db.execute(
            f"""
            UPDATE PERSON
            SET is_pilot_cohort = 1,
                pilot_cohort_assigned_at = ?,
                last_updated_at = ?
            WHERE person_id IN ({placeholders})
              AND is_active = 1
            """,
            tuple([now, now] + requested_ids),
        )
        async with db.execute(
            f"""
            SELECT COUNT(*) AS assigned_count
            FROM PERSON
            WHERE person_id IN ({placeholders})
              AND is_active = 1
              AND COALESCE(is_pilot_cohort, 0) = 1
            """,
            tuple(requested_ids),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row["assigned_count"] or 0) if row else 0

    assigned_count = await run_write(_update, label="set explicit pilot cohort")
    return {
        "status": "success",
        "assigned_count": assigned_count,
        "mode": "explicit" if assigned_count else "recommended",
    }


@router.post("/bulk-update")
async def bulk_update_people(req: BulkUpdateRequest):
    if not req.person_ids:
        raise HTTPException(400, "person_ids are required")

    fields = []
    values = []
    for field in ("network_tier", "maintenance_mode", "relationship_owner", "account_priority"):
        value = getattr(req, field)
        if value is not None:
            fields.append(f"{field}=?")
            values.append(value)
    if not fields and not req.create_task_text:
        raise HTTPException(400, "No bulk changes requested")

    placeholders = ",".join("?" for _ in req.person_ids)
    now = _now()

    async def _update(db):
        if fields:
            await db.execute(
                f"UPDATE PERSON SET {', '.join(fields)}, last_updated_at=? WHERE person_id IN ({placeholders})",
                tuple(values + [now] + req.person_ids),
            )
        if req.create_task_text:
            for person_id in req.person_ids:
                await db.execute(
                    """
                    INSERT INTO TASK (task_id, person_id, task_text, due_date, priority, status, created_at)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4())[:12],
                        person_id,
                        req.create_task_text,
                        req.create_task_due_date,
                        "medium",
                        "open",
                        now,
                    ),
                )

    await run_write(_update, label="bulk update network lab people")
    return {"status": "success", "updated_count": len(req.person_ids)}


@router.get("/company-opportunities")
async def list_company_opportunities(company_name_raw: Optional[str] = None):
    async with get_db() as db:
        if company_name_raw:
            async with db.execute(
                """
                SELECT company_opportunity_id, company_name_raw, opportunity_type, stage, value_band, trigger_date,
                       strategic_importance, status, owner, notes, created_at, updated_at
                FROM COMPANY_OPPORTUNITY
                WHERE LOWER(TRIM(company_name_raw)) = LOWER(TRIM(?))
                ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, trigger_date ASC, updated_at DESC
                """,
                (company_name_raw,),
            ) as cursor:
                items = [dict(row) for row in await cursor.fetchall()]
        else:
            async with db.execute(
                """
                SELECT company_opportunity_id, company_name_raw, opportunity_type, stage, value_band, trigger_date,
                       strategic_importance, status, owner, notes, created_at, updated_at
                FROM COMPANY_OPPORTUNITY
                ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, trigger_date ASC, updated_at DESC
                """
            ) as cursor:
                items = [dict(row) for row in await cursor.fetchall()]
    return {"company_opportunities": items}


@router.post("/company-opportunities")
async def create_company_opportunity(req: CompanyOpportunityCreate):
    now = _now()
    company_opportunity_id = str(uuid.uuid4())

    async def _create(db):
        await db.execute(
            """
            INSERT INTO COMPANY_OPPORTUNITY (
                company_opportunity_id, company_name_raw, opportunity_type, stage, value_band, trigger_date,
                strategic_importance, status, owner, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                company_opportunity_id,
                req.company_name_raw,
                req.opportunity_type,
                req.stage,
                req.value_band,
                req.trigger_date,
                req.strategic_importance,
                req.status,
                req.owner,
                req.notes,
                now,
                now,
            ),
        )

    await run_write(_create, label=f"create company opportunity {req.company_name_raw}")
    return {"status": "created", "company_opportunity_id": company_opportunity_id}


@router.patch("/company-opportunities/{company_opportunity_id}")
@router.put("/company-opportunities/{company_opportunity_id}")
async def update_company_opportunity(company_opportunity_id: str, req: CompanyOpportunityUpdate):
    data = req.model_dump(exclude_none=True)
    if not data:
        return {"status": "no_change"}
    fields = [f"{field}=?" for field in data.keys()]
    values = list(data.values()) + [_now(), company_opportunity_id]

    async def _update(db):
        await db.execute(
            f"UPDATE COMPANY_OPPORTUNITY SET {', '.join(fields)}, updated_at=? WHERE company_opportunity_id=?",
            tuple(values),
        )

    await run_write(_update, label=f"update company opportunity {company_opportunity_id}")
    return {"status": "success"}


@router.delete("/company-opportunities/{company_opportunity_id}")
async def delete_company_opportunity(company_opportunity_id: str):
    async def _delete(db):
        await db.execute(
            "DELETE FROM COMPANY_OPPORTUNITY WHERE company_opportunity_id=?",
            (company_opportunity_id,),
        )

    await run_write(_delete, label=f"delete company opportunity {company_opportunity_id}")
    return {"status": "success"}
