# Pilot Instance Risk Assessment

## Goal
Run a fully isolated pilot CRM on a separate port with a trimmed contact set, while keeping the live CRM intact and operational.

## Main Risks And Mitigations

### 1. Session crossover between live and pilot
- Risk: browser cookies are shared by domain, not port, so the live and pilot apps could silently reuse the same auth cookie.
- Mitigation: the pilot uses its own `SESSION_COOKIE_NAME` and its own `SECRET_KEY`.

### 2. Pilot writes leaking into live data
- Risk: a filtered view on the main database would still allow writes back into the live CRM.
- Mitigation: the pilot runs against a separate database file created by `scripts/provision_pilot_instance.py`.

### 3. Accidental mutation of the source database during provisioning
- Risk: a bad pruning script could delete records from the live CRM instead of a copy.
- Mitigation: the provisioning script refuses to run when source and target paths resolve to the same file, clones first, and only prunes the cloned target.

### 4. Microsoft 365 side effects
- Risk: the pilot could sync email/calendar data or perform account actions against real M365 state.
- Mitigation: `start_pilot.bat` forces `M365_ENABLED=false` and the pilot database clears M365 account and credential tables.

### 5. Shared uploads or backups
- Risk: pilot-generated uploads, audio briefs, or backups could mix with the live app.
- Mitigation: the pilot uses its own `pilot/uploads`, `pilot/backups`, and `pilot/backups_external` directories.

### 6. Dirty operational queues or background jobs in the pilot
- Risk: cloned in-flight jobs or logs could trigger confusing behavior and waste AI budget.
- Mitigation: the provisioning script clears `AI_JOB`, `AI_RUN_LOG`, `AI_FEEDBACK`, and platform memory before the pilot starts.

### 7. Broken references after pruning
- Risk: trimming people without linked cleanup could leave orphaned events, opportunities, or AI records.
- Mitigation: the provisioning script prunes linked person data, linked company data, orphaned events, and then vacuums the database.

### 8. Misleading pilot conclusions
- Risk: using only the richest 50 contacts will make the model look cleaner than it may behave on sparse records.
- Mitigation: the pilot report records that the selection strategy is `top_populated_contacts`; sparse-contact validation should be a later pass, not inferred from this pilot.

## Operational Recommendation
- Use the pilot as a workflow and UX validation environment.
- Do not treat it as proof that weak-data contacts are solved.
- Rebuild the pilot database deliberately when you want a fresh snapshot of the live CRM.
