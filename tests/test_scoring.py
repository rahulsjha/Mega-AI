"""
Tests for scoring functions.
"""

import pytest
from api.context.schema import (
    AgentContext, CritiqueResult, ProvenanceEntry, Chunk, AgentOutput, PolicyViolation
)
from api.eval.scoring import ScoringEngine, compute_all_scores
from uuid import uuid4


@pytest.fixture
def context():
    """Create test context."""
    return AgentContext(
        job_id=uuid4(),
        query="What is AI?"
    )


def test_answer_correctness_exact_match():
    """Test exact match scoring."""
    score, justif = ScoringEngine.score_answer_correctness(
        "Artificial Intelligence is the simulation of human intelligence",
        "Artificial Intelligence is the simulation of human intelligence"
    )
    assert score == 1.0


def test_answer_correctness_partial_match():
    """Test partial match scoring."""
    score, justif = ScoringEngine.score_answer_correctness(
        "Artificial Intelligence enables computers to learn",
        "Artificial Intelligence"
    )
    assert score > 0.5


def test_answer_correctness_no_match():
    """Test no match scoring."""
    score, justif = ScoringEngine.score_answer_correctness(
        "The weather is nice today",
        "Artificial Intelligence"
    )
    assert score < 0.2


def test_citation_accuracy(context):
    """Test citation accuracy scoring."""
    # Add chunks
    chunk = Chunk(
        id="chunk_1",
        content="AI is great",
        source_url="https://example.com",
        relevance_score=0.9
    )
    context.retrieved_chunks.append(chunk)
    
    # Add valid provenance
    prov = ProvenanceEntry(
        sentence_idx=0,
        sentence_text="AI is great",
        source_agent="rag",
        source_chunk_id="chunk_1"
    )
    context.provenance_map.append(prov)
    
    score, justif = ScoringEngine.score_citation_accuracy(context)
    assert score == 1.0


def test_contradiction_resolution(context):
    """Test contradiction resolution scoring."""
    # Add flagged critique
    critique = CritiqueResult(
        id="c1",
        span_start=0,
        span_end=10,
        claim="test",
        confidence=0.9,
        flagged=True,
        reasoning="test",
        source_agent="test"
    )
    context.critique_results.append(critique)
    
    # Add synthesis output mentioning resolution
    output = AgentOutput(
        agent_name="synthesis",
        result="We resolved this contradiction by..."
    )
    context.agent_outputs["synthesis"] = output
    
    score, justif = ScoringEngine.score_contradiction_resolution(context)
    assert score > 0.0


def test_budget_compliance(context):
    """Test budget compliance scoring."""
    # No violations
    score, justif = ScoringEngine.score_budget_compliance(context)
    assert score == 1.0
    
    # Add violation
    violation = PolicyViolation(
        id="v1",
        violation_type="budget_exceeded",
        severity="critical",
        agent_name="test",
        description="Over budget"
    )
    context.policy_violations.append(violation)
    
    score, justif = ScoringEngine.score_budget_compliance(context)
    assert score < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
