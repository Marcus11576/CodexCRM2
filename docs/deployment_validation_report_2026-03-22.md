# Deployment Validation Report (2026-03-22)

## Scope
Pre-deploy validation executed against local runtime (`http://127.0.0.1:8009`) before production deployment and before full data import.

## Deployment Execution

- Git commit created: `d215c44c7f5749fe2a1f5b5697c548909d676f9d`
- Branch pushed for deploy: `origin/codex/deploy-prep`
- Remote verification: branch head equals commit above.
- Production-mode startup smoke (local) passed with:
  - `ENV=production`
  - `AUTH_DISABLED=false`
  - `COOKIE_SECURE=true`
  - Health check result: HTTP `200` on `http://127.0.0.1:8015/api/health`

## Automated Checks Executed

1. Backend regression suite
- Command: `./.venv/Scripts/python.exe -m pytest -q tests`
- Result: `118 passed, 1 warning`
- Notes: warning is Python `imghdr` deprecation in `backend/routers/interactions.py`.

2. Browser full audit
- Command: `./.venv/Scripts/python.exe tests/ui_full_audit_selenium.py`
- Result: `PASS`
- Pages validated: dashboard, agenda, analytics, events, activities, settings, 2 profile pages.

3. Browser profile upload/chat flow
- Command: `./.venv/Scripts/python.exe tests/ui_profile_chat_upload_selenium.py`
- Result: `PASS`
- Steps validated:
  - upload image via profile chat
  - upload PDF via profile chat
  - chat-driven role end-date update
- Notes: one transient timeout occurred on first attempt; immediate rerun passed fully.

4. Runtime health
- Command: `GET /api/health`
- Result: HTTP `200`

## Pre-Deploy Feature Status

Validation matrix has been updated to:
- `Owner`: `Codex automation`
- `Status`: `PASS_PRE_DEPLOY | PENDING_POST_DATA`

File: `docs/system_feature_validation_matrix.csv`

## Route-Level Tracking

Route inventory and per-route status tracker:
- `docs/system_feature_routes.csv`

## Post-Data Import Plan (Required)

After full data load, execute:

1. Data quality sampling
- 30 random uploaded artifacts (filename normalization, correct channel label, profile match)
- 30 random databank points (grounded, concise, no cross-profile contamination)

2. Workflow verification
- Profile chat updates against imported profiles
- Network Lab profile review for top strategic contacts
- M365 mailbox/calendar matching accuracy spot-check

3. Sign-off update
- Mark `post_data_status` in `docs/system_feature_routes.csv`
- Update `Status` in `docs/system_feature_validation_matrix.csv` to `PASS_POST_DATA` when complete
