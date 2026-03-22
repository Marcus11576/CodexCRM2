"""
Remove clearly synthetic CRM records before production/mobile rollout.

The script creates a timestamped ZIP backup using the app's backup service,
then deletes only known test fixtures and explicit test-marker content.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.services.backup_service import run_backup


PERSON_PATTERNS = (
    "m365-test-person-%",
    "export-person-%",
    "p-%",
)

EXACT_PERSON_IDS = {
    "p1",
    "p2",
    "BACKUP_TEST_999",
    "6e78fb77-8439-4452-91ce-72135dd26b4e",  # TEST_AUTOMATION_PROFILE
    "06b926a9-4c63-4e94-880a-7112c73a2696",  # Codex Bot Test
    "276ea814-9a2e-4eb4-9b96-fd710f22a3ce",  # Top Skills / example.com fixture
    "d58ea2c9-60a4-4ab5-9bd5-667b8b4866bb",  # Jane Sample
}

TEST_MARKER_INTERACTION_SQL = """
    lower(coalesce(raw_text, '')) LIKE '%test note - added by agent%'
    OR lower(coalesce(raw_text, '')) LIKE '%test partner%'
"""

TEST_MARKER_PERSON_SQL = """
    lower(coalesce(intel_notes, '')) LIKE '%test note - added by agent%'
    OR lower(coalesce(personal_data, '')) LIKE '%test partner%'
"""

PERSON_DEPENDENCY_TABLES = (
    ("AI_BRIEF", "person_id"),
    ("AI_BRIEF", "profile_id"),
    ("AI_JOB", "person_id"),
    ("AI_JOB", "related_profile_id"),
    ("AI_ARTIFACT", "person_id"),
    ("AI_ARTIFACT", "profile_id_nullable"),
    ("AI_SIGNAL", "person_id"),
    ("AI_SIGNAL", "profile_id"),
    ("AI_FEEDBACK", "profile_id"),
    ("TOPIC_INTELLIGENCE", "person_id"),
    ("M365_ACCOUNT", "person_id"),
    ("PERSON_EVENT", "person_id"),
    ("TASK", "person_id"),
    ("INTERACTION", "person_id"),
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _fetch_target_people(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    where_clauses = ["person_id IN ({})".format(",".join("?" for _ in EXACT_PERSON_IDS))]
    params: list[str] = list(EXACT_PERSON_IDS)
    for pattern in PERSON_PATTERNS:
        where_clauses.append("person_id LIKE ?")
        params.append(pattern)
    sql = f"""
        SELECT person_id, full_name, email_primary, company_name_raw
        FROM PERSON
        WHERE {" OR ".join(where_clauses)}
        ORDER BY created_at DESC
    """
    return conn.execute(sql, params).fetchall()


def _delete_people(conn: sqlite3.Connection, person_ids: list[str]) -> dict[str, int]:
    stats: dict[str, int] = {}
    if not person_ids:
        return stats

    placeholders = ",".join("?" for _ in person_ids)
    for table, column in PERSON_DEPENDENCY_TABLES:
        sql = f"DELETE FROM {table} WHERE {column} IN ({placeholders})"
        cursor = conn.execute(sql, person_ids)
        stats[f"{table}.{column}"] = cursor.rowcount

    cursor = conn.execute(f"DELETE FROM PERSON WHERE person_id IN ({placeholders})", person_ids)
    stats["PERSON"] = cursor.rowcount
    return stats


def _delete_marker_feedback(conn: sqlite3.Connection) -> dict[str, int]:
    stats: dict[str, int] = {}
    cursor = conn.execute(f"DELETE FROM INTERACTION WHERE {TEST_MARKER_INTERACTION_SQL}")
    stats["INTERACTION_test_markers"] = cursor.rowcount

    cursor = conn.execute(
        f"""
        UPDATE PERSON
        SET intel_notes = CASE
                WHEN lower(coalesce(intel_notes, '')) LIKE '%test note - added by agent%' THEN NULL
                ELSE intel_notes
            END,
            personal_data = CASE
                WHEN lower(coalesce(personal_data, '')) LIKE '%test partner%' THEN NULL
                ELSE personal_data
            END
        WHERE {TEST_MARKER_PERSON_SQL}
        """
    )
    stats["PERSON_test_marker_fields"] = cursor.rowcount
    return stats


def _remove_upload_artifacts() -> dict[str, int]:
    uploads_dir = Path(settings.UPLOADS_DIR)
    removed = 0
    for relative in (
        Path("test_backup.txt"),
    ):
        target = uploads_dir / relative
        if target.exists():
            target.unlink()
            removed += 1
    return {"upload_files_removed": removed}


def main() -> None:
    backup_path = run_backup(label="pre_mobile_cleanup")
    conn = _connect()
    try:
        target_rows = _fetch_target_people(conn)
        target_ids = [row["person_id"] for row in target_rows]
        deletion_stats = _delete_people(conn, target_ids)
        marker_stats = _delete_marker_feedback(conn)
        conn.commit()
    finally:
        conn.close()

    upload_stats = _remove_upload_artifacts()
    summary = {
        "backup_path": backup_path,
        "people_targets": [dict(row) for row in target_rows],
        "deleted_counts": deletion_stats,
        "marker_cleanup": marker_stats,
        "upload_cleanup": upload_stats,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
