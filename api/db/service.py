"""
Database service for job and event persistence.

Handles all database operations for jobs, events, tool calls, and evaluations.
"""

import logging
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from api.db.models import Job, Event, ToolCall, CritiqueLog, PolicyViolationLog, EvalRun, PromptProposal
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class JobService:
    """Service for managing job lifecycle and persistence."""
    
    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.db = db_session
    
    async def create_job(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> Job:
        """
        Create a new job record.
        
        Args:
            query: The user query
            metadata: Optional metadata dictionary
            
        Returns:
            Created Job record with ID
        """
        job = Job(
            query=query,
            status="queued",
            job_metadata=metadata or {}
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(
            f"Created job {job.id}",
            extra={"job_id": str(job.id), "query_len": len(query)}
        )
        
        return job
    
    async def get_job(self, job_id: UUID) -> Optional[Job]:
        """
        Get job by ID.
        
        Args:
            job_id: Job UUID
            
        Returns:
            Job record or None
        """
        result = await self.db.execute(
            select(Job).where(Job.id == job_id)
        )
        return result.scalar_one_or_none()
    
    async def update_job_status(self, job_id: UUID, status: str, error: Optional[str] = None) -> Job:
        """
        Update job status.
        
        Args:
            job_id: Job UUID
            status: New status (queued, running, completed, failed)
            error: Optional error message if failed
            
        Returns:
            Updated Job record
        """
        job = await self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        job.status = status
        if status == "running":
            job.started_at = datetime.utcnow()
        elif status in ("completed", "failed"):
            job.completed_at = datetime.utcnow()
        
        if error:
            job.error_message = error
        
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(
            f"Updated job {job_id} status to {status}",
            extra={"job_id": str(job_id), "status": status}
        )
        
        return job
    
    async def set_job_result(self, job_id: UUID, final_answer: str, latency_ms: float) -> Job:
        """
        Set job completion result.
        
        Args:
            job_id: Job UUID
            final_answer: The final answer/result
            latency_ms: Total execution time in milliseconds
            
        Returns:
            Updated Job record
        """
        job = await self.update_job_status(job_id, "completed")
        job.final_answer = final_answer
        job.total_latency_ms = latency_ms
        
        await self.db.commit()
        await self.db.refresh(job)
        
        logger.info(
            f"Set job {job_id} result",
            extra={
                "job_id": str(job_id),
                "answer_len": len(final_answer),
                "latency_ms": latency_ms
            }
        )
        
        return job


class EventService:
    """Service for managing event logs."""
    
    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.db = db_session
    
    async def log_event(
        self,
        job_id: UUID,
        event_type: str,
        data: Dict[str, Any],
        agent_id: Optional[str] = None,
        latency_ms: float = 0.0,
        token_count: int = 0,
        policy_violations: Optional[List[str]] = None
    ) -> Event:
        """
        Log an event to the database.
        
        Args:
            job_id: Job UUID
            event_type: Type of event
            data: Event-specific data
            agent_id: Optional agent ID
            latency_ms: Optional latency in milliseconds
            token_count: Optional token count
            policy_violations: Optional list of violations
            
        Returns:
            Created Event record
        """
        event = Event(
            job_id=job_id,
            event_type=event_type,
            agent_id=agent_id,
            data=data,
            latency_ms=latency_ms,
            token_count=token_count,
            policy_violations=policy_violations or []
        )
        self.db.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        
        return event
    
    async def get_job_events(self, job_id: UUID, event_type: Optional[str] = None) -> List[Event]:
        """
        Get all events for a job, optionally filtered by type.
        
        Args:
            job_id: Job UUID
            event_type: Optional event type filter
            
        Returns:
            List of Event records
        """
        query = select(Event).where(Event.job_id == job_id)
        
        if event_type:
            query = query.where(Event.event_type == event_type)
        
        query = query.order_by(Event.created_at)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def stream_events(self, job_id: UUID, since: Optional[datetime] = None) -> List[Event]:
        """
        Get events since a specific timestamp (for streaming/polling).
        
        Args:
            job_id: Job UUID
            since: Optional timestamp to filter events
            
        Returns:
            List of Event records in chronological order
        """
        query = select(Event).where(Event.job_id == job_id)
        
        if since:
            query = query.where(Event.created_at > since)
        
        query = query.order_by(Event.created_at)
        
        result = await self.db.execute(query)
        return result.scalars().all()


class ToolCallService:
    """Service for managing tool call logs."""
    
    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.db = db_session
    
    async def log_tool_call(
        self,
        job_id: UUID,
        tool_name: str,
        input_hash: str,
        input_preview: str,
        output_hash: str,
        output_preview: str,
        latency_ms: float,
        called_by_agent: str,
        accepted: bool = True,
        rejection_reason: Optional[str] = None,
        error_type: Optional[str] = None,
        attempt_number: int = 1
    ) -> ToolCall:
        """
        Log a tool call to the database.
        
        Args:
            job_id: Job UUID
            tool_name: Name of tool called
            input_hash: SHA256 hash of input
            input_preview: Preview of input
            output_hash: SHA256 hash of output
            output_preview: Preview of output
            latency_ms: Execution time
            called_by_agent: Which agent called the tool
            accepted: Whether result was accepted
            rejection_reason: Why it was rejected
            error_type: Error type if failed
            attempt_number: Which attempt (for retries)
            
        Returns:
            Created ToolCall record
        """
        tool_call = ToolCall(
            job_id=job_id,
            tool_name=tool_name,
            input_hash=input_hash,
            input_preview=input_preview,
            output_hash=output_hash,
            output_preview=output_preview,
            latency_ms=latency_ms,
            attempt_number=attempt_number,
            accepted=accepted,
            rejection_reason=rejection_reason,
            called_by_agent=called_by_agent,
            error_type=error_type
        )
        self.db.add(tool_call)
        await self.db.commit()
        await self.db.refresh(tool_call)
        
        return tool_call
    
    async def get_job_tool_calls(self, job_id: UUID) -> List[ToolCall]:
        """
        Get all tool calls for a job.
        
        Args:
            job_id: Job UUID
            
        Returns:
            List of ToolCall records
        """
        result = await self.db.execute(
            select(ToolCall)
            .where(ToolCall.job_id == job_id)
            .order_by(ToolCall.created_at)
        )
        return result.scalars().all()


class EvalService:
    """Service for managing evaluation runs and results."""
    
    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.db = db_session
    
    async def get_latest_eval_run(self) -> Optional[EvalRun]:
        """
        Get the most recent evaluation run.
        
        Returns:
            Latest EvalRun or None
        """
        result = await self.db.execute(
            select(EvalRun).order_by(desc(EvalRun.created_at)).limit(1)
        )
        return result.scalar_one_or_none()
    
    async def get_eval_runs_by_group(self, group: str) -> List[EvalRun]:
        """
        Get all evaluation runs for a specific group.
        
        Args:
            group: Group identifier (A, B, or C)
            
        Returns:
            List of EvalRun records
        """
        result = await self.db.execute(
            select(EvalRun)
            .where(EvalRun.group == group)
            .order_by(desc(EvalRun.created_at))
        )
        return result.scalars().all()


class ProposalService:
    """Service for managing prompt proposals."""
    
    def __init__(self, db_session: AsyncSession):
        """Initialize with database session."""
        self.db = db_session
    
    async def create_proposal(
        self,
        original_prompt: str,
        rewritten_prompt: str,
        unified_diff: str,
        justification: str,
        target_dimension: str,
        expected_improvement: float
    ) -> PromptProposal:
        """
        Create a new prompt proposal.
        
        Args:
            original_prompt: Original prompt text
            rewritten_prompt: Rewritten prompt text
            unified_diff: Unified diff format
            justification: Reason for rewrite
            target_dimension: Which dimension to improve
            expected_improvement: Expected score improvement
            
        Returns:
            Created PromptProposal record
        """
        proposal = PromptProposal(
            original_prompt=original_prompt,
            rewritten_prompt=rewritten_prompt,
            unified_diff=unified_diff,
            justification=justification,
            target_dimension=target_dimension,
            expected_improvement=expected_improvement
        )
        self.db.add(proposal)
        await self.db.commit()
        await self.db.refresh(proposal)
        
        return proposal
    
    async def get_pending_proposals(self) -> List[PromptProposal]:
        """
        Get all unapproved proposals.
        
        Returns:
            List of pending PromptProposal records
        """
        result = await self.db.execute(
            select(PromptProposal)
            .where(PromptProposal.decision.is_(None))
            .order_by(desc(PromptProposal.created_at))
        )
        return result.scalars().all()
    
    async def approve_proposal(
        self,
        proposal_id: UUID,
        reviewer_notes: Optional[str] = None
    ) -> PromptProposal:
        """
        Approve a proposal.
        
        Args:
            proposal_id: Proposal UUID
            reviewer_notes: Optional reviewer notes
            
        Returns:
            Updated PromptProposal record
        """
        result = await self.db.execute(
            select(PromptProposal).where(PromptProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        proposal.decision = "approved"
        proposal.reviewer_notes = reviewer_notes
        proposal.decided_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(proposal)
        
        return proposal
    
    async def reject_proposal(
        self,
        proposal_id: UUID,
        reviewer_notes: Optional[str] = None
    ) -> PromptProposal:
        """
        Reject a proposal.
        
        Args:
            proposal_id: Proposal UUID
            reviewer_notes: Optional reviewer notes
            
        Returns:
            Updated PromptProposal record
        """
        result = await self.db.execute(
            select(PromptProposal).where(PromptProposal.id == proposal_id)
        )
        proposal = result.scalar_one_or_none()
        
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")
        
        proposal.decision = "rejected"
        proposal.reviewer_notes = reviewer_notes
        proposal.decided_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(proposal)
        
        return proposal
