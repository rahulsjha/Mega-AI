"""
Integration tests for core system components.
"""

import pytest
from uuid import uuid4
from api.context.schema import (
    AgentContext, SubTask, SubTaskStatus, SubTaskType,
    Chunk, AgentOutput, CritiqueResult, ProvenanceEntry,
    PolicyViolation
)
from api.context.budget import ContextBudgetManager


class TestAgentContextModel:
    """Test AgentContext data model."""

    def test_create_context(self):
        """Test creating AgentContext."""
        job_id = uuid4()
        query = "What is AI?"
        
        context = AgentContext(job_id=job_id, query=query)
        
        assert context.job_id == job_id
        assert context.query == query
        assert len(context.sub_tasks) == 0
        assert len(context.retrieved_chunks) == 0

    def test_add_sub_tasks(self):
        """Test adding sub-tasks."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        task1 = SubTask(
            id="t1",
            description="First task",
            type=SubTaskType.FACTUAL,
            depends_on=[]
        )
        task2 = SubTask(
            id="t2",
            description="Second task",
            type=SubTaskType.ANALYTICAL,
            depends_on=["t1"]
        )
        
        context.sub_tasks.append(task1)
        context.sub_tasks.append(task2)
        
        assert len(context.sub_tasks) == 2
        assert context.sub_tasks[0].description == "First task"
        assert context.sub_tasks[1].depends_on == ["t1"]

    def test_add_retrieved_chunks(self):
        """Test adding retrieved chunks."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        chunk = Chunk(
            id="c1",
            content="AI is amazing",
            source_url="https://example.com",
            relevance_score=0.95
        )
        
        context.retrieved_chunks.append(chunk)
        
        assert len(context.retrieved_chunks) == 1
        assert context.retrieved_chunks[0].content == "AI is amazing"
        assert context.retrieved_chunks[0].relevance_score == 0.95

    def test_add_agent_outputs(self):
        """Test adding agent outputs."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        output = AgentOutput(
            agent_name="rag",
            result="Retrieved information about AI"
        )
        
        context.agent_outputs["rag"] = output
        
        assert "rag" in context.agent_outputs
        assert context.agent_outputs["rag"].result.startswith("Retrieved")

    def test_add_critique_results(self):
        """Test adding critique results."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        critique = CritiqueResult(
            id="crit1",
            span_start=0,
            span_end=10,
            claim="False claim",
            confidence=0.95,
            flagged=True,
            reasoning="This is incorrect",
            source_agent="test"
        )
        
        context.critique_results.append(critique)
        
        assert len(context.critique_results) == 1
        assert context.critique_results[0].flagged
        assert context.critique_results[0].confidence == 0.95

    def test_add_provenance_entries(self):
        """Test adding provenance entries."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        entry = ProvenanceEntry(
            sentence_idx=0,
            sentence_text="AI is transformative",
            source_agent="rag",
            source_chunk_id="c1",
            confidence=0.92
        )
        
        context.provenance_map.append(entry)
        
        assert len(context.provenance_map) == 1
        assert context.provenance_map[0].source_agent == "rag"

    def test_record_policy_violation(self):
        """Test recording policy violations."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        violation = PolicyViolation(
            id="v1",
            violation_type="budget_exceeded",
            severity="warning",
            agent_name="rag",
            description="Over budget"
        )
        
        context.policy_violations.append(violation)
        
        assert len(context.policy_violations) == 1
        assert context.policy_violations[0].severity == "warning"


class TestContextBudgetIntegration:
    """Integration tests for context budget manager."""

    def test_complete_budget_lifecycle(self):
        """Test complete budget lifecycle."""
        mgr = ContextBudgetManager(default_budget_tokens=5000)
        context = AgentContext(job_id=uuid4(), query="Test")
        
        # 1. Declare budgets
        mgr.declare_budget("agent1", 2000)
        mgr.declare_budget("agent2", 1500)
        
        # 2. Sync to context
        mgr.sync_to_context(context)
        assert "agent1" in context.context_budget
        
        # 3. Consume tokens
        assert mgr.consume("agent1", 1000)
        assert mgr.check_remaining("agent1") == 1000
        
        # 4. Consume more
        assert mgr.consume("agent1", 900)
        assert mgr.check_remaining("agent1") == 100
        
        # 5. Over budget
        assert not mgr.consume("agent1", 200, context)
        assert len(context.policy_violations) > 0

    def test_compression_triggered(self):
        """Test compression trigger at 80%."""
        mgr = ContextBudgetManager(default_budget_tokens=1000)
        context = AgentContext(job_id=uuid4(), query="Test")
        
        mgr.declare_budget("agent1", 1000)
        
        # Consume to 80%
        mgr.consume("agent1", 800, context)
        
        # Check compression flag
        assert context.metadata.get("needs_compression") == True

    def test_multiple_agents_budget_tracking(self):
        """Test tracking multiple agent budgets."""
        mgr = ContextBudgetManager(default_budget_tokens=3000)
        context = AgentContext(job_id=uuid4(), query="Test")
        
        mgr.declare_budget("decomp", 1000)
        mgr.declare_budget("rag", 1200)
        mgr.declare_budget("synthesis", 800)
        
        # Consume across agents
        assert mgr.consume("decomp", 500)
        assert mgr.consume("rag", 600)
        assert mgr.consume("synthesis", 400)
        
        # Check remaining
        assert mgr.check_remaining("decomp") == 500
        assert mgr.check_remaining("rag") == 600
        assert mgr.check_remaining("synthesis") == 400
        
        # Sync and verify
        mgr.sync_to_context(context)
        assert context.context_budget["decomp"].consumed_tokens == 500


class TestSubTaskDependencies:
    """Test sub-task dependency management."""

    def test_dependency_graph(self):
        """Test sub-task dependency graph."""
        context = AgentContext(job_id=uuid4(), query="Complex query")
        
        # Create tasks with dependencies
        task1 = SubTask(
            id="t1",
            description="Find definition",
            type=SubTaskType.FACTUAL,
            depends_on=[]
        )
        task2 = SubTask(
            id="t2",
            description="List examples",
            type=SubTaskType.ANALYTICAL,
            depends_on=["t1"]
        )
        task3 = SubTask(
            id="t3",
            description="Compare approaches",
            type=SubTaskType.ANALYTICAL,
            depends_on=["t1", "t2"]
        )
        
        context.sub_tasks.extend([task1, task2, task3])
        
        # Verify dependencies
        assert context.sub_tasks[0].depends_on == []
        assert context.sub_tasks[1].depends_on == ["t1"]
        assert context.sub_tasks[2].depends_on == ["t1", "t2"]

    def test_task_status_transitions(self):
        """Test task status transitions."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        task = SubTask(
            id="t1",
            description="Test",
            type=SubTaskType.FACTUAL,
            status=SubTaskStatus.PENDING
        )
        
        context.sub_tasks.append(task)
        
        # Update status
        context.sub_tasks[0].status = SubTaskStatus.IN_PROGRESS
        assert context.sub_tasks[0].status == SubTaskStatus.IN_PROGRESS
        
        context.sub_tasks[0].status = SubTaskStatus.COMPLETED
        assert context.sub_tasks[0].status == SubTaskStatus.COMPLETED


class TestRetrievalAndRanking:
    """Test retrieved chunks and ranking."""

    def test_chunk_relevance_scoring(self):
        """Test chunk relevance scoring."""
        context = AgentContext(job_id=uuid4(), query="What is AI?")
        
        # Add chunks with varying relevance
        chunks = [
            Chunk(id="c1", content="AI definition", source_url="url1", relevance_score=0.95),
            Chunk(id="c2", content="AI history", source_url="url2", relevance_score=0.78),
            Chunk(id="c3", content="AI applications", source_url="url3", relevance_score=0.82),
        ]
        
        context.retrieved_chunks.extend(chunks)
        
        # Verify scores
        scores = [c.relevance_score for c in context.retrieved_chunks]
        assert max(scores) == 0.95
        assert len(scores) == 3
        assert all(0 <= s <= 1 for s in scores)

    def test_chunk_deduplication(self):
        """Test chunk deduplication."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        # Add duplicate chunks
        chunk1 = Chunk(id="c1", content="AI", source_url="url1", relevance_score=0.9)
        chunk2 = Chunk(id="c1", content="AI", source_url="url1", relevance_score=0.85)
        
        context.retrieved_chunks.append(chunk1)
        context.retrieved_chunks.append(chunk2)
        
        # Manual deduplication
        unique_ids = set(c.id for c in context.retrieved_chunks)
        assert len(unique_ids) == 1


class TestCritiqueSpanAnalysis:
    """Test critique span identification."""

    def test_span_based_critique(self):
        """Test span-based critique results."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        # Add critique with specific spans
        critique = CritiqueResult(
            id="c1",
            span_start=10,
            span_end=45,
            claim="Specific claim",
            confidence=0.98,
            flagged=True,
            reasoning="This is problematic",
            source_agent="test"
        )
        
        context.critique_results.append(critique)
        
        # Verify spans
        assert context.critique_results[0].span_start == 10
        assert context.critique_results[0].span_end == 45
        assert context.critique_results[0].confidence == 0.98

    def test_multiple_flagged_items(self):
        """Test multiple flagged critique items."""
        context = AgentContext(job_id=uuid4(), query="Test")
        
        critiques = [
            CritiqueResult(
                id="c1",
                span_start=0,
                span_end=10,
                claim="First issue",
                confidence=0.95,
                flagged=True,
                reasoning="First problem",
                source_agent="test"
            ),
            CritiqueResult(
                id="c2",
                span_start=50,
                span_end=70,
                claim="Second issue",
                confidence=0.88,
                flagged=True,
                reasoning="Second problem",
                source_agent="test"
            ),
            CritiqueResult(
                id="c3",
                span_start=100,
                span_end=110,
                claim="Minor concern",
                confidence=0.65,
                flagged=False,
                reasoning="Minor issue",
                source_agent="test"
            ),
        ]
        
        context.critique_results.extend(critiques)
        
        flagged = [c for c in context.critique_results if c.flagged]
        assert len(flagged) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
