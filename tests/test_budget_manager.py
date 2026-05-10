"""
Unit tests for context budget manager.
"""

import pytest
from api.context.budget import ContextBudgetManager
from api.context.schema import AgentContext, PolicyViolation
from uuid import uuid4


@pytest.fixture
def budget_manager():
    """Create fresh budget manager."""
    return ContextBudgetManager(default_budget_tokens=1000)


@pytest.fixture
def context():
    """Create test context."""
    return AgentContext(
        job_id=uuid4(),
        query="Test query"
    )


def test_declare_budget(budget_manager):
    """Test budget declaration."""
    budget = budget_manager.declare_budget("agent1", 500)
    
    assert budget.agent_name == "agent1"
    assert budget.max_tokens == 500
    assert budget.consumed_tokens == 0
    assert budget.remaining_tokens == 500


def test_consume_tokens(budget_manager):
    """Test token consumption."""
    budget_manager.declare_budget("agent1", 500)
    
    success = budget_manager.consume("agent1", 200)
    
    assert success
    assert budget_manager.budgets["agent1"].consumed_tokens == 200
    assert budget_manager.check_remaining("agent1") == 300


def test_consume_exceeds_budget(budget_manager, context):
    """Test consuming over budget."""
    budget_manager.declare_budget("agent1", 500)
    budget_manager.consume("agent1", 400)
    
    success = budget_manager.consume("agent1", 200, context)
    
    assert not success
    assert len(context.policy_violations) == 1
    assert context.policy_violations[0].violation_type == "budget_exceeded"


def test_compression_threshold(budget_manager, context):
    """Test compression threshold detection."""
    budget_manager.declare_budget("agent1", 1000)
    budget_manager.consume("agent1", 850, context)
    
    # Should trigger compression alert
    assert context.metadata.get("needs_compression") == True


def test_sync_to_context(budget_manager, context):
    """Test syncing budget to context."""
    budget_manager.declare_budget("agent1", 500)
    budget_manager.declare_budget("agent2", 600)
    
    budget_manager.sync_to_context(context)
    
    assert "agent1" in context.context_budget
    assert "agent2" in context.context_budget
    assert context.context_budget["agent1"].max_tokens == 500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
