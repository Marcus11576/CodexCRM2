"""
Antigravity CRM - AI pipeline service
Artifact-first persistence, signal traceability, brief storage, and ops views.
"""
import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.database import run_read, run_write
from backend.services.ai_foundation import (
    business_subtopic_label,
    canonical_event_status,
    canonical_business_subtopic,
    canonical_primary_category,
    canonical_sentiment,
    confidence_summary,
    infer_communication_channel,
    infer_business_subtopic,
    has_meaningful_signal_context,
    importance_score,
    input_type_for_channel,
    is_placeholder_signal_text,
    looks_like_raw_conversational_signal,
    most_recent_changes,
    normalize_signal_text,
    now_utc,
    review_state_for_signal,
    score_category_hypotheses,
    secondary_relevance_json,
    signal_set_hash,
    strip_speculative_filler,
    source_strength,
    suggest_profile_matches,
)


def _json(value) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


FEEDBACK_IMPORTANCE_ADJUSTMENTS = {
    "approve": 0.04,
    "reject": -0.2,
    "promote": 0.12,
    "demote": -0.12,
    "include_in_brief": 0.08,
    "exclude_from_brief": -0.12,
}


def _feedback_boost(feedback_counts: dict[str, int]) -> float:
    total = 0.0
    for event_type, count in (feedback_counts or {}).items():
        total += FEEDBACK_IMPORTANCE_ADJUSTMENTS.get(event_type, 0.0) * int(count or 0)
    return round(total, 3)


def _category_signal_key(category: Optional[str], text: Optional[str]) -> str:
    return f"{str(category or '').strip().lower()}::{normalize_signal_text(text).lower()}"


def _normalized_review_state(status: Optional[str], review_state: Optional[str]) -> str:
    if (review_state or "").strip():
        return review_state
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "approved":
        return "approved"
    if normalized_status == "rejected":
        return "rejected"
    return "pending_review"


def _feedback_counts_by_signal(rows: list[dict]) -> dict[str, dict[str, int]]:
    feedback_by_signal: dict[str, dict[str, int]] = {}
    for row in rows:
        target_id = row.get("target_id")
        event_type = row.get("event_type")
        if not target_id or not event_type:
            continue
        bucket = feedback_by_signal.setdefault(target_id, {})
        bucket[event_type] = bucket.get(event_type, 0) + int(row.get("event_count") or 0)
    return feedback_by_signal


def _clean_supporting_context(value: Optional[str]) -> str:
    text = normalize_signal_text(value)
    if not text:
        return ""
    text = text.replace("Received Email:", "").replace("Sent Email:", "").strip(" -:")
    if text.lower().startswith("traceback "):
        return ""
    return text


def _truncate_context_text(value: Optional[str], max_chars: int = 760) -> str:
    text = normalize_signal_text(value)
    if len(text) <= max_chars:
        return text
    sentence_break = text.rfind(". ", 0, max_chars)
    if sentence_break >= int(max_chars * 0.55):
        return text[: sentence_break + 1].strip()
    word_break = text.rfind(" ", 0, max_chars)
    if word_break >= int(max_chars * 0.55):
        return text[:word_break].strip()
    return text[:max_chars].rstrip()


def _looks_generic_supporting_context(value: Optional[str]) -> bool:
    text = normalize_signal_text(value).lower()
    if not text:
        return True
    return text.startswith((
        "a whatsapp conversation discussing",
        "this image is a screenshot",
        "the image is a",
        "the image shows",
        "image processed",
    ))


def _context_fingerprint(value: Optional[str]) -> str:
    text = normalize_signal_text(value).lower()
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]+", "", text)


def _context_equivalent(left: Optional[str], right: Optional[str]) -> bool:
    left_key = _context_fingerprint(left)
    right_key = _context_fingerprint(right)
    return bool(left_key and right_key and left_key == right_key)


def _keyword_candidates(signal_text: str) -> list[str]:
    stopwords = {
        "the", "and", "for", "that", "with", "from", "this", "into", "about", "will", "have",
        "been", "were", "they", "them", "their", "your", "just", "also", "more", "than", "each",
        "very", "what", "when", "where", "which", "while", "would", "there", "because", "project",
    }
    keywords = []
    for token in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", signal_text or ""):
        lowered = token.lower()
        if lowered in stopwords:
            continue
        keywords.append(lowered)
        if lowered.endswith("s") and len(lowered) > 4:
            keywords.append(lowered[:-1])
        if lowered.endswith("ment") and len(lowered) > 6:
            keywords.append(lowered[:-4])
    seen = []
    for keyword in keywords:
        if keyword not in seen:
            seen.append(keyword)
    return seen[:12]


def _text_token_set(value: Optional[str]) -> set[str]:
    tokens = set()
    for token in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", normalize_signal_text(value).lower()):
        if token in {
            "the", "and", "for", "that", "with", "from", "this", "have", "will", "would", "there", "their",
            "project", "projects", "discussion", "conversation", "focused", "focus", "issue", "issues",
        }:
            continue
        tokens.add(token)
    return tokens


def _text_overlap_ratio(left: Optional[str], right: Optional[str]) -> float:
    left_tokens = _text_token_set(left)
    right_tokens = _text_token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    return len(overlap) / max(min(len(left_tokens), len(right_tokens)), 1)


def _looks_generic_signal_summary(value: Optional[str]) -> bool:
    text = normalize_signal_text(value).lower()
    if not text:
        return True
    return text.startswith((
        "discussion on ",
        "the discussion ",
        "the conversation ",
        "conversation about ",
        "discussion focused on ",
        "the email subject ",
        "the image ",
    ))


def _legacy_signal_shadowed_by_ai_signal(legacy_signal: dict, ai_signal: dict) -> bool:
    if ai_signal.get("source_kind") != "ai_signal":
        return False
    if ai_signal.get("review_state") == "rejected":
        return False
    if legacy_signal.get("primary_category") != ai_signal.get("primary_category"):
        return False
    if not _looks_generic_signal_summary(legacy_signal.get("signal_text")):
        return False
    if legacy_signal.get("source_interaction_id") and legacy_signal.get("source_interaction_id") == ai_signal.get("source_interaction_id"):
        return True
    if _text_overlap_ratio(legacy_signal.get("supporting_context"), ai_signal.get("supporting_context")) >= 0.25:
        return True
    if _text_overlap_ratio(legacy_signal.get("supporting_context"), ai_signal.get("signal_text")) >= 0.25:
        return True
    return _text_overlap_ratio(legacy_signal.get("signal_text"), ai_signal.get("signal_text")) >= 0.55


def _signals_semantically_duplicate(left: dict, right: dict) -> bool:
    if not left or not right:
        return False
    if left.get("primary_category") != right.get("primary_category"):
        return False
    left_interaction = left.get("source_interaction_id")
    right_interaction = right.get("source_interaction_id")
    if left_interaction and right_interaction and left_interaction == right_interaction:
        return True
    if (
        left.get("business_subtopic")
        and right.get("business_subtopic")
        and left.get("business_subtopic") != right.get("business_subtopic")
    ):
        return False

    left_context = left.get("supporting_context") or left.get("source_snippet")
    right_context = right.get("supporting_context") or right.get("source_snippet")
    if _text_overlap_ratio(left_context, right_context) >= 0.55:
        return True
    if _text_overlap_ratio(left_context, right.get("signal_text")) >= 0.65:
        return True
    if _text_overlap_ratio(left.get("signal_text"), right.get("signal_text")) >= 0.72:
        return True
    return False


def _signal_rank(item: dict) -> tuple:
    return (
        0 if _is_surface_ready_signal(item) else 1,
        0 if item.get("source_kind") == "ai_signal" else 1,
        -(float(item.get("importance_score") or 0)),
        -(float(item.get("confidence_score") or 0)),
        -(len(normalize_signal_text(item.get("supporting_context") or item.get("source_snippet")))),
        item.get("updated_at") or item.get("created_at") or "",
    )


def _preferred_signal(left: dict, right: dict) -> dict:
    return left if _signal_rank(left) <= _signal_rank(right) else right


def _score_segment(segment: str, keywords: list[str]) -> int:
    lowered = segment.lower()
    score = sum(1 for keyword in keywords if keyword and keyword in lowered)
    word_count = len(re.findall(r"[A-Za-z][A-Za-z'-]*", segment))
    if word_count >= 35:
        score += 1
    if word_count >= 65:
        score += 1
    if "?" in segment and word_count <= 28:
        score -= 2
    return score


def _clean_transcript_segment(segment: str) -> str:
    cleaned = normalize_signal_text(segment)
    return re.sub(r"^[A-Z][A-Za-z .'-]{1,60}:\s*", "", cleaned).strip()


def _relevant_transcript_excerpt(source_text: str, signal_text: str, *, max_segments: int = 1) -> str:
    source = normalize_signal_text(source_text)
    if not source:
        return ""
    keywords = _keyword_candidates(signal_text)
    if not keywords:
        return ""
    raw_segments = [segment.strip() for segment in re.split(r"(?:\n+|\[(?:\d{1,2}:\d{2},[^\]]+)\])", source_text) if segment.strip()]
    segments = [normalize_signal_text(segment) for segment in raw_segments if normalize_signal_text(segment)]
    scored = [(idx, _score_segment(segment, keywords), segment) for idx, segment in enumerate(segments)]
    scored = [item for item in scored if item[1] > 0]
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[1], item[0]))
    chosen_indexes = set()
    score_lookup = {idx: score for idx, score, _segment in scored}
    for idx, _score, _segment in scored[:max_segments]:
        chosen_indexes.add(idx)
        if idx + 1 < len(segments) and score_lookup.get(idx + 1, 0) > 0:
            chosen_indexes.add(idx + 1)
    chosen_indexes = sorted(chosen_indexes)
    excerpt_segments = []
    for idx in chosen_indexes:
        segment = _clean_transcript_segment(segments[idx])
        if segment not in excerpt_segments:
            excerpt_segments.append(segment)
    return _truncate_context_text(" ".join(excerpt_segments))


def _contextual_excerpt(source_text: str, signal_text: str, *, window: int = 180) -> str:
    source = normalize_signal_text(source_text)
    signal = normalize_signal_text(signal_text)
    if not source or not signal:
        return ""
    lowered_source = source.lower()
    lowered_signal = signal.lower()
    idx = lowered_source.find(lowered_signal[: min(len(lowered_signal), 40)])
    if idx < 0:
        return ""
    start = max(0, idx - window)
    end = min(len(source), idx + len(signal) + window)
    excerpt = source[start:end].strip()
    if start > 0:
        excerpt = f"...{excerpt}"
    if end < len(source):
        excerpt = f"{excerpt}..."
    return excerpt


def _derive_supporting_context(
    *,
    signal_text: Optional[str],
    snippet: Optional[str],
    summary: Optional[str],
    raw_text: Optional[str],
    extracted_text: Optional[str],
) -> str:
    text = normalize_signal_text(signal_text)
    snippet_text = normalize_signal_text(snippet)
    if snippet_text and not _context_equivalent(snippet_text, text) and len(snippet_text) > 20:
        return snippet_text

    for candidate in (raw_text, extracted_text):
        transcript_excerpt = _relevant_transcript_excerpt(candidate or "", text)
        if transcript_excerpt and not _context_equivalent(transcript_excerpt, text):
            return _truncate_context_text(transcript_excerpt)
        excerpt = _contextual_excerpt(candidate or "", text)
        if excerpt and not _context_equivalent(excerpt, text):
            return _truncate_context_text(excerpt, max_chars=420)

    summary_text = _clean_supporting_context(summary)
    if summary_text and not _context_equivalent(summary_text, text):
        return _truncate_context_text(summary_text, max_chars=320)

    return ""


def _find_richer_supporting_context(
    *,
    signal_text: Optional[str],
    current_context: Optional[str],
    display_channel: Optional[str],
    candidates: list[dict],
) -> str:
    text = normalize_signal_text(signal_text)
    if not text:
        return ""
    current_normalized = normalize_signal_text(current_context)
    if current_context and not _looks_generic_supporting_context(current_context) and not _context_equivalent(current_normalized, text):
        return current_context
    wanted_channel = str(display_channel or "").strip().lower()
    best_context = current_context or ""
    best_length = len(best_context)
    current_is_generic = _looks_generic_supporting_context(current_context) or _context_equivalent(current_normalized, text)
    for candidate in candidates or []:
        candidate_channel = str(candidate.get("display_channel") or "").strip().lower()
        if wanted_channel and candidate_channel and candidate_channel != wanted_channel:
            continue
        combined = "\n".join(
            value for value in (
                candidate.get("raw_text"),
                candidate.get("extracted_text"),
            )
            if normalize_signal_text(value)
        )
        excerpt = _relevant_transcript_excerpt(combined, text)
        if not excerpt:
            excerpt = _clean_supporting_context(candidate.get("summary"))
        if excerpt and (current_is_generic or len(excerpt) > best_length):
            best_context = excerpt
            best_length = len(excerpt)
            current_is_generic = False
    return best_context


def _normalize_ai_signal_row(row: dict, feedback_counts: Optional[dict[str, int]] = None) -> Optional[dict]:
    text = strip_speculative_filler(row.get("signal_text") or row.get("content"))
    if not text or is_placeholder_signal_text(text):
        return None
    try:
        category = canonical_primary_category(row.get("primary_category") or row.get("category"))
    except Exception:
        return None
    snippet = strip_speculative_filler(row.get("source_snippet") or text)
    if not snippet or is_placeholder_signal_text(snippet):
        snippet = text
    if not has_meaningful_signal_context(text, snippet, category=category):
        return None
    feedback_counts = feedback_counts or {}
    base_importance = float(row.get("importance_score") or 0)
    adjusted_importance = round(max(min(base_importance + _feedback_boost(feedback_counts), 1.0), 0.05), 3)
    review_state = _normalized_review_state(row.get("status"), row.get("review_state"))
    included_in_brief = int(row.get("included_in_brief") if row.get("included_in_brief") is not None else 1)
    display_channel = infer_communication_channel(
        channel=row.get("channel") or row.get("input_type"),
        summary=row.get("summary"),
        raw_text=row.get("raw_text"),
        extracted_text=row.get("extracted_text"),
        metadata=row.get("artifact_metadata"),
    )
    supporting_context = _derive_supporting_context(
        signal_text=text,
        snippet=snippet,
        summary=row.get("summary"),
        raw_text=row.get("raw_text"),
        extracted_text=row.get("extracted_text"),
    )
    business_subtopic = None
    if category == "business_focus":
        business_subtopic = canonical_business_subtopic(row.get("business_subtopic")) or infer_business_subtopic(text, supporting_context or snippet)
    return {
        "id": row["signal_id"],
        "signal_ref": row["signal_id"],
        "signal_id": row["signal_id"],
        "intel_id": row["signal_id"],
        "source_kind": "ai_signal",
        "source_id": row["signal_id"],
        "artifact_id": row.get("artifact_id"),
        "source_interaction_id": row.get("source_interaction_id"),
        "primary_category": category,
        "category": category,
        "text": text,
        "signal_text": text,
        "snippet": snippet,
        "source_snippet": snippet,
        "supporting_context": supporting_context,
        "business_subtopic": business_subtopic,
        "business_subtopic_label": business_subtopic_label(business_subtopic),
        "confidence": int(row.get("confidence") or max(1, min(int(round((row.get("confidence_score") or 0.5) * 5)), 5))),
        "confidence_score": round(float(row.get("confidence_score") or 0.5), 3),
        "signal_sentiment": canonical_sentiment(row.get("signal_sentiment")),
        "signal_sentiment_confidence": float(row.get("signal_sentiment_confidence") or 0.5),
        "importance_score": adjusted_importance,
        "base_importance_score": round(base_importance, 3),
        "source_strength": float(row.get("source_strength") or 0.5),
        "section_hypothesis_fit_score": float(row.get("section_hypothesis_fit_score") or 0),
        "overall_hypothesis_fit_score": float(row.get("overall_hypothesis_fit_score") or 0),
        "review_state": review_state,
        "status": row.get("status") or ("approved" if review_state == "approved" else "draft"),
        "included_in_brief": included_in_brief,
        "influences_brief": bool(included_in_brief and review_state != "rejected"),
        "channel": row.get("channel") or row.get("input_type") or "note",
        "display_channel": display_channel,
        "input_type": row.get("input_type"),
        "profile_match_state": row.get("profile_match_state"),
        "requires_confirmation": bool(row.get("requires_confirmation")),
        "artifact_status": row.get("artifact_status"),
        "date": row.get("updated_at") or row.get("created_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "feedback_counts": feedback_counts,
    }


def _is_surface_ready_signal(item: dict) -> bool:
    status = str(item.get("status") or "").strip().lower()
    if status in {"archived", "rejected"}:
        return False
    review_state = str(item.get("review_state") or "").strip().lower()
    if review_state == "approved":
        return True
    if str(item.get("source_kind") or "").strip().lower() != "ai_signal":
        return False
    if review_state != "pending_review":
        return False
    if bool(item.get("requires_confirmation")):
        return False
    if str(item.get("artifact_status") or "").strip().lower() in {"failed", "duplicate"}:
        return False
    return (
        float(item.get("confidence_score") or 0) >= 0.45
        and float(item.get("source_strength") or 0) >= 0.35
    )


def _is_databank_visible_signal(item: dict) -> bool:
    if int(item.get("included_in_brief", 1)) != 1:
        return False

    status = str(item.get("status") or "").strip().lower()
    if status in {"archived", "rejected"}:
        return False

    review_state = str(item.get("review_state") or "").strip().lower()
    if review_state == "rejected":
        return False

    if _is_surface_ready_signal(item):
        return True

    source_kind = str(item.get("source_kind") or "").strip().lower()
    if source_kind != "legacy_intelligence":
        return False

    signal_text = normalize_signal_text(item.get("signal_text"))
    supporting_context = normalize_signal_text(item.get("supporting_context") or item.get("source_snippet"))
    if not signal_text or is_placeholder_signal_text(signal_text):
        return False
    if looks_like_raw_conversational_signal(signal_text):
        return False
    if not supporting_context:
        supporting_context = signal_text
    if not has_meaningful_signal_context(signal_text, supporting_context, category=item.get("primary_category")):
        return False
    return float(item.get("confidence_score") or 0) >= 0.2


def _normalize_legacy_signal_row(person_id: str, row: dict, feedback_counts: Optional[dict[str, int]] = None) -> Optional[dict]:
    legacy_text = strip_speculative_filler(row.get("intel_text"))
    if not legacy_text or is_placeholder_signal_text(legacy_text):
        return None
    try:
        category = canonical_primary_category(row.get("topic") or "")
    except Exception:
        return None
    legacy_confidence = round(max(min((row.get("confidence") or 3) / 5.0, 1.0), 0.05), 3)
    snippet = strip_speculative_filler(row.get("source_snippet") or legacy_text)
    if not snippet or is_placeholder_signal_text(snippet):
        snippet = legacy_text
    if not has_meaningful_signal_context(legacy_text, snippet, category=category):
        return None
    section_fit, overall_fit, secondary = score_category_hypotheses(legacy_text, category)
    feedback_counts = feedback_counts or {}
    base_importance = importance_score(
        legacy_text,
        source_strength_value=source_strength(
            input_type_for_channel(row.get("channel"))[0],
            profile_match_state="confirmed",
            confidence=1.0,
        ),
        sentiment="Unclear",
        confidence_score=legacy_confidence,
    )
    adjusted_importance = round(max(min(base_importance + _feedback_boost(feedback_counts), 1.0), 0.05), 3)
    status = row.get("status") or "draft"
    review_state = _normalized_review_state(status, None)
    signal_ref = f"legacy:{row['intel_id']}"
    supporting_context = _derive_supporting_context(
        signal_text=legacy_text,
        snippet=snippet,
        summary=row.get("summary"),
        raw_text=row.get("raw_text"),
        extracted_text=row.get("extracted_text"),
    )
    business_subtopic = None
    if category == "business_focus":
        business_subtopic = canonical_business_subtopic(row.get("business_subtopic")) or infer_business_subtopic(legacy_text, supporting_context or snippet)
    return {
        "id": signal_ref,
        "signal_ref": signal_ref,
        "signal_id": None,
        "intel_id": signal_ref,
        "legacy_intel_id": row["intel_id"],
        "source_kind": "legacy_intelligence",
        "source_id": row["intel_id"],
        "artifact_id": None,
        "source_interaction_id": row.get("source_interaction_id"),
        "primary_category": category,
        "category": category,
        "text": legacy_text,
        "signal_text": legacy_text,
        "snippet": snippet,
        "source_snippet": snippet,
        "supporting_context": supporting_context,
        "business_subtopic": business_subtopic,
        "business_subtopic_label": business_subtopic_label(business_subtopic),
        "confidence": max(1, min(int(row.get("confidence") or 3), 5)),
        "confidence_score": legacy_confidence,
        "signal_sentiment": "Unclear",
        "signal_sentiment_confidence": 0.5,
        "importance_score": adjusted_importance,
        "base_importance_score": round(base_importance, 3),
        "source_strength": source_strength(
            input_type_for_channel(row.get("channel"))[0],
            profile_match_state="confirmed",
            confidence=1.0,
        ),
        "section_hypothesis_fit_score": section_fit,
        "overall_hypothesis_fit_score": overall_fit,
        "secondary_relevance_json": secondary_relevance_json(secondary),
        "review_state": review_state,
        "status": status,
        "included_in_brief": 0 if status in {"rejected", "archived"} else 1,
        "influences_brief": status not in {"rejected", "archived"},
        "channel": row.get("channel") or "manual override",
        "display_channel": infer_communication_channel(
            channel=row.get("channel") or "note",
            summary=row.get("summary"),
            raw_text=row.get("raw_text"),
            extracted_text=row.get("extracted_text"),
            metadata=row.get("artifact_metadata"),
        ),
        "input_type": input_type_for_channel(row.get("channel"))[0],
        "profile_match_state": "confirmed",
        "requires_confirmation": False,
        "artifact_status": "legacy",
        "date": row.get("created_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("created_at"),
        "feedback_counts": feedback_counts,
        "profile_id": person_id,
    }


def _merged_signal_sort_key(item: dict):
    return (
        0 if item.get("review_state") == "approved" else 1,
        0 if item.get("source_kind") == "ai_signal" else 1,
        -(float(item.get("importance_score") or 0)),
        item.get("updated_at") or item.get("created_at") or "",
    )


async def get_artifact(artifact_id: str) -> Optional[dict]:
    async def _load(db):
        async with db.execute("SELECT * FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact_id,)) as cursor:
            return await cursor.fetchone()

    row = await run_read(_load, label=f"load artifact {artifact_id}")
    return dict(row) if row else None


async def get_artifact_by_interaction(interaction_id: str) -> Optional[dict]:
    async def _load(db):
        async with db.execute(
            "SELECT * FROM AI_ARTIFACT WHERE source_interaction_id = ? ORDER BY created_at DESC LIMIT 1",
            (interaction_id,),
        ) as cursor:
            return await cursor.fetchone()

    row = await run_read(_load, label=f"load artifact for interaction {interaction_id}")
    return dict(row) if row else None


async def create_or_update_artifact(
    *,
    person_id: Optional[str],
    channel: str,
    source_interaction_id: Optional[str] = None,
    artifact_id: Optional[str] = None,
    raw_content: Optional[str] = None,
    media_url: Optional[str] = None,
    source_name: Optional[str] = None,
    source_type: Optional[str] = None,
    extracted_metadata: Optional[dict] = None,
    duplicate_hash: Optional[str] = None,
    input_type: Optional[str] = None,
    input_type_confidence: Optional[float] = None,
    profile_match_state: Optional[str] = None,
    requires_confirmation: Optional[bool] = None,
    status: str = "queued",
) -> dict:
    now = now_utc()
    inferred_input_type, inferred_confidence = input_type_for_channel(
        channel,
        source_kind="text",
        filename=source_name,
    )
    input_type = input_type or inferred_input_type
    input_type_confidence = float(
        input_type_confidence if input_type_confidence is not None else inferred_confidence
    )
    profile_match_state = profile_match_state or ("confirmed" if person_id else "needs_review")
    requires_confirmation = bool(
        requires_confirmation if requires_confirmation is not None else not person_id
    )
    artifact_id = artifact_id or str(uuid.uuid4())
    source_type = source_type or channel
    duplicate_hash = duplicate_hash or f"manual::{artifact_id}"

    async def _write(db):
        duplicate_of = None
        if duplicate_hash:
            async with db.execute(
                """
                SELECT artifact_id, status, updated_at
                FROM AI_ARTIFACT
                WHERE duplicate_hash = ?
                  AND COALESCE(profile_id_nullable, person_id, '') = COALESCE(?, '')
                  AND artifact_id != ?
                ORDER BY datetime(created_at) DESC, artifact_id DESC
                LIMIT 25
                """,
                (duplicate_hash, person_id, artifact_id),
            ) as cursor:
                duplicate_rows = await cursor.fetchall()
            for duplicate_row in duplicate_rows or []:
                duplicate_candidate_id = duplicate_row["artifact_id"]
                duplicate_candidate_status = str(duplicate_row["status"] or "").strip().lower()
                allow_duplicate_short_circuit = duplicate_candidate_status in {"processed", "duplicate"}
                if not allow_duplicate_short_circuit and duplicate_candidate_status in {"queued", "running", "pending"}:
                    candidate_updated_at = _parse_iso_datetime(duplicate_row["updated_at"] if "updated_at" in duplicate_row.keys() else None)
                    now_dt = datetime.now(timezone.utc)
                    recent_candidate = bool(
                        candidate_updated_at
                        and (now_dt - candidate_updated_at.astimezone(timezone.utc)).total_seconds() <= 15 * 60
                    )
                    async with db.execute(
                        """
                        SELECT 1
                        FROM AI_JOB
                        WHERE related_artifact_id = ?
                          AND job_type IN ('signal_extraction', 'transcription')
                          AND status IN ('queued', 'running')
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (duplicate_candidate_id,),
                    ) as job_cursor:
                        active_job = await job_cursor.fetchone()
                    allow_duplicate_short_circuit = bool(active_job) or recent_candidate
                if allow_duplicate_short_circuit:
                    duplicate_of = duplicate_candidate_id
                    break

        existing = None
        if source_interaction_id:
            async with db.execute(
                "SELECT artifact_id FROM AI_ARTIFACT WHERE source_interaction_id = ? ORDER BY created_at DESC LIMIT 1",
                (source_interaction_id,),
            ) as cursor:
                existing = await cursor.fetchone()

        if existing:
            artifact_id_local = existing["artifact_id"]
            await db.execute(
                """
                UPDATE AI_ARTIFACT
                SET person_id = COALESCE(?, person_id),
                    profile_id_nullable = COALESCE(?, profile_id_nullable),
                    channel = ?,
                    raw_content = COALESCE(?, raw_content),
                    raw_content_or_path = COALESCE(?, raw_content_or_path),
                    media_url = COALESCE(?, media_url),
                    metadata = COALESCE(?, metadata),
                    extracted_metadata_json = COALESCE(?, extracted_metadata_json),
                    source_name = COALESCE(?, source_name),
                    source_type = COALESCE(?, source_type),
                    input_type = COALESCE(?, input_type),
                    input_type_confidence = COALESCE(?, input_type_confidence),
                    source_strength = COALESCE(source_strength, ?),
                    profile_match_state = COALESCE(?, profile_match_state),
                    requires_confirmation = ?,
                    duplicate_hash = COALESCE(?, duplicate_hash),
                    status = ?,
                    duplicate_of_artifact_id = ?,
                    updated_at = ?
                WHERE artifact_id = ?
                """,
                (
                    person_id,
                    person_id,
                    channel,
                    raw_content,
                    raw_content or media_url,
                    media_url,
                    _json(extracted_metadata),
                    _json(extracted_metadata),
                    source_name,
                    source_type,
                    input_type,
                    input_type_confidence,
                    source_strength(
                        input_type,
                        profile_match_state=profile_match_state,
                        confidence=input_type_confidence,
                    ),
                    profile_match_state,
                    int(requires_confirmation),
                    duplicate_hash,
                    "duplicate" if duplicate_of else status,
                    duplicate_of,
                    now,
                    artifact_id_local,
                ),
            )
            async with db.execute(
                "SELECT * FROM AI_ARTIFACT WHERE artifact_id = ?",
                (artifact_id_local,),
            ) as cursor:
                row = await cursor.fetchone()
            return dict(row)

        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, source_interaction_id, channel,
                raw_content, raw_content_or_path, media_url, metadata, extracted_metadata_json,
                source_name, source_type, input_type, input_type_confidence, source_strength,
                profile_match_state, requires_confirmation, duplicate_hash, status, created_at, updated_at,
                duplicate_of_artifact_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                source_interaction_id,
                channel,
                raw_content,
                raw_content or media_url,
                media_url,
                _json(extracted_metadata),
                _json(extracted_metadata),
                source_name,
                source_type,
                input_type,
                input_type_confidence,
                source_strength(
                    input_type,
                    profile_match_state=profile_match_state,
                    confidence=input_type_confidence,
                ),
                profile_match_state,
                int(requires_confirmation),
                duplicate_hash,
                "duplicate" if duplicate_of else status,
                now,
                now,
                duplicate_of,
            ),
        )
        async with db.execute("SELECT * FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    return await run_write(_write, label=f"create or update artifact {artifact_id}")


async def update_artifact_state(
    artifact_id: str,
    *,
    input_type: Optional[str] = None,
    input_type_confidence: Optional[float] = None,
    extracted_text: Optional[str] = None,
    artifact_sentiment: Optional[str] = None,
    artifact_sentiment_confidence: Optional[float] = None,
    metadata_patch: Optional[dict] = None,
    status: Optional[str] = None,
    requires_confirmation: Optional[bool] = None,
    profile_match_state: Optional[str] = None,
) -> Optional[dict]:
    async def _write(db):
        async with db.execute("SELECT * FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        artifact = dict(row)
        merged_metadata = {}
        for raw_value in (artifact.get("metadata"), artifact.get("extracted_metadata_json")):
            if raw_value:
                try:
                    merged_metadata.update(json.loads(raw_value))
                except Exception:
                    pass
        merged_metadata.update(metadata_patch or {})
        final_input_type = input_type or artifact.get("input_type") or "unknown"
        final_match_state = profile_match_state or artifact.get("profile_match_state") or (
            "confirmed" if artifact.get("person_id") else "needs_review"
        )
        final_confidence = float(
            input_type_confidence if input_type_confidence is not None else artifact.get("input_type_confidence") or 0.5
        )
        await db.execute(
            """
            UPDATE AI_ARTIFACT
            SET input_type = ?,
                input_type_confidence = ?,
                extracted_text = COALESCE(?, extracted_text),
                extracted_metadata_json = ?,
                artifact_sentiment = COALESCE(?, artifact_sentiment),
                artifact_sentiment_confidence = COALESCE(?, artifact_sentiment_confidence),
                profile_match_state = ?,
                requires_confirmation = ?,
                source_strength = ?,
                status = COALESCE(?, status),
                updated_at = ?
            WHERE artifact_id = ?
            """,
            (
                final_input_type,
                final_confidence,
                extracted_text,
                _json(merged_metadata),
                artifact_sentiment,
                artifact_sentiment_confidence,
                final_match_state,
                int(bool(requires_confirmation if requires_confirmation is not None else artifact.get("requires_confirmation"))),
                source_strength(final_input_type, profile_match_state=final_match_state, confidence=final_confidence),
                status,
                now_utc(),
                artifact_id,
            ),
        )
        async with db.execute("SELECT * FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact_id,)) as cursor:
            updated = await cursor.fetchone()
        return dict(updated) if updated else None

    return await run_write(_write, label=f"update artifact state {artifact_id}")


async def mark_artifact_failed(artifact_id: str, error_text: str) -> None:
    await update_artifact_state(
        artifact_id,
        status="failed",
        metadata_patch={"error": error_text},
    )


async def invalidate_briefs_for_profile(person_id: str) -> None:
    async def _write(db):
        await invalidate_briefs_for_profile_tx(db, person_id)

    await run_write(_write, label=f"invalidate briefs {person_id}")


async def invalidate_briefs_for_profile_tx(db, person_id: str) -> None:
    now = now_utc()
    await db.execute(
        "UPDATE PERSON SET cached_briefing = NULL, briefing_last_updated = NULL, last_updated_at = ? WHERE person_id = ?",
        (now, person_id),
    )
    await db.execute(
        """
        UPDATE AI_BRIEF
        SET is_stale = 1, stale_after = ?, updated_at = ?
        WHERE COALESCE(profile_id, person_id) = ? AND COALESCE(is_stale, 0) = 0
        """,
        (now, now, person_id),
    )


async def _upsert_platform_memories_tx(db, memories: list[dict]) -> None:
    now = now_utc()
    for item in memories:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("type") or "").strip()
        memory_text = str(item.get("text") or "").strip()
        entity_ref = str(item.get("entity") or item.get("entity_ref") or "").strip() or None
        if not memory_type or not memory_text:
            continue
        async with db.execute(
            """
            SELECT memory_id
            FROM PLATFORM_MEMORY
            WHERE memory_type = ? AND COALESCE(entity_ref, '') = COALESCE(?, '') AND memory_text = ?
            LIMIT 1
            """,
            (memory_type, entity_ref, memory_text),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing:
            await db.execute(
                "UPDATE PLATFORM_MEMORY SET strength = COALESCE(strength, 0) + 1, last_reinforced = ? WHERE memory_id = ?",
                (now, existing["memory_id"]),
            )
        else:
            await db.execute(
                """
                INSERT INTO PLATFORM_MEMORY (memory_id, memory_type, entity_ref, memory_text, strength, last_reinforced, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), memory_type, entity_ref, memory_text, 1, now, now),
            )


async def sync_ai_signals_for_artifact(
    *,
    artifact_id: str,
    person_id: str,
    interaction_id: Optional[str],
    result: dict,
    artifact: Optional[dict] = None,
) -> dict:
    artifact = artifact or await get_artifact(artifact_id)
    if not artifact:
        raise ValueError("Artifact not found")
    now = now_utc()
    input_type = artifact.get("input_type") or "unknown"
    artifact_status = artifact.get("status") or "processed"
    artifact_sentiment = canonical_sentiment(result.get("sentiment") or artifact.get("artifact_sentiment"))
    artifact_sentiment_confidence = float(
        result.get("sentiment_confidence") or artifact.get("artifact_sentiment_confidence") or 0.5
    )
    nuggets = result.get("topic_nuggets") or []

    async def _write(db):
        await db.execute("DELETE FROM AI_SIGNAL WHERE artifact_id = ?", (artifact_id,))
        async with db.execute(
            """
            SELECT signal_id, primary_category, signal_text, source_snippet, source_interaction_id,
                   confidence_score, importance_score, review_state, status, business_subtopic,
                   created_at, updated_at
            FROM AI_SIGNAL
            WHERE COALESCE(profile_id, person_id) = ?
              AND artifact_id != ?
            ORDER BY COALESCE(updated_at, created_at) DESC
            """,
            (person_id, artifact_id),
        ) as cursor:
            existing_rows = [dict(row) for row in await cursor.fetchall()]
        inserted = []
        for nugget in nuggets:
            if not isinstance(nugget, dict):
                continue
            text = normalize_signal_text(nugget.get("text") or nugget.get("signal_text"))
            text = strip_speculative_filler(text)
            if not text or is_placeholder_signal_text(text):
                continue
            raw_category = nugget.get("topic") or nugget.get("category")
            if not raw_category:
                continue
            category = canonical_primary_category(raw_category)
            snippet = strip_speculative_filler(nugget.get("snippet") or nugget.get("source_snippet") or text[:280])
            if not snippet or is_placeholder_signal_text(snippet):
                snippet = text[:280]
            if not has_meaningful_signal_context(text, snippet, category=category):
                continue
            raw_confidence = nugget.get("confidence", 0.6)
            business_subtopic = None
            if category == "business_focus":
                business_subtopic = canonical_business_subtopic(nugget.get("business_subtopic")) or infer_business_subtopic(text, snippet)
            confidence_score = float(raw_confidence / 5.0) if isinstance(raw_confidence, int) and raw_confidence > 1 else float(raw_confidence)
            confidence_score = round(max(min(confidence_score, 1.0), 0.05), 3)
            signal_sentiment = canonical_sentiment(nugget.get("sentiment") or artifact_sentiment)
            signal_sentiment_confidence = float(
                nugget.get("sentiment_confidence") or artifact_sentiment_confidence or 0.5
            )
            source_strength_value = source_strength(
                input_type,
                profile_match_state=artifact.get("profile_match_state") or "confirmed",
                confidence=float(artifact.get("input_type_confidence") or 0.5),
            )
            section_fit, overall_fit, secondary = score_category_hypotheses(text, category)
            importance = importance_score(
                text,
                source_strength_value=source_strength_value,
                sentiment=signal_sentiment,
                confidence_score=confidence_score,
            )
            review_state = review_state_for_signal(
                confidence_score=confidence_score,
                source_strength_value=source_strength_value,
                artifact_status=artifact_status,
                requires_confirmation=bool(artifact.get("requires_confirmation")),
            )
            status = "approved" if review_state == "approved" else "draft"
            candidate_signal = {
                "primary_category": category,
                "signal_text": text,
                "source_snippet": snippet,
                "supporting_context": snippet,
                "source_interaction_id": interaction_id,
                "importance_score": importance,
                "confidence_score": confidence_score,
                "review_state": review_state,
                "status": status,
                "business_subtopic": business_subtopic,
                "source_kind": "ai_signal",
                "created_at": now,
                "updated_at": now,
            }
            if any(_signals_semantically_duplicate(candidate_signal, existing) for existing in existing_rows):
                continue
            signal_id = str(uuid.uuid4())
            await db.execute(
                """
                INSERT INTO AI_SIGNAL (
                    signal_id, artifact_id, person_id, profile_id, category, primary_category,
                    content, signal_text, source_snippet, confidence, confidence_score, status,
                    review_state, signal_sentiment, signal_sentiment_confidence, importance_score,
                    source_strength, section_hypothesis_fit_score, overall_hypothesis_fit_score,
                    business_subtopic, secondary_relevance_json, included_in_brief, source_interaction_id,
                    event_relevance_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    artifact_id,
                    person_id,
                    person_id,
                    category,
                    category,
                    text,
                    text,
                    snippet,
                    max(1, min(int(round(confidence_score * 5)), 5)),
                    confidence_score,
                    status,
                    review_state,
                    signal_sentiment,
                    signal_sentiment_confidence,
                    importance,
                    source_strength_value,
                    section_fit,
                    overall_fit,
                    business_subtopic,
                    secondary_relevance_json(secondary),
                    1,
                    interaction_id,
                    _json(nugget.get("event_relevance") or []),
                    now,
                    now,
                ),
            )
            inserted.append(
                {
                    "signal_id": signal_id,
                    "primary_category": category,
                    "signal_text": text,
                    "source_snippet": snippet,
                    "confidence_score": confidence_score,
                    "importance_score": importance,
                    "source_strength": source_strength_value,
                    "section_hypothesis_fit_score": section_fit,
                    "overall_hypothesis_fit_score": overall_fit,
                    "business_subtopic": business_subtopic,
                    "business_subtopic_label": business_subtopic_label(business_subtopic),
                    "review_state": review_state,
                    "updated_at": now,
                    "created_at": now,
                    "included_in_brief": 1,
                }
            )
            existing_rows.append(candidate_signal)

        await _upsert_platform_memories_tx(db, result.get("global_insights") or [])
        await invalidate_briefs_for_profile_tx(db, person_id)
        return {"signals": inserted, "inserted_count": len(inserted)}

    return await run_write(_write, label=f"sync ai signals {artifact_id}")


async def suggest_matches_for_artifact_text(query_text: str) -> list[dict]:
    return await suggest_profile_matches(query_text)


async def load_profile_signals(person_id: str, *, include_rejected: bool = False, limit: Optional[int] = None) -> list[dict]:
    async def _load(db):
        async with db.execute(
            """
            SELECT signal_id, artifact_id, COALESCE(profile_id, person_id) AS profile_id, primary_category, category,
                   signal_text, content, source_snippet, confidence, confidence_score, source_strength, importance_score,
                   section_hypothesis_fit_score, overall_hypothesis_fit_score, review_state, status, business_subtopic,
                   included_in_brief, signal_sentiment, signal_sentiment_confidence, created_at, updated_at,
                   source_interaction_id
            FROM AI_SIGNAL
            WHERE COALESCE(profile_id, person_id) = ?
            ORDER BY COALESCE(updated_at, created_at) DESC
            """,
            (person_id,),
        ) as cursor:
            ai_signals = [dict(row) for row in await cursor.fetchall()]

        artifact_ids = [row["artifact_id"] for row in ai_signals if row.get("artifact_id")]
        artifact_lookup = {}
        if artifact_ids:
            placeholders = ",".join("?" for _ in artifact_ids)
            async with db.execute(
                f"""
                SELECT artifact_id, input_type, status AS artifact_status, channel, profile_match_state,
                       requires_confirmation, extracted_text, extracted_metadata_json
                FROM AI_ARTIFACT
                WHERE artifact_id IN ({placeholders})
                """,
                artifact_ids,
            ) as cursor:
                artifact_lookup = {row["artifact_id"]: dict(row) for row in await cursor.fetchall()}

        interaction_ids = [row["source_interaction_id"] for row in ai_signals if row.get("source_interaction_id")]
        interaction_lookup = {}
        if interaction_ids:
            placeholders = ",".join("?" for _ in interaction_ids)
            async with db.execute(
                f"SELECT interaction_id, channel, summary, raw_text FROM INTERACTION WHERE interaction_id IN ({placeholders})",
                interaction_ids,
            ) as cursor:
                interaction_lookup = {row["interaction_id"]: dict(row) for row in await cursor.fetchall()}

        async with db.execute(
            """
            SELECT t.intel_id, t.topic, t.intel_text, t.confidence, t.status, t.source_snippet, t.business_subtopic, t.created_at,
                   t.source_interaction_id, i.channel, i.summary, i.raw_text
            FROM TOPIC_INTELLIGENCE t
            LEFT JOIN INTERACTION i ON i.interaction_id = t.source_interaction_id
            WHERE t.person_id = ?
            ORDER BY t.created_at DESC
            """,
            (person_id,),
        ) as cursor:
            legacy_rows = [dict(row) for row in await cursor.fetchall()]
        feedback_target_ids = [row["signal_id"] for row in ai_signals if row.get("signal_id")]
        feedback_target_ids.extend([row["intel_id"] for row in legacy_rows if row.get("intel_id")])
        feedback_lookup = {}
        if feedback_target_ids:
            placeholders = ",".join("?" for _ in feedback_target_ids)
            async with db.execute(
                f"""
                SELECT target_id, event_type, COUNT(*) AS event_count
                FROM AI_FEEDBACK
                WHERE target_type = 'signal'
                  AND target_id IN ({placeholders})
                GROUP BY target_id, event_type
                """,
                feedback_target_ids,
            ) as cursor:
                feedback_lookup = _feedback_counts_by_signal([dict(row) for row in await cursor.fetchall()])
        async with db.execute(
            """
            SELECT i.interaction_id, i.channel, i.summary, i.raw_text,
                   a.extracted_text, a.extracted_metadata_json
            FROM INTERACTION i
            LEFT JOIN AI_ARTIFACT a ON a.source_interaction_id = i.interaction_id
            WHERE i.person_id = ?
            ORDER BY i.interaction_at DESC
            LIMIT 40
            """,
            (person_id,),
        ) as cursor:
            context_rows = [dict(row) for row in await cursor.fetchall()]
        return ai_signals, legacy_rows, artifact_lookup, interaction_lookup, feedback_lookup, context_rows

    ai_signals, legacy_rows, artifact_lookup, interaction_lookup, feedback_lookup, context_rows = await run_read(
        _load,
        label=f"load profile signals {person_id}",
    )
    context_candidates = []
    for row in context_rows:
        try:
            metadata = json.loads(row.get("extracted_metadata_json") or "{}")
        except Exception:
            metadata = {}
        context_candidates.append({
            "interaction_id": row.get("interaction_id"),
            "raw_text": row.get("raw_text"),
            "summary": row.get("summary"),
            "extracted_text": row.get("extracted_text"),
            "display_channel": infer_communication_channel(
                channel=row.get("channel"),
                summary=row.get("summary"),
                raw_text=row.get("raw_text"),
                extracted_text=row.get("extracted_text"),
                metadata=metadata,
            ),
        })
    merged_lookup = {}
    for signal in ai_signals:
        artifact = artifact_lookup.get(signal.get("artifact_id")) or {}
        interaction = interaction_lookup.get(signal.get("source_interaction_id")) or {}
        signal.update(artifact)
        for key in ("channel", "summary", "raw_text"):
            if interaction.get(key) and not signal.get(key):
                signal[key] = interaction[key]
        try:
            signal["artifact_metadata"] = json.loads(signal.get("extracted_metadata_json") or "{}")
        except Exception:
            signal["artifact_metadata"] = {}
        normalized = _normalize_ai_signal_row(signal, feedback_lookup.get(signal.get("signal_id")))
        if not normalized:
            continue
        normalized["supporting_context"] = _find_richer_supporting_context(
            signal_text=normalized.get("signal_text"),
            current_context=normalized.get("supporting_context"),
            display_channel=normalized.get("display_channel"),
            candidates=context_candidates,
        )
        if str(normalized.get("status") or "").strip().lower() == "archived":
            continue
        if not include_rejected and normalized.get("review_state") == "rejected":
            continue
        duplicate_key = next(
            (key for key, existing in merged_lookup.items() if _signals_semantically_duplicate(normalized, existing)),
            None,
        )
        if duplicate_key:
            merged_lookup[duplicate_key] = _preferred_signal(normalized, merged_lookup[duplicate_key])
            continue
        merged_lookup[_category_signal_key(normalized.get("primary_category"), normalized.get("signal_text"))] = normalized

    for row in legacy_rows:
        normalized = _normalize_legacy_signal_row(person_id, row, feedback_lookup.get(row.get("intel_id")))
        if not normalized:
            continue
        normalized["supporting_context"] = _find_richer_supporting_context(
            signal_text=normalized.get("signal_text"),
            current_context=normalized.get("supporting_context"),
            display_channel=normalized.get("display_channel"),
            candidates=context_candidates,
        )
        if str(normalized.get("status") or "").strip().lower() == "archived":
            continue
        if not include_rejected and normalized.get("review_state") == "rejected":
            continue
        if any(_legacy_signal_shadowed_by_ai_signal(normalized, existing) for existing in merged_lookup.values()):
            continue
        duplicate_key = next(
            (key for key, existing in merged_lookup.items() if _signals_semantically_duplicate(normalized, existing)),
            None,
        )
        if duplicate_key:
            merged_lookup[duplicate_key] = _preferred_signal(merged_lookup[duplicate_key], normalized)
            continue
        key = _category_signal_key(normalized.get("primary_category"), normalized.get("signal_text"))
        if key in merged_lookup:
            continue
        merged_lookup[key] = normalized

    merged = sorted(merged_lookup.values(), key=_merged_signal_sort_key)
    if limit is not None:
        return merged[:limit]
    return merged


async def grouped_profile_signals(person_id: str, *, limit_per_category: Optional[int] = None) -> dict[str, list[dict]]:
    signals = await load_profile_signals(person_id)
    signals = [signal for signal in signals if _is_databank_visible_signal(signal)]
    grouped = {
        "business_focus": [],
        "recruitment_talent": [],
        "family_personal": [],
        "obe_focus": [],
    }
    for signal in signals:
        category = signal.get("primary_category")
        if category not in grouped:
            continue
        if limit_per_category is not None and len(grouped[category]) >= limit_per_category:
            continue
        grouped[category].append(signal)
    return grouped


async def load_signals_for_brief(person_id: str, limit: int = 24) -> list[dict]:
    merged = await load_profile_signals(person_id)
    merged = [
        item
        for item in merged
        if _is_surface_ready_signal(item) and int(item.get("included_in_brief", 1)) == 1
    ]
    return merged[:limit]


async def store_brief(
    *,
    person_id: str,
    briefing: dict,
    signals: list[dict],
    events: list[dict],
) -> dict:
    now = now_utc()
    brief_id = briefing.get("brief_id") or str(uuid.uuid4())
    signal_hash = signal_set_hash(signals)
    confidence = confidence_summary(signals)
    recent_changes = most_recent_changes(signals)
    event_relevance = [
        {
            "event_id": event.get("event_id"),
            "event_name": event.get("event_name"),
            "event_date": event.get("event_date"),
            "status": event.get("status"),
            "topics": event.get("topics"),
        }
        for event in events
    ]
    payload = dict(briefing)
    payload["brief_id"] = brief_id
    payload["generated_from_signal_set_hash"] = signal_hash
    payload["confidence_summary"] = confidence
    payload["recent_changes"] = recent_changes
    payload["event_relevance"] = event_relevance
    source_signal_ids = [signal.get("signal_id") for signal in signals if signal.get("signal_id")]

    async def _write(db):
        await db.execute(
            "UPDATE AI_BRIEF SET is_stale = 1, stale_after = ?, updated_at = ? WHERE COALESCE(profile_id, person_id) = ? AND brief_id != ?",
            (now, now, person_id, brief_id),
        )
        await db.execute(
            """
            INSERT INTO AI_BRIEF (
                brief_id, person_id, profile_id, content_json, source_signal_ids, generated_from_signal_set_hash,
                business_focus_summary, recruitment_talent_summary, family_personal_summary, obe_focus_summary,
                overall_brief_summary, top_priorities_json, recent_changes_json, event_relevance_json,
                confidence_summary_json, created_at, updated_at, stale_after, is_stale
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                brief_id,
                person_id,
                person_id,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(source_signal_ids),
                signal_hash,
                payload.get("business_focus") or payload.get("business_focus_summary"),
                payload.get("recruitment_talent") or payload.get("recruitment_talent_summary"),
                payload.get("personal_rapport") or payload.get("family_personal_summary"),
                payload.get("obe_focus") or payload.get("obe_focus_summary"),
                payload.get("overall_brief_summary") or payload.get("audio_script") or "",
                json.dumps(payload.get("top_priorities") or []),
                json.dumps(recent_changes),
                json.dumps(event_relevance),
                json.dumps(confidence),
                now,
                now,
                None,
            ),
        )
        await db.execute(
            "UPDATE PERSON SET cached_briefing = ?, briefing_last_updated = ?, last_updated_at = ? WHERE person_id = ?",
            (json.dumps(payload, ensure_ascii=False), now, now, person_id),
        )
        async with db.execute("SELECT * FROM AI_BRIEF WHERE brief_id = ?", (brief_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    stored = await run_write(_write, label=f"store brief {person_id}")
    payload["brief_id"] = brief_id
    return {"brief_id": brief_id, "briefing": payload, "stored": stored}


async def get_review_queue(limit: int = 50) -> dict:
    async def _load(db):
        async with db.execute(
            """
            SELECT artifact_id, COALESCE(profile_id_nullable, person_id) AS profile_id, input_type, source_name,
                   status, profile_match_state, requires_confirmation, artifact_sentiment, updated_at
            FROM AI_ARTIFACT
            WHERE COALESCE(requires_confirmation, 0) = 1
               OR status IN ('failed', 'duplicate', 'needs_review')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            artifacts = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            """
            SELECT signal_id, COALESCE(profile_id, person_id) AS profile_id, primary_category, signal_text,
                   review_state, confidence_score, source_strength, updated_at
            FROM AI_SIGNAL
            WHERE COALESCE(review_state, 'pending_review') IN ('pending_review', 'failed', 'duplicate')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            signals = [dict(row) for row in await cursor.fetchall()]
        return artifacts, signals

    artifacts, signals = await run_read(_load, label="load review queue")
    return {
        "artifacts": artifacts,
        "signals": signals,
        "total_items": len(artifacts) + len(signals),
    }


async def get_operations_summary() -> dict:
    async def _load(db):
        async with db.execute("SELECT COUNT(*) AS count FROM AI_JOB WHERE status = 'failed'") as cursor:
            failed_jobs = (await cursor.fetchone())["count"]
        async with db.execute(
            """
            SELECT COUNT(*) AS count
            FROM AI_JOB
            WHERE status = 'running'
              AND started_at IS NOT NULL
              AND datetime(started_at) < datetime('now', '-30 minutes')
            """
        ) as cursor:
            stuck_jobs = (await cursor.fetchone())["count"]
        async with db.execute("SELECT COALESCE(SUM(COALESCE(retry_count, 0)), 0) AS count FROM AI_JOB") as cursor:
            retry_volume = (await cursor.fetchone())["count"]
        async with db.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'duplicate' THEN 1 ELSE 0 END) AS duplicates,
                COUNT(*) AS total
            FROM AI_ARTIFACT
            """
        ) as cursor:
            duplicate_row = await cursor.fetchone()
        async with db.execute(
            """
            SELECT
                SUM(CASE WHEN action_type = 'relink_profile' THEN 1 ELSE 0 END) AS relinks,
                SUM(CASE WHEN action_type IN ('edit', 'reject', 'reclassify_category', 'correct_sentiment') THEN 1 ELSE 0 END) AS corrections,
                COUNT(*) AS total
            FROM AI_FEEDBACK
            """
        ) as cursor:
            feedback_row = await cursor.fetchone()
        async with db.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM AI_ARTIFACT
            """
        ) as cursor:
            extraction_row = await cursor.fetchone()
        async with db.execute(
            """
            SELECT task_type, AVG(latency_ms) AS avg_latency_ms
            FROM AI_RUN_LOG
            WHERE latency_ms IS NOT NULL
            GROUP BY task_type
            ORDER BY task_type
            """
        ) as cursor:
            latency_rows = [dict(row) for row in await cursor.fetchall()]
        async with db.execute("SELECT COUNT(*) AS count FROM AI_SIGNAL WHERE review_state = 'pending_review'") as cursor:
            conflict_row = await cursor.fetchone()
        return failed_jobs, stuck_jobs, retry_volume, duplicate_row, feedback_row, extraction_row, latency_rows, conflict_row

    failed_jobs, stuck_jobs, retry_volume, duplicate_row, feedback_row, extraction_row, latency_rows, conflict_row = await run_read(_load, label="load ai ops summary")
    duplicate_rate = round((duplicate_row["duplicates"] or 0) / max(duplicate_row["total"] or 1, 1), 3)
    relink_rate = round((feedback_row["relinks"] or 0) / max(feedback_row["total"] or 1, 1), 3)
    correction_rate = round((feedback_row["corrections"] or 0) / max(feedback_row["total"] or 1, 1), 3)
    processed = extraction_row["processed"] or 0
    failed = extraction_row["failed"] or 0
    extraction_success_rate = round(processed / max(processed + failed, 1), 3)
    average_ai_latency_by_task = {
        row["task_type"]: round(float(row["avg_latency_ms"] or 0), 1)
        for row in latency_rows
    }
    return {
        "failed_jobs": failed_jobs,
        "stuck_jobs": stuck_jobs,
        "retry_volume": retry_volume,
        "duplicate_rate": duplicate_rate,
        "relink_rate": relink_rate,
        "correction_rate": correction_rate,
        "conflict_rate": round((conflict_row["count"] or 0) / max(processed or 1, 1), 3),
        "extraction_success_rate": extraction_success_rate,
        "average_ai_latency_by_task": average_ai_latency_by_task,
    }


async def export_event_participants_csv(event_id: str, *, status_filter: str = "all") -> str:
    filter_value = status_filter.strip()
    normalized_status = None
    if filter_value and filter_value.lower() != "all":
        normalized_status = canonical_event_status(filter_value)

    async def _load(db):
        async with db.execute("SELECT event_id FROM EVENT WHERE event_id = ?", (event_id,)) as cursor:
            if not await cursor.fetchone():
                raise ValueError("Event not found")
        sql = """
            SELECT p.full_name, p.company_name_raw, p.title_current, p.phone_primary, p.email_primary, pe.status
            FROM PERSON_EVENT pe
            JOIN PERSON p ON p.person_id = pe.person_id
            WHERE pe.event_id = ?
        """
        params = [event_id]
        if normalized_status:
            sql += " AND pe.status = ?"
            params.append(normalized_status)
        sql += " ORDER BY p.full_name COLLATE NOCASE ASC"
        async with db.execute(sql, params) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    rows = await run_read(_load, label=f"export event participants {event_id}")
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["Name", "Company", "Position", "Mobile", "Email", "Event Status"])
    for row in rows:
        writer.writerow(
            [
                row.get("full_name") or "",
                row.get("company_name_raw") or "",
                row.get("title_current") or "",
                row.get("phone_primary") or "",
                row.get("email_primary") or "",
                row.get("status") or "",
            ]
        )
    return output.getvalue()
