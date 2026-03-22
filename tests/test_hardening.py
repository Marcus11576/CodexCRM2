import uuid

import httpx
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.auth_service import create_user, get_user_by_email

TEST_BASE_URL = "https://testserver"


def ensure_test_user(email: str, password: str, full_name: str = "Audit User"):
    import asyncio

    existing = asyncio.run(get_user_by_email(email))
    if existing:
        return existing
    return asyncio.run(create_user(email, full_name, password, role="admin"))


def login_client(email: str | None = None, password: str = 'password123') -> tuple[TestClient, dict]:
    email = email or f"audit-{uuid.uuid4().hex[:8]}@example.com"
    user = ensure_test_user(email, password)
    authed = TestClient(app, base_url=TEST_BASE_URL)
    response = authed.post('/api/auth/login', json={'email': email, 'password': password})
    assert response.status_code == 200
    assert response.cookies.get('session_token')
    return authed, user


def test_unauthorized_api_access():
    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.get('/api/people')
    finally:
        client.close()
    assert response.status_code == 401


def test_unauthorized_page_redirect():
    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.get('/', follow_redirects=False)
    finally:
        client.close()
    assert response.status_code == 307
    assert response.headers['location'] == '/login'


def test_unauthorized_uploads_access():
    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.get('/uploads/any_file.jpg')
    finally:
        client.close()
    assert response.status_code == 401


def test_login_flow_and_session_cookie():
    email = f"audit-{uuid.uuid4().hex[:8]}@example.com"
    password = 'password123'
    ensure_test_user(email, password)

    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.post('/api/auth/login', json={'email': email, 'password': password})
    finally:
        client.close()
    assert response.status_code == 200
    assert 'session_token' in response.cookies

    authed = TestClient(app, base_url=TEST_BASE_URL)
    try:
        authed.cookies.set('session_token', response.cookies.get('session_token'))
        me = authed.get('/api/auth/me')
    finally:
        authed.close()
    assert me.status_code == 200
    assert me.json()['email'] == email


def test_error_sanitization():
    authed, _ = login_client()
    try:
        response = authed.get('/api/analytics/network-pulse')
    finally:
        authed.close()
    assert response.status_code == 200
    assert 'traceback' not in response.text.lower()


def test_auth_status_exposes_microsoft_availability(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    monkeypatch.setattr(settings, 'M365_CLIENT_ID', 'client-id')
    monkeypatch.setattr(settings, 'M365_TENANT_ID', 'tenant-id')
    monkeypatch.setattr(settings, 'M365_CLIENT_SECRET', 'client-secret')

    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        response = client.get('/api/auth/status')
    finally:
        client.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload['microsoft_oauth_enabled'] is True
    assert payload['microsoft_device_enabled'] is True


def test_microsoft_callback_creates_session(monkeypatch):
    from backend.config import settings
    from backend.routers import auth as auth_router

    monkeypatch.setattr(settings, 'M365_ENABLED', True)
    monkeypatch.setattr(settings, 'M365_CLIENT_ID', 'client-id')
    monkeypatch.setattr(settings, 'M365_TENANT_ID', 'tenant-id')
    monkeypatch.setattr(settings, 'M365_CLIENT_SECRET', 'client-secret')
    monkeypatch.setattr(settings, 'M365_AUTH_REDIRECT_URI', 'https://testserver/api/auth/microsoft/callback')
    auth_router._microsoft_states.clear()

    class DummyResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    async def fake_post(self, url, data=None, timeout=None):
        assert url.endswith('/token')
        assert data['grant_type'] == 'authorization_code'
        return DummyResp({'access_token': 'ms-access-token'})

    async def fake_get(self, url, headers=None, params=None, timeout=None):
        assert url.endswith('/me')
        return DummyResp({
            'id': 'ms-user-123',
            'displayName': 'Marcus Taylor',
            'mail': 'marcus@example.com',
            'userPrincipalName': 'marcus@example.com',
        })

    monkeypatch.setattr(httpx.AsyncClient, 'post', fake_post)
    monkeypatch.setattr(httpx.AsyncClient, 'get', fake_get)

    client = TestClient(app, base_url=TEST_BASE_URL)
    try:
        start = client.get('/api/auth/microsoft/start', follow_redirects=False)
        assert start.status_code == 302
        callback_url = start.headers['location']
        state = callback_url.split('state=')[1].split('&', 1)[0]

        callback = client.get(
            f'/api/auth/microsoft/callback?code=test-code&state={state}',
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert callback.headers['location'] == '/'
        assert callback.cookies.get('session_token')

        me = client.get('/api/auth/me')
    finally:
        client.close()

    assert me.status_code == 200
    assert me.json()['email'] == 'marcus@example.com'
