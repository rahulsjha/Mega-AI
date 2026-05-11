"""
FastAPI Main Application

Mega AI Multi-Agent Orchestration System
- 5 specialized agents with LLM-powered routing
- Comprehensive evaluation framework (15 cases, 6 dimensions, A/B/C groups)
- Full TRACE_EVENT protocol for execution transparency
- Database-backed audit trail (PostgreSQL)
- Redis worker queue for async processing
- Meta-agent optimization loop with A/B testing

All endpoints are modular and imported from api/endpoints/ submodules:
- health.py: Infrastructure connectivity checks
- query.py: Direct execution with SSE streaming
- jobs.py: Async queue management
- evaluation.py: Evaluation harness and meta-agent loop
- trace.py: Execution trace retrieval
- logs.py: Event logs
- documentation.py: API specification and endpoint discovery
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from typing import Optional

from api.logging_config import setup_logging
from api.db.database import setup_db, init_db
from api.context.budget import ContextBudgetManager
from api.endpoints import health, query, jobs, evaluation, trace, logs, documentation

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    logger.info("Intialization of Project")
    setup_db()
    await init_db()
    logger.info("Database initialized")
    
    from api.queue.job_queue import get_job_queue
    try:
        job_queue = get_job_queue()
        await job_queue.connect()
        logger.info("Job queue connected")
    except Exception as e:
        logger.warning(f"Failed to connect job queue (non-critical): {e}")
    
    logger.info("API ready to accept requests")
    yield
    
    logger.info("Shutting Up")
    try:
        job_queue = get_job_queue()
        await job_queue.disconnect()
        logger.info("Job queue disconnected")
    except Exception as e:
        logger.warning(f"Error disconnecting job queue: {e}")


app = FastAPI(
    title=" Mega AI Take Home - Multi-Agent Orchestrator",
    description="Production-grade multi-agent LLM orchestration system with comprehensive evaluation framework",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)


budget_manager = ContextBudgetManager()
orchestrator_instance: Optional[object] = None


app.include_router(documentation.router)
app.include_router(health.router)
app.include_router(query.router)
app.include_router(jobs.router)
app.include_router(evaluation.router)
app.include_router(trace.router)
app.include_router(logs.router)




@app.on_event("startup")
async def startup_event():
    logger.info("FastAPI startup event completed")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("FastAPI shutdown event completed")




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
