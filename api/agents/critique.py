"""
Critique Agent - analyzes outputs for factual accuracy and contradictions.

Identifies specific spans in text that are problematic, with confidence scores.
Never flags the entire output - must identify specific spans.
"""

import logging
import json
import uuid
from typing import Optional
from api.context.schema import (
    AgentContext, CritiqueResult, AgentOutput
)
from api.context.budget import ContextBudgetManager
from api.llm import build_openrouter_llm
from langchain_openai import ChatOpenAI
import os

logger = logging.getLogger(__name__)

class CritiqueAgent:
    """
    Critiques outputs from other agents by identifying specific claims/spans
    that are flagged as problematic.
    
    For each output, produces: list of CritiqueResult with:
    - span (start/end char position)
    - claim text
    - confidence (0.0-1.0)
    - flagged: bool
    """
    
    def __init__(self):
        """Initialize the critique agent."""
        self.name = "critique"
        self.budget_tokens = 2000
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM client."""
        self.client = build_openrouter_llm(3000)
        if self.client is not None:
            return

        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    async def execute(
        self,
        context: AgentContext,
        budget_manager: ContextBudgetManager
    ) -> AgentContext:
        """
        Execute the critique agent.
        
        Analyzes every agent output that exists in context.agent_outputs.
        
        Args:
            context: The shared agent context
            budget_manager: Budget manager for token tracking
            
        Returns:
            Updated context with critique_results populated
        """
        import time
        
        start_time = time.time()
        
        # Check budget
        remaining = budget_manager.check_remaining(self.name)
        if remaining <= 0:
            logger.error(f"Critique agent: budget exhausted")
            return context
        
        try:
            budget_manager.declare_budget(self.name, self.budget_tokens)
            
            logger.info(
                f"Critique agent starting for job {context.job_id}",
                extra={"job_id": str(context.job_id)}
            )
            
            total_tokens = 0
            
            for agent_name, agent_output in context.agent_outputs.items():
                if not agent_output.result:
                    continue
                
                logger.debug(
                    f"Critiquing output from {agent_name}",
                    extra={"agent_name": agent_name}
                )
                
                prompt = self._create_prompt(agent_output.result, agent_name)
                await context.emit_event("TOOL_CALL", {
                    "tool_name": f"llm.critique.{agent_name}",
                    "tool_input": {"prompt_preview": prompt[:300], "source_agent": agent_name}
                }, agent_id=self.name)
                response = await self._call_llm(prompt, context.job_id)
                await context.emit_event("TOOL_RESULT", {
                    "tool_name": f"llm.critique.{agent_name}",
                    "tool_output": {"response_preview": response[:500], "chars": len(response)}
                }, agent_id=self.name)
                results = self._parse_response(response, agent_output.result, agent_name)
                context.critique_results.extend(results)
                token_count = self._estimate_tokens(prompt + response)
                total_tokens += token_count
                
                logger.debug(
                    f"Critique completed for {agent_name}: {len(results)} findings",
                    extra={
                        "agent_name": agent_name,
                        "findings_count": len(results),
                        "flagged_count": sum(1 for r in results if r.flagged)
                    }
                )


            budget_manager.consume(self.name, total_tokens, context)
            flagged_count = sum(1 for c in context.critique_results if c.flagged)
            latency_ms = (time.time() - start_time) * 1000
            
            context.agent_outputs[self.name] = AgentOutput(
                agent_name=self.name,
                result=f"Analyzed {len(context.agent_outputs)} outputs, found {flagged_count} issues",
                tokens_used=total_tokens,
                tool_calls_made=len(context.agent_outputs),
                confidence=0.85
            )
            
            logger.info(
                f"Critique agent completed: {flagged_count} issues flagged",
                extra={
                    "job_id": str(context.job_id),
                    "total_critiques": len(context.critique_results),
                    "flagged_count": flagged_count,
                    "latency_ms": latency_ms
                }
            )
            
            return context
        
        except Exception as e:
            logger.error(
                f"Critique agent failed: {str(e)}",
                extra={"job_id": str(context.job_id), "error": str(e)}
            )
            return context
    
    def _create_prompt(self, output: str, agent_name: str) -> str:
        """Create critique prompt."""
        return f"""You are a rigorous fact-checker and logical analyzer. Your job is to examine the following 
output from the '{agent_name}' agent and identify specific claims or statements that are problematic.

You should look for:
1. Factually incorrect statements
2. Logical contradictions
3. Unsupported claims
4. Ambiguous or misleading language
5. Missing important context

For each problematic span, provide:
- The exact character positions (start and end index in the text)
- The claim/statement itself
- Your confidence that this is actually a problem (0.0-1.0)
- Whether to flag it as significant (true if this should be corrected)
- Your reasoning

Return as JSON:
{{
    "critiques": [
        {{
            "span_start": 10,
            "span_end": 45,
            "claim": "the exact text from the output",
            "confidence": 0.85,
            "flagged": true,
            "reasoning": "explanation of why this is problematic"
        }}
    ]
}}

If you find no issues, return empty critiques array.

Output to critique:
{output}

Return only valid JSON, no other text."""
    
    async def _call_llm(self, prompt: str, job_id) -> str:
        """Call the LLM."""
        try:
            if isinstance(self.client, ChatOpenAI):
                message = self.client.invoke(prompt)
                return message.content
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                max_tokens=3000,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM call failed for critique: {str(e)}")
            raise
    
    def _parse_response(
        self,
        response: str,
        original_output: str,
        agent_name: str
    ) -> list[CritiqueResult]:
        """Parse LLM response into CritiqueResult objects."""
        try:
            data = json.loads(response)
            results = []
            
            for critique_data in data.get("critiques", []):
                result = CritiqueResult(
                    id=str(uuid.uuid4()),
                    span_start=critique_data.get("span_start", 0),
                    span_end=critique_data.get("span_end", 1),
                    claim=critique_data.get("claim", ""),
                    confidence=critique_data.get("confidence", 0.5),
                    flagged=critique_data.get("flagged", False),
                    reasoning=critique_data.get("reasoning", ""),
                    source_agent=agent_name
                )
                results.append(result)
            
            return results
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse critique response: {str(e)}")
            return []
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens using simple heuristic (1 token ≈ 4 chars)."""
        return max(1, len(text) // 4)
