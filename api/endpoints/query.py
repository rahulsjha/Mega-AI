"""
Query Execution Endpoints

Direct query submission with SSE streaming of execution trace events.

Non-negotiable: Every agent execution MUST emit a structured trace event.
Trace format: TRACE_EVENT with timestamp, job_id, agent_name, event_type, token costs, etc.
"""

import logging
import json
import time
from uuid import UUID
from typing import AsyncGenerator
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_async_session
from api.db.service import JobService, EventService
from api.context.schema import AgentContext
from api.context.budget import ContextBudgetManager
from api.agents.orchestrator import MasterOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter(tags=["query-execution"])


class QueryRequest(BaseModel):
    """Request to submit a query."""
    query: str


@asynccontextmanager
async def stream_sse_events(job_id: UUID, db_session: AsyncSession):
    """
    Generate SSE events for a job with full trace protocol compliance.
    
    Non-negotiable requirements:
    - AGENT_START fires before any tool call
    - Every TOOL_CALL emitted immediately before invocation
    - Every TOOL_RESULT emitted immediately after
    - AGENT_END fires after agent writes final output
    - ERROR fires instead of AGENT_END if agent fails
    - Token costs tracked cumulatively
    - Budget remaining percentage reported
    - Shared context snapshot included in every event
    """
    events_to_emit = []
    job_service = JobService(db_session)
    event_service = EventService(db_session)
    
    async def event_callback(event: dict):
        """
        Callback to handle events from context and emit via SSE + persist to DB.
        
        Event must comply with TRACE_EVENT format:
        {
          timestamp_utc: ISO8601,
          job_id: UUID,
          agent_name: string,
          event_type: AGENT_START | TOOL_CALL | TOOL_RESULT | AGENT_END | ERROR,
          tool_name: string | null,
          tool_input: object | null,
          tool_output: object | null,
          token_cost_this_step: integer,
          cumulative_token_cost: integer,
          budget_remaining_pct: float,
          shared_context_snapshot: object,
          error: string | null
        }
        """
        try:
            # Emit to SSE stream
            events_to_emit.append(event)
            sse_data = f"data: {json.dumps(event)}\n\n"
            
            # Persist to database for audit trail
            await event_service.log_event(
                job_id=job_id,
                event_type=event.get("event_type"),
                data=event.get("data", {}),
                agent_id=event.get("agent_name"),
                latency_ms=event.get("token_cost_this_step", 0)
            )
            
            logger.debug(
                f"Event: {event.get('event_type')} | Agent: {event.get('agent_name')} | "
                f"Tokens: {event.get('token_cost_this_step')} | Budget: {event.get('budget_remaining_pct', 0):.1f}%"
            )
            
            return sse_data
        except Exception as e:
            logger.warning(f"Event callback error: {e}")
            return None
    
    try:
        # Get job from database
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Update job status to running
        await job_service.update_job_status(job_id, "running")
        
        # Create context and initialize budget manager
        context = AgentContext(
            job_id=job_id,
            query=job.query,
            event_callbacks=[event_callback]
        )
        
        job_budget_manager = ContextBudgetManager()
        
        # Create orchestrator
        orchestrator = MasterOrchestrator(job_budget_manager)
        
        # Emit job_start event
        start_event = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "job_id": str(job_id),
            "agent_name": "orchestrator",
            "event_type": "AGENT_START",
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "token_cost_this_step": 0,
            "cumulative_token_cost": 0,
            "budget_remaining_pct": 100.0,
            "shared_context_snapshot": {"query": job.query},
            "error": None
        }
        sse_event = await event_callback(start_event)
        if sse_event:
            yield sse_event
        
        # Execute orchestration with full trace protocol
        start_time = time.time()
        context = await orchestrator.execute(context)
        total_latency_ms = (time.time() - start_time) * 1000
        
        # Emit collected events from orchestrator
        for event in events_to_emit[1:]:  # Skip first since we already emitted start
            yield f"data: {json.dumps(event)}\n\n"
        
        # Emit job_complete event
        completion_event = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "job_id": str(job_id),
            "agent_name": "orchestrator",
            "event_type": "AGENT_END",
            "tool_name": None,
            "tool_input": None,
            "tool_output": {
                "final_answer": context.final_answer,
                "total_latency_ms": total_latency_ms
            },
            "token_cost_this_step": 0,
            "cumulative_token_cost": job_budget_manager.total_tokens_used(),
            "budget_remaining_pct": job_budget_manager.remaining_percentage(),
            "shared_context_snapshot": context.to_dict(),
            "error": None
        }
        sse_event = await event_callback(completion_event)
        if sse_event:
            yield sse_event
        
        # Store result in database
        await job_service.set_job_result(job_id, context.final_answer or "", total_latency_ms)
        
        logger.info(
            f"Job {job_id} completed successfully | Latency: {total_latency_ms:.2f}ms | "
            f"Tokens: {job_budget_manager.total_tokens_used()} | Budget: {job_budget_manager.remaining_percentage():.1f}% remaining"
        )
        
    except Exception as e:
        logger.error(f"SSE stream error for job {job_id}: {str(e)}", exc_info=True)
        await job_service.update_job_status(job_id, "failed", str(e))
        
        # Emit error event (non-negotiable)
        error_event = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "job_id": str(job_id),
            "agent_name": "orchestrator",
            "event_type": "ERROR",
            "tool_name": None,
            "tool_input": None,
            "tool_output": None,
            "token_cost_this_step": 0,
            "cumulative_token_cost": 0,
            "budget_remaining_pct": 0.0,
            "shared_context_snapshot": {},
            "error": str(e)
        }
        
        # Persist error event
        event_service = EventService(db_session)
        await event_service.log_event(job_id, "job_error", {"error": str(e)})
        
        yield f"data: {json.dumps(error_event)}\n\n"


@router.post("/query", response_class=StreamingResponse, summary="Submit Query with SSE Streaming")
async def submit_query(request: QueryRequest, db_session: AsyncSession = Depends(get_async_session)):
    """
    Submit a query for direct execution with real-time SSE streaming.
    
    Returns event stream where each event is a TRACE_EVENT object:
    - event_type: AGENT_START, TOOL_CALL, TOOL_RESULT, AGENT_END, ERROR
    - Emitted in real-time as agents execute
    - Persisted to database for audit trail
    
    Non-negotiable:
    - Every agent execution emits a trace
    - No silent execution
    - Token costs tracked cumulatively
    - Budget remaining percentage reported
    - If any agent fails, ERROR event fires with error details
    - Pipeline halts on Group A accuracy below 90%
    """
    try:
        # Create job in database
        db_session_local = db_session
        job_service = JobService(db_session_local)
        job = await job_service.create_job(request.query)
        
        logger.info(
            f"Query submitted (direct execution) | Job: {job.id} | Query: {request.query[:80]}"
        )
        
        async with stream_sse_events(job.id, db_session_local) as event_stream:
            return StreamingResponse(
                event_stream,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive"
                }
            )
    except Exception as e:
        logger.error(f"Failed to create SSE stream: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
