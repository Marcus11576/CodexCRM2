import asyncio

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import standalone_transcript_tool
from backend.config import settings

TEST_BASE_URL = "https://testserver"


def test_standalone_transcript_prompt_includes_examples_and_sections():
    prompt = standalone_transcript_tool._build_prompt(
        transcript="Brian says the issue is project specific.",
        title="WhatsApp extract",
        source_type="whatsapp",
        guidance="Keep commercial nuance and drop banter.",
        section_schema=standalone_transcript_tool._build_section_schema(),
        examples=[
            {
                "transcript": "Raw chat here",
                "preferred_summary": "Useful summary here",
                "preferred_sections": {"business_focus": "Business summary"},
                "notes": ["Drop the jokes", "Keep the practical view"],
            }
        ],
        max_points_per_section=4,
    )
    assert "Useful summary here" in prompt
    assert "Business Focus" in prompt
    assert "Drop the jokes" in prompt
    assert "Brian says the issue is project specific." in prompt


def test_toolkit_route_accepts_api_key_and_returns_structured_output(monkeypatch):
    async def fake_run_json_chat_task(**kwargs):
        return (
            {
                "executive_summary": "Brian sees supply issues as highly project specific.",
                "sections": [
                    {
                        "id": "business_focus",
                        "label": "Business Focus",
                        "summary": "Brian frames supply disruption as a project-by-project commercial issue.",
                        "points": [
                            {
                                "text": "Mid-stage projects with imported materials face delay and double-cost risk.",
                                "evidence": "somebody will need to pay twice",
                                "speaker": "Brian Scholfield",
                                "confidence": 0.92,
                            }
                        ],
                        "confidence": 0.9,
                    }
                ],
                "other_topics": [],
                "omitted_content": [{"text": "have i told you that i love you LOL", "reason": "banter"}],
            },
            "run-123",
        )

    monkeypatch.setattr(standalone_transcript_tool, "run_json_chat_task", fake_run_json_chat_task)
    monkeypatch.setattr(settings, "STANDALONE_TOOL_API_KEY", "tool-secret")

    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.post(
            "/api/toolkit/transcripts/summarize",
            headers={"X-Tool-Api-Key": "tool-secret"},
            json={
                "source_type": "whatsapp",
                "transcript": "Brian says somebody will need to pay twice.",
                "examples": [
                    {
                        "transcript": "Example transcript",
                        "preferred_summary": "Example output",
                        "preferred_sections": {"business_focus": "Business example"},
                        "notes": ["Preserve commercial nuance"],
                    }
                ],
            },
        )
    finally:
        client.close()
        monkeypatch.setattr(settings, "STANDALONE_TOOL_API_KEY", "")

    assert response.status_code == 200
    payload = response.json()
    assert payload["executive_summary"].startswith("Brian sees supply issues")
    assert payload["sections"][0]["id"] == "business_focus"
    assert payload["sections"][0]["points"][0]["evidence"] == "somebody will need to pay twice"
    assert payload["omitted_content"][0]["reason"] == "banter"
    assert payload["metadata"]["source_type"] == "whatsapp"


def test_toolkit_route_requires_credentials_when_api_key_configured(monkeypatch):
    monkeypatch.setattr(settings, "STANDALONE_TOOL_API_KEY", "tool-secret")
    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.post(
            "/api/toolkit/transcripts/summarize",
            json={"transcript": "Some transcript"},
        )
    finally:
        client.close()
        monkeypatch.setattr(settings, "STANDALONE_TOOL_API_KEY", "")

    assert response.status_code == 401
    assert "X-Tool-Api-Key" in response.json()["detail"]
