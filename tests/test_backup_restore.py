import os
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

from fastapi.testclient import TestClient

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.main import app
from backend.config import settings
from backend.services.backup_service import run_backup, get_next_backup_run
from backend.services.auth_service import create_user, get_user_by_email
from scripts.restore import restore_backup

TEST_BASE_URL = "https://testserver"


def login_client(password: str = "password123") -> TestClient:
    import asyncio as _asyncio

    email = f"backup-{uuid.uuid4().hex[:8]}@example.com"
    existing = _asyncio.run(get_user_by_email(email))
    if not existing:
        _asyncio.run(create_user(email, "Backup Audit User", password, role="admin"))
    client = TestClient(app, base_url=TEST_BASE_URL)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


def _read_restored_row(db_path: Path):
    with tempfile.TemporaryDirectory(prefix='restore_verify_') as temp_dir:
        snapshot = Path(temp_dir) / 'crm.db'
        shutil.copy2(db_path, snapshot)
        conn = sqlite3.connect(snapshot)
        try:
            return conn.execute("SELECT val FROM _test_backup").fetchone()
        finally:
            conn.close()


def test_backup_restore_lifecycle():
    print("--- STARTING BACKUP/RESTORE VERIFICATION TEST ---")

    db_path = Path(settings.DB_PATH).resolve()
    test_val = f"TEST_RECORD_{datetime.now().timestamp()}"

    print(f"1. Creating test record in database: {test_val}")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS _test_backup (val TEXT)")
    conn.execute("DELETE FROM _test_backup")
    conn.execute("INSERT INTO _test_backup (val) VALUES (?)", (test_val,))
    conn.commit()
    conn.close()
    time.sleep(0.5)

    uploads_dir = Path(settings.UPLOADS_DIR).resolve()
    os.makedirs(uploads_dir, exist_ok=True)
    test_file = uploads_dir / "test_backup.txt"
    test_file.write_text("RESTORE_SUCCESS")
    print(f"2. Created test upload: {test_file}")

    print("3. Running Backup...")
    backup_file = run_backup(label="test")
    print(f"[OK] Backup created: {backup_file}")

    backup_name = Path(backup_file).name

    print("4. Deleting local data to simulate loss...")
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM _test_backup")
    conn.commit()
    conn.close()

    if test_file.exists():
        test_file.unlink()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT val FROM _test_backup").fetchone()
    conn.close()
    assert row is None, "Test record should be deleted before restore"
    assert not test_file.exists(), "Test file should be deleted before restore"
    print("[OK] Data deleted successfully.")

    print("5. Running Restore...")
    import builtins
    original_input = builtins.input
    builtins.input = lambda _: "RESTORE"

    success = restore_backup(backup_name)
    builtins.input = original_input

    assert success, "Restore operation failed"
    print("[OK] Restore reported success.")

    print("6. Verifying restored data...")
    time.sleep(1)
    row = _read_restored_row(db_path)

    if row is None:
        print("ERROR: Test record is missing from database after restore!")
    elif row[0] != test_val:
        print(f"ERROR: Found incorrect value in database: {row[0]} (Expected: {test_val})")

    assert row is not None and row[0] == test_val, "Restored database data is incorrect"

    assert test_file.exists(), "Restored upload file is missing"
    assert test_file.read_text() == "RESTORE_SUCCESS", "Restored upload content is incorrect"

    print("\n--- ALL TESTS PASSED: BACKUP/RESTORE SYSTEM IS ROBUST ---")

    if Path(backup_file).exists():
        Path(backup_file).unlink()
    external_backup = Path(settings.BACKUP_EXTERNAL_DIR) / backup_name
    if external_backup.exists():
        external_backup.unlink()


def test_backup_status_endpoint_reports_latest_backup(monkeypatch):
    backup_dir = Path(settings.BACKUP_DIR).resolve()
    external_dir = Path(settings.BACKUP_EXTERNAL_DIR).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    external_dir.mkdir(parents=True, exist_ok=True)

    latest = backup_dir / "backup_daily_20990101_010203.zip"
    latest.write_text("backup")
    old = external_dir / "backup_weekly_19990101_010203.zip"
    old.write_text("backup")

    latest_ts = time.time()
    os.utime(latest, (latest_ts, latest_ts))
    old_ts = latest_ts - 3600
    os.utime(old, (old_ts, old_ts))

    client = login_client()
    try:
        res = client.get("/api/health/backups/status")
        assert res.status_code == 200
        payload = res.json()
        assert payload["exists"] is True
        assert payload["filename"] == latest.name
        assert payload["label"] == "daily"
        assert payload["location"] == "local"
        assert payload["last_backup_at"]
    finally:
        client.close()
        latest.unlink(missing_ok=True)
        old.unlink(missing_ok=True)


def test_fixed_backup_schedule_rolls_to_next_day_when_past():
    now = datetime(2026, 3, 13, 4, 0, 0, tzinfo=settings.BACKUP_ZONEINFO).astimezone(timezone.utc)
    next_run = get_next_backup_run(now)
    next_local = next_run.astimezone(settings.BACKUP_ZONEINFO)
    assert next_local.hour == settings.BACKUP_SCHEDULE_HOUR
    assert next_local.minute == settings.BACKUP_SCHEDULE_MINUTE
    assert next_local.date() >= now.astimezone(settings.BACKUP_ZONEINFO).date()


def test_manual_backup_endpoint_returns_fresh_metadata():
    client = login_client()
    try:
        res = client.post("/api/health/backups/run")
        assert res.status_code == 200
        payload = res.json()
        assert payload["exists"] is True
        assert payload["filename"]
        assert payload["next_backup_at"]
    finally:
        client.close()


if __name__ == "__main__":
    try:
        test_backup_restore_lifecycle()
    except Exception as e:
        print(f"\nTEST FAILED: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
