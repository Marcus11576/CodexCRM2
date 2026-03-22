import asyncio
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.database import run_write
from backend.main import app
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = "password123") -> TestClient:
    email = f"relationships-{uuid.uuid4().hex[:8]}@example.com"
    existing = asyncio.run(get_user_by_email(email))
    if not existing:
        asyncio.run(create_user(email, "Relationships Audit User", password, role="admin"))
    client = TestClient(app, base_url=TEST_BASE_URL)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


async def _delete_people(person_ids: list[str]):
    if not person_ids:
        return
    placeholders = ",".join("?" for _ in person_ids)

    async def cleanup(db):
        await db.execute(f"DELETE FROM INTERACTION WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(f"DELETE FROM PERSON WHERE person_id IN ({placeholders})", tuple(person_ids))

    await run_write(cleanup)


def test_get_person_includes_same_company_relationships():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"rel-person-{uuid.uuid4().hex[:8]}"
    colleague_id = f"rel-colleague-{uuid.uuid4().hex[:8]}"
    outsider_id = f"rel-outsider-{uuid.uuid4().hex[:8]}"
    created_people = [person_id, colleague_id, outsider_id]

    async def setup(db):
        people = [
            (person_id, "Primary Contact", "Director", "Acme Advisory"),
            (colleague_id, "Shared Company Contact", "Principal", "ACME ADVISORY"),
            (outsider_id, "Other Company Contact", "Manager", "Different Group"),
        ]
        for pid, full_name, title, company in people:
            await db.execute(
                """
                INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, created_at, last_updated_at)
                VALUES (?,?,?,?,?,?)
                """,
                (pid, full_name, title, company, created_at, created_at),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_delete_people(created_people))

    assert response.status_code == 200
    relationships = {item["person_id"]: item for item in payload["relationships"]}
    assert colleague_id in relationships
    assert outsider_id not in relationships
    assert relationships[colleague_id]["relationship_type"] == "org_peer"
    assert relationships[colleague_id]["same_company"] is True
    assert relationships[colleague_id]["link_basis"] == "same_company"


def test_relationship_endpoint_detects_friend_and_referral_mentions():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"rel-mentions-{uuid.uuid4().hex[:8]}"
    friend_id = f"rel-friend-{uuid.uuid4().hex[:8]}"
    referral_id = f"rel-referral-{uuid.uuid4().hex[:8]}"
    created_people = [person_id, friend_id, referral_id]

    async def setup(db):
        people = [
            (person_id, "Target Contact", "Director", "Orbit Projects"),
            (friend_id, "Aisha Rahman", "Advisor", "North Star"),
            (referral_id, "Omar Khan", "Lead", "Blue Ridge"),
        ]
        for pid, full_name, title, company in people:
            await db.execute(
                """
                INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, created_at, last_updated_at)
                VALUES (?,?,?,?,?,?)
                """,
                (pid, full_name, title, company, created_at, created_at),
            )

        interactions = [
            ("Aisha Rahman is a close friend from university.", created_at),
            ("Omar Khan was referred by a trusted client for a live role.", created_at),
        ]
        for raw_text, interaction_at in interactions:
            await db.execute(
                """
                INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    f"rel-interaction-{uuid.uuid4().hex[:8]}",
                    person_id,
                    "note",
                    raw_text,
                    raw_text,
                    interaction_at,
                    interaction_at,
                ),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/relationships")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_delete_people(created_people))

    assert response.status_code == 200
    relationships = {item["person_id"]: item for item in payload["relationships"]}
    assert relationships[friend_id]["relationship_type"] == "friend"
    assert relationships[friend_id]["mentioned_in_inputs"] is True
    assert relationships[referral_id]["relationship_type"] == "referral"
    assert relationships[referral_id]["mentioned_in_inputs"] is True


def test_relationship_endpoint_uses_factual_chat_mentions_but_ignores_operational_chat():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"rel-chat-{uuid.uuid4().hex[:8]}"
    mentioned_id = f"rel-paul-{uuid.uuid4().hex[:8]}"
    created_people = [person_id, mentioned_id]

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (person_id, "Target Contact", "Director", "Orbit Projects", created_at, created_at),
        )
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, title_current, company_name_raw, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (mentioned_id, "Paul Whelan", "Chief Executive Officer", "Dutco Construction", created_at, created_at),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"rel-chat-{uuid.uuid4().hex[:8]}",
                person_id,
                "chat",
                "Spoke this morning. He is talking to Paul Whelan today and will share feedback after the meeting.",
                "Spoke this morning. He is talking to Paul Whelan today and will share feedback after the meeting.",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"rel-chat-{uuid.uuid4().hex[:8]}",
                person_id,
                "chat",
                "Please use this for the profile photo.",
                "Please use this for the profile photo.",
                created_at,
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/people/{person_id}/relationships")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_delete_people(created_people))

    assert response.status_code == 200
    relationships = {item["person_id"]: item for item in payload["relationships"]}
    assert mentioned_id in relationships
    assert relationships[mentioned_id]["relationship_type"] == "mentioned"
    assert "Paul Whelan" in (relationships[mentioned_id]["mention_excerpt"] or "")
