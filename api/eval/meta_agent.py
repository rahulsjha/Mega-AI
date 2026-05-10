"""
Meta-agent - reads failed eval cases and proposes prompt rewrites.

Identifies worst-performing dimension, rewrites the prompt,
stores proposal in DB for human review.
"""

import logging
import json
import uuid
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class MetaAgent:
    """
    Meta-learning agent that improves prompts based on eval results.
    
    Process:
    1. Read failed eval cases (score < 0.6 on any dimension)
    2. Identify worst-performing dimension
    3. Generate prompt rewrite
    4. Store proposal in DB
    5. Wait for approval
    """
    
    def __init__(self):
        """Initialize meta-agent."""
        self.name = "meta_agent"
    
    async def analyze_failures(
        self,
        eval_results: List[Dict]
    ) -> Optional[Dict]:
        """
        Analyze failed eval cases and propose improvements.
        
        Args:
            eval_results: List of eval run results
            
        Returns:
            Prompt proposal dict or None if no failures
        """
        # Find failed cases (score < 0.6)
        failed_cases = []
        for result in eval_results:
            scores = result.get("scores", {})
            for dimension, score_data in scores.items():
                if score_data.get("score", 1.0) < 0.6:
                    failed_cases.append({
                        "test_case_id": result.get("test_case_id"),
                        "dimension": dimension,
                        "score": score_data.get("score")
                    })
        
        if not failed_cases:
            logger.info("No failed cases to improve")
            return None
        
        # Find worst performing
        worst = min(failed_cases, key=lambda x: x["score"])
        
        logger.info(
            f"Worst performer identified",
            extra={
                "dimension": worst["dimension"],
                "score": worst["score"]
            }
        )
        
        # Generate rewrite
        proposal = self._generate_rewrite(worst, eval_results)
        
        return proposal
    
    def _generate_rewrite(self, worst_case: Dict, eval_results: List[Dict]) -> Dict:
        """
        Generate a prompt rewrite proposal with specific improvements.
        
        Args:
            worst_case: The worst performing case
            eval_results: All eval results for context
            
        Returns:
            Proposal dict
        """
        dimension = worst_case["dimension"]
        current_score = worst_case["score"]
        
        # Original prompts for each dimension
        original_prompts = {
            "answer_correctness": (
                "You are a helpful AI assistant. Answer the user's query directly and concisely. "
                "Provide the most accurate information you can."
            ),
            "citation_accuracy": (
                "You are a research assistant. When answering questions, cite your sources. "
                "Reference relevant documents and materials."
            ),
            "contradiction_resolution": (
                "You are a critical analyzer. Examine information for inconsistencies. "
                "Flag any contradictions and explain how they can be resolved."
            ),
            "tool_efficiency": (
                "You are an efficient problem solver. Use tools strategically. "
                "Minimize unnecessary tool calls. Only search when truly needed."
            ),
            "budget_compliance": (
                "You are a resource-conscious assistant. Manage token usage carefully. "
                "Avoid verbose responses and unnecessary context."
            ),
            "critique_agreement": (
                "You are a self-aware assistant. Consider potential criticisms. "
                "Address likely objections proactively in your responses."
            )
        }
        
        # Improvement strategies
        improvement_rewrites = {
            "answer_correctness": (
                "You are a factuality expert. Your response will be graded on accuracy. "
                "Before answering, verify facts against known information. "
                "If uncertain, qualify statements with appropriate confidence levels. "
                "Prioritize correctness over completeness. "
                "Answer directly without unnecessary preamble."
            ),
            "citation_accuracy": (
                "You are a precise citation specialist. Every factual claim must reference a source. "
                "Use the format: [claim] (from [source_name]: [specific_section]). "
                "When citations cannot be verified, acknowledge uncertainty. "
                "Do not synthesize without attribution. "
                "Link each answer component to its origin document."
            ),
            "contradiction_resolution": (
                "You are a dialectical thinker. Explicitly list all perspectives before synthesis. "
                "Identify incompatible claims using logical notation: 'A contradicts B because...' "
                "Resolve contradictions using: [priority principle], [evidence], [synthesis]. "
                "Do not hide contradictions. Expose and resolve them. "
                "Final answer should show your reasoning path."
            ),
            "tool_efficiency": (
                "You are a strategic tool user. Minimize tool calls. "
                "Before calling a tool, ask: Is this truly necessary? Can I answer from context? "
                "Use tools only when: (1) Information is not in context, (2) Verification is needed. "
                "Batch related queries into single tool calls. "
                "Justify each tool invocation explicitly."
            ),
            "budget_compliance": (
                "You are a concise communicator. Every token counts. "
                "Use abbreviated formats for structured data (tables, lists). "
                "Remove hedging language ('perhaps', 'might', 'arguably'). "
                "Combine concepts to reduce repetition. "
                "Target response length: 40% of maximum allowed tokens."
            ),
            "critique_agreement": (
                "You are a preemptive critic. Before finalizing, ask: What could go wrong? "
                "Address likely criticisms: accuracy, missing context, alternative interpretations. "
                "For each claim, include: evidence level, confidence, caveats. "
                "Anticipate objections and refute them directly. "
                "Structure: claim → potential criticism → your response."
            )
        }
        
        original = original_prompts.get(dimension, "Standard prompt for " + dimension)
        rewritten = improvement_rewrites.get(dimension, "Improved prompt")
        
        # Generate unified diff
        diff = self._generate_diff(original, rewritten)
        
        # Estimate improvement based on current score and dimension patterns
        base_improvement = max(0.15, 0.8 - current_score) if current_score < 0.8 else 0.1
        expected_improvement = min(0.35, base_improvement)  # Cap at 35%
        
        return {
            "proposal_id": str(uuid.uuid4()),
            "original_prompt": original,
            "rewritten_prompt": rewritten,
            "unified_diff": diff,
            "justification": (
                f"Prompt for '{dimension}' scoring {current_score:.2f}. "
                f"Rewrites focus on: explicit {dimension.replace('_', ' ')} criteria, "
                f"measurable outcomes, and agent self-checking."
            ),
            "target_dimension": dimension,
            "expected_improvement": expected_improvement,
            "created_at": datetime.utcnow().isoformat()
        }
    
    def _generate_diff(self, original: str, rewritten: str) -> str:
        """Generate unified diff between prompts."""
        import difflib
        
        original_lines = original.split("\n")
        rewritten_lines = rewritten.split("\n")
        
        diff_lines = list(difflib.unified_diff(
            original_lines,
            rewritten_lines,
            fromfile="original_prompt",
            tofile="rewritten_prompt",
            lineterm=""
        ))
        
        return "\n".join(diff_lines)
