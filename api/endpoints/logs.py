"""
Event Logs Endpoints

Real-time event streaming and historical log retrieval.
Complements trace retrieval with real-time capabilities.

Note: See trace.py for full trace retrieval endpoint (/trace/{job_id})
This module focuses on real-time and filtering capabilities.
"""

import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_async_session
from api.db.service import JobService, EventService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["event-logs"])


@router.get("/logs/{job_id}", summary="Get Job Event Logs", include_in_schema=False)
async def stream_job_logs(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)):
    from api.endpoints.trace import stream_job_logs as trace_stream_job_logs
    return await trace_stream_job_logs(job_id, db_session)
