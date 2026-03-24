import asyncio
import json
import os
import tempfile
import uuid

from fastapi.testclient import TestClient

from backend.database import run_read, run_write
from backend.main import app
from backend.routers.compat_v1 import _infer_twin_action
from backend.routers import intelligence as intelligence_router
from backend.routers.interactions import _create_pending_interaction, _persist_interaction
from backend.services import ai_service
from backend.services.ai_jobs import _channel_from_image_context, _handle_brief_generation, _handle_signal_extraction
from backend.services.ai_pipeline_service import create_or_update_artifact
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = "password123") -> TestClient:
    email = f"pipeline-{uuid.uuid4().hex[:8]}@example.com"
    existing = asyncio.run(get_user_by_email(email))
    if not existing:
        asyncio.run(create_user(email, "Pipeline Audit User", password, role="admin"))
    client = TestClient(app, base_url=TEST_BASE_URL)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


def test_event_participant_export_csv_matches_required_columns():
    person_id = f"export-person-{uuid.uuid4().hex[:8]}"
    event_id = f"export-event-{uuid.uuid4().hex[:8]}"
    person_event_id = f"pe-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, company_name_raw, title_current, phone_primary, email_primary, created_at, last_updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (person_id, "Taylor Export", "Antigravity", "Director", "+971500000000", "taylor@example.com", now, now),
        )
        await db.execute(
            "INSERT INTO EVENT (event_id, event_name, event_date, created_at, updated_at) VALUES (?,?,?,?,?)",
            (event_id, "Pipeline Summit", "2099-02-01", now, now),
        )
        await db.execute(
            "INSERT INTO PERSON_EVENT (person_event_id, person_id, event_id, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (person_event_id, person_id, event_id, "Confirmed", now, now),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/events/{event_id}/participants/export?status_filter=Confirmed")
    finally:
        client.close()

    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert lines[0] == "Name,Company,Position,Mobile,Email,Event Status"
    assert "Taylor Export,Antigravity,Director,+971500000000,taylor@example.com,Confirmed" in lines[1]


def test_profile_picture_signal_extraction_does_not_overwrite_existing_profile_photo(monkeypatch):
    person_id = f"photo-person-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, profile_photo_url, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, "Profile Guardrail", "/uploads/original.jpg", now, now),
        )

    asyncio.run(run_write(setup))
    interaction_id = asyncio.run(_create_pending_interaction(person_id, "screenshot", "Image uploaded", now, media_url="/uploads/new.jpg"))
    artifact = asyncio.run(
        create_or_update_artifact(
            person_id=person_id,
            channel="screenshot",
            source_interaction_id=interaction_id,
            raw_content="Image uploaded",
            media_url="/uploads/new.jpg",
            source_name="headshot.png",
            source_type="image",
            status="queued",
        )
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        handle.write(b"fake image")
        file_path = handle.name

    async def fake_process_image(_path, _person_id=None):
        return {
            "image_type": "profile_picture",
            "image_type_confidence": 0.99,
            "summary": "Headshot only",
            "extracted_text": "",
            "sentiment": "Unclear",
            "sentiment_confidence": 0.9,
            "topics": [],
            "action_items": [],
            "topic_nuggets": [],
            "contact_info": {},
            "is_profile_photo": True,
            "success_metrics": {},
            "global_insights": [],
        }

    monkeypatch.setattr(ai_service, "process_image", fake_process_image)
    try:
        result = asyncio.run(
            _handle_signal_extraction(
                {
                    "job_id": f"job-{uuid.uuid4().hex[:8]}",
                    "payload": {
                        "interaction_id": interaction_id,
                        "person_id": person_id,
                        "channel": "screenshot",
                        "raw_text": "Image uploaded",
                        "file_path": file_path,
                        "media_url": "/uploads/new.jpg",
                        "source_kind": "image",
                        "artifact_id": artifact["artifact_id"],
                    },
                }
            )
        )
    finally:
        os.unlink(file_path)

    assert result["profile_photo_updated"] is False
    assert result["input_type"] == "profile_picture"
    assert result["image_review_required"] is True

    async def verify(db):
        async with db.execute("SELECT profile_photo_url FROM PERSON WHERE person_id = ?", (person_id,)) as cursor:
            person_row = await cursor.fetchone()
        async with db.execute("SELECT input_type, requires_confirmation FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact["artifact_id"],)) as cursor:
            artifact_row = await cursor.fetchone()
        async with db.execute("SELECT COUNT(*) AS count FROM AI_SIGNAL WHERE artifact_id = ?", (artifact["artifact_id"],)) as cursor:
            signal_row = await cursor.fetchone()
        return person_row["profile_photo_url"], artifact_row["input_type"], artifact_row["requires_confirmation"], signal_row["count"]

    photo_url, input_type, requires_confirmation, signal_count = asyncio.run(run_read(verify))
    assert photo_url == "/uploads/original.jpg"
    assert input_type == "profile_picture"
    assert requires_confirmation == 1
    assert signal_count == 0


def test_profile_picture_signal_extraction_auto_attaches_when_profile_has_no_photo(monkeypatch):
    person_id = f"photo-empty-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, profile_photo_url, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, "Photo Missing", None, now, now),
        )

    asyncio.run(run_write(setup))
    interaction_id = asyncio.run(_create_pending_interaction(person_id, "screenshot", "Image uploaded", now, media_url="/uploads/new-headshot.jpg"))
    artifact = asyncio.run(
        create_or_update_artifact(
            person_id=person_id,
            channel="screenshot",
            source_interaction_id=interaction_id,
            raw_content="Image uploaded",
            media_url="/uploads/new-headshot.jpg",
            source_name="headshot.png",
            source_type="image",
            status="queued",
        )
    )

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        handle.write(b"fake image")
        file_path = handle.name

    async def fake_process_image(_path, _person_id=None):
        return {
            "image_type": "profile_picture",
            "image_type_confidence": 0.99,
            "summary": "Headshot only",
            "extracted_text": "",
            "sentiment": "Unclear",
            "sentiment_confidence": 0.9,
            "topics": [],
            "action_items": [],
            "topic_nuggets": [],
            "contact_info": {},
            "is_profile_photo": True,
            "success_metrics": {},
            "global_insights": [],
        }

    monkeypatch.setattr(ai_service, "process_image", fake_process_image)
    try:
        result = asyncio.run(
            _handle_signal_extraction(
                {
                    "job_id": f"job-{uuid.uuid4().hex[:8]}",
                    "payload": {
                        "interaction_id": interaction_id,
                        "person_id": person_id,
                        "channel": "screenshot",
                        "raw_text": "Image uploaded",
                        "file_path": file_path,
                        "media_url": "/uploads/new-headshot.jpg",
                        "source_kind": "image",
                        "artifact_id": artifact["artifact_id"],
                    },
                }
            )
        )
    finally:
        os.unlink(file_path)

    assert result["profile_photo_updated"] is True
    assert result["input_type"] == "profile_picture"
    assert result["image_review_required"] is False

    async def verify(db):
        async with db.execute("SELECT profile_photo_url FROM PERSON WHERE person_id = ?", (person_id,)) as cursor:
            person_row = await cursor.fetchone()
        async with db.execute("SELECT input_type, requires_confirmation FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact["artifact_id"],)) as cursor:
            artifact_row = await cursor.fetchone()
        async with db.execute(
            "SELECT summary, media_url FROM INTERACTION WHERE person_id = ? AND channel = 'system_audit' ORDER BY created_at DESC LIMIT 1",
            (person_id,),
        ) as cursor:
            audit_row = await cursor.fetchone()
        return person_row["profile_photo_url"], artifact_row["input_type"], artifact_row["requires_confirmation"], dict(audit_row)

    photo_url, input_type, requires_confirmation, audit_row = asyncio.run(run_read(verify))
    assert photo_url == "/uploads/new-headshot.jpg"
    assert input_type == "profile_picture"
    assert requires_confirmation == 0
    assert audit_row["media_url"] == "/uploads/new-headshot.jpg"
    assert "Profile photo updated" in audit_row["summary"]


def test_channel_from_image_context_infers_whatsapp_from_transcript_text():
    channel = _channel_from_image_context(
        "screenshot",
        {
            "is_profile_photo": False,
            "source_app": "",
            "screen_context": "",
            "summary": "Screenshot intake",
            "extracted_text": "[14:26] Brian: Somebody will need to pay twice. Last seen today at 10:22.",
        },
    )
    assert channel == "whatsapp"


def test_twin_action_infers_company_people_query():
    intent = _infer_twin_action("show me everyone who works for Acme Build Group")
    assert intent["type"] == "search_company_people"
    assert intent["params"]["company"] == "Acme Build Group"


def test_twin_action_infers_db_summary_count_query():
    intent = _infer_twin_action("how many contacts do we have?")
    assert intent["type"] == "db_summary"
    assert intent["params"]["scope"] == "counts"


def test_twin_chat_company_people_query_returns_company_matches():
    company = f"TwinLookup-{uuid.uuid4().hex[:8]}"
    now = "2026-03-23T00:00:00Z"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (f"tw1-{uuid.uuid4().hex[:8]}", "Twin One", "Director", company, "GEN", now, now),
        )
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (f"tw2-{uuid.uuid4().hex[:8]}", "Twin Two", "Manager", company, "GEN", now, now),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.post(
            "/api/intelligence/twin/chat",
            json={"message": f"show me everyone who works for {company}", "history": []},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert "found" in str(payload.get("reply") or "").lower()
    matches = payload.get("data") or []
    assert len(matches) >= 2
    assert all(company.lower() in str(row.get("company_name_raw") or "").lower() for row in matches)


def test_twin_chat_generic_search_returns_company_and_people_matches():
    company = f"TwinGeneric-{uuid.uuid4().hex[:8]}"
    now = "2026-03-24T00:00:00Z"
    person_id = f"twg-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Twin Generic", "Commercial Director", company, "GEN", now, now),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.post(
            "/api/intelligence/twin/chat",
            json={"message": f"search {company}", "history": []},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    data = payload.get("data") or []
    assert any(str(item.get("result_type") or "") == "company" for item in data)
    assert any(str(item.get("result_type") or "") == "person" for item in data)


def test_people_create_auto_backfills_career_background():
    full_name = f"Backfill Person {uuid.uuid4().hex[:6]}"
    company = f"BackfillCo-{uuid.uuid4().hex[:6]}"

    client = login_client()
    try:
        response = client.post(
            "/api/people",
            json={
                "full_name": full_name,
                "title_current": "Associate Director",
                "company_name_raw": company,
                "cat": "GEN",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    person_id = payload.get("person_id")
    assert person_id

    async def verify(db):
        async with db.execute(
            "SELECT career_summary, employment_history FROM PERSON WHERE person_id=?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else {}

    person = asyncio.run(run_read(verify))
    assert "Associate Director" in str(person.get("career_summary") or "")
    history = json.loads(person.get("employment_history") or "[]")
    assert isinstance(history, list)
    assert history
    assert history[0].get("company") == company


def test_companies_page_route_renders():
    client = login_client()
    try:
        response = client.get("/companies")
    finally:
        client.close()

    assert response.status_code == 200
    assert "Companies" in response.text


def test_persist_interaction_conflict_updates_channel_field():
    person_id = f"channel-person-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Channel Update", now, now),
        )

    asyncio.run(run_write(setup))
    interaction_id = asyncio.run(
        _create_pending_interaction(
            person_id,
            "screenshot",
            "Image uploaded: chat.png",
            now,
            media_url="/uploads/chat.png",
        )
    )

    result = {
        "summary": "WhatsApp chat processed.",
        "action_items": [],
        "topics": [],
        "sentiment": "Neutral",
        "success_metrics": {},
        "profile_updates": {},
    }

    async def persist(db):
        await _persist_interaction(
            db,
            interaction_id,
            person_id,
            "whatsapp",
            "WhatsApp conversation captured.",
            result,
            now,
            now,
            media_url="/uploads/chat.png",
        )

    asyncio.run(run_write(persist))

    async def verify(db):
        async with db.execute("SELECT channel FROM INTERACTION WHERE interaction_id = ?", (interaction_id,)) as cursor:
            row = await cursor.fetchone()
        return row["channel"] if row else None

    channel = asyncio.run(run_read(verify))
    assert channel == "whatsapp"


def test_document_persist_interaction_fills_missing_fields_without_overwriting_existing_profile():
    person_id = f"doc-merge-{uuid.uuid4().hex[:8]}"
    interaction_id = f"doc-interaction-{uuid.uuid4().hex[:8]}"
    now = "2026-03-23T00:00:00Z"
    existing_history = [
        {
            "title": "Development Manager",
            "company": "OldCo",
            "start_date": "2019-01",
            "end_date": "2022-12",
            "location": "",
            "description": "",
        }
    ]

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, email_primary,
                career_summary, employment_history, created_at, last_updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Document Merge Guard",
                "Old Title",
                "OldCo",
                "TGT",
                "existing@example.com",
                "Existing summary",
                json.dumps(existing_history),
                now,
                now,
            ),
        )

    asyncio.run(run_write(setup))

    async def persist(db):
        await _persist_interaction(
            db,
            interaction_id,
            person_id,
            "document",
            "Profile document uploaded",
            {
                "summary": "Document parsed",
                "action_items": [],
                "topics": [],
                "sentiment": "Neutral",
                "success_metrics": {},
                "profile_updates": {
                    "title_current": "Managing Director",
                    "company_name_raw": "NewCo",
                    "email_primary": "new@example.com",
                    "phone_primary": "+971500000000",
                    "linkedin_url": "https://linkedin.com/in/doc-merge-guard",
                    "cat": "GEN",
                    "disc": "Corporate",
                },
                "career_summary": "New summary from CV",
                "key_professional_notes": "Strong project delivery track record.",
                "employment_history": [
                    {
                        "title": "Managing Director",
                        "company": "NewCo",
                        "start_date": "2023-01",
                        "end_date": "",
                        "location": "",
                        "description": "",
                    }
                ],
            },
            now,
            now,
        )

    asyncio.run(run_write(persist))

    async def verify(db):
        async with db.execute(
            """
            SELECT title_current, company_name_raw, cat, email_primary, phone_primary, linkedin_url,
                   career_summary, key_professional_notes, employment_history
            FROM PERSON WHERE person_id=?
            """,
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    person = asyncio.run(run_read(verify))
    assert person["title_current"] == "Managing Director"
    assert person["company_name_raw"] == "NewCo"
    assert person["cat"] == "TGT"
    assert person["email_primary"] == "existing@example.com"
    assert person["phone_primary"] == "+971500000000"
    assert person["linkedin_url"] == "https://linkedin.com/in/doc-merge-guard"
    assert person["career_summary"] == "Existing summary"
    assert person["key_professional_notes"] == "Strong project delivery track record."
    merged_history = json.loads(person["employment_history"] or "[]")
    assert isinstance(merged_history, list)
    assert len(merged_history) == 2
    assert merged_history[0]["title"] == "Development Manager"
    assert merged_history[0]["company"] == "OldCo"
    assert merged_history[1]["title"] == "Managing Director"
    assert merged_history[1]["company"] == "NewCo"


def test_document_signal_extraction_maps_header_updates_even_without_employment_history(monkeypatch):
    person_id = f"doc-extract-{uuid.uuid4().hex[:8]}"
    now = "2026-03-23T00:00:00Z"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (person_id, "Document Extract", "Old Role", "OldCo", now, now),
        )

    asyncio.run(run_write(setup))
    interaction_id = asyncio.run(
        _create_pending_interaction(
            person_id,
            "document",
            "Document uploaded",
            now,
            media_url="/uploads/doc-extract.txt",
        )
    )

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        handle.write(b"Test CV text")
        file_path = handle.name

    async def fake_process_text(_text, _channel, _person_id=None):
        return {
            "summary": "Document parsed",
            "sentiment": "Neutral",
            "sentiment_confidence": 0.6,
            "topics": [],
            "action_items": [],
            "profile_updates": {},
            "topic_nuggets": [],
            "success_metrics": {},
            "global_insights": [],
        }

    async def fake_extract_document_profile(_text):
        return {
            "title_current": "Chief Growth Officer",
            "company_name_raw": "FutureWorks",
            "email_primary": "doc.extract@example.com",
            "phone_primary": "",
            "linkedin_url": "",
            "career_summary": "",
            "key_professional_notes": "",
            "employment_history": [],
        }

    monkeypatch.setattr(ai_service, "extract_text_from_file", lambda _path: "Document CV text")
    monkeypatch.setattr(ai_service, "process_text", fake_process_text)
    monkeypatch.setattr(ai_service, "extract_document_profile", fake_extract_document_profile)

    try:
        asyncio.run(
            _handle_signal_extraction(
                {
                    "job_id": f"job-{uuid.uuid4().hex[:8]}",
                    "payload": {
                        "interaction_id": interaction_id,
                        "person_id": person_id,
                        "channel": "document",
                        "raw_text": "Document uploaded",
                        "file_path": file_path,
                        "media_url": "/uploads/doc-extract.txt",
                        "source_kind": "document",
                    },
                }
            )
        )
    finally:
        os.unlink(file_path)

    async def verify(db):
        async with db.execute(
            "SELECT title_current, company_name_raw, email_primary, employment_history FROM PERSON WHERE person_id=?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    person = asyncio.run(run_read(verify))
    assert person["title_current"] == "Chief Growth Officer"
    assert person["company_name_raw"] == "FutureWorks"
    assert person["email_primary"] == "doc.extract@example.com"
    assert json.loads(person["employment_history"] or "[]") == []


def test_document_persist_interaction_replaces_seeded_summary_and_enriches_existing_role():
    person_id = f"doc-seeded-{uuid.uuid4().hex[:8]}"
    interaction_id = f"doc-interaction-{uuid.uuid4().hex[:8]}"
    now = "2026-03-24T00:00:00Z"
    full_name = "Iustina Blidariu"
    title = "Talent Acquisition Manager - Middle East"
    company = "Mott MacDonald"
    seeded_summary = f"{full_name} is currently {title} at {company}."
    existing_history = [
        {
            "title": title,
            "company": company,
            "start_date": "",
            "end_date": "Present",
            "location": "",
            "description": "",
        }
    ]

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw,
                career_summary, employment_history, created_at, last_updated_at
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (person_id, full_name, title, company, seeded_summary, json.dumps(existing_history), now, now),
        )

    asyncio.run(run_write(setup))

    async def persist(db):
        await _persist_interaction(
            db,
            interaction_id,
            person_id,
            "document",
            "Profile document uploaded",
            {
                "summary": "Document parsed",
                "action_items": [],
                "topics": [],
                "sentiment": "Neutral",
                "success_metrics": {},
                "profile_updates": {
                    "title_current": title,
                    "company_name_raw": company,
                },
                "career_summary": "Over 7 years of experience in talent acquisition and mobility across the Middle East.",
                "employment_history": [
                    {
                        "title": title,
                        "company": company,
                        "start_date": "2023-01",
                        "end_date": "Present",
                        "location": "Dubai, United Arab Emirates",
                        "description": "Owns talent acquisition strategy for the region.",
                    },
                    {
                        "title": "Talent Acquisition Lead - Middle East",
                        "company": company,
                        "start_date": "2021-03",
                        "end_date": "2022-12",
                        "location": "Dubai, United Arab Emirates",
                        "description": "Implemented TA strategy across the Middle East unit.",
                    },
                ],
            },
            now,
            now,
        )

    asyncio.run(run_write(persist))

    async def verify(db):
        async with db.execute(
            "SELECT career_summary, employment_history FROM PERSON WHERE person_id=?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row)

    person = asyncio.run(run_read(verify))
    assert person["career_summary"].startswith("Over 7 years of experience")
    history = json.loads(person["employment_history"] or "[]")
    assert len(history) == 2
    assert history[0]["title"] == title
    assert history[0]["start_date"] == "2023-01"
    assert history[0]["location"] == "Dubai, United Arab Emirates"
    assert history[1]["title"] == "Talent Acquisition Lead - Middle East"


def test_brief_generation_uses_signals_only(monkeypatch):
    person_id = f"brief-person-{uuid.uuid4().hex[:8]}"
    signal_id = f"legacy-signal-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, company_name_raw, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, "Brief Signal Only", "Antigravity", now, now),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (f"i-{uuid.uuid4().hex[:8]}", person_id, "email", "THIS RAW INTERACTION SHOULD NOT DRIVE THE BRIEF", "ignored", now, now),
        )
        await db.execute(
            "INSERT INTO TASK (task_id, person_id, task_text, status, created_at) VALUES (?,?,?,?,?)",
            (f"t-{uuid.uuid4().hex[:8]}", person_id, "THIS TASK SHOULD NOT DRIVE THE BRIEF", "open", now),
        )
        await db.execute(
            "INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, status, source_snippet, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (signal_id, person_id, "business_focus", "Important commercial signal", 5, "approved", "Important commercial signal", now),
        )

    asyncio.run(run_write(setup))
    captured = {}

    async def fake_generate_briefing(person, signals, events, preference_profile=None):
        captured["signals"] = signals
        captured["events"] = events
        return {
            "business_focus": "Important commercial signal",
            "recruitment_talent": "",
            "personal_rapport": "",
            "obe_focus": "",
            "strategic_hypotheses": [],
            "audio_script": "Important commercial signal",
        }

    monkeypatch.setattr(ai_service, "generate_briefing", fake_generate_briefing)
    result = asyncio.run(_handle_brief_generation({"job_id": "brief-job", "payload": {"person_id": person_id}}))

    assert result["signal_count"] >= 1
    assert any((signal.get("signal_text") or signal.get("text")) == "Important commercial signal" for signal in captured["signals"])
    assert all("raw_text" not in signal for signal in captured["signals"])
    assert all("task_text" not in signal for signal in captured["signals"])


def test_duplicate_manual_note_marks_second_artifact_duplicate():
    person_id = f"dedupe-person-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Duplicate Notes", now, now),
        )

    asyncio.run(run_write(setup))
    client = login_client()
    payload = {
        "person_id": person_id,
        "channel": "note",
        "raw_text": "Same note twice",
        "process_with_ai": False,
    }
    try:
        first = client.post("/api/interactions", json=payload)
        second = client.post("/api/interactions", json=payload)
    finally:
        client.close()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["artifact_id"]
    assert "Duplicate evidence was detected" in second.json()["message"]


def test_create_interaction_ignores_control_prompt_chat_inputs():
    person_id = f"ctrl-person-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Control Prompt Person", now, now),
        )

    asyncio.run(run_write(setup))
    client = login_client()
    payload = {
        "person_id": person_id,
        "channel": "chat",
        "raw_text": "show stages please",
        "process_with_ai": False,
    }
    try:
        response = client.post("/api/interactions", json=payload)
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ignored"
    assert body["interaction_id"] is None

    async def check(db):
        async with db.execute("SELECT COUNT(*) AS count FROM INTERACTION WHERE person_id=?", (person_id,)) as cursor:
            row = await cursor.fetchone()
            return int(row["count"] or 0)

    interaction_count = asyncio.run(run_read(check))
    assert interaction_count == 0


def test_create_interaction_ignores_profile_completion_typos():
    person_id = f"ctrl-typo-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Control Prompt Typo Person", now, now),
        )

    asyncio.run(run_write(setup))
    client = login_client()
    payload = {
        "person_id": person_id,
        "channel": "chat",
        "raw_text": "need infortmation for provideing data to compleate profile",
        "process_with_ai": False,
    }
    try:
        response = client.post("/api/interactions", json=payload)
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ignored"
    assert body["interaction_id"] is None

    async def check(db):
        async with db.execute("SELECT COUNT(*) AS count FROM INTERACTION WHERE person_id=?", (person_id,)) as cursor:
            row = await cursor.fetchone()
            return int(row["count"] or 0)

    interaction_count = asyncio.run(run_read(check))
    assert interaction_count == 0


def test_create_interaction_keeps_real_stage_content():
    person_id = f"real-stage-{uuid.uuid4().hex[:8]}"
    now = "2026-03-10T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Real Stage Person", now, now),
        )

    asyncio.run(run_write(setup))
    client = login_client()
    payload = {
        "person_id": person_id,
        "channel": "chat",
        "raw_text": "Project stage 2 package pressure is rising and we need a follow-up call.",
        "process_with_ai": False,
    }
    try:
        response = client.post("/api/interactions", json=payload)
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["interaction_id"]

def test_brief_endpoint_returns_cached_legacy_brief_shape():
    person_id = f"legacy-brief-{uuid.uuid4().hex[:8]}"
    brief_id = f"brief-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"
    cached_payload = {
        "business_focus": {
            "strategic_priorities": "Expand the project pipeline in KSA.",
            "company_wins": "Recently won two major delivery mandates.",
        },
        "recruitment_talent": {
            "challenges": "Finding delivery leaders fast enough.",
        },
        "personal_rapport": {
            "family": "Three children at home.",
        },
        "obe_focus": {
            "opportunities": "Potential OBE roundtable host.",
        },
        "audio_script": "Discuss KSA growth and delivery leadership hiring.",
    }

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, cached_briefing, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, "Legacy Brief Contact", None, now, now),
        )
        await db.execute(
            "INSERT INTO AI_BRIEF (brief_id, person_id, profile_id, content_json, source_signal_ids, generated_from_signal_set_hash, business_focus_summary, recruitment_talent_summary, family_personal_summary, obe_focus_summary, overall_brief_summary, top_priorities_json, recent_changes_json, event_relevance_json, confidence_summary_json, created_at, updated_at, stale_after, is_stale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                brief_id,
                person_id,
                person_id,
                json.dumps(cached_payload),
                "[]",
                "legacy-hash",
                "",
                "",
                "",
                "",
                "",
                "[]",
                "[]",
                "[]",
                "{}",
                now,
                now,
                None,
                0,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/intelligence/brief/{person_id}")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["briefing"]["brief_id"] == brief_id
    assert payload["briefing"]["business_focus"] == "Expand the project pipeline in KSA. Recently won two major delivery mandates."
    assert payload["briefing"]["recruitment_talent"] == "Finding delivery leaders fast enough."
    assert payload["briefing"]["personal_rapport"] == "Three children at home."


def test_persist_interaction_skips_placeholder_intelligence_nuggets():
    person_id = f"placeholder-person-{uuid.uuid4().hex[:8]}"
    interaction_id = f"placeholder-interaction-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Placeholder Guard", now, now),
        )

    asyncio.run(run_write(setup))

    result = {
        "summary": "Screenshot reviewed",
        "sentiment": "Unclear",
        "action_items": [],
        "topics": [],
        "topic_nuggets": [
            {"topic": "business_focus", "text": "No relevant content", "snippet": "No relevant content", "confidence": 0},
            {"topic": "family_personal", "text": "None", "snippet": "None", "confidence": 0},
            {"topic": "obe_focus", "text": "Potential OBE roundtable host.", "snippet": "Potential OBE roundtable host.", "confidence": 0.8},
        ],
        "success_metrics": {},
    }

    async def persist(db):
        await _persist_interaction(
            db,
            interaction_id,
            person_id,
            "screenshot",
            "raw text",
            result,
            now,
            now,
            media_url="/uploads/test.png",
        )
        async with db.execute("SELECT intel_text FROM TOPIC_INTELLIGENCE WHERE person_id = ? ORDER BY created_at ASC", (person_id,)) as cursor:
            return [row["intel_text"] for row in await cursor.fetchall()]

    stored = asyncio.run(run_write(persist))
    assert stored == []


def test_force_refresh_brief_queues_new_job_even_when_cached_brief_exists(monkeypatch):
    person_id = f"force-brief-{uuid.uuid4().hex[:8]}"
    brief_id = f"brief-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, cached_briefing, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, "Force Refresh Contact", json.dumps({"brief_id": brief_id, "business_focus": "Cached brief"}), now, now),
        )
        await db.execute(
            "INSERT INTO AI_BRIEF (brief_id, person_id, profile_id, content_json, source_signal_ids, generated_from_signal_set_hash, business_focus_summary, recruitment_talent_summary, family_personal_summary, obe_focus_summary, overall_brief_summary, top_priorities_json, recent_changes_json, event_relevance_json, confidence_summary_json, created_at, updated_at, stale_after, is_stale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                brief_id,
                person_id,
                person_id,
                json.dumps({"brief_id": brief_id, "business_focus": "Cached brief"}),
                "[]",
                "cached-hash",
                "Cached brief",
                "",
                "",
                "",
                "Cached brief",
                "[]",
                "[]",
                "[]",
                "{}",
                now,
                now,
                None,
                0,
            ),
        )

    asyncio.run(run_write(setup))

    async def fake_latest_brief_job(_person_id):
        return {"status": intelligence_router.JOB_STATUS_COMPLETED, "job_id": "completed-job"}

    async def fake_enqueue_job(*args, **kwargs):
        return {"status": intelligence_router.JOB_STATUS_QUEUED, "job_id": "queued-refresh"}

    monkeypatch.setattr(intelligence_router, "_latest_brief_job", fake_latest_brief_job)
    monkeypatch.setattr(intelligence_router, "enqueue_job", fake_enqueue_job)

    result = asyncio.run(intelligence_router.get_brief(person_id, force_refresh=True))
    assert result == {"status": "queued", "job_id": "queued-refresh", "cached": False}


def test_brief_generation_skips_rejected_legacy_intelligence(monkeypatch):
    person_id = f"reject-brief-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Rejected Legacy Brief", now, now),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, status, source_snippet, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (f"approved-{person_id}", person_id, "business_focus", "Keep this live business signal.", 4, "approved", "Keep this live business signal.", now),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, status, source_snippet, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (f"rejected-{person_id}", person_id, "family_personal", "Do not keep this rejected personal signal.", 4, "rejected", "Do not keep this rejected personal signal.", now),
        )

    asyncio.run(run_write(setup))
    captured = {}

    async def fake_generate_briefing(person, signals, events, preference_profile=None):
        captured["signals"] = signals
        return {
            "business_focus": "Keep this live business signal.",
            "recruitment_talent": "",
            "personal_rapport": "",
            "obe_focus": "",
            "strategic_hypotheses": [],
            "audio_script": "Keep this live business signal.",
        }

    monkeypatch.setattr(ai_service, "generate_briefing", fake_generate_briefing)
    asyncio.run(_handle_brief_generation({"job_id": "brief-job-2", "payload": {"person_id": person_id}}))

    texts = [(signal.get("signal_text") or signal.get("text") or "") for signal in captured["signals"]]
    assert "Keep this live business signal." in texts
    assert "Do not keep this rejected personal signal." not in texts


def test_people_intelligence_endpoint_hides_rejected_rows():
    person_id = f"reject-intel-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Rejected Intel View", now, now),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, status, source_snippet, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (f"approved-view-{person_id}", person_id, "business_focus", "Visible approved signal", 4, "approved", "Visible approved signal", now),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, status, source_snippet, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (f"rejected-view-{person_id}", person_id, "family_personal", "Hidden rejected signal", 4, "rejected", "Hidden rejected signal", now),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/intelligence")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["business_focus"][0]["text"] == "Visible approved signal"
    assert payload["family_personal"] == []


def test_people_intelligence_endpoint_merges_ai_and_legacy_signals():
    person_id = f"intel-merge-{uuid.uuid4().hex[:8]}"
    artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"
    signal_id = f"signal-{uuid.uuid4().hex[:8]}"
    legacy_id = f"legacy-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Merged Signals", now, now),
        )
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, channel, raw_content, raw_content_or_path,
                source_name, source_type, input_type, input_type_confidence, profile_match_state,
                requires_confirmation, duplicate_hash, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                "email",
                "Real email",
                "Real email",
                "email.eml",
                "email",
                "email",
                0.95,
                "confirmed",
                0,
                f"dup-{artifact_id}",
                "processed",
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, included_in_brief, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                artifact_id,
                person_id,
                person_id,
                "business_focus",
                "business_focus",
                "AI commercial priority",
                "AI commercial priority",
                "AI commercial priority",
                5,
                1.0,
                "approved",
                "approved",
                "Positive",
                0.9,
                0.88,
                0.9,
                0.8,
                0.79,
                1,
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE (
                intel_id, person_id, topic, intel_text, confidence, source_snippet, status, created_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                legacy_id,
                person_id,
                "family_personal",
                "Legacy rapport detail",
                4,
                "Legacy rapport detail",
                "approved",
                now,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/intelligence")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["business_focus"][0]["text"] == "AI commercial priority"
    assert payload["business_focus"][0]["source_kind"] == "ai_signal"
    assert payload["family_personal"][0]["text"] == "Legacy rapport detail"
    assert payload["family_personal"][0]["source_kind"] == "legacy_intelligence"


def test_safe_pending_ai_signals_surface_in_profile_intelligence():
    person_id = f"pending-visible-{uuid.uuid4().hex[:8]}"
    artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"
    now = "2026-03-12T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Pending Visible", now, now),
        )
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, channel, raw_content, raw_content_or_path,
                source_name, source_type, input_type, input_type_confidence, profile_match_state,
                requires_confirmation, duplicate_hash, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                "note",
                "James is looking to hire a new CTO soon.",
                "James is looking to hire a new CTO soon.",
                "pending.txt",
                "text",
                "manual_note",
                0.8,
                "confirmed",
                0,
                f"dup-{artifact_id}",
                "processed",
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, included_in_brief, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"signal-{uuid.uuid4().hex[:8]}",
                artifact_id,
                person_id,
                person_id,
                "recruitment_talent",
                "recruitment_talent",
                "Looking to hire a new CTO for JLL soon.",
                "Looking to hire a new CTO for JLL soon.",
                "Looking to hire a new CTO for JLL soon.",
                3,
                0.6,
                "approved",
                "pending_review",
                "Neutral",
                0.7,
                0.62,
                0.5,
                0.5,
                0.5,
                1,
                now,
                now,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/intelligence")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["recruitment_talent"]) == 1
    assert payload["recruitment_talent"][0]["text"] == "Looking to hire a new CTO for JLL soon."
    assert payload["recruitment_talent"][0]["review_state"] == "pending_review"
    assert payload["recruitment_talent"][0]["source_kind"] == "ai_signal"


def test_signal_status_patch_updates_legacy_and_ai_rows():
    person_id = f"signal-patch-{uuid.uuid4().hex[:8]}"
    artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"
    ai_signal_id = f"signal-{uuid.uuid4().hex[:8]}"
    legacy_id = f"legacy-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Signal Patcher", now, now),
        )
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, channel, raw_content, raw_content_or_path,
                source_name, source_type, input_type, input_type_confidence, profile_match_state,
                requires_confirmation, duplicate_hash, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                "note",
                "Manual note",
                "Manual note",
                "manual.txt",
                "manual",
                "manual_note",
                1.0,
                "confirmed",
                0,
                f"dup-{artifact_id}",
                "processed",
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, included_in_brief, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ai_signal_id,
                artifact_id,
                person_id,
                person_id,
                "business_focus",
                "business_focus",
                "AI signal text",
                "AI signal text",
                "AI signal text",
                3,
                0.6,
                "draft",
                "pending_review",
                "Unclear",
                0.5,
                0.55,
                0.8,
                0.5,
                0.5,
                1,
                now,
                now,
            ),
        )
        await db.execute(
            "INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, status, created_at) VALUES (?,?,?,?,?,?,?)",
            (legacy_id, person_id, "family_personal", "Legacy signal text", 3, "draft", now),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        legacy_response = client.patch(
            f"/api/ai/signals/legacy:{legacy_id}/status",
            json={"action": "approve", "category": "obe_focus", "text": "Legacy signal updated"},
        )
        ai_response = client.patch(
            f"/api/ai/signals/{ai_signal_id}/status",
            json={"action": "promote", "included_in_brief": False, "status": "approved"},
        )
        archived_response = client.patch(
            f"/api/ai/signals/{ai_signal_id}/status",
            json={"status": "archived"},
        )
    finally:
        client.close()

    assert legacy_response.status_code == 200
    assert ai_response.status_code == 200
    assert archived_response.status_code == 200

    async def verify(db):
        async with db.execute(
            "SELECT topic, intel_text, status FROM TOPIC_INTELLIGENCE WHERE intel_id = ?",
            (legacy_id,),
        ) as cursor:
            legacy_row = await cursor.fetchone()
        async with db.execute(
            "SELECT status, review_state, included_in_brief, importance_score FROM AI_SIGNAL WHERE signal_id = ?",
            (ai_signal_id,),
        ) as cursor:
            ai_row = await cursor.fetchone()
        return dict(legacy_row), dict(ai_row)

    legacy_row, ai_row = asyncio.run(run_read(verify))
    assert legacy_row["topic"] == "obe_focus"
    assert legacy_row["intel_text"] == "Legacy signal updated"
    assert legacy_row["status"] == "approved"
    assert ai_row["status"] == "archived"
    assert ai_row["review_state"] == "pending_review"
    assert ai_row["included_in_brief"] == 0
    assert ai_row["importance_score"] > 0.55


def test_person_history_filters_operational_noise_and_same_company_relationships_are_org_peers():
    person_id = f"history-person-{uuid.uuid4().hex[:8]}"
    colleague_id = f"history-colleague-{uuid.uuid4().hex[:8]}"
    artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, company_name_raw, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, "Primary Person", "Shared Co", now, now),
        )
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, company_name_raw, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (colleague_id, "Colleague Person", "Shared Co", now, now),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (f"chat-{person_id}", person_id, "chat", "please use this for the profile", "please use this for the profile", now, now),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, media_url, created_at, interaction_at) VALUES (?,?,?,?,?,?,?,?)",
            (f"img-{person_id}", person_id, "screenshot", "Image uploaded: headshot.png", "Headshot only", "/uploads/headshot.png", now, now),
        )
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, source_interaction_id, channel, raw_content, raw_content_or_path,
                media_url, source_name, source_type, input_type, input_type_confidence, profile_match_state,
                requires_confirmation, duplicate_hash, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                f"img-{person_id}",
                "screenshot",
                "Image uploaded: headshot.png",
                "Image uploaded: headshot.png",
                "/uploads/headshot.png",
                "headshot.png",
                "image",
                "profile_picture",
                0.99,
                "confirmed",
                1,
                f"dup-{artifact_id}",
                "processed",
                now,
                now,
            ),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (f"email-{person_id}", person_id, "email", "Discussed 2026 priorities", "Discussed 2026 priorities", now, "2026-02-01T10:00:00Z"),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["history"]) == 1
    assert payload["history"][0]["channel"] == "email"
    assert len(payload["system_activity"]) == 2
    assert payload["relationships"][0]["relationship_type"] == "org_peer"
    assert payload["relationships"][0]["link_basis"] == "same_company"


def test_whatsapp_screenshot_surfaces_as_whatsapp_and_conversational_fragments_are_filtered():
    person_id = f"wa-intel-{uuid.uuid4().hex[:8]}"
    artifact_id = f"artifact-{uuid.uuid4().hex[:8]}"
    useful_signal_id = f"signal-{uuid.uuid4().hex[:8]}"
    noisy_signal_id = f"signal-{uuid.uuid4().hex[:8]}"
    transcript_interaction_id = f"interaction-{uuid.uuid4().hex[:8]}"
    now = "2026-03-11T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "WhatsApp Contact", now, now),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (
                transcript_interaction_id,
                person_id,
                "screenshot",
                "[14:26, 3/10/2026] Brian Schofield: The second batch are midway with a decent proportion of imported products which are not yet on site and sourcing alternatives means somebody will need to pay twice. Depends on the contract. [14:53, 3/10/2026] Brian Schofield: Only idiots will play hardball, if you want your project handed over you will need to pay. You may do a deal and pay 50% but also depends on the contract.",
                "A WhatsApp conversation discussing project management challenges, material supply issues, and cost negotiations in construction.",
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, channel, raw_content, raw_content_or_path,
                source_interaction_id, source_name, source_type, input_type, input_type_confidence, profile_match_state,
                requires_confirmation, duplicate_hash, status, extracted_text, extracted_metadata_json,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                "screenshot",
                "WhatsApp screenshot",
                "WhatsApp screenshot",
                transcript_interaction_id,
                "wa.png",
                "image",
                "screenshot",
                0.95,
                "confirmed",
                0,
                f"dup-{artifact_id}",
                "processed",
                "Brian last seen today at 06:06",
                json.dumps({"screen_context": "whatsapp_chat", "source_app": "whatsapp"}),
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, business_subtopic, included_in_brief, source_interaction_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                useful_signal_id,
                artifact_id,
                person_id,
                person_id,
                "business_focus",
                "business_focus",
                    "Developer payment decisions will depend on contract terms and material supply clarity.",
                    "Developer payment decisions will depend on contract terms and material supply clarity.",
                    "developer payment decisions will depend on contract terms and material supply clarity",
                    4,
                    0.82,
                "approved",
                "approved",
                "Neutral",
                0.8,
                0.72,
                    0.8,
                    0.75,
                    0.71,
                    "commercial_position",
                    1,
                    transcript_interaction_id,
                    now,
                    now,
                ),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE
            (intel_id, person_id, topic, intel_text, confidence, source_interaction_id, status, source_snippet, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                f"legacy-{artifact_id}"[:12],
                person_id,
                "business_focus",
                "Discussion on project completion, materials, and cost management strategies.",
                1,
                transcript_interaction_id,
                "draft",
                "Discussion on project completion, materials, and cost management strategies.",
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, included_in_brief, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                noisy_signal_id,
                artifact_id,
                person_id,
                person_id,
                "recruitment_talent",
                "recruitment_talent",
                "have i told you that i love you LOL - too many a-holes.",
                "have i told you that i love you LOL - too many a-holes.",
                "have i told you that i love you LOL - too many a-holes.",
                4,
                0.78,
                "approved",
                "approved",
                "Mixed",
                0.7,
                0.68,
                0.8,
                0.45,
                0.4,
                1,
                now,
                now,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/intelligence")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["business_focus"][0]["display_channel"] == "whatsapp"
    assert payload["business_focus"][0]["text"].startswith("Developer payment decisions")
    assert len(payload["business_focus"]) == 1
    assert payload["business_focus"][0]["business_subtopic"] == "commercial_position"
    assert payload["business_focus"][0]["business_subtopic_label"] == "Commercial Position"
    assert payload["business_focus"][0]["supporting_context"]
    assert payload["business_focus"][0]["supporting_context"] != payload["business_focus"][0]["text"]
    assert "somebody will need to pay twice" in payload["business_focus"][0]["supporting_context"].lower()
    assert payload["recruitment_talent"] == []


def test_persist_interaction_does_not_create_legacy_topic_rows():
    person_id = f"persist-clean-{uuid.uuid4().hex[:8]}"
    interaction_id = f"interaction-{uuid.uuid4().hex[:8]}"
    now = "2026-03-12T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Persist Clean", now, now),
        )

    asyncio.run(run_write(setup))

    async def persist(db):
        return await _persist_interaction(
            db,
            interaction_id,
            person_id,
            "note",
            "James is looking to hire a new CTO soon.",
            {
                "summary": "James is planning a CTO hire.",
                "action_items": ["Follow up next week"],
                "topics": ["cto", "hiring"],
                "sentiment": "Neutral",
                "topic_nuggets": [
                    {
                        "topic": "recruitment_talent",
                        "text": "Looking to hire a new CTO for JLL soon.",
                        "snippet": "Looking to hire a new CTO for JLL soon.",
                        "confidence": 0.6,
                    }
                ],
                "success_metrics": {"rating": 3, "engagement_value": 65, "is_strategic": 1, "tags": ["recruitment_lead"]},
            },
            now,
            now,
        )

    asyncio.run(run_write(persist))

    async def load_counts(db):
        async with db.execute("SELECT COUNT(*) AS count FROM TOPIC_INTELLIGENCE WHERE source_interaction_id = ?", (interaction_id,)) as cursor:
            legacy_count = (await cursor.fetchone())["count"]
        async with db.execute("SELECT COUNT(*) AS count FROM TASK WHERE source_interaction_id = ?", (interaction_id,)) as cursor:
            task_count = (await cursor.fetchone())["count"]
        async with db.execute("SELECT summary FROM INTERACTION WHERE interaction_id = ?", (interaction_id,)) as cursor:
            interaction = await cursor.fetchone()
        return legacy_count, task_count, dict(interaction)

    legacy_count, task_count, interaction = asyncio.run(run_read(load_counts))

    assert legacy_count == 0
    assert task_count == 1
    assert interaction["summary"] == "James is planning a CTO hire."


def test_delete_interaction_removes_downstream_ai_context():
    person_id = f"delete-person-{uuid.uuid4().hex[:8]}"
    interaction_id = f"delete-interaction-{uuid.uuid4().hex[:8]}"
    artifact_id = f"delete-artifact-{uuid.uuid4().hex[:8]}"
    signal_id = f"delete-signal-{uuid.uuid4().hex[:8]}"
    now = "2026-03-12T00:00:00Z"

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Delete Test Contact", now, now),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (interaction_id, person_id, "note", "Delete this interaction", "Delete this interaction", now, now),
        )
        await db.execute(
            """
            INSERT INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, source_interaction_id, channel, raw_content,
                raw_content_or_path, source_name, source_type, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                interaction_id,
                "note",
                "Delete this interaction",
                "Delete this interaction",
                "manual_note.txt",
                "text",
                "processed",
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, included_in_brief, source_interaction_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                signal_id,
                artifact_id,
                person_id,
                person_id,
                "family_personal",
                "family_personal",
                "A follow-up coffee was suggested.",
                "A follow-up coffee was suggested.",
                "A follow-up coffee was suggested.",
                4,
                0.8,
                "approved",
                "approved",
                1,
                interaction_id,
                now,
                now,
            ),
        )
        await db.execute(
            "INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, details_json, created_at) VALUES (?,?,?,?,?,?)",
            (f"fb-{uuid.uuid4().hex[:8]}", "signal", signal_id, "approval", "{}", now),
        )
        await db.execute(
            """
            INSERT INTO TOPIC_INTELLIGENCE
            (intel_id, person_id, topic, intel_text, confidence, source_interaction_id, status, source_snippet, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                f"intel-{uuid.uuid4().hex[:8]}"[:12],
                person_id,
                "family_personal",
                "A follow-up coffee was suggested.",
                4,
                interaction_id,
                "approved",
                "A follow-up coffee was suggested.",
                now,
            ),
        )
        await db.execute(
            "INSERT INTO TASK (task_id, person_id, task_text, status, source_interaction_id, created_at) VALUES (?,?,?,?,?,?)",
            (f"task-{uuid.uuid4().hex[:8]}"[:12], person_id, "Follow up", "open", interaction_id, now),
        )
        await db.execute(
            """
            INSERT INTO AI_JOB (
                job_id, person_id, interaction_id, job_type, status, payload_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (f"job-{uuid.uuid4().hex[:8]}", person_id, interaction_id, "signal_extraction", "completed", "{}", now, now),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.delete(f"/api/interactions/{interaction_id}")
    finally:
        client.close()

    assert response.status_code == 200

    async def verify(db):
        counts = {}
        checks = (
            ("interaction", "SELECT COUNT(*) AS count FROM INTERACTION WHERE interaction_id = ?", (interaction_id,)),
            ("artifact", "SELECT COUNT(*) AS count FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact_id,)),
            ("signal", "SELECT COUNT(*) AS count FROM AI_SIGNAL WHERE signal_id = ?", (signal_id,)),
            ("feedback", "SELECT COUNT(*) AS count FROM AI_FEEDBACK WHERE target_type='signal' AND target_id = ?", (signal_id,)),
            ("legacy", "SELECT COUNT(*) AS count FROM TOPIC_INTELLIGENCE WHERE source_interaction_id = ?", (interaction_id,)),
            ("task", "SELECT COUNT(*) AS count FROM TASK WHERE source_interaction_id = ?", (interaction_id,)),
            ("job", "SELECT COUNT(*) AS count FROM AI_JOB WHERE interaction_id = ?", (interaction_id,)),
        )
        for label, query, params in checks:
            async with db.execute(query, params) as cursor:
                row = await cursor.fetchone()
            counts[label] = row["count"]
        return counts

    counts = asyncio.run(run_read(verify))
    assert counts == {
        "interaction": 0,
        "artifact": 0,
        "signal": 0,
        "feedback": 0,
        "legacy": 0,
        "task": 0,
        "job": 0,
    }


def test_semantic_duplicate_ai_signals_collapse_in_profile_intelligence():
    person_id = f"dupe-collapse-{uuid.uuid4().hex[:8]}"
    artifact_one = f"artifact-{uuid.uuid4().hex[:8]}"
    artifact_two = f"artifact-{uuid.uuid4().hex[:8]}"
    interaction_one = f"interaction-{uuid.uuid4().hex[:8]}"
    interaction_two = f"interaction-{uuid.uuid4().hex[:8]}"
    now = "2026-03-12T00:00:00Z"
    shared_context = (
        "I left UAE early hours of Monday morning, as my father in law passed away in Serbia on Sunday, "
        "very suddenly. Funeral is tomorrow and I will try travel back on Saturday."
    )

    async def setup(db):
        await db.execute(
            "INSERT INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, "Duplicate Collapse", now, now),
        )
        for artifact_id, interaction_id in ((artifact_one, interaction_one), (artifact_two, interaction_two)):
            await db.execute(
                "INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
                (interaction_id, person_id, "screenshot", shared_context, "Family bereavement update", now, now),
            )
            await db.execute(
                """
                INSERT INTO AI_ARTIFACT (
                    artifact_id, person_id, profile_id_nullable, source_interaction_id, channel, raw_content, raw_content_or_path,
                    source_name, source_type, input_type, input_type_confidence, profile_match_state,
                    requires_confirmation, duplicate_hash, status, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    artifact_id,
                    person_id,
                    person_id,
                    interaction_id,
                    "screenshot",
                    shared_context,
                    shared_context,
                    f"{artifact_id}.txt",
                    "text",
                    "screenshot",
                    0.9,
                    "confirmed",
                    0,
                    f"dup-{artifact_id}",
                    "processed",
                    now,
                    now,
                ),
            )

        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, included_in_brief, source_interaction_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"signal-{uuid.uuid4().hex[:8]}",
                artifact_one,
                person_id,
                person_id,
                "family_personal",
                "family_personal",
                "Contact is dealing with the sudden passing of a father-in-law in Serbia and will return after the funeral.",
                "Contact is dealing with the sudden passing of a father-in-law in Serbia and will return after the funeral.",
                shared_context,
                4,
                0.82,
                "approved",
                "approved",
                "Mixed",
                0.8,
                0.78,
                0.6,
                0.5,
                0.5,
                1,
                interaction_one,
                now,
                now,
            ),
        )
        await db.execute(
            """
            INSERT INTO AI_SIGNAL (
                signal_id, artifact_id, person_id, profile_id, category, primary_category, content, signal_text,
                source_snippet, confidence, confidence_score, status, review_state, signal_sentiment,
                signal_sentiment_confidence, importance_score, source_strength,
                section_hypothesis_fit_score, overall_hypothesis_fit_score, included_in_brief, source_interaction_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"signal-{uuid.uuid4().hex[:8]}",
                artifact_two,
                person_id,
                person_id,
                "family_personal",
                "family_personal",
                "Father-in-law passed away suddenly in Serbia and the contact travelled for the funeral before returning to the UAE.",
                "Father-in-law passed away suddenly in Serbia and the contact travelled for the funeral before returning to the UAE.",
                shared_context,
                4,
                0.8,
                "approved",
                "approved",
                "Mixed",
                0.8,
                0.7,
                0.6,
                0.5,
                0.5,
                1,
                interaction_two,
                now,
                now,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/intelligence")
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["family_personal"]) == 1
