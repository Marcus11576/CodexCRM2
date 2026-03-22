import os
import atexit
import shutil
import tempfile


# Keep the automated test suite running in auth-enabled mode even while the
# live app is temporarily opened up for the rebuild phase.
os.environ["AUTH_DISABLED"] = "false"

# Run pytest against an isolated scratch database and storage tree so the
# verification suite never mutates the live CRM data.
_TEST_ROOT = tempfile.mkdtemp(prefix="antigravity-crm-tests-")
os.environ["DB_PATH"] = os.path.join(_TEST_ROOT, "crm-test.db")
os.environ["UPLOADS_DIR"] = os.path.join(_TEST_ROOT, "uploads")
os.environ["BACKUP_DIR"] = os.path.join(_TEST_ROOT, "backups")
os.environ["BACKUP_EXTERNAL_DIR"] = os.path.join(_TEST_ROOT, "backups_external")

from backend.database import init_db

init_db()


@atexit.register
def _cleanup_test_root():
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
