# Post-Data Validation Execution (2026-03-23)

_Generated at 2026-03-23T02:02:02.992914+00:00_

## API Smoke
- /api/health: 200 (payload bytes: 33)
- /api/people: 200 (payload bytes: 333524)
- /api/network-lab/databank: 200 (payload bytes: 405586)
- /api/dashboard/network-feed: 200 (payload bytes: 1433604)

## Data Volume After Import
- PERSON: **294**
- INTERACTION: **1961**
- TOPIC_INTELLIGENCE: **634**
- AI_ARTIFACT: **76**
- AI_SIGNAL: **14**
- AI_BRIEF: **101**
- INTERPRETED_INTERACTION: **213**
- REL_INTEL_RUN: **239**

## Sample Quality Checks
- Sampled artifacts: 30 | potential mojibake filenames: 0
- Sampled interpreted interactions: 30
- Empty `what_is_happening` in sample: 2
- Empty `why_it_matters` in sample: 0
- Noise/profanity hits in sample: 0
- Cross-profile name leakage heuristic hits: 0

## Verdict
- Post-data validation status: **PASS (local)**
