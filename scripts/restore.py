import os
import shutil
import stat
import sys
import time
import zipfile
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
from backend.config import settings


def list_backups():
    """Returns a list of available backups in local and external storage."""
    backups = []
    for directory in [settings.BACKUP_DIR, settings.BACKUP_EXTERNAL_DIR]:
        path = Path(directory).resolve()
        if path.exists():
            backups.extend(list(path.glob("backup_*.zip")))
    backups.sort(key=lambda item: item.name, reverse=True)
    return list(dict.fromkeys([item.name for item in backups]))


def _clear_readonly(func, path, exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _remove_tree(path: Path):
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return
    for child in path.rglob('*'):
        try:
            os.chmod(child, stat.S_IWRITE)
        except Exception:
            pass
    shutil.rmtree(path, onerror=_clear_readonly)


def _swap_out_existing_directory(path: Path) -> Path | None:
    if not path.exists():
        return None
    temp_path = path.parent / f"{path.name}_pre_restore"
    if temp_path.exists():
        _remove_tree(temp_path)
    try:
        os.replace(path, temp_path)
        return temp_path
    except Exception:
        _remove_tree(path)
        return None


def restore_backup(backup_name: str):
    """Performs a full restoration from a named backup. WARNING: Overwrites data."""
    print(f"\n--- RESTORE INITIATED: {backup_name} ---")
    print("WARNING: This will overwrite your current database, uploads, and .env file.")
    confirm = input("Are you absolutely sure? Type 'RESTORE' to proceed: ")
    if confirm != "RESTORE":
        print("Restore aborted.")
        return False

    source_file = None
    for directory in [settings.BACKUP_DIR, settings.BACKUP_EXTERNAL_DIR]:
        candidate = Path(directory).resolve() / backup_name
        if candidate.exists():
            source_file = candidate
            break

    if not source_file:
        print(f"Error: Backup file {backup_name} not found.")
        return False

    print(f"Using source: {source_file}")
    extract_path = Path(settings.BASE_DIR).resolve() / "_restore_temp"
    if extract_path.exists():
        _remove_tree(extract_path)
    os.makedirs(extract_path, exist_ok=True)

    uploads_backup = None
    try:
        with zipfile.ZipFile(source_file, 'r') as archive:
            archive.extractall(extract_path)

        print("Backup extracted. Overwriting files...")

        env_src = extract_path / ".env"
        if env_src.exists():
            shutil.copy2(env_src, Path(settings.BASE_DIR) / ".env")
            print("[OK] Restored .env")

        db_src = extract_path / "crm.db"
        if db_src.exists():
            try:
                shutil.copy2(db_src, settings.DB_PATH)
                print("[OK] Restored crm.db")
                for sidecar in ["crm.db-wal", "crm.db-shm"]:
                    sidecar_src = extract_path / sidecar
                    if sidecar_src.exists():
                        shutil.copy2(sidecar_src, Path(settings.DB_PATH).parent / sidecar)
                        print(f"[OK] Restored {sidecar}")
            except PermissionError:
                print("CRITICAL: Permission denied on crm.db. Is the server running? Please stop it and try again.")
                return False

        uploads_src = extract_path / "uploads"
        uploads_dst = Path(settings.UPLOADS_DIR)
        if uploads_src.exists():
            uploads_backup = _swap_out_existing_directory(uploads_dst)
            shutil.copytree(uploads_src, uploads_dst, dirs_exist_ok=True)
            print("[OK] Restored uploads/")
            if uploads_backup and uploads_backup.exists():
                _remove_tree(uploads_backup)
                uploads_backup = None

        print("\n--- RESTORE COMPLETE: SUCCESS ---")
        return True
    except Exception as exc:
        print(f"CRITICAL ERROR DURING RESTORE: {exc}")
        if uploads_backup and uploads_backup.exists() and not Path(settings.UPLOADS_DIR).exists():
            os.replace(uploads_backup, Path(settings.UPLOADS_DIR))
        return False
    finally:
        if extract_path.exists():
            _remove_tree(extract_path)
        if uploads_backup and uploads_backup.exists():
            try:
                _remove_tree(uploads_backup)
            except Exception:
                pass


if __name__ == "__main__":
    backups = list_backups()
    if not backups:
        print("No backups found.")
        sys.exit(1)

    if len(sys.argv) > 1:
        restore_backup(sys.argv[1])
    else:
        print("Available Backups:")
        for idx, backup in enumerate(backups):
            print(f"[{idx}] {backup}")

        choice = input("\nEnter index of backup to restore (or 'cancel'): ")
        if choice.isdigit() and int(choice) < len(backups):
            restore_backup(backups[int(choice)])
        else:
            print("Restore cancelled.")
