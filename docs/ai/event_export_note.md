# Event Export Note

## Endpoint

- `GET /api/events/{event_id}/participants/export`

## Query parameter

- `status_filter`
  - `all`
  - `Target`
  - `Invited`
  - `Confirmed`
  - `Registered`

## Output

CSV with exact default columns:

1. `Name`
2. `Company`
3. `Position`
4. `Mobile`
5. `Email`
6. `Event Status`

## UI

- event detail page now exposes an export filter and `Export CSV` action

## Notes

- event status input is normalized to the canonical status set
- export ordering is alphabetical by participant name
