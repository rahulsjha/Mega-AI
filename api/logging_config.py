"""
Structured logging configuration using structlog.

All log lines must have: timestamp, job_id, agent_id, event_type, input_hash,
output_hash, latency_ms, token_count, policy_violations
"""

import logging
import logging.config
import os
import structlog
from typing import Optional
from uuid import UUID


def setup_logging():
    """Configure structured logging with JSON output."""
    
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard logging
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(message)s",
            },
        },
        "handlers": {
            "default": {
                "level": log_level,
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "loggers": {
            "": {
                "handlers": ["default"],
                "level": log_level,
                "propagate": True,
            }
        }
    })


class StructuredLogger:
    """Wrapper for structured logging with required fields."""
    
    @staticmethod
    def get_logger(name: str) -> structlog.BoundLogger:
        """Get a configured logger."""
        return structlog.get_logger(name)
    
    @staticmethod
    def log_event(
        logger: structlog.BoundLogger,
        event_type: str,
        job_id: Optional[UUID] = None,
        agent_id: Optional[str] = None,
        input_hash: Optional[str] = None,
        output_hash: Optional[str] = None,
        latency_ms: float = 0.0,
        token_count: int = 0,
        policy_violations: Optional[list] = None,
        **kwargs
    ):
        """
        Log an event with all required fields.
        
        Args:
            logger: structlog logger
            event_type: Type of event
            job_id: Job ID
            agent_id: Agent ID
            input_hash: Input hash
            output_hash: Output hash
            latency_ms: Latency in milliseconds
            token_count: Token count
            policy_violations: List of violations
            **kwargs: Additional fields
        """
        logger.info(
            event_type,
            job_id=str(job_id) if job_id else None,
            agent_id=agent_id,
            event_type=event_type,
            input_hash=input_hash,
            output_hash=output_hash,
            latency_ms=latency_ms,
            token_count=token_count,
            policy_violations=policy_violations or [],
            **kwargs
        )
