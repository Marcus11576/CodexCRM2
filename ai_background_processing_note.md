# AI Background Processing Note

## How Job Status Works
- Every long AI task is stored in `AI_JOB` with a `job_type`, `status`, timestamps, payload, result, and error text.
- The main statuses are `queued`, `running`, `retrying`, `completed`, and `failed`.
- The UI reads job state from `/api/ai/jobs/{job_id}` or `/api/ai/jobs/person/{person_id}`.

## How Failed Jobs Are Retried
- Failed jobs stay visible in the profile `Background Jobs` panel.
- The retry button calls `POST /api/ai/jobs/{job_id}/retry`.
- Retry resets the job back into the queue and the background worker picks it up again using the original payload.

## How The UI Knows Processing Is Complete
- The profile page polls the person job list while any AI job is active.
- When no active jobs remain, the UI refreshes the person view, briefing, and related summaries.
- Standalone transcription polling checks the specific job endpoint until the job becomes `completed` or `failed`.
