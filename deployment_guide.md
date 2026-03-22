# Deployment Guide

## Current deployment target
- Recommended first host: Render
- Runtime shape: single FastAPI web service with background workers in-process
- Persistence requirement: mounted disk for SQLite, uploads, and backups

## Included deployment files
- `Dockerfile`
- `Procfile`
- `render.yaml`
- `.env.example`

## Required production environment values
- `SECRET_KEY`
- `OPENAI_API_KEY` if AI features should run live
- `AUTH_DISABLED=false`
- `COOKIE_SECURE=true`
- Optional M365 secrets if mailbox sync is needed

## Production storage paths
- `DB_PATH=/var/data/crm.db`
- `UPLOADS_DIR=/var/data/uploads`
- `BACKUP_DIR=/var/data/backups`
- `BACKUP_EXTERNAL_DIR=/var/data/backups_external`

## Important rollout notes
- This deployment is intended for a single running web instance while SQLite remains the database.
- Do not scale horizontally with SQLite background jobs.
- Move to Postgres before multi-instance deployment or heavier AI concurrency.
- Serve the app over `https://` in production. Microphone capture on Android/tablet browsers will be blocked on insecure origins.
- Verify `OPENAI_API_KEY` before enabling voice transcription, AI chat, and generated meeting audio.
- Use `/api/health/status` after deploy to confirm the new `deployment_checks` values before opening the system to users.

## Render steps
1. Push this repo to GitHub.
2. Create a new Render Blueprint or Web Service from the repo.
3. Attach the persistent disk defined in `render.yaml`.
4. Set `SECRET_KEY` and any AI/M365 keys.
5. Confirm `AUTH_DISABLED=false` before public access.
6. Confirm the public URL is HTTPS and that secure cookies are being set.
7. Deploy and run first-time admin setup from `/login` if no users exist.
8. Check `/api/health/status` and `/api/health/backups/status` after first boot.
