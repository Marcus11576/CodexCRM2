"""
Antigravity CRM — Analytics V2 Router
Exposes high-density activity and momentum data for the dashboard.
"""
from fastapi import APIRouter, HTTPException
import backend.services.analytics_service as analytics_service

router = APIRouter(prefix="/api/v2/analytics", tags=["analytics-v2"])

@router.get("/momentum")
async def get_momentum():
    return await analytics_service.get_daily_activity_momentum()

@router.get("/categories")
async def get_categories():
    return await analytics_service.get_dynamic_categories()

@router.get("/recent-intel")
async def get_recent_intel(limit: int = 10):
    return await analytics_service.get_recent_intelligence(limit)

@router.get("/category-trends")
async def get_category_trends():
    return await analytics_service.get_category_sentiment()
