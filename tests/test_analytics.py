import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.database import run_write
from backend.main import app
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = "password123") -> TestClient:
    email = f"analytics-{uuid.uuid4().hex[:8]}@example.com"
    existing = asyncio.run(get_user_by_email(email))
    if not existing:
        asyncio.run(create_user(email, "Analytics Audit User", password, role="admin"))
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


def test_profile_growth_excludes_bulk_batches_and_synthetic_records():
    today = datetime.now(timezone.utc).date().isoformat()
    base_client = login_client()
    try:
        base_data = base_client.get(f"/api/analytics/profile-growth-stats?start_date={today}&end_date={today}").json()
    finally:
        base_client.close()

    base_total = base_data["total_profiles"]
    base_excluded = base_data["excluded_profiles"]
    base_hpc = next((row["count"] for row in base_data["stats"] if row["cat"] == "HPC"), 0)

    bulk_created_at = datetime.now(timezone.utc).replace(microsecond=123456).isoformat()
    real_created_at = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    synthetic_created_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()

    real_person_id = f"analytics-real-{uuid.uuid4().hex[:8]}"
    synthetic_person_id = f"analytics-synth-{uuid.uuid4().hex[:8]}"
    bulk_person_ids = [f"analytics-bulk-{uuid.uuid4().hex[:8]}" for _ in range(12)]
    created_people = [real_person_id, synthetic_person_id, *bulk_person_ids]

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, email_primary, cat, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                real_person_id,
                "Analytics Genuine Contact",
                f"genuine.{uuid.uuid4().hex[:6]}@company.com",
                "HPC",
                real_created_at,
                real_created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, email_primary, cat, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                synthetic_person_id,
                "Analytics Sample Contact",
                "sample@example.com",
                "HPC",
                synthetic_created_at,
                synthetic_created_at,
            ),
        )
        for person_id in bulk_person_ids:
            await db.execute(
                """
                INSERT INTO PERSON (person_id, full_name, email_primary, cat, created_at, last_updated_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    person_id,
                    f"Analytics Batch {person_id[-4:]}",
                    f"{person_id[-4:]}@company.com",
                    "HPC",
                    bulk_created_at,
                    bulk_created_at,
                ),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        data = client.get(f"/api/analytics/profile-growth-stats?start_date={today}&end_date={today}").json()
    finally:
        client.close()
        asyncio.run(_delete_people(created_people))

    hpc_count = next((row["count"] for row in data["stats"] if row["cat"] == "HPC"), 0)
    assert data["total_profiles"] == base_total + 1
    assert hpc_count == base_hpc + 1
    assert data["excluded_profiles"] >= base_excluded + 13


def test_effort_stats_normalizes_channels_and_compares_previous_period():
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=2)).isoformat()
    end = today.isoformat()
    current_day = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    previous_day = current_day - timedelta(days=3)

    person_id = f"analytics-effort-{uuid.uuid4().hex[:8]}"
    interaction_ids = [f"i-{uuid.uuid4().hex[:8]}" for _ in range(6)]

    async def setup(db):
        created_at = (current_day - timedelta(days=10)).isoformat()
        await db.execute(
            """
            INSERT INTO PERSON (person_id, full_name, email_primary, cat, created_at, last_updated_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                person_id,
                "Analytics Effort Contact",
                f"effort.{uuid.uuid4().hex[:6]}@company.com",
                "HPC",
                created_at,
                created_at,
            ),
        )
        interactions = [
            (interaction_ids[0], "Email", current_day.isoformat()),
            (interaction_ids[1], "Mobile", (current_day + timedelta(hours=1)).isoformat()),
            (interaction_ids[2], "Teams", (current_day + timedelta(hours=2)).isoformat()),
            (interaction_ids[3], "Whatsapp", (current_day + timedelta(hours=3)).isoformat()),
            (interaction_ids[4], "system_audit", (current_day + timedelta(hours=4)).isoformat()),
            (interaction_ids[5], "email", previous_day.isoformat()),
        ]
        for interaction_id, channel, interaction_at in interactions:
            await db.execute(
                """
                INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    interaction_id,
                    person_id,
                    channel,
                    channel,
                    channel,
                    interaction_at,
                    interaction_at,
                ),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/analytics/effort-stats?start_date={start}&end_date={end}&cat=HPC")
        data = response.json()
    finally:
        client.close()
        asyncio.run(_delete_people([person_id]))

    assert response.status_code == 200
    assert data["totals"] == {"email": 1, "call": 1, "meeting": 1, "whatsapp": 1}
    assert data["comparison_totals"] == {"email": 1}
