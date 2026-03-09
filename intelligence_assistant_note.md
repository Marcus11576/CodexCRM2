# Intelligence Assistant Feature

This document describes the new *intelligence assistant* AI chatbot that reviews stored signals and helps generate actionable intelligence.

## Role & Capabilities
- Reads all **signals** recorded in `TOPIC_INTELLIGENCE` for a contact.
- Summarises each signal, removes fluff and ensures the category is correct.
- Classifies every signal into **exactly one** of the four buckets:
  `business_focus`, `recruitment_talent`, `family_personal`, `obe_focus`.
- Builds a **four‑part meeting brief** using only the signals (not raw interactions).
- Prioritises recency and practical importance when creating summaries.
- Provides traceability by carrying the original snippet back to the UI.
- Supports human feedback: approve, reject, edit, promote, demote signals.
- Logs all user actions in the `AI_FEEDBACK` table for future model training.

## Intelligence Layer Extension
- The briefing worker (`_handle_brief_generation`) now also loads *upcoming event* context from `EVENT`/`PERSON_EVENT`.
- `generate_briefing()` was expanded with an `events` parameter and the prompt includes event names, dates, topics and attendance status.
- This makes future briefs aware of whether the contact is a target/invited/confirmed/registered for events.

## Database Changes
- `TOPIC_INTELLIGENCE` gains two new columns:
  - `status` (`draft` | `approved` | `rejected` | `archived`)
  - `source_snippet` (text excerpt for traceability)
- Migration code added via `_add_column_if_missing` during startup.
- New AI pipeline tables (`AI_SIGNAL`, `AI_BRIEF`, `AI_FEEDBACK`) already exist; the assistant uses `AI_FEEDBACK` for tracking.

## API Endpoints
- **`POST /api/intelligence/assistant/{person_id}/review`**
  Runs the intelligence assistant over signals and events, returns structured JSON with reviewed signals and a draft brief.
- **`PATCH /api/people/{person_id}/intelligence/{intel_id}`**
  Edit text, topic, status or confidence of an existing signal.
- **`POST /api/ai/feedback`**
  Existing endpoint used from the UI to record user actions (approve/reject/edit/promotion/demotion).

Feedback entries do not automatically change signal status; the UI may call the patch endpoint separately if needed.
## Preference Learning Layer

The system builds a lightweight preference model from the structured feedback events stored in `AI_FEEDBACK`.
Every time a user approves, rejects, edits, promotes, demotes or manually adds a signal we record an event with the exact action type.
These events are counted by `compute_signal_scores`, which assigns positive weights to desirable behaviours (approval, promotion, edit, manual_add)
and negative weights to undesired ones (rejection, demotion).  Scores accumulate per signal per person.

### How learning affects behaviour

* **Signal ordering** – when the assistant reviews signals it sorts them by descending score, so the most “liked” items surface first.
* **Brief prioritisation** – the background briefing job pulls signals in score order before composing the databank text, causing high‑scoring intelligence to appear earlier in generated briefs.

The model is purely additive and never alters the factual content of a signal; it only influences ranking.
Since feedback events are explicit, the system learns from actual user behaviour rather than vague heuristics.

### User control & correction

Users can always override the AI:
- In the review modal they can change a signal’s category, text or confidence.
- They can manually add, promote, demote or reject any signal at any time.
- Each of these actions generates a new feedback event, immediately affecting future rankings.

If the system seems to prioritise the wrong material, simply apply corrective feedback: rejecting extraneous fluff or promoting a crucial detail will steer future briefs toward concise, commercially useful, relationship‑relevant content. Manual additions are given a boost so they remain prominent.

### Summary

The preference layer ensures that the assistant’s outputs progressively align with the user’s style: concise summaries, practical meeting preparation, and minimal fluff. Transparent feedback and the ability to override at any moment keep the human firmly in the loop.
## UI Flow
1. **Reviewing signals**
   - A **"Review Signals"** button appears in the Intelligence Databank header.
   - Clicking it posts to `/api/intelligence/assistant/{person}` and opens a modal.
   - The modal lists each signal with category, text, snippet and action buttons.
   - The bottom of the modal shows a preview of the suggested four‑part brief.

2. **Editing signals**
   - Within the review modal each signal has an **Edit** button.
   - Editing opens a prompt where the text may be changed; the change is PATCHed to the server and a `edit` feedback event is logged.
   - Approving, rejecting, promoting, or demoting also sends corresponding feedback events.
   - The status field is updated via the `PATCH /people/.../intelligence` endpoint when appropriate.

3. **Generating the four‑part meeting brief**
   - The brief appears in the review modal after the signals list.
   - The same assistant call can be reused by clicking the review button again.
   - Approved signals (status `approved`) may later be used by the normal briefing job when `POST /api/intelligence/brief/{person}` is invoked.

## Testing
- New `tests/test_intelligence_assistant.py` covers:
  - review endpoint invocation with dummy AI service, ensuring signals/events passed correctly.
  - feedback logging and signal editing persistence.

## Notes
- Events context is included automatically in both the review and the regular brief generation routines.
- The existing strategist service (`/api/v2/intelligence/synthesize`) remains unchanged and independent.
- Future iterations could migrate stored signals to `AI_SIGNAL` and phase out `TOPIC_INTELLIGENCE`.
