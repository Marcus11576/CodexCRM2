import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import app
from backend.services import ai_service
from backend.services import strategist_service
from backend.services.preference_learning import record_feedback_event
from backend.database import run_write, run_read
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = 'password123') -> TestClient:
    import asyncio as _asyncio

    email = f"intel-{uuid.uuid4().hex[:8]}@example.com"
    existing = _asyncio.run(get_user_by_email(email))
    if not existing:
        _asyncio.run(create_user(email, 'Intelligence Audit User', password, role='admin'))
    authed = TestClient(app, base_url=TEST_BASE_URL)
    response = authed.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return authed


def test_intelligence_job_status_endpoint(monkeypatch):
    async def fake_get_job(job_id: str):
        if job_id == "job-123":
            return {
                "job_id": "job-123",
                "job_type": "transcription",
                "status": "completed",
                "result": {"text": "hello world"},
            }
        return None

    monkeypatch.setattr("backend.routers.intelligence.get_job", fake_get_job)

    authed = login_client()
    try:
        ok = authed.get("/api/intelligence/jobs/job-123")
        assert ok.status_code == 200
        payload = ok.json()
        assert payload["job_id"] == "job-123"
        assert payload["result"]["text"] == "hello world"

        missing = authed.get("/api/intelligence/jobs/missing")
        assert missing.status_code == 404
    finally:
        authed.close()


def test_transcribe_endpoint_returns_job_id(monkeypatch):
    captured = {}

    async def fake_enqueue_job(job_type, payload, **kwargs):
        captured["job_type"] = job_type
        captured["payload"] = payload
        return {"status": "queued", "job_id": "job-transcribe-1"}

    monkeypatch.setattr("backend.routers.intelligence.enqueue_job", fake_enqueue_job)
    monkeypatch.setattr("backend.routers.intelligence.settings.OPENAI_API_KEY", "sk-test-key")

    authed = login_client()
    try:
        res = authed.post(
            "/api/intelligence/transcribe",
            files={"file": ("voice.webm", b"fake-audio-bytes", "audio/webm")},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["status"] == "queued"
        assert payload["job_id"] == "job-transcribe-1"
        assert captured["payload"]["file_path"].endswith(".webm")
    finally:
        temp_path = captured.get("payload", {}).get("file_path")
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        authed.close()


def test_intelligence_review_and_feedback(monkeypatch):
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    intel_id = f"i1-{person_id}"
    event_id = f"e1-{person_id}"

    async def setup(db):
        now = '2026-03-09T00:00:00Z'
        try:
            await db.execute("ALTER TABLE TOPIC_INTELLIGENCE ADD COLUMN status TEXT DEFAULT 'draft'")
        except Exception:
            pass
        try:
            await db.execute('ALTER TABLE TOPIC_INTELLIGENCE ADD COLUMN source_snippet TEXT')
        except Exception:
            pass
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)", (person_id, 'Test Person', now, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)", (intel_id, person_id, 'business_focus', 'Initial signal text', 3, now))
        await db.execute("INSERT OR REPLACE INTO EVENT (event_id, event_name, event_date, created_at, updated_at) VALUES (?,?,?,?,?)", (event_id, 'Future Summit', '2099-01-01T00:00:00Z', now, now))
        await db.execute("INSERT OR REPLACE INTO PERSON_EVENT (person_event_id, person_id, event_id, status, created_at, updated_at) VALUES (?,?,?,?,?,?)", (f'pe-{person_id}', person_id, event_id, 'invited', now, now))
    asyncio.run(run_write(setup))

    captured = {}

    async def fake_review(person, signals, events):
        captured['person'] = person
        captured['signals'] = signals
        captured['events'] = events
        return {'signals': signals, 'brief': {'business_focus': 'ok', 'recruitment_talent': '', 'personal_rapport': '', 'obe_focus': '', 'strategic_hypotheses': [], 'audio_script': ''}}

    monkeypatch.setattr(ai_service, 'review_signals', fake_review)

    authed = login_client()
    try:
        res = authed.post(f'/api/intelligence/assistant/{person_id}/review')
        assert res.status_code == 200
        assert res.json()['signals'][0]['text'] == 'Initial signal text'
        assert captured['events'][0]['event_name'] == 'Future Summit'

        fb_payload = {'target_type': 'signal', 'target_id': intel_id, 'event_type': 'approval', 'details': {'reason': 'looks good'}, 'user_id': 'u1'}
        fb_res = authed.post('/api/ai/feedback', json=fb_payload)
        assert fb_res.status_code == 200
        assert 'feedback_id' in fb_res.json()

        patch_res = authed.patch(f'/api/people/{person_id}/intelligence/{intel_id}', json={'text': 'edited text', 'status': 'approved'})
        assert patch_res.status_code == 200
    finally:
        authed.close()

    async def check(db):
        async with db.execute('SELECT intel_text, status FROM TOPIC_INTELLIGENCE WHERE intel_id=?', (intel_id,)) as c:
            row = await c.fetchone()
            return dict(row)

    updated = asyncio.run(run_read(check))
    assert updated['intel_text'] == 'edited text'
    assert updated['status'] == 'approved'


def test_signal_scoring_from_feedback():
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    signal_one = f's1-{person_id}'
    signal_two = f's2-{person_id}'

    async def setup2(db):
        now = '2026-03-09T00:00:00Z'
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)", (person_id, 'Another', now, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)", (signal_one, person_id, 'business_focus', 'A', 3, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)", (signal_two, person_id, 'business_focus', 'B', 3, now))
        await db.execute('DELETE FROM AI_FEEDBACK WHERE target_id IN (?, ?)', (signal_one, signal_two))
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), 'signal', signal_one, 'approval', now))
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), 'signal', signal_one, 'approval', now))
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), 'signal', signal_two, 'reject', now))
    asyncio.run(run_write(setup2))

    from backend.services.ai_service import compute_signal_scores
    scores = asyncio.run(compute_signal_scores(person_id))
    assert scores.get(signal_one, 0) > scores.get(signal_two, 0)


def test_review_signals_sorting(monkeypatch):
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    signal_one = f's1-{person_id}'
    signal_two = f's2-{person_id}'
    signals = [
        {'intel_id': signal_one, 'category': 'business_focus', 'text': 'A', 'snippet': 'A', 'date': '2026-01-01', 'confidence': 3},
        {'intel_id': signal_two, 'category': 'business_focus', 'text': 'B', 'snippet': 'B', 'date': '2026-01-02', 'confidence': 3},
    ]

    async def setup3(db):
        now = '2026-03-09T00:00:00Z'
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)", (person_id, 'X', now, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)", (signal_one, person_id, 'business_focus', 'A', 3, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)", (signal_two, person_id, 'business_focus', 'B', 3, now))
        await db.execute('DELETE FROM AI_FEEDBACK WHERE target_id IN (?, ?)', (signal_one, signal_two))
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), 'signal', signal_two, 'promotion', now))
    asyncio.run(run_write(setup3))

    captured = {}

    def fake_get():
        class FakeClient:
            class Chat:
                class Completions:
                    async def create(self, model=None, messages=None, response_format=None, temperature=None, **kwargs):
                        captured['messages'] = messages
                        class R:
                            choices = [type('c', (), {'message': type('m', (), {'content': '{}'})})]
                        return R()
                completions = Completions()
            chat = Chat()
        return FakeClient()

    monkeypatch.setattr('backend.services.ai_service._get_client', fake_get)

    asyncio.run(ai_service.review_signals({'person_id': person_id}, signals, []))
    signals_message = next(msg['content'] for msg in captured['messages'] if msg['content'].startswith('SIGNALS:'))
    assert signal_two in signals_message.split('\n')[1]


def test_profile_chat_can_apply_latest_headshot_candidate(monkeypatch):
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    artifact_id = f"a-{uuid.uuid4().hex[:8]}"
    now = '2026-03-11T00:00:00Z'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, profile_photo_url, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, 'Brian Schofield', '/uploads/original.jpg', now, now),
        )
        await db.execute(
            """
            INSERT OR REPLACE INTO AI_ARTIFACT (
                artifact_id, person_id, profile_id_nullable, channel, raw_content, raw_content_or_path,
                media_url, source_name, source_type, input_type, input_type_confidence, profile_match_state,
                requires_confirmation, duplicate_hash, status, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                artifact_id,
                person_id,
                person_id,
                'screenshot',
                'Image uploaded',
                'Image uploaded',
                '/uploads/candidate-headshot.jpg',
                'headshot.png',
                'image',
                'profile_picture',
                0.99,
                'confirmed',
                1,
                f'dupe-{artifact_id}',
                'processed',
                now,
                now,
            ),
        )

    asyncio.run(run_write(setup))

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        async def create(self, model=None, messages=None, tools=None, **kwargs):
            self.calls += 1
            if self.calls == 1:
                tool_call = SimpleNamespace(
                    id='tool-1',
                    function=SimpleNamespace(
                        name='apply_profile_photo',
                        arguments=json.dumps({})
                    ),
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[tool_call]))]
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='Profile photo updated.', tool_calls=None))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(ai_service, '_get_client', lambda: fake_client)

    result = asyncio.run(
        ai_service.profile_chat(
            person_id,
            {"person_id": person_id, "full_name": "Brian Schofield", "profile_photo_url": "/uploads/original.jpg"},
            "Please use this for the profile photo.",
            history=[],
        )
    )

    assert result["operations"][0]["type"] == "apply_profile_photo"
    assert result["operations"][0]["media_url"] == "/uploads/candidate-headshot.jpg"

    async def verify(db):
        async with db.execute("SELECT profile_photo_url FROM PERSON WHERE person_id = ?", (person_id,)) as cursor:
            person_row = await cursor.fetchone()
        async with db.execute("SELECT requires_confirmation FROM AI_ARTIFACT WHERE artifact_id = ?", (artifact_id,)) as cursor:
            artifact_row = await cursor.fetchone()
        async with db.execute(
            "SELECT summary, media_url FROM INTERACTION WHERE person_id = ? AND channel = 'system_audit' ORDER BY created_at DESC LIMIT 1",
            (person_id,),
        ) as cursor:
            audit_row = await cursor.fetchone()
        return person_row["profile_photo_url"], artifact_row["requires_confirmation"], dict(audit_row)

    photo_url, requires_confirmation, audit_row = asyncio.run(run_read(verify))
    assert photo_url == "/uploads/candidate-headshot.jpg"
    assert requires_confirmation == 0
    assert audit_row["media_url"] == "/uploads/candidate-headshot.jpg"
    assert "Profile photo updated" in audit_row["summary"]


def test_profile_chat_prompt_allows_proactive_task_suggestions(monkeypatch):
    captured = {}

    class FakeCompletions:
        async def create(self, model=None, messages=None, tools=None, **kwargs):
            captured["messages"] = messages
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="We should set a task to call Brian after Eid and lock in coffee.", tool_calls=None))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(ai_service, "_get_client", lambda: fake_client)

    result = asyncio.run(
        ai_service.profile_chat(
            "person-1",
            {"person_id": "person-1", "full_name": "Brian Schofield", "profile_photo_url": ""},
            "What should I do with this?",
            history=[],
        )
    )

    system_message = captured["messages"][0]["content"]
    assert "proactively suggest a concrete task or follow-up" in system_message
    assert "call Brian after Eid and lock in coffee" in system_message
    assert result["response"].startswith("We should set a task")
    assert result["operations"] == []


def test_normalize_due_date_for_message_rolls_relative_weekdays_forward():
    stale_monday = "2023-10-16"
    normalized = ai_service._normalize_due_date_for_message(
        "follow up on Monday if we have not heard back yet",
        stale_monday,
    )
    today = datetime.now(timezone.utc).date()
    expected_delta = (0 - today.weekday()) % 7
    if expected_delta == 0:
        expected_delta = 7
    expected = (today + timedelta(days=expected_delta)).isoformat()
    assert normalized == expected


def test_normalize_due_date_for_message_keeps_explicit_iso_dates():
    explicit_date = "2026-04-07"
    normalized = ai_service._normalize_due_date_for_message(
        "set the follow up for 2026-04-07 at 09:00",
        explicit_date,
    )
    assert normalized == explicit_date


def test_preference_profile_learns_from_missed_follow_up_feedback():
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    interaction_id = f"i-{uuid.uuid4().hex[:8]}"
    now = '2026-03-12T00:00:00Z'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, 'Brian Schofield', now, now),
        )
        await db.execute(
            "INSERT OR REPLACE INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (
                interaction_id,
                person_id,
                'chat',
                'You should have suggested a task to call Brian after Eid for coffee.',
                'Corrective feedback about missed follow-up suggestion.',
                now,
                now,
            ),
        )

    asyncio.run(run_write(setup))
    asyncio.run(
        record_feedback_event(
            target_type='interaction',
            target_id=interaction_id,
            event_type='missed_follow_up',
            details={
                'person_id': person_id,
                'text': 'You should have suggested a task to call Brian after Eid for coffee.',
                'preferred_behavior': 'proactive_follow_up',
            },
        )
    )

    profile = asyncio.run(ai_service.compute_preference_profile(person_id))
    guidance = ai_service.preference_guidance_lines(profile)

    assert profile['scores']['proactive_follow_through'] > 0
    assert any('Proactively surface concrete next-step follow-ups' in line for line in guidance)


def test_chat_route_records_missed_follow_up_feedback(monkeypatch):
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    now = '2026-03-12T00:00:00Z'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, 'Brian Schofield', now, now),
        )

    asyncio.run(run_write(setup))

    async def fake_profile_chat(person_id, person, message, history):
        return {'response': 'Noted.', 'operations': []}

    monkeypatch.setattr(ai_service, 'profile_chat', fake_profile_chat)

    authed = login_client()
    try:
        res = authed.post(
            f'/api/intelligence/chat/{person_id}',
            json={'message': 'You should have suggested a task to call Brian after Eid for coffee.', 'history': []},
        )
        assert res.status_code == 200
    finally:
        authed.close()

    async def check(db):
        async with db.execute(
            "SELECT event_type, details_json FROM AI_FEEDBACK WHERE target_type='interaction' ORDER BY created_at DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    feedback = asyncio.run(run_read(check))
    assert feedback is not None
    assert feedback['event_type'] == 'missed_follow_up'
    assert 'after Eid for coffee' in feedback['details_json']


def test_chat_route_does_not_persist_stage_or_profile_completion_control_prompts(monkeypatch):
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    now = '2026-03-12T00:00:00Z'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, 'Control Prompt Contact', now, now),
        )

    asyncio.run(run_write(setup))

    async def fake_profile_chat(person_id, person, message, history):
        return {'response': 'Acknowledged.', 'operations': []}

    monkeypatch.setattr(ai_service, 'profile_chat', fake_profile_chat)

    control_messages = [
        'show stages please',
        'what information is missing to complete profile?',
        'need infortmation for provideing data to compleate profile',
    ]

    authed = login_client()
    try:
        for message in control_messages:
            res = authed.post(
                f'/api/intelligence/chat/{person_id}',
                json={'message': message, 'history': []},
            )
            assert res.status_code == 200
            assert res.json().get('interaction_id') is None
    finally:
        authed.close()

    async def check(db):
        async with db.execute(
            "SELECT COUNT(*) AS count FROM INTERACTION WHERE person_id=?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row['count'] or 0)

    interaction_count = asyncio.run(run_read(check))
    assert interaction_count == 0


def test_chat_route_native_stage_list_request_is_not_persisted():
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    now = '2026-03-12T00:00:00Z'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
            (person_id, 'Native Stage Prompt Contact', now, now),
        )

    asyncio.run(run_write(setup))

    authed = login_client()
    try:
        res = authed.post(
            f'/api/intelligence/chat/{person_id}',
            json={'message': 'show stages please', 'history': []},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload.get('interaction_id') is None
        assert 'Relationship Stages' in payload.get('response', '')
    finally:
        authed.close()

    async def check(db):
        async with db.execute(
            "SELECT COUNT(*) AS count FROM INTERACTION WHERE person_id=?",
            (person_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row['count'] or 0)

    interaction_count = asyncio.run(run_read(check))
    assert interaction_count == 0


def test_strategist_v2_synthesis_logs_result(monkeypatch):
    person_id = f"p-{uuid.uuid4().hex[:8]}"
    now = '2026-03-11T00:00:00Z'

    async def setup(db):
        await db.execute(
            """
            INSERT OR REPLACE INTO PERSON (
                person_id, full_name, title_current, company_name_raw, cat, env, disc, created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (person_id, 'Strategy Test', 'Director', 'Antigravity', 'GEN', 'Developer - Private', 'Delivery', now, now),
        )
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, summary, raw_text, created_at, interaction_at) VALUES (?,?,?,?,?,?,?)",
            (f'i-{person_id}', person_id, 'meeting', 'Discussed hiring needs', 'Hiring pressure in Riyadh is growing.', now, now),
        )
        await db.execute(
            "INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, source_snippet, created_at) VALUES (?,?,?,?,?,?,?)",
            (f'intel-{person_id}', person_id, 'recruitment_talent', 'Hiring pressure is rising in Riyadh.', 4, 'Hiring pressure in Riyadh is growing.', now),
        )
        await db.execute(
            "INSERT INTO PLATFORM_MEMORY (memory_id, memory_type, entity_ref, memory_text, strength, last_reinforced, created_at) VALUES (?,?,?,?,?,?,?)",
            (f'memory-{person_id}', 'market_trend', 'Riyadh', 'Hiring competition for project managers is intensifying.', 4, now, now),
        )

    asyncio.run(run_write(setup))

    async def fake_run_json_chat_task(**kwargs):
        return ({
            'behavioral_analysis': 'Clear operator with hiring pressure.',
            'intelligence_gaps': ['Confirm the timing of the Riyadh hiring push.'],
            'strategic_hypotheses': ['Talent scarcity is shaping decision speed.'],
            'platform_connections': ['Riyadh hiring trend aligns with platform memory.'],
            'sitrep_brief': 'Hiring pressure is the main live issue.'
        }, 'run-1')

    monkeypatch.setattr(strategist_service, 'run_json_chat_task', fake_run_json_chat_task)

    authed = login_client()
    try:
        res = authed.post(f'/api/v2/intelligence/synthesize/{person_id}')
    finally:
        authed.close()

    assert res.status_code == 200
    payload = res.json()
    assert payload['sitrep_brief'] == 'Hiring pressure is the main live issue.'
    assert payload['intelligence_gaps'][0].startswith('Confirm the timing')

    async def check(db):
        async with db.execute(
            """
            SELECT summary
            FROM INTERACTION
            WHERE person_id=? AND channel='system_audit'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (person_id,),
        ) as c:
            row = await c.fetchone()
        return row['summary']

    summary = asyncio.run(run_read(check))
    assert 'Platinum Synthesis' in summary
