# Antigravity CRM - Network Orchestration Rollout Spec

This document defines the rollout from a simple `meeting_status` / `overdue` model to a network orchestration model designed for 300+ active contacts.

The goal is not only to protect current opportunity, but also to preserve future optionality, internal and external influence, and long-tail relationship value.

## 1. Problem Statement

The current CRM is good at storing contacts and interactions, but weaker at managing relationship coverage across a large active network.

`overdue` remains useful as a narrow operational fact, but it is not sufficient as the main coordination model because it does not answer:

- who needs action now
- who must be maintained to protect strategic access
- who should be lightly preserved for future value
- who is at risk of being forgotten
- where opportunity could emerge indirectly through influence

The product should therefore move to a queue-led network management model with explicit coverage safeguards.

## 2. Live Data Test Summary

The proposed model was tested against the live `crm.db` and the current data supports a phased rollout.

### Current baseline

- Active people: `293`
- Total interactions: `1,912`
- People with `last_contact_datetime`: `276`
- People with an interaction-based recency signal: `196`
- People with `contact_value`: `170`
- People with `meeting_status`: `39`
- People with `next_contact_due_date`: `34`
- People with `next_meeting_date`: `3`
- People with `engagement_status`: `1`
- Tasks total: `35`
- Open or in-progress tasks: `30`

### Current risk

- People with no recency signal: `97`
- People with no future cover: `252`
- People effectively invisible to a score-only system: `96`

Definition of "invisible":

- no interaction recency
- no `last_success_at`
- no `next_contact_due_date`
- no `next_meeting_date`
- no open task

Conclusion:

- the platform is ready for a queue-based network model now
- the platform is not ready for a single health score to be the sole operating truth

## 3. Product Direction

The CRM should shift from a single follow-up mindset to a network orchestration mindset.

### Core concepts

- `network_tier`: how strategically important the person is
- `maintenance_mode`: how the relationship should be handled
- `coverage_state`: whether the relationship is protected or drifting
- `opportunity_state`: whether timing or motion makes action urgent

`meeting_status` remains in the system, but only as one operational signal among many.

## 4. Phase Plan

## Phase 1 - Queue-led rollout using current data

Goal:

- improve practical coverage now without waiting for a richer schema

No schema changes are required for initial release.

### Queues

- `Act Now`
- `Maintain`
- `Preserve`
- `Monitor`

### Phase 1 overlays

- `No Next Step`
- `No Relationship Signal`
- `Recently Reactivated`
- `Open Task Pressure`

### Phase 1 data inputs

Use existing fields only:

- `meeting_status`
- `next_contact_due_date`
- `next_meeting_date`
- open tasks
- `last_contact_datetime`
- `last_success_at`
- interaction recency from `INTERACTION`
- `cat`
- `contact_value`

### Phase 1 queue logic

#### `Act Now`

Place a person in `Act Now` if any of the following are true:

- `meeting_status = overdue`
- open task exists and due date is today or past
- no future cover and relationship appears beyond expected cadence
- `cat IN ('OBE M', 'OBE T', 'TGT')` and there is no next step
- new inbound or newly logged interaction appears after a dormant period

#### `Maintain`

Place a person in `Maintain` if:

- they are strategically relevant but not urgent
- they have recent activity but no explicit next step
- they are `Hot` or `Warm`
- they are `OBE M`, `OBE T`, `TGT`, or `EXT` and not already in `Act Now`

#### `Preserve`

Place a person in `Preserve` if:

- they have some history or relevance
- there is no current urgency
- they appear future-useful but do not justify active weekly management

#### `Monitor`

Place a person in `Monitor` if:

- there is no clear current engagement need
- the relationship should be retained for resurfacing on triggers
- data coverage is too thin to justify active cadence

`Monitor` is not a dead zone. It is a trigger-based resurfacing bucket.

### Phase 1 safety rules

Always surface regardless of score:

- any `OBE M`, `OBE T`, or `TGT` contact with no next step
- any contact with no recency signal and no future cover
- any contact with a new inbound interaction after dormancy
- any open task due or overdue

### Phase 1 expected result

- immediate visibility into who needs action
- reduced dependence on memory
- explicit identification of "invisible" contacts
- no requirement to trust incomplete health scoring

## Phase 2 - Schema and data enrichment

Goal:

- support true network tiering, influence tracking, and explainable health scoring

### `PERSON` additions

Add the following columns:

- `network_tier TEXT`
- `maintenance_mode TEXT`
- `relationship_owner TEXT`
- `decision_role TEXT`
- `influence_scope TEXT`
- `strategic_value_score INTEGER DEFAULT 50`
- `influence_score INTEGER DEFAULT 50`
- `future_option_score INTEGER DEFAULT 50`
- `coverage_risk_score INTEGER DEFAULT 50`
- `opportunity_readiness_score INTEGER DEFAULT 0`
- `relationship_confidence_score INTEGER DEFAULT 50`
- `last_meaningful_contact_at TEXT`
- `last_inbound_at TEXT`
- `last_outbound_at TEXT`
- `unanswered_outbound_count INTEGER DEFAULT 0`
- `reactivation_trigger_notes TEXT`
- `account_priority TEXT`
- `tier_rationale TEXT`
- `last_health_refresh_at TEXT`

### `INTERACTION` additions

Add the following columns:

- `direction TEXT`
- `meaningful_flag INTEGER DEFAULT 0`
- `outcome_type TEXT`
- `response_flag INTEGER DEFAULT 0`
- `follow_up_committed_flag INTEGER DEFAULT 0`

### New table: `PERSON_OPPORTUNITY`

Create a separate table to track live or latent opportunity context.

Suggested columns:

- `opportunity_id TEXT PRIMARY KEY`
- `person_id TEXT NOT NULL REFERENCES PERSON(person_id)`
- `account_name TEXT`
- `opportunity_type TEXT`
- `stage TEXT`
- `value_band TEXT`
- `trigger_date TEXT`
- `strategic_importance INTEGER DEFAULT 50`
- `status TEXT`
- `owner TEXT`
- `notes TEXT`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

### Phase 2 purpose

This phase makes it possible to distinguish:

- direct value from influence value
- current opportunity from future optionality
- weak relationship data from high-confidence relationship knowledge

## Phase 3 - Composite scoring and tiering

Goal:

- support explainable prioritization without hiding safeguards

### Network tiers

- `T1 Strategic Core`
- `T2 Active Opportunity`
- `T3 Strategic Network`
- `T4 Keep Warm`
- `T5 Monitor`

### Maintenance modes

- `work`
- `maintain`
- `preserve`
- `monitor`

### Score components

Do not rely on one opaque value. Compute:

- `coverage_health`
- `relationship_strength`
- `strategic_value`
- `opportunity_readiness`
- `confidence`

Then compute a derived `network_health_score`.

Suggested weights:

- Coverage Health: `30`
- Opportunity Readiness: `25`
- Strategic Value: `20`
- Relationship Strength: `15`
- Confidence: `10`

### Tiering principles

- live opportunity can lift a person to at least `T2`
- major influence can lift a person even if no current opportunity exists
- strategic value should decay slowly
- opportunity readiness can move quickly
- confidence should suppress false precision

### Scoring safeguards

No person should be considered "healthy" if:

- there is no meaningful recency signal
- there is no future cover
- the relationship is strategic and has no owner
- there is an active opportunity with no action path
- confidence in the underlying data is low

## Phase 4 - Learning model assist

Goal:

- use real platform outcomes to improve ranking inside queues

ML should not replace queues or safety rules.

### Required labels before ML

- meeting booked
- response received
- opportunity opened
- opportunity won or lost
- introduction made
- relationship reactivated
- outreach ignored or stalled

### ML role

Use ML to:

- rank within `Act Now`
- identify likely reactivation candidates
- identify likely opportunity emergence

Do not use ML to hide relationships from visibility.

## 5. Detailed Queue Definitions

These rules should exist server-side, not only in the browser.

## `Act Now`

Purpose:

- urgent relationships that require immediate action

Suggested conditions:

- `meeting_status = overdue`
- open task due within 3 days or already overdue
- `network_tier IN ('T1', 'T2')` and no next step
- `PERSON_OPPORTUNITY.trigger_date` within 30 days
- unanswered outbound streak >= 3
- recent inbound after long dormancy

## `Maintain`

Purpose:

- active, important relationships that need routine care

Suggested conditions:

- `network_tier IN ('T1', 'T3')`
- maintenance mode is `maintain`
- recent activity exists
- no immediate break in coverage

## `Preserve`

Purpose:

- retain long-tail optionality with low noise

Suggested conditions:

- `network_tier IN ('T3', 'T4')`
- maintenance mode is `preserve`
- no urgent opportunity, but still worth light upkeep

## `Monitor`

Purpose:

- retain visibility without forced touch cadence

Suggested conditions:

- `network_tier = 'T5'`
- maintenance mode is `monitor`
- resurface only on triggers or strategic review

## 6. Trigger Resurfacing Rules

The following should resurface `Preserve` and `Monitor` contacts:

- inbound message, email, or call
- new meeting logged
- job move or role change
- company/project relevance detected
- event registration or attendance
- mention or introduction from another contact
- opportunity created against the contact or account

## 7. Technical Implementation Plan

## Backend

### New service

Add a server-side service, for example:

- `backend/services/network_orchestration_service.py`

Responsibilities:

- compute queue membership
- compute score components
- compute derived health
- compute data confidence
- return explanation payloads for why the person is surfaced

### New endpoints

Suggested endpoints:

- `GET /api/network/queues`
- `GET /api/network/summary`
- `GET /api/network/person/{person_id}`
- `POST /api/network/recompute`

### Suggested response shape

```json
{
  "queues": {
    "act_now": [],
    "maintain": [],
    "preserve": [],
    "monitor": []
  },
  "overlays": {
    "no_next_step": [],
    "no_relationship_signal": [],
    "recently_reactivated": [],
    "open_task_pressure": []
  },
  "summary": {
    "act_now_count": 0,
    "maintain_count": 0,
    "preserve_count": 0,
    "monitor_count": 0,
    "invisible_count": 0
  }
}
```

### Computation order

1. Gather recency and future-cover inputs
2. Apply fail-safe overlays
3. Assign queue membership
4. Compute explanation text
5. Compute scores where enough confidence exists

## Frontend

### Dashboard changes

Replace meeting-status-first framing with queue-first framing.

Primary dashboard blocks:

- `Act Now`
- `Maintain This Week`
- `Preserve This Month`
- `Monitoring`

Secondary overlays:

- `No Next Step`
- `No Relationship Signal`
- `Recently Reactivated`

### Profile page changes

Show:

- current queue
- network tier
- maintenance mode
- coverage state
- why the person is surfaced
- next recommended action

## 8. Migration and Backfill Strategy

## Backfill v1 proxies

Before richer data exists:

- set `last_meaningful_contact_at` from the best available proxy:
  - `last_success_at`
  - latest qualifying `INTERACTION.interaction_at`
  - `last_contact_datetime`
- derive temporary future cover from:
  - open tasks
  - `next_contact_due_date`
  - `next_meeting_date`

## Normalize existing data

Normalize:

- channel naming (`email`, `Email`, `Whatsapp`, `whatsapp`, `Mobile`, `Face to Face`)
- `contact_value` casing (`Hot`, `hot`, `Hot'`)
- `meeting_status`

## Manual review list

Generate a review queue for:

- `96` invisible contacts
- contacts missing `contact_value`
- strategic contacts with no owner after Phase 2

## 9. Acceptance Criteria

Phase 1 is acceptable when:

- every active contact appears in one and only one primary queue
- invisible contacts are explicitly counted and surfaced
- strategic contacts with no next step are impossible to miss
- dashboard no longer depends on `meeting_status` alone

Phase 2 is acceptable when:

- schema supports tiering, influence, confidence, and opportunity context
- interaction logging supports direction and meaningfulness
- a manual override path exists for tier and maintenance mode

Phase 3 is acceptable when:

- score components are explainable
- low-confidence data never produces falsely healthy outcomes
- queue membership remains stable and auditable

## 10. Risks

- score inflation if weak data is treated as strong data
- hidden contacts if queues rely too much on missing metadata
- noisy dashboard if overlays are not collapsed well
- frontend-only scoring causing inconsistent behavior

Primary mitigation:

- keep fail-safe rules server-side
- keep low-confidence records visible
- keep `overdue` as a bounded operational signal, not the product center

## 11. Recommended Build Order

1. Implement queue computation with current schema
2. Add overlays and invisible-contact reporting
3. Add schema columns and `PERSON_OPPORTUNITY`
4. Backfill meaningful contact and future cover
5. Add tiering and maintenance mode controls
6. Add composite scoring
7. Add ML ranking assist after outcome data exists

## 12. Final Recommendation

The CRM should evolve from:

- "who is overdue"

to:

- "who needs action"
- "who must be maintained"
- "who should be preserved"
- "who is drifting out of coverage"
- "where opportunity can emerge through direct or indirect influence"

That is the correct operating model for a 300+ active relationship network.
