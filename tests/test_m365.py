import asyncio

from fastapi.testclient import TestClient
from backend.main import app
from backend.config import settings
import httpx

client = TestClient(app)


def test_m365_initial_state():
    # by default feature is disabled in example env
    assert not settings.M365_ENABLED

    res = client.get("/api/m365/auth/status")
    assert res.status_code == 200
    assert res.json()["status"] in ("disabled", "unauthenticated")

    res2 = client.post("/api/m365/auth/start")
    assert res2.status_code == 200
    assert res2.json()["status"] == "disabled"

    res3 = client.get("/api/m365/account/someid")
    assert res3.status_code == 200
    assert res3.json()["status"] in ("disabled", "not_found")


def test_refresh_tokens(monkeypatch):
    """Verify that expired credentials are refreshed via the refresh endpoint."""
    settings.M365_ENABLED = True
    from backend.routers import m365
    # write expired credentials directly
    def write_creds():
        from backend.database import get_sync_db
        conn = get_sync_db()
        conn.execute("INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))", ("old", "rftok", "2000-01-01T00:00:00",))
        conn.commit()
    write_creds()

    # patch HTTP call to token endpoint
    class DummyResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"access_token": "newtok", "refresh_token": "newrftok", "expires_in": 3600}
    async def fake_post(*args, **kwargs):
        return DummyResp()
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    creds = asyncio.run(m365._get_credentials())
    assert creds["access_token"] == "newtok"
    assert creds["refresh_token"] == "newrftok"


def test_sync_account(monkeypatch):
    """Syncing should create an interaction entry and dedupe existing ones."""
    settings.M365_ENABLED = True
    from backend.services import m365_worker
    from backend.database import run_write, run_read

    # create person with email
    person_id = "p1"
    async def create_person(db):
        await db.execute("INSERT OR REPLACE INTO PERSON (person_id, full_name, email_primary, created_at, last_updated_at) VALUES (?,?,?,?,?)", (person_id, "Test", "foo@example.com", "now", "now"))
    asyncio.run(run_write(create_person))

    # clear any leftover interactions for the test person
    from backend.database import get_sync_db
    dbconn = get_sync_db()
    dbconn.execute("DELETE FROM INTERACTION WHERE person_id=?", (person_id,))
    dbconn.commit()

    # stub Graph response with one message
    fake_msg = {"value": [{"id": "m1", "subject": "Hi", "bodyPreview": "Hello", "receivedDateTime": "2026-03-09T00:00:00Z"}]}
    class DummyResp2:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_msg
    async def fake_get(self, url, headers=None, params=None, timeout=None):
        return DummyResp2()
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    # run sync
    new_count = asyncio.run(m365_worker._sync_account(person_id, "tok"))
    assert new_count == 1
    # running again should return 0 (dedup)
    new_count2 = asyncio.run(m365_worker._sync_account(person_id, "tok"))
    assert new_count2 == 0

    # also exercise HTTP endpoint
    # ensure global credentials row exists
    from backend.database import get_sync_db
    conn = get_sync_db()
    conn.execute("INSERT OR REPLACE INTO M365_CREDENTIALS (id, access_token, refresh_token, token_expires_at, created_at) VALUES (1,?,?,?,datetime('now'))", ("tok", "r", "2099-01-01T00:00:00",))
    conn.commit()
    res = client.get(f"/api/m365/emails/{person_id}")
    assert res.status_code == 200
    assert res.json()["new_synced"] == 0
