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
            contact_value           TEXT,   -- Hot | Warm | Cold | Frozen
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
            is_pilot_cohort         INTEGER DEFAULT 0,
            pilot_cohort_assigned_at TEXT,
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

    # Canonical company directory layer (additive and non-breaking).
    c.execute("""
        CREATE TABLE IF NOT EXISTS COMPANY_DIRECTORY (
            company_key          TEXT PRIMARY KEY,
            company_name         TEXT NOT NULL,
            company_type         TEXT,
            parent_company_key   TEXT REFERENCES COMPANY_DIRECTORY(company_key) ON DELETE SET NULL,
            industry             TEXT,
            website              TEXT,
            headquarters         TEXT,
            description          TEXT,
            notes                TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS COMPANY_ALIAS (
            alias_key            TEXT PRIMARY KEY,
            company_key          TEXT NOT NULL REFERENCES COMPANY_DIRECTORY(company_key) ON DELETE CASCADE,
            alias_name           TEXT NOT NULL,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            UNIQUE(company_key, alias_name)
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS PERSON_OPPORTUNITY (
            opportunity_id       TEXT PRIMARY KEY,
            person_id            TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            account_name         TEXT,
            opportunity_type     TEXT,
            stage                TEXT,
            value_band           TEXT,
            trigger_date         TEXT,
            strategic_importance INTEGER DEFAULT 50,
            status               TEXT DEFAULT 'open',
            owner                TEXT,
            notes                TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS COMPANY_OPPORTUNITY (
            company_opportunity_id TEXT PRIMARY KEY,
            company_name_raw       TEXT NOT NULL,
            opportunity_type       TEXT,
            stage                  TEXT,
            value_band             TEXT,
            trigger_date           TEXT,
            strategic_importance   INTEGER DEFAULT 50,
            status                 TEXT DEFAULT 'open',
            owner                  TEXT,
            notes                  TEXT,
            created_at             TEXT NOT NULL,
            updated_at             TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS INTERPRETED_INTERACTION (
            interpretation_id         TEXT PRIMARY KEY,
            person_id                 TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            company_name_raw          TEXT,
            source_interaction_id     TEXT NOT NULL REFERENCES INTERACTION(interaction_id) ON DELETE CASCADE,
            source_kind               TEXT NOT NULL DEFAULT 'interaction',
            thread_id                 TEXT,
            what_is_happening         TEXT NOT NULL,
            why_it_matters            TEXT NOT NULL,
            stage                     TEXT,
            momentum                  TEXT,
            intent_signals_json       TEXT,
            pain_points_json          TEXT,
            relationship_signals_json TEXT,
            opportunity_signals_json  TEXT,
            influence_signals_json    TEXT,
            market_intel_signals_json TEXT,
            friction_signals_json     TEXT,
            recommended_action        TEXT,
            confidence_score          INTEGER DEFAULT 0,
            evidence_snippets_json    TEXT,
            created_at                TEXT NOT NULL,
            updated_at                TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS ENDURING_MEMORY (
            memory_id                TEXT PRIMARY KEY,
            person_id                TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            memory_domain            TEXT NOT NULL,
            memory_type              TEXT NOT NULL,
            memory_text              TEXT NOT NULL,
            importance_score         INTEGER DEFAULT 50,
            confidence_score         INTEGER DEFAULT 50,
            status                   TEXT DEFAULT 'draft',
            source_interpretation_id TEXT REFERENCES INTERPRETED_INTERACTION(interpretation_id) ON DELETE SET NULL,
            source_interaction_id    TEXT REFERENCES INTERACTION(interaction_id) ON DELETE SET NULL,
            evidence_snippets_json   TEXT,
            created_at               TEXT NOT NULL,
            updated_at               TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS MARKET_INTEL (
            market_intel_id          TEXT PRIMARY KEY,
            topic                    TEXT NOT NULL,
            sector                   TEXT,
            region                   TEXT,
            signal_text              TEXT NOT NULL,
            signal_type              TEXT,
            confidence_score         INTEGER DEFAULT 50,
            importance_score         INTEGER DEFAULT 50,
            linked_people_json       TEXT,
            linked_companies_json    TEXT,
            evidence_snippets_json   TEXT,
            status                   TEXT DEFAULT 'draft',
            source_interpretation_id TEXT REFERENCES INTERPRETED_INTERACTION(interpretation_id) ON DELETE SET NULL,
            created_at               TEXT NOT NULL,
            updated_at               TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS RELATIONSHIP_SITUATION (
            situation_id             TEXT PRIMARY KEY,
            person_id                TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            company_name_raw         TEXT,
            situation_key            TEXT NOT NULL,
            situation_type           TEXT NOT NULL,
            title                    TEXT NOT NULL,
            why_it_matters           TEXT,
            situation_summary        TEXT,
            stage                    TEXT,
            status                   TEXT DEFAULT 'open',
            momentum                 TEXT,
            confidence_score         INTEGER DEFAULT 0,
            first_seen_at            TEXT NOT NULL,
            last_seen_at             TEXT NOT NULL,
            last_interaction_at      TEXT,
            state_changed_at         TEXT NOT NULL,
            channels_json            TEXT,
            key_points_json          TEXT,
            recommended_action       TEXT,
            source_count             INTEGER DEFAULT 0,
            owner                    TEXT,
            resolution_note          TEXT,
            created_at               TEXT NOT NULL,
            updated_at               TEXT NOT NULL,
            UNIQUE(person_id, situation_key)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS RELATIONSHIP_SITUATION_SOURCE (
            situation_source_id      TEXT PRIMARY KEY,
            situation_id             TEXT NOT NULL REFERENCES RELATIONSHIP_SITUATION(situation_id) ON DELETE CASCADE,
            interpretation_id        TEXT NOT NULL REFERENCES INTERPRETED_INTERACTION(interpretation_id) ON DELETE CASCADE,
            interaction_at           TEXT,
            created_at               TEXT NOT NULL,
            UNIQUE(situation_id, interpretation_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS RELATIONSHIP_SITUATION_EVENT (
            event_id                 TEXT PRIMARY KEY,
            situation_id             TEXT NOT NULL REFERENCES RELATIONSHIP_SITUATION(situation_id) ON DELETE CASCADE,
            person_id                TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            event_type               TEXT NOT NULL,
            previous_status          TEXT,
            new_status               TEXT,
            previous_stage           TEXT,
            new_stage                TEXT,
            previous_momentum        TEXT,
            new_momentum             TEXT,
            summary                  TEXT,
            details_json             TEXT,
            source_interpretation_id TEXT REFERENCES INTERPRETED_INTERACTION(interpretation_id) ON DELETE SET NULL,
            created_at               TEXT NOT NULL
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
        if not existing:
            return
        if column not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # ensure PERSON has last_m365_sync column for quick lookup
    _add_column_if_missing("PERSON", "m365_last_sync", "TEXT")
    _add_column_if_missing("PERSON", "next_meeting_date", "TEXT")
    _add_column_if_missing("PERSON", "next_meeting_topic", "TEXT")
    _add_column_if_missing("PERSON", "network_tier", "TEXT")
    _add_column_if_missing("PERSON", "maintenance_mode", "TEXT")
    _add_column_if_missing("PERSON", "relationship_owner", "TEXT")
    _add_column_if_missing("PERSON", "decision_role", "TEXT")
    _add_column_if_missing("PERSON", "influence_scope", "TEXT")
    _add_column_if_missing("PERSON", "strategic_value_score", "INTEGER DEFAULT 50")
    _add_column_if_missing("PERSON", "influence_score", "INTEGER DEFAULT 50")
    _add_column_if_missing("PERSON", "future_option_score", "INTEGER DEFAULT 50")
    _add_column_if_missing("PERSON", "coverage_risk_score", "INTEGER DEFAULT 50")
    _add_column_if_missing("PERSON", "opportunity_readiness_score", "INTEGER DEFAULT 0")
    _add_column_if_missing("PERSON", "relationship_confidence_score", "INTEGER DEFAULT 50")
    _add_column_if_missing("PERSON", "last_meaningful_contact_at", "TEXT")
    _add_column_if_missing("PERSON", "last_inbound_at", "TEXT")
    _add_column_if_missing("PERSON", "last_outbound_at", "TEXT")
    _add_column_if_missing("PERSON", "unanswered_outbound_count", "INTEGER DEFAULT 0")
    _add_column_if_missing("PERSON", "reactivation_trigger_notes", "TEXT")
    _add_column_if_missing("PERSON", "account_priority", "TEXT")
    _add_column_if_missing("PERSON", "tier_rationale", "TEXT")
    _add_column_if_missing("PERSON", "last_health_refresh_at", "TEXT")
    _add_column_if_missing("PERSON", "is_pilot_cohort", "INTEGER DEFAULT 0")
    _add_column_if_missing("PERSON", "pilot_cohort_assigned_at", "TEXT")
    _add_column_if_missing("PERSON", "relationship_stage_override", "TEXT")
    _add_column_if_missing("PERSON", "stage_override_source_interaction_id", "TEXT")
    _add_column_if_missing("PERSON", "stage_override_updated_at", "TEXT")
    _add_column_if_missing("REL_INTEL_RUN", "action_ledger_json", "TEXT")
    # ensure M365_ACCOUNT has last_synced_count for diagnostics
    _add_column_if_missing("M365_ACCOUNT", "last_synced_count", "INTEGER DEFAULT 0")
    _add_column_if_missing("USER", "auth_provider", "TEXT DEFAULT 'local'")
    _add_column_if_missing("USER", "external_subject", "TEXT")
    # migrate TOPIC_INTELLIGENCE to add status and source_snippet for user review
    _add_column_if_missing("TOPIC_INTELLIGENCE", "status", "TEXT DEFAULT 'draft'")
    _add_column_if_missing("TOPIC_INTELLIGENCE", "source_snippet", "TEXT")
    _add_column_if_missing("TOPIC_INTELLIGENCE", "business_subtopic", "TEXT")
    _add_column_if_missing("INTERACTION", "direction", "TEXT")
    _add_column_if_missing("INTERACTION", "meaningful_flag", "INTEGER DEFAULT 0")
    _add_column_if_missing("INTERACTION", "outcome_type", "TEXT")
    _add_column_if_missing("INTERACTION", "response_flag", "INTEGER DEFAULT 0")
    _add_column_if_missing("INTERACTION", "follow_up_committed_flag", "INTEGER DEFAULT 0")
    _add_column_if_missing("INTERACTION", "meeting_quality_status", "TEXT")
    _add_column_if_missing("INTERACTION", "meeting_response_status", "TEXT")
    _add_column_if_missing("INTERACTION", "meeting_last_modified_at", "TEXT")
    _add_column_if_missing("INTERPRETED_INTERACTION", "thread_id", "TEXT")

    # data hygiene migrations for legacy intelligence rows
    c.execute("UPDATE TOPIC_INTELLIGENCE SET source_snippet = intel_text WHERE source_snippet IS NULL OR TRIM(source_snippet) = ''")
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS SYSTEM_SETTING (
            setting_key     TEXT PRIMARY KEY,
            setting_json    TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS TRANSCRIPT_TAG_OVERRIDE (
            override_id        TEXT PRIMARY KEY,
            person_id          TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            evidence_id        TEXT NOT NULL,
            mode               TEXT NOT NULL,  -- stage | knowledge
            segment_hash       TEXT NOT NULL,
            segment_text       TEXT NOT NULL,
            tag_code           TEXT NOT NULL,
            tag_label          TEXT,
            tag_class          TEXT,
            approach_version   TEXT NOT NULL,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            UNIQUE(person_id, evidence_id, mode, segment_hash, approach_version)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS TRANSCRIPT_TAG_LEARNING (
            learning_id        TEXT PRIMARY KEY,
            mode               TEXT NOT NULL,  -- stage | knowledge
            segment_hash       TEXT NOT NULL,
            normalized_text    TEXT NOT NULL,
            token_signature    TEXT NOT NULL,
            tag_code           TEXT NOT NULL,
            tag_label          TEXT,
            tag_class          TEXT,
            vote_count         INTEGER DEFAULT 1,
            last_person_id     TEXT,
            approach_version   TEXT NOT NULL,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            UNIQUE(mode, segment_hash, approach_version)
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS AI_RUN_LOG (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            related_artifact_id TEXT,
            related_signal_id TEXT,
            related_profile_id TEXT,
            model_name TEXT NOT NULL,
            prompt_family TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            token_usage_json TEXT,
            latency_ms INTEGER,
            accepted_output_boolean INTEGER,
            rejection_reason TEXT,
            metadata_json TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS REL_INTEL_RUN (
            run_id                    TEXT PRIMARY KEY,
            person_id                 TEXT NOT NULL REFERENCES PERSON(person_id) ON DELETE CASCADE,
            source_digest             TEXT NOT NULL,
            pipeline_version          TEXT NOT NULL,
            model_name                TEXT NOT NULL,
            status                    TEXT NOT NULL,
            cleaned_interactions_json TEXT,
            claim_ledger_json         TEXT,
            action_ledger_json        TEXT,
            scores_json               TEXT,
            briefing_json             TEXT,
            created_at                TEXT NOT NULL,
            updated_at                TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS REL_INTEL_AGENT_OUTPUT (
            output_id                 TEXT PRIMARY KEY,
            run_id                    TEXT NOT NULL REFERENCES REL_INTEL_RUN(run_id) ON DELETE CASCADE,
            agent_name                TEXT NOT NULL,
            model_name                TEXT NOT NULL,
            output_json               TEXT,
            created_at                TEXT NOT NULL
        )
    """)

    artifact_columns = {
        "profile_id_nullable": "TEXT",
        "input_type": "TEXT",
        "input_type_confidence": "REAL",
        "raw_content_or_path": "TEXT",
        "extracted_text": "TEXT",
        "extracted_metadata_json": "TEXT",
        "source_name": "TEXT",
        "source_type": "TEXT",
        "source_strength": "REAL DEFAULT 0.5",
        "artifact_sentiment": "TEXT",
        "artifact_sentiment_confidence": "REAL",
        "profile_match_state": "TEXT DEFAULT 'confirmed'",
        "requires_confirmation": "INTEGER DEFAULT 0",
        "duplicate_hash": "TEXT",
        "status": "TEXT DEFAULT 'pending'",
        "updated_at": "TEXT",
        "duplicate_of_artifact_id": "TEXT",
    }
    for column, definition in artifact_columns.items():
        _add_column_if_missing("AI_ARTIFACT", column, definition)

    signal_columns = {
        "profile_id": "TEXT",
        "signal_text": "TEXT",
        "primary_category": "TEXT",
        "business_subtopic": "TEXT",
        "secondary_relevance_json": "TEXT",
        "signal_sentiment": "TEXT",
        "signal_sentiment_confidence": "REAL",
        "importance_score": "REAL DEFAULT 0",
        "confidence_score": "REAL DEFAULT 0",
        "source_strength": "REAL DEFAULT 0.5",
        "section_hypothesis_fit_score": "REAL DEFAULT 0",
        "overall_hypothesis_fit_score": "REAL DEFAULT 0",
        "review_state": "TEXT DEFAULT 'pending_review'",
        "included_in_brief": "INTEGER DEFAULT 1",
        "source_interaction_id": "TEXT REFERENCES INTERACTION(interaction_id)",
        "event_relevance_json": "TEXT",
    }
    for column, definition in signal_columns.items():
        _add_column_if_missing("AI_SIGNAL", column, definition)

    brief_columns = {
        "profile_id": "TEXT",
        "generated_from_signal_set_hash": "TEXT",
        "business_focus_summary": "TEXT",
        "recruitment_talent_summary": "TEXT",
        "family_personal_summary": "TEXT",
        "obe_focus_summary": "TEXT",
        "overall_brief_summary": "TEXT",
        "top_priorities_json": "TEXT",
        "recent_changes_json": "TEXT",
        "event_relevance_json": "TEXT",
        "confidence_summary_json": "TEXT",
        "updated_at": "TEXT",
        "stale_after": "TEXT",
        "is_stale": "INTEGER DEFAULT 0",
    }
    for column, definition in brief_columns.items():
        _add_column_if_missing("AI_BRIEF", column, definition)

    feedback_columns = {
        "profile_id": "TEXT",
        "artifact_id": "TEXT",
        "signal_id": "TEXT",
        "brief_id": "TEXT",
        "action_type": "TEXT",
        "before_text": "TEXT",
        "after_text": "TEXT",
        "before_category": "TEXT",
        "after_category": "TEXT",
        "before_profile_id": "TEXT",
        "after_profile_id": "TEXT",
        "reason_code": "TEXT",
    }
    for column, definition in feedback_columns.items():
        _add_column_if_missing("AI_FEEDBACK", column, definition)

    job_columns = {
        "related_artifact_id": "TEXT",
        "related_profile_id": "TEXT",
        "related_event_id": "TEXT",
        "progress": "REAL DEFAULT 0",
        "error_message": "TEXT",
        "retry_count": "INTEGER DEFAULT 0",
        "dedupe_key": "TEXT",
        "heartbeat_at": "TEXT",
    }
    for column, definition in job_columns.items():
        _add_column_if_missing("AI_JOB", column, definition)

    for legacy_value, canonical_value in {
        "Business Focus": "business_focus",
        "Recruitment & Talent": "recruitment_talent",
        "Family & Personal": "family_personal",
        "OBE Focus": "obe_focus",
    }.items():
        c.execute("UPDATE AI_SIGNAL SET category = ? WHERE category = ?", (canonical_value, legacy_value))
    c.execute("UPDATE PERSON_EVENT SET status = 'Invited' WHERE LOWER(TRIM(status)) = 'invited'")
    c.execute("UPDATE PERSON_EVENT SET status = 'Target' WHERE LOWER(TRIM(status)) = 'target'")
    c.execute("UPDATE PERSON_EVENT SET status = 'Confirmed' WHERE LOWER(TRIM(status)) = 'confirmed'")
    c.execute("UPDATE PERSON_EVENT SET status = 'Registered' WHERE LOWER(TRIM(status)) = 'registered'")
    c.execute("UPDATE AI_ARTIFACT SET profile_id_nullable = person_id WHERE profile_id_nullable IS NULL AND person_id IS NOT NULL")
    c.execute("UPDATE AI_ARTIFACT SET raw_content_or_path = COALESCE(raw_content, media_url, raw_content_or_path) WHERE raw_content_or_path IS NULL")
    c.execute("UPDATE AI_ARTIFACT SET extracted_metadata_json = metadata WHERE extracted_metadata_json IS NULL AND metadata IS NOT NULL")
    c.execute("UPDATE AI_ARTIFACT SET updated_at = created_at WHERE updated_at IS NULL")
    c.execute("UPDATE AI_ARTIFACT SET status = COALESCE(status, 'processed') WHERE status IS NULL")
    c.execute("UPDATE AI_SIGNAL SET profile_id = person_id WHERE profile_id IS NULL AND person_id IS NOT NULL")
    c.execute("UPDATE AI_SIGNAL SET signal_text = content WHERE signal_text IS NULL AND content IS NOT NULL")
    c.execute("UPDATE AI_SIGNAL SET primary_category = category WHERE primary_category IS NULL AND category IS NOT NULL")
    c.execute("UPDATE AI_SIGNAL SET confidence_score = CASE WHEN confidence IS NOT NULL THEN ROUND(confidence / 5.0, 3) ELSE confidence_score END WHERE confidence_score IS NULL OR confidence_score = 0")
    c.execute("UPDATE AI_SIGNAL SET updated_at = created_at WHERE updated_at IS NULL")
    c.execute("UPDATE AI_SIGNAL SET review_state = CASE status WHEN 'approved' THEN 'approved' WHEN 'rejected' THEN 'rejected' ELSE COALESCE(review_state, 'pending_review') END WHERE review_state IS NULL OR TRIM(review_state) = ''")
    c.execute("UPDATE AI_BRIEF SET profile_id = person_id WHERE profile_id IS NULL AND person_id IS NOT NULL")
    c.execute("UPDATE AI_BRIEF SET updated_at = created_at WHERE updated_at IS NULL")
    c.execute("UPDATE AI_FEEDBACK SET action_type = event_type WHERE action_type IS NULL AND event_type IS NOT NULL")
    c.execute("UPDATE AI_FEEDBACK SET signal_id = target_id WHERE signal_id IS NULL AND target_type = 'signal'")
    c.execute("UPDATE AI_FEEDBACK SET brief_id = target_id WHERE brief_id IS NULL AND target_type = 'brief'")
    c.execute("UPDATE AI_JOB SET related_profile_id = person_id WHERE related_profile_id IS NULL AND person_id IS NOT NULL")
    c.execute("UPDATE AI_JOB SET error_message = error_text WHERE error_message IS NULL AND error_text IS NOT NULL")
    c.execute("UPDATE AI_JOB SET progress = CASE WHEN status = 'completed' THEN 1.0 WHEN status = 'running' THEN 0.5 ELSE COALESCE(progress, 0) END WHERE progress IS NULL")

    # --- INDEXES ---
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_person_active ON PERSON(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_person_cat ON PERSON(cat)",
        "CREATE INDEX IF NOT EXISTS idx_person_env ON PERSON(env)",
        "CREATE INDEX IF NOT EXISTS idx_person_meeting_status ON PERSON(meeting_status)",
        "CREATE INDEX IF NOT EXISTS idx_person_name ON PERSON(full_name)",
        "CREATE INDEX IF NOT EXISTS idx_person_next_meeting_date ON PERSON(next_meeting_date)",
        "CREATE INDEX IF NOT EXISTS idx_interaction_person ON INTERACTION(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_interaction_at ON INTERACTION(interaction_at)",
        "CREATE INDEX IF NOT EXISTS idx_interaction_external_id ON INTERACTION(external_id)",
        "CREATE INDEX IF NOT EXISTS idx_topic_person ON TOPIC_INTELLIGENCE(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_topic_type ON TOPIC_INTELLIGENCE(topic)",
        "CREATE INDEX IF NOT EXISTS idx_task_person ON TASK(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_task_status ON TASK(status)",
        "CREATE INDEX IF NOT EXISTS idx_task_due ON TASK(due_date)",
        "CREATE INDEX IF NOT EXISTS idx_opportunity_person ON PERSON_OPPORTUNITY(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_opportunity_status ON PERSON_OPPORTUNITY(status)",
        "CREATE INDEX IF NOT EXISTS idx_opportunity_trigger_date ON PERSON_OPPORTUNITY(trigger_date)",
        "CREATE INDEX IF NOT EXISTS idx_company_opportunity_name ON COMPANY_OPPORTUNITY(company_name_raw)",
        "CREATE INDEX IF NOT EXISTS idx_company_opportunity_status ON COMPANY_OPPORTUNITY(status)",
        "CREATE INDEX IF NOT EXISTS idx_company_opportunity_trigger_date ON COMPANY_OPPORTUNITY(trigger_date)",
        "CREATE INDEX IF NOT EXISTS idx_company_directory_name ON COMPANY_DIRECTORY(company_name)",
        "CREATE INDEX IF NOT EXISTS idx_company_directory_parent ON COMPANY_DIRECTORY(parent_company_key)",
        "CREATE INDEX IF NOT EXISTS idx_company_alias_company ON COMPANY_ALIAS(company_key)",
        "CREATE INDEX IF NOT EXISTS idx_company_alias_name ON COMPANY_ALIAS(alias_name)",
        "CREATE INDEX IF NOT EXISTS idx_interpreted_interaction_person ON INTERPRETED_INTERACTION(person_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_interpreted_interaction_source ON INTERPRETED_INTERACTION(source_interaction_id)",
        "CREATE INDEX IF NOT EXISTS idx_enduring_memory_person ON ENDURING_MEMORY(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_enduring_memory_domain ON ENDURING_MEMORY(memory_domain)",
        "CREATE INDEX IF NOT EXISTS idx_enduring_memory_status ON ENDURING_MEMORY(status)",
        "CREATE INDEX IF NOT EXISTS idx_market_intel_status ON MARKET_INTEL(status)",
        "CREATE INDEX IF NOT EXISTS idx_market_intel_topic ON MARKET_INTEL(topic)",
        "CREATE INDEX IF NOT EXISTS idx_relationship_situation_person ON RELATIONSHIP_SITUATION(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationship_situation_status ON RELATIONSHIP_SITUATION(status)",
        "CREATE INDEX IF NOT EXISTS idx_relationship_situation_last_seen ON RELATIONSHIP_SITUATION(last_seen_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_situation_key ON RELATIONSHIP_SITUATION(person_id, situation_key)",
        "CREATE INDEX IF NOT EXISTS idx_relationship_situation_source_situation ON RELATIONSHIP_SITUATION_SOURCE(situation_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_situation_source_pair ON RELATIONSHIP_SITUATION_SOURCE(situation_id, interpretation_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationship_situation_event_situation ON RELATIONSHIP_SITUATION_EVENT(situation_id)",
        "CREATE INDEX IF NOT EXISTS idx_relationship_situation_event_person ON RELATIONSHIP_SITUATION_EVENT(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_event_date ON EVENT(event_date)",
        "CREATE INDEX IF NOT EXISTS idx_event_name ON EVENT(event_name)",
        "CREATE INDEX IF NOT EXISTS idx_person_event_person ON PERSON_EVENT(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_person_event_event ON PERSON_EVENT(event_id)",
        "CREATE INDEX IF NOT EXISTS idx_person_event_status ON PERSON_EVENT(status)",
        "CREATE INDEX IF NOT EXISTS idx_taxonomy_type ON CONFIG_TAXONOMY(category_type)",
        "CREATE INDEX IF NOT EXISTS idx_system_setting_updated ON SYSTEM_SETTING(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_override_lookup ON TRANSCRIPT_TAG_OVERRIDE(person_id, evidence_id, mode)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_override_mode_hash ON TRANSCRIPT_TAG_OVERRIDE(mode, segment_hash)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_override_approach ON TRANSCRIPT_TAG_OVERRIDE(approach_version)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_learning_mode ON TRANSCRIPT_TAG_LEARNING(mode)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_learning_mode_hash ON TRANSCRIPT_TAG_LEARNING(mode, segment_hash)",
        "CREATE INDEX IF NOT EXISTS idx_transcript_learning_approach ON TRANSCRIPT_TAG_LEARNING(approach_version)",

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
        "CREATE INDEX IF NOT EXISTS idx_ai_artifact_duplicate ON AI_ARTIFACT(duplicate_hash)",
        "CREATE INDEX IF NOT EXISTS idx_ai_artifact_status ON AI_ARTIFACT(status)",
        "CREATE INDEX IF NOT EXISTS idx_ai_signal_review_state ON AI_SIGNAL(review_state)",
        "CREATE INDEX IF NOT EXISTS idx_ai_signal_primary_category ON AI_SIGNAL(primary_category)",
        "CREATE INDEX IF NOT EXISTS idx_ai_signal_business_subtopic ON AI_SIGNAL(business_subtopic)",
        "CREATE INDEX IF NOT EXISTS idx_ai_brief_stale ON AI_BRIEF(person_id, is_stale)",
        "CREATE INDEX IF NOT EXISTS idx_ai_job_dedupe ON AI_JOB(dedupe_key)",
        "CREATE INDEX IF NOT EXISTS idx_ai_run_log_task_type ON AI_RUN_LOG(task_type)",
        "CREATE INDEX IF NOT EXISTS idx_ai_run_log_status ON AI_RUN_LOG(status)",
        "CREATE INDEX IF NOT EXISTS idx_rel_intel_run_person ON REL_INTEL_RUN(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_rel_intel_run_digest ON REL_INTEL_RUN(person_id, source_digest)",
        "CREATE INDEX IF NOT EXISTS idx_rel_intel_run_created ON REL_INTEL_RUN(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_rel_intel_agent_output_run ON REL_INTEL_AGENT_OUTPUT(run_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_external_subject ON USER(external_subject)",
    ]
    for idx in indexes:
        c.execute(idx)

    conn.commit()

    # --- SEED TAXONOMY (only if empty) ---
    c.execute("SELECT COUNT(*) FROM CONFIG_TAXONOMY")
    if c.fetchone()[0] == 0:
        _seed_taxonomy(c)
        conn.commit()
    else:
        _ensure_taxonomy_defaults(c)
        conn.commit()

    conn.close()
    print(f"Database ready: {settings.DB_PATH}")


def _seed_taxonomy(cursor):
    """Canonical taxonomy values — single source of truth for all value codes."""
    import uuid
    seed = _taxonomy_seed_rows()
    for cat_type, label, value, color, order in seed:
        cursor.execute(
            "INSERT INTO CONFIG_TAXONOMY (config_id, category_type, label, value, color, display_order) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], cat_type, label, value, color, order)
        )
    print("Taxonomy seeded with canonical values")


def _taxonomy_seed_rows():
    return [
        # Categories (cat)
        ("cat", "OBE Member",                   "OBE M",                "#3b82f6", 1),
        ("cat", "OBE Target",                   "OBE T",                "#6366f1", 2),
        ("cat", "Target Client",                "TGT",                  "#f59e0b", 3),
        ("cat", "Existing Client",              "EXT",                  "#10b981", 4),
        ("cat", "High Performing Candidate",    "HPC",                  "#8b5cf6", 5),
        ("cat", "General Contact",              "GEN",                  "#6b7280", 6),
        ("cat", "TS Advisory",                  "TSA",                  "#e5e7eb", 7),

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
        ("contact_value", "Hot",    "Hot",    "#ef4444", 1),
        ("contact_value", "Warm",   "Warm",   "#f97316", 2),
        ("contact_value", "Cold",   "Cold",   "#3b82f6", 3),
        ("contact_value", "Frozen", "Frozen", "#94a3b8", 4),

        # Engagement Status
        ("engagement_status", "Active",  "Active",  "#10b981", 1),
        ("engagement_status", "Dormant", "Dormant", "#f59e0b", 2),
        ("engagement_status", "Lost",    "Lost",    "#ef4444", 3),
    ]


def _ensure_taxonomy_defaults(cursor):
    import uuid

    for cat_type, label, value, color, order in _taxonomy_seed_rows():
        cursor.execute(
            "SELECT 1 FROM CONFIG_TAXONOMY WHERE category_type = ? AND value = ? LIMIT 1",
            (cat_type, value),
        )
        if cursor.fetchone():
            continue
        cursor.execute(
            "INSERT INTO CONFIG_TAXONOMY (config_id, category_type, label, value, color, display_order) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4())[:12], cat_type, label, value, color, order)
        )


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





