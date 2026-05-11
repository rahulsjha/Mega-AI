"""
Master Orchestrator - LLM-powered routing agent.

Receives query and AgentContext, uses structured output to decide next agent.
Loops until "done" or max-iterations (10) reached.
Handles failures gracefully by re-routing or degrading.
"""

import logging
import json
import os
from typing import Optional, List
from api.context.schema import AgentContext, RoutingDecision, AgentOutput
from api.context.budget import ContextBudgetManager
from api.llm import build_openrouter_llm
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

class MasterOrchestrator:
    """
    LLM-powered orchestrator that routes between agents.
    
    Routing sequence:
    1. decomposition - break down the query
    2. rag - retrieve relevant information
    3. critique - analyze outputs for issues
    4. synthesis - combine into final answer
    5. done - return result
    
    Makes routing decisions using structured output (JSON mode).
    """
    
    def __init__(self, budget_manager: ContextBudgetManager):
        """
        Initialize the orchestrator.
        
        Args:
            budget_manager: Shared budget manager for all agents
        """
        self.name = "orchestrator"
        self.budget_tokens = 2000
        self.max_iterations = int(os.getenv("MAX_ORCHESTRATOR_ITERATIONS", "10"))
        self.budget_manager = budget_manager
        self._init_llm()
        self._init_agents()
    
    def _init_llm(self):
        """Initialize LLM client."""
        self.client = build_openrouter_llm(2000)
        if self.client is not None:
            return

        from openai import OpenAI
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    def _init_agents(self):
        """Initialize all sub-agents."""
        from api.agents.decomposition import DecompositionAgent
        from api.agents.rag import RAGAgent
        from api.agents.critique import CritiqueAgent
        from api.agents.synthesis import SynthesisAgent
        from api.agents.compression import CompressionAgent
        
        self.agents = {
            "decomposition": DecompositionAgent(),
            "rag": RAGAgent(),
            "critique": CritiqueAgent(),
            "synthesis": SynthesisAgent(),
            "compression": CompressionAgent(),
        }
    
    async def execute(self, context: AgentContext) -> AgentContext:
        """
        Execute the orchestration loop.
        
        Args:
            context: The shared agent context
            
        Returns:
            Context with final_answer populated
        """
        import time
        
        start_time = time.time()
        
        await context.emit_event("orchestration_start", {
            "query": context.query,
            "job_id": str(context.job_id)
        })
        
        logger.info(
            f"Orchestrator starting for job {context.job_id}",
            extra={"job_id": str(context.job_id), "query": context.query}
        )
        
        self.budget_manager.declare_budget(self.name, self.budget_tokens)
        iteration = 0
        
        while iteration < self.max_iterations:
            iteration += 1
            context.iteration_count = iteration
            
            logger.debug(
                f"Orchestration iteration {iteration}",
                extra={"job_id": str(context.job_id), "iteration": iteration}
            )
            
            try:
                decision = await self._make_routing_decision(context)
            except Exception as e:
                logger.error(
                    f"Routing decision failed: {str(e)}",
                    extra={"job_id": str(context.job_id), "error": str(e)}
                )
                await context.emit_event("routing_error", {
                    "error": str(e),
                    "iteration": iteration
                })
                decision = RoutingDecision(
                    next_agent="synthesis",
                    justification="Fallback due to routing error",
                    confidence=0.5
                )
            
            context.routing_history.append(decision)
            
            await context.emit_event("routing_decision", {
                "next_agent": decision.next_agent,
                "justification": decision.justification,
                "confidence": decision.confidence,
                "iteration": iteration
            })
            
            logger.info(
                f"Routing decision: {decision.next_agent}",
                extra={
                    "job_id": str(context.job_id),
                    "next_agent": decision.next_agent,
                    "justification": decision.justification,
                    "iteration": iteration
                }
            )
            
            if decision.next_agent == "done":
                logger.info(
                    f"Orchestrator completed",
                    extra={
                        "job_id": str(context.job_id),
                        "iterations": iteration,
                        "final_answer": context.final_answer[:100] if context.final_answer else None
                    }
                )
                break
            



            if decision.next_agent in self.agents:
                try:
                    await context.emit_event("agent_start", {
                        "agent": decision.next_agent,
                        "iteration": iteration
                    }, agent_id=decision.next_agent)
                    
                    agent = self.agents[decision.next_agent]
                    agent_start = time.time()
                    context = await agent.execute(context, self.budget_manager)
                    agent_latency = (time.time() - agent_start) * 1000
                    
                    await context.emit_event("agent_done", {
                        "agent": decision.next_agent,
                        "iteration": iteration,
                        "latency_ms": agent_latency,
                        "output_tokens": len(context.agent_outputs.get(decision.next_agent, {}).get("output", "").split())
                    }, agent_id=decision.next_agent, latency_ms=agent_latency)
                    
                except Exception as e:
                    logger.error(
                        f"Agent {decision.next_agent} failed: {str(e)}",
                        extra={
                            "job_id": str(context.job_id),
                            "agent": decision.next_agent,
                            "error": str(e)
                        }
                    )
                    await context.emit_event("agent_error", {
                        "agent": decision.next_agent,
                        "error": str(e),
                        "iteration": iteration
                    }, agent_id=decision.next_agent)
                    # Try to recover by re-routing
                    continue
            
            # Check if compression is needed
            if context.metadata.get("needs_compression"):
                logger.info(
                    "Triggering compression",
                    extra={"job_id": str(context.job_id)}
                )
                await context.emit_event("compression_start", {"iteration": iteration})
                context = await self.agents["compression"].execute(context)
                await context.emit_event("compression_done", {"iteration": iteration})
                context.metadata["needs_compression"] = False
            
            # Sync budget to context
            self.budget_manager.sync_to_context(context)
        
        # Mark completion
        from datetime import datetime
        context.completed_at = datetime.utcnow()
        
        total_latency = (time.time() - start_time) * 1000
        
        await context.emit_event("orchestration_complete", {
            "iterations": iteration,
            "total_latency_ms": total_latency,
            "final_answer_length": len(context.final_answer) if context.final_answer else 0,
            "has_answer": context.final_answer is not None
        })
        
        logger.info(
            f"Orchestration pipeline completed",
            extra={
                "job_id": str(context.job_id),
                "total_iterations": iteration,
                "total_latency_ms": total_latency,
                "final_answer_length": len(context.final_answer) if context.final_answer else 0
            }
        )
        
        return context
    
    async def _make_routing_decision(self, context: AgentContext) -> RoutingDecision:
        """
        Use LLM to make routing decision.
        
        Args:
            context: Current context
            
        Returns:
            RoutingDecision
        """
        # Check what we've done so far
        completed_agents = list(context.agent_outputs.keys())
        available_agents = [a for a in self.agents.keys() if a != "compression"]
        
        # Remove synthesis if not all other agents have run
        can_synthesize = (
            "decomposition" in completed_agents or len(completed_agents) == 0
        ) and "rag" in completed_agents
        
        prompt = self._create_routing_prompt(context, completed_agents, available_agents, can_synthesize)
        
        response = await self._call_llm(prompt)
        decision = self._parse_routing_response(response)
        
        return decision
    
    def _create_routing_prompt(
        self,
        context: AgentContext,
        completed_agents: list,
        available_agents: list,
        can_synthesize: bool
    ) -> str:
        """Create the routing decision prompt."""
        return f"""You are the orchestrator for a multi-agent LLM system. Your job is to decide 
which agent should run next to answer the user's query.

User Query: {context.query}

Agents Available:
- decomposition: breaks down complex queries into sub-tasks
- rag: retrieves relevant information from a knowledge base
- critique: analyzes outputs for factual accuracy and contradictions
- synthesis: combines all outputs into a final answer {"(AVAILABLE)" if can_synthesize else "(NOT YET AVAILABLE)"}

Agents Already Executed: {completed_agents if completed_agents else "none"}

Current Status:
- Sub-tasks created: {len(context.sub_tasks)}
- Chunks retrieved: {len(context.retrieved_chunks)}
- Critique results: {len(context.critique_results)}
- Final answer: {"Yes" if context.final_answer else "No"}

Based on the query and current progress, decide which agent should run next.
Valid next agents: {available_agents}{"," if can_synthesize else ""}{" synthesis, done" if can_synthesize else ""}

Return JSON:
{{
    "next_agent": "decomposition" | "rag" | "critique" | "synthesis" | "done",
    "justification": "why this agent is needed",
    "context_budget_allocation": {{"agent_name": tokens}},
    "confidence": 0.95
}}"""
    
    async def _call_llm(self, prompt: str) -> str:
        """Call LLM for routing decision."""
        try:
            if isinstance(self.client, ChatOpenAI):
                message = self.client.invoke(prompt)
                return message.content
            response = self.client.chat.completions.create(
                model="gpt-4-turbo-preview",
                max_tokens=300,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LLM routing call failed: {str(e)}")
            raise
    
    def _parse_routing_response(self, response: str) -> RoutingDecision:
        """Parse routing decision from LLM response."""
        try:
            data = json.loads(response)
            return RoutingDecision(
                next_agent=data.get("next_agent", "done"),
                justification=data.get("justification", ""),
                context_budget_allocation=data.get("context_budget_allocation", {}),
                confidence=data.get("confidence", 0.8)
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse routing response: {str(e)}")
            return RoutingDecision(
                next_agent="done",
                justification="Failed to parse routing decision",
                confidence=0.0
            )
