# AI Data Flow Note

## Primary flow

`Artifact -> classification -> extraction -> signals -> brief -> feedback -> learning`

## Manual note / WhatsApp / text import

1. Request hits `backend/routers/interactions.py` or `backend/routers/intelligence.py`.
2. A pending `INTERACTION` row is created to preserve existing CRM behaviour.
3. An `AI_ARTIFACT` row is created with:
   - duplicate hash
   - input type
   - profile match state
   - confirmation flag
4. A background AI job is queued.
5. Extraction updates the artifact, persists legacy interaction/topic/task side effects, and writes traceable `AI_SIGNAL` rows.
6. The person brief is marked stale and a deduped brief job is queued.

## Image flow

1. Upload is saved and recorded as an artifact.
2. Vision classifies `image_type`.
3. If `profile_picture`, the artifact is stored and the interaction summary is updated, but no profile photo overwrite happens automatically.
4. If `screenshot` or `general_image`, readable content is extracted and signal generation continues.

## Audio flow

1. Upload creates the artifact and a transcription job.
2. Transcription updates the interaction and artifact.
3. Signal extraction runs as a second job using the transcribed text.

## Brief flow

1. `backend/services/ai_pipeline_service.py::load_signals_for_brief` loads AI signals first and backfills legacy signal rows when needed.
2. `backend/services/ai_service.py::generate_briefing` receives only:
   - person profile
   - signals
   - upcoming events
3. `backend/services/ai_pipeline_service.py::store_brief` stores:
   - structured brief sections
   - signal set hash
   - confidence summary
   - recent changes
   - event relevance

## Feedback flow

1. User feedback is written to `AI_FEEDBACK`.
2. Feedback updates preference scoring and preserves before/after context when supplied.
3. Signal/category/status edits invalidate cached briefs so the next brief regenerates from updated signal truth.
