"""
Antigravity CRM - AI foundation helpers
Shared constants, normalization, scoring, and matching utilities.
"""
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Optional

from backend.database import run_read

PRIMARY_CATEGORIES = (
    "business_focus",
    "recruitment_talent",
    "family_personal",
    "obe_focus",
)

PRIMARY_CATEGORY_LABELS = {
    "business_focus": "Business Focus",
    "recruitment_talent": "Recruitment & Talent",
    "family_personal": "Family & Personal",
    "obe_focus": "OBE Focus",
}

BUSINESS_SUBTOPICS = (
    "business_interests",
    "market_pulse",
    "leadership_view",
    "commercial_position",
    "operational_pressure",
)

BUSINESS_SUBTOPIC_LABELS = {
    "business_interests": "Business Interests",
    "market_pulse": "Market Pulse",
    "leadership_view": "Leadership View",
    "commercial_position": "Commercial Position",
    "operational_pressure": "Operational Pressure",
}

BUSINESS_SUBTOPIC_ALIASES = {
    "business interests": "business_interests",
    "business_interests": "business_interests",
    "market pulse": "market_pulse",
    "market_pulse": "market_pulse",
    "leadership": "leadership_view",
    "leadership view": "leadership_view",
    "leadership_view": "leadership_view",
    "commercial position": "commercial_position",
    "commercial_position": "commercial_position",
    "strategy growth": "commercial_position",
    "strategy & growth": "commercial_position",
    "strategy_growth": "commercial_position",
    "operational pressure": "operational_pressure",
    "operational_pressure": "operational_pressure",
}

SENTIMENT_LABELS = ("Positive", "Negative", "Neutral", "Mixed", "Unclear")

PROFILE_MATCH_STATES = ("confirmed", "probable", "tentative", "needs_review")

REVIEW_STATES = ("approved", "pending_review", "rejected", "duplicate", "failed")

ARTIFACT_INPUT_TYPES = (
    "document",
    "chat_transcript",
    "email_correspondence",
    "screenshot",
    "profile_picture",
    "general_image",
    "audio_note",
    "manual_note",
    "event_import",
    "csv_context",
    "unknown",
)

EVENT_STATUSES = ("Target", "Invited", "Confirmed", "Registered")

CATEGORY_ALIASES = {
    "business focus": "business_focus",
    "business_focus": "business_focus",
    "recruitment & talent": "recruitment_talent",
    "recruitment_talent": "recruitment_talent",
    "family & personal": "family_personal",
    "family_personal": "family_personal",
    "obe focus": "obe_focus",
    "obe_focus": "obe_focus",
}

SENTIMENT_ALIASES = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
    "mixed": "Mixed",
    "unclear": "Unclear",
    "unknown": "Unclear",
}

PLACEHOLDER_SIGNAL_TEXTS = {
    "none",
    "no relevant content",
    "no relevant information",
    "n/a",
    "na",
    "null",
    "unknown",
    "not applicable",
    "not available",
}

LOW_VALUE_SIGNAL_PATTERNS = (
    re.compile(r"\b(?:lol|haha|lmao)\b", re.IGNORECASE),
    re.compile(r"\b(?:a-?holes?|idiots?)\b", re.IGNORECASE),
)

SPECULATIVE_FILLER_PATTERNS = (
    re.compile(r"\s*,?\s*which could be a rapport[- ]building point\.?$", re.IGNORECASE),
    re.compile(r"\s*,?\s*which may be a rapport[- ]building point\.?$", re.IGNORECASE),
    re.compile(r"\s*,?\s*indicating a personal rapport hook(?: related to [^.]+)?\.?$", re.IGNORECASE),
    re.compile(r"\s*,?\s*which may be relevant for future rapport\.?$", re.IGNORECASE),
    re.compile(r"\s*,?\s*suggesting relevance to OBE events\.?$", re.IGNORECASE),
    re.compile(r"\s*,?\s*which could be useful for rapport\.?$", re.IGNORECASE),
)

RAW_CONVERSATIONAL_OPENERS = (
    "i think ",
    "think you would ",
    "have i told you ",
    "lets ",
    "let's ",
    "you need to ",
    "happy to ",
    "maybe,",
)

CHANNEL_TO_INPUT_TYPE = {
    "whatsapp": ("chat_transcript", 0.98),
    "chat": ("chat_transcript", 0.9),
    "email": ("email_correspondence", 0.98),
    "document": ("document", 0.98),
    "audio": ("audio_note", 0.98),
    "note": ("manual_note", 0.95),
    "manual": ("manual_note", 0.95),
    "screenshot": ("screenshot", 0.92),
}

SOURCE_STRENGTH_BY_INPUT = {
    "chat_transcript": 0.95,
    "email_correspondence": 0.92,
    "manual_note": 0.84,
    "event_import": 0.9,
    "csv_context": 0.82,
    "document": 0.78,
    "audio_note": 0.75,
    "screenshot": 0.66,
    "general_image": 0.58,
    "profile_picture": 0.4,
    "unknown": 0.35,
}

CATEGORY_KEYWORDS = {
    "business_focus": (
        "business",
        "pipeline",
        "commercial",
        "project",
        "deal",
        "opportunity",
        "client",
        "growth",
        "strategy",
        "revenue",
        "proposal",
        "meeting",
        "delivery",
        "tender",
    ),
    "recruitment_talent": (
        "hire",
        "hiring",
        "recruit",
        "recruitment",
        "talent",
        "candidate",
        "team",
        "staff",
        "staffing",
        "headcount",
        "role",
        "vacancy",
        "retention",
    ),
    "family_personal": (
        "family",
        "wife",
        "husband",
        "partner",
        "kids",
        "children",
        "holiday",
        "travel",
        "birthday",
        "weekend",
        "school",
        "home",
        "golf",
        "football",
    ),
    "obe_focus": (
        "obe",
        "members",
        "member",
        "board",
        "event",
        "summit",
        "committee",
        "network",
        "association",
        "chapter",
        "registration",
    ),
}

BUSINESS_SUBTOPIC_KEYWORDS = {
    "business_interests": ("interested", "interest", "focus on", "priority", "priorities", "keen on"),
    "market_pulse": ("market", "sector", "industry", "sentiment", "demand", "supply", "developer", "client appetite"),
    "leadership_view": ("believes", "view", "opinion", "thinks", "leadership", "benchmark", "speak up", "expects"),
    "commercial_position": ("contract", "cashflow", "pay", "payment", "commercial", "deal", "margin", "cost", "growth", "expansion", "strategy", "pipeline", "positioning", "territory", "plan"),
    "operational_pressure": ("delivery", "materials", "delay", "programme", "resource", "site", "midway", "completion"),
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_primary_category(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    normalized = CATEGORY_ALIASES.get(normalized, normalized)
    if normalized not in PRIMARY_CATEGORIES:
        raise ValueError(f"Invalid primary category: {value}")
    return normalized


def category_label(value: Optional[str]) -> str:
    key = canonical_primary_category(value)
    return PRIMARY_CATEGORY_LABELS[key]


def canonical_business_subtopic(value: Optional[str], *, allow_none: bool = True) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None if allow_none else ""
    normalized = str(value).strip().lower().replace("-", "_")
    normalized = BUSINESS_SUBTOPIC_ALIASES.get(normalized, normalized)
    if normalized not in BUSINESS_SUBTOPICS:
        if allow_none:
            return None
        raise ValueError(f"Invalid business subtopic: {value}")
    return normalized


def business_subtopic_label(value: Optional[str]) -> str:
    key = canonical_business_subtopic(value)
    return BUSINESS_SUBTOPIC_LABELS.get(key or "", "")


def canonical_sentiment(value: Optional[str], *, default: str = "Unclear") -> str:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if value >= 0.7:
            return "Positive"
        if value <= 0.3:
            return "Negative"
        return "Neutral"
    normalized = str(value).strip().lower()
    return SENTIMENT_ALIASES.get(normalized, default)


def normalize_signal_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_speculative_filler(value: Optional[str]) -> str:
    text = normalize_signal_text(value)
    if not text:
        return ""
    cleaned = text
    for pattern in SPECULATIVE_FILLER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;")
    return cleaned


def is_placeholder_signal_text(value: Optional[str]) -> bool:
    normalized = strip_speculative_filler(value).strip(" .,:;!-").lower()
    if not normalized:
        return True
    if normalized in PLACEHOLDER_SIGNAL_TEXTS:
        return True
    if normalized.startswith("no relevant content"):
        return True
    if normalized.startswith("no relevant information"):
        return True
    return False


def looks_like_raw_conversational_signal(value: Optional[str]) -> bool:
    text = strip_speculative_filler(value)
    if not text:
        return False
    lowered = text.lower()
    if text.endswith("?"):
        return True
    if any(lowered.startswith(prefix) for prefix in RAW_CONVERSATIONAL_OPENERS):
        return True
    if lowered[:1].islower() and any(token in lowered for token in (" i ", " you ", " we ", " my view", "your life")):
        return True
    return any(pattern.search(text) for pattern in LOW_VALUE_SIGNAL_PATTERNS)


def has_meaningful_signal_context(signal_text: Optional[str], snippet: Optional[str], *, category: Optional[str] = None) -> bool:
    text = strip_speculative_filler(signal_text)
    snippet_text = strip_speculative_filler(snippet or signal_text)
    if is_placeholder_signal_text(text) or looks_like_raw_conversational_signal(text):
        return False
    if len(text.split()) < 3 and category != "family_personal":
        return False
    if len(snippet_text) < 12 and len(text.split()) < 4:
        return False
    return True


def canonical_event_status(value: Optional[str]) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "target": "Target",
        "invited": "Invited",
        "confirmed": "Confirmed",
        "registered": "Registered",
    }
    result = mapping.get(normalized)
    if not result:
        raise ValueError(f"Invalid event status: {value}")
    return result


def input_type_for_channel(channel: Optional[str], *, source_kind: Optional[str] = None, filename: Optional[str] = None, image_type: Optional[str] = None) -> tuple[str, float]:
    channel_key = str(channel or "").strip().lower()
    if image_type:
        image_key = str(image_type).strip().lower()
        if image_key == "screenshot":
            return "screenshot", 0.96
        if image_key in {"profile_picture", "profile photo", "headshot"}:
            return "profile_picture", 0.95
        if image_key == "general_image":
            return "general_image", 0.9
    if channel_key in CHANNEL_TO_INPUT_TYPE:
        return CHANNEL_TO_INPUT_TYPE[channel_key]
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in {".pdf", ".doc", ".docx", ".txt"}:
        return "document", 0.95
    if ext in {".csv", ".xlsx", ".xls"}:
        return "csv_context", 0.9
    if ext in {".eml", ".msg"}:
        return "email_correspondence", 0.9
    if ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return "general_image", 0.72
    if ext in {".mp3", ".m4a", ".wav", ".ogg", ".webm"}:
        return "audio_note", 0.9
    if source_kind == "text":
        return "manual_note", 0.6
    return "unknown", 0.3


def infer_communication_channel(
    *,
    channel: Optional[str],
    summary: Optional[str] = None,
    raw_text: Optional[str] = None,
    extracted_text: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> str:
    base_channel = str(channel or "").strip().lower()
    metadata = metadata or {}
    screen_context = str(metadata.get("screen_context") or "").strip().lower()
    source_app = str(metadata.get("source_app") or "").strip().lower()
    haystack = " ".join(
        normalize_signal_text(value)
        for value in (summary, raw_text, extracted_text)
        if normalize_signal_text(value)
    ).lower()

    if source_app in {"whatsapp", "whatsapp_chat"} or screen_context in {"whatsapp_chat", "chat"}:
        return "whatsapp"
    if source_app in {"email", "outlook", "gmail"} or screen_context == "email":
        return "email"
    if source_app == "linkedin":
        return "linkedin"
    if screen_context == "document_capture":
        return "document"
    if "whatsapp conversation" in haystack or "last seen today" in haystack or "last seen at" in haystack:
        return "whatsapp"
    if "email thread" in haystack or "from:" in haystack and "subject:" in haystack:
        return "email"
    return base_channel or "note"


def compute_duplicate_hash(*parts: Optional[str], raw_bytes: Optional[bytes] = None) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        if part is None:
            continue
        hasher.update(str(part).strip().encode("utf-8", errors="ignore"))
        hasher.update(b"\x1f")
    if raw_bytes is not None:
        hasher.update(raw_bytes)
    return hasher.hexdigest()


def source_strength(input_type: str, *, profile_match_state: str = "confirmed", confidence: float = 1.0) -> float:
    base = SOURCE_STRENGTH_BY_INPUT.get(input_type, SOURCE_STRENGTH_BY_INPUT["unknown"])
    match_penalty = {
        "confirmed": 1.0,
        "probable": 0.82,
        "tentative": 0.62,
        "needs_review": 0.45,
    }.get(profile_match_state, 0.45)
    return round(max(min(base * match_penalty * max(min(confidence, 1.0), 0.25), 1.0), 0.05), 3)


def extract_terms(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_/\-]+", (text or "").lower())


def score_category_hypotheses(signal_text: str, primary_category: str) -> tuple[float, float, dict]:
    text = strip_speculative_filler(signal_text).lower()
    words = Counter(extract_terms(text))
    per_category = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        hit_count = sum(words.get(keyword, 0) for keyword in keywords)
        keyword_density = hit_count / max(len(text.split()), 1)
        per_category[category] = round(min(hit_count * 0.18 + keyword_density * 3, 1.0), 3)
    primary_score = per_category.get(primary_category, 0.15)
    other_categories = {
        category: score
        for category, score in per_category.items()
        if category != primary_category and score > 0
    }
    overall = max(primary_score, round(min(primary_score + (sum(other_categories.values()) * 0.15), 1.0), 3))
    return primary_score, overall, other_categories


def secondary_relevance_json(other_categories: dict) -> str:
    ordered = [
        {"category": category, "score": score}
        for category, score in sorted(other_categories.items(), key=lambda item: item[1], reverse=True)
        if score >= 0.15
    ]
    return json.dumps(ordered[:3])


def importance_score(signal_text: str, *, source_strength_value: float, sentiment: str, confidence_score: float) -> float:
    text = strip_speculative_filler(signal_text) or ""
    word_count = len(text.split())
    emphasis = 0.0
    if any(token in text.lower() for token in ("urgent", "critical", "priority", "important", "confirmed", "deadline")):
        emphasis += 0.15
    if sentiment in {"Positive", "Negative", "Mixed"}:
        emphasis += 0.08
    if word_count <= 30:
        emphasis += 0.05
    elif word_count >= 90:
        emphasis -= 0.08
    return round(max(min((source_strength_value * 0.45) + (confidence_score * 0.4) + emphasis, 1.0), 0.05), 3)


def review_state_for_signal(*, confidence_score: float, source_strength_value: float, artifact_status: str, requires_confirmation: bool) -> str:
    if artifact_status == "failed":
        return "failed"
    if artifact_status == "duplicate":
        return "duplicate"
    if requires_confirmation or confidence_score < 0.45 or source_strength_value < 0.35:
        return "pending_review"
    return "approved"


def signal_set_hash(signals: Iterable[dict]) -> str:
    normalized = [
        {
            "signal_id": signal.get("signal_id") or signal.get("id"),
            "updated_at": signal.get("updated_at") or signal.get("created_at"),
            "included_in_brief": int(signal.get("included_in_brief", 1)),
            "review_state": signal.get("review_state") or signal.get("status"),
        }
        for signal in signals
    ]
    payload = json.dumps(sorted(normalized, key=lambda item: item["signal_id"] or ""), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def confidence_summary(signals: Iterable[dict]) -> dict:
    items = list(signals)
    if not items:
        return {
            "signal_count": 0,
            "avg_confidence": 0,
            "avg_source_strength": 0,
            "needs_review_count": 0,
        }
    avg_confidence = sum(float(item.get("confidence_score") or 0) for item in items) / len(items)
    avg_source_strength = sum(float(item.get("source_strength") or 0) for item in items) / len(items)
    needs_review = sum(1 for item in items if item.get("review_state") == "pending_review")
    return {
        "signal_count": len(items),
        "avg_confidence": round(avg_confidence, 3),
        "avg_source_strength": round(avg_source_strength, 3),
        "needs_review_count": needs_review,
    }


def most_recent_changes(signals: Iterable[dict], limit: int = 5) -> list[dict]:
    ordered = sorted(
        signals,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return [
        {
            "signal_id": item.get("signal_id"),
            "category": item.get("primary_category") or item.get("category"),
            "text": strip_speculative_filler(item.get("signal_text") or item.get("content")),
            "updated_at": item.get("updated_at") or item.get("created_at"),
        }
        for item in ordered[:limit]
    ]


def infer_business_subtopic(text: Optional[str], snippet: Optional[str] = None) -> Optional[str]:
    haystack = " ".join(
        part for part in (
            strip_speculative_filler(text),
            strip_speculative_filler(snippet),
        ) if part
    ).lower()
    if not haystack:
        return None
    scores = {}
    for subtopic, keywords in BUSINESS_SUBTOPIC_KEYWORDS.items():
        scores[subtopic] = sum(1 for keyword in keywords if keyword in haystack)
    best = max(scores.items(), key=lambda item: item[1])
    if best[1] <= 0:
        return None
    return best[0]


async def suggest_profile_matches(query_text: str, limit: int = 5) -> list[dict]:
    query_text = (query_text or "").strip()
    if not query_text:
        return []

    terms = extract_terms(query_text)
    email_hits = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}", query_text, flags=re.IGNORECASE)
    phone_hits = re.findall(r"[+]?[0-9][0-9\\s\\-()]{6,}[0-9]", query_text)

    async def _load(db):
        async with db.execute(
            """
            SELECT person_id, full_name, company_name_raw, title_current, email_primary, email_secondary, phone_primary, phone_secondary
            FROM PERSON
            WHERE is_active = 1
            ORDER BY full_name COLLATE NOCASE ASC
            """
        ) as cursor:
            return await cursor.fetchall()

    rows = await run_read(_load, label="suggest profile matches")
    scored = []
    for row in rows:
        item = dict(row)
        haystack = " ".join(
            str(item.get(field) or "")
            for field in ("full_name", "company_name_raw", "title_current", "email_primary", "email_secondary", "phone_primary", "phone_secondary")
        ).lower()
        score = 0.0
        reasons = []
        for email in email_hits:
            if email.lower() and email.lower() in haystack:
                score += 0.75
                reasons.append("email match")
        for phone in phone_hits:
            digits = re.sub(r"\\D", "", phone)
            if digits and digits in re.sub(r"\\D", "", haystack):
                score += 0.7
                reasons.append("phone match")
        for term in terms:
            if len(term) < 2:
                continue
            if term in (item.get("full_name") or "").lower():
                score += 0.18
                reasons.append(f"name term '{term}'")
            elif term in (item.get("company_name_raw") or "").lower():
                score += 0.12
                reasons.append(f"company term '{term}'")
            elif term in haystack:
                score += 0.06
        if score <= 0:
            continue
        confidence = round(min(score, 0.99), 3)
        if confidence >= 0.8:
            state = "confirmed"
        elif confidence >= 0.6:
            state = "probable"
        elif confidence >= 0.4:
            state = "tentative"
        else:
            state = "needs_review"
        scored.append({
            "person_id": item["person_id"],
            "full_name": item.get("full_name"),
            "company_name_raw": item.get("company_name_raw"),
            "title_current": item.get("title_current"),
            "confidence": confidence,
            "profile_match_state": state,
            "reasons": sorted(set(reasons)),
        })
    scored.sort(key=lambda item: item["confidence"], reverse=True)
    return scored[:limit]
