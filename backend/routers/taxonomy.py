"""
Antigravity CRM — Taxonomy Router
Manage configurable taxonomy values (categories, environments, disciplines, etc.)
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database import get_db

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


class TaxonomyCreate(BaseModel):
    category_type: str   # cat | env | disc | contact_value | engagement_status
    label: str
    value: str
    color: Optional[str] = "#6b7280"
    display_order: Optional[int] = 99


class TaxonomyUpdate(BaseModel):
    label: Optional[str] = None
    value: Optional[str] = None
    color: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[int] = None


@router.get("")
async def get_taxonomy(category_type: Optional[str] = None):
    """Get active taxonomy values, optionally filtered by category_type."""
    sql = "SELECT * FROM CONFIG_TAXONOMY WHERE is_active=1"
    params = []
    if category_type:
        sql += " AND category_type=?"
        params.append(category_type)
    sql += " ORDER BY category_type, display_order, label"
    async with get_db() as db:
        async with db.execute(sql, params) as c:
            rows = await c.fetchall()
    return [dict(r) for r in rows]


@router.get("/all")
async def get_all_taxonomy(category_type: Optional[str] = None):
    """Get ALL taxonomy entries (including inactive) — for settings management."""
    sql = "SELECT * FROM CONFIG_TAXONOMY"
    params = []
    if category_type:
        sql += " WHERE category_type=?"
        params.append(category_type)
    sql += " ORDER BY category_type, display_order, label"
    async with get_db() as db:
        async with db.execute(sql, params) as c:
            rows = await c.fetchall()
    return [dict(r) for r in rows]


@router.post("")
async def add_taxonomy(item: TaxonomyCreate):
    config_id = str(uuid.uuid4())[:12]
    async with get_db() as db:
        await db.execute("""
            INSERT INTO CONFIG_TAXONOMY (config_id, category_type, label, value, color, display_order)
            VALUES (?,?,?,?,?,?)
        """, (config_id, item.category_type, item.label, item.value, item.color, item.display_order))
        await db.commit()
    return {"status": "created", "config_id": config_id}


@router.put("/{config_id}")
async def update_taxonomy(config_id: str, item: TaxonomyUpdate):
    fields, values = [], []
    data = item.model_dump(exclude_none=True)
    for k, v in data.items():
        fields.append(f"{k}=?")
        values.append(v)
    if not fields:
        return {"status": "no_change"}
    values.append(config_id)
    async with get_db() as db:
        await db.execute(f"UPDATE CONFIG_TAXONOMY SET {', '.join(fields)} WHERE config_id=?", values)
        await db.commit()
    return {"status": "updated"}


@router.delete("/{config_id}")
async def deactivate_taxonomy(config_id: str):
    """Soft-delete — preserves historical references."""
    async with get_db() as db:
        await db.execute("UPDATE CONFIG_TAXONOMY SET is_active=0 WHERE config_id=?", (config_id,))
        await db.commit()
    return {"status": "deactivated"}
