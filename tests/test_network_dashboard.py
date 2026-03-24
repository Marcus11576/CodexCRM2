import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import backend.routers.network_lab as network_lab_module
from backend.database import run_write
from backend.main import app
from backend.routers.network_lab import _build_profile_evidence_inputs
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = "password123") -> TestClient:
    email = f"network-{uuid.uuid4().hex[:8]}@example.com"
    existing = asyncio.run(get_user_by_email(email))
    if not existing:
        asyncio.run(create_user(email, "Network Dashboard User", password, role="admin"))
    client = TestClient(app, base_url=TEST_BASE_URL)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


async def _cleanup_records(person_ids: list[str]):
    if not person_ids:
        return
    placeholders = ",".join("?" for _ in person_ids)

    async def cleanup(db):
        await db.execute(f"DELETE FROM RELATIONSHIP_SITUATION_EVENT WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(f"DELETE FROM RELATIONSHIP_SITUATION WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(f"DELETE FROM ENDURING_MEMORY WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(
            f"DELETE FROM MARKET_INTEL WHERE linked_people_json LIKE '%' || ? || '%' OR linked_people_json LIKE '%' || ? || '%'",
            tuple(person_ids[:2] if len(person_ids) >= 2 else person_ids + person_ids),
        )
        await db.execute(f"DELETE FROM INTERPRETED_INTERACTION WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(f"DELETE FROM INTERACTION WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(f"DELETE FROM TASK WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(
            f"DELETE FROM COMPANY_OPPORTUNITY WHERE company_name_raw IN (SELECT company_name_raw FROM PERSON WHERE person_id IN ({placeholders}))",
            tuple(person_ids),
        )
        await db.execute(f"DELETE FROM PERSON_OPPORTUNITY WHERE person_id IN ({placeholders})", tuple(person_ids))
        await db.execute(f"DELETE FROM PERSON WHERE person_id IN ({placeholders})", tuple(person_ids))

    await run_write(cleanup)


def test_network_feed_assigns_phase_one_queues_and_overlays():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    act_now_id = f"net-act-{uuid.uuid4().hex[:8]}"
    maintain_id = f"net-main-{uuid.uuid4().hex[:8]}"
    preserve_id = f"net-pres-{uuid.uuid4().hex[:8]}"
    monitor_id = f"net-mon-{uuid.uuid4().hex[:8]}"
    reactivated_id = f"net-react-{uuid.uuid4().hex[:8]}"
    person_ids = [act_now_id, maintain_id, preserve_id, monitor_id, reactivated_id]

    async def setup(db):
        people = [
            (
                act_now_id,
                "Act Now Contact",
                "Director",
                "Alpha Projects",
                "TGT",
                "Hot",
                "overdue",
                None,
                None,
                None,
                (now - timedelta(days=40)).isoformat(),
            ),
            (
                maintain_id,
                "Maintain Contact",
                "Principal",
                "Beta Partners",
                "OBE M",
                "Warm",
                "soon",
                (now + timedelta(days=10)).date().isoformat(),
                None,
                None,
                (now - timedelta(days=5)).isoformat(),
            ),
            (
                preserve_id,
                "Preserve Contact",
                "Associate",
                "Gamma Advisory",
                "GEN",
                "Cold",
                None,
                None,
                None,
                None,
                (now - timedelta(days=20)).isoformat(),
            ),
            (
                monitor_id,
                "Monitor Contact",
                "Manager",
                "Delta Holdings",
                "GEN",
                None,
                None,
                None,
                None,
                None,
                None,
            ),
            (
                reactivated_id,
                "Reactivated Contact",
                "Lead",
                "Echo Ventures",
                "EXT",
                "Warm",
                None,
                None,
                None,
                None,
                None,
            ),
        ]
        for person in people:
            await db.execute(
                """
                INSERT INTO PERSON (
                    person_id, full_name, title_current, company_name_raw, cat, contact_value,
                    meeting_status, next_contact_due_date, next_meeting_date, last_success_at,
                    last_contact_datetime, created_at, last_updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (*person, created_at, created_at),
            )

        interactions = [
            (
                f"int-{uuid.uuid4().hex[:8]}",
                preserve_id,
                "email",
                "Preserve contact had a useful exchange last month.",
                "Preserve contact had a useful exchange last month.",
                (now - timedelta(days=20)).isoformat(),
            ),
            (
                f"int-{uuid.uuid4().hex[:8]}",
                reactivated_id,
                "email",
                "Old relationship came back into motion today.",
                "Old relationship came back into motion today.",
                (now - timedelta(days=1)).isoformat(),
            ),
            (
                f"int-{uuid.uuid4().hex[:8]}",
                reactivated_id,
                "email",
                "Last touch was a while ago.",
                "Last touch was a while ago.",
                (now - timedelta(days=90)).isoformat(),
            ),
        ]
        for interaction_id, person_id, channel, raw_text, summary, interaction_at in interactions:
            await db.execute(
                """
                INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at),
            )

        await db.execute(
            """
            INSERT INTO TASK (task_id, person_id, task_text, due_date, priority, status, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"task-{uuid.uuid4().hex[:8]}",
                act_now_id,
                "Urgent follow-up required",
                (now - timedelta(days=1)).date().isoformat(),
                "high",
                "open",
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get("/api/dashboard/network-feed")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_cleanup_records(person_ids))

    assert response.status_code == 200
    assert any(item["person_id"] == act_now_id for item in payload["act_now"])
    assert any(item["person_id"] == maintain_id for item in payload["maintain"])
    assert any(item["person_id"] == preserve_id for item in payload["preserve"])
    assert any(item["person_id"] == monitor_id for item in payload["monitor"])
    assert any(
        item["person_id"] == reactivated_id
        for item in payload["act_now"] + payload["maintain"]
    )

    overlays = payload["overlays"]
    assert any(item["person_id"] == monitor_id for item in overlays["no_relationship_signal"])
    assert any(item["person_id"] == monitor_id for item in overlays["no_next_step"])
    assert any(item["person_id"] == reactivated_id for item in overlays["recently_reactivated"])
    assert any(item["person_id"] == act_now_id for item in overlays["open_task_pressure"])

    summary = payload["summary"]
    assert summary["act_now_count"] >= 1
    assert summary["monitor_count"] >= 1
    assert summary["invisible_count"] >= 1


def test_network_feed_derives_opportunity_readiness_from_live_signal_not_default_zero():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-opp-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Opportunity Signal Contact",
                "Director",
                "Signal Opportunity Group",
                "OBE M",
                "Warm",
                "T2",
                None,
                "Marcus",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO PERSON_OPPORTUNITY (
                opportunity_id, person_id, account_name, opportunity_type, stage, value_band,
                trigger_date, strategic_importance, status, owner, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"opp-{uuid.uuid4().hex[:8]}",
                person_id,
                "Signal Opportunity Group",
                "search",
                "active",
                "high",
                (now + timedelta(days=14)).date().isoformat(),
                88,
                "open",
                "Marcus",
                "Live search process",
                created_at,
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    contact = next(item for item in payload["act_now"] if item["person_id"] == person_id)
    assert contact["opportunity_readiness"] >= 70
    assert contact["network_health_score"] >= 60
    assert contact["score_band"] in {"Priority", "Act Now"}
    assert any("active linked person opportunity" in reason["text"].lower() for reason in contact["score_component_reasons"]["opportunity_readiness"])


def test_network_feed_score_spread_distinguishes_live_priority_from_fresh_covered_contact():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    priority_id = f"net-pri-{uuid.uuid4().hex[:8]}"
    covered_id = f"net-cov-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                meeting_status, network_tier, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                priority_id,
                "Priority Drift Contact",
                "Director",
                "Priority Group",
                "OBE M",
                "Hot",
                "overdue",
                "T1",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                next_contact_due_date, network_tier, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                covered_id,
                "Fresh Covered Contact",
                "Principal",
                "Covered Group",
                "GEN",
                "Warm",
                (now + timedelta(days=20)).date().isoformat(),
                "T4",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        interactions = [
            (
                f"int-{uuid.uuid4().hex[:8]}",
                priority_id,
                "email",
                "The assignment is moving and we need to close out the next step quickly.",
                "The assignment is moving and we need to close out the next step quickly.",
                (now - timedelta(days=38)).isoformat(),
            ),
            (
                f"int-{uuid.uuid4().hex[:8]}",
                covered_id,
                "email",
                "Good to stay close and keep the relationship moving.",
                "Good to stay close and keep the relationship moving.",
                (now - timedelta(days=3)).isoformat(),
            ),
        ]
        for interaction_id, person_id, channel, raw_text, summary, interaction_at in interactions:
            await db.execute(
                """
                INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?)
                """,
                (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at),
            )
        await db.execute(
            """
            INSERT INTO TASK (task_id, person_id, task_text, due_date, priority, status, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"task-{uuid.uuid4().hex[:8]}",
                priority_id,
                "Urgent next step",
                (now - timedelta(days=1)).date().isoformat(),
                "high",
                "open",
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO PERSON_OPPORTUNITY (
                opportunity_id, person_id, account_name, opportunity_type, stage, value_band,
                trigger_date, strategic_importance, status, owner, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"opp-{uuid.uuid4().hex[:8]}",
                priority_id,
                "Priority Group",
                "search",
                "active",
                "high",
                (now + timedelta(days=10)).date().isoformat(),
                92,
                "open",
                "Marcus",
                "Urgent active process",
                created_at,
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([priority_id, covered_id]))

    all_items = payload["act_now"] + payload["maintain"] + payload["preserve"] + payload["monitor"]
    priority = next(item for item in all_items if item["person_id"] == priority_id)
    covered = next(item for item in all_items if item["person_id"] == covered_id)

    assert priority["network_health_score"] >= covered["network_health_score"] + 20
    assert priority["coverage_health"] < covered["coverage_health"]
    assert priority["score_band"] in {"Priority", "Act Now"}
    assert covered["score_band"] in {"Maintain", "Monitor"}


def test_high_priority_uncovered_but_fresh_contact_stays_out_of_act_now():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-fresh-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Fresh Strategic Contact",
                "Director",
                "Fresh Group",
                "OBE M",
                "Hot",
                "T1",
                "Marcus",
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
                f"int-{uuid.uuid4().hex[:8]}",
                person_id,
                "email",
                "Good recent exchange with no immediate action needed.",
                "Good recent exchange with no immediate action needed.",
                created_at,
                (now - timedelta(days=4)).isoformat(),
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    maintain_ids = {item["person_id"] for item in payload["maintain"]}
    act_now_ids = {item["person_id"] for item in payload["act_now"]}
    assert person_id in maintain_ids
    assert person_id not in act_now_ids


def test_future_meeting_counts_as_premium_cover_for_strategic_contact():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-meet-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, relationship_owner, next_meeting_date, next_meeting_topic,
                last_contact_datetime, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Meeting Covered Contact",
                "Managing Director",
                "Meeting Group",
                "OBE M",
                "Hot",
                "T1",
                "Marcus",
                (now + timedelta(days=4)).isoformat(),
                "Quarterly catch-up",
                (now - timedelta(days=18)).isoformat(),
                created_at,
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    all_items = payload["act_now"] + payload["maintain"] + payload["preserve"] + payload["monitor"]
    item = next(entry for entry in all_items if entry["person_id"] == person_id)
    assert item["queue_reason"] == "Strategic relationship needs regular maintenance"
    assert item["cover_kind"] == "meeting"
    assert item["has_future_cover"] is True
    assert item["coverage_health"] >= 50


def test_undated_call_task_does_not_count_as_real_cover():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-undated-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, relationship_owner, last_contact_datetime, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Undated Task Contact",
                "Director",
                "Undated Group",
                "OBE M",
                "Warm",
                "T1",
                "Marcus",
                (now - timedelta(days=8)).isoformat(),
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO TASK (task_id, person_id, task_text, priority, status, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                f"task-{uuid.uuid4().hex[:8]}",
                person_id,
                "Call Mark to reconnect",
                "medium",
                "open",
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    all_items = payload["act_now"] + payload["maintain"] + payload["preserve"] + payload["monitor"]
    item = next(entry for entry in all_items if entry["person_id"] == person_id)
    assert item["cover_kind"] == "undated_task"
    assert item["has_future_cover"] is False
    assert item["primary_open_task_kind"] == "relationship_follow_up"


def test_passed_follow_up_date_without_new_evidence_requires_confirmation():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-confirm-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, relationship_owner, last_contact_datetime, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Confirmation Needed Contact",
                "Director",
                "Confirmation Group",
                "OBE M",
                "Warm",
                "T1",
                "Marcus",
                (now - timedelta(days=12)).isoformat(),
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO TASK (task_id, person_id, task_text, due_date, priority, status, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"task-{uuid.uuid4().hex[:8]}",
                person_id,
                "Arrange call about commercial gap",
                (now - timedelta(days=2)).date().isoformat(),
                "high",
                "open",
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    item = next(entry for entry in payload["act_now"] if entry["person_id"] == person_id)
    assert item["follow_up_confirmation_needed"] is True
    assert "passed" in item["queue_reason"].lower() or "outcome" in item["queue_reason"].lower()
    assert any("recorded outcome" in reason["text"].lower() for reason in item["score_reason_summary"])


def test_follow_up_confirmation_is_counted_in_dashboard_summary():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-confirmsum-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, relationship_owner, next_contact_due_date, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Confirmation Summary Contact",
                "Director",
                "Summary Group",
                "OBE M",
                "Warm",
                "T1",
                "Marcus",
                (now - timedelta(days=1)).date().isoformat(),
                created_at,
                created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert payload["summary"]["follow_up_confirmation_count"] >= 1
    assert any(item["person_id"] == person_id for item in payload["overlays"]["follow_up_confirmation"])


def test_recent_cancelled_m365_meeting_creates_meeting_churn_signal():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-cancel-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, contact_value,
                network_tier, relationship_owner, last_contact_datetime, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Cancelled Meeting Contact",
                "Managing Director",
                "Calendar Group",
                "OBE M",
                "Hot",
                "T1",
                "Marcus",
                (now - timedelta(days=24)).isoformat(),
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, external_id, created_at, interaction_at,
                meeting_quality_status, meeting_response_status, meeting_last_modified_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"int-{uuid.uuid4().hex[:8]}",
                person_id,
                "meeting",
                "Microsoft 365 calendar event: SSH catch-up\nCalendar status: cancelled\nResponse status: accepted",
                "SSH catch-up (Cancelled)",
                f"m365-event:{uuid.uuid4().hex}:{person_id}",
                created_at,
                (now + timedelta(days=2)).isoformat(),
                "cancelled",
                "accepted",
                now.isoformat(),
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get("/api/dashboard/network-feed").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    all_items = payload["act_now"] + payload["maintain"] + payload["preserve"] + payload["monitor"]
    item = next(entry for entry in all_items if entry["person_id"] == person_id)
    assert item["recent_cancelled_meeting_count"] >= 1
    assert item["has_meeting_churn"] is True
    assert payload["summary"]["meeting_churn_count"] >= 1
    assert any(entry["person_id"] == person_id for entry in payload["overlays"]["meeting_churn"])


def test_task_updates_recalculate_next_contact_due_date_and_meeting_status():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-tasksync-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Task Sync Contact", "Director", "Task Sync Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        create_payload = {
            "person_id": person_id,
            "task_text": "Follow up on shortlist",
            "due_date": (now + timedelta(days=5)).date().isoformat(),
            "priority": "high",
        }
        create_response = client.post("/api/tasks", json=create_payload)
        assert create_response.status_code == 200
        task_id = create_response.json()["task_id"]

        person_payload = client.get(f"/api/people/{person_id}").json()["person"]
        assert person_payload["next_contact_due_date"] == create_payload["due_date"]
        assert person_payload["meeting_status"] == "soon"

        updated_due = (now + timedelta(days=20)).date().isoformat()
        update_response = client.patch(f"/api/tasks/{task_id}", json={"due_date": updated_due})
        assert update_response.status_code == 200

        refreshed_person = client.get(f"/api/people/{person_id}").json()["person"]
        assert refreshed_person["next_contact_due_date"] == updated_due
        assert refreshed_person["meeting_status"] == "on_track"
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))


def test_people_support_network_fields_and_opportunity_crud():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-person-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, decision_role,
                influence_scope, account_priority, tier_rationale,
                created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id, "Network Fields Contact", "Director", "Signal Partners", "OBE M",
                "T1", "maintain", "Owner One", "decision_maker",
                "both", "high", "Key strategic relationship", created_at, created_at,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        person_response = client.get(f"/api/people/{person_id}")
        assert person_response.status_code == 200
        person_payload = person_response.json()["person"]
        assert person_payload["network_tier"] == "T1"
        assert person_payload["maintenance_mode"] == "maintain"
        assert person_payload["relationship_owner"] == "Owner One"
        assert person_payload["network_score_context"]["effective_network_tier"] == "T1"
        assert "network_health_score" in person_payload["network_score_context"]

        create_response = client.post(
            f"/api/people/{person_id}/opportunities",
            json={
                "account_name": "Signal Partners",
                "opportunity_type": "introduction",
                "stage": "active",
                "value_band": "high",
                "trigger_date": (datetime.now(timezone.utc) + timedelta(days=14)).date().isoformat(),
                "strategic_importance": 88,
                "status": "open",
                "owner": "Owner One",
                "notes": "Priority introduction path",
            },
        )
        assert create_response.status_code == 200
        opportunity_id = create_response.json()["opportunity_id"]

        list_response = client.get(f"/api/people/{person_id}/opportunities")
        assert list_response.status_code == 200
        assert any(item["opportunity_id"] == opportunity_id for item in list_response.json()["opportunities"])

        update_response = client.patch(
            f"/api/people/{person_id}/opportunities/{opportunity_id}",
            json={"stage": "closed_won", "status": "closed"},
        )
        assert update_response.status_code == 200

        queue_response = client.get("/api/network/queues")
        assert queue_response.status_code == 200
        queue_payload = queue_response.json()
        maintain_ids = {item["person_id"] for item in queue_payload["maintain"]}
        act_now_ids = {item["person_id"] for item in queue_payload["act_now"]}
        assert person_id in maintain_ids or person_id in act_now_ids
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))


def test_network_lab_profile_returns_interpreted_correspondence_intelligence():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-intel-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Craig Intelligence Test",
                "Director",
                "Moorfield Advisory",
                "OBE M",
                "T2",
                "work",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        interactions = [
            (
                f"int-{uuid.uuid4().hex[:8]}",
                "email",
                "We are arranging first-round interviews next week and the shortlist is ready. The client is also pushing on package and flight cost expectations.",
                created_at,
            ),
            (
                f"int-{uuid.uuid4().hex[:8]}",
                "email",
                "The market is moving quickly, salary pressure is rising, and there is a real shortage of senior delivery talent in Riyadh right now.",
                created_at,
            ),
            (
                f"int-{uuid.uuid4().hex[:8]}",
                "whatsapp",
                "Great catching up. Hope the family is well and let us plan that golf round after Ramadan.",
                created_at,
            ),
        ]
        for interaction_id, channel, summary, interaction_at in interactions:
            await db.execute(
                """
                INSERT INTO INTERACTION (
                    interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                    meaningful_flag, direction, response_flag, follow_up_committed_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    interaction_id,
                    person_id,
                    channel,
                    summary,
                    summary,
                    created_at,
                    interaction_at,
                    1,
                    "outbound",
                    1,
                    1,
                ),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/network-lab/profile/{person_id}")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert response.status_code == 200
    assert payload["interpreted_interactions"]
    assert "interview" in payload["what_is_happening_summary"].lower()
    assert "market intelligence" in payload["market_intel_summary"].lower()
    assert "rapport" in payload["rapport_summary"].lower() or "personal context" in payload["rapport_summary"].lower()

    merged_text = " ".join(
        f"{item.get('what_is_happening', '')} {item.get('why_it_matters', '')} {' '.join(item.get('evidence_snippets', []))}"
        for item in payload["interpreted_interactions"]
    ).lower()
    assert "package" in merged_text or "cost" in merged_text
    assert "salary pressure" in merged_text or "talent" in merged_text


def test_network_lab_databank_groups_cross_contact_interpreted_memory():
    created_at = datetime.now(timezone.utc).isoformat()
    person_ids = [f"net-db-{uuid.uuid4().hex[:8]}", f"net-db-{uuid.uuid4().hex[:8]}"]

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_ids[0],
                "Market Intel Contact",
                "Director",
                "Riyadh Delivery Group",
                "OBE M",
                "T2",
                "work",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_ids[1],
                "Rapport Contact",
                "Partner",
                "Gulf Search Partners",
                "EXT",
                "T3",
                "maintain",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        rows = [
            (
                person_ids[0],
                "email",
                "The market is tightening, compensation is moving quickly, and we are arranging interviews for a senior hire while the client pushes back on package levels.",
            ),
            (
                person_ids[1],
                "whatsapp",
                "Great to see you. Hope the family is well and I'm keen to reconnect after Ramadan and plan that golf round.",
            ),
        ]
        for person_id, channel, text in rows:
            await db.execute(
                """
                INSERT INTO INTERACTION (
                    interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                    meaningful_flag, direction, response_flag, follow_up_committed_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"int-{uuid.uuid4().hex[:8]}",
                    person_id,
                    channel,
                    text,
                    text,
                    created_at,
                    created_at,
                    1,
                    "outbound",
                    1,
                    1,
                ),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get("/api/network-lab/databank?scope=all")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_cleanup_records(person_ids))

    assert response.status_code == 200
    assert payload["summary"]["items_scanned"] >= 2
    assert payload["market_intel"]
    assert payload["opportunity_watch"]
    assert payload["rapport_memory"]
    assert payload["friction_watch"]
    assert payload["intent_watch"]
    assert payload["relationship_trajectory"]
    assert any(item.get("full_evidence_text") for item in payload["market_intel"])


def test_generic_coordination_does_not_create_market_intel_or_fake_rapport():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-noise-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Noise Contact", "Director", "Signal Works", "GEN", created_at, created_at),
        )
        text = "Can we arrange a meeting next week to review the shortlist and confirm the next step."
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "email", text, text, created_at, created_at, 1, "outbound", 1, 1),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
        payload_again = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert payload["interpreted_interactions"]
    item = payload["interpreted_interactions"][0]
    assert item["market_intel_signals"] == []
    assert not any("rapport" in signal.lower() for signal in item["relationship_signals"])


def test_courtesy_ramadan_greeting_does_not_become_topic_or_prompt():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-ramadan-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "David Hutton",
                "Managing Director",
                "Mott MacDonald",
                "OBE M",
                "T2",
                "maintain",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        text = "Hope that you are having a good Ramadan so far?"
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "email", text, text, created_at, created_at, 1, "outbound", 1, 0),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    if payload["interpreted_interactions"]:
        item = payload["interpreted_interactions"][0]
        assert not item["relationship_signals"]
    assert not payload["relationship_topics"]["personal_continuity"]
    assert not payload["relationship_topics"]["clarification_prompts"]


def test_meeting_response_noise_does_not_create_topic_or_prompt():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-step-{uuid.uuid4().hex[:8]}"
    text = "Accepted: Step\n\nMicrosoft Teams meeting\nJoin the meeting now\nMeeting ID: 123 456 789\nPasscode: abc123"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Matt Squires",
                "Chief Executive Officer",
                "SSH Design",
                "OBE M",
                "T2",
                "maintain",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "meeting", text, text, created_at, created_at, 1, "inbound", 1, 0),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert not payload["relationship_topics"]["active_topics"]
    assert not payload["relationship_topics"]["clarification_prompts"]
    assert not payload["relationship_topics"]["personal_continuity"]


def test_hiring_thread_prompt_asks_for_current_status_not_generic_meeting_outcome():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-hiring-prompt-{uuid.uuid4().hex[:8]}"
    text = (
        "Sent Email: Taylor Sterling: Marivic Mendoza - Senior Design Project Manager\n\n"
        "Matt, this is the woman we discussed for the senior design PM thread. "
        "If you want to progress her we can arrange interviews next week."
    )

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Matt Squires",
                "Chief Executive Officer",
                "SSH Design",
                "OBE M",
                "T2",
                "maintain",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "email", text, text, created_at, created_at, 1, "outbound", 1, 1),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    prompts = payload["relationship_topics"]["clarification_prompts"]
    assert prompts
    question = prompts[0]["question"].lower()
    assert "now stand" in question or "current truth" in question
    assert "did this meeting happen" not in question


def test_network_lab_can_promote_enduring_memory_and_market_intel():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-promote-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Promotion Contact",
                "Director",
                "Promotion Group",
                "OBE M",
                "T2",
                "work",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        text = "We are arranging interviews next week, the package is under pressure, and the market is short of senior talent."
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"int-{uuid.uuid4().hex[:8]}",
                person_id,
                "email",
                text,
                text,
                created_at,
                created_at,
                1,
                "outbound",
                1,
                1,
            ),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        profile_response = client.get(f"/api/network-lab/profile/{person_id}")
        interpretation_id = profile_response.json()["interpreted_interactions"][0]["interpretation_id"]

        memory_response = client.post(
            f"/api/network-lab/interpretations/{interpretation_id}/promote-memory",
            json={"memory_domain": "opportunity", "status": "approved"},
        )
        market_response = client.post(
            f"/api/network-lab/interpretations/{interpretation_id}/promote-market-intel",
            json={"status": "approved"},
        )
        refreshed_profile = client.get(f"/api/network-lab/profile/{person_id}").json()
        databank_payload = client.get("/api/network-lab/databank?scope=all").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert memory_response.status_code == 200
    assert market_response.status_code == 200
    assert refreshed_profile["enduring_memory"]
    assert refreshed_profile["promoted_market_intel"]
    assert any(item.get("promoted_memory_status") == "approved" for item in databank_payload["opportunity_watch"])
    assert any(item.get("promoted_market_intel_status") == "approved" for item in databank_payload["market_intel"])


def test_old_correspondence_beyond_four_years_is_ignored():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    old_interaction_at = (now - timedelta(days=(365 * 4) + 30)).isoformat()
    recent_interaction_at = (now - timedelta(days=10)).isoformat()
    person_id = f"net-cutoff-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Cutoff Contact",
                "Director",
                "Cutoff Group",
                "OBE M",
                "T3",
                "maintain",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        rows = [
            (
                f"int-{uuid.uuid4().hex[:8]}",
                "email",
                "The market is short of senior talent and salary pressure is rising fast.",
                old_interaction_at,
            ),
            (
                f"int-{uuid.uuid4().hex[:8]}",
                "email",
                "We are arranging interviews next week and package pressure needs handling.",
                recent_interaction_at,
            ),
        ]
        for interaction_id, channel, text, interaction_at in rows:
            await db.execute(
                """
                INSERT INTO INTERACTION (
                    interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                    meaningful_flag, direction, response_flag, follow_up_committed_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (interaction_id, person_id, channel, text, text, created_at, interaction_at, 1, "outbound", 1, 1),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        profile_payload = client.get(f"/api/network-lab/profile/{person_id}").json()
        databank_payload = client.get("/api/network-lab/databank?scope=all").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert len(profile_payload["interpreted_interactions"]) == 1
    interpreted_text = " ".join(
        f"{item.get('what_is_happening', '')} {' '.join(item.get('evidence_snippets', []))}"
        for item in profile_payload["interpreted_interactions"]
    ).lower()
    assert "interviews" in interpreted_text or "package" in interpreted_text
    assert "salary pressure" not in interpreted_text
    assert not any(item["person_id"] == person_id for item in databank_payload["market_intel"])


def test_market_intel_attribution_handles_third_party_subject():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-third-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Ian Test Contact",
                "Managing Director",
                "WSP Middle East",
                "OBE M",
                "T2",
                "maintain",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        text = "Met with Kevin who is focused on AI expansion in MENA and seeking talent in LLM fine-tuning."
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "note", text, text, created_at, created_at, 1, "internal", 1, 1),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
        payload_again = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    first_item = payload["interpreted_interactions"][0]
    merged = " ".join([
        first_item.get("what_is_happening", ""),
        first_item.get("why_it_matters", ""),
        " ".join(first_item.get("market_intel_signals", [])),
    ]).lower()
    assert "ai expansion in mena" in merged or "llm fine-tuning" in merged
    assert "kevin" in merged
    assert "real market intelligence" not in merged
    assert "hiring demand, talent, pay, or market movement" not in merged


def test_signature_progression_is_not_shown_as_clipped_summary():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-signature-{uuid.uuid4().hex[:8]}"
    summary = "Re: Taylor Sterling - Executive Search Assignment - GECO - confidential\nMarcus,\nI hope you're well and apologies for the delay in concluding this from our side. Can you please resh"
    raw_text = "Re: Taylor Sterling - Executive Search Assignment - GECO - confidential\nMarcus,\nI hope you're well and apologies for the delay in concluding this from our side. Can you please reshare the agreement for signature.\nI trust that this will kick off a long term relationship between GECO and TS."

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "GECO Contact",
                "Director",
                "GECO",
                "TGT",
                "T2",
                "work",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "email", raw_text, summary, created_at, created_at, 1, "inbound", 1, 1),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
        payload_again = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    item = payload["interpreted_interactions"][0]
    assert item["stage"] == "Assignment / Signature Progression"
    assert "formal commercial commitment" in item["what_is_happening"].lower()
    assert "summary:" not in item["full_evidence_text"].lower()
    assert "reshare the agreement for signature" in item["full_evidence_text"].lower()


def test_profile_storyline_groups_cross_channel_sequence():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    person_id = f"net-story-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Storyline Contact",
                "Director",
                "Storyline Group",
                "OBE M",
                "T2",
                "work",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        rows = [
            ("email", "Please reshare the agreement for signature so we can kick off the executive search assignment.", (now - timedelta(days=6)).isoformat()),
            ("whatsapp", "Sharing over WhatsApp as well so the signed agreement does not get missed.", (now - timedelta(days=4)).isoformat()),
            ("call", "We discussed the assignment on the phone and agreed the search will start once signature lands.", (now - timedelta(days=2)).isoformat()),
        ]
        for channel, text, interaction_at in rows:
            await db.execute(
                """
                INSERT INTO INTERACTION (
                    interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                    meaningful_flag, direction, response_flag, follow_up_committed_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (f"int-{uuid.uuid4().hex[:8]}", person_id, channel, text, text, created_at, interaction_at, 1, "outbound", 1, 1),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        payload = client.get(f"/api/network-lab/profile/{person_id}").json()
        payload_again = client.get(f"/api/network-lab/profile/{person_id}").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert payload["storyline_groups"]
    assert payload["tracked_situations"]
    assert payload["surfaced_intelligence"]
    assert len(payload["storyline_groups"]) == 1
    group = payload["storyline_groups"][0]
    assert group["entry_count"] == 3
    assert len(group["channels"]) == 3
    assert group["topic_type"] == "opportunity"
    assert group["topic_type_label"] == "Opportunity"
    assert group["situation_id"].startswith("S-OPP-")
    assert "interactions on" in group["timeline_summary"].lower()
    assert group["window_label"]
    assert len(group["supporting_entries"]) == 3
    assert str(group["supporting_entries"][0]["channel"]).lower() == "email"
    assert group["tracking_status"] == "open"
    assert group["tracking_status_label"] == "Open"
    assert group["recent_events"]
    assert payload_again["storyline_groups"][0]["situation_id"] == group["situation_id"]
    assert any(item["primary_category"] == "Tracked Situation" for item in payload["surfaced_intelligence"])
    assert "current state:" in payload["current_state_summary"].lower()


def test_network_lab_review_queue_and_status_updates():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-review-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat,
                network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                person_id,
                "Review Queue Contact",
                "Partner",
                "Review Group",
                "OBE M",
                "T2",
                "work",
                "Marcus",
                created_at,
                created_at,
            ),
        )
        text = "The market is tightening, package pressure is rising, and we want to move quickly on interviews next week."
        await db.execute(
            """
            INSERT INTO INTERACTION (
                interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                meaningful_flag, direction, response_flag, follow_up_committed_flag
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (f"int-{uuid.uuid4().hex[:8]}", person_id, "email", text, text, created_at, created_at, 1, "outbound", 1, 1),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        profile_response = client.get(f"/api/network-lab/profile/{person_id}")
        interpretation_id = profile_response.json()["interpreted_interactions"][0]["interpretation_id"]
        memory_response = client.post(
            f"/api/network-lab/interpretations/{interpretation_id}/promote-memory",
            json={"memory_domain": "market", "status": "draft"},
        )
        market_response = client.post(
            f"/api/network-lab/interpretations/{interpretation_id}/promote-market-intel",
            json={"status": "draft"},
        )
        queue_before = client.get("/api/network-lab/review-queue?scope=all").json()
        assert any(item["person_id"] == person_id for item in queue_before["interpreted_drafts"])
        memory_id = next(item["memory_id"] for item in queue_before["enduring_memory"] if item["person_id"] == person_id)
        market_intel_id = next(item["market_intel_id"] for item in queue_before["market_intel"] if item["person_id"] == person_id)

        memory_update = client.post(f"/api/network-lab/memory/{memory_id}/status", json={"status": "approved"})
        market_update = client.post(f"/api/network-lab/market-intel/{market_intel_id}/status", json={"status": "approved"})
        queue_after = client.get("/api/network-lab/review-queue?scope=all").json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert memory_response.status_code == 200
    assert market_response.status_code == 200
    assert queue_before["summary"]["enduring_pending_count"] >= 1
    assert queue_before["summary"]["market_pending_count"] >= 1
    assert memory_update.status_code == 200
    assert market_update.status_code == 200
    assert any(item["person_id"] == person_id and item["status"] == "approved" for item in queue_after["enduring_memory"])
    assert any(item["person_id"] == person_id and item["status"] == "approved" for item in queue_after["market_intel"])


def test_network_lab_workspace_bulk_and_company_opportunity_flow():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-lab-{uuid.uuid4().hex[:8]}"
    company_name = "Future Access Group"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Lab Contact", "Director", company_name, "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        owners_response = client.get("/api/network-lab/owners")
        assert owners_response.status_code == 200
        owners = owners_response.json()["owners"]
        assert owners

        workspace_response = client.get("/api/network-lab/workspace")
        assert workspace_response.status_code == 200
        workspace_payload = workspace_response.json()
        review = workspace_payload["review"]
        assert "missing_tier" in review
        assert "pilot_cohort_ids" in workspace_payload
        assert workspace_payload["pilot_cohort_summary"]["recommended_size"] >= 1

        bulk_response = client.post(
            "/api/network-lab/bulk-update",
            json={
                "person_ids": [person_id],
                "network_tier": "T3",
                "maintenance_mode": "maintain",
                "relationship_owner": owners[0]["full_name"],
                "account_priority": "Warm",
                "create_task_text": "Review this strategic contact",
            },
        )
        assert bulk_response.status_code == 200

        profile_response = client.get(f"/api/network-lab/profile/{person_id}")
        assert profile_response.status_code == 200
        profile_payload = profile_response.json()
        assert profile_payload["person"]["network_tier"] == "T3"
        assert profile_payload["person"]["maintenance_mode"] == "maintain"
        assert profile_payload["person"]["relationship_owner"] == owners[0]["full_name"]

        company_create_response = client.post(
            "/api/network-lab/company-opportunities",
            json={
                "company_name_raw": company_name,
                "opportunity_type": "framework",
                "stage": "open",
                "value_band": "high",
                "trigger_date": (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat(),
                "owner": owners[0]["full_name"],
                "notes": "Potential framework opening",
            },
        )
        assert company_create_response.status_code == 200

        profile_after_response = client.get(f"/api/network-lab/profile/{person_id}")
        assert profile_after_response.status_code == 200
        company_opps = profile_after_response.json()["company_opportunities"]
        assert any(item["company_name_raw"] == company_name for item in company_opps)
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))


def test_network_lab_profile_builds_conversation_prep_and_related_team_context():
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    target_id = f"net-prep-{uuid.uuid4().hex[:8]}"
    teammate_id = f"net-team-{uuid.uuid4().hex[:8]}"
    company_name = "SSH Design"

    async def setup(db):
        people = [
            (
                target_id,
                "Mark Obrien",
                "COO",
                company_name,
                "OBE M",
                "Hot",
                "T2",
                "work",
                "Marcus",
            ),
            (
                teammate_id,
                "Matt Squires",
                "Chief Executive Officer, SSH Design",
                company_name,
                "OBE M",
                "Hot",
                "T2",
                "work",
                "Marcus",
            ),
        ]
        for person_id, full_name, title, company, cat, contact_value, network_tier, maintenance_mode, owner in people:
            await db.execute(
                """
                INSERT INTO PERSON (
                    person_id, full_name, title_current, company_name_raw, cat, contact_value,
                    network_tier, maintenance_mode, relationship_owner, created_at, last_updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (person_id, full_name, title, company, cat, contact_value, network_tier, maintenance_mode, owner, created_at, created_at),
            )

        target_rows = [
            (
                "email",
                "Sent Email: Taylor Sterling: Damian Arnillas - Structural Engineer\n\nMark,\nthis is the chap we spoke about yesterday - we really like him - committed to coming to the UAE. Let me know if you would like to have a Teams call.",
                (now - timedelta(days=4)).isoformat(),
            ),
            (
                "email",
                "Sent Email: Proposed SSH Session - Taylor Sterling + Catchup + Alignment + Focus\n\nProposed attendance to visit SSH leadership to discuss commercial gap and any other needs.",
                (now - timedelta(days=18)).isoformat(),
            ),
            (
                "email",
                "Sent Email: RE: Taylor Sterling - Signed Contract - Mark Earley\n\nThis is confirmed and accepted from our side and you may proceed accordingly.",
                (now - timedelta(days=40)).isoformat(),
            ),
        ]
        for channel, text, interaction_at in target_rows:
            await db.execute(
                """
                INSERT INTO INTERACTION (
                    interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                    meaningful_flag, direction, response_flag, follow_up_committed_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (f"int-{uuid.uuid4().hex[:8]}", target_id, channel, text, text, created_at, interaction_at, 1, "outbound", 1, 1),
            )

        teammate_rows = [
            (
                "email",
                "Sent Email: Marivic Mendoza - Senior Design Project Manager\n\nMatt,\nthis is the woman we spoke about for the senior design project manager thread.",
                (now - timedelta(days=6)).isoformat(),
            ),
            (
                "email",
                "Sent Email: Package pressure is rising on this role and we need to be clear on the commercial position before interviews move.",
                (now - timedelta(days=8)).isoformat(),
            ),
        ]
        for channel, text, interaction_at in teammate_rows:
            await db.execute(
                """
                INSERT INTO INTERACTION (
                    interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at,
                    meaningful_flag, direction, response_flag, follow_up_committed_flag
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (f"int-{uuid.uuid4().hex[:8]}", teammate_id, channel, text, text, created_at, interaction_at, 1, "outbound", 1, 1),
            )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        response = client.get(f"/api/network-lab/profile/{target_id}")
        payload = response.json()
    finally:
        client.close()
        asyncio.run(_cleanup_records([target_id, teammate_id]))

    assert response.status_code == 200
    assert payload["network_score_context"]
    assert payload["score"] is not None
    assert payload["score_band"]
    assert payload["queue"]
    assert payload["queue_reason"]
    prep = payload["conversation_prep"]
    assert prep["summary"]
    assert prep["relationship_context"]
    assert prep["recent_shifts"]
    assert any("Damian Arnillas" in item for item in prep["topics_to_cover"])
    assert any("commercial gap" in item.lower() for item in prep["topics_to_cover"])
    assert "opening" not in prep["summary"].lower()
    assert prep["clarification_prompts"]

    related = payload["related_team_context"]
    assert related["threads"]
    assert "separately attributed" in related["summary"].lower()
    assert any(item["full_name"] == "Matt Squires" for item in related["threads"])
    matt_thread = next(item for item in related["threads"] if item["full_name"] == "Matt Squires")
    assert matt_thread["attribution"].startswith("With Matt Squires")
    assert matt_thread["profile_path"].endswith(teammate_id)
    evidence_text = " ".join(matt_thread.get("evidence") or [])
    assert "Marivic Mendoza" in evidence_text or "package pressure" in evidence_text.lower()

    relationship_topics = payload["relationship_topics"]
    assert relationship_topics["summary"]
    assert relationship_topics["active_topics"]
    assert relationship_topics["clarification_prompts"]
    assert any(
        "commercial gap" in item["title"].lower()
        or "mark earley" in item["title"].lower()
        or "marivic mendoza" in item["title"].lower()
        for item in relationship_topics["active_topics"]
    )
    assert any(
        "Mark Earley" in item["title"] or "Matt Squires" in " ".join(item.get("source_people") or [])
        for item in relationship_topics["all_topics"]
    )


def test_profile_evidence_inputs_ignore_chatbot_stage_and_profile_completion_requests():
    now = datetime.now(timezone.utc).isoformat()
    interactions = [
        {
            "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
            "channel": "chat",
            "interaction_at": now,
            "summary": "show stages please",
            "raw_text": "show stages please",
        },
        {
            "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
            "channel": "chat",
            "interaction_at": now,
            "summary": "What information is missing to complete profile?",
            "raw_text": "What information is missing to complete profile?",
        },
        {
            "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
            "channel": "chat",
            "interaction_at": now,
            "summary": "Need infortmation for provideing data to compleate profile",
            "raw_text": "Need infortmation for provideing data to compleate profile",
        },
        {
            "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
            "channel": "chat",
            "interaction_at": now,
            "summary": "Capture this update for the profile:",
            "raw_text": "Capture this update for the profile:",
        },
        {
            "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
            "channel": "chat",
            "interaction_at": now,
            "summary": "Known Peter for 14 years and he is on Omnium board.",
            "raw_text": "Known Peter for 14 years and he is on Omnium board.",
        },
        {
            "interaction_id": f"int-{uuid.uuid4().hex[:8]}",
            "channel": "email",
            "interaction_at": now,
            "summary": "Project stage 2 package pressure is rising.",
            "raw_text": "Project stage 2 package pressure is rising.",
        },
    ]

    evidence = _build_profile_evidence_inputs(interactions, tracked_situations=[])
    texts = " ".join(item.get("content") or "" for item in evidence).lower()

    assert len(evidence) == 2
    assert "show stages please" not in texts
    assert "missing to complete profile" not in texts
    assert "provideing data to compleate profile" not in texts
    assert "capture this update for the profile" not in texts
    assert "known peter for 14 years" in texts
    assert "project stage 2 package pressure" in texts


def test_transcript_segment_tags_ignore_stage_and_profile_completion_chat_requests():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-tag-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Tag Filter Contact", "Director", "Filter Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    client = login_client()
    try:
        stage_response = client.post(
            f"/api/network-lab/profile/{person_id}/transcript-segment-tags",
            json={"mode": "stage", "content": "show stage please"},
        )
        completion_response = client.post(
            f"/api/network-lab/profile/{person_id}/transcript-segment-tags",
            json={"mode": "stage", "content": "What data do I need to complete profile?"},
        )
        completion_typo_response = client.post(
            f"/api/network-lab/profile/{person_id}/transcript-segment-tags",
            json={"mode": "stage", "content": "Need infortmation for provideing data to compleate profile"},
        )
    finally:
        client.close()
        asyncio.run(_cleanup_records([person_id]))

    assert stage_response.status_code == 200
    assert completion_response.status_code == 200
    assert completion_typo_response.status_code == 200
    assert stage_response.json()["segments"] == []
    assert completion_response.json()["segments"] == []
    assert completion_typo_response.json()["segments"] == []
    assert stage_response.json()["totals"]["total_segments"] == 0
    assert completion_response.json()["totals"]["total_segments"] == 0
    assert completion_typo_response.json()["totals"]["total_segments"] == 0


def test_transcript_segment_tags_remap_presentation_text_from_s9_to_s3():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-tag-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Stage Remap Contact", "Director", "Filter Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    original_runner = network_lab_module.run_json_chat_task

    async def fake_run_json_chat_task(**_kwargs):
        return (
            {
                "segments": [
                    {"index": 0, "tag_code": "S9", "confidence": 0.92, "reason": "model output"}
                ]
            },
            None,
        )

    network_lab_module.run_json_chat_task = fake_run_json_chat_task
    try:
        req = network_lab_module.TranscriptSegmentTagRequest(
            mode="stage",
            content=(
                "I need to sit down with him and go through a presentation of exactly "
                "what Taylor Stirling's abilities are after Eid."
            ),
            transcript_tagging={
                "stage_relationship": [
                    {"code": "S3", "label": "S3 Position"},
                    {"code": "S9", "label": "S9 Active Nurture"},
                ],
                "stage_opportunity": [],
            },
        )
        result = asyncio.run(network_lab_module.tag_profile_transcript_segments(person_id, req))
    finally:
        network_lab_module.run_json_chat_task = original_runner
        asyncio.run(_cleanup_records([person_id]))

    assert result["segments"]
    assert result["segments"][0]["tag_code"] == "S3"
    assert result["segments"][0]["tag_label"].startswith("S3")


def test_transcript_segment_tags_fallback_when_model_quota_exhausted():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-tag-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Quota Fallback Contact", "Director", "Fallback Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    original_runner = network_lab_module.run_json_chat_task

    async def fake_run_json_chat_task(**_kwargs):
        raise RuntimeError(
            "Error code: 429 - {'error': {'message': 'You exceeded your current quota', 'type': 'insufficient_quota'}}"
        )

    network_lab_module.run_json_chat_task = fake_run_json_chat_task
    try:
        req = network_lab_module.TranscriptSegmentTagRequest(
            mode="stage",
            content="Met Matt today. He asked for a proposal next week.",
            transcript_tagging={
                "stage_relationship": [
                    {"code": "S1", "label": "S1 Introduction"},
                    {"code": "S2", "label": "S2 Understand"},
                ],
                "stage_opportunity": [],
            },
        )
        result = asyncio.run(network_lab_module.tag_profile_transcript_segments(person_id, req))
    finally:
        network_lab_module.run_json_chat_task = original_runner
        asyncio.run(_cleanup_records([person_id]))

    assert result["status"] == "success"
    assert result["model_degraded"] is True
    assert result["segments"]
    assert result["segments"][0]["mapped"] is True
    assert result["segments"][0]["source"] == "default_mapping_model_unavailable"


def test_transcript_segment_tags_remap_s9_problem_text_to_s5():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-tag-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Stage Pressure Contact", "Director", "Pressure Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    original_runner = network_lab_module.run_json_chat_task

    async def fake_run_json_chat_task(**_kwargs):
        return (
            {
                "segments": [
                    {"index": 0, "tag_code": "S9", "confidence": 0.9, "reason": "model output"}
                ]
            },
            None,
        )

    network_lab_module.run_json_chat_task = fake_run_json_chat_task
    try:
        req = network_lab_module.TranscriptSegmentTagRequest(
            mode="stage",
            content=(
                "Continued a problem with his back and health. "
                "He is concerned that leadership has been leaving the area due to stress."
            ),
            transcript_tagging={
                "stage_relationship": [
                    {"code": "S5", "label": "S5 Problem Identified"},
                    {"code": "S9", "label": "S9 Active Nurture"},
                ],
                "stage_opportunity": [],
            },
        )
        result = asyncio.run(network_lab_module.tag_profile_transcript_segments(person_id, req))
    finally:
        network_lab_module.run_json_chat_task = original_runner
        asyncio.run(_cleanup_records([person_id]))

    assert result["segments"]
    assert result["segments"][0]["tag_code"] == "S5"
    assert result["segments"][0]["tag_label"].startswith("S5")


def test_transcript_segment_tags_remap_personal_health_from_k5_to_k1():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-tag-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Knowledge Remap Contact", "Director", "Knowledge Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    original_runner = network_lab_module.run_json_chat_task

    async def fake_run_json_chat_task(**_kwargs):
        return (
            {
                "segments": [
                    {"index": 0, "tag_code": "K5", "confidence": 0.88, "reason": "model output"}
                ]
            },
            None,
        )

    network_lab_module.run_json_chat_task = fake_run_json_chat_task
    try:
        req = network_lab_module.TranscriptSegmentTagRequest(
            mode="knowledge",
            content="Continued a problem with his back and health.",
            transcript_tagging={
                "knowledge_buckets": [
                    {"box_id": 1, "code": "K1", "box_key": "family_status", "box_title": "Family Status"},
                    {"box_id": 5, "code": "K5", "box_key": "challenges_demands", "box_title": "Challenges and Demands"},
                ],
                "stage_relationship": [],
                "stage_opportunity": [],
            },
        )
        result = asyncio.run(network_lab_module.tag_profile_transcript_segments(person_id, req))
    finally:
        network_lab_module.run_json_chat_task = original_runner
        asyncio.run(_cleanup_records([person_id]))

    assert result["segments"]
    assert result["segments"][0]["tag_code"] == "K1"
    assert result["segments"][0]["tag_label"].startswith("K1")


def test_transcript_segment_tags_split_mixed_personal_business_stage_content():
    created_at = datetime.now(timezone.utc).isoformat()
    person_id = f"net-tag-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, "Mixed Context Contact", "Director", "Context Group", "GEN", created_at, created_at),
        )

    asyncio.run(run_write(setup))

    original_runner = network_lab_module.run_json_chat_task

    async def fake_run_json_chat_task(**_kwargs):
        return (
            {
                "segments": [
                    {"index": 0, "tag_code": "S9", "confidence": 0.92, "reason": "model output"},
                    {"index": 1, "tag_code": "S9", "confidence": 0.92, "reason": "model output"},
                    {"index": 2, "tag_code": "S9", "confidence": 0.92, "reason": "model output"},
                    {"index": 3, "tag_code": "S9", "confidence": 0.92, "reason": "model output"},
                    {"index": 4, "tag_code": "S9", "confidence": 0.92, "reason": "model output"},
                ]
            },
            None,
        )

    network_lab_module.run_json_chat_task = fake_run_json_chat_task
    try:
        req = network_lab_module.TranscriptSegmentTagRequest(
            mode="stage",
            content=(
                "Strongly, strongly believes that leadership should be here, which is why he is trying to make "
                "himself seen and around sight in charge of 4,500 people in the region. "
                "His daughter and his wife are safe. "
                "His wife is Lebanese-Palestinian. "
                "Still a little upset about not being involved in the OBE steering committees. "
                "Other than that, the relationship remains strong."
            ),
            transcript_tagging={
                "stage_relationship": [
                    {"code": "S2", "label": "S2 Understand"},
                    {"code": "S4", "label": "S4 Nurture"},
                    {"code": "S9", "label": "S9 Active Nurture"},
                ],
                "stage_opportunity": [],
            },
        )
        result = asyncio.run(network_lab_module.tag_profile_transcript_segments(person_id, req))
    finally:
        network_lab_module.run_json_chat_task = original_runner
        asyncio.run(_cleanup_records([person_id]))

    assert len(result["segments"]) == 5
    assert result["segments"][0]["text"].startswith("Strongly, strongly believes")
    assert result["segments"][0]["tag_code"] == "S2"
    assert result["segments"][-1]["text"].startswith("Other than that")
    assert result["segments"][-1]["tag_code"] == "S4"
