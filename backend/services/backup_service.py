import os
import shutil
import sqlite3
import stat
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import settings


def _create_sqlite_snapshot(source_path: Path, snapshot_path: Path):
    """Create a consistent SQLite snapshot, including any pending WAL state."""
    source_uri = f"file:{source_path.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as source_conn:
        with sqlite3.connect(snapshot_path) as snapshot_conn:
            source_conn.backup(snapshot_conn)
            snapshot_conn.commit()


def _cleanup_temp_file(path: Path):
    if not path.exists():
        return
    for _ in range(5):
        try:
            os.chmod(path, stat.S_IWRITE)
        except Exception:
            pass
        try:
            path.unlink()
            return
        except PermissionError:
            time.sleep(0.2)
    print(f"BACKUP WARNING: Temporary snapshot cleanup skipped for {path}")


def run_backup(label: str = "daily") -> str:
    """
    Creates a full backup of the DB, uploads, and config.
    label: 'daily', 'weekly', or 'monthly'
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{label}_{timestamp}.zip"

    os.makedirs(settings.BACKUP_DIR, exist_ok=True)
    os.makedirs(settings.BACKUP_EXTERNAL_DIR, exist_ok=True)

    local_path = Path(settings.BACKUP_DIR).resolve() / backup_name

    print(f"BACKUP: Creating {backup_name}...")

    temp_fd, temp_name = tempfile.mkstemp(prefix='ag_backup_', suffix='.db')
    os.close(temp_fd)
    snapshot_path = Path(temp_name)

    try:
        db_path = Path(settings.DB_PATH).resolve()
        if db_path.exists():
            _create_sqlite_snapshot(db_path, snapshot_path)

        with zipfile.ZipFile(local_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            if snapshot_path.exists() and snapshot_path.stat().st_size > 0:
                zipf.write(snapshot_path, 'crm.db')
                print('BACKUP: Added database snapshot crm.db')

            uploads_dir = Path(settings.UPLOADS_DIR).resolve()
            if uploads_dir.exists():
                print(f"BACKUP: Adding uploads from {uploads_dir}...")
                for root, _dirs, files in os.walk(uploads_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(uploads_dir.parent)
                        zipf.write(file_path, arcname)

            env_path = (Path(settings.BASE_DIR) / '.env').resolve()
            if env_path.exists():
                zipf.write(env_path, '.env')
                print('BACKUP: Added .env config')
    except Exception as e:
        print(f"BACKUP: Zip creation failed: {e}")
        if local_path.exists():
            local_path.unlink()
        raise e
    finally:
        _cleanup_temp_file(snapshot_path)

    external_path = Path(settings.BACKUP_EXTERNAL_DIR).resolve() / backup_name
    try:
        shutil.copy2(local_path, external_path)
        print(f"BACKUP: Copied to external: {external_path}")
    except Exception as e:
        print(f"BACKUP WARNING: External copy failed: {e}")

    purge_old_backups()

    return str(local_path)


def purge_old_backups():
    """Removes old backups based on retention policy."""
    retention = {
        'daily': settings.BACKUP_RETENTION_DAILY,
        'weekly': settings.BACKUP_RETENTION_WEEKLY,
        'monthly': settings.BACKUP_RETENTION_MONTHLY,
    }

    for folder in [settings.BACKUP_DIR, settings.BACKUP_EXTERNAL_DIR]:
        path = Path(folder)
        if not path.exists():
            continue

        backups_by_label = {'daily': [], 'weekly': [], 'monthly': []}
        for f in path.glob('backup_*.zip'):
            for label in backups_by_label:
                if f"backup_{label}_" in f.name:
                    backups_by_label[label].append(f)
                    break

        for label, files in backups_by_label.items():
            files.sort(key=lambda x: x.name, reverse=True)
            if len(files) > retention[label]:
                for old_file in files[retention[label]:]:
                    try:
                        old_file.unlink()
                        print(f"Purged old {label} backup: {old_file.name}")
                    except Exception as e:
                        print(f"Error purging {old_file}: {e}")


def get_backup_label() -> str:
    """Determines if the current run should be daily, weekly, or monthly."""
    now = datetime.now(timezone.utc)
    if now.day == 1:
        return 'monthly'
    if now.weekday() == 6:
        return 'weekly'
    return 'daily'


def get_next_backup_run(now_utc: datetime | None = None) -> datetime:
    """Return the next scheduled backup run in UTC based on configured backup timezone."""
    now_utc = now_utc or datetime.now(timezone.utc)
    zone = settings.BACKUP_ZONEINFO
    local_now = now_utc.astimezone(zone)
    scheduled_local = local_now.replace(
        hour=settings.BACKUP_SCHEDULE_HOUR,
        minute=settings.BACKUP_SCHEDULE_MINUTE,
        second=0,
        microsecond=0,
    )
    if scheduled_local <= local_now:
        scheduled_local = scheduled_local + timedelta(days=1)
    return scheduled_local.astimezone(timezone.utc)


def get_backup_schedule_metadata(now_utc: datetime | None = None) -> dict:
    next_run = get_next_backup_run(now_utc)
    return {
        "timezone": settings.BACKUP_TIMEZONE,
        "hour": settings.BACKUP_SCHEDULE_HOUR,
        "minute": settings.BACKUP_SCHEDULE_MINUTE,
        "next_backup_at": next_run.isoformat(),
    }


def get_latest_backup_metadata() -> dict:
    """Returns metadata for the newest backup available on disk."""
    candidates: list[tuple[str, Path]] = []
    for scope, folder in (("local", settings.BACKUP_DIR), ("external", settings.BACKUP_EXTERNAL_DIR)):
        path = Path(folder)
        if not path.exists():
            continue
        for file_path in path.glob("backup_*.zip"):
            if file_path.is_file():
                candidates.append((scope, file_path))

    if not candidates:
        return {
            "exists": False,
            "last_backup_at": None,
            "label": None,
            "filename": None,
            "location": None,
            **get_backup_schedule_metadata(),
        }

    scope, latest = max(candidates, key=lambda item: item[1].stat().st_mtime)
    name = latest.name
    label = None
    for candidate in ("daily", "weekly", "monthly", "test", "manual"):
        if f"backup_{candidate}_" in name:
            label = candidate
            break

    last_backup_at = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "exists": True,
        "last_backup_at": last_backup_at,
        "label": label,
        "filename": name,
        "location": scope,
        **get_backup_schedule_metadata(),
    }


