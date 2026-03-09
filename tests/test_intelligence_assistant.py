import asyncio
from fastapi.testclient import TestClient
from backend.main import app
from backend.services import ai_service
from backend.database import run_write, run_read, get_sync_db

client = TestClient(app)


def test_intelligence_review_and_feedback(monkeypatch):
    # prepare test data: person, one intelligence row and one future event
    person_id = "p2"

    async def setup(db):
        now = "2026-03-09T00:00:00Z"
        # ensure new columns exist so test can run regardless of previous schema
        try:
            await db.execute("ALTER TABLE TOPIC_INTELLIGENCE ADD COLUMN status TEXT DEFAULT 'draft'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE TOPIC_INTELLIGENCE ADD COLUMN source_snippet TEXT")
        except Exception:
            pass
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
                         (person_id, "Test Person", now, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)",
                         ("i1", person_id, "business_focus", "Initial signal text", 3, now))
        await db.execute("INSERT OR REPLACE INTO EVENT (event_id, event_name, event_date, created_at, updated_at) VALUES (?,?,?,?,?)",
                         ("e1", "Future Summit", "2099-01-01T00:00:00Z", now, now))
        await db.execute("INSERT OR REPLACE INTO PERSON_EVENT (person_event_id, person_id, event_id, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                         ("pe1", person_id, "e1", "invited", now, now))
    asyncio.run(run_write(setup))

    # monkeypatch the AI service to capture input and return predictable output
    captured = {}

    async def fake_review(person, signals, events):
        captured['person'] = person
        captured['signals'] = signals
        captured['events'] = events
        return {"signals": signals, "brief": {"business_focus": "ok", "recruitment_talent": "", "personal_rapport": "", "obe_focus": "", "strategic_hypotheses": [], "audio_script": ""}}

    monkeypatch.setattr(ai_service, "review_signals", fake_review)

    # call the review endpoint
    res = client.post(f"/api/intelligence/assistant/{person_id}/review")
    assert res.status_code == 200
    assert res.json()['signals'][0]['text'] == "Initial signal text"
    # verify events passed through
    assert isinstance(captured.get('events'), list)
    assert captured['events'][0]['event_name'] == "Future Summit"

    # test feedback logging endpoint
    fb_payload = {
        "target_type": "signal",
        "target_id": "i1",
        "event_type": "approval",
        "details": {"reason": "looks good"},
        "user_id": "u1"
    }
    fb_res = client.post("/api/ai/feedback", json=fb_payload)
    assert fb_res.status_code == 200
    assert "feedback_id" in fb_res.json()

    # test editing the intelligence entry
    patch_res = client.patch(f"/api/people/{person_id}/intelligence/i1", json={"text": "edited text", "status": "approved"})
    assert patch_res.status_code == 200

    # verify the update persisted
    async def check(db):
        async with db.execute("SELECT intel_text, status FROM TOPIC_INTELLIGENCE WHERE intel_id=?", ("i1",)) as c:
            row = await c.fetchone()
            return dict(row)
    updated = asyncio.run(run_read(check))
    assert updated['intel_text'] == "edited text"
    assert updated['status'] == "approved"


def test_signal_scoring_from_feedback():
    # ensure compute_signal_scores returns values according to past actions
    person_id = "p3"

    async def setup2(db):
        now = "2026-03-09T00:00:00Z"
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
                         (person_id, "Another", now, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)",
                         ("s1", person_id, "business_focus", "A", 3, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)",
                         ("s2", person_id, "business_focus", "B", 3, now))
        # feedback: approve s1 twice, reject s2 once
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)",
                         ("f1", "signal", "s1", "approval", now))
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)",
                         ("f2", "signal", "s1", "approval", now))
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)",
                         ("f3", "signal", "s2", "reject", now))
    asyncio.run(run_write(setup2))

    from backend.services.ai_service import compute_signal_scores
    scores = asyncio.run(compute_signal_scores(person_id))
    assert scores.get('s1', 0) > scores.get('s2', 0)


def test_review_signals_sorting(monkeypatch):
    # build two signals, feedback makes s2 preferred
    person = {'person_id': 'p4'}
    signals = [
        {'intel_id': 's1', 'category': 'business_focus', 'text': 'A', 'snippet': 'A', 'date': '2026-01-01', 'confidence': 3},
        {'intel_id': 's2', 'category': 'business_focus', 'text': 'B', 'snippet': 'B', 'date': '2026-01-02', 'confidence': 3},
    ]
    events = []
    # setup feedback to prefer s2
    async def setup3(db):
        now = "2026-03-09T00:00:00Z"
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, created_at, last_updated_at) VALUES (?,?,?,?)",
                         ('p4', 'X', now, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)",
                         ('s1', 'p4', 'business_focus', 'A', 3, now))
        await db.execute("INSERT OR REPLACE INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)",
                         ('s2', 'p4', 'business_focus', 'B', 3, now))
        # feedback: promote s2
        await db.execute("INSERT INTO AI_FEEDBACK (feedback_id, target_type, target_id, event_type, created_at) VALUES (?,?,?,?,?)",
                         ('f4','signal','s2','promotion',now))
    asyncio.run(run_write(setup3))

    # monkeypatch _get_client to capture messages
    captured = {}
    def fake_get():
        class FakeClient:
            class Chat:
                class Completions:
                    async def create(self, model=None, messages=None, response_format=None, temperature=None, **kwargs):
                        captured['messages'] = messages
                        class R:
                            choices = [type('c',(),{'message':type('m',(),{'content':'{}'})})]
                        return R()
                completions = Completions()
            chat = Chat()
        return FakeClient()
    monkeypatch.setattr('backend.services.ai_service._get_client', fake_get)

    # call review_signals directly
    result = asyncio.run(ai_service.review_signals(person, signals, events))
    # captured messages should include signals JSON with s2 first
    msg = captured.get('messages')[2]['content']  # third message is SIGNALS
    assert 's2' in msg.split('\n')[0]  # first line of signals JSON contains s2
