# Preference Learning Note

## New module structure
- `backend/services/preference_learning.py`: canonical feedback events, structured event recording, preference profile aggregation, and prompt guidance helpers.
- `backend/routers/ai_pipeline.py`: normalized feedback intake and manual signal creation logging.
- `backend/services/ai_service.py`: learned signal scoring, non-fabrication guardrails, and preference-aware signal review and brief generation.
- `backend/services/ai_jobs.py`: passes learned preference profile into background brief generation and stores `brief_id` plus source signal ids.
- `backend/routers/intelligence.py`: returns the latest `brief_id` with cached briefs so brief feedback targets the actual brief record.
- `frontend/js/profile/core.js`, `frontend/js/profile/signals.js`, `frontend/js/profile/briefing.js`, `frontend/profile.html`: canonical feedback actions from the profile UI and brief UI.

## Responsibilities moved where
- Structured feedback storage now goes through `record_feedback_event(...)` instead of ad hoc inserts.
- Feedback event normalization now maps legacy names like `approval` and `rejection` to canonical actions like `approve` and `reject`.
- Learned user preferences are aggregated from explicit behaviour, not vague memory, using the stored feedback event details.
- Future signal ranking now blends action weights with learned preferences for concise, commercial, relationship-relevant, low-fluff, practical content.
- Future meeting briefs now receive the learned preference guidance and explicit instructions not to silently change facts.

## Legacy code still left for later cleanup
- `TOPIC_INTELLIGENCE` and `AI_SIGNAL` still coexist as two signal stores; the ranking logic now handles both, but the model would be cleaner if they are unified later.
- The profile feedback UI is still plain JS with modal prompts and could use stronger automated browser coverage later.
- Some older brief and signal flows still use broad fetch-and-render patterns instead of a more testable state store.

## How the system learns
- Every `approve`, `reject`, `edit`, `promote`, `demote`, and `manual_add` action is stored as a structured `AI_FEEDBACK` event.
- Each event records normalized action type, source context, inferred or explicit preference dimensions, and whether the action was a user override.
- The backend aggregates those events into a per-person preference profile, then uses that profile to re-rank signals and guide future brief generation.

## How the user can correct it
- The user can always override the AI by editing a signal, manually adding a signal, promoting something, or demoting/rejecting it.
- Those override actions are stored explicitly and weighted more strongly than passive approval so the next ranking pass respects the correction.
- Prompt guardrails now tell the assistant to reorder and compress facts, but never silently change factual meaning.

## How feedback affects future briefs
- Signal ranking uses both the structured action weights and the learned preference profile before selecting the highest-priority inputs for a brief.
- Background brief generation now passes the learned preferences into the brief prompt, pushing the output toward concise, commercially useful, relationship-relevant, practical prep with minimal fluff.
- Stored briefs now carry `brief_id` and source signal ids so future brief feedback is linked to the real brief artifact.
