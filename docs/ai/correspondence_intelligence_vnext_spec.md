# Correspondence Intelligence vNext Spec

## Purpose

Antigravity CRM should not behave like a passive contact database. It should operate as a relationship intelligence system for:

- executive search in the built environment across the Middle East
- high-trust network cultivation through the OBE network
- direct opportunity creation
- indirect influence mapping
- market intelligence capture
- rapport preservation and strategic engagement

The platform must absorb meaningful input from correspondence, notes, calls, meetings, events, and uploads, then convert that into usable intelligence with clear evidence and clear action value.

## Product Standard

The system must be able to answer, for any important contact:

- What is happening?
- Why does it matter?
- What does this reveal about opportunity, risk, influence, and timing?
- What does this reveal about the person personally and professionally?
- What should happen next?
- What evidence supports that conclusion?

If it cannot do this reliably, the system will feel administrative rather than strategic.

## Core Design Principle

Separate relationship memory into 3 layers:

1. Evidence
- raw email, WhatsApp, call notes, meeting notes, event notes, transcript, attachment, manual note

2. Interpretation
- what the platform believes is happening in that evidence

3. Enduring Memory
- long-term intelligence worth retaining on the profile and using for future prioritization, briefings, and engagement

This separation prevents:
- dumping raw clutter into the profile
- flattening nuance into weak generic summaries
- presenting inference as fact

## First-Class Intelligence Domains

The platform should interpret and store intelligence across these domains:

1. Relationship Intelligence
- rapport markers
- trust signals
- engagement style
- personal interests
- family/personal context
- social preferences
- relationship trajectory

2. Opportunity Intelligence
- executive search mandates
- hiring motion
- business development opportunities
- referral/introduction opportunities
- account expansion opportunities
- future optionality

3. Market Intelligence
- hiring trends
- compensation pressure
- talent scarcity
- company expansion
- project timing
- market sentiment
- strategic shifts
- leadership movement
- reputational changes

4. Influence Intelligence
- who opens doors
- who blocks movement
- who actually influences decisions
- connectors, champions, introducers, market nodes

5. Friction Intelligence
- cost sensitivity
- payment friction
- timeline risk
- process stalling
- internal politics
- candidate hesitation
- offer risk
- delivery risk

## New vNext Module Stack

### 1. Correspondence Intelligence

Input:
- emails
- WhatsApp screenshots/messages
- meeting notes
- call notes
- event notes
- transcripts
- uploaded docs
- manual notes

Output per item:
- what_is_happening
- why_it_matters
- stage
- momentum
- intent_signals
- pain_points
- relationship_signals
- opportunity_signals
- influence_signals
- market_intel_signals
- friction_signals
- recommended_action
- confidence
- evidence_snippets

### 2. Relationship Memory

Stores enduring relationship truths:
- known interests
- family/personal markers
- preferred communication style
- engagement tone
- values
- sensitivities
- relationship history
- trust markers
- relationship risks

This should be explicitly separate from short-term business motion.

### 3. Opportunity Memory

Stores:
- person-level opportunity
- company-level opportunity
- candidate/hiring opportunity
- indirect opportunity via network influence
- future optionality

### 4. Market Intel Memory

Stores cross-contact market patterns:
- talent shortages
- salary pressure
- active hiring pockets
- company growth signals
- market slowdown signals
- role demand
- leadership movement
- regional market shifts
- sector momentum

This must be platform-level as well as contact-linked.

### 5. Engagement Orchestration

Uses interpreted memory to decide:
- who should be contacted
- why now
- which angle matters
- how to engage
- what next-best action is appropriate

## Required New Data Model

### Table: `INTERPRETED_INTERACTION`

One row per meaningful interaction or thread interpretation.

Fields:
- `interpretation_id`
- `person_id`
- `company_name_raw`
- `source_interaction_id`
- `source_kind`
- `thread_id`
- `what_is_happening`
- `why_it_matters`
- `stage`
- `momentum`
- `intent_signals_json`
- `pain_points_json`
- `relationship_signals_json`
- `opportunity_signals_json`
- `influence_signals_json`
- `market_intel_signals_json`
- `friction_signals_json`
- `recommended_action`
- `confidence_score`
- `evidence_snippets_json`
- `created_at`
- `updated_at`

### Table: `ENDURING_MEMORY`

Stores long-term profile truths promoted from interpreted interactions.

Fields:
- `memory_id`
- `person_id`
- `memory_domain`
- `memory_type`
- `memory_text`
- `importance_score`
- `confidence_score`
- `status`
- `source_interpretation_id`
- `source_interaction_id`
- `evidence_snippets_json`
- `created_at`
- `updated_at`

Suggested `memory_domain` values:
- `rapport`
- `professional`
- `opportunity`
- `market_intel`
- `influence`
- `risk`

### Table: `MARKET_INTEL`

Stores cross-contact market intelligence.

Fields:
- `market_intel_id`
- `topic`
- `sector`
- `region`
- `signal_text`
- `signal_type`
- `confidence_score`
- `importance_score`
- `linked_people_json`
- `linked_companies_json`
- `evidence_snippets_json`
- `status`
- `created_at`
- `updated_at`

## Interpretation Rules

The interpreter should not only classify topics. It should determine:

- process stage
- signal strength
- whether something is enduring or temporary
- whether something is profile-specific or market-wide
- whether something is evidence-backed or inferred

### Example: Craig Moorfield emails

The system should infer:
- active hiring process
- shortlist to interview / offer coordination
- candidate cost sensitivity
- operational engagement from Craig
- likely recruitment-stage friction
- possible market intel about hiring activity and candidate economics

And should output both:
- profile-level opportunity intelligence
- platform-level market intel

## Evidence vs Inference Standard

Every interpreted output must include provenance.

Allowed evidence labels:
- `substantiated`
- `inferred`
- `weak_signal`

Rules:
- direct statements from correspondence or clear operational facts -> `substantiated`
- model synthesis from multiple facts -> `inferred`
- partial / uncertain pattern with limited support -> `weak_signal`

Never present inferred relationship or market conclusions as hard fact.

## World-Class Relationship Requirements

The system must capture more than business facts.

### Rapport Memory Should Include
- interests
- family markers
- travel preferences
- social style
- relationship rituals
- introductions history
- trust markers
- sensitivities
- rapport anchors

### Why This Matters

For executive search and high-level relationship cultivation, edge comes from:
- remembering what matters to the person
- knowing how to engage them
- understanding pressure and priorities
- building trust over time

This is not optional metadata. It is operating intelligence.

## World-Class Market Intel Requirements

Market intel must be treated as a first-class system output.

It should be created from all contacts, not just strategic ones.

Examples:
- active salary inflation in a function
- repeated interview slowdowns in a sector
- multiple firms opening the same role type
- candidate relocation concerns recurring
- leadership reshuffles
- project or hiring timing shifts

Market intel should have:
- linked evidence
- source diversity
- region and sector tags
- confidence based on repeated corroboration

## vNext UI Changes

### Profile
- show `What’s Happening`
- show `Why It Matters`
- show `Enduring Memory`
- show `Draft Interpretation`
- show `Recent Evidence`
- show `Market Intel linked to this contact`

### Dashboard / Network Lab
- show `What changed recently`
- show `Opportunity emerging`
- show `Market signal emerging`
- show `Relationship warming/cooling`
- show `Draft intel waiting review`

### Databank
- split:
  - surfaced databank
  - draft interpretation
  - enduring memory
  - market intel references

## Scoring Implications

The score should not be the starting point.

The score should be downstream of:
- interpreted correspondence
- enduring memory
- opportunity memory
- market intelligence
- relationship trajectory

New score inputs should include:
- evidence-backed relationship momentum
- process stage progression
- friction signals
- influence significance
- market relevance
- quality of recent interaction, not just existence

## Blind Spots To Explicitly Avoid

- treating any interaction as meaningful
- ignoring market intel because it is not person-specific
- flattening thread meaning into generic labels
- hiding valuable draft intelligence
- mixing enduring profile truth with temporary operational chatter
- over-trusting default scores
- over-relying on manual tagging
- missing rapport data because it is “non-business”

## Recommended Build Order

### Phase 1
- create `INTERPRETED_INTERACTION`
- add correspondence interpretation pipeline
- show `What’s Happening` and `Why It Matters` on profile
- surface draft interpretation visibly

### Phase 2
- create `ENDURING_MEMORY`
- promote durable profile truths from interpreted interactions
- add rapport memory workflows

### Phase 3
- create `MARKET_INTEL`
- aggregate repeated cross-contact signals into market intelligence

### Phase 4
- rebuild scoring and orchestration using interpreted memory and market intel

## Success Criteria

The system is behaving correctly when:

- a meaningful email thread can be summarized accurately in operational terms
- a profile with real evidence no longer looks empty
- the system distinguishes person opportunity, company opportunity, and market intel
- rapport signals are retained and usable later
- market trends accumulate across contacts instead of being lost in isolated notes
- users can see what is fact, what is inferred, and what needs review
- the platform helps decide how to engage, not just what was stored
