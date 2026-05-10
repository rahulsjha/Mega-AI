"""
FastAPI main application with all endpoints and SSE streaming.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import UUID, uuid4
import json
import os
from datetime import datetime
from typing import Optional, AsyncGenerator

from api.logging_config import setup_logging, StructuredLogger
from api.db.database import setup_db, init_db
from api.context.schema import AgentContext
from api.context.budget import ContextBudgetManager
from api.agents.orchestrator import MasterOrchestrator

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


# =====================
# Request/Response Models
# =====================

class QueryRequest(BaseModel):
    """Request to submit a query."""
    query: str


class QueryResponse(BaseModel):
    """Response from query submission."""
    job_id: UUID
    message: str


class TraceEvent(BaseModel):
    """A single event in the execution trace."""
    timestamp: datetime
    event_type: str
    agent_id: Optional[str] = None
    data: dict


class TraceResponse(BaseModel):
    """Complete execution trace."""
    job_id: UUID
    query: str
    events: list[TraceEvent]
    final_answer: Optional[str] = None
    status: str


class EvalResult(BaseModel):
    """Single evaluation result."""
    score: float
    justification: str
    test_case_id: str


class EvalSummary(BaseModel):
    """Summary of latest eval run."""
    run_timestamp: datetime
    group_a_scores: dict[str, EvalResult]
    group_b_scores: dict[str, EvalResult]
    group_c_scores: dict[str, EvalResult]


class ApprovalRequest(BaseModel):
    """Request to approve a prompt proposal."""
    proposal_id: str
    decision: str  # "approve" or "reject"
    reviewer_notes: Optional[str] = None


# =====================
# Lifecycle Events
# =====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("API starting up")
    setup_db()
    await init_db()
    yield
    # Shutdown
    logger.info("API shutting down")


# =====================
# Create FastAPI App
# =====================

app = FastAPI(
    title="Mega AI - Multi-Agent Orchestrator",
    description="Production-grade multi-agent LLM orchestration system",
    version="1.0.0",
    lifespan=lifespan
)


# =====================
# Global State
# =====================

budget_manager = ContextBudgetManager()
orchestrator_instance: Optional[MasterOrchestrator] = None

# Shared state for jobs (in production would be in database)
jobs_state = {}


# =====================
# Helper Functions
# =====================

async def stream_sse_events(job_id: UUID) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for a job.
    
    Yields event data in SSE format.
    """
    try:
        # Create context and orchestrator
        context = AgentContext(
            job_id=job_id,
            query=jobs_state[str(job_id)]["query"]
        )
        
        # Initialize budget manager for this job
        job_budget_manager = ContextBudgetManager()
        
        # Create orchestrator
        orchestrator = MasterOrchestrator(job_budget_manager)
        
        # Emit start event
        yield f"data: {json.dumps({'event': 'job_start', 'data': {'job_id': str(job_id)}})}\n\n"
        
        # Execute orchestration
        context = await orchestrator.execute(context)
        
        # Emit completion event
        completion_data = {
            "event": "done",
            "data": {
                "job_id": str(job_id),
                "final_answer": context.final_answer,
                "total_latency_ms": (context.completed_at - context.started_at).total_seconds() * 1000
                                    if context.completed_at else 0
            }
        }
        yield f"data: {json.dumps(completion_data)}\n\n"
        
        # Store result
        jobs_state[str(job_id)]["status"] = "completed"
        jobs_state[str(job_id)]["result"] = context
        
    except Exception as e:
        logger.error(f"SSE stream error for job {job_id}: {str(e)}")
        error_data = {
            "event": "error",
            "data": {
                "job_id": str(job_id),
                "error": str(e)
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"
        jobs_state[str(job_id)]["status"] = "failed"
        jobs_state[str(job_id)]["error"] = str(e)


# =====================
# API Endpoints
# =====================

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/query", response_class=StreamingResponse)
async def submit_query(request: QueryRequest):
    """
    Submit a query and stream execution events via SSE.
    
    Returns SSE stream with events:
    - agent_start: agent starting
    - token: token from agent output
    - tool_call: tool being called
    - agent_done: agent finished
    - budget_update: budget changed
    - done: orchestration complete
    """
    job_id = uuid4()
    
    logger.info(
        f"Query submitted",
        extra={
            "job_id": str(job_id),
            "query": request.query[:50]
        }
    )
    
    # Store job info
    jobs_state[str(job_id)] = {
        "query": request.query,
        "status": "running",
        "started_at": datetime.utcnow()
    }
    
    try:
        return StreamingResponse(
            stream_sse_events(job_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error(f"Failed to create SSE stream: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/trace/{job_id}")
async def get_trace(job_id: UUID) -> TraceResponse:
    """
    Get complete execution trace for a job.
    
    Returns full ordered sequence of agent decisions, tool calls, and outputs.
    """
    job_id_str = str(job_id)
    
    if job_id_str not in jobs_state:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    job_data = jobs_state[job_id_str]
    
    if job_data.get("status") == "running":
        raise HTTPException(status_code=202, detail="Job still running")
    
    if "result" not in job_data:
        raise HTTPException(status_code=404, detail="No result available")
    
    context: AgentContext = job_data["result"]
    
    # Build trace events from context
    events = []
    
    # Add routing decisions
    for i, decision in enumerate(context.routing_history):
        events.append(TraceEvent(
            timestamp=context.started_at,  # Approximate
            event_type="routing_decision",
            agent_id="orchestrator",
            data={
                "next_agent": decision.next_agent,
                "justification": decision.justification,
                "confidence": decision.confidence,
                "iteration": i + 1
            }
        ))
    
    # Add tool calls
    for tool_call in context.tool_call_log:
        events.append(TraceEvent(
            timestamp=tool_call.called_at,
            event_type="tool_call",
            agent_id=tool_call.called_by_agent,
            data={
                "tool_name": tool_call.tool_name,
                "latency_ms": tool_call.latency_ms,
                "attempt": tool_call.attempt_number,
                "accepted": tool_call.accepted
            }
        ))
    
    # Add critique results
    for critique in context.critique_results:
        events.append(TraceEvent(
            timestamp=critique.id,  # Use ID as timestamp placeholder
            event_type="critique",
            agent_id="critique",
            data={
                "flagged": critique.flagged,
                "confidence": critique.confidence,
                "claim": critique.claim
            }
        ))
    
    return TraceResponse(
        job_id=job_id,
        query=context.query,
        events=events,
        final_answer=context.final_answer,
        status=job_data.get("status", "unknown")
    )


@app.get("/eval/latest")
async def get_latest_eval() -> EvalSummary:
    """
    Get latest evaluation run results.
    
    Returns breakdown by group (A/B/C) and all 6 scoring dimensions.
    """
    # In production, would query database for latest eval run
    # For now, return placeholder
    raise HTTPException(status_code=501, detail="Eval harness not yet implemented")


@app.post("/eval/approve")
async def approve_prompt(request: ApprovalRequest):
    """
    Approve or reject a prompt proposal.
    
    If approved, triggers rerun of failed cases with new prompt
    and stores delta scores.
    """
    # In production, would update database and trigger rerun
    raise HTTPException(status_code=501, detail="Approval system not yet implemented")


@app.post("/eval/rerun")
async def rerun_eval():
    """
    Rerun evaluation with latest approved prompts.
    
    Returns updated scores and deltas vs previous run.
    """
    # In production, would run full eval suite again
    raise HTTPException(status_code=501, detail="Evaluation runner not yet implemented")


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Mega AI - Multi-Agent Orchestrator",
        "version": "1.0.0",
        "endpoints": {
            "POST /query": "Submit a query (SSE streaming)",
            "GET /trace/{job_id}": "Get execution trace",
            "GET /eval/latest": "Get latest eval results",
            "POST /eval/approve": "Approve/reject prompt proposal",
            "POST /eval/rerun": "Rerun evaluation",
            "GET /health": "Health check"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
