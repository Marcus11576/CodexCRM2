from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


LENS_FAMILY = "Family & Personal"
LENS_LIFESTYLE = "Interests & Lifestyle"
LENS_ACTIVE = "Active Opportunity"
LENS_MARKET = "Market & Business"
LENS_TRACK = "Track Record & Strategic Value"
LENS_ORDER = [LENS_FAMILY, LENS_LIFESTYLE, LENS_ACTIVE, LENS_MARKET, LENS_TRACK]

SUB_LENS_FAMILY = "Family & Personal"
SUB_LENS_LIFESTYLE = "Interests & Lifestyle"

SOURCE_TYPE = Literal[
    "manual_resolution",
    "manual_input",
    "transcript",
    "whatsapp",
    "email",
    "meeting_note",
    "calendar_metadata",
    "ai_summary",
    "other",
]

CLAIM_STATUS = Literal["active", "historical", "superseded", "disproved", "uncertain"]
TRUTH_STATE = Literal["Confirmed", "Likely", "Unverified", "Retired"]
LENS_NAME = Literal[
    "Family & Personal",
    "Interests & Lifestyle",
    "Active Opportunity",
    "Market & Business",
    "Track Record & Strategic Value",
]


class IntelligenceBaseModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class NormalizedInteraction(IntelligenceBaseModel):
    source_id: str
    contact_name: str
    company: str
    date: str
    datetime: Optional[str] = None
    source_type: SOURCE_TYPE
    title: str
    raw_text: str
    noise_candidate: bool = False
    metadata: dict = Field(default_factory=dict)


class CandidatePoint(IntelligenceBaseModel):
    point_id: str
    point: str
    status: CLAIM_STATUS
    confidence: float = Field(ge=0.0, le=1.0)
    priority: int = Field(ge=1, le=8)
    source_ids: list[str] = Field(default_factory=list)
    why_it_matters: str
    supersedes_point_ids: list[str] = Field(default_factory=list)
    disproved_by_point_ids: list[str] = Field(default_factory=list)
    sub_lens: Optional[Literal["Family & Personal", "Interests & Lifestyle"]] = None
    secondary_sub_lens: Optional[Literal["Family & Personal", "Interests & Lifestyle", "none"]] = None


class LensAgentOutput(IntelligenceBaseModel):
    lens: str
    lens_summary: str
    candidate_points: list[CandidatePoint] = Field(default_factory=list)
    changed_points: list[str] = Field(default_factory=list)
    uncertain_points: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    watchouts: list[str] = Field(default_factory=list)


class Claim(IntelligenceBaseModel):
    claim_id: str
    claim_text: str
    lens: LENS_NAME
    claim_family: str = "other"
    entity_key: str = "general"
    status: CLAIM_STATUS
    truth_state: TRUTH_STATE = "Unverified"
    confidence: float = Field(ge=0.0, le=1.0)
    priority: int = Field(ge=1, le=8)
    source_ids: list[str] = Field(default_factory=list)
    why_it_matters: str
    source_rank: int = Field(default=9, ge=1, le=9)
    first_seen: str = ""
    last_seen: str = ""
    supersedes_claim_ids: list[str] = Field(default_factory=list)
    disproved_by_claim_ids: list[str] = Field(default_factory=list)


class ClaimLedger(IntelligenceBaseModel):
    claims: list[Claim] = Field(default_factory=list)
    active_truths: list[str] = Field(default_factory=list)
    changed_recently: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    disproved_or_retired: list[str] = Field(default_factory=list)
    relationship_gaps: list[str] = Field(default_factory=list)
    risks_or_watchouts: list[str] = Field(default_factory=list)
    source_quality_notes: list[str] = Field(default_factory=list)
    lens_outputs: dict[str, list[str]] = Field(default_factory=dict)


ACTION_STATUS = Literal["open", "in_progress", "completed", "stale", "missed", "cancelled"]
ACTION_URGENCY = Literal["low", "medium", "high", "critical"]


class ActionItem(IntelligenceBaseModel):
    action_id: str
    action_text: str
    action_type: str
    status: ACTION_STATUS
    owner: str = "Marcus"
    urgency: ACTION_URGENCY = "medium"
    due_window: str = ""
    linked_claim_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)
    why_now: str = ""
    blocker: str = ""
    consequence_if_missed: str = ""
    last_updated: str = ""


class ActionLedger(IntelligenceBaseModel):
    actions: list[ActionItem] = Field(default_factory=list)
    open_actions: list[str] = Field(default_factory=list)
    completed_actions: list[str] = Field(default_factory=list)
    stale_actions: list[str] = Field(default_factory=list)
    missed_actions: list[str] = Field(default_factory=list)


class ScoreBundle(IntelligenceBaseModel):
    relationship_health_score: int = Field(ge=0, le=100)
    commercial_priority_score: int = Field(ge=0, le=100)
    execution_pressure_score: int = Field(ge=0, le=100)
    score_drivers: list[str] = Field(default_factory=list)
    score_reducers: list[str] = Field(default_factory=list)
    execution_pressure_drivers: list[str] = Field(default_factory=list)
    execution_pressure_reducers: list[str] = Field(default_factory=list)


class LensBrief(IntelligenceBaseModel):
    lens_summary: str
    top_points: list[str] = Field(default_factory=list)
    what_changed: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    best_use_before_next_conversation: str


class BriefingOutput(IntelligenceBaseModel):
    contact_name: str
    company: str
    title: str
    relationship_health_score: int = Field(ge=0, le=100)
    commercial_priority_score: int = Field(ge=0, le=100)
    execution_pressure_score: int = Field(ge=0, le=100)
    score_drivers: list[str] = Field(default_factory=list)
    score_reducers: list[str] = Field(default_factory=list)
    execution_pressure_drivers: list[str] = Field(default_factory=list)
    execution_pressure_reducers: list[str] = Field(default_factory=list)
    current_read: str
    what_is_true_now: list[str] = Field(default_factory=list)
    what_changed_recently: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    relationship_gaps: list[str] = Field(default_factory=list)
    risks_or_watchouts: list[str] = Field(default_factory=list)
    next_conversation_priorities: list[str] = Field(default_factory=list)
    lenses: dict[str, LensBrief]
    personal_hooks_worth_remembering: list[str] = Field(default_factory=list)
    commercial_signals_worth_tracking: list[str] = Field(default_factory=list)
    market_signals_worth_tracking: list[str] = Field(default_factory=list)
    disproved_or_retired_claims: list[str] = Field(default_factory=list)


class PipelineMeta(IntelligenceBaseModel):
    pipeline_version: str
    model_name: str
    cache_status: str
    source_digest: str
    agent_mode: str


class PipelineTrace(IntelligenceBaseModel):
    raw_interactions: list[dict] = Field(default_factory=list)
    cleaned_interactions: list[dict] = Field(default_factory=list)
    agent_outputs: dict[str, dict] = Field(default_factory=dict)
    claim_ledger: dict = Field(default_factory=dict)
    action_ledger: dict = Field(default_factory=dict)
    retired_claims: list[dict] = Field(default_factory=list)
    scores: dict = Field(default_factory=dict)
