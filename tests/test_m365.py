import asyncio
import uuid

import httpx
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import settings
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def login_client(password: str = 'password123') -> TestClient:
    import asyncio as _asyncio

    email = f"m365-{uuid.uuid4().hex[:8]}@example.com"
    existing = _asyncio.run(get_user_by_email(email))
    if not existing:
        _asyncio.run(create_user(email, 'M365 Audit User', password, role='admin'))
    authed = TestClient(app, base_url=TEST_BASE_URL)
    response = authed.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    return authed


def test_m365_disabled_state(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', False)
    authed = login_client()
    try:
        res = authed.get('/api/m365/auth/status')
        assert res.status_code == 200
        assert res.json()['status'] == 'disabled'

        res2 = authed.post('/api/m365/auth/start')
        assert res2.status_code == 200
        assert res2.json()['status'] == 'disabled'

        res3 = authed.get('/api/m365/account/someid')
        assert res3.status_code == 200
        assert res3.json()['status'] == 'disabled'

        res4 = authed.get('/api/m365/overview')
        assert res4.status_code == 200
        assert res4.json()['status'] == 'disabled'
    finally:
        authed.close()


def test_refresh_tokens(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.routers import m365
    from backend.database import get_sync_db

    conn = get_sync_db()
    conn.execute('DELETE FROM M365_CREDENTIALS')
    conn.execute("INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))", ('old', 'rftok', '2000-01-01T00:00:00'))
    conn.commit()
    conn.close()

    class DummyResp:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {'access_token': 'newtok', 'refresh_token': 'newrftok', 'expires_in': 3600}

    async def fake_post(self, *args, **kwargs):
        return DummyResp()

    monkeypatch.setattr(httpx.AsyncClient, 'post', fake_post)

    creds = asyncio.run(m365._get_credentials())
    assert creds['access_token'] == 'newtok'
    assert creds['refresh_token'] == 'newrftok'


def test_sync_account(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.services import m365_worker
    from backend.database import run_write, get_sync_db

    person_id = f'm365-test-person-{uuid.uuid4().hex[:8]}'
    message_id = f'm365-message-{uuid.uuid4().hex[:8]}'

    async def create_person(db):
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, email_primary, created_at, last_updated_at) VALUES (?,?,?,?,?)", (person_id, 'Test', 'foo@example.com', 'now', 'now'))

    asyncio.run(run_write(create_person))

    dbconn = get_sync_db()
    dbconn.execute('DELETE FROM INTERACTION WHERE person_id=?', (person_id,))
    dbconn.execute('DELETE FROM INTERACTION WHERE external_id=?', (message_id,))
    dbconn.execute('DELETE FROM M365_CREDENTIALS')
    dbconn.commit()
    dbconn.close()

    fake_msg = {'value': [{'id': message_id, 'subject': 'Hi', 'bodyPreview': 'Hello', 'receivedDateTime': '2026-03-09T00:00:00Z'}]}

    class DummyResp2:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return fake_msg

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        return DummyResp2()

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    new_count = asyncio.run(m365_worker._sync_account(person_id, 'tok'))
    assert new_count == 1
    new_count2 = asyncio.run(m365_worker._sync_account(person_id, 'tok'))
    assert new_count2 == 0

    conn = get_sync_db()
    conn.execute("INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))", ('tok', 'r', '2099-01-01T00:00:00'))
    conn.commit()
    conn.close()

    authed = login_client()
    try:
        res = authed.get(f'/api/m365/emails/{person_id}')
    finally:
        authed.close()
    assert res.status_code == 200
    assert res.json()['new_synced'] == 0


def test_fetch_emails_returns_preview_and_updates_status(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.database import run_write, run_read, get_sync_db

    person_id = f'm365-preview-person-{uuid.uuid4().hex[:8]}'
    message_id = f'm365-preview-message-{uuid.uuid4().hex[:8]}'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, email_primary, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, 'Preview Test', 'preview@example.com', 'now', 'now'),
        )

    asyncio.run(run_write(setup))

    conn = get_sync_db()
    conn.execute(
        "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))",
        ('tok', 'r', '2099-01-01T00:00:00'),
    )
    conn.commit()
    conn.close()

    class DummyResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError('boom', request=None, response=self)

        def json(self):
            return self._payload

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        if url.endswith('/me'):
            return DummyResp({'id': 'me'})
        return DummyResp({
            'value': [{
                'id': message_id,
                'subject': 'Status update',
                'bodyPreview': 'Shared the updated schedule.',
                'receivedDateTime': '2026-03-10T08:00:00Z',
                'sender': {'emailAddress': {'address': 'preview@example.com'}},
                'toRecipients': [],
                'ccRecipients': [],
            }]
        })

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    authed = login_client()
    try:
        res = authed.get(f'/api/m365/emails/{person_id}')
    finally:
        authed.close()

    assert res.status_code == 200
    payload = res.json()
    assert payload['status'] == 'success'
    assert payload['new_synced'] == 1
    assert payload['emails'][0]['subject'] == 'Status update'

    async def check(db):
        async with db.execute(
            'SELECT sync_status, last_synced_count, last_sync_at FROM M365_ACCOUNT WHERE person_id=?',
            (person_id,),
        ) as c:
            row = await c.fetchone()
        return dict(row)

    status_row = asyncio.run(run_read(check))
    assert status_row['sync_status'] == 'idle'
    assert status_row['last_synced_count'] == 1
    assert status_row['last_sync_at']


def test_send_email_records_local_interaction(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.database import run_write, run_read, get_sync_db

    person_id = f'm365-send-person-{uuid.uuid4().hex[:8]}'

    async def setup(db):
        await db.execute(
            "INSERT OR REPLACE INTO PERSON (person_id, full_name, email_primary, created_at, last_updated_at) VALUES (?,?,?,?,?)",
            (person_id, 'Send Test', 'send@example.com', 'now', 'now'),
        )

    asyncio.run(run_write(setup))

    conn = get_sync_db()
    conn.execute(
        "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))",
        ('tok', 'r', '2099-01-01T00:00:00'),
    )
    conn.commit()
    conn.close()

    class DummyResp:
        def __init__(self, payload=None, status_code=200):
            self._payload = payload or {}
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError('boom', request=None, response=self)

        def json(self):
            return self._payload

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        assert url.endswith('/me')
        return DummyResp({'id': 'me'})

    async def fake_post(self, url, headers=None, json=None, data=None, timeout=None):
        assert url.endswith('/sendMail')
        assert json['message']['subject'] == 'Intro'
        assert json['message']['toRecipients'][0]['emailAddress']['address'] == 'send@example.com'
        return DummyResp({}, status_code=202)

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)
    monkeypatch.setattr(httpx.AsyncClient, 'post', fake_post)

    authed = login_client()
    try:
        res = authed.post(
            f'/api/m365/emails/{person_id}/send',
            json={'subject': 'Intro', 'body': 'Looking forward to meeting.'},
        )
    finally:
        authed.close()

    assert res.status_code == 200
    assert res.json()['status'] == 'success'

    async def check(db):
        async with db.execute(
            """
            SELECT summary, raw_text, external_id
            FROM INTERACTION
            WHERE person_id=? AND channel='email'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (person_id,),
        ) as c:
            row = await c.fetchone()
        return dict(row)

    row = asyncio.run(run_read(check))
    assert row['summary'] == 'Intro'
    assert row['raw_text'] == 'Looking forward to meeting.'
    assert row['external_id'].startswith('local-send:')


def test_auth_status_returns_connected_account_summary(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.database import get_sync_db

    conn = get_sync_db()
    conn.execute(
        "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))",
        (
            'eyJhbGciOiJub25lIn0.eyJzY3AiOiJNYWlsLlJlYWQgTWFpbC5TZW5kIENhbGVuZGFycy5SZWFkIiwidXBuIjoibWFyY3VzQGV4YW1wbGUuY29tIiwibmFtZSI6Ik1hcmN1cyBUYXlsb3IiLCJ0aWQiOiJ0ZW5hbnQtMTIzIn0.sig',
            'r',
            '2099-01-01T00:00:00',
        ),
    )
    conn.commit()
    conn.close()

    class DummyResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError('boom', request=None, response=self)

        def json(self):
            return self._payload

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        if url.endswith('/me'):
            return DummyResp({
                'id': 'user-1',
                'displayName': 'Marcus Taylor',
                'userPrincipalName': 'marcus@example.com',
                'mail': 'marcus@example.com',
            })
        return DummyResp({}, status_code=200)

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    authed = login_client()
    try:
        res = authed.get('/api/m365/overview')
    finally:
        authed.close()

    assert res.status_code == 200
    payload = res.json()
    assert payload['status'] == 'authenticated'
    assert payload['account']['email'] == 'marcus@example.com'
    assert payload['features']['mail_send'] is True
    assert payload['features']['calendar_read'] is True


def test_calendar_events_endpoint_returns_preview(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.database import get_sync_db

    conn = get_sync_db()
    conn.execute(
        "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))",
        ('tok', 'r', '2099-01-01T00:00:00'),
    )
    conn.commit()
    conn.close()

    class DummyResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError('boom', request=None, response=self)

        def json(self):
            return self._payload

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        if url.endswith('/me'):
            return DummyResp({'id': 'me'})
        return DummyResp({
            'value': [
                {
                    'id': 'evt-1',
                    'subject': 'Board prep',
                    'start': {'dateTime': '2026-03-13T09:00:00Z'},
                    'end': {'dateTime': '2026-03-13T10:00:00Z'},
                    'location': {'displayName': 'Teams'},
                }
            ]
        })

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    authed = login_client()
    try:
        res = authed.get('/api/m365/calendar/events?days=7&limit=5')
    finally:
        authed.close()

    assert res.status_code == 200
    payload = res.json()
    assert payload['status'] == 'success'
    assert payload['days'] == 7
    assert payload['events'][0]['subject'] == 'Board prep'


def test_full_sync_links_mailbox_and_calendar_to_matching_contacts(monkeypatch):
    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    from backend.database import run_write, run_read, get_sync_db

    person_id = f'm365-full-person-{uuid.uuid4().hex[:8]}'
    email_message_id = f'm365-full-message-{uuid.uuid4().hex[:8]}'
    event_id = f'm365-full-event-{uuid.uuid4().hex[:8]}'

    async def setup(db):
        await db.execute(
            """
            INSERT OR REPLACE INTO PERSON (
                person_id, full_name, email_primary, created_at, last_updated_at
            ) VALUES (?,?,?,?,?)
            """,
            (person_id, 'Full Sync Test', 'fullsync@example.com', 'now', 'now'),
        )

    asyncio.run(run_write(setup))

    conn = get_sync_db()
    conn.execute("DELETE FROM INTERACTION WHERE person_id=?", (person_id,))
    conn.execute(
        "INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))",
        ('tok', 'r', '2099-01-01T00:00:00'),
    )
    conn.commit()
    conn.close()

    class DummyResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError('boom', request=None, response=self)

        def json(self):
            return self._payload

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        if url.endswith('/me'):
            return DummyResp({'id': 'me'})
        if url.endswith('/me/messages'):
            return DummyResp({
                'value': [{
                    'id': email_message_id,
                    'subject': 'Intro email',
                    'bodyPreview': 'Can we meet next week?',
                    'receivedDateTime': '2026-03-10T08:00:00Z',
                    'sender': {'emailAddress': {'address': 'fullsync@example.com'}},
                    'toRecipients': [],
                    'ccRecipients': [],
                    'bccRecipients': [],
                    'replyTo': [],
                }]
            })
        return DummyResp({
            'value': [{
                'id': event_id,
                'subject': 'Project catch-up',
                'start': {'dateTime': '2026-03-20T09:00:00Z'},
                'end': {'dateTime': '2026-03-20T10:00:00Z'},
                'location': {'displayName': 'Teams'},
                'organizer': {'emailAddress': {'address': 'owner@example.com'}},
                'attendees': [{'emailAddress': {'address': 'fullsync@example.com'}}],
                'webLink': 'https://teams.microsoft.com/l/meetup-join/test',
            }]
        })

    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    authed = login_client()
    try:
        res = authed.post('/api/m365/sync/full?days=30&limit=50')
    finally:
        authed.close()

    assert res.status_code == 200
    payload = res.json()
    assert payload['status'] == 'success'
    assert payload['summary']['mailbox']['new_emails'] == 1
    assert payload['summary']['calendar']['new_meetings'] == 1
    assert payload['summary']['calendar']['scheduled_contacts'] == 1

    async def check(db):
        async with db.execute(
            """
            SELECT next_meeting_topic, next_meeting_date
            FROM PERSON
            WHERE person_id=?
            """,
            (person_id,),
        ) as c:
            person_row = await c.fetchone()
        async with db.execute(
            """
            SELECT channel, summary, external_id
            FROM INTERACTION
            WHERE person_id=?
            ORDER BY created_at DESC
            """,
            (person_id,),
        ) as c:
            rows = await c.fetchall()
        return dict(person_row), [dict(row) for row in rows]

    person_row, interactions = asyncio.run(run_read(check))
    assert person_row['next_meeting_topic'] == 'Project catch-up'
    assert person_row['next_meeting_date'].startswith('2026-03-20T09:00:00')
    assert any(row['channel'] == 'email' and row['external_id'] == email_message_id for row in interactions)
    assert any(row['channel'] == 'meeting' and row['external_id'] == f'm365-event:{event_id}:{person_id}' for row in interactions)
