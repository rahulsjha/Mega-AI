"""
Redis-based job queue for asynchronous orchestration.

Handles job queuing, processing, and result storage.
"""

import logging
import json
import os
from typing import Optional, Dict, Any
import redis.asyncio as redis
from datetime import datetime
from uuid import UUID

logger = logging.getLogger(__name__)


class JobQueue:
    """Redis-based job queue for async processing."""
    
    QUEUE_NAME = "orchestration_jobs"
    RESULT_PREFIX = "job_result:"
    STATUS_PREFIX = "job_status:"
    
    def __init__(self):
        """Initialize Redis connection."""
        self.redis_url = os.getenv(
            "REDIS_URL",
            "redis://localhost:6379/0"
        )
        self.client = None
    
    async def connect(self):
        """Establish Redis connection."""
        try:
            self.client = await redis.from_url(self.redis_url, decode_responses=True)
            await self.client.ping()
            logger.info("Connected to Redis job queue")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise


async def check_redis_connection(redis_url: Optional[str] = None) -> bool:
    """Check whether Redis is reachable."""
    client = None
    try:
        client = await redis.from_url(
            redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        await client.ping()
        return True
    except Exception as e:
        logger.error(f"Redis connectivity check failed: {e}")
        return False
    finally:
        if client:
            await client.close()


async def probe_redis_connection(redis_url: Optional[str] = None) -> dict:
    """Probe Redis connectivity and return a structured status response."""
    client = None
    url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        client = await redis.from_url(url, decode_responses=True)
        await client.ping()
        return {
            "connected": True,
            "source": "REDIS_URL" if os.getenv("REDIS_URL") else "default",
            "url": url,
        }
    except Exception as e:
        logger.warning(f"Redis probe failed: {e}")
        return {
            "connected": False,
            "source": "REDIS_URL" if os.getenv("REDIS_URL") else "default",
            "url": url,
            "error": str(e),
        }
    finally:
        if client:
            await client.close()
    
    async def disconnect(self):
        """Close Redis connection."""
        if self.client:
            await self.client.close()
            logger.info("Disconnected from Redis job queue")
    
    async def enqueue_job(self, job_id: UUID, query: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Enqueue a job for processing.
        
        Args:
            job_id: Job UUID
            query: The query to process
            metadata: Optional metadata dictionary
            
        Returns:
            True if enqueued successfully
        """
        if not self.client:
            await self.connect()
        
        try:
            job_data = {
                "job_id": str(job_id),
                "query": query,
                "metadata": json.dumps(metadata or {}),
                "created_at": datetime.utcnow().isoformat(),
                "status": "queued"
            }
            
            # Push to queue
            await self.client.rpush(
                self.QUEUE_NAME,
                json.dumps(job_data)
            )
            
            # Set status in Redis
            await self.client.set(
                f"{self.STATUS_PREFIX}{str(job_id)}",
                "queued"
            )
            
            logger.info(
                f"Enqueued job {job_id}",
                extra={"job_id": str(job_id), "query_len": len(query)}
            )
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to enqueue job {job_id}: {e}")
            return False
    
    async def dequeue_job(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """
        Dequeue the next job from the queue.
        
        Args:
            timeout: Timeout in seconds for blocking pop
            
        Returns:
            Job dict or None if queue empty
        """
        if not self.client:
            await self.connect()
        
        try:
            # Blocking pop with timeout
            job_json = await self.client.blpop(self.QUEUE_NAME, timeout=timeout)
            
            if not job_json:
                return None
            
            # job_json is a tuple (key, value)
            job_data = json.loads(job_json[1])
            
            # Update status
            await self.client.set(
                f"{self.STATUS_PREFIX}{job_data['job_id']}",
                "processing"
            )
            
            logger.info(
                f"Dequeued job {job_data['job_id']}",
                extra={"job_id": job_data['job_id']}
            )
            
            return job_data
        
        except Exception as e:
            logger.error(f"Failed to dequeue job: {e}")
            return None
    
    async def get_job_status(self, job_id: UUID) -> Optional[str]:
        """
        Get the status of a job.
        
        Args:
            job_id: Job UUID
            
        Returns:
            Status string (queued, processing, completed, failed) or None
        """
        if not self.client:
            await self.connect()
        
        try:
            status = await self.client.get(f"{self.STATUS_PREFIX}{str(job_id)}")
            return status
        except Exception as e:
            logger.error(f"Failed to get job status: {e}")
            return None
    
    async def set_job_result(self, job_id: UUID, result: Dict[str, Any], ttl: int = 86400):
        """
        Store the result of a completed job.
        
        Args:
            job_id: Job UUID
            result: Result dictionary
            ttl: Time to live in seconds (default 24 hours)
        """
        if not self.client:
            await self.connect()
        
        try:
            result_key = f"{self.RESULT_PREFIX}{str(job_id)}"
            result_json = json.dumps(result)
            
            # Store result
            await self.client.set(result_key, result_json, ex=ttl)
            
            # Update status
            await self.client.set(
                f"{self.STATUS_PREFIX}{str(job_id)}",
                "completed"
            )
            
            logger.info(
                f"Stored result for job {job_id}",
                extra={"job_id": str(job_id), "result_size": len(result_json)}
            )
        
        except Exception as e:
            logger.error(f"Failed to store job result: {e}")
    
    async def set_job_error(self, job_id: UUID, error: str):
        """
        Mark a job as failed with error message.
        
        Args:
            job_id: Job UUID
            error: Error message
        """
        if not self.client:
            await self.connect()
        
        try:
            error_result = {
                "status": "error",
                "error": error,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            result_key = f"{self.RESULT_PREFIX}{str(job_id)}"
            await self.client.set(result_key, json.dumps(error_result), ex=86400)
            
            # Update status
            await self.client.set(
                f"{self.STATUS_PREFIX}{str(job_id)}",
                "failed"
            )
            
            logger.error(
                f"Marked job {job_id} as failed",
                extra={"job_id": str(job_id), "error": error}
            )
        
        except Exception as e:
            logger.error(f"Failed to store job error: {e}")
    
    async def get_queue_size(self) -> int:
        """
        Get the number of jobs in the queue.
        
        Returns:
            Queue size
        """
        if not self.client:
            await self.connect()
        
        try:
            size = await self.client.llen(self.QUEUE_NAME)
            return size
        except Exception as e:
            logger.error(f"Failed to get queue size: {e}")
            return -1
    
    async def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Returns:
            Dict with queue stats
        """
        if not self.client:
            await self.connect()
        
        try:
            queue_size = await self.get_queue_size()
            info = await self.client.info()
            
            return {
                "queue_size": queue_size,
                "redis_memory_usage": info.get("used_memory_human", "unknown"),
                "redis_connected_clients": info.get("connected_clients", 0),
                "redis_uptime_seconds": info.get("uptime_in_seconds", 0)
            }
        except Exception as e:
            logger.error(f"Failed to get queue stats: {e}")
            return {
                "queue_size": -1,
                "error": str(e)
            }


# Global job queue instance
_job_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Get or create the global job queue instance."""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue
