"""
Antigravity CRM — Analytics Service (V2)
Handles high-performance aggregation for the Activities Dashboard.
"""
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
from backend.database import get_db


def _sentiment_ratio(value) -> float:
    raw = str(value or "").strip().lower()
    if raw == "positive":
        return 0.9
    if raw == "negative":
        return 0.1
    if raw == "mixed":
        return 0.5
    if raw == "neutral":
        return 0.55
    return 0.5

async def get_daily_activity_momentum() -> Dict[str, Any]:
    """
    Returns daily CRM activity split by Morning (Pre-1PM) and Afternoon (Post-1PM).
    Includes: Profile Creation, Notes, Intelligence Nuggets, and Channel Breakdown.
    """
    # Define time windows
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    split_time = now.replace(hour=13, minute=0, second=0, microsecond=0) # 1 PM
    
    start_iso = start_of_day.isoformat()
    split_iso = split_time.isoformat()
    end_iso = now.isoformat()

    async with get_db() as db:
        # 1. New People Created
        async with db.execute("""
            SELECT 
                COUNT(IIF(created_at < ?, 1, NULL)) as morning_count,
                COUNT(IIF(created_at >= ?, 1, NULL)) as afternoon_count
            FROM PERSON
            WHERE created_at >= ?
        """, (split_iso, split_iso, start_iso)) as c:
            people_stats = dict(await c.fetchone())

        # 2. Interactions by Type/Channel
        # This covers: voice, note (type), screenshot, email, etc.
        async with db.execute("""
            SELECT 
                channel,
                COUNT(IIF(interaction_at < ?, 1, NULL)) as morning_count,
                COUNT(IIF(interaction_at >= ?, 1, NULL)) as afternoon_count
            FROM INTERACTION
            WHERE interaction_at >= ?
            GROUP BY channel
        """, (split_iso, split_iso, start_iso)) as c:
            interaction_rows = [dict(r) for r in await c.fetchall()]

        # 3. Intelligence Nuggets (Topic Intelligence)
        async with db.execute("""
            SELECT 
                topic,
                COUNT(IIF(created_at < ?, 1, NULL)) as morning_count,
                COUNT(IIF(created_at >= ?, 1, NULL)) as afternoon_count
            FROM TOPIC_INTELLIGENCE
            WHERE created_at >= ?
            GROUP BY topic
        """, (split_iso, split_iso, start_iso)) as c:
            intel_rows = [dict(r) for r in await c.fetchall()]

        # 4. Success/Sentiment Trends
        async with db.execute("""
            SELECT 
                sentiment,
                COUNT(*) as count
            FROM INTERACTION
            WHERE interaction_at >= ?
            GROUP BY sentiment
        """, (start_iso,)) as c:
            sentiment_stats = {r['sentiment']: r['count'] for r in await c.fetchall()}

    return {
        "date": start_of_day.strftime("%Y-%m-%d"),
        "splits": {
            "morning_end": "13:00",
            "afternoon_start": "13:00"
        },
        "people": {
            "morning": people_stats['morning_count'],
            "afternoon": people_stats['afternoon_count']
        },
        "interactions": interaction_rows,
        "intelligence": intel_rows,
        "sentiment_summary": sentiment_stats,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

async def get_dynamic_categories():
    """Fetches active interaction categories from the taxonomy system."""
    async with get_db() as db:
        async with db.execute("""
            SELECT label, value, color 
            FROM CONFIG_TAXONOMY 
            WHERE category_type = 'cat' AND is_active = 1
        """) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

async def get_recent_intelligence(limit: int = 10):
    """Fetches the latest intelligence nuggets with sentiment data."""
    async with get_db() as db:
        async with db.execute("""
            SELECT t.intel_id, t.topic, t.intel_text, t.created_at, 
                   p.full_name, p.person_id,
                   i.sentiment as sentiment
            FROM TOPIC_INTELLIGENCE t
            JOIN PERSON p ON t.person_id = p.person_id
            LEFT JOIN INTERACTION i ON t.source_interaction_id = i.interaction_id
            ORDER BY t.created_at DESC
            LIMIT ?
        """, (limit,)) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]
    for row in rows:
        row["sentiment"] = _sentiment_ratio(row.get("sentiment"))
    return rows

async def get_category_sentiment():
    """Calculates sentiment distribution per category for the last 30 days."""
    async with get_db() as db:
        async with db.execute("""
            SELECT p.cat, i.sentiment, COUNT(*) as count
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE i.sentiment IS NOT NULL 
            AND i.interaction_at > date('now', '-30 days')
            GROUP BY p.cat, i.sentiment
        """) as cursor:
            rows = [dict(r) for r in await cursor.fetchall()]

    stats = {}
    for row in rows:
        cat = row['cat'] or 'GEN'
        stats.setdefault(cat, {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0, "unclear": 0, "total": 0})
        key = str(row['sentiment'] or 'unclear').lower()
        if key not in stats[cat]:
            key = 'unclear'
        stats[cat][key] += row['count']
        stats[cat]["total"] += row["count"]

    categories = []
    for cat, counts in stats.items():
        total = max(counts["total"], 1)
        weighted_positive = (
            (counts["positive"] * 1.0)
            + (counts["neutral"] * 0.55)
            + (counts["mixed"] * 0.5)
            + (counts["unclear"] * 0.45)
        ) / total
        confidence = (counts["positive"] + counts["negative"] + counts["neutral"] + counts["mixed"]) / total
        categories.append(
            {
                "category": cat,
                "label": cat,
                "sentiment": round(weighted_positive, 3),
                "confidence": round(confidence, 3),
                "counts": counts,
            }
        )
    categories.sort(key=lambda item: item["label"])
    return {"categories": categories}
