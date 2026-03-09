"""
Antigravity CRM — Data Migration Script
Migrates all contacts from the old crm.db to the new clean schema.
Run ONCE after setting up the new system.

Usage:
  python scripts/migrate_data.py

The old database is NEVER modified — this is read-only from the source.
"""
import sqlite3
import uuid
import json
import sys
import os
from datetime import datetime, timezone

# ── Config ────────────────────────────────────────────────────────────────────
OLD_DB = r"C:\Users\marcu\.antigravity\CRM Project\execution\crm.db"
NEW_DB = os.path.join(os.path.dirname(__file__), "..", "crm.db")

# Taxonomy normalisation map — old inconsistent values → new canonical values
ENV_MAP = {
    "DEV-G": "Developer - Gov",
    "DEV-S": "Developer - Semi-Gov",
    "DEV-P": "Developer - Private",
    "CONS": "Consultant",
    "MAIN": "Main Contractor",
    "SUB": "Sub Contractor",
    "MGMT": "Management Consultant",
    "OTHR": "Other",
    "OTHER": "Other",
    "Developer - Gov": "Developer - Gov",
    "Developer - Semi-Gov": "Developer - Semi-Gov",
    "Developer - Private": "Developer - Private",
    "Consultant": "Consultant",
    "Main Contractor": "Main Contractor",
    "Sub Contractor": "Sub Contractor",
    "Management Consultant": "Management Consultant",
    "CLNT": "Other",
    "Client": "Other",
}

DISC_MAP = {
    "COMM": "Commercial",
    "DELV": "Delivery",
    "DSGN": "Design",
    "CORP": "Corporate",
    "SUPP": "Support Services",
    "OTHR": "Other",
    "Commercial": "Commercial",
    "Delivery": "Delivery",
    "Design": "Design",
    "Corporate": "Corporate",
    "Support Services": "Support Services",
    "Other": "Other",
}

CAT_MAP = {
    "OBE M": "OBE M",
    "OBE T": "OBE T",
    "TGT": "TGT",
    "EXT": "EXT",
    "HPC": "HPC",
    "GEN": "GEN",
    "OBE Member": "OBE M",
    "OBE Target": "OBE T",
}


def normalise_env(val):
    if not val:
        return None
    return ENV_MAP.get(val.strip(), val.strip())

def normalise_disc(val):
    if not val:
        return None
    return DISC_MAP.get(val.strip(), val.strip())

def normalise_cat(val):
    if not val:
        return "GEN"
    return CAT_MAP.get(val.strip(), val.strip())


def migrate():
    if not os.path.exists(OLD_DB):
        print(f"Error: Old database not found at: {OLD_DB}")
        print("   Edit OLD_DB path in this script to point to your old crm.db")
        sys.exit(1)

    print(f"Reading from: {OLD_DB}")
    print(f"Writing to:   {NEW_DB}")
    print()

    old = sqlite3.connect(OLD_DB)
    old.row_factory = sqlite3.Row
    new = sqlite3.connect(NEW_DB)
    new.row_factory = sqlite3.Row

    now = datetime.now(timezone.utc).isoformat()

    # ── People ────────────────────────────────────────────────────────────────
    print("Migrating contacts...")
    old_people = old.execute("SELECT * FROM PERSON").fetchall()
    migrated = 0
    skipped = 0
    taxonomy_fixes = 0

    for p in old_people:
        p = dict(p)
        person_id = p.get("person_id") or str(uuid.uuid4())

        # Check if already exists in new DB
        existing = new.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)).fetchone()
        if existing:
            skipped += 1
            continue

        old_env = p.get("env") or p.get("environment")
        old_disc = p.get("disc") or p.get("discipline")
        old_cat = p.get("cat") or p.get("category")

        norm_env = normalise_env(old_env)
        norm_disc = normalise_disc(old_disc)
        norm_cat = normalise_cat(old_cat)

        if norm_env != old_env or norm_disc != old_disc or norm_cat != old_cat:
            taxonomy_fixes += 1

        new.execute("""
            INSERT OR IGNORE INTO PERSON (
                person_id, full_name, title_current, company_name_raw,
                email_primary, email_secondary, phone_primary, phone_secondary,
                linkedin_url, cat, env, disc, contact_value,
                career_summary, key_professional_notes, key_personal_notes,
                key_gossip_notes, intel_notes, employment_history, personal_data,
                profile_photo_url, meeting_status, next_contact_due_date,
                last_meeting_date, last_contact_datetime,
                is_active, is_ts_advisory_candidate,
                created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            person_id,
            p.get("full_name", "Unknown"),
            p.get("title_current"),
            p.get("company_name_raw"),
            p.get("email_primary"),
            p.get("email_secondary"),
            p.get("phone_primary"),
            p.get("phone_secondary"),
            p.get("linkedin_url"),
            norm_cat,
            norm_env,
            norm_disc,
            p.get("contact_value"),
            p.get("career_summary"),
            p.get("key_professional_notes"),
            p.get("key_personal_notes"),
            p.get("key_gossip_notes"),
            p.get("intel_notes"),
            p.get("employment_history"),
            p.get("personal_data"),
            p.get("profile_photo_url"),
            p.get("meeting_status"),
            p.get("next_contact_due_date"),
            p.get("last_meeting_date"),
            p.get("last_contact_datetime") or p.get("last_updated_datetime"),
            p.get("is_active", 1),
            p.get("is_ts_advisory_candidate", 0),
            p.get("created_datetime") or now,
            p.get("last_updated_datetime") or now,
        ))
        migrated += 1

    new.commit()
    print(f"   Done: {migrated} contacts migrated | {skipped} already existed | {taxonomy_fixes} taxonomy values normalised")

    # ── Companies ─────────────────────────────────────────────────────────────
    print("Migrating companies...")
    try:
        old_companies = old.execute("SELECT * FROM COMPANY").fetchall()
        comp_migrated = 0
        for c in old_companies:
            c = dict(c)
            cid = c.get("company_id") or str(uuid.uuid4())
            existing = new.execute("SELECT company_id FROM COMPANY WHERE company_id=?", (cid,)).fetchone()
            if existing:
                continue
            new.execute("""
                INSERT OR IGNORE INTO COMPANY
                (company_id, company_name_raw, industry, website, headquarters, description, created_at, last_updated_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                cid,
                c.get("company_name_raw", "Unknown"),
                c.get("industry"),
                c.get("website"),
                c.get("headquarters"),
                c.get("description"),
                c.get("created_datetime") or now,
                c.get("last_updated_datetime") or now,
            ))
            comp_migrated += 1
        new.commit()
        print(f"   Done: {comp_migrated} companies migrated")
    except Exception as e:
        print(f"   Warning: Companies migration skipped: {e}")

    # Interactions
    print("Migrating interactions...")
    try:
        old_interactions = old.execute("SELECT * FROM INTERACTION").fetchall()
        int_migrated = 0
        for i in old_interactions:
            i = dict(i)
            iid = i.get("interaction_id") or str(uuid.uuid4())
            existing = new.execute("SELECT interaction_id FROM INTERACTION WHERE interaction_id=?", (iid,)).fetchone()
            if existing:
                continue

            # Old schema had 'datetime' and 'channel' — map them
            interaction_at = i.get("interaction_at") or i.get("datetime") or i.get("timestamp") or now
            channel = i.get("channel") or i.get("type") or "note"
            raw_text = i.get("raw_text") or i.get("notes") or ""
            summary = i.get("summary") or i.get("summary_text") or raw_text[:200]

            action_items = i.get("action_items", "[]")
            if not isinstance(action_items, str):
                action_items = json.dumps(action_items or [])

            topics = i.get("topics", "[]")
            if not isinstance(topics, str):
                topics = json.dumps(topics or [])

            new.execute("""
                INSERT OR IGNORE INTO INTERACTION
                (interaction_id, person_id, channel, raw_text, summary, action_items,
                 topics, external_id, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                iid,
                i.get("person_id"),
                channel,
                raw_text,
                summary,
                action_items,
                topics,
                i.get("external_id"),
                i.get("created_datetime") or now,
                interaction_at,
            ))
            int_migrated += 1
        new.commit()
        print(f"   Done: {int_migrated} interactions migrated")
    except Exception as e:
        print(f"   Warning: Interactions migration partial: {e}")

    # ── Tasks ─────────────────────────────────────────────────────────────────
    print("Migrating tasks...")
    try:
        old_tasks = old.execute("SELECT * FROM TASK").fetchall()
        task_migrated = 0
        for t in old_tasks:
            t = dict(t)
            tid = t.get("task_id") or str(uuid.uuid4())
            existing = new.execute("SELECT task_id FROM TASK WHERE task_id=?", (tid,)).fetchone()
            if existing:
                continue
            new.execute("""
                INSERT OR IGNORE INTO TASK
                (task_id, person_id, task_text, due_date, due_time, priority, status, created_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (
                tid,
                t.get("person_id"),
                t.get("task_text", "Task"),
                t.get("due_date"),
                t.get("due_time"),
                t.get("priority", "medium"),
                t.get("status", "open"),
                t.get("created_datetime") or now,
            ))
            task_migrated += 1
        new.commit()
        print(f"   Done: {task_migrated} tasks migrated")
    except Exception as e:
        print(f"   Warning: Tasks migration partial: {e}")

    # ── Topic Intelligence ────────────────────────────────────────────────────
    print("Migrating intelligence databank...")
    try:
        old_intel = old.execute("SELECT * FROM TOPIC_INTELLIGENCE").fetchall()
        intel_migrated = 0
        for i in old_intel:
            i = dict(i)
            iid = i.get("intel_id") or str(uuid.uuid4())[:12]
            existing = new.execute("SELECT intel_id FROM TOPIC_INTELLIGENCE WHERE intel_id=?", (iid,)).fetchone()
            if existing:
                continue
            new.execute("""
                INSERT OR IGNORE INTO TOPIC_INTELLIGENCE
                (intel_id, person_id, topic, intel_text, confidence, source_interaction_id, created_at)
                VALUES (?,?,?,?,?,?,?)
            """, (
                iid,
                i.get("person_id"),
                i.get("topic"),
                i.get("intel_text"),
                i.get("confidence", 3),
                i.get("source_interaction_id"),
                i.get("timestamp") or now,
            ))
            intel_migrated += 1
        new.commit()
        print(f"   Done: {intel_migrated} intelligence nuggets migrated")
    except Exception as e:
        print(f"   Warning: Intelligence migration partial: {e}")

    old.close()
    new.close()

    print()
    print("=" * 50)
    print("MIGRATION COMPLETE")
    print(f"   New database: {os.path.abspath(NEW_DB)}")
    print("   Old database: UNTOUCHED (safe to keep as backup)")
    print("=" * 50)


if __name__ == "__main__":
    migrate()
