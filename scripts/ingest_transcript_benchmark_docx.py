"""
Ingest a Word document containing transcript runs followed by summary blocks
into a reusable benchmark JSON corpus for the standalone transcript tool.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _normalize(text: str) -> str:
    text = (text or "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _paragraphs_from_docx(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for paragraph in root.findall(".//w:body/w:p", NS):
        parts = [node.text or "" for node in paragraph.findall(".//w:t", NS)]
        text = _normalize("".join(parts))
        if text:
            paragraphs.append(text)
    return paragraphs


def _is_timecode(text: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{2}:)?\d{2}:\d{2}(?::\d{2})?", text or ""))


def _looks_like_summary_bullet(text: str) -> bool:
    if not text or len(text) > 260:
        return False
    if text in {"Notes", "Overview", "Action items"}:
        return False
    if _is_timecode(text) or text == "1×":
        return False
    return bool(re.match(r"^[A-Z][^:]{2,80}:\s+\S", text))


def _looks_like_section_heading(text: str) -> bool:
    if not text or len(text) > 140:
        return False
    if text in {"Notes", "Overview", "Action items"}:
        return False
    if ":" in text:
        return False
    if text.endswith((".", "?", "!", ",")):
        return False
    if not re.fullmatch(r"[A-Za-z0-9&()'’/\- ]+", text):
        return False
    if re.search(r"\(\d{1,2}:\d{2}", text):
        return True
    words = text.split()
    if not (2 <= len(words) <= 8 and text[:1].isupper()):
        return False
    alpha_words = [word for word in words if re.search(r"[A-Za-z]", word)]
    titled = [word for word in alpha_words if word[:1].isupper()]
    return len(titled) >= max(2, len(alpha_words) - 1)


def _looks_like_speaker_label(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    if _is_timecode(text) or text == "1×":
        return False
    if re.match(r"^[A-Z][A-Za-z .'\-|&]+:\s*\d", text):
        return True
    return bool(re.match(r"^[A-Z][A-Za-z .,'|&()/-]{2,80}:\s*$", text))


def _looks_like_transcript_line(text: str) -> bool:
    if not text:
        return False
    if _looks_like_summary_bullet(text) or _looks_like_section_heading(text):
        return False
    if _is_timecode(text) or text == "1×":
        return True
    if _looks_like_speaker_label(text):
        return True
    if re.match(r"^[A-Z][a-z]+ [A-Z][a-z]+: \d{1,2}:\d{2}$", text):
        return True
    return False


def _looks_like_dialogue_fragment(text: str) -> bool:
    if not text or _looks_like_summary_bullet(text) or _looks_like_section_heading(text):
        return False
    lowered = text.lower().strip()
    starters = (
        "yeah", "okay", "ok", "lovely", "thanks", "thank you", "bye", "cheers",
        "great", "all right", "alright", "no problem", "sounds good", "exactly",
        "correct", "absolutely", "interesting", "cool", "fantastic",
    )
    if lowered.startswith(starters) and len(text) <= 120:
        return True
    if len(text) <= 90 and ("?" in text or lowered.endswith("right.") or lowered.endswith("okay.")):
        return True
    return False


def _is_transcript_run(paragraphs: list[str], index: int) -> bool:
    window = paragraphs[index:index + 6]
    transcriptish = 0
    for item in window:
        if _looks_like_transcript_line(item) or _looks_like_dialogue_fragment(item):
            transcriptish += 1
    return transcriptish >= 3


def _preceding_dialogue_density(paragraphs: list[str], index: int, window: int = 8) -> int:
    score = 0
    start = max(0, index - window)
    for item in paragraphs[start:index]:
        if _is_timecode(item) or item == "1×" or _looks_like_speaker_label(item):
            score += 2
        elif _looks_like_dialogue_fragment(item):
            score += 1
    return score


def _find_unmarked_summary_starts(paragraphs: list[str], reserved_indexes: set[int]) -> list[int]:
    starts: list[int] = []
    for index, text in enumerate(paragraphs):
        if index in reserved_indexes:
            continue
        if not _looks_like_section_heading(text):
            continue
        next_text = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        if len(next_text) < 50:
            continue
        if not (next_text[:1].isupper() or next_text.startswith("•")):
            continue
        heading_count = 0
        content_span = 0
        for offset, look_ahead in enumerate(paragraphs[index + 1:index + 30], start=1):
            if _is_transcript_run(paragraphs, index + offset):
                break
            if look_ahead == "Action items":
                heading_count += 1
            elif _looks_like_section_heading(look_ahead):
                heading_count += 1
            content_span += 1
        if heading_count < 1:
            continue
        if content_span < 12:
            continue
        if _preceding_dialogue_density(paragraphs, index) < 3:
            continue
        starts.append(index)
    return starts


def _collect_summary_bullets(paragraphs: list[str], marker_index: int) -> tuple[int, list[str]]:
    bullets = []
    index = marker_index - 1
    while index >= 0 and _looks_like_summary_bullet(paragraphs[index]):
        bullets.append(paragraphs[index])
        index -= 1
    bullets.reverse()
    return index + 1, bullets


def _collect_notes_content(paragraphs: list[str], start_index: int, next_marker_index: int | None) -> tuple[int, list[dict], list[str]]:
    sections: list[dict] = []
    overview_lines: list[str] = []
    index = start_index
    current_heading = None
    current_lines: list[str] = []
    saw_structured_content = False
    max_index = min(len(paragraphs), (next_marker_index if next_marker_index is not None else len(paragraphs)), start_index + 140)

    while index < max_index:
        text = paragraphs[index]
        next_text = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
        if saw_structured_content and _is_transcript_run(paragraphs, index):
            break
        if _looks_like_speaker_label(text) and (_is_timecode(next_text) or _looks_like_transcript_line(next_text)):
            break
        if _is_timecode(text) or text == "1×":
            break
        if text in {"Notes", "Overview"} and saw_structured_content:
            break
        if text == "Action items":
            if current_heading and current_lines:
                sections.append({"heading": current_heading, "content": " ".join(current_lines).strip()})
            action_items = []
            index += 1
            while index < max_index:
                item = paragraphs[index]
                upcoming = paragraphs[index + 1] if index + 1 < len(paragraphs) else ""
                if _is_transcript_run(paragraphs, index):
                    break
                if _looks_like_speaker_label(item) and (_is_timecode(upcoming) or _looks_like_transcript_line(upcoming)):
                    break
                if _is_timecode(item) or item == "1×":
                    break
                if item in {"Notes", "Overview"}:
                    break
                action_items.append(item)
                index += 1
            sections.append({"heading": "Action items", "content": " ".join(action_items).strip()})
            break
        if _looks_like_section_heading(text):
            saw_structured_content = True
            if current_heading and current_lines:
                sections.append({"heading": current_heading, "content": " ".join(current_lines).strip()})
            current_heading = text
            current_lines = []
        else:
            if current_heading:
                current_lines.append(text)
                saw_structured_content = True
            else:
                overview_lines.append(text)
        index += 1

    if current_heading and current_lines:
        sections.append({"heading": current_heading, "content": " ".join(current_lines).strip()})

    return index, sections, overview_lines


def extract_benchmarks(paragraphs: list[str], source_name: str) -> list[dict]:
    examples = []
    explicit_markers = [(index, text) for index, text in enumerate(paragraphs) if text in {"Notes", "Overview"}]
    reserved_indexes = {index for index, _text in explicit_markers}
    unmarked_starts = _find_unmarked_summary_starts(paragraphs, reserved_indexes)
    markers = [(index, text) for index, text in explicit_markers]
    markers.extend((index, "UNMARKED") for index in unmarked_starts)
    markers.sort(key=lambda item: item[0])

    for marker_number, (index, marker_type) in enumerate(markers):
        if marker_type == "UNMARKED":
            summary_start = index
            bullets = []
            content_start = index
        else:
            summary_start, bullets = _collect_summary_bullets(paragraphs, index)
            if not bullets and marker_type != "Overview":
                continue
            content_start = index + 1
        next_marker_index = markers[marker_number + 1][0] if marker_number + 1 < len(markers) else None
        content_end, sections, overview_lines = _collect_notes_content(paragraphs, content_start, next_marker_index)
        transcript_start = max(0, summary_start - 220)
        transcript_lines = [line for line in paragraphs[transcript_start:summary_start] if line not in {"1×"} and not _is_timecode(line)]
        transcript = "\n".join(transcript_lines).strip()
        if not transcript:
            continue
        title = ""
        if sections:
            title = sections[0]["heading"]
        elif bullets:
            title = bullets[0].split(":", 1)[0]
        elif overview_lines:
            title = "Overview"
        detailed_summary_parts = []
        if overview_lines:
            detailed_summary_parts.append(" ".join(overview_lines).strip())
        for section in sections:
            if section["heading"] == "Action items":
                continue
            detailed_summary_parts.append(f"{section['heading']}: {section['content']}".strip())
        preferred_summary = "\n\n".join(part for part in detailed_summary_parts if part).strip()
        examples.append(
            {
                "source_file": source_name,
                "title": title or f"Example {len(examples) + 1}",
                "transcript": transcript,
                "summary_bullets": bullets,
                "preferred_summary": preferred_summary,
                "sections": sections,
                "overview_lines": overview_lines,
            }
        )
    return examples


def summarize_examples(examples: list[dict]) -> dict:
    headings = Counter()
    transcript_lengths = []
    summary_lengths = []
    for item in examples:
        transcript_lengths.append(len(item.get("transcript", "")))
        summary_lengths.append(len(item.get("preferred_summary", "")))
        for section in item.get("sections", []):
            headings[section.get("heading") or ""] += 1
    return {
        "example_count": len(examples),
        "avg_transcript_chars": int(sum(transcript_lengths) / max(len(transcript_lengths), 1)),
        "avg_summary_chars": int(sum(summary_lengths) / max(len(summary_lengths), 1)),
        "top_section_headings": headings.most_common(20),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_transcript_benchmark_docx.py <input.docx> [output_dir]")
        return 1
    input_path = Path(sys.argv[1]).expanduser().resolve()
    output_dir = (
        Path(sys.argv[2]).expanduser().resolve()
        if len(sys.argv) > 2
        else Path("docs/ai/benchmark_corpus").resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    paragraphs = _paragraphs_from_docx(input_path)
    examples = extract_benchmarks(paragraphs, input_path.name)
    stats = summarize_examples(examples)

    stem = re.sub(r"[^a-z0-9]+", "_", input_path.stem.lower()).strip("_")
    corpus_path = output_dir / f"{stem}.json"
    stats_path = output_dir / f"{stem}_stats.json"

    corpus_path.write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {len(examples)} examples to {corpus_path}")
    print(f"Wrote stats to {stats_path}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
