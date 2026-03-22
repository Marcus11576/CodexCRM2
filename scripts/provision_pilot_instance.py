"""
Create an isolated pilot CRM database from the live CRM.

The pilot database is a one-way clone of the source DB and is then pruned down
to the most populated contacts so the pilot can be exercised safely on a
separate port without touching the main instance.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT_DIR / "crm.db"
DEFAULT_TARGET = ROOT_DIR / "pilot" / "pilot_crm.db"
DEFAULT_REPORT = ROOT_DIR / "pilot" / "pilot_cohort_report.json"


@dataclass
class CohortContact:
    person_id: str
    full_name: str
    company_name_raw: str | None
    interaction_count: int
    task_count: int
    person_opportunity_count: int
    company_opportunity_count: int
    event_count: int
    signal_count: int
    brief_count: int
    has_last_contact: int
    has_next_step: int
    population_score: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision an isolated pilot CRM database.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Source SQLite database path.")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="Target SQLite database path.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="JSON report output path.")
    parser.add_argument("--size", type=int, default=50, help="Number of contacts to keep in the pilot.")
    parser.add_argument("--force", action="store_true", help="Overwrite the target if it already exists.")
    return parser.parse_args()


def _normalized_company_names(rows: Iterable[sqlite3.Row]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        company_name = str(row["company_name_raw"] or "").strip().lower()
        if company_name:
            names.add(company_name)
    return sorted(names)


def _select_pilot_contacts(conn: sqlite3.Connection, size: int) -> list[CohortContact]:
    query = """
    WITH interaction_counts AS (
        SELECT person_id, COUNT(*) AS count_value
        FROM INTERACTION
        GROUP BY person_id
    ),
    task_counts AS (
        SELECT person_id, COUNT(*) AS count_value
        FROM TASK
        GROUP BY person_id
    ),
    person_opportunity_counts AS (
        SELECT person_id, COUNT(*) AS count_value
        FROM PERSON_OPPORTUNITY
        GROUP BY person_id
    ),
    company_opportunity_counts AS (
        SELECT LOWER(TRIM(company_name_raw)) AS company_key, COUNT(*) AS count_value
        FROM COMPANY_OPPORTUNITY
        GROUP BY LOWER(TRIM(company_name_raw))
    ),
    event_counts AS (
        SELECT person_id, COUNT(*) AS count_value
        FROM PERSON_EVENT
        GROUP BY person_id
    ),
    signal_counts AS (
        SELECT person_id, COUNT(*) AS count_value
        FROM AI_SIGNAL
        GROUP BY person_id
    ),
    brief_counts AS (
        SELECT person_id, COUNT(*) AS count_value
        FROM AI_BRIEF
        GROUP BY person_id
    )
    SELECT
        p.person_id,
        p.full_name,
        p.company_name_raw,
        COALESCE(ic.count_value, 0) AS interaction_count,
        COALESCE(tc.count_value, 0) AS task_count,
        COALESCE(poc.count_value, 0) AS person_opportunity_count,
        COALESCE(coc.count_value, 0) AS company_opportunity_count,
        COALESCE(ec.count_value, 0) AS event_count,
        COALESCE(sc.count_value, 0) AS signal_count,
        COALESCE(bc.count_value, 0) AS brief_count,
        CASE WHEN p.last_contact_datetime IS NOT NULL THEN 1 ELSE 0 END AS has_last_contact,
        CASE
            WHEN p.next_contact_due_date IS NOT NULL
              OR p.next_meeting_date IS NOT NULL
              OR p.meeting_status IS NOT NULL
            THEN 1 ELSE 0
        END AS has_next_step,
        (
            COALESCE(ic.count_value, 0) * 1000 +
            COALESCE(tc.count_value, 0) * 140 +
            COALESCE(poc.count_value, 0) * 180 +
            COALESCE(coc.count_value, 0) * 120 +
            COALESCE(ec.count_value, 0) * 90 +
            COALESCE(sc.count_value, 0) * 60 +
            COALESCE(bc.count_value, 0) * 30 +
            CASE WHEN p.last_contact_datetime IS NOT NULL THEN 25 ELSE 0 END +
            CASE
                WHEN p.next_contact_due_date IS NOT NULL
                  OR p.next_meeting_date IS NOT NULL
                  OR p.meeting_status IS NOT NULL
                THEN 15 ELSE 0
            END
        ) AS population_score
    FROM PERSON p
    LEFT JOIN interaction_counts ic ON ic.person_id = p.person_id
    LEFT JOIN task_counts tc ON tc.person_id = p.person_id
    LEFT JOIN person_opportunity_counts poc ON poc.person_id = p.person_id
    LEFT JOIN company_opportunity_counts coc ON coc.company_key = LOWER(TRIM(p.company_name_raw))
    LEFT JOIN event_counts ec ON ec.person_id = p.person_id
    LEFT JOIN signal_counts sc ON sc.person_id = p.person_id
    LEFT JOIN brief_counts bc ON bc.person_id = p.person_id
    WHERE p.is_active = 1
    ORDER BY
        population_score DESC,
        interaction_count DESC,
        signal_count DESC,
        task_count DESC,
        full_name COLLATE NOCASE ASC
    LIMIT ?
    """
    rows = conn.execute(query, (size,)).fetchall()
    return [CohortContact(**dict(row)) for row in rows]


def _delete_by_ids(conn: sqlite3.Connection, table: str, column: str, keep_ids: list[str]) -> None:
    if not keep_ids:
        conn.execute(f"DELETE FROM {table}")
        return
    placeholders = ",".join("?" for _ in keep_ids)
    conn.execute(f"DELETE FROM {table} WHERE {column} NOT IN ({placeholders})", keep_ids)


def _delete_by_company_names(conn: sqlite3.Connection, table: str, company_names: list[str]) -> None:
    if not company_names:
        conn.execute(f"DELETE FROM {table}")
        return
    placeholders = ",".join("?" for _ in company_names)
    conn.execute(
        f"DELETE FROM {table} WHERE LOWER(TRIM(company_name_raw)) NOT IN ({placeholders})",
        company_names,
    )


def _prune_database(conn: sqlite3.Connection, keep_contacts: list[CohortContact]) -> dict[str, int]:
    keep_ids = [contact.person_id for contact in keep_contacts]
    people_rows = conn.execute(
        f"SELECT person_id, company_name_raw FROM PERSON WHERE person_id IN ({','.join('?' for _ in keep_ids)})",
        keep_ids,
    ).fetchall()
    keep_company_names = _normalized_company_names(people_rows)

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM M365_ACCOUNT")
        conn.execute("DELETE FROM M365_CREDENTIALS")
        conn.execute("DELETE FROM PLATFORM_MEMORY")
        conn.execute("DELETE FROM AI_RUN_LOG")
        conn.execute("DELETE FROM AI_FEEDBACK")
        conn.execute("DELETE FROM AI_JOB")

        _delete_by_ids(conn, "TOPIC_INTELLIGENCE", "person_id", keep_ids)
        _delete_by_ids(conn, "TASK", "person_id", keep_ids)
        _delete_by_ids(conn, "PERSON_OPPORTUNITY", "person_id", keep_ids)
        _delete_by_ids(conn, "PERSON_EVENT", "person_id", keep_ids)
        _delete_by_ids(conn, "AI_BRIEF", "person_id", keep_ids)
        _delete_by_ids(conn, "AI_SIGNAL", "person_id", keep_ids)
        _delete_by_ids(conn, "AI_ARTIFACT", "person_id", keep_ids)
        _delete_by_ids(conn, "INTERACTION", "person_id", keep_ids)
        _delete_by_company_names(conn, "COMPANY_OPPORTUNITY", keep_company_names)
        _delete_by_company_names(conn, "COMPANY", keep_company_names)
        _delete_by_ids(conn, "PERSON", "person_id", keep_ids)

        conn.execute("DELETE FROM EVENT WHERE event_id NOT IN (SELECT DISTINCT event_id FROM PERSON_EVENT)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("VACUUM")
    summary = {}
    for table in (
        "PERSON",
        "INTERACTION",
        "TASK",
        "PERSON_OPPORTUNITY",
        "COMPANY_OPPORTUNITY",
        "PERSON_EVENT",
        "EVENT",
        "AI_ARTIFACT",
        "AI_SIGNAL",
        "AI_BRIEF",
    ):
        summary[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return summary


def _guard_paths(source: Path, target: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source database not found: {source}")
    if source.resolve() == target.resolve():
        raise ValueError("Source and target database paths must be different.")
    if target.exists() and not target.is_file():
        raise ValueError(f"Target path is not a file: {target}")


def main() -> int:
    args = parse_args()
    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    report = Path(args.report).resolve()
    _guard_paths(source, target)

    if target.exists() and not args.force:
        raise FileExistsError(f"Target database already exists: {target}. Use --force to overwrite.")

    target.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        target.unlink()
    shutil.copy2(source, target)

    with sqlite3.connect(target) as conn:
        conn.row_factory = sqlite3.Row
        keep_contacts = _select_pilot_contacts(conn, args.size)
        if not keep_contacts:
            raise RuntimeError("No contacts were selected for the pilot cohort.")
        summary = _prune_database(conn, keep_contacts)

    report_payload = {
        "source": str(source),
        "target": str(target),
        "selected_count": len(keep_contacts),
        "selection_strategy": "top_populated_contacts",
        "cohort": [asdict(contact) for contact in keep_contacts],
        "remaining_counts": summary,
    }
    report.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")

    print(f"Pilot database created: {target}")
    print(f"Pilot report written: {report}")
    print(f"Contacts kept: {len(keep_contacts)}")
    for table_name, row_count in summary.items():
        print(f"  {table_name}: {row_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
