import os
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from backend.config import settings

def run_backup(label: str = "daily") -> str:
    """
    Creates a full backup of the DB, uploads, and config.
    label: 'daily', 'weekly', or 'monthly'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{label}_{timestamp}.zip"
    
    os.makedirs(settings.BACKUP_DIR, exist_ok=True)
    os.makedirs(settings.BACKUP_EXTERNAL_DIR, exist_ok=True)
    
    local_path = Path(settings.BACKUP_DIR).resolve() / backup_name
    
    print(f"BACKUP: Creating {backup_name}...")
    
    try:
        with zipfile.ZipFile(local_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 1. Database
            db_path = Path(settings.DB_PATH).resolve()
            if db_path.exists():
                zipf.write(db_path, db_path.name)
                print(f"BACKUP: Added database {db_path.name}")
                # Capture WAL/SHM if they exist
                for sidecar in [f"{db_path.name}-wal", f"{db_path.name}-shm"]:
                    sidecar_path = db_path.parent / sidecar
                    if sidecar_path.exists():
                        zipf.write(sidecar_path, sidecar)
                        print(f"BACKUP: Added sidecar {sidecar}")
                
            # 2. Uploads
            uploads_dir = Path(settings.UPLOADS_DIR).resolve()
            if uploads_dir.exists():
                print(f"BACKUP: Adding uploads from {uploads_dir}...")
                for root, dirs, files in os.walk(uploads_dir):
                    for file in files:
                        file_path = Path(root) / file
                        # Store relative to parent of uploads to preserve the 'uploads/' folder structure in zip
                        arcname = file_path.relative_to(uploads_dir.parent)
                        zipf.write(file_path, arcname)
                        
            # 3. Environment Config
            env_path = (Path(settings.BASE_DIR) / ".env").resolve()
            if env_path.exists():
                zipf.write(env_path, ".env")
                print("BACKUP: Added .env config")
    except Exception as e:
        print(f"BACKUP: Zip creation failed: {e}")
        if local_path.exists():
            local_path.unlink()
        raise e
            
    # Copy to external location
    external_path = Path(settings.BACKUP_EXTERNAL_DIR).resolve() / backup_name
    try:
        shutil.copy2(local_path, external_path)
        print(f"BACKUP: Copied to external: {external_path}")
    except Exception as e:
        print(f"BACKUP WARNING: External copy failed: {e}")
        
    # Purge old backups
    purge_old_backups()
    
    return str(local_path)

def purge_old_backups():
    """Removes old backups based on retention policy."""
    # Retention settings
    retention = {
        "daily": settings.BACKUP_RETENTION_DAILY,
        "weekly": settings.BACKUP_RETENTION_WEEKLY,
        "monthly": settings.BACKUP_RETENTION_MONTHLY
    }
    
    for folder in [settings.BACKUP_DIR, settings.BACKUP_EXTERNAL_DIR]:
        path = Path(folder)
        if not path.exists():
            continue
            
        # Group backups by label
        backups_by_label = {"daily": [], "weekly": [], "monthly": []}
        for f in path.glob("backup_*.zip"):
            for label in backups_by_label:
                if f"backup_{label}_" in f.name:
                    backups_by_label[label].append(f)
                    break
        
        # Sort and remove oldest
        for label, files in backups_by_label.items():
            files.sort(key=lambda x: x.name, reverse=True) # Newest first
            if len(files) > retention[label]:
                for old_file in files[retention[label]:]:
                    try:
                        old_file.unlink()
                        print(f"Purged old {label} backup: {old_file.name}")
                    except Exception as e:
                        print(f"Error purging {old_file}: {e}")

def get_backup_label() -> str:
    """Determines if the current run should be daily, weekly, or monthly."""
    now = datetime.now()
    # If first day of month -> monthly
    if now.day == 1:
        return "monthly"
    # If Sunday -> weekly (assuming Sunday = 6 in weekday())
    if now.weekday() == 6:
        return "weekly"
    return "daily"
