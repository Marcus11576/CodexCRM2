"""
Standalone transcript intelligence service.
Reusable outside the CRM for transcript-to-summary and sectioned intelligence extraction.
"""
from __future__ import annotations

from typing import Optional

from backend.config import settings
from backend.services.ai_foundation import (
    BUSINESS_SUBTOPIC_LABELS,
    BUSINESS_SUBTOPICS,
    canonical_business_subtopic,
    normalize_signal_text,
    strip_speculative_filler,
)
from backend.services.benchmark_corpus import select_style_examples
from backend.services.ai_runtime import run_json_chat_task


DEFAULT_SECTION_SCHEMA = [
    {"id": "business_focus", "label": "Business Focus"},
    {"id": "recruitment_talent", "label": "Recruitment & Talent"},
    {"id": "family_personal", "label": "Family & Personal"},
    {"id": "obe_focus", "label": "OBE Focus"},
]


def _slugify_section(label: str) -> str:
    cleaned = normalize_signal_text(label).lower()
    if not cleaned:
        return ""
    return "_".join(part for part in cleaned.replace("&", " and ").split() if part)


def _build_section_schema(custom_sections: Optional[list[str]] = None) -> list[dict]:
    labels = [normalize_signal_text(item) for item in (custom_sections or []) if normalize_signal_text(item)]
    if not labels:
        return [dict(item) for item in DEFAULT_SECTION_SCHEMA]
    schema = []
    seen = set()
    for label in labels:
        section_id = _slugify_section(label)
        if not section_id or section_id in seen:
            continue
        schema.append({"id": section_id, "label": label})
        seen.add(section_id)
    return schema or [dict(item) for item in DEFAULT_SECTION_SCHEMA]


def _format_examples(examples: list[dict], section_schema: list[dict]) -> str:
    if not examples:
        return "No style examples were provided."
    rendered = []
    for idx, example in enumerate(examples[:8], start=1):
        transcript = normalize_signal_text((example or {}).get("transcript"))[:3500]
        preferred_summary = normalize_signal_text((example or {}).get("preferred_summary"))[:1800]
        preferred_sections = (example or {}).get("preferred_sections") or {}
        title = normalize_signal_text((example or {}).get("title"))
        notes = [
            normalize_signal_text(note)
            for note in ((example or {}).get("notes") or [])
            if normalize_signal_text(note)
        ][:8]
        lines = [f"EXAMPLE {idx}"]
        if title:
            lines.append(f"Title: {title}")
        if transcript:
            lines.append(f"Transcript:\n{transcript}")
        if preferred_summary:
            lines.append(f"Preferred summary:\n{preferred_summary}")
        if isinstance(preferred_sections, dict) and preferred_sections:
            lines.append("Preferred section treatment:")
            for section in section_schema:
                section_text = normalize_signal_text(
                    preferred_sections.get(section["id"]) or preferred_sections.get(section["label"])
                )
                if section_text:
                    lines.append(f"- {section['label']}: {section_text}")
        if notes:
            lines.append("Notes:")
            for note in notes:
                lines.append(f"- {note}")
        rendered.append("\n".join(lines))
    return "\n\n".join(rendered)


def _build_prompt(
    *,
    transcript: str,
    title: Optional[str],
    source_type: str,
    guidance: Optional[str],
    section_schema: list[dict],
    examples: list[dict],
    max_points_per_section: int,
) -> str:
    section_lines = "\n".join(f"- {item['id']}: {item['label']}" for item in section_schema)
    examples_block = _format_examples(examples, section_schema)
    business_subtopic_lines = "\n".join(
        f"  - {key}: {label}" for key, label in BUSINESS_SUBTOPIC_LABELS.items()
    )
    title_line = normalize_signal_text(title)
    guidance_line = normalize_signal_text(guidance)
    return f"""You are a high-judgement transcript intelligence system.

Your job is to turn messy real-world discussion into briefing-grade intelligence.

Rules:
- Preserve factual meaning and commercially relevant nuance.
- Remove fluff, repetition, banter, profanity-led chatter, and throwaway lines unless they are genuinely useful for future briefing or rapport.
- Multiple topics may exist in one transcript. Separate them cleanly.
- Do not force content into a section if it does not belong there.
- If something is useful but does not fit a configured section, put it in other_topics.
- If something is not useful, put it in omitted_content with a short reason.
- Keep section summaries in natural prose, not clipped fragments.
- Section summaries should retain the decision logic, caveats, and consequences when that substance matters for briefing.
- For business content, preserve the framework of the argument, not just the headline conclusion.
- Evidence snippets should preserve the most relevant source wording without dumping the entire transcript.
- Never invent facts, commitments, motives, dates, or hiring signals.
- Do not use speculative softeners such as "could be a rapport-building point", "may suggest", or similar filler.

Configured sections:
{section_lines}

Business Focus subtopics:
{business_subtopic_lines}

Style examples:
{examples_block}

Request context:
- Title: {title_line or "Untitled transcript"}
- Source type: {source_type}
- Additional guidance: {guidance_line or "None"}
- Max points per section: {max_points_per_section}

Transcript:
\"\"\"{transcript[:16000]}\"\"\"

Return JSON with these exact keys:
- executive_summary: concise narrative summary of the useful substance
- sections: array of objects with:
    - id
    - label
    - summary
    - points: array of objects with:
        - text
        - evidence
        - speaker
        - subtopic
        - confidence
    - confidence
- other_topics: array of objects with:
    - label
    - summary
    - points
- omitted_content: array of objects with:
    - text
    - reason

Requirements:
- Use the configured section ids exactly when content belongs in one of them.
- A point should appear once only.
- Keep no more than {max_points_per_section} points in any one section.
- If a section has no useful content, return it with an empty summary and empty points array.
- For points inside Business Focus, set subtopic to one of: {", ".join(BUSINESS_SUBTOPICS)}.
- For points outside Business Focus, set subtopic to an empty string.
- Confidence values must be numbers between 0 and 1.
- Return valid JSON only.
"""


def _clean_points(points: list, *, max_points: int) -> list[dict]:
    cleaned = []
    seen = set()
    for point in points or []:
        if not isinstance(point, dict):
            continue
        text = normalize_signal_text(point.get("text"))
        evidence = normalize_signal_text(point.get("evidence"))
        speaker = normalize_signal_text(point.get("speaker"))
        subtopic = canonical_business_subtopic(point.get("subtopic"))
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            confidence = float(point.get("confidence", 0.6))
        except Exception:
            confidence = 0.6
        cleaned.append(
            {
                "text": text,
                "evidence": strip_speculative_filler(evidence),
                "speaker": speaker,
                "subtopic": subtopic or "",
                "confidence": round(max(min(confidence, 1.0), 0.0), 3),
            }
        )
        if len(cleaned) >= max_points:
            break
    return cleaned


def _normalize_response(payload: dict, section_schema: list[dict], *, max_points_per_section: int) -> dict:
    raw_sections = payload.get("sections") or []
    raw_lookup = {}
    if isinstance(raw_sections, list):
        for item in raw_sections:
            if not isinstance(item, dict):
                continue
            item_id = _slugify_section(item.get("id") or item.get("label") or "")
            if item_id:
                raw_lookup[item_id] = item
    sections = []
    for section in section_schema:
        raw = raw_lookup.get(section["id"], {})
        try:
            confidence = float(raw.get("confidence", 0.0))
        except Exception:
            confidence = 0.0
        sections.append(
            {
                "id": section["id"],
                "label": section["label"],
                "summary": strip_speculative_filler(raw.get("summary")),
                "points": _clean_points(raw.get("points") or [], max_points=max_points_per_section),
                "confidence": round(max(min(confidence, 1.0), 0.0), 3),
            }
        )

    other_topics = []
    for item in payload.get("other_topics") or []:
        if not isinstance(item, dict):
            continue
        label = normalize_signal_text(item.get("label"))
        summary = normalize_signal_text(item.get("summary"))
        points = _clean_points(item.get("points") or [], max_points=max_points_per_section)
        if not label and not summary and not points:
            continue
        other_topics.append(
            {
                "label": label or "Other",
                "summary": strip_speculative_filler(summary),
                "points": points,
            }
        )

    omitted_content = []
    for item in payload.get("omitted_content") or []:
        if not isinstance(item, dict):
            continue
        text = normalize_signal_text(item.get("text"))
        reason = normalize_signal_text(item.get("reason"))
        if not text and not reason:
            continue
        omitted_content.append({"text": strip_speculative_filler(text), "reason": reason})

    return {
        "executive_summary": strip_speculative_filler(payload.get("executive_summary")),
        "sections": sections,
        "other_topics": other_topics,
        "omitted_content": omitted_content,
    }


async def summarize_transcript_intelligence(
    *,
    transcript: str,
    title: Optional[str] = None,
    source_type: str = "transcript",
    guidance: Optional[str] = None,
    custom_sections: Optional[list[str]] = None,
    examples: Optional[list[dict]] = None,
    max_points_per_section: int = 4,
) -> dict:
    section_schema = _build_section_schema(custom_sections)
    selected_examples = list(examples or [])
    if len(selected_examples) < 4:
        selected_examples.extend(
            select_style_examples(
                transcript,
                source_type=normalize_signal_text(source_type) or "transcript",
                max_examples=max(0, 4 - len(selected_examples)),
            )
        )
    prompt = _build_prompt(
        transcript=transcript,
        title=title,
        source_type=normalize_signal_text(source_type) or "transcript",
        guidance=guidance,
        section_schema=section_schema,
        examples=selected_examples,
        max_points_per_section=max(1, min(int(max_points_per_section or 4), 8)),
    )
    data, run_id = await run_json_chat_task(
        task_type="standalone_transcript_summary",
        prompt_family="standalone_transcript_intelligence_v2",
        messages=[
            {
                "role": "system",
                "content": "You are a precise transcript intelligence engine. Return only valid JSON and never invent facts.",
            },
            {"role": "user", "content": prompt},
        ],
        model=settings.STANDALONE_TOOL_MODEL,
        temperature=0.2,
        metadata={
            "source_type": source_type,
            "custom_section_count": len(custom_sections or []),
            "example_count": len(selected_examples),
        },
    )
    normalized = _normalize_response(
        data,
        section_schema,
        max_points_per_section=max(1, min(int(max_points_per_section or 4), 8)),
    )
    normalized["run_id"] = run_id
    normalized["metadata"] = {
        "source_type": normalize_signal_text(source_type) or "transcript",
        "section_schema": section_schema,
        "prompt_family": "standalone_transcript_intelligence_v2",
        "model": settings.STANDALONE_TOOL_MODEL,
        "example_count": len(selected_examples),
    }
    return normalized
