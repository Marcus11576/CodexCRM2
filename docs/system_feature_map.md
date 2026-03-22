# System Feature Map

_Generated from application routes on 2026-03-22 10:16:55Z UTC._

Regenerate with: `./.venv/Scripts/python.exe scripts/generate_feature_map.py`

## Coverage Snapshot

- Total routes: **177**
- API routes: **146**
- UI/static routes and mounts: **31**
- Frontend HTML pages: **13**
- Frontend JS modules: **22**

## Route Counts By Area

| Area | Route Count |
| --- | --- |
| Network Lab | 25 |
| People & Profiles | 17 |
| Events | 16 |
| AI Pipeline | 12 |
| Core UI | 12 |
| Intelligence Assistant | 11 |
| Microsoft 365 | 9 |
| Network Lab UI | 8 |
| Authentication | 7 |
| Analytics | 6 |
| Interaction Capture | 6 |
| Health & Operations | 5 |
| Profile UI | 5 |
| System Settings | 5 |
| Tasks | 5 |
| Taxonomy | 5 |
| V2 APIs (analytics) | 5 |
| Authentication UI | 3 |
| Configuration | 3 |
| Dashboard Compatibility | 3 |
| Frontend Assets | 2 |
| Toolkit | 2 |
| General API (proxy) | 1 |
| Legacy Twin | 1 |
| Network Queues | 1 |
| Uploads | 1 |
| V2 APIs (intelligence) | 1 |

## UI Surface Map

| Page | Purpose |
| --- | --- |
| activities.html | Activities |
| agenda.html | Agenda |
| analytics.html | Analytics |
| events.html | Events |
| index.html | Main UI |
| login.html | Authentication |
| network-lab-databank.html | Network Lab workspace |
| network-lab-profile.html | Network Lab workspace |
| network-lab-review.html | Network Lab workspace |
| network-lab.html | Network Lab workspace |
| profile-layout-options.html | Main UI |
| profile.html | Profile workspace |
| settings.html | Settings |

## Frontend Module Map

| JavaScript Module | Domain |
| --- | --- |
| frontend/js/activities.js | Activities |
| frontend/js/agenda.js | Agenda |
| frontend/js/analytics.js | Analytics |
| frontend/js/background.js | General |
| frontend/js/events.js | Events |
| frontend/js/index.js | General |
| frontend/js/network-lab-databank.js | Network Lab |
| frontend/js/network-lab-profile-review.js | Network Lab |
| frontend/js/network-lab-profile.js | Network Lab |
| frontend/js/network-lab-review.js | Network Lab |
| frontend/js/network-lab.js | Network Lab |
| frontend/js/plugins/PluginManager.js | General |
| frontend/js/plugins/StrategistPlugin.js | General |
| frontend/js/profile.js | General |
| frontend/js/profile/briefing.js | Profile |
| frontend/js/profile/core.js | Profile |
| frontend/js/profile/header.js | Profile |
| frontend/js/profile/interactions.js | Profile |
| frontend/js/profile/relationships.js | Profile |
| frontend/js/profile/signals.js | Profile |
| frontend/js/profile/workflow.js | Profile |
| frontend/js/settings.js | Settings |

## Deployment + Post-Data Validation Matrix

| Feature Area | Pre-Deploy Check | Post-Data Check | Owner | Status |
| --- | --- | --- | --- | --- |
| Authentication | Login, session cookie, logout | Role-based access still enforced with real users | TBD | Pending |
| People & Profile | Create/update person, profile load, profile widgets | Data completeness, profile photos, relationship signals render correctly | TBD | Pending |
| Interaction Capture | Text/image/pdf upload via chat, interaction create/edit/delete | Bulk imported history lands on correct profiles with no mojibake | TBD | Pending |
| Intelligence Assistant | Profile chat response, brief endpoint, TTS/transcription queues | Claims, stages, and updates remain grounded after full data ingestion | TBD | Pending |
| AI Pipeline | Artifacts/signals CRUD, review queue, status patching | Signal quality, dedupe behavior, inclusion/exclusion in briefs | TBD | Pending |
| Network Lab | Databank/review/profile pages load, refresh + tagging actions work | Databank has grounded non-noisy points and no profile cross-contamination | TBD | Pending |
| Dashboard & Analytics | Dashboard queues, analytics endpoints, category trends | Scores and trend distributions look realistic with full dataset | TBD | Pending |
| Events | CRUD + participant linking + export | Event relevance and participant states stay consistent at scale | TBD | Pending |
| Tasks | Task CRUD + pipeline endpoint | Follow-up pressure and due-state logic remains correct after import | TBD | Pending |
| M365 | Auth status/start/reset, mail fetch, calendar fetch, full sync | Mailbox/calendar matching accuracy and meeting metadata integrity | TBD | Pending |
| System Settings | Intelligence + runtime settings read/write/reset | No config drift after deploy restart | TBD | Pending |
| Health & Operations | Health endpoint + backup status/run | Nightly jobs, backups, and workers stable for 24h | TBD | Pending |

## Release Checklist

- [ ] Run backend tests: `./.venv/Scripts/python.exe -m pytest -q tests`
- [ ] Run browser smoke audit: `./.venv/Scripts/python.exe tests/ui_full_audit_selenium.py`
- [ ] Run profile upload/chat flow: `./.venv/Scripts/python.exe tests/ui_profile_chat_upload_selenium.py`
- [ ] Verify `GET /api/health` returns `200`
- [ ] Validate top 20 strategic profiles in Network Lab for stage/queue sanity
- [ ] Validate random sample of 30 imported artifacts for filename/channel correctness
- [ ] Validate random sample of 30 databank points for grounding and no cross-profile leakage

## Full Route Inventory

| Methods | Path | Area | Handler |
| --- | --- | --- | --- |
| GET | / | Authentication UI | serve_index |
| GET | /activities | Core UI | serve_activities |
| GET | /activities.html | Core UI | serve_activities |
| GET | /agenda | Core UI | serve_agenda |
| GET | /agenda.html | Core UI | serve_agenda |
| GET | /analytics | Core UI | serve_analytics |
| GET | /analytics.html | Core UI | serve_analytics |
| POST | /api/ai/artifacts | AI Pipeline | create_artifact |
| POST | /api/ai/briefs/{person_id} | AI Pipeline | store_brief |
| POST | /api/ai/feedback | AI Pipeline | log_feedback |
| GET | /api/ai/jobs/person/{person_id} | AI Pipeline | list_person_ai_jobs |
| GET | /api/ai/jobs/{job_id} | AI Pipeline | get_ai_job |
| POST | /api/ai/jobs/{job_id}/retry | AI Pipeline | retry_ai_job |
| GET | /api/ai/ops/summary | AI Pipeline | ops_summary |
| POST | /api/ai/profile-match/suggest | AI Pipeline | suggest_profile_match |
| GET | /api/ai/review-queue | AI Pipeline | review_queue |
| POST | /api/ai/signals | AI Pipeline | create_signal |
| GET | /api/ai/signals/{person_id} | AI Pipeline | get_signals |
| PATCH | /api/ai/signals/{signal_id}/status | AI Pipeline | update_signal_status |
| GET | /api/analytics/effort-stats | Analytics | get_effort_stats |
| GET | /api/analytics/influence-matrix | Analytics | get_influence_matrix |
| GET | /api/analytics/network-pulse | Analytics | get_network_pulse |
| GET | /api/analytics/profile-growth-stats | Analytics | get_profile_growth_stats |
| GET | /api/analytics/propensity/{person_id} | Analytics | get_person_propensity |
| GET | /api/analytics/success-report | Analytics | get_success_report |
| POST | /api/auth/login | Authentication | login |
| POST | /api/auth/logout | Authentication | logout |
| GET | /api/auth/me | Authentication | get_me |
| GET | /api/auth/microsoft/callback | Authentication | microsoft_callback |
| GET | /api/auth/microsoft/start | Authentication | microsoft_start |
| POST | /api/auth/setup | Authentication | setup_first_admin |
| GET | /api/auth/status | Authentication | auth_status |
| GET | /api/config/ai | Configuration | get_ai_config |
| POST | /api/config/ai | Configuration | update_ai_config |
| GET | /api/config/taxonomy | Configuration | compat_taxonomy |
| GET | /api/dashboard/meeting-feed | Dashboard Compatibility | compat_meeting_feed |
| GET | /api/dashboard/network-feed | Dashboard Compatibility | compat_network_feed |
| GET | /api/dashboard/task-pipeline | Dashboard Compatibility | compat_task_pipeline |
| GET | /api/events | Events | list_events |
| POST | /api/events | Events | create_event |
| GET | /api/events/dashboard/summary | Events | get_event_dashboard_summary |
| GET | /api/events/people/{person_id}/links | Events | get_person_events |
| POST | /api/events/people/{person_id}/links | Events | link_event_to_person |
| DELETE | /api/events/people/{person_id}/links/{event_id} | Events | remove_event_from_person |
| PATCH | /api/events/people/{person_id}/links/{event_id} | Events | update_person_event_link |
| GET | /api/events/status-options | Events | get_event_status_options |
| GET | /api/events/{event_id} | Events | get_event |
| PATCH | /api/events/{event_id} | Events | update_event |
| PUT | /api/events/{event_id} | Events | update_event |
| GET | /api/events/{event_id}/participants/export | Events | export_event_participants |
| GET | /api/events/{event_id}/people | Events | get_event_people |
| POST | /api/events/{event_id}/people | Events | add_person_to_event |
| DELETE | /api/events/{event_id}/people/{person_id} | Events | remove_person_from_event |
| PATCH | /api/events/{event_id}/people/{person_id} | Events | update_event_person_status |
| GET | /api/health | Health & Operations | health_check_public |
| POST | /api/health/backups/run | Health & Operations | run_backup_now |
| GET | /api/health/backups/status | Health & Operations | get_backup_status |
| GET | /api/health/status | Health & Operations | get_health_status |
| POST | /api/health/trigger | Health & Operations | trigger_full_audit |
| POST | /api/intelligence/assistant/{person_id}/review | Intelligence Assistant | intelligence_review |
| POST | /api/intelligence/backfill/{person_id} | Intelligence Assistant | admin_backfill_person |
| GET | /api/intelligence/brief/{person_id} | Intelligence Assistant | get_brief |
| POST | /api/intelligence/brief/{person_id} | Intelligence Assistant | get_brief |
| POST | /api/intelligence/chat/{person_id} | Intelligence Assistant | chat_with_profile |
| GET | /api/intelligence/jobs/{job_id} | Intelligence Assistant | get_intelligence_job |
| POST | /api/intelligence/transcribe | Intelligence Assistant | transcribe |
| POST | /api/intelligence/tts/{person_id} | Intelligence Assistant | generate_audio_brief |
| POST | /api/intelligence/twin/chat | Intelligence Assistant | compat_twin_chat |
| POST | /api/intelligence/twin/execute | Intelligence Assistant | compat_twin_execute |
| POST | /api/intelligence/whatsapp-import | Intelligence Assistant | import_whatsapp |
| POST | /api/interactions | Interaction Capture | create_interaction |
| POST | /api/interactions/upload/{person_id} | Interaction Capture | upload_media |
| DELETE | /api/interactions/{interaction_id} | Interaction Capture | delete_interaction |
| PUT | /api/interactions/{interaction_id} | Interaction Capture | update_interaction |
| POST | /api/interactions/{interaction_id}/realign | Interaction Capture | realign_interaction_api |
| PUT | /api/interactions/{interaction_id}/stage-override | Interaction Capture | update_interaction_stage_override |
| GET | /api/m365/account/{person_id} | Microsoft 365 | account_status |
| POST | /api/m365/auth/reset | Microsoft 365 | auth_reset |
| POST | /api/m365/auth/start | Microsoft 365 | auth_start |
| GET | /api/m365/auth/status | Microsoft 365 | auth_status |
| GET | /api/m365/calendar/events | Microsoft 365 | calendar_events |
| GET | /api/m365/emails/{person_id} | Microsoft 365 | fetch_emails |
| POST | /api/m365/emails/{person_id}/send | Microsoft 365 | send_email |
| GET | /api/m365/overview | Microsoft 365 | m365_overview |
| POST | /api/m365/sync/full | Microsoft 365 | full_sync |
| POST | /api/network-lab/bulk-update | Network Lab | bulk_update_people |
| GET | /api/network-lab/company-opportunities | Network Lab | list_company_opportunities |
| POST | /api/network-lab/company-opportunities | Network Lab | create_company_opportunity |
| DELETE | /api/network-lab/company-opportunities/{company_opportunity_id} | Network Lab | delete_company_opportunity |
| PATCH | /api/network-lab/company-opportunities/{company_opportunity_id} | Network Lab | update_company_opportunity |
| PUT | /api/network-lab/company-opportunities/{company_opportunity_id} | Network Lab | update_company_opportunity |
| GET | /api/network-lab/databank | Network Lab | get_network_databank |
| POST | /api/network-lab/interpretations/{interpretation_id}/promote-market-intel | Network Lab | promote_market_intel |
| POST | /api/network-lab/interpretations/{interpretation_id}/promote-memory | Network Lab | promote_memory |
| POST | /api/network-lab/market-intel/{market_intel_id}/status | Network Lab | set_market_intel_status |
| POST | /api/network-lab/memory/{memory_id}/status | Network Lab | set_memory_status |
| GET | /api/network-lab/owners | Network Lab | list_owners |
| POST | /api/network-lab/pilot-cohort | Network Lab | set_pilot_cohort |
| GET | /api/network-lab/profile/{person_id} | Network Lab | get_network_profile |
| POST | /api/network-lab/profile/{person_id}/actions/update | Network Lab | update_action_status |
| POST | /api/network-lab/profile/{person_id}/claims/action | Network Lab | apply_claim_action |
| POST | /api/network-lab/profile/{person_id}/manual-resolution | Network Lab | add_manual_resolution |
| GET | /api/network-lab/profile/{person_id}/relationship-intelligence | Network Lab | get_profile_relationship_intelligence |
| POST | /api/network-lab/profile/{person_id}/relationship-intelligence/refresh | Network Lab | refresh_profile_relationship_intelligence |
| POST | /api/network-lab/profile/{person_id}/transcript-segment-tags | Network Lab | tag_profile_transcript_segments |
| POST | /api/network-lab/profile/{person_id}/transcript-segment-tags/override | Network Lab | set_profile_transcript_segment_override |
| GET | /api/network-lab/review-queue | Network Lab | get_review_queue |
| DELETE | /api/network-lab/situation-events/{event_id} | Network Lab | delete_situation_event |
| PUT | /api/network-lab/situation-events/{event_id} | Network Lab | update_situation_event |
| GET | /api/network-lab/workspace | Network Lab | get_workspace |
| GET | /api/network/queues | Network Queues | list_network_queues |
| GET | /api/people | People & Profiles | list_people |
| POST | /api/people | People & Profiles | create_person |
| GET | /api/people/stats | People & Profiles | get_stats |
| DELETE | /api/people/{person_id} | People & Profiles | deactivate_person |
| GET | /api/people/{person_id} | People & Profiles | get_person |
| PATCH | /api/people/{person_id} | People & Profiles | update_person |
| PUT | /api/people/{person_id} | People & Profiles | update_person |
| GET | /api/people/{person_id}/intelligence | People & Profiles | get_intelligence |
| PATCH | /api/people/{person_id}/intelligence/{intel_id} | People & Profiles | update_intelligence |
| POST | /api/people/{person_id}/media | People & Profiles | compat_upload_photo |
| POST | /api/people/{person_id}/meeting-brief | People & Profiles | compat_meeting_brief |
| GET | /api/people/{person_id}/opportunities | People & Profiles | list_opportunities |
| POST | /api/people/{person_id}/opportunities | People & Profiles | create_opportunity |
| DELETE | /api/people/{person_id}/opportunities/{opportunity_id} | People & Profiles | delete_opportunity |
| PATCH | /api/people/{person_id}/opportunities/{opportunity_id} | People & Profiles | update_opportunity |
| PUT | /api/people/{person_id}/opportunities/{opportunity_id} | People & Profiles | update_opportunity |
| GET | /api/people/{person_id}/relationships | People & Profiles | get_person_relationships |
| GET | /api/proxy/image | General API (proxy) | proxy_image |
| GET | /api/settings/intelligence | System Settings | get_intelligence_settings_endpoint |
| PUT | /api/settings/intelligence | System Settings | save_intelligence_settings_endpoint |
| POST | /api/settings/intelligence/reset | System Settings | reset_intelligence_settings_endpoint |
| GET | /api/settings/runtime | System Settings | get_runtime_settings_endpoint |
| PUT | /api/settings/runtime/openai-key | System Settings | save_openai_key_endpoint |
| GET | /api/tasks | Tasks | list_tasks |
| POST | /api/tasks | Tasks | create_task |
| GET | /api/tasks/pipeline | Tasks | get_pipeline |
| DELETE | /api/tasks/{task_id} | Tasks | delete_task |
| PATCH | /api/tasks/{task_id} | Tasks | update_task |
| GET | /api/taxonomy | Taxonomy | get_taxonomy |
| POST | /api/taxonomy | Taxonomy | add_taxonomy |
| GET | /api/taxonomy/all | Taxonomy | get_all_taxonomy |
| DELETE | /api/taxonomy/{config_id} | Taxonomy | deactivate_taxonomy |
| PUT | /api/taxonomy/{config_id} | Taxonomy | update_taxonomy |
| GET | /api/toolkit/health | Toolkit | toolkit_health |
| POST | /api/toolkit/transcripts/summarize | Toolkit | summarize_transcript |
| POST | /api/twin/upload_pdf | Legacy Twin | twin_upload_pdf |
| GET | /api/v2/analytics/categories | V2 APIs (analytics) | get_categories |
| GET | /api/v2/analytics/category-sentiment | V2 APIs (analytics) | get_category_sentiment_compat |
| GET | /api/v2/analytics/category-trends | V2 APIs (analytics) | get_category_trends |
| GET | /api/v2/analytics/momentum | V2 APIs (analytics) | get_momentum |
| GET | /api/v2/analytics/recent-intel | V2 APIs (analytics) | get_recent_intel |
| POST | /api/v2/intelligence/synthesize/{person_id} | V2 APIs (intelligence) | run_synthesis |
| GET | /events | Core UI | serve_events |
| GET | /events.html | Core UI | serve_events |
| GET | /events/{event_id} | Core UI | serve_events |
| GET | /favicon.ico | Core UI | serve_favicon |
| - | /js | Frontend Assets | js |
| GET | /login | Authentication UI | serve_login |
| GET | /login.html | Authentication UI | serve_login |
| GET | /network-lab | Network Lab UI | serve_network_lab |
| GET | /network-lab-databank.html | Network Lab UI | serve_network_lab_databank |
| GET | /network-lab-profile.html | Network Lab UI | serve_network_lab_profile |
| GET | /network-lab-review.html | Network Lab UI | serve_network_lab_review |
| GET | /network-lab.html | Network Lab UI | serve_network_lab |
| GET | /network-lab/databank | Network Lab UI | serve_network_lab_databank |
| GET | /network-lab/profile/{person_id} | Network Lab UI | serve_network_lab_profile |
| GET | /network-lab/review | Network Lab UI | serve_network_lab_review |
| GET | /person/{person_id} | Profile UI | serve_profile |
| GET | /profile | Profile UI | serve_profile |
| GET | /profile-layout-options | Profile UI | serve_profile_layout_options |
| GET | /profile-layout-options.html | Profile UI | serve_profile_layout_options |
| GET | /profile.html | Profile UI | serve_profile |
| GET | /settings | Core UI | serve_settings |
| GET | /settings.html | Core UI | serve_settings |
| - | /static | Frontend Assets | static |
| GET | /uploads/{path:path} | Uploads | protected_uploads |
