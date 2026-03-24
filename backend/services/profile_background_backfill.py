import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from backend.database import run_read, run_write


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_missing_text(value: Any) -> bool:
    return not _clean_text(value)


def _coerce_employment_history(value: Any) -> list[dict]:
    parsed = value
    if isinstance(parsed, str):
        raw = parsed.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []

    cleaned: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        role = {
            "title": _clean_text(item.get("title")),
            "company": _clean_text(item.get("company")),
            "start_date": _clean_text(item.get("start_date")),
            "end_date": _clean_text(item.get("end_date")),
            "location": _clean_text(item.get("location")),
            "description": _clean_text(item.get("description")),
        }
        if any(role.values()):
            cleaned.append(role)
    return cleaned


def _is_missing_history(value: Any) -> bool:
    return len(_coerce_employment_history(value)) == 0


def _seed_career_summary(full_name: str, title_current: str, company_name_raw: str) -> str:
    person_name = _clean_text(full_name) or "This contact"
    title = _clean_text(title_current)
    company = _clean_text(company_name_raw)
    if title and company:
        return f"{person_name} is currently {title} at {company}."
    if title:
        return f"{person_name} currently works as {title}."
    if company:
        return f"{person_name} is currently associated with {company}."
    return ""


def _seed_employment_history(title_current: str, company_name_raw: str) -> list[dict]:
    title = _clean_text(title_current)
    company = _clean_text(company_name_raw)
    if not title and not company:
        return []
    return [
        {
            "title": title,
            "company": company,
            "start_date": "",
            "end_date": "Present",
            "location": "",
            "description": "",
        }
    ]


def _planned_updates(person: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if _is_missing_text(person.get("career_summary")):
        seeded_summary = _seed_career_summary(
            full_name=person.get("full_name") or "",
            title_current=person.get("title_current") or "",
            company_name_raw=person.get("company_name_raw") or "",
        )
        if seeded_summary:
            updates["career_summary"] = seeded_summary

    if _is_missing_history(person.get("employment_history")):
        seeded_history = _seed_employment_history(
            title_current=person.get("title_current") or "",
            company_name_raw=person.get("company_name_raw") or "",
        )
        if seeded_history:
            updates["employment_history"] = seeded_history

    return updates


async def _load_candidates(person_ids: Optional[list[str]], limit: int) -> list[dict[str, Any]]:
    ids = [str(pid or "").strip() for pid in (person_ids or []) if str(pid or "").strip()]
    placeholders = ",".join(["?"] * len(ids))
    where_person_ids = f"AND p.person_id IN ({placeholders})" if ids else ""
    params: list[Any] = list(ids)
    params.append(max(1, int(limit)))

    async def _load(db):
        async with db.execute(
            f"""
            SELECT
                p.person_id,
                p.full_name,
                p.title_current,
                p.company_name_raw,
                p.career_summary,
                p.employment_history
            FROM PERSON p
            WHERE p.is_active = 1
              AND (
                    COALESCE(TRIM(p.career_summary), '') = ''
                    OR COALESCE(TRIM(p.employment_history), '') = ''
                    OR TRIM(COALESCE(p.employment_history, '')) = '[]'
              )
              {where_person_ids}
            ORDER BY p.last_updated_at DESC
            LIMIT ?
            """,
            tuple(params),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    return await run_read(_load, label="load profile background backfill candidates")


async def backfill_missing_profile_background(
    *,
    person_ids: Optional[list[str]] = None,
    limit: int = 200,
    dry_run: bool = False,
) -> dict[str, Any]:
    candidates = await _load_candidates(person_ids=person_ids, limit=limit)
    planned: list[dict[str, Any]] = []
    for person in candidates:
        updates = _planned_updates(person)
        if not updates:
            continue
        planned.append(
            {
                "person_id": person["person_id"],
                "full_name": person.get("full_name"),
                "updates": updates,
            }
        )

    updated_count = 0
    if planned and not dry_run:
        now = datetime.now(timezone.utc).isoformat()

        async def _apply(db):
            applied = 0
            for item in planned:
                updates = item["updates"]
                fields: list[str] = []
                values: list[Any] = []
                if "career_summary" in updates:
                    fields.append("career_summary = ?")
                    values.append(updates["career_summary"])
                if "employment_history" in updates:
                    fields.append("employment_history = ?")
                    values.append(json.dumps(updates["employment_history"], ensure_ascii=False))
                if not fields:
                    continue
                fields.append("last_updated_at = ?")
                values.append(now)
                values.append(item["person_id"])
                await db.execute(
                    f"UPDATE PERSON SET {', '.join(fields)} WHERE person_id = ?",
                    tuple(values),
                )
                applied += 1
            return applied

        updated_count = int(await run_write(_apply, label="backfill profile background"))

    return {
        "scanned": len(candidates),
        "planned_updates": len(planned),
        "updated": updated_count if not dry_run else 0,
        "dry_run": bool(dry_run),
        "sample": planned[:10],
    }
