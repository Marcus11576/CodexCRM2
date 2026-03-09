"""
Antigravity CRM — Strategist Service (V2)
Higher-order relationship intelligence and pattern synthesis.
"""
import json
from datetime import datetime, timezone
from typing import Optional, List
from backend.config import settings
from backend.database import get_db
from backend.services.ai_service import _get_client, _get_taxonomy_block

async def synthesize_strategic_intel(person_id: str) -> dict:
    """
    Multi-stage intelligence synthesis.
    1. Retrieve deep context (all interactions, intel, tasks).
    2. Scan for platform-wide patterns (global memory).
    3. Generate high-density strategic hypotheses.
    """
    # 1. Gather Deep Context
    async with get_db() as db:
        # Get Person
        async with db.execute("SELECT * FROM PERSON WHERE person_id=?", (person_id,)) as c:
            person = dict(await c.fetchone())
        
        # Get Histroy (last 50)
        async with db.execute("SELECT * FROM INTERACTION WHERE person_id=? ORDER BY interaction_at DESC LIMIT 50", (person_id,)) as c:
            interactions = [dict(r) for r in await c.fetchall()]
            
        # Get Intelligence
        async with db.execute("SELECT * FROM TOPIC_INTELLIGENCE WHERE person_id=?", (person_id,)) as c:
            intel = [dict(r) for r in await c.fetchall()]

        # Get Global Context (Platform Memory) — Cross-contact patterns
        async with db.execute("SELECT * FROM PLATFORM_MEMORY ORDER BY strength DESC LIMIT 20") as c:
            global_mem = [dict(r) for r in await c.fetchall()]

    # Format context blocks
    history_text = "\n".join([f"- [{i['interaction_at'][:10]}] {i['summary'] or i['raw_text'][:200]}" for i in interactions])
    intel_text = "\n".join([f"- [{n['topic']}]: {n['intel_text']}" for n in intel])
    platform_context = "\n".join([f"- [{m['entity_ref']}]: {m['memory_text']}" for m in global_mem if m['entity_ref']])

    prompt = f"""You are the Antigravity 'Strategist' Agent. Your goal is to move beyond simple data extraction into deep relationship strategy.

=== SUBJECT PROFILE ===
NAME: {person['full_name']}
TITLE/COMPANY: {person['title_current']} @ {person['company_name_raw']}
CATEGORIZATION: {person['cat']} | {person['env']} | {person['disc']}

=== RELATIONSHIP HISTORY ===
{history_text or 'No history.'}

=== CURRENT INTELLIGENCE DATABANK ===
{intel_text or 'Empty.'}

=== GLOBAL MARKET CONTEXT (Pattern Synthesis) ===
{platform_context or 'No global patterns identified yet.'}

=== MISSION ===
1. Analyze the subject's stated goals vs. their actual behavior in interactions.
2. Identify intelligence gaps: What CRITICAL information is missing that prevents a 'Platinum' level of trust?
3. Strategic Hypotheses: Propose 3 non-obvious theories about what really motivates this person or what their next business move might be.
4. Connection Discovery: Based on the Global Context, are there any connections to companies or trends that this person hasn't mentioned, but should be aware of?

Return ONLY a JSON objects with these keys:
- behavioral_analysis: Analysis of goals vs behavior.
- intelligence_gaps: Array of specific things we need to find out.
- strategic_hypotheses: Array of 3 deep insights.
- platform_connections: Array of links to other companies/entities in our global memory.
- sitrep_brief: A 3-sentence high-density executive summary.
"""

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a master relationship strategist. You see patterns others miss. Return valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.4
        )
        result = json.loads(response.choices[0].message.content)
        
        # Save synthesis to person's profile as a system interaction
        await log_strategic_synthesis(person_id, result['sitrep_brief'])
        
        return result
    except Exception as e:
        print(f"Strategist Error: {e}")
        return {"error": str(e)}

async def log_strategic_synthesis(person_id: str, brief: str):
    """Logs the strategic synthesis as an interaction for historical tracking."""
    import uuid
    from datetime import datetime, timezone
    iid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    msg = f"Platinum Synthesis: {brief}"
    async with get_db() as db:
        await db.execute(
            "INSERT INTO INTERACTION (interaction_id, person_id, channel, summary, created_at, interaction_at, is_strategic) VALUES (?,?,?,?,?,?,?)",
            (iid, person_id, "system_audit", msg, now, now, 1)
        )
        await db.commit()
