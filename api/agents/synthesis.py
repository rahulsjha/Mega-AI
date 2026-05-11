"""
Synthesis Agent - combines all agent outputs into a final answer.

Resolves every flagged contradiction explicitly and creates provenance map
linking each sentence to its source_agent and optional chunk_id.
"""

import logging
import json
import uuid
from typing import Optional
from api.context.schema import (
    AgentContext, AgentOutput, ProvenanceEntry
)
from api.context.budget import ContextBudgetManager
from api.llm import build_openrouter_llm
from langchain_openai import ChatOpenAI
import os

logger = logging.getLogger(__name__)

class SynthesisAgent:
    """
    Synthesizes all agent outputs into a final answer, resolving contradictions.
    
    Reads:
    - All agent outputs
    - Critique flags
    - Retrieved chunks
    - Provenance information
    
    Produces:
    - final_answer
    - provenance_map linking sentences to sources
    """
    
    def __init__(self):
        """Initialize the synthesis agent."""
        self.name = "synthesis"
        self.budget_tokens = 3000
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM client."""
        self.client = build_openrouter_llm(4000)
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
        Execute the synthesis agent.
        
        Args:
            context: The shared agent context
            budget_manager: Budget manager for token tracking
            
        Returns:
            Updated context with final_answer and provenance_map populated
        """
        import time
        
        start_time = time.time()
        
        # Check budget
        remaining = budget_manager.check_remaining(self.name)
        if remaining <= 0:
            logger.error(f"Synthesis agent: budget exhausted")
            return context
        
        try:
            budget_manager.declare_budget(self.name, self.budget_tokens)
            
            logger.info(
                f"Synthesis agent starting for job {context.job_id}",
                extra={"job_id": str(context.job_id)}
            )
            
            synthesis_context = self._build_context(context)
            prompt = self._create_prompt(synthesis_context, context)
            await context.emit_event("TOOL_CALL", {
                "tool_name": "llm.synthesis",
                "tool_input": {"prompt_preview": prompt[:300], "context_summary_preview": synthesis_context[:300]}
            }, agent_id=self.name)
            response = await self._call_llm(prompt, context.job_id)
            await context.emit_event("TOOL_RESULT", {
                "tool_name": "llm.synthesis",
                "tool_output": {"response_preview": response[:500], "chars": len(response)}
            }, agent_id=self.name)
            final_answer, reasoning = self._parse_response(response)
            context.final_answer = final_answer
            self._build_provenance_map(context, final_answer)
            token_count = self._estimate_tokens(prompt + response)
            budget_manager.consume(self.name, token_count, context)

            latency_ms = (time.time() - start_time) * 1000
            context.agent_outputs[self.name] = AgentOutput(
                agent_name=self.name,
                result=final_answer,
                tokens_used=token_count,
                tool_calls_made=1,
                confidence=0.9
            )
            
            flagged_count = sum(1 for c in context.critique_results if c.flagged)
            logger.info(
                f"Synthesis agent completed",
                extra={
                    "job_id": str(context.job_id),
                    "flagged_contradictions": flagged_count,
                    "provenance_entries": len(context.provenance_map),
                    "latency_ms": latency_ms,
                    "tokens_used": token_count
                }
            )
            
            return context
        
        except Exception as e:
            logger.error(
                f"Synthesis agent failed: {str(e)}",
                extra={"job_id": str(context.job_id), "error": str(e)}
            )
            return context
    
    def _build_context(self, context: AgentContext) -> str:
        """Build a summary of all context for the synthesis prompt."""
        parts = []
        
        for agent_name, agent_output in context.agent_outputs.items():
            parts.append(f"Agent '{agent_name}' output: {agent_output.result}")
        
        if context.critique_results:
            flagged = [c for c in context.critique_results if c.flagged]
            if flagged:
                parts.append("\nFlagged Issues:")
                for critique in flagged:
                    parts.append(
                        f"  - From {critique.source_agent}: \"{critique.claim}\" "
                        f"(confidence: {critique.confidence})"
                    )
        
        if context.retrieved_chunks:
            parts.append("\nRetrieved Information:")
            for chunk in context.retrieved_chunks[:3]:  # Top 3
                parts.append(f"  - {chunk.source_url}: {chunk.content[:100]}...")
        
        return "\n".join(parts)
    
    def _create_prompt(self, synthesis_context: str, context: AgentContext) -> str:
        """Create synthesis prompt."""
        flagged_count = sum(1 for c in context.critique_results if c.flagged)
        return f"""You are an expert synthesizer. Your task is to combine the following information
into a comprehensive, factually accurate final answer. You must:

1. Integrate insights from all agent outputs
2. Resolve any flagged contradictions (noted below)
3. Cite specific sources when appropriate
4. Be explicit about how you resolved conflicts

There are {flagged_count} flagged issues that need resolution. Document how you handled each one.

CONTEXT TO SYNTHESIZE:
{synthesis_context}

INSTRUCTIONS:
- Produce a coherent, well-structured final answer
- For contradictions: explicitly state what conflicted, why, and which source you trust more
- Explain the reasoning for each major claim
- If information is incomplete, acknowledge it

Return as JSON:
{{
    "final_answer": "Your comprehensive answer here",
    "contradiction_resolutions": [
        {{
            "issue": "what was contradicted",
            "resolution": "how it was resolved",
            "rationale": "why this resolution"
        }}
    ],
    "confidence": 0.85,
    "key_sources": ["source1", "source2"]
}}"""
    
    async def _call_llm(self, prompt: str, job_id) -> str:
        """Call the LLM."""
        try:
            if isinstance(self.client, ChatOpenAI):
                message = self.client.invoke(prompt)
                return message.content
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                max_tokens=4000,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM call failed for synthesis: {str(e)}")
            raise
    
    def _parse_response(self, response: str) -> tuple[str, dict]:
        """Parse LLM response into final answer and reasoning."""
        try:
            data = json.loads(response)
            final_answer = data.get("final_answer", "")
            reasoning = {
                "contradictions_resolved": data.get("contradiction_resolutions", []),
                "confidence": data.get("confidence", 0.8),
                "key_sources": data.get("key_sources", [])
            }
            return final_answer, reasoning
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse synthesis response: {str(e)}")
            return response, {}
    
    def _build_provenance_map(self, context: AgentContext, final_answer: str):
        """
        Build provenance map linking sentences to sources.
        """
        sentences = final_answer.split(".")
        
        for idx, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
            
            best_agent = None
            best_score = 0
            
            for agent_name, agent_output in context.agent_outputs.items():
                if agent_name == "synthesis": 
                    continue
                
                words_in_sentence = set(sentence.lower().split())
                words_in_output = set(agent_output.result.lower().split())
                overlap = len(words_in_sentence & words_in_output)
                
                if overlap > best_score:
                    best_score = overlap
                    best_agent = agent_name
            



            best_chunk_id = None
            if best_score > 2: 
                for chunk in context.retrieved_chunks:
                    if any(word in chunk.content.lower()
                           for word in words_in_sentence if len(word) > 5):
                        best_chunk_id = chunk.id
                        break
            
            # Create provenance entry
            if best_agent or best_chunk_id:
                entry = ProvenanceEntry(
                    sentence_idx=idx,
                    sentence_text=sentence.strip(),
                    source_agent=best_agent or "unknown",
                    source_chunk_id=best_chunk_id,
                    confidence=min(best_score / 10.0, 1.0)
                )
                context.provenance_map.append(entry)
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens using simple heuristic."""
        return max(1, len(text) // 4)
