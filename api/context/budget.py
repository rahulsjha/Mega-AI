"""
Context Budget Manager - manages token allocation and consumption tracking.

Ensures agents stay within budget, tracks compression, and logs policy violations.
"""

import logging
from typing import Dict, Optional
from api.context.schema import AgentContext, TokenBudget, PolicyViolation
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


class ContextBudgetManager:
    """
    Manages context token budgets for all agents.
    
    Responsibilities:
    - Declare budgets for each agent
    - Track consumption
    - Trigger compression when needed
    - Log policy violations
    """
    
    def __init__(self, default_budget_tokens: int = 4000):
        """
        Initialize the budget manager.
        
        Args:
            default_budget_tokens: Default token budget per agent
        """
        self.default_budget_tokens = default_budget_tokens
        self.budgets: Dict[str, TokenBudget] = {}
    
    def declare_budget(self, agent_name: str, max_tokens: Optional[int] = None) -> TokenBudget:
        """
        Declare a budget for an agent.
        
        Args:
            agent_name: Name of the agent
            max_tokens: Maximum tokens (uses default if None)
            
        Returns:
            The TokenBudget object
        """
        if max_tokens is None:
            max_tokens = self.default_budget_tokens
        
        budget = TokenBudget(
            agent_name=agent_name,
            max_tokens=max_tokens,
            consumed_tokens=0,
            compressed_tokens=0
        )
        self.budgets[agent_name] = budget
        logger.info(
            f"Budget declared for {agent_name}: {max_tokens} tokens",
            extra={"agent_name": agent_name, "max_tokens": max_tokens}
        )
        return budget
    
    def check_remaining(self, agent_name: str) -> int:
        """
        Check remaining tokens for an agent.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            Remaining tokens (0 if over budget)
        """
        if agent_name not in self.budgets:
            self.declare_budget(agent_name)
        
        budget = self.budgets[agent_name]
        return max(0, budget.remaining_tokens)
    
    def consume(
        self,
        agent_name: str,
        tokens: int,
        context: Optional[AgentContext] = None
    ) -> bool:
        """
        Consume tokens from an agent's budget.
        
        Args:
            agent_name: Name of the agent
            tokens: Number of tokens to consume
            context: Context object to record violations
            
        Returns:
            True if consumption succeeded, False if over budget
        """
        if agent_name not in self.budgets:
            self.declare_budget(agent_name)
        
        budget = self.budgets[agent_name]
        
        # Check if this would exceed budget
        if budget.consumed_tokens + tokens > budget.max_tokens:
            logger.warning(
                f"Budget exceeded for {agent_name}: "
                f"attempted {tokens} tokens, only {budget.remaining_tokens} available",
                extra={
                    "agent_name": agent_name,
                    "tokens_requested": tokens,
                    "tokens_remaining": budget.remaining_tokens
                }
            )
            
            # Record policy violation if context provided
            if context:
                violation = PolicyViolation(
                    id=str(uuid.uuid4()),
                    violation_type="budget_exceeded",
                    severity="critical",
                    agent_name=agent_name,
                    description=(
                        f"Agent attempted to consume {tokens} tokens "
                        f"but only {budget.remaining_tokens} available"
                    ),
                    context={
                        "tokens_requested": tokens,
                        "max_budget": budget.max_tokens,
                        "already_consumed": budget.consumed_tokens,
                        "remaining": budget.remaining_tokens
                    }
                )
                context.policy_violations.append(violation)
            
            return False
        
        budget.consumed_tokens += tokens
        logger.debug(
            f"Tokens consumed for {agent_name}: {tokens} "
            f"(total: {budget.consumed_tokens}/{budget.max_tokens})",
            extra={
                "agent_name": agent_name,
                "tokens_consumed": tokens,
                "percent_used": budget.percent_used
            }
        )
        
        # Check if compression threshold reached (80%)
        if budget.percent_used >= 80:
            logger.info(
                f"Compression threshold reached for {agent_name}: {budget.percent_used:.1f}% used",
                extra={"agent_name": agent_name, "percent_used": budget.percent_used}
            )
            if context:
                # Mark that compression is needed
                context.metadata["needs_compression"] = True
        
        return True
    
    def get_budget_status(self, agent_name: str) -> Dict:
        """
        Get detailed budget status for an agent.
        
        Args:
            agent_name: Name of the agent
            
        Returns:
            Dictionary with budget status
        """
        if agent_name not in self.budgets:
            self.declare_budget(agent_name)
        
        budget = self.budgets[agent_name]
        return {
            "agent_name": agent_name,
            "max_tokens": budget.max_tokens,
            "consumed_tokens": budget.consumed_tokens,
            "remaining_tokens": budget.remaining_tokens,
            "compressed_tokens": budget.compressed_tokens,
            "percent_used": budget.percent_used,
            "at_threshold": budget.percent_used >= 80
        }
    
    def record_compression(
        self,
        agent_name: str,
        tokens_freed: int,
        context: Optional[AgentContext] = None
    ) -> None:
        """
        Record that compression freed up tokens for an agent.
        
        Args:
            agent_name: Name of the agent
            tokens_freed: Number of tokens freed by compression
            context: Context to record in
        """
        if agent_name not in self.budgets:
            self.declare_budget(agent_name)
        
        budget = self.budgets[agent_name]
        budget.compressed_tokens += tokens_freed
        
        logger.info(
            f"Compression recorded for {agent_name}: {tokens_freed} tokens freed",
            extra={"agent_name": agent_name, "tokens_freed": tokens_freed}
        )
    
    def sync_to_context(self, context: AgentContext) -> None:
        """
        Synchronize all budget states into the context object.
        
        Args:
            context: The context to update
        """
        context.context_budget = dict(self.budgets)
        logger.debug("Budget state synchronized to context")
    
    def load_from_context(self, context: AgentContext) -> None:
        """
        Load budget state from a context object.
        
        Args:
            context: The context to load from
        """
        self.budgets = dict(context.context_budget)
        logger.debug("Budget state loaded from context")
