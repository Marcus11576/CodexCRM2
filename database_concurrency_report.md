# Database Concurrency Report

## What caused the locking risk
- Each request and background job opened its own SQLite connection, but writes were still competing for the single SQLite writer.
- The AI worker could launch multiple jobs at once, so background updates to `AI_JOB`, `INTERACTION`, `TASK`, `TOPIC_INTELLIGENCE`, and `PERSON` could collide with live profile and upload actions.
- The old database layer relied mostly on per-call commits with no shared retry policy for `database is locked` failures.
- Some synchronous SQLite reads in the AI service used default connection settings, so they were not aligned with WAL and timeout tuning.

## What was changed
- Added a lock-aware database layer in `backend/database.py` with:
  - WAL, `busy_timeout`, `synchronous=NORMAL`, `foreign_keys=ON`, `temp_store=MEMORY`, and `wal_autocheckpoint`
  - `run_read(...)` with lock retry handling
  - `run_write(...)` with short `BEGIN IMMEDIATE` transactions, rollback on failure, and retry handling for SQLite lock errors
  - a process-local write gate so background jobs and live requests in this app instance do not stampede the SQLite writer
- Moved the AI job system in `backend/services/ai_jobs.py` onto the new helpers:
  - atomic job claiming
  - bounded background concurrency
  - short read phases and short write phases around long AI/file work
- Moved high-contention CRM paths onto the new helpers:
  - `backend/routers/interactions.py`
  - `backend/routers/intelligence.py`
  - key profile writes in `backend/routers/people.py`
  - chatbot tool writes in `backend/services/ai_service.py`
- Updated synchronous AI-service reads to use the tuned SQLite connection helper instead of raw default `sqlite3.connect(...)` calls.

## Whether SQLite is still suitable
- SQLite is still acceptable for the next phase if deployment stays single-node, background job concurrency stays modest, and AI/sync throughput is still moderate.
- With the changes above, SQLite is materially safer for the current CRM plus background AI pattern because transactions are shorter, retries are explicit, and writes are coordinated.

## Whether a move to Postgres is recommended
- Yes, a move to Postgres is recommended before pushing much further into higher-volume AI automation, multi-worker deployment, or heavier external sync.
- The trigger to move is not basic usage; it is scaling into more simultaneous writers, more queued AI jobs, scheduled sync jobs, and any plan to run multiple app instances.
- Recommendation: keep SQLite for the immediate next slice of product work, but treat Postgres as the next infrastructure milestone before broader AI and sync scaling.
