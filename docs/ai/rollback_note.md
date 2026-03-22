# AI Rollback Note

## Rollback principle

This phase was designed to be additive and compatibility-safe. Rollback should prefer code rollback plus database restore over ad hoc manual deletions.

## Before deployment

- take a full database backup
- copy the uploads directory

## If deployment must be rolled back

1. Stop the app.
2. Revert to the previous application build.
3. Restore the pre-deploy database backup.
4. Restore uploads if artifact/media paths changed during the failed deployment window.
5. Restart the previous version.

## Why restore is preferred

- new columns are added in place
- new AI rows may be created after deployment
- a code-only rollback without data restore can leave the older code unaware of newer AI metadata

## Partial rollback option

If a full restore is not acceptable, the older CRM should still function because the changes are additive, but the following new capabilities will be ignored by older code:

- `AI_RUN_LOG`
- richer `AI_ARTIFACT` metadata
- richer `AI_SIGNAL` scoring/review fields
- stale-brief fields on `AI_BRIEF`
- enriched `AI_FEEDBACK` columns
