# AI Deployment Note

This environment was used to implement and verify the AI foundation locally. No remote deployment was executed from this workspace.

## Environment variables

Required for AI:

- `OPENAI_API_KEY`

Core app variables:

- `DB_PATH`
- `UPLOADS_DIR`
- `AUTH_DISABLED`
- `HOST`
- `PORT`

Optional:

- `M365_ENABLED`
- `M365_CLIENT_ID`
- `M365_TENANT_ID`
- `M365_CLIENT_SECRET`

## Safe deployment order

1. Back up the database and uploads.
2. Deploy code.
3. Start the app once so `backend/database.py::init_db()` applies the additive schema migration.
4. Verify the app starts and background workers initialize.
5. Verify AI endpoints and event CSV export.

## Commands

```powershell
python -m pytest -q
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8009
```

## Post-deploy verification

- open the CRM and create a manual note
- confirm an `AI_ARTIFACT` row is created
- confirm a signal extraction job appears
- upload an image that is clearly a headshot and verify the profile photo is not replaced automatically
- generate a brief and confirm it returns after background processing
- export event participants from an event detail page and verify CSV columns

## Migration style

- additive only
- startup-driven via `init_db()`
- no destructive schema rewrite was introduced in this phase
