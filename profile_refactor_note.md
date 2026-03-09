# Profile Refactor Note

## New module structure
- `frontend/js/profile/core.js`
  Handles shared state, person loading, URL parsing, common field updates, and light profile-level helpers.
- `frontend/js/profile/header.js`
  Handles the profile header render, taxonomy toggles, advisory state, and the edit-profile header modal.
- `frontend/js/profile/interactions.js`
  Handles the interaction timeline, note/file submission flow, drag-drop uploads, and edit/delete interaction actions.
- `frontend/js/profile/briefing.js`
  Handles meeting brief loading, background AI job status, retry flow, audio generation, and propensity widgets.
- `frontend/js/profile/signals.js`
  Handles intelligence databank rendering, personal intelligence editing, and employment timeline editing.
- `frontend/js/profile/workflow.js`
  Handles tasks, event linking on the profile, scroll helpers, and page bootstrap wiring.
- `frontend/js/profile.js`
  Now acts as a thin compatibility/bootstrap placeholder instead of holding the page logic.

## Responsibilities moved where
- Profile header, contact surface, taxonomy controls, and header editing moved to `header.js`.
- Interaction logging, uploads, and editing moved to `interactions.js`.
- Signal/intelligence display and personal data editing moved to `signals.js`.
- Meeting brief logic and AI background-job polling moved to `briefing.js`.
- Task deletion, event links, and DOMContentLoaded bootstrap moved to `workflow.js`.
- Shared state and API-facing person refresh/update logic moved to `core.js`.

## Legacy code left for later cleanup
- `frontend/profile.html` still contains a large inline M365/chat script block that should be split later.  We have added status fetching and display code; migrating script to `/js/m365.js` would clean up the page.
- `frontend/js/profile.full.js` remains as a safety reference copy of the pre-split monolith during this transition.
- The profile page still relies on global browser functions for inline button handlers; converting those handlers is a later cleanup step, not part of this behavior-preserving refactor.
