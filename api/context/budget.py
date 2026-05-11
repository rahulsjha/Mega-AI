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
        self.default_budget_tokens = default_budget_tokens
        self.budgets: Dict[str, TokenBudget] = {}
    
    def declare_budget(self, agent_name: str, max_tokens: Optional[int] = None) -> TokenBudget:
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
        if agent_name not in self.budgets:
            self.declare_budget(agent_name)
        
        budget = self.budgets[agent_name]
        
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
        
        if budget.percent_used >= 80:
            logger.info(
                f"Compression threshold reached for {agent_name}: {budget.percent_used:.1f}% used",
                extra={"agent_name": agent_name, "percent_used": budget.percent_used}
            )
            if context:
                context.metadata["needs_compression"] = True
        
        return True
    
    def get_budget_status(self, agent_name: str) -> Dict:
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

    def total_tokens_used(self) -> int:
        """Return the total tokens consumed across all tracked budgets."""
        return sum(budget.consumed_tokens for budget in self.budgets.values())

    def total_tokens_available(self) -> int:
        """Return the total budget capacity across all tracked budgets."""
        return sum(budget.max_tokens for budget in self.budgets.values())

    def remaining_percentage(self) -> float:
        """Return the remaining percentage across all tracked budgets."""
        total_available = self.total_tokens_available()
        if total_available <= 0:
            return 0.0
        remaining = total_available - self.total_tokens_used()
        return max(0.0, (remaining / total_available) * 100)
    
    def record_compression(
        self,
        agent_name: str,
        tokens_freed: int,
        context: Optional[AgentContext] = None
    ) -> None:
        if agent_name not in self.budgets:
            self.declare_budget(agent_name)
        
        budget = self.budgets[agent_name]
        budget.compressed_tokens += tokens_freed
        
        logger.info(
            f"Compression recorded for {agent_name}: {tokens_freed} tokens freed",
            extra={"agent_name": agent_name, "tokens_freed": tokens_freed}
        )
    
    def sync_to_context(self, context: AgentContext) -> None:
        context.context_budget = dict(self.budgets)
        logger.debug("Budget state synchronized to context")
    
    def load_from_context(self, context: AgentContext) -> None:
        self.budgets = dict(context.context_budget)
        logger.debug("Budget state loaded from context")
