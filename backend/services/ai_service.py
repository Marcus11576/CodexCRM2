"""
Antigravity CRM — AI Service
All OpenAI calls live here. Clean, testable, no side effects.
"""
import json
import base64
import os
from typing import Optional
from backend.config import settings
from backend.database import get_sync_db, run_write
from backend.services.preference_learning import (
    EVENT_WEIGHTS,
    compute_preference_profile,
    normalize_feedback_event,
    preference_guidance_lines,
)

# --- PLATINUM PROTECTION WHITEMAP ---
# These are the ONLY fields AI is allowed to update directly on a Person record.
# Manual notes, gossip, and intel_notes are EXCLUDED to prevent data pollution.
ALLOWED_PROFILE_FIELDS = {
    "cat", "env", "disc", "contact_value", "title_current", 
    "company_name_raw", "email_primary", "phone_primary", "linkedin_url",
    "is_ts_advisory_candidate"
}

# Lazy-init client — only created when first needed
_client = None

def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _get_taxonomy_block() -> str:
    """Load live taxonomy from DB for AI context."""
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute("SELECT category_type, label, value FROM CONFIG_TAXONOMY WHERE is_active=1 ORDER BY category_type, display_order")
        rows = c.fetchall()
        conn.close()
        tax = {}
        for cat_type, label, value in rows:
            tax.setdefault(cat_type, []).append(f"{label} ({value})")
        lines = []
        for k, vals in tax.items():
            lines.append(f"{k.upper()}: {', '.join(vals)}")
        return "\n".join(lines)
    except Exception:
        return "CAT: OBE Member (OBE M), OBE Target (OBE T), TGT, EXT, HPC, GEN\nENV: Consultant, Developer - Gov, Developer - Semi-Gov, Developer - Private, Main Contractor\nDISC: Commercial, Delivery, Design, Corporate, Support Services"


def _get_success_calibration_block() -> str:
    """Load top 3 highest-rated interactions to calibrate AI success scoring."""
    try:
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute("""
            SELECT summary, metric_tags 
            FROM INTERACTION 
            WHERE is_strategic=1 AND success_rating=5 
            ORDER BY created_at DESC LIMIT 3
        """)
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return ""
            
        lines = ["HISTORICAL 'GAME-CHANGING WINS' FOR CALIBRATION:"]
        for summary, tags in rows:
            lines.append(f"- Summary: {summary} | Tags: {tags}")
        return "\n".join(lines) + "\n"
    except Exception as e:
        print(f"Calibration load error: {e}")
        return ""



async def process_text(text: str, channel: str, person_id: Optional[str] = None) -> dict:
    """
    Process raw interaction text with GPT-4o.
    Returns structured analysis: summary, topics, action_items, sentiment, topic_nuggets, profile_updates.
    """
    tax_block = _get_taxonomy_block()
    calibration_block = _get_success_calibration_block()

    prompt = f"""Analyze this CRM interaction and return a JSON object.

TAXONOMY (use ONLY these exact values for profile_updates):
{tax_block}

{calibration_block}
CHANNEL: {channel}
INTERACTION TEXT:
"{text[:8000]}"

Return JSON with these exact keys:
- summary: 1 sentence factual summary
- sentiment: positive | neutral | negative
- topics: array of up to 3 keyword strings
- action_items: array of follow-up task strings (empty if none)
- profile_updates: dict of field→value to update on the person's profile.
  Allowed fields: {', '.join(sorted(ALLOWED_PROFILE_FIELDS))}.
  (IMPORTANT: NEVER include manual notes or gossip here. Facts go to topic_nuggets.)
- topic_nuggets: array of intelligence objects (obe_focus | business_focus | recruitment_talent | family_personal).
- success_metrics: object with:
    - rating: 1-5 (1=low/admin, 3=meaningful, 5=game-changing win for TS/OBE)
    - engagement_value: 0-100 (weighted by depth/trust)
    - is_strategic: 0 or 1 (1 if moves the needle on recruitment, brand, or OBE network)
    - tags: array (e.g. "brand_win", "recruitment_lead", "obe_engagement")
- global_insights: array of knowledge items for the PLATFORM level (not just this person).
    - e.g. {{"type": "market_trend", "text": "Data centers in KSA are expanding", "entity": "KSA Data Centers"}}
    - e.g. {{"type": "company_shift", "text": "Stantec is shifting to BIM-first", "entity": "Stantec"}}
"""
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise CRM data extraction engine. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"AI text processing error: {e}")
        return {
            "summary": text[:200],
            "sentiment": "neutral",
            "topics": [],
            "action_items": [],
            "profile_updates": {},
            "topic_nuggets": [],
            "success_metrics": {},
            "global_insights": []
        }

async def realign_interaction(text: str, channel: str, feedback: str, person_id: Optional[str] = None) -> dict:
    """
    Re-processes raw interaction text incorporating explicit user feedback to correct hallucinations.
    """
    tax_block = _get_taxonomy_block()
    calibration_block = _get_success_calibration_block()

    prompt = f"""You are a precise CRM data extraction engine.
You previously analyzed the following interaction, but the user provided the following CORRECTIVE FEEDBACK:
"{feedback}"

You MUST re-analyze the text, strictly incorporating the user's feedback to correct any previous errors, hallucinations, or misdirections.

TAXONOMY (use ONLY these exact values for profile_updates):
{tax_block}

{calibration_block}
CHANNEL: {channel}
INTERACTION TEXT:
"{text[:8000]}"

Return JSON with these exact keys:
- summary: 1 sentence factual summary (adjusted by feedback)
- sentiment: positive | neutral | negative
- topics: array of up to 3 keyword strings
- action_items: array of follow-up strings (adjusted by feedback)
- profile_updates: object mapping taxonomy categories (cat, env, disc) to their STRICT exact value strings.
- topic_nuggets: array of {{topic, text, confidence}} for business_focus, recruitment_talent, family_personal, obe_focus
- success_metrics: object with rating (1-5), engagement_value (0-100), is_strategic (0/1), tags (array)
- global_insights: array of {{type, text, entity}} for platform-wide learning"""

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": prompt
            }],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"AI realign error: {e}")
        return {}


async def process_image(image_path: str, person_id: Optional[str] = None) -> dict:
    """Extract intelligence from a screenshot or photo using GPT-4o Vision."""
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(image_path)[1].lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

        client = _get_client()
        calibration_block = _get_success_calibration_block()
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"""Analyze this image (screenshot, business card, LinkedIn, WhatsApp, etc.).

{calibration_block}
Return JSON with:
- summary: What this image shows
- topics: key topics
- action_items: any follow-ups visible
- topic_nuggets: array of {{topic, text, confidence}} for business_focus, recruitment_talent, family_personal, obe_focus
- contact_info: {{name, email, phone, company, title, linkedin}} if visible
- is_profile_photo: true if the image contains a person's face, portrait, or headshot.
- success_metrics: object with rating (1-5), engagement_value (0-100), is_strategic (0/1), tags (array)
- global_insights: array of {{type, text, entity}} for platform-wide learning (market_trend, company_shift, etc.)"""},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                ]
            }],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        
        # Ensure strict boolean casting for profile photo
        photo_val = data.get("is_profile_photo", False)
        if isinstance(photo_val, str):
            data["is_profile_photo"] = photo_val.lower().strip() == "true"
        else:
            data["is_profile_photo"] = bool(photo_val)
            
        print(f"VISION AI RESULT: {data}")
        return data
    except Exception as e:
        print(f"Vision AI error: {e}")
        return {"summary": "Image uploaded", "topics": [], "action_items": [], "topic_nuggets": [], "is_profile_photo": False}


async def transcribe_audio(audio_path: str) -> str:
    """Transcribe audio file using OpenAI Whisper."""
    try:
        client = _get_client()
        with open(audio_path, "rb") as f:
            transcript = await client.audio.transcriptions.create(model="whisper-1", file=f)
        return transcript.text
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""


async def generate_tts(text: str, voice: str = "shimmer") -> bytes:
    """Generate MP3 audio from text using OpenAI TTS."""
    client = _get_client()
    response = await client.audio.speech.create(model="tts-1-hd", voice=voice, input=text[:4000], response_format="mp3")
    return response.content



async def compute_signal_scores(person_id: str) -> dict:
    """Compute a numeric score for each signal using explicit structured feedback plus learned preference weights."""
    scores = {}
    try:
        preference_profile = await compute_preference_profile(person_id)
        preference_scores = preference_profile.get("scores", {})
        conn = get_sync_db(read_only=True)
        c = conn.cursor()
        c.execute(
            """
            SELECT intel_id AS signal_id, topic AS category, intel_text AS content, created_at, 'topic_intelligence' AS source_kind
            FROM TOPIC_INTELLIGENCE
            WHERE person_id=?
            UNION ALL
            SELECT signal_id AS signal_id, category, content, created_at, 'ai_signal' AS source_kind
            FROM AI_SIGNAL
            WHERE person_id=?
            """,
            (person_id, person_id),
        )
        for signal_id, category, content, created_at, source_kind in c.fetchall():
            text = str(content or "")
            word_count = len(text.split())
            score = 0.0
            category_key = str(category or "").strip().lower()
            if category_key in {"business_focus", "recruitment_talent", "business focus", "recruitment & talent"}:
                score += preference_scores.get("commercially_useful_content", 0.0)
                score += preference_scores.get("practical_meeting_preparation", 0.0) * 0.5
            if category_key in {"family_personal", "obe_focus", "family & personal", "obe focus"}:
                score += preference_scores.get("relationship_relevant_content", 0.0)
            if word_count and word_count <= 35:
                score += preference_scores.get("concise_summaries", 0.0)
                score += preference_scores.get("minimal_fluff", 0.0)
            elif word_count >= 80:
                score -= abs(preference_scores.get("minimal_fluff", 0.0))
            scores[signal_id] = score

        c.execute(
            """
            SELECT target_id, event_type
            FROM AI_FEEDBACK
            WHERE target_type='signal' AND target_id IN (
                SELECT intel_id FROM TOPIC_INTELLIGENCE WHERE person_id=?
                UNION
                SELECT signal_id FROM AI_SIGNAL WHERE person_id=?
            )
            """,
            (person_id, person_id),
        )
        for target_id, event_type in c.fetchall():
            normalized = normalize_feedback_event(event_type)
            scores[target_id] = scores.get(target_id, 0.0) + EVENT_WEIGHTS.get(normalized, 0.0)
        conn.close()
    except Exception as e:
        print(f"Score computation error: {e}")
    return scores


async def review_signals(person: dict, signals: list, events: list) -> dict:
    """Review and summarise existing intelligence signals without changing source facts."""
    person_id = person.get("person_id")
    preference_profile = await compute_preference_profile(person_id) if person_id else {"scores": {}}
    if person_id:
        scores = await compute_signal_scores(person_id)
        signals = sorted(
            signals,
            key=lambda signal: (scores.get(signal.get("intel_id") or signal.get("signal_id"), 0), signal.get("date") or ""),
            reverse=True,
        )

    guidance = "\n".join(preference_guidance_lines(preference_profile))
    prompt = f"""You are an intelligence assistant reviewing stored CRM signals for a contact.
You may reorder, label, and compress the signals, but you must not silently change facts.
Hard rules:
- Preserve factual meaning from the stored signal text and source snippet.
- Do not invent names, dates, intent, deals, family details, or commitments.
- If a category is wrong, only correct the category, not the fact itself.
- If the source is ambiguous, keep the ambiguity visible.
- User edits, promotions, demotions, and manual additions override the AI and should stay visible.

Learned user preferences from behaviour:
{guidance}

For each signal, return:
- intel_id
- category
- text
- snippet
- concise_summary
- priority_reason

Then create a meeting brief using only confirmed source facts. Return valid JSON with EXACT keys 'signals' and 'brief'.
The brief must contain EXACT keys:
- business_focus
- recruitment_talent
- personal_rapport
- obe_focus
- strategic_hypotheses
- audio_script
"""
    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an elite relationship intelligence system. Return valid JSON only and never fabricate facts."},
                {"role": "user", "content": prompt},
                {"role": "user", "content": f"PERSON:\n{json.dumps(person)}"},
                {"role": "user", "content": f"SIGNALS:\n{json.dumps(signals)}"},
                {"role": "user", "content": f"EVENTS:\n{json.dumps(events)}"}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        result = json.loads(response.choices[0].message.content)
        result.setdefault("preference_profile", preference_profile)
        return result
    except Exception as e:
        print(f"Review signals error: {e}")
        return {"signals": signals, "brief": {"business_focus": "", "recruitment_talent": "", "personal_rapport": "", "obe_focus": "", "strategic_hypotheses": [], "audio_script": ""}, "preference_profile": preference_profile}

async def generate_briefing(person: dict, interactions: list, tasks: list, intel: dict, events: list = None, preference_profile: dict = None) -> dict:
    """
    Generate a world-class 5-section PA-style meeting brief.
    Returns structured JSON with sections the frontend renders.
    """
    tasks_text = "\n".join(f"- [Due {t.get('due_date', '')}] {t.get('task_text', '')}" for t in tasks) or "None."

    intel_text = ""
    for topic, items in intel.items():
        if items:
            intel_text += f"\n{topic.upper()}:\n"
            intel_text += "\n".join(
                f"  - {(item.get('intel_text') or item.get('text') or 'Fact missing')}"
                for item in items[:5]
            )

    events_text = ""
    if events:
        events_text = "\nUPCOMING EVENTS:\n" + "\n".join(
            f"- [{e['event_date'][:10]}] {e['event_name']} (status: {e.get('status', '')}) topics: {e.get('topics', '[]')}"
            for e in events
        )

    guidance = "\n".join(preference_guidance_lines(preference_profile or {"scores": {}}))
    prompt = f"""You are an elite personal assistant preparing a meeting brief.
Your goal is to provide a high-density strategic overview and test specific hypotheses.
You must not silently change facts. Only prioritise, compress, and organise what the stored signals, event context, and task context support.
If data is ambiguous, keep the ambiguity visible instead of filling gaps.
User edits, manual additions, promotions, and demotions override the AI ranking.

CONTACT: {person.get('full_name') or 'Unknown'} | {person.get('title_current') or 'Contact'} @ {person.get('company_name_raw') or 'Unknown'}
PROFILE: Cat={person.get('cat') or 'GEN'} | Env={person.get('env') or 'Other'} | Disc={person.get('disc') or 'Other'}

LEARNED USER PREFERENCES FROM BEHAVIOUR:
{guidance}

INTELLIGENCE DATABANK:
{intel_text or 'No intel recorded yet.'}
\nOPEN TASKS:
{tasks_text}

{events_text}

CORE HYPOTHESIS QUESTIONS TO ANSWER:
{settings.BRIEF_HYPOTHESIS_QUESTIONS}

Generate a structured meeting brief as JSON with these EXACT keys:
- business_focus: Strategic priorities, company wins, commercial remit and pipeline focus.
- recruitment_talent: Specific challenges and needs for "{settings.BRIEF_LABEL_RECRUITMENT}".
- personal_rapport: Family, hobbies, travel, values, lifestyle hooks that matter for the relationship.
- obe_focus: Relevant intelligence and opportunities regarding "{settings.BRIEF_LABEL_OBE}".
- strategic_hypotheses: Based on the Core Hypothesis Questions and databank, provide 3 testable theories or follow-up questions for this specific meeting.
- audio_script: A polished 60-second spoken brief for voice playback.

Prioritise concise summaries, commercially useful content, relationship-relevant context, minimal fluff, and practical meeting preparation."""

    try:
        client = _get_client()
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a precise, elite relationship intelligence system. Return valid JSON only. Never fabricate facts or silently overwrite user intent."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2
        )
        data = json.loads(response.choices[0].message.content)
        data["voice"] = settings.BRIEF_TTS_VOICE
        data["label_recruitment"] = settings.BRIEF_LABEL_RECRUITMENT
        data["label_obe"] = settings.BRIEF_LABEL_OBE
        data["preference_profile"] = preference_profile or {"scores": {}}
        return data
    except Exception as e:
        print(f"Briefing generation error: {e}")
        return {
            "business_focus": (person.get("key_professional_notes") or "No professional data recorded yet."),
            "recruitment_talent": "No hiring or team signals recorded yet.",
            "personal_rapport": (person.get("key_personal_notes") or "No personal rapport hooks recorded yet."),
            "obe_focus": (person.get("intel_notes") or "No OBE intelligence recorded yet."),
            "strategic_hypotheses": ["Ask a direct practical question to validate the highest-priority opportunity."],
            "audio_script": "Briefing unavailable right now.",
            "voice": settings.BRIEF_TTS_VOICE,
            "label_recruitment": settings.BRIEF_LABEL_RECRUITMENT,
            "label_obe": settings.BRIEF_LABEL_OBE,
            "preference_profile": preference_profile or {"scores": {}},
        }
async def profile_chat(person_id: str, person: dict, message: str, history: list) -> str:
    """
    Agentic profile assistant with function calling.
    Can update profile fields, create tasks, and answer questions about the contact.
    """
    import uuid
    from datetime import datetime, timezone

    tax_block = _get_taxonomy_block()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "update_profile",
                "description": "Update a field on this person's profile in the database.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": list(ALLOWED_PROFILE_FIELDS)
                        },
                        "value": {"type": "string"}
                    },
                    "required": ["field", "value"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "create_task",
                "description": "Create a follow-up task linked to this person.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "due_date": {"type": "string"},
                        "priority": {"type": "string", "enum": ["low", "medium", "high"]}
                    },
                    "required": ["title"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "log_intelligence",
                "description": "Save structured intelligence to the profile.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "enum": ["business_focus", "recruitment_talent", "family_personal", "obe_focus"]},
                        "text": {"type": "string"}
                    },
                    "required": ["topic", "text"]
                }
            }
        }
    ]

    system = f"""You are the Antigravity CRM Profile Assistant.
You are chatting about this contact:
Name: {person.get('full_name')}
Company: {person.get('company_name_raw')}
Title: {person.get('title_current')}
Category: {person.get('cat')}
Environment: {person.get('env')}
Discipline: {person.get('disc')}
Career Summary: {person.get('career_summary')}
Professional Notes: {person.get('key_professional_notes')}
Personal Notes: {person.get('key_personal_notes')}
Taxonomy:
{tax_block}

Use tools only when the user explicitly wants a profile update, task creation, or intelligence logging.
Otherwise answer conversationally and succinctly."""

    msgs = [{"role": "system", "content": system}]
    msgs.extend(history or [])
    msgs.append({"role": "user", "content": message})

    try:
        client = _get_client()
        response = await client.chat.completions.create(model="gpt-4o", messages=msgs, tools=tools)
        msg = response.choices[0].message

        if msg.tool_calls:
            msgs.append(msg)
            for tc in msg.tool_calls:
                fn = tc.function.name
                args = json.loads(tc.function.arguments)
                result = "Error"

                if fn == "update_profile":
                    field, value = args["field"], args["value"]

                    async def _update_profile(db):
                        await db.execute(
                            f"UPDATE PERSON SET {field}=?, last_updated_at=?, cached_briefing=NULL WHERE person_id=?",
                            (value, datetime.now(timezone.utc).isoformat(), person_id)
                        )

                    await run_write(_update_profile, label=f"chat update profile {person_id}")
                    result = f"Updated {field}"

                elif fn == "create_task":
                    tid = str(uuid.uuid4())
                    now = datetime.now(timezone.utc).isoformat()

                    async def _create_task(db):
                        await db.execute(
                            "INSERT INTO TASK (task_id, person_id, task_text, due_date, priority, status, created_at) VALUES (?,?,?,?,?,?,?)",
                            (tid, person_id, args["title"], args.get("due_date"), args.get("priority", "medium"), "open", now)
                        )

                    await run_write(_create_task, label=f"chat create task {person_id}")
                    result = f"Task created: {args['title']}"

                elif fn == "log_intelligence":
                    tid = str(uuid.uuid4())[:12]
                    now = datetime.now(timezone.utc).isoformat()

                    async def _log_intel(db):
                        await db.execute(
                            "INSERT INTO TOPIC_INTELLIGENCE (intel_id, person_id, topic, intel_text, confidence, created_at) VALUES (?,?,?,?,?,?)",
                            (tid, person_id, args["topic"], args["text"], 5, now)
                        )

                    await run_write(_log_intel, label=f"chat log intelligence {person_id}")
                    result = f"Logged {args['topic']}: {args['text']}"

                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            final = await client.chat.completions.create(model="gpt-4o", messages=msgs)
            return final.choices[0].message.content

        return msg.content
    except Exception as e:
        print(f"Chatbot AI error: {e}")
        return f"AI Service Error: {str(e)[:150]}. Please check your OpenAI API key in the Settings Dashboard and ensure your account has sufficient quota."

def extract_text_from_file(file_path: str) -> Optional[str]:
    """Extract text from PDF or TXT files."""
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(file_path)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            return text.strip()
        elif ext == ".txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
    except Exception as e:
        print(f"File extraction error: {e}")
    return None








