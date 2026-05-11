"""
Health Check Endpoints

Provides infrastructure status with explicit DB and Redis connectivity checks.
Non-negotiable: Always report connectivity probes with source information.
"""

from fastapi import APIRouter
from api.db.database import probe_db_connection
from api.queue.job_queue import probe_redis_connection

router = APIRouter(tags=["infrastructure"])


@router.get("/health", summary="Infrastructure Health Check")
async def health_check():
    db_probe = await probe_db_connection()
    redis_probe = await probe_redis_connection()

    status = "ok" if db_probe["connected"] and redis_probe["connected"] else "degraded"
    http_status = 200 if status == "ok" else 503
    
    return {
        "status": status,
        "database": db_probe,
        "redis": redis_probe,
        "http_status": http_status
    }
