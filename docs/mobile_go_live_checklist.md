# Mobile Go-Live Checklist

## 1. Production `.env`

Use these production-safe values as the baseline:

```env
ENV=production
HOST=0.0.0.0
PORT=8009

DB_PATH=./crm.db

SECRET_KEY=<generate-a-new-64-char-secret>
TOKEN_EXPIRE_MINUTES=1440
AUTH_DISABLED=false
COOKIE_SECURE=true
API_DOCS_ENABLED=false

OPENAI_API_KEY=<new-rotated-key>
GEMINI_API_KEY=

M365_ENABLED=true
M365_CLIENT_ID=<production-client-id>
M365_TENANT_ID=<tenant-id>
M365_CLIENT_SECRET=<production-client-secret>
M365_SYNC_INTERVAL_SECONDS=300

UPLOADS_DIR=./uploads
MAX_UPLOAD_MB=50

BACKUP_DIR=./backups
BACKUP_EXTERNAL_DIR=./backups_external
BACKUP_RETENTION_DAILY=7
BACKUP_RETENTION_WEEKLY=4
BACKUP_RETENTION_MONTHLY=3

ALLOWED_ORIGINS=https://your-domain.com,https://www.your-domain.com
STANDALONE_TOOL_API_KEY=<optional-toolkit-key-or-blank>
STANDALONE_TOOL_MODEL=gpt-4o
```

Generate a new secret with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

## 2. Secret Rotation

- Rotate the OpenAI key currently used by the app.
- Update `OPENAI_API_KEY` in production only after rotation.
- If Microsoft 365 is enabled, confirm the app registration secret is current.
- If the standalone toolkit is needed, set a fresh `STANDALONE_TOOL_API_KEY`.
- Never reuse the current placeholder `SECRET_KEY`.

## 3. Pre-Launch Data Checks

- Confirm `AUTH_DISABLED=false` in the live environment.
- Confirm `API_DOCS_ENABLED=false` in the live environment.
- Confirm test/demo data has been removed from `crm.db`.
- Confirm no `@example.com` contacts remain unless intentionally retained.
- Confirm uploads do not contain leftover test artifacts.

## 4. Release Verification

Run these before launch:

```powershell
python -m pytest -q
python tests\ui_full_audit_selenium.py
```

Manual checks:

- Open `/login` and verify login works with a real admin account.
- Open `/` while logged out and confirm redirect to `/login`.
- Confirm `/api/people` returns `401` when logged out.
- Confirm `/api/proxy/image?...` returns `401` when logged out.
- Confirm `/api/toolkit/health` returns `401` when logged out unless authenticated or using a valid toolkit key.
- Confirm main pages load on a phone-sized viewport: dashboard, profile, agenda, analytics, events, settings.

## 5. Mobile UX Smoke Test

- Dashboard cards fit without horizontal scroll.
- Search and filter chips remain tappable on small screens.
- Profile header actions wrap cleanly on mobile.
- Task modal opens and closes without layout jumping.
- Twin chat opens, scrolls, and closes correctly on mobile.
- Event and analytics pages do not pin content off-screen.

## 6. Operational Readiness

- Confirm backups are writing to both local and external backup locations.
- Confirm restart procedure is documented.
- Confirm one admin user exists before launch.
- Confirm logs do not expose raw tracebacks or secrets in normal flows.
- Confirm HTTPS is enabled at the deployment layer before relying on `COOKIE_SECURE=true`.

## 7. Go / No-Go

Go only if all are true:

- Auth is enabled.
- Secrets are rotated.
- Docs are disabled.
- Tests pass.
- Mobile smoke test passes.
- Backup path is healthy.
