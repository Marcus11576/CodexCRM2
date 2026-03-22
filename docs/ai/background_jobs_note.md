# Background Jobs Note

## Active job types

- `transcription`
- `signal_extraction`
- `brief_generation`

## Where jobs run

- `backend/services/ai_jobs.py`

## Safety behaviours

- queued/running/retrying states are durable in `AI_JOB`
- retry counts are stored
- dedupe keys prevent duplicate active jobs for the same artifact/profile path
- completed jobs write result payloads
- failed jobs remain visible and retryable

## Idempotency

- repeated signal extraction for the same artifact deletes and rewrites `AI_SIGNAL` rows for that artifact
- duplicate artifacts are marked `duplicate` and skipped instead of reprocessed
- brief generation is deduped per profile while a job is already active

## Recovery

- worker startup requeues jobs left in `running`
- health audit requeues jobs stuck in `running` too long
- artifact failures are preserved as failed states instead of hidden behind synthetic AI output
