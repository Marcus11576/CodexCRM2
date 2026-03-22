# Self-Check And Recovery Note

## Current self-checks

- `backend/services/health_service.py::run_integrity_audit`
  - repairs legacy labels
  - removes orphaned legacy intelligence rows
  - normalizes event statuses
  - requeues stale running jobs
  - flags processed artifacts with empty extraction as `needs_review`
- `backend/services/ai_pipeline_service.py::get_operations_summary`
  - failed jobs
  - stuck jobs
  - retry volume
  - duplicate rate
  - relink rate
  - correction rate
  - extraction success rate
  - average AI latency by task
- `backend/services/ai_pipeline_service.py::get_review_queue`
  - artifacts requiring review
  - signals pending review

## Recovery behaviours

- failed artifacts stay preserved for retry
- failed jobs remain retryable
- stale briefs are invalidated automatically when signals change
- duplicate artifacts are retained and marked rather than silently dropped

## Important limitation

This phase improves detection, retry, and recovery behaviour, but it does not yet implement a full dead-letter dashboard UI.
