# AI Architecture Note

This repository now runs a migration-safe hybrid AI architecture on top of the existing CRM instead of replacing it.

## Active layers

- Guardrail and intake layer
  - `backend/routers/interactions.py`
  - `backend/routers/intelligence.py`
  - `backend/services/ai_pipeline_service.py`
  - Every new note/upload/import creates an `AI_ARTIFACT` record first.
- Shared learning and run audit layer
  - `backend/services/preference_learning.py`
  - `backend/services/ai_runtime.py`
  - Cross-profile learning is stored in `PLATFORM_MEMORY`.
  - Model execution is logged in `AI_RUN_LOG`.
- Profile-specific intelligence layer
  - `AI_SIGNAL`, `AI_BRIEF`, `AI_FEEDBACK`
  - Briefs are generated from signals plus event context, not from raw interactions/tasks.

## Compatibility strategy

- Existing CRM behaviour is preserved by keeping:
  - `INTERACTION`
  - `TOPIC_INTELLIGENCE`
  - `TASK`
  - cached briefing reads in `PERSON`
- New AI processing dual-writes traceable records into the richer AI tables.
- Legacy UI paths still work while the AI foundation is upgraded underneath them.

## Core service boundaries

- `backend/services/ai_runtime.py`
  - central OpenAI execution
  - retries delegated to jobs
  - AI run audit logging
- `backend/services/ai_pipeline_service.py`
  - artifact creation/update
  - duplicate detection
  - signal persistence
  - brief storage
  - review queue and ops metrics
- `backend/services/ai_jobs.py`
  - background orchestration
  - idempotent job processing
  - artifact-first extraction flow

## Important guardrails now enforced

- profile-picture uploads are identified only and do not silently overwrite `PERSON.profile_photo_url`
- failed extraction marks artifacts failed instead of fabricating successful-looking AI output
- duplicate artifacts are detected and marked instead of being reprocessed blindly
- signal-generated briefs are built from signals only
