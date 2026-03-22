"""
Antigravity CRM — Intelligence V2 Router
Exposes the Strategist Service for non-disruptive testing.
"""
from fastapi import APIRouter, HTTPException
from backend.services.strategist_service import synthesize_strategic_intel

router = APIRouter(prefix="/api/v2/intelligence", tags=["intelligence-v2"])

@router.post("/synthesize/{person_id}")
async def run_synthesis(person_id: str):
    """
    Triggers a Platinum Synthesis for a specific contact.
    This does NOT replace the V1 brief, but creates a 'Strategic SIT-REP' 
    that can be viewed in the V2 dashboard.
    """
    try:
        return await synthesize_strategic_intel(person_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
