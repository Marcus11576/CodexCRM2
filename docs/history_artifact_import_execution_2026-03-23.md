# History + Artifact Import Execution (2026-03-23)

- Source DB: `C:\Users\marcu\OneDrive - TSA\Desktop\CODEX CRM v2\backups\pre_chatbot_reset_20260318T091210Z.db`
- Target DB: `C:\Users\marcu\OneDrive - TSA\Desktop\CODEX CRM v2\crm.db`
- Mode: `insert_only_by_primary_key_fk_safe` (no updates or deletes)

## Table Results

| Table | Old Count | Eligible | Before | Inserted | After | Status |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| INTERACTION | 1918 | 1904 | 51 | 1904 | 1955 | imported |
| INTERPRETED_INTERACTION | 204 | 204 | 3 | 204 | 207 | imported |
| TOPIC_INTELLIGENCE | 629 | 629 | 5 | 629 | 634 | imported |
| TASK | 38 | 37 | 0 | 37 | 37 | imported |
| AI_ARTIFACT | 44 | 44 | 28 | 44 | 72 | imported |
| AI_SIGNAL | 11 | 11 | 3 | 11 | 14 | imported |
| AI_BRIEF | 93 | 93 | 8 | 93 | 101 | imported |
| REL_INTEL_RUN | 85 | 85 | 145 | 85 | 230 | imported |
| REL_INTEL_AGENT_OUTPUT | 643 | 643 | 1104 | 643 | 1747 | imported |

- Total inserted rows across selected tables: **3650**
- Detailed CSV: `C:\Users\marcu\OneDrive - TSA\Desktop\CODEX CRM v2\docs\history_artifact_import_changes_2026-03-23.csv`
- Executed at: `2026-03-23T01:53:22.577301+00:00`