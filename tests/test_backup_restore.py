import os
import sqlite3
import shutil
import sys
import time
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from backend.config import settings
from backend.services.backup_service import run_backup
from scripts.restore import restore_backup

def test_backup_restore_lifecycle():
    print("--- STARTING BACKUP/RESTORE VERIFICATION TEST ---")
    
    # 1. Setup Test Data
    db_path = Path(settings.DB_PATH).resolve()
    test_val = f"TEST_RECORD_{datetime.now().timestamp()}"
    
    print(f"1. Creating test record in database: {test_val}")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS _test_backup (val TEXT)")
    conn.execute("DELETE FROM _test_backup")
    conn.execute("INSERT INTO _test_backup (val) VALUES (?)", (test_val,))
    conn.commit()
    conn.close() # EXPLICITLY CLOSE
    time.sleep(0.5) # Give OS a breath
    
    # 2. Add test upload
    uploads_dir = Path(settings.UPLOADS_DIR).resolve()
    os.makedirs(uploads_dir, exist_ok=True)
    test_file = uploads_dir / "test_backup.txt"
    test_file.write_text("RESTORE_SUCCESS")
    print(f"2. Created test upload: {test_file}")

    # 3. Trigger Backup
    print("3. Running Backup...")
    backup_file = run_backup(label="test")
    print(f"[OK] Backup created: {backup_file}")
    
    backup_name = Path(backup_file).name

    # 4. Corrupt/Delete Data
    print("4. Deleting local data to simulate loss...")
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM _test_backup")
    conn.commit()
    conn.close()
    
    if test_file.exists():
        test_file.unlink()
    
    # Verify it's gone
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT val FROM _test_backup").fetchone()
    conn.close()
    assert row is None, "Test record should be deleted before restore"
    assert not test_file.exists(), "Test file should be deleted before restore"
    print("[OK] Data deleted successfully.")

    # 5. Restore (Mocking input)
    print("5. Running Restore...")
    # Monkeypatch input to bypass the 'RESTORE' prompt
    import builtins
    original_input = builtins.input
    builtins.input = lambda _: "RESTORE"
    
    success = restore_backup(backup_name)
    builtins.input = original_input
    
    assert success, "Restore operation failed"
    print("[OK] Restore reported success.")

    # 6. Verify Data Integrity
    print("6. Verifying restored data...")
    time.sleep(1) # Wait for file sync
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT val FROM _test_backup").fetchone()
    conn.close()
    
    if row is None:
        print("ERROR: Test record is missing from database after restore!")
    elif row[0] != test_val:
        print(f"ERROR: Found incorrect value in database: {row[0]} (Expected: {test_val})")
    
    assert row is not None and row[0] == test_val, "Restored database data is incorrect"
    
    assert test_file.exists(), "Restored upload file is missing"
    assert test_file.read_text() == "RESTORE_SUCCESS", "Restored upload content is incorrect"
    
    print("\n--- ALL TESTS PASSED: BACKUP/RESTORE SYSTEM IS ROBUST ---")
    
    # Cleanup test artifacts
    if Path(backup_file).exists():
        Path(backup_file).unlink()
    external_backup = Path(settings.BACKUP_EXTERNAL_DIR) / backup_name
    if external_backup.exists():
        external_backup.unlink()

if __name__ == "__main__":
    try:
        test_backup_restore_lifecycle()
    except Exception as e:
        print(f"\nTEST FAILED: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
