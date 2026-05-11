"""
Job Queue Management Endpoints

Async job submission, status tracking, and queue statistics.

Non-negotiable: Worker instances consume jobs from Redis queue and emit full trace protocols.
Every queued job must persist to database with complete audit trail.
"""

import logging
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_async_session
from api.db.service import JobService
from api.queue.job_queue import get_job_queue

logger = logging.getLogger(__name__)
router = APIRouter(tags=["job-management"])


class QueryRequest(BaseModel):
    """Request to submit a query."""
    query: str


@router.post("/submit-job", summary="Submit Job for Async Processing")
async def submit_job_for_processing(request: QueryRequest, db_session: AsyncSession = Depends(get_async_session)):
    """
    Submit a job for asynchronous processing via Redis worker queue.
    
    The job will be:
    - Persisted to database immediately
    - Enqueued in Redis for worker consumption
    - Processed by worker instances with full trace protocol compliance
    
    Use GET /queue-status/{job_id} to check processing status.
    
    Non-negotiable:
    - Job must be in database before enqueuing
    - Worker must emit full TRACE_EVENT stream
    - Failure in worker is tracked with ERROR event
    - Timeout handling: job status set to "failed" after TTL
    
    Returns:
        {
            "job_id": UUID,
            "status": "queued",
            "queue_size": integer,
            "worker_instruction": "Workers will consume and execute with full trace protocol"
        }
    """
    try:
        job_service = JobService(db_session)
        job = await job_service.create_job(request.query)
        job_queue = get_job_queue()
        enqueued = await job_queue.enqueue_job(job.id, request.query)
        
        if not enqueued:
            await job_service.update_job_status(job.id, "failed", "Failed to enqueue job")
            raise HTTPException(status_code=500, detail="Failed to enqueue job in Redis queue")
        
        queue_size = await job_queue.get_queue_size()
        
        logger.info(
            f"Job submitted to queue | Job: {job.id} | Query: {request.query[:80]} | Queue size: {queue_size}"
        )
        
        return {
            "job_id": str(job.id),
            "status": "queued",
            "queue_size": queue_size,
            "worker_instruction": "Workers will consume and execute with full trace protocol"
        }
    
    except Exception as e:
        logger.error(f"Failed to submit job: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@router.get("/queue-status/{job_id}", summary="Check Job Queue Status")
async def check_queue_status(job_id: UUID, db_session: AsyncSession = Depends(get_async_session)):
    """
    Check the status of a queued job.
    
    Returns:
        {
            "job_id": UUID,
            "status": "queued" | "processing" | "completed" | "failed",
            "query": first 100 chars of original query,
            "created_at": ISO8601 timestamp,
            "final_answer": result if completed (null otherwise),
            "error_message": if status is failed,
            "total_latency_ms": execution time
        }
    
    Non-negotiable:
    - Status reflects actual worker progress from database
    - If worker encountered ERROR event, status is "failed" with error_message
    - Completed jobs include final_answer from synthesis agent
    """
    try:
        job_service = JobService(db_session)
        job_queue = get_job_queue()
        
        job = await job_service.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        
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
        logger.error(f"Failed to check queue status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/queue-stats", summary="Get Queue Statistics")
async def get_queue_stats():
    """
    Get current queue statistics and health.
    
    Returns:
        {
            "status": "ok" | "error",
            "queue": {
                "size": current number of jobs in queue,
                "redis_connection": connection status,
                "avg_processing_time_ms": average job latency
            }
        }
    
    Non-negotiable:
    - Reports actual Redis queue size
    - Returns error if Redis connection fails
    - Used to trigger compression if queue grows beyond threshold
    """
    try:
        job_queue = get_job_queue()
        stats = await job_queue.get_queue_stats()
        
        return {
            "status": "ok",
            "queue": stats
        }
    
    except Exception as e:
        logger.error(f"Failed to get queue stats: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }
