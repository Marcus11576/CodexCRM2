from __future__ import annotations

from backend.models.relationship_intelligence import (
    LENS_ACTIVE,
    LENS_FAMILY,
    LENS_LIFESTYLE,
    LENS_MARKET,
    LENS_ORDER,
    LENS_TRACK,
)


PIPELINE_VERSION = "relationship-intelligence-v2-multi-agent"
AGENT_NOISE_GATE = "Agent 0: Noise Gate"
AGENT_FAMILY = "Agent 1: Family & Personal + Interests & Lifestyle"
AGENT_ACTIVE = "Agent 2: Active Opportunity"
AGENT_MARKET = "Agent 3: Market & Business"
AGENT_TRACK = "Agent 4: Track Record & Strategic Value"
AGENT_ARBITER = "Agent 5: Truth Arbiter"
AGENT_BRIEF = "Agent 6: Brief Writer"
AGENT_ACTION = "Agent 7: Action Tracker"
AGENT_COMPANY_VERIFY = "Agent 8: Company Verifier"

AGENT_ORDER = [
    AGENT_NOISE_GATE,
    AGENT_FAMILY,
    AGENT_ACTIVE,
    AGENT_MARKET,
    AGENT_TRACK,
    AGENT_ARBITER,
    AGENT_BRIEF,
    AGENT_ACTION,
    AGENT_COMPANY_VERIFY,
]


PROMPT_REGISTRY: dict[str, str] = {
    AGENT_FAMILY: """You are Agent 1 in the Taylor Sterling Relationship Intelligence Engine.

Your remit is narrow.
Extract only human relationship hooks for Family & Personal and Interests & Lifestyle.

Rules:
1. Extract candidate points only.
2. Do not write final prose.
3. Do not decide final truth globally.
4. If family is present, Family & Personal takes precedence.
5. "Ran with his daughter" is Family & Personal primary and Interests & Lifestyle secondary.
6. Keep business, market, and commercial details out unless essential context.
7. Treat explicit age or life-stage context (for example "in his 60s" or "well into her 60s") as Family & Personal context when relevant.
8. Include status, confidence, priority, source_ids, and why_it_matters.
9. Be conservative and specific.
10. If signal is weak, say so by returning fewer points rather than padding.
11. If transcript_guidance is present, use it as authoritative guidance for classification.""",
    AGENT_ACTIVE: """You are Agent 2 in the Taylor Sterling Relationship Intelligence Engine.

Your remit is narrow.
Extract only current commercial opportunity candidate points.

Rules:
1. Extract candidate points only.
2. Do not write final prose.
3. Do not decide final truth globally.
4. Focus on roles, mandates, follow-up need, urgency, ownership, and status shifts.
5. Filled roles must not remain active.
6. Narrower newer role counts replace older larger counts.
7. Old glamour claims must not survive unless current evidence supports them.
8. Keep broad market commentary out unless it directly affects live opportunity.
9. Include status, confidence, priority, source_ids, and why_it_matters.
10. If transcript_guidance is present, use it as authoritative guidance for classification.""",
    AGENT_MARKET: """You are Agent 3 in the Taylor Sterling Relationship Intelligence Engine.

Your remit is narrow.
Extract only company and market intelligence candidate points.

Rules:
1. Extract candidate points only.
2. Do not write final prose.
3. Do not decide final truth globally.
4. Focus on pricing pressure, competition, sector frustration, business direction, project focus, and capability shortage.
5. Do not turn market comments into live mandates.
6. Do not inflate one comment into strategic certainty.
7. Include status, confidence, priority, source_ids, and why_it_matters.
8. If transcript_guidance is present, use it as authoritative guidance for classification.""",
    AGENT_TRACK: """You are Agent 4 in the Taylor Sterling Relationship Intelligence Engine.

Your remit is narrow.
Extract only track record and strategic value candidate points.

Rules:
1. Extract candidate points only.
2. Do not write final prose.
3. Do not decide final truth globally.
4. Focus on account value, influence, access quality, seniority, strategic relevance, and long-term account importance.
5. No fantasy access.
6. No inflated partnership language.
7. If access was corrected down, reflect that.
8. Include status, confidence, priority, source_ids, and why_it_matters.
9. If transcript_guidance is present, use it as authoritative guidance for classification.""",
    AGENT_ARBITER: """You are Agent 5, the only truth arbiter in the Taylor Sterling Relationship Intelligence Engine.

You receive candidate points from specialist lens agents plus cleaned source metadata.

Rules:
1. You alone decide final truth classification.
2. Merge duplicate meaning.
3. Apply source precedence strictly.
4. Prefer current narrow truth over older exciting story.
5. Separate active, historical, superseded, disproved, and uncertain.
6. Never let disproved or superseded claims survive in active truth.
7. If evidence is mixed, prefer uncertainty over false coherence.
8. Keep claims atomic and precise.
9. Do not score.
10. Do not write executive summary language.
11. If transcript_guidance is present, use it to keep stage and bucket interpretation aligned.""",
    AGENT_BRIEF: """You are Agent 6, the Taylor Sterling Brief Writer.

You are writing from a reconciled claim ledger and deterministic scores only.

Rules:
1. Use only reconciled truth.
2. Do not revive stale or disproved claims.
3. Use concise executive UK English.
4. No fluff.
5. No generic CRM filler.
6. No em dashes.
7. Each lens must contain 3 to 8 prioritised points where evidence supports it.
8. If a lens is thin, label it low signal and provide only evidence-backed points.
9. Do not reinterpret raw evidence.
10. Include all three deterministic scores: relationship health, commercial priority, and execution pressure.
11. Help Marcus decide what to say next and what not to rely on.""",
    AGENT_ACTION: """You are Agent 7, the Taylor Sterling Action Tracker.

You are not writing a summary.
You extract only concrete action items from reconciled truth and recent evidence.

Rules:
1. Output structured action items only.
2. Focus on what Marcus or Taylor Sterling must do, check, or close.
3. Prefer action items that protect live opportunity, timing, ownership, or relationship continuity.
4. Do not invent tasks not grounded in the claim ledger or recent evidence.
5. If a meeting was postponed and opportunity remains live, create an action to reschedule or follow up.
6. If ownership or mandate status is unclear, create a clarification action.
7. If later evidence suggests the action happened, mark it completed only if directly supported.
8. Use concise executive UK English.
9. Keep actions specific, commercially useful, and auditable.
10. If transcript_guidance is present, respect its stage and bucket definitions when framing actions.""",
    AGENT_COMPANY_VERIFY: """You are Agent 8, the Taylor Sterling Company Verifier.

You use web search to check public company context only.

Rules:
1. Verify only company-level public context.
2. Do not invent relationship truth from web sources.
3. Do not overwrite reconciled CRM truth.
4. Compare public context against the current claim ledger and say whether it is corroborated, not found, or in tension.
5. Keep output concise and factual.
6. Return JSON only.""",
}


def lens_agent_response_format(agent_name: str) -> dict:
    if agent_name == AGENT_FAMILY:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "relationship_lens_family_v2",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["lens", "lens_summary", "candidate_points", "changed_points", "uncertain_points", "gaps", "watchouts"],
                    "properties": {
                        "lens": {"type": "string"},
                        "lens_summary": {"type": "string"},
                        "candidate_points": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["point_id", "point", "sub_lens", "secondary_sub_lens", "status", "confidence", "priority", "source_ids", "why_it_matters"],
                                "properties": {
                                    "point_id": {"type": "string"},
                                    "point": {"type": "string"},
                                    "sub_lens": {"type": "string", "enum": [LENS_FAMILY, LENS_LIFESTYLE]},
                                    "secondary_sub_lens": {"type": "string", "enum": [LENS_FAMILY, LENS_LIFESTYLE, "none"]},
                                    "status": {"type": "string", "enum": ["active", "historical", "superseded", "disproved", "uncertain"]},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                    "priority": {"type": "integer", "minimum": 1, "maximum": 8},
                                    "source_ids": {"type": "array", "items": {"type": "string"}},
                                    "why_it_matters": {"type": "string"},
                                },
                            },
                        },
                        "changed_points": {"type": "array", "items": {"type": "string"}},
                        "uncertain_points": {"type": "array", "items": {"type": "string"}},
                        "gaps": {"type": "array", "items": {"type": "string"}},
                        "watchouts": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": f"relationship_lens_{agent_name.lower().replace(' ', '_').replace(':', '').replace('&', 'and').replace('+', 'plus')}_v2",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["lens", "lens_summary", "candidate_points", "changed_points", "uncertain_points", "gaps", "watchouts"],
                "properties": {
                    "lens": {"type": "string"},
                    "lens_summary": {"type": "string"},
                    "candidate_points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["point_id", "point", "status", "confidence", "priority", "source_ids", "why_it_matters", "supersedes_point_ids", "disproved_by_point_ids"],
                            "properties": {
                                "point_id": {"type": "string"},
                                "point": {"type": "string"},
                                "status": {"type": "string", "enum": ["active", "historical", "superseded", "disproved", "uncertain"]},
                                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                "priority": {"type": "integer", "minimum": 1, "maximum": 8},
                                "source_ids": {"type": "array", "items": {"type": "string"}},
                                "why_it_matters": {"type": "string"},
                                "supersedes_point_ids": {"type": "array", "items": {"type": "string"}},
                                "disproved_by_point_ids": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                    "changed_points": {"type": "array", "items": {"type": "string"}},
                    "uncertain_points": {"type": "array", "items": {"type": "string"}},
                    "gaps": {"type": "array", "items": {"type": "string"}},
                    "watchouts": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }


TRUTH_ARBITER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "relationship_truth_arbiter_v2",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "claim_ledger",
            ],
            "properties": {
                "claim_ledger": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "claims",
                        "active_truths",
                        "changed_recently",
                        "uncertainties",
                        "disproved_or_retired",
                        "relationship_gaps",
                        "risks_or_watchouts",
                        "source_quality_notes",
                        "lens_outputs",
                    ],
                    "properties": {
                        "claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["claim_id", "claim_text", "lens", "status", "confidence", "priority", "source_ids", "why_it_matters", "supersedes_claim_ids", "disproved_by_claim_ids"],
                                "properties": {
                                    "claim_id": {"type": "string"},
                                    "claim_text": {"type": "string"},
                                    "lens": {"type": "string", "enum": LENS_ORDER},
                                    "status": {"type": "string", "enum": ["active", "historical", "superseded", "disproved", "uncertain"]},
                                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                    "priority": {"type": "integer", "minimum": 1, "maximum": 8},
                                    "source_ids": {"type": "array", "items": {"type": "string"}},
                                    "why_it_matters": {"type": "string"},
                                    "supersedes_claim_ids": {"type": "array", "items": {"type": "string"}},
                                    "disproved_by_claim_ids": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                        "active_truths": {"type": "array", "items": {"type": "string"}},
                        "changed_recently": {"type": "array", "items": {"type": "string"}},
                        "uncertainties": {"type": "array", "items": {"type": "string"}},
                        "disproved_or_retired": {"type": "array", "items": {"type": "string"}},
                        "relationship_gaps": {"type": "array", "items": {"type": "string"}},
                        "risks_or_watchouts": {"type": "array", "items": {"type": "string"}},
                        "source_quality_notes": {"type": "array", "items": {"type": "string"}},
                        "lens_outputs": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": LENS_ORDER,
                            "properties": {lens: {"type": "array", "items": {"type": "string"}} for lens in LENS_ORDER},
                        },
                    },
                }
            },
        },
    },
}


BRIEF_WRITER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "relationship_brief_writer_v2",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "contact_name",
                "company",
                "title",
                "relationship_health_score",
                "commercial_priority_score",
                "execution_pressure_score",
                "score_drivers",
                "score_reducers",
                "execution_pressure_drivers",
                "execution_pressure_reducers",
                "current_read",
                "what_is_true_now",
                "what_changed_recently",
                "uncertainties",
                "relationship_gaps",
                "risks_or_watchouts",
                "next_conversation_priorities",
                "lenses",
                "personal_hooks_worth_remembering",
                "commercial_signals_worth_tracking",
                "market_signals_worth_tracking",
                "disproved_or_retired_claims",
            ],
            "properties": {
                "contact_name": {"type": "string"},
                "company": {"type": "string"},
                "title": {"type": "string"},
                "relationship_health_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "commercial_priority_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "execution_pressure_score": {"type": "integer", "minimum": 0, "maximum": 100},
                "score_drivers": {"type": "array", "items": {"type": "string"}},
                "score_reducers": {"type": "array", "items": {"type": "string"}},
                "execution_pressure_drivers": {"type": "array", "items": {"type": "string"}},
                "execution_pressure_reducers": {"type": "array", "items": {"type": "string"}},
                "current_read": {"type": "string"},
                "what_is_true_now": {"type": "array", "items": {"type": "string"}},
                "what_changed_recently": {"type": "array", "items": {"type": "string"}},
                "uncertainties": {"type": "array", "items": {"type": "string"}},
                "relationship_gaps": {"type": "array", "items": {"type": "string"}},
                "risks_or_watchouts": {"type": "array", "items": {"type": "string"}},
                "next_conversation_priorities": {"type": "array", "items": {"type": "string"}},
                "lenses": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": LENS_ORDER,
                    "properties": {
                        lens: {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["lens_summary", "top_points", "what_changed", "uncertainties", "best_use_before_next_conversation"],
                            "properties": {
                                "lens_summary": {"type": "string"},
                                "top_points": {"type": "array", "items": {"type": "string"}},
                                "what_changed": {"type": "array", "items": {"type": "string"}},
                                "uncertainties": {"type": "array", "items": {"type": "string"}},
                                "best_use_before_next_conversation": {"type": "string"},
                            },
                        }
                        for lens in LENS_ORDER
                    },
                },
                "personal_hooks_worth_remembering": {"type": "array", "items": {"type": "string"}},
                "commercial_signals_worth_tracking": {"type": "array", "items": {"type": "string"}},
                "market_signals_worth_tracking": {"type": "array", "items": {"type": "string"}},
                "disproved_or_retired_claims": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


ACTION_TRACKER_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "relationship_action_tracker_v1",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["actions"],
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "action_id",
                            "action_text",
                            "action_type",
                            "status",
                            "owner",
                            "urgency",
                            "due_window",
                            "linked_claim_ids",
                            "supporting_source_ids",
                            "why_now",
                            "blocker",
                            "consequence_if_missed",
                        ],
                        "properties": {
                            "action_id": {"type": "string"},
                            "action_text": {"type": "string"},
                            "action_type": {"type": "string"},
                            "status": {"type": "string", "enum": ["open", "in_progress", "completed", "stale", "missed", "cancelled"]},
                            "owner": {"type": "string"},
                            "urgency": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                            "due_window": {"type": "string"},
                            "linked_claim_ids": {"type": "array", "items": {"type": "string"}},
                            "supporting_source_ids": {"type": "array", "items": {"type": "string"}},
                            "why_now": {"type": "string"},
                            "blocker": {"type": "string"},
                            "consequence_if_missed": {"type": "string"},
                        },
                    },
                }
            },
        },
    },
}
