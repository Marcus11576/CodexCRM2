import asyncio

from backend.services import ai_service, standalone_transcript_tool
from backend.services.ai_foundation import canonical_business_subtopic


def test_standalone_tool_uses_benchmark_examples_when_none_provided(monkeypatch):
    captured = {}

    async def fake_run_json_chat_task(**kwargs):
        captured["prompt"] = kwargs["messages"][1]["content"]
        captured["metadata"] = kwargs["metadata"]
        return (
            {
                "executive_summary": "Summary",
                "sections": [],
                "other_topics": [],
                "omitted_content": [],
            },
            "run-1",
        )

    monkeypatch.setattr(
        standalone_transcript_tool,
        "select_style_examples",
        lambda transcript, source_type="transcript", max_examples=3: [
            {
                "title": "Benchmark Example",
                "transcript": "Raw benchmark transcript",
                "preferred_summary": "Preferred benchmark summary",
                "preferred_sections": {},
                "notes": ["Keep the useful commercial substance"],
            }
        ],
    )
    monkeypatch.setattr(standalone_transcript_tool, "run_json_chat_task", fake_run_json_chat_task)

    payload = asyncio.run(
        standalone_transcript_tool.summarize_transcript_intelligence(
            transcript="Brian says the issue is highly project specific.",
            source_type="whatsapp",
        )
    )

    assert payload["metadata"]["example_count"] == 1
    assert captured["metadata"]["example_count"] == 1
    assert "Title: Benchmark Example" in captured["prompt"]
    assert "Preferred benchmark summary" in captured["prompt"]


def test_process_text_replaces_thin_nuggets_with_transcript_enrichment(monkeypatch):
    transcript = (
        "[13:55] Brian: We are all good and mostly in the office with a business as usual mindset.\n"
        "[14:14] Marcus: would you join us for the meet next week regarding the materials and supply issues?\n"
        "[14:26] Brian: somebody will need to pay twice. Depends on the contract. The second batch are midway with "
        "imported materials not yet on site and sourcing alternatives means delay and commercial pain.\n"
        "[14:53] Brian: if you want your project handed over you will need to pay. You may do a deal and pay 50% "
        "but it also depends on the contract and the developer cashflow position."
    )

    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "summary": "Generic summary",
                "sentiment": "Neutral",
                "sentiment_confidence": 0.8,
                "topics": [],
                "action_items": [],
                "profile_updates": {},
                "topic_nuggets": [
                    {
                        "topic": "business_focus",
                        "text": "Project supply issues were discussed.",
                        "snippet": "Project supply issues were discussed.",
                        "confidence": 0.6,
                        "sentiment": "Neutral",
                    }
                ],
                "success_metrics": {},
                "global_insights": [],
            },
            "run-2",
        )

    async def fake_summarize_transcript_intelligence(**kwargs):
        return {
            "executive_summary": "Brian sees supply constraints as a project-specific commercial issue requiring pragmatic payment decisions.",
            "sections": [
                {
                    "id": "business_focus",
                    "label": "Business Focus",
                    "summary": (
                        "Brian breaks current projects into three buckets: near-complete work with limited disruption, "
                        "mid-stage jobs exposed to imported-material delays and double-cost risk, and new starts that "
                        "should not proceed without supply clarity."
                    ),
                    "points": [
                        {
                            "text": "Developers will likely need to share cost pain if they want projects handed over.",
                            "evidence": "somebody will need to pay twice. Depends on the contract.",
                            "speaker": "Brian Schofield",
                            "subtopic": "commercial_position",
                            "confidence": 0.94,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
            "other_topics": [],
            "omitted_content": [],
        }

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(ai_service, "summarize_transcript_intelligence", fake_summarize_transcript_intelligence)

    payload = asyncio.run(
        ai_service.process_text(
            transcript,
            "whatsapp",
        )
    )

    assert payload["summary"].startswith("Brian sees supply constraints")
    assert payload["topic_nuggets"][0]["text"].startswith("Brian breaks current projects into three buckets")
    assert payload["topic_nuggets"][0]["business_subtopic"] == "commercial_position"
    assert "Developers will likely need to share cost pain" in payload["topic_nuggets"][0]["text"]
    assert "somebody will need to pay twice" in payload["topic_nuggets"][0]["snippet"].lower()


def test_process_text_skips_transcript_enrichment_for_profile_documents(monkeypatch):
    cv_text = (
        "John Example\n"
        "Senior Commercial Director\n"
        "Professional Summary: Commercial and delivery leader with 18 years in major projects.\n"
        "Experience\n"
        "- Senior Commercial Director, ACME Group, 2020 - Present\n"
        "- Commercial Manager, BuildCo, 2016 - 2020\n"
        "Education\n"
        "- MSc Construction Management\n"
        "Skills\n"
        "- Contracts, claims, procurement, and delivery governance\n"
        "LinkedIn: linkedin.com/in/john-example-profile\n"
    )
    enrichment_calls = {"count": 0}

    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "summary": "Document parsed as profile content.",
                "sentiment": "Neutral",
                "sentiment_confidence": 0.8,
                "topics": [],
                "action_items": [],
                "profile_updates": {},
                "topic_nuggets": [],
                "success_metrics": {},
                "global_insights": [],
            },
            "run-doc-1",
        )

    async def fake_summarize_transcript_intelligence(**kwargs):
        enrichment_calls["count"] += 1
        return {
            "executive_summary": "Should not run for CV/profile documents.",
            "sections": [],
            "other_topics": [],
            "omitted_content": [],
        }

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(ai_service, "summarize_transcript_intelligence", fake_summarize_transcript_intelligence)

    payload = asyncio.run(ai_service.process_text(cv_text, "document"))

    assert enrichment_calls["count"] == 0
    assert payload["summary"] == "Document parsed as profile content."
    assert payload["topic_nuggets"] == []


def test_process_text_keeps_transcript_enrichment_for_conversation_documents(monkeypatch):
    transcript_doc = (
        "Subject: Follow-up from site review\n"
        "From: brian@example.com\n"
        "To: marcus@example.com\n"
        "[09:11] Brian: The developer can only release part payment this week.\n"
        "[09:14] Marcus: Let's align on options before Thursday.\n"
        "[09:19] Brian: Agreed, if we need handover this month we need a pragmatic deal.\n"
    )
    enrichment_calls = {"count": 0}

    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "summary": "Generic document summary.",
                "sentiment": "Neutral",
                "sentiment_confidence": 0.6,
                "topics": [],
                "action_items": [],
                "profile_updates": {},
                "topic_nuggets": [],
                "success_metrics": {},
                "global_insights": [],
            },
            "run-doc-2",
        )

    async def fake_summarize_transcript_intelligence(**kwargs):
        enrichment_calls["count"] += 1
        return {
            "executive_summary": "Conversation highlights immediate commercial payment pressure.",
            "sections": [
                {
                    "id": "business_focus",
                    "summary": "Brian flags a payment constraint and requests pragmatic deal terms for handover.",
                    "points": [
                        {
                            "text": "Handover depends on pragmatic payment alignment this month.",
                            "evidence": "if we need handover this month we need a pragmatic deal",
                            "subtopic": "commercial_position",
                            "confidence": 0.92,
                        }
                    ],
                    "confidence": 0.9,
                }
            ],
            "other_topics": [],
            "omitted_content": [],
        }

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(ai_service, "summarize_transcript_intelligence", fake_summarize_transcript_intelligence)

    payload = asyncio.run(ai_service.process_text(transcript_doc, "document"))

    assert enrichment_calls["count"] == 1
    assert payload["summary"].startswith("Conversation highlights immediate commercial payment pressure.")
    assert payload["topic_nuggets"][0]["business_subtopic"] == "commercial_position"


def test_process_image_reuses_transcript_enrichment_for_whatsapp_screenshots(monkeypatch, tmp_path):
    image_path = tmp_path / "wa.png"
    image_path.write_bytes(b"fakepng")
    transcript = (
        "[13:55] Brian: We are all good and mostly in the office with a business as usual mindset.\n"
        "[14:14] Marcus: would you join us for the meet next week regarding the materials and supply issues?\n"
        "[14:26] Brian: somebody will need to pay twice. Depends on the contract. The second batch are midway with "
        "imported materials not yet on site and sourcing alternatives means delay and commercial pain.\n"
        "[14:53] Brian: if you want your project handed over you will need to pay. You may do a deal and pay 50% "
        "but it also depends on the contract and the developer cashflow position."
    )

    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "image_type": "screenshot",
                "image_type_confidence": 0.97,
                "screen_context": "whatsapp_chat",
                "source_app": "whatsapp",
                "summary": "Generic screenshot summary",
                "extracted_text": transcript,
                "sentiment": "Neutral",
                "sentiment_confidence": 0.7,
                "topics": [],
                "action_items": [],
                "topic_nuggets": [],
                "contact_info": {},
                "is_profile_photo": False,
                "success_metrics": {},
                "global_insights": [],
            },
            "run-3",
        )

    async def fake_summarize_transcript_intelligence(**kwargs):
        return {
            "executive_summary": "Brian frames the issue as project-specific and commercially driven rather than a one-size-fits-all market problem.",
            "sections": [
                {
                    "id": "business_focus",
                    "label": "Business Focus",
                    "summary": "Brian says mid-stage projects with imported materials face delay and double-cost exposure, with outcomes hinging on contract position and developer pragmatism.",
                    "points": [
                        {
                            "text": "If developers want handover, they will need to pay in some form.",
                            "evidence": "if you want your project handed over you will need to pay",
                            "speaker": "Brian Schofield",
                            "subtopic": "commercial_position",
                            "confidence": 0.95,
                        }
                    ],
                    "confidence": 0.92,
                }
            ],
            "other_topics": [],
            "omitted_content": [],
        }

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(ai_service, "summarize_transcript_intelligence", fake_summarize_transcript_intelligence)

    payload = asyncio.run(ai_service.process_image(str(image_path)))

    assert payload["summary"].startswith("Brian frames the issue")
    assert payload["topic_nuggets"][0]["topic"] == "business_focus"
    assert payload["topic_nuggets"][0]["business_subtopic"] == "commercial_position"
    assert "handed over" in payload["topic_nuggets"][0]["snippet"].lower()


def test_process_text_strips_speculative_rapport_filler(monkeypatch):
    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "summary": "Travel plans were discussed, which could be a rapport-building point.",
                "sentiment": "Neutral",
                "sentiment_confidence": 0.7,
                "topics": [],
                "action_items": [],
                "profile_updates": {},
                "topic_nuggets": [
                    {
                        "topic": "family_personal",
                        "text": "Travel plans to KSA were discussed, which could be a rapport-building point.",
                        "snippet": "Travel plans to KSA were discussed, which could be a rapport-building point.",
                        "confidence": 0.72,
                        "sentiment": "Neutral",
                    }
                ],
                "success_metrics": {},
                "global_insights": [],
            },
            "run-rapport",
        )

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(ai_service, "summarize_transcript_intelligence", lambda **kwargs: None)

    payload = asyncio.run(ai_service.process_text("Brian mentioned travel plans to KSA.", "note"))

    assert "rapport-building point" not in payload["summary"].lower()
    assert "rapport-building point" not in payload["topic_nuggets"][0]["text"].lower()


def test_process_image_preserves_relationship_follow_up_from_other_topics(monkeypatch, tmp_path):
    image_path = tmp_path / "wa-followup.png"
    image_path.write_bytes(b"fakepng")
    transcript = (
        "[13:55] Brian: We are all good and mostly in the office with a business as usual mindset.\n"
        "[14:26] Brian: The second batch are midway with imported products not yet on site and sourcing alternatives means somebody will need to pay twice.\n"
        "[14:53] Brian: If you want your project handed over you will need to pay.\n"
        "[15:12] Marcus: lets grab a coffee after EID if there is a break in the madness ;)"
    )

    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "image_type": "screenshot",
                "image_type_confidence": 0.97,
                "screen_context": "whatsapp_chat",
                "source_app": "whatsapp",
                "summary": "Generic screenshot summary",
                "extracted_text": transcript,
                "sentiment": "Positive",
                "sentiment_confidence": 0.8,
                "topics": [],
                "action_items": [],
                "topic_nuggets": [],
                "contact_info": {},
                "is_profile_photo": False,
                "success_metrics": {},
                "global_insights": [],
            },
            "run-followup",
        )

    async def fake_summarize_transcript_intelligence(**kwargs):
        return {
            "executive_summary": "The exchange mixes project discussion with a clear plan to catch up socially after Eid.",
            "sections": [
                {
                    "id": "business_focus",
                    "label": "Business Focus",
                    "summary": "Material supply and payment risk were discussed.",
                    "points": [],
                    "confidence": 0.84,
                }
            ],
            "other_topics": [
                {
                    "label": "Relationship follow-up",
                    "summary": "Marcus suggested grabbing a coffee after Eid when schedules calm down.",
                    "points": [
                        {
                            "text": "They discussed meeting for coffee after Eid when things are less hectic.",
                            "evidence": "lets grab a coffee after EID if there is a break in the madness",
                            "speaker": "Marcus",
                            "confidence": 0.91,
                        }
                    ],
                }
            ],
            "omitted_content": [],
        }

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(ai_service, "summarize_transcript_intelligence", fake_summarize_transcript_intelligence)

    payload = asyncio.run(ai_service.process_image(str(image_path)))

    personal = [item for item in payload["topic_nuggets"] if item["topic"] == "family_personal"]
    assert len(personal) == 1
    assert "coffee after eid" in personal[0]["text"].lower()
    assert "break in the madness" in personal[0]["snippet"].lower()
    assert payload["action_items"] == ["Call Brian after Eid to arrange coffee."]


def test_strategy_growth_alias_maps_to_commercial_position():
    assert canonical_business_subtopic("strategy_growth") == "commercial_position"
    assert canonical_business_subtopic("Strategy & Growth") == "commercial_position"


def test_generate_briefing_coerces_nested_section_payloads(monkeypatch):
    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "business_focus": {"summary": "Commercial pressure is project-specific."},
                "recruitment_talent": {"text": "No direct hiring signal."},
                "personal_rapport": ["Children at home are affecting work patterns."],
                "obe_focus": "",
                "strategic_hypotheses": [],
                "audio_script": {"content": "Commercial brief audio."},
            },
            "run-4",
        )

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)

    payload = asyncio.run(
        ai_service.generate_briefing(
            {"person_id": "person-1", "full_name": "Brian Schofield"},
            [
                {"primary_category": "business_focus", "signal_text": "Signal text", "source_snippet": "Snippet"},
                {"primary_category": "recruitment_talent", "signal_text": "Hiring signal", "source_snippet": "Snippet"},
                {"primary_category": "family_personal", "signal_text": "Family signal", "source_snippet": "Snippet"},
            ],
            [],
        )
    )

    assert payload["business_focus"] == "Commercial pressure is project-specific."
    assert payload["recruitment_talent"] == "No direct hiring signal."
    assert payload["personal_rapport"] == "Children at home are affecting work patterns."
    assert payload["audio_script"] == "Commercial brief audio."


def test_generate_briefing_clears_sections_without_direct_signals(monkeypatch):
    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "business_focus": "Commercial pressure is project-specific.",
                "recruitment_talent": "Potential cash-flow issues could affect hiring.",
                "personal_rapport": "Children at home affect routines.",
                "obe_focus": "Network opportunity exists.",
                "strategic_hypotheses": [],
                "audio_script": "Audio",
            },
            "run-5",
        )

    monkeypatch.setattr(ai_service, "run_json_chat_task", fake_run_json_chat_task)

    payload = asyncio.run(
        ai_service.generate_briefing(
            {"person_id": "person-1", "full_name": "Brian Schofield"},
            [{"primary_category": "business_focus", "signal_text": "Signal text", "source_snippet": "Snippet"}],
            [],
        )
    )

    assert payload["business_focus"] == "Commercial pressure is project-specific."
    assert payload["recruitment_talent"] == ""
    assert payload["personal_rapport"] == ""
    assert payload["obe_focus"] == ""
