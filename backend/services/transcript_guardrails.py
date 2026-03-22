import re
from typing import Optional


CHAT_LIKE_TEXT_CHANNELS = {"chat", "typed", "note"}
COMPLETE_WORD = r"(?:complete|completion|completing|completed|compleate)"
PROVIDE_WORD = r"(?:provide|providing|provideing|provided)"
INFO_WORD = r"(?:information|infortmation|info|data|details?|fields?)"
STAGE_COMMAND_PATTERNS = (
    re.compile(r"\b(?:show|list|open|display)\s+(?:me\s+|the\s+)?(?:all\s+)?stages?\b"),
    re.compile(r"\b(?:show|open|display)\s+(?:the\s+)?stage\s+view\b"),
    re.compile(r"\bswitch(?:\s+to)?\s+(?:the\s+)?stage\s+view\b"),
)
PROFILE_COMPLETION_PATTERNS = (
    re.compile(rf"\b{COMPLETE_WORD}\s+(?:the\s+)?profile\b"),
    re.compile(rf"\bprofile\s+{COMPLETE_WORD}\b"),
    re.compile(rf"\bmissing\s+(?:profile\s+)?{INFO_WORD}\b"),
    re.compile(rf"\bwhat\s+{INFO_WORD}\s+(?:is|are)\s+missing\b"),
    re.compile(rf"\bwhich\s+{INFO_WORD}\s+(?:is|are)\s+missing\b"),
    re.compile(rf"\bwhat\s+do\s+you\s+need\s+to\s+{COMPLETE_WORD}\s+(?:the\s+)?profile\b"),
    re.compile(rf"\bwhat\s+should\s+i\s+{PROVIDE_WORD}\s+to\s+{COMPLETE_WORD}\s+(?:the\s+)?profile\b"),
    re.compile(rf"\b{PROVIDE_WORD}\s+(?:data|information|infortmation|info|details?)\s+(?:to|for)\s+{COMPLETE_WORD}\s+(?:the\s+)?profile\b"),
    re.compile(rf"\b{INFO_WORD}\s+(?:needed|required)\s+(?:to|for)\s+{COMPLETE_WORD}\s+(?:the\s+)?profile\b"),
)
LOW_SIGNAL_CHAT_EXACT = {
    "ping",
    "test",
    "ok",
    "okay",
    "yes",
    "no",
    "thanks",
    "thank you",
    "no change",
    "nothing to log",
    "n/a",
    "na",
}
LOW_SIGNAL_CHAT_PATTERNS = (
    re.compile(r"^(?:hi|hello|hey|yo|sup)[.!?]*$"),
    re.compile(r"^(?:yes|ok(?:ay)?|sure|please)[,\s]*(?:log|save|capture|record)\s+(?:this|it|that)(?:\s+as\s+intelligence)?(?:\s+and\s+keep\s+the\s+wording\s+concise)?[.!?]*$"),
    re.compile(r"^(?:log|save|capture|record)\s+(?:this|it|that)(?:\s+as\s+intelligence)?[.!?]*$"),
    re.compile(r"^(?:no\s+change|nothing\s+to\s+log|skip|carry\s+on|all\s+good)[.!?]*$"),
)


def normalize_chat_text(value: str | None) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return " ".join(text.lower().split())


def looks_like_stage_command(value: str | None) -> bool:
    text = normalize_chat_text(value)
    if not text or "stage" not in text:
        return False
    return "all stages" in text or any(pattern.search(text) for pattern in STAGE_COMMAND_PATTERNS)


def looks_like_profile_completion_request(value: str | None) -> bool:
    text = normalize_chat_text(value)
    if not text or "profile" not in text:
        return False
    return any(pattern.search(text) for pattern in PROFILE_COMPLETION_PATTERNS)


def looks_like_low_signal_chat_input(value: str | None) -> bool:
    text = normalize_chat_text(value)
    if not text:
        return False
    if text in LOW_SIGNAL_CHAT_EXACT:
        return True
    return any(pattern.search(text) for pattern in LOW_SIGNAL_CHAT_PATTERNS)


def is_non_transcript_chat_input(
    value: str | None,
    channel: Optional[str] = None,
    max_chars: int = 320,
) -> bool:
    raw_text = str(value or "")
    text = normalize_chat_text(raw_text)
    if not text:
        return False
    normalized_channel = str(channel or "").strip().lower()
    if normalized_channel and normalized_channel not in CHAT_LIKE_TEXT_CHANNELS:
        return False
    if len(raw_text.strip()) > max_chars:
        return False
    return (
        looks_like_stage_command(raw_text)
        or looks_like_profile_completion_request(raw_text)
        or looks_like_low_signal_chat_input(raw_text)
    )


def segment_prefers_positioning_stage(value: str | None) -> bool:
    text = normalize_chat_text(value)
    if not text:
        return False
    return any(
        phrase in text
        for phrase in (
            "need to sit down",
            "go through a presentation",
            "presentation of",
            "presentation about",
            "presentation on",
            "what taylor sterling",
            "taylor sterling abilities",
            "taylor stirling abilities",
            "what we do",
            "after eid",
            "after e-break",
            "after the e-break",
        )
    )
