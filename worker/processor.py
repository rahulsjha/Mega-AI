"""
Worker processor - background worker for async job processing.

Consumes jobs from Redis queue and executes orchestration.
"""

import logging
import asyncio
import os
import sys
from datetime import datetime
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from api.queue.job_queue import get_job_queue
from api.db.service import JobService
from api.db.database import setup_db, get_async_session
from api.context.schema import AgentContext
from api.context.budget import ContextBudgetManager
from api.agents.orchestrator import MasterOrchestrator
from uuid import UUID

logger = logging.getLogger(__name__)


async def process_job(job_data: dict, db_session):
    """
    Process a single job from the queue.
    
    Args:
        job_data: Job data from queue
        db_session: Database session
    """
    job_id = UUID(job_data["job_id"])
    query = job_data["query"]
    
    job_service = JobService(db_session)
    
    start_time = time.time()
    
    try:
        logger.info(
            f"Processing job {job_id}",
            extra={"job_id": str(job_id), "query_len": len(query)}
        )
        
        # Update job status to running
        await job_service.update_job_status(job_id, "running")
        
        # Create context
        context = AgentContext(
            job_id=job_id,
            query=query
        )
        
        # Initialize budget manager
        budget_manager = ContextBudgetManager()
        
        # Create and execute orchestrator
        orchestrator = MasterOrchestrator(budget_manager)
        context = await orchestrator.execute(context)
        
        latency_ms = (time.time() - start_time) * 1000
        
        # Store result
        await job_service.set_job_result(
            job_id,
            context.final_answer or "",
            latency_ms
        )
        
        logger.info(
            f"Job {job_id} completed successfully",
            extra={
                "job_id": str(job_id),
                "latency_ms": latency_ms,
                "answer_len": len(context.final_answer or "")
            }
        )
    
    except Exception as e:
        logger.error(
            f"Job {job_id} failed: {str(e)}",
            extra={"job_id": str(job_id), "error": str(e)}
        )
        await job_service.update_job_status(job_id, "failed", str(e))
    
    finally:
        await db_session.close()


async def process_jobs():
    """
    Main worker loop.
    
    Continuously consumes jobs from Redis queue and processes them.
    """
    logger.info("Worker processor started")
    
    # Setup database
    setup_db()
    
    # Get job queue
    job_queue = get_job_queue()
    await job_queue.connect()
    
    try:
        while True:
            try:
                # Get queue stats
                stats = await job_queue.get_queue_stats()
                if stats["queue_size"] > 0:
                    logger.debug(
                        f"Queue stats",
                        extra=stats
                    )
                
                # Dequeue job
                job_data = await job_queue.dequeue_job(timeout=5)
                
                if not job_data:
                    # Queue empty, continue polling
                    await asyncio.sleep(1)
                    continue
                
                # Create database session for this job
                from api.db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as db_session:
                    await process_job(job_data, db_session)
                
            except Exception as e:
                logger.error(
                    f"Error in worker loop: {str(e)}",
                    extra={"error": str(e)}
                )
                await asyncio.sleep(1)  # Back off briefly on error
    
    except KeyboardInterrupt:
        logger.info("Worker processor shutting down")
    
    finally:
        await job_queue.disconnect()
        logger.info("Worker processor stopped")


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run worker
    asyncio.run(process_jobs())
