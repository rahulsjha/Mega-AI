"""
API Endpoints Module

Modular endpoint organization for Mega AI orchestration framework.
Each endpoint file implements specific capabilities of the multi-agent system.

Modules:
- health.py: Infrastructure status (DB, Redis, connectivity)
- query.py: Direct query execution with SSE streaming
- jobs.py: Async job queue management
- evaluation.py: Eval harness, scoring, meta-agent loop
- trace.py: Execution trace retrieval and analysis
- logs.py: Event logs and audit trails
- documentation.py: API docs and endpoint discovery
"""

__all__ = [
    "health",
    "query", 
    "jobs",
    "evaluation",
    "trace",
    "logs",
    "documentation",
]
