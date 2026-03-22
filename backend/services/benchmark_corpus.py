"""
Benchmark corpus helpers for transcript-style intelligence extraction.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from backend.services.ai_foundation import normalize_signal_text


CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "ai"
    / "benchmark_corpus"
    / "autorecovery_save_of_document2.json"
)

_STOPWORDS = {
    "the", "and", "that", "with", "from", "this", "have", "will", "would", "there", "their", "about",
    "into", "your", "just", "been", "they", "them", "what", "when", "where", "which", "while", "were",
    "more", "than", "then", "also", "only", "each", "such", "very", "some", "much", "many", "does",
    "dont", "can't", "cant", "should", "could", "because", "discussion", "conversation", "meeting",
    "project", "projects",
}


def _truncate(text: str, limit: int) -> str:
    cleaned = normalize_signal_text(text)
    if len(cleaned) <= limit:
        return cleaned
    sentence_break = cleaned.rfind(". ", 0, limit)
    if sentence_break >= int(limit * 0.6):
        return cleaned[: sentence_break + 1].strip()
    word_break = cleaned.rfind(" ", 0, limit)
    if word_break >= int(limit * 0.6):
        return cleaned[:word_break].strip()
    return cleaned[:limit].rstrip()


def _keyword_tokens(text: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[A-Za-z][A-Za-z&/-]{2,}", text or ""):
        lowered = token.lower()
        if lowered in _STOPWORDS:
            continue
        tokens.append(lowered)
        if lowered.endswith("s") and len(lowered) > 4:
            tokens.append(lowered[:-1])
    deduped = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped[:18]


def _score_example(example: dict, keywords: list[str], source_type: str) -> tuple[int, int]:
    haystack = " ".join(
        normalize_signal_text(part)
        for part in (
            example.get("title"),
            example.get("preferred_summary"),
            " ".join(example.get("summary_bullets") or []),
            example.get("transcript"),
        )
        if normalize_signal_text(part)
    ).lower()
    score = sum(3 for keyword in keywords if keyword in haystack)
    if source_type and source_type in haystack:
        score += 2
    return score, len(haystack)


def _compact_example(example: dict) -> dict:
    notes = [
        _truncate(note, 220)
        for note in (example.get("summary_bullets") or [])
        if normalize_signal_text(note)
    ][:4]
    preferred_sections = {}
    for section in example.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = normalize_signal_text(section.get("heading"))
        content = _truncate(section.get("content") or "", 900)
        if heading and content:
            preferred_sections[heading] = content
    return {
        "title": normalize_signal_text(example.get("title")) or "Benchmark Example",
        "transcript": _truncate(example.get("transcript") or "", 1600),
        "preferred_summary": _truncate(example.get("preferred_summary") or "", 1800),
        "preferred_sections": preferred_sections,
        "notes": notes,
    }


@lru_cache(maxsize=1)
def load_benchmark_corpus() -> list[dict]:
    try:
        payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    examples = []
    for raw in payload if isinstance(payload, list) else []:
        if not isinstance(raw, dict):
            continue
        transcript = normalize_signal_text(raw.get("transcript"))
        preferred_summary = normalize_signal_text(raw.get("preferred_summary"))
        if not transcript or not preferred_summary:
            continue
        examples.append(raw)
    return examples


def select_style_examples(query_text: str, *, source_type: str = "transcript", max_examples: int = 3) -> list[dict]:
    corpus = load_benchmark_corpus()
    if not corpus or max_examples <= 0:
        return []
    keywords = _keyword_tokens(query_text)
    ranked = sorted(
        corpus,
        key=lambda example: _score_example(example, keywords, source_type.lower()),
        reverse=True,
    )
    chosen = []
    seen_titles = set()
    for example in ranked:
        compact = _compact_example(example)
        title_key = compact["title"].lower()
        if title_key in seen_titles:
            continue
        chosen.append(compact)
        seen_titles.add(title_key)
        if len(chosen) >= max_examples:
            break
    return chosen
