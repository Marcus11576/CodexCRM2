from fastapi import APIRouter, Depends, HTTPException
from backend.database import get_db
from datetime import datetime, timedelta
import json

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.get("/success-report")
async def get_success_report(days: int = 30):
    """Returns top strategic wins and engagement trends."""
    async with get_db() as db:
        async with db.execute("""
            SELECT i.interaction_id, i.summary, i.success_rating, i.metric_tags, p.full_name, i.interaction_at
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE i.is_strategic = 1
            AND i.created_at > ?
            ORDER BY i.success_rating DESC, i.created_at DESC
        """, ( (datetime.now() - timedelta(days=days)).isoformat(), )) as c:
            wins = [dict(r) for r in await c.fetchall()]
            
        return {
            "top_wins": wins,
            "period_days": days
        }

@router.get("/network-pulse")
async def get_network_pulse():
    """Aggregates market sentiment and identifies the 'Hot' areas of the network."""
    async with get_db() as db:
        # Trending Memories
        async with db.execute("""
            SELECT memory_type, entity_ref, memory_text, strength, last_reinforced
            FROM PLATFORM_MEMORY
            WHERE strength > 1
            ORDER BY strength DESC, last_reinforced DESC
            LIMIT 10
        """) as c:
            trends = [dict(r) for r in await c.fetchall()]
            
        # Hot Companies (based on interaction volume and success)
        async with db.execute("""
            SELECT company_name_raw, COUNT(*) as hit_count, AVG(success_rating) as avg_success
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE company_name_raw IS NOT NULL
            GROUP BY company_name_raw
            HAVING hit_count > 2
            ORDER BY hit_count DESC, avg_success DESC
            LIMIT 5
        """) as c:
            hot_companies = [dict(r) for r in await c.fetchall()]
            
        return {
            "trends": trends,
            "hot_companies": hot_companies,
            "pulse_at": datetime.now(timezone.utc).isoformat()
        }

@router.get("/influence-matrix")
async def get_influence_matrix():
    """Identified key nodes in the network based on strategic value."""
    async with get_db() as db:
        async with db.execute("""
            SELECT p.person_id, p.full_name, p.company_name_raw, p.cat,
                   COUNT(i.interaction_id) as strategic_interactions,
                   SUM(i.engagement_value) as total_engagement
            FROM PERSON p
            LEFT JOIN INTERACTION i ON p.person_id = i.person_id
            WHERE i.is_strategic = 1 OR p.cat IN ('OBE M', 'OBE T')
            GROUP BY p.person_id
            ORDER BY total_engagement DESC, strategic_interactions DESC
            LIMIT 20
        """) as c:
            nodes = [dict(r) for r in await c.fetchall()]
            
        return { "matrix": nodes }

@router.get("/propensity/{person_id}")
async def get_person_propensity(person_id: str):
    """Calculates engagement health and next best action for a specific person."""
    async with get_db() as db:
        async with db.execute("""
            SELECT relationship_health, engagement_velocity, peak_engagement_time, next_best_action
            FROM PERSON WHERE person_id = ?
        """, (person_id,)) as c:
            row = await c.fetchone()
        
        if not row:
            raise HTTPException(404, "Person not found")
        
        # Calculate recent velocity shift
        async with db.execute("""
            SELECT COUNT(*) FROM INTERACTION 
            WHERE person_id = ? AND interaction_at > ?
        """, (person_id, (datetime.now() - timedelta(days=14)).isoformat())) as c:
            count = (await c.fetchone())[0]
            
        return {
            "health": row["relationship_health"],
            "velocity": row["engagement_velocity"],
            "recent_hits_14d": count,
            "peak_time": row["peak_engagement_time"],
            "next_best_action": row["next_best_action"] or "Initiate high-value catchup"
        }
@router.get("/effort-stats")
async def get_effort_stats(start_date: str = None, end_date: str = None, cat: str = None):
    """
    Returns interaction volume by channel and day, plus period totals.
    Filtered by date range and optional category.
    """
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = datetime.now().isoformat()
    
    # 1. Total counts for summary cards
    summary_query = """
        SELECT i.channel, COUNT(*) as count
        FROM INTERACTION i
        JOIN PERSON p ON i.person_id = p.person_id
        WHERE i.interaction_at BETWEEN ? AND ?
    """
    params = [start_date, end_date]
    if cat:
        summary_query += " AND p.cat = ?"
        params.append(cat)
    summary_query += " GROUP BY i.channel"
    
    # 2. Daily breakdown for the graph
    graph_query = """
        SELECT date(i.interaction_at) as day, i.channel, COUNT(*) as count
        FROM INTERACTION i
        JOIN PERSON p ON i.person_id = p.person_id
        WHERE i.interaction_at BETWEEN ? AND ?
    """
    if cat:
        graph_query += " AND p.cat = ?"
    graph_query += " GROUP BY day, i.channel ORDER BY day ASC"
    
    async with get_db() as db:
        async with db.execute(summary_query, tuple(params)) as c:
            summary_rows = [dict(r) for r in await c.fetchall()]
        
        async with db.execute(graph_query, tuple(params)) as c:
            graph_rows = [dict(r) for r in await c.fetchall()]
            
    # Format summary into a dict for easier frontend consumption
    totals = {row["channel"]: row["count"] for row in summary_rows}
    
    return {
        "totals": totals,
        "daily_breakdown": graph_rows,
        "start_date": start_date,
        "end_date": end_date,
        "cat_filter": cat
    }

@router.get("/profile-growth-stats")
async def get_profile_growth_stats(start_date: str = None, end_date: str = None):
    """
    Returns new profile counts by category within a date range.
    """
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).isoformat()
    if not end_date:
        end_date = datetime.now().isoformat()
        
    async with get_db() as db:
        async with db.execute("""
            SELECT p.cat, t.label, t.color, COUNT(*) as count
            FROM PERSON p
            LEFT JOIN CONFIG_TAXONOMY t ON p.cat = t.value AND t.category_type = 'cat'
            WHERE p.created_at BETWEEN ? AND ?
            GROUP BY p.cat
        """, (start_date, end_date)) as c:
            rows = [dict(r) for r in await c.fetchall()]
            
    return {
        "stats": rows,
        "start_date": start_date,
        "end_date": end_date
    }
