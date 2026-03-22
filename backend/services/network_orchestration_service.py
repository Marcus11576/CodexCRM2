from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.config import settings
from backend.database import get_db
from backend.services.relationship_intelligence_pipeline import STAGE2_RELATIONSHIP_STAGE_DETAILS

HIGH_PRIORITY_CATEGORIES = {"OBE M", "OBE T", "TGT"}
STRATEGIC_CATEGORIES = HIGH_PRIORITY_CATEGORIES | {"EXT", "HPC", "TSA"}
TIER_LABELS = {
    "T1": "T1 - Strategic Core",
    "T2": "T2 - Active Opportunity",
    "T3": "T3 - Strategic Network",
    "T4": "T4 - Keep Warm",
    "T5": "T5 - Monitor",
}


def _reason(text: str, evidence: str) -> dict[str, str]:
    return {"text": text, "evidence": evidence}


def _clamp(value: float | int, lower: int = 0, upper: int = 100) -> int:
    return int(max(lower, min(upper, round(value))))


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00").replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_contact_value(value: str | None) -> str:
    cleaned = str(value or "").replace("'", "").strip().lower()
    if cleaned == "hot":
        return "Hot"
    if cleaned == "cold":
        return "Cold"
    if cleaned == "frozen":
        return "Frozen"
    return "Warm" if cleaned == "warm" else str(value or "").strip()


def _parse_categories(raw: str | None) -> set[str]:
    return {part.strip().upper() for part in str(raw or "").split(",") if part.strip()}


def _classify_task_intent(task_text: str | None) -> dict[str, Any]:
    text = str(task_text or "").strip()
    lowered = text.lower()
    if not lowered:
        return {"key": "unknown", "label": "Unclear task", "cover_strength": 22}

    if any(token in lowered for token in ("agreement", "contract", "proposal", "interview", "offer", "shortlist", "candidate", "cv", "search assignment")):
        return {"key": "opportunity_follow_up", "label": "Opportunity follow-up", "cover_strength": 72}
    if any(token in lowered for token in ("arrange call", "schedule call", "set call", "book call", "teams call", "zoom call", "arrange meeting", "schedule meeting", "book meeting")):
        return {"key": "meeting_arrangement", "label": "Meeting arrangement", "cover_strength": 64}
    if any(token in lowered for token in ("catch up", "catch-up", "reconnect", "touch base", "check in", "call ", " call", "phone", "coffee", "lunch")):
        return {"key": "relationship_follow_up", "label": "Relationship follow-up", "cover_strength": 54}
    if any(token in lowered for token in ("update crm", "log", "note", "admin", "tidy", "file")):
        return {"key": "admin", "label": "Admin follow-up", "cover_strength": 16}
    return {"key": "generic_follow_up", "label": "Generic follow-up", "cover_strength": 36}


def _expected_cadence_days(contact: dict[str, Any]) -> int:
    contact_value = _normalize_contact_value(contact.get("contact_value"))
    categories = _parse_categories(contact.get("cat"))
    cadence = 45
    if contact_value == "Hot":
        cadence = 14
    elif contact_value == "Warm":
        cadence = 30
    elif contact_value == "Cold":
        cadence = 60

    if categories & HIGH_PRIORITY_CATEGORIES:
        cadence = min(cadence, 21)
    if "EXT" in categories:
        cadence = min(cadence, 35)
    return cadence


def _has_future_cover(contact: dict[str, Any], now: datetime) -> bool:
    return int(contact.get("cover_strength") or 0) >= 40


def _trigger_due_soon(contact: dict[str, Any], now: datetime) -> bool:
    trigger = _parse_datetime(contact.get("nearest_open_trigger_date"))
    if trigger is None:
        return False
    return (trigger.date() - now.date()).days <= 30


def _task_pressure(contact: dict[str, Any], now: datetime) -> bool:
    if int(contact.get("open_task_count") or 0) <= 0:
        return False
    due = _parse_datetime(contact.get("earliest_open_task_due_date"))
    if due is None:
        return True
    return due.date() <= now.date()


def _meeting_churn(contact: dict[str, Any]) -> bool:
    return int(contact.get("recent_cancelled_meeting_count") or 0) > 0 or int(contact.get("recent_rescheduled_meeting_count") or 0) > 0


def _compute_recency_days(contact: dict[str, Any], now: datetime) -> int | None:
    candidates = [
        _parse_datetime(contact.get("last_meaningful_contact_at")),
        _parse_datetime(contact.get("last_success_at")),
        _parse_datetime(contact.get("last_interaction_at")),
        _parse_datetime(contact.get("last_contact_datetime")),
    ]
    candidates = [item for item in candidates if item is not None]
    if not candidates:
        return None
    anchor = max(candidates)
    return max(0, int((now - anchor).days))


def _score_default_value(field_name: str) -> int:
    return {
        "opportunity_readiness_score": 0,
        "strategic_value_score": 50,
        "influence_score": 50,
        "future_option_score": 50,
        "relationship_confidence_score": 50,
    }.get(field_name, 50)


def _has_manual_score_override(contact: dict[str, Any], field_name: str) -> bool:
    raw = contact.get(field_name)
    if raw is None:
        return False
    try:
        numeric = int(raw)
    except (TypeError, ValueError):
        return False
    if numeric != _score_default_value(field_name):
        return True
    # Treat schema defaults as "unknown" unless the relationship health
    # was explicitly refreshed.
    return bool(str(contact.get("last_health_refresh_at") or "").strip())


def _is_recently_reactivated(contact: dict[str, Any], now: datetime) -> bool:
    latest = _parse_datetime(contact.get("last_interaction_at"))
    previous = _parse_datetime(contact.get("previous_interaction_at"))
    if latest is None:
        return False
    if (now - latest).days > 14:
        return False
    if previous is None:
        return True
    return (latest - previous).days >= 45


def _latest_relationship_signal(contact: dict[str, Any]) -> datetime | None:
    candidates = [
        _parse_datetime(contact.get("last_meaningful_contact_at")),
        _parse_datetime(contact.get("last_success_at")),
        _parse_datetime(contact.get("last_interaction_at")),
        _parse_datetime(contact.get("last_contact_datetime")),
        _parse_datetime(contact.get("last_meeting_date")),
    ]
    candidates = [item for item in candidates if item is not None]
    return max(candidates) if candidates else None


def _build_cover_analysis(contact: dict[str, Any], now: datetime) -> dict[str, Any]:
    next_meeting = _parse_datetime(contact.get("next_meeting_date"))
    next_due = _parse_datetime(contact.get("next_contact_due_date"))
    task_due = _parse_datetime(contact.get("earliest_open_task_due_date"))
    last_signal = _latest_relationship_signal(contact)
    task_meta = _classify_task_intent(contact.get("primary_open_task_text"))
    dated_open_tasks = int(contact.get("dated_open_task_count") or 0)
    undated_open_tasks = int(contact.get("undated_open_task_count") or 0)

    cover_kind = "none"
    cover_strength = 0
    cover_reason = "No scheduled follow-up cover is recorded"

    if next_meeting is not None and next_meeting.date() >= now.date():
        days_until = (next_meeting.date() - now.date()).days
        cover_kind = "meeting"
        cover_strength = 90 if days_until <= 14 else 82
        topic = str(contact.get("next_meeting_topic") or "meeting").strip()
        cover_reason = f"Future meeting cover is booked: {topic}"
    elif task_due is not None and task_due.date() >= now.date() and dated_open_tasks > 0:
        days_until = (task_due.date() - now.date()).days
        cover_kind = "task"
        cover_strength = int(task_meta["cover_strength"])
        if days_until <= 7:
            cover_strength += 6
        elif days_until <= 21:
            cover_strength += 2
        cover_strength = _clamp(cover_strength)
        cover_reason = f"Dated {task_meta['label'].lower()} is in place"
    elif next_due is not None and next_due.date() >= now.date():
        days_until = (next_due.date() - now.date()).days
        cover_kind = "scheduled_touchpoint"
        cover_strength = 48 if days_until <= 14 else 40
        cover_reason = "A scheduled follow-up date is in place"
    elif undated_open_tasks > 0:
        cover_kind = "undated_task"
        cover_strength = 0
        cover_reason = "Open tasks exist, but they are undated and do not count as reliable cover"

    confirmation_needed = False
    confirmation_reason = ""
    confirmation_prompt = ""

    if task_due is not None and task_due.date() < now.date() and int(contact.get("open_task_count") or 0) > 0:
        if last_signal is None or last_signal.date() <= task_due.date():
            confirmation_needed = True
            confirmation_reason = "Task due date passed with no recorded outcome or next step"
            confirmation_prompt = "Confirm whether the scheduled follow-up happened and log the outcome or next step."
    elif next_due is not None and next_due.date() < now.date():
        if last_signal is None or last_signal.date() <= next_due.date():
            confirmation_needed = True
            confirmation_reason = "Scheduled follow-up date passed with no recorded outcome"
            confirmation_prompt = "Add the follow-up outcome or log a new next step."
    else:
        last_meeting = _parse_datetime(contact.get("last_meeting_date"))
        if last_meeting is not None and 0 <= (now.date() - last_meeting.date()).days <= 5:
            if last_signal is None or last_signal <= last_meeting:
                confirmation_needed = True
                confirmation_reason = "Recent meeting is recorded, but there is no logged outcome or next step yet"
                confirmation_prompt = "Capture the meeting outcome and book the next step while it is still current."

    return {
        "cover_kind": cover_kind,
        "cover_strength": cover_strength,
        "cover_reason": cover_reason,
        "primary_open_task_kind": task_meta["key"],
        "primary_open_task_label": task_meta["label"],
        "follow_up_confirmation_needed": confirmation_needed,
        "follow_up_confirmation_reason": confirmation_reason,
        "follow_up_confirmation_prompt": confirmation_prompt,
    }


def _queue_rank(contact: dict[str, Any], now: datetime) -> tuple[int, int, int, int, int]:
    recency_days = contact.get("recency_days")
    opportunity_pressure = 1 if (
        int(contact.get("open_opportunity_count") or 0) > 0
        or int(contact.get("open_company_opportunity_count") or 0) > 0
        or int(contact.get("open_opportunity_situation_count") or 0) > 0
        or contact.get("trigger_due_soon")
    ) else 0
    return (
        int(contact.get("network_health_score") or 0),
        1 if contact.get("follow_up_confirmation_needed") else 0,
        1 if contact.get("has_task_pressure") else 0,
        opportunity_pressure,
        1 if contact.get("is_high_priority") else 0,
    )


def _infer_effective_tier(contact: dict[str, Any]) -> tuple[str, list[str]]:
    explicit = str(contact.get("network_tier") or "").strip().upper()
    reasons: list[dict[str, str]] = []
    if explicit in TIER_LABELS:
        reasons.append(_reason(f"Manual tier set: {TIER_LABELS[explicit]}", "substantiated"))
        if contact.get("tier_rationale"):
            reasons.append(_reason(str(contact["tier_rationale"]).strip(), "substantiated"))
        return explicit, reasons

    categories = _parse_categories(contact.get("cat"))
    if int(contact.get("open_opportunity_count") or 0) > 0:
        reasons.append(_reason("Active opportunity linked to this relationship", "substantiated"))
        return "T2", reasons
    if categories & {"OBE M"}:
        reasons.append(_reason("OBE Member category suggests strategic core coverage", "substantiated"))
        return "T1", reasons
    if categories & {"OBE T", "TGT", "EXT", "TSA"}:
        reasons.append(_reason("Strategic category implies maintained network value", "substantiated"))
        return "T3", reasons
    if contact.get("contact_value") in {"Hot", "Warm"}:
        reasons.append(_reason("Relationship temperature suggests keep-warm value", "substantiated"))
        return "T4", reasons
    reasons.append(_reason("Low evidence relationship defaults to monitor tier", "inferred"))
    return "T5", reasons


def _compute_network_scores(contact: dict[str, Any]) -> dict[str, int]:
    score_reasons: list[dict[str, str]] = []
    component_reasons: dict[str, list[dict[str, str]]] = {
        "coverage_health": [],
        "strategic_value": [],
        "opportunity_readiness": [],
        "relationship_strength": [],
        "confidence": [],
    }

    recency_days = contact.get("recency_days")
    cadence_days = max(7, int(contact.get("cadence_days") or 30))
    recency_ratio = None if recency_days is None else float(recency_days) / float(cadence_days)

    cover_strength = int(contact.get("cover_strength") or 0)
    cover_kind = str(contact.get("cover_kind") or "none")

    if recency_ratio is None:
        coverage = 10
        component_reasons["coverage_health"].append(_reason("There is no dated recent relationship signal", "substantiated"))
    elif recency_ratio <= 0.40:
        coverage = 94
        component_reasons["coverage_health"].append(_reason("Recent contact sits comfortably inside expected cadence", "substantiated"))
    elif recency_ratio <= 0.75:
        coverage = 82
        component_reasons["coverage_health"].append(_reason("Recent contact is healthy against expected cadence", "substantiated"))
    elif recency_ratio <= 1.0:
        coverage = 70
        component_reasons["coverage_health"].append(_reason("Recent contact is still within expected cadence", "substantiated"))
    elif recency_ratio <= 1.25:
        coverage = 55
        component_reasons["coverage_health"].append(_reason("Contact is drifting toward the edge of expected cadence", "substantiated"))
    elif recency_ratio <= 1.75:
        coverage = 35
        component_reasons["coverage_health"].append(_reason("Contact is now outside expected cadence", "substantiated"))
    else:
        coverage = 15
        component_reasons["coverage_health"].append(_reason("Relationship coverage is stale against expected cadence", "substantiated"))

    if cover_strength >= 80:
        coverage += 18
        component_reasons["coverage_health"].append(_reason(str(contact.get("cover_reason") or "Future meeting cover is in place"), "substantiated"))
    elif cover_strength >= 60:
        coverage += 12
        component_reasons["coverage_health"].append(_reason(str(contact.get("cover_reason") or "A strong dated follow-up is in place"), "substantiated"))
    elif cover_strength >= 40:
        coverage += 8
        component_reasons["coverage_health"].append(_reason(str(contact.get("cover_reason") or "Scheduled follow-up cover exists"), "substantiated"))
    else:
        coverage -= 12
        component_reasons["coverage_health"].append(_reason(str(contact.get("cover_reason") or "No future cover is in place"), "substantiated"))
    if contact.get("is_high_priority") and not contact.get("has_future_cover"):
        coverage -= 15
        component_reasons["coverage_health"].append(_reason("Priority relationship is uncovered", "substantiated"))
    if str(contact.get("meeting_status") or "").lower() == "overdue":
        coverage -= 20
        component_reasons["coverage_health"].append(_reason("Meeting status is overdue", "substantiated"))
    if contact.get("has_task_pressure"):
        coverage -= 16
        component_reasons["coverage_health"].append(_reason("An open task is already under pressure", "substantiated"))
    if int(contact.get("unanswered_outbound_count") or 0) >= 3:
        coverage -= 12
        component_reasons["coverage_health"].append(_reason("Multiple outbound attempts remain unanswered", "substantiated"))
    if int(contact.get("open_risk_situation_count") or 0) > 0:
        coverage -= 8
        component_reasons["coverage_health"].append(_reason("An active risk situation increases the need for coverage", "substantiated"))
    if cover_kind == "undated_task":
        coverage -= 8
        component_reasons["coverage_health"].append(_reason("Undated tasks need tightening before they can count as relationship cover", "substantiated"))
    if int(contact.get("recent_cancelled_meeting_count") or 0) > 0:
        coverage -= 10
        component_reasons["coverage_health"].append(_reason("A recent Microsoft 365 meeting cancellation weakened current cover", "substantiated"))
    elif int(contact.get("recent_rescheduled_meeting_count") or 0) > 0:
        coverage -= 6
        component_reasons["coverage_health"].append(_reason("A recent Microsoft 365 meeting reschedule suggests timing has shifted", "substantiated"))
    if contact.get("follow_up_confirmation_needed"):
        coverage -= 18
        component_reasons["coverage_health"].append(_reason(str(contact.get("follow_up_confirmation_reason") or "Follow-up confirmation is required"), "substantiated"))
    coverage = _clamp(coverage)

    strategic = int(contact.get("strategic_value_score") or 0)
    influence = int(contact.get("influence_score") or 0)
    future_option = int(contact.get("future_option_score") or 0)
    strategic_manual = _has_manual_score_override(contact, "strategic_value_score")
    influence_manual = _has_manual_score_override(contact, "influence_score")
    future_option_manual = _has_manual_score_override(contact, "future_option_score")
    confidence_manual = _has_manual_score_override(contact, "relationship_confidence_score")
    opportunity_manual = _has_manual_score_override(contact, "opportunity_readiness_score")

    if not strategic_manual:
        strategic = {
            "T1": 72,
            "T2": 66,
            "T3": 54,
            "T4": 38,
            "T5": 28,
        }.get(str(contact.get("effective_network_tier") or "").upper(), 34)
        component_reasons["strategic_value"].append(
            _reason(
                f"Effective tier {contact.get('effective_network_tier_label') or contact.get('effective_network_tier') or 'unknown'} sets the base strategic value",
                "substantiated",
            )
        )
        categories = _parse_categories(contact.get("cat"))
        if "OBE M" in categories:
            strategic = max(strategic, 74)
            component_reasons["strategic_value"].append(_reason("OBE Member category raises strategic importance", "substantiated"))
        elif categories & {"OBE T", "TGT"}:
            strategic = max(strategic, 68)
            component_reasons["strategic_value"].append(_reason("Targeted strategic category raises strategic importance", "substantiated"))
        elif categories & {"EXT", "TSA", "HPC"}:
            strategic = max(strategic, 60)
            component_reasons["strategic_value"].append(_reason("External strategic category raises network importance", "substantiated"))
        decision_role = str(contact.get("decision_role") or "").strip()
        if decision_role in {"decision_maker", "influencer", "connector"}:
            strategic += 5
            component_reasons["strategic_value"].append(_reason("Decision role increases strategic importance", "substantiated"))
        account_priority = str(contact.get("account_priority") or "").strip().lower()
        if account_priority == "hot":
            strategic += 8
            component_reasons["strategic_value"].append(_reason("Hot account priority increases strategic importance", "substantiated"))
        elif account_priority == "warm":
            strategic += 4
            component_reasons["strategic_value"].append(_reason("Warm account priority increases strategic importance", "substantiated"))
        if int(contact.get("interaction_count") or 0) >= 25:
            strategic += 4
            component_reasons["strategic_value"].append(_reason("Dense interaction history supports sustained relevance", "substantiated"))
        elif int(contact.get("interaction_count") or 0) >= 10:
            strategic += 2
            component_reasons["strategic_value"].append(_reason("Interaction history supports ongoing strategic relevance", "substantiated"))
        if int(contact.get("open_opportunity_count") or 0) > 0 or int(contact.get("open_company_opportunity_count") or 0) > 0:
            strategic += 4
            component_reasons["strategic_value"].append(_reason("Live opportunity activity raises the cost of missing this relationship", "substantiated"))
        strategic = _clamp(strategic)
    else:
        component_reasons["strategic_value"].append(_reason("Manual strategic value score is set", "substantiated"))

    if not influence_manual:
        influence = 18
        if str(contact.get("influence_scope") or "").strip():
            influence += 12
            component_reasons["relationship_strength"].append(_reason("Influence scope is defined", "substantiated"))
        else:
            component_reasons["relationship_strength"].append(_reason("Influence scope is not yet defined", "substantiated"))
        if str(contact.get("decision_role") or "").strip() in {"decision_maker", "influencer", "connector"}:
            influence += 18
            component_reasons["relationship_strength"].append(_reason("Decision role suggests influence over access or outcomes", "substantiated"))
        if int(contact.get("interaction_count") or 0) >= 20:
            influence += 10
            component_reasons["relationship_strength"].append(_reason("Repeated interaction history supports working influence", "substantiated"))
        elif int(contact.get("interaction_count") or 0) >= 8:
            influence += 6
            component_reasons["relationship_strength"].append(_reason("Interaction history suggests some working influence", "substantiated"))
        influence = _clamp(influence)
    else:
        component_reasons["relationship_strength"].append(_reason("Manual influence score is set", "substantiated"))

    if not future_option_manual:
        future_option = 12
        contact_value = contact.get("contact_value")
        if contact_value == "Hot":
            future_option += 24
            component_reasons["relationship_strength"].append(_reason("Hot relationship temperature supports future option value", "substantiated"))
        elif contact_value == "Warm":
            future_option += 16
            component_reasons["relationship_strength"].append(_reason("Warm relationship temperature supports future option value", "substantiated"))
        elif contact_value == "Cold":
            future_option += 6
            component_reasons["relationship_strength"].append(_reason("Cold relationship temperature limits future option value", "substantiated"))
        elif contact_value == "Frozen":
            future_option -= 6
            component_reasons["relationship_strength"].append(_reason("Frozen relationship temperature materially limits future option value", "substantiated"))
        if int(contact.get("interaction_count") or 0) >= 20:
            future_option += 14
            component_reasons["relationship_strength"].append(_reason("Repeated interaction history suggests future option value", "substantiated"))
        elif int(contact.get("interaction_count") or 0) >= 8:
            future_option += 8
            component_reasons["relationship_strength"].append(_reason("Some interaction history supports future option value", "substantiated"))
        if recency_ratio is not None and recency_ratio <= 1.0:
            future_option += 8
            component_reasons["relationship_strength"].append(_reason("Recent contact supports current relationship strength", "substantiated"))
        elif recency_ratio is not None and recency_ratio > 1.5:
            future_option -= 12
            component_reasons["relationship_strength"].append(_reason("Relationship drift weakens future option value", "substantiated"))
        if contact.get("has_future_cover"):
            future_option += 6
            component_reasons["relationship_strength"].append(_reason("A next step reinforces relationship continuity", "substantiated"))
        if str(contact.get("decision_role") or "").strip() in {"decision_maker", "influencer", "connector"}:
            future_option += 6
            component_reasons["relationship_strength"].append(_reason("Decision role supports future optionality", "substantiated"))
        if str(contact.get("effective_network_tier") or "").upper() in {"T1", "T2"}:
            future_option += 4
            component_reasons["relationship_strength"].append(_reason("Higher-tier relationships carry more future option value", "substantiated"))
        future_option = _clamp(future_option)
    else:
        component_reasons["relationship_strength"].append(_reason("Manual future option score is set", "substantiated"))

    opportunity = int(contact.get("opportunity_readiness_score") or 0)
    if not opportunity_manual:
        opportunity = 0
        if int(contact.get("open_opportunity_count") or 0) > 0:
            opportunity = max(opportunity, min(96, 72 + (int(contact.get("open_opportunity_count") or 0) - 1) * 8))
            component_reasons["opportunity_readiness"].append(_reason("There is an active linked person opportunity", "substantiated"))
        if int(contact.get("open_company_opportunity_count") or 0) > 0:
            opportunity = max(opportunity, min(84, 56 + (int(contact.get("open_company_opportunity_count") or 0) - 1) * 6))
            component_reasons["opportunity_readiness"].append(_reason("There is an active company-level opportunity", "substantiated"))
        if int(contact.get("open_opportunity_situation_count") or 0) > 0:
            opportunity = max(opportunity, min(86, 50 + int(contact.get("open_opportunity_situation_count") or 0) * 10))
            component_reasons["opportunity_readiness"].append(_reason("Tracked opportunity situations are currently open", "substantiated"))
        if int(contact.get("open_risk_situation_count") or 0) > 0 and opportunity >= 40:
            opportunity += 10
            component_reasons["opportunity_readiness"].append(_reason("Active risk or friction sits inside the current opportunity picture", "substantiated"))
        if contact.get("trigger_due_soon"):
            opportunity = max(opportunity, 64)
            component_reasons["opportunity_readiness"].append(_reason("A trigger date is approaching within 30 days", "substantiated"))
        if contact.get("is_recently_reactivated"):
            opportunity = max(opportunity, 42)
            component_reasons["opportunity_readiness"].append(_reason("Recent reactivation creates near-term opportunity potential", "substantiated"))
        if contact.get("follow_up_confirmation_needed"):
            opportunity = max(opportunity, 36)
            component_reasons["opportunity_readiness"].append(_reason("A passed follow-up date with no recorded outcome creates actionable pressure", "substantiated"))
        if contact.get("is_high_priority") and not contact.get("has_future_cover") and recency_ratio is not None and recency_ratio >= 0.75:
            opportunity = max(opportunity, 28)
            component_reasons["opportunity_readiness"].append(_reason("Priority relationship is active but uncovered", "substantiated"))
        if opportunity == 0:
            component_reasons["opportunity_readiness"].append(_reason("No live opportunity pressure is visible right now", "substantiated"))
        opportunity = _clamp(opportunity)
    else:
        component_reasons["opportunity_readiness"].append(_reason("Manual opportunity readiness score is set", "substantiated"))

    confidence = int(contact.get("relationship_confidence_score") or 0)
    if not confidence_manual:
        confidence = 10
        if contact.get("has_relationship_signal"):
            confidence += 18
            component_reasons["confidence"].append(_reason("Recent relationship signal increases confidence", "substantiated"))
        if int(contact.get("interaction_count") or 0) >= 5:
            confidence += 10
            component_reasons["confidence"].append(_reason("A basic interaction history exists", "substantiated"))
        if int(contact.get("interaction_count") or 0) >= 15:
            confidence += 8
            component_reasons["confidence"].append(_reason("A deeper interaction history improves confidence", "substantiated"))
        if str(contact.get("network_tier") or "").strip():
            confidence += 10
            component_reasons["confidence"].append(_reason("A manual network tier improves score confidence", "substantiated"))
        if str(contact.get("relationship_owner") or "").strip():
            confidence += 8
            component_reasons["confidence"].append(_reason("Relationship ownership is defined", "substantiated"))
        if str(contact.get("decision_role") or "").strip():
            confidence += 8
            component_reasons["confidence"].append(_reason("Decision role is defined", "substantiated"))
        if str(contact.get("influence_scope") or "").strip():
            confidence += 6
            component_reasons["confidence"].append(_reason("Influence scope is defined", "substantiated"))
        if str(contact.get("account_priority") or "").strip():
            confidence += 6
            component_reasons["confidence"].append(_reason("Account priority is defined", "substantiated"))
        if any(str(contact.get(field) or "").strip() for field in ("last_meaningful_contact_at", "last_inbound_at", "last_outbound_at")):
            confidence += 8
            component_reasons["confidence"].append(_reason("Structured recency fields improve score confidence", "substantiated"))
        if int(contact.get("open_situation_count") or 0) > 0:
            confidence += 6
            component_reasons["confidence"].append(_reason("Tracked situations provide structured live signal", "substantiated"))
        if int(contact.get("open_opportunity_count") or 0) > 0 or int(contact.get("open_company_opportunity_count") or 0) > 0:
            confidence += 4
            component_reasons["confidence"].append(_reason("Opportunity records provide structured evidence", "substantiated"))
        confidence = _clamp(confidence)
    else:
        component_reasons["confidence"].append(_reason("Manual confidence score is set", "substantiated"))

    relationship_strength = max(0, min(100, round((influence + future_option) / 2)))
    coverage_gap = 100 - coverage
    relationship_gap = 100 - relationship_strength
    confidence_gap = 100 - confidence

    pressure_bonus = 0
    if str(contact.get("meeting_status") or "").lower() == "overdue":
        pressure_bonus += 8
    if contact.get("has_task_pressure"):
        pressure_bonus += 6
    if contact.get("trigger_due_soon"):
        pressure_bonus += 5
    if contact.get("is_recently_reactivated"):
        pressure_bonus += 4
    if int(contact.get("open_risk_situation_count") or 0) > 0:
        pressure_bonus += 4
    if contact.get("follow_up_confirmation_needed"):
        pressure_bonus += 8
    if int(contact.get("recent_cancelled_meeting_count") or 0) > 0:
        pressure_bonus += 5
    elif int(contact.get("recent_rescheduled_meeting_count") or 0) > 0:
        pressure_bonus += 3

    network_health = round(
        (coverage_gap * 0.35)
        + (opportunity * 0.25)
        + (strategic * 0.20)
        + (relationship_gap * 0.10)
        + (confidence_gap * 0.10)
        + pressure_bonus
    )

    if coverage <= 55:
        score_reasons.append(_reason("Coverage gap is pulling this relationship into attention", "inferred"))
    elif coverage >= 80:
        score_reasons.append(_reason("Coverage is healthy enough not to drive urgent attention", "inferred"))

    if opportunity >= 65:
        score_reasons.append(_reason("Live opportunity pressure is active", "inferred"))
    elif opportunity <= 20:
        score_reasons.append(_reason("There is limited immediate opportunity pressure", "inferred"))

    if strategic >= 75:
        score_reasons.append(_reason("This relationship is strategically important enough to stay high in the workload", "inferred"))

    if relationship_strength <= 45:
        score_reasons.append(_reason("Relationship strength is not strong enough to coast without attention", "inferred"))

    if confidence <= 45:
        score_reasons.append(_reason("Data confidence is limited and the record needs tightening", "inferred"))
    elif confidence >= 75:
        score_reasons.append(_reason("The flag is supported by a reasonable amount of structured evidence", "inferred"))

    if pressure_bonus >= 10:
        score_reasons.append(_reason("Urgency signals are adding pressure on top of the base score", "inferred"))
    if contact.get("follow_up_confirmation_needed"):
        score_reasons.append(_reason(str(contact.get("follow_up_confirmation_reason") or "A scheduled follow-up needs an outcome update"), "inferred"))
    if int(contact.get("recent_cancelled_meeting_count") or 0) > 0:
        score_reasons.append(_reason("A recent Microsoft 365 meeting cancellation has put this relationship back into attention", "inferred"))
    elif int(contact.get("recent_rescheduled_meeting_count") or 0) > 0:
        score_reasons.append(_reason("A recent Microsoft 365 meeting reschedule means the timing needs checking", "inferred"))

    return {
        "coverage_health": int(coverage),
        "strategic_value": int(strategic),
        "opportunity_readiness": int(opportunity),
        "relationship_strength": int(relationship_strength),
        "confidence": int(confidence),
        "network_health_score": _clamp(network_health),
        "score_reason_summary": score_reasons,
        "score_component_reasons": component_reasons,
    }


def _classify_contact(contact: dict[str, Any], now: datetime) -> str:
    categories = _parse_categories(contact.get("cat"))
    network_tier = str(contact.get("network_tier") or "").strip().upper()
    maintenance_mode = str(contact.get("maintenance_mode") or "").strip().lower()
    high_priority = bool(categories & HIGH_PRIORITY_CATEGORIES)
    strategic = bool(categories & STRATEGIC_CATEGORIES)
    recency_days = contact["recency_days"]
    cadence_days = contact["cadence_days"]
    has_future_cover = contact["has_future_cover"]
    has_task_pressure = contact["has_task_pressure"]
    meeting_status = str(contact.get("meeting_status") or "").strip().lower()
    contact_value = _normalize_contact_value(contact.get("contact_value"))
    recently_reactivated = contact["is_recently_reactivated"]
    has_relationship_signal = recency_days is not None
    active_opportunities = int(contact.get("open_opportunity_count") or 0) + int(contact.get("open_company_opportunity_count") or 0)
    trigger_due_soon = contact["trigger_due_soon"]
    score = int(contact.get("network_health_score") or 0)
    is_drifting = bool(has_relationship_signal and recency_days is not None and recency_days > cadence_days)
    is_near_edge = bool(has_relationship_signal and recency_days is not None and recency_days >= int(cadence_days * 0.75))
    has_open_priority_signal = bool(
        active_opportunities > 0
        or int(contact.get("open_opportunity_situation_count") or 0) > 0
        or trigger_due_soon
    )

    if maintenance_mode == "work":
        return "act_now"
    if maintenance_mode == "maintain":
        return "maintain"
    if maintenance_mode == "preserve":
        return "preserve"
    if maintenance_mode == "monitor":
        return "monitor"

    if (
        contact.get("follow_up_confirmation_needed")
        or
        meeting_status == "overdue"
        or has_task_pressure
        or trigger_due_soon
        or active_opportunities > 0
        or int(contact.get("open_opportunity_situation_count") or 0) > 0
        or (high_priority and not has_future_cover and is_drifting)
        or (high_priority and not has_future_cover and score >= 75)
        or (has_relationship_signal and recency_days > cadence_days and not has_future_cover)
        or (recently_reactivated and score >= 55)
        or (score >= 80 and (not has_future_cover or has_task_pressure or meeting_status == "overdue"))
    ):
        return "act_now"

    if network_tier in {"T1", "T2"}:
        return "maintain" if network_tier == "T1" else "act_now"
    if network_tier == "T3":
        return "maintain"
    if network_tier == "T4":
        return "preserve"
    if network_tier == "T5":
        return "monitor"

    if strategic or contact_value in {"Hot", "Warm"} or has_future_cover or (high_priority and not has_future_cover) or (is_near_edge and not has_open_priority_signal):
        return "maintain"

    if has_relationship_signal or contact_value or categories - {"GEN"}:
        return "preserve"

    return "monitor"


def _score_band(score: int) -> str:
    if score >= 75:
        return "Act Now"
    if score >= 55:
        return "Priority"
    if score >= 35:
        return "Maintain"
    return "Monitor"


def _legacy_scoring_disabled_row(
    row: dict[str, Any],
    relationship_score_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned = dict(row)
    cleaned.update(
        {
            "cadence_days": None,
            "recency_days": None,
            "has_future_cover": False,
            "has_task_pressure": False,
            "has_meeting_churn": False,
            "is_recently_reactivated": False,
            "trigger_due_soon": False,
            "has_relationship_signal": False,
            "is_high_priority": False,
            "effective_network_tier": None,
            "effective_network_tier_label": None,
            "tier_reason_trace": [],
            "coverage_health": None,
            "strategic_value": None,
            "opportunity_readiness": None,
            "relationship_strength": None,
            "confidence": None,
            "network_health_score": None,
            "score_reason_summary": [
                _reason(
                    "Legacy scoring is disabled while the new chatbot-native intelligence model is being implemented.",
                    "substantiated",
                )
            ],
            "score_component_reasons": {},
            "score_band": "Disabled",
            "queue_key": "monitor",
            "queue_reason": "Legacy scoring disabled; awaiting new intelligence scoring.",
        }
    )
    score_context = relationship_score_context if isinstance(relationship_score_context, dict) else {}
    rel_health_raw = score_context.get("relationship_health_score")
    try:
        rel_health_score = _clamp(float(rel_health_raw)) if rel_health_raw is not None else None
    except (TypeError, ValueError):
        rel_health_score = None

    if rel_health_score is not None:
        cleaned["network_health_score"] = rel_health_score
        cleaned["relationship_health_score"] = rel_health_score
        cleaned["score_band"] = _score_band(rel_health_score)
        cleaned["score_reason_summary"] = [
            _reason(
                "Relationship score is sourced from transcript-grounded Stage 1/2 intelligence while legacy scoring remains disabled.",
                "substantiated",
            )
        ]
        cleaned["queue_key"] = ""
        cleaned["queue_reason"] = "Relationship intelligence score is active (legacy queue scoring disabled)."
        cleaned["relationship_score_source"] = "relationship_intelligence"
        cleaned["relationship_score_generated_at"] = score_context.get("generated_at")

        commercial_raw = score_context.get("commercial_priority_score")
        execution_raw = score_context.get("execution_pressure_score")
        try:
            if commercial_raw is not None:
                cleaned["commercial_priority_score"] = _clamp(float(commercial_raw))
        except (TypeError, ValueError):
            pass
        try:
            if execution_raw is not None:
                cleaned["execution_pressure_score"] = _clamp(float(execution_raw))
        except (TypeError, ValueError):
            pass

    return cleaned


def _normalize_relationship_stage_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if not code:
        return ""
    if code in STAGE2_RELATIONSHIP_STAGE_DETAILS:
        return code
    if code.startswith("S") and code[1:].isdigit():
        return code
    return ""


def _extract_stage_from_briefing_json(raw: Any) -> tuple[str, str]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return "", ""
    stage2 = payload.get("relationship_business_flow_stage2")
    stage2 = stage2 if isinstance(stage2, dict) else {}
    relationship_stage = stage2.get("relationship_stage")
    relationship_stage = relationship_stage if isinstance(relationship_stage, dict) else {}
    stage_code = _normalize_relationship_stage_code(relationship_stage.get("code"))
    stage_label = str(relationship_stage.get("label") or "").strip()
    return stage_code, stage_label


def _resolve_stage_context_payload(override_code: str, stage_code: str, stage_label: str) -> dict[str, Any]:
    override = _normalize_relationship_stage_code(override_code)
    code = _normalize_relationship_stage_code(stage_code)
    label = str(stage_label or "").strip()

    if override:
        detail = STAGE2_RELATIONSHIP_STAGE_DETAILS.get(override) or {}
        resolved_label = str(detail.get("label") or label or override).strip()
        return {
            "relationship_stage_code": override,
            "relationship_stage_label": resolved_label,
            "relationship_stage": override,
            "relationship_stage_source": "override",
        }
    if code:
        detail = STAGE2_RELATIONSHIP_STAGE_DETAILS.get(code) or {}
        resolved_label = str(label or detail.get("label") or code).strip()
        return {
            "relationship_stage_code": code,
            "relationship_stage_label": resolved_label,
            "relationship_stage": code,
            "relationship_stage_source": "stage2",
        }
    return {}


async def _load_relationship_stage_context_map(person_ids: list[str]) -> dict[str, dict[str, Any]]:
    normalized_ids = [str(person_id or "").strip() for person_id in person_ids if str(person_id or "").strip()]
    if not normalized_ids:
        return {}

    placeholders = ",".join(["?"] * len(normalized_ids))
    overrides: dict[str, str] = {}
    stage_rows: dict[str, tuple[str, str]] = {}

    async with get_db() as db:
        async with db.execute(
            f"""
            SELECT person_id, relationship_stage_override
            FROM PERSON
            WHERE person_id IN ({placeholders})
            """,
            tuple(normalized_ids),
        ) as cursor:
            for row in await cursor.fetchall():
                overrides[str(row["person_id"])] = _normalize_relationship_stage_code(row["relationship_stage_override"])

        async with db.execute(
            f"""
            SELECT person_id, briefing_json
            FROM (
                SELECT
                    person_id,
                    briefing_json,
                    ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY created_at DESC) AS rn
                FROM REL_INTEL_RUN
                WHERE status = 'completed'
                  AND person_id IN ({placeholders})
            ) ranked
            WHERE rn = 1
            """,
            tuple(normalized_ids),
        ) as cursor:
            for row in await cursor.fetchall():
                stage_rows[str(row["person_id"])] = _extract_stage_from_briefing_json(row["briefing_json"])

    result: dict[str, dict[str, Any]] = {}
    for person_id in normalized_ids:
        stage_code, stage_label = stage_rows.get(person_id, ("", ""))
        payload = _resolve_stage_context_payload(overrides.get(person_id, ""), stage_code, stage_label)
        if payload:
            result[person_id] = payload
    return result


async def _load_relationship_score_context_map(person_ids: list[str]) -> dict[str, dict[str, Any]]:
    normalized_ids = [str(person_id or "").strip() for person_id in person_ids if str(person_id or "").strip()]
    if not normalized_ids:
        return {}

    placeholders = ",".join(["?"] * len(normalized_ids))
    result: dict[str, dict[str, Any]] = {}
    async with get_db() as db:
        async with db.execute(
            f"""
            SELECT person_id, scores_json, created_at
            FROM (
                SELECT
                    person_id,
                    scores_json,
                    created_at,
                    ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY created_at DESC) AS rn
                FROM REL_INTEL_RUN
                WHERE status = 'completed'
                  AND person_id IN ({placeholders})
            ) ranked
            WHERE rn = 1
            """,
            tuple(normalized_ids),
        ) as cursor:
            for row in await cursor.fetchall():
                person_id = str(row["person_id"])
                try:
                    scores = json.loads(row["scores_json"] or "{}")
                except Exception:
                    scores = {}
                if not isinstance(scores, dict):
                    continue
                rel_health_raw = scores.get("relationship_health_score")
                try:
                    rel_health_score = _clamp(float(rel_health_raw)) if rel_health_raw is not None else None
                except (TypeError, ValueError):
                    rel_health_score = None
                if rel_health_score is None:
                    continue
                payload: dict[str, Any] = {
                    "relationship_health_score": rel_health_score,
                    "generated_at": row["created_at"],
                }
                commercial_raw = scores.get("commercial_priority_score")
                execution_raw = scores.get("execution_pressure_score")
                try:
                    if commercial_raw is not None:
                        payload["commercial_priority_score"] = _clamp(float(commercial_raw))
                except (TypeError, ValueError):
                    pass
                try:
                    if execution_raw is not None:
                        payload["execution_pressure_score"] = _clamp(float(execution_raw))
                except (TypeError, ValueError):
                    pass
                result[person_id] = payload
    return result


async def _load_relationship_stage_context(person_id: str) -> dict[str, Any]:
    return (await _load_relationship_stage_context_map([person_id])).get(str(person_id), {})


async def _load_network_rows(person_id: str | None = None) -> list[dict[str, Any]]:
    async with get_db() as db:
        async with db.execute(
            """
            WITH interaction_ranked AS (
                SELECT
                    i.person_id,
                    i.interaction_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY i.person_id
                        ORDER BY datetime(i.interaction_at) DESC, i.interaction_id DESC
                    ) AS rn
                FROM INTERACTION i
                WHERE COALESCE(i.channel, '') != 'system_audit'
            ),
            interaction_rollup AS (
                SELECT
                    person_id,
                    MAX(CASE WHEN rn = 1 THEN interaction_at END) AS last_interaction_at,
                    MAX(CASE WHEN rn = 2 THEN interaction_at END) AS previous_interaction_at,
                    COUNT(*) AS interaction_count
                FROM interaction_ranked
                GROUP BY person_id
            ),
            open_tasks AS (
                SELECT
                    t.person_id,
                    COUNT(*) AS open_task_count,
                    SUM(CASE WHEN t.due_date IS NOT NULL AND TRIM(t.due_date) <> '' THEN 1 ELSE 0 END) AS dated_open_task_count,
                    SUM(CASE WHEN t.due_date IS NULL OR TRIM(t.due_date) = '' THEN 1 ELSE 0 END) AS undated_open_task_count,
                    SUM(CASE WHEN t.due_date IS NOT NULL AND TRIM(t.due_date) <> '' AND date(t.due_date) < date('now') THEN 1 ELSE 0 END) AS overdue_open_task_count,
                    MIN(CASE WHEN t.due_date IS NOT NULL AND TRIM(t.due_date) <> '' THEN t.due_date END) AS earliest_open_task_due_date,
                    (
                        SELECT t2.task_text
                        FROM TASK t2
                        WHERE t2.person_id = t.person_id
                          AND t2.status IN ('open', 'in_progress')
                        ORDER BY
                          CASE WHEN t2.due_date IS NULL OR TRIM(t2.due_date) = '' THEN 1 ELSE 0 END,
                          t2.due_date ASC,
                          t2.created_at DESC
                        LIMIT 1
                    ) AS primary_open_task_text
                FROM TASK t
                WHERE t.status IN ('open', 'in_progress')
                GROUP BY t.person_id
            ),
            opportunities AS (
                SELECT
                    po.person_id,
                    COUNT(*) AS opportunity_count,
                    SUM(CASE WHEN COALESCE(po.status, 'open') = 'open' THEN 1 ELSE 0 END) AS open_opportunity_count,
                    MIN(CASE WHEN COALESCE(po.status, 'open') = 'open' AND po.trigger_date IS NOT NULL AND TRIM(po.trigger_date) <> '' THEN po.trigger_date END) AS nearest_open_trigger_date
                FROM PERSON_OPPORTUNITY po
                GROUP BY po.person_id
            ),
            company_opportunities AS (
                SELECT
                    LOWER(TRIM(company_name_raw)) AS company_key,
                    COUNT(*) AS company_opportunity_count,
                    SUM(CASE WHEN COALESCE(status, 'open') = 'open' THEN 1 ELSE 0 END) AS open_company_opportunity_count,
                    MIN(CASE WHEN COALESCE(status, 'open') = 'open' AND trigger_date IS NOT NULL AND TRIM(trigger_date) <> '' THEN trigger_date END) AS nearest_company_trigger_date
                FROM COMPANY_OPPORTUNITY
                GROUP BY LOWER(TRIM(company_name_raw))
            ),
            situations AS (
                SELECT
                    rs.person_id,
                    SUM(CASE WHEN rs.status != 'closed' THEN 1 ELSE 0 END) AS open_situation_count,
                    SUM(CASE WHEN rs.status != 'closed' AND rs.situation_type = 'opportunity' THEN 1 ELSE 0 END) AS open_opportunity_situation_count,
                    SUM(CASE WHEN rs.status != 'closed' AND rs.situation_type = 'risk' THEN 1 ELSE 0 END) AS open_risk_situation_count,
                    SUM(CASE WHEN rs.status != 'closed' AND rs.situation_type = 'market' THEN 1 ELSE 0 END) AS open_market_situation_count,
                    MAX(rs.last_interaction_at) AS last_situation_at
                FROM RELATIONSHIP_SITUATION rs
                GROUP BY rs.person_id
            ),
            meeting_health AS (
                SELECT
                    i.person_id,
                    SUM(
                        CASE
                            WHEN i.channel = 'meeting'
                              AND i.external_id LIKE 'm365-event:%'
                              AND LOWER(COALESCE(i.meeting_quality_status, '')) = 'cancelled'
                              AND datetime(COALESCE(i.meeting_last_modified_at, i.created_at, i.interaction_at)) >= datetime('now', '-30 day')
                            THEN 1
                            ELSE 0
                        END
                    ) AS recent_cancelled_meeting_count,
                    SUM(
                        CASE
                            WHEN i.channel = 'meeting'
                              AND i.external_id LIKE 'm365-event:%'
                              AND LOWER(COALESCE(i.meeting_quality_status, '')) = 'rescheduled'
                              AND datetime(COALESCE(i.meeting_last_modified_at, i.created_at, i.interaction_at)) >= datetime('now', '-30 day')
                            THEN 1
                            ELSE 0
                        END
                    ) AS recent_rescheduled_meeting_count
                FROM INTERACTION i
                GROUP BY i.person_id
            )
            SELECT
                p.person_id,
                p.full_name,
                p.title_current,
                p.company_name_raw,
                p.cat,
                p.env,
                p.disc,
                p.contact_value,
                p.engagement_status,
                p.profile_photo_url,
                p.meeting_status,
                p.next_meeting_date,
                p.next_meeting_topic,
                p.next_contact_due_date,
                p.network_tier,
                p.maintenance_mode,
                p.relationship_owner,
                p.decision_role,
                p.influence_scope,
                p.strategic_value_score,
                p.influence_score,
                p.future_option_score,
                p.coverage_risk_score,
                p.opportunity_readiness_score,
                p.relationship_confidence_score,
                p.last_meaningful_contact_at,
                p.last_inbound_at,
                p.last_outbound_at,
                p.unanswered_outbound_count,
                p.account_priority,
                p.tier_rationale,
                p.last_health_refresh_at,
                p.is_ts_advisory_candidate,
                p.last_success_at,
                p.last_meeting_date,
                p.last_contact_datetime,
                ir.last_interaction_at,
                ir.previous_interaction_at,
                COALESCE(ir.interaction_count, 0) AS interaction_count,
                COALESCE(ot.open_task_count, 0) AS open_task_count,
                COALESCE(ot.dated_open_task_count, 0) AS dated_open_task_count,
                COALESCE(ot.undated_open_task_count, 0) AS undated_open_task_count,
                COALESCE(ot.overdue_open_task_count, 0) AS overdue_open_task_count,
                ot.earliest_open_task_due_date,
                ot.primary_open_task_text,
                COALESCE(op.opportunity_count, 0) AS opportunity_count,
                COALESCE(op.open_opportunity_count, 0) AS open_opportunity_count,
                op.nearest_open_trigger_date,
                COALESCE(co.company_opportunity_count, 0) AS company_opportunity_count,
                COALESCE(co.open_company_opportunity_count, 0) AS open_company_opportunity_count,
                co.nearest_company_trigger_date,
                COALESCE(rs.open_situation_count, 0) AS open_situation_count,
                COALESCE(rs.open_opportunity_situation_count, 0) AS open_opportunity_situation_count,
                COALESCE(rs.open_risk_situation_count, 0) AS open_risk_situation_count,
                COALESCE(rs.open_market_situation_count, 0) AS open_market_situation_count,
                rs.last_situation_at,
                COALESCE(mh.recent_cancelled_meeting_count, 0) AS recent_cancelled_meeting_count,
                COALESCE(mh.recent_rescheduled_meeting_count, 0) AS recent_rescheduled_meeting_count
            FROM PERSON p
            LEFT JOIN interaction_rollup ir ON ir.person_id = p.person_id
            LEFT JOIN open_tasks ot ON ot.person_id = p.person_id
            LEFT JOIN opportunities op ON op.person_id = p.person_id
            LEFT JOIN company_opportunities co ON co.company_key = LOWER(TRIM(p.company_name_raw))
            LEFT JOIN situations rs ON rs.person_id = p.person_id
            LEFT JOIN meeting_health mh ON mh.person_id = p.person_id
            WHERE p.is_active = 1
              AND (? IS NULL OR p.person_id = ?)
            ORDER BY COALESCE(p.next_contact_due_date, p.next_meeting_date, ir.last_interaction_at, p.last_updated_at) DESC
            """,
            (person_id, person_id),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]


def _enrich_network_row(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    categories = _parse_categories(row.get("cat"))
    row["contact_value"] = _normalize_contact_value(row.get("contact_value"))
    row["cadence_days"] = _expected_cadence_days(row)
    row["recency_days"] = _compute_recency_days(row, now)
    row.update(_build_cover_analysis(row, now))
    row["has_future_cover"] = _has_future_cover(row, now)
    row["has_task_pressure"] = _task_pressure(row, now)
    row["has_meeting_churn"] = _meeting_churn(row)
    row["is_recently_reactivated"] = _is_recently_reactivated(row, now)
    row["trigger_due_soon"] = _trigger_due_soon(row, now)
    row["has_relationship_signal"] = row["recency_days"] is not None
    row["is_high_priority"] = bool(categories & HIGH_PRIORITY_CATEGORIES)
    effective_tier, tier_reason_trace = _infer_effective_tier(row)
    row["effective_network_tier"] = effective_tier
    row["effective_network_tier_label"] = TIER_LABELS.get(effective_tier, effective_tier)
    row["tier_reason_trace"] = tier_reason_trace
    row.update(_compute_network_scores(row))
    row["score_band"] = _score_band(int(row.get("network_health_score") or 0))
    return row

def _assign_queue_reason(row: dict[str, Any], queue_key: str) -> None:
    row["queue_reason"] = ""
    if queue_key == "act_now":
        if row.get("follow_up_confirmation_needed"):
            row["queue_reason"] = str(row.get("follow_up_confirmation_reason") or "Scheduled follow-up needs an update")
        elif int(row.get("recent_cancelled_meeting_count") or 0) > 0 and not row.get("has_future_cover"):
            row["queue_reason"] = "Recent meeting cancellation left this relationship uncovered"
        elif int(row.get("recent_rescheduled_meeting_count") or 0) > 0 and not row.get("has_future_cover"):
            row["queue_reason"] = "Recent meeting reschedule means the next step needs confirming"
        elif str(row.get("meeting_status") or "").lower() == "overdue":
            row["queue_reason"] = "Overdue relationship coverage"
        elif row["has_task_pressure"]:
            row["queue_reason"] = "Open task needs attention"
        elif row["trigger_due_soon"]:
            row["queue_reason"] = "Opportunity trigger date is approaching"
        elif int(row.get("open_opportunity_count") or 0) > 0:
            row["queue_reason"] = "Active opportunity requires active management"
        elif row["is_high_priority"] and not row["has_future_cover"]:
            row["queue_reason"] = "Priority contact without a next step"
        elif row["is_recently_reactivated"]:
            row["queue_reason"] = "Recently reactivated relationship"
        else:
            row["queue_reason"] = "Cadence exceeded without future cover"
    elif queue_key == "maintain":
        row["queue_reason"] = "Strategic relationship needs regular maintenance"
    elif queue_key == "preserve":
        row["queue_reason"] = "Keep this relationship warm for future optionality"
    else:
        row["queue_reason"] = "Monitor for triggers and resurface when relevant"


async def get_network_contact_context(person_id: str) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    rows = await _load_network_rows(person_id)
    if not rows:
        return None
    stage_context_map = await _load_relationship_stage_context_map([person_id])
    relationship_score_map = await _load_relationship_score_context_map([person_id])
    if not settings.LEGACY_SCORING_ENABLED:
        row = _legacy_scoring_disabled_row(
            rows[0],
            relationship_score_context=relationship_score_map.get(str(person_id), {}),
        )
    else:
        row = _enrich_network_row(rows[0], now)
        queue_key = _classify_contact(row, now)
        _assign_queue_reason(row, queue_key)
        row["queue_key"] = queue_key
    stage_context = stage_context_map.get(person_id) or {}
    if stage_context:
        row.update(stage_context)
    return row


async def build_network_feed() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = await _load_network_rows()
    person_ids = [str(row.get("person_id") or "") for row in rows]
    stage_context_map = await _load_relationship_stage_context_map(person_ids)
    relationship_score_map = await _load_relationship_score_context_map(person_ids)
    if not settings.LEGACY_SCORING_ENABLED:
        monitor = [
            _legacy_scoring_disabled_row(
                row,
                relationship_score_context=relationship_score_map.get(str(row.get("person_id") or ""), {}),
            )
            for row in rows
        ]
        for item in monitor:
            stage_context = stage_context_map.get(str(item.get("person_id") or ""))
            if stage_context:
                item.update(stage_context)
        payload = {
            "act_now": [],
            "maintain": [],
            "preserve": [],
            "monitor": monitor,
            "overlays": {
                "no_next_step": [],
                "no_relationship_signal": [],
                "recently_reactivated": [],
                "open_task_pressure": [],
                "follow_up_confirmation": [],
                "meeting_churn": [],
            },
            "summary": {
                "act_now_count": 0,
                "maintain_count": 0,
                "preserve_count": 0,
                "monitor_count": len(monitor),
                "no_next_step_count": 0,
                "no_relationship_signal_count": 0,
                "recently_reactivated_count": 0,
                "open_task_pressure_count": 0,
                "follow_up_confirmation_count": 0,
                "meeting_churn_count": 0,
                "invisible_count": 0,
            },
            "overdue": [],
            "soon": [],
            "on_track": [],
            "not_scheduled": monitor,
        }
        return payload

    queues = {
        "act_now": [],
        "maintain": [],
        "preserve": [],
        "monitor": [],
    }
    overlays = {
        "no_next_step": [],
        "no_relationship_signal": [],
        "recently_reactivated": [],
        "open_task_pressure": [],
        "follow_up_confirmation": [],
        "meeting_churn": [],
    }

    for row in rows:
        row = _enrich_network_row(row, now)
        stage_context = stage_context_map.get(str(row.get("person_id") or ""))
        if stage_context:
            row.update(stage_context)

        if not row["has_future_cover"]:
            overlays["no_next_step"].append(row)
        if not row["has_relationship_signal"]:
            overlays["no_relationship_signal"].append(row)
        if row["is_recently_reactivated"]:
            overlays["recently_reactivated"].append(row)
        if row["has_task_pressure"]:
            overlays["open_task_pressure"].append(row)
        if row.get("follow_up_confirmation_needed"):
            overlays["follow_up_confirmation"].append(row)
        if row.get("has_meeting_churn"):
            overlays["meeting_churn"].append(row)

        queue_key = _classify_contact(row, now)
        _assign_queue_reason(row, queue_key)
        queues[queue_key].append(row)

    for bucket in queues.values():
        bucket.sort(key=lambda item: _queue_rank(item, now), reverse=True)
    for bucket in overlays.values():
        bucket.sort(key=lambda item: _queue_rank(item, now), reverse=True)

    summary = {
        "act_now_count": len(queues["act_now"]),
        "maintain_count": len(queues["maintain"]),
        "preserve_count": len(queues["preserve"]),
        "monitor_count": len(queues["monitor"]),
        "no_next_step_count": len(overlays["no_next_step"]),
        "no_relationship_signal_count": len(overlays["no_relationship_signal"]),
        "recently_reactivated_count": len(overlays["recently_reactivated"]),
        "open_task_pressure_count": len(overlays["open_task_pressure"]),
        "follow_up_confirmation_count": len(overlays["follow_up_confirmation"]),
        "meeting_churn_count": len(overlays["meeting_churn"]),
        "invisible_count": len(
            [
                item
                for item in overlays["no_relationship_signal"]
                if not item.get("has_future_cover") and int(item.get("open_task_count") or 0) == 0
            ]
        ),
    }

    payload = {
        **queues,
        "overlays": overlays,
        "summary": summary,
        # Legacy aliases kept so old consumers do not break abruptly.
        "overdue": queues["act_now"],
        "soon": queues["maintain"],
        "on_track": queues["preserve"],
        "not_scheduled": queues["monitor"],
    }
    return payload
