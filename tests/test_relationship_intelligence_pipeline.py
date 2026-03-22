import asyncio
import copy
import json
import uuid
from datetime import datetime, timezone

from backend.config import settings
from backend.database import run_write
from backend.services.relationship_intelligence_pipeline import (
    build_relationship_intelligence_pipeline,
)
from backend.services.system_settings_service import (
    get_intelligence_settings,
    save_intelligence_settings,
)


def _kevin_person(person_id: str) -> dict:
    return {
        "person_id": person_id,
        "full_name": "Kevin C.",
        "company_name_raw": "Stantec",
        "title_current": "Regional Director - Buildings MENA",
        "relationship_owner": "Marcus",
    }


def _kevin_evidence() -> list[dict]:
    return [
        {
            "evidence_id": "manual-ceo-false",
            "source_kind": "manual_resolution",
            "source_type": "Manual resolution",
            "date_at": "2026-03-16T12:35:16+00:00",
            "date_label": "2026-03-16",
            "title": "Incorrect CEO introduction note removed",
            "preview": "Kevin did not offer an introduction to the CEO of Stantec.",
            "content": "Kevin did not offer an introduction to the CEO of Stantec. That earlier note was incorrect and should be removed from Kevin's live relationship storyline and clarification queue.",
        },
        {
            "evidence_id": "manual-current-truth",
            "source_kind": "manual_update",
            "source_type": "Manual input",
            "date_at": "2026-03-16T12:09:19+00:00",
            "date_label": "2026-03-16",
            "title": "Meeting with Kevin on live roles",
            "preview": "One BIM lead and a head of data centres remain active.",
            "content": "I met with Kevin and Oliver in their office. We discussed the situation, market frustrations, and hospital project focus. Kevin's role in commercial projects, now filled, and the need for a data center specialist and BIM lead were highlighted. The meeting planned for last week was postponed due to an emergency in Abu Dhabi. Meeting to be reorganized possibly after Eid. Active roles include one BIM lead and a head of data centers.",
        },
        {
            "evidence_id": "chat-live-update",
            "source_kind": "interaction",
            "source_type": "chat",
            "date_at": "2026-03-05T12:44:49+00:00",
            "date_label": "2026-03-05",
            "title": "Kevin live update",
            "preview": "Commercial role filled, BIM and data centre roles still active.",
            "content": "I spoke to Kevin this morning. We've arranged a meeting for next Wednesday at 11 o'clock in the meadows in Starbucks with Nigel and myself and Kevin, obviously. He's filled the commercial role, the commercial unicorn role, filled that already, but still interested in talking about the BIM role and potentially the data center lead role, which would be excellent to get. On a personal note, it hasn't been running at all in the last week because of the attacks on the UEE and hopefully he'll get a run in over the weekend. Other than that, he's in good spirits.",
        },
        {
            "evidence_id": "old-five-bim",
            "source_kind": "interaction",
            "source_type": "Calendar meeting",
            "date_at": "2026-03-05T13:51:51+00:00",
            "date_label": "2026-03-05",
            "title": "Older BIM claim",
            "preview": "Stantec needs to hire 5 BIM Leads.",
            "content": "High-level meeting with Kevin from Stantec today. He confirmed Stantec is pivoting to a BIM-first strategy in the UAE and needs to hire 5 BIM Leads. We've secured Taylor Sterling as the lead partner for this recruitment drive. Also, Kevin expressed strong interest in hosting the next OBE Roundtable at their office. This is a massive strategic win for us.",
        },
        {
            "evidence_id": "market-note",
            "source_kind": "interaction",
            "source_type": "Note",
            "date_at": "2026-03-05T15:34:24+00:00",
            "date_label": "2026-03-05",
            "title": "OBE breakfast and shortages",
            "preview": "Kevin expects talent shortages next quarter for design leads.",
            "content": "Kevin from Stantec said the OBE breakfast was fantastic. He expects severe talent shortages next quarter for design leads.",
        },
        {
            "evidence_id": "old-ceo-note",
            "source_kind": "interaction",
            "source_type": "Calendar meeting",
            "date_at": "2026-03-05T14:05:54+00:00",
            "date_label": "2026-03-05",
            "title": "Old CEO intro note",
            "preview": "Kevin wants to introduce us to the CEO of Stantec Middle East.",
            "content": "Met at the cafe. Kevin wants to introduce us to the CEO of Stantec Middle East. This could lead to a massive OBE partnership. He's also confirmed for the breakfast next week.",
        },
        {
            "evidence_id": "personal-run",
            "source_kind": "interaction",
            "source_type": "chat",
            "date_at": "2026-02-27T15:26:51+00:00",
            "date_label": "2026-02-27",
            "title": "Burj to Burj run",
            "preview": "Kevin recently did the Burj to Burj run with his daughter.",
            "content": "Kevin recently did the Burj to Burj run with his daughter, which is approximately 20 Ks. So he worked really hard on that. He bought himself a watch and an app on his phone that allowed him to train really early in the mornings to be able to do that 20 kilometer run. Was pretty proud of himself when he finished it.",
        },
        {
            "evidence_id": "accepted-wrapper",
            "source_kind": "interaction",
            "source_type": "Meeting response",
            "date_at": "2026-02-16T15:34:11+00:00",
            "date_label": "2026-02-16",
            "title": "Accepted: Kevin (Stantec) & Marcus",
            "preview": "Received Email: Accepted: Kevin (Stantec) & Marcus",
            "content": "Received Email: Accepted: Kevin (Stantec) & Marcus (Taylor Sterling)",
        },
    ]


def test_kevin_relationship_intelligence_regression():
    original_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = ""
    person_id = f"kevin-{uuid.uuid4().hex[:8]}"
    person = _kevin_person(person_id)
    now = datetime.now(timezone.utc).isoformat()

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (person_id, person["full_name"], person["title_current"], person["company_name_raw"], now, now),
        )

    async def cleanup(db):
        await db.execute("DELETE FROM REL_INTEL_AGENT_OUTPUT WHERE run_id IN (SELECT run_id FROM REL_INTEL_RUN WHERE person_id=?)", (person_id,))
        await db.execute("DELETE FROM REL_INTEL_RUN WHERE person_id=?", (person_id,))
        await db.execute("DELETE FROM PERSON WHERE person_id=?", (person_id,))

    asyncio.run(run_write(setup))
    try:
        result = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=_kevin_evidence(),
                force_refresh=True,
            )
        )
    finally:
        settings.OPENAI_API_KEY = original_key
        asyncio.run(run_write(cleanup))

    briefing = result["briefing"]
    stage1 = result["knowledge_bank_stage1"]
    stage2 = result["relationship_business_flow_stage2"]
    truths_blob = " ".join(briefing["what_is_true_now"]).lower()
    retired_blob = " ".join(briefing["disproved_or_retired_claims"]).lower()
    active_blob = " ".join(briefing["lenses"]["Active Opportunity"]["top_points"]).lower()
    market_blob = " ".join(briefing["lenses"]["Market & Business"]["top_points"]).lower()
    family_blob = " ".join(briefing["lenses"]["Family & Personal"]["top_points"]).lower()
    action_blob = " ".join(action["action_text"] for action in result["action_ledger"]["actions"]).lower()
    priority_blob = " ".join(briefing["next_conversation_priorities"]).lower()

    assert "ceo" not in truths_blob
    assert "ceo" in retired_blob
    assert "5 bim leads" not in active_blob
    assert "one bim lead" in active_blob or "1 bim lead" in active_blob
    assert "data center" in active_blob or "data centres" in active_blob or "data center specialist" in active_blob
    assert "commercial unicorn" not in truths_blob
    assert "hospital" in market_blob
    assert "competition" in market_blob or "pricing" in market_blob or "shortages" in market_blob
    assert "daughter" in family_blob
    assert briefing["uncertainties"]
    assert briefing["relationship_gaps"]
    assert result["action_ledger"]["open_actions"]
    assert "rearrange" in action_blob or "follow-up meeting" in action_blob or "reschedule" in action_blob
    assert "ownership" in action_blob or "owns the next step" in action_blob
    assert "rearrange" in priority_blob or "follow-up meeting" in priority_blob or "ownership" in priority_blob
    assert 50 <= briefing["relationship_health_score"] <= 70
    assert briefing["execution_pressure_score"] >= 60
    assert result["scores"]["execution_pressure_score"] == briefing["execution_pressure_score"]
    assert result["scores"]["execution_pressure_drivers"]
    assert result["trace"]["cleaned_interactions"]
    assert result["trace"]["agent_outputs"]
    assert result["trace"]["action_ledger"]
    assert result["pipeline_meta"]["agent_mode"] == "multi_agent_truth_system"
    assert stage1["framework"] == "stage1-knowledge-bank-v1"
    assert stage1["calibration_profile"] in {"strict", "balanced", "lenient"}
    assert stage1["calibration"]["recency_windows_days"]["fresh"] >= 7
    assert len(stage1["boxes"]) == 11
    assert all(0 <= int(box.get("completeness_pct") or 0) <= 100 for box in stage1["boxes"])
    assert all(0 <= int(box.get("confidence_pct") or 0) <= 100 for box in stage1["boxes"])
    assert all("what_is_known" in box and "what_is_missing" in box for box in stage1["boxes"])
    recruitment_box = next((box for box in stage1["boxes"] if box.get("box_key") == "recruitment_signals"), None)
    assert recruitment_box is not None
    assert int(recruitment_box.get("completeness_pct") or 0) >= 20
    assert stage2["framework"] == "stage2-relationship-business-flow-v1"
    assert stage2["relationship_stage"]["code"] in {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"}
    if stage2.get("opportunity_stage"):
        assert stage2["opportunity_stage"]["code"] in {"O1", "O2", "O3", "O4", "O5", "O6", "O7"}


def test_imported_sent_email_threads_are_not_dropped_as_noise():
    original_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = ""
    person_id = f"craig-{uuid.uuid4().hex[:8]}"
    person = {
        "person_id": person_id,
        "full_name": "Craig Moorfield",
        "company_name_raw": "Keltbray",
        "title_current": "Executive Director",
        "relationship_owner": "Marcus",
    }
    evidence = [
        {
            "evidence_id": "craig-1",
            "source_kind": "interaction",
            "source_type": "Email",
            "date_at": "2026-02-27T09:29:41Z",
            "date_label": "2026-02-27",
            "title": "Sent Email: Re: Taylor Sterling: Muzzammil Sulaiman - Mobile number for Daniel and notes",
            "preview": "Presented as requested - he is a little blue as he knows the cost of flights but going to review.",
            "content": "Sent Email: Re: Taylor Sterling: Muzzammil Sulaiman - Mobile number for Daniel and notes\n\nGents,\nPresented as requested - he is a little blue as he knows the cost of flights but going to review.",
        },
        {
            "evidence_id": "craig-2",
            "source_kind": "interaction",
            "source_type": "Email",
            "date_at": "2026-02-05T07:51:00Z",
            "date_label": "2026-02-05",
            "title": "Sent Email: Taylor Sterling: Muzzammil Sulaiman - Associate Structural Engineer - Passport Copy",
            "preview": "Craig, please let me know if there is any additional info you need to create the offer for Muzzammil.",
            "content": "Sent Email: Taylor Sterling: Muzzammil Sulaiman - Associate Structural Engineer - Passport Copy\n\nCraig, Please let me know if there is any additional info you need to create the offer for Muzzammil.",
        },
        {
            "evidence_id": "craig-3",
            "source_kind": "interaction",
            "source_type": "Email",
            "date_at": "2025-12-03T07:52:39Z",
            "date_label": "2025-12-03",
            "title": "Sent Email: Re: Associate Structural Engineer - Shortlist",
            "preview": "We realise time is not on our side here and the clock is ticking.",
            "content": "Sent Email: Re: Associate Structural Engineer - Shortlist\n\nWe realise time is not on our side here and the clock is ticking. We have reviewed the shortlist and need to move quickly.",
        },
    ]

    now = datetime.now(timezone.utc).isoformat()

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (person_id, person["full_name"], person["title_current"], person["company_name_raw"], now, now),
        )

    async def cleanup(db):
        await db.execute("DELETE FROM REL_INTEL_AGENT_OUTPUT WHERE run_id IN (SELECT run_id FROM REL_INTEL_RUN WHERE person_id=?)", (person_id,))
        await db.execute("DELETE FROM REL_INTEL_RUN WHERE person_id=?", (person_id,))
        await db.execute("DELETE FROM PERSON WHERE person_id=?", (person_id,))

    asyncio.run(run_write(setup))
    try:
        result = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=evidence,
                force_refresh=True,
            )
        )
    finally:
        settings.OPENAI_API_KEY = original_key
        asyncio.run(run_write(cleanup))

    cleaned = result["trace"]["cleaned_interactions"]
    stage1 = result["knowledge_bank_stage1"]
    stage2 = result["relationship_business_flow_stage2"]
    assert cleaned
    assert any(not item["noise_candidate"] for item in cleaned)
    gaps_blob = " ".join((result["briefing"] or {}).get("relationship_gaps") or []).lower()
    assert "no recent interaction data is available" not in gaps_blob
    drivers_blob = " ".join((result["scores"] or {}).get("score_drivers") or []).lower()
    assert "specialist or senior hiring need" in drivers_blob or "live opportunity" in drivers_blob
    assert stage1["boxes"]
    assert stage2["relationship_stage"]["code"] in {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"}


def test_stage2_does_not_treat_follow_up_need_to_as_problem_identified():
    original_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = ""
    person_id = f"needto-{uuid.uuid4().hex[:8]}"
    person = {
        "person_id": person_id,
        "full_name": "Peter Westeng",
        "company_name_raw": "Omnium International Ltd.",
        "title_current": "Board Advisor",
        "relationship_owner": "Marcus",
    }
    evidence = [
        {
            "evidence_id": "westeng-1",
            "source_kind": "interaction",
            "source_type": "chat",
            "date_at": "2026-03-18T11:18:51Z",
            "date_label": "2026-03-18",
            "title": "Peter update and follow-up",
            "preview": "Need to sit down and present TS capabilities after Eid.",
            "content": (
                "I spoke to his colleague Nicholas Harris, although I need to sit down with him "
                "and go through a presentation of exactly what Taylor Stirling's abilities are, "
                "maybe after the E-Break, so in about a week and a half."
            ),
        }
    ]

    now = datetime.now(timezone.utc).isoformat()

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (person_id, person["full_name"], person["title_current"], person["company_name_raw"], now, now),
        )

    async def cleanup(db):
        await db.execute("DELETE FROM REL_INTEL_AGENT_OUTPUT WHERE run_id IN (SELECT run_id FROM REL_INTEL_RUN WHERE person_id=?)", (person_id,))
        await db.execute("DELETE FROM REL_INTEL_RUN WHERE person_id=?", (person_id,))
        await db.execute("DELETE FROM PERSON WHERE person_id=?", (person_id,))

    asyncio.run(run_write(setup))
    try:
        result = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=evidence,
                force_refresh=True,
            )
        )
    finally:
        settings.OPENAI_API_KEY = original_key
        asyncio.run(run_write(cleanup))

    stage2 = result["relationship_business_flow_stage2"]
    signal_counts = (stage2.get("evidence") or {}).get("sentence_signal_counts") or {}
    assert int(signal_counts.get("positioning") or 0) >= 1
    assert int(signal_counts.get("problem_identified") or 0) == 0
    if stage2.get("opportunity_stage"):
        assert stage2["opportunity_stage"]["code"] not in {"O1", "O4"}


def test_stage2_uses_mature_cycle_after_active_nurture():
    original_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = ""
    person_id = f"mature-{uuid.uuid4().hex[:8]}"
    person = {
        "person_id": person_id,
        "full_name": "Mature Client Contact",
        "company_name_raw": "RepeatCo",
        "title_current": "Operations Director",
        "relationship_owner": "Marcus",
        "cat": "EXT",
    }
    evidence = [
        {
            "evidence_id": "mature-1",
            "source_kind": "interaction",
            "source_type": "chat",
            "date_at": "2026-03-18T10:00:00Z",
            "date_label": "2026-03-18",
            "title": "Repeat hiring discussion",
            "preview": "Need to discuss a repeat assignment for a Commercial Director role.",
            "content": "We should discuss a repeat hiring assignment next week. They need a new Commercial Director and want to review scope before committing.",
        }
    ]

    now = datetime.now(timezone.utc).isoformat()
    previous_briefing = {
        "relationship_business_flow_stage2": {
            "framework": "stage2-relationship-business-flow-v1",
            "generated_at": "2026-03-10T10:00:00Z",
            "mature_cycle_active": True,
            "relationship_stage": {"code": "S9", "label": "S9 Active Nurture"},
            "opportunity_stage": None,
        }
    }

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (person_id, person["full_name"], person["title_current"], person["company_name_raw"], person["cat"], now, now),
        )
        await db.execute(
            """
            INSERT INTO REL_INTEL_RUN (
                run_id, person_id, source_digest, pipeline_version, model_name, status,
                cleaned_interactions_json, claim_ledger_json, action_ledger_json, scores_json, briefing_json,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()),
                person_id,
                "seed-stage2",
                "seed-version",
                "deterministic-fallback",
                "completed",
                "[]",
                "{}",
                "{}",
                "{}",
                json.dumps(previous_briefing),
                "2026-03-10T10:00:00Z",
                "2026-03-10T10:00:00Z",
            ),
        )

    async def cleanup(db):
        await db.execute("DELETE FROM REL_INTEL_AGENT_OUTPUT WHERE run_id IN (SELECT run_id FROM REL_INTEL_RUN WHERE person_id=?)", (person_id,))
        await db.execute("DELETE FROM REL_INTEL_RUN WHERE person_id=?", (person_id,))
        await db.execute("DELETE FROM PERSON WHERE person_id=?", (person_id,))

    asyncio.run(run_write(setup))
    try:
        result = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=evidence,
                force_refresh=True,
            )
        )
    finally:
        settings.OPENAI_API_KEY = original_key
        asyncio.run(run_write(cleanup))

    stage2 = result["relationship_business_flow_stage2"]
    assert stage2["mature_cycle_active"] is True
    assert stage2["relationship_stage"]["code"] in {"S6", "S7", "S9", "S5"}
    assert stage2["opportunity_stage"] is not None
    assert stage2["opportunity_stage"]["code"] in {"O4", "O5", "O6", "O7"}


def test_stage2_keeps_higher_historical_relationship_stage_without_explicit_regression_signal():
    original_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = ""
    person_id = f"guard-{uuid.uuid4().hex[:8]}"
    person = {
        "person_id": person_id,
        "full_name": "History Guard Contact",
        "company_name_raw": "Omnium International Ltd.",
        "title_current": "Board Advisor",
        "relationship_owner": "Marcus",
    }
    evidence = [
        {
            "evidence_id": "guard-1",
            "source_kind": "interaction",
            "source_type": "chat",
            "date_at": "2026-03-20T11:00:00Z",
            "date_label": "2026-03-20",
            "title": "Light intro note",
            "preview": "Quick intro follow-up only.",
            "content": "Just met briefly and made an initial introduction. We will catch up later.",
        }
    ]
    now = datetime.now(timezone.utc).isoformat()
    previous_briefing = {
        "relationship_business_flow_stage2": {
            "framework": "stage2-relationship-business-flow-v1",
            "generated_at": "2026-03-10T10:00:00Z",
            "mature_cycle_active": False,
            "relationship_stage": {"code": "S3", "label": "S3 Position"},
            "opportunity_stage": None,
        }
    }

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (person_id, person["full_name"], person["title_current"], person["company_name_raw"], now, now),
        )
        await db.execute(
            """
            INSERT INTO REL_INTEL_RUN (
                run_id, person_id, source_digest, pipeline_version, model_name, status,
                cleaned_interactions_json, claim_ledger_json, action_ledger_json, scores_json, briefing_json,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()),
                person_id,
                "seed-stage2-regression-guard",
                "seed-version",
                "deterministic-fallback",
                "completed",
                "[]",
                "{}",
                "{}",
                "{}",
                json.dumps(previous_briefing),
                "2026-03-10T10:00:00Z",
                "2026-03-10T10:00:00Z",
            ),
        )

    async def cleanup(db):
        await db.execute("DELETE FROM REL_INTEL_AGENT_OUTPUT WHERE run_id IN (SELECT run_id FROM REL_INTEL_RUN WHERE person_id=?)", (person_id,))
        await db.execute("DELETE FROM REL_INTEL_RUN WHERE person_id=?", (person_id,))
        await db.execute("DELETE FROM PERSON WHERE person_id=?", (person_id,))

    asyncio.run(run_write(setup))
    try:
        result = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=evidence,
                force_refresh=True,
            )
        )
    finally:
        settings.OPENAI_API_KEY = original_key
        asyncio.run(run_write(cleanup))

    stage2 = result["relationship_business_flow_stage2"]
    assert stage2["relationship_stage"]["code"] == "S3"
    transition_notes = " ".join((stage2.get("transition") or {}).get("notes") or []).lower()
    assert "regression guard applied" in transition_notes
    evidence_blob = stage2.get("evidence") or {}
    assert evidence_blob.get("relationship_stage_regression_guard_applied") is True
    assert str(evidence_blob.get("relationship_stage_inferred_code") or "") in {"S1", "S2"}


def test_stage_map_is_ignored_and_custom_bucket_alignment_without_force_refresh():
    original_key = settings.OPENAI_API_KEY
    settings.OPENAI_API_KEY = ""
    person_id = f"map-{uuid.uuid4().hex[:8]}"
    person = {
        "person_id": person_id,
        "full_name": "Map Driven Contact",
        "company_name_raw": "Alignment Co",
        "title_current": "Director",
        "relationship_owner": "Marcus",
    }
    evidence = [
        {
            "evidence_id": "map-1",
            "source_kind": "interaction",
            "source_type": "chat",
            "date_at": "2026-03-18T10:10:00Z",
            "date_label": "2026-03-18",
            "title": "Custom signal",
            "preview": "Nebulaflag came up in the conversation.",
            "content": "Nebulaflag came up in the conversation and was confirmed as current context.",
        }
    ]
    now = datetime.now(timezone.utc).isoformat()

    async def setup(db):
        await db.execute(
            """
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?)
            """,
            (person_id, person["full_name"], person["title_current"], person["company_name_raw"], now, now),
        )

    async def cleanup(db):
        await db.execute("DELETE FROM REL_INTEL_AGENT_OUTPUT WHERE run_id IN (SELECT run_id FROM REL_INTEL_RUN WHERE person_id=?)", (person_id,))
        await db.execute("DELETE FROM REL_INTEL_RUN WHERE person_id=?", (person_id,))
        await db.execute("DELETE FROM PERSON WHERE person_id=?", (person_id,))

    def _custom_transcript_tagging(stage_code: str) -> dict:
        return {
            "knowledge_buckets": [
                {
                    "box_id": 91,
                    "code": "K91",
                    "box_key": "nebula_signal",
                    "box_title": "Nebula Signal",
                    "keywords": ["nebulaflag"],
                }
            ],
            "stage_from_knowledge_map": {
                "nebula_signal": stage_code,
            },
        }

    original_settings = asyncio.run(get_intelligence_settings()).get("settings") or {}
    asyncio.run(run_write(setup))
    try:
        asyncio.run(
            save_intelligence_settings(
                {"transcript_tagging": _custom_transcript_tagging("O2")},
                merge=True,
            )
        )
        first = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=evidence,
                force_refresh=True,
            )
        )
        first_stage1 = first["knowledge_bank_stage1"]
        first_stage2 = first["relationship_business_flow_stage2"]
        nebula_box = next(
            (box for box in (first_stage1.get("boxes") or []) if box.get("box_key") == "nebula_signal"),
            None,
        )
        assert nebula_box is not None
        assert int(nebula_box.get("completeness_pct") or 0) > 0
        assert first_stage2["relationship_stage"]["code"] in {"S1", "S2"}
        assert first_stage2.get("opportunity_stage") is None
        assert (first_stage2.get("evidence") or {}).get("knowledge_mapped_stage_codes", []) == []

        asyncio.run(
            save_intelligence_settings(
                {"transcript_tagging": _custom_transcript_tagging("S2")},
                merge=True,
            )
        )
        second = asyncio.run(
            build_relationship_intelligence_pipeline(
                person=person,
                evidence_inputs=evidence,
                force_refresh=False,
            )
        )
        second_stage2 = second["relationship_business_flow_stage2"]
        assert second_stage2["relationship_stage"]["code"] in {"S1", "S2"}
        assert second["pipeline_meta"]["cache_status"] == "hit"
    finally:
        settings.OPENAI_API_KEY = original_key
        asyncio.run(save_intelligence_settings(copy.deepcopy(original_settings), merge=False))
        asyncio.run(run_write(cleanup))
