# Known Risks Note

## Still incomplete or intentionally deferred

- ambiguous profile matching is available as a suggestion API, but the full end-user confirmation workflow is not fully surfaced in the main UI yet
- conflict detection is still heuristic and currently reported through review-state/ops summaries rather than a dedicated conflict object model
- the CRM still carries legacy `TOPIC_INTELLIGENCE` alongside `AI_SIGNAL`; this is deliberate for migration safety, but it means the platform is still in a dual-read/write transition
- event import and CSV import ingestion are not yet full first-class artifact workflows
- the profile review modal is still a lightweight UI and not yet a complete analyst workbench
- M365 duplicate route debt and deprecation warnings remain outside this AI foundation phase

## Operational caution

- startup migrations are additive and safe, but they are still startup-driven rather than managed by a dedicated migration framework
- older environments that bypass normal app startup can miss new schema until `init_db()` is called
