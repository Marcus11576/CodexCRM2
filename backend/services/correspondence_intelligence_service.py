import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from backend.database import run_read, run_write


RELEVANCE_WINDOW_DAYS = 365 * 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relevance_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=RELEVANCE_WINDOW_DAYS)


def _parse_datetime(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_recent_enough(value: str | None) -> bool:
    parsed = _parse_datetime(value)
    if not parsed:
        return False
    return parsed >= _relevance_cutoff()


def _json_array(values: list[str]) -> str:
    cleaned = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return json.dumps(cleaned, ensure_ascii=False)


def _keyword_hits(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def _phrase_hits(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    return any(re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", lowered) for phrase in phrases)


def _extract_evidence_snippets(text: str, keywords: tuple[str, ...], max_items: int = 2) -> list[str]:
    segments = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    snippets: list[str] = []
    for segment in segments:
        cleaned = " ".join(segment.split()).strip()
        cleaned = re.sub(r"^(Sent Email:|Received Email:|Imported record:?|Image processed:?|This image is a screenshot of)\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+(Sent Email:|Received Email:).*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" -:")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if not keywords or any(keyword in lowered for keyword in keywords):
            snippet = cleaned[:240]
            if snippet not in snippets:
                snippets.append(snippet)
        if len(snippets) >= max_items:
            break
    if snippets:
        return snippets
    fallback = " ".join((text or "").split()).strip()
    fallback = re.sub(r"^(Sent Email:|Received Email:|Imported record:?|Image processed:?|This image is a screenshot of)\s*", "", fallback, flags=re.IGNORECASE).strip(" -:")
    return [fallback[:240]] if fallback else []


def _clean_source_text(text: str | None) -> str:
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(
        r"^(Sent Email:|Received Email:|Imported record:?|Image processed:?|This image is a screenshot of)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    lines = []
    for line in cleaned.split("\n"):
        normalized = " ".join(line.split()).strip()
        normalized = re.sub(
            r"^(Sent Email:|Received Email:|Imported record:?|Image processed:?|This image is a screenshot of)\s*",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip(" -:")
        if re.fullmatch(r"_+", normalized):
            continue
        if normalized:
            lines.append(normalized)
    deduped_lines: list[str] = []
    for line in lines:
        if line not in deduped_lines:
            deduped_lines.append(line)
    return "\n".join(deduped_lines).strip()


def _build_full_evidence_text(summary: str | None, raw_text: str | None) -> str:
    summary_clean = _clean_source_text(summary)
    raw_clean = _clean_source_text(raw_text)
    if raw_clean and summary_clean:
        raw_lower = raw_clean.lower()
        summary_lower = summary_clean.lower()
        if raw_clean == summary_clean or raw_lower.startswith(summary_lower):
            return raw_clean
        return f"Summary:\n{summary_clean}\n\nSource:\n{raw_clean}"
    return raw_clean or summary_clean


def _source_text_blob(summary: str | None = None, raw_text: str | None = None) -> str:
    return "\n".join(
        part.strip()
        for part in (str(summary or ""), str(raw_text or ""))
        if str(part or "").strip()
    ).lower()


def _looks_like_teams_meeting_invite(summary: str | None = None, raw_text: str | None = None) -> bool:
    blob = _source_text_blob(summary, raw_text)
    if not blob or "microsoft teams" not in blob:
        return False
    return any(
        marker in blob
        for marker in (
            "join the meeting now",
            "meeting id:",
            "meeting options",
            "passcode:",
        )
    )


def _looks_like_meeting_response(summary: str | None = None, raw_text: str | None = None) -> bool:
    blob = _source_text_blob(summary, raw_text)
    if not blob:
        return False
    return any(
        marker in blob
        for marker in (
            "accepted:",
            "declined:",
            "tentative:",
            "accepted this invitation",
        )
    )


def _display_channel_label(channel: str | None, summary: str | None = None, raw_text: str | None = None) -> str:
    base_channel = str(channel or "").strip().lower()
    blob = _source_text_blob(summary, raw_text)
    if _looks_like_meeting_response(summary, raw_text):
        return "Teams meeting response" if "microsoft teams" in blob else "Meeting response"
    if base_channel == "meeting":
        return "Teams meeting" if "teams" in blob else "Calendar meeting"
    if _looks_like_teams_meeting_invite(summary, raw_text):
        return "Teams meeting invite"
    if base_channel == "email":
        return "Email"
    if base_channel == "call":
        return "Call"
    if base_channel == "whatsapp":
        return "WhatsApp"
    if base_channel == "linkedin":
        return "LinkedIn"
    if base_channel in {"screenshot", "upload", "general_image"}:
        if any(marker in blob for marker in ("whatsapp", "last seen", "typing...", "double tick", "chat screenshot")):
            return "WhatsApp"
        if any(marker in blob for marker in ("subject:", "from:", "sent:", "inbox", "outlook", "gmail", "email")):
            return "Email"
        if "linkedin" in blob:
            return "LinkedIn"
        if any(marker in blob for marker in ("curriculum vitae", "resume", "profile.pdf", "document uploaded", "extraction pending")):
            return "Document capture"
        return "Screenshot"
    if base_channel == "note":
        return "Note"
    if base_channel == "chat_topic_resolution":
        return "Topic resolution"
    return str(channel or "Interaction").strip() or "Interaction"


def _clip(text: str, max_len: int = 220) -> str:
    cleaned = " ".join((text or "").split()).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _story_topic_label(item: dict) -> str:
    for field in (
        "market_intel_signals",
        "opportunity_signals",
        "friction_signals",
        "relationship_signals",
        "intent_signals",
    ):
        values = item.get(field) or []
        if values:
            return _clip(str(values[0]), 120)
    if item.get("stage"):
        return str(item["stage"])
    return _clip(str(item.get("what_is_happening") or "Relationship development"), 120)


def _same_storyline_group(previous: dict, current: dict) -> bool:
    prev_at = _parse_datetime(previous.get("interaction_at"))
    current_at = _parse_datetime(current.get("interaction_at"))
    if not prev_at or not current_at:
        return False
    day_gap = abs((current_at - prev_at).days)
    if previous.get("thread_id") and current.get("thread_id") and previous.get("thread_id") == current.get("thread_id"):
        return True
    if day_gap > 21:
        return False
    if previous.get("_story_topic_type") and current.get("_story_topic_type"):
        if previous.get("_story_topic_type") != current.get("_story_topic_type"):
            return False
    if previous.get("stage") and current.get("stage") and previous.get("stage") == current.get("stage"):
        return True
    if previous.get("_story_topic") == current.get("_story_topic"):
        return True
    return False


def _story_topic_type(item: dict) -> str:
    if item.get("market_intel_signals"):
        return "market"
    if item.get("opportunity_signals") or item.get("stage") == "Assignment / Signature Progression":
        return "opportunity"
    if item.get("friction_signals"):
        return "risk"
    if item.get("influence_signals"):
        return "influence"
    return "relationship"


def _story_topic_type_label(topic_type: str) -> str:
    return {
        "market": "Market",
        "opportunity": "Opportunity",
        "risk": "Risk",
        "influence": "Influence",
        "relationship": "Relationship",
    }.get(topic_type, "Relationship")


def _story_topic_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:18] or "story"


def _story_window_label(start_at: str, end_at: str) -> str:
    start_dt = _parse_datetime(start_at)
    end_dt = _parse_datetime(end_at)
    if not start_dt and not end_dt:
        return "No clear timeline"
    if start_dt and end_dt:
        start_label = start_dt.strftime("%d %b %Y")
        end_label = end_dt.strftime("%d %b %Y")
        if start_label == end_label:
            return start_label
        return f"{start_label} - {end_label}"
    only_dt = start_dt or end_dt
    return only_dt.strftime("%d %b %Y") if only_dt else "No clear timeline"


def _storyline_key_points(entries: list[dict]) -> list[str]:
    points: list[str] = []
    for entry in entries:
        for field in (
            "market_intel_signals",
            "opportunity_signals",
            "friction_signals",
            "relationship_signals",
            "intent_signals",
            "influence_signals",
        ):
            for value in entry.get(field) or []:
                text = str(value or "").strip()
                if text and text not in points:
                    points.append(text)
    return points[:5]


def _storyline_timeline_summary(bucket: dict, latest: dict) -> str:
    channels = bucket.get("channels") or []
    channel_text = ", ".join(channels[:3]) if channels else "recorded channels"
    if len(channels) > 3:
        channel_text += f" +{len(channels) - 3} more"
    stage = str(latest.get("stage") or "Relationship Update")
    momentum = str(latest.get("momentum") or "steady")
    if bucket.get("entry_count", 0) <= 1:
        return f"This situation is currently visible through {channel_text}. Stage is {stage.lower()} with {momentum.lower()} momentum."
    return (
        f"This situation built across {bucket['entry_count']} interactions on {channel_text}. "
        f"It currently sits at {stage.lower()} with {momentum.lower()} momentum."
    )


def _merge_storyline_groups_by_key(groups: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    ordered_keys: list[str] = []

    def _dt(value: str | None) -> datetime:
        return _parse_datetime(value) or datetime(1970, 1, 1, tzinfo=timezone.utc)

    for group in groups or []:
        situation_key = _relationship_situation_key(group)
        existing = merged.get(situation_key)
        if not existing:
            merged[situation_key] = {
                **group,
                "channels": list(group.get("channels") or []),
                "key_points": list(group.get("key_points") or []),
                "supporting_entries": list(group.get("supporting_entries") or []),
                "entry_count": int(group.get("entry_count") or len(group.get("supporting_entries") or [])),
            }
            ordered_keys.append(situation_key)
            continue

        existing["start_at"] = min(
            [value for value in (existing.get("start_at"), group.get("start_at")) if value],
            key=_dt,
        )
        existing["end_at"] = max(
            [value for value in (existing.get("end_at"), group.get("end_at")) if value],
            key=_dt,
        )
        existing["channels"] = _dedupe_text_list(existing.get("channels", []) + list(group.get("channels") or []), limit=6)
        existing["key_points"] = _dedupe_text_list(existing.get("key_points", []) + list(group.get("key_points") or []), limit=6)

        entry_seen = {
            f"{str(item.get('interpretation_id') or '').strip()}|{str(item.get('interaction_at') or '').strip()}"
            for item in existing.get("supporting_entries") or []
            if isinstance(item, dict)
        }
        for entry in group.get("supporting_entries") or []:
            if not isinstance(entry, dict):
                continue
            key = f"{str(entry.get('interpretation_id') or '').strip()}|{str(entry.get('interaction_at') or '').strip()}"
            if key in entry_seen:
                continue
            entry_seen.add(key)
            existing.setdefault("supporting_entries", []).append(entry)

        existing["supporting_entries"] = sorted(
            existing.get("supporting_entries") or [],
            key=lambda item: (
                _dt(item.get("interaction_at")),
                str(item.get("interpretation_id") or ""),
            ),
        )
        existing["entry_count"] = len(existing.get("supporting_entries") or [])

        if _dt(group.get("end_at")) >= _dt(existing.get("end_at")):
            for field in (
                "headline",
                "why_it_matters",
                "stage",
                "momentum",
                "confidence_score",
                "recommended_action",
                "topic",
                "topic_type",
                "topic_type_label",
            ):
                if group.get(field) not in (None, ""):
                    existing[field] = group.get(field)

        existing["window_label"] = _story_window_label(existing.get("start_at"), existing.get("end_at"))
        existing["timeline_summary"] = _storyline_timeline_summary(
            {"channels": existing.get("channels") or [], "entry_count": existing.get("entry_count") or 0},
            {
                "stage": existing.get("stage"),
                "momentum": existing.get("momentum"),
            },
        )

    return [merged[key] for key in ordered_keys]


def _relationship_situation_key(group: dict) -> str:
    explicit_thread_ids = [
        str(entry.get("thread_id") or "").strip()
        for entry in group.get("supporting_entries", [])
        if str(entry.get("thread_id") or "").strip()
    ]
    if explicit_thread_ids:
        anchor = f"thread|{explicit_thread_ids[0]}"
    else:
        anchor = "|".join(
            [
                str(group.get("topic_type") or "").strip().lower(),
                str(group.get("stage") or "").strip().lower(),
                str(group.get("topic") or group.get("headline") or "").strip().lower(),
            ]
        )
    digest = hashlib.sha1(anchor.encode("utf-8")).hexdigest()[:16]
    return f"{str(group.get('topic_type') or 'relationship')}:{digest}"


def _relationship_situation_status(group: dict) -> str:
    momentum = str(group.get("momentum") or "").lower()
    stage = str(group.get("stage") or "").lower()
    headline = str(group.get("headline") or "").lower()
    if any(token in " ".join([momentum, stage, headline]) for token in ("stalled", "blocked", "delay", "delayed", "friction")):
        return "stalled"
    if str(group.get("topic_type") or "") in {"market", "relationship", "influence"} and momentum in {"", "steady", "neutral"}:
        return "watching"
    return "open"


def _relationship_situation_status_label(status: str) -> str:
    return {
        "open": "Open",
        "watching": "Watching",
        "stalled": "Stalled",
        "closed": "Closed",
    }.get(str(status or "").lower(), "Watching")


def _relationship_situation_display_id(situation_type: str, situation_key: str) -> str:
    type_prefix = str(situation_type or "relationship")[:3].upper()
    key_tail = str(situation_key or "").split(":")[-1][:8].upper() or "TRACKED"
    return f"S-{type_prefix}-{key_tail}"


def _relationship_situation_event_summary(
    *,
    event_type: str,
    title: str,
    previous_status: str,
    new_status: str,
    previous_stage: str,
    new_stage: str,
    previous_momentum: str,
    new_momentum: str,
) -> str:
    if event_type == "opened":
        return f"Situation opened: {title}"
    if event_type == "manual_resolution":
        return f"Manual resolution recorded for: {title}"
    if event_type == "manual_update":
        return f"Manual update recorded for: {title}"
    if event_type == "reopened":
        return f"Situation reopened as {new_status or 'open'}: {title}"
    if event_type == "status_changed":
        return f"Situation status changed from {previous_status or 'unknown'} to {new_status or 'unknown'}."
    if event_type == "stage_changed":
        return f"Situation stage changed from {previous_stage or 'unknown'} to {new_stage or 'unknown'}."
    if event_type == "momentum_changed":
        return f"Situation momentum changed from {previous_momentum or 'unknown'} to {new_momentum or 'unknown'}."
    if event_type == "closed":
        return f"Situation closed: {title}"
    return f"Situation refreshed: {title}"


def _preserve_recent_manual_close(existing: dict, grouped_last_seen_at: str | None) -> bool:
    if str(existing.get("status") or "").lower() != "closed":
        return False
    if not str(existing.get("resolution_note") or "").strip():
        return False
    manual_state_dt = _parse_datetime(existing.get("state_changed_at") or existing.get("updated_at"))
    grouped_last_seen_dt = _parse_datetime(grouped_last_seen_at)
    if not manual_state_dt:
        return False
    if not grouped_last_seen_dt:
        return True
    return manual_state_dt > grouped_last_seen_dt


def _preserve_recent_manual_override(manual_event: dict | None, grouped_last_seen_at: str | None) -> bool:
    if not manual_event:
        return False
    manual_dt = _parse_datetime(manual_event.get("created_at"))
    grouped_last_seen_dt = _parse_datetime(grouped_last_seen_at)
    if not manual_dt:
        return False
    if not grouped_last_seen_dt:
        return True
    return manual_dt >= grouped_last_seen_dt


def _strip_signature_noise(text: str) -> str:
    cleaned = str(text or "")
    signature_markers = (
        "\nfrom:",
        "\nphone / whatsapp",
        "\nphone:",
        "\nfollow us on linkedin",
        "\nvisit us:",
        "\nmanaging partner",
        "\nkind regards",
        "\nbest regards",
        "\nregards,",
    )
    lowered = cleaned.lower()
    cut_points = [lowered.find(marker) for marker in signature_markers if lowered.find(marker) != -1]
    if cut_points:
        cleaned = cleaned[: min(cut_points)]
    return cleaned.strip()


def _detect_third_party_subject(text: str) -> str:
    patterns = (
        r"\bmet with ([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        r"\bspoke with ([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?) is focused on\b",
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?) is seeking\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def _memory_type_for_domain(domain: str) -> str:
    return {
        "rapport": "relationship_memory",
        "opportunity": "opportunity_memory",
        "influence": "influence_memory",
        "risk": "risk_memory",
        "market": "market_memory",
    }.get(domain, "relationship_memory")


def _market_topic_from_item(item: dict) -> str:
    stage = str(item.get("stage") or "").strip()
    if "market" in stage.lower():
        return "Market Pulse"
    return "Talent & Search Market"


def _derive_market_theme_labels(text: str) -> list[str]:
    labels = []
    theme_rules = (
        (("salary pressure", "compensation pressure", "package"), "Compensation and package pressure"),
        (("talent shortage", "shortage of", "talent in short supply"), "Talent shortage"),
        (("ai expansion", "llm", "fine-tuning", "artificial intelligence"), "AI expansion demand"),
        (("hiring demand", "headcount growth", "expansion in", "growth in"), "Active hiring expansion"),
        (("market is slowing", "slowdown in", "slower market"), "Market slowdown"),
        (("project pipeline", "pipeline", "new projects", "project awards"), "Project pipeline movement"),
    )
    for patterns, label in theme_rules:
        if any(pattern in text for pattern in patterns) and label not in labels:
            labels.append(label)
    return labels


def _has_explicit_market_view(text: str) -> bool:
    patterns = (
        "market is", "market's", "in the market", "across the market",
        "salary pressure", "compensation pressure", "talent shortage", "shortage of",
        "hiring demand", "candidate market", "clients are", "firms are",
        "growth in", "slowdown in", "expansion in", "headcount growth",
    )
    return any(pattern in text for pattern in patterns)


def _derive_market_specific_points(text: str) -> list[str]:
    points: list[str] = []
    lowered = text.lower()
    if "ai expansion" in lowered or "llm" in lowered or "fine-tuning" in lowered:
        points.append("AI expansion in MENA is driving demand for LLM fine-tuning talent.")
    if "salary pressure" in lowered or "compensation pressure" in lowered:
        points.append("Compensation pressure is rising in the market.")
    if "shortage of" in lowered and "talent" in lowered:
        points.append("There is a shortage of senior talent in the market.")
    if "headcount growth" in lowered or ("expansion" in lowered and "hiring" in lowered):
        points.append("Hiring expansion is increasing headcount demand in the market.")
    if "slowdown" in lowered:
        points.append("The market is showing signs of slowdown.")
    if "pipeline" in lowered and ("project" in lowered or "awards" in lowered):
        points.append("Project pipeline movement is shaping hiring demand.")
    if points:
        return points

    segments = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    for segment in segments:
        cleaned = " ".join(segment.split()).strip(" -:")
        if not cleaned:
            continue
        lowered_segment = cleaned.lower()
        if _keyword_hits(lowered_segment, ("market", "salary", "compensation", "talent", "demand", "supply", "expansion", "growth", "headcount", "pipeline")):
            if len(cleaned) > 180:
                cleaned = _clip(cleaned, 180)
            if not cleaned.endswith("."):
                cleaned += "."
            points.append(cleaned[0].upper() + cleaned[1:] if len(cleaned) > 1 else cleaned.upper())
            break
    return points


def _has_real_rapport_marker(text: str) -> bool:
    if _is_courtesy_only_rapport_text(text):
        return False
    rapport_terms = (
        "family", "wife", "husband", "daughter", "son", "kids", "children", "golf",
        "travel", "holiday", "weekend", "father", "mother", "birthday", "ramadan", "eid",
    )
    return any(term in text for term in rapport_terms)


def _is_courtesy_only_rapport_text(text: str | None) -> bool:
    lowered = " ".join(str(text or "").lower().split())
    if not lowered:
        return False
    strong_personal_markers = (
        "daughter",
        "son",
        "kids",
        "children",
        "wife",
        "husband",
        "family",
        "golf",
        "travel",
        "birthday",
        "school",
        "rugby",
        "football",
        "christopher",
        "jimmy",
        "susie",
    )
    if any(marker in lowered for marker in strong_personal_markers):
        return False
    courtesy_patterns = (
        r"hope (?:that )?you(?:'re| are)? well",
        r"hope (?:that )?you(?:'re| are)? having a good ramadan(?: so far)?",
        r"hope (?:that )?you had a (?:good|nice) weekend",
        r"hope the weekend was nice(?: and relaxing)?",
        r"enjoy the holiday",
        r"had a nice holiday",
    )
    if any(re.search(pattern, lowered) for pattern in courtesy_patterns):
        return True
    courtesy_tokens = ("hope", "well", "good", "nice", "weekend", "ramadan", "eid", "holiday")
    words = re.findall(r"[a-z']+", lowered)
    if words and len(words) <= 14 and any(token in lowered for token in ("weekend", "ramadan", "eid", "holiday")):
        if all(word in courtesy_tokens for word in words):
            return True
    return False


def _infer_relationship_trajectory(text: str) -> str:
    if any(term in text for term in ("good to reconnect", "great catching up", "great to see you", "back in touch", "reconnect")):
        return "reactivating"
    if any(term in text for term in ("great catching up", "great to see you", "appreciate your help", "thanks for hosting", "thanks for arranging")):
        return "warming"
    if any(term in text for term in ("delay", "apologies", "sorry", "slow", "stalled", "issue", "problem")):
        return "under_strain"
    return ""


def _infer_timing_triggers(text: str) -> list[str]:
    triggers = []
    trigger_patterns = (
        ("next week", "Next-week timing is explicitly mentioned."),
        ("this week", "This-week timing is explicitly mentioned."),
        ("by friday", "A near-term deadline is explicitly mentioned."),
        ("clock is ticking", "Timing pressure is explicitly stated."),
        ("urgent", "Urgency is explicitly stated."),
        ("before ramadan", "A seasonal timing trigger is explicitly stated."),
        ("after ramadan", "A seasonal timing trigger is explicitly stated."),
        ("after eid", "A post-Eid timing trigger is explicitly stated."),
        ("end of month", "Month-end timing is explicitly mentioned."),
    )
    for pattern, label in trigger_patterns:
        if pattern in text and label not in triggers:
            triggers.append(label)
    return triggers


def _infer_intent_signals(text: str) -> list[str]:
    signals = []
    if any(term in text for term in ("want to", "would like to", "keen to", "looking to", "plan to", "aim to")):
        signals.append("The contact is expressing forward intent directly.")
    if any(term in text for term in ("need", "needs", "must", "priority", "important")):
        signals.append("The contact is signaling a concrete requirement or priority.")
    if any(term in text for term in ("introduce", "connect", "open access", "make an introduction")):
        signals.append("The contact is signaling intent to engage or open access.")
    return signals


def _interpret_interaction(row: dict) -> dict | None:
    raw_text = " ".join(
        part for part in [row.get("summary"), row.get("raw_text")] if str(part or "").strip()
    ).strip()
    if not raw_text:
        return None

    core_text = _strip_signature_noise(raw_text)
    lowered = core_text.lower()
    third_party_subject = _detect_third_party_subject(core_text)
    hiring_terms = (
        "interview", "candidate", "shortlist", "offer", "recruit", "recruitment",
        "search", "mandate", "role", "position", "cv", "resume",
    )
    commercial_progression_terms = (
        "agreement", "signature", "sign", "signed", "contract", "assignment", "kick off",
        "kickoff", "long term relationship", "long-term relationship", "reshare the agreement",
    )
    payment_terms = (
        "payment", "invoice", "fee", "fees", "salary", "package", "budget", "cost", "flight",
        "allowance", "retainer", "paid",
    )
    market_terms = (
        "market", "sector", "hiring", "salary", "compensation", "talent", "pipeline",
        "demand", "supply", "expansion", "growth", "slowdown", "headcount", "move",
    )
    influence_terms = (
        "introduce", "introduction", "connect", "connector", "champion", "influence",
        "decision", "stakeholder", "board", "ceo", "chairman", "partner",
    )
    friction_terms = (
        "delay", "issue", "problem", "blocked", "concern", "pressure", "friction",
        "risk", "hesitation", "stalled", "pushback", "difficult", "slow",
    )
    next_step_terms = ("arrange", "schedule", "scheduled", "confirm", "next step")

    relationship_signals: list[str] = []
    opportunity_signals: list[str] = []
    influence_signals: list[str] = []
    market_intel_signals: list[str] = []
    pain_points: list[str] = []
    friction_signals: list[str] = []
    intent_signals: list[str] = _infer_intent_signals(lowered)
    timing_triggers: list[str] = _infer_timing_triggers(lowered)
    evidence_terms: list[str] = []
    happening_parts: list[str] = []
    why_parts: list[str] = []
    market_specific_points: list[str] = _derive_market_specific_points(core_text)

    if _keyword_hits(lowered, hiring_terms):
        happening_parts.append("An active hiring or search process is being discussed.")
        opportunity_signals.append("Executive search or hiring activity is live.")
        evidence_terms.extend(hiring_terms)
    if _keyword_hits(lowered, commercial_progression_terms):
        happening_parts.append("The search assignment is moving into formal commercial commitment.")
        opportunity_signals.append("Assignment confirmation or signature progress is visible.")
        why_parts.append("This is commercial progression toward a live client relationship, not only process chatter.")
        evidence_terms.extend(commercial_progression_terms)
    if "agreement" in lowered and "signature" in lowered:
        pain_points.append("Agreement execution still needs to be completed.")
    if "delay" in lowered or "apologies for the delay" in lowered:
        friction_signals.append("There has been delay on the client side.")
    if _keyword_hits(lowered, ("interview", "shortlist", "offer", "schedule", "arrange")):
        happening_parts.append("Process stage movement is visible through shortlist, interview, or offer coordination.")
        why_parts.append("This is operational movement rather than a generic relationship update.")
        evidence_terms.extend(("interview", "shortlist", "offer", "schedule", "arrange"))
    if _keyword_hits(lowered, payment_terms):
        happening_parts.append("Commercial terms, cost, or package details are being discussed.")
        friction_signals.append("Commercial sensitivity is visible in the correspondence.")
        pain_points.append("Payment, fee, salary, or package terms need active management.")
        why_parts.append("Commercial friction can slow or derail progress if it is not handled directly.")
        evidence_terms.extend(payment_terms)
    if _keyword_hits(lowered, market_terms) and _has_explicit_market_view(lowered):
        if market_specific_points:
            happening_parts.extend(market_specific_points[:2])
            market_intel_signals.extend(market_specific_points[:2])
            if third_party_subject:
                happening_parts.append(f"The source note attributes this market signal to {third_party_subject}.")
                market_intel_signals.append(f"Source note attributes this market signal to {third_party_subject}.")
        elif third_party_subject:
            happening_parts.append(f"The source note attributes a market view to {third_party_subject}.")
            market_intel_signals.append(f"Market signal attributed to {third_party_subject}, not directly to the profile owner.")
        else:
            happening_parts.append("A concrete market view is captured in the source evidence.")
            market_intel_signals.append("A concrete market view is captured in the source evidence.")
        why_parts.append("This contributes to platform-level market intelligence that should inform future search and network decisions.")
        evidence_terms.extend(market_terms)
    explicit_influence = _keyword_hits(lowered, ("introduce", "introduction", "connect", "connector", "champion", "influence", "decision", "stakeholder", "board", "ceo", "chairman"))
    if explicit_influence:
        happening_parts.append("The interaction shows influence, access, or decision-shaping potential around the relationship.")
        influence_signals.append("The interaction points to door-opening or decision influence around the relationship.")
        why_parts.append("Influence pathways matter even when there is no immediate direct opportunity.")
        evidence_terms.extend(("introduce", "introduction", "connect", "connector", "champion", "influence", "decision", "stakeholder", "board", "ceo", "chairman"))
    if _has_real_rapport_marker(lowered):
        happening_parts.append("The interaction contains meaningful personal or rapport-relevant context.")
        relationship_signals.append("The interaction contains rapport-relevant personal context worth retaining.")
        why_parts.append("Personal context supports relationship continuity and higher-quality engagement.")
        evidence_terms.extend(("family", "golf", "travel", "holiday", "weekend", "ramadan", "eid", "birthday"))
    if _keyword_hits(lowered, friction_terms):
        friction_signals.append("The interaction contains process friction or execution risk.")
        pain_points.append("A blocker, concern, or slowdown is visible in the thread.")
        evidence_terms.extend(friction_terms)
    if _keyword_hits(lowered, next_step_terms):
        evidence_terms.extend(next_step_terms)

    if timing_triggers:
        why_parts.append("There is explicit timing pressure or a stated trigger in the interaction.")
        evidence_terms.extend(("next week", "this week", "urgent", "clock is ticking", "before ramadan", "after ramadan", "after eid"))

    stage = "Relationship Update"
    if "interview" in lowered or "shortlist" in lowered:
        stage = "Interview Coordination"
    elif "agreement" in lowered or "signature" in lowered or "assignment" in lowered or "contract" in lowered:
        stage = "Assignment / Signature Progression"
    elif "offer" in lowered or "package" in lowered or "salary" in lowered:
        stage = "Offer / Package Discussion"
    elif _keyword_hits(lowered, market_terms):
        stage = "Market Intel Exchange"
    elif explicit_influence:
        stage = "Influence / Introduction"

    momentum = "steady"
    if _keyword_hits(lowered, ("arrange", "schedule", "confirmed", "progress", "moving", "next step", "interview", "signature", "agreement", "kick off", "kickoff")):
        momentum = "advancing"
    if _keyword_hits(lowered, friction_terms + payment_terms):
        momentum = "at_risk" if momentum != "advancing" else "advancing_with_friction"
    relationship_trajectory = _infer_relationship_trajectory(lowered)

    recommended_action = "Keep the relationship active and retain the evidence in interpreted memory."
    if opportunity_signals and friction_signals:
        recommended_action = "Stay close to the process, track the commercial friction, and turn the evidence into an explicit opportunity record."
    elif opportunity_signals:
        recommended_action = "Track the process stage directly and convert the thread into an active opportunity or hiring record."
    elif market_intel_signals:
        recommended_action = "Promote the market view into market intel memory and use it to shape future outreach and search positioning."
    elif relationship_signals:
        recommended_action = "Retain the relationship context and use it to improve the next engagement."

    if not happening_parts and not relationship_signals and not market_intel_signals and not opportunity_signals and not friction_signals and not influence_signals and not intent_signals:
        return None
    if not why_parts:
        why_parts.append("This interaction changes the working picture enough to retain as interpreted memory.")

    relationship_extras = []
    if relationship_trajectory:
        relationship_extras.append(f"Relationship trajectory is {relationship_trajectory}.")
    relationship_extras.extend(timing_triggers)

    evidence_snippets = _extract_evidence_snippets(raw_text, tuple(dict.fromkeys(evidence_terms)))
    confidence = min(
        95,
        40
        + (10 if opportunity_signals else 0)
        + (10 if market_intel_signals else 0)
        + (10 if relationship_signals else 0)
        + (10 if friction_signals else 0)
        + (10 if len(evidence_snippets) > 1 else 0),
    )

    return {
        "person_id": row["person_id"],
        "company_name_raw": row.get("company_name_raw"),
        "source_interaction_id": row["interaction_id"],
        "source_kind": "interaction",
        "thread_id": row.get("external_id"),
        "what_is_happening": " ".join(dict.fromkeys(happening_parts)),
        "why_it_matters": " ".join(dict.fromkeys(why_parts)),
        "stage": stage,
        "momentum": momentum,
        "intent_signals_json": _json_array(intent_signals),
        "pain_points_json": _json_array(pain_points),
        "relationship_signals_json": _json_array(relationship_signals + relationship_extras),
        "opportunity_signals_json": _json_array(opportunity_signals),
        "influence_signals_json": _json_array(influence_signals),
        "market_intel_signals_json": _json_array(market_intel_signals),
        "friction_signals_json": _json_array(friction_signals),
        "recommended_action": recommended_action,
        "confidence_score": confidence,
        "evidence_snippets_json": json.dumps(evidence_snippets, ensure_ascii=False),
    }


async def refresh_interpreted_interactions_for_person(person_id: str, limit: int = 10) -> None:
    async def _read(db):
        async with db.execute(
            """
            SELECT
                i.interaction_id,
                i.person_id,
                i.channel,
                i.summary,
                i.raw_text,
                i.external_id,
                i.interaction_at,
                p.company_name_raw
            FROM INTERACTION i
            JOIN PERSON p ON p.person_id = i.person_id
            WHERE i.person_id = ?
              AND COALESCE(i.channel, '') NOT IN ('system_audit', 'imported')
              AND TRIM(COALESCE(i.summary, i.raw_text, '')) != ''
            ORDER BY datetime(i.interaction_at) DESC, i.interaction_id DESC
            LIMIT ?
            """,
            (person_id, max(limit * 6, 40)),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    interactions = await run_read(_read, label="load interpreted interactions source data")
    recent_interactions = [row for row in interactions if _is_recent_enough(row.get("interaction_at"))][:limit]
    interpreted_rows = [item for item in (_interpret_interaction(row) for row in recent_interactions) if item]
    kept_source_ids = {row["source_interaction_id"] for row in interpreted_rows}

    now = _now()

    async def _write(db):
        placeholders = ",".join("?" for _ in kept_source_ids) if kept_source_ids else ""
        if kept_source_ids:
            await db.execute(
                f"""
                DELETE FROM INTERPRETED_INTERACTION
                WHERE person_id = ?
                  AND source_interaction_id NOT IN ({placeholders})
                """,
                tuple([person_id] + list(kept_source_ids)),
            )
        else:
            await db.execute(
                "DELETE FROM INTERPRETED_INTERACTION WHERE person_id = ?",
                (person_id,),
            )
            return
        for row in interpreted_rows:
            async with db.execute(
                """
                SELECT interpretation_id, created_at
                FROM INTERPRETED_INTERACTION
                WHERE source_interaction_id = ?
                LIMIT 1
                """,
                (row["source_interaction_id"],),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing:
                await db.execute(
                    """
                    UPDATE INTERPRETED_INTERACTION
                    SET person_id = ?, company_name_raw = ?, source_kind = ?, thread_id = ?,
                        what_is_happening = ?, why_it_matters = ?, stage = ?, momentum = ?,
                        intent_signals_json = ?, pain_points_json = ?, relationship_signals_json = ?,
                        opportunity_signals_json = ?, influence_signals_json = ?, market_intel_signals_json = ?,
                        friction_signals_json = ?, recommended_action = ?, confidence_score = ?,
                        evidence_snippets_json = ?, updated_at = ?
                    WHERE interpretation_id = ?
                    """,
                    (
                        row["person_id"],
                        row.get("company_name_raw"),
                        row["source_kind"],
                        row.get("thread_id"),
                        row["what_is_happening"],
                        row["why_it_matters"],
                        row["stage"],
                        row["momentum"],
                        row["intent_signals_json"],
                        row["pain_points_json"],
                        row["relationship_signals_json"],
                        row["opportunity_signals_json"],
                        row["influence_signals_json"],
                        row["market_intel_signals_json"],
                        row["friction_signals_json"],
                        row["recommended_action"],
                        row["confidence_score"],
                        row["evidence_snippets_json"],
                        now,
                        existing["interpretation_id"],
                    ),
                )
            else:
                await db.execute(
                    """
                    INSERT INTO INTERPRETED_INTERACTION (
                        interpretation_id, person_id, company_name_raw, source_interaction_id, source_kind, thread_id,
                        what_is_happening, why_it_matters, stage, momentum,
                        intent_signals_json, pain_points_json, relationship_signals_json, opportunity_signals_json,
                        influence_signals_json, market_intel_signals_json, friction_signals_json,
                        recommended_action, confidence_score, evidence_snippets_json, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4())[:12],
                        row["person_id"],
                        row.get("company_name_raw"),
                        row["source_interaction_id"],
                        row["source_kind"],
                        row.get("thread_id"),
                        row["what_is_happening"],
                        row["why_it_matters"],
                        row["stage"],
                        row["momentum"],
                        row["intent_signals_json"],
                        row["pain_points_json"],
                        row["relationship_signals_json"],
                        row["opportunity_signals_json"],
                        row["influence_signals_json"],
                        row["market_intel_signals_json"],
                        row["friction_signals_json"],
                        row["recommended_action"],
                        row["confidence_score"],
                        row["evidence_snippets_json"],
                        now,
                        now,
                    ),
                )

    await run_write(_write, label="refresh interpreted interactions")


async def load_interpreted_interactions(person_id: str, limit: int = 8) -> list[dict]:
    async def _read(db):
        async with db.execute(
            """
            SELECT
                ii.interpretation_id,
                ii.person_id,
                ii.company_name_raw,
                ii.source_interaction_id,
                ii.source_kind,
                ii.thread_id,
                ii.what_is_happening,
                ii.why_it_matters,
                ii.stage,
                ii.momentum,
                ii.intent_signals_json,
                ii.pain_points_json,
                ii.relationship_signals_json,
                ii.opportunity_signals_json,
                ii.influence_signals_json,
                ii.market_intel_signals_json,
                ii.friction_signals_json,
                ii.recommended_action,
                ii.confidence_score,
                ii.evidence_snippets_json,
                ii.created_at,
                ii.updated_at,
                i.interaction_at,
                i.channel,
                i.summary AS source_summary,
                i.raw_text AS source_raw_text
            FROM INTERPRETED_INTERACTION ii
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE ii.person_id = ?
            ORDER BY datetime(ii.updated_at) DESC, ii.interpretation_id DESC
            """,
            (person_id,),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
        rows = [row for row in rows if _is_recent_enough(row.get("interaction_at"))][:limit]
        for row in rows:
            for field in (
                "intent_signals_json",
                "pain_points_json",
                "relationship_signals_json",
                "opportunity_signals_json",
                "influence_signals_json",
                "market_intel_signals_json",
                "friction_signals_json",
                "evidence_snippets_json",
            ):
                try:
                    row[field.replace("_json", "")] = json.loads(row.get(field) or "[]")
                except json.JSONDecodeError:
                    row[field.replace("_json", "")] = []
            row["headline"] = _clip(row.get("what_is_happening") or "")
            row["full_evidence_text"] = _build_full_evidence_text(row.get("source_summary"), row.get("source_raw_text"))
            row["display_channel"] = _display_channel_label(
                row.get("channel"),
                row.get("source_summary"),
                row.get("source_raw_text"),
            )
        return rows

    return await run_read(_read, label="load interpreted interactions")


def _deserialize_interpreted_row(row: dict) -> dict:
    parsed = dict(row)
    for field in (
        "intent_signals_json",
        "pain_points_json",
        "relationship_signals_json",
        "opportunity_signals_json",
        "influence_signals_json",
        "market_intel_signals_json",
        "friction_signals_json",
        "evidence_snippets_json",
    ):
        try:
            parsed[field.replace("_json", "")] = json.loads(parsed.get(field) or "[]")
        except json.JSONDecodeError:
            parsed[field.replace("_json", "")] = []
    parsed["headline"] = _clip(parsed.get("what_is_happening") or "")
    parsed["full_evidence_text"] = _build_full_evidence_text(parsed.get("summary"), parsed.get("raw_text"))
    parsed["display_channel"] = _display_channel_label(
        parsed.get("channel"),
        parsed.get("summary"),
        parsed.get("raw_text"),
    )
    return parsed


async def load_interpreted_databank(person_ids: list[str], limit: int = 120) -> dict:
    if not person_ids:
        return {
            "market_intel": [],
            "opportunity_watch": [],
            "rapport_memory": [],
            "friction_watch": [],
            "influence_map": [],
            "intent_watch": [],
            "relationship_trajectory": [],
            "timing_triggers": [],
            "market_themes": [],
            "summary": {
                "items_scanned": 0,
                "market_intel_count": 0,
                "opportunity_watch_count": 0,
                "rapport_memory_count": 0,
                "friction_watch_count": 0,
                "influence_map_count": 0,
                "intent_watch_count": 0,
                "relationship_trajectory_count": 0,
                "timing_trigger_count": 0,
                "market_theme_count": 0,
            },
        }

    async def _read(db):
        placeholders = ",".join("?" for _ in person_ids)
        async with db.execute(
            f"""
            SELECT
                ii.*,
                p.full_name,
                p.title_current,
                p.company_name_raw AS person_company_name_raw,
                p.network_tier,
                p.relationship_owner,
                i.channel,
                i.interaction_at,
                i.summary,
                i.raw_text
            FROM INTERPRETED_INTERACTION ii
            JOIN PERSON p ON p.person_id = ii.person_id
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE ii.person_id IN ({placeholders})
            ORDER BY datetime(ii.updated_at) DESC, ii.interpretation_id DESC
            LIMIT ?
            """,
            tuple(person_ids + [limit]),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            f"""
            SELECT source_interpretation_id, memory_domain, status
            FROM ENDURING_MEMORY
            WHERE person_id IN ({placeholders})
            """,
            tuple(person_ids),
        ) as cursor:
            enduring_rows = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            """
            SELECT source_interpretation_id, status
            FROM MARKET_INTEL
            """
        ) as cursor:
            market_rows = [dict(row) for row in await cursor.fetchall()]
        return rows, enduring_rows, market_rows

    rows, enduring_rows, market_rows = await run_read(_read, label="load interpreted databank")
    rows = [
        _deserialize_interpreted_row(row)
        for row in rows
        if _is_recent_enough(row.get("interaction_at"))
    ]
    enduring_lookup: dict[tuple[str, str], str] = {
        (str(row.get("source_interpretation_id") or ""), str(row.get("memory_domain") or "")): str(row.get("status") or "")
        for row in enduring_rows
        if row.get("source_interpretation_id")
    }
    market_lookup: dict[str, str] = {
        str(row.get("source_interpretation_id") or ""): str(row.get("status") or "")
        for row in market_rows
        if row.get("source_interpretation_id")
    }

    def _shape(item: dict, domain_label: str, chips: list[str]) -> dict:
        domain_key = {
            "Market Intel": "market_intel",
            "Opportunity Watch": "opportunity",
            "Intent Watch": "opportunity",
            "Rapport Memory": "rapport",
            "Relationship Trajectory": "rapport",
            "Timing Triggers": "risk",
            "Friction Watch": "risk",
            "Influence Map": "influence",
        }.get(domain_label, "")
        return {
            "interpretation_id": item.get("interpretation_id"),
            "person_id": item.get("person_id"),
            "full_name": item.get("full_name"),
            "title_current": item.get("title_current"),
            "company_name_raw": item.get("person_company_name_raw") or item.get("company_name_raw"),
            "network_tier": item.get("network_tier"),
            "relationship_owner": item.get("relationship_owner"),
            "channel": item.get("channel"),
            "interaction_at": item.get("interaction_at"),
            "stage": item.get("stage"),
            "momentum": item.get("momentum"),
            "confidence_score": item.get("confidence_score"),
            "what_is_happening": item.get("what_is_happening"),
            "why_it_matters": item.get("why_it_matters"),
            "recommended_action": item.get("recommended_action"),
            "evidence_snippets": item.get("evidence_snippets", []),
            "full_evidence_text": item.get("full_evidence_text"),
            "source_channel": item.get("channel"),
            "source_summary": item.get("summary"),
            "domain_label": domain_label,
            "domain_key": domain_key,
            "chips": chips,
            "promoted_memory_status": enduring_lookup.get((str(item.get("interpretation_id") or ""), domain_key)),
            "promoted_market_intel_status": market_lookup.get(str(item.get("interpretation_id") or "")),
        }

    market_intel = []
    opportunity_watch = []
    rapport_memory = []
    friction_watch = []
    influence_map = []
    intent_watch = []
    relationship_trajectory = []
    timing_triggers = []
    market_theme_counts: dict[str, dict] = {}

    for item in rows:
        if item.get("market_intel_signals"):
            market_intel.append(_shape(item, "Market Intel", item["market_intel_signals"][:3]))
            for signal in _derive_market_theme_labels(" ".join([
                str(item.get("what_is_happening") or ""),
                str(item.get("why_it_matters") or ""),
                " ".join(item.get("evidence_snippets", [])),
            ])):
                bucket = market_theme_counts.setdefault(signal, {"count": 0, "people": set(), "companies": set(), "evidence": []})
                bucket["count"] += 1
                if item.get("person_id"):
                    bucket["people"].add(item["person_id"])
                if item.get("person_company_name_raw") or item.get("company_name_raw"):
                    bucket["companies"].add(item.get("person_company_name_raw") or item.get("company_name_raw"))
                for snippet in item.get("evidence_snippets", [])[:1]:
                    if snippet not in bucket["evidence"]:
                        bucket["evidence"].append(snippet)
        if item.get("opportunity_signals"):
            opportunity_watch.append(_shape(item, "Opportunity Watch", item["opportunity_signals"][:3]))
        rapport_only = [signal for signal in item.get("relationship_signals", []) if "rapport" in signal.lower() or "personal context" in signal.lower()]
        if rapport_only:
            rapport_memory.append(_shape(item, "Rapport Memory", rapport_only[:3]))
        if item.get("friction_signals") or item.get("pain_points"):
            friction_watch.append(_shape(item, "Friction Watch", (item.get("friction_signals") or item.get("pain_points") or [])[:3]))
        if item.get("influence_signals"):
            influence_map.append(_shape(item, "Influence Map", item["influence_signals"][:3]))
        if item.get("intent_signals"):
            intent_watch.append(_shape(item, "Intent Watch", item["intent_signals"][:3]))
        trajectory_signals = [signal for signal in item.get("relationship_signals", []) if signal.lower().startswith("relationship trajectory is")]
        if trajectory_signals:
            relationship_trajectory.append(_shape(item, "Relationship Trajectory", trajectory_signals[:3]))
        timing_only = [signal for signal in item.get("relationship_signals", []) if "timing" in signal.lower() or "deadline" in signal.lower() or "trigger" in signal.lower()]
        if timing_only:
            timing_triggers.append(_shape(item, "Timing Triggers", timing_only[:3]))

    def _dedupe(items: list[dict]) -> list[dict]:
        seen: set[str] = set()
        deduped = []
        for item in items:
            key = item["interpretation_id"]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    market_intel = _dedupe(market_intel)[:30]
    opportunity_watch = _dedupe(opportunity_watch)[:30]
    rapport_memory = _dedupe(rapport_memory)[:30]
    friction_watch = _dedupe(friction_watch)[:30]
    influence_map = _dedupe(influence_map)[:30]
    intent_watch = _dedupe(intent_watch)[:30]
    relationship_trajectory = _dedupe(relationship_trajectory)[:30]
    timing_triggers = _dedupe(timing_triggers)[:30]
    market_themes = sorted(
        [
            {
                "theme": theme,
                "count": bucket["count"],
                "people_count": len(bucket["people"]),
                "company_count": len(bucket["companies"]),
                "evidence_snippets": bucket["evidence"][:2],
            }
            for theme, bucket in market_theme_counts.items()
        ],
        key=lambda item: (-item["count"], item["theme"].lower()),
    )[:20]

    return {
        "market_intel": market_intel,
        "opportunity_watch": opportunity_watch,
        "rapport_memory": rapport_memory,
        "friction_watch": friction_watch,
        "influence_map": influence_map,
        "intent_watch": intent_watch,
        "relationship_trajectory": relationship_trajectory,
        "timing_triggers": timing_triggers,
        "market_themes": market_themes,
        "summary": {
            "items_scanned": len(rows),
            "market_intel_count": len(market_intel),
            "opportunity_watch_count": len(opportunity_watch),
            "rapport_memory_count": len(rapport_memory),
            "friction_watch_count": len(friction_watch),
            "influence_map_count": len(influence_map),
            "intent_watch_count": len(intent_watch),
            "relationship_trajectory_count": len(relationship_trajectory),
            "timing_trigger_count": len(timing_triggers),
            "market_theme_count": len(market_themes),
        },
    }


async def promote_interpretation_to_enduring_memory(
    interpretation_id: str,
    *,
    memory_domain: str,
    status: str = "approved",
) -> dict:
    now = _now()

    async def _write(db):
        async with db.execute(
            """
            SELECT ii.interpretation_id, ii.person_id, ii.source_interaction_id, ii.what_is_happening, ii.why_it_matters,
                   ii.confidence_score, ii.evidence_snippets_json, i.interaction_at
            FROM INTERPRETED_INTERACTION ii
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE ii.interpretation_id = ?
            """,
            (interpretation_id,),
        ) as cursor:
            interpretation = await cursor.fetchone()
        if not interpretation:
            raise ValueError("Interpretation not found")
        interpretation = dict(interpretation)
        if not _is_recent_enough(interpretation.get("interaction_at")):
            raise ValueError("Interpretation is no longer within the live relevance window")
        async with db.execute(
            """
            SELECT memory_id
            FROM ENDURING_MEMORY
            WHERE source_interpretation_id = ? AND memory_domain = ?
            LIMIT 1
            """,
            (interpretation_id, memory_domain),
        ) as cursor:
            existing = await cursor.fetchone()
        memory_text = interpretation["what_is_happening"]
        if memory_domain in {"rapport", "risk", "opportunity", "influence"} and interpretation.get("why_it_matters"):
            memory_text = f"{interpretation['what_is_happening']} {interpretation['why_it_matters']}".strip()
        if existing:
            await db.execute(
                """
                UPDATE ENDURING_MEMORY
                SET memory_text = ?, importance_score = ?, confidence_score = ?, status = ?, evidence_snippets_json = ?, updated_at = ?
                WHERE memory_id = ?
                """,
                (
                    memory_text,
                    min(95, max(50, int(interpretation.get("confidence_score") or 50))),
                    int(interpretation.get("confidence_score") or 50),
                    status,
                    interpretation.get("evidence_snippets_json"),
                    now,
                    existing["memory_id"],
                ),
            )
            memory_id = existing["memory_id"]
        else:
            memory_id = str(uuid.uuid4())[:12]
            await db.execute(
                """
                INSERT INTO ENDURING_MEMORY (
                    memory_id, person_id, memory_domain, memory_type, memory_text,
                    importance_score, confidence_score, status, source_interpretation_id,
                    source_interaction_id, evidence_snippets_json, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    memory_id,
                    interpretation["person_id"],
                    memory_domain,
                    _memory_type_for_domain(memory_domain),
                    memory_text,
                    min(95, max(50, int(interpretation.get("confidence_score") or 50))),
                    int(interpretation.get("confidence_score") or 50),
                    status,
                    interpretation_id,
                    interpretation.get("source_interaction_id"),
                    interpretation.get("evidence_snippets_json"),
                    now,
                    now,
                ),
            )
        async with db.execute("SELECT * FROM ENDURING_MEMORY WHERE memory_id = ?", (memory_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    return await run_write(_write, label="promote enduring memory")


async def promote_interpretation_to_market_intel(
    interpretation_id: str,
    *,
    status: str = "approved",
) -> dict:
    now = _now()

    async def _write(db):
        async with db.execute(
            """
            SELECT ii.interpretation_id, ii.person_id, ii.company_name_raw, ii.what_is_happening, ii.why_it_matters, ii.stage,
                   ii.confidence_score, ii.evidence_snippets_json, ii.market_intel_signals_json, i.interaction_at
            FROM INTERPRETED_INTERACTION ii
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE ii.interpretation_id = ?
            """,
            (interpretation_id,),
        ) as cursor:
            interpretation = await cursor.fetchone()
        if not interpretation:
            raise ValueError("Interpretation not found")
        interpretation = dict(interpretation)
        if not _is_recent_enough(interpretation.get("interaction_at")):
            raise ValueError("Interpretation is no longer within the live relevance window")
        signal_text = interpretation["why_it_matters"] or interpretation["what_is_happening"]
        async with db.execute(
            "SELECT market_intel_id FROM MARKET_INTEL WHERE source_interpretation_id = ? LIMIT 1",
            (interpretation_id,),
        ) as cursor:
            existing = await cursor.fetchone()
        linked_people_json = json.dumps([interpretation["person_id"]], ensure_ascii=False)
        linked_companies_json = json.dumps([interpretation.get("company_name_raw")] if interpretation.get("company_name_raw") else [], ensure_ascii=False)
        if existing:
            await db.execute(
                """
                UPDATE MARKET_INTEL
                SET topic = ?, signal_text = ?, signal_type = ?, confidence_score = ?, importance_score = ?,
                    linked_people_json = ?, linked_companies_json = ?, evidence_snippets_json = ?, status = ?, updated_at = ?
                WHERE market_intel_id = ?
                """,
                (
                    _market_topic_from_item(interpretation),
                    signal_text,
                    "interpreted_interaction",
                    int(interpretation.get("confidence_score") or 50),
                    min(95, max(55, int(interpretation.get("confidence_score") or 50))),
                    linked_people_json,
                    linked_companies_json,
                    interpretation.get("evidence_snippets_json"),
                    status,
                    now,
                    existing["market_intel_id"],
                ),
            )
            market_intel_id = existing["market_intel_id"]
        else:
            market_intel_id = str(uuid.uuid4())[:12]
            await db.execute(
                """
                INSERT INTO MARKET_INTEL (
                    market_intel_id, topic, sector, region, signal_text, signal_type,
                    confidence_score, importance_score, linked_people_json, linked_companies_json,
                    evidence_snippets_json, status, source_interpretation_id, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    market_intel_id,
                    _market_topic_from_item(interpretation),
                    "Built Environment",
                    "Middle East",
                    signal_text,
                    "interpreted_interaction",
                    int(interpretation.get("confidence_score") or 50),
                    min(95, max(55, int(interpretation.get("confidence_score") or 50))),
                    linked_people_json,
                    linked_companies_json,
                    interpretation.get("evidence_snippets_json"),
                    status,
                    interpretation_id,
                    now,
                    now,
                ),
            )
        async with db.execute("SELECT * FROM MARKET_INTEL WHERE market_intel_id = ?", (market_intel_id,)) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    return await run_write(_write, label="promote market intel")


async def load_promoted_memory_for_person(person_id: str) -> dict:
    async def _read(db):
        async with db.execute(
            """
            SELECT em.memory_id, em.memory_domain, em.memory_type, em.memory_text, em.importance_score,
                   em.confidence_score, em.status, em.updated_at, i.interaction_at
            FROM ENDURING_MEMORY em
            LEFT JOIN INTERACTION i ON i.interaction_id = em.source_interaction_id
            WHERE em.person_id = ?
            ORDER BY CASE WHEN em.status = 'approved' THEN 0 ELSE 1 END, em.importance_score DESC, em.updated_at DESC
            """,
            (person_id,),
        ) as cursor:
            enduring = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            """
            SELECT mi.market_intel_id, mi.topic, mi.signal_text, mi.signal_type, mi.confidence_score,
                   mi.importance_score, mi.status, mi.updated_at, i.interaction_at
            FROM MARKET_INTEL mi
            LEFT JOIN INTERPRETED_INTERACTION ii ON ii.interpretation_id = mi.source_interpretation_id
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE mi.linked_people_json LIKE ?
            ORDER BY CASE WHEN mi.status = 'approved' THEN 0 ELSE 1 END, mi.importance_score DESC, mi.updated_at DESC
            """,
            (f'%{person_id}%',),
        ) as cursor:
            market = [dict(row) for row in await cursor.fetchall()]
        enduring = [row for row in enduring if _is_recent_enough(row.get("interaction_at"))][:24]
        market = [row for row in market if _is_recent_enough(row.get("interaction_at"))][:12]
        return {"enduring_memory": enduring, "promoted_market_intel": market}

    return await run_read(_read, label="load promoted memory")


async def load_review_queue(person_ids: list[str], limit: int = 80) -> dict:
    if not person_ids:
        return {
            "interpreted_drafts": [],
            "enduring_memory": [],
            "market_intel": [],
            "market_themes": [],
            "summary": {
                "interpreted_draft_count": 0,
                "enduring_pending_count": 0,
                "market_pending_count": 0,
                "theme_count": 0,
            },
        }

    async def _read(db):
        placeholders = ",".join("?" for _ in person_ids)
        async with db.execute(
            f"""
            SELECT
                ii.interpretation_id,
                ii.person_id,
                ii.stage,
                ii.momentum,
                ii.what_is_happening,
                ii.why_it_matters,
                ii.recommended_action,
                ii.confidence_score,
                ii.evidence_snippets_json,
                ii.intent_signals_json,
                ii.opportunity_signals_json,
                ii.market_intel_signals_json,
                ii.relationship_signals_json,
                p.full_name,
                p.title_current,
                p.company_name_raw,
                p.network_tier,
                p.relationship_owner,
                i.channel,
                i.interaction_at,
                i.summary,
                i.raw_text
            FROM INTERPRETED_INTERACTION ii
            JOIN PERSON p ON p.person_id = ii.person_id
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE ii.person_id IN ({placeholders})
            ORDER BY ii.confidence_score DESC, datetime(ii.updated_at) DESC
            LIMIT ?
            """,
            tuple(person_ids + [limit]),
        ) as cursor:
            interpreted = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            f"""
            SELECT
                em.memory_id,
                em.person_id,
                em.memory_domain,
                em.memory_type,
                em.memory_text,
                em.importance_score,
                em.confidence_score,
                em.status,
                em.source_interpretation_id,
                em.updated_at,
                em.evidence_snippets_json,
                p.full_name,
                p.title_current,
                p.company_name_raw,
                p.network_tier,
                p.relationship_owner,
                i.interaction_at,
                i.summary,
                i.raw_text
            FROM ENDURING_MEMORY em
            JOIN PERSON p ON p.person_id = em.person_id
            LEFT JOIN INTERACTION i ON i.interaction_id = em.source_interaction_id
            WHERE em.person_id IN ({placeholders})
            ORDER BY CASE WHEN em.status = 'draft' THEN 0 WHEN em.status = 'approved' THEN 1 ELSE 2 END,
                     em.importance_score DESC,
                     em.updated_at DESC
            LIMIT ?
            """,
            tuple(person_ids + [limit]),
        ) as cursor:
            enduring = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            f"""
            SELECT
                mi.market_intel_id,
                mi.topic,
                mi.sector,
                mi.region,
                mi.signal_text,
                mi.signal_type,
                mi.confidence_score,
                mi.importance_score,
                mi.status,
                mi.source_interpretation_id,
                mi.updated_at,
                mi.linked_people_json,
                mi.linked_companies_json,
                mi.evidence_snippets_json,
                ii.person_id,
                p.full_name,
                p.title_current,
                p.company_name_raw,
                p.network_tier,
                p.relationship_owner,
                i.interaction_at,
                i.summary,
                i.raw_text
            FROM MARKET_INTEL mi
            LEFT JOIN INTERPRETED_INTERACTION ii ON ii.interpretation_id = mi.source_interpretation_id
            LEFT JOIN PERSON p ON p.person_id = ii.person_id
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE ii.person_id IN ({placeholders})
            ORDER BY CASE WHEN mi.status = 'draft' THEN 0 WHEN mi.status = 'approved' THEN 1 ELSE 2 END,
                     mi.importance_score DESC,
                     mi.updated_at DESC
            LIMIT ?
            """,
            tuple(person_ids + [limit]),
        ) as cursor:
            market = [dict(row) for row in await cursor.fetchall()]
        return interpreted, enduring, market

    interpreted_rows, enduring_rows, market_rows = await run_read(_read, label="load review queue")
    interpreted_rows = [row for row in interpreted_rows if _is_recent_enough(row.get("interaction_at"))]
    enduring_rows = [row for row in enduring_rows if _is_recent_enough(row.get("interaction_at"))]
    market_rows = [row for row in market_rows if _is_recent_enough(row.get("interaction_at"))]

    enduring_lookup: dict[tuple[str, str], str] = {}
    market_lookup: dict[str, str] = {}

    for row in enduring_rows:
        try:
            row["evidence_snippets"] = json.loads(row.get("evidence_snippets_json") or "[]")
        except json.JSONDecodeError:
            row["evidence_snippets"] = []
        row["full_evidence_text"] = _build_full_evidence_text(row.get("summary"), row.get("raw_text"))
        if row.get("source_interpretation_id") and row.get("memory_domain"):
            enduring_lookup[(str(row["source_interpretation_id"]), str(row["memory_domain"]))] = str(row.get("status") or "")
    for row in market_rows:
        try:
            row["evidence_snippets"] = json.loads(row.get("evidence_snippets_json") or "[]")
        except json.JSONDecodeError:
            row["evidence_snippets"] = []
        try:
            row["linked_people"] = json.loads(row.get("linked_people_json") or "[]")
        except json.JSONDecodeError:
            row["linked_people"] = []
        try:
            row["linked_companies"] = json.loads(row.get("linked_companies_json") or "[]")
        except json.JSONDecodeError:
            row["linked_companies"] = []
        row["full_evidence_text"] = _build_full_evidence_text(row.get("summary"), row.get("raw_text"))
        if row.get("source_interpretation_id"):
            market_lookup[str(row["source_interpretation_id"])] = str(row.get("status") or "")

    interpreted_drafts = []
    for row in interpreted_rows:
        parsed = _deserialize_interpreted_row(row)
        memory_domains = []
        if parsed.get("market_intel_signals"):
            memory_domains.append("market")
        if parsed.get("opportunity_signals") or parsed.get("intent_signals"):
            memory_domains.append("opportunity")
        rapport_only = [signal for signal in parsed.get("relationship_signals", []) if "rapport" in signal.lower() or "personal context" in signal.lower()]
        if rapport_only:
            memory_domains.append("rapport")
        if parsed.get("friction_signals") or parsed.get("pain_points"):
            memory_domains.append("risk")
        if parsed.get("influence_signals"):
            memory_domains.append("influence")
        memory_statuses = {
            domain: enduring_lookup.get((str(parsed.get("interpretation_id") or ""), domain))
            for domain in memory_domains
        }
        parsed["source_channel"] = parsed.get("channel")
        parsed["source_summary"] = parsed.get("summary")
        parsed["draft_memory_statuses"] = memory_statuses
        parsed["promoted_market_intel_status"] = market_lookup.get(str(parsed.get("interpretation_id") or ""))
        parsed["needs_review"] = any(status != "approved" for status in memory_statuses.values()) or (
            bool(parsed.get("market_intel_signals")) and parsed["promoted_market_intel_status"] != "approved"
        ) or (not memory_statuses and not parsed.get("promoted_market_intel_status"))
        if parsed["needs_review"]:
            interpreted_drafts.append(parsed)

    theme_buckets: dict[str, dict] = {}
    for row in market_rows:
        theme = str(row.get("topic") or "").strip() or "Unclassified theme"
        bucket = theme_buckets.setdefault(
            theme,
            {
                "theme": theme,
                "count": 0,
                "draft_count": 0,
                "approved_count": 0,
                "people": set(),
                "companies": set(),
                "evidence": [],
            },
        )
        bucket["count"] += 1
        if row.get("status") == "approved":
            bucket["approved_count"] += 1
        else:
            bucket["draft_count"] += 1
        if row.get("person_id"):
            bucket["people"].add(row["person_id"])
        for company in row.get("linked_companies", []):
            if company:
                bucket["companies"].add(company)
        for snippet in row.get("evidence_snippets", [])[:2]:
            if snippet not in bucket["evidence"]:
                bucket["evidence"].append(snippet)

    market_themes = sorted(
        [
            {
                "theme": theme,
                "count": bucket["count"],
                "draft_count": bucket["draft_count"],
                "approved_count": bucket["approved_count"],
                "people_count": len(bucket["people"]),
                "company_count": len(bucket["companies"]),
                "evidence_snippets": bucket["evidence"][:3],
            }
            for theme, bucket in theme_buckets.items()
        ],
        key=lambda item: (-item["draft_count"], -item["count"], item["theme"].lower()),
    )

    return {
        "interpreted_drafts": interpreted_drafts[:40],
        "enduring_memory": enduring_rows,
        "market_intel": market_rows,
        "market_themes": market_themes,
        "summary": {
            "interpreted_draft_count": len(interpreted_drafts),
            "enduring_pending_count": len([row for row in enduring_rows if row.get("status") != "approved"]),
            "market_pending_count": len([row for row in market_rows if row.get("status") != "approved"]),
            "theme_count": len(market_themes),
        },
    }


async def update_enduring_memory_status(memory_id: str, status: str) -> dict:
    now = _now()

    async def _write(db):
        await db.execute(
            "UPDATE ENDURING_MEMORY SET status = ?, updated_at = ? WHERE memory_id = ?",
            (status, now, memory_id),
        )
        async with db.execute("SELECT * FROM ENDURING_MEMORY WHERE memory_id = ?", (memory_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise ValueError("Enduring memory not found")
        return dict(row)

    return await run_write(_write, label="update enduring memory status")


async def update_market_intel_status(market_intel_id: str, status: str) -> dict:
    now = _now()

    async def _write(db):
        await db.execute(
            "UPDATE MARKET_INTEL SET status = ?, updated_at = ? WHERE market_intel_id = ?",
            (status, now, market_intel_id),
        )
        async with db.execute("SELECT * FROM MARKET_INTEL WHERE market_intel_id = ?", (market_intel_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise ValueError("Market intel not found")
        return dict(row)

    return await run_write(_write, label="update market intel status")


async def sync_relationship_situations_for_person(
    person_id: str,
    storyline_groups: list[dict],
    *,
    relationship_owner: str | None = None,
    company_name_raw: str | None = None,
) -> None:
    now = _now()
    now_dt = _parse_datetime(now) or datetime.now(timezone.utc)
    live_keys: set[str] = set()
    storyline_groups = _merge_storyline_groups_by_key(storyline_groups)

    async def _write(db):
        async with db.execute(
            "SELECT * FROM RELATIONSHIP_SITUATION WHERE person_id = ?",
            (person_id,),
        ) as cursor:
            existing_rows = [dict(row) for row in await cursor.fetchall()]
        existing_by_key = {str(row.get("situation_key") or ""): row for row in existing_rows}
        latest_manual_event_by_situation: dict[str, dict] = {}
        if existing_rows:
            situation_ids = [str(row.get("situation_id") or "").strip() for row in existing_rows if str(row.get("situation_id") or "").strip()]
            if situation_ids:
                placeholders = ",".join("?" for _ in situation_ids)
                async with db.execute(
                    f"""
                    SELECT situation_id, event_type, created_at, details_json
                    FROM RELATIONSHIP_SITUATION_EVENT
                    WHERE person_id = ?
                      AND situation_id IN ({placeholders})
                      AND event_type IN ('manual_update', 'manual_resolution')
                    ORDER BY datetime(created_at) DESC
                    """,
                    tuple([person_id] + situation_ids),
                ) as cursor:
                    for row in await cursor.fetchall():
                        event = dict(row)
                        situation_id = str(event.get("situation_id") or "").strip()
                        if situation_id and situation_id not in latest_manual_event_by_situation:
                            latest_manual_event_by_situation[situation_id] = event

        for group in storyline_groups:
            situation_key = _relationship_situation_key(group)
            live_keys.add(situation_key)
            existing = existing_by_key.get(situation_key)
            status = _relationship_situation_status(group)
            source_ids = [
                str(entry.get("interpretation_id") or "").strip()
                for entry in group.get("supporting_entries", [])
                if str(entry.get("interpretation_id") or "").strip()
            ]
            source_ids = list(dict.fromkeys(source_ids))
            channels_json = _json_array([str(channel) for channel in group.get("channels") or [] if str(channel).strip()])
            key_points_json = _json_array([str(point) for point in group.get("key_points") or [] if str(point).strip()])
            current_title = str(group.get("headline") or group.get("topic") or "Relationship situation").strip()
            situation_summary = str(group.get("timeline_summary") or "").strip()
            why_it_matters = str(group.get("why_it_matters") or "").strip()
            stage = str(group.get("stage") or "Relationship Update").strip()
            momentum = str(group.get("momentum") or "steady").strip()
            confidence_score = int(group.get("confidence_score") or 0)
            first_seen_at = str(group.get("start_at") or now)
            last_seen_at = str(group.get("end_at") or now)
            recommended_action = str(group.get("recommended_action") or "").strip()
            source_count = int(group.get("entry_count") or len(source_ids) or 0)

            if existing:
                manual_event = latest_manual_event_by_situation.get(str(existing.get("situation_id") or "").strip())
                if _preserve_recent_manual_close(existing, last_seen_at):
                    status = "closed"
                    current_title = str(existing.get("title") or current_title).strip()
                    situation_summary = str(existing.get("situation_summary") or situation_summary).strip()
                    why_it_matters = str(existing.get("why_it_matters") or why_it_matters).strip()
                    stage = str(existing.get("stage") or stage).strip()
                    momentum = str(existing.get("momentum") or momentum).strip()
                    recommended_action = str(existing.get("recommended_action") or recommended_action).strip()
                    confidence_score = max(confidence_score, int(existing.get("confidence_score") or 0))
                    last_seen_at = str(existing.get("last_seen_at") or last_seen_at or now)
                elif _preserve_recent_manual_override(manual_event, last_seen_at):
                    try:
                        manual_details = json.loads(manual_event.get("details_json") or "{}")
                    except json.JSONDecodeError:
                        manual_details = {}
                    manual_analysis = manual_details.get("analysis") if isinstance(manual_details, dict) else {}
                    if not isinstance(manual_analysis, dict):
                        manual_analysis = {}
                    status = str(
                        manual_analysis.get("status")
                        or existing.get("status")
                        or status
                    ).strip() or status
                    current_title = str(
                        manual_analysis.get("headline")
                        or existing.get("title")
                        or current_title
                    ).strip()
                    situation_summary = str(
                        manual_analysis.get("current_read")
                        or manual_analysis.get("summary")
                        or existing.get("situation_summary")
                        or situation_summary
                    ).strip()
                    why_it_matters = str(
                        manual_analysis.get("why_it_matters")
                        or existing.get("why_it_matters")
                        or why_it_matters
                    ).strip()
                    stage = str(
                        manual_analysis.get("stage")
                        or existing.get("stage")
                        or stage
                    ).strip()
                    momentum = str(
                        manual_analysis.get("momentum")
                        or existing.get("momentum")
                        or momentum
                    ).strip()
                    recommended_action = str(
                        manual_analysis.get("recommended_action")
                        or existing.get("recommended_action")
                        or recommended_action
                    ).strip()
                    confidence_score = max(
                        confidence_score,
                        int(manual_analysis.get("confidence_score") or existing.get("confidence_score") or 0),
                    )
                    last_seen_at = str(
                        existing.get("last_seen_at")
                        or manual_event.get("created_at")
                        or last_seen_at
                        or now
                    )
                previous_status = str(existing.get("status") or "")
                previous_stage = str(existing.get("stage") or "")
                previous_momentum = str(existing.get("momentum") or "")
                event_type = ""
                if previous_status == "closed" and status != "closed":
                    event_type = "reopened"
                elif previous_status != status:
                    event_type = "status_changed"
                elif previous_stage != stage:
                    event_type = "stage_changed"
                elif previous_momentum != momentum:
                    event_type = "momentum_changed"
                state_changed_at = now if event_type else str(existing.get("state_changed_at") or now)
                await db.execute(
                    """
                    UPDATE RELATIONSHIP_SITUATION
                    SET company_name_raw = ?, situation_type = ?, title = ?, why_it_matters = ?,
                        situation_summary = ?, stage = ?, status = ?, momentum = ?,
                        confidence_score = ?, first_seen_at = ?, last_seen_at = ?, last_interaction_at = ?,
                        state_changed_at = ?, channels_json = ?, key_points_json = ?, recommended_action = ?,
                        source_count = ?, owner = ?, updated_at = ?
                    WHERE situation_id = ?
                    """,
                    (
                        company_name_raw,
                        group.get("topic_type") or "relationship",
                        current_title,
                        why_it_matters,
                        situation_summary,
                        stage,
                        status,
                        momentum,
                        confidence_score,
                        str(existing.get("first_seen_at") or first_seen_at),
                        last_seen_at,
                        last_seen_at,
                        state_changed_at,
                        channels_json,
                        key_points_json,
                        recommended_action,
                        source_count,
                        relationship_owner,
                        now,
                        existing["situation_id"],
                    ),
                )
                situation_id = str(existing["situation_id"])
                if event_type:
                    await db.execute(
                        """
                        INSERT INTO RELATIONSHIP_SITUATION_EVENT (
                            event_id, situation_id, person_id, event_type,
                            previous_status, new_status, previous_stage, new_stage,
                            previous_momentum, new_momentum, summary, details_json,
                            source_interpretation_id, created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            str(uuid.uuid4())[:12],
                            situation_id,
                            person_id,
                            event_type,
                            previous_status or None,
                            status or None,
                            previous_stage or None,
                            stage or None,
                            previous_momentum or None,
                            momentum or None,
                            _relationship_situation_event_summary(
                                event_type=event_type,
                                title=current_title,
                                previous_status=previous_status,
                                new_status=status,
                                previous_stage=previous_stage,
                                new_stage=stage,
                                previous_momentum=previous_momentum,
                                new_momentum=momentum,
                            ),
                            None,
                            source_ids[-1] if source_ids else None,
                            now,
                        ),
                    )
            else:
                situation_id = str(uuid.uuid4())[:12]
                await db.execute(
                    """
                    INSERT INTO RELATIONSHIP_SITUATION (
                        situation_id, person_id, company_name_raw, situation_key, situation_type, title,
                        why_it_matters, situation_summary, stage, status, momentum, confidence_score,
                        first_seen_at, last_seen_at, last_interaction_at, state_changed_at,
                        channels_json, key_points_json, recommended_action, source_count,
                        owner, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        situation_id,
                        person_id,
                        company_name_raw,
                        situation_key,
                        group.get("topic_type") or "relationship",
                        current_title,
                        why_it_matters,
                        situation_summary,
                        stage,
                        status,
                        momentum,
                        confidence_score,
                        first_seen_at,
                        last_seen_at,
                        last_seen_at,
                        now,
                        channels_json,
                        key_points_json,
                        recommended_action,
                        source_count,
                        relationship_owner,
                        now,
                        now,
                    ),
                )
                await db.execute(
                    """
                    INSERT INTO RELATIONSHIP_SITUATION_EVENT (
                        event_id, situation_id, person_id, event_type,
                        previous_status, new_status, previous_stage, new_stage,
                        previous_momentum, new_momentum, summary, details_json,
                        source_interpretation_id, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4())[:12],
                        situation_id,
                        person_id,
                        "opened",
                        None,
                        status,
                        None,
                        stage,
                        None,
                        momentum,
                        _relationship_situation_event_summary(
                            event_type="opened",
                            title=current_title,
                            previous_status="",
                            new_status=status,
                            previous_stage="",
                            new_stage=stage,
                            previous_momentum="",
                            new_momentum=momentum,
                        ),
                        None,
                        source_ids[-1] if source_ids else None,
                        now,
                    ),
                )

            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                await db.execute(
                    f"""
                    DELETE FROM RELATIONSHIP_SITUATION_SOURCE
                    WHERE situation_id = ?
                      AND interpretation_id NOT IN ({placeholders})
                    """,
                    tuple([situation_id] + source_ids),
                )
            else:
                await db.execute(
                    "DELETE FROM RELATIONSHIP_SITUATION_SOURCE WHERE situation_id = ?",
                    (situation_id,),
                )

            for entry in group.get("supporting_entries", []):
                interpretation_id = str(entry.get("interpretation_id") or "").strip()
                if not interpretation_id:
                    continue
                await db.execute(
                    """
                    INSERT OR IGNORE INTO RELATIONSHIP_SITUATION_SOURCE (
                        situation_source_id, situation_id, interpretation_id, interaction_at, created_at
                    ) VALUES (?,?,?,?,?)
                    """,
                    (
                        str(uuid.uuid4())[:12],
                        situation_id,
                        interpretation_id,
                        entry.get("interaction_at"),
                        now,
                    ),
                )

        for existing in existing_rows:
            situation_key = str(existing.get("situation_key") or "")
            if situation_key in live_keys:
                continue
            previous_status = str(existing.get("status") or "")
            last_seen_dt = _parse_datetime(existing.get("last_seen_at"))
            if last_seen_dt and (now_dt - last_seen_dt).days >= 60:
                new_status = "closed"
                event_type = "closed"
            else:
                new_status = "watching"
                event_type = "status_changed" if previous_status != "watching" else ""
            if not event_type and previous_status == new_status:
                continue
            await db.execute(
                """
                UPDATE RELATIONSHIP_SITUATION
                SET status = ?, state_changed_at = ?, updated_at = ?
                WHERE situation_id = ?
                """,
                (new_status, now, now, existing["situation_id"]),
            )
            await db.execute(
                """
                INSERT INTO RELATIONSHIP_SITUATION_EVENT (
                    event_id, situation_id, person_id, event_type,
                    previous_status, new_status, previous_stage, new_stage,
                    previous_momentum, new_momentum, summary, details_json,
                    source_interpretation_id, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4())[:12],
                    existing["situation_id"],
                    person_id,
                    event_type or "status_changed",
                    previous_status or None,
                    new_status,
                    existing.get("stage"),
                    existing.get("stage"),
                    existing.get("momentum"),
                    existing.get("momentum"),
                    _relationship_situation_event_summary(
                        event_type=event_type or "status_changed",
                        title=str(existing.get("title") or "Relationship situation"),
                        previous_status=previous_status,
                        new_status=new_status,
                        previous_stage=str(existing.get("stage") or ""),
                        new_stage=str(existing.get("stage") or ""),
                        previous_momentum=str(existing.get("momentum") or ""),
                        new_momentum=str(existing.get("momentum") or ""),
                    ),
                    None,
                    None,
                    now,
                ),
            )

    await run_write(_write, label="sync relationship situations")


async def load_relationship_situations_for_person(person_id: str, *, include_closed: bool = False, limit: int = 8) -> list[dict]:
    async def _read(db):
        if include_closed:
            where_clause = "WHERE person_id = ?"
            params: tuple = (person_id, limit)
        else:
            where_clause = "WHERE person_id = ? AND status != 'closed'"
            params = (person_id, limit)
        async with db.execute(
            f"""
            SELECT *
            FROM RELATIONSHIP_SITUATION
            {where_clause}
            ORDER BY
                CASE status
                    WHEN 'open' THEN 0
                    WHEN 'stalled' THEN 1
                    WHEN 'watching' THEN 2
                    ELSE 3
                END,
                datetime(last_interaction_at) DESC,
                datetime(updated_at) DESC
            LIMIT ?
            """,
            params,
        ) as cursor:
            situations = [dict(row) for row in await cursor.fetchall()]
        situation_ids = [str(row.get("situation_id") or "") for row in situations if row.get("situation_id")]
        if not situation_ids:
            return situations, [], []
        placeholders = ",".join("?" for _ in situation_ids)
        async with db.execute(
            f"""
            SELECT
                rss.situation_id,
                ii.interpretation_id,
                ii.thread_id,
                ii.what_is_happening,
                ii.why_it_matters,
                ii.stage,
                ii.momentum,
                ii.confidence_score,
                ii.evidence_snippets_json,
                i.interaction_at,
                i.channel,
                i.summary AS source_summary,
                i.raw_text AS source_raw_text
            FROM RELATIONSHIP_SITUATION_SOURCE rss
            JOIN INTERPRETED_INTERACTION ii ON ii.interpretation_id = rss.interpretation_id
            LEFT JOIN INTERACTION i ON i.interaction_id = ii.source_interaction_id
            WHERE rss.situation_id IN ({placeholders})
            ORDER BY datetime(i.interaction_at) ASC, ii.interpretation_id ASC
            """,
            tuple(situation_ids),
        ) as cursor:
            sources = [dict(row) for row in await cursor.fetchall()]
        async with db.execute(
            f"""
            SELECT event_id, situation_id, event_type, previous_status, new_status, previous_stage, new_stage,
                   previous_momentum, new_momentum, summary, details_json, created_at
            FROM RELATIONSHIP_SITUATION_EVENT
            WHERE situation_id IN ({placeholders})
            ORDER BY datetime(created_at) DESC
            """,
            tuple(situation_ids),
        ) as cursor:
            events = [dict(row) for row in await cursor.fetchall()]
        return situations, sources, events

    situation_rows, source_rows, event_rows = await run_read(_read, label="load relationship situations")
    sources_by_situation: dict[str, list[dict]] = {}
    for row in source_rows:
        situation_id = str(row.get("situation_id") or "")
        parsed = dict(row)
        try:
            parsed["evidence_snippets"] = json.loads(parsed.get("evidence_snippets_json") or "[]")
        except json.JSONDecodeError:
            parsed["evidence_snippets"] = []
        parsed["full_evidence_text"] = _build_full_evidence_text(parsed.get("source_summary"), parsed.get("source_raw_text"))
        parsed["display_channel"] = _display_channel_label(
            parsed.get("channel"),
            parsed.get("source_summary"),
            parsed.get("source_raw_text"),
        )
        sources_by_situation.setdefault(situation_id, []).append(
            {
                "interpretation_id": parsed.get("interpretation_id"),
                "interaction_at": parsed.get("interaction_at"),
                "channel": parsed.get("display_channel") or parsed.get("channel") or "unknown",
                "thread_id": parsed.get("thread_id"),
                "stage": parsed.get("stage") or "Relationship Update",
                "momentum": parsed.get("momentum") or "steady",
                "confidence_score": int(parsed.get("confidence_score") or 0),
                "what_is_happening": parsed.get("what_is_happening") or "",
                "why_it_matters": parsed.get("why_it_matters") or "",
                "evidence_snippets": (parsed.get("evidence_snippets") or [])[:2],
                "full_evidence_text": parsed.get("full_evidence_text") or "",
            }
        )
    events_by_situation: dict[str, list[dict]] = {}
    for row in event_rows:
        events_by_situation.setdefault(str(row.get("situation_id") or ""), []).append(
            {
                "event_id": row.get("event_id"),
                "event_type": row.get("event_type"),
                "summary": row.get("summary"),
                "details_json": row.get("details_json"),
                "created_at": row.get("created_at"),
                "previous_status": row.get("previous_status"),
                "new_status": row.get("new_status"),
            }
        )

    shaped = []
    for row in situation_rows:
        situation_id = str(row.get("situation_id") or "")
        situation_key = str(row.get("situation_key") or "")
        try:
            channels = json.loads(row.get("channels_json") or "[]")
        except json.JSONDecodeError:
            channels = []
        display_channels = _dedupe_text_list(
            [
                str(entry.get("channel") or "").strip()
                for entry in sources_by_situation.get(situation_id, [])
                if str(entry.get("channel") or "").strip()
            ]
            + [_display_channel_label(channel) for channel in channels],
            limit=6,
        )
        source_count = int(row.get("source_count") or 0)
        latest_supporting_entry = (sources_by_situation.get(situation_id) or [])[-1] if sources_by_situation.get(situation_id) else {}
        timeline_summary = _storyline_timeline_summary(
            {
                "channels": display_channels or channels,
                "entry_count": source_count or len(sources_by_situation.get(situation_id) or []),
            },
            {
                "stage": latest_supporting_entry.get("stage") or row.get("stage"),
                "momentum": latest_supporting_entry.get("momentum") or row.get("momentum"),
            },
        )
        try:
            key_points = json.loads(row.get("key_points_json") or "[]")
        except json.JSONDecodeError:
            key_points = []
        shaped.append(
            {
                "situation_record_id": situation_id,
                "situation_id": _relationship_situation_display_id(row.get("situation_type"), situation_key),
                "topic": row.get("title") or "Relationship situation",
                "topic_type": row.get("situation_type") or "relationship",
                "topic_type_label": _story_topic_type_label(str(row.get("situation_type") or "relationship")),
                "headline": row.get("title") or "Relationship situation",
                "why_it_matters": row.get("why_it_matters") or "",
                "stage": row.get("stage") or "Relationship Update",
                "momentum": row.get("momentum") or "steady",
                "confidence_score": int(row.get("confidence_score") or 0),
                "start_at": row.get("first_seen_at"),
                "end_at": row.get("last_seen_at"),
                "window_label": _story_window_label(str(row.get("first_seen_at") or ""), str(row.get("last_interaction_at") or row.get("last_seen_at") or "")),
                "channels": display_channels or channels,
                "entry_count": source_count,
                "recommended_action": row.get("recommended_action") or "",
                "key_points": key_points,
                "timeline_summary": timeline_summary,
                "resolution_note": row.get("resolution_note") or "",
                "supporting_entries": sources_by_situation.get(situation_id, []),
                "tracking_status": row.get("status") or "watching",
                "tracking_status_label": _relationship_situation_status_label(str(row.get("status") or "")),
                "state_changed_at": row.get("state_changed_at"),
                "recent_events": events_by_situation.get(situation_id, [])[:3],
            }
        )
    return shaped


async def apply_manual_relationship_topic_resolution(
    *,
    person_id: str,
    situation_record_id: str,
    update_text: str,
    analysis: dict,
    source: str = "profile_assistant",
) -> dict:
    now = _now()

    async def _write(db):
        async with db.execute(
            "SELECT * FROM RELATIONSHIP_SITUATION WHERE situation_id = ? AND person_id = ?",
            (situation_record_id, person_id),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise ValueError("Relationship topic not found")

        existing = dict(row)
        previous_status = str(existing.get("status") or "")
        previous_stage = str(existing.get("stage") or "")
        previous_momentum = str(existing.get("momentum") or "")

        title = str(analysis.get("headline") or existing.get("title") or "Relationship situation").strip()
        current_read = str(analysis.get("current_read") or title).strip()
        why_it_matters = str(analysis.get("why_it_matters") or existing.get("why_it_matters") or "").strip()
        stage = str(analysis.get("stage") or existing.get("stage") or "Relationship Update").strip()
        status = str(analysis.get("status") or existing.get("status") or "watching").strip().lower()
        if status not in {"open", "watching", "stalled", "closed"}:
            status = str(existing.get("status") or "watching").strip().lower() or "watching"
        momentum = str(analysis.get("momentum") or existing.get("momentum") or "steady").strip()
        recommended_action = str(analysis.get("recommended_action") or "").strip()
        resolution_note = str(analysis.get("resolution_note") or "").strip()
        confidence_score = int(analysis.get("confidence_score") or existing.get("confidence_score") or 0)
        key_points = _json_array([str(value) for value in (analysis.get("key_points") or []) if str(value or "").strip()])
        try:
            channels = json.loads(existing.get("channels_json") or "[]") if existing.get("channels_json") else []
        except json.JSONDecodeError:
            channels = []
        channels_json = _json_array([*channels, "chat"])
        resolution_summary = str(analysis.get("summary") or current_read).strip()
        resolution_type = str(analysis.get("resolution_type") or "none").strip().lower()

        event_type = "manual_resolution" if status != previous_status or resolution_type != "none" else "manual_update"
        state_changed_at = now if event_type == "manual_resolution" or previous_stage != stage or previous_momentum != momentum else str(existing.get("state_changed_at") or now)

        await db.execute(
            """
            UPDATE RELATIONSHIP_SITUATION
            SET title = ?, why_it_matters = ?, situation_summary = ?, stage = ?, status = ?, momentum = ?,
                confidence_score = ?, last_seen_at = ?, last_interaction_at = ?, state_changed_at = ?,
                channels_json = ?, key_points_json = ?, recommended_action = ?, resolution_note = ?, updated_at = ?
            WHERE situation_id = ? AND person_id = ?
            """,
            (
                title,
                why_it_matters,
                current_read,
                stage,
                status,
                momentum,
                confidence_score,
                now,
                now,
                state_changed_at,
                channels_json,
                key_points,
                recommended_action,
                resolution_note,
                now,
                situation_record_id,
                person_id,
            ),
        )
        await db.execute(
            """
            INSERT INTO RELATIONSHIP_SITUATION_EVENT (
                event_id, situation_id, person_id, event_type,
                previous_status, new_status, previous_stage, new_stage,
                previous_momentum, new_momentum, summary, details_json,
                source_interpretation_id, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4())[:12],
                situation_record_id,
                person_id,
                event_type,
                previous_status or None,
                status or None,
                previous_stage or None,
                stage or None,
                previous_momentum or None,
                momentum or None,
                _relationship_situation_event_summary(
                    event_type=event_type,
                    title=title,
                    previous_status=previous_status,
                    new_status=status,
                    previous_stage=previous_stage,
                    new_stage=stage,
                    previous_momentum=previous_momentum,
                    new_momentum=momentum,
                ),
                json.dumps(
                    {
                        "source": source,
                        "update_text": update_text,
                        "analysis": analysis,
                    },
                    ensure_ascii=False,
                ),
                None,
                now,
            ),
        )
        await db.execute(
            "UPDATE PERSON SET cached_briefing = NULL, last_updated_at = ? WHERE person_id = ?",
            (now, person_id),
        )

        return {
            "situation_record_id": situation_record_id,
            "situation_key": existing.get("situation_key"),
            "situation_id": _relationship_situation_display_id(existing.get("situation_type"), existing.get("situation_key")),
            "title": title,
            "current_read": current_read,
            "why_it_matters": why_it_matters,
            "stage": stage,
            "status": status,
            "status_label": _relationship_situation_status_label(status),
            "momentum": momentum,
            "recommended_action": recommended_action,
            "resolution_note": resolution_note,
            "resolution_type": resolution_type,
            "confidence_score": confidence_score,
            "key_points": json.loads(key_points or "[]"),
            "state_changed_at": state_changed_at,
        }

    return await run_write(_write, label=f"manual relationship topic resolution {person_id}")


def _manual_event_type_from_analysis(analysis: dict) -> str:
    status = str(analysis.get("status") or "").strip().lower()
    resolution_type = str(analysis.get("resolution_type") or "none").strip().lower()
    if status in {"closed"} or resolution_type not in {"", "none"}:
        return "manual_resolution"
    return "manual_update"


async def _replay_manual_relationship_events(person_id: str, situation_record_id: str) -> None:
    async def _load_person(db):
        async with db.execute(
            "SELECT relationship_owner, company_name_raw FROM PERSON WHERE person_id = ?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    person_row = await run_read(_load_person, label=f"load person for situation rebuild {person_id}")
    if not person_row:
        raise ValueError("Person not found")

    interpreted_interactions = await load_interpreted_interactions(person_id, limit=24)
    storyline = build_storyline_state(interpreted_interactions)
    await sync_relationship_situations_for_person(
        person_id,
        storyline.get("storyline_groups", []),
        relationship_owner=person_row.get("relationship_owner"),
        company_name_raw=person_row.get("company_name_raw"),
    )

    async def _replay(db):
        async with db.execute(
            """
            SELECT event_id, event_type, details_json, created_at
            FROM RELATIONSHIP_SITUATION_EVENT
            WHERE situation_id = ? AND person_id = ? AND event_type IN ('manual_update', 'manual_resolution')
            ORDER BY datetime(created_at) ASC, event_id ASC
            """,
            (situation_record_id, person_id),
        ) as cursor:
            manual_events = [dict(row) for row in await cursor.fetchall()]

        for manual_event in manual_events:
            async with db.execute(
                "SELECT * FROM RELATIONSHIP_SITUATION WHERE situation_id = ? AND person_id = ?",
                (situation_record_id, person_id),
            ) as cursor:
                current_row = await cursor.fetchone()
            if not current_row:
                break

            try:
                details = json.loads(manual_event.get("details_json") or "{}")
            except json.JSONDecodeError:
                continue
            if not isinstance(details, dict):
                continue
            analysis = details.get("analysis") if isinstance(details.get("analysis"), dict) else {}
            existing = dict(current_row)

            title = str(analysis.get("headline") or existing.get("title") or "Relationship situation").strip()
            current_read = str(analysis.get("current_read") or title).strip()
            why_it_matters = str(analysis.get("why_it_matters") or existing.get("why_it_matters") or "").strip()
            stage = str(analysis.get("stage") or existing.get("stage") or "Relationship Update").strip()
            status = str(analysis.get("status") or existing.get("status") or "watching").strip().lower()
            if status not in {"open", "watching", "stalled", "closed"}:
                status = str(existing.get("status") or "watching").strip().lower() or "watching"
            momentum = str(analysis.get("momentum") or existing.get("momentum") or "steady").strip()
            recommended_action = str(analysis.get("recommended_action") or "").strip()
            resolution_note = str(analysis.get("resolution_note") or "").strip()
            confidence_score = int(analysis.get("confidence_score") or existing.get("confidence_score") or 0)
            key_points_json = _json_array([str(value) for value in (analysis.get("key_points") or []) if str(value or "").strip()])
            try:
                channels = json.loads(existing.get("channels_json") or "[]") if existing.get("channels_json") else []
            except json.JSONDecodeError:
                channels = []
            channels_json = _json_array([*channels, "chat"])
            effective_at = str(manual_event.get("created_at") or existing.get("updated_at") or _now())

            await db.execute(
                """
                UPDATE RELATIONSHIP_SITUATION
                SET title = ?, why_it_matters = ?, situation_summary = ?, stage = ?, status = ?, momentum = ?,
                    confidence_score = ?, last_seen_at = ?, last_interaction_at = ?, state_changed_at = ?,
                    channels_json = ?, key_points_json = ?, recommended_action = ?, resolution_note = ?, updated_at = ?
                WHERE situation_id = ? AND person_id = ?
                """,
                (
                    title,
                    why_it_matters,
                    current_read,
                    stage,
                    status,
                    momentum,
                    confidence_score,
                    effective_at,
                    effective_at,
                    effective_at,
                    channels_json,
                    key_points_json,
                    recommended_action,
                    resolution_note,
                    _now(),
                    situation_record_id,
                    person_id,
                ),
            )

        await db.execute(
            "UPDATE PERSON SET cached_briefing = NULL, last_updated_at = ? WHERE person_id = ?",
            (_now(), person_id),
        )

    await run_write(_replay, label=f"replay manual relationship events {person_id}:{situation_record_id}")


async def update_manual_relationship_event(
    *,
    event_id: str,
    update_text: str,
    analysis: dict,
) -> dict:
    async def _update(db):
        async with db.execute(
            """
            SELECT event_id, situation_id, person_id, details_json
            FROM RELATIONSHIP_SITUATION_EVENT
            WHERE event_id = ? AND event_type IN ('manual_update', 'manual_resolution')
            """,
            (event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise ValueError("Manual relationship event not found")

        event = dict(row)
        details_payload = {
            "source": "manual_editor",
            "update_text": update_text,
            "analysis": analysis,
        }
        title = str(analysis.get("headline") or analysis.get("current_read") or "Relationship situation").strip()
        event_type = _manual_event_type_from_analysis(analysis)
        await db.execute(
            """
            UPDATE RELATIONSHIP_SITUATION_EVENT
            SET event_type = ?, summary = ?, details_json = ?
            WHERE event_id = ?
            """,
            (
                event_type,
                _relationship_situation_event_summary(
                    event_type=event_type,
                    title=title,
                    previous_status="",
                    new_status=str(analysis.get("status") or ""),
                    previous_stage="",
                    new_stage=str(analysis.get("stage") or ""),
                    previous_momentum="",
                    new_momentum=str(analysis.get("momentum") or ""),
                ),
                json.dumps(details_payload, ensure_ascii=False),
                event_id,
            ),
        )
        return {
            "person_id": str(event.get("person_id") or ""),
            "situation_record_id": str(event.get("situation_id") or ""),
        }

    result = await run_write(_update, label=f"update manual relationship event {event_id}")
    await _replay_manual_relationship_events(result["person_id"], result["situation_record_id"])
    return result


async def delete_manual_relationship_event(*, event_id: str) -> dict:
    async def _delete(db):
        async with db.execute(
            """
            SELECT event_id, situation_id, person_id
            FROM RELATIONSHIP_SITUATION_EVENT
            WHERE event_id = ? AND event_type IN ('manual_update', 'manual_resolution')
            """,
            (event_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise ValueError("Manual relationship event not found")
        event = dict(row)
        await db.execute("DELETE FROM RELATIONSHIP_SITUATION_EVENT WHERE event_id = ?", (event_id,))
        return {
            "person_id": str(event.get("person_id") or ""),
            "situation_record_id": str(event.get("situation_id") or ""),
        }

    result = await run_write(_delete, label=f"delete manual relationship event {event_id}")
    await _replay_manual_relationship_events(result["person_id"], result["situation_record_id"])
    return result


def build_storyline_state(items: list[dict]) -> dict:
    if not items:
        return {
            "storyline_summary": "No storyline is available yet.",
            "current_state_summary": "No current state has been derived yet.",
            "storyline_groups": [],
        }

    sorted_items = sorted(
        items,
        key=lambda item: (
            _parse_datetime(item.get("interaction_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(item.get("interpretation_id") or ""),
        ),
    )
    prepared = []
    for item in sorted_items:
        enriched = dict(item)
        enriched["_story_topic"] = _story_topic_label(item)
        enriched["_story_topic_type"] = _story_topic_type(item)
        enriched["display_channel"] = str(item.get("display_channel") or item.get("channel") or "unknown").strip()
        prepared.append(enriched)

    grouped: list[dict] = []
    for item in prepared:
        if not grouped or not _same_storyline_group(grouped[-1]["latest_item"], item):
            grouped.append(
                {
                    "topic": item["_story_topic"],
                    "topic_type": item["_story_topic_type"],
                    "start_at": item.get("interaction_at"),
                    "end_at": item.get("interaction_at"),
                    "channels": [item.get("display_channel") or "unknown"],
                    "entries": [item],
                    "latest_item": item,
                }
            )
            continue
        bucket = grouped[-1]
        bucket["entries"].append(item)
        bucket["end_at"] = item.get("interaction_at")
        bucket["latest_item"] = item
        if item.get("_story_topic_type") and item.get("_story_topic_type") != bucket.get("topic_type"):
            bucket["topic_type"] = "relationship"
        if item.get("display_channel") and item.get("display_channel") not in bucket["channels"]:
            bucket["channels"].append(item["display_channel"])

    storyline_groups = []
    for index, bucket in enumerate(grouped, start=1):
        latest = bucket["latest_item"]
        topic_type = bucket.get("topic_type") or _story_topic_type(latest)
        entry_count = len(bucket["entries"])
        key_points = _storyline_key_points(bucket["entries"])
        window_label = _story_window_label(bucket["start_at"], bucket["end_at"])
        situation_id = f"S-{topic_type[:3].upper()}-{index:02d}-{_story_topic_slug(bucket['topic'])}"
        timeline_summary = _storyline_timeline_summary(
            {
                "channels": bucket["channels"],
                "entry_count": entry_count,
            },
            latest,
        )
        supporting_entries = [
            {
                "interpretation_id": entry.get("interpretation_id"),
                "interaction_at": entry.get("interaction_at"),
                "channel": entry.get("display_channel") or entry.get("channel") or "unknown",
                "thread_id": entry.get("thread_id"),
                "stage": entry.get("stage") or "Relationship Update",
                "momentum": entry.get("momentum") or "steady",
                "confidence_score": int(entry.get("confidence_score") or 0),
                "what_is_happening": entry.get("what_is_happening") or "",
                "why_it_matters": entry.get("why_it_matters") or "",
                "evidence_snippets": (entry.get("evidence_snippets") or [])[:2],
                "full_evidence_text": entry.get("full_evidence_text") or "",
            }
            for entry in bucket["entries"]
        ]
        storyline_groups.append(
            {
                "situation_id": situation_id,
                "topic": bucket["topic"],
                "topic_type": topic_type,
                "topic_type_label": _story_topic_type_label(topic_type),
                "headline": latest.get("what_is_happening") or bucket["topic"],
                "why_it_matters": latest.get("why_it_matters") or "",
                "stage": latest.get("stage") or "Relationship Update",
                "momentum": latest.get("momentum") or "steady",
                "confidence_score": int(latest.get("confidence_score") or 0),
                "start_at": bucket["start_at"],
                "end_at": bucket["end_at"],
                "window_label": window_label,
                "channels": bucket["channels"],
                "entry_count": entry_count,
                "recommended_action": latest.get("recommended_action") or "",
                "key_points": key_points,
                "timeline_summary": timeline_summary,
                "supporting_entries": supporting_entries,
            }
        )

    first_at = storyline_groups[0]["start_at"] or ""
    last_at = storyline_groups[-1]["end_at"] or ""
    channel_count = len(set(channel for group in storyline_groups for channel in group["channels"]))
    latest_group = storyline_groups[-1]

    return {
        "storyline_summary": (
            f"Across {len(items)} interpreted interactions from {first_at[:10]} to {last_at[:10]}, "
            f"the relationship story spans {len(storyline_groups)} live situation"
            f"{'' if len(storyline_groups) == 1 else 's'} across {channel_count} channel"
            f"{'' if channel_count == 1 else 's'}."
        ),
        "current_state_summary": (
            f"Current state: {latest_group['headline']} "
            f"This is an {latest_group['topic_type_label'].lower()} situation with {latest_group['momentum']} momentum. "
            f"Latest channels: {', '.join(latest_group['channels'])}. "
            f"Next move: {latest_group['recommended_action'] or 'Review the latest situation and decide the next action.'}"
        ),
        "storyline_groups": storyline_groups[-6:],
    }


def build_interpreted_memory_summary(items: list[dict]) -> dict:
    if not items:
        return {
            "what_is_happening_summary": "No interpreted interaction summary is available yet.",
            "why_it_matters_summary": "No interpreted interaction summary is available yet.",
            "market_intel_summary": "No market intelligence has been extracted yet.",
            "rapport_summary": "No rapport intelligence has been extracted yet.",
        }

    latest = max(
        items,
        key=lambda item: (
            int(item.get("confidence_score") or 0),
            len(item.get("opportunity_signals", [])),
            len(item.get("market_intel_signals", [])),
            len(item.get("friction_signals", [])),
            item.get("updated_at") or "",
        ),
    )
    market_points: list[str] = []
    rapport_points: list[str] = []
    for item in items:
        for point in item.get("market_intel_signals", []):
            if point not in market_points:
                market_points.append(point)
        for point in item.get("relationship_signals", []):
            if point not in rapport_points:
                rapport_points.append(point)

    return {
        "what_is_happening_summary": latest.get("what_is_happening") or "No interpreted interaction summary is available yet.",
        "why_it_matters_summary": latest.get("why_it_matters") or "No interpreted interaction summary is available yet.",
        "market_intel_summary": (
            f"Market intelligence: {'; '.join(market_points[:3])}"
            if market_points else
            "No market intelligence has been extracted yet."
        ),
        "rapport_summary": (
            f"Rapport memory: {'; '.join(rapport_points[:3])}"
            if rapport_points else
            "No rapport intelligence has been extracted yet."
        ),
    }


def _brief_date_label(value: str | None) -> str:
    parsed = _parse_datetime(value)
    if not parsed:
        return "No dated interaction"
    return parsed.strftime("%d %b %Y")


def _dedupe_text_list(values: list[str], limit: int | None = None) -> list[str]:
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in deduped:
            deduped.append(text)
        if limit and len(deduped) >= limit:
            break
    return deduped


def _is_noise_preview(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return True
    if lowered.startswith("join:") or lowered.startswith("join now") or lowered.startswith("https://teams.microsoft.com/"):
        return True
    if "accepted this invitation" in lowered:
        return True
    if lowered.startswith("meeting id:") or lowered.startswith("passcode:"):
        return True
    if lowered.replace("_", "") == "":
        return True
    noise_patterns = (
        "imported record",
        "accepted:",
        "message recall report",
        "your message recall request",
        "microsoft teams meeting",
        "join the meeting",
        "you tried to recall the message",
        "need help?",
        "tea/coffee",
    )
    return any(pattern in lowered for pattern in noise_patterns)


def _is_greeting_line(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    if re.fullmatch(r"[A-Z][a-z]+,", cleaned):
        return True
    lowered = cleaned.lower()
    if lowered in {"hi", "hi,", "hello", "hello,", "mark,", "matt,", "marcus,", "team,"}:
        return True
    return re.fullmatch(r"(hi|hello|dear)\s+[a-z]+,?", lowered) is not None


def _preview_signal_score(text: str | None) -> int:
    cleaned = _clean_source_text(text)
    if not cleaned:
        return -100
    lowered = cleaned.lower()
    score = min(12, len(re.findall(r"[a-z0-9]+", lowered)))
    if _is_noise_preview(cleaned):
        score -= 20
    if _is_greeting_line(cleaned) or _is_courtesy_only_rapport_text(cleaned):
        score -= 8
    if len(cleaned) < 28:
        score -= 3
    signal_phrases = (
        "introduction",
        "great to meet",
        "meet up",
        "quick call",
        "get acquainted",
        "message me to arrange",
        "let me know your number",
        "whatsapp",
        "support you",
        "profile attached",
        "secure the gent",
        "proposal",
        "role",
        "search",
        "assignment",
        "meeting",
        "teams",
        "call",
    )
    score += sum(3 for phrase in signal_phrases if phrase in lowered)
    if re.search(r"\b\d{7,}\b", cleaned):
        score += 4
    return score


def _best_preview_line(lines: list[str]) -> str:
    best_line = ""
    best_score = -100
    for line in lines:
        cleaned = str(line or "").strip()
        if not cleaned or _is_noise_preview(cleaned):
            continue
        score = _preview_signal_score(cleaned)
        if score > best_score:
            best_line = cleaned
            best_score = score
    return best_line


def _best_evidence_preview(
    *,
    summary: str | None = None,
    raw_text: str | None = None,
    evidence_snippets: list[str] | None = None,
    max_len: int = 170,
) -> str:
    best_snippet = ""
    best_snippet_score = -100
    for snippet in evidence_snippets or []:
        cleaned = _clip(_clean_source_text(snippet), max_len)
        if cleaned and not _is_noise_preview(cleaned):
            score = _preview_signal_score(cleaned)
            if score > best_snippet_score:
                best_snippet = cleaned
                best_snippet_score = score

    cleaned_source = _clean_source_text(summary or raw_text)
    source_candidate = ""
    source_score = -100
    if cleaned_source:
        useful_lines = [
            line.strip()
            for line in cleaned_source.split("\n")
            if line.strip() and not _is_noise_preview(line)
        ]
        if useful_lines:
            if _looks_like_teams_meeting_invite(summary, raw_text):
                source_candidate = _clip(f"Teams meeting invite: {useful_lines[0]}", max_len)
                source_score = _preview_signal_score(source_candidate)
            elif _looks_like_meeting_response(summary, raw_text):
                source_candidate = _clip(f"Meeting response: {useful_lines[0]}", max_len)
                source_score = _preview_signal_score(source_candidate)
            else:
                subject_line = useful_lines[0]
                best_follow_up = _best_preview_line(useful_lines[1:])
                if best_follow_up and best_follow_up != subject_line:
                    source_candidate = _clip(f"{subject_line}: {best_follow_up}", max_len)
                else:
                    source_candidate = _clip(subject_line, max_len)
                source_score = _preview_signal_score(source_candidate)

    if source_candidate and source_score >= best_snippet_score:
        return source_candidate
    if best_snippet:
        return best_snippet
    return source_candidate


def _dedupe_brief_topics(values: list[str], limit: int = 5) -> list[str]:
    deduped: list[str] = []
    normalized_seen: list[str] = []
    for value in values:
        text = str(value or "").strip().strip(".")
        if not text:
            continue
        normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        if not normalized:
            continue
        if any(normalized == existing or normalized in existing or existing in normalized for existing in normalized_seen):
            continue
        normalized_seen.append(normalized)
        deduped.append(text)
        if len(deduped) >= limit:
            break
    return deduped


def _strip_topic_admin_prefixes(text: str | None) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    patterns = (
        r"^(re|fw|fwd):\s*",
        r"^(summary|source):\s*",
        r"^(accepted|declined|tentative|canceled|cancelled):\s*",
        r"^(teams meeting invite|teams meeting response|meeting response|calendar meeting|message recall report|your message recall request|topic resolution):\s*",
        r"^(taylor sterling|tsa|antigravity|antigravity crm)\s*[-:]\s*",
    )
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip(" -:")


def _is_topic_admin_noise_text(text: str | None) -> bool:
    cleaned = _strip_topic_admin_prefixes(_clean_source_text(text))
    lowered = " ".join(cleaned.lower().split())
    if not lowered:
        return True
    if lowered in {"step", "accepted", "declined", "tentative"}:
        return True
    blocker_phrases = (
        "message recall report",
        "your message recall request",
        "you tried to recall the message",
        "join the meeting now",
        "meeting id:",
        "meeting options",
        "passcode:",
        "microsoft teams meeting",
        "accepted this invitation",
        "teams meeting invite",
        "meeting response",
        "calendar meeting",
        "contact details are not included",
        "wanted to reach out and stay in touch",
        "stay in touch with",
        "out of office",
        "automatic reply",
    )
    return any(phrase in lowered for phrase in blocker_phrases)


def _brief_topic_label(text: str | None) -> str:
    original = str(text or "").strip().strip(".")
    if not original:
        return "Active relationship thread"
    candidate_lines: list[str] = []
    for raw_line in _clean_source_text(original).split("\n"):
        candidate = _strip_topic_admin_prefixes(raw_line)
        if not candidate or _is_topic_admin_noise_text(candidate):
            continue
        candidate_lines.append(candidate)
    candidate = _best_preview_line(candidate_lines) or next(
        (line for line in candidate_lines if not _is_noise_preview(line)),
        "",
    )
    if not candidate:
        candidate = _strip_topic_admin_prefixes(original) or original
    if _is_topic_admin_noise_text(candidate):
        return "Active relationship thread"
    candidate = re.sub(r"\s+-\s+confidential\b", "", candidate, flags=re.IGNORECASE).strip(" -:")
    lowered = candidate.lower()
    if "damian arnillas" in lowered and "structural engineer" in lowered:
        return "Damian Arnillas / structural engineer thread"
    if "commercial gap" in lowered:
        return "Commercial gap and broader SSH needs"
    if "mark earley" in lowered and ("signed contract" in lowered or "contract" in lowered or "assignment" in lowered):
        return "Mark Earley contract / assignment progression"
    if "offer acceptance" in lowered:
        return "Offer acceptance and execution friction"
    if "marivic mendoza" in lowered and ("senior design" in lowered or "project manager" in lowered):
        return "Marivic Mendoza / senior design PM thread"
    if "package pressure" in lowered or "commercial position" in lowered or "commercial terms" in lowered:
        return "Commercial terms and package pressure"
    if "interview" in lowered and "next week" in lowered:
        return "Interview coordination and timing"
    return _clip(candidate, 96)


def _is_generic_prep_text(text: str | None) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return True
    if _is_topic_admin_noise_text(lowered):
        return True
    generic_values = {
        "active relationship thread",
        "the contact is expressing forward intent directly.",
        "the contact is signaling a concrete requirement or priority.",
        "the interaction changes the working picture enough to retain as interpreted memory.",
        "no explanation",
        "relationship situation",
    }
    if lowered in generic_values:
        return True
    return "working picture enough to retain" in lowered


def _topic_primary_preview(topic: dict) -> str:
    for detail in topic.get("evidence_details") or []:
        preview = str((detail or {}).get("preview") or "").strip()
        if preview:
            return preview
    for value in topic.get("evidence") or []:
        preview = str(value or "").strip()
        if preview:
            return preview
    return str(topic.get("title") or "").strip()


def _topic_prompt_text_blob(topic: dict) -> str:
    return _topic_text_blob(
        [
            topic.get("title"),
            topic.get("current_read"),
            topic.get("why_it_matters"),
            topic.get("recommended_action"),
            _topic_primary_preview(topic),
            " ".join(topic.get("channels") or []),
            " ".join(topic.get("key_points") or []),
        ]
    )


def _topic_evidence_text_blob(topic: dict) -> str:
    return _topic_text_blob(
        [
            topic.get("title"),
            _topic_primary_preview(topic),
            " ".join(topic.get("channels") or []),
        ]
    )


def _topic_age_days(topic: dict) -> int | None:
    last_touch = _parse_datetime(topic.get("last_touch_at") or topic.get("end_at") or topic.get("state_changed_at"))
    if not last_touch:
        return None
    return max(0, (datetime.now(timezone.utc) - last_touch).days)


def _is_invite_only_meeting_topic(topic: dict) -> bool:
    details = [detail for detail in (topic.get("evidence_details") or []) if isinstance(detail, dict)]
    if not details:
        return False
    previews = [str(detail.get("preview") or "").strip().lower() for detail in details if str(detail.get("preview") or "").strip()]
    channels = [str(detail.get("channel") or "").strip().lower() for detail in details if str(detail.get("channel") or "").strip()]
    if not previews or not channels:
        return False
    if not all(("invite" in channel or "response" in channel or "confirmation" in channel) for channel in channels):
        return False
    title = str(topic.get("title") or "").strip().lower()
    if previews and all(preview == title or preview in title or title in preview for preview in previews):
        return True
    return False


def _is_speculative_support_offer_topic(topic: dict) -> bool:
    text_blob = _topic_prompt_text_blob(topic)
    if not text_blob:
        return False
    return (
        len(topic.get("evidence_details") or []) <= 2
        and _phrase_hits(
            text_blob,
            (
                "would love to show you the impact we can make",
                "would love to support",
                "if you don't secure",
                "anything else we can support",
                "supporting nv5",
                "profile attached",
            ),
        )
    )


def _has_recent_manual_answer(topic: dict) -> bool:
    recent_events = [event for event in (topic.get("recent_events") or []) if isinstance(event, dict)]
    if not recent_events:
        return False
    for event in recent_events:
        if str(event.get("event_type") or "").lower() not in {"manual_update", "manual_resolution"}:
            continue
        created_at = _parse_datetime(event.get("created_at"))
        if created_at and (datetime.now(timezone.utc) - created_at).days <= 14:
            return True
    return False


def _latest_manual_answer_at(topic: dict) -> datetime | None:
    latest: datetime | None = None
    for event in (topic.get("recent_events") or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("event_type") or "").lower() not in {"manual_update", "manual_resolution"}:
            continue
        created_at = _parse_datetime(event.get("created_at"))
        if created_at and (latest is None or created_at > latest):
            latest = created_at
    return latest


def _topic_subject_root(topic: dict) -> str:
    for candidate in (
        topic.get("title"),
        _topic_primary_preview(topic),
        *(detail.get("preview") for detail in (topic.get("evidence_details") or []) if isinstance(detail, dict)),
    ):
        text = str(candidate or "").strip()
        if not text:
            continue
        text = re.sub(r"^(re|fw|fwd):\s*", "", text, flags=re.IGNORECASE).strip()
        left = text.split(":", 1)[0].strip() if ":" in text else text
        normalized = re.sub(r"[^a-z0-9]+", " ", left.lower()).strip()
        if len(normalized.split()) >= 2:
            return " ".join(normalized.split()[:6])
    return ""


def _topic_propagation_family_key(topic: dict) -> str:
    kind = _clarification_prompt_kind(topic)
    if kind not in {"introduction", "meeting"}:
        return str(topic.get("storyline_family_key") or _topic_storyline_family_key(topic) or "")
    source_person = next(
        (
            re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
            for name in (topic.get("source_people") or [])
            if str(name or "").strip()
        ),
        "",
    )
    subject_root = _topic_subject_root(topic)
    bits = ["connection", source_person, subject_root]
    return "|".join(bit for bit in bits if bit) or str(topic.get("storyline_family_key") or _topic_storyline_family_key(topic) or "")


def _is_topic_covered_by_answer(topic: dict, answered_families: dict[str, dict]) -> bool:
    family_key = _topic_propagation_family_key(topic)
    if not family_key:
        return False
    answered = answered_families.get(family_key)
    if not answered:
        return False
    topic_anchor = _parse_datetime(topic.get("anchor_at"))
    answered_anchor = answered.get("anchor_at")
    if topic_anchor and answered_anchor:
        if topic_anchor < answered_anchor:
            return False
        if abs((topic_anchor - answered_anchor).days) > 21:
            return False
    answered_situation_id = str(answered.get("situation_record_id") or "").strip()
    current_situation_id = str(topic.get("situation_record_id") or "").strip()
    if answered_situation_id and current_situation_id and answered_situation_id == current_situation_id:
        return False
    return True


def _is_noise_clarification_topic(topic: dict) -> bool:
    text_blob = _topic_prompt_text_blob(topic)
    title = str(topic.get("title") or "").strip().lower()
    if not text_blob:
        return True

    hard_blockers = (
        "profile picture",
        "headshot",
        "this image is a",
        "i am uploading a cv/resume document",
        "please review this content and extract any career-relevant information",
        "i want to connect",
        "connections, experience, and more",
        "usual foloowup",
        "usual followup",
        "payment authorization",
        "car insurance",
        "trade gold",
        "take your hiring to the next level",
        "founding day offer",
        "network on zoom",
        "register to attend",
        "automatic reply",
        "out of office",
        "your message recall",
        "message recall",
        "privileged information",
        "confidential to the named recipient",
        "this email is privileged",
        "unsubscribe",
        "letter from",
        "contact details are not included",
        "wanted to reach out and stay in touch",
        "stay in touch with",
    )
    if _phrase_hits(text_blob, hard_blockers):
        return True

    if title.startswith("re: camel cup") or "camel cup" in title:
        return True

    if title.startswith("this situation is currently visible through"):
        return True

    if re.fullmatch(r"(.{4,80})\s+\1", title):
        return True

    if "weekend schedule" in text_blob and str(topic.get("topic_type") or "").lower() == "relationship":
        return True

    return False


def _clarification_prompt_kind(topic: dict) -> str:
    text_blob = _topic_prompt_text_blob(topic)
    evidence_blob = _topic_evidence_text_blob(topic)
    status = str(topic.get("status") or "").lower()
    topic_type = str(topic.get("topic_type") or "").lower()
    if _phrase_hits(
        evidence_blob,
        (
            "introduction",
            "introduced",
            "appreciate the introduction",
            "great to meet you",
            "friend of yours",
            "leave you guys to chat",
            "leave you to chat",
            "good addition to the obe network",
        ),
    ) or topic_type == "influence":
        return "introduction"
    if topic_type == "market":
        return "market"
    if _phrase_hits(
        text_blob,
        (
            "invoice",
            "nda",
            "agreement",
            "package",
            "terms",
            "commercial",
            "proposal",
            "fee",
        ),
    ):
        return "commercial"
    if _phrase_hits(
        text_blob,
        (
            "offer",
            "contract",
            "candidate",
            "shortlist",
            "role",
            "search",
            "recruitment",
            "hiring",
            "cv",
            "position",
            "executive search",
            "assignment",
        ),
    ):
        return "hiring"
    if _phrase_hits(
        evidence_blob,
        (
            "meeting",
            "teams",
            "interview",
            "zoom",
            "invite",
            "confirmation",
            "accepted",
            "canceled",
            "cancelled",
        ),
    ):
        return "meeting"
    if not topic.get("direct_present"):
        return "account"
    if status == "stale":
        return "stale"
    return "general"


def _clarification_prompt_subject(topic: dict) -> str:
    title = str(topic.get("title") or "").strip().strip(".")
    cleaned = re.sub(r"^(re|fw|fwd):\s*", "", title, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if (
        cleaned
        and len(cleaned) <= 52
        and len(cleaned.split()) <= 8
        and not _is_noise_clarification_topic({**topic, "title": cleaned})
    ):
        return cleaned

    kind = _clarification_prompt_kind(topic)
    return {
        "meeting": "this meeting thread",
        "introduction": "this introduction",
        "hiring": "this hiring thread",
        "commercial": "this commercial thread",
        "market": "this market signal",
        "account": "this account thread",
        "influence": "this influence thread",
        "stale": "this thread",
        "general": "this thread",
    }.get(kind, "this thread")


def _should_prompt_for_topic(topic: dict, *, person: dict) -> bool:
    if _is_noise_clarification_topic(topic):
        return False
    if _is_speculative_support_offer_topic(topic):
        return False
    if _has_recent_manual_answer(topic):
        return False
    if not topic.get("direct_present"):
        return False

    importance = int(topic.get("importance_score") or 0)
    if importance < 75:
        return False

    age_days = _topic_age_days(topic)
    kind = _clarification_prompt_kind(topic)
    is_personal_only = bool(topic.get("personal_continuity")) and str(topic.get("topic_type") or "").lower() == "relationship"
    prompt_blob = _topic_prompt_text_blob(topic)

    if is_personal_only and kind not in {"meeting", "introduction"}:
        return False
    if kind == "meeting" and (
        _is_invite_only_meeting_topic(topic)
        or not _phrase_hits(
            prompt_blob,
            (
                "interview",
                "assignment",
                "search",
                "candidate",
                "commercial",
                "introduction",
                "great to meet",
                "message me to arrange",
                "let me know your number",
                "whatsapp",
                "catch up",
                "reconnect",
            ),
        )
    ):
        return False

    if age_days is not None:
        if age_days > 30 and _is_invite_only_meeting_topic(topic):
            return False
        if age_days > 180 and kind in {"meeting", "general", "market", "influence"}:
            return False
        if age_days > 365:
            return False

    preview = _topic_primary_preview(topic).lower()
    if kind == "meeting" and ("invitation:" in preview or "register to attend" in preview) and age_days is not None and age_days < 30:
        return False

    if kind == "meeting":
        details = [detail for detail in (topic.get("evidence_details") or []) if isinstance(detail, dict)]
        channels = [str(detail.get("channel") or "").strip().lower() for detail in details]
        previews = [str(detail.get("preview") or "").strip() for detail in details if str(detail.get("preview") or "").strip()]
        if previews and len(previews) == 1 and len(previews[0].split()) <= 8 and "whatsapp" in "".join(channels):
            return False
        if channels and all(("response" in channel or "confirmation" in channel) for channel in channels):
            return False

    if not (topic.get("evidence_details") or topic.get("evidence")):
        return False

    return True


def _situation_status_sort_value(status: str | None) -> int:
    return {
        "open": 0,
        "stalled": 1,
        "watching": 2,
        "closed": 3,
    }.get(str(status or "").lower(), 4)


def _is_useful_prep_situation(item: dict) -> bool:
    headline = str(item.get("headline") or item.get("topic") or "").strip()
    why = str(item.get("why_it_matters") or "").strip()
    stage = str(item.get("stage") or "").strip()
    key_points = [point for point in (item.get("key_points") or []) if not _is_generic_prep_text(point)]
    if key_points:
        return True
    if stage and stage != "Relationship Update" and not _is_generic_prep_text(headline):
        return True
    if headline and not _is_generic_prep_text(headline):
        return True
    if why and not _is_generic_prep_text(why):
        return True
    return False


def _shape_prep_thread(item: dict) -> dict:
    supporting_entries = item.get("supporting_entries") or []
    evidence = _dedupe_text_list(
        [
            _best_evidence_preview(
                summary=entry.get("full_evidence_text"),
                evidence_snippets=entry.get("evidence_snippets") or [],
            )
            for entry in supporting_entries
        ],
        limit=2,
    )
    last_touch_at = item.get("end_at") or (supporting_entries[-1].get("interaction_at") if supporting_entries else None)
    raw_headline = item.get("headline") or item.get("topic") or "Live thread"
    display_headline = _brief_topic_label(evidence[0] if evidence else raw_headline)
    return {
        "situation_id": item.get("situation_id"),
        "headline": display_headline,
        "current_read": raw_headline,
        "topic_type": item.get("topic_type") or "relationship",
        "topic_type_label": item.get("topic_type_label") or _story_topic_type_label(item.get("topic_type") or "relationship"),
        "stage": item.get("stage") or "Relationship Update",
        "momentum": item.get("momentum") or "steady",
        "tracking_status": item.get("tracking_status") or "watching",
        "tracking_status_label": item.get("tracking_status_label") or _relationship_situation_status_label(item.get("tracking_status") or "watching"),
        "why_it_matters": item.get("why_it_matters") or "",
        "recommended_action": item.get("recommended_action") or "",
        "key_points": _dedupe_text_list(item.get("key_points") or [], limit=4),
        "evidence": evidence,
        "window_label": item.get("window_label") or "",
        "last_touch_at": last_touch_at,
        "last_touch_label": _brief_date_label(last_touch_at),
        "channels": item.get("channels") or [],
        "entry_count": int(item.get("entry_count") or 0),
    }


def _relationship_topic_identity(text: str | None, topic_type: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()
    if not normalized:
        normalized = "relationship topic"
    return f"{str(topic_type or 'relationship').lower()}|{normalized}"


def _topic_text_blob(parts: list[str | None]) -> str:
    values = []
    for part in parts:
        text = str(part or "").strip()
        if text:
            values.append(text)
    return " ".join(values).lower()


def _topic_supporting_evidence(item: dict) -> list[str]:
    evidence = _dedupe_text_list(
        [
            _best_evidence_preview(
                summary=entry.get("full_evidence_text"),
                evidence_snippets=entry.get("evidence_snippets") or [],
            )
            for entry in item.get("supporting_entries") or []
        ],
        limit=3,
    )
    if evidence:
        return evidence
    fallback = _best_evidence_preview(summary=item.get("timeline_summary"))
    return [fallback] if fallback else []


def _topic_supporting_context_details(item: dict, limit: int = 3) -> list[dict]:
    details: list[dict] = []
    seen: set[str] = set()
    for entry in item.get("supporting_entries") or []:
        preview = _best_evidence_preview(
            summary=entry.get("full_evidence_text"),
            evidence_snippets=entry.get("evidence_snippets") or [],
            max_len=220,
        )
        if not preview:
            continue
        channel = str(entry.get("channel") or "Interaction").strip()
        date_label = _brief_date_label(entry.get("interaction_at"))
        dedupe_key = f"{date_label}|{channel}|{preview.lower()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        details.append(
            {
                "interaction_at": entry.get("interaction_at"),
                "date_label": date_label,
                "channel": channel,
                "preview": preview,
            }
        )
        if len(details) >= limit:
            break
    return details


def _is_personal_topic_text(text: str | None) -> bool:
    lowered = _clean_source_text(text).lower()
    if not lowered:
        return False
    if _is_courtesy_only_rapport_text(lowered):
        return False
    if _is_topic_admin_noise_text(lowered):
        return False
    strong_personal_keywords = (
        "daughter",
        "son",
        "kids",
        "children",
        "wife",
        "husband",
        "family",
        "rugby",
        "football",
        "golf",
        "birthday",
        "school",
        "hobby",
    )
    if any(keyword in lowered for keyword in strong_personal_keywords):
        return True
    weaker_personal_keywords = (
        "weekend",
        "holiday",
        "travel",
        "ramadan",
        "eid",
    )
    business_blockers = (
        "candidate",
        "search",
        "role",
        "assignment",
        "cv",
        "profile",
        "passport",
        "position",
        "interview",
        "commercial",
        "offer",
        "package",
        "salary",
        "agreement",
        "invoice",
        "structural engineer",
        "project manager",
        "director",
        "meeting",
        "teams",
    )
    return any(keyword in lowered for keyword in weaker_personal_keywords) and not any(
        blocker in lowered for blocker in business_blockers
    )


def _is_market_topic_text(text: str | None) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    market_keywords = (
        "market",
        "demand",
        "salary",
        "package",
        "pay",
        "hiring",
        "talent",
        "growth",
        "strategy",
        "expansion",
        "pressure",
        "leadership",
    )
    return any(keyword in lowered for keyword in market_keywords)


def _is_track_record_topic_text(text: str | None) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    track_keywords = (
        "started",
        "joins",
        "joining",
        "signed contract",
        "contract signed",
        "accepted",
        "proceed accordingly",
        "went wrong",
        "went well",
        "success",
        "failed",
        "lost",
        "completed",
        "filled",
    )
    return any(keyword in lowered for keyword in track_keywords)


def _relationship_topic_status(item: dict, *, direct_present: bool = True) -> str:
    text_blob = _topic_text_blob(
        [
            item.get("headline"),
            item.get("current_read"),
            item.get("why_it_matters"),
            item.get("stage"),
            item.get("recommended_action"),
            " ".join(item.get("key_points") or []),
            " ".join(item.get("evidence") or []),
        ]
    )
    source_status = str(item.get("tracking_status") or item.get("status") or "").lower()
    last_touch = _parse_datetime(item.get("last_touch_at") or item.get("end_at") or item.get("state_changed_at"))
    now = datetime.now(timezone.utc)

    transitioned_keywords = (
        "signed contract",
        "contract signed",
        "proceed accordingly",
        "start on",
        "starts on",
        "starting on",
        "kick off",
        "active assignment",
        "existing client",
        "welcome him",
        "welcome her",
    )
    if any(keyword in text_blob for keyword in transitioned_keywords):
        return "transitioned"

    closed_keywords = (
        "mandate lost",
        "role filled",
        "position filled",
        "no longer available",
        "topic addressed",
        "cancelled",
        "withdrawn",
        "superseded",
        "closed off",
    )
    if source_status == "closed" or any(keyword in text_blob for keyword in closed_keywords):
        return "closed"

    stale_keywords = (
        "waiting",
        "pending",
        "on hold",
        "paused",
        "not awarded",
        "hasn't moved",
        "has not moved",
        "no movement",
        "stale",
        "delayed",
        "delay",
    )
    if source_status in {"watching", "stalled"} or any(keyword in text_blob for keyword in stale_keywords):
        return "stale"

    if last_touch:
        age_days = (now - last_touch).days
        if age_days >= 45 and not direct_present:
            return "stale"
        if age_days >= 60:
            return "stale"

    return "open"


def _relationship_topic_status_label(status: str | None) -> str:
    return {
        "open": "Open",
        "stale": "Stale",
        "closed": "Closed",
        "transitioned": "Transitioned",
    }.get(str(status or "").lower(), "Open")


def _relationship_topic_importance(
    topic_type: str | None,
    *,
    personal: bool = False,
    direct_present: bool = False,
    source_count: int = 1,
    status: str | None = None,
) -> int:
    base_scores = {
        "relationship": 62 if not personal else 74,
        "opportunity": 88,
        "market": 80,
        "risk": 72,
        "influence": 70,
    }
    score = base_scores.get(str(topic_type or "relationship").lower(), 72)
    if direct_present:
        score += 4
    score += min(6, max(0, source_count - 1) * 2)
    if str(status or "").lower() == "transitioned":
        score += 4
    if str(status or "").lower() == "stale":
        score -= 4
    if str(status or "").lower() == "closed":
        score -= 12
    return max(35, min(98, score))


def _relationship_topic_sort_key(topic: dict) -> tuple:
    status_value = {
        "open": 0,
        "transitioned": 1,
        "stale": 2,
        "closed": 3,
    }.get(str(topic.get("status") or "").lower(), 4)
    last_touch = _parse_datetime(topic.get("last_touch_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        status_value,
        -int(topic.get("importance_score") or 0),
        -int(last_touch.timestamp()),
    )


def _topic_anchor_at(topic: dict) -> str:
    candidates: list[str] = []
    for thread in topic.get("supporting_threads") or []:
        if not isinstance(thread, dict):
            continue
        value = str(thread.get("last_touch_at") or "").strip()
        if value:
            candidates.append(value)
        for detail in thread.get("evidence_details") or []:
            if isinstance(detail, dict):
                detail_value = str(detail.get("interaction_at") or "").strip()
                if detail_value:
                    candidates.append(detail_value)
    for detail in topic.get("evidence_details") or []:
        if isinstance(detail, dict):
            value = str(detail.get("interaction_at") or "").strip()
            if value:
                candidates.append(value)
    if topic.get("last_touch_at"):
        candidates.append(str(topic.get("last_touch_at")))
    if not candidates:
        return ""
    return min(candidates, key=lambda value: _parse_datetime(value) or datetime(2100, 1, 1, tzinfo=timezone.utc))


def _topic_storyline_family_key(topic: dict) -> str:
    source_people = [
        re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()
        for name in (topic.get("source_people") or [])
        if str(name or "").strip()
    ]
    text_blob = _topic_text_blob(
        [
            topic.get("title"),
            _topic_primary_preview(topic),
            " ".join(topic.get("channels") or []),
        ]
    )
    tokens: list[str] = []
    stopwords = {
        "this", "that", "with", "from", "into", "between", "there", "their", "what", "where",
        "topic", "thread", "meeting", "invite", "confirmation", "email", "call", "teams",
        "relationship", "update", "hiring", "commercial", "current", "status", "should",
        "retain", "truth", "good", "made", "both", "were", "they", "them", "have", "will",
    }
    for raw_token in re.findall(r"[a-z0-9]+", text_blob):
        token = raw_token.strip()
        if len(token) < 4 or token in stopwords:
            continue
        if token not in tokens:
            tokens.append(token)
        if len(tokens) >= 4:
            break
    family_type = str(topic.get("topic_type") or "relationship").lower()
    if _clarification_prompt_kind(topic) in {"introduction", "meeting"}:
        family_type = "connection"
    family_bits = [family_type]
    if source_people:
        family_bits.append(source_people[0])
    if family_type == "connection":
        anchor_at = _parse_datetime(topic.get("anchor_at"))
        if anchor_at:
            family_bits.append(anchor_at.date().isoformat())
        family_bits.extend(tokens[:2])
    else:
        family_bits.extend(tokens[:3])
    return "|".join(bit for bit in family_bits if bit) or str(topic.get("topic_key") or "")


def _clarification_queue_sort_key(topic: dict) -> tuple:
    anchor_at = _parse_datetime(topic.get("anchor_at")) or datetime(2100, 1, 1, tzinfo=timezone.utc)
    last_touch = _parse_datetime(topic.get("last_touch_at")) or datetime(2100, 1, 1, tzinfo=timezone.utc)
    return (
        0 if topic.get("direct_present") else 1,
        int(anchor_at.timestamp()),
        int(last_touch.timestamp()),
        -int(topic.get("importance_score") or 0),
        str(topic.get("title") or "").lower(),
    )


def _build_relationship_topic_prompt(topic: dict, person: dict) -> str:
    if not _should_prompt_for_topic(topic, person=person):
        return ""

    status = str(topic.get("status") or "").lower()
    company_name = str(person.get("company_name_raw") or "the account").strip()
    person_name = str(person.get("full_name") or "this contact").strip()
    kind = _clarification_prompt_kind(topic)
    text_blob = _topic_prompt_text_blob(topic)
    subject = _clarification_prompt_subject(topic)
    connection_progression = _phrase_hits(
        text_blob,
        (
            "meet up",
            "quick call",
            "get acquainted",
            "message me to arrange",
            "let me know your number",
            "whatsapp",
        ),
    )
    if kind == "meeting":
        if _phrase_hits(text_blob, ("introduction", "great to meet you", "friend of yours")):
            return f"What actually happened after {subject}, and what should the system retain as the current truth?"
        return f"Did {subject} happen, and what changed as a result?"
    if kind == "introduction":
        if connection_progression:
            return f"What came from {subject}, and what should the system retain now?"
        return f"Did {subject} happen, and what came from it?"
    if status == "stale":
        return f"Is {subject} still active, paused, or closed, and what is the current truth?"
    if status == "transitioned":
        return f"What is the current status of {subject} now, and what is the next step?"
    if kind == "hiring":
        return f"Where does {subject} now stand, and what should the system retain as the current truth?"
    if kind == "commercial":
        return f"Where does {subject} now stand commercially, and what should the system retain?"
    if kind == "market":
        return f"Is {subject} still a live market point, or just background context now?"
    if not topic.get("direct_present") and int(topic.get("importance_score") or 0) >= 75:
        return f"Is {subject} directly live with {person_name}, or only wider account context at {company_name}?"
    if int(topic.get("confidence_score") or 0) < 65 and int(topic.get("importance_score") or 0) >= 70:
        return f"What is actually happening on {subject} with {person_name}, and what should the system retain as the current truth?"
    return ""


def build_relationship_topics(
    *,
    person: dict,
    tracked_situations: list[dict],
    related_team_context: dict | None = None,
) -> dict:
    person_id = str(person.get("person_id") or "")
    person_name = str(person.get("full_name") or "this contact")

    topic_candidates: list[dict] = []
    for item in tracked_situations or []:
        evidence = _topic_supporting_evidence(item)
        evidence_details = _topic_supporting_context_details(item)
        title = _brief_topic_label((evidence[0] if evidence else "") or item.get("headline") or item.get("topic") or "")
        if _is_generic_prep_text(title):
            continue
        topic_candidates.append(
            {
                "topic_key": _relationship_topic_identity(title, item.get("topic_type")),
                "title": title,
                "topic_type": item.get("topic_type") or "relationship",
                "current_read": item.get("headline") or item.get("topic") or title,
                "why_it_matters": item.get("why_it_matters") or "",
                "stage": item.get("stage") or "Relationship Update",
                "momentum": item.get("momentum") or "steady",
                "tracking_status": item.get("tracking_status") or "watching",
                "window_label": item.get("window_label") or "",
                "channels": item.get("channels") or [],
                "key_points": _dedupe_text_list(item.get("key_points") or [], limit=4),
                "evidence": evidence,
                "evidence_details": evidence_details,
                "recommended_action": item.get("recommended_action") or "",
                "confidence_score": int(item.get("confidence_score") or 0),
                "last_touch_at": item.get("end_at"),
                "situation_record_id": item.get("situation_record_id"),
                "situation_id": item.get("situation_id"),
                "recent_events": list(item.get("recent_events") or []),
                "source_kind": "direct",
                "source_person_id": person_id,
                "source_person_name": person_name,
            }
        )

    for thread in (related_team_context or {}).get("threads") or []:
        evidence = _dedupe_text_list(thread.get("evidence") or [], limit=3)
        evidence_details = [
            {
                "interaction_at": thread.get("last_touch_at"),
                "date_label": _brief_date_label(thread.get("last_touch_at")),
                "channel": str(thread.get("full_name") or "Account context"),
                "preview": str(value).strip(),
            }
            for value in evidence[:2]
            if str(value or "").strip()
        ]
        title = _brief_topic_label((evidence[0] if evidence else "") or thread.get("headline") or thread.get("current_read") or "")
        if _is_generic_prep_text(title):
            continue
        topic_candidates.append(
            {
                "topic_key": _relationship_topic_identity(title, thread.get("topic_type")),
                "title": title,
                "topic_type": thread.get("topic_type") or "relationship",
                "current_read": thread.get("current_read") or thread.get("headline") or title,
                "why_it_matters": thread.get("why_it_matters") or "",
                "stage": thread.get("stage") or "Relationship Update",
                "momentum": thread.get("momentum") or "steady",
                "tracking_status": thread.get("tracking_status") or "watching",
                "window_label": thread.get("window_label") or "",
                "channels": thread.get("channels") or [],
                "key_points": _dedupe_text_list(thread.get("key_points") or [], limit=4),
                "evidence": evidence,
                "evidence_details": evidence_details,
                "recommended_action": thread.get("recommended_action") or "",
                "confidence_score": int(thread.get("confidence_score") or 68),
                "last_touch_at": thread.get("last_touch_at"),
                "source_kind": "account",
                "source_person_id": thread.get("person_id"),
                "source_person_name": thread.get("full_name") or "Account contact",
            }
        )

    merged_topics: dict[str, dict] = {}
    for candidate in topic_candidates:
        key = str(candidate.get("topic_key") or "")
        if not key:
            continue
        topic = merged_topics.setdefault(
            key,
            {
                "topic_key": key,
                "title": candidate["title"],
                "topic_type": candidate["topic_type"],
                "topic_type_label": _story_topic_type_label(candidate["topic_type"]),
                "current_read": candidate["current_read"],
                "why_it_matters": candidate["why_it_matters"],
                "stage": candidate["stage"],
                "momentum": candidate["momentum"],
                "channels": [],
                "key_points": [],
                "evidence": [],
                "evidence_details": [],
                "recommended_action": candidate["recommended_action"],
                "confidence_values": [],
                "last_touch_values": [],
                "tracking_status": candidate["tracking_status"],
                "situation_record_id": None,
                "situation_id": None,
                "recent_events": [],
                "source_people": [],
                "direct_present": False,
                "account_context_count": 0,
                "supporting_threads": [],
            },
        )
        topic["direct_present"] = topic["direct_present"] or candidate["source_kind"] == "direct"
        if candidate["source_kind"] == "direct" and candidate.get("situation_record_id") and not topic.get("situation_record_id"):
            topic["situation_record_id"] = candidate.get("situation_record_id")
            topic["situation_id"] = candidate.get("situation_id")
        if candidate["source_kind"] != "direct":
            topic["account_context_count"] += 1
        if candidate["source_person_name"] and candidate["source_person_name"] not in topic["source_people"]:
            topic["source_people"].append(candidate["source_person_name"])
        existing_status = str(topic.get("tracking_status") or "").lower()
        candidate_status = str(candidate.get("tracking_status") or "").lower()
        status_rank = {
            "open": 0,
            "transitioned": 1,
            "stalled": 2,
            "watching": 3,
            "closed": 4,
        }
        if status_rank.get(candidate_status, 9) < status_rank.get(existing_status, 9):
            topic["tracking_status"] = candidate.get("tracking_status")
        topic["channels"] = _dedupe_text_list(topic["channels"] + list(candidate.get("channels") or []), limit=6)
        topic["key_points"] = _dedupe_text_list(topic["key_points"] + list(candidate.get("key_points") or []), limit=5)
        topic["evidence"] = _dedupe_text_list(topic["evidence"] + list(candidate.get("evidence") or []), limit=4)
        topic["recent_events"] = sorted(
            [
                *(topic.get("recent_events") or []),
                *(candidate.get("recent_events") or []),
            ],
            key=lambda item: _parse_datetime((item or {}).get("created_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc),
            reverse=True,
        )[:4]
        existing_detail_keys = {
            f"{str(item.get('date_label') or '').strip()}|{str(item.get('channel') or '').strip()}|{str(item.get('preview') or '').strip().lower()}"
            for item in topic["evidence_details"]
            if isinstance(item, dict)
        }
        for detail in candidate.get("evidence_details") or []:
            if not isinstance(detail, dict):
                continue
            preview = str(detail.get("preview") or "").strip()
            channel = str(detail.get("channel") or "").strip()
            date_label = str(detail.get("date_label") or "").strip()
            if not preview:
                continue
            dedupe_key = f"{date_label}|{channel}|{preview.lower()}"
            if dedupe_key in existing_detail_keys:
                continue
            existing_detail_keys.add(dedupe_key)
            topic["evidence_details"].append(
                {
                    "interaction_at": detail.get("interaction_at"),
                    "date_label": date_label,
                    "channel": channel,
                    "preview": preview,
                }
            )
        topic["evidence_details"] = topic["evidence_details"][:4]
        topic["supporting_threads"].append(
            {
                "source_kind": candidate["source_kind"],
                "source_person_id": candidate["source_person_id"],
                "source_person_name": candidate["source_person_name"],
                "situation_record_id": candidate.get("situation_record_id"),
                "situation_id": candidate.get("situation_id"),
                "current_read": candidate["current_read"],
                "why_it_matters": candidate["why_it_matters"],
                "stage": candidate["stage"],
                "tracking_status": candidate["tracking_status"],
                "window_label": candidate["window_label"],
                "evidence": list(candidate.get("evidence") or []),
                "evidence_details": list(candidate.get("evidence_details") or []),
            }
        )
        if candidate.get("recommended_action") and not topic.get("recommended_action"):
            topic["recommended_action"] = candidate["recommended_action"]
        if candidate.get("current_read") and len(str(candidate["current_read"])) > len(str(topic.get("current_read") or "")):
            topic["current_read"] = candidate["current_read"]
        if candidate.get("why_it_matters") and len(str(candidate["why_it_matters"])) > len(str(topic.get("why_it_matters") or "")):
            topic["why_it_matters"] = candidate["why_it_matters"]
        topic["confidence_values"].append(int(candidate.get("confidence_score") or 0))
        if candidate.get("last_touch_at"):
            topic["last_touch_values"].append(candidate["last_touch_at"])

    shaped_topics: list[dict] = []
    for topic in merged_topics.values():
        text_blob = _topic_text_blob(
            [
                topic.get("title"),
                topic.get("current_read"),
                topic.get("why_it_matters"),
                " ".join(topic.get("key_points") or []),
                " ".join(topic.get("evidence") or []),
            ]
        )
        if _is_topic_admin_noise_text(text_blob):
            continue
        status = _relationship_topic_status(topic, direct_present=bool(topic.get("direct_present")))
        personal = _is_personal_topic_text(text_blob)
        market = str(topic.get("topic_type") or "") == "market" or _is_market_topic_text(text_blob)
        track_record = _is_track_record_topic_text(text_blob) or status in {"transitioned", "closed"}
        confidence_values = topic.pop("confidence_values", [])
        confidence_score = int(round(sum(confidence_values) / len(confidence_values))) if confidence_values else 0
        last_touch_values = topic.pop("last_touch_values", [])
        last_touch_at = max(
            last_touch_values,
            key=lambda value: _parse_datetime(value) or datetime(1970, 1, 1, tzinfo=timezone.utc),
        ) if last_touch_values else ""
        importance_score = _relationship_topic_importance(
            topic.get("topic_type"),
            personal=personal,
            direct_present=bool(topic.get("direct_present")),
            source_count=len(topic.get("source_people") or []),
            status=status,
        )
        prompt = _build_relationship_topic_prompt(
            {
                **topic,
                "status": status,
                "confidence_score": confidence_score,
                "importance_score": importance_score,
                "last_touch_at": last_touch_at,
                "personal_continuity": personal,
            },
            person,
        )
        anchor_at = _topic_anchor_at({**topic, "last_touch_at": last_touch_at})
        recent_manual_answer = _has_recent_manual_answer({**topic, "anchor_at": anchor_at})
        shaped_topics.append(
            {
                **topic,
                "status": status,
                "status_label": _relationship_topic_status_label(status),
                "confidence_score": confidence_score,
                "importance_score": importance_score,
                "last_touch_at": last_touch_at,
                "last_touch_label": _brief_date_label(last_touch_at),
                "anchor_at": anchor_at,
                "personal_continuity": personal,
                "market_relevant": market,
                "track_record": track_record,
                "clarification_prompt": prompt,
                "answer_status": "answered" if recent_manual_answer else "unanswered",
                "recent_manual_answer": recent_manual_answer,
                "propagation_family_key": _topic_propagation_family_key({**topic, "anchor_at": anchor_at}),
                "latest_manual_answer_at": (
                    _latest_manual_answer_at({**topic, "anchor_at": anchor_at}).isoformat()
                    if _latest_manual_answer_at({**topic, "anchor_at": anchor_at})
                    else ""
                ),
            }
        )

    answered_families: dict[str, dict] = {}
    for topic in shaped_topics:
        if not topic.get("recent_manual_answer"):
            continue
        family_key = str(topic.get("propagation_family_key") or "")
        if not family_key:
            continue
        latest_answer_at = _parse_datetime(topic.get("latest_manual_answer_at"))
        anchor_at = _parse_datetime(topic.get("anchor_at"))
        existing = answered_families.get(family_key)
        if not existing or (
            latest_answer_at and (existing.get("latest_answer_at") is None or latest_answer_at > existing.get("latest_answer_at"))
        ):
            answered_families[family_key] = {
                "latest_answer_at": latest_answer_at,
                "anchor_at": anchor_at,
                "situation_record_id": topic.get("situation_record_id"),
            }

    for topic in shaped_topics:
        if topic.get("recent_manual_answer"):
            continue
        if _is_topic_covered_by_answer(topic, answered_families):
            topic["answer_status"] = "covered_by_recent_answer"
            topic["clarification_prompt"] = ""

    shaped_topics = sorted(shaped_topics, key=_relationship_topic_sort_key)
    personal_continuity = [topic for topic in shaped_topics if topic.get("personal_continuity")][:4]
    active_topics = [topic for topic in shaped_topics if topic.get("status") != "closed" and not topic.get("personal_continuity")][:6]
    market_business_view = [topic for topic in shaped_topics if topic.get("market_relevant")][:5]
    track_record = [topic for topic in shaped_topics if topic.get("track_record")][:5]
    clarification_candidates = []
    for topic in shaped_topics:
        if not topic.get("clarification_prompt"):
            continue
        clarification_candidates.append(
            {
                "topic_key": topic.get("topic_key"),
                "title": topic.get("title"),
                "situation_record_id": topic.get("situation_record_id") or next(
                    (
                        thread.get("situation_record_id")
                        for thread in (topic.get("supporting_threads") or [])
                        if isinstance(thread, dict) and thread.get("situation_record_id")
                    ),
                    None,
                ),
                "situation_id": topic.get("situation_id") or next(
                    (
                        thread.get("situation_id")
                        for thread in (topic.get("supporting_threads") or [])
                        if isinstance(thread, dict) and thread.get("situation_id")
                    ),
                    None,
                ),
                "question": topic.get("clarification_prompt"),
                "status": topic.get("status"),
                "status_label": topic.get("status_label"),
                "importance_score": topic.get("importance_score"),
                "source_people": topic.get("source_people") or [],
                "topic_type": topic.get("topic_type"),
                "topic_type_label": topic.get("topic_type_label"),
                "current_read": topic.get("current_read"),
                "why_it_matters": topic.get("why_it_matters"),
                "recommended_action": topic.get("recommended_action"),
                "evidence": topic.get("evidence") or [],
                "evidence_details": topic.get("evidence_details") or [],
                "supporting_threads": topic.get("supporting_threads") or [],
                "recent_events": topic.get("recent_events") or [],
                "answer_status": topic.get("answer_status") or "unanswered",
                "anchor_at": topic.get("anchor_at"),
                "anchor_label": _brief_date_label(topic.get("anchor_at")),
                "storyline_family_key": _topic_storyline_family_key(topic),
                "propagation_family_key": topic.get("propagation_family_key") or "",
                "context": (
                    f"{topic.get('title')} | {topic.get('status_label')} | "
                    f"{'Direct and account-linked' if topic.get('direct_present') and topic.get('account_context_count') else 'Direct' if topic.get('direct_present') else 'Account-linked'}"
                ),
            }
        )

    family_counts: dict[str, int] = {}
    for item in clarification_candidates:
        family_key = str(item.get("storyline_family_key") or "")
        family_counts[family_key] = family_counts.get(family_key, 0) + 1

    seen_families: set[str] = set()
    clarification_prompts = []
    for item in sorted(clarification_candidates, key=_clarification_queue_sort_key):
        family_key = str(item.get("storyline_family_key") or "")
        if family_key and family_key in seen_families:
            continue
        if family_key:
            seen_families.add(family_key)
        item["follow_on_topic_count"] = max(0, family_counts.get(family_key, 1) - 1)
        clarification_prompts.append(item)
        if len(clarification_prompts) >= 4:
            break

    summary_parts = []
    if active_topics:
        summary_parts.append(f"{len(active_topics)} active topic{'s' if len(active_topics) != 1 else ''}")
    if personal_continuity:
        summary_parts.append(f"{len(personal_continuity)} personal continuity point{'s' if len(personal_continuity) != 1 else ''}")
    if market_business_view:
        summary_parts.append(f"{len(market_business_view)} market or business thread{'s' if len(market_business_view) != 1 else ''}")
    if clarification_prompts:
        summary_parts.append(f"{len(clarification_prompts)} clarification question{'s' if len(clarification_prompts) != 1 else ''}")
    summary = (
        f"Relationship topics for {person_name} currently include " + ", ".join(summary_parts) + "."
        if summary_parts
        else f"No relationship topics are ready for {person_name} yet."
    )

    return {
        "summary": summary,
        "all_topics": shaped_topics,
        "personal_continuity": personal_continuity,
        "active_topics": active_topics,
        "market_business_view": market_business_view,
        "track_record": track_record,
        "clarification_prompts": clarification_prompts,
    }


def build_relationship_story(
    *,
    person: dict,
    tracked_situations: list[dict],
    relationship_topics: dict | None = None,
    recent_evidence: list[dict] | None = None,
    interpreted_interactions: list[dict] | None = None,
    promoted_memory: dict | None = None,
) -> dict:
    name = str(person.get("full_name") or "this contact")
    company_name = str(
        person.get("company_name")
        or person.get("company_name_raw")
        or person.get("company")
        or ""
    ).strip()
    topics = list((relationship_topics or {}).get("all_topics") or [])
    direct_topics = [topic for topic in topics if topic.get("direct_present")]
    answered_topics = [
        topic
        for topic in direct_topics
        if str(topic.get("answer_status") or "") in {"answered", "covered_by_recent_answer"}
    ]
    resolved_situations = [
        item for item in (tracked_situations or [])
        if str(item.get("tracking_status") or "").lower() == "closed"
    ]
    open_questions = list((relationship_topics or {}).get("clarification_prompts") or [])

    def _topic_source_lines(topic: dict, *, limit: int = 2) -> list[str]:
        lines: list[str] = []
        for detail in topic.get("evidence_details") or []:
            if not isinstance(detail, dict):
                continue
            preview = str(detail.get("preview") or "").strip()
            if preview:
                lines.append(preview)
            if len(lines) >= limit:
                return lines
        for evidence in topic.get("evidence") or []:
            preview = str(evidence or "").strip()
            if preview:
                lines.append(preview)
            if len(lines) >= limit:
                return lines
        primary_preview = _topic_primary_preview(topic)
        if primary_preview:
            lines.append(primary_preview)
        return lines[:limit]

    def _topic_business_blob(topic: dict) -> str:
        return _topic_text_blob(
            [
                topic.get("title"),
                topic.get("current_read"),
                " ".join(topic.get("key_points") or []),
                " ".join(_topic_source_lines(topic, limit=2)),
                topic.get("recommended_action"),
                topic.get("stage"),
            ]
        )

    def _clean_story_text(text: str | None) -> str:
        cleaned = _clean_source_text(text or "")
        if not cleaned:
            return ""
        escaped_name = re.escape(name)
        escaped_company = re.escape(company_name) if company_name else ""
        patterns: list[tuple[str, str]] = [
            (
                rf"^(Meeting|Call|Discussion|Conversation|Follow(?:-| )up|Update|Email|Chat)\s+with\s+{escaped_name}(?:\s+from\s+{escaped_company})?\b",
                r"\1",
            ),
            (
                rf"\bwith\s+{escaped_name}(?:\s+from\s+{escaped_company})?\b",
                "",
            ),
        ]
        if escaped_company:
            patterns.extend(
                [
                    (rf"\b{escaped_name}\s+from\s+{escaped_company}\b", ""),
                    (
                        rf"^(Meeting|Call|Discussion|Conversation|Follow(?:-| )up|Update|Email|Chat)\s+from\s+{escaped_company}\b",
                        r"\1",
                    ),
                    (
                        rf"^(Meeting|Call|Discussion|Conversation|Follow(?:-| )up|Update|Email|Chat)\s*{escaped_company}\b",
                        r"\1",
                    ),
                ]
            )
        for pattern, replacement in patterns:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bsummary:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:re:\s*|fw:\s*|fwd:\s*)?[^:]{6,90}:\s+", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = cleaned.replace("_", " ")
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
        cleaned = re.sub(r"^[-,:;.\s]+", "", cleaned).strip()
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        return cleaned

    def _story_topic_heading(topic: dict, summary: str = "") -> str:
        blob = _topic_business_blob(topic)
        lowered_summary = str(summary or "").lower()
        if _is_personal_story_topic(topic):
            return "Personal continuity"
        if "introduction" in blob or "introduction" in lowered_summary:
            return "Introduction thread"
        if any(term in blob for term in ("bim", "data center", "data centres", "head of data centers", "specialist")):
            return "Hiring focus"
        if any(term in blob for term in ("commercial", "pricing", "package", "filled", "terms")):
            return "Commercial position"
        if any(term in blob for term in ("hospital", "project", "pipeline")):
            return "Project focus"
        if any(term in blob for term in ("meeting", "call", "follow up", "follow-up")):
            return "Meeting thread"
        if _is_market_business_story_topic(topic):
            return "Market & business"
        if _is_track_record_story_topic(topic):
            return "Track record"
        return "Active thread"

    def _story_truth_line(topic: dict) -> str:
        resolution_note = str(topic.get("resolution_note") or "").strip()
        if resolution_note and str(topic.get("status") or "").lower() == "closed":
            return _clean_story_text(resolution_note)
        current_read = str(topic.get("current_read") or "").strip()
        title = str(topic.get("title") or "").strip()
        preview = _topic_primary_preview(topic)
        lowered_current = current_read.lower()
        vague_markers = (
            "engagement with",
            "discussions",
            "process stage movement",
            "relationship update",
            "current story",
            "thread",
            "situation",
            "working picture",
            "visible through",
            "interaction points to",
            "contains meaningful",
            "operational movement",
            "door-opening",
        )
        if current_read and not _is_generic_prep_text(current_read):
            if not any(marker in lowered_current for marker in vague_markers) and not _is_low_signal_story_summary(current_read):
                return _clean_story_text(current_read)
        for point in topic.get("key_points") or []:
            point_text = str(point or "").strip()
            lowered_point = point_text.lower()
            if (
                point_text
                and not _is_generic_prep_text(point_text)
                and not any(marker in lowered_point for marker in vague_markers)
                and not _is_low_signal_story_summary(point_text)
            ):
                return _clean_story_text(point_text)
        if preview:
            return _clean_story_text(_clip(preview, 180))
        if title:
            return _clean_story_text(_brief_topic_label(title))
        return _clean_story_text(current_read)

    def _topic_evidence_anchor(topic: dict) -> str:
        for detail in topic.get("evidence_details") or []:
            if isinstance(detail, dict) and str(detail.get("preview") or "").strip():
                return (
                    f"{detail.get('date_label') or _brief_date_label(detail.get('interaction_at'))} | "
                    f"{detail.get('channel') or 'Interaction'} | "
                    f"{str(detail.get('preview') or '').strip()}"
                )
        return ""

    def _is_personal_story_topic(topic: dict) -> bool:
        source_blob = _topic_text_blob(
            [
                topic.get("title"),
                " ".join(_topic_source_lines(topic, limit=2)),
            ]
        )
        if not source_blob:
            return False
        strong_personal_terms = ("wife", "husband", "family", "children", "kids", "daughter", "son", "birthday", "school")
        soft_personal_terms = ("golf", "rugby", "football", "holiday", "travel", "weekend")
        business_terms = (
            "candidate",
            "role",
            "search",
            "hiring",
            "recruitment",
            "talent",
            "commercial",
            "client",
            "project",
            "market",
            "salary",
            "package",
            "meeting",
            "cv",
            "data center",
            "bim",
            "obe",
        )
        has_strong_personal = any(term in source_blob for term in strong_personal_terms)
        has_soft_personal = any(term in source_blob for term in soft_personal_terms)
        if has_strong_personal:
            return True
        if has_soft_personal and not any(term in source_blob for term in business_terms):
            return True
        return False

    def _is_market_business_story_topic(topic: dict) -> bool:
        business_blob = _topic_text_blob(
            [
                topic.get("title"),
                " ".join(_topic_source_lines(topic, limit=2)),
                " ".join(topic.get("key_points") or []),
            ]
        )
        if not business_blob:
            return False
        business_keywords = (
            "commercial",
            "client",
            "mandate",
            "role",
            "search",
            "hiring",
            "recruitment",
            "salary",
            "package",
            "talent",
            "growth",
            "strategy",
            "data center",
            "bim",
            "candidate",
            "cv",
            "market",
            "pressure",
            "leadership",
        )
        has_business_signal = any(keyword in business_blob for keyword in business_keywords)
        if not has_business_signal:
            return False
        if str(topic.get("topic_type") or "").lower() in {"market", "opportunity", "risk"}:
            return True
        return _is_market_topic_text(business_blob) or has_business_signal

    def _is_track_record_story_topic(topic: dict) -> bool:
        status = str(topic.get("status") or "").lower()
        if status in {"closed", "transitioned"}:
            return True
        if str(topic.get("resolution_note") or "").strip():
            return True
        return bool(topic.get("track_record")) and status not in {"open", "stalled"}

    def _is_active_story_topic(topic: dict) -> bool:
        if _is_personal_story_topic(topic):
            return False
        if str(topic.get("answer_status") or "") == "covered_by_recent_answer":
            return False
        status = str(topic.get("status") or "").lower()
        if status == "closed":
            return False
        if str(topic.get("answer_status") or "") == "answered":
            return True
        return status in {"open", "stalled", "transitioned"}

    def _supporting_story_points(
        topic: dict,
        *,
        summary: str = "",
        extra_points: list[str] | None = None,
        limit: int = 3,
    ) -> list[str]:
        points: list[str] = []
        seen: set[str] = set()
        for raw_point in list(extra_points or []) + list(topic.get("key_points") or []):
            point = _clean_story_text(raw_point)
            lowered = point.lower()
            if not point or _is_generic_prep_text(point) or _is_low_signal_story_summary(point):
                continue
            if summary and lowered == str(summary).strip().lower():
                continue
            if lowered in seen:
                continue
            seen.add(lowered)
            points.append(point)
            if len(points) >= limit:
                break
        return points

    def _section_item_from_topic(
        topic: dict,
        *,
        include_next_move: bool = False,
        extra_points: list[str] | None = None,
    ) -> dict:
        summary = _story_truth_line(topic)
        return {
            "title": _story_topic_heading(topic, summary),
            "summary": summary,
            "why_it_matters": topic.get("why_it_matters") or "",
            "status": topic.get("status") or "",
            "status_label": topic.get("status_label") or "",
            "last_updated_at": topic.get("last_touch_at") or "",
            "last_updated_label": topic.get("last_touch_label") or _brief_date_label(topic.get("last_touch_at")),
            "evidence_anchor": _topic_evidence_anchor(topic),
            "next_move": topic.get("recommended_action") or "" if include_next_move else "",
            "supporting_points": _supporting_story_points(topic, summary=summary, extra_points=extra_points),
            "answer_status": topic.get("answer_status") or "unanswered",
        }

    def _dedupe_section_items(items: list[dict], limit: int = 4) -> list[dict]:
        deduped: list[dict] = []
        seen: set[str] = set()
        for item in items:
            key = "|".join(
                [
                    str(item.get("title") or "").strip().lower(),
                    str(item.get("summary") or "").strip().lower(),
                ]
            )
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _section_summary(prefix: str, items: list[dict], empty_text: str) -> str:
        if not items:
            return empty_text
        points = [str(item.get("summary") or item.get("title") or "").strip() for item in items[:3]]
        points = [point for point in points if point]
        if not points:
            return empty_text
        return f"{prefix} " + "; ".join(points) + "."

    def _is_low_signal_story_summary(text: str | None) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return True
        generic_markers = (
            "an active hiring or search process is being discussed",
            "executive search or hiring activity is live",
            "the interaction contains meaningful personal or rapport-relevant context",
            "the contact is signaling a concrete requirement or priority",
            "the interaction points to door-opening or decision influence around the relationship",
            "the interaction contains process friction or execution risk",
            "relationship trajectory is under_strain",
            "relationship trajectory is under strain",
            "next-week timing is explicitly mentioned",
            "the interaction contains rapport-relevant personal context worth retaining",
        )
        return any(marker in lowered for marker in generic_markers)

    def _manual_event_payloads(topic: dict) -> list[dict]:
        payloads: list[dict] = []
        for event in topic.get("recent_events") or []:
            if not isinstance(event, dict):
                continue
            raw_details = event.get("details_json")
            if not raw_details:
                continue
            try:
                details = json.loads(raw_details) if isinstance(raw_details, str) else raw_details
            except json.JSONDecodeError:
                continue
            if isinstance(details, dict):
                payloads.append(details)
        return payloads

    def _manual_market_business_points(topic: dict) -> list[str]:
        business_keywords = (
            "commercial", "market", "pricing", "competition", "hospital", "project",
            "bim", "data center", "data centres", "data center", "role", "head of data centers",
            "specialist", "filled", "hiring", "search", "client",
        )
        points: list[str] = []
        for payload in _manual_event_payloads(topic):
            analysis = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
            for value in analysis.get("key_points") or []:
                text = str(value or "").strip()
                lowered = text.lower()
                if text and any(keyword in lowered for keyword in business_keywords):
                    points.append(text)
            update_text = str(payload.get("update_text") or "").strip()
            if update_text:
                for sentence in re.split(r"(?<=[.!?])\s+", update_text):
                    text = str(sentence or "").strip(" -")
                    lowered = text.lower()
                    if not text:
                        continue
                    if len(text) < 18:
                        continue
                    if any(keyword in lowered for keyword in business_keywords):
                        points.append(_clip(text, 220))
        return _dedupe_text_list(points, limit=6)

    def _market_point_item(point: str, topic: dict) -> dict:
        summary = _clean_story_text(point)
        return {
            "title": _story_topic_heading(topic, summary),
            "summary": summary,
            "why_it_matters": topic.get("why_it_matters") or "",
            "status": topic.get("status") or "",
            "status_label": topic.get("status_label") or "",
            "last_updated_at": topic.get("last_touch_at") or "",
            "last_updated_label": topic.get("last_touch_label") or _brief_date_label(topic.get("last_touch_at")),
            "evidence_anchor": _topic_evidence_anchor(topic),
            "next_move": "",
            "supporting_points": _supporting_story_points(
                topic,
                summary=summary,
                extra_points=[candidate for candidate in _manual_market_business_points(topic) if candidate != point],
            ),
            "answer_status": topic.get("answer_status") or "unanswered",
        }

    def _personal_fact_group(text: str) -> str:
        lowered = str(text or "").lower()
        if re.search(r"\b(daughter|son|kids|children|wife|husband|family|mother|father|parents|school|birthday)\b", lowered):
            return "family"
        if re.search(r"\b(run|running|race|golf|rugby|football|motorbike|bmw|holiday|travel|thailand|diving|watch|training|gym|cycle|cycling|swim|swimming|hike|hiking)\b", lowered):
            return "interests"
        return "interests"

    def _has_personal_fact_marker(text: str) -> bool:
        lowered = str(text or "").lower()
        if not lowered:
            return False
        if re.search(r"\b(accepted|received email|sent email|in-person|teams meeting|calendar meeting|meeting response)\b", lowered):
            return False
        return bool(
            re.search(r"\b(daughter|son|kids|children|wife|husband|family|mother|father|parents|school|birthday)\b", lowered)
            or re.search(r"\b(run|running|race|golf|rugby|football|motorbike|bmw|holiday|travel|thailand|diving|watch|training|gym|cycle|cycling|swim|swimming|hike|hiking)\b", lowered)
        )

    def _personal_fact_candidates(text: str | None) -> list[str]:
        cleaned = _clean_source_text(text or "")
        if not cleaned:
            return []
        fragments: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", cleaned):
            sentence = str(sentence or "").strip(" -")
            if not sentence:
                continue
            subparts = [sentence]
            if sentence.count(",") >= 1 and len(sentence) > 60:
                subparts = [part.strip(" -") for part in sentence.split(",") if str(part).strip(" -")]
            for part in subparts:
                if part and not _is_courtesy_only_rapport_text(part):
                    fragments.append(_clip(part, 180))
        return fragments[:8]

    def _personal_memory_items() -> tuple[list[dict], list[dict]]:
        candidates: list[dict] = []
        for memory in (promoted_memory or {}).get("enduring_memory") or []:
            if str(memory.get("memory_domain") or "").lower() != "rapport":
                continue
            candidates.append(
                {
                    "text": memory.get("memory_text"),
                    "date": memory.get("interaction_at") or memory.get("updated_at"),
                    "date_label": _brief_date_label(memory.get("interaction_at") or memory.get("updated_at")),
                    "channel": "Retained memory",
                    "priority": 0 if str(memory.get("status") or "").lower() == "approved" else 1,
                }
            )
        for row in interpreted_interactions or []:
            relationship_signals = [str(signal or "").lower() for signal in row.get("relationship_signals") or []]
            source_text = " ".join(
                part
                for part in [
                    row.get("full_evidence_text"),
                    row.get("source_summary"),
                    " ".join(row.get("evidence_snippets") or []),
                ]
                if str(part or "").strip()
            )
            if not source_text:
                continue
            if not (
                any("rapport" in signal or "personal context" in signal for signal in relationship_signals)
                or _is_personal_topic_text(source_text)
            ):
                continue
            candidates.append(
                {
                    "text": source_text,
                    "date": row.get("interaction_at") or row.get("created_at"),
                    "date_label": _brief_date_label(row.get("interaction_at") or row.get("created_at")),
                    "channel": row.get("display_channel") or row.get("channel") or "Interaction",
                    "priority": 2,
                }
            )

        candidates = sorted(
            candidates,
            key=lambda item: (
                int(item.get("priority") or 9),
                -int((_parse_datetime(item.get("date")) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp()),
            ),
        )
        seen: set[str] = set()
        family_items: list[dict] = []
        interests_items: list[dict] = []
        for candidate in candidates:
            for fact in _personal_fact_candidates(candidate.get("text")):
                lowered = fact.lower()
                if not _has_personal_fact_marker(fact):
                    continue
                if lowered in seen:
                    continue
                seen.add(lowered)
                item = {
                    "title": "Personal continuity",
                    "summary": fact,
                    "why_it_matters": "Useful personal continuity for future engagement.",
                    "status": "",
                    "status_label": "Retained",
                    "last_updated_at": candidate.get("date") or "",
                    "last_updated_label": candidate.get("date_label") or "",
                    "evidence_anchor": (
                        f"{candidate.get('date_label') or ''} | {candidate.get('channel') or 'Interaction'} | {fact}"
                    ).strip(" |"),
                    "next_move": "",
                    "answer_status": "retained",
                }
                if _personal_fact_group(fact) == "family":
                    family_items.append(item)
                else:
                    interests_items.append(item)
                if len(family_items) >= 4 and len(interests_items) >= 4:
                    break
            if len(family_items) >= 4 and len(interests_items) >= 4:
                break
        return family_items[:4], interests_items[:4]

    personal_topics = [topic for topic in direct_topics if _is_personal_story_topic(topic)]
    active_topics = [topic for topic in direct_topics if _is_active_story_topic(topic)]
    market_topics = [topic for topic in direct_topics if _is_market_business_story_topic(topic)]
    track_topics = [topic for topic in direct_topics if _is_track_record_story_topic(topic)]

    active_threads = []
    for topic in active_topics[:5]:
        thread = _section_item_from_topic(topic, include_next_move=True)
        thread["current_truth"] = thread["summary"]
        thread["situation_record_id"] = topic.get("situation_record_id")
        active_threads.append(thread)

    resolved_threads = []
    for topic in answered_topics[:4]:
        if str(topic.get("answer_status") or "") == "covered_by_recent_answer":
            continue
        resolved_threads.append(
            {
                "title": _story_topic_heading(topic, _story_truth_line(topic)),
                "outcome": _story_truth_line(topic),
                "why_it_matters": topic.get("why_it_matters") or "",
                "resolution_note": _clean_story_text(topic.get("resolution_note") or ""),
                "last_updated_at": topic.get("last_touch_at") or "",
                "last_updated_label": topic.get("last_touch_label") or _brief_date_label(topic.get("last_touch_at")),
                "status": topic.get("status") or "",
                "answer_status": topic.get("answer_status") or "",
            }
        )
    for item in resolved_situations[:4]:
        resolved_threads.append(
            {
                "title": "Resolved thread",
                "outcome": _clean_story_text(item.get("headline") or item.get("topic") or "Resolved thread"),
                "why_it_matters": item.get("why_it_matters") or "",
                "resolution_note": _clean_story_text(item.get("resolution_note") or ""),
                "last_updated_at": item.get("state_changed_at") or item.get("end_at") or "",
                "last_updated_label": _brief_date_label(item.get("state_changed_at") or item.get("end_at")),
                "status": item.get("tracking_status") or "",
                "answer_status": "resolved",
            }
        )
    resolved_threads = _dedupe_text_list(
        [json.dumps(item, sort_keys=True) for item in resolved_threads],
        limit=5,
    )
    resolved_threads = [json.loads(item) for item in resolved_threads]

    family_personal_items, interests_personal_items = _personal_memory_items()
    fallback_personal_items = _dedupe_section_items([
        _section_item_from_topic(topic)
        for topic in personal_topics
    ], limit=4)
    personal_items = family_personal_items + interests_personal_items
    if not personal_items:
        personal_items = fallback_personal_items
    market_items = _dedupe_section_items(
        [
            _market_point_item(point, topic)
            for topic in market_topics
            for point in _manual_market_business_points(topic)
        ]
        + [
            item
            for item in [
                _section_item_from_topic(topic)
                for topic in market_topics
            ]
            if not _is_low_signal_story_summary(item.get("summary"))
        ],
        limit=6,
    )
    track_items = _dedupe_section_items(
        [
            _section_item_from_topic(topic)
            for topic in track_topics
        ]
        + [
            {
                "title": item.get("title"),
                "summary": item.get("outcome") or item.get("title"),
                "why_it_matters": item.get("why_it_matters") or "",
                "status": item.get("status") or "",
                "status_label": item.get("status") or "",
                "last_updated_at": item.get("last_updated_at") or "",
                "last_updated_label": item.get("last_updated_label") or "",
                "evidence_anchor": "",
                "next_move": "",
                "supporting_points": _dedupe_text_list(
                    [
                        _clean_story_text(item.get("resolution_note") or ""),
                        _clean_story_text(item.get("why_it_matters") or ""),
                    ],
                    limit=2,
                ),
                "answer_status": item.get("answer_status") or "",
                "resolution_note": item.get("resolution_note") or "",
            }
            for item in resolved_threads
            if item.get("resolution_note")
            or _is_track_record_topic_text(item.get("outcome"))
            or str(item.get("status") or "").lower() in {"closed", "transitioned"}
        ],
        limit=5,
    )

    next_moves = _dedupe_text_list(
        [
            str(topic.get("recommended_action") or "").strip()
            for topic in active_topics
            if str(topic.get("recommended_action") or "").strip()
            and not _is_generic_prep_text(topic.get("recommended_action"))
        ],
        limit=4,
    )

    evidence_trail = []
    seen_evidence: set[str] = set()
    evidence_topics = active_topics[:4] or market_topics[:3] or track_topics[:3]
    for topic in evidence_topics:
        for detail in topic.get("evidence_details") or []:
            if not isinstance(detail, dict):
                continue
            preview = str(detail.get("preview") or "").strip()
            if not preview:
                continue
            key = f"{detail.get('interaction_at')}|{preview.lower()}"
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            evidence_trail.append(
                {
                    "date_label": detail.get("date_label") or _brief_date_label(detail.get("interaction_at")),
                    "channel": detail.get("channel") or "Interaction",
                    "preview": preview,
                    "related_topic": _story_topic_heading(topic, _story_truth_line(topic)),
                }
            )
            if len(evidence_trail) >= 6:
                break
        if len(evidence_trail) >= 6:
            break
    if len(evidence_trail) < 4:
        for evidence_row in recent_evidence or []:
            preview = _best_evidence_preview(
                summary=evidence_row.get("summary"),
                raw_text=evidence_row.get("raw_text"),
            )
            if not preview:
                continue
            key = f"{evidence_row.get('interaction_at')}|{preview.lower()}"
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            evidence_trail.append(
                {
                    "date_label": _brief_date_label(evidence_row.get("interaction_at")),
                    "channel": evidence_row.get("channel") or "Interaction",
                    "preview": preview,
                    "related_topic": "",
                }
            )
            if len(evidence_trail) >= 6:
                break

    open_question_titles = [str(item.get("title") or "").strip() for item in open_questions if str(item.get("title") or "").strip()]
    if active_threads:
        current_story = f"{name}'s current story centers on " + ", ".join(
            [str(item.get("current_truth") or item.get("title") or "").strip() for item in active_threads[:3] if str(item.get("current_truth") or item.get("title") or "").strip()]
        ) + "."
    elif market_items:
        current_story = f"{name}'s main retained story currently sits in market and business context: " + "; ".join(
            [str(item.get("summary") or item.get("title") or "").strip() for item in market_items[:2] if str(item.get("summary") or item.get("title") or "").strip()]
        ) + "."
    elif resolved_threads:
        current_story = f"{name}'s recent story is currently resolved, with the latest retained truth captured in resolved threads."
    else:
        current_story = f"No clear relationship story has been retained for {name} yet."

    if open_questions:
        current_story += f" There {'is' if len(open_questions) == 1 else 'are'} {len(open_questions)} open clarification question"
        current_story += "" if len(open_questions) == 1 else "s"
        if open_question_titles:
            current_story += f", led by {open_question_titles[0]}."
        else:
            current_story += "."
    elif next_moves:
        current_story += f" The next move is {next_moves[0]}."

    relationship_memory = _dedupe_text_list(
        [str(item.get("summary") or item.get("title") or "").strip() for item in personal_items],
        limit=8,
    )

    sections = {
        "personal": {
            "label": "Personal",
            "summary": _section_summary(
                f"Retained personal continuity for {name} includes",
                personal_items,
                f"No meaningful personal continuity has been retained for {name} yet.",
            ),
            "items": personal_items,
            "count": len(personal_items),
            "groups": [
                {
                    "label": "Family",
                    "summary": _section_summary(
                        f"Retained family continuity for {name} includes",
                        family_personal_items,
                        f"No family continuity has been retained for {name} yet.",
                    ),
                    "items": family_personal_items,
                    "count": len(family_personal_items),
                },
                {
                    "label": "Interests & Life",
                    "summary": _section_summary(
                        f"Retained interests and life continuity for {name} includes",
                        interests_personal_items,
                        f"No interests or life continuity has been retained for {name} yet.",
                    ),
                    "items": interests_personal_items,
                    "count": len(interests_personal_items),
                },
            ],
        },
        "active": {
            "label": "Active",
            "summary": _section_summary(
                f"Current live threads with {name} are",
                active_threads,
                (
                    f"No confirmed live relationship threads are currently retained for {name}."
                    if not open_questions
                    else f"No confirmed live relationship threads are currently retained for {name}; clarification is still needed."
                ),
            ),
            "items": active_threads[:5],
            "count": len(active_threads),
        },
        "market_business": {
            "label": "Market & Business",
            "summary": _section_summary(
                f"The current market and business read on {name} is",
                market_items,
                f"No business or market view is currently retained for {name}.",
            ),
            "items": market_items,
            "count": len(market_items),
        },
        "track_record": {
            "label": "Track Record",
            "summary": _section_summary(
                f"Track record retained for {name} includes",
                track_items,
                f"No track record outcomes are currently retained for {name}.",
            ),
            "items": track_items,
            "count": len(track_items),
        },
    }

    return {
        "summary": current_story,
        "current_story": current_story,
        "active_thread_count": len(active_threads),
        "resolved_thread_count": len(resolved_threads),
        "open_question_count": len(open_questions),
        "current_truth": [item.get("current_truth") for item in active_threads[:4] if item.get("current_truth")],
        "active_threads": active_threads,
        "resolved_threads": resolved_threads,
        "open_questions": [
            {
                "title": item.get("title"),
                "question": item.get("question"),
                "status": item.get("status"),
                "answer_status": item.get("answer_status") or "unanswered",
            }
            for item in open_questions[:5]
        ],
        "next_recommended_moves": next_moves,
        "relationship_memory": relationship_memory,
        "evidence_trail": evidence_trail,
        "sections": sections,
        "query_examples": [
            f"What personal context should I remember about {name}?",
            f"What is currently active with {name}?",
            f"What are {name}'s market or business concerns?",
            f"What has gone well or badly with {name} historically?",
            f"What should I do next with {name}?",
        ],
    }


def build_conversation_prep(
    *,
    person: dict,
    interpreted_interactions: list[dict],
    tracked_situations: list[dict],
    recent_evidence: list[dict],
    person_opportunities: list[dict],
    company_opportunities: list[dict],
    relevant_interaction_count: int = 0,
    related_team_context: dict | None = None,
    relationship_topics: dict | None = None,
    relationship_story: dict | None = None,
) -> dict:
    name = str(person.get("full_name") or "this contact")
    useful_situations = sorted(
        [item for item in tracked_situations if _is_useful_prep_situation(item)],
        key=lambda item: (
            _situation_status_sort_value(item.get("tracking_status")),
            -int(item.get("confidence_score") or 0),
            -int((_parse_datetime(item.get("end_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp()),
        ),
        reverse=False,
    )
    live_threads = [_shape_prep_thread(item) for item in useful_situations[:4]]

    interpreted_by_source = {
        str(item.get("source_interaction_id") or ""): item
        for item in interpreted_interactions
        if item.get("source_interaction_id")
    }
    recent_shifts = []
    seen_shift_keys: set[str] = set()
    for evidence_row in recent_evidence:
        preview = _best_evidence_preview(
            summary=evidence_row.get("summary"),
            raw_text=evidence_row.get("raw_text"),
        )
        if not preview:
            continue
        interpreted = interpreted_by_source.get(str(evidence_row.get("interaction_id") or ""))
        shift_text = str(interpreted.get("what_is_happening") or "").strip() if interpreted else ""
        topic_label = _brief_topic_label(preview or shift_text)
        if _is_generic_prep_text(topic_label):
            continue
        if _is_courtesy_only_rapport_text(preview) and not _has_real_rapport_marker(preview.lower()):
            continue
        if _is_generic_prep_text(shift_text):
            shift_text = topic_label
        detail_text = str(interpreted.get("why_it_matters") or "").strip() if interpreted else ""
        if _is_generic_prep_text(detail_text) or detail_text == shift_text:
            detail_text = ""
        if not detail_text and preview and topic_label != preview:
            detail_text = preview
        key = f"{shift_text.lower()}|{preview.lower()}"
        if key in seen_shift_keys:
            continue
        seen_shift_keys.add(key)
        recent_shifts.append(
            {
                "interaction_at": evidence_row.get("interaction_at"),
                "interaction_label": _brief_date_label(evidence_row.get("interaction_at")),
                "channel": evidence_row.get("channel") or "Interaction",
                "summary": shift_text,
                "detail": detail_text,
                "evidence": preview,
            }
        )
        if len(recent_shifts) >= 4:
            break

    open_person_opportunities = [item for item in person_opportunities if str(item.get("status") or "").lower() == "open"]
    open_company_opportunities = [item for item in company_opportunities if str(item.get("status") or "").lower() == "open"]
    person_opp_label = "opportunity" if len(open_person_opportunities) == 1 else "opportunities"
    company_opp_label = "opportunity" if len(open_company_opportunities) == 1 else "opportunities"

    latest_shift = recent_shifts[0] if recent_shifts else None

    relationship_context = [
        f"Last relevant contact: {(latest_shift['interaction_label'] + ' via ' + latest_shift['channel']) if latest_shift else 'No recent live-window interaction is currently surfaced.'}",
        (
            f"Working picture: {len(live_threads)} live thread"
            f"{'' if len(live_threads) == 1 else 's'}, "
            f"{len(open_person_opportunities)} open person {person_opp_label}, "
            f"and {len(open_company_opportunities)} open company {company_opp_label}."
        ),
        (
            f"Coverage in live window: {relevant_interaction_count or len(recent_evidence)} relevant interaction"
            f"{'' if (relevant_interaction_count or len(recent_evidence)) == 1 else 's'} "
            f"and {len(interpreted_interactions)} interpreted item"
            f"{'' if len(interpreted_interactions) == 1 else 's'}."
        ),
    ]
    metadata_parts = [
        str(person.get("contact_value") or "").strip(),
        str(person.get("cat") or "").strip(),
        f"Owner {person.get('relationship_owner')}" if person.get("relationship_owner") else "Owner not set",
    ]
    relationship_context.append("Relationship metadata: " + " | ".join(part for part in metadata_parts if part))
    if related_team_context and int(related_team_context.get("thread_count") or 0) > 0:
        relationship_context.append(
            f"Related company context: {related_team_context.get('thread_count')} separately attributed team thread"
            f"{'' if int(related_team_context.get('thread_count') or 0) == 1 else 's'} across "
            f"{related_team_context.get('contact_count')} other contact"
            f"{'' if int(related_team_context.get('contact_count') or 0) == 1 else 's'}."
        )

    topic_candidates: list[str] = []
    for item in recent_shifts:
        label = _brief_topic_label(str(item.get("evidence") or item.get("summary") or ""))
        if not _is_generic_prep_text(label):
            topic_candidates.append(label)
    for thread in live_threads:
        if thread.get("evidence"):
            label = _brief_topic_label(thread["evidence"][0])
        elif thread.get("headline"):
            label = _brief_topic_label(str(thread["headline"]))
        else:
            label = ""
        if label and not _is_generic_prep_text(label):
            topic_candidates.append(label)
    for item in open_person_opportunities[:2]:
        label = _brief_topic_label(
            f"{item.get('opportunity_type') or 'Opportunity'} at {item.get('stage') or 'open stage'}"
            + (f" ({item.get('notes')})" if item.get("notes") else "")
        )
        if not _is_generic_prep_text(label):
            topic_candidates.append(label)
    if relationship_topics:
        topic_candidates = (
            topic_candidates
            + [item.get("title") for item in relationship_topics.get("active_topics") or []]
            + [item.get("title") for item in relationship_topics.get("market_business_view") or []]
        )
    topics_to_cover = _dedupe_brief_topics(
        [item for item in topic_candidates if not _is_generic_prep_text(item)],
        limit=5,
    )

    top_focus = topics_to_cover[:2] or [thread["headline"] for thread in live_threads[:2]]
    if latest_shift:
        summary = (
            f"Current prep for {name} centers on "
            f"{', '.join(top_focus) if top_focus else 'the latest live relationship threads'}. "
            f"The latest visible move was on {latest_shift['interaction_label']}."
        )
    elif top_focus:
        summary = f"Current prep for {name} centers on {', '.join(top_focus)}."
    else:
        summary = f"No briefing-grade conversation prep is ready for {name} yet."

    follow_up_to_lock = _dedupe_text_list(
        [
            thread.get("recommended_action") or ""
            for thread in live_threads
            if thread.get("recommended_action") and not _is_generic_prep_text(thread.get("recommended_action"))
        ],
        limit=4,
    )

    if relationship_topics and relationship_topics.get("personal_continuity"):
        rapport_points = _dedupe_text_list(
            [item.get("title") for item in relationship_topics.get("personal_continuity") or []],
            limit=4,
        )
    else:
        rapport_points = _dedupe_text_list(
            [
                signal
                for item in interpreted_interactions
                for signal in item.get("relationship_signals") or []
                if "rapport" in str(signal).lower() or "personal context" in str(signal).lower()
            ],
            limit=3,
        )

    return {
        "summary": summary,
        "relevant_interaction_count": int(relevant_interaction_count or len(recent_evidence)),
        "interpreted_count": len(interpreted_interactions),
        "live_thread_count": len(live_threads),
        "open_person_opportunity_count": len(open_person_opportunities),
        "open_company_opportunity_count": len(open_company_opportunities),
        "relationship_context": relationship_context,
        "relationship_story_summary": str((relationship_story or {}).get("summary") or "").strip(),
        "topics_to_cover": topics_to_cover,
        "follow_up_to_lock": follow_up_to_lock,
        "rapport_points": rapport_points,
        "live_threads": live_threads,
        "recent_shifts": recent_shifts,
        "personal_continuity": (relationship_topics or {}).get("personal_continuity") or [],
        "market_business_view": (relationship_topics or {}).get("market_business_view") or [],
        "track_record": (relationship_topics or {}).get("track_record") or [],
        "clarification_prompts": (relationship_topics or {}).get("clarification_prompts") or [],
    }


async def load_related_team_context(
    *,
    person_id: str,
    company_name_raw: str | None,
    limit_contacts: int = 4,
    situations_per_contact: int = 2,
) -> dict:
    company_name = str(company_name_raw or "").strip()
    if not company_name:
        return {
            "company_name_raw": "",
            "summary": "No company context is available for this profile yet.",
            "contact_count": 0,
            "thread_count": 0,
            "threads": [],
        }

    async def _read_contacts(db):
        async with db.execute(
            """
            SELECT person_id, full_name, title_current, relationship_owner, company_name_raw,
                   last_contact_datetime, last_updated_at, created_at
            FROM PERSON
            WHERE is_active = 1
              AND person_id != ?
              AND LOWER(TRIM(company_name_raw)) = LOWER(TRIM(?))
            ORDER BY datetime(COALESCE(last_contact_datetime, last_updated_at, created_at)) DESC, full_name ASC
            LIMIT ?
            """,
            (person_id, company_name, limit_contacts),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    contacts = await run_read(_read_contacts, label="load related company contacts")
    if not contacts:
        return {
            "company_name_raw": company_name,
            "summary": f"No other live-window {company_name} contact context is currently visible.",
            "contact_count": 0,
            "thread_count": 0,
            "threads": [],
        }

    threads: list[dict] = []
    for contact in contacts:
        await refresh_interpreted_interactions_for_person(contact["person_id"], limit=12)
        contact_interpreted = await load_interpreted_interactions(contact["person_id"], limit=12)
        if contact_interpreted:
            storyline = build_storyline_state(contact_interpreted)
            await sync_relationship_situations_for_person(
                contact["person_id"],
                storyline.get("storyline_groups", []),
                relationship_owner=contact.get("relationship_owner"),
                company_name_raw=contact.get("company_name_raw"),
            )
        situations = await load_relationship_situations_for_person(contact["person_id"], limit=situations_per_contact + 2)
        useful_situations = [item for item in situations if _is_useful_prep_situation(item)]
        for item in useful_situations[:situations_per_contact]:
            evidence = _dedupe_text_list(
                [
                    _best_evidence_preview(
                        summary=entry.get("full_evidence_text"),
                        evidence_snippets=entry.get("evidence_snippets") or [],
                    )
                    for entry in item.get("supporting_entries") or []
                ],
                limit=2,
            )
            threads.append(
                {
                    "person_id": contact.get("person_id"),
                    "full_name": contact.get("full_name"),
                    "title_current": contact.get("title_current"),
                    "relationship_owner": contact.get("relationship_owner"),
                    "attribution": f"With {contact.get('full_name')} at {contact.get('company_name_raw')}",
                    "headline": _brief_topic_label((evidence[0] if evidence else item.get("headline")) or item.get("topic") or "Related team thread"),
                    "current_read": item.get("headline") or item.get("topic") or "Related team thread",
                    "why_it_matters": item.get("why_it_matters") or "",
                    "topic_type": item.get("topic_type") or "relationship",
                    "topic_type_label": item.get("topic_type_label") or _story_topic_type_label(item.get("topic_type") or "relationship"),
                    "stage": item.get("stage") or "Relationship Update",
                    "momentum": item.get("momentum") or "steady",
                    "tracking_status": item.get("tracking_status") or "watching",
                    "tracking_status_label": item.get("tracking_status_label") or _relationship_situation_status_label(item.get("tracking_status") or "watching"),
                    "window_label": item.get("window_label") or "",
                    "channels": item.get("channels") or [],
                    "key_points": _dedupe_text_list(item.get("key_points") or [], limit=3),
                    "evidence": evidence,
                    "recommended_action": item.get("recommended_action") or "",
                    "profile_path": f"/network-lab/profile/{contact.get('person_id')}",
                    "last_touch_at": item.get("end_at"),
                }
            )

    threads = sorted(
        threads,
        key=lambda item: (
            _situation_status_sort_value(item.get("tracking_status")),
            0 if item.get("topic_type") == "opportunity" else 1,
            -int((_parse_datetime(item.get("last_touch_at")) or datetime(1970, 1, 1, tzinfo=timezone.utc)).timestamp()),
        ),
    )[:8]

    if not threads:
        summary = f"Other {company_name} contacts exist, but no clean separately attributed team threads are ready to brief from yet."
    else:
        summary = (
            f"{len(threads)} separately attributed team thread"
            f"{'' if len(threads) == 1 else 's'} are currently visible across "
            f"{len({item['person_id'] for item in threads})} other {company_name} contact"
            f"{'' if len({item['person_id'] for item in threads}) == 1 else 's'}. "
            f"These inform the account picture without being stored as this person's personal memory."
        )

    return {
        "company_name_raw": company_name,
        "summary": summary,
        "contact_count": len({item["person_id"] for item in threads}),
        "thread_count": len(threads),
        "threads": threads,
    }
