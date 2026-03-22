from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

from backend.database import get_db

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

KNOWN_CATEGORY_VALUES = ("OBE M", "OBE T", "TGT", "EXT", "HPC", "GEN")
BULK_PROFILE_THRESHOLD = 10


def _parse_date_param(value: str | None, *, default: date) -> date:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.") from exc


def _resolve_date_range(start_date: str | None, end_date: str | None, *, default_days: int = 30) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    end = _parse_date_param(end_date, default=today)
    start_default = end - timedelta(days=default_days)
    start = _parse_date_param(start_date, default=start_default)
    if start > end:
        raise HTTPException(status_code=400, detail="start_date must be before or equal to end_date")
    return start, end


def _comparison_range(start: date, end: date) -> tuple[date, date]:
    span_days = max((end - start).days + 1, 1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=span_days - 1)
    return previous_start, previous_end


def _real_profile_filter(alias: str = "p", *, exclude_bulk_batches: bool = False) -> str:
    clauses = [
        f"COALESCE(LOWER({alias}.person_id), '') NOT LIKE 'm365-test-person-%'",
        f"COALESCE(LOWER({alias}.email_primary), '') NOT LIKE '%@example.com'",
        f"COALESCE(LOWER({alias}.created_at), '') <> 'now'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE 'test%'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '% test%'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '%sample%'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE 'qa %'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '% qa %'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '%codex%'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '% bot%'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '%drag person%'",
        f"COALESCE(LOWER({alias}.full_name), '') NOT LIKE '%verify%'",
    ]
    if exclude_bulk_batches:
        clauses.append(
            f"""COALESCE({alias}.created_at, '') NOT IN (
                SELECT created_at
                FROM PERSON
                WHERE COALESCE(created_at, '') <> ''
                GROUP BY created_at
                HAVING COUNT(*) >= {BULK_PROFILE_THRESHOLD}
            )"""
        )
    return " AND ".join(f"({clause})" for clause in clauses)


def _channel_group_sql(alias: str = "i") -> str:
    return f"""
        CASE
            WHEN lower(trim({alias}.channel)) = 'email' THEN 'email'
            WHEN lower(trim({alias}.channel)) = 'whatsapp' THEN 'whatsapp'
            WHEN lower(trim({alias}.channel)) IN ('call', 'mobile', 'phone') THEN 'call'
            WHEN lower(trim({alias}.channel)) IN ('meeting', 'face to face', 'teams') THEN 'meeting'
            ELSE NULL
        END
    """


def _profile_category_sql(alias: str = "p") -> str:
    category_values = ", ".join(f"'{value}'" for value in KNOWN_CATEGORY_VALUES)
    return f"""
        CASE
            WHEN TRIM(COALESCE({alias}.cat, '')) IN ({category_values}) THEN TRIM({alias}.cat)
            WHEN TRIM(COALESCE({alias}.cat, '')) = '' THEN 'UNCATEGORISED'
            ELSE 'OTHER'
        END
    """


@router.get("/success-report")
async def get_success_report(days: int = 30):
    """Returns top strategic wins and engagement trends."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT i.interaction_id, i.summary, i.success_rating, i.metric_tags, p.full_name, i.interaction_at
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE i.is_strategic = 1
              AND i.created_at > ?
            ORDER BY i.success_rating DESC, i.created_at DESC
            """,
            ((datetime.now() - timedelta(days=days)).isoformat(),),
        ) as c:
            wins = [dict(r) for r in await c.fetchall()]

    return {
        "top_wins": wins,
        "period_days": days,
    }


@router.get("/network-pulse")
async def get_network_pulse():
    """Aggregates market sentiment and identifies the 'Hot' areas of the network."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT memory_type, entity_ref, memory_text, strength, last_reinforced
            FROM PLATFORM_MEMORY
            WHERE strength > 1
            ORDER BY strength DESC, last_reinforced DESC
            LIMIT 10
            """
        ) as c:
            trends = [dict(r) for r in await c.fetchall()]

        async with db.execute(
            """
            SELECT company_name_raw, COUNT(*) as hit_count, AVG(success_rating) as avg_success
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE company_name_raw IS NOT NULL
            GROUP BY company_name_raw
            HAVING hit_count > 2
            ORDER BY hit_count DESC, avg_success DESC
            LIMIT 5
            """
        ) as c:
            hot_companies = [dict(r) for r in await c.fetchall()]

    return {
        "trends": trends,
        "hot_companies": hot_companies,
        "pulse_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/influence-matrix")
async def get_influence_matrix():
    """Identified key nodes in the network based on strategic value."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT p.person_id, p.full_name, p.company_name_raw, p.cat,
                   COUNT(i.interaction_id) as strategic_interactions,
                   SUM(i.engagement_value) as total_engagement
            FROM PERSON p
            LEFT JOIN INTERACTION i ON p.person_id = i.person_id
            WHERE i.is_strategic = 1 OR p.cat IN ('OBE M', 'OBE T')
            GROUP BY p.person_id
            ORDER BY total_engagement DESC, strategic_interactions DESC
            LIMIT 20
            """
        ) as c:
            nodes = [dict(r) for r in await c.fetchall()]

    return {"matrix": nodes}


@router.get("/propensity/{person_id}")
async def get_person_propensity(person_id: str):
    """Calculates engagement health and next best action for a specific person."""
    async with get_db() as db:
        async with db.execute(
            """
            SELECT relationship_health, engagement_velocity, peak_engagement_time, next_best_action
            FROM PERSON WHERE person_id = ?
            """,
            (person_id,),
        ) as c:
            row = await c.fetchone()

        if not row:
            raise HTTPException(404, "Person not found")

        async with db.execute(
            """
            SELECT COUNT(*) FROM INTERACTION
            WHERE person_id = ? AND interaction_at > ?
            """,
            (person_id, (datetime.now() - timedelta(days=14)).isoformat()),
        ) as c:
            count = (await c.fetchone())[0]

    return {
        "health": row["relationship_health"],
        "velocity": row["engagement_velocity"],
        "recent_hits_14d": count,
        "peak_time": row["peak_engagement_time"],
        "next_best_action": row["next_best_action"] or "Initiate high-value catchup",
    }


@router.get("/effort-stats")
async def get_effort_stats(start_date: str = None, end_date: str = None, cat: str = None):
    """
    Returns normalized human interaction volume by channel and day, plus period totals.
    Automated/system channels are excluded so the page reflects real relationship effort.
    """
    start, end = _resolve_date_range(start_date, end_date)
    comparison_start, comparison_end = _comparison_range(start, end)
    channel_group_sql = _channel_group_sql("i")
    category_sql = _profile_category_sql("p")
    profile_filter = _real_profile_filter("p")
    cat_clause = f" AND {category_sql} = ?" if cat else ""
    params: list[str] = [start.isoformat(), end.isoformat()]
    comparison_params: list[str] = [comparison_start.isoformat(), comparison_end.isoformat()]
    if cat:
        params.append(cat)
        comparison_params.append(cat)

    summary_query = f"""
        WITH normalized AS (
            SELECT {channel_group_sql} AS channel_group
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE date(datetime(i.interaction_at)) BETWEEN date(?) AND date(?)
              AND {profile_filter}
              {cat_clause}
        )
        SELECT channel_group AS channel, COUNT(*) AS count
        FROM normalized
        WHERE channel_group IS NOT NULL
        GROUP BY channel_group
    """

    graph_query = f"""
        WITH normalized AS (
            SELECT date(datetime(i.interaction_at)) AS day,
                   {channel_group_sql} AS channel_group
            FROM INTERACTION i
            JOIN PERSON p ON i.person_id = p.person_id
            WHERE date(datetime(i.interaction_at)) BETWEEN date(?) AND date(?)
              AND {profile_filter}
              {cat_clause}
        )
        SELECT day, channel_group AS channel, COUNT(*) AS count
        FROM normalized
        WHERE channel_group IS NOT NULL
        GROUP BY day, channel_group
        ORDER BY day ASC
    """

    async with get_db() as db:
        async with db.execute(summary_query, tuple(params)) as c:
            summary_rows = [dict(r) for r in await c.fetchall()]

        async with db.execute(graph_query, tuple(params)) as c:
            graph_rows = [dict(r) for r in await c.fetchall()]

        async with db.execute(summary_query, tuple(comparison_params)) as c:
            comparison_rows = [dict(r) for r in await c.fetchall()]

    totals = {row["channel"]: row["count"] for row in summary_rows}
    comparison_totals = {row["channel"]: row["count"] for row in comparison_rows}

    return {
        "totals": totals,
        "comparison_totals": comparison_totals,
        "daily_breakdown": graph_rows,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "comparison_start_date": comparison_start.isoformat(),
        "comparison_end_date": comparison_end.isoformat(),
        "cat_filter": cat,
    }


@router.get("/profile-growth-stats")
async def get_profile_growth_stats(start_date: str = None, end_date: str = None):
    """
    Returns manually-added profile counts by category within a date range.
    Bulk imports/migrations and obvious synthetic records are excluded so the
    page reflects genuine profile growth rather than setup/test noise.
    """
    start, end = _resolve_date_range(start_date, end_date)
    category_sql = _profile_category_sql("p")
    profile_filter = _real_profile_filter("p", exclude_bulk_batches=True)
    range_params = (start.isoformat(), end.isoformat())

    async with get_db() as db:
        async with db.execute(
            f"""
            WITH grouped AS (
                SELECT {category_sql} AS cat_key, COUNT(*) AS count
                FROM PERSON p
                WHERE date(datetime(p.created_at)) BETWEEN date(?) AND date(?)
                  AND datetime(p.created_at) IS NOT NULL
                  AND {profile_filter}
                GROUP BY cat_key
            )
            SELECT
                grouped.cat_key AS cat,
                COALESCE(
                    t.label,
                    CASE
                        WHEN grouped.cat_key = 'UNCATEGORISED' THEN 'Uncategorised'
                        ELSE 'Other'
                    END
                ) AS label,
                COALESCE(
                    t.color,
                    CASE
                        WHEN grouped.cat_key = 'UNCATEGORISED' THEN '#94a3b8'
                        ELSE '#64748b'
                    END
                ) AS color,
                grouped.count AS count
            FROM grouped
            LEFT JOIN CONFIG_TAXONOMY t
              ON grouped.cat_key = t.value
             AND t.category_type = 'cat'
            ORDER BY grouped.count DESC, grouped.cat_key ASC
            """,
            range_params,
        ) as c:
            rows = [dict(r) for r in await c.fetchall()]

        async with db.execute(
            """
            SELECT COUNT(*) AS count
            FROM PERSON p
            WHERE date(datetime(p.created_at)) BETWEEN date(?) AND date(?)
              AND datetime(p.created_at) IS NOT NULL
            """,
            range_params,
        ) as c:
            raw_total = (await c.fetchone())["count"]

    included_total = sum(row["count"] for row in rows)
    return {
        "stats": rows,
        "total_profiles": included_total,
        "excluded_profiles": max(raw_total - included_total, 0),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
