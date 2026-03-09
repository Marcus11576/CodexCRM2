# Known Issues & Technical Debt Register

This register identifies current architectural limitations and identified debt for the v2.0.0 implementation.

### 1. Database & Persistence
- **Single Async Connection**: Current SQLite implementation uses a single async connection pool. High concurrent write loads (e.g., mass email sync) may cause target database locked errors despite WAL mode.
- **JSON in SQL**: Fields like `employment_history` and `personal_data` are stored as JSON strings. This limits direct SQL queryability for these fields and requires Python-level filtering.

### 2. Frontend Architecture
- **Monolithic Page Scripts**: `profile.js` exceeds 1,600 lines. Responsibilities include DOM manipulation, API calls, and local state management. This makes unit testing complex.
- **Manual Reactive UI**: UI updates are handled through manual DOM manipulation (`innerHTML`, `getElementById`). There is no centralized state management or virtual DOM, leading to potential race conditions during rapid updates.
- **In-Memory Cache**: `window.currentPersonData` is used as a global store. Page reloads clear this state, requiring unnecessary API refetches.

### 3. AI & Data Extraction
- **Latency**: GPT-4o based briefing generation can take 5-10 seconds. We currently lack a background job/polling mechanism for UI "loading" states for these long-running tasks.
- **Hallucination Protection**: While `ALLOWED_PROFILE_FIELDS` restricts AI scope, the extraction of "Intelligence Nuggets" remains subject to minor LLM hallucinations in high-ambiguity transcripts.

### 4. Testing & Reliability
- **Verification Gap**: Integration tests (`tests/`) focus on happy-path API responses. There is very limited coverage for edge cases (e.g., malformed M365 payloads or DB disconnection).
- **Environment Isolation**: The app assumes a local `crm.db`. Automated tests currently modify the live local database rather than using a mock or temporary DB.

### 5. Legacy Debt
- **v1/v2 Redundancy**: `compat_v1.py` contains duplicated logic for interaction logging. Failure to decommission the v1 layer results in increased maintenance overhead.

### 6. M365 Sync
- **Partial Rollout Risk**: Sync worker still uses SQLite and long polling; heavy mailbox volumes can trigger locking issues and slow down the API if not throttled. Consider moving sync state to a dedicated queue or migrating to Postgres before enabling at scale.
- **OAuth Flow State**: The device-code flow state is kept in-memory; a server restart during auth progress will orphan the login attempt. A migration to persistent state will be required for production.
