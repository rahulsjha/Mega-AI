"""
Decomposition Agent - breaks down complex queries into sub-tasks.

Output: Populates context.sub_tasks with explicit dependency edges.
"""

import logging
import json
import uuid
from typing import Optional
from api.context.schema import (
    AgentContext, SubTask, SubTaskType, SubTaskStatus, AgentOutput
)
from api.context.budget import ContextBudgetManager
import os

logger = logging.getLogger(__name__)

# Use environment to select LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")


class DecompositionAgent:
    """
    Decomposes a complex query into sub-tasks with dependencies.
    
    Uses structured output (JSON mode) to produce:
    - task_id
    - description
    - type (factual/analytical/creative)
    - depends_on: list[task_id]
    """
    
    def __init__(self):
        """Initialize the decomposition agent."""
        self.name = "decomposition"
        self.budget_tokens = 1500
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM client based on provider."""
        if LLM_PROVIDER == "anthropic":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        else:  # default to openai
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    async def execute(
        self,
        context: AgentContext,
        budget_manager: ContextBudgetManager
    ) -> AgentContext:
        """
        Execute the decomposition agent.
        
        Args:
            context: The shared agent context
            budget_manager: Budget manager for token tracking
            
        Returns:
            Updated context with sub_tasks populated
        """
        import time
        
        start_time = time.time()
        
        # Check budget
        remaining = budget_manager.check_remaining(self.name)
        if remaining <= 0:
            logger.error(f"Decomposition agent: budget exhausted")
            return context
        
        try:
            # Declare budget
            budget_manager.declare_budget(self.name, self.budget_tokens)
            
            logger.info(
                f"Decomposition agent starting for job {context.job_id}",
                extra={"job_id": str(context.job_id), "query": context.query}
            )
            
            # Create decomposition prompt
            prompt = self._create_prompt(context.query)
            
            # Call LLM
            response = await self._call_llm(prompt, context.job_id)
            
            # Parse response to extract tasks
            tasks = self._parse_response(response)
            
            # Add tasks to context
            for task in tasks:
                context.sub_tasks.append(task)
                logger.debug(
                    f"Task created: {task.id} - {task.description}",
                    extra={
                        "task_id": task.id,
                        "task_type": task.type,
                        "depends_on": task.depends_on
                    }
                )
            
            # Track token usage
            token_count = self._estimate_tokens(prompt + response)
            budget_manager.consume(self.name, token_count, context)
            
            # Record output
            latency_ms = (time.time() - start_time) * 1000
            context.agent_outputs[self.name] = AgentOutput(
                agent_name=self.name,
                result=f"Created {len(tasks)} sub-tasks",
                tokens_used=token_count,
                tool_calls_made=1,  # Called LLM once
                confidence=0.95
            )
            
            logger.info(
                f"Decomposition agent completed: {len(tasks)} tasks created",
                extra={
                    "job_id": str(context.job_id),
                    "task_count": len(tasks),
                    "latency_ms": latency_ms,
                    "tokens_used": token_count
                }
            )
            
            return context
        
        except Exception as e:
            logger.error(
                f"Decomposition agent failed: {str(e)}",
                extra={"job_id": str(context.job_id), "error": str(e)}
            )
            return context
    
    def _create_prompt(self, query: str) -> str:
        """Create decomposition prompt."""
        return f"""You are an expert at breaking down complex queries into manageable sub-tasks.

Given the following query, create a detailed breakdown into sub-tasks. Each task should have:
1. A unique task ID (format: task_N where N is a number)
2. A clear description of what the task involves
3. A type: one of "factual" (requires looking up information), 
   "analytical" (requires reasoning/analysis), or "creative" (requires generating new ideas)
4. Dependencies: list of other task IDs that must be completed first (may be empty)

Return your response as a JSON object with this structure:
{{
    "tasks": [
        {{
            "id": "task_1",
            "description": "...",
            "type": "factual",
            "depends_on": []
        }},
        ...
    ]
}}

Query: {query}

Return only valid JSON, no other text."""
    
    async def _call_llm(self, prompt: str, job_id) -> str:
        """Call the LLM with structured output."""
        try:
            if LLM_PROVIDER == "anthropic":
                message = self.client.messages.create(
                    model="claude-3-sonnet-20240229",
                    max_tokens=2000,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return message.content[0].text
            else:  # OpenAI
                response = self.client.chat.completions.create(
                    model="gpt-4-turbo-preview",
                    max_tokens=2000,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
        except Exception as e:
            logger.error(
                f"LLM call failed for decomposition: {str(e)}",
                extra={"job_id": str(job_id), "error": str(e)}
            )
            raise
    
    def _parse_response(self, response: str) -> list[SubTask]:
        """Parse LLM response into SubTask objects."""
        try:
            data = json.loads(response)
            tasks = []
            
            for task_data in data.get("tasks", []):
                task = SubTask(
                    id=task_data.get("id", f"task_{len(tasks)}"),
                    description=task_data.get("description", ""),
                    type=SubTaskType(task_data.get("type", "factual")),
                    depends_on=task_data.get("depends_on", []),
                    status=SubTaskStatus.PENDING
                )
                tasks.append(task)
            
            return tasks
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse decomposition response: {str(e)}")
            return []
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens using simple heuristic (1 token ≈ 4 chars)."""
        return max(1, len(text) // 4)
