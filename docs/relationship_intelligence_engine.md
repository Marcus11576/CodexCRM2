# Relationship Intelligence Engine

## What it is

This rebuild replaces the old weighted intelligence layer with a controlled multi-agent truth system for Marcus Taylor.

The goal is simple:

- remove admin noise
- extract meaningful evidence
- split insight by specialist lens
- reconcile contradictions through one truth arbiter
- score from reconciled truth only
- render a briefing Marcus can actually use

## Why each agent exists

### Agent 0: Noise Gate

Deterministic preparation. It normalises raw CRM history, assigns stable `source_id` values, classifies source type, flags likely admin noise, and preserves raw evidence for audit.

### Agent 1: Family & Personal + Interests & Lifestyle

Finds human context and rapport hooks. It does not decide business truth.

### Agent 2: Active Opportunity

Finds live commercial opportunity only. It does not decide final truth globally.

### Agent 3: Market & Business

Finds business reality, sector pressure, and market signal. It does not turn that into mandate status.

### Agent 4: Track Record & Strategic Value

Finds strategic value, influence, seniority, and access reality. It does not inflate access.

### Agent 5: Truth Arbiter

This is the only agent allowed to classify final truth. It reconciles all candidate points, applies precedence, and retires stale or disproved claims.

### Agent 6: Brief Writer

Writes the final Marcus-ready briefing from the reconciled claim ledger and deterministic scores only.

## How truth arbitration works

The arbiter uses this source precedence order:

1. `manual_resolution`
2. `manual_input`
3. `transcript`, `whatsapp`, `email`, `meeting_note`
4. `calendar_metadata`
5. `ai_summary`

Hard rules are also enforced in code after arbitration:

- disproved CEO intro claims are retired
- filled roles cannot remain active
- narrower newer role counts supersede larger older ones
- stale OBE/partnership claims do not survive by momentum
- uncertainty and relationship gaps are forced in when evidence is mixed

## How stale claims are retired

Claims are retired in three ways:

1. A newer stronger source explicitly contradicts an older claim
2. A newer narrower claim replaces a broader older claim
3. Deterministic hard rules suppress stale storyline residue

That means attractive old claims do not survive just because they were repeated.

## Cost control

The pipeline keeps cost down by:

- using a deterministic Noise Gate first
- running lens agents in parallel
- filtering lens-specific inputs before model calls
- using structured JSON outputs only
- giving the Brief Writer only the reconciled ledger and scores
- caching runs by source digest
- re-running only when the evidence chain changes or a force refresh is requested

## Persistence model

Raw sources and manual corrections remain in the source tables:

- `INTERACTION`
- `RELATIONSHIP_SITUATION_EVENT`

Pipeline outputs are persisted in:

- `REL_INTEL_RUN`
- `REL_INTEL_AGENT_OUTPUT`

Each run stores:

- cleaned interactions
- agent outputs
- claim ledger
- scores
- final briefing

## UI shape

The profile page shows:

- contact identity
- relationship health
- commercial priority
- current read
- core briefing sections
- five lens panels
- raw evidence
- cleaned interactions
- per-agent outputs
- claim ledger
- retired claims

Manual controls currently support:

- retire claim
- promote claim
- mark uncertain
- merge duplicate
- correct source
- add manual resolution
- force refresh

All claim actions are written back as `manual_resolution` source material so future runs inherit the correction.
