"""
Antigravity CRM — People Router
All contact CRUD, search, pipeline, meeting management.
"""
import uuid
import json
import re
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from backend.database import get_db, run_write
from backend.services.ai_foundation import (
    canonical_business_subtopic,
    infer_communication_channel,
    is_placeholder_signal_text,
    normalize_signal_text,
)
from backend.services.ai_pipeline_service import grouped_profile_signals, invalidate_briefs_for_profile, load_profile_signals
from backend.services.preference_learning import record_feedback_event
from backend.services.network_orchestration_service import get_network_contact_context
from backend.services.profile_background_backfill import backfill_missing_profile_background

router = APIRouter(prefix="/api/people", tags=["people"])


# ── Pydantic Models ──────────────────────────────────────────────────────────

class PersonCreate(BaseModel):
    full_name: str
    title_current: Optional[str] = None
    company_name_raw: Optional[str] = None
    email_primary: Optional[str] = None
    email_secondary: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    linkedin_url: Optional[str] = None
    cat: Optional[str] = "GEN"
    env: Optional[str] = None
    disc: Optional[str] = None
    contact_value: Optional[str] = None
    career_summary: Optional[str] = None
    key_professional_notes: Optional[str] = None
    key_personal_notes: Optional[str] = None
    profile_photo_url: Optional[str] = None
    network_tier: Optional[str] = None
    maintenance_mode: Optional[str] = None
    relationship_owner: Optional[str] = None
    decision_role: Optional[str] = None
    influence_scope: Optional[str] = None
    account_priority: Optional[str] = None
    tier_rationale: Optional[str] = None


class PersonUpdate(BaseModel):
    full_name: Optional[str] = None
    title_current: Optional[str] = None
    company_name_raw: Optional[str] = None
    email_primary: Optional[str] = None
    email_secondary: Optional[str] = None
    phone_primary: Optional[str] = None
    phone_secondary: Optional[str] = None
    linkedin_url: Optional[str] = None
    cat: Optional[str] = None
    env: Optional[str] = None
    disc: Optional[str] = None
    contact_value: Optional[str] = None
    engagement_status: Optional[str] = None
    is_ts_advisory_candidate: Optional[bool] = None
    career_summary: Optional[str] = None
    key_professional_notes: Optional[str] = None
    key_personal_notes: Optional[str] = None
    key_gossip_notes: Optional[str] = None
    intel_notes: Optional[str] = None
    employment_history: Optional[str] = None   # JSON string
    personal_data: Optional[str] = None        # JSON string
    profile_photo_url: Optional[str] = None
    next_contact_due_date: Optional[str] = None
    meeting_status: Optional[str] = None
    network_tier: Optional[str] = None
    maintenance_mode: Optional[str] = None
    relationship_owner: Optional[str] = None
    decision_role: Optional[str] = None
    influence_scope: Optional[str] = None
    strategic_value_score: Optional[int] = None
    influence_score: Optional[int] = None
    future_option_score: Optional[int] = None
    coverage_risk_score: Optional[int] = None
    opportunity_readiness_score: Optional[int] = None
    relationship_confidence_score: Optional[int] = None
    last_meaningful_contact_at: Optional[str] = None
    last_inbound_at: Optional[str] = None
    last_outbound_at: Optional[str] = None
    unanswered_outbound_count: Optional[int] = None
    reactivation_trigger_notes: Optional[str] = None
    account_priority: Optional[str] = None
    tier_rationale: Optional[str] = None
    last_health_refresh_at: Optional[str] = None


class OpportunityCreate(BaseModel):
    account_name: Optional[str] = None
    opportunity_type: Optional[str] = None
    stage: Optional[str] = None
    value_band: Optional[str] = None
    trigger_date: Optional[str] = None
    strategic_importance: int = 50
    status: str = "open"
    owner: Optional[str] = None
    notes: Optional[str] = None


class OpportunityUpdate(BaseModel):
    account_name: Optional[str] = None
    opportunity_type: Optional[str] = None
    stage: Optional[str] = None
    value_band: Optional[str] = None
    trigger_date: Optional[str] = None
    strategic_importance: Optional[int] = None
    status: Optional[str] = None
    owner: Optional[str] = None
    notes: Optional[str] = None


class ProfileBackgroundBackfillRequest(BaseModel):
    person_ids: Optional[List[str]] = None
    limit: Optional[int] = 200
    dry_run: Optional[bool] = False


def _now():
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    """Convert aiosqlite Row to dict and parse JSON fields."""
    d = dict(row)
    for field in ("employment_history", "personal_data", "cached_briefing", "action_items", "topics"):
        if field in d and isinstance(d[field], str) and d[field]:
            try:
                d[field] = json.loads(d[field])
            except Exception:
                pass
    return d


RELATIONSHIP_PRIORITY = {
    "referral": 4,
    "friend": 3,
    "colleague": 2,
    "mentioned": 1,
    "org_peer": 0,
}

RELATIONSHIP_PATTERNS = {
    "referral": (
        re.compile(r"\brefer(?:red|ral|ring)?\b", re.IGNORECASE),
        re.compile(r"\bintro(?:duced|duction)?\b", re.IGNORECASE),
        re.compile(r"\brecommend(?:ed|ation)?\b", re.IGNORECASE),
    ),
    "friend": (
        re.compile(r"\bfriend(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bmate(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bbuddy\b", re.IGNORECASE),
    ),
    "colleague": (
        re.compile(r"\bcolleague(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bcoworker(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bco-worker(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bteammate(?:s)?\b", re.IGNORECASE),
        re.compile(r"\bworks with\b", re.IGNORECASE),
        re.compile(r"\bworked with\b", re.IGNORECASE),
    ),
}


def _clean_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_company_name(value: Optional[str]) -> str:
    text = _clean_text(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _build_name_patterns(full_name: Optional[str]):
    cleaned = _clean_text(full_name)
    parts = [part for part in cleaned.split() if part]
    if not parts:
        return []

    patterns = []
    if len(parts) >= 2:
        patterns.append(r"\s+".join(re.escape(part) for part in parts))
        if len(parts) > 2:
            patterns.append(r"\s+".join((re.escape(parts[0]), re.escape(parts[-1]))))
    elif len(parts[0]) >= 6:
        patterns.append(re.escape(parts[0]))

    unique_patterns = list(dict.fromkeys(patterns))
    return [re.compile(rf"\b{pattern}\b", re.IGNORECASE) for pattern in unique_patterns]


def _classify_relationship_snippet(snippet: str) -> tuple[str, str]:
    for rel_type in ("referral", "friend", "colleague"):
        if any(pattern.search(snippet) for pattern in RELATIONSHIP_PATTERNS[rel_type]):
            if rel_type == "referral":
                return rel_type, "Referred in notes or interactions"
            if rel_type == "friend":
                return rel_type, "Marked as a friend in notes"
            return rel_type, "Mentioned as a colleague in notes"
    return "mentioned", "Mentioned in notes or interactions"


def _relationship_score(rel_type: str, *, same_company: bool = False, mentioned: bool = False) -> int:
    score = RELATIONSHIP_PRIORITY.get(rel_type, 0) * 10
    if same_company:
        score += 3
    if mentioned:
        score += 2
    return score


def _relationship_confidence(rel_type: str, *, same_company: bool = False, mentioned: bool = False) -> float:
    if rel_type == "referral":
        return 0.88
    if rel_type == "friend":
        return 0.8
    if rel_type == "colleague":
        return 0.72 if mentioned else 0.55
    if rel_type == "mentioned":
        return 0.56
    if rel_type == "org_peer":
        return 0.28 if same_company and not mentioned else 0.4
    return 0.4


def _build_relationship_segments(person: dict, interactions: List[dict]) -> list[str]:
    segments: list[str] = []
    for field in (
        "career_summary",
        "key_professional_notes",
        "key_personal_notes",
        "key_gossip_notes",
        "intel_notes",
    ):
        text = _clean_text(person.get(field))
        if text:
            segments.append(text)

    for interaction in interactions[:80]:
        for field in ("summary", "raw_text"):
            text = _clean_text(interaction.get(field))
            if text:
                segments.append(text)
    return segments


def _is_operational_interaction(interaction: dict) -> bool:
    channel = str(interaction.get("channel") or "").strip().lower()
    summary = normalize_signal_text(interaction.get("summary") or "")
    raw_text = normalize_signal_text(interaction.get("raw_text") or "")
    artifact_input_type = str(interaction.get("artifact_input_type") or "").strip().lower()
    active_signal_count = int(interaction.get("active_signal_count") or 0)

    if channel == "system_audit":
        return True
    if channel == "chat":
        lowered = f"{summary} {raw_text}".lower()
        operational_chat_markers = (
            "profile photo",
            "use this for the profile",
            "set this as the profile",
            "update the profile",
            "change the profile",
            "for the profile",
            "apply this photo",
        )
        if any(marker in lowered for marker in operational_chat_markers):
            return True
    if artifact_input_type == "profile_picture":
        return True
    if channel == "screenshot" and active_signal_count == 0 and summary.lower().startswith(("the image", "image processed", "this image")):
        return True
    if summary.lower() == "ai processing queued...":
        return True
    if raw_text.lower().startswith(("image uploaded:", "audio uploaded:", "document uploaded:", "uploaded file:")) and (
        not summary or summary.lower() == "ai processing queued..."
    ):
        return True
    return False


def _split_interactions(interactions: List[dict]) -> tuple[List[dict], List[dict]]:
    relationship_history = []
    system_activity = []
    for interaction in interactions:
        interaction["display_channel"] = infer_communication_channel(
            channel=interaction.get("channel"),
            summary=interaction.get("summary"),
            raw_text=interaction.get("raw_text"),
            extracted_text=interaction.get("extracted_text"),
            metadata=interaction.get("artifact_metadata"),
        )
        if _is_operational_interaction(interaction):
            system_activity.append(interaction)
        else:
            relationship_history.append(interaction)
    return relationship_history, system_activity


async def _derive_relationships(db, person_id: str, person: dict, interactions: List[dict]) -> list[dict]:
    subject_company = _normalize_company_name(person.get("company_name_raw"))
    segments = _build_relationship_segments(person, interactions)

    async with db.execute(
        """
        SELECT person_id, full_name, title_current, company_name_raw, profile_photo_url
        FROM PERSON
        WHERE is_active = 1 AND person_id != ?
        ORDER BY full_name COLLATE NOCASE
        """,
        (person_id,),
    ) as cursor:
        candidates = [dict(row) for row in await cursor.fetchall()]

    relationships = []
    for candidate in candidates:
        candidate_company = _normalize_company_name(candidate.get("company_name_raw"))
        same_company = bool(subject_company and candidate_company and candidate_company == subject_company)

        mention = None
        patterns = _build_name_patterns(candidate.get("full_name"))
        if patterns:
            for segment in segments:
                for pattern in patterns:
                    match = pattern.search(segment)
                    if not match:
                        continue
                    start = max(0, match.start() - 80)
                    end = min(len(segment), match.end() + 80)
                    snippet = segment[start:end]
                    rel_type, rel_reason = _classify_relationship_snippet(snippet)
                    score = RELATIONSHIP_PRIORITY.get(rel_type, 0)
                    if not mention or score > mention["priority"]:
                        mention = {
                            "type": rel_type,
                            "reason": rel_reason,
                            "excerpt": snippet,
                            "priority": score,
                        }
                    break
                if mention and mention["priority"] == RELATIONSHIP_PRIORITY["referral"]:
                    break

        if not same_company and not mention:
            continue

        if mention:
            primary_type = mention["type"]
            primary_reason = mention["reason"]
        elif same_company:
            primary_type = "org_peer"
            primary_reason = (
                f"Same company only: {candidate['company_name_raw']}"
                if candidate.get("company_name_raw")
                else "Same company only"
            )
        else:
            primary_type = "mentioned"
            primary_reason = "Mentioned in notes or interactions"

        if same_company and mention and primary_type == "mentioned":
            primary_type = "colleague"
            primary_reason = (
                f"Named in notes and shares {candidate['company_name_raw']}"
                if candidate.get("company_name_raw")
                else "Named in notes and shares the same company"
            )

        secondary_reasons = []
        if same_company:
            company_reason = (
                f"Same company: {candidate['company_name_raw']}"
                if candidate.get("company_name_raw")
                else "Same company"
            )
            if company_reason != primary_reason:
                secondary_reasons.append(company_reason)

        if mention and mention["reason"] != primary_reason:
            secondary_reasons.append(mention["reason"])

        relationships.append({
            "person_id": candidate["person_id"],
            "full_name": candidate.get("full_name"),
            "title_current": candidate.get("title_current"),
            "company_name_raw": candidate.get("company_name_raw"),
            "profile_photo_url": candidate.get("profile_photo_url"),
            "relationship_type": primary_type,
            "reason": primary_reason,
            "secondary_reasons": secondary_reasons,
            "same_company": same_company,
            "mentioned_in_inputs": bool(mention),
            "mention_excerpt": mention["excerpt"] if mention else None,
            "confidence": _relationship_confidence(primary_type, same_company=same_company, mentioned=bool(mention)),
            "link_basis": "same_company_and_mention" if same_company and mention else "mention" if mention else "same_company",
            "score": _relationship_score(primary_type, same_company=same_company, mentioned=bool(mention)),
        })

    relationships.sort(key=lambda item: (-item["score"], (item.get("full_name") or "").casefold()))
    return relationships[:10]


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("")
async def list_people(
    q: Optional[str] = Query(None),
    cat: Optional[str] = Query(None),
    env: Optional[str] = Query(None),
    disc: Optional[str] = Query(None),
    meeting_status: Optional[str] = Query(None),
    contact_value: Optional[str] = Query(None),
    limit: int = Query(200, le=500),
    offset: int = Query(0),
):
    """Search and filter contacts. All parameters are optional and combinable."""
    sql = """
        SELECT person_id, full_name, title_current, company_name_raw,
               email_primary, phone_primary, linkedin_url,
               cat, env, disc, contact_value, engagement_status,
               profile_photo_url, meeting_status, next_contact_due_date,
               last_contact_datetime, is_active, is_ts_advisory_candidate,
               network_tier, maintenance_mode, relationship_owner, decision_role,
               influence_scope, strategic_value_score, influence_score,
               future_option_score, coverage_risk_score, opportunity_readiness_score,
               relationship_confidence_score, last_meaningful_contact_at,
               last_inbound_at, last_outbound_at, unanswered_outbound_count,
               reactivation_trigger_notes, account_priority, tier_rationale,
               career_summary, key_professional_notes, created_at, last_updated_at
        FROM PERSON WHERE is_active = 1
    """
    params = []

    if q and q.strip():
        sql += " AND (full_name LIKE ? OR company_name_raw LIKE ? OR title_current LIKE ? OR email_primary LIKE ?)"
        t = f"%{q.strip()}%"
        params.extend([t, t, t, t])
    if cat and cat != "All":
        sql += " AND cat = ?"
        params.append(cat)
    if env and env != "All":
        sql += " AND env = ?"
        params.append(env)
    if disc and disc != "All":
        sql += " AND disc = ?"
        params.append(disc)
    if meeting_status and meeting_status != "All":
        sql += " AND meeting_status = ?"
        params.append(meeting_status)
    if contact_value and contact_value != "All":
        sql += " AND contact_value = ?"
        params.append(contact_value)

    sql += " ORDER BY last_updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with get_db() as db:
        async with db.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        async with db.execute("SELECT COUNT(*) FROM PERSON WHERE is_active=1") as c:
            total = (await c.fetchone())[0]

    return {"total": total, "people": [_row_to_dict(r) for r in rows]}


@router.post("")
async def create_person(person: PersonCreate):
    """Create a new contact. Returns existing person if name+company match found."""
    now = _now()
    pid = str(uuid.uuid4())

    async def _create(db):
        async with db.execute(
            "SELECT person_id FROM PERSON WHERE full_name=? AND company_name_raw=?",
            (person.full_name, person.company_name_raw)
        ) as cur:
            existing = await cur.fetchone()
        if existing:
            return {"status": "exists", "person_id": existing["person_id"]}

        await db.execute("""
            INSERT INTO PERSON (
                person_id, full_name, title_current, company_name_raw,
                email_primary, email_secondary, phone_primary, phone_secondary,
                linkedin_url, cat, env, disc, contact_value,
                career_summary, key_professional_notes, key_personal_notes,
                profile_photo_url, network_tier, maintenance_mode, relationship_owner,
                decision_role, influence_scope, account_priority, tier_rationale,
                created_at, last_updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (pid, person.full_name, person.title_current, person.company_name_raw,
              person.email_primary, person.email_secondary, person.phone_primary,
              person.phone_secondary, person.linkedin_url, person.cat, person.env,
              person.disc, person.contact_value, person.career_summary,
              person.key_professional_notes, person.key_personal_notes,
              person.profile_photo_url, person.network_tier, person.maintenance_mode,
              person.relationship_owner, person.decision_role, person.influence_scope,
              person.account_priority, person.tier_rationale, now, now))
        return {"status": "created", "person_id": pid}

    result = await run_write(_create, label=f"create person {person.full_name}")
    if result.get("status") == "created":
        try:
            await backfill_missing_profile_background(person_ids=[result.get("person_id")], limit=1, dry_run=False)
        except Exception as exc:
            print(f"Background backfill skipped for {result.get('person_id')}: {exc}")
    return result


@router.post("/background/backfill")
async def backfill_profile_background(req: ProfileBackgroundBackfillRequest):
    limit = int(req.limit or 200)
    limit = max(1, min(limit, 5000))
    result = await backfill_missing_profile_background(
        person_ids=req.person_ids,
        limit=limit,
        dry_run=bool(req.dry_run),
    )
    return {"status": "success", **result}

@router.get("/stats")
async def get_stats():
    """Dashboard counters."""
    async with get_db() as db:
        stats = {}
        async with db.execute("SELECT COUNT(*) FROM PERSON WHERE is_active=1") as c:
            stats["total_contacts"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM INTERACTION") as c:
            stats["total_interactions"] = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM TASK WHERE status IN ('open', 'in_progress')") as c:
            stats["open_tasks"] = (await c.fetchone())[0]
        async with db.execute(
            "SELECT meeting_status, COUNT(*) as cnt FROM PERSON WHERE is_active=1 AND meeting_status IS NOT NULL GROUP BY meeting_status"
        ) as c:
            rows = await c.fetchall()
            for row in rows:
                stats[f"meeting_{row['meeting_status']}"] = row["cnt"]
        async with db.execute(
            "SELECT cat, COUNT(*) as cnt FROM PERSON WHERE is_active=1 GROUP BY cat"
        ) as c:
            rows = await c.fetchall()
            stats["by_cat"] = {r["cat"]: r["cnt"] for r in rows if r["cat"]}
    return stats


@router.get("/{person_id}/relationships")
async def get_person_relationships(person_id: str):
    async with get_db() as db:
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as c:
            row = await c.fetchone()
        if not row:
            raise HTTPException(404, "Person not found")
        person = _row_to_dict(row)

        async with db.execute("""
            SELECT i.interaction_id, i.channel, i.raw_text, i.summary, i.action_items,
                   i.topics, i.sentiment, i.media_url, i.created_at, i.interaction_at,
                   a.input_type AS artifact_input_type, a.extracted_text, a.extracted_metadata_json,
                   (
                     SELECT COUNT(*) FROM TOPIC_INTELLIGENCE t
                     WHERE t.source_interaction_id = i.interaction_id
                       AND COALESCE(t.status, 'draft') NOT IN ('rejected', 'archived')
                   ) +
                   (
                     SELECT COUNT(*) FROM AI_SIGNAL s
                     WHERE s.source_interaction_id = i.interaction_id
                       AND COALESCE(s.review_state, 'pending_review') != 'rejected'
                       AND COALESCE(s.included_in_brief, 1) = 1
                   ) AS active_signal_count
            FROM INTERACTION i
            LEFT JOIN AI_ARTIFACT a ON a.source_interaction_id = i.interaction_id
            WHERE i.person_id=? AND i.channel != 'system_audit'
            ORDER BY interaction_at DESC LIMIT 80
        """, (person_id,)) as c:
            interactions = [_row_to_dict(r) for r in await c.fetchall()]
            for interaction in interactions:
                try:
                    interaction["artifact_metadata"] = json.loads(interaction.get("extracted_metadata_json") or "{}")
                except Exception:
                    interaction["artifact_metadata"] = {}

        relationship_history, _system_activity = _split_interactions(interactions)
        relationships = await _derive_relationships(db, person_id, person, relationship_history)

    return {"relationships": relationships}


@router.get("/{person_id}")
async def get_person(person_id: str):
    """Full person profile with interaction history and open tasks."""
    async with get_db() as db:
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as c:
            row = await c.fetchone()
        if not row:
            raise HTTPException(404, "Person not found")
        person = _row_to_dict(row)

        async with db.execute("""
            SELECT i.interaction_id, i.channel, i.raw_text, i.summary, i.action_items,
                   i.topics, i.sentiment, i.media_url, i.created_at, i.interaction_at,
                   a.input_type AS artifact_input_type, a.extracted_text, a.extracted_metadata_json,
                   (
                     SELECT COUNT(*) FROM TOPIC_INTELLIGENCE t
                     WHERE t.source_interaction_id = i.interaction_id
                       AND COALESCE(t.status, 'draft') NOT IN ('rejected', 'archived')
                   ) +
                   (
                     SELECT COUNT(*) FROM AI_SIGNAL s
                     WHERE s.source_interaction_id = i.interaction_id
                       AND COALESCE(s.review_state, 'pending_review') != 'rejected'
                       AND COALESCE(s.included_in_brief, 1) = 1
                   ) AS active_signal_count
            FROM INTERACTION i
            LEFT JOIN AI_ARTIFACT a ON a.source_interaction_id = i.interaction_id
            WHERE i.person_id=? AND i.channel != 'system_audit'
            ORDER BY interaction_at DESC LIMIT 50
        """, (person_id,)) as c:
            interactions = [_row_to_dict(r) for r in await c.fetchall()]
            for interaction in interactions:
                try:
                    interaction["artifact_metadata"] = json.loads(interaction.get("extracted_metadata_json") or "{}")
                except Exception:
                    interaction["artifact_metadata"] = {}

        async with db.execute("""
            SELECT task_id, task_text, due_date, due_time, priority, status, created_at
            FROM TASK WHERE person_id=? AND status IN ('open', 'in_progress') ORDER BY due_date ASC
        """, (person_id,)) as c:
            tasks = [dict(r) for r in await c.fetchall()]

        async with db.execute("""
            SELECT opportunity_id, account_name, opportunity_type, stage, value_band,
                   trigger_date, strategic_importance, status, owner, notes,
                   created_at, updated_at
            FROM PERSON_OPPORTUNITY
            WHERE person_id=?
            ORDER BY
                CASE WHEN status = 'open' THEN 0 ELSE 1 END,
                trigger_date ASC,
                updated_at DESC
        """, (person_id,)) as c:
            opportunities = [dict(r) for r in await c.fetchall()]

        relationship_history, system_activity = _split_interactions(interactions)
        intel = await load_profile_signals(person_id)
        relationships = await _derive_relationships(db, person_id, person, relationship_history)

    network_score_context = await get_network_contact_context(person_id)
    if network_score_context:
        person["network_score_context"] = network_score_context

    return {
        "person": person,
        "history": relationship_history,
        "system_activity": system_activity,
        "tasks": tasks,
        "opportunities": opportunities,
        "intelligence": intel,
        "relationships": relationships,
        "network_score_context": network_score_context,
    }


@router.patch("/{person_id}")
@router.put("/{person_id}")
async def update_person(person_id: str, req: PersonUpdate):
    """Partial update — only provided fields are updated."""
    fields, values = [], []
    data = req.model_dump(exclude_none=True)

    for field, value in data.items():
        if field == "is_ts_advisory_candidate":
            value = 1 if value else 0
        if isinstance(value, (list, dict)):
            value = json.dumps(value, ensure_ascii=False)
        fields.append(f"{field}=?")
        values.append(value)

    if not fields:
        return {"status": "no_change"}

    now = _now()
    fields.append("last_updated_at=?")
    values.append(now)
    values.append(person_id)

    audit_fields = {
        "cat", "env", "disc", "full_name", "company_name_raw", "title_current",
        "network_tier", "maintenance_mode", "relationship_owner", "decision_role",
        "influence_scope", "account_priority"
    }
    audit_entries = [f for f in data.keys() if f in audit_fields]

    async def _update(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=?", (person_id,)) as c:
            if not await c.fetchone():
                raise HTTPException(404, "Person not found")

        await db.execute(f"UPDATE PERSON SET {', '.join(fields)} WHERE person_id=?", values)

        for field in audit_entries:
            iid = str(uuid.uuid4())
            msg = f"Manual Update: {field.replace('_',' ').title()} -> '{data[field]}'"
            await db.execute("""
                INSERT INTO INTERACTION (interaction_id, person_id, channel, raw_text, summary, created_at, interaction_at)
                VALUES (?,?,?,?,?,?,?)
            """, (iid, person_id, "system_audit", msg, msg, now, now))

        await db.execute("UPDATE PERSON SET cached_briefing=NULL WHERE person_id=?", (person_id,))

    await run_write(_update, label=f"update person {person_id}")
    return {"status": "success"}


@router.get("/{person_id}/opportunities")
async def list_opportunities(person_id: str):
    async with get_db() as db:
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=? AND is_active=1", (person_id,)) as c:
            if not await c.fetchone():
                raise HTTPException(404, "Person not found")
        async with db.execute("""
            SELECT opportunity_id, account_name, opportunity_type, stage, value_band,
                   trigger_date, strategic_importance, status, owner, notes,
                   created_at, updated_at
            FROM PERSON_OPPORTUNITY
            WHERE person_id=?
            ORDER BY
                CASE WHEN status = 'open' THEN 0 ELSE 1 END,
                trigger_date ASC,
                updated_at DESC
        """, (person_id,)) as c:
            opportunities = [dict(r) for r in await c.fetchall()]
    return {"opportunities": opportunities}


@router.post("/{person_id}/opportunities")
async def create_opportunity(person_id: str, req: OpportunityCreate):
    now = _now()
    opportunity_id = str(uuid.uuid4())

    async def _create(db):
        async with db.execute("SELECT person_id FROM PERSON WHERE person_id=? AND is_active=1", (person_id,)) as c:
            if not await c.fetchone():
                raise HTTPException(404, "Person not found")

        await db.execute("""
            INSERT INTO PERSON_OPPORTUNITY (
                opportunity_id, person_id, account_name, opportunity_type, stage, value_band,
                trigger_date, strategic_importance, status, owner, notes, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            opportunity_id, person_id, req.account_name, req.opportunity_type, req.stage,
            req.value_band, req.trigger_date, req.strategic_importance, req.status,
            req.owner, req.notes, now, now
        ))

    await run_write(_create, label=f"create opportunity {person_id}")
    return {"status": "created", "opportunity_id": opportunity_id}


@router.patch("/{person_id}/opportunities/{opportunity_id}")
@router.put("/{person_id}/opportunities/{opportunity_id}")
async def update_opportunity(person_id: str, opportunity_id: str, req: OpportunityUpdate):
    data = req.model_dump(exclude_none=True)
    if not data:
        return {"status": "no_change"}

    fields = [f"{field}=?" for field in data.keys()]
    values = list(data.values())
    values.extend([_now(), opportunity_id, person_id])

    async def _update(db):
        async with db.execute(
            "SELECT opportunity_id FROM PERSON_OPPORTUNITY WHERE opportunity_id=? AND person_id=?",
            (opportunity_id, person_id),
        ) as c:
            if not await c.fetchone():
                raise HTTPException(404, "Opportunity not found")
        await db.execute(
            f"UPDATE PERSON_OPPORTUNITY SET {', '.join(fields)}, updated_at=? WHERE opportunity_id=? AND person_id=?",
            values,
        )

    await run_write(_update, label=f"update opportunity {opportunity_id}")
    return {"status": "success"}


@router.delete("/{person_id}/opportunities/{opportunity_id}")
async def delete_opportunity(person_id: str, opportunity_id: str):
    async def _delete(db):
        await db.execute(
            "DELETE FROM PERSON_OPPORTUNITY WHERE opportunity_id=? AND person_id=?",
            (opportunity_id, person_id),
        )

    await run_write(_delete, label=f"delete opportunity {opportunity_id}")
    return {"status": "success"}

@router.delete("/{person_id}")
async def deactivate_person(person_id: str):
    """Soft delete — marks as inactive, preserves all data."""
    async def _deactivate(db):
        await db.execute("UPDATE PERSON SET is_active=0, last_updated_at=? WHERE person_id=?",
                         (_now(), person_id))

    await run_write(_deactivate, label=f"deactivate person {person_id}")
    return {"status": "success"}

class IntelligenceUpdate(BaseModel):
    text: Optional[str] = None
    topic: Optional[str] = None
    business_subtopic: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[int] = None

@router.get("/{person_id}/intelligence")
async def get_intelligence(person_id: str):
    """4-quadrant intelligence databank for a person."""
    return await grouped_profile_signals(person_id, limit_per_category=18)

@router.patch("/{person_id}/intelligence/{intel_id}")
async def update_intelligence(person_id: str, intel_id: str, req: IntelligenceUpdate):
    """Edit or change status/category of a single intelligence point."""
    requested_updates = []
    feedback_tasks = []
    if req.text is not None:
        requested_updates.append(("intel_text=?", req.text))
        feedback_tasks.append(("edit", {"after_text": req.text}))
    if req.topic is not None:
        requested_updates.append(("topic=?", req.topic))
        feedback_tasks.append(("reclassify_category", {"after_category": req.topic}))
    if req.status is not None:
        requested_updates.append(("status=?", req.status))
        normalized = "approve" if req.status == "approved" else "reject" if req.status == "rejected" else None
        if normalized:
            feedback_tasks.append((normalized, {"reason_code": "status_change"}))
    if req.confidence is not None:
        requested_updates.append(("confidence=?", req.confidence))
    if not requested_updates and req.business_subtopic is None:
        raise HTTPException(400, "No fields to update")

    async def _update(db):
        async with db.execute("SELECT topic FROM TOPIC_INTELLIGENCE WHERE intel_id=?", (intel_id,)) as c:
            row = await c.fetchone()
        if not row:
            raise HTTPException(404, "Signal not found")
        active_topic = req.topic or row["topic"]
        fields = [field for field, _value in requested_updates]
        values = [value for _field, value in requested_updates]
        if req.topic is not None and req.topic != "business_focus":
            fields.append("business_subtopic=NULL")
        if req.business_subtopic is not None:
            subtopic = canonical_business_subtopic(req.business_subtopic) if active_topic == "business_focus" else None
            fields.append("business_subtopic=?")
            values.append(subtopic)
        if not fields:
            raise HTTPException(400, "No fields to update")
        values.append(intel_id)
        await db.execute(f"UPDATE TOPIC_INTELLIGENCE SET {', '.join(fields)} WHERE intel_id=?", tuple(values))
    await run_write(_update, label=f"update intelligence {intel_id}")
    await invalidate_briefs_for_profile(person_id)
    for event_type, details in feedback_tasks:
        await record_feedback_event(
            target_type="signal",
            target_id=intel_id,
            event_type=event_type,
            details={"source": "legacy_intelligence_patch", **details, "person_id": person_id},
        )
    return {"status": "updated"}



