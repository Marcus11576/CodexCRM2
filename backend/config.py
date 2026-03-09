"""
Antigravity CRM - Configuration
Reads all settings from environment variables.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / '.env')


class Settings:
    BASE_DIR: Path = BASE_DIR

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8009"))
    ENV: str = os.getenv("ENV", "development")

    DB_PATH: str = str((BASE_DIR / os.getenv("DB_PATH", "crm.db")).resolve()) if not os.path.isabs(os.getenv("DB_PATH", "crm.db")) else os.getenv("DB_PATH", "crm.db")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-insecure-key-change-in-production")
    TOKEN_EXPIRE_MINUTES: int = int(os.getenv("TOKEN_EXPIRE_MINUTES", "1440"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true" if os.getenv("ENV", "development") != "development" else "false").lower() in ("1", "true", "yes")
    AUTH_DISABLED: bool = os.getenv("AUTH_DISABLED", "true" if os.getenv("ENV", "development") == "development" else "false").lower() in ("1", "true", "yes")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    BRIEF_HYPOTHESIS_QUESTIONS: str = os.getenv("BRIEF_HYPOTHESIS_QUESTIONS", "What are their personal and professional motivations? What is their current business focus and commercial remit? What are their known talent or recruitment challenges?")
    BRIEF_TTS_VOICE: str = os.getenv("BRIEF_TTS_VOICE", "nova")
    BRIEF_LABEL_RECRUITMENT: str = os.getenv("BRIEF_LABEL_RECRUITMENT", "Recruitment & Talent")
    BRIEF_LABEL_OBE: str = os.getenv("BRIEF_LABEL_OBE", "OBE Focus")

    M365_ENABLED: bool = os.getenv("M365_ENABLED", "false").lower() in ("1", "true", "yes")
    M365_CLIENT_ID: str = os.getenv("M365_CLIENT_ID", "")
    M365_TENANT_ID: str = os.getenv("M365_TENANT_ID", "")
    M365_CLIENT_SECRET: str = os.getenv("M365_CLIENT_SECRET", "")
    M365_SYNC_INTERVAL_SECONDS: int = int(os.getenv("M365_SYNC_INTERVAL_SECONDS", "300"))

    UPLOADS_DIR: str = str((BASE_DIR / os.getenv("UPLOADS_DIR", "uploads")).resolve()) if not os.path.isabs(os.getenv("UPLOADS_DIR", "uploads")) else os.getenv("UPLOADS_DIR", "uploads")
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "50"))

    BACKUP_DIR: str = str((BASE_DIR / os.getenv("BACKUP_DIR", "backups")).resolve()) if not os.path.isabs(os.getenv("BACKUP_DIR", "backups")) else os.getenv("BACKUP_DIR", "backups")
    BACKUP_EXTERNAL_DIR: str = str((BASE_DIR / os.getenv("BACKUP_EXTERNAL_DIR", "backups_external")).resolve()) if not os.path.isabs(os.getenv("BACKUP_EXTERNAL_DIR", "backups_external")) else os.getenv("BACKUP_EXTERNAL_DIR", "backups_external")
    BACKUP_RETENTION_DAILY: int = int(os.getenv("BACKUP_RETENTION_DAILY", "7"))
    BACKUP_RETENTION_WEEKLY: int = int(os.getenv("BACKUP_RETENTION_WEEKLY", "4"))
    BACKUP_RETENTION_MONTHLY: int = int(os.getenv("BACKUP_RETENTION_MONTHLY", "3"))

    FRONTEND_DIR: str = str((Path(__file__).parent.parent / "frontend").resolve())
    ALLOWED_ORIGINS: list[str] = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8009,http://127.0.0.1:8009,http://localhost:8001,http://127.0.0.1:8001").split(",") if origin.strip()]


settings = Settings()
