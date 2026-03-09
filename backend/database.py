"""
Antigravity CRM — Database Layer
Single async SQLite connection with WAL mode for concurrent reads.
All queries go through this module — no raw sqlite3 calls elsewhere.
"""
import asyncio
import sqlite3
from contextlib import asynccontextmanager

import aiosqlite

from backend.config import settings

SQLITE_BUSY_TIMEOUT_MS = 15000
SQLITE_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1000
LOCK_RETRY_DELAYS = (0.1, 0.25, 0.5, 1.0, 2.0)
WRITE_LOCK = asyncio.Lock()


def _is_lock_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "database is locked",
            "database table is locked",
            "database schema is locked",
            "database is busy",
        )
    )


def _configure_sync_connection(conn: sqlite3.Connection, *, read_only: bool = False) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    if read_only:
        conn.execute("PRAGMA query_only=ON")


async def _configure_async_connection(db: aiosqlite.Connection, *, read_only: bool = False) -> None:
    db.row_factory = aiosqlite.Row
    await db.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA temp_store=MEMORY")
    await db.execute("PRAGMA wal_autocheckpoint=1000")
    if read_only:
        await db.execute("PRAGMA query_only=ON")


def get_sync_db(*, read_only: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(
        settings.DB_PATH,
        timeout=SQLITE_TIMEOUT_SECONDS,
        isolation_level=None,
        check_same_thread=False,
    )
    _configure_sync_connection(conn, read_only=read_only)
    return conn

def _create_tables_sync():
    """
    Create all tables on first run. Uses synchronous sqlite3 for startup only.
    This is the SINGLE place the schema is defined — no ALTER TABLE hacks ever again.
    """
    conn = get_sync_db()
    c = conn.cursor()

    # --- USERS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS USER (
            user_id     TEXT PRIMARY KEY,
            email       TEXT UNIQUE NOT NULL,
            full_name   TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role        TEXT DEFAULT 'member',  -- admin | member | viewer
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT NOT NULL,
            last_login  TEXT
        )
    """)

    # --- PEOPLE ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS PERSON (
            person_id               TEXT PRIMARY KEY,
            full_name               TEXT NOT NULL,
            title_current           TEXT,
            company_name_raw        TEXT,

            -- Contact info
            email_primary           TEXT,
            email_secondary         TEXT,
            phone_primary           TEXT,
            phone_secondary         TEXT,
            linkedin_url            TEXT,

            -- Taxonomy (all use canonical CONFIG_TAXONOMY values)
            cat                     TEXT,   -- OBE M | OBE T | TGT | EXT | HPC | GEN
            env                     TEXT,   -- Developer - Gov | Consultant | etc.
            disc                    TEXT,   -- Commercial | Design | Delivery | etc.
            contact_value           TEXT,   -- Hot | Warm | Cold
            engagement_status       TEXT,   -- Active | Dormant | Lost

            -- Intelligence
            career_summary          TEXT,
            key_professional_notes  TEXT,
            key_personal_notes      TEXT,
            key_gossip_notes        TEXT,
            intel_notes             TEXT,
            employment_history      TEXT,   -- JSON array
            personal_data           TEXT,   -- JSON object

            -- Media
            profile_photo_url       TEXT,

            -- Meeting management
            meeting_status          TEXT,   -- on_track | soon | overdue
            next_contact_due_date   TEXT,
            last_meeting_date       TEXT,
            last_contact_datetime   TEXT,

            -- Briefing cache
            cached_briefing         TEXT,   -- JSON
            briefing_last_updated   TEXT,
            briefing_ttl_hours      INTEGER DEFAULT 24,

            -- Flags
            is_active               INTEGER DEFAULT 1,
            is_ts_advisory_candidate INTEGER DEFAULT 0,
            reminder_sent           INTEGER DEFAULT 0,

            -- Predictive Metrics (Phase 2)
            relationship_health     INTEGER DEFAULT 50, -- 0-100
            engagement_velocity     REAL DEFAULT 0.0,   -- Rate of interactions
            peak_engagement_time    TEXT,               -- Recommended time/day
            next_best_action        TEXT,               -- AI recommendation
            last_success_at         TEXT,

            -- Audit
            created_at              TEXT NOT NULL,
            last_updated_at         TEXT NOT NULL
        )
    """)

    # --- INTERACTIONS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS INTERACTION (
            interaction_id  TEXT PRIMARY KEY,
            person_id       TEXT NOT NULL REFERENCES PERSON(person_id),
            channel         TEXT NOT NULL,  -- note | whatsapp | email | call | meeting | screenshot | audio | upload | system_audit
            raw_text        TEXT,
            summary         TEXT,
            action_items    TEXT,   -- JSON array of strings
            topics          TEXT,   -- JSON array of strings
            sentiment       TEXT,   -- positive | neutral | negative
            external_id     TEXT,   -- for M365 dedup
            media_url       TEXT,   -- attached file path
            created_at      TEXT NOT NULL,
            interaction_at  TEXT NOT NULL,  -- when the interaction happened (not when logged)
            
            -- Success & Metrics (Phase 2)
            success_rating  INTEGER,        -- 1-5 score
            engagement_value INTEGER,       -- 0-100 impact score
            is_strategic    INTEGER DEFAULT 0, -- 1 if moved the needle for TS/OBE
            metric_tags     TEXT            -- JSON array of specific wins
        )
    """)

    # --- TOPIC INTELLIGENCE ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS TOPIC_INTELLIGENCE (
            intel_id                TEXT PRIMARY KEY,
            person_id               TEXT NOT NULL REFERENCES PERSON(person_id),
            topic                   TEXT NOT NULL,  -- business_focus | recruitment_talent | family_personal | obe_focus
            intel_text              TEXT NOT NULL,
            confidence              INTEGER DEFAULT 3,  -- 1-5
            source_interaction_id   TEXT,
            status                  TEXT DEFAULT 'draft',  -- draft | approved | rejected | archived
            source_snippet          TEXT,
            created_at              TEXT NOT NULL
        )
    """)

    # --- COMPANIES ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS COMPANY (
            company_id          TEXT PRIMARY KEY,
            company_name_raw    TEXT NOT NULL,
            industry            TEXT,
            website             TEXT,
            headquarters        TEXT,
            description         TEXT,
            created_at          TEXT NOT NULL,
            last_updated_at     TEXT NOT NULL
        )
    """)

    # --- TASKS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS TASK (
            task_id         TEXT PRIMARY KEY,
            person_id       TEXT REFERENCES PERSON(person_id),
            task_text       TEXT NOT NULL,
            due_date        TEXT,
            due_time        TEXT,
            priority        TEXT DEFAULT 'medium',  -- high | medium | low
            status          TEXT DEFAULT 'open',    -- open | done | cancelled
            recurrence_rule TEXT,
            source_interaction_id TEXT,
            created_at      TEXT NOT NULL,
            completed_at    TEXT
        )
    """)

    # --- EVENTS ---

    # --- M365 ACCOUNTS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS M365_ACCOUNT (
            person_id TEXT PRIMARY KEY REFERENCES PERSON(person_id),
            last_sync_at TEXT,
            sync_status TEXT DEFAULT 'idle',  -- idle | working | error
            sync_error TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # global credentials store for authenticated CRM user
    c.execute("""
        CREATE TABLE IF NOT EXISTS M365_CREDENTIALS (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # migration helpers for added columns
    def _add_column_if_missing(table: str, column: str, definition: str):
        c.execute(f"PRAGMA table_info({table})")
        existing = [row[1] for row in c.fetchall()]
        if column not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ensure PERSON has last_m365_sync column for quick lookup
    _add_column_if_missing("PERSON", "m365_last_sync", "TEXT")
    # ensure M365_ACCOUNT has last_synced_count for diagnostics
    _add_column_if_missing("M365_ACCOUNT", "last_synced_count", "INTEGER DEFAULT 0")
    # migrate TOPIC_INTELLIGENCE to add status and source_snippet for user review
    _add_column_if_missing("TOPIC_INTELLIGENCE", "status", "TEXT DEFAULT 'draft'")
    _add_column_if_missing("TOPIC_INTELLIGENCE", "source_snippet", "TEXT")

    # data hygiene migrations for legacy intelligence rows
    c.execute("UPDATE TOPIC_INTELLIGENCE SET source_snippet = intel_text WHERE source_snippet IS NULL OR TRIM(source_snippet) = ''")
    for legacy_value, canonical_value in {
        "Business Focus": "business_focus",
        "Recruitment & Talent": "recruitment_talent",
        "Family & Personal": "family_personal",
        "OBE Focus": "obe_focus",
    }.items():
        c.execute("UPDATE AI_SIGNAL SET category = ? WHERE category = ?", (canonical_value, legacy_value))
    c.execute("""
        CREATE TABLE IF NOT EXISTS EVENT (
            event_id         TEXT PRIMARY KEY,
            event_name       TEXT NOT NULL,
            location         TEXT,
            event_date       TEXT NOT NULL,
            topics           TEXT,   -- JSON array of strings
            notes            TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS PERSON_EVENT (
            person_event_id   TEXT PRIMARY KEY,
            person_id         TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            event_id          TEXT NOT NULL REFERENCES EVENT(event_id) ON DELETE CASCADE,
            status            TEXT NOT NULL,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            UNIQUE(person_id, event_id)
        )
    """)

    # --- TAXONOMY CONFIG ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS CONFIG_TAXONOMY (
            config_id       TEXT PRIMARY KEY,
            category_type   TEXT NOT NULL,  -- cat | env | disc | contact_value | engagement_status
            label           TEXT NOT NULL,  -- Human readable: "OBE Member"
            value           TEXT NOT NULL,  -- Stored code: "OBE M"
            color           TEXT,
            display_order   INTEGER DEFAULT 0,
            is_active       INTEGER DEFAULT 1
        )
    """)

    # --- PLATFORM MEMORY (Phase 2 Cross-Contact Learning) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS PLATFORM_MEMORY (
            memory_id       TEXT PRIMARY KEY,
            memory_type     TEXT NOT NULL,  -- market_trend | company_shift | talent_pattern
            entity_ref      TEXT,           -- Optional: "Stantec" or "Data Centers"
            memory_text     TEXT NOT NULL,
            strength        INTEGER DEFAULT 1,
            last_reinforced TEXT NOT NULL,
            created_at      TEXT NOT NULL
        )
    """)

    # --- AI PIPELINE: ARTIFACTS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS AI_ARTIFACT (
            artifact_id     TEXT PRIMARY KEY,
            person_id       TEXT NOT NULL REFERENCES PERSON(person_id),
            source_interaction_id TEXT REFERENCES INTERACTION(interaction_id),
            channel         TEXT NOT NULL,  -- email | chat | audio | file | manual_paste
            raw_content     TEXT,
            media_url       TEXT,           -- path to uploaded file
            metadata        TEXT,           -- JSON (headers, filenames, etc)
            created_at      TEXT NOT NULL
        )
    """)

    # --- AI PIPELINE: SIGNALS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS AI_SIGNAL (
            signal_id       TEXT PRIMARY KEY,
            artifact_id     TEXT NOT NULL REFERENCES AI_ARTIFACT(artifact_id),
            person_id       TEXT NOT NULL REFERENCES PERSON(person_id),
            category        TEXT NOT NULL,  -- Business Focus | Recruitment & Talent | Family & Personal | OBE Focus
            content         TEXT NOT NULL,  -- The extracted point
            source_snippet  TEXT NOT NULL,  -- Traceability excerpt
            confidence      INTEGER DEFAULT 3,
            status          TEXT DEFAULT 'draft', -- draft | approved | archived | rejected
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)

    # --- AI PIPELINE: BRIEFS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS AI_BRIEF (
            brief_id        TEXT PRIMARY KEY,
            person_id       TEXT NOT NULL REFERENCES PERSON(person_id),
            content_json    TEXT NOT NULL,
            source_signal_ids TEXT,          -- JSON array
            created_at      TEXT NOT NULL
        )
    """)

    # --- AI PIPELINE: FEEDBACK EVENTS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS AI_FEEDBACK (
            feedback_id     TEXT PRIMARY KEY,
            target_type     TEXT NOT NULL,  -- signal | brief
            target_id       TEXT NOT NULL,
            event_type      TEXT NOT NULL,  -- approval | edit | rejection | promotion | demotion | deletion
            details_json    TEXT,           -- Diff or reason
            user_id         TEXT,           -- Admin user ID
            created_at      TEXT NOT NULL
        )
    """)

    # --- AI JOBS ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS AI_JOB (
            job_id           TEXT PRIMARY KEY,
            person_id        TEXT REFERENCES PERSON(person_id),
            interaction_id   TEXT REFERENCES INTERACTION(interaction_id),
            parent_job_id    TEXT REFERENCES AI_JOB(job_id),
            job_type         TEXT NOT NULL,
            status           TEXT NOT NULL,
            payload_json     TEXT,
            result_json      TEXT,
            error_text       TEXT,
            attempts         INTEGER DEFAULT 0,
            max_attempts     INTEGER DEFAULT 3,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            started_at       TEXT,
            completed_at     TEXT
        )
    """)

    # --- INDEXES ---
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_person_active ON PERSON(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_person_cat ON PERSON(cat)",
        "CREATE INDEX IF NOT EXISTS idx_person_env ON PERSON(env)",
        "CREATE INDEX IF NOT EXISTS idx_person_meeting_status ON PERSON(meeting_status)",
        "CREATE INDEX IF NOT EXISTS idx_person_name ON PERSON(full_name)",
        "CREATE INDEX IF NOT EXISTS idx_interaction_person ON INTERACTION(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_interaction_at ON INTERACTION(interaction_at)",
        "CREATE INDEX IF NOT EXISTS idx_topic_person ON TOPIC_INTELLIGENCE(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_topic_type ON TOPIC_INTELLIGENCE(topic)",
        "CREATE INDEX IF NOT EXISTS idx_task_person ON TASK(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_task_status ON TASK(status)",
        "CREATE INDEX IF NOT EXISTS idx_task_due ON TASK(due_date)",
        "CREATE INDEX IF NOT EXISTS idx_event_date ON EVENT(event_date)",
        "CREATE INDEX IF NOT EXISTS idx_event_name ON EVENT(event_name)",
        "CREATE INDEX IF NOT EXISTS idx_person_event_person ON PERSON_EVENT(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_person_event_event ON PERSON_EVENT(event_id)",
        "CREATE INDEX IF NOT EXISTS idx_person_event_status ON PERSON_EVENT(status)",
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_type ON CONFIG_TAXONOMY(category_type)",

        # AI Pipeline Indexes
        "CREATE INDEX IF NOT EXISTS idx_ai_artifact_person ON AI_ARTIFACT(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_signal_person ON AI_SIGNAL(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_signal_artifact ON AI_SIGNAL(artifact_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_signal_category ON AI_SIGNAL(category)",
        "CREATE INDEX IF NOT EXISTS idx_ai_brief_person ON AI_BRIEF(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_feedback_target ON AI_FEEDBACK(target_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_job_person ON AI_JOB(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_job_status ON AI_JOB(status)",
        "CREATE INDEX IF NOT EXISTS idx_ai_job_interaction ON AI_JOB(interaction_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_job_type ON AI_JOB(job_type)",
    ]
    for idx in indexes:
        c.execute(idx)

    conn.commit()

    # --- SEED TAXONOMY (only if empty) ---
    c.execute("SELECT COUNT(*) FROM CONFIG_TAXONOMY")
    if c.fetchone()[0] == 0:
        _seed_taxonomy(c)
        conn.commit()

    conn.close()
    print(f"Database ready: {settings.DB_PATH}")


def _seed_taxonomy(cursor):
    """Canonical taxonomy values — single source of truth for all value codes."""
    import uuid
    seed = [
        # Categories (cat)
        ("cat", "OBE Member",                   "OBE M",                "#3b82f6", 1),
        ("cat", "OBE Target",                   "OBE T",                "#6366f1", 2),
        ("cat", "Target Client",                "TGT",                  "#f59e0b", 3),
        ("cat", "Existing Client",              "EXT",                  "#10b981", 4),
        ("cat", "High Performing Candidate",    "HPC",                  "#8b5cf6", 5),
        ("cat", "General Contact",              "GEN",                  "#6b7280", 6),

        # Environments (env)
        ("env", "Developer - Government",       "Developer - Gov",      "#ef4444", 1),
        ("env", "Developer - Semi-Government",  "Developer - Semi-Gov", "#f97316", 2),
        ("env", "Developer - Private",          "Developer - Private",  "#facc15", 3),
        ("env", "Consultant",                   "Consultant",           "#84cc16", 4),
        ("env", "Main Contractor",              "Main Contractor",      "#06b6d4", 5),
        ("env", "Sub Contractor",               "Sub Contractor",       "#3b82f6", 6),
        ("env", "Management Consultant",        "Management Consultant","#a855f7", 7),
        ("env", "Other",                        "Other",                "#ec4899", 8),

        # Disciplines (disc)
        ("disc", "Commercial",                  "Commercial",           "#3b82f6", 1),
        ("disc", "Delivery",                    "Delivery",             "#10b981", 2),
        ("disc", "Design",                      "Design",               "#f59e0b", 3),
        ("disc", "Corporate",                   "Corporate",            "#8b5cf6", 4),
        ("disc", "Support Services",            "Support Services",     "#6b7280", 5),
        ("disc", "Other",                       "Other",                "#94a3b8", 6),

        # Contact Value
        ("contact_value", "Hot",  "Hot",  "#ef4444", 1),
        ("contact_value", "Warm", "Warm", "#f97316", 2),
        ("contact_value", "Cold", "Cold", "#3b82f6", 3),

        # Engagement Status
        ("engagement_status", "Active",  "Active",  "#10b981", 1),
        ("engagement_status", "Dormant", "Dormant", "#f59e0b", 2),
        ("engagement_status", "Lost",    "Lost",    "#ef4444", 3),
    ]
    for cat_type, label, value, color, order in seed:
        cursor.execute(
            "INSERT INTO CONFIG_TAXONOMY (config_id, category_type, label, value, color, display_order) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], cat_type, label, value, color, order)
        )
    print("Taxonomy seeded with canonical values")


@asynccontextmanager
async def get_db(*, read_only: bool = False):
    """
    Async database context manager. Usage:
        async with get_db() as db:
            await db.execute(...)
    """
    async with aiosqlite.connect(
        settings.DB_PATH,
        timeout=SQLITE_TIMEOUT_SECONDS,
        isolation_level=None,
    ) as db:
        await _configure_async_connection(db, read_only=read_only)
        yield db


async def run_read(operation, *, label: str = "read"):
    last_exc = None
    for attempt, delay in enumerate((*LOCK_RETRY_DELAYS, None), start=1):
        try:
            async with get_db(read_only=True) as db:
                return await operation(db)
        except Exception as exc:
            last_exc = exc
            if not _is_lock_error(exc) or delay is None:
                raise
            print(f"SQLite lock during {label}; retrying read (attempt {attempt})")
            await asyncio.sleep(delay)
    raise last_exc


async def run_write(operation, *, label: str = "write", immediate: bool = True):
    async with WRITE_LOCK:
        last_exc = None
        for attempt, delay in enumerate((*LOCK_RETRY_DELAYS, None), start=1):
            try:
                async with get_db() as db:
                    await db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                    try:
                        result = await operation(db)
                    except Exception:
                        await db.rollback()
                        raise
                    await db.commit()
                    return result
            except Exception as exc:
                last_exc = exc
                if not _is_lock_error(exc) or delay is None:
                    raise
                print(f"SQLite lock during {label}; retrying write (attempt {attempt})")
                await asyncio.sleep(delay)
        raise last_exc


def init_db():
    """Called once at application startup."""
    _create_tables_sync()





