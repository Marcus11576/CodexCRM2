from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from typing import Any

from backend.config import settings
from backend.database import run_read, run_write

INTELLIGENCE_SETTINGS_KEY = "intelligence_framework"
INTELLIGENCE_SETTINGS_SCHEMA_VERSION = "stage-settings-v1"

DEFAULT_STAGE1_CALIBRATION = {
    "profile": "balanced",
    "coverage_weight_pct": 60,
    "confidence_weight_pct": 25,
    "recency_weight_pct": 10,
    "density_weight_pct": 5,
    "recency_windows_days": {
        "fresh": 60,
        "recent": 180,
        "aged": 365,
    },
    "status_multipliers_pct": {
        "active": 100,
        "historical": 78,
        "uncertain": 58,
    },
    "source_multipliers_pct": {
        "manual": 100,
        "direct": 88,
        "indirect": 76,
        "low": 62,
    },
}

DEFAULT_TRANSCRIPT_KNOWLEDGE_BUCKETS: list[dict[str, Any]] = [
    {
        "box_id": 1,
        "code": "K1",
        "box_key": "family_status",
        "box_title": "Family Status",
        "keywords": [
            "partner", "spouse", "wife", "husband", "married", "single", "divorced", "children", "daughter", "son",
            "kids", "pet", "dog", "cat", "family based", "grandparents", "grandfather", "grandkids", "grandchildren",
            "years old", "50s", "60s", "70s", "in his 60s", "in her 60s", "in his 70s", "in her 70s", "in his 50s",
            "in her 50s", "live in the us", "some of them live in",
        ],
    },
    {
        "box_id": 2,
        "code": "K2",
        "box_key": "family_interests",
        "box_title": "Family Interests",
        "keywords": [
            "family travel", "family holiday", "weekend", "kids activities", "school activities", "family routine",
            "walking the dog", "summer trip",
        ],
    },
    {
        "box_id": 3,
        "code": "K3",
        "box_key": "personal_interests",
        "box_title": "Personal Interests",
        "keywords": [
            "running", "golf", "fishing", "gym", "cars", "food", "books", "watches", "hiking", "fitness", "travel",
            "skiing", "ski",
        ],
    },
    {
        "box_id": 4,
        "code": "K4",
        "box_key": "business_understanding",
        "box_title": "Business Understanding",
        "keywords": [
            "company", "division", "role", "director", "team", "market focus", "projects", "project management",
            "sector", "seniority", "leadership", "responsible", "board", "managing director", "consultant",
            "cost consultant", "omnium", "gcc", "dubai", "united arab emirates", "footprint", "emar", "acom",
            "dg jones", "no longer an active part of the business",
        ],
    },
    {
        "box_id": 5,
        "code": "K5",
        "box_key": "challenges_demands",
        "box_title": "Challenges and Demands",
        "keywords": [
            "pressure", "critical", "struggling", "workload", "gap", "shortage", "delivery", "resource",
            "internal change", "demand", "knee operations", "knee operation", "operation", "operations", "surgery",
            "surgeries",
        ],
    },
    {
        "box_id": 6,
        "code": "K6",
        "box_key": "recruitment_signals",
        "box_title": "Recruitment Signals",
        "keywords": [
            "hiring", "hire", "live role", "active role", "position", "replacement", "succession", "build-out",
            "team growth", "mandate", "placed", "placed about", "growth", "160 people",
        ],
    },
    {
        "box_id": 7,
        "code": "K7",
        "box_key": "market_intelligence",
        "box_title": "Market Intelligence",
        "keywords": [
            "market", "salary", "inflation", "candidate shortage", "pipeline", "sector", "competitor", "competition",
            "client behavior", "regional demand",
        ],
    },
    {
        "box_id": 8,
        "code": "K8",
        "box_key": "taylor_sterling_positioning",
        "box_title": "Taylor Sterling Positioning",
        "keywords": [
            "taylor sterling", "taylor stirling", "presentation", "introduced our services", "understands what we do",
            "know what we do", "they do know what we do", "model", "objection", "interest in support", "abilities",
            "presenting taylor sterling", "presenting taylor stirling", "presentation with taylor sterling",
        ],
    },
    {
        "box_id": 9,
        "code": "K9",
        "box_key": "obe_interest",
        "box_title": "OBE Interest",
        "keywords": [
            "obe", "breakfast", "roundtable", "event", "join network", "attend", "host", "introduction",
        ],
    },
    {
        "box_id": 10,
        "code": "K10",
        "box_key": "action_follow_up",
        "box_title": "Action / Follow-Up",
        "keywords": [
            "follow up", "next step", "arrange meeting", "send", "share", "invite", "reconnect", "next week",
            "next couple of weeks", "need to sit down", "sit down", "go through", "after the e-break",
            "week and a half", "i spoke to his colleague", "spoke to his colleague",
        ],
    },
    {
        "box_id": 11,
        "code": "K11",
        "box_key": "relationship_signal",
        "box_title": "Relationship Signal",
        "keywords": [
            "warm", "trust", "open", "responsive", "engaged", "hesitation", "guarded", "distance", "momentum",
            "last spoke", "known peter for", "known for about", "plenty of discussions over the years",
            "plenty of business over the years", "used us a lot before", "not used us recently",
        ],
    },
]

DEFAULT_TRANSCRIPT_RELATIONSHIP_STAGES: list[dict[str, Any]] = [
    {"code": "S1", "label": "S1 Introduction", "summary": "Very early relationship with light contact only."},
    {"code": "S2", "label": "S2 Understand", "summary": "Building understanding of the person, role, company, and context."},
    {"code": "S3", "label": "S3 Position", "summary": "Taylor Sterling positioning is visible, but relationship depth is still early."},
    {"code": "S4", "label": "S4 Nurture", "summary": "Relationship is active and healthy with no defined opportunity yet."},
    {"code": "S5", "label": "S5 Problem Identified", "summary": "A need, pressure, or talent gap is visible."},
    {"code": "S6", "label": "S6 Active Discussion", "summary": "A role, assignment, or commercial need is being discussed."},
    {"code": "S7", "label": "S7 Conversion Pending", "summary": "Commercial commitment is being shaped."},
    {"code": "S8", "label": "S8 Active Client", "summary": "A live assignment is underway."},
    {"code": "S9", "label": "S9 Active Nurture", "summary": "A mature trusted relationship is being maintained between assignments."},
]

DEFAULT_TRANSCRIPT_OPPORTUNITY_STAGES: list[dict[str, Any]] = [
    {"code": "O1", "label": "O1 Mature Problem Identified", "summary": "An emerging need is visible."},
    {"code": "O2", "label": "O2 Mature Active Discussion", "summary": "A role or commercial need is under active discussion."},
    {"code": "O3", "label": "O3 Mature Conversion Pending", "summary": "Commercial terms or commitment are being shaped."},
    {"code": "O4", "label": "O4 Mature Problem Identified", "summary": "A new need is identified inside a mature relationship."},
    {"code": "O5", "label": "O5 Mature Active Discussion", "summary": "A repeat or follow-on role is in active discussion."},
    {"code": "O6", "label": "O6 Mature Conversion Pending", "summary": "A repeat or follow-on assignment is being shaped commercially."},
    {"code": "O7", "label": "O7 Mature Active Client", "summary": "A live assignment is underway."},
]

DEFAULT_TRANSCRIPT_STAGE_RULES: list[dict[str, Any]] = [
    {"code": "O7", "label": "O7 Mature Active Client", "keywords": ["live assignment", "assignment underway", "onboarding", "mobilized", "mobilised", "currently delivering"]},
    {"code": "O6", "label": "O6 Mature Conversion Pending", "keywords": ["repeat assignment", "follow-on", "renewal", "extension", "commercial terms"]},
    {"code": "O3", "label": "O3 Mature Conversion Pending", "keywords": ["commercial terms", "scope", "proposal", "contract", "commitment", "fee", "sign off", "signoff"]},
    {"code": "O5", "label": "O5 Mature Active Discussion", "keywords": ["repeat role", "follow-on role", "again with us", "continuing brief"]},
    {"code": "O2", "label": "O2 Mature Active Discussion", "keywords": ["role", "assignment", "mandate", "hiring", "hire", "live role", "open role", "replacement", "succession", "headcount"]},
    {"code": "O4", "label": "O4 Mature Problem Identified", "keywords": ["new need in existing account", "new issue with existing client", "fresh pressure in existing relationship"]},
    {"code": "O1", "label": "O1 Mature Problem Identified", "keywords": ["need", "pressure", "gap", "challenge", "shortage", "demand", "critical"]},
    {"code": "S4", "label": "S4 Nurture", "keywords": ["relationship is warm", "active relationship", "keep in touch", "maintain relationship"]},
    {"code": "S3", "label": "S3 Position", "keywords": ["taylor sterling", "presentation", "introduced", "understands what we do", "positioning", "taylor stirling's abilities", "presentation of exactly what taylor stirling's abilities are", "presenting taylor sterling", "presenting taylor stirling", "presentation with taylor sterling"]},
    {"code": "S2", "label": "S2 Understand", "keywords": ["their role", "their company", "team size", "context", "responsible for", "market focus"]},
    {"code": "S1", "label": "S1 Introduction", "keywords": ["first call", "intro call", "initial conversation", "just met"]},
    {"code": "S9", "label": "S9 Active Nurture", "keywords": ["trusted relationship", "between assignments", "repeat relationship", "active nurture"]},
]

# Stage derivation from Knowledge buckets is intentionally disabled so
# Relationship/Opportunity stages remain independent from Knowledge.
DEFAULT_TRANSCRIPT_STAGE_FROM_KNOWLEDGE_MAP: dict[str, str] = {}

DEFAULT_TRANSCRIPT_BUCKET_GUIDANCE_BY_KEY: dict[str, dict[str, Any]] = {
    "family_status": {
        "what_it_is": "Core personal and family setup that helps relationship context stay accurate.",
        "includes": ["family setup", "life stage", "partner or spouse", "children", "location context"],
        "good_content_looks_like": "Specific family facts with direct context, not generic assumptions.",
    },
    "family_interests": {
        "what_it_is": "Family-led interests and routines that naturally support rapport.",
        "includes": ["family activities", "weekend routines", "school or kids activities", "shared travel"],
        "good_content_looks_like": "Practical details tied to family life that can be used naturally in conversation.",
    },
    "personal_interests": {
        "what_it_is": "Individual hobbies and non-family interests.",
        "includes": ["sport", "fitness", "hobbies", "lifestyle preferences"],
        "good_content_looks_like": "Clear personal interest signals with concrete wording from the source.",
    },
    "business_understanding": {
        "what_it_is": "What we know about their role, remit, and business context.",
        "includes": ["role scope", "team context", "company context", "market focus", "seniority"],
        "good_content_looks_like": "Commercially useful role and business specifics, not vague company references.",
    },
    "challenges_demands": {
        "what_it_is": "Current pressures, pain points, priorities, or resource demands affecting them or their business.",
        "includes": [
            "growth pressure",
            "hiring pressure",
            "restructuring",
            "delivery issues",
            "resource shortages",
            "budget pressure",
            "client problems",
            "team gaps",
        ],
        "good_content_looks_like": "Specific operational or leadership pain points, not vague complaints.",
    },
    "recruitment_signals": {
        "what_it_is": "Signals that indicate live or emerging hiring demand.",
        "includes": ["live roles", "future hiring", "replacement demand", "timing or urgency"],
        "good_content_looks_like": "Role-level detail with clear demand signal, ownership, or timing.",
    },
    "market_intelligence": {
        "what_it_is": "External market signals and commercial read-through from the contact.",
        "includes": ["market movement", "salary pressure", "talent availability", "competitive behavior"],
        "good_content_looks_like": "Factual market observations that are useful for positioning or planning.",
    },
    "taylor_sterling_positioning": {
        "what_it_is": "Evidence of how Taylor Sterling positioning has been presented and received.",
        "includes": ["presentation signal", "service understanding", "positive reaction", "objection or friction"],
        "good_content_looks_like": "Explicit feedback on understanding, interest, objection, or clarity gaps.",
    },
    "obe_interest": {
        "what_it_is": "Interest or engagement with OBE events, network activity, or introductions.",
        "includes": ["event participation", "network contribution", "attendance intent", "host/introduce intent"],
        "good_content_looks_like": "Clear evidence of OBE engagement intent, contribution, or participation.",
    },
    "action_follow_up": {
        "what_it_is": "Concrete next steps, commitments, and follow-up actions.",
        "includes": ["follow-up action", "owner", "timing", "send/share/introduce"],
        "good_content_looks_like": "Specific commitments with action and timing, not vague future intent.",
    },
    "relationship_signal": {
        "what_it_is": "Signals about trust, warmth, access quality, and relationship momentum.",
        "includes": ["trust signal", "openness", "responsiveness", "guarded behavior", "momentum direction"],
        "good_content_looks_like": "Direct relationship-quality signals tied to real interaction evidence.",
    },
}

DEFAULT_TRANSCRIPT_STAGE_GUIDANCE_BY_CODE: dict[str, dict[str, Any]] = {
    "S1": {
        "what_it_is": "Early introduction stage with light or first-touch relationship signal.",
        "includes": ["intro call", "first meeting", "new contact", "early rapport"],
        "good_content_looks_like": "Evidence of first contact and early understanding, with no commercial depth yet.",
    },
    "S2": {
        "what_it_is": "Understanding stage where role, remit, and context are being clarified.",
        "includes": ["role understanding", "company context", "team context", "scope clarification"],
        "good_content_looks_like": "Clear context-building signals that deepen understanding of the contact.",
    },
    "S3": {
        "what_it_is": "Positioning stage where Taylor Sterling capability is being presented or tested.",
        "includes": ["service presentation", "value positioning", "objection handling", "capability understanding"],
        "good_content_looks_like": "Specific evidence that positioning happened and how it landed.",
    },
    "S4": {
        "what_it_is": "Nurture stage with active relationship maintenance but no defined live mandate.",
        "includes": ["relationship warmth", "continuity touchpoints", "trusted dialogue", "active nurture"],
        "good_content_looks_like": "Steady engagement signals without explicit live opportunity demand.",
    },
    "S5": {
        "what_it_is": "Problem identified stage where a clear pain, gap, or pressure has surfaced.",
        "includes": ["business pressure", "talent gap", "delivery issue", "pain point visibility"],
        "good_content_looks_like": "Concrete need statements tied to business or leadership pressure.",
    },
    "S6": {
        "what_it_is": "Active discussion stage with live role or commercial conversation underway.",
        "includes": ["live role discussion", "mandate discussion", "scope discussion", "active commercial dialogue"],
        "good_content_looks_like": "Current, specific dialogue on roles, process, or commercial need.",
    },
    "S7": {
        "what_it_is": "Conversion pending stage where commitment terms are being shaped.",
        "includes": ["commercial terms", "commitment shaping", "scope confirmation", "decision progression"],
        "good_content_looks_like": "Signals that indicate near-term commitment but not yet active delivery.",
    },
    "S8": {
        "what_it_is": "Active client stage with confirmed live assignment activity.",
        "includes": ["active assignment", "delivery live", "onboarding", "work underway"],
        "good_content_looks_like": "Definite evidence that assignment execution is live.",
    },
    "S9": {
        "what_it_is": "Active nurture in mature trusted relationships between assignments.",
        "includes": ["trusted continuity", "ongoing relationship maintenance", "between-assignment engagement"],
        "good_content_looks_like": "Mature relationship signals with continuity and strategic retention focus.",
    },
    "O1": {
        "what_it_is": "Mature relationship problem identified stage.",
        "includes": ["new mature-account pressure", "new need in known account", "emerging role gap"],
        "good_content_looks_like": "Clear new pain or demand signal in an already-established relationship.",
    },
    "O2": {
        "what_it_is": "Mature relationship active discussion stage.",
        "includes": ["active role discussion", "live mandate conversation", "resource planning dialogue"],
        "good_content_looks_like": "Specific mature-account discussions showing active role or mandate movement.",
    },
    "O3": {
        "what_it_is": "Mature relationship conversion pending stage.",
        "includes": ["commercial terms", "scope finalization", "commitment progression", "approval shaping"],
        "good_content_looks_like": "Strong evidence that commitment is being finalized in a mature cycle.",
    },
    "O4": {
        "what_it_is": "New mature-cycle problem identified signal within an existing trusted account.",
        "includes": ["new account issue", "fresh pressure in existing relationship", "new demand in mature account"],
        "good_content_looks_like": "Fresh need signal distinct from prior mature-cycle activity.",
    },
    "O5": {
        "what_it_is": "Mature-cycle active discussion for repeat or follow-on roles.",
        "includes": ["repeat role discussion", "follow-on scope discussion", "continuing brief"],
        "good_content_looks_like": "Direct evidence of repeat-role movement in a mature account.",
    },
    "O6": {
        "what_it_is": "Mature-cycle conversion pending for repeat or follow-on assignments.",
        "includes": ["repeat commercial terms", "renewal/extension shaping", "follow-on commitment"],
        "good_content_looks_like": "Near-commitment signals for repeat or extension work.",
    },
    "O7": {
        "what_it_is": "Mature-cycle active client stage with live repeat assignment delivery.",
        "includes": ["repeat assignment underway", "active mature delivery", "extension now live"],
        "good_content_looks_like": "Confirmed live delivery evidence in a mature relationship cycle.",
    },
}


def _apply_default_transcript_guidance() -> None:
    for bucket in DEFAULT_TRANSCRIPT_KNOWLEDGE_BUCKETS:
        key = str(bucket.get("box_key") or "").strip()
        guidance = DEFAULT_TRANSCRIPT_BUCKET_GUIDANCE_BY_KEY.get(key, {})
        bucket["what_it_is"] = str(
            bucket.get("what_it_is")
            or guidance.get("what_it_is")
            or f"Knowledge captured for {bucket.get('box_title') or key}."
        ).strip()
        includes = guidance.get("includes") if isinstance(guidance.get("includes"), list) else []
        bucket["includes"] = [str(item).strip() for item in (bucket.get("includes") or includes) if str(item).strip()][:16]
        if not bucket["includes"]:
            bucket["includes"] = [str(item).strip() for item in (bucket.get("keywords") or []) if str(item).strip()][:8]
        bucket["good_content_looks_like"] = str(
            bucket.get("good_content_looks_like")
            or guidance.get("good_content_looks_like")
            or "Specific, evidence-backed detail grounded in source wording."
        ).strip()

    for stage in DEFAULT_TRANSCRIPT_RELATIONSHIP_STAGES + DEFAULT_TRANSCRIPT_OPPORTUNITY_STAGES:
        code = str(stage.get("code") or "").strip().upper()
        guidance = DEFAULT_TRANSCRIPT_STAGE_GUIDANCE_BY_CODE.get(code, {})
        stage["what_it_is"] = str(
            stage.get("what_it_is")
            or guidance.get("what_it_is")
            or f"Stage definition for {code}."
        ).strip()
        includes = guidance.get("includes") if isinstance(guidance.get("includes"), list) else []
        stage["includes"] = [str(item).strip() for item in (stage.get("includes") or includes) if str(item).strip()][:16]
        stage["good_content_looks_like"] = str(
            stage.get("good_content_looks_like")
            or guidance.get("good_content_looks_like")
            or "Specific evidence that clearly indicates this stage."
        ).strip()


_apply_default_transcript_guidance()

DEFAULT_TRANSCRIPT_TAGGING = {
    "knowledge_buckets": copy.deepcopy(DEFAULT_TRANSCRIPT_KNOWLEDGE_BUCKETS),
    "stage_relationship": copy.deepcopy(DEFAULT_TRANSCRIPT_RELATIONSHIP_STAGES),
    "stage_opportunity": copy.deepcopy(DEFAULT_TRANSCRIPT_OPPORTUNITY_STAGES),
    "stage_rules": copy.deepcopy(DEFAULT_TRANSCRIPT_STAGE_RULES),
    "stage_from_knowledge_map": copy.deepcopy(DEFAULT_TRANSCRIPT_STAGE_FROM_KNOWLEDGE_MAP),
}

STAGE1_CALIBRATION_PROFILES: dict[str, dict[str, Any]] = {
    "strict": {
        "profile": "strict",
        "coverage_weight_pct": 55,
        "confidence_weight_pct": 25,
        "recency_weight_pct": 15,
        "density_weight_pct": 5,
        "recency_windows_days": {"fresh": 45, "recent": 120, "aged": 240},
        "status_multipliers_pct": {"active": 100, "historical": 65, "uncertain": 40},
        "source_multipliers_pct": {"manual": 100, "direct": 85, "indirect": 70, "low": 55},
    },
    "balanced": copy.deepcopy(DEFAULT_STAGE1_CALIBRATION),
    "lenient": {
        "profile": "lenient",
        "coverage_weight_pct": 65,
        "confidence_weight_pct": 22,
        "recency_weight_pct": 7,
        "density_weight_pct": 6,
        "recency_windows_days": {"fresh": 90, "recent": 240, "aged": 420},
        "status_multipliers_pct": {"active": 100, "historical": 86, "uncertain": 70},
        "source_multipliers_pct": {"manual": 100, "direct": 92, "indirect": 84, "low": 72},
    },
}

CORE_INTELLIGENCE_LAYERS: list[dict[str, Any]] = [
    {
        "layer_id": "stage1_knowledge_bank",
        "label": "Stage 1 Knowledge Bank Build",
        "description": "Track completeness, confidence, freshness, and gaps across 11 approved knowledge boxes.",
        "enabled": True,
        "status": "active",
    },
    {
        "layer_id": "stage2_relationship_flow",
        "label": "Stage 2 Relationship and Business Flow",
        "description": "Track commercial journey stages (S1-S9) and mature-cycle opportunity stages (O1-O7).",
        "enabled": True,
        "status": "active",
    },
]

LEGACY_OPPORTUNITY_STAGE_CODE_MAP: dict[str, str] = {
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

DEFAULT_INTELLIGENCE_SETTINGS = {
    "schema_version": INTELLIGENCE_SETTINGS_SCHEMA_VERSION,
    "chatbot_only_inputs": bool(settings.CHATBOT_ONLY_MODE),
    "legacy_scoring_enabled": False,
    "layers": copy.deepcopy(CORE_INTELLIGENCE_LAYERS),
    "stage1_calibration": copy.deepcopy(DEFAULT_STAGE1_CALIBRATION),
    "transcript_tagging": copy.deepcopy(DEFAULT_TRANSCRIPT_TAGGING),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (updates or {}).items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _clamp_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _normalize_profile(profile: Any) -> str:
    value = str(profile or "balanced").strip().lower()
    if value not in STAGE1_CALIBRATION_PROFILES:
        return "balanced"
    return value


def _normalize_stage1_calibration(payload: dict[str, Any]) -> dict[str, Any]:
    profile = _normalize_profile(payload.get("profile"))
    baseline = _deep_merge(
        STAGE1_CALIBRATION_PROFILES["balanced"],
        STAGE1_CALIBRATION_PROFILES[profile],
    )
    merged = _deep_merge(baseline, payload or {})

    weights = {
        "coverage_weight_pct": _clamp_int(
            merged.get("coverage_weight_pct"),
            minimum=0,
            maximum=100,
            default=baseline["coverage_weight_pct"],
        ),
        "confidence_weight_pct": _clamp_int(
            merged.get("confidence_weight_pct"),
            minimum=0,
            maximum=100,
            default=baseline["confidence_weight_pct"],
        ),
        "recency_weight_pct": _clamp_int(
            merged.get("recency_weight_pct"),
            minimum=0,
            maximum=100,
            default=baseline["recency_weight_pct"],
        ),
        "density_weight_pct": _clamp_int(
            merged.get("density_weight_pct"),
            minimum=0,
            maximum=100,
            default=baseline["density_weight_pct"],
        ),
    }
    weight_total = sum(weights.values())
    if weight_total <= 0:
        weights = {
            "coverage_weight_pct": baseline["coverage_weight_pct"],
            "confidence_weight_pct": baseline["confidence_weight_pct"],
            "recency_weight_pct": baseline["recency_weight_pct"],
            "density_weight_pct": baseline["density_weight_pct"],
        }
        weight_total = sum(weights.values())
    if weight_total != 100:
        scale = 100.0 / float(weight_total)
        normalized_weights = {
            key: max(0, min(100, int(round(value * scale))))
            for key, value in weights.items()
        }
        drift = 100 - sum(normalized_weights.values())
        if drift:
            normalized_weights["coverage_weight_pct"] = max(
                0,
                min(100, normalized_weights["coverage_weight_pct"] + drift),
            )
        weights = normalized_weights

    windows = merged.get("recency_windows_days") if isinstance(merged.get("recency_windows_days"), dict) else {}
    fresh = _clamp_int(
        windows.get("fresh"),
        minimum=7,
        maximum=365,
        default=baseline["recency_windows_days"]["fresh"],
    )
    recent = _clamp_int(
        windows.get("recent"),
        minimum=fresh + 1,
        maximum=730,
        default=max(baseline["recency_windows_days"]["recent"], fresh + 1),
    )
    aged = _clamp_int(
        windows.get("aged"),
        minimum=recent + 1,
        maximum=1460,
        default=max(baseline["recency_windows_days"]["aged"], recent + 1),
    )

    status = merged.get("status_multipliers_pct") if isinstance(merged.get("status_multipliers_pct"), dict) else {}
    source = merged.get("source_multipliers_pct") if isinstance(merged.get("source_multipliers_pct"), dict) else {}

    return {
        "profile": profile,
        **weights,
        "recency_windows_days": {
            "fresh": fresh,
            "recent": recent,
            "aged": aged,
        },
        "status_multipliers_pct": {
            "active": _clamp_int(status.get("active"), minimum=1, maximum=100, default=baseline["status_multipliers_pct"]["active"]),
            "historical": _clamp_int(status.get("historical"), minimum=1, maximum=100, default=baseline["status_multipliers_pct"]["historical"]),
            "uncertain": _clamp_int(status.get("uncertain"), minimum=1, maximum=100, default=baseline["status_multipliers_pct"]["uncertain"]),
        },
        "source_multipliers_pct": {
            "manual": _clamp_int(source.get("manual"), minimum=1, maximum=100, default=baseline["source_multipliers_pct"]["manual"]),
            "direct": _clamp_int(source.get("direct"), minimum=1, maximum=100, default=baseline["source_multipliers_pct"]["direct"]),
            "indirect": _clamp_int(source.get("indirect"), minimum=1, maximum=100, default=baseline["source_multipliers_pct"]["indirect"]),
            "low": _clamp_int(source.get("low"), minimum=1, maximum=100, default=baseline["source_multipliers_pct"]["low"]),
        },
    }


def _normalize_layer_id(value: Any, index: int) -> str:
    raw = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").strip().lower())
    raw = raw.strip("_-")
    return raw or f"layer_{index:02d}"


def _normalize_layers(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        layer_id = _normalize_layer_id(row.get("layer_id"), idx)
        if layer_id in seen:
            continue
        seen.add(layer_id)
        status = str(row.get("status") or "planned").strip().lower()
        if status not in {"active", "planned", "disabled"}:
            status = "planned"
        label = str(row.get("label") or "").strip() or layer_id.replace("_", " ").title()
        normalized.append(
            {
                "layer_id": layer_id,
                "label": label,
                "description": str(row.get("description") or "").strip(),
                "enabled": bool(row.get("enabled", True)),
                "status": status,
            }
        )

    if not normalized:
        return copy.deepcopy(CORE_INTELLIGENCE_LAYERS)

    by_id = {row["layer_id"]: row for row in normalized}
    for core_layer in CORE_INTELLIGENCE_LAYERS:
        if core_layer["layer_id"] not in by_id:
            normalized.append(copy.deepcopy(core_layer))
    return normalized


def _normalize_text_list(value: Any, *, limit: int = 240) -> list[str]:
    rows = value if isinstance(value, list) else []
    normalized: list[str] = []
    seen: set[str] = set()
    for row in rows:
        text = str(row or "").strip()
        if not text:
            continue
        text = text[:limit]
        canonical = text.lower()
        if canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(text)
    return normalized


def _normalize_guidance_text(value: Any, fallback: Any, *, limit: int = 360) -> str:
    if value is None:
        chosen = fallback
    else:
        raw = str(value).strip()
        chosen = raw if raw else fallback
    text = str(chosen or "").strip()
    return text[:limit]


def _normalize_guidance_includes(value: Any, fallback: Any, *, limit: int = 16) -> list[str]:
    if isinstance(value, str):
        rows = [part.strip() for part in re.split(r"[,;\n]+", value) if part and part.strip()]
    elif isinstance(value, list):
        rows = value
    elif isinstance(fallback, str):
        rows = [part.strip() for part in re.split(r"[,;\n]+", fallback) if part and part.strip()]
    elif isinstance(fallback, list):
        rows = fallback
    else:
        rows = []
    return _normalize_text_list(rows, limit=80)[:limit]


def _normalize_knowledge_buckets(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    defaults_by_key = {item["box_key"]: item for item in DEFAULT_TRANSCRIPT_KNOWLEDGE_BUCKETS}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for idx, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        key = re.sub(r"[^a-z0-9_]+", "_", str(row.get("box_key") or "").strip().lower()).strip("_")
        if not key or key in seen:
            continue
        seen.add(key)
        fallback = defaults_by_key.get(key, {})
        label = str(row.get("box_title") or fallback.get("box_title") or key.replace("_", " ").title()).strip()
        box_id = _clamp_int(row.get("box_id"), minimum=1, maximum=99, default=(fallback.get("box_id") or idx))
        raw_code = str(row.get("code") or fallback.get("code") or f"K{box_id}").strip().upper()
        code_match = re.fullmatch(r"K?\s*(\d{1,2})", raw_code)
        code = f"K{int(code_match.group(1))}" if code_match else f"K{box_id}"
        keywords = _normalize_text_list(row.get("keywords"), limit=80)
        if not keywords:
            keywords = list(fallback.get("keywords") or [])
        what_it_is = _normalize_guidance_text(
            row.get("what_it_is"),
            fallback.get("what_it_is"),
            limit=320,
        )
        includes = _normalize_guidance_includes(
            row.get("includes"),
            fallback.get("includes") or keywords[:8],
            limit=16,
        )
        good_content = _normalize_guidance_text(
            row.get("good_content_looks_like"),
            fallback.get("good_content_looks_like"),
            limit=360,
        )
        normalized.append(
            {
                "box_id": box_id,
                "code": code,
                "box_key": key,
                "box_title": label,
                "keywords": keywords[:80],
                "what_it_is": what_it_is,
                "includes": includes,
                "good_content_looks_like": good_content,
            }
        )

    if not normalized:
        return copy.deepcopy(DEFAULT_TRANSCRIPT_KNOWLEDGE_BUCKETS)

    by_key = {item["box_key"]: item for item in normalized}
    for fallback in DEFAULT_TRANSCRIPT_KNOWLEDGE_BUCKETS:
        if fallback["box_key"] not in by_key:
            normalized.append(copy.deepcopy(fallback))
    return sorted(normalized, key=lambda item: int(item.get("box_id") or 99))


def _normalize_stage_definitions(value: Any, defaults: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    defaults_by_code = {str(item["code"]).upper(): item for item in defaults}
    is_opportunity_defs = any(str(item.get("code") or "").upper().startswith(("R", "O")) for item in defaults)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().upper()
        if is_opportunity_defs:
            code = LEGACY_OPPORTUNITY_STAGE_CODE_MAP.get(code, code)
        if not code or code in seen:
            continue
        seen.add(code)
        fallback = defaults_by_code.get(code, {})
        what_it_is = _normalize_guidance_text(
            row.get("what_it_is"),
            fallback.get("what_it_is"),
            limit=320,
        )
        includes = _normalize_guidance_includes(
            row.get("includes"),
            fallback.get("includes"),
            limit=16,
        )
        good_content = _normalize_guidance_text(
            row.get("good_content_looks_like"),
            fallback.get("good_content_looks_like"),
            limit=360,
        )
        normalized.append(
            {
                "code": code,
                "label": str(row.get("label") or fallback.get("label") or code).strip(),
                "summary": str(row.get("summary") or fallback.get("summary") or "").strip(),
                "what_it_is": what_it_is,
                "includes": includes,
                "good_content_looks_like": good_content,
            }
        )
    if not normalized:
        return copy.deepcopy(defaults)
    by_code = {item["code"]: item for item in normalized}
    for fallback in defaults:
        code = str(fallback["code"]).upper()
        if code not in by_code:
            normalized.append(copy.deepcopy(fallback))
    for item in normalized:
        code = str(item.get("code") or "").upper()
        if not code.startswith(("R", "O")):
            continue
        raw_label = str(item.get("label") or "").strip()
        plain_label = re.sub(r"^[SRO][0-9M]+\s+", "", raw_label, flags=re.IGNORECASE).strip()
        if not plain_label:
            fallback = defaults_by_code.get(code, {})
            plain_label = re.sub(
                r"^[SRO][0-9M]+\s+",
                "",
                str(fallback.get("label") or code).strip(),
                flags=re.IGNORECASE,
            ).strip()
        if plain_label and not plain_label.lower().startswith("mature "):
            plain_label = f"Mature {plain_label}"
        item["label"] = f"{code} {plain_label or 'Mature Stage'}".strip()
    return normalized


def _normalize_stage_rules(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    defaults_by_code = {str(item["code"]).upper(): item for item in DEFAULT_TRANSCRIPT_STAGE_RULES}
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().upper()
        code = LEGACY_OPPORTUNITY_STAGE_CODE_MAP.get(code, code)
        if not code or code in seen:
            continue
        seen.add(code)
        fallback = defaults_by_code.get(code, {})
        keywords = _normalize_text_list(row.get("keywords"), limit=80)
        if not keywords:
            keywords = list(fallback.get("keywords") or [])
        normalized.append(
            {
                "code": code,
                "label": str(row.get("label") or fallback.get("label") or code).strip(),
                "keywords": keywords[:80],
            }
        )
    if not normalized:
        return copy.deepcopy(DEFAULT_TRANSCRIPT_STAGE_RULES)
    by_code = {item["code"]: item for item in normalized}
    for fallback in DEFAULT_TRANSCRIPT_STAGE_RULES:
        code = str(fallback["code"]).upper()
        if code not in by_code:
            normalized.append(copy.deepcopy(fallback))
    for item in normalized:
        code = str(item.get("code") or "").upper()
        if not code.startswith(("R", "O")):
            continue
        raw_label = str(item.get("label") or "").strip()
        plain_label = re.sub(r"^[SRO][0-9M]+\s+", "", raw_label, flags=re.IGNORECASE).strip()
        if not plain_label:
            fallback = defaults_by_code.get(code, {})
            plain_label = re.sub(
                r"^[SRO][0-9M]+\s+",
                "",
                str(fallback.get("label") or code).strip(),
                flags=re.IGNORECASE,
            ).strip()
        if plain_label and not plain_label.lower().startswith("mature "):
            plain_label = f"Mature {plain_label}"
        item["label"] = f"{code} {plain_label or 'Mature Stage'}".strip()
    return normalized


def _normalize_transcript_tagging(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    knowledge_buckets = _normalize_knowledge_buckets(payload.get("knowledge_buckets"))
    relationship_stages = _normalize_stage_definitions(
        payload.get("stage_relationship"),
        DEFAULT_TRANSCRIPT_RELATIONSHIP_STAGES,
    )
    opportunity_stages = _normalize_stage_definitions(
        payload.get("stage_opportunity"),
        DEFAULT_TRANSCRIPT_OPPORTUNITY_STAGES,
    )
    stage_rules = _normalize_stage_rules(payload.get("stage_rules"))

    return {
        "knowledge_buckets": knowledge_buckets,
        "stage_relationship": relationship_stages,
        "stage_opportunity": opportunity_stages,
        "stage_rules": stage_rules,
        "stage_from_knowledge_map": {},
    }


def normalize_intelligence_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(copy.deepcopy(DEFAULT_INTELLIGENCE_SETTINGS), payload or {})
    return {
        "schema_version": INTELLIGENCE_SETTINGS_SCHEMA_VERSION,
        "chatbot_only_inputs": bool(merged.get("chatbot_only_inputs", settings.CHATBOT_ONLY_MODE)),
        "legacy_scoring_enabled": bool(merged.get("legacy_scoring_enabled", False)),
        "layers": _normalize_layers(merged.get("layers")),
        "stage1_calibration": _normalize_stage1_calibration(merged.get("stage1_calibration") or {}),
        "transcript_tagging": _normalize_transcript_tagging(merged.get("transcript_tagging") or {}),
    }


async def _read_intelligence_settings_row() -> dict[str, Any] | None:
    async def _operation(db):
        async with db.execute(
            """
            SELECT setting_json, updated_at
            FROM SYSTEM_SETTING
            WHERE setting_key = ?
            LIMIT 1
            """,
            (INTELLIGENCE_SETTINGS_KEY,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        try:
            parsed = json.loads(row["setting_json"] or "{}")
        except json.JSONDecodeError:
            parsed = {}
        return {
            "settings": parsed if isinstance(parsed, dict) else {},
            "updated_at": str(row["updated_at"] or ""),
        }

    return await run_read(_operation, label="load intelligence settings")


async def _write_intelligence_settings(settings_payload: dict[str, Any]) -> str:
    now = _now_iso()

    async def _operation(db):
        await db.execute(
            """
            INSERT INTO SYSTEM_SETTING (setting_key, setting_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_json = excluded.setting_json,
                updated_at = excluded.updated_at
            """,
            (
                INTELLIGENCE_SETTINGS_KEY,
                json.dumps(settings_payload, ensure_ascii=False),
                now,
            ),
        )

    await run_write(_operation, label="save intelligence settings")
    return now


async def get_intelligence_settings() -> dict[str, Any]:
    row = await _read_intelligence_settings_row()
    if row:
        normalized = normalize_intelligence_settings(row.get("settings") or {})
        return {
            "settings_key": INTELLIGENCE_SETTINGS_KEY,
            "updated_at": row.get("updated_at") or "",
            "settings": normalized,
        }

    normalized = normalize_intelligence_settings({})
    updated_at = await _write_intelligence_settings(normalized)
    return {
        "settings_key": INTELLIGENCE_SETTINGS_KEY,
        "updated_at": updated_at,
        "settings": normalized,
    }


async def save_intelligence_settings(payload: dict[str, Any] | None, *, merge: bool = True) -> dict[str, Any]:
    current = await get_intelligence_settings()
    current_settings = current.get("settings") or {}
    candidate = _deep_merge(current_settings, payload or {}) if merge else (payload or {})
    normalized = normalize_intelligence_settings(candidate)
    updated_at = await _write_intelligence_settings(normalized)
    return {
        "settings_key": INTELLIGENCE_SETTINGS_KEY,
        "updated_at": updated_at,
        "settings": normalized,
    }


async def reset_intelligence_settings() -> dict[str, Any]:
    normalized = normalize_intelligence_settings({})
    updated_at = await _write_intelligence_settings(normalized)
    return {
        "settings_key": INTELLIGENCE_SETTINGS_KEY,
        "updated_at": updated_at,
        "settings": normalized,
    }


async def get_stage1_calibration_settings() -> dict[str, Any]:
    state = await get_intelligence_settings()
    stage1 = state.get("settings", {}).get("stage1_calibration")
    if isinstance(stage1, dict):
        return stage1
    return copy.deepcopy(DEFAULT_STAGE1_CALIBRATION)
