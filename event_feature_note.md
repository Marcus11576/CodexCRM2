# Event Feature Note

## Tables
- `EVENT`: stores event name, location, date, topics, notes, and created/updated timestamps.
- `PERSON_EVENT`: stores the many-to-many person-to-event relationship, one status per link, and created/updated timestamps.

## Profile Flow
- Open a person profile.
- Use the `Event Tracking` section to link that person to an existing event.
- Update the link status inline from the profile or remove the link if it is no longer relevant.
- Jump directly from the profile into the full event detail view.

## Dashboard Flow
- The dashboard shows an `Upcoming Events` widget with the next events, linked-people totals, and confirmed/registered counts.
- Each card links into the dedicated event detail view for fast follow-up.

## Event Status Workflow
- Start with `Target` when the person is part of the event strategy.
- Move to `Invited` once outreach has happened.
- Move to `Confirmed` after attendance is verbally or directly confirmed.
- Move to `Registered` once the final registration step is complete.
- Status can be updated from either the event detail page or the person profile.
