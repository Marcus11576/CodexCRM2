"""
Preference learning helpers for AI signal ranking and meeting brief prioritisation.
Learns from explicit user actions and preserves user overrides as first-class signals.
"""
import json
import uuid
from datetime import datetime, timezone

from backend.database import get_sync_db, run_write

CANONICAL_FEEDBACK_EVENTS = {
    "approve",
    "reject",
    "edit",
    "promote",
    "demote",
    "manual_add",
}

FEEDBACK_EVENT_ALIASES = {
    "approve": "approve",
    "approved": "approve",
    "approval": "approve",
    "reject": "reject",
    "rejected": "reject",
    "rejection": "reject",
    "edit": "edit",
    "edited": "edit",
    "promote": "promote",
    "promoted": "promote",
    "promotion": "promote",
    "demote": "demote",
    "demoted": "demote",
    "demotion": "demote",
    "manual_add": "manual_add",
    "manual add": "manual_add",
    "manually_add": "manual_add",
}

EVENT_WEIGHTS = {
    "approve": 1.0,
    "reject": -2.0,
    "edit": 1.5,
    "promote": 2.5,
    "demote": -2.5,
    "manual_add": 3.0,
}

PREFERENCE_KEYS = (
    "concise_summaries",
    "commercially_useful_content",
    "relationship_relevant_content",
    "minimal_fluff",
    "practical_meeting_preparation",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_feedback_event(event_type: str) -> str:
    normalized = FEEDBACK_EVENT_ALIASES.get((event_type or "").strip().lower())
    if not normalized:
        raise ValueError(f"Unsupported feedback event: {event_type}")
    return normalized


def _safe_json_loads(raw_value):
    if not raw_value:
        return {}
    try:
        return json.loads(raw_value)
    except Exception:
        return {}


def _estimate_preference_dimensions(target_type: str, target_snapshot: dict, details: dict) -> dict:
    details = details or {}
    explicit = details.get("preference_dimensions")
    if isinstance(explicit, dict):
        return {
            key: float(explicit.get(key, 0))
            for key in PREFERENCE_KEYS
        }

    dimensions = {key: 0.0 for key in PREFERENCE_KEYS}
    category = str(
        target_snapshot.get("topic")
        or target_snapshot.get("category")
        or details.get("category")
        or ""
    ).strip().lower()
    text = str(
        target_snapshot.get("intel_text")
        or target_snapshot.get("content")
        or details.get("text")
        or details.get("new")
        or ""
    ).strip()
    word_count = len(text.split())

    if text:
        if word_count <= 35:
            dimensions["concise_summaries"] += 1.0
            dimensions["minimal_fluff"] += 1.0
        elif word_count >= 80:
            dimensions["minimal_fluff"] -= 1.0

    if category in {"business_focus", "business focus", "recruitment_talent", "recruitment & talent"}:
        dimensions["commercially_useful_content"] += 1.0
        dimensions["practical_meeting_preparation"] += 0.75

    if category in {"family_personal", "family & personal", "obe_focus", "obe focus"}:
        dimensions["relationship_relevant_content"] += 1.0
        dimensions["practical_meeting_preparation"] += 0.5

    if target_type == "brief":
        dimensions["practical_meeting_preparation"] += 1.0
        dimensions["concise_summaries"] += 0.5

    return dimensions


def _load_feedback_target_snapshot(target_type: str, target_id: str) -> dict:
    conn = get_sync_db(read_only=True)
    try:
        c = conn.cursor()
        if target_type == "signal":
            c.execute(
                """
                SELECT signal_id AS target_id, person_id, category, content, source_snippet, created_at, 'ai_signal' AS source_kind
                FROM AI_SIGNAL WHERE signal_id = ?
                UNION ALL
                SELECT intel_id AS target_id, person_id, topic AS category, intel_text AS content, source_snippet, created_at, 'topic_intelligence' AS source_kind
                FROM TOPIC_INTELLIGENCE WHERE intel_id = ?
                LIMIT 1
                """,
                (target_id, target_id),
            )
        elif target_type == "brief":
            c.execute(
                """
                SELECT brief_id AS target_id, person_id, content_json, created_at
                FROM AI_BRIEF WHERE brief_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (target_id,),
            )
        else:
            return {}
        row = c.fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


async def record_feedback_event(*, target_type: str, target_id: str, event_type: str, details=None, user_id: str = None) -> dict:
    normalized_event = normalize_feedback_event(event_type)
    snapshot = _load_feedback_target_snapshot(target_type, target_id)
    payload = dict(details or {})
    payload["normalized_event"] = normalized_event
    if snapshot:
        payload.setdefault("person_id", snapshot.get("person_id"))
        payload.setdefault("target_snapshot", {
            key: snapshot.get(key)
            for key in ("target_id", "person_id", "category", "content", "source_snippet", "source_kind", "created_at")
            if snapshot.get(key) is not None
        })
    payload.setdefault("preference_dimensions", _estimate_preference_dimensions(target_type, snapshot, payload))
    payload.setdefault("user_override", normalized_event in {"edit", "manual_add", "promote", "demote"})

    feedback_id = str(uuid.uuid4())
    created_at = _now()

    async def _insert(db):
        await db.execute(
            """
            INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, details_json, user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback_id,
                target_type,
                target_id,
                normalized_event,
                json.dumps(payload),
                user_id,
                created_at,
            ),
        )

    await run_write(_insert, label=f"record feedback {target_type} {normalized_event}")
    return {
        "feedback_id": feedback_id,
        "event_type": normalized_event,
        "details": payload,
    }


def _load_feedback_rows(person_id: str) -> list:
    conn = get_sync_db(read_only=True)
    try:
        c = conn.cursor()
        c.execute(
            """
            SELECT f.feedback_id, f.target_type, f.target_id, f.event_type, f.details_json, f.created_at
            FROM AI_FEEDBACK f
            WHERE
                (f.target_type = 'signal' AND f.target_id IN (
                    SELECT intel_id FROM TOPIC_INTELLIGENCE WHERE person_id = ?
                    UNION
                    SELECT signal_id FROM AI_SIGNAL WHERE person_id = ?
                ))
                OR
                (f.target_type = 'brief' AND (
                    f.target_id = ?
                    OR f.target_id IN (SELECT brief_id FROM AI_BRIEF WHERE person_id = ?)
                ))
            ORDER BY f.created_at DESC
            """,
            (person_id, person_id, person_id, person_id),
        )
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


async def compute_preference_profile(person_id: str) -> dict:
    profile = {key: 0.0 for key in PREFERENCE_KEYS}
    event_counts = {key: 0 for key in CANONICAL_FEEDBACK_EVENTS}
    rows = _load_feedback_rows(person_id)

    for row in rows:
        event_type = normalize_feedback_event(row["event_type"])
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
        event_weight = EVENT_WEIGHTS.get(event_type, 0.0)
        details = _safe_json_loads(row.get("details_json"))
        dimensions = details.get("preference_dimensions") if isinstance(details, dict) else {}
        if not isinstance(dimensions, dict):
            dimensions = {}
        for key in PREFERENCE_KEYS:
            profile[key] += float(dimensions.get(key, 0.0)) * event_weight

    return {
        "scores": profile,
        "event_counts": event_counts,
        "total_events": len(rows),
    }


def preference_guidance_lines(preference_profile: dict) -> list:
    scores = (preference_profile or {}).get("scores", {})
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    labels = {
        "concise_summaries": "Prefer concise summaries",
        "commercially_useful_content": "Prioritise commercially useful content",
        "relationship_relevant_content": "Keep relationship-relevant context visible",
        "minimal_fluff": "Remove fluff and generic filler",
        "practical_meeting_preparation": "Optimise for practical meeting preparation",
    }
    lines = [f"- {labels[key]} (learned strength {score:.1f})" for key, score in ordered if score > 0]
    if not lines:
        lines.append("- Default to concise, commercially useful, relationship-relevant, practical summaries with minimal fluff")
    return lines
