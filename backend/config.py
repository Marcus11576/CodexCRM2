"""
Antigravity CRM - Configuration
Reads all settings from environment variables.
"""
import os
from pathlib import Path
from datetime import timezone
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.parent
load_dotenv(BASE_DIR / '.env')


class Settings:
    BASE_DIR: Path = BASE_DIR

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8009"))
    ENV: str = os.getenv("ENV", "development")
    ENV_LOWER: str = ENV.lower()

    DB_PATH: str = str((BASE_DIR / os.getenv("DB_PATH", "crm.db")).resolve()) if not os.path.isabs(os.getenv("DB_PATH", "crm.db")) else os.getenv("DB_PATH", "crm.db")

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-only-insecure-key-change-in-production")
    TOKEN_EXPIRE_MINUTES: int = int(os.getenv("TOKEN_EXPIRE_MINUTES", "1440"))
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "session_token").strip() or "session_token"
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true" if os.getenv("ENV", "development") != "development" else "false").lower() in ("1", "true", "yes")
    AUTH_DISABLED: bool = os.getenv("AUTH_DISABLED", "false").lower() in ("1", "true", "yes")
    API_DOCS_ENABLED: bool = os.getenv("API_DOCS_ENABLED", "false").lower() in ("1", "true", "yes")

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    STANDALONE_TOOL_API_KEY: str = os.getenv("STANDALONE_TOOL_API_KEY", "")
    STANDALONE_TOOL_MODEL: str = os.getenv("STANDALONE_TOOL_MODEL", "gpt-4o")
    RELATIONSHIP_STORY_MODEL: str = os.getenv("RELATIONSHIP_STORY_MODEL", os.getenv("STANDALONE_TOOL_MODEL", "gpt-4o"))
    BRIEF_HYPOTHESIS_QUESTIONS: str = os.getenv("BRIEF_HYPOTHESIS_QUESTIONS", "What are their personal and professional motivations? What is their current business focus and commercial remit? What are their known talent or recruitment challenges?")
    BRIEF_TTS_VOICE: str = os.getenv("BRIEF_TTS_VOICE", "nova")
    BRIEF_LABEL_RECRUITMENT: str = os.getenv("BRIEF_LABEL_RECRUITMENT", "Recruitment & Talent")
    BRIEF_LABEL_OBE: str = os.getenv("BRIEF_LABEL_OBE", "OBE Focus")

    M365_ENABLED: bool = os.getenv("M365_ENABLED", "false").lower() in ("1", "true", "yes")
    M365_CLIENT_ID: str = os.getenv("M365_CLIENT_ID", "")
    M365_TENANT_ID: str = os.getenv("M365_TENANT_ID", "")
    M365_CLIENT_SECRET: str = os.getenv("M365_CLIENT_SECRET", "")
    M365_SCOPES: str = os.getenv(
        "M365_SCOPES",
        "openid profile offline_access User.Read Mail.Read Mail.ReadWrite Mail.Send Calendars.Read Calendars.ReadWrite",
    )
    M365_AUTH_REDIRECT_URI: str = os.getenv("M365_AUTH_REDIRECT_URI", "")
    M365_SYNC_INTERVAL_SECONDS: int = int(os.getenv("M365_SYNC_INTERVAL_SECONDS", "300"))

    UPLOADS_DIR: str = str((BASE_DIR / os.getenv("UPLOADS_DIR", "uploads")).resolve()) if not os.path.isabs(os.getenv("UPLOADS_DIR", "uploads")) else os.getenv("UPLOADS_DIR", "uploads")
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "50"))
    CHATBOT_ONLY_MODE: bool = os.getenv("CHATBOT_ONLY_MODE", "true").lower() in ("1", "true", "yes")
    # Keep legacy intelligence endpoints/runtime behind an env flag so sandbox and
    # production can choose rollout posture without code changes.
    LEGACY_SCORING_ENABLED: bool = os.getenv("LEGACY_SCORING_ENABLED", "true").lower() in ("1", "true", "yes")
    CHATBOT_ALLOWED_TEXT_CHANNELS: list[str] = [
        channel.strip().lower()
        for channel in os.getenv(
            "CHATBOT_ALLOWED_TEXT_CHANNELS",
            "chat,note,typed,chat_topic_resolution",
        ).split(",")
        if channel.strip()
    ]

    BACKUP_DIR: str = str((BASE_DIR / os.getenv("BACKUP_DIR", "backups")).resolve()) if not os.path.isabs(os.getenv("BACKUP_DIR", "backups")) else os.getenv("BACKUP_DIR", "backups")
    BACKUP_EXTERNAL_DIR: str = str((BASE_DIR / os.getenv("BACKUP_EXTERNAL_DIR", "backups_external")).resolve()) if not os.path.isabs(os.getenv("BACKUP_EXTERNAL_DIR", "backups_external")) else os.getenv("BACKUP_EXTERNAL_DIR", "backups_external")
    BACKUP_RETENTION_DAILY: int = int(os.getenv("BACKUP_RETENTION_DAILY", "7"))
    BACKUP_RETENTION_WEEKLY: int = int(os.getenv("BACKUP_RETENTION_WEEKLY", "4"))
    BACKUP_RETENTION_MONTHLY: int = int(os.getenv("BACKUP_RETENTION_MONTHLY", "3"))
    BACKUP_SCHEDULE_HOUR: int = int(os.getenv("BACKUP_SCHEDULE_HOUR", "3"))
    BACKUP_SCHEDULE_MINUTE: int = int(os.getenv("BACKUP_SCHEDULE_MINUTE", "0"))
    BACKUP_TIMEZONE: str = os.getenv("BACKUP_TIMEZONE", "UTC")

    FRONTEND_DIR: str = str((Path(__file__).parent.parent / "frontend").resolve())
    ALLOWED_ORIGINS: list[str] = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8009,http://127.0.0.1:8009,http://localhost:8001,http://127.0.0.1:8001").split(",") if origin.strip()]

    @staticmethod
    def _has_real_secret(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        placeholders = {
            "<secret>",
            "<your_openai_api_key>",
            "your_openai_api_key",
            "replace_me",
            "changeme",
            "sk-your-key-here",
        }
        lowered = text.lower()
        return lowered not in placeholders and not (text.startswith("<") and text.endswith(">"))

    @property
    def OPENAI_CONFIGURED(self) -> bool:
        return self._has_real_secret(self.OPENAI_API_KEY)

    @property
    def GEMINI_CONFIGURED(self) -> bool:
        return self._has_real_secret(self.GEMINI_API_KEY)

    @property
    def BACKUP_ZONEINFO(self):
        try:
            return ZoneInfo(self.BACKUP_TIMEZONE)
        except ZoneInfoNotFoundError:
            return timezone.utc


settings = Settings()
