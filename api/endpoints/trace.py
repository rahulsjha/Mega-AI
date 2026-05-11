"""
Trace and Event Retrieval Endpoints

Complete execution trace retrieval from database with structured event format.

Non-negotiable: Every agent execution trace is persisted and retrievable.
Trace events follow TRACE_EVENT format with full metadata.
"""

import logging
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_async_session
from api.db.service import JobService, EventService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["trace-retrieval"])


class TraceEvent(BaseModel):
    """A single event in the execution trace."""
    timestamp: datetime
    event_type: str
    agent_id: str | None = None
    data: dict


class TraceResponse(BaseModel):
    """Complete execution trace."""
    job_id: UUID
    query: str
    events: list[TraceEvent]
    final_answer: str | None = None
    status: str


@router.get("/trace/{job_id}", response_model=TraceResponse, summary="Get Execution Trace")
async def get_trace(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)) -> TraceResponse:
    """
    Get complete execution trace for a job from database.
    
    Returns full ordered sequence of all TRACE_EVENT objects that fired during execution.
    
    Event types:
    - AGENT_START: Agent beginning execution
    - TOOL_CALL: Tool being invoked
    - TOOL_RESULT: Tool execution result
    - AGENT_END: Agent finished, output written to context
    - ERROR: Agent failed
    - COMPRESSION_REPORT: Compression agent fired (additional metadata)
    
    Trace includes:
    - Chronological event sequence
    - Token costs per step
    - Cumulative budget tracking
    - Agent routing decisions
    - Tool selections
    - Error information if present
    
    Non-negotiable:
    - Events ordered by timestamp
    - No events dropped or filtered
    - All agent executions accounted for
    - Error events included for failed pipelines
    - If job still running, return 202 Accepted
    - If job not found, return 404 Not Found
    
    Returns:
        {
            "job_id": UUID,
            "query": original query string,
            "events": [TRACE_EVENT objects in chronological order],
            "final_answer": synthesis agent output (null if incomplete),
            "status": "queued" | "running" | "completed" | "failed"
        }
    """
    try:
        job_service = JobService(db_session)
        event_service = EventService(db_session)
        
        # Get job from database
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Check if still running
        if job.status == "queued" or job.status == "running":
            raise HTTPException(status_code=202, detail="Job still running")
        
        # Get all events from database (ordered by timestamp)
        events_from_db = await event_service.get_job_events(job_id)
        
        # Convert DB events to TraceEvent objects
        events = []
        for event in events_from_db:
            events.append(TraceEvent(
                timestamp=event.created_at,
                event_type=event.event_type,
                agent_id=event.agent_id,
                data=event.data
            ))
        
        logger.info(
            f"Trace retrieved | Job: {job_id} | Events: {len(events)} | Status: {job.status}"
        )
        
        return TraceResponse(
            job_id=job.id,
            query=job.query,
            events=events,
            final_answer=job.final_answer,
            status=job.status
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving trace: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/{job_id}", summary="Get Job Event Logs")
async def stream_job_logs(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)):
    """
    Get live event logs for a job with optional filtering.
    
    Returns all events with metadata:
    - timestamp: When event occurred
    - event_type: Agent/tool/error event
    - agent_id: Which agent fired (null for orchestrator)
    - data: Event-specific payload
    - latency_ms: Execution time for this step
    
    Non-negotiable:
    - Events ordered by timestamp (earliest first)
    - All events included (no filtering except by job_id)
    - Latency accurate to milliseconds
    - Null events not included (all events must have valid data)
    - If job not found, return 404
    
    Returns:
        {
            "job_id": UUID,
            "total_events": integer,
            "events": [
                {
                    "timestamp": ISO8601,
                    "event_type": string,
                    "agent_id": string,
                    "data": object,
                    "latency_ms": float
                }
            ]
        }
    """
    try:
        job_service = JobService(db_session)
        event_service = EventService(db_session)
        
        # Verify job exists
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Get all events for the job
        events = await event_service.get_job_events(job_id)
        
        logger.info(
            f"Event logs retrieved | Job: {job_id} | Total events: {len(events)}"
        )
        
        return {
            "job_id": str(job.id),
            "total_events": len(events),
            "events": [
                {
                    "timestamp": e.created_at.isoformat(),
                    "event_type": e.event_type,
                    "agent_id": e.agent_id,
                    "data": e.data,
                    "latency_ms": e.latency_ms
                }
                for e in events
            ]
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job logs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
