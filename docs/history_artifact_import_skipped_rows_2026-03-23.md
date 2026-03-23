# History Import Skipped Rows (2026-03-23)

_Generated at 2026-03-23T02:06:52.735340+00:00_

## Summary

- Total skipped rows: **15**
- Skipped `INTERACTION` rows: **14**
- Skipped `TASK` rows: **1**
- Distinct missing parent people: **6**

## Missing Parent Person IDs
- `(blank person_id)`
- `1`
- `3d709f75-f43f-4f06-b761-6312b4ebd740`
- `632d631f-0605-455f-9a83-9fce293beb75`
- `74b127c5-0bea-4ddb-bc48-2ee369886a42`
- `edb545de-3e43-403d-8135-821dc26041a2`

- Full detail CSV: `C:\Users\marcu\OneDrive - TSA\Desktop\CODEX CRM v2\docs\history_artifact_import_skipped_rows_2026-03-23.csv`

## Sample Skipped Rows

| table | primary_id | person_id | reason | context |
| --- | --- | --- | --- | --- |
| INTERACTION | d32892f5-30c | 632d631f-0605-455f-9a83-9fce293beb75 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 18:48:09; summary=Manual Update: Company Name Raw set to 'Google Deepmind'. |
| INTERACTION | 1129bfe2-8c9 | 632d631f-0605-455f-9a83-9fce293beb75 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 18:48:09; summary=Manual Update: Last Updated Datetime set to '2026-03-03T18:48:09.374722'. |
| INTERACTION | 20c263ae-2d58-4087-8b3b-4c06fc218c3b | 632d631f-0605-455f-9a83-9fce293beb75 | missing_parent_person | channel=Email; interaction_at=2026-03-03T18:48:09.401888; summary=Had a test sync today. Agreed to buy standard license. |
| INTERACTION | a165c55c-465 | 74b127c5-0bea-4ddb-bc48-2ee369886a42 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 18:52:50; summary=Manual Update: Company Name Raw set to 'Google Deepmind'. |
| INTERACTION | 56b65e65-d4f | 74b127c5-0bea-4ddb-bc48-2ee369886a42 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 18:52:50; summary=Manual Update: Last Updated Datetime set to '2026-03-03T18:52:50.399839'. |
| INTERACTION | 742388f6-2486-4da6-9d48-6b848a1e3e04 | 74b127c5-0bea-4ddb-bc48-2ee369886a42 | missing_parent_person | channel=Email; interaction_at=2026-03-03T18:52:50.435439; summary=Had a test sync today. Agreed to buy standard license. |
| INTERACTION | 310d40d7-597 | edb545de-3e43-403d-8135-821dc26041a2 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 18:54:11; summary=Manual Update: Company Name Raw set to 'Google Deepmind'. |
| INTERACTION | a1a95f4c-02c | edb545de-3e43-403d-8135-821dc26041a2 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 18:54:11; summary=Manual Update: Last Updated Datetime set to '2026-03-03T18:54:11.726606'. |
| INTERACTION | 2d1f3d66-db3d-418b-9f7d-7ecd6f90576b | edb545de-3e43-403d-8135-821dc26041a2 | missing_parent_person | channel=Email; interaction_at=2026-03-03T18:54:11.766989; summary=Had a test sync today. Agreed to buy standard license. |
| INTERACTION | aa2836a3-94c | 3d709f75-f43f-4f06-b761-6312b4ebd740 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 19:25:54; summary=Manual Update: Company Name Raw set to 'Google Deepmind'. |
| INTERACTION | 6f11f5ee-e26 | 3d709f75-f43f-4f06-b761-6312b4ebd740 | missing_parent_person | channel=system_audit; interaction_at=2026-03-03 19:25:54; summary=Manual Update: Last Updated Datetime set to '2026-03-03T19:25:54.077698'. |
| INTERACTION | d11c598f-d7f5-42ba-b5a5-d282f24e3ac4 | 3d709f75-f43f-4f06-b761-6312b4ebd740 | missing_parent_person | channel=Email; interaction_at=2026-03-03T19:25:54.121361; summary=Had a test sync today. Agreed to buy standard license. |
| INTERACTION | 446f573c-752 | 3d709f75-f43f-4f06-b761-6312b4ebd740 | missing_parent_person | channel=chat; interaction_at=2026-03-03 19:25:56; summary=Write a quick test message. |
| INTERACTION | e72869ee-dd8 | 1 | missing_parent_person | channel=system_audit; interaction_at=2026-03-04 11:15:23; summary=Manual Update: Cat set to 'OBE M, TGT'. |
| TASK | d05be2ee-9875-4a76-8b68-e9d02bcd3693 | (blank) | missing_parent_person | due_date=2026-03-11; status=open; task_text=follow up with Steve Flint tomorrow |