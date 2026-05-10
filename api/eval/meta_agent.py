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
        Generate a prompt rewrite proposal.
        
        Args:
            worst_case: The worst performing case
            eval_results: All eval results for context
            
        Returns:
            Proposal dict
        """
        original_prompt = f"Agent prompt for {worst_case['dimension']}"  # Would get from DB
        
        rewrite_guidance = {
            "answer_correctness": "Focus on eliciting concise, factually accurate answers",
            "citation_accuracy": "Require explicit source citations",
            "contradiction_resolution": "Ask agent to explicitly list and resolve contradictions",
            "tool_efficiency": "Discourage unnecessary tool calls",
            "budget_compliance": "Emphasize token efficiency",
            "critique_agreement": "Ask agent to preemptively address likely criticisms"
        }
        
        guidance = rewrite_guidance.get(worst_case["dimension"], "Improve answer quality")
        
        rewritten = (
            f"[IMPROVED] {original_prompt}\n\n"
            f"Improvement focus: {guidance}\n"
            f"(This is a demonstration proposal)"
        )
        
        # Generate unified diff
        diff = self._generate_diff(original_prompt, rewritten)
        
        return {
            "proposal_id": str(uuid.uuid4()),
            "original_prompt": original_prompt,
            "rewritten_prompt": rewritten,
            "unified_diff": diff,
            "justification": f"Improve {worst_case['dimension']} (score: {worst_case['score']:.2f})",
            "target_dimension": worst_case["dimension"],
            "expected_improvement": 0.2,  # Conservative estimate
            "created_at": datetime.utcnow().isoformat()
        }
    
    def _generate_diff(self, original: str, rewritten: str) -> str:
        """Generate unified diff between prompts."""
        import difflib
        
        original_lines = original.split("\n")
        rewritten_lines = rewritten.split("\n")
        
        diff = difflib.unified_diff(
            original_lines,
            rewritten_lines,
            lineterm=""
        )
        
        return "\n".join(diff)
