import asyncio
import uuid

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def _login_client(password: str = "password123") -> TestClient:
    email = f"int-settings-{uuid.uuid4().hex[:8]}@example.com"
    existing = asyncio.run(get_user_by_email(email))
    if not existing:
        asyncio.run(create_user(email, "Intelligence Settings Tester", password, role="admin"))
    client = TestClient(app, base_url=TEST_BASE_URL)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    assert response.cookies.get("session_token")
    return client


def test_intelligence_settings_round_trip():
    client = _login_client()
    try:
        initial = client.get("/api/settings/intelligence")
        assert initial.status_code == 200
        initial_payload = initial.json()
        assert initial_payload["settings_key"] == "intelligence_framework"
        assert initial_payload["settings"]["stage1_calibration"]["profile"] in {"strict", "balanced", "lenient"}

        update_payload = {
            "settings": {
                "chatbot_only_inputs": True,
                "legacy_scoring_enabled": False,
                "layers": [
                    {
                        "layer_id": "stage1_knowledge_bank",
                        "label": "Stage 1 Knowledge Bank Build",
                        "description": "Baseline knowledge completeness layer.",
                        "enabled": True,
                        "status": "active",
                    },
                    {
                        "layer_id": "layer_2_strategy",
                        "label": "Layer 2 Strategy Lens",
                        "description": "Future strategy layer scaffold.",
                        "enabled": False,
                        "status": "planned",
                    },
                ],
                "stage1_calibration": {
                    "profile": "strict",
                    "coverage_weight_pct": 52,
                    "confidence_weight_pct": 24,
                    "recency_weight_pct": 18,
                    "density_weight_pct": 6,
                    "recency_windows_days": {
                        "fresh": 45,
                        "recent": 120,
                        "aged": 240,
                    },
                },
            },
            "merge": False,
        }

        saved = client.put("/api/settings/intelligence", json=update_payload)
        assert saved.status_code == 200
        saved_payload = saved.json()
        saved_settings = saved_payload["settings"]

        assert saved_settings["stage1_calibration"]["profile"] == "strict"
        assert sum(
            [
                saved_settings["stage1_calibration"]["coverage_weight_pct"],
                saved_settings["stage1_calibration"]["confidence_weight_pct"],
                saved_settings["stage1_calibration"]["recency_weight_pct"],
                saved_settings["stage1_calibration"]["density_weight_pct"],
            ]
        ) == 100
        assert any(layer["layer_id"] == "layer_2_strategy" for layer in saved_settings["layers"])

        fetched = client.get("/api/settings/intelligence")
        assert fetched.status_code == 200
        fetched_settings = fetched.json()["settings"]
        assert fetched_settings["stage1_calibration"]["profile"] == "strict"
        assert any(layer["layer_id"] == "layer_2_strategy" for layer in fetched_settings["layers"])
    finally:
        client.close()


def test_intelligence_settings_reset_restores_defaults():
    client = _login_client()
    try:
        save_custom = client.put(
            "/api/settings/intelligence",
            json={
                "settings": {
                    "legacy_scoring_enabled": True,
                    "stage1_calibration": {
                        "profile": "lenient",
                    },
                },
                "merge": True,
            },
        )
        assert save_custom.status_code == 200

        reset = client.post("/api/settings/intelligence/reset")
        assert reset.status_code == 200
        reset_settings = reset.json()["settings"]
        assert reset_settings["legacy_scoring_enabled"] is False
        assert reset_settings["stage1_calibration"]["profile"] == "balanced"
        assert any(layer["layer_id"] == "stage1_knowledge_bank" for layer in reset_settings["layers"])
        assert any(layer["layer_id"] == "stage2_relationship_flow" for layer in reset_settings["layers"])
    finally:
        client.close()


def test_intelligence_settings_transcript_guidance_fields_round_trip():
    client = _login_client()
    try:
        update = client.put(
            "/api/settings/intelligence",
            json={
                "settings": {
                    "transcript_tagging": {
                        "knowledge_buckets": [
                            {
                                "box_id": 5,
                                "code": "K5",
                                "box_key": "challenges_demands",
                                "box_title": "Challenges and Demands",
                                "keywords": ["pressure", "resource shortage"],
                                "what_it_is": "Current pressures, pain points, priorities, or resource demands affecting them or their business.",
                                "includes": ["growth pressure", "hiring pressure", "resource shortages"],
                                "good_content_looks_like": "Specific operational or leadership pain points, not vague complaints.",
                            }
                        ],
                        "stage_relationship": [
                            {
                                "code": "S5",
                                "label": "S5 Problem Identified",
                                "summary": "A need, pressure, or talent gap is visible.",
                                "what_it_is": "Problem stage where pressure is explicit and current.",
                                "includes": ["pain visibility", "delivery pressure"],
                                "good_content_looks_like": "Concrete need language with direct evidence.",
                            }
                        ],
                    }
                },
                "merge": True,
            },
        )
        assert update.status_code == 200
        settings_payload = update.json()["settings"]["transcript_tagging"]

        bucket = next(item for item in settings_payload["knowledge_buckets"] if item["box_key"] == "challenges_demands")
        assert bucket["what_it_is"].startswith("Current pressures")
        assert "growth pressure" in bucket["includes"]
        assert "Specific operational or leadership pain points" in bucket["good_content_looks_like"]

        stage = next(item for item in settings_payload["stage_relationship"] if item["code"] == "S5")
        assert stage["what_it_is"].startswith("Problem stage")
        assert "pain visibility" in stage["includes"]
        assert "Concrete need language" in stage["good_content_looks_like"]
    finally:
        client.close()
