"""
SQLAlchemy ORM models for persistent storage.

Stores jobs, events, eval results, and prompt proposals.
"""

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, JSON, UUID, ForeignKey, Enum, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
import enum

Base = declarative_base()


class Job(Base):
    """Represents a single orchestration job."""
    __tablename__ = "jobs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    query = Column(Text, nullable=False)
    status = Column(String, default="pending")  # pending, running, completed, failed
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    total_latency_ms = Column(Float, nullable=True)
    final_answer = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    job_metadata = Column("metadata", JSON, default=dict)
    
    # Relationships
    events = relationship("Event", back_populates="job", cascade="all, delete-orphan")
    tool_calls = relationship("ToolCall", back_populates="job", cascade="all, delete-orphan")
    critique_results = relationship("CritiqueLog", back_populates="job", cascade="all, delete-orphan")
    policy_violations = relationship("PolicyViolationLog", back_populates="job", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created", "started_at"),
    )


class Event(Base):
    """Structured log event for every significant action."""
    __tablename__ = "events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    agent_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)  # agent_start, token, tool_call, agent_done, etc.
    input_hash = Column(String, nullable=True)
    output_hash = Column(String, nullable=True)
    latency_ms = Column(Float, default=0.0)
    token_count = Column(Integer, default=0)
    policy_violations = Column(JSON, default=list)
    data = Column(JSON, default=dict)  # Event-specific data
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    job = relationship("Job", back_populates="events")
    
    __table_args__ = (
        Index("ix_events_job_type", "job_id", "event_type"),
        Index("ix_events_created", "created_at"),
    )


class ToolCall(Base):
    """Record of each tool call with full tracing."""
    __tablename__ = "tool_calls"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    tool_name = Column(String, nullable=False)
    input_hash = Column(String, nullable=False)
    input_preview = Column(Text, nullable=False)
    output_hash = Column(String, nullable=False)
    output_preview = Column(Text, nullable=False)
    latency_ms = Column(Float, nullable=False)
    attempt_number = Column(Integer, default=1)
    accepted = Column(Boolean, default=True)
    rejection_reason = Column(Text, nullable=True)
    called_by_agent = Column(String, nullable=False)
    error_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    job = relationship("Job", back_populates="tool_calls")
    
    __table_args__ = (
        Index("ix_tool_calls_job", "job_id"),
        Index("ix_tool_calls_tool", "tool_name"),
    )


class CritiqueLog(Base):
    """Log of critique results."""
    __tablename__ = "critique_logs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    span_start = Column(Integer, nullable=False)
    span_end = Column(Integer, nullable=False)
    claim = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    flagged = Column(Boolean, default=False)
    reasoning = Column(Text, nullable=False)
    source_agent = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    job = relationship("Job", back_populates="critique_results")
    
    __table_args__ = (
        Index("ix_critique_job", "job_id"),
    )


class PolicyViolationLog(Base):
    """Log of policy violations."""
    __tablename__ = "policy_violations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    violation_type = Column(String, nullable=False)
    severity = Column(String, nullable=False)  # critical, warning, info
    agent_name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    context = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationships
    job = relationship("Job", back_populates="policy_violations")
    
    __table_args__ = (
        Index("ix_violations_job", "job_id"),
        Index("ix_violations_severity", "severity"),
    )


class EvalRun(Base):
    """Results from an evaluation run."""
    __tablename__ = "eval_runs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id = Column(String, nullable=False)
    group = Column(String, nullable=False)  # A, B, or C
    
    # Prompts and calls
    prompts_used = Column(JSON, nullable=False)  # {agent_name: prompt}
    tool_calls_made = Column(JSON, nullable=False)  # List of tool calls
    outputs_received = Column(JSON, nullable=False)  # {agent_name: output}
    
    # Scores (all 0-1)
    score_answer_correctness = Column(Float, nullable=False)
    score_citation_accuracy = Column(Float, nullable=False)
    score_contradiction_resolution = Column(Float, nullable=False)
    score_tool_efficiency = Column(Float, nullable=False)
    score_budget_compliance = Column(Float, nullable=False)
    score_critique_agreement = Column(Float, nullable=False)
    
    # Justifications
    justification_correctness = Column(Text, nullable=False)
    justification_citation = Column(Text, nullable=False)
    justification_contradiction = Column(Text, nullable=False)
    justification_efficiency = Column(Text, nullable=False)
    justification_budget = Column(Text, nullable=False)
    justification_critique = Column(Text, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index("ix_eval_runs_group", "group"),
        Index("ix_eval_runs_test_case", "test_case_id"),
    )


class PromptProposal(Base):
    """Proposed prompt rewrite from meta-agent."""
    __tablename__ = "prompt_proposals"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_id = Column(String, nullable=False)
    original_prompt = Column(Text, nullable=False)
    rewritten_prompt = Column(Text, nullable=False)
    unified_diff = Column(Text, nullable=False)
    justification = Column(Text, nullable=False)
    target_dimension = Column(String, nullable=False)
    expected_improvement = Column(Float, nullable=False)
    
    decision = Column(String, nullable=True)  # "approve", "reject", None
    reviewer_notes = Column(Text, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    __table_args__ = (
        Index("ix_proposals_decision", "decision"),
        Index("ix_proposals_created", "created_at"),
    )


class EvalDelta(Base):
    """Score deltas after rerunning eval with new prompt."""
    __tablename__ = "eval_deltas"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id = Column(UUID(as_uuid=True), ForeignKey("prompt_proposals.id"), nullable=False)
    test_case_id = Column(String, nullable=False)
    
    # Delta scores (new - old)
    delta_correctness = Column(Float, nullable=False)
    delta_citation = Column(Float, nullable=False)
    delta_contradiction = Column(Float, nullable=False)
    delta_efficiency = Column(Float, nullable=False)
    delta_budget = Column(Float, nullable=False)
    delta_critique = Column(Float, nullable=False)
    
    improvement_ratio = Column(Float, nullable=False)  # (sum of positive deltas) / (sum of absolute deltas)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("ix_deltas_proposal", "proposal_id"),
    )
