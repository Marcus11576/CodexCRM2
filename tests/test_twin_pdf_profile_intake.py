import asyncio
import json
import uuid

from fastapi.testclient import TestClient

from backend.database import run_read
from backend.main import app
from backend.routers import compat_v1
from backend.services import ai_service
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = "password123") -> TestClient:
    email = f"twin-pdf-{uuid.uuid4().hex[:8]}@example.com"
    existing = asyncio.run(get_user_by_email(email))
    if not existing:
        asyncio.run(create_user(email, "Twin PDF Audit User", password, role="admin"))
    client = TestClient(app, base_url=TEST_BASE_URL)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


def test_twin_upload_pdf_creates_structured_profile(monkeypatch):
    unique = uuid.uuid4().hex[:8]
    suffix = "".join(chr(65 + (int(ch, 16) % 26)) for ch in unique[:5])
    full_name = f"Jordan Intake {suffix}"
    extracted_text = (
        f"{full_name}\n"
        "Senior Commercial Director\n"
        "ACME Build Group\n"
        "Email: jordan.intake@example.com\n"
        "Mobile: +971 55 123 4567\n"
        "LinkedIn: linkedin.com/in/jordan-intake\n"
        "Experience\n"
        "- Senior Commercial Director, ACME Build Group, 2021 - Present\n"
        "- Commercial Manager, NorthGate Developments, 2017 - 2021\n"
    )

    async def fake_extract_document_profile(_text):
        return {
            "full_name": full_name,
            "title_current": "Senior Commercial Director",
            "company_name_raw": "ACME Build Group",
            "email_primary": "jordan.intake@example.com",
            "phone_primary": "+971551234567",
            "linkedin_url": "https://linkedin.com/in/jordan-intake",
            "career_summary": "Commercial leader across major mixed-use and infrastructure projects.",
            "key_professional_notes": "Strong on contract strategy, procurement, and handover negotiations.",
            "employment_history": [
                {
                    "title": "Senior Commercial Director",
                    "company": "ACME Build Group",
                    "start_date": "2021-01",
                    "end_date": "",
                    "location": "Dubai",
                    "description": "Leads project commercial strategy and delivery negotiations.",
                },
                {
                    "title": "Commercial Manager",
                    "company": "NorthGate Developments",
                    "start_date": "2017-01",
                    "end_date": "2021-01",
                    "location": "Abu Dhabi",
                    "description": "Managed contracts, claims, and procurement frameworks.",
                },
            ],
        }

    monkeypatch.setattr(compat_v1.settings, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(ai_service, "extract_text_from_file", lambda _path: extracted_text)
    monkeypatch.setattr(ai_service, "extract_document_profile", fake_extract_document_profile)

    client = login_client()
    try:
        response = client.post(
            "/api/twin/upload_pdf",
            files={"file": ("profile.pdf", b"%PDF-1.4\n%fake", "application/pdf")},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "created"
    person_id = payload["data"]["person_id"]

    async def _load(db):
        async with db.execute(
            """
            SELECT full_name, title_current, company_name_raw, email_primary, phone_primary, linkedin_url,
                   career_summary, key_professional_notes, employment_history
            FROM PERSON
            WHERE person_id = ?
            """,
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    person = asyncio.run(run_read(_load))
    assert person is not None
    assert person["full_name"] == full_name
    assert person["title_current"] == "Senior Commercial Director"
    assert person["company_name_raw"] == "ACME Build Group"
    assert person["email_primary"] == "jordan.intake@example.com"
    assert person["phone_primary"] == "+971551234567"
    assert person["linkedin_url"] == "https://linkedin.com/in/jordan-intake"
    assert "Commercial leader" in person["career_summary"]
    assert "contract strategy" in person["key_professional_notes"]
    employment_history = json.loads(person["employment_history"] or "[]")
    assert len(employment_history) == 2
    assert employment_history[0]["company"] == "ACME Build Group"


def test_twin_upload_pdf_fallback_name_ignores_heading_lines(monkeypatch):
    unique = uuid.uuid4().hex[:8]
    suffix = "".join(chr(65 + (int(ch, 16) % 26)) for ch in unique[:4])
    expected_name = f"Harper Quill {suffix}"
    extracted_text = (
        "Contact\n"
        "harper.quill@example.com\n"
        "Top Skills\n"
        "Real Estate Development\n"
        "Certifications\n"
        "Royal Institution of Chartered Surveyors\n"
        f"{expected_name}, MRICS\n"
        "Executive Director of Development at Miral\n"
        "Abu Dhabi Emirate, United Arab Emirates\n"
        "Summary\n"
        "Commercial and development leader across UAE mixed-use programs.\n"
        "Experience\n"
        "Miral\n"
    )

    async def broken_extract_document_profile(_text):
        raise RuntimeError("simulated extraction failure")

    monkeypatch.setattr(compat_v1.settings, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(ai_service, "extract_text_from_file", lambda _path: extracted_text)
    monkeypatch.setattr(ai_service, "extract_document_profile", broken_extract_document_profile)

    client = login_client()
    try:
        response = client.post(
            "/api/twin/upload_pdf",
            files={"file": ("profile.pdf", b"%PDF-1.4\n%fake", "application/pdf")},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "created"
    person_id = payload["data"]["person_id"]

    async def _load(db):
        async with db.execute(
            "SELECT full_name, title_current, company_name_raw FROM PERSON WHERE person_id = ?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    person = asyncio.run(run_read(_load))
    assert person is not None
    assert person["full_name"] == expected_name
    assert person["full_name"] != "Top Skills"
    assert "Executive Director" in str(person["title_current"] or "")


def test_twin_upload_pdf_rejects_heading_only_documents(monkeypatch):
    extracted_text = (
        "Contact\n"
        "Top Skills\n"
        "Summary\n"
        "Experience\n"
        "Certifications\n"
    )

    async def broken_extract_document_profile(_text):
        raise RuntimeError("simulated extraction failure")

    monkeypatch.setattr(compat_v1.settings, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(ai_service, "extract_text_from_file", lambda _path: extracted_text)
    monkeypatch.setattr(ai_service, "extract_document_profile", broken_extract_document_profile)

    client = login_client()
    try:
        response = client.post(
            "/api/twin/upload_pdf",
            files={"file": ("profile.pdf", b"%PDF-1.4\n%fake", "application/pdf")},
        )
    finally:
        client.close()

    assert response.status_code == 400
    payload = response.json()
    assert "identify a contact name" in str(payload.get("detail", "")).lower()


def test_twin_upload_pdf_replaces_skill_phrase_name_with_real_name(monkeypatch):
    extracted_text = (
        "Contact\n"
        "www.linkedin.com/in/mandy-van-de-velde-00627030\n"
        "Top Skills\n"
        "Strategy Execution\n"
        "Business Transformation\n"
        "Leadership\n"
        "Mandy van de Velde\n"
        "Senior Vice President IDO | Board Member | Former McKinsey & Shell\n"
        "Dubai, United Arab Emirates\n"
        "Summary\n"
        "Transformation and value creation leader across public and private sectors.\n"
    )

    async def biased_extract_document_profile(_text):
        return {
            "full_name": "Business Transformation",
            "title_current": "Senior Vice President",
            "company_name_raw": "Investment and Development Office (IDO) - Ras Al Khaimah",
            "email_primary": "",
            "phone_primary": "",
            "linkedin_url": "https://www.linkedin.com/in/mandy-van-de-velde-00627030",
            "career_summary": "Transformation and value creation leader.",
            "key_professional_notes": "",
            "employment_history": [],
        }

    monkeypatch.setattr(compat_v1.settings, "OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(ai_service, "extract_text_from_file", lambda _path: extracted_text)
    monkeypatch.setattr(ai_service, "extract_document_profile", biased_extract_document_profile)

    client = login_client()
    try:
        response = client.post(
            "/api/twin/upload_pdf",
            files={"file": ("profile.pdf", b"%PDF-1.4\n%fake", "application/pdf")},
        )
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "created"
    person_id = payload["data"]["person_id"]

    async def _load(db):
        async with db.execute(
            "SELECT full_name, title_current, company_name_raw FROM PERSON WHERE person_id = ?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return dict(row) if row else None

    person = asyncio.run(run_read(_load))
    assert person is not None
    assert person["full_name"] == "Mandy van de Velde"
    assert person["full_name"] != "Business Transformation"
