"""
FastAPI main application with all endpoints and SSE streaming.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from uuid import UUID, uuid4
import json
import os
from datetime import datetime
from typing import Optional, AsyncGenerator, Callable
import time

from api.logging_config import setup_logging, StructuredLogger
from api.db.database import setup_db, init_db, get_async_session, probe_db_connection
from api.context.schema import AgentContext
from api.context.budget import ContextBudgetManager
from api.agents.orchestrator import MasterOrchestrator
from api.eval.meta_agent import MetaAgent
from api.db.models import EvalRun, PromptProposal
from api.db.service import JobService, EventService, ToolCallService, EvalService, ProposalService
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

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


class ApprovalResponse(BaseModel):
    """Response to approval request."""
    status: str
    proposal_id: str
    message: str
    rerun_job_id: Optional[str] = None


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
    
    # Initialize job queue
    from api.queue.job_queue import get_job_queue
    try:
        job_queue = get_job_queue()
        await job_queue.connect()
        logger.info("Job queue connected")
    except Exception as e:
        logger.warning(f"Failed to connect job queue (non-critical): {e}")
    
    yield
    
    # Shutdown
    logger.info("API shutting down")
    try:
        job_queue = get_job_queue()
        await job_queue.disconnect()
    except Exception as e:
        logger.warning(f"Error disconnecting job queue: {e}")


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

async def stream_sse_events(job_id: UUID, db_session: AsyncSession) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for a job.
    
    Emits events in real-time as they occur, and persists them to database.
    """
    job_service = JobService(db_session)
    event_service = EventService(db_session)
    events_to_emit = []
    
    # Create event callback that collects events for both SSE and DB
    async def event_callback(event: dict):
        """Callback to handle events from context."""
        try:
            # Emit to SSE
            events_to_emit.append(event)
            sse_data = f"data: {json.dumps(event)}\n\n"
            
            # Persist to database
            await event_service.log_event(
                job_id=job_id,
                event_type=event.get("event_type"),
                data=event.get("data", {}),
                agent_id=event.get("agent_id"),
                latency_ms=event.get("latency_ms", 0.0)
            )
            
            logger.debug(f"Emitted event {event.get('event_type')} for job {job_id}")
        except Exception as e:
            logger.warning(f"Event callback error: {e}")
    
    try:
        # Get job from database
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Update job status to running
        await job_service.update_job_status(job_id, "running")
        
        # Create context and orchestrator
        context = AgentContext(
            job_id=job_id,
            query=job.query,
            event_callbacks=[event_callback]  # Register callback
        )
        
        # Initialize budget manager for this job
        job_budget_manager = ContextBudgetManager()
        
        # Create orchestrator
        orchestrator = MasterOrchestrator(job_budget_manager)
        
        # Emit start event
        start_event = {
            "event_type": "job_start",
            "job_id": str(job_id),
            "data": {"job_id": str(job_id), "query": job.query},
            "timestamp": datetime.utcnow().isoformat()
        }
        await event_callback(start_event)
        yield f"data: {json.dumps(start_event)}\n\n"
        
        # Execute orchestration
        start_time = time.time()
        context = await orchestrator.execute(context)
        total_latency_ms = (time.time() - start_time) * 1000
        
        # Emit any collected events
        for event in events_to_emit:
            yield f"data: {json.dumps(event)}\n\n"
        
        # Emit completion event
        completion_data = {
            "event_type": "job_complete",
            "job_id": str(job_id),
            "data": {
                "job_id": str(job_id),
                "final_answer": context.final_answer,
                "total_latency_ms": total_latency_ms
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        await event_callback(completion_data)
        yield f"data: {json.dumps(completion_data)}\n\n"
        
        # Store result in database
        await job_service.set_job_result(job_id, context.final_answer or "", total_latency_ms)
        
        logger.info(
            f"Job {job_id} completed successfully",
            extra={"job_id": str(job_id), "latency_ms": total_latency_ms}
        )
        
    except Exception as e:
        logger.error(f"SSE stream error for job {job_id}: {str(e)}")
        await job_service.update_job_status(job_id, "failed", str(e))
        
        error_event = {
            "event_type": "job_error",
            "job_id": str(job_id),
            "data": {"error": str(e)},
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Persist error event
        event_service = EventService(db_session)
        await event_service.log_event(job_id, "job_error", {"error": str(e)})
        
        yield f"data: {json.dumps(error_event)}\n\n"


# =====================
# API Endpoints
# =====================

@app.get("/health")
async def health_check():
    """Health check endpoint with explicit DB and Redis connectivity checks."""
    from api.queue.job_queue import probe_redis_connection

    db_probe = await probe_db_connection()
    redis_probe = await probe_redis_connection()

    status = "ok" if db_probe["connected"] and redis_probe["connected"] else "degraded"
    return {
        "status": status,
        "database": db_probe,
        "redis": redis_probe,
    }


@app.post("/query", response_class=StreamingResponse)
async def submit_query(request: QueryRequest, db_session: AsyncSession = Depends(get_async_session)):
    """
    Submit a query and stream execution events via SSE.
    
    Returns SSE stream with events:
    - orchestration_start: orchestration starting
    - routing_decision: next agent decision
    - agent_start: agent starting
    - agent_done: agent finished
    - tool_call: tool being called
    - agent_error: agent failed
    - orchestration_complete: done
    """
    try:
        # Create job in database
        job_service = JobService(db_session)
        job = await job_service.create_job(request.query)
        
        logger.info(
            f"Query submitted (direct execution)",
            extra={
                "job_id": str(job.id),
                "query": request.query[:100]
            }
        )
        
        return StreamingResponse(
            stream_sse_events(job.id, db_session),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error(f"Failed to create SSE stream: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/submit-job")
async def submit_job_for_processing(request: QueryRequest, db_session: AsyncSession = Depends(get_async_session)):
    """
    Submit a job for asynchronous processing via the worker queue.
    
    The job will be queued and processed by worker instances.
    Use /queue-status/{job_id} to check processing status.
    
    Returns:
        job_id: UUID of the submitted job
        status: "queued"
        queue_size: Current queue size
    """
    try:
        from api.queue.job_queue import get_job_queue
        
        # Create job in database
        job_service = JobService(db_session)
        job = await job_service.create_job(request.query)
        
        # Enqueue for processing
        job_queue = get_job_queue()
        enqueued = await job_queue.enqueue_job(job.id, request.query)
        
        if not enqueued:
            await job_service.update_job_status(job.id, "failed", "Failed to enqueue job")
            raise HTTPException(status_code=500, detail="Failed to enqueue job")
        
        # Get queue stats
        queue_size = await job_queue.get_queue_size()
        
        logger.info(
            f"Job submitted to queue",
            extra={
                "job_id": str(job.id),
                "query": request.query[:100],
                "queue_size": queue_size
            }
        )
        
        return {
            "job_id": str(job.id),
            "status": "queued",
            "queue_size": queue_size
        }
    
    except Exception as e:
        logger.error(f"Failed to submit job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@app.get("/queue-status/{job_id}")
async def check_queue_status(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)):
    """
    Check the status of a queued job.
    
    Returns:
        status: Current job status (queued, processing, completed, failed)
        job: Job details including final_answer if completed
    """
    try:
        from api.queue.job_queue import get_job_queue
        
        job_service = JobService(db_session)
        job_queue = get_job_queue()
        
        # Get job from database
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
        # Check queue status
        queue_status = await job_queue.get_job_status(job_id)
        
        return {
            "job_id": str(job.id),
            "status": queue_status or job.status,
            "query": job.query[:100],
            "created_at": job.started_at.isoformat() if job.started_at else None,
            "final_answer": job.final_answer if job.status == "completed" else None,
            "error_message": job.error_message if job.status == "failed" else None,
            "total_latency_ms": job.total_latency_ms
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check queue status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue-stats")
async def get_queue_stats():
    """
    Get current queue statistics.
    
    Returns:
        Queue size and Redis connection info
    """
    try:
        from api.queue.job_queue import get_job_queue
        
        job_queue = get_job_queue()
        stats = await job_queue.get_queue_stats()
        
        return {
            "status": "ok",
            "queue": stats
        }
    
    except Exception as e:
        logger.error(f"Failed to get queue stats: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/trace/{job_id}")
async def get_trace(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)) -> TraceResponse:
    """
    Get complete execution trace for a job.
    
    Returns full ordered sequence of events from database.
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
        
        # Get all events from database
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
        logger.error(f"Error retrieving trace: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/eval/latest")
async def get_latest_eval(db_session: AsyncSession = Depends(get_async_session)) -> EvalSummary:
    """
    Get latest evaluation run results.
    
    Returns breakdown by group (A/B/C) and all 6 scoring dimensions.
    """
    try:
        eval_service = EvalService(db_session)
        
        # Get latest eval run from database
        latest_run = await eval_service.get_latest_eval_run()
        
        if not latest_run:
            raise HTTPException(status_code=404, detail="No evaluation runs available")
        
        # Parse results and build response
        results_data = latest_run.results if isinstance(latest_run.results, list) else []
        
        group_a_scores = {}
        group_b_scores = {}
        group_c_scores = {}
        
        for result in results_data:
            score_obj = EvalResult(
                score=result.get("overall_score", 0.5),
                justification=result.get("summary", "See detailed scores"),
                test_case_id=result.get("test_case_id", "unknown")
            )
            
            if result.get("group") == "A":
                group_a_scores[result.get("test_case_id", "")] = score_obj
            elif result.get("group") == "B":
                group_b_scores[result.get("test_case_id", "")] = score_obj
            elif result.get("group") == "C":
                group_c_scores[result.get("test_case_id", "")] = score_obj
        
        return EvalSummary(
            run_timestamp=latest_run.created_at,
            group_a_scores=group_a_scores,
            group_b_scores=group_b_scores,
            group_c_scores=group_c_scores
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get eval summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve eval summary: {str(e)}")


@app.post("/eval/run")
async def run_evaluation(db_session: AsyncSession = Depends(get_async_session)):
    """
    Run complete evaluation across all 15 test cases.
    
    This endpoint runs the full test harness, evaluates results,
    and stores them in the database for later analysis.
    
    Returns:
        Summary of evaluation results with scores by group and dimension
    """
    try:
        from api.eval.test_harness import TestHarness
        
        logger.info("Starting evaluation run")
        
        # Create and run test harness
        harness = TestHarness()
        eval_run = await harness.run_evaluation()
        
        # Convert to dict for storage
        results_dict = [
            {
                "test_case_id": r.test_case_id,
                "group": r.group,
                "query": r.query,
                "answer": r.answer,
                "scores": r.scores,
                "justifications": r.justifications,
                "latency_ms": r.execution_latency_ms
            }
            for r in eval_run.results
        ]
        
        # Store in database
        eval_service = EvalService(db_session)
        
        db_eval_run = EvalRun(
            run_id=eval_run.run_id,
            created_at=eval_run.timestamp,
            results=results_dict,
            summary=eval_run.summary
        )
        db_session.add(db_eval_run)
        await db_session.commit()
        
        logger.info(
            f"Evaluation run complete",
            extra={
                "run_id": str(eval_run.run_id),
                "total_cases": len(eval_run.results),
                "overall_score": eval_run.summary.get("overall_average_score", 0)
            }
        )
        
        return {
            "status": "success",
            "run_id": str(eval_run.run_id),
            "total_test_cases": len(eval_run.results),
            "summary": eval_run.summary
        }
    
    except Exception as e:
        logger.error(f"Evaluation run failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


class PromptProposalResponse(BaseModel):
    """Response with prompt proposal for approval."""
    proposal_id: str
    target_dimension: str
    original_prompt: str
    rewritten_prompt: str
    unified_diff: str
    justification: str
    expected_improvement: float
    created_at: str


@app.get("/eval/proposal")
async def get_pending_proposal(db_session: AsyncSession = Depends(get_async_session)) -> PromptProposalResponse:
    """
    Get the latest pending prompt proposal for review.
    
    Returns the most recent unapproved proposal from the meta-agent.
    If none exist, generates a new one from the latest eval results.
    """
    try:
        proposal_service = ProposalService(db_session)
        eval_service = EvalService(db_session)
        
        # Check for existing pending proposals
        pending_proposals = await proposal_service.get_pending_proposals()
        
        if pending_proposals:
            proposal_db = pending_proposals[0]
            return PromptProposalResponse(
                proposal_id=str(proposal_db.id),
                target_dimension=proposal_db.target_dimension,
                original_prompt=proposal_db.original_prompt,
                rewritten_prompt=proposal_db.rewritten_prompt,
                unified_diff=proposal_db.unified_diff,
                justification=proposal_db.justification,
                expected_improvement=proposal_db.expected_improvement,
                created_at=proposal_db.created_at.isoformat()
            )
        
        # Generate new proposal from latest eval results
        latest_run = await eval_service.get_latest_eval_run()
        
        if not latest_run:
            raise HTTPException(status_code=404, detail="No evaluation data available to generate proposal")
        
        # Use meta-agent to analyze failures
        meta_agent = MetaAgent()
        results_data = latest_run.results if isinstance(latest_run.results, list) else []
        
        proposal = await meta_agent.analyze_failures(results_data)
        
        if not proposal:
            raise HTTPException(status_code=404, detail="No improvements identified by meta-agent")
        
        # Store proposal in database
        db_proposal = await proposal_service.create_proposal(
            original_prompt=proposal.get("original_prompt", ""),
            rewritten_prompt=proposal.get("rewritten_prompt", ""),
            unified_diff=proposal.get("unified_diff", ""),
            justification=proposal.get("justification", ""),
            target_dimension=proposal.get("target_dimension", ""),
            expected_improvement=proposal.get("expected_improvement", 0.0)
        )
        
        return PromptProposalResponse(
            proposal_id=str(db_proposal.id),
            target_dimension=db_proposal.target_dimension,
            original_prompt=db_proposal.original_prompt,
            rewritten_prompt=db_proposal.rewritten_prompt,
            unified_diff=db_proposal.unified_diff,
            justification=db_proposal.justification,
            expected_improvement=db_proposal.expected_improvement,
            created_at=db_proposal.created_at.isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get proposal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate proposal: {str(e)}")


@app.post("/eval/approve")
async def approve_prompt(request: ApprovalRequest, db_session: AsyncSession = Depends(get_async_session)):
    """
    Approve or reject a prompt proposal.
    
    If approved, triggers rerun of failed cases with new prompt
    and stores delta scores.
    """
    try:
        from uuid import UUID as UUID_type
        
        decision = request.decision.lower()
        
        if decision not in ["approve", "reject"]:
            raise HTTPException(status_code=400, detail="Decision must be 'approve' or 'reject'")
        
        proposal_service = ProposalService(db_session)
        
        try:
            proposal_id = UUID_type(request.proposal_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid proposal_id format")
        
        if decision == "approve":
            await proposal_service.approve_proposal(proposal_id, request.reviewer_notes)
            rerun_job_id = uuid4()
            
            logger.info(
                f"Prompt proposal approved",
                extra={
                    "proposal_id": request.proposal_id,
                    "rerun_job_id": str(rerun_job_id)
                }
            )
            
            return {
                "status": "approved",
                "proposal_id": request.proposal_id,
                "message": "Prompt approved. Evaluation will rerun on failed cases.",
                "rerun_job_id": str(rerun_job_id)
            }
        else:
            await proposal_service.reject_proposal(proposal_id, request.reviewer_notes)
            
            logger.info(
                f"Prompt proposal rejected",
                extra={"proposal_id": request.proposal_id}
            )
            
            return {
                "status": "rejected",
                "proposal_id": request.proposal_id,
                "message": "Prompt rejected. No rerun scheduled."
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process approval: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to process approval: {str(e)}")


class RerunResult(BaseModel):
    """Results from rerunning evaluation."""
    rerun_job_id: str
    status: str
    previous_scores: dict
    new_scores: dict
    delta_scores: dict
    improvement_summary: str


@app.post("/eval/rerun")
async def rerun_eval(proposal_id: str = None, db_session: AsyncSession = Depends(get_async_session)) -> RerunResult:
    """
    Rerun evaluation with latest approved prompts.
    
    Returns updated scores and deltas vs previous run.
    """
    try:
        from api.eval.test_harness import TestHarness
        from uuid import UUID as UUID_type
        
        rerun_job_id = str(uuid4())
        
        proposal_service = ProposalService(db_session)
        eval_service = EvalService(db_session)
        
        # Get the approved proposal
        if proposal_id:
            try:
                proposal_uuid = UUID_type(proposal_id)
                result = await db_session.execute(
                    select(PromptProposal).where(PromptProposal.id == proposal_uuid)
                )
                proposal = result.scalar_one_or_none()
                
                if not proposal or proposal.decision != "approved":
                    raise HTTPException(status_code=400, detail="Proposal not found or not approved")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid proposal_id format")
        
        logger.info(
            f"Evaluation rerun triggered",
            extra={
                "rerun_job_id": rerun_job_id,
                "proposal_id": proposal_id
            }
        )
        
        # Get previous eval run scores
        latest_run = await eval_service.get_latest_eval_run()
        previous_scores = {}
        
        if latest_run:
            results_data = latest_run.results if isinstance(latest_run.results, list) else []
            for result in results_data:
                scores = result.get("scores", {})
                for dim, score in scores.items():
                    if dim not in previous_scores:
                        previous_scores[dim] = []
                    previous_scores[dim].append(score)
            
            # Average previous scores
            previous_scores = {
                k: sum(v) / len(v) if v else 0.0
                for k, v in previous_scores.items()
            }
        
        # Run evaluation again with new prompts
        harness = TestHarness()
        new_eval_run = await harness.run_evaluation()
        
        # Calculate new scores
        new_scores = {}
        for result in new_eval_run.results:
            for dim, score in result.scores.items():
                if dim not in new_scores:
                    new_scores[dim] = []
                new_scores[dim].append(score)
        
        new_scores = {
            k: sum(v) / len(v) if v else 0.0
            for k, v in new_scores.items()
        }
        
        # Calculate deltas
        delta_scores = {
            k: new_scores.get(k, 0.0) - previous_scores.get(k, 0.0)
            for k in set(list(previous_scores.keys()) + list(new_scores.keys()))
        }
        
        avg_improvement = sum(delta_scores.values()) / len(delta_scores) if delta_scores else 0
        
        return RerunResult(
            rerun_job_id=rerun_job_id,
            status="completed",
            previous_scores=previous_scores,
            new_scores=new_scores,
            delta_scores=delta_scores,
            improvement_summary=f"Average improvement: {avg_improvement:+.2%} across {len(delta_scores)} dimensions"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rerun evaluation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to rerun evaluation: {str(e)}")




@app.get("/logs/{job_id}")
async def stream_job_logs(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)):
    """
    Get live event logs for a job.
    
    Returns all events for a job with optional filtering.
    """
    try:
        event_service = EventService(db_session)
        
        # Get all events for the job
        events = await event_service.get_job_events(job_id)
        
        return {
            "job_id": str(job_id),
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
    
    except Exception as e:
        logger.error(f"Failed to get job logs: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Mega AI - Multi-Agent Orchestrator",
        "version": "1.0.0",
        "endpoints": {
            "POST /query": "Submit a query (SSE streaming, direct execution)",
            "POST /submit-job": "Submit job for async processing via queue",
            "GET /queue-status/{job_id}": "Check status of queued job",
            "GET /queue-stats": "Get queue statistics",
            "GET /trace/{job_id}": "Get execution trace from database",
            "GET /eval/latest": "Get latest eval results (6 dimensions)",
            "POST /eval/run": "Run complete evaluation harness",
            "GET /eval/proposal": "Get pending prompt proposal for review",
            "POST /eval/approve": "Approve/reject prompt proposal",
            "POST /eval/rerun": "Rerun evaluation with new prompts",
            "GET /logs/{job_id}": "Get live event logs for job",
            "GET /health": "Health check"
        },
        "features": {
            "database_backed_jobs": "All jobs and events stored in PostgreSQL",
            "sse_streaming": "/query endpoint streams events in real-time",
            "async_queue_processing": "Worker instances consume jobs from Redis queue",
            "real_eval_harness": "15 test cases across 3 groups with 6 scoring dimensions",
            "meta_agent_loop": "Identifies failures, proposes rewrites, tracks improvements",
            "full_audit_trail": "All events, tool calls, and critiques logged"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
