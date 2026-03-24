from backend.services.transcript_guardrails import (
    is_non_transcript_chat_input,
    looks_like_profile_completion_request,
    looks_like_stage_command,
    segment_prefers_positioning_stage,
)


def test_stage_command_detection_covers_common_phrases():
    phrases = [
        "show stages please",
        "show stage",
        "show me stages",
        "list stages",
        "show all stages",
        "list all stage",
        "open stage view",
        "switch to stage view",
    ]
    for phrase in phrases:
        assert looks_like_stage_command(phrase), phrase


def test_profile_completion_detection_covers_common_phrases():
    phrases = [
        "what information is missing to complete profile?",
        "which fields are missing in the profile",
        "what should I provide to complete the profile?",
        "provide data to complete profile",
        "profile completion info",
        "provideing data to compleate profile",
        "what infortmation is needed to compleate profile",
    ]
    for phrase in phrases:
        assert looks_like_profile_completion_request(phrase), phrase


def test_non_transcript_filter_does_not_drop_real_commercial_chat():
    assert not is_non_transcript_chat_input(
        "Project stage 2 package pressure is rising and we need to align this week.",
        channel="chat",
    )
    assert not is_non_transcript_chat_input(
        "Need to discuss stage sequencing with client in tomorrow's meeting.",
        channel="chat",
    )


def test_non_transcript_filter_only_applies_to_chat_like_channels():
    assert not is_non_transcript_chat_input("show stages please", channel="email")
    assert is_non_transcript_chat_input("show stages please", channel="chat")
    assert is_non_transcript_chat_input("Capture this update for the profile:", channel="chat")
    assert is_non_transcript_chat_input("Create task:", channel="chat")
    assert is_non_transcript_chat_input("Next Action", channel="chat")


def test_positioning_phrase_detection_for_stage_remap():
    assert segment_prefers_positioning_stage(
        "I need to sit down with him and go through a presentation of what Taylor Stirling's abilities are."
    )
    assert not segment_prefers_positioning_stage(
        "He confirmed an active client mandate and signed project expansion."
    )
