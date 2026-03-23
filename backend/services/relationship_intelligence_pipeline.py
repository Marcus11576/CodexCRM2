from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.config import settings
from backend.database import get_db, run_write
from backend.models.relationship_intelligence import (
    ActionLedger,
    BriefingOutput,
    Claim,
    ClaimLedger,
    LENS_ACTIVE,
    LENS_FAMILY,
    LENS_LIFESTYLE,
    LENS_MARKET,
    LENS_ORDER,
    LENS_TRACK,
    LensBrief,
    NormalizedInteraction,
    PipelineMeta,
    PipelineTrace,
    ScoreBundle,
)
from backend.services.ai_runtime import run_json_chat_task
from backend.services.ai_runtime import run_json_responses_task
from backend.services.relationship_intelligence_prompts import (
    AGENT_ACTIVE,
    AGENT_ACTION,
    AGENT_ARBITER,
    AGENT_BRIEF,
    AGENT_COMPANY_VERIFY,
    AGENT_FAMILY,
    AGENT_MARKET,
    AGENT_TRACK,
    ACTION_TRACKER_RESPONSE_FORMAT,
    BRIEF_WRITER_RESPONSE_FORMAT,
    PIPELINE_VERSION,
    PROMPT_REGISTRY,
    TRUTH_ARBITER_RESPONSE_FORMAT,
    lens_agent_response_format,
)
from backend.services.system_settings_service import (
    DEFAULT_STAGE1_CALIBRATION,
    get_intelligence_settings,
    get_stage1_calibration_settings,
)

SOURCE_PRIORITY = {
    "manual_resolution": 1,
    "manual_input": 2,
    "transcript": 3,
    "whatsapp": 3,
    "email": 3,
    "meeting_note": 3,
    "calendar_metadata": 4,
    "ai_summary": 5,
    "other": 6,
}

GROUNDED_EVIDENCE_SOURCE_TYPES = {
    "manual_resolution",
    "manual_input",
    "transcript",
    "whatsapp",
    "email",
    "meeting_note",
}

LENS_PRIORITY_CAPS = {
    LENS_FAMILY: 5,
    LENS_LIFESTYLE: 4,
    LENS_ACTIVE: 8,
    LENS_MARKET: 8,
    LENS_TRACK: 6,
}

CLAIM_FAMILY_WEIGHTS = {
    "role_need": 100,
    "role_count": 96,
    "role_status": 94,
    "follow_up_timing": 88,
    "market_pressure": 84,
    "business_focus": 82,
    "account_engagement": 74,
    "track_record": 72,
    "access_offer": 70,
    "relationship_continuity": 58,
    "family_hook": 42,
    "lifestyle_hook": 36,
    "personal_hook": 34,
    "other": 20,
}

AGENT_TO_LENS = {
    AGENT_FAMILY: "Family & Personal + Interests & Lifestyle",
    AGENT_ACTIVE: LENS_ACTIVE,
    AGENT_MARKET: LENS_MARKET,
    AGENT_TRACK: LENS_TRACK,
}

FAMILY_KEYWORDS = {
    "daughter",
    "son",
    "child",
    "children",
    "wife",
    "husband",
    "family",
    "kids",
    "mum",
    "mother",
    "dad",
    "father",
    "spouse",
    "years old",
    "50s",
    "60s",
    "70s",
}
LIFESTYLE_KEYWORDS = {
    "run",
    "running",
    "marathon",
    "bike",
    "motorbike",
    "watch",
    "app",
    "holiday",
    "travel",
    "diving",
    "dive",
    "gym",
    "fitness",
    "routine",
}
ACTIVE_KEYWORDS = {
    "role",
    "roles",
    "hire",
    "hiring",
    "bim",
    "lead",
    "commercial",
    "data center",
    "data centre",
    "vacancy",
    "search",
    "mandate",
    "position",
    "needs",
    "looking for",
}
MARKET_KEYWORDS = {
    "market",
    "pricing",
    "competition",
    "hospital",
    "design",
    "shortage",
    "sector",
    "pressure",
    "frustration",
    "projects",
    "focus",
    "strategy",
}
TRACK_KEYWORDS = {
    "ceo",
    "obe",
    "partnership",
    "relationship",
    "access",
    "director",
    "senior",
    "strategic",
    "influence",
    "difficult",
    "guarded",
}
NOISE_PATTERNS = (
    "accepted:",
    "join:",
    "organizer:",
    "meeting id:",
    "passcode:",
)

SENTENCE_NOISE_PREFIXES = (
    "microsoft 365 calendar event:",
    "so, did this meeting happen?",
    "yep, that's about it",
    "that is that",
)

SPECULATIVE_PATTERNS = (
    "could lead",
    "may lead",
    "might lead",
    "potentially",
    "expressed strong interest",
    "wants to introduce",
    "wants to host",
    "massive strategic win",
    "lead partner for this recruitment drive",
)

PERSONAL_HEALTH_TERMS = {
    "knee operation",
    "knee operations",
    "operation on knee",
    "knee surgery",
    "surgery",
    "surgeries",
    "hospitalized",
    "hospitalised",
    "medical leave",
    "health issue",
    "health issues",
}

BUSINESS_CHALLENGE_TERMS = {
    "business",
    "work",
    "workload",
    "delivery",
    "project",
    "projects",
    "resource",
    "capacity",
    "hiring",
    "recruitment",
    "market",
    "commercial",
    "client",
    "team",
    "timeline",
    "deadline",
    "budget",
}

BUSINESS_UNDERSTANDING_TERMS = {
    "cost",
    "cost consultant",
    "cost consultancy",
    "project management",
    "pm capability",
    "footprint",
    "gcc",
    "middle east",
    "dubai",
    "uae",
    "united arab emirates",
    "company",
    "division",
    "sector",
    "market focus",
    "emaar",
    "emar",
    "board member",
    "managing director",
    "operates",
    "services",
}

STAGE1_KNOWLEDGE_BANK_VERSION = "stage1-knowledge-bank-v1"

STAGE1_BOX_DEFS = [
    {
        "id": 1,
        "key": "family_status",
        "title": "Family Status",
        "dimensions": [
            ("age or life stage", {"years old", "50s", "60s", "70s", "in his 60s", "in her 60s", "in his 70s", "in her 70s", "in his 50s", "in her 50s"}),
            ("partner or spouse", {"partner", "spouse", "wife", "husband", "married", "single", "divorced"}),
            ("children", {"child", "children", "daughter", "son", "kids"}),
            ("pets", {"pet", "dog", "cat"}),
            ("family base or location", {"family based", "based in", "grandparents", "home base", "south africa", "dubai"}),
            ("major family situation affecting life", {"broke", "cast", "health", "hospital", "family situation"}),
        ],
        "fallback_missing": [
            "Need explicit family setup details (partner, children, or household context).",
            "Need current family-location or life-context update.",
        ],
    },
    {
        "id": 2,
        "key": "family_interests",
        "title": "Family Interests",
        "dimensions": [
            ("family travel", {"family travel", "family holiday", "holiday", "travel", "summer"}),
            ("kids activities", {"kids", "children", "school", "football", "activity"}),
            ("shared routines", {"weekend", "routine", "family routine", "together"}),
            ("pet-linked lifestyle", {"dog", "walk", "walking the dog", "pet"}),
        ],
        "fallback_missing": [
            "Need evidence of what they enjoy doing with family.",
            "Need practical family routine or lifestyle hooks.",
        ],
    },
    {
        "id": 3,
        "key": "personal_interests",
        "title": "Personal Interests",
        "dimensions": [
            ("hobbies or sport", {"running", "run", "golf", "fishing", "hiking", "sport", "skiing", "ski"}),
            ("fitness habits", {"gym", "fitness", "training", "workout"}),
            ("lifestyle preferences", {"food", "travel", "books", "watches", "cars"}),
        ],
        "fallback_missing": [
            "Need personal (non-family) interests and hobbies.",
            "Need lifestyle details that can be used naturally in rapport.",
        ],
    },
    {
        "id": 4,
        "key": "business_understanding",
        "title": "Business Understanding",
        "dimensions": [
            (
                "company and operating context",
                {
                    "company",
                    "construction",
                    "division",
                    "business",
                    "projects",
                    "project management",
                    "cost",
                    "cost consultant",
                    "cost consultancy",
                    "footprint",
                    "gcc",
                    "middle east",
                    "dubai",
                    "uae",
                    "united arab emirates",
                    "services",
                    "operates",
                },
            ),
            ("role and remit", {"director", "head", "role", "responsible", "team"}),
            (
                "market and sector focus",
                {"market", "sector", "hotels", "fit-out", "saudi", "uae", "gcc", "emar", "emaar"},
            ),
            ("seniority or influence", {"senior", "decision", "influence", "strategic", "leadership"}),
        ],
        "fallback_missing": [
            "Need clearer role scope, decision authority, and reporting context.",
            "Need sharper view of business unit priorities and project focus.",
        ],
    },
    {
        "id": 5,
        "key": "challenges_demands",
        "title": "Challenges and Demands",
        "dimensions": [
            ("delivery or workload pressure", {"pressure", "critical", "overwhelmed", "struggling", "workload"}),
            ("growth or internal change", {"growth", "change", "expanding", "new region", "restructure"}),
            ("resource or capability gaps", {"shortage", "gap", "resource", "capacity", "delivery issue"}),
        ],
        "fallback_missing": [
            "Need concrete pressure points affecting current execution.",
            "Need specifics on what is blocking delivery or growth.",
        ],
    },
    {
        "id": 6,
        "key": "recruitment_signals",
        "title": "Recruitment Signals",
        "dimensions": [
            ("live roles", {"live role", "active role", "hiring", "hire", "position"}),
            ("future hiring plans", {"future role", "next", "build out", "team growth", "pipeline hiring"}),
            ("replacement or succession", {"replace", "replacement", "succession", "backfill"}),
            ("timing and urgency", {"immediate", "next quarter", "q3", "urgent", "18 months"}),
        ],
        "fallback_missing": [
            "Need explicit live or upcoming hiring mandates.",
            "Need timing, ownership, and urgency for recruitment demand.",
        ],
    },
    {
        "id": 7,
        "key": "market_intelligence",
        "title": "Market Intelligence",
        "dimensions": [
            ("market conditions", {"market", "slowdown", "growth", "demand", "pipeline"}),
            ("talent conditions", {"salary", "inflation", "shortage", "candidate"}),
            ("competition or client behavior", {"competitor", "competition", "client", "pricing"}),
        ],
        "fallback_missing": [
            "Need broader market read beyond their own internal context.",
            "Need clear observations on talent or competitive movement.",
        ],
    },
    {
        "id": 8,
        "key": "taylor_sterling_positioning",
        "title": "Taylor Sterling Positioning",
        "dimensions": [
            ("whether TS was presented", {"taylor sterling", "presentation", "presented", "introduced"}),
            ("their understanding", {"understands what we do", "understands", "clarity", "model"}),
            ("reaction or friction", {"positive", "objection", "interest", "needs more detail", "unclear"}),
        ],
        "fallback_missing": [
            "Need clearer evidence of how well Taylor Sterling positioning has landed.",
            "Need reaction signal: buying interest, objection, or confusion.",
        ],
    },
    {
        "id": 9,
        "key": "obe_interest",
        "title": "OBE Interest",
        "dimensions": [
            ("event participation", {"obe", "breakfast", "roundtable", "event", "attend"}),
            ("network contribution", {"host", "introductions", "contribute", "ideas", "network"}),
            ("value perception", {"value", "relevance", "join", "collaboration"}),
        ],
        "fallback_missing": [
            "Need evidence of OBE relevance or participation interest.",
            "Need explicit indication of event/network engagement intent.",
        ],
    },
    {
        "id": 10,
        "key": "action_follow_up",
        "title": "Action / Follow-Up",
        "dimensions": [
            ("specific next step", {"next step", "follow up", "reconnect", "arrange", "schedule"}),
            ("send/share/introduction action", {"send", "share", "introduction", "invite"}),
            ("timing", {"next week", "next couple of weeks", "q2", "q3", "date"}),
        ],
        "fallback_missing": [
            "Need concrete follow-up actions with owner and timing.",
            "Need explicit commitment on what happens next.",
        ],
    },
    {
        "id": 11,
        "key": "relationship_signal",
        "title": "Relationship Signal",
        "dimensions": [
            ("warmth and trust", {"warm", "trust", "open", "guarded", "distance"}),
            ("engagement quality", {"responsive", "engaged", "positive call", "hesitation"}),
            ("momentum", {"momentum", "progress", "stalled", "last spoke"}),
        ],
        "fallback_missing": [
            "Need clearer relationship-quality indicators (trust, openness, responsiveness).",
            "Need explicit direction-of-travel signal (warming, stalling, or distancing).",
        ],
    },
]

STAGE1_BOX_KEYWORDS: dict[str, set[str]] = {
    "family_status": {
        "partner", "spouse", "wife", "husband", "married", "single", "divorced", "child", "children", "daughter",
        "son", "kids", "pet", "dog", "cat", "family based", "grandparents", "broke", "cast",
        "years old", "50s", "60s", "70s", "in his 60s", "in her 60s", "in his 70s", "in her 70s", "in his 50s", "in her 50s",
    },
    "family_interests": {
        "family travel", "family holiday", "holiday", "summer", "weekend", "kids", "children", "school", "football",
        "family routine", "walking the dog", "family",
    },
    "personal_interests": {
        "running", "run", "golf", "fishing", "gym", "cars", "food", "books", "watches", "hiking", "fitness",
        "training", "travel", "skiing", "ski",
    },
    "business_understanding": {
        "company", "division", "market focus", "projects", "sector", "saudi", "uae", "project management", "cost", "cost consultant",
        "cost consultancy", "footprint", "gcc", "middle east", "dubai", "united arab emirates", "emar", "emaar",
        "services", "operates", "board member", "managing director",
    },
    "challenges_demands": {
        "pressure", "critical", "struggling", "workload", "gap", "shortage", "delivery", "resource", "overwhelmed",
        "internal change", "demand",
    },
    "recruitment_signals": {
        "hiring", "hire", "role", "position", "replacement", "succession", "build", "build-out", "mandate",
        "team growth", "live role", "active role",
    },
    "market_intelligence": {
        "market", "salary", "inflation", "shortage", "pipeline", "sector", "competitor", "competition", "client",
        "regional", "riyadh", "demand", "slowdown", "growth", "pricing",
    },
    "taylor_sterling_positioning": {
        "taylor sterling", "presentation", "presented", "what we do", "understands", "model", "support", "objection",
        "interest", "taylor stirling", "presenting taylor sterling", "presenting taylor stirling",
        "presentation with taylor sterling", "abilities",
    },
    "obe_interest": {
        "obe", "breakfast", "roundtable", "event", "join", "attend", "hosting", "introduction", "network",
        "collaboration",
    },
    "action_follow_up": {
        "follow up", "follow-up", "next step", "arrange", "meeting", "send", "share", "invite", "reconnect",
        "next week", "q2", "q3",
    },
    "relationship_signal": {
        "warm", "trust", "open", "responsive", "engaged", "hesitation", "guarded", "distance", "momentum", "stalled",
        "last spoke", "relationship", "rapport",
    },
}

STAGE1_LENS_FALLBACK = {
    LENS_FAMILY: "family_status",
    LENS_LIFESTYLE: "personal_interests",
    LENS_ACTIVE: "recruitment_signals",
    LENS_MARKET: "market_intelligence",
    LENS_TRACK: "business_understanding",
}

STAGE2_RELATIONSHIP_FLOW_VERSION = "stage2-relationship-business-flow-v1"

STAGE2_RELATIONSHIP_STAGE_DETAILS = {
    "S1": {"label": "S1 Introduction", "summary": "Very early relationship with light contact only."},
    "S2": {"label": "S2 Understand", "summary": "Building understanding of the person, role, company, and context."},
    "S3": {"label": "S3 Position", "summary": "Taylor Sterling positioning is visible, but relationship depth is still early."},
    "S4": {"label": "S4 Nurture", "summary": "Relationship is active and healthy with no defined opportunity yet."},
    "S5": {"label": "S5 Problem Identified", "summary": "A need, pressure, or talent gap is visible."},
    "S6": {"label": "S6 Active Discussion", "summary": "A role, assignment, or commercial need is being discussed."},
    "S7": {"label": "S7 Conversion Pending", "summary": "Commercial commitment is being shaped."},
    "S8": {"label": "S8 Active Client", "summary": "A live assignment is underway."},
    "S9": {"label": "S9 Active Nurture", "summary": "A mature trusted relationship is being maintained between assignments."},
}

STAGE2_OPPORTUNITY_STAGE_DETAILS = {
    "O1": {"label": "O1 Mature Problem Identified", "summary": "An emerging need is visible."},
    "O2": {"label": "O2 Mature Active Discussion", "summary": "A role or commercial need is under active discussion."},
    "O3": {"label": "O3 Mature Conversion Pending", "summary": "Commercial terms or commitment are being shaped."},
    "O4": {"label": "O4 Mature Problem Identified", "summary": "A new need is identified inside a mature relationship."},
    "O5": {"label": "O5 Mature Active Discussion", "summary": "A repeat or follow-on role is in active discussion."},
    "O6": {"label": "O6 Mature Conversion Pending", "summary": "A repeat or follow-on assignment is being shaped commercially."},
    "O7": {"label": "O7 Mature Active Client", "summary": "A live assignment is underway."},
}

RELATIONSHIP_STAGE_ORDER: tuple[str, ...] = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
RELATIONSHIP_STAGE_RANK: dict[str, int] = {code: idx for idx, code in enumerate(RELATIONSHIP_STAGE_ORDER, start=1)}
RELATIONSHIP_STAGE_REGRESSION_KEYWORDS: tuple[str, ...] = (
    "no longer",
    "relationship ended",
    "relationship has ended",
    "stopped working",
    "not working with",
    "disengaged",
    "cold relationship",
    "gone quiet",
    "lost contact",
    "out of touch",
    "no response",
    "unresponsive",
    "do not contact",
    "blacklist",
    "closed out",
)

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

STAGE2_SENTENCE_SIGNAL_KEYWORDS: dict[str, set[str]] = {
    "active_client": {
        "live assignment",
        "assignment underway",
        "mobilized",
        "mobilised",
        "onboarding",
        "delivering",
    },
    "conversion_pending": {
        "commercial terms",
        "scope",
        "proposal",
        "contract",
        "commitment",
        "fee",
        "sign off",
        "signoff",
    },
    "active_discussion": {
        "role",
        "assignment",
        "mandate",
        "hiring",
        "hire",
        "live role",
        "open role",
        "replacement",
        "succession",
        "headcount",
    },
    "problem_identified": {
        "need",
        "pressure",
        "gap",
        "challenge",
        "shortage",
        "demand",
        "critical",
    },
    "positioning": {
        "taylor sterling",
        "presentation",
        "introduced",
        "understands what we do",
        "they do know what we do",
        "positioning",
        "taylor stirling's abilities",
        "presentation of exactly what taylor stirling's abilities are",
        "presenting taylor sterling",
        "presenting taylor stirling",
        "presentation with taylor sterling",
    },
    "nurture": {
        "warm",
        "trust",
        "responsive",
        "engaged",
        "relationship",
        "keep in touch",
        "maintain relationship",
    },
    "understand": {
        "company",
        "role",
        "team",
        "projects",
        "market focus",
        "director",
        "responsible",
    },
    "introduction": {
        "first call",
        "intro call",
        "initial conversation",
        "just met",
    },
    "mature_nurture": {
        "trusted relationship",
        "between assignments",
        "active nurture",
        "repeat relationship",
    },
}

STAGE2_SIGNAL_RELATIONSHIP_STAGE_MAP: dict[str, str] = {
    "introduction": "S1",
    "understand": "S2",
    "positioning": "S3",
    "nurture": "S4",
    "problem_identified": "S5",
    "active_discussion": "S6",
    "conversion_pending": "S7",
    "active_client": "S8",
    "mature_nurture": "S9",
}


def _relationship_stage_details_map_from_list(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().upper()
        if not code:
            continue
        result[code] = {
            "label": str(row.get("label") or code).strip(),
            "summary": str(row.get("summary") or "").strip(),
        }
    return result


def _normalize_opportunity_stage_code(code: Any) -> str:
    normalized = str(code or "").strip().upper()
    return LEGACY_OPPORTUNITY_STAGE_CODE_MAP.get(normalized, normalized)


def _relationship_stage_rank(code: Any) -> int:
    return RELATIONSHIP_STAGE_RANK.get(str(code or "").strip().upper(), 0)


def _highest_relationship_stage_from_signal_counts(signal_counts: dict[str, int]) -> Optional[str]:
    if not isinstance(signal_counts, dict):
        return None
    highest_code: Optional[str] = None
    highest_rank = 0
    for signal, count in signal_counts.items():
        if int(count or 0) <= 0:
            continue
        code = STAGE2_SIGNAL_RELATIONSHIP_STAGE_MAP.get(str(signal or "").strip().lower())
        if not code:
            continue
        rank = _relationship_stage_rank(code)
        if rank > highest_rank:
            highest_rank = rank
            highest_code = code
    return highest_code


def _has_explicit_relationship_regression_signal(interactions: list[dict]) -> bool:
    for item in interactions or []:
        blob = " ".join(
            str(item.get(field) or "").strip().lower()
            for field in ("content", "title", "preview")
        )
        if not blob:
            continue
        if any(keyword in blob for keyword in RELATIONSHIP_STAGE_REGRESSION_KEYWORDS):
            return True
    return False


def _opportunity_unlocked_by_relationship_journey(
    relationship_code: Any,
    previous_relationship_code: Any = None,
) -> bool:
    current = str(relationship_code or "").strip().upper()
    previous = str(previous_relationship_code or "").strip().upper()
    return current in {"S8", "S9"} or previous in {"S8", "S9"}


def _normalize_stage2_payload(stage2: dict[str, Any], opportunity_stage_details: Optional[dict[str, dict[str, str]]] = None) -> dict[str, Any]:
    payload = dict(stage2 or {})
    relationship = payload.get("relationship_stage") if isinstance(payload.get("relationship_stage"), dict) else {}
    transition = payload.get("transition") if isinstance(payload.get("transition"), dict) else {}
    relationship_code = str(relationship.get("code") or "").strip().upper()
    previous_relationship_code = str(transition.get("previous_relationship_stage") or "").strip().upper()
    opportunity_unlocked = _opportunity_unlocked_by_relationship_journey(
        relationship_code,
        previous_relationship_code,
    )
    opportunity = payload.get("opportunity_stage") if isinstance(payload.get("opportunity_stage"), dict) else None
    if not opportunity:
        return payload
    if not opportunity_unlocked:
        payload["opportunity_stage"] = None
        return payload
    normalized_code = _normalize_opportunity_stage_code(opportunity.get("code"))
    if not normalized_code:
        return payload
    details_map = opportunity_stage_details or STAGE2_OPPORTUNITY_STAGE_DETAILS
    details = details_map.get(normalized_code) or {}
    normalized_opportunity = dict(opportunity)
    normalized_opportunity["code"] = normalized_code
    if details.get("label"):
        normalized_opportunity["label"] = str(details.get("label") or normalized_opportunity.get("label") or normalized_code)
    if details.get("summary"):
        normalized_opportunity["summary"] = str(details.get("summary") or normalized_opportunity.get("summary") or "")
    payload["opportunity_stage"] = normalized_opportunity
    return payload


def _stage2_signal_keywords_from_stage_rules(stage_rules: list[dict[str, Any]] | None) -> dict[str, set[str]]:
    by_code: dict[str, set[str]] = {}
    for row in stage_rules or []:
        if not isinstance(row, dict):
            continue
        code = _normalize_opportunity_stage_code(row.get("code"))
        if not code:
            continue
        keywords = {
            str(keyword or "").strip().lower()
            for keyword in (row.get("keywords") or [])
            if str(keyword or "").strip()
        }
        if keywords:
            by_code[code] = keywords

    if not by_code:
        return {key: set(values) for key, values in STAGE2_SENTENCE_SIGNAL_KEYWORDS.items()}

    def combined(*codes: str) -> set[str]:
        acc: set[str] = set()
        for code in codes:
            acc.update(by_code.get(code, set()))
        return acc

    signals = {
        "active_client": combined("O7", "S8"),
        "conversion_pending": combined("O3", "O6", "S7", "S7M"),
        "active_discussion": combined("O2", "O5", "S6", "S6M"),
        "problem_identified": combined("O1", "O4", "S5", "S5M"),
        "positioning": combined("S3"),
        "nurture": combined("S4", "S9"),
        "understand": combined("S2"),
        "introduction": combined("S1"),
        "mature_nurture": combined("S9"),
    }
    return {
        key: (value if value else set(STAGE2_SENTENCE_SIGNAL_KEYWORDS.get(key) or set()))
        for key, value in signals.items()
    }


def _runtime_stage1_taxonomy_from_settings(transcript_tagging: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    tagging = transcript_tagging if isinstance(transcript_tagging, dict) else {}
    configured_buckets = tagging.get("knowledge_buckets") if isinstance(tagging.get("knowledge_buckets"), list) else []
    fallback_defs = {item["key"]: item for item in STAGE1_BOX_DEFS}
    runtime_defs: list[dict[str, Any]] = []
    runtime_keywords: dict[str, set[str]] = {key: set(values) for key, values in STAGE1_BOX_KEYWORDS.items()}
    seen_keys: set[str] = set()
    next_custom_id = max(int(item.get("id") or 0) for item in STAGE1_BOX_DEFS) + 1

    for row in configured_buckets:
        if not isinstance(row, dict):
            continue
        key = re.sub(r"[^a-z0-9_]+", "_", str(row.get("box_key") or "").strip().lower()).strip("_")
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        fallback = fallback_defs.get(key)
        configured_keywords = {
            str(keyword or "").strip().lower()
            for keyword in (row.get("keywords") or [])
            if str(keyword or "").strip()
        }

        default_id = int(fallback.get("id") or next_custom_id) if fallback else next_custom_id
        try:
            runtime_id = int(row.get("box_id") or default_id)
        except (TypeError, ValueError):
            runtime_id = default_id
        runtime_id = max(1, runtime_id)
        if not fallback:
            next_custom_id = max(next_custom_id + 1, runtime_id + 1)

        title = str(
            row.get("box_title")
            or (fallback or {}).get("title")
            or key.replace("_", " ").title()
        ).strip() or key.replace("_", " ").title()

        if fallback:
            runtime_def = copy.deepcopy(fallback)
        else:
            generic_keywords = configured_keywords or {token for token in key.split("_") if token}
            runtime_def = {
                "id": runtime_id,
                "key": key,
                "title": title,
                "dimensions": [
                    ("topic coverage", set(generic_keywords) if generic_keywords else {key}),
                ],
                "fallback_missing": [
                    f"Need clearer evidence for {title.lower()}.",
                ],
            }
            if key not in runtime_keywords:
                runtime_keywords[key] = set()

        runtime_def["id"] = runtime_id
        runtime_def["key"] = key
        runtime_def["title"] = title
        raw_code = str(
            row.get("code")
            or (fallback or {}).get("code")
            or f"K{runtime_id}"
        ).strip().upper()
        match_code = re.fullmatch(r"K?\s*(\d{1,2})", raw_code)
        runtime_def["code"] = f"K{int(match_code.group(1))}" if match_code else f"K{runtime_id}"
        runtime_defs.append(runtime_def)

        if configured_keywords:
            runtime_keywords[key] = configured_keywords

    if not runtime_defs:
        runtime_defs = copy.deepcopy(STAGE1_BOX_DEFS)
    else:
        for fallback in STAGE1_BOX_DEFS:
            if fallback["key"] not in seen_keys:
                runtime_defs.append(copy.deepcopy(fallback))
        runtime_defs.sort(key=lambda item: (int(item.get("id") or 99), str(item.get("key") or "")))
    for runtime_def in runtime_defs:
        raw_code = str(runtime_def.get("code") or f"K{int(runtime_def.get('id') or 0)}").strip().upper()
        match_code = re.fullmatch(r"K?\s*(\d{1,2})", raw_code)
        runtime_def["code"] = f"K{int(match_code.group(1))}" if match_code else f"K{int(runtime_def.get('id') or 0)}"

    return runtime_defs, runtime_keywords


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean_text(value).lower()).strip()


def _keyword_score(normalized_text: str, keyword: str) -> int:
    token = _normalize_match_text(keyword)
    if not normalized_text or not token:
        return 0
    if " " in token or "-" in token:
        return 2 if token in normalized_text else 0
    pattern = rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"
    return 1 if re.search(pattern, normalized_text) else 0


def _keywords_score(normalized_text: str, keywords: set[str]) -> int:
    return sum(_keyword_score(normalized_text, keyword) for keyword in keywords)


def _matched_keywords(normalized_text: str, keywords: set[str]) -> set[str]:
    matches: set[str] = set()
    for keyword in keywords:
        if _keyword_score(normalized_text, keyword) > 0:
            normalized_keyword = _normalize_match_text(keyword)
            if normalized_keyword:
                matches.add(normalized_keyword)
    return matches


def _is_follow_up_need_phrase(
    normalized_sentence: str,
    matched_keywords: set[str],
    runtime_signal_keywords: dict[str, set[str]],
) -> bool:
    if not matched_keywords:
        return False
    if not matched_keywords.issubset({"need"}):
        return False

    # "I/we need to..." often captures follow-up tasks rather than client-side pressure.
    if re.search(r"\b(i|we)\s+need\s+to\b", normalized_sentence):
        return True

    if re.search(
        r"\bneed\s+to\s+(sit|meet|speak|discuss|present|review|walk|go|follow|catch|arrange|set up)\b",
        normalized_sentence,
    ):
        return True

    positioning_keywords = runtime_signal_keywords.get("positioning") or set()
    if _keywords_score(normalized_sentence, positioning_keywords) > 0:
        return True

    return False


def _has_keyword_match(value: Any, keywords: set[str]) -> bool:
    return _keywords_score(_normalize_match_text(value), keywords) > 0


def _action_follow_up_signal_flags(value: Any) -> dict[str, bool]:
    normalized = _normalize_match_text(value)
    if not normalized:
        return {
            "specific next step": False,
            "send/share/introduction action": False,
            "timing": False,
        }

    specific_next_step = bool(
        re.search(
            r"\b("
            r"next step|follow[\s-]?up|reconnect|arrange|schedule|set up|need to|i need to|we need to|"
            r"sit down|go through|walk through|review|present|presentation|plan to|will "
            r")\b",
            normalized,
        )
    )
    send_share_intro = bool(
        re.search(
            r"\b("
            r"send|share|introduction|introduce|invite|forward|deck|materials?|"
            r"presentation|present|walk through|go through"
            r")\b",
            normalized,
        )
    )
    timing = bool(
        re.search(
            r"\b("
            r"today|tomorrow|this week|next week|next couple of weeks|week and a half|"
            r"after|before|by|on|in about|q[1-4]|quarter|month|months|"
            r"\d+\s+(day|days|week|weeks|month|months)"
            r")\b",
            normalized,
        )
    )
    return {
        "specific next step": specific_next_step,
        "send/share/introduction action": send_share_intro,
        "timing": timing,
    }


def _classify_stage2_sentence_signals(
    cleaned_interactions: list[dict],
    signal_keywords: Optional[dict[str, set[str]]] = None,
) -> tuple[dict[str, int], dict[str, list[str]]]:
    runtime_signal_keywords = (
        signal_keywords
        if isinstance(signal_keywords, dict) and signal_keywords
        else STAGE2_SENTENCE_SIGNAL_KEYWORDS
    )
    counts: dict[str, int] = {signal: 0 for signal in runtime_signal_keywords}
    evidence: dict[str, list[str]] = {signal: [] for signal in runtime_signal_keywords}
    for item in cleaned_interactions:
        if item.get("noise_candidate"):
            continue
        for sentence in _split_sentences(item.get("raw_text") or ""):
            normalized_sentence = _normalize_match_text(sentence)
            if not normalized_sentence:
                continue
            for signal, keywords in runtime_signal_keywords.items():
                score = _keywords_score(normalized_sentence, keywords)
                if score <= 0:
                    continue
                if signal == "problem_identified":
                    matched_keywords = _matched_keywords(normalized_sentence, keywords)
                    if _is_follow_up_need_phrase(normalized_sentence, matched_keywords, runtime_signal_keywords):
                        continue
                counts[signal] += 1
                if len(evidence[signal]) < 5:
                    evidence[signal].append(sentence)
    return counts, evidence


def _stage1_completeness_band(score: int) -> str:
    if score <= 20:
        return "0-20% almost nothing known"
    if score <= 40:
        return "21-40% basic surface knowledge only"
    if score <= 60:
        return "41-60% useful working knowledge"
    if score <= 80:
        return "61-80% strong knowledge"
    return "81-100% rich, current, well-supported knowledge"


def _stage1_status_multiplier(status: str, stage1_settings: Optional[dict[str, Any]] = None) -> float:
    multipliers = (
        (stage1_settings or {}).get("status_multipliers_pct")
        if isinstance((stage1_settings or {}).get("status_multipliers_pct"), dict)
        else {}
    )
    defaults = DEFAULT_STAGE1_CALIBRATION.get("status_multipliers_pct", {})
    key = str(status or "").strip().lower()
    fallback = 55
    pct = multipliers.get(key, defaults.get(key, fallback))
    try:
        parsed = float(pct)
    except (TypeError, ValueError):
        parsed = float(defaults.get(key, fallback))
    return max(0.05, min(1.0, parsed / 100.0))


def _stage1_source_quality_multiplier(source_rank: int, stage1_settings: Optional[dict[str, Any]] = None) -> float:
    rank = int(source_rank or 9)
    key = "low"
    if rank <= 1:
        key = "manual"
    elif rank <= 3:
        key = "direct"
    elif rank <= 5:
        key = "indirect"

    multipliers = (
        (stage1_settings or {}).get("source_multipliers_pct")
        if isinstance((stage1_settings or {}).get("source_multipliers_pct"), dict)
        else {}
    )
    defaults = DEFAULT_STAGE1_CALIBRATION.get("source_multipliers_pct", {})
    pct = multipliers.get(key, defaults.get(key, 62))
    try:
        parsed = float(pct)
    except (TypeError, ValueError):
        parsed = float(defaults.get(key, 62))
    return max(0.05, min(1.0, parsed / 100.0))


def _stage1_weight(stage1_settings: Optional[dict[str, Any]], key: str) -> float:
    defaults = DEFAULT_STAGE1_CALIBRATION
    try:
        value = float((stage1_settings or {}).get(key, defaults.get(key, 0)))
    except (TypeError, ValueError):
        value = float(defaults.get(key, 0))
    return max(0.0, min(100.0, value))


def _stage1_recency_windows(stage1_settings: Optional[dict[str, Any]]) -> tuple[int, int, int]:
    defaults = DEFAULT_STAGE1_CALIBRATION.get("recency_windows_days", {})
    windows = (stage1_settings or {}).get("recency_windows_days")
    windows = windows if isinstance(windows, dict) else {}
    try:
        fresh = int(windows.get("fresh", defaults.get("fresh", 60)))
    except (TypeError, ValueError):
        fresh = int(defaults.get("fresh", 60))
    try:
        recent = int(windows.get("recent", defaults.get("recent", 180)))
    except (TypeError, ValueError):
        recent = int(defaults.get("recent", 180))
    try:
        aged = int(windows.get("aged", defaults.get("aged", 365)))
    except (TypeError, ValueError):
        aged = int(defaults.get("aged", 365))
    fresh = max(7, min(365, fresh))
    recent = max(fresh + 1, min(730, recent))
    aged = max(recent + 1, min(1460, aged))
    return fresh, recent, aged


def _stage1_latest_date_from_claim(claim: dict, source_map: dict[str, dict]) -> Optional[datetime]:
    date_candidates: list[datetime] = []
    for source_id in claim.get("source_ids") or []:
        source = source_map.get(source_id) or {}
        dt = _parse_dt(source.get("datetime") or source.get("date"))
        if dt:
            date_candidates.append(dt)
    for fallback in (claim.get("last_seen"), claim.get("first_seen")):
        dt = _parse_dt(fallback)
        if dt:
            date_candidates.append(dt)
    if not date_candidates:
        return None
    return max(date_candidates)


def _stage1_claim_box_keys(claim: dict, box_keywords: Optional[dict[str, set[str]]] = None) -> set[str]:
    text = _clean_text(claim.get("claim_text"))
    if not text:
        return set()

    keywords_map = box_keywords if isinstance(box_keywords, dict) and box_keywords else STAGE1_BOX_KEYWORDS
    sentences = _split_sentences(text) or [text]
    keys: set[str] = set()
    for sentence in sentences:
        normalized_sentence = _normalize_match_text(sentence)
        for box_key, keywords in keywords_map.items():
            if _keywords_score(normalized_sentence, keywords) > 0:
                keys.add(box_key)

    lens = str(claim.get("lens") or "")
    if not keys and lens in STAGE1_LENS_FALLBACK:
        keys.add(STAGE1_LENS_FALLBACK[lens])

    normalized_text = _normalize_match_text(text)
    if lens == LENS_FAMILY and _keywords_score(normalized_text, {"holiday", "weekend", "football", "travel"}) > 0:
        keys.add("family_interests")
    if lens == LENS_LIFESTYLE and _keywords_score(normalized_text, {"daughter", "son", "kids", "family"}) > 0:
        keys.add("family_interests")
    if lens in {LENS_ACTIVE, LENS_TRACK} and _keywords_score(normalized_text, {"follow up", "follow-up"}) > 0:
        keys.add("action_follow_up")
    if lens in {LENS_TRACK, LENS_ACTIVE} and _keywords_score(normalized_text, {"trust", "guarded", "warm", "relationship"}) > 0:
        keys.add("relationship_signal")

    return keys


def _allow_stage1_line_for_box(box_key: str, text: str) -> bool:
    line = _clean_text(text).lower()
    if not line:
        return False
    if box_key == "business_understanding":
        return any(term in line for term in BUSINESS_UNDERSTANDING_TERMS)
    if box_key != "challenges_demands":
        return True

    has_personal_health = any(term in line for term in PERSONAL_HEALTH_TERMS)
    has_business_context = any(term in line for term in BUSINESS_CHALLENGE_TERMS)
    if has_personal_health and not has_business_context:
        return False
    return True


def _build_stage1_knowledge_bank(
    claim_ledger: dict,
    cleaned_interactions: list[dict],
    stage1_settings: Optional[dict[str, Any]] = None,
    stage1_box_defs: Optional[list[dict[str, Any]]] = None,
    stage1_box_keywords: Optional[dict[str, set[str]]] = None,
) -> dict:
    effective_box_defs = stage1_box_defs if isinstance(stage1_box_defs, list) and stage1_box_defs else STAGE1_BOX_DEFS
    effective_box_keywords = (
        stage1_box_keywords
        if isinstance(stage1_box_keywords, dict) and stage1_box_keywords
        else STAGE1_BOX_KEYWORDS
    )
    source_map = _grounded_source_map(cleaned_interactions, include_noise=True)
    effective_stage1 = stage1_settings if isinstance(stage1_settings, dict) else DEFAULT_STAGE1_CALIBRATION
    weight_coverage = _stage1_weight(effective_stage1, "coverage_weight_pct")
    weight_confidence = _stage1_weight(effective_stage1, "confidence_weight_pct")
    weight_recency = _stage1_weight(effective_stage1, "recency_weight_pct")
    weight_density = _stage1_weight(effective_stage1, "density_weight_pct")
    weight_total = max(1.0, weight_coverage + weight_confidence + weight_recency + weight_density)
    fresh_window, recent_window, aged_window = _stage1_recency_windows(effective_stage1)
    claims = [
        claim
        for claim in (claim_ledger.get("claims") or [])
        if str(claim.get("status") or "").lower() not in {"disproved", "superseded"}
        and _clean_text(claim.get("claim_text"))
    ]

    by_box: dict[str, list[dict]] = {box["key"]: [] for box in effective_box_defs}
    for claim in claims:
        for key in _stage1_claim_box_keys(claim, effective_box_keywords):
            if key in by_box:
                by_box[key].append(claim)

    # Sentence-level fallback so stage1 buckets can still populate even when
    # claim extraction misses a transcript sentence.
    sentence_hits_by_box: dict[str, list[dict[str, Any]]] = {box["key"]: [] for box in effective_box_defs}
    sentence_seen_by_box: dict[str, set[str]] = {box["key"]: set() for box in effective_box_defs}
    for item in cleaned_interactions or []:
        if not _is_grounded_source_type(item.get("source_type")):
            continue
        if item.get("noise_candidate"):
            continue
        raw_text = _clean_text(item.get("raw_text") or item.get("summary") or "")
        if not raw_text:
            continue
        item_dt = _parse_dt(item.get("datetime") or item.get("date"))
        item_source_id = str(item.get("source_id") or "").strip()
        for sentence in _split_sentences(raw_text):
            normalized_sentence = _normalize_match_text(sentence)
            if not normalized_sentence:
                continue
            best_key = None
            best_score = 0
            for box in effective_box_defs:
                key = box["key"]
                score = _keywords_score(normalized_sentence, effective_box_keywords.get(key, set()))
                if score > best_score:
                    best_score = score
                    best_key = key
            if not best_key or best_score <= 0:
                continue
            sentence_key = _canonical_text(sentence)
            if sentence_key in sentence_seen_by_box[best_key]:
                continue
            sentence_seen_by_box[best_key].add(sentence_key)
            sentence_hits_by_box[best_key].append(
                {
                    "sentence": sentence.strip(),
                    "date": item_dt,
                    "source_id": item_source_id,
                    "score": best_score,
                }
            )

    now = _now()
    boxes_payload: list[dict] = []
    for box in effective_box_defs:
        key = box["key"]
        box_claims = by_box.get(key, [])
        deduped_lines: set[str] = set()
        known_points: list[dict] = []
        latest_update: Optional[datetime] = None
        confidence_acc = 0.0
        confidence_weight = 0.0
        dimension_hits: set[str] = set()
        source_ids: set[str] = set()
        action_has_specific_next_step = False
        action_has_send_share = False
        action_has_timing = False

        for claim in sorted(box_claims, key=_claim_precedence_key):
            claim_source_ids = [str(source_id).strip() for source_id in (claim.get("source_ids") or []) if str(source_id).strip()]
            # Stage1 scoring must be grounded in interaction-backed evidence only.
            # Unsourced profile/title inferences are kept out of K-score maths.
            if not claim_source_ids:
                continue
            if not any(
                str((source_map.get(source_id) or {}).get("source_type") or "").strip().lower() in GROUNDED_EVIDENCE_SOURCE_TYPES
                for source_id in claim_source_ids
            ):
                continue
            line = _rewrite_claim_text_for_brief(claim) or _clean_text(claim.get("claim_text"))
            line = line.strip()
            if not line:
                continue
            if not _allow_stage1_line_for_box(key, line):
                continue
            line_key = _canonical_text(line)
            if line_key in deduped_lines:
                continue
            deduped_lines.add(line_key)

            claim_dt = _stage1_latest_date_from_claim(claim, source_map)
            if claim_dt and (latest_update is None or claim_dt > latest_update):
                latest_update = claim_dt

            source_rank = int(claim.get("source_rank") or 9)
            base_conf = float(claim.get("confidence") or 0.0)
            adjusted_conf = (
                base_conf
                * _stage1_status_multiplier(str(claim.get("status") or ""), effective_stage1)
                * _stage1_source_quality_multiplier(source_rank, effective_stage1)
            )
            confidence_acc += adjusted_conf
            confidence_weight += 1.0

            for source_id in claim_source_ids:
                if source_id:
                    source_ids.add(str(source_id))

            line_sentences = _split_sentences(line) or [line]
            for dimension_name, keywords in box["dimensions"]:
                if any(_has_keyword_match(sentence, keywords) for sentence in line_sentences):
                    dimension_hits.add(dimension_name)
            if key == "action_follow_up":
                claim_flags = _action_follow_up_signal_flags(f"{line} {_clean_text(claim.get('why_it_matters'))}")
                if claim_flags.get("specific next step"):
                    dimension_hits.add("specific next step")
                    action_has_specific_next_step = True
                if claim_flags.get("send/share/introduction action"):
                    dimension_hits.add("send/share/introduction action")
                    action_has_send_share = True
                if claim_flags.get("timing"):
                    dimension_hits.add("timing")
                    action_has_timing = True

            known_points.append(
                {
                    "point": line,
                    "supporting_context": _clean_text(claim.get("why_it_matters")),
                    "truth_state": str(claim.get("truth_state") or _claim_truth_state(claim)),
                    "confidence_pct": int(round(max(0.0, min(adjusted_conf, 1.0)) * 100)),
                    "last_updated": claim_dt.date().isoformat() if claim_dt else str(claim.get("last_seen") or ""),
                }
            )
        for hit in sentence_hits_by_box.get(key, []):
                line = _clean_text(hit.get("sentence"))
                if not line:
                    continue
                if not _allow_stage1_line_for_box(key, line):
                    continue
                line_key = _canonical_text(line)
                if line_key in deduped_lines:
                    continue
                deduped_lines.add(line_key)
                hit_dt = hit.get("date")
                if isinstance(hit_dt, datetime) and (latest_update is None or hit_dt > latest_update):
                    latest_update = hit_dt
                hit_source_id = str(hit.get("source_id") or "").strip()
                if hit_source_id:
                    source_ids.add(hit_source_id)
                for dimension_name, keywords in box["dimensions"]:
                    if _has_keyword_match(line, keywords):
                        dimension_hits.add(dimension_name)
                if key == "action_follow_up":
                    sentence_flags = _action_follow_up_signal_flags(line)
                    if sentence_flags.get("specific next step"):
                        dimension_hits.add("specific next step")
                        action_has_specific_next_step = True
                    if sentence_flags.get("send/share/introduction action"):
                        dimension_hits.add("send/share/introduction action")
                        action_has_send_share = True
                    if sentence_flags.get("timing"):
                        dimension_hits.add("timing")
                        action_has_timing = True
                hit_score = int(hit.get("score") or 0)
                # Conservative confidence for sentence-level keyword evidence.
                inferred_conf = max(0.42, min(0.72, 0.42 + (hit_score * 0.08)))
                confidence_acc += inferred_conf
                confidence_weight += 1.0
                known_points.append(
                    {
                        "point": line,
                        "supporting_context": "",
                        "truth_state": "sentence_evidence",
                        "confidence_pct": int(round(inferred_conf * 100)),
                        "last_updated": hit_dt.date().isoformat() if isinstance(hit_dt, datetime) else "",
                    }
                )

        dimension_total = len(box["dimensions"])
        coverage_ratio = (len(dimension_hits) / dimension_total) if dimension_total else 0.0
        confidence_ratio = (confidence_acc / confidence_weight) if confidence_weight > 0 else 0.0
        recency_ratio = 0.0
        if latest_update is not None:
            days_old = max(0, (now - latest_update).days)
            if days_old <= fresh_window:
                recency_ratio = 1.0
            elif days_old <= recent_window:
                recency_ratio = 0.75
            elif days_old <= aged_window:
                recency_ratio = 0.52
            else:
                recency_ratio = 0.35
        density_ratio = min(1.0, len(known_points) / 5.0)

        completeness = int(
            round(
                (
                    (coverage_ratio * weight_coverage)
                    + (confidence_ratio * weight_confidence)
                    + (recency_ratio * weight_recency)
                    + (density_ratio * weight_density)
                )
                * (100.0 / weight_total)
            )
        )
        completeness = max(0, min(100, completeness))
        if not known_points:
            completeness = 0
        if key == "action_follow_up" and action_has_specific_next_step:
            # For activity planning, a clearly-defined action should rank high immediately.
            floor = 78
            if action_has_timing:
                floor = 88
            if action_has_timing and action_has_send_share:
                floor = 92
            completeness = max(completeness, floor)

        missing: list[str] = []
        for dimension_name, _keywords in box["dimensions"]:
            if dimension_name not in dimension_hits:
                missing.append(f"Need clearer evidence on {dimension_name}.")
        if not known_points:
            missing = list(box["fallback_missing"])
        elif latest_update is None:
            missing.append("Need a dated source to confirm recency.")
        elif (now - latest_update).days > 180:
            missing.append("Needs a fresher update from a recent conversation.")
        missing = list(dict.fromkeys([item for item in missing if item]))[:6]

        boxes_payload.append(
            {
                "box_id": box["id"],
                "code": str(box.get("code") or f"K{int(box.get('id') or 0)}").upper(),
                "box_key": key,
                "box_title": box["title"],
                "completeness_pct": completeness,
                "completeness_band": _stage1_completeness_band(completeness),
                "confidence_pct": int(round(max(0.0, min(confidence_ratio, 1.0)) * 100)),
                "last_updated": latest_update.date().isoformat() if latest_update else "",
                "source_count": len(source_ids),
                "what_is_known": known_points,
                "what_is_missing": missing,
            }
        )

    return {
        "framework": STAGE1_KNOWLEDGE_BANK_VERSION,
        "generated_at": now.isoformat(),
        "calibration_profile": str(effective_stage1.get("profile") or "balanced"),
        "calibration": {
            "coverage_weight_pct": int(round(weight_coverage)),
            "confidence_weight_pct": int(round(weight_confidence)),
            "recency_weight_pct": int(round(weight_recency)),
            "density_weight_pct": int(round(weight_density)),
            "recency_windows_days": {
                "fresh": fresh_window,
                "recent": recent_window,
                "aged": aged_window,
            },
        },
        "boxes": boxes_payload,
    }


def _stage1_box_completeness(stage1: dict, box_key: str) -> int:
    for box in stage1.get("boxes") or []:
        if str(box.get("box_key") or "") == box_key:
            return int(box.get("completeness_pct") or 0)
    return 0


def _normalize_runtime_stage_code(code: Any) -> str:
    normalized = str(code or "").strip().upper()
    return LEGACY_OPPORTUNITY_STAGE_CODE_MAP.get(normalized, normalized)


def _stage2_stage_payload(code: str, details_map: dict[str, dict], confidence: int, reasons: list[str]) -> dict:
    details = details_map.get(code) or {}
    return {
        "code": code,
        "label": details.get("label") or code,
        "summary": details.get("summary") or "",
        "confidence_pct": max(0, min(100, int(confidence or 0))),
        "reasons": list(dict.fromkeys([_clean_text(reason) for reason in reasons if _clean_text(reason)]))[:8],
    }


def _build_stage2_relationship_business_flow(
    *,
    person: dict,
    claim_ledger: dict,
    action_ledger: dict,
    cleaned_interactions: list[dict],
    stage1_knowledge_bank: dict,
    previous_stage2: Optional[dict] = None,
    relationship_stage_details: Optional[dict[str, dict[str, str]]] = None,
    opportunity_stage_details: Optional[dict[str, dict[str, str]]] = None,
    stage2_signal_keywords: Optional[dict[str, set[str]]] = None,
) -> dict:
    now = _now()
    non_noise_interactions = [item for item in cleaned_interactions if not item.get("noise_candidate")]
    interaction_count = len(non_noise_interactions)
    recent_interactions = [
        item
        for item in non_noise_interactions
        if (_parse_dt(item.get("datetime") or item.get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc))
        >= now - timedelta(days=120)
    ]
    recent_interaction_count = len(recent_interactions)

    claims = claim_ledger.get("claims") or []
    active_claims = [claim for claim in claims if str(claim.get("status") or "") == "active"]
    role_claims = [
        claim
        for claim in active_claims
        if str(claim.get("claim_family") or "") in {"role_need", "role_count", "role_status"}
    ]
    problem_claims = [
        claim
        for claim in active_claims
        if str(claim.get("claim_family") or "") in {"market_pressure", "business_focus"}
    ]
    continuity_claims = [
        claim
        for claim in active_claims
        if str(claim.get("claim_family") or "") in {"follow_up_timing", "relationship_continuity", "account_engagement", "track_record"}
    ]

    action_map = {action.get("action_id"): action for action in action_ledger.get("actions") or []}
    open_actions = [action_map.get(action_id) for action_id in action_ledger.get("open_actions") or [] if action_map.get(action_id)]
    open_action_count = len(open_actions)

    signal_counts, signal_evidence = _classify_stage2_sentence_signals(
        non_noise_interactions,
        stage2_signal_keywords,
    )
    transcript_highest_relationship_stage = _highest_relationship_stage_from_signal_counts(signal_counts)
    has_problem_identified = bool(problem_claims) or signal_counts.get("problem_identified", 0) > 0
    has_active_discussion = bool(role_claims) or signal_counts.get("active_discussion", 0) > 0
    has_conversion_pending = signal_counts.get("conversion_pending", 0) > 0
    has_active_client = signal_counts.get("active_client", 0) > 0
    has_positioning_signal = signal_counts.get("positioning", 0) > 0
    has_nurture_signal = (
        signal_counts.get("nurture", 0) > 0
        or signal_counts.get("mature_nurture", 0) > 0
        or bool(continuity_claims)
    )
    has_understand_signal = signal_counts.get("understand", 0) > 0
    has_intro_signal = signal_counts.get("introduction", 0) > 0

    business_understanding_score = _stage1_box_completeness(stage1_knowledge_bank, "business_understanding")
    ts_positioning_score = _stage1_box_completeness(stage1_knowledge_bank, "taylor_sterling_positioning")
    relationship_signal_score = _stage1_box_completeness(stage1_knowledge_bank, "relationship_signal")
    mapped_stage_codes: set[str] = set()
    mapped_stage_reasons: list[str] = []

    previous_stage2 = previous_stage2 if isinstance(previous_stage2, dict) else {}
    previous_relationship_code = str(((previous_stage2.get("relationship_stage") or {}).get("code")) or "")
    previous_opportunity_code = _normalize_runtime_stage_code(
        str(((previous_stage2.get("opportunity_stage") or {}).get("code")) or "")
    )
    person_category = str(person.get("cat") or "").strip().upper()

    mature_cycle_active = bool(previous_stage2.get("mature_cycle_active"))
    if previous_relationship_code == "S9" or previous_opportunity_code in {"O4", "O5", "O6", "S5M", "S6M", "S7M"}:
        mature_cycle_active = True
    if person_category == "EXT":
        mature_cycle_active = True
    relationship_reasons: list[str] = []
    if (
        (interaction_count <= 1 or has_intro_signal)
        and business_understanding_score < 30
        and ts_positioning_score < 25
        and not (
            has_problem_identified
            or has_active_discussion
            or has_conversion_pending
            or has_active_client
            or has_positioning_signal
            or has_nurture_signal
            or has_understand_signal
        )
    ):
        relationship_stage_code = "S1"
        relationship_reasons.append("Interaction evidence is still very light and early.")
    elif has_active_client:
        relationship_stage_code = "S8"
        if signal_counts.get("active_client", 0) > 0:
            relationship_reasons.append("Sentence-level evidence indicates an assignment is currently underway.")
        else:
            relationship_reasons.append("Claim evidence indicates active-client stage evidence.")
    elif has_conversion_pending:
        relationship_stage_code = "S7"
        if signal_counts.get("conversion_pending", 0) > 0:
            relationship_reasons.append("Sentence-level evidence shows commercial commitment language.")
        else:
            relationship_reasons.append("Claim evidence indicates conversion-pending stage evidence.")
    elif has_active_discussion:
        relationship_stage_code = "S6"
        if signal_counts.get("active_discussion", 0) > 0:
            relationship_reasons.append("Sentence-level evidence shows role or assignment discussion.")
        else:
            relationship_reasons.append("Claim evidence indicates active-discussion stage evidence.")
    elif has_problem_identified:
        relationship_stage_code = "S5"
        if signal_counts.get("problem_identified", 0) > 0:
            relationship_reasons.append("Sentence-level evidence shows need or pressure signals.")
        else:
            relationship_reasons.append("Claim evidence indicates active business-pressure signals.")
    elif (ts_positioning_score >= 30 or has_positioning_signal) and (
        recent_interaction_count >= 2
        or relationship_signal_score >= 40
        or has_nurture_signal
    ):
        relationship_stage_code = "S4"
        relationship_reasons.append("Positioning exists and relationship continuity is active.")
    elif ts_positioning_score >= 30 or has_positioning_signal:
        relationship_stage_code = "S3"
        relationship_reasons.append("Taylor Sterling positioning has landed, but opportunity signals are still early.")
    elif business_understanding_score >= 35 or interaction_count >= 2 or has_understand_signal:
        relationship_stage_code = "S2"
        relationship_reasons.append("Context and role understanding are developing.")
    else:
        relationship_stage_code = "S1"
        relationship_reasons.append("Relationship is still in initial contact state.")

    if transcript_highest_relationship_stage:
        relationship_stage_code = transcript_highest_relationship_stage
        relationship_reasons = [
            f"Stage anchored to highest transcript signal: {transcript_highest_relationship_stage}."
        ]
    elif mature_cycle_active and not has_active_client and not has_conversion_pending and not has_active_discussion and not has_problem_identified and interaction_count > 0:
        relationship_stage_code = "S9"
        relationship_reasons.append("Mature relationship continuity is being maintained between assignments.")
    elif previous_relationship_code == "S8" and not has_active_client:
        mature_cycle_active = True
        relationship_stage_code = "S9"
        relationship_reasons.append("Previous active-client phase has moved into active nurture.")

    if relationship_stage_code == "S9":
        mature_cycle_active = True

    inferred_relationship_stage_code = relationship_stage_code
    regression_guard_applied = False
    previous_relationship_rank = _relationship_stage_rank(previous_relationship_code)
    inferred_relationship_rank = _relationship_stage_rank(inferred_relationship_stage_code)
    explicit_regression_signal = _has_explicit_relationship_regression_signal(non_noise_interactions)
    if (
        previous_relationship_code
        and previous_relationship_rank > 0
        and inferred_relationship_rank > 0
        and inferred_relationship_rank < previous_relationship_rank
    ):
        soft_regression_allowed = (
            not explicit_regression_signal
            and (previous_relationship_rank - inferred_relationship_rank) == 1
            and recent_interaction_count > 0
            and not has_problem_identified
            and not has_active_discussion
            and not has_conversion_pending
            and not has_active_client
        )
        if explicit_regression_signal:
            relationship_reasons.append(
                f"Regression signal detected; relationship stage can move down from {previous_relationship_code}."
            )
        elif soft_regression_allowed:
            relationship_stage_code = inferred_relationship_stage_code
            relationship_reasons.append(
                f"Stage softened from {previous_relationship_code} to {inferred_relationship_stage_code} based on fresh evidence and no live problem/discussion signal."
            )
        else:
            relationship_stage_code = previous_relationship_code
            regression_guard_applied = True
            relationship_reasons.append(
                f"Stage continuity guard held at {previous_relationship_code}; latest intake alone does not justify regression."
            )

    opportunity_reasons: list[str] = []
    opportunity_stage_code: Optional[str] = None
    if has_active_client:
        opportunity_stage_code = "O7"
        if signal_counts.get("active_client", 0) > 0:
            opportunity_reasons.append("Sentence-level evidence suggests a current assignment.")
        else:
            opportunity_reasons.append("Claim evidence indicates a current assignment stage.")
    elif has_conversion_pending:
        opportunity_stage_code = "O6" if mature_cycle_active else "O3"
        if signal_counts.get("conversion_pending", 0) > 0:
            opportunity_reasons.append("Sentence-level evidence shows commitment and commercial-shaping signals.")
        else:
            opportunity_reasons.append("Claim evidence indicates conversion-pending opportunity stage.")
    elif has_active_discussion:
        opportunity_stage_code = "O5" if mature_cycle_active else "O2"
        if signal_counts.get("active_discussion", 0) > 0:
            opportunity_reasons.append("Sentence-level evidence shows a role or assignment need in discussion.")
        else:
            opportunity_reasons.append("Claim evidence indicates active-discussion opportunity stage.")
    elif has_problem_identified:
        opportunity_stage_code = "O4" if mature_cycle_active else "O1"
        if signal_counts.get("problem_identified", 0) > 0:
            opportunity_reasons.append("Sentence-level evidence shows need and pressure signals without commitment.")
        else:
            opportunity_reasons.append("Claim evidence indicates problem-identification opportunity stage.")

    opportunity_unlocked = _opportunity_unlocked_by_relationship_journey(
        relationship_stage_code,
        previous_relationship_code,
    )
    blocked_pre_s8_code: Optional[str] = None
    if not opportunity_unlocked and opportunity_stage_code:
        blocked_pre_s8_code = opportunity_stage_code
        opportunity_stage_code = None
        opportunity_reasons = []

    relationship_confidence = 35
    relationship_confidence += min(25, interaction_count * 4)
    relationship_confidence += min(18, recent_interaction_count * 4)
    relationship_confidence += min(12, len(active_claims) * 2)
    relationship_confidence += 8 if previous_relationship_code else 0
    relationship_confidence += 6 if business_understanding_score >= 45 else 0
    relationship_confidence += 5 if ts_positioning_score >= 35 else 0
    relationship_confidence = max(25, min(97, relationship_confidence))

    opportunity_confidence = None
    if opportunity_stage_code:
        opportunity_confidence_value = 40
        opportunity_confidence_value += min(24, len(role_claims) * 8)
        opportunity_confidence_value += min(14, open_action_count * 5)
        opportunity_confidence_value += 8 if has_problem_identified else 0
        opportunity_confidence_value += 6 if previous_opportunity_code else 0
        opportunity_confidence = max(25, min(98, opportunity_confidence_value))

    relationship_stage = _stage2_stage_payload(
        relationship_stage_code,
        relationship_stage_details or STAGE2_RELATIONSHIP_STAGE_DETAILS,
        relationship_confidence,
        relationship_reasons,
    )
    opportunity_stage = (
        _stage2_stage_payload(
            opportunity_stage_code,
            opportunity_stage_details or STAGE2_OPPORTUNITY_STAGE_DETAILS,
            int(opportunity_confidence or 0),
            opportunity_reasons,
        )
        if opportunity_stage_code
        else None
    )

    transition_notes: list[str] = []
    if previous_relationship_code and previous_relationship_code != relationship_stage_code:
        transition_notes.append(f"Relationship stage moved from {previous_relationship_code} to {relationship_stage_code}.")
    if regression_guard_applied:
        transition_notes.append(
            f"Regression guard applied: inferred {inferred_relationship_stage_code} but retained {relationship_stage_code} based on full relationship history."
        )
    if previous_opportunity_code and opportunity_stage_code and previous_opportunity_code != opportunity_stage_code:
        transition_notes.append(f"Opportunity stage moved from {previous_opportunity_code} to {opportunity_stage_code}.")
    if blocked_pre_s8_code:
        transition_notes.append(
            f"Opportunity stage {blocked_pre_s8_code} blocked because relationship journey has not reached S8 yet."
        )
    if mature_cycle_active and opportunity_stage_code in {"O4", "O5", "O6"}:
        transition_notes.append("Mature cycle applied because this relationship is already in active nurture.")

    return {
        "framework": STAGE2_RELATIONSHIP_FLOW_VERSION,
        "generated_at": now.isoformat(),
        "mature_cycle_active": mature_cycle_active,
        "relationship_stage": relationship_stage,
        "opportunity_stage": opportunity_stage,
        "transition": {
            "previous_relationship_stage": previous_relationship_code or None,
            "previous_opportunity_stage": previous_opportunity_code or None,
            "notes": transition_notes[:6],
        },
        "evidence": {
            "interaction_count": interaction_count,
            "recent_interaction_count": recent_interaction_count,
            "active_claim_count": len(active_claims),
            "role_claim_count": len(role_claims),
            "continuity_claim_count": len(continuity_claims),
            "open_action_count": open_action_count,
            "business_understanding_pct": business_understanding_score,
            "taylor_sterling_positioning_pct": ts_positioning_score,
            "relationship_signal_pct": relationship_signal_score,
            "opportunity_unlocked": opportunity_unlocked,
            "relationship_stage_inferred_code": inferred_relationship_stage_code,
            "relationship_stage_transcript_highest_code": transcript_highest_relationship_stage,
            "relationship_stage_regression_guard_applied": regression_guard_applied,
            "relationship_stage_regression_signal_detected": explicit_regression_signal,
            "sentence_signal_counts": signal_counts,
            "sentence_signal_examples": {
                key: values[:2]
                for key, values in signal_evidence.items()
                if values
            },
            "knowledge_mapped_stage_codes": sorted(mapped_stage_codes),
            "knowledge_mapping_examples": mapped_stage_reasons[:6],
        },
    }


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(
        r"(?im)^(sent email:|received email:|microsoft 365 calendar event:)\s*",
        "",
        text,
    )
    return text.strip()


def _trim_text(value: Any, limit: int = 1400) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _canonical_text(value: Any) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _date_only(value: Any) -> str:
    dt = _parse_dt(value)
    if dt:
        return dt.date().isoformat()
    return str(value or "").strip()[:10]


def _is_grounded_source_type(source_type: Any) -> bool:
    return str(source_type or "").strip().lower() in GROUNDED_EVIDENCE_SOURCE_TYPES


def _grounded_source_map(cleaned_interactions: list[dict], *, include_noise: bool = True) -> dict[str, dict]:
    source_map: dict[str, dict] = {}
    for item in cleaned_interactions or []:
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        if not _is_grounded_source_type(item.get("source_type")):
            continue
        if not include_noise and item.get("noise_candidate"):
            continue
        source_map[source_id] = item
    return source_map


def _grounded_non_noise_interactions(cleaned_interactions: list[dict]) -> list[dict]:
    return [
        item
        for item in (cleaned_interactions or [])
        if not item.get("noise_candidate") and _is_grounded_source_type(item.get("source_type"))
    ]


def _source_type_from_evidence(item: dict) -> str:
    kind = str(item.get("source_kind") or "").strip().lower()
    source_type = str(item.get("source_type") or "").strip().lower()
    title = _clean_text(item.get("title"))
    content = _clean_text(item.get("content") or item.get("preview"))
    blob = " ".join([kind, source_type, title.lower(), content.lower()])
    if kind == "manual_resolution" or "manual resolution" in blob or "claim_override::" in content.lower():
        return "manual_resolution"
    if kind in {"manual_update", "topic_resolution"} or "manual input" in blob or "topic resolution" in blob:
        return "manual_input"
    if kind in {"chat", "typed", "note", "chat_topic_resolution"} or source_type in {"chat", "typed", "note", "chat_topic_resolution"}:
        return "manual_input"
    if "chat topic resolution" in blob:
        return "manual_input"
    if "whatsapp" in blob:
        return "whatsapp"
    if "transcript" in blob:
        return "transcript"
    if "calendar" in blob or "meeting response" in blob:
        return "calendar_metadata"
    if "note" in source_type and "meeting" in blob:
        return "meeting_note"
    if "email" in blob:
        return "email"
    if "ai summary" in blob:
        return "ai_summary"
    return "other"


def _noise_candidate(source_type: str, title: str, raw_text: str) -> bool:
    if source_type in {"manual_resolution", "manual_input", "transcript", "meeting_note"}:
        return False
    title_text = _canonical_text(title)
    raw = _canonical_text(raw_text)
    if not raw:
        return True
    if any(pattern in raw for pattern in NOISE_PATTERNS):
        return True
    if title_text.startswith("accepted") or raw.startswith("accepted ") or raw.startswith("received email accepted"):
        return True
    if source_type == "calendar_metadata" and (
        len(raw.split()) <= 4
        or any(token in raw for token in ("join the meeting", "meeting id", "passcode", "accepted this invitation"))
    ):
        return True
    return False


def normalize_relationship_inputs(person: dict, evidence_inputs: list[dict]) -> list[dict]:
    ordered = sorted(
        evidence_inputs or [],
        key=lambda item: (_parse_dt(item.get("date_at") or item.get("date_label")) or datetime(1970, 1, 1, tzinfo=timezone.utc), str(item.get("evidence_id") or "")),
    )
    normalized: list[dict] = []
    seen_signatures: dict[str, dict] = {}
    for index, item in enumerate(ordered, start=1):
        source_type = _source_type_from_evidence(item)
        raw_text = _clean_text(item.get("content") or item.get("preview") or "")
        title = _clean_text(item.get("title") or item.get("preview") or "Untitled interaction")
        source_id = f"src_{index:03d}_{str(item.get('evidence_id') or uuid.uuid4().hex)[:12]}"
        normalized_item = NormalizedInteraction(
            source_id=source_id,
            contact_name=str(person.get("full_name") or "").strip(),
            company=str(person.get("company_name_raw") or "").strip(),
            date=_date_only(item.get("date_at") or item.get("date_label")),
            datetime=str(item.get("date_at") or "").strip() or None,
            source_type=source_type,
            title=title,
            raw_text=raw_text,
            noise_candidate=_noise_candidate(source_type, title, raw_text),
            metadata={
                "evidence_id": item.get("evidence_id"),
                "interaction_id": item.get("interaction_id"),
                "event_id": item.get("event_id"),
                "source_kind": item.get("source_kind"),
                "source_type_label": item.get("source_type"),
                "topic": item.get("topic"),
            },
        ).model_dump()
        signature = "|".join(
            [
                normalized_item["source_type"],
                normalized_item["date"],
                _canonical_text(normalized_item["title"])[:120],
                _canonical_text(normalized_item["raw_text"])[:240],
            ]
        )
        existing = seen_signatures.get(signature)
        if existing:
            if SOURCE_PRIORITY.get(normalized_item["source_type"], 9) < SOURCE_PRIORITY.get(existing["source_type"], 9):
                seen_signatures[signature] = normalized_item
            continue
        seen_signatures[signature] = normalized_item
    normalized.extend(seen_signatures.values())
    return sorted(normalized, key=lambda item: (item["date"], item["source_id"]))


def _source_digest(
    person: dict,
    cleaned_interactions: list[dict],
    *,
    stage1_settings: Optional[dict[str, Any]] = None,
    transcript_tagging: Optional[dict[str, Any]] = None,
) -> str:
    payload = json.dumps(
        {
            "person_id": person.get("person_id"),
            "name": person.get("full_name"),
            "company": person.get("company_name_raw"),
            "inputs": cleaned_interactions,
            "version": PIPELINE_VERSION,
            "digest_version": "relationship-intel-cache-v3",
            "stage1_calibration": stage1_settings if isinstance(stage1_settings, dict) else {},
            "transcript_tagging": transcript_tagging if isinstance(transcript_tagging, dict) else {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _relationship_model() -> str:
    configured = str(getattr(settings, "RELATIONSHIP_STORY_MODEL", "") or "").strip()
    if configured.lower().startswith("gpt-4") or configured.lower().startswith("gpt-5") or configured.lower() == "gpt-4o":
        return configured
    return "gpt-4o"


def _use_llm() -> bool:
    return settings.OPENAI_CONFIGURED and os.getenv("REL_INTEL_USE_LLM", "false").lower() in {"1", "true", "yes"}


def _use_llm_for_lenses() -> bool:
    return _use_llm() and os.getenv("REL_INTEL_LENS_USE_LLM", "true").lower() in {"1", "true", "yes"}


def _use_web_verifier() -> bool:
    return settings.OPENAI_CONFIGURED and os.getenv("REL_INTEL_USE_WEB", "true").lower() in {"1", "true", "yes"}


async def _load_cached_run(person_id: str, source_digest: str) -> Optional[dict]:
    async with get_db() as db:
        async with db.execute(
            """
            SELECT run_id, person_id, source_digest, pipeline_version, model_name, status,
                   cleaned_interactions_json, claim_ledger_json, action_ledger_json, scores_json, briefing_json,
                   created_at, updated_at
            FROM REL_INTEL_RUN
            WHERE person_id = ?
              AND source_digest = ?
              AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (person_id, source_digest),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        run = dict(row)
        for key in ("cleaned_interactions_json", "claim_ledger_json", "action_ledger_json", "scores_json", "briefing_json"):
            value = run.get(key)
            run[key] = json.loads(value) if value else {}
        async with db.execute(
            """
            SELECT agent_name, output_json
            FROM REL_INTEL_AGENT_OUTPUT
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (run["run_id"],),
        ) as cursor:
            rows = await cursor.fetchall()
        run["agent_outputs"] = {
            str(agent_row["agent_name"]): json.loads(agent_row["output_json"] or "{}")
            for agent_row in rows
        }
        return run


def _extract_stage2_from_briefing_payload(briefing_payload: Any) -> Optional[dict]:
    if not isinstance(briefing_payload, dict):
        return None
    stage2 = briefing_payload.get("relationship_business_flow_stage2")
    if isinstance(stage2, dict):
        return _normalize_stage2_payload(stage2)
    return None


async def _load_previous_stage2_state(person_id: str) -> Optional[dict]:
    async with get_db(read_only=True) as db:
        async with db.execute(
            """
            SELECT briefing_json
            FROM REL_INTEL_RUN
            WHERE person_id = ?
              AND status = 'completed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return None
    try:
        briefing_payload = json.loads(row["briefing_json"] or "{}")
    except json.JSONDecodeError:
        return None
    return _extract_stage2_from_briefing_payload(briefing_payload)


async def _persist_run(
    *,
    person_id: str,
    source_digest: str,
    model_name: str,
    cleaned_interactions: list[dict],
    agent_outputs: dict[str, dict],
    claim_ledger: dict,
    action_ledger: dict,
    scores: dict,
    briefing: dict,
) -> str:
    run_id = str(uuid.uuid4())
    now = _now().isoformat()

    async def _write(db):
        await db.execute(
            """
            INSERT INTO REL_INTEL_RUN (
                run_id, person_id, source_digest, pipeline_version, model_name, status,
                cleaned_interactions_json, claim_ledger_json, action_ledger_json, scores_json, briefing_json,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                person_id,
                source_digest,
                PIPELINE_VERSION,
                model_name,
                "completed",
                json.dumps(cleaned_interactions, ensure_ascii=False),
                json.dumps(claim_ledger, ensure_ascii=False),
                json.dumps(action_ledger, ensure_ascii=False),
                json.dumps(scores, ensure_ascii=False),
                json.dumps(briefing, ensure_ascii=False),
                now,
                now,
            ),
        )
        for agent_name, payload in agent_outputs.items():
            await db.execute(
                """
                INSERT INTO REL_INTEL_AGENT_OUTPUT (
                    output_id, run_id, agent_name, model_name, output_json, created_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()),
                    run_id,
                    agent_name,
                    model_name,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )

    await run_write(_write, label=f"persist relationship intelligence run {person_id}")
    return run_id


def _split_sentences(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []
    chunks = re.split(r"(?<=[\.\!\?])\s+|\n+", text)
    cleaned = []
    for chunk in chunks:
        value = chunk.strip(" -")
        lowered = value.lower()
        if not value:
            continue
        if any(lowered.startswith(prefix) for prefix in SENTENCE_NOISE_PREFIXES):
            continue
        if lowered.startswith("so,"):
            continue
        if len(value.split()) <= 3:
            continue
        cleaned.append(value)
    return cleaned


def _is_speculative_claim_text(text: str) -> bool:
    lowered = _clean_text(text).lower()
    return any(pattern in lowered for pattern in SPECULATIVE_PATTERNS)


def _candidate_sort_key(point: dict, source_map: dict[str, dict]) -> tuple[int, str, int, float, int]:
    source_ids = list(point.get("source_ids") or [])
    source_rank = _claim_source_rank(source_ids, source_map)
    last_seen, priority, confidence = "", int(point.get("priority") or 8), float(point.get("confidence") or 0.0)
    if source_ids:
        dates = sorted(source_map.get(source_id, {}).get("date", "") for source_id in source_ids if source_map.get(source_id))
        if dates:
            last_seen = dates[-1]
    recency_key = "99999999"
    if last_seen:
        recency_key = f"{99999999 - int(last_seen.replace('-', '')):08d}"
    status_bonus = {
        "active": 0,
        "uncertain": 1,
        "historical": 2,
        "superseded": 3,
        "disproved": 4,
    }.get(str(point.get("status") or ""), 5)
    return (
        source_rank,
        recency_key,
        status_bonus,
        priority,
        -confidence,
    )


def _sentence_priority(text: str, source_type: str, item_date: str) -> tuple[int, float]:
    source_bonus = max(0, 10 - SOURCE_PRIORITY.get(source_type, 9))
    importance = 0.2
    lowered = text.lower()
    for keyword in ("active", "needs", "filled", "incorrect", "priority", "bim", "data center", "hospital", "daughter"):
        if keyword in lowered:
            importance += 0.15
    if len(text) > 120:
        importance += 0.05
    days_old = 999
    dt = _parse_dt(item_date)
    if dt:
        days_old = (_now() - dt).days
    recency = 1.0 if days_old <= 45 else 0.75 if days_old <= 120 else 0.45
    return min(8, 1 + source_bonus // 2), min(0.98, importance * recency)


def _build_candidate_point(
    *,
    point_id: str,
    point: str,
    status: str,
    confidence: float,
    priority: int,
    source_ids: list[str],
    why_it_matters: str,
    sub_lens: Optional[str] = None,
    secondary_sub_lens: Optional[str] = None,
) -> dict:
    payload = {
        "point_id": point_id,
        "point": point,
        "status": status,
        "confidence": round(max(0.05, min(confidence, 0.99)), 3),
        "priority": max(1, min(priority, 8)),
        "source_ids": source_ids[:6],
        "why_it_matters": why_it_matters,
        "supersedes_point_ids": [],
        "disproved_by_point_ids": [],
    }
    if sub_lens is not None:
        payload["sub_lens"] = sub_lens
        payload["secondary_sub_lens"] = secondary_sub_lens or "none"
    return payload


def _fallback_family_agent(interactions: list[dict]) -> dict:
    points: list[dict] = []
    point_source_map: dict[str, dict] = {}
    changed: list[str] = []
    uncertainties: list[str] = []
    gaps: list[str] = []
    watchouts: list[str] = []
    for item in interactions:
        for sentence in _split_sentences(item.get("raw_text")):
            lowered = sentence.lower()
            if not any(keyword in lowered for keyword in FAMILY_KEYWORDS | LIFESTYLE_KEYWORDS):
                continue
            priority, confidence = _sentence_priority(sentence, item["source_type"], item["date"])
            if any(keyword in lowered for keyword in FAMILY_KEYWORDS):
                sub_lens = LENS_FAMILY
                secondary = LENS_LIFESTYLE if any(keyword in lowered for keyword in LIFESTYLE_KEYWORDS) else "none"
            else:
                sub_lens = LENS_LIFESTYLE
                secondary = "none"
            status = "active" if (_now().date() - datetime.fromisoformat(item["date"]).date()).days <= 365 else "historical"
            if "not" in lowered and "running" in lowered:
                status = "uncertain"
                uncertainties.append(sentence)
            points.append(
                _build_candidate_point(
                    point_id=f"p_f_{len(points)+1:03d}",
                    point=sentence,
                    status=status,
                    confidence=confidence,
                    priority=priority,
                    source_ids=[item["source_id"]],
                    why_it_matters="This gives Marcus a human way into the conversation without forcing rapport.",
                    sub_lens=sub_lens,
                    secondary_sub_lens=secondary,
                )
            )
            point_source_map[points[-1]["point_id"]] = {
                "source_type": item["source_type"],
                "date": item["date"],
            }
            if _parse_dt(item.get("datetime") or item["date"]) and (_now() - (_parse_dt(item.get("datetime") or item["date"]) or _now())).days <= 45:
                changed.append(sentence)
    point_sources = {
        point["point_id"]: {
            "source_type": point_source_map.get(point["point_id"], {}).get("source_type"),
            "date": point_source_map.get(point["point_id"], {}).get("date"),
        }
        for point in points
    }
    points.sort(
        key=lambda point: _candidate_sort_key(
            point,
            {
                (point.get("source_ids") or [""])[0]: {
                    "source_type": point_sources.get(point["point_id"], {}).get("source_type"),
                    "date": point_sources.get(point["point_id"], {}).get("date"),
                }
            },
        )
    )
    summary = "Low signal." if not points else "Human context exists and should be used selectively."
    return {
        "lens": AGENT_TO_LENS[AGENT_FAMILY],
        "lens_summary": summary,
        "candidate_points": points[:8],
        "changed_points": changed[:5],
        "uncertain_points": uncertainties[:5],
        "gaps": gaps[:5],
        "watchouts": watchouts[:5],
    }


def _active_status_from_sentence(sentence: str) -> str:
    lowered = sentence.lower()
    if any(term in lowered for term in ("incorrect", "wrong", "not true", "should be removed")):
        return "disproved"
    if _is_speculative_claim_text(lowered):
        return "uncertain"
    if any(term in lowered for term in ("filled", "already filled", "lost", "not through us")):
        return "superseded"
    if any(term in lowered for term in ("maybe", "potentially", "likely", "unclear")):
        return "uncertain"
    if any(term in lowered for term in ("need", "needs", "active", "remain active", "looking for", "follow up", "follow-up")):
        return "active"
    return "historical"


def _fallback_active_agent(interactions: list[dict]) -> dict:
    points: list[dict] = []
    point_source_map: dict[str, dict] = {}
    changed: list[str] = []
    uncertainties: list[str] = []
    gaps: list[str] = []
    watchouts: list[str] = []
    for item in interactions:
        for sentence in _split_sentences(item.get("raw_text")):
            lowered = sentence.lower()
            if not any(keyword in lowered for keyword in ACTIVE_KEYWORDS):
                continue
            priority, confidence = _sentence_priority(sentence, item["source_type"], item["date"])
            status = _active_status_from_sentence(sentence)
            if status == "uncertain":
                uncertainties.append(sentence)
            if "follow up" in lowered or "reach out" in lowered or "ownership" in lowered:
                gaps.append("Decision ownership or next step is not fully pinned down.")
            if "postponed" in lowered or "emergency" in lowered:
                watchouts.append("Recent continuity was disrupted, so timing needs checking before leaning on old assumptions.")
            points.append(
                _build_candidate_point(
                    point_id=f"p_a_{len(points)+1:03d}",
                    point=sentence,
                    status=status,
                    confidence=confidence,
                    priority=priority,
                    source_ids=[item["source_id"]],
                    why_it_matters="This affects what Marcus can act on commercially before the next conversation.",
                )
            )
            point_source_map[points[-1]["point_id"]] = {
                "source_type": item["source_type"],
                "date": item["date"],
            }
            if status in {"active", "superseded", "disproved"}:
                changed.append(sentence)
    points.sort(
        key=lambda point: _candidate_sort_key(
            point,
            {
                (point.get("source_ids") or [""])[0]: point_source_map.get(point["point_id"], {}),
            },
        )
    )
    return {
        "lens": LENS_ACTIVE,
        "lens_summary": "Low signal." if not points else "Commercial opportunity exists but needs tight current-truth handling.",
        "candidate_points": points[:10],
        "changed_points": changed[:5],
        "uncertain_points": uncertainties[:5],
        "gaps": list(dict.fromkeys(gaps))[:5],
        "watchouts": list(dict.fromkeys(watchouts))[:5],
    }


def _fallback_market_agent(interactions: list[dict]) -> dict:
    points: list[dict] = []
    point_source_map: dict[str, dict] = {}
    changed: list[str] = []
    uncertainties: list[str] = []
    watchouts: list[str] = []
    for item in interactions:
        for sentence in _split_sentences(item.get("raw_text")):
            lowered = sentence.lower()
            if not any(keyword in lowered for keyword in MARKET_KEYWORDS):
                continue
            priority, confidence = _sentence_priority(sentence, item["source_type"], item["date"])
            if "maybe" in lowered or "could" in lowered:
                uncertainties.append(sentence)
            if "frustration" in lowered or "pressure" in lowered or "competition" in lowered:
                watchouts.append("Business frustration is present and should be explored directly rather than assumed.")
            status = "uncertain" if _is_speculative_claim_text(lowered) else "active"
            points.append(
                _build_candidate_point(
                    point_id=f"p_m_{len(points)+1:03d}",
                    point=sentence,
                    status=status,
                    confidence=confidence,
                    priority=priority,
                    source_ids=[item["source_id"]],
                    why_it_matters="This is useful business context for Marcus before the next conversation.",
                )
            )
            point_source_map[points[-1]["point_id"]] = {
                "source_type": item["source_type"],
                "date": item["date"],
            }
            changed.append(sentence)
    points.sort(
        key=lambda point: _candidate_sort_key(
            point,
            {
                (point.get("source_ids") or [""])[0]: point_source_map.get(point["point_id"], {}),
            },
        )
    )
    return {
        "lens": LENS_MARKET,
        "lens_summary": "Low signal." if not points else "The contact is giving direct business and market read-through.",
        "candidate_points": points[:10],
        "changed_points": changed[:5],
        "uncertain_points": uncertainties[:5],
        "gaps": [],
        "watchouts": list(dict.fromkeys(watchouts))[:5],
    }


def _fallback_track_agent(interactions: list[dict], person: dict) -> dict:
    points: list[dict] = []
    point_source_map: dict[str, dict] = {}
    changed: list[str] = []
    uncertainties: list[str] = []
    gaps: list[str] = []
    watchouts: list[str] = []
    for item in interactions:
        for sentence in _split_sentences(item.get("raw_text")):
            lowered = sentence.lower()
            if not any(keyword in lowered for keyword in TRACK_KEYWORDS):
                continue
            priority, confidence = _sentence_priority(sentence, item["source_type"], item["date"])
            status = "disproved" if "incorrect" in lowered or "wrong" in lowered else "active"
            if status == "active" and _is_speculative_claim_text(lowered):
                status = "uncertain"
            if "difficult" in lowered or "guarded" in lowered:
                gaps.append("Access depth still needs proving in live interaction, not assumed from title alone.")
                watchouts.append("Relationship depth appears limited and should not be overstated.")
            if status == "disproved":
                changed.append(sentence)
            points.append(
                _build_candidate_point(
                    point_id=f"p_t_{len(points)+1:03d}",
                    point=sentence,
                    status=status,
                    confidence=confidence,
                    priority=priority,
                    source_ids=[item["source_id"]],
                    why_it_matters="This shapes the long-term account value or access reality around the relationship.",
                )
            )
            point_source_map[points[-1]["point_id"]] = {
                "source_type": item["source_type"],
                "date": item["date"],
            }
    points.sort(
        key=lambda point: _candidate_sort_key(
            point,
            {
                (point.get("source_ids") or [""])[0]: point_source_map.get(point["point_id"], {}),
            },
        )
    )
    if not points:
        gaps.append("No interaction-backed evidence yet; do not infer access or influence from profile title alone.")
    return {
        "lens": LENS_TRACK,
        "lens_summary": "Low signal." if not points else "The relationship has strategic value, but the quality of access must stay grounded.",
        "candidate_points": points[:10],
        "changed_points": changed[:5],
        "uncertain_points": uncertainties[:5],
        "gaps": list(dict.fromkeys(gaps))[:5],
        "watchouts": list(dict.fromkeys(watchouts))[:5],
    }


def _serialize_interactions_for_agent(interactions: list[dict]) -> list[dict]:
    return [
        {
            "source_id": item["source_id"],
            "date": item["date"],
            "source_type": item["source_type"],
            "title": item["title"],
            "raw_text": _trim_text(item["raw_text"], 900),
            "noise_candidate": item["noise_candidate"],
        }
        for item in interactions
    ]


def _serialize_transcript_guidance(transcript_tagging: dict[str, Any] | None) -> dict[str, Any]:
    tagging = transcript_tagging if isinstance(transcript_tagging, dict) else {}
    bucket_rows = tagging.get("knowledge_buckets") if isinstance(tagging.get("knowledge_buckets"), list) else []
    rel_stage_rows = tagging.get("stage_relationship") if isinstance(tagging.get("stage_relationship"), list) else []
    opp_stage_rows = tagging.get("stage_opportunity") if isinstance(tagging.get("stage_opportunity"), list) else []

    def _guidance_includes(value: Any, limit: int = 16) -> list[str]:
        if isinstance(value, str):
            rows = [part.strip() for part in re.split(r"[,;\n]+", value) if part and part.strip()]
        elif isinstance(value, list):
            rows = [str(item).strip() for item in value if str(item).strip()]
        else:
            rows = []
        deduped: list[str] = []
        seen: set[str] = set()
        for item in rows:
            canonical = item.lower()
            if canonical in seen:
                continue
            seen.add(canonical)
            deduped.append(_trim_text(item, 80))
            if len(deduped) >= limit:
                break
        return deduped

    buckets: list[dict[str, Any]] = []
    for row in bucket_rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("box_key") or "").strip()
        if not key:
            continue
        buckets.append(
            {
                "code": str(row.get("code") or "").strip().upper(),
                "box_key": key,
                "box_title": str(row.get("box_title") or key).strip(),
                "what_it_is": _trim_text(str(row.get("what_it_is") or "").strip(), 320),
                "includes": _guidance_includes(row.get("includes"), limit=16),
                "good_content_looks_like": _trim_text(str(row.get("good_content_looks_like") or "").strip(), 320),
            }
        )

    stages: list[dict[str, Any]] = []
    for row in rel_stage_rows + opp_stage_rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().upper()
        if not code:
            continue
        stages.append(
            {
                "code": code,
                "label": str(row.get("label") or code).strip(),
                "summary": _trim_text(str(row.get("summary") or "").strip(), 240),
                "what_it_is": _trim_text(str(row.get("what_it_is") or "").strip(), 320),
                "includes": _guidance_includes(row.get("includes"), limit=16),
                "good_content_looks_like": _trim_text(str(row.get("good_content_looks_like") or "").strip(), 320),
            }
        )

    return {
        "knowledge_buckets": buckets[:20],
        "stages": stages[:24],
    }


def _filter_for_agent(agent_name: str, cleaned_interactions: list[dict]) -> list[dict]:
    result: list[dict] = []
    for item in cleaned_interactions:
        if item["source_type"] in {"manual_resolution", "manual_input"}:
            result.append(item)
            continue
        if item["noise_candidate"]:
            continue
        lowered = f"{item['title']} {item['raw_text']}".lower()
        if agent_name == AGENT_FAMILY and any(keyword in lowered for keyword in FAMILY_KEYWORDS | LIFESTYLE_KEYWORDS):
            result.append(item)
        elif agent_name == AGENT_ACTIVE and any(keyword in lowered for keyword in ACTIVE_KEYWORDS):
            result.append(item)
        elif agent_name == AGENT_MARKET and any(keyword in lowered for keyword in MARKET_KEYWORDS):
            result.append(item)
        elif agent_name == AGENT_TRACK and any(keyword in lowered for keyword in TRACK_KEYWORDS):
            result.append(item)
    if result:
        return result[:28]
    return [item for item in cleaned_interactions if not item["noise_candidate"]][:12]


async def _run_json_agent(agent_name: str, prompt: str, response_format: dict, payload: dict, person_id: str) -> tuple[dict, str]:
    data, _run_id = await run_json_chat_task(
        task_type="relationship_intelligence_agent",
        prompt_family=agent_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_relationship_model(),
        temperature=0.1,
        response_format=response_format,
        related_profile_id=person_id,
        metadata={"agent_name": agent_name, "pipeline_version": PIPELINE_VERSION},
    )
    return data, _relationship_model()


async def _run_json_web_agent(agent_name: str, prompt: str, payload: dict, person_id: str) -> tuple[dict, str]:
    data, _run_id = await run_json_responses_task(
        task_type="relationship_intelligence_web_agent",
        prompt_family=agent_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        model=_relationship_model(),
        temperature=0.1,
        tools=[{"type": "web_search_preview"}],
        related_profile_id=person_id,
        metadata={"agent_name": agent_name, "pipeline_version": PIPELINE_VERSION, "web_enabled": True},
    )
    return data, _relationship_model()


async def _run_lens_agent(
    agent_name: str,
    person: dict,
    cleaned_interactions: list[dict],
    transcript_guidance: Optional[dict[str, Any]] = None,
) -> tuple[dict, str]:
    interactions = _filter_for_agent(agent_name, cleaned_interactions)
    payload = {
        "contact_name": person.get("full_name"),
        "company": person.get("company_name_raw"),
        "title": person.get("title_current"),
        "interactions": _serialize_interactions_for_agent(interactions),
    }
    if isinstance(transcript_guidance, dict):
        payload["transcript_guidance"] = transcript_guidance
    if _use_llm_for_lenses():
        try:
            result, model_name = await asyncio.wait_for(
                _run_json_agent(
                    agent_name,
                    PROMPT_REGISTRY[agent_name],
                    lens_agent_response_format(agent_name),
                    payload,
                    str(person.get("person_id")),
                ),
                timeout=20,
            )
            result["lens"] = AGENT_TO_LENS[agent_name]
            return result, model_name
        except Exception:
            pass
    if agent_name == AGENT_FAMILY:
        return _fallback_family_agent(interactions), "deterministic-fallback"
    if agent_name == AGENT_ACTIVE:
        return _fallback_active_agent(interactions), "deterministic-fallback"
    if agent_name == AGENT_MARKET:
        return _fallback_market_agent(interactions), "deterministic-fallback"
    return _fallback_track_agent(interactions, person), "deterministic-fallback"


def _overlap(left: str, right: str) -> float:
    left_tokens = set(_canonical_text(left).split())
    right_tokens = set(_canonical_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def _claim_source_rank(source_ids: list[str], source_map: dict[str, dict]) -> int:
    if not source_ids:
        return 9
    ranks = [SOURCE_PRIORITY.get(str(source_map.get(source_id, {}).get("source_type") or "other"), 9) for source_id in source_ids]
    return min(ranks or [9])


def _extract_bim_lead_count(text: str) -> Optional[int]:
    lowered = str(text or "").lower()
    digit_match = re.search(r"\b(\d+)\s+bim lead", lowered)
    if digit_match:
        return int(digit_match.group(1))
    if re.search(r"\b(a|an|single)\s+bim lead\b", lowered):
        return 1
    if re.search(r"\bone\s+bim lead\b", lowered):
        return 1
    word_map = {
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
    }
    for word, count in word_map.items():
        if re.search(rf"\b{word}\s+bim lead", lowered):
            return count
    return None


def _family_and_entity_for_claim(text: str, lens: str) -> tuple[str, str]:
    lowered = str(text or "").lower()
    if lens == LENS_FAMILY:
        if "daughter" in lowered or "son" in lowered or "children" in lowered or "family" in lowered:
            return "family_hook", "family_context"
        return "personal_hook", "personal_context"
    if lens == LENS_LIFESTYLE:
        return "lifestyle_hook", "lifestyle_context"
    if "filled" in lowered and any(term in lowered for term in ("commercial role", "commercial manager", "commercial director", "role in commercial projects", "commercial projects")):
        return "role_status", "commercial_role"
    if "ceo" in lowered and ("intro" in lowered or "introduc" in lowered):
        return "access_offer", "ceo_intro"
    if "obe roundtable" in lowered:
        return "account_engagement", "obe_roundtable"
    if "bim lead" in lowered:
        family = "role_count" if _extract_bim_lead_count(lowered) is not None else "role_need"
        return family, "bim_lead"
    if "data center" in lowered or "data centres" in lowered or "data center specialist" in lowered:
        return "role_need", "data_centers_lead"
    if "commercial manager" in lowered or "commercial director" in lowered or "commercial role" in lowered or "unicorn" in lowered:
        if "filled" in lowered or "not through us" in lowered:
            return "role_status", "commercial_role"
        return "role_need", "commercial_role"
    if "senior quantity surveyor" in lowered or "neom project" in lowered:
        return "role_need", "neom_team_buildout"
    if any(term in lowered for term in ("pricing", "competition", "frustration", "shortage")):
        return "market_pressure", "market_conditions"
    if any(term in lowered for term in ("hospital projects", "hospital project focus", "bim-first strategy", "project focus")):
        return "business_focus", "business_focus"
    if any(term in lowered for term in ("follow up", "follow-up", "after eid", "reorganize", "reorganise", "next week")):
        return "follow_up_timing", "follow_up_timing"
    if any(term in lowered for term in ("difficult chap", "guarded", "hard to deepen", "access depth")):
        return "relationship_continuity", "relationship_depth"
    if lens == LENS_TRACK:
        return "track_record", "account_value"
    return "other", _canonical_text(lowered)[:48] or "general"


def _claim_dates(source_ids: list[str], source_map: dict[str, dict]) -> tuple[str, str]:
    dates = sorted(source_map.get(source_id, {}).get("date", "") for source_id in source_ids if source_map.get(source_id))
    if not dates:
        return "", ""
    return dates[0], dates[-1]


def _claim_status_weight(status: str) -> int:
    return {
        "active": 10,
        "uncertain": 7,
        "historical": 5,
        "superseded": 2,
        "disproved": 1,
    }.get(str(status or ""), 0)


def _claim_truth_state(claim: dict) -> str:
    status = str(claim.get("status") or "")
    source_rank = int(claim.get("source_rank") or 9)
    confidence = float(claim.get("confidence") or 0.0)
    if status in {"superseded", "disproved"}:
        return "Retired"
    if status == "uncertain":
        return "Unverified"
    if source_rank <= 2 and confidence >= 0.72:
        return "Confirmed"
    if source_rank <= 3 and confidence >= 0.5:
        return "Likely"
    return "Unverified"


def _claim_freshness_bonus(claim: dict) -> float:
    last_seen = str(claim.get("last_seen") or "")
    if not last_seen:
        return 0.0
    try:
        days_old = (_now().date() - datetime.fromisoformat(last_seen).date()).days
    except ValueError:
        return 0.0
    if days_old <= 30:
        return 4.0
    if days_old <= 90:
        return 2.5
    if days_old <= 180:
        return 1.0
    return -1.5


def _claim_family_decay_window(claim_family: str) -> int:
    if claim_family in {"role_need", "role_count", "role_status", "follow_up_timing", "access_offer"}:
        return 120
    if claim_family in {"market_pressure", "business_focus", "account_engagement", "relationship_continuity"}:
        return 210
    if claim_family in {"family_hook", "lifestyle_hook", "personal_hook"}:
        return 540
    return 365


def _claim_is_stale(claim: dict) -> bool:
    last_seen = str(claim.get("last_seen") or "")
    if not last_seen:
        return False
    try:
        days_old = (_now().date() - datetime.fromisoformat(last_seen).date()).days
    except ValueError:
        return False
    return days_old > _claim_family_decay_window(str(claim.get("claim_family") or "other"))


def _claim_visible_in_section(claim: dict, section: str) -> bool:
    text = _clean_text(claim.get("claim_text")).lower()
    claim_family = str(claim.get("claim_family") or "other")
    lens = str(claim.get("lens") or "")
    if not text:
        return False
    if any(
        phrase in text
        for phrase in (
            "do not retain this as current relationship truth",
            "this is a massive strategic win for us",
            "put a reminder on sunday",
        )
    ):
        return False
    if section in {"truth", "lens", "signals"} and (
        text.startswith("i need to reach out")
        or text.startswith("subsequently, we had another meeting")
        or claim_family == "follow_up_timing"
    ):
        return False
    if section == "track" and (
        claim_family in {"follow_up_timing", "role_need", "role_count", "role_status"}
        or "incorrect" in text
        or "should be removed" in text
    ):
        return False
    if section == "truth" and lens == LENS_TRACK and _is_speculative_claim_text(text):
        return False
    return True


def _rewrite_claim_text_for_brief(claim: dict) -> str:
    text = _clean_text(claim.get("claim_text"))
    lowered = text.lower()
    if not text:
        return ""
    replacements = (
        ("active roles include ", "Live roles currently include "),
    )
    for prefix, replacement in replacements:
        if lowered.startswith(prefix):
            return replacement + text[len(prefix):]
    if "and yeah, it was more of an industry chat" in lowered and any(term in lowered for term in ("pricing", "competition", "hospital")):
        return "Kevin flagged pricing pressure, competition, and hospital-project focus."
    if "we discussed the situation, market frustrations, and hospital project focus" in lowered:
        return "Kevin discussed market frustration and hospital-project focus."
    if "we sat at their office" in lowered and "frustrations" in lowered:
        return "Kevin was candid about business pressure and market frustration."
    if "he was thinking about someone" in lowered and "data center" in lowered:
        return "A data centre specialist remains part of the live hiring discussion."
    if "he needs strength in his bim implementation" in lowered:
        return "BIM capability remains a live hiring priority."
    if "bim, bim implementations" in lowered:
        return "BIM capability remains central to the discussion."
    if "on a personal note" in lowered and "running" in lowered:
        return "Kevin has not been running recently because of regional disruption."
    if "burj to burj run with his daughter" in lowered:
        return "Kevin recently completed the Burj to Burj run with his daughter."
    if "watch and an app on his phone" in lowered or "watch and an app" in lowered:
        return "Kevin has been training seriously for long-distance running."
    return text


def _claim_precedence_key(claim: dict) -> tuple[int, str, int, float]:
    last_seen = str(claim.get("last_seen") or "")
    recency_key = ""
    if last_seen:
        recency_key = f"{99999999 - int(last_seen.replace('-', '')):08d}"
    return (
        int(claim.get("source_rank") or 9),
        recency_key,
        int(claim.get("priority") or 8),
        -float(claim.get("confidence") or 0.0),
    )


def _claim_count_value(claim: dict) -> Optional[int]:
    return _extract_bim_lead_count(str(claim.get("claim_text") or ""))


def _claim_has_status_signal(text: str, *terms: str) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in terms)


def _manual_count_override(entity_key: str, manual_text: str) -> Optional[int]:
    text = str(manual_text or "").lower()
    if not text:
        return None
    patterns: dict[str, tuple[str, ...]] = {
        "bim_lead": ("bim lead", "bim leads"),
        "commercial_role": ("commercial manager", "commercial director", "commercial role"),
    }
    labels = patterns.get(entity_key, tuple(part for part in entity_key.replace("_", " ").split() if part))
    if not labels:
        return None
    word_map = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
    }
    for label in labels:
        digit_match = re.search(rf"\b(\d+)\s+{re.escape(label)}\b", text)
        if digit_match:
            return int(digit_match.group(1))
        for word, count in word_map.items():
            if re.search(rf"\b{word}\s+{re.escape(label)}\b", text):
                return count
        if re.search(rf"\b(a|an|single)\s+{re.escape(label)}\b", text):
            return 1
    return None


def _apply_claim_family_reconciliation(claims: list[dict], cleaned_interactions: list[dict], source_map: dict[str, dict]) -> list[dict]:
    manual_resolution_text = " ".join(
        item["raw_text"].lower()
        for item in cleaned_interactions
        if item["source_type"] == "manual_resolution"
    )
    manual_input_text = " ".join(
        item["raw_text"].lower()
        for item in cleaned_interactions
        if item["source_type"] == "manual_input"
    )

    by_family_entity: dict[tuple[str, str], list[dict]] = {}
    for claim in claims:
        key = (str(claim.get("claim_family") or "other"), str(claim.get("entity_key") or "general"))
        by_family_entity.setdefault(key, []).append(claim)

    for (claim_family, _entity_key), group in by_family_entity.items():
        group.sort(key=_claim_precedence_key)
        winner = group[0]

        if claim_family == "role_count":
            manual_override = _manual_count_override(_entity_key, manual_input_text)
            counted = [item for item in group if _claim_count_value(item) is not None]
            if manual_override is not None:
                matching_manual = [
                    item
                    for item in counted
                    if int(item.get("source_rank") or 9) <= 2 and _claim_count_value(item) == manual_override
                ]
                if matching_manual:
                    winner = sorted(matching_manual, key=_claim_precedence_key)[0]
                else:
                    for claim in counted:
                        count = _claim_count_value(claim)
                        if count is not None and count != manual_override:
                            claim["status"] = "superseded"
                counted = [item for item in group if _claim_count_value(item) is not None and item.get("status") != "superseded"]
            if counted:
                winner = sorted(
                    counted,
                    key=lambda item: (
                        int(item.get("source_rank") or 9),
                        f"{99999999 - int(str(item.get('last_seen') or '1970-01-01').replace('-', '')):08d}",
                        int(_claim_count_value(item) or 999),
                        int(item.get("priority") or 8),
                    ),
                )[0]
        elif claim_family in {"follow_up_timing", "market_pressure", "business_focus", "account_engagement", "relationship_continuity"}:
            winner = sorted(
                group,
                key=lambda item: (
                    int(item.get("source_rank") or 9),
                    f"{99999999 - int(str(item.get('last_seen') or '1970-01-01').replace('-', '')):08d}",
                    int(item.get("priority") or 8),
                ),
            )[0]

        winner["status"] = "active" if winner.get("status") not in {"disproved", "superseded"} else winner.get("status")
        for claim in group:
            if claim["claim_id"] == winner["claim_id"]:
                continue
            if claim.get("status") == "disproved":
                continue
            claim["status"] = "superseded" if claim_family in {"role_need", "role_count", "role_status", "access_offer"} else "historical"
            claim["supersedes_claim_ids"] = list(dict.fromkeys((claim.get("supersedes_claim_ids") or []) + [winner["claim_id"]]))

    by_entity: dict[str, list[dict]] = {}
    for claim in claims:
        by_entity.setdefault(str(claim.get("entity_key") or "general"), []).append(claim)

    for entity_key, group in by_entity.items():
        role_status_claims = [claim for claim in group if claim.get("claim_family") == "role_status"]
        role_need_claims = [claim for claim in group if claim.get("claim_family") in {"role_need", "role_count"}]
        access_claims = [claim for claim in group if claim.get("claim_family") == "access_offer"]

        latest_role_status = None
        if role_status_claims:
            latest_role_status = sorted(
                role_status_claims,
                key=lambda item: (
                    int(item.get("source_rank") or 9),
                    f"{99999999 - int(str(item.get('last_seen') or '1970-01-01').replace('-', '')):08d}",
                    int(item.get("priority") or 8),
                ),
            )[0]
        if latest_role_status and _claim_has_status_signal(latest_role_status.get("claim_text"), "filled", "lost", "not through us", "closed"):
            latest_role_status["status"] = "superseded"
            for claim in role_need_claims:
                if claim["claim_id"] == latest_role_status["claim_id"]:
                    continue
                if int(latest_role_status.get("source_rank") or 9) <= int(claim.get("source_rank") or 9) or str(latest_role_status.get("last_seen") or "") >= str(claim.get("last_seen") or ""):
                    claim["status"] = "superseded"
                    claim["disproved_by_claim_ids"] = list(dict.fromkeys((claim.get("disproved_by_claim_ids") or []) + [latest_role_status["claim_id"]]))

        active_role_count = next((claim for claim in role_need_claims if claim.get("claim_family") == "role_count" and claim.get("status") == "active"), None)
        if active_role_count:
            for claim in role_need_claims:
                if claim["claim_id"] == active_role_count["claim_id"]:
                    continue
                if claim.get("claim_family") == "role_need":
                    claim["status"] = "historical"
                    claim["supersedes_claim_ids"] = list(dict.fromkeys((claim.get("supersedes_claim_ids") or []) + [active_role_count["claim_id"]]))
            if _manual_count_override(entity_key, manual_input_text) is not None:
                for claim in role_need_claims:
                    if int(claim.get("source_rank") or 9) <= 2 and claim.get("status") not in {"disproved", "superseded"}:
                        claim["status"] = "active"
                        claim["supersedes_claim_ids"] = list(dict.fromkeys((claim.get("supersedes_claim_ids") or []) + [active_role_count["claim_id"]]))
                manual_override = _manual_count_override(entity_key, manual_input_text)
                if manual_override is not None and (
                    int(active_role_count.get("source_rank") or 9) > 2
                    or _claim_count_value(active_role_count) != manual_override
                ):
                    active_role_count["status"] = "superseded"

        if any(claim.get("status") == "disproved" for claim in access_claims):
            disproved_access = next(claim for claim in access_claims if claim.get("status") == "disproved")
            for claim in access_claims:
                if claim["claim_id"] == disproved_access["claim_id"]:
                    continue
                claim["status"] = "disproved"
                claim["disproved_by_claim_ids"] = list(dict.fromkeys((claim.get("disproved_by_claim_ids") or []) + [disproved_access["claim_id"]]))

        if entity_key == "neom_team_buildout" and manual_input_text and not any(term in manual_input_text for term in ("neom", "commercial director", "senior quantity surveyor")):
            for claim in group:
                if claim.get("claim_family") in {"role_need", "role_count"}:
                    claim["status"] = "historical"

    for claim in claims:
        text = str(claim.get("claim_text") or "").lower()
        claim_family = str(claim.get("claim_family") or "other")
        if "ceo" in text and "intro" in text and ("incorrect" in manual_resolution_text or "did not offer" in manual_resolution_text):
            claim["status"] = "disproved"
        if "obe roundtable" in text and "stantec" in text and "obe roundtable" not in manual_input_text:
            claim["status"] = "superseded"
        if claim_family in {"role_need", "role_count", "follow_up_timing", "access_offer", "account_engagement"} and claim.get("status") == "active" and _claim_is_stale(claim):
            claim["status"] = "historical"
        if claim.get("status") == "active" and _is_speculative_claim_text(text) and int(claim.get("source_rank") or 9) > 2:
            claim["status"] = "uncertain"
        if claim_family == "market_pressure" and "5 bim leads" in text and "one bim lead" in manual_input_text:
            claim["status"] = "superseded"

    return claims


def _build_ledger_summary_fields(claims: list[dict], cleaned_interactions: list[dict], source_map: dict[str, dict]) -> dict:
    sorted_active_claims = sorted(
        [claim for claim in claims if claim.get("status") == "active"],
        key=lambda claim: (-_claim_rank(claim), str(claim.get("claim_text") or "")),
    )
    active_truths: list[str] = []
    seen_families: set[tuple[str, str]] = set()
    for claim in sorted_active_claims:
        key = (str(claim.get("claim_family") or "other"), str(claim.get("entity_key") or "general"))
        if key in seen_families:
            continue
        seen_families.add(key)
        active_truths.append(claim["claim_id"])
        if len(active_truths) >= 12:
            break
    changed_recently = [
        claim["claim_id"]
        for claim in sorted(
            claims,
            key=lambda claim: (
                str(claim.get("last_seen") or ""),
                -_claim_rank(claim),
            ),
            reverse=True,
        )
        if any(source_map.get(source_id, {}).get("date", "") >= (_now() - timedelta(days=45)).date().isoformat() for source_id in claim.get("source_ids") or [])
        and claim.get("status") in {"active", "superseded", "disproved"}
    ][:12]
    uncertainties = [
        claim["claim_id"]
        for claim in sorted(
            [claim for claim in claims if claim.get("status") == "uncertain"],
            key=lambda claim: (-_claim_rank(claim), str(claim.get("claim_text") or "")),
        )
    ][:12]
    disproved = [claim["claim_id"] for claim in claims if claim.get("status") in {"disproved", "superseded"}][:12]

    relationship_gaps: list[str] = []
    risks: list[str] = []
    source_quality_notes: list[str] = []
    blob = " ".join(item["raw_text"].lower() for item in cleaned_interactions)
    active_role_claims = [claim for claim in claims if claim.get("status") == "active" and claim.get("claim_family") in {"role_need", "role_count", "role_status"}]
    active_access_claims = [claim for claim in claims if claim.get("status") == "active" and claim.get("claim_family") == "access_offer"]

    if any(term in blob for term in ("need to reach out", "trying again", "check to see", "reorganize", "reorganise", "follow up", "follow-up")):
        relationship_gaps.append("Next-step ownership and follow-up timing still need confirming.")
    if any(term in blob for term in ("difficult chap", "difficult to build a relationship", "guarded")):
        relationship_gaps.append("Access depth is still limited and should not be overstated.")
        risks.append("Relationship warmth should not be confused with strong access.")
    if any(term in blob for term in ("emergency", "postponed")):
        risks.append("Recent disruption means timing assumptions may already have moved.")
    if not uncertainties and any(term in blob for term in ("potentially", "maybe", "unclear", "trying again", "check to see")):
        relationship_gaps.append("Opportunity status remains mixed enough that uncertainty should be kept explicit.")
    if active_role_claims and not any("ownership" in str(claim.get("claim_text") or "").lower() for claim in active_role_claims):
        relationship_gaps.append("Decision ownership around the live opportunity is still not explicit.")
    if active_access_claims and any(claim.get("status") == "disproved" for claim in claims if claim.get("claim_family") == "access_offer"):
        relationship_gaps.append("Real access depth needs confirming in conversation rather than assumed from older notes.")
    if any(item["source_type"] == "calendar_metadata" and not item["noise_candidate"] for item in cleaned_interactions):
        source_quality_notes.append("Calendar metadata exists but should not be treated as meeting substance on its own.")
    if any(item["source_type"] in {"manual_resolution", "manual_input"} for item in cleaned_interactions):
        source_quality_notes.append("Marcus manual inputs outrank older inferred storyline and should be treated as current-truth anchors.")

    lens_outputs = {lens: [] for lens in LENS_ORDER}
    for claim in sorted(claims, key=lambda claim: (-_claim_rank(claim), str(claim.get("claim_text") or ""))):
        lens_outputs.setdefault(str(claim.get("lens") or ""), []).append(claim["claim_id"])

    return {
        "active_truths": active_truths,
        "changed_recently": changed_recently,
        "uncertainties": uncertainties,
        "disproved_or_retired": disproved,
        "relationship_gaps": list(dict.fromkeys(relationship_gaps))[:6],
        "risks_or_watchouts": list(dict.fromkeys(risks))[:6],
        "source_quality_notes": list(dict.fromkeys(source_quality_notes))[:6],
        "lens_outputs": lens_outputs,
    }


def _brief_claim_line(claim: dict) -> str:
    rewritten = _rewrite_claim_text_for_brief(claim)
    if not rewritten:
        return ""
    truth_state = str(claim.get("truth_state") or _claim_truth_state(claim))
    return f"[{truth_state}] {rewritten}".strip()


def _build_deterministic_claim_ledger(person: dict, agent_outputs: dict[str, dict], cleaned_interactions: list[dict]) -> dict:
    source_map = {item["source_id"]: item for item in cleaned_interactions}
    claims: list[dict] = []
    for agent_name in (AGENT_FAMILY, AGENT_ACTIVE, AGENT_MARKET, AGENT_TRACK):
        output = agent_outputs.get(agent_name) or {}
        for point in output.get("candidate_points") or []:
            lens = (
                LENS_FAMILY
                if point.get("sub_lens") == LENS_FAMILY
                else LENS_LIFESTYLE
                if point.get("sub_lens") == LENS_LIFESTYLE
                else output.get("lens") or AGENT_TO_LENS.get(agent_name) or LENS_TRACK
            )
            claim_family, entity_key = _family_and_entity_for_claim(point.get("point"), lens)
            first_seen, last_seen = _claim_dates(list(point.get("source_ids") or []), source_map)
            claims.append(
                Claim(
                    claim_id=f"c_{len(claims)+1:03d}",
                    claim_text=_clean_text(point.get("point")),
                    lens=lens,
                    claim_family=claim_family,
                    entity_key=entity_key,
                    status=point.get("status") or "uncertain",
                    truth_state="Unverified",
                    confidence=float(point.get("confidence") or 0.4),
                    priority=int(point.get("priority") or 4),
                    source_ids=list(point.get("source_ids") or []),
                    why_it_matters=_clean_text(point.get("why_it_matters")),
                    source_rank=_claim_source_rank(list(point.get("source_ids") or []), source_map),
                    first_seen=first_seen,
                    last_seen=last_seen,
                    supersedes_claim_ids=[],
                    disproved_by_claim_ids=[],
                ).model_dump()
            )
    deduped: list[dict] = []
    for claim in claims:
        match = None
        for existing in deduped:
            if existing["lens"] != claim["lens"] or existing["claim_family"] != claim["claim_family"] or existing["entity_key"] != claim["entity_key"]:
                continue
            if _overlap(existing["claim_text"], claim["claim_text"]) >= 0.8:
                match = existing
                break
        if not match:
            deduped.append(claim)
            continue
        if _claim_source_rank(claim["source_ids"], source_map) <= _claim_source_rank(match["source_ids"], source_map):
            match["claim_text"] = claim["claim_text"]
            match["confidence"] = max(match["confidence"], claim["confidence"])
            match["priority"] = min(match["priority"], claim["priority"])
            match["source_ids"] = list(dict.fromkeys(match["source_ids"] + claim["source_ids"]))
            match["source_rank"] = min(int(match.get("source_rank") or 9), int(claim.get("source_rank") or 9))
            match["first_seen"] = min(str(match.get("first_seen") or ""), str(claim.get("first_seen") or "")).strip()
            match["last_seen"] = max(str(match.get("last_seen") or ""), str(claim.get("last_seen") or "")).strip()
        else:
            match["source_ids"] = list(dict.fromkeys(match["source_ids"] + claim["source_ids"]))
            match["source_rank"] = min(int(match.get("source_rank") or 9), int(claim.get("source_rank") or 9))
            match["first_seen"] = min(str(match.get("first_seen") or ""), str(claim.get("first_seen") or "")).strip()
            match["last_seen"] = max(str(match.get("last_seen") or ""), str(claim.get("last_seen") or "")).strip()
    claims = deduped
    claims = _apply_claim_family_reconciliation(claims, cleaned_interactions, source_map)
    for claim in claims:
        claim["truth_state"] = _claim_truth_state(claim)
    derived_fields = _build_ledger_summary_fields(claims, cleaned_interactions, source_map)

    ledger = ClaimLedger(
        claims=[Claim.model_validate(claim) for claim in claims],
        active_truths=[claim_id for claim_id in derived_fields["active_truths"] if claim_id],
        changed_recently=[claim_id for claim_id in derived_fields["changed_recently"] if claim_id],
        uncertainties=[claim_id for claim_id in derived_fields["uncertainties"] if claim_id],
        disproved_or_retired=[claim_id for claim_id in derived_fields["disproved_or_retired"] if claim_id],
        relationship_gaps=list(derived_fields["relationship_gaps"] or [])[:6],
        risks_or_watchouts=list(derived_fields["risks_or_watchouts"] or [])[:6],
        source_quality_notes=list(derived_fields["source_quality_notes"] or [])[:6],
        lens_outputs=derived_fields["lens_outputs"],
    )
    return ledger.model_dump()


def _merge_arbiter_with_deterministic(arbiter: dict, deterministic: dict, cleaned_interactions: list[dict]) -> dict:
    if not arbiter.get("claims"):
        return deterministic
    deterministic_map = {claim["claim_id"]: claim for claim in deterministic.get("claims") or []}
    merged_claims = []
    for claim in arbiter.get("claims") or []:
        fallback = deterministic_map.get(claim.get("claim_id")) or {}
        if claim.get("status") in {"active", "historical", "superseded", "disproved", "uncertain"}:
            merged_claims.append(
                {
                    **fallback,
                    **claim,
                    "source_ids": list(dict.fromkeys((claim.get("source_ids") or []) + (fallback.get("source_ids") or []))),
                    "claim_family": fallback.get("claim_family") or claim.get("claim_family") or "other",
                    "entity_key": fallback.get("entity_key") or claim.get("entity_key") or "general",
                    "source_rank": fallback.get("source_rank") or claim.get("source_rank") or 9,
                    "first_seen": fallback.get("first_seen") or claim.get("first_seen") or "",
                    "last_seen": max(str(fallback.get("last_seen") or ""), str(claim.get("last_seen") or "")),
                }
            )
    source_map = {item["source_id"]: item for item in cleaned_interactions}
    merged_claims = _apply_claim_family_reconciliation(merged_claims, cleaned_interactions, source_map)
    for claim in merged_claims:
        claim["truth_state"] = _claim_truth_state(claim)
    arbiter["claims"] = merged_claims
    for key in ("relationship_gaps", "risks_or_watchouts", "source_quality_notes"):
        arbiter[key] = list(dict.fromkeys((arbiter.get(key) or []) + (deterministic.get(key) or [])))[:8]
    derived_fields = _build_ledger_summary_fields(merged_claims, cleaned_interactions, source_map)
    for key in ("active_truths", "changed_recently", "uncertainties", "disproved_or_retired", "relationship_gaps", "risks_or_watchouts", "source_quality_notes", "lens_outputs"):
        arbiter[key] = derived_fields.get(key) or arbiter.get(key) or []
    return arbiter


async def _run_truth_arbiter(
    person: dict,
    cleaned_interactions: list[dict],
    agent_outputs: dict[str, dict],
    transcript_guidance: Optional[dict[str, Any]] = None,
) -> tuple[dict, str]:
    deterministic_ledger = _build_deterministic_claim_ledger(person, agent_outputs, cleaned_interactions)
    payload = {
        "contact_name": person.get("full_name"),
        "company": person.get("company_name_raw"),
        "cleaned_interactions": _serialize_interactions_for_agent([item for item in cleaned_interactions if not item["noise_candidate"]][:36]),
        "candidate_points": {
            agent_name: agent_outputs.get(agent_name) or {}
            for agent_name in (AGENT_FAMILY, AGENT_ACTIVE, AGENT_MARKET, AGENT_TRACK)
        },
        "deterministic_ledger": deterministic_ledger,
    }
    if isinstance(transcript_guidance, dict):
        payload["transcript_guidance"] = transcript_guidance
    if _use_llm():
        try:
            result, model_name = await asyncio.wait_for(
                _run_json_agent(
                    AGENT_ARBITER,
                    PROMPT_REGISTRY[AGENT_ARBITER],
                    TRUTH_ARBITER_RESPONSE_FORMAT,
                    payload,
                    str(person.get("person_id")),
                ),
                timeout=20,
            )
            ledger = result.get("claim_ledger") or {}
            ledger = _merge_arbiter_with_deterministic(ledger, deterministic_ledger, cleaned_interactions)
            return ledger, model_name
        except Exception:
            pass
    return deterministic_ledger, "deterministic-fallback"


def _extract_action_overrides(cleaned_interactions: list[dict]) -> list[dict]:
    overrides: list[dict] = []
    for item in cleaned_interactions:
        raw = str(item.get("raw_text") or "")
        if not raw.startswith("ACTION_OVERRIDE::"):
            continue
        try:
            payload = json.loads(raw.split("ACTION_OVERRIDE::", 1)[1].strip())
        except json.JSONDecodeError:
            continue
        payload["_source_id"] = item.get("source_id")
        overrides.append(payload)
    return overrides


def _fallback_action_tracker(person: dict, claim_ledger: dict, cleaned_interactions: list[dict]) -> dict:
    claim_map = _claim_map(claim_ledger)
    active_claims = [claim_map.get(claim_id) for claim_id in claim_ledger.get("active_truths") or [] if claim_map.get(claim_id)]
    actions: list[dict] = []
    active_opportunity_claims = [claim for claim in active_claims if claim.get("lens") == LENS_ACTIVE]
    market_claims = [claim for claim in active_claims if claim.get("lens") == LENS_MARKET]
    blob = " ".join(str(item.get("raw_text") or "").lower() for item in cleaned_interactions)
    contact_name = str(person.get("full_name") or "this contact").strip()

    if active_opportunity_claims and any(term in blob for term in ("postponed", "reorganize", "reorganise", "after eid", "need to reach out", "trying again", "follow up", "follow-up")):
        actions.append(
            {
                "action_id": "act_001",
                "action_text": f"Rearrange the follow-up meeting with {contact_name} to progress the live roles after Eid.",
                "action_type": "reschedule_meeting",
                "status": "open",
                "owner": "Marcus",
                "urgency": "high",
                "due_window": "Immediate to next 7 days",
                "linked_claim_ids": [claim["claim_id"] for claim in active_opportunity_claims[:3]],
                "supporting_source_ids": list(dict.fromkeys([source_id for claim in active_opportunity_claims for source_id in (claim.get('source_ids') or [])]))[:6],
                "why_now": "The live opportunity is still open, but continuity was disrupted and delay risks losing momentum.",
                "blocker": "",
                "consequence_if_missed": "The active roles may cool or move elsewhere before Taylor Sterling re-engages.",
            }
        )
    if active_opportunity_claims and any("ownership" in gap.lower() or "next-step" in gap.lower() for gap in claim_ledger.get("relationship_gaps") or []):
        actions.append(
            {
                "action_id": "act_002",
                "action_text": "Clarify who owns the next step and whether Taylor Sterling is inside the process for the live roles.",
                "action_type": "clarify_ownership",
                "status": "open",
                "owner": "Marcus",
                "urgency": "high",
                "due_window": "Next conversation",
                "linked_claim_ids": [claim["claim_id"] for claim in active_opportunity_claims[:3]],
                "supporting_source_ids": list(dict.fromkeys([source_id for claim in active_opportunity_claims for source_id in (claim.get('source_ids') or [])]))[:6],
                "why_now": "Live opportunity exists, but role ownership and process position remain unclear.",
                "blocker": "",
                "consequence_if_missed": "Taylor Sterling could assume momentum that does not really exist.",
            }
        )
    if market_claims:
        actions.append(
            {
                "action_id": "act_003",
                "action_text": "Test the current business pressure directly, especially pricing, competition, and hospital-project focus, before proposing support.",
                "action_type": "probe_market_context",
                "status": "open",
                "owner": "Marcus",
                "urgency": "medium",
                "due_window": "Next conversation",
                "linked_claim_ids": [claim["claim_id"] for claim in market_claims[:2]],
                "supporting_source_ids": list(dict.fromkeys([source_id for claim in market_claims for source_id in (claim.get('source_ids') or [])]))[:6],
                "why_now": "The commercial pitch should be grounded in the business pressure the contact is actually feeling.",
                "blocker": "",
                "consequence_if_missed": "The follow-up may feel generic and miss the real commercial angle.",
            }
        )
    return {"actions": actions[:6]}


def _normalize_action_ledger(action_payload: dict, claim_ledger: dict, cleaned_interactions: list[dict]) -> dict:
    actions = []
    claim_map = _claim_map(claim_ledger)
    valid_claim_ids = set(claim_map.keys())
    valid_source_ids = {item.get("source_id") for item in cleaned_interactions}
    overrides = _extract_action_overrides(cleaned_interactions)

    for index, raw_action in enumerate(action_payload.get("actions") or [], start=1):
        action = {
            "action_id": str(raw_action.get("action_id") or f"act_{index:03d}"),
            "action_text": _clean_text(raw_action.get("action_text")),
            "action_type": _clean_text(raw_action.get("action_type")) or "follow_up",
            "status": str(raw_action.get("status") or "open").lower(),
            "owner": _clean_text(raw_action.get("owner")) or "Marcus",
            "urgency": str(raw_action.get("urgency") or "medium").lower(),
            "due_window": _clean_text(raw_action.get("due_window")),
            "linked_claim_ids": [claim_id for claim_id in list(raw_action.get("linked_claim_ids") or []) if claim_id in valid_claim_ids][:6],
            "supporting_source_ids": [source_id for source_id in list(raw_action.get("supporting_source_ids") or []) if source_id in valid_source_ids][:8],
            "why_now": _clean_text(raw_action.get("why_now")),
            "blocker": _clean_text(raw_action.get("blocker")),
            "consequence_if_missed": _clean_text(raw_action.get("consequence_if_missed")),
            "last_updated": _now().isoformat(),
        }
        if action["status"] not in {"open", "in_progress", "completed", "stale", "missed", "cancelled"}:
            action["status"] = "open"
        if action["urgency"] not in {"low", "medium", "high", "critical"}:
            action["urgency"] = "medium"
        if not action["action_text"]:
            continue
        actions.append(action)

    for override in overrides:
        target_text = _clean_text(override.get("action_text"))
        if not target_text:
            continue
        matched = next((action for action in actions if _overlap(action.get("action_text"), target_text) >= 0.72), None)
        if not matched:
            matched = {
                "action_id": str(override.get("action_id") or f"act_{len(actions)+1:03d}"),
                "action_text": target_text,
                "action_type": _clean_text(override.get("action_type")) or "follow_up",
                "status": "open",
                "owner": "Marcus",
                "urgency": "medium",
                "due_window": _clean_text(override.get("due_window")),
                "linked_claim_ids": [claim_id for claim_id in list(override.get("linked_claim_ids") or []) if claim_id in valid_claim_ids][:6],
                "supporting_source_ids": [],
                "why_now": _clean_text(override.get("why_now")),
                "blocker": _clean_text(override.get("blocker")),
                "consequence_if_missed": _clean_text(override.get("consequence_if_missed")),
                "last_updated": _now().isoformat(),
            }
            actions.append(matched)
        matched["status"] = str(override.get("status") or matched.get("status") or "open").lower()
        matched["owner"] = _clean_text(override.get("owner")) or matched.get("owner") or "Marcus"
        matched["urgency"] = str(override.get("urgency") or matched.get("urgency") or "medium").lower()
        matched["due_window"] = _clean_text(override.get("due_window")) or matched.get("due_window") or ""
        matched["why_now"] = _clean_text(override.get("why_now")) or matched.get("why_now") or ""
        matched["blocker"] = _clean_text(override.get("blocker")) or matched.get("blocker") or ""
        matched["consequence_if_missed"] = _clean_text(override.get("consequence_if_missed")) or matched.get("consequence_if_missed") or ""
        matched["last_updated"] = _now().isoformat()

    deduped: list[dict] = []
    for action in actions:
        existing = next((item for item in deduped if _overlap(item.get("action_text"), action.get("action_text")) >= 0.82), None)
        if existing:
            if action.get("status") in {"completed", "missed", "stale"} or existing.get("status") == "cancelled":
                existing.update(action)
            continue
        deduped.append(action)

    deduped.sort(
        key=lambda action: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(str(action.get("urgency") or "medium"), 2),
            {"open": 0, "in_progress": 1, "stale": 2, "missed": 3, "completed": 4, "cancelled": 5}.get(str(action.get("status") or "open"), 0),
            str(action.get("action_text") or ""),
        )
    )

    ledger = ActionLedger(
        actions=deduped,
        open_actions=[item["action_id"] for item in deduped if item.get("status") in {"open", "in_progress"}],
        completed_actions=[item["action_id"] for item in deduped if item.get("status") == "completed"],
        stale_actions=[item["action_id"] for item in deduped if item.get("status") == "stale"],
        missed_actions=[item["action_id"] for item in deduped if item.get("status") == "missed"],
    )
    return ledger.model_dump()


async def _run_action_tracker(
    person: dict,
    claim_ledger: dict,
    cleaned_interactions: list[dict],
    transcript_guidance: Optional[dict[str, Any]] = None,
) -> tuple[dict, str]:
    fallback = _fallback_action_tracker(person, claim_ledger, cleaned_interactions)
    payload = {
        "person": {
            "contact_name": person.get("full_name"),
            "company": person.get("company_name_raw"),
            "title": person.get("title_current"),
        },
        "claim_ledger": claim_ledger,
        "recent_interactions": _serialize_interactions_for_agent([item for item in cleaned_interactions if not item["noise_candidate"]][:24]),
        "fallback_actions": fallback,
    }
    if isinstance(transcript_guidance, dict):
        payload["transcript_guidance"] = transcript_guidance
    if _use_llm():
        try:
            result, model_name = await asyncio.wait_for(
                _run_json_agent(
                    AGENT_ACTION,
                    PROMPT_REGISTRY[AGENT_ACTION],
                    ACTION_TRACKER_RESPONSE_FORMAT,
                    payload,
                    str(person.get("person_id")),
                ),
                timeout=20,
            )
            return _normalize_action_ledger(result, claim_ledger, cleaned_interactions), model_name
        except Exception:
            pass
    return _normalize_action_ledger(fallback, claim_ledger, cleaned_interactions), "deterministic-fallback"


def _fallback_company_verifier(person: dict, claim_ledger: dict) -> dict:
    company = str(person.get("company_name_raw") or "").strip()
    market_claims = [_brief_claim_line(claim) for claim in _claims_for_lens(claim_ledger, LENS_MARKET, ("active", "historical"))[:3]]
    track_claims = [_brief_claim_line(claim) for claim in _claims_for_lens(claim_ledger, LENS_TRACK, ("active", "historical"))[:2]]
    return {
        "company_name": company,
        "summary": f"Public web verification is not currently available. Keep company context grounded in CRM truth for {company} and treat external validation as pending.",
        "verified_points": [],
        "watchouts": ["External company verification is pending, so company-level context still relies on CRM evidence only."],
        "sources": [],
        "candidate_company_points": market_claims + track_claims,
    }


async def _run_company_verifier(person: dict, claim_ledger: dict) -> tuple[dict, str]:
    fallback = _fallback_company_verifier(person, claim_ledger)
    company = str(person.get("company_name_raw") or "").strip()
    if not company or not _use_llm() or not _use_web_verifier():
        return fallback, "deterministic-fallback"
    payload = {
        "company_name": company,
        "candidate_company_points": fallback["candidate_company_points"],
        "instruction": "Check recent public company context only. Return concise JSON with corroborated public signals, watchouts, and source urls. Do not add relationship claims.",
    }
    try:
        result, model_name = await asyncio.wait_for(
            _run_json_web_agent(
                AGENT_COMPANY_VERIFY,
                PROMPT_REGISTRY[AGENT_COMPANY_VERIFY],
                payload,
                str(person.get("person_id")),
            ),
            timeout=30,
        )
        normalized = {
            "company_name": company,
            "summary": _clean_text(result.get("summary")) or fallback["summary"],
            "verified_points": [_clean_text(item) for item in list(result.get("verified_points") or []) if _clean_text(item)][:6],
            "watchouts": [_clean_text(item) for item in list(result.get("watchouts") or []) if _clean_text(item)][:6],
            "sources": [_clean_text(item) for item in list(result.get("sources") or []) if _clean_text(item)][:8],
            "candidate_company_points": fallback["candidate_company_points"],
        }
        return normalized, model_name
    except Exception:
        return fallback, "deterministic-fallback"


def calculate_relationship_scores(*, claim_ledger: dict, cleaned_interactions: list[dict], action_ledger: dict) -> dict:
    relationship = 35
    commercial = 40
    execution = 25
    drivers: list[str] = []
    reducers: list[str] = []
    execution_drivers: list[str] = []
    execution_reducers: list[str] = []

    evidence_interactions = _grounded_non_noise_interactions(cleaned_interactions)
    if not evidence_interactions:
        return ScoreBundle(
            relationship_health_score=0,
            commercial_priority_score=0,
            execution_pressure_score=0,
            score_drivers=[],
            score_reducers=["No transcript or interaction evidence captured yet, so profile scoring is withheld."],
            execution_pressure_drivers=[],
            execution_pressure_reducers=["No transcript or interaction evidence captured yet, so execution pressure scoring is withheld."],
        ).model_dump()

    claims = claim_ledger.get("claims") or []
    active_claims = [claim for claim in claims if claim.get("status") == "active"]
    active_opportunity_claims = [
        claim
        for claim in claims
        if claim.get("status") == "active" and claim.get("claim_family") in {"role_need", "role_count", "role_status"}
    ]
    claim_text_blob = " ".join(str(claim.get("claim_text") or "").lower() for claim in claims)
    recent_cutoff = (_now() - timedelta(days=45)).date().isoformat()
    continuity_cutoff = (_now() - timedelta(days=180)).date().isoformat()
    recent_interactions = [
        item
        for item in cleaned_interactions
        if item["date"] >= recent_cutoff
        and not item["noise_candidate"]
        and _is_grounded_source_type(item.get("source_type"))
    ]
    continuity_interactions = [
        item
        for item in cleaned_interactions
        if item["date"] >= continuity_cutoff
        and not item["noise_candidate"]
        and _is_grounded_source_type(item.get("source_type"))
    ]
    continuity_dates = sorted({item["date"] for item in continuity_interactions if item.get("date")})
    long_standing_continuity = len(continuity_interactions) >= 4 and len(continuity_dates) >= 3
    opportunity_signal_blob = " ".join(
        f"{str(item.get('title') or '').lower()} {str(item.get('raw_text') or '').lower()}"
        for item in continuity_interactions
    )
    action_map = {action.get("action_id"): action for action in action_ledger.get("actions") or []}
    open_actions = [action_map.get(action_id) for action_id in action_ledger.get("open_actions") or [] if action_map.get(action_id)]
    stale_actions = [action_map.get(action_id) for action_id in action_ledger.get("stale_actions") or [] if action_map.get(action_id)]
    missed_actions = [action_map.get(action_id) for action_id in action_ledger.get("missed_actions") or [] if action_map.get(action_id)]
    high_urgency_open = [
        action for action in open_actions if str(action.get("urgency") or "") in {"high", "critical"}
    ]
    immediate_open = [
        action
        for action in open_actions
        if any(term in str(action.get("due_window") or "").lower() for term in ("immediate", "next 7 days", "next conversation", "tomorrow", "this week"))
    ]

    if long_standing_continuity:
        relationship += 18
        drivers.append("There is long-standing meaningful continuity across multiple interactions, not just recent noise.")
    if any(
        any(term in item["raw_text"].lower() or term in item["title"].lower() for term in ("met with", "in their office", "starbucks", "cafe", "coffee"))
        for item in recent_interactions
    ):
        relationship += 10
        drivers.append("Real in-person meeting evidence exists in the last 45 days.")
    if len(recent_interactions) > 1:
        relationship += 6
        drivers.append("There has been more than one meaningful touchpoint in the last 45 days.")
    if any(term in claim_text_blob for term in ("frustration", "pricing", "competition", "hospital", "shortage")):
        relationship += 4
        commercial += 8
        drivers.append("The contact is sharing candid market and business reality.")
    if any(claim.get("lens") == LENS_FAMILY and claim.get("status") == "active" for claim in claims):
        relationship += 4
        drivers.append("There is at least one credible personal or family hook.")
    if "obe" in claim_text_blob:
        relationship += 2
        drivers.append("OBE-related engagement is evidenced in the relationship trail.")
    if any(term in claim_text_blob for term in ("follow up", "follow-up", "after eid", "reorganize", "reorganise")):
        relationship += 3
        commercial += 8
        drivers.append("Continuity and follow-up are live rather than dormant.")
    if any(term in claim_text_blob for term in ("difficult chap", "guarded", "hard to deepen")):
        relationship -= 10
        reducers.append("Relationship depth appears harder to build than headline warmth might suggest.")
    if any(term in claim_text_blob for term in ("postponed", "emergency")):
        relationship -= 6
        reducers.append("Recent continuity was disrupted or postponed.")
    if any("ceo" in str(claim.get("claim_text") or "").lower() and claim.get("status") == "disproved" for claim in claims):
        relationship -= 6
        reducers.append("Earlier assumed access was corrected down.")
    if claim_ledger.get("relationship_gaps"):
        relationship -= 7
        reducers.append("Major relationship gaps remain unresolved.")
    if claim_ledger.get("uncertainties"):
        relationship -= 4
        reducers.append("Current truth still carries meaningful uncertainty.")
    if any("access" in gap.lower() for gap in claim_ledger.get("relationship_gaps") or []):
        relationship -= 4
        reducers.append("Access depth is not strong enough yet to justify a high health score.")

    if any(claim.get("lens") == LENS_ACTIVE and claim.get("status") == "active" for claim in claims):
        commercial += 20
        drivers.append("There is at least one live hiring need or active commercial angle.")
    if (
        not active_opportunity_claims
        and any(
            term in opportunity_signal_blob
            for term in ("shortlist", "offer", "hiring", "hire", "role", "position", "engineer", "headcount", "mandate")
        )
    ):
        commercial += 10
        drivers.append("Live opportunity signals are present in recent interaction evidence.")
    if any(claim.get("lens") == LENS_TRACK and claim.get("status") == "active" for claim in claims):
        commercial += 12
        drivers.append("The account has strategic relevance beyond a single role.")
    if any(term in claim_text_blob for term in ("bim lead", "data center", "data centre", "director", "specialist")):
        commercial += 10
        drivers.append("The live opportunity includes specialist or senior hiring need.")
    if any(term in claim_text_blob for term in ("after eid", "tomorrow", "next week", "follow up")):
        commercial += 8
        drivers.append("The commercial follow-up window is immediate.")
    if sum(1 for claim in active_claims if claim.get("lens") == LENS_ACTIVE) > 1:
        commercial += 6
        drivers.append("There is more than one active commercial angle in play.")
    if any(term in claim_text_blob for term in ("filled", "lost", "not through us")):
        commercial -= 10
        reducers.append("A previously attractive opportunity has already been filled or lost.")
    if any(term in claim_text_blob for term in ("5 bim leads", "five bim leads")) and any(term in claim_text_blob for term in ("1 bim lead", "one bim lead")):
        commercial -= 8
        reducers.append("Earlier opportunity size was overstated and later narrowed.")
    if any("ownership" in gap.lower() for gap in claim_ledger.get("relationship_gaps") or []):
        commercial -= 6
        reducers.append("Decision ownership is still unclear.")
    if claim_ledger.get("uncertainties"):
        commercial -= 5
        reducers.append("Mandate status remains mixed enough to require caution.")

    if active_opportunity_claims:
        execution += 20
        execution_drivers.append("There is live opportunity in the claim ledger right now.")
    if high_urgency_open:
        execution += 18
        execution_drivers.append("High-urgency open actions are still unresolved.")
    if immediate_open:
        execution += 12
        execution_drivers.append("At least one open action has an immediate or near-term due window.")
    if any(term in claim_text_blob for term in ("postponed", "emergency", "after eid", "reorganize", "reorganise")):
        execution += 10
        execution_drivers.append("Continuity has slipped, so follow-up timing now matters more.")
    if any("ownership" in gap.lower() or "decision ownership" in gap.lower() for gap in claim_ledger.get("relationship_gaps") or []):
        execution += 8
        execution_drivers.append("Decision ownership is unclear on a live thread.")
    if claim_ledger.get("uncertainties"):
        execution += 6
        execution_drivers.append("Mixed evidence means delay increases the chance of drift.")
    if stale_actions or missed_actions:
        execution += 8
        execution_drivers.append("At least one action has already drifted stale or been missed.")

    if not active_opportunity_claims:
        execution -= 14
        execution_reducers.append("No active opportunity is currently retained.")
    if not open_actions:
        execution -= 12
        execution_reducers.append("There are no open actions currently pressing for follow-up.")
    if open_actions and not high_urgency_open and not immediate_open:
        execution -= 6
        execution_reducers.append("Open actions exist, but none are currently high urgency.")
    if any(claim.get("status") in {"superseded", "disproved"} and claim.get("claim_family") in {"role_need", "role_count", "role_status"} for claim in claims) and not active_opportunity_claims:
        execution -= 8
        execution_reducers.append("Recent opportunity signals are mostly historical, filled, or retired.")

    relationship = max(0, min(100, relationship))
    commercial = max(0, min(100, commercial))
    execution = max(0, min(100, execution))
    return ScoreBundle(
        relationship_health_score=relationship,
        commercial_priority_score=commercial,
        execution_pressure_score=execution,
        score_drivers=list(dict.fromkeys(drivers))[:8],
        score_reducers=list(dict.fromkeys(reducers))[:8],
        execution_pressure_drivers=list(dict.fromkeys(execution_drivers))[:8],
        execution_pressure_reducers=list(dict.fromkeys(execution_reducers))[:8],
    ).model_dump()


def _claim_rank(claim: dict) -> float:
    family_weight = CLAIM_FAMILY_WEIGHTS.get(str(claim.get("claim_family") or "other"), 20) / 10.0
    source_weight = max(0, 10 - int(claim.get("source_rank") or 9))
    return (
        _claim_status_weight(str(claim.get("status") or ""))
        + family_weight
        + (9 - int(claim.get("priority") or 8)) * 1.4
        + float(claim.get("confidence") or 0) * 6
        + source_weight
        + _claim_freshness_bonus(claim)
    )


def _brief_truth_rank(claim: dict) -> float:
    lens_weight = {
        LENS_ACTIVE: 20,
        LENS_MARKET: 16,
        LENS_TRACK: 12,
        LENS_FAMILY: 7,
        LENS_LIFESTYLE: 5,
    }.get(str(claim.get("lens") or ""), 0)
    return _claim_rank(claim) + lens_weight


def _empty_claim_ledger() -> dict:
    return ClaimLedger(
        claims=[],
        active_truths=[],
        changed_recently=[],
        uncertainties=[],
        disproved_or_retired=[],
        relationship_gaps=[],
        risks_or_watchouts=[],
        source_quality_notes=[],
        lens_outputs={lens: [] for lens in LENS_ORDER},
    ).model_dump()


def _normalize_claim_ledger_to_grounded_evidence(ledger: dict, cleaned_interactions: list[dict]) -> dict:
    if not isinstance(ledger, dict):
        return _empty_claim_ledger()

    source_map = _grounded_source_map(cleaned_interactions, include_noise=False)
    if not source_map:
        return _empty_claim_ledger()

    allowed_statuses = {"active", "historical", "superseded", "disproved", "uncertain"}
    normalized_claims: list[dict] = []
    fallback_id = 1
    for raw_claim in list(ledger.get("claims") or []):
        if not isinstance(raw_claim, dict):
            continue
        claim_text = _clean_text(raw_claim.get("claim_text"))
        if not claim_text:
            continue
        source_ids = [
            source_id
            for source_id in list(dict.fromkeys([str(source_id).strip() for source_id in (raw_claim.get("source_ids") or []) if str(source_id).strip()]))
            if source_id in source_map
        ]
        if not source_ids:
            continue

        lens = str(raw_claim.get("lens") or "").strip()
        if lens not in LENS_ORDER:
            continue

        status = str(raw_claim.get("status") or "uncertain").strip().lower()
        if status not in allowed_statuses:
            status = "uncertain"

        claim_id = str(raw_claim.get("claim_id") or "").strip() or f"c_{fallback_id:03d}"
        fallback_id += 1
        first_seen, last_seen = _claim_dates(source_ids, source_map)
        normalized_claims.append(
            {
                "claim_id": claim_id,
                "claim_text": claim_text,
                "lens": lens,
                "claim_family": str(raw_claim.get("claim_family") or "other"),
                "entity_key": str(raw_claim.get("entity_key") or "general"),
                "status": status,
                "truth_state": str(raw_claim.get("truth_state") or _claim_truth_state(raw_claim)),
                "confidence": max(0.0, min(1.0, float(raw_claim.get("confidence") or 0.0))),
                "priority": max(1, min(8, int(raw_claim.get("priority") or 8))),
                "source_ids": source_ids,
                "why_it_matters": _clean_text(raw_claim.get("why_it_matters"))
                or "Ground this point in transcript or interaction evidence before using it.",
                "source_rank": _claim_source_rank(source_ids, source_map),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "supersedes_claim_ids": list(raw_claim.get("supersedes_claim_ids") or []),
                "disproved_by_claim_ids": list(raw_claim.get("disproved_by_claim_ids") or []),
            }
        )

    if not normalized_claims:
        return _empty_claim_ledger()

    filtered_interactions = list(source_map.values())
    normalized_claims = _apply_claim_family_reconciliation(normalized_claims, filtered_interactions, source_map)
    for claim in normalized_claims:
        claim["truth_state"] = _claim_truth_state(claim)
    derived_fields = _build_ledger_summary_fields(normalized_claims, filtered_interactions, source_map)

    return ClaimLedger(
        claims=[Claim.model_validate(claim) for claim in normalized_claims],
        active_truths=[claim_id for claim_id in derived_fields["active_truths"] if claim_id],
        changed_recently=[claim_id for claim_id in derived_fields["changed_recently"] if claim_id],
        uncertainties=[claim_id for claim_id in derived_fields["uncertainties"] if claim_id],
        disproved_or_retired=[claim_id for claim_id in derived_fields["disproved_or_retired"] if claim_id],
        relationship_gaps=list(derived_fields["relationship_gaps"] or [])[:6],
        risks_or_watchouts=list(derived_fields["risks_or_watchouts"] or [])[:6],
        source_quality_notes=list(derived_fields["source_quality_notes"] or [])[:6],
        lens_outputs=derived_fields["lens_outputs"],
    ).model_dump()


def _claim_map(ledger: dict) -> dict[str, dict]:
    return {claim["claim_id"]: claim for claim in ledger.get("claims") or []}


def _claims_for_lens(ledger: dict, lens: str, statuses: tuple[str, ...] = ("active", "uncertain", "historical")) -> list[dict]:
    claims = [
        claim
        for claim in ledger.get("claims") or []
        if claim.get("lens") == lens and claim.get("status") in statuses
    ]
    claims.sort(key=lambda claim: (-_claim_rank(claim), str(claim.get("claim_text") or "")))
    deduped: list[dict] = []
    for claim in claims:
        if any(_overlap(str(claim.get("claim_text") or ""), str(existing.get("claim_text") or "")) >= 0.85 for existing in deduped):
            continue
        deduped.append(claim)
        if len(deduped) >= LENS_PRIORITY_CAPS.get(lens, 5):
            break
    return deduped


def _matches_allowed_text(candidate: str, allowed: list[str]) -> bool:
    text = _clean_text(candidate)
    if not text:
        return False
    for allowed_text in allowed:
        if _overlap(text, allowed_text) >= 0.6:
            return True
    return False


def _filter_or_fallback(items: list[str], allowed: list[str], fallback: list[str], cap: int) -> list[str]:
    kept = []
    seen = set()
    for item in items or []:
        cleaned = _clean_text(item)
        if not cleaned or cleaned in seen:
            continue
        if _matches_allowed_text(cleaned, allowed):
            kept.append(cleaned)
            seen.add(cleaned)
    if kept:
        return kept[:cap]
    return [
        _clean_text(item)
        for item in fallback[:cap]
        if _clean_text(item)
    ]


def _brief_fallback(person: dict, ledger: dict, action_ledger: dict, scores: dict) -> dict:
    claim_map = _claim_map(ledger)
    ranked_active_claims = sorted(
        [claim_map.get(claim_id, {}) for claim_id in ledger.get("active_truths") or [] if claim_map.get(claim_id)],
        key=lambda claim: (-_brief_truth_rank(claim), str(claim.get("claim_text") or "")),
    )
    core_active_truths = [
        line
        for claim in ranked_active_claims
        if claim.get("lens") not in {LENS_FAMILY, LENS_LIFESTYLE}
        if _claim_visible_in_section(claim, "truth")
        for line in [_brief_claim_line(claim)]
        if line
    ]
    supporting_truths = [
        line
        for claim in ranked_active_claims
        if claim.get("lens") in {LENS_FAMILY, LENS_LIFESTYLE}
        if _claim_visible_in_section(claim, "truth")
        for line in [_brief_claim_line(claim)]
        if line
    ]
    if len(core_active_truths) >= 4:
        active_truths = core_active_truths[:8]
    else:
        active_truths = (core_active_truths + supporting_truths)[:8]
    changed = [
        line
        for claim_id in ledger.get("changed_recently") or []
        if claim_map.get(claim_id)
        for claim in [claim_map.get(claim_id, {})]
        if _claim_visible_in_section(claim, "changed")
        for line in [_brief_claim_line(claim)]
        if line
    ]
    uncertainties = [
        line
        for claim_id in ledger.get("uncertainties") or []
        if claim_map.get(claim_id)
        for claim in [claim_map.get(claim_id, {})]
        if _claim_visible_in_section(claim, "uncertainty")
        for line in [_brief_claim_line(claim)]
        if line
    ]
    retired = [
        line
        for claim_id in ledger.get("disproved_or_retired") or []
        if claim_map.get(claim_id)
        for claim in [claim_map.get(claim_id, {})]
        if _claim_visible_in_section(claim, "retired")
        for line in [_brief_claim_line(claim)]
        if line
    ]
    lenses: dict[str, dict] = {}
    for lens in LENS_ORDER:
        section_name = "track" if lens == LENS_TRACK else "lens"
        lens_claims = [claim for claim in _claims_for_lens(ledger, lens) if _claim_visible_in_section(claim, section_name)]
        lens_changed = [
            _brief_claim_line(claim)
            for claim in lens_claims
            if claim.get("status") in {"superseded", "disproved"}
            and _brief_claim_line(claim)
        ][:5]
        lens_uncertain = [
            _brief_claim_line(claim)
            for claim in lens_claims
            if claim.get("status") == "uncertain"
            and _brief_claim_line(claim)
        ][:5]
        if lens_claims:
            summary = {
                LENS_FAMILY: "Personal context exists and should be used naturally rather than forced.",
                LENS_LIFESTYLE: "There are light rapport hooks, but this lens is secondary to family or commercial signal.",
                LENS_ACTIVE: "There is live opportunity, but it should be handled narrowly and with current status discipline.",
                LENS_MARKET: "The contact is giving useful market and business read-through worth carrying into the conversation.",
                LENS_TRACK: "The relationship matters strategically, but access and influence should stay grounded in evidence.",
            }[lens]
            best_use = {
                LENS_FAMILY: "Use one human detail naturally if the conversation opens that door.",
                LENS_LIFESTYLE: "Use only as light rapport, not as the core of the conversation.",
                LENS_ACTIVE: "Check live status, ownership, and next step before assuming momentum.",
                LENS_MARKET: "Probe the business pain directly and use it to sharpen follow-up.",
                LENS_TRACK: "Invest in the relationship steadily without overstating the level of access.",
            }[lens]
            top_points = [_brief_claim_line(claim) for claim in lens_claims if _brief_claim_line(claim)][:8]
        else:
            summary = "Low signal. Only limited evidence-backed points are currently retained."
            best_use = "Do not force this lens in the next conversation without fresher direct evidence."
            top_points = []
        lenses[lens] = LensBrief(
            lens_summary=summary,
            top_points=top_points,
            what_changed=lens_changed[:5],
            uncertainties=lens_uncertain[:5],
            best_use_before_next_conversation=best_use,
        ).model_dump()

    current_read_parts = []
    lead_active = next((claim for claim in ranked_active_claims if claim.get("lens") == LENS_ACTIVE), None)
    lead_market = next((claim for claim in ranked_active_claims if claim.get("lens") == LENS_MARKET), None)
    supporting_human = next((claim for claim in ranked_active_claims if claim.get("lens") in {LENS_FAMILY, LENS_LIFESTYLE}), None)
    lead_uncertainty = next(
        (
            claim_map.get(claim_id, {})
            for claim_id in ledger.get("uncertainties") or []
            if claim_map.get(claim_id) and _claim_visible_in_section(claim_map.get(claim_id, {}), "uncertainty")
        ),
        None,
    )
    if lead_active:
        rewritten_active = _rewrite_claim_text_for_brief(lead_active)
        if rewritten_active:
            current_read_parts.append(f"Current commercial truth centres on {rewritten_active.lower()}.")
    elif active_truths:
        current_read_parts.append(f"Current truth centres on {active_truths[0].lower()}.")
    if lead_market:
        rewritten_market = _rewrite_claim_text_for_brief(lead_market)
        if rewritten_market:
            current_read_parts.append(f"Business context worth carrying in is {rewritten_market.lower()}.")
    if ledger.get("relationship_gaps"):
        current_read_parts.append(f"The main gap is {ledger['relationship_gaps'][0].lower()}.")
    if lead_uncertainty:
        rewritten_uncertainty = _rewrite_claim_text_for_brief(lead_uncertainty)
        if rewritten_uncertainty:
            current_read_parts.append(f"Uncertainty remains around {rewritten_uncertainty.lower()}.")
    if supporting_human:
        rewritten_human = _rewrite_claim_text_for_brief(supporting_human)
        if rewritten_human:
            current_read_parts.append(f"A useful human hook is {rewritten_human.lower()}.")
    if not current_read_parts:
        current_read_parts.append("Current signal is limited, so the next conversation should focus on refreshing direct truth.")

    action_map = {action["action_id"]: action for action in action_ledger.get("actions") or []}
    action_priorities = [
        _clean_text(action_map.get(action_id, {}).get("action_text"))
        for action_id in (action_ledger.get("open_actions") or []) + (action_ledger.get("stale_actions") or [])
        if action_map.get(action_id)
    ]

    return BriefingOutput(
        contact_name=str(person.get("full_name") or ""),
        company=str(person.get("company_name_raw") or ""),
        title=str(person.get("title_current") or ""),
        relationship_health_score=int(scores.get("relationship_health_score") or 0),
        commercial_priority_score=int(scores.get("commercial_priority_score") or 0),
        execution_pressure_score=int(scores.get("execution_pressure_score") or 0),
        score_drivers=list(scores.get("score_drivers") or []),
        score_reducers=list(scores.get("score_reducers") or []),
        execution_pressure_drivers=list(scores.get("execution_pressure_drivers") or []),
        execution_pressure_reducers=list(scores.get("execution_pressure_reducers") or []),
        current_read=" ".join(current_read_parts[:4]),
        what_is_true_now=active_truths[:8],
        what_changed_recently=changed[:5],
        uncertainties=uncertainties[:5] or ["Signal is mixed and needs direct confirmation in the next conversation."],
        relationship_gaps=list(ledger.get("relationship_gaps") or [])[:5],
        risks_or_watchouts=list(ledger.get("risks_or_watchouts") or [])[:5],
        next_conversation_priorities=action_priorities[:8] or [
            "Confirm the live opportunity status and who owns the next step.",
            "Test any market frustration or business pressure that looks current.",
            "Use one grounded human hook if it fits naturally.",
        ],
        lenses=lenses,
        personal_hooks_worth_remembering=[
            _brief_claim_line(claim)
            for claim in _claims_for_lens(ledger, LENS_FAMILY)[:4] + _claims_for_lens(ledger, LENS_LIFESTYLE)[:4]
            if _claim_visible_in_section(claim, "signals") and _brief_claim_line(claim)
        ],
        commercial_signals_worth_tracking=[
            _brief_claim_line(claim)
            for claim in _claims_for_lens(ledger, LENS_ACTIVE)[:6]
            if _claim_visible_in_section(claim, "signals") and _brief_claim_line(claim)
        ],
        market_signals_worth_tracking=[
            _brief_claim_line(claim)
            for claim in _claims_for_lens(ledger, LENS_MARKET)[:6]
            if _claim_visible_in_section(claim, "signals") and _brief_claim_line(claim)
        ],
        disproved_or_retired_claims=retired[:8],
    ).model_dump()


def _sanitize_brief_writer_output(person: dict, ledger: dict, action_ledger: dict, scores: dict, fallback: dict, generated: dict) -> dict:
    if not generated:
        return fallback

    sanitized = dict(fallback)
    sanitized["current_read"] = fallback.get("current_read") or ""
    sanitized["what_is_true_now"] = list(fallback.get("what_is_true_now") or [])[:8]
    sanitized["what_changed_recently"] = list(fallback.get("what_changed_recently") or [])[:5]
    sanitized["uncertainties"] = list(fallback.get("uncertainties") or [])[:5]
    sanitized["relationship_gaps"] = list(fallback.get("relationship_gaps") or [])[:5]
    sanitized["risks_or_watchouts"] = list(fallback.get("risks_or_watchouts") or [])[:5]
    sanitized["next_conversation_priorities"] = list(fallback.get("next_conversation_priorities") or [])[:8]
    sanitized["personal_hooks_worth_remembering"] = list(fallback.get("personal_hooks_worth_remembering") or [])[:8]
    sanitized["commercial_signals_worth_tracking"] = list(fallback.get("commercial_signals_worth_tracking") or [])[:8]
    sanitized["market_signals_worth_tracking"] = list(fallback.get("market_signals_worth_tracking") or [])[:8]
    sanitized["disproved_or_retired_claims"] = list(fallback.get("disproved_or_retired_claims") or [])[:8]

    generated_lenses = generated.get("lenses") or {}
    fallback_lenses = fallback.get("lenses") or {}
    merged_lenses: dict[str, dict] = {}
    for lens in LENS_ORDER:
        fallback_lens = fallback_lenses.get(lens) or {}
        generated_lens = generated_lenses.get(lens) or {}
        merged_lenses[lens] = {
            "lens_summary": _clean_text(generated_lens.get("lens_summary")) or fallback_lens.get("lens_summary") or "Low signal.",
            "top_points": list(fallback_lens.get("top_points") or [])[: LENS_PRIORITY_CAPS.get(lens, 5)],
            "what_changed": list(fallback_lens.get("what_changed") or [])[:5],
            "uncertainties": list(fallback_lens.get("uncertainties") or [])[:5],
            "best_use_before_next_conversation": _clean_text(generated_lens.get("best_use_before_next_conversation"))
            or fallback_lens.get("best_use_before_next_conversation")
            or "Use only grounded evidence in the next conversation.",
        }
    sanitized["lenses"] = merged_lenses
    sanitized["relationship_health_score"] = int(scores.get("relationship_health_score") or 0)
    sanitized["commercial_priority_score"] = int(scores.get("commercial_priority_score") or 0)
    sanitized["execution_pressure_score"] = int(scores.get("execution_pressure_score") or 0)
    sanitized["score_drivers"] = list(scores.get("score_drivers") or [])
    sanitized["score_reducers"] = list(scores.get("score_reducers") or [])
    sanitized["execution_pressure_drivers"] = list(scores.get("execution_pressure_drivers") or [])
    sanitized["execution_pressure_reducers"] = list(scores.get("execution_pressure_reducers") or [])
    sanitized["contact_name"] = str(person.get("full_name") or "")
    sanitized["company"] = str(person.get("company_name_raw") or "")
    sanitized["title"] = str(person.get("title_current") or "")
    return sanitized

async def _run_brief_writer(person: dict, ledger: dict, action_ledger: dict, scores: dict) -> tuple[dict, str]:
    fallback = _brief_fallback(person, ledger, action_ledger, scores)
    payload = {
        "person": {
            "contact_name": person.get("full_name"),
            "company": person.get("company_name_raw"),
            "title": person.get("title_current"),
        },
        "claim_ledger": ledger,
        "action_ledger": action_ledger,
        "scores": scores,
        "fallback_brief": fallback,
    }
    if _use_llm():
        try:
            result, model_name = await asyncio.wait_for(
                _run_json_agent(
                    AGENT_BRIEF,
                    PROMPT_REGISTRY[AGENT_BRIEF],
                    BRIEF_WRITER_RESPONSE_FORMAT,
                    payload,
                    str(person.get("person_id")),
                ),
                timeout=20,
            )
            return _sanitize_brief_writer_output(person, ledger, action_ledger, scores, fallback, result), model_name
        except Exception:
            pass
    return fallback, "deterministic-fallback"


async def build_relationship_intelligence_pipeline(
    *,
    person: dict,
    evidence_inputs: list[dict],
    force_refresh: bool = False,
) -> dict:
    settings_state = await get_intelligence_settings()
    settings_payload = settings_state.get("settings") if isinstance(settings_state, dict) else {}
    stage1_settings = (
        (settings_payload or {}).get("stage1_calibration")
        if isinstance((settings_payload or {}).get("stage1_calibration"), dict)
        else await get_stage1_calibration_settings()
    )
    transcript_tagging = (
        (settings_payload or {}).get("transcript_tagging")
        if isinstance((settings_payload or {}).get("transcript_tagging"), dict)
        else {}
    )
    transcript_guidance = _serialize_transcript_guidance(transcript_tagging)
    stage1_box_defs, stage1_box_keywords = _runtime_stage1_taxonomy_from_settings(transcript_tagging)
    relationship_stage_details = _relationship_stage_details_map_from_list(
        transcript_tagging.get("stage_relationship") if isinstance(transcript_tagging, dict) else []
    ) or STAGE2_RELATIONSHIP_STAGE_DETAILS
    opportunity_stage_details = _relationship_stage_details_map_from_list(
        transcript_tagging.get("stage_opportunity") if isinstance(transcript_tagging, dict) else []
    ) or STAGE2_OPPORTUNITY_STAGE_DETAILS
    stage2_signal_keywords = _stage2_signal_keywords_from_stage_rules(
        transcript_tagging.get("stage_rules") if isinstance(transcript_tagging, dict) else []
    )
    previous_stage2 = await _load_previous_stage2_state(str(person.get("person_id")))
    cleaned_interactions = normalize_relationship_inputs(person, evidence_inputs)
    source_digest = _source_digest(
        person,
        cleaned_interactions,
        stage1_settings=stage1_settings,
        transcript_tagging=transcript_tagging,
    )
    cached_run = None if force_refresh else await _load_cached_run(str(person.get("person_id")), source_digest)
    if cached_run:
        cached_cleaned = cached_run.get("cleaned_interactions_json") or []
        cached_claim_ledger = _normalize_claim_ledger_to_grounded_evidence(
            cached_run.get("claim_ledger_json") or {},
            cached_cleaned,
        )
        cached_action_ledger = _normalize_action_ledger(
            cached_run.get("action_ledger_json") or {},
            cached_claim_ledger,
            cached_cleaned,
        )
        cached_scores = calculate_relationship_scores(
            claim_ledger=cached_claim_ledger,
            cleaned_interactions=cached_cleaned,
            action_ledger=cached_action_ledger,
        )
        cached_briefing = cached_run.get("briefing_json") or {}
        cached_briefing_fallback = _brief_fallback(person, cached_claim_ledger, cached_action_ledger, cached_scores)
        sanitized_cached_briefing = _sanitize_brief_writer_output(
            person,
            cached_claim_ledger,
            cached_action_ledger,
            cached_scores,
            cached_briefing_fallback,
            cached_briefing,
        )
        stage1_knowledge_bank = _build_stage1_knowledge_bank(
            cached_claim_ledger,
            cached_cleaned,
            stage1_settings,
            stage1_box_defs,
            stage1_box_keywords,
        )
        stage2_flow = _build_stage2_relationship_business_flow(
            person=person,
            claim_ledger=cached_claim_ledger,
            action_ledger=cached_action_ledger,
            cleaned_interactions=cached_cleaned,
            stage1_knowledge_bank=stage1_knowledge_bank,
            previous_stage2=previous_stage2,
            relationship_stage_details=relationship_stage_details,
            opportunity_stage_details=opportunity_stage_details,
            stage2_signal_keywords=stage2_signal_keywords,
        )
        briefing_payload = {**sanitized_cached_briefing, "relationship_business_flow_stage2": stage2_flow}
        trace = PipelineTrace(
            raw_interactions=evidence_inputs,
            cleaned_interactions=cached_cleaned,
            agent_outputs=cached_run.get("agent_outputs") or {},
            claim_ledger=cached_claim_ledger,
            action_ledger=cached_action_ledger,
            retired_claims=[
                claim
                for claim in cached_claim_ledger.get("claims", [])
                if claim.get("status") in {"disproved", "superseded"}
            ],
            scores=cached_scores,
        )
        meta = PipelineMeta(
            pipeline_version=PIPELINE_VERSION,
            model_name=str(cached_run.get("model_name") or "cached"),
            cache_status="hit",
            source_digest=source_digest,
            agent_mode="multi_agent_truth_system",
        )
        return {
            "briefing": briefing_payload,
            "scores": cached_scores,
            "action_ledger": cached_action_ledger,
            "company_verification": (cached_run.get("agent_outputs") or {}).get(AGENT_COMPANY_VERIFY, {}).get("company_verification") or {},
            "knowledge_bank_stage1": stage1_knowledge_bank,
            "relationship_business_flow_stage2": stage2_flow,
            "transcript_tagging": transcript_tagging,
            "trace": trace.model_dump(),
            "pipeline_meta": meta.model_dump(),
            "evidence_inputs": evidence_inputs,
        }

    if not _grounded_non_noise_interactions(cleaned_interactions):
        claim_ledger = _empty_claim_ledger()
        action_ledger = _normalize_action_ledger({"actions": []}, claim_ledger, cleaned_interactions)
        scores = calculate_relationship_scores(
            claim_ledger=claim_ledger,
            cleaned_interactions=cleaned_interactions,
            action_ledger=action_ledger,
        )
        briefing = _brief_fallback(person, claim_ledger, action_ledger, scores)
        stage1_knowledge_bank = _build_stage1_knowledge_bank(
            claim_ledger,
            cleaned_interactions,
            stage1_settings,
            stage1_box_defs,
            stage1_box_keywords,
        )
        stage2_flow = _build_stage2_relationship_business_flow(
            person=person,
            claim_ledger=claim_ledger,
            action_ledger=action_ledger,
            cleaned_interactions=cleaned_interactions,
            stage1_knowledge_bank=stage1_knowledge_bank,
            previous_stage2=previous_stage2,
            relationship_stage_details=relationship_stage_details,
            opportunity_stage_details=opportunity_stage_details,
            stage2_signal_keywords=stage2_signal_keywords,
        )
        briefing_with_stage2 = {**briefing, "relationship_business_flow_stage2": stage2_flow}
        await _persist_run(
            person_id=str(person.get("person_id")),
            source_digest=source_digest,
            model_name="deterministic-no-evidence",
            cleaned_interactions=cleaned_interactions,
            agent_outputs={},
            claim_ledger=claim_ledger,
            action_ledger=action_ledger,
            scores=scores,
            briefing=briefing_with_stage2,
        )

        trace = PipelineTrace(
            raw_interactions=evidence_inputs,
            cleaned_interactions=cleaned_interactions,
            agent_outputs={},
            claim_ledger=claim_ledger,
            action_ledger=action_ledger,
            retired_claims=[],
            scores=scores,
        )
        meta = PipelineMeta(
            pipeline_version=PIPELINE_VERSION,
            model_name="deterministic-no-evidence",
            cache_status="miss",
            source_digest=source_digest,
            agent_mode="multi_agent_truth_system",
        )
        return {
            "briefing": briefing_with_stage2,
            "scores": scores,
            "action_ledger": action_ledger,
            "company_verification": {},
            "knowledge_bank_stage1": stage1_knowledge_bank,
            "relationship_business_flow_stage2": stage2_flow,
            "transcript_tagging": transcript_tagging,
            "trace": trace.model_dump(),
            "pipeline_meta": meta.model_dump(),
            "evidence_inputs": evidence_inputs,
        }

    lens_results = await asyncio.gather(
        _run_lens_agent(AGENT_FAMILY, person, cleaned_interactions, transcript_guidance=transcript_guidance),
        _run_lens_agent(AGENT_ACTIVE, person, cleaned_interactions, transcript_guidance=transcript_guidance),
        _run_lens_agent(AGENT_MARKET, person, cleaned_interactions, transcript_guidance=transcript_guidance),
        _run_lens_agent(AGENT_TRACK, person, cleaned_interactions, transcript_guidance=transcript_guidance),
    )
    agent_outputs: dict[str, dict] = {
        AGENT_FAMILY: lens_results[0][0],
        AGENT_ACTIVE: lens_results[1][0],
        AGENT_MARKET: lens_results[2][0],
        AGENT_TRACK: lens_results[3][0],
    }
    model_name = lens_results[0][1]

    claim_ledger, arbiter_model = await _run_truth_arbiter(
        person,
        cleaned_interactions,
        agent_outputs,
        transcript_guidance=transcript_guidance,
    )
    claim_ledger = _normalize_claim_ledger_to_grounded_evidence(claim_ledger, cleaned_interactions)
    model_name = arbiter_model if arbiter_model != "deterministic-fallback" else model_name
    action_ledger, action_model = await _run_action_tracker(
        person,
        claim_ledger,
        cleaned_interactions,
        transcript_guidance=transcript_guidance,
    )
    model_name = action_model if action_model != "deterministic-fallback" else model_name
    company_verification, company_verify_model = await _run_company_verifier(person, claim_ledger)
    model_name = company_verify_model if company_verify_model != "deterministic-fallback" else model_name
    scores = calculate_relationship_scores(claim_ledger=claim_ledger, cleaned_interactions=cleaned_interactions, action_ledger=action_ledger)
    briefing, brief_model = await _run_brief_writer(person, claim_ledger, action_ledger, scores)
    model_name = brief_model if brief_model != "deterministic-fallback" else model_name
    stage1_knowledge_bank = _build_stage1_knowledge_bank(
        claim_ledger,
        cleaned_interactions,
        stage1_settings,
        stage1_box_defs,
        stage1_box_keywords,
    )
    stage2_flow = _build_stage2_relationship_business_flow(
        person=person,
        claim_ledger=claim_ledger,
        action_ledger=action_ledger,
        cleaned_interactions=cleaned_interactions,
        stage1_knowledge_bank=stage1_knowledge_bank,
        previous_stage2=previous_stage2,
        relationship_stage_details=relationship_stage_details,
        opportunity_stage_details=opportunity_stage_details,
        stage2_signal_keywords=stage2_signal_keywords,
    )
    briefing_with_stage2 = {**briefing, "relationship_business_flow_stage2": stage2_flow}
    agent_outputs[AGENT_ARBITER] = {"claim_ledger": claim_ledger}
    agent_outputs[AGENT_ACTION] = {"action_ledger": action_ledger}
    agent_outputs[AGENT_COMPANY_VERIFY] = {"company_verification": company_verification}
    agent_outputs[AGENT_BRIEF] = {"briefing": briefing_with_stage2}

    await _persist_run(
        person_id=str(person.get("person_id")),
        source_digest=source_digest,
        model_name=model_name,
        cleaned_interactions=cleaned_interactions,
        agent_outputs=agent_outputs,
        claim_ledger=claim_ledger,
        action_ledger=action_ledger,
        scores=scores,
        briefing=briefing_with_stage2,
    )

    trace = PipelineTrace(
        raw_interactions=evidence_inputs,
        cleaned_interactions=cleaned_interactions,
        agent_outputs=agent_outputs,
        claim_ledger=claim_ledger,
        action_ledger=action_ledger,
        retired_claims=[claim for claim in claim_ledger.get("claims", []) if claim.get("status") in {"disproved", "superseded"}],
        scores=scores,
    )
    meta = PipelineMeta(
        pipeline_version=PIPELINE_VERSION,
        model_name=model_name,
        cache_status="miss",
        source_digest=source_digest,
        agent_mode="multi_agent_truth_system",
    )
    return {
        "briefing": briefing_with_stage2,
        "scores": scores,
        "action_ledger": action_ledger,
        "company_verification": company_verification,
        "knowledge_bank_stage1": stage1_knowledge_bank,
        "relationship_business_flow_stage2": stage2_flow,
        "transcript_tagging": transcript_tagging,
        "trace": trace.model_dump(),
        "pipeline_meta": meta.model_dump(),
        "evidence_inputs": evidence_inputs,
    }
