"""
Core Pydantic models for agent communication and context management.

AgentContext is the ONLY way agents communicate. Every agent receives it,
mutates its slice, and returns it to the orchestrator.
"""

import logging
from enum import Enum
from typing import Optional, Any, Dict, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SubTaskType(str, Enum):
    """Types of sub-tasks the decomposition agent can generate."""
    FACTUAL = "factual"
    ANALYTICAL = "analytical"
    CREATIVE = "creative"


class SubTaskStatus(str, Enum):
    """Status of a sub-task during execution."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SubTask(BaseModel):
    """Represents a sub-task created by the decomposition agent."""
    id: str = Field(..., description="Unique task ID")
    description: str = Field(..., description="Human-readable task description")
    type: SubTaskType = Field(..., description="Type of task")
    status: SubTaskStatus = Field(default=SubTaskStatus.PENDING, description="Current status")
    depends_on: List[str] = Field(default_factory=list, description="List of task IDs this depends on")
    result: Optional[str] = Field(default=None, description="Result when completed")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)


class Chunk(BaseModel):
    """Represents a retrieved chunk from the RAG system."""
    id: str = Field(..., description="Unique chunk ID")
    content: str = Field(..., description="Text content of the chunk")
    source_url: str = Field(..., description="URL or source of the chunk")
    relevance_score: float = Field(..., ge=0.0, le=1.0, description="Relevance score 0-1")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)


class ToolCallRecord(BaseModel):
    """Record of a tool call with full tracing information."""
    id: str = Field(..., description="Unique tool call ID")
    tool_name: str = Field(..., description="Name of the tool called")
    input_hash: str = Field(..., description="SHA256 hash of input")
    input_preview: str = Field(..., description="Preview of input for readability")
    output_hash: str = Field(..., description="SHA256 hash of output")
    output_preview: str = Field(..., description="Preview of output")
    latency_ms: float = Field(..., description="Execution time in milliseconds")
    attempt_number: int = Field(default=1, description="Which attempt (for retries)")
    accepted: bool = Field(default=True, description="Whether result was accepted")
    rejection_reason: Optional[str] = Field(default=None, description="Why rejected if applicable")
    called_by_agent: str = Field(..., description="Which agent called this tool")
    called_at: datetime = Field(default_factory=datetime.utcnow)
    error_type: Optional[str] = Field(default=None, description="Error type if failed")


class CritiqueResult(BaseModel):
    """Result from the critique agent for a specific claim."""
    id: str = Field(..., description="Unique critique ID")
    span_start: int = Field(..., description="Character position where claim starts")
    span_end: int = Field(..., description="Character position where claim ends")
    claim: str = Field(..., description="The actual claim text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in critique 0-1")
    flagged: bool = Field(default=False, description="Whether this is flagged as problematic")
    reasoning: str = Field(..., description="Why this claim was flagged/approved")
    source_agent: str = Field(..., description="Which agent produced this claim")


class ProvenanceEntry(BaseModel):
    """Links a sentence/claim to its source agent and optionally source chunk."""
    sentence_idx: int = Field(..., description="Index in final answer")
    sentence_text: str = Field(..., description="The sentence text")
    source_agent: str = Field(..., description="Which agent provided this")
    source_chunk_id: Optional[str] = Field(default=None, description="Which chunk if from RAG")
    confidence: float = Field(default=1.0, description="Confidence score")


class TokenBudget(BaseModel):
    """Token budget tracking for an agent."""
    agent_name: str = Field(..., description="Name of the agent")
    max_tokens: int = Field(..., description="Maximum tokens allowed")
    consumed_tokens: int = Field(default=0, description="Tokens consumed so far")
    compressed_tokens: int = Field(default=0, description="Tokens freed by compression")
    
    @property
    def remaining_tokens(self) -> int:
        """Calculate remaining tokens."""
        return self.max_tokens - self.consumed_tokens
    
    @property
    def percent_used(self) -> float:
        """Calculate percentage of budget used."""
        return (self.consumed_tokens / self.max_tokens * 100) if self.max_tokens > 0 else 0.0


class PolicyViolation(BaseModel):
    """Record of a policy violation."""
    id: str = Field(..., description="Unique violation ID")
    violation_type: str = Field(..., description="Type of violation (e.g., budget_exceeded)")
    severity: str = Field(..., description="critical, warning, info")
    agent_name: str = Field(..., description="Which agent caused it")
    description: str = Field(..., description="What happened")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class AgentOutput(BaseModel):
    """Output from an agent execution."""
    agent_name: str = Field(..., description="Which agent produced this")
    result: str = Field(..., description="The actual result/output")
    tokens_used: int = Field(default=0, description="Tokens used by this agent")
    tool_calls_made: int = Field(default=0, description="Number of tools called")
    confidence: float = Field(default=1.0, description="Confidence in the result")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RoutingDecision(BaseModel):
    """Decision made by the orchestrator on which agent to run next."""
    next_agent: str = Field(..., description="decomposition|rag|critique|synthesis|done")
    justification: str = Field(..., description="Why this decision was made")
    context_budget_allocation: Dict[str, int] = Field(
        default_factory=dict,
        description="Token allocation for next agent"
    )
    confidence: float = Field(default=1.0, description="Confidence in routing decision")


class CompressionRecord(BaseModel):
    """Record of compression performed on the context."""
    original_tokens: int = Field(..., description="Tokens before compression")
    compressed_tokens: int = Field(..., description="Tokens after compression")
    compression_ratio: float = Field(..., description="Ratio of compression")
    sections_compressed: List[str] = Field(..., description="Which sections were compressed")
    compressed_at: datetime = Field(default_factory=datetime.utcnow)


class AgentContext(BaseModel):
    """
    Shared context object that is the ONLY way agents communicate.
    
    All agents receive the full context, mutate their assigned fields,
    and return it to the orchestrator. No agent calls another directly.
    """

    job_id: UUID = Field(..., description="Unique job identifier")
    session_id: Optional[UUID] = Field(default=None, description="Session identifier")
    query: str = Field(..., description="Original user query")
    sub_tasks: List[SubTask] = Field(default_factory=list, description="Tasks from decomposition")
    retrieved_chunks: List[Chunk] = Field(default_factory=list, description="Retrieved chunks")
    retrieval_iteration: int = Field(default=0, description="Which retrieval iteration we're on")


    agent_outputs: Dict[str, AgentOutput] = Field(
        default_factory=dict,
        description="Results from each agent"
    )
    
    critique_results: List[CritiqueResult] = Field(
        default_factory=list,
        description="All critique results"
    )
    
    final_answer: Optional[str] = Field(default=None, description="Final synthesized answer")
    
    provenance_map: List[ProvenanceEntry] = Field(
        default_factory=list,
        description="Links sentences to sources"
    )
    
    context_budget: Dict[str, TokenBudget] = Field(
        default_factory=dict,
        description="Budget tracking per agent"
    )
    compression_records: List[CompressionRecord] = Field(
        default_factory=list,
        description="History of compressions applied"
    )
    
    tool_call_log: List[ToolCallRecord] = Field(
        default_factory=list,
        description="All tool calls made during execution"
    )
    
    policy_violations: List[PolicyViolation] = Field(
        default_factory=list,
        description="Any policy violations that occurred"
    )
    
    routing_history: List[RoutingDecision] = Field(
        default_factory=list,
        description="History of orchestrator routing decisions"
    )
    iteration_count: int = Field(default=0, description="Current iteration number")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)
    
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    
    event_callbacks: List[Any] = Field(
        default_factory=list,
        description="Callbacks to emit events for SSE streaming"
    )
    
    class Config:
        arbitrary_types_allowed = True
    
    def model_dump_json(self, **kwargs) -> str:
        return super().model_dump_json(**kwargs)
    
    async def emit_event(self, event_type: str, data: Dict[str, Any], agent_id: Optional[str] = None, latency_ms: float = 0.0):
        """
        Emit an event to all registered callbacks.
        
        Args:
            event_type: Type of event (agent_start, token, tool_call, etc.)
            data: Event-specific data dictionary
            agent_id: Optional agent ID for the event
            latency_ms: Optional latency in milliseconds
        """
        event = {
            "event_type": event_type,
            "job_id": str(self.job_id),
            "agent_id": agent_id,
            "data": data,
            "latency_ms": latency_ms,
            "timestamp": datetime.utcnow().isoformat()
        }
        for callback in self.event_callbacks:
            try:
                if callable(callback):
                    await callback(event) if hasattr(callback, '__await__') else callback(event)
            except Exception as e:
                logger.warning(f"Event callback failed: {e}")
