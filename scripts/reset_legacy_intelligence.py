"""
Hard reset legacy scoring/intelligence data for chatbot-native rebuild.

What this script does:
1) Creates a timestamped backup copy of crm.db.
2) Purges legacy intelligence/scoring containers.
3) Resets score-related PERSON fields to neutral defaults.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings


DELETE_TABLES = [
    "AI_FEEDBACK",
    "AI_RUN_LOG",
    "AI_JOB",
    "AI_SIGNAL",
    "AI_ARTIFACT",
    "AI_BRIEF",
    "TOPIC_INTELLIGENCE",
    "INTERPRETED_INTERACTION",
    "RELATIONSHIP_SITUATION_SOURCE",
    "RELATIONSHIP_SITUATION_EVENT",
    "RELATIONSHIP_SITUATION",
    "REL_INTEL_AGENT_OUTPUT",
    "REL_INTEL_RUN",
    "ENDURING_MEMORY",
    "MARKET_INTEL",
    "PLATFORM_MEMORY",
    "PERSON_OPPORTUNITY",
    "COMPANY_OPPORTUNITY",
    "TASK",
    "INTERACTION",
    "M365_ACCOUNT",
    "M365_CREDENTIALS",
]

PERSON_DEFAULTS: dict[str, object] = {
    "meeting_status": None,
    "next_contact_due_date": None,
    "next_meeting_date": None,
    "next_meeting_topic": None,
    "last_meeting_date": None,
    "last_contact_datetime": None,
    "cached_briefing": None,
    "briefing_last_updated": None,
    "relationship_health": 50,
    "engagement_velocity": 0.0,
    "peak_engagement_time": None,
    "next_best_action": None,
    "last_success_at": None,
    "network_tier": None,
    "maintenance_mode": None,
    "relationship_owner": None,
    "decision_role": None,
    "influence_scope": None,
    "strategic_value_score": 50,
    "influence_score": 50,
    "future_option_score": 50,
    "coverage_risk_score": 50,
    "opportunity_readiness_score": 0,
    "relationship_confidence_score": 50,
    "last_meaningful_contact_at": None,
    "last_inbound_at": None,
    "last_outbound_at": None,
    "unanswered_outbound_count": 0,
    "reactivation_trigger_notes": None,
    "account_priority": None,
    "tier_rationale": None,
    "last_health_refresh_at": None,
    "m365_last_sync": None,
    "m365_last_sync_at": None,
}


def table_exists(cur: sqlite3.Cursor, table_name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cur.fetchone() is not None


def backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"pre_chatbot_reset_{stamp}.db"
    shutil.copy2(db_path, backup_path)
    return backup_path


def reset_person_fields(cur: sqlite3.Cursor) -> int:
    cur.execute("PRAGMA table_info(PERSON)")
    existing_columns = {row[1] for row in cur.fetchall()}

    assignments: list[str] = []
    params: list[object] = []
    for column, value in PERSON_DEFAULTS.items():
        if column in existing_columns:
            assignments.append(f"{column} = ?")
            params.append(value)

    if "last_updated_at" in existing_columns:
        assignments.append("last_updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())

    if not assignments:
        return 0

    sql = f"UPDATE PERSON SET {', '.join(assignments)}"
    cur.execute(sql, tuple(params))
    return int(cur.rowcount or 0)


def main() -> None:
    db_path = Path(settings.DB_PATH)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    backup_path = backup_database(db_path, Path(settings.BACKUP_DIR))

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=OFF")

        deleted_counts: dict[str, int] = {}
        for table in DELETE_TABLES:
            if not table_exists(cur, table):
                continue
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            deleted_counts[table] = int(cur.fetchone()[0])
            cur.execute(f"DELETE FROM {table}")

        person_rows_reset = reset_person_fields(cur)

        conn.commit()
        cur.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    print(f"Backup created: {backup_path}")
    print("Legacy containers purged:")
    for table in DELETE_TABLES:
        if table in deleted_counts:
            print(f"  - {table}: {deleted_counts[table]}")
    print(f"PERSON rows reset: {person_rows_reset}")
    print("Reset complete.")


if __name__ == "__main__":
    main()
