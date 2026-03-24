import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import get_db
from backend.services.network_orchestration_service import _load_relationship_score_context_map

router = APIRouter(prefix="/api/companies", tags=["Companies"])


def _normalize_company_key(value: str | None) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    return cleaned.lower()


def _score_for_person(row: dict[str, Any], score_map: dict[str, dict[str, Any]]) -> tuple[Optional[int], str]:
    person_id = str(row.get("person_id") or "")
    context = score_map.get(person_id) or {}
    rel_health = context.get("relationship_health_score")
    if rel_health is not None:
        try:
            return max(0, min(100, int(rel_health))), "relationship_intelligence"
        except (TypeError, ValueError):
            pass

    raw = row.get("relationship_health_score")
    if raw is None:
        return None, ""
    try:
        score = int(raw)
    except (TypeError, ValueError):
        return None, ""

    # Treat untouched default values as unknown where possible.
    if score == 50 and not str(row.get("last_health_refresh_at") or "").strip():
        return None, ""
    return max(0, min(100, score)), "person_profile"


async def _load_company_list_rows(query: str, limit: int, offset: int) -> tuple[int, list[dict[str, Any]]]:
    search = str(query or "").strip().lower()
    where_sql = ""
    params: list[Any] = []
    if search:
        like = f"%{search}%"
        where_sql = """
        WHERE (
            LOWER(COALESCE(cd.company_name, nr.company_name_raw)) LIKE ?
            OR LOWER(COALESCE(cd.company_type, '')) LIKE ?
            OR LOWER(cr.company_key) LIKE ?
            OR EXISTS (
                SELECT 1
                FROM COMPANY_ALIAS ca
                WHERE ca.company_key = cr.company_key
                  AND LOWER(ca.alias_name) LIKE ?
            )
        )
        """
        params.extend([like, like, like, like])

    async with get_db() as db:
        async with db.execute(
            f"""
            WITH person_companies AS (
                SELECT
                    LOWER(TRIM(company_name_raw)) AS company_key,
                    TRIM(company_name_raw) AS company_name_raw,
                    person_id
                FROM PERSON
                WHERE is_active = 1
                  AND TRIM(COALESCE(company_name_raw, '')) <> ''
            ),
            name_counts AS (
                SELECT company_key, company_name_raw, COUNT(*) AS variant_count
                FROM person_companies
                GROUP BY company_key, company_name_raw
            ),
            name_ranked AS (
                SELECT
                    company_key,
                    company_name_raw,
                    variant_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY company_key
                        ORDER BY variant_count DESC, LENGTH(company_name_raw) DESC, company_name_raw ASC
                    ) AS rn
                FROM name_counts
            ),
            company_rollup AS (
                SELECT company_key, COUNT(*) AS employee_count
                FROM person_companies
                GROUP BY company_key
            )
            SELECT COUNT(*) AS total_count
            FROM company_rollup cr
            JOIN name_ranked nr ON nr.company_key = cr.company_key AND nr.rn = 1
            LEFT JOIN COMPANY_DIRECTORY cd ON cd.company_key = cr.company_key
            {where_sql}
            """,
            tuple(params),
        ) as cursor:
            total_count = int((await cursor.fetchone())["total_count"])

        data_params = list(params) + [limit, offset]
        async with db.execute(
            f"""
            WITH person_companies AS (
                SELECT
                    LOWER(TRIM(company_name_raw)) AS company_key,
                    TRIM(company_name_raw) AS company_name_raw,
                    person_id
                FROM PERSON
                WHERE is_active = 1
                  AND TRIM(COALESCE(company_name_raw, '')) <> ''
            ),
            name_counts AS (
                SELECT company_key, company_name_raw, COUNT(*) AS variant_count
                FROM person_companies
                GROUP BY company_key, company_name_raw
            ),
            name_ranked AS (
                SELECT
                    company_key,
                    company_name_raw,
                    variant_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY company_key
                        ORDER BY variant_count DESC, LENGTH(company_name_raw) DESC, company_name_raw ASC
                    ) AS rn
                FROM name_counts
            ),
            company_rollup AS (
                SELECT company_key, COUNT(*) AS employee_count
                FROM person_companies
                GROUP BY company_key
            )
            SELECT
                cr.company_key,
                COALESCE(cd.company_name, nr.company_name_raw) AS company_name,
                COALESCE(cd.company_type, '') AS company_type,
                cd.parent_company_key,
                parent.company_name AS parent_company_name,
                cr.employee_count
            FROM company_rollup cr
            JOIN name_ranked nr ON nr.company_key = cr.company_key AND nr.rn = 1
            LEFT JOIN COMPANY_DIRECTORY cd ON cd.company_key = cr.company_key
            LEFT JOIN COMPANY_DIRECTORY parent ON parent.company_key = cd.parent_company_key
            {where_sql}
            ORDER BY cr.employee_count DESC, LOWER(COALESCE(cd.company_name, nr.company_name_raw)) ASC
            LIMIT ? OFFSET ?
            """,
            tuple(data_params),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]

    return total_count, rows


async def _load_people_for_company_keys(company_keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    keys = [str(key or "").strip() for key in company_keys if str(key or "").strip()]
    if not keys:
        return {}

    placeholders = ",".join(["?"] * len(keys))
    async with get_db() as db:
        async with db.execute(
            f"""
            SELECT
                person_id,
                full_name,
                title_current,
                company_name_raw,
                relationship_health AS relationship_health_score,
                last_health_refresh_at,
                LOWER(TRIM(company_name_raw)) AS company_key
            FROM PERSON
            WHERE is_active = 1
              AND LOWER(TRIM(COALESCE(company_name_raw, ''))) IN ({placeholders})
            ORDER BY full_name COLLATE NOCASE ASC
            """,
            tuple(keys),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]

    person_ids = [str(row.get("person_id") or "") for row in rows if str(row.get("person_id") or "").strip()]
    score_map = await _load_relationship_score_context_map(person_ids)

    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        company_key = str(row.get("company_key") or "").strip()
        if not company_key:
            continue
        score, score_source = _score_for_person(row, score_map)
        person_payload = {
            "person_id": row.get("person_id"),
            "full_name": row.get("full_name"),
            "title_current": row.get("title_current"),
            "company_name_raw": row.get("company_name_raw"),
            "score": score,
            "score_source": score_source,
        }
        by_key.setdefault(company_key, []).append(person_payload)

    for key in by_key:
        by_key[key].sort(
            key=lambda item: (
                -1 if item.get("score") is not None else 0,
                -(int(item.get("score") or 0)),
                str(item.get("full_name") or "").lower(),
            )
        )
    return by_key


def _enrich_company_rollup(company_rows: list[dict[str, Any]], employees_by_key: dict[str, list[dict[str, Any]]], *, preview_count: int = 3) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in company_rows:
        company_key = str(row.get("company_key") or "").strip()
        employees = employees_by_key.get(company_key, [])
        top_with_score = next((employee for employee in employees if employee.get("score") is not None), None)

        payload = {
            **row,
            "employee_count": int(row.get("employee_count") or 0),
            "highest_employee_score": int(top_with_score["score"]) if top_with_score and top_with_score.get("score") is not None else None,
            "highest_employee_score_source": top_with_score.get("score_source") if top_with_score else "",
            "top_employee": {
                "person_id": top_with_score.get("person_id"),
                "full_name": top_with_score.get("full_name"),
                "title_current": top_with_score.get("title_current"),
                "score": top_with_score.get("score"),
            } if top_with_score else None,
            "employees_preview": employees[:preview_count],
        }
        enriched.append(payload)
    return enriched


class CompanyUpdateRequest(BaseModel):
    company_name: Optional[str] = None
    company_type: Optional[str] = None
    parent_company_key: Optional[str] = None
    parent_company_name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    headquarters: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    aliases: Optional[list[str]] = Field(default=None)


@router.get("")
async def list_companies(
    q: Optional[str] = Query(None),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    total, rows = await _load_company_list_rows(query=q or "", limit=limit, offset=offset)
    employees_by_key = await _load_people_for_company_keys([row.get("company_key") for row in rows])
    companies = _enrich_company_rollup(rows, employees_by_key)
    return {"total": total, "companies": companies}


@router.get("/{company_key}")
async def get_company(company_key: str):
    normalized_key = _normalize_company_key(company_key)
    if not normalized_key:
        raise HTTPException(status_code=400, detail="Company key is required")

    employees_by_key = await _load_people_for_company_keys([normalized_key])
    employees = employees_by_key.get(normalized_key, [])

    async with get_db() as db:
        async with db.execute(
            """
            SELECT
                cd.company_key,
                cd.company_name,
                cd.company_type,
                cd.parent_company_key,
                parent.company_name AS parent_company_name,
                cd.industry,
                cd.website,
                cd.headquarters,
                cd.description,
                cd.notes,
                cd.created_at,
                cd.updated_at
            FROM COMPANY_DIRECTORY cd
            LEFT JOIN COMPANY_DIRECTORY parent ON parent.company_key = cd.parent_company_key
            WHERE cd.company_key = ?
            """,
            (normalized_key,),
        ) as cursor:
            directory_row = await cursor.fetchone()
        directory = dict(directory_row) if directory_row else None

        async with db.execute(
            """
            SELECT alias_name
            FROM COMPANY_ALIAS
            WHERE company_key = ?
            ORDER BY LOWER(alias_name) ASC
            """,
            (normalized_key,),
        ) as cursor:
            aliases = [str(row["alias_name"]) for row in await cursor.fetchall()]

        async with db.execute(
            """
            SELECT company_key, company_name, company_type
            FROM COMPANY_DIRECTORY
            WHERE parent_company_key = ?
            ORDER BY LOWER(company_name) ASC
            """,
            (normalized_key,),
        ) as cursor:
            children = [dict(row) for row in await cursor.fetchall()]

        async with db.execute(
            """
            SELECT
                company_opportunity_id,
                company_name_raw,
                opportunity_type,
                stage,
                value_band,
                trigger_date,
                strategic_importance,
                status,
                owner,
                notes,
                created_at,
                updated_at
            FROM COMPANY_OPPORTUNITY
            WHERE LOWER(TRIM(COALESCE(company_name_raw, ''))) = ?
            ORDER BY CASE WHEN COALESCE(status, 'open') = 'open' THEN 0 ELSE 1 END, trigger_date ASC, updated_at DESC
            """,
            (normalized_key,),
        ) as cursor:
            opportunities = [dict(row) for row in await cursor.fetchall()]

    if not directory and not employees:
        raise HTTPException(status_code=404, detail="Company not found")

    display_name = ""
    if directory and str(directory.get("company_name") or "").strip():
        display_name = str(directory.get("company_name") or "").strip()
    elif employees:
        # Keep the profile-facing name from employee records when no canonical override exists.
        display_name = str(employees[0].get("company_name_raw") or "").strip()

    top_with_score = next((employee for employee in employees if employee.get("score") is not None), None)

    company_payload = {
        "company_key": normalized_key,
        "company_name": display_name,
        "company_type": str((directory or {}).get("company_type") or ""),
        "parent_company_key": (directory or {}).get("parent_company_key"),
        "parent_company_name": (directory or {}).get("parent_company_name"),
        "industry": (directory or {}).get("industry"),
        "website": (directory or {}).get("website"),
        "headquarters": (directory or {}).get("headquarters"),
        "description": (directory or {}).get("description"),
        "notes": (directory or {}).get("notes"),
        "aliases": aliases,
        "employee_count": len(employees),
        "highest_employee_score": int(top_with_score["score"]) if top_with_score and top_with_score.get("score") is not None else None,
        "highest_employee_score_source": top_with_score.get("score_source") if top_with_score else "",
        "top_employee": {
            "person_id": top_with_score.get("person_id"),
            "full_name": top_with_score.get("full_name"),
            "title_current": top_with_score.get("title_current"),
            "score": top_with_score.get("score"),
        } if top_with_score else None,
        "children": children,
        "opportunities": opportunities,
        "employees": employees,
    }
    return {"company": company_payload}


@router.patch("/{company_key}")
@router.put("/{company_key}")
async def update_company(company_key: str, req: CompanyUpdateRequest):
    normalized_key = _normalize_company_key(company_key)
    if not normalized_key:
        raise HTTPException(status_code=400, detail="Company key is required")

    payload = req.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc).isoformat()

    async with get_db() as db:
        async with db.execute(
            """
            SELECT
                company_key,
                company_name,
                company_type,
                parent_company_key,
                industry,
                website,
                headquarters,
                description,
                notes,
                created_at
            FROM COMPANY_DIRECTORY
            WHERE company_key = ?
            """,
            (normalized_key,),
        ) as cursor:
            existing_row = await cursor.fetchone()
        existing = dict(existing_row) if existing_row else {}

        parent_input_provided = "parent_company_key" in payload or "parent_company_name" in payload
        if parent_input_provided:
            parent_key = payload.get("parent_company_key")
            parent_name = payload.get("parent_company_name")
            normalized_parent_key = _normalize_company_key(parent_key or parent_name)
        else:
            normalized_parent_key = _normalize_company_key(existing.get("parent_company_key"))

        if normalized_parent_key == normalized_key:
            raise HTTPException(status_code=400, detail="A company cannot be its own parent")

        effective_name = str(payload.get("company_name") or existing.get("company_name") or "").strip()
        if not effective_name:
            # Fall back to current PEOPLE display value when no canonical name is provided yet.
            async with db.execute(
                """
                SELECT TRIM(company_name_raw) AS company_name
                FROM PERSON
                WHERE is_active = 1
                  AND LOWER(TRIM(COALESCE(company_name_raw, ''))) = ?
                ORDER BY last_updated_at DESC
                LIMIT 1
                """,
                (normalized_key,),
            ) as cursor:
                name_row = await cursor.fetchone()
            effective_name = str((dict(name_row).get("company_name") if name_row else "") or "").strip()

        if not effective_name:
            raise HTTPException(status_code=400, detail="company_name is required for new company directory records")

        if parent_input_provided and normalized_parent_key:
            parent_display_name = str(payload.get("parent_company_name") or "").strip() or " ".join(word.capitalize() for word in normalized_parent_key.split())
            await db.execute(
                """
                INSERT INTO COMPANY_DIRECTORY (
                    company_key, company_name, created_at, updated_at
                ) VALUES (?,?,?,?)
                ON CONFLICT(company_key) DO UPDATE SET
                    company_name = COALESCE(NULLIF(EXCLUDED.company_name, ''), COMPANY_DIRECTORY.company_name),
                    updated_at = excluded.updated_at
                """,
                (normalized_parent_key, parent_display_name, now, now),
            )

        await db.execute(
            """
            INSERT INTO COMPANY_DIRECTORY (
                company_key, company_name, company_type, parent_company_key,
                industry, website, headquarters, description, notes,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(company_key) DO UPDATE SET
                company_name = excluded.company_name,
                company_type = excluded.company_type,
                parent_company_key = excluded.parent_company_key,
                industry = excluded.industry,
                website = excluded.website,
                headquarters = excluded.headquarters,
                description = excluded.description,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                normalized_key,
                effective_name,
                payload.get("company_type", existing.get("company_type")),
                normalized_parent_key if normalized_parent_key else None,
                payload.get("industry", existing.get("industry")),
                payload.get("website", existing.get("website")),
                payload.get("headquarters", existing.get("headquarters")),
                payload.get("description", existing.get("description")),
                payload.get("notes", existing.get("notes")),
                existing.get("created_at") or now,
                now,
            ),
        )

        aliases = payload.get("aliases")
        if aliases is not None:
            await db.execute("DELETE FROM COMPANY_ALIAS WHERE company_key = ?", (normalized_key,))
            unique_aliases: set[str] = set()
            for alias in aliases:
                alias_name = re.sub(r"\s+", " ", str(alias or "").strip())
                if not alias_name:
                    continue
                if _normalize_company_key(alias_name) == normalized_key:
                    continue
                alias_lc = alias_name.lower()
                if alias_lc in unique_aliases:
                    continue
                unique_aliases.add(alias_lc)
                alias_key = hashlib.sha1(f"{normalized_key}|{alias_lc}".encode("utf-8")).hexdigest()[:24]
                await db.execute(
                    """
                    INSERT INTO COMPANY_ALIAS (alias_key, company_key, alias_name, created_at, updated_at)
                    VALUES (?,?,?,?,?)
                    """,
                    (alias_key, normalized_key, alias_name, now, now),
                )

        await db.commit()

    return {"status": "success", "company_key": normalized_key}
