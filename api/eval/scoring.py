"""
Scoring functions for evaluation - 6 dimensions.

1. answer_correctness - semantic similarity to expected answer
2. citation_accuracy - verify cited chunks exist and are relevant
3. contradiction_resolution - did synthesis resolve all flagged issues?
4. tool_selection_efficiency - penalize unnecessary tool calls
5. budget_compliance - any policy violations?
6. critique_agreement - does final answer match critique flagged items?
"""

import logging
from typing import Dict, Tuple
from api.context.schema import AgentContext

logger = logging.getLogger(__name__)


class ScoringEngine:
    """Computes all 6 scoring dimensions."""
    
    @staticmethod
    def score_answer_correctness(
        final_answer: str,
        expected_answer: str
    ) -> Tuple[float, str]:
        """
        Score answer correctness (0-1).
        
        Uses simple keyword matching + length comparison.
        Production would use embeddings for semantic similarity.
        """
        if not final_answer:
            return 0.0, "No answer provided"
        
        final_lower = final_answer.lower()
        expected_lower = expected_answer.lower()
        
        # Exact match
        if final_lower == expected_lower:
            return 1.0, "Exact match"
        
        # Contains key phrase
        if expected_lower in final_lower:
            return 0.9, "Contains expected answer"
        
        # Partial match
        expected_words = set(expected_lower.split())
        final_words = set(final_lower.split())
        overlap = len(expected_words & final_words) / len(expected_words)
        
        if overlap > 0.7:
            return 0.7, f"High word overlap ({overlap:.1%})"
        elif overlap > 0.3:
            return 0.4, f"Partial word overlap ({overlap:.1%})"
        else:
            return 0.1, "Minimal overlap with expected answer"
    
    @staticmethod
    def score_citation_accuracy(context: AgentContext) -> Tuple[float, str]:
        """
        Score citation accuracy (0-1).
        
        Verify that cited chunks actually exist and are relevant.
        """
        if not context.provenance_map:
            return 0.5, "No provenance information"
        
        chunk_ids = {c.id for c in context.retrieved_chunks}
        valid_citations = 0
        total_citations = 0
        
        for entry in context.provenance_map:
            if entry.source_chunk_id:
                total_citations += 1
                if entry.source_chunk_id in chunk_ids:
                    valid_citations += 1
        
        if total_citations == 0:
            return 0.8, "No chunk citations, agent citations used"
        
        accuracy = valid_citations / total_citations
        return accuracy, f"Citation accuracy: {accuracy:.0%}"
    
    @staticmethod
    def score_contradiction_resolution(context: AgentContext) -> Tuple[float, str]:
        """
        Score contradiction resolution (0-1).
        
        Did synthesis agent resolve all flagged contradictions?
        """
        flagged_count = sum(1 for c in context.critique_results if c.flagged)
        
        if flagged_count == 0:
            return 1.0, "No contradictions found"
        
        # Check if synthesis mentioned resolution
        synthesis_output = context.agent_outputs.get("synthesis")
        if not synthesis_output:
            return 0.0, "No synthesis output"
        
        result = synthesis_output.result.lower()
        
        # Look for resolution keywords
        resolution_keywords = ["resolved", "clarify", "contradiction", "addressed", "resolved"]
        resolved_mentions = sum(1 for kw in resolution_keywords if kw in result)
        
        if resolved_mentions > 0:
            resolution_score = min(1.0, resolved_mentions / flagged_count)
            return resolution_score, f"Resolved {resolved_mentions}/{flagged_count} flagged items"
        else:
            return 0.2, "Synthesis did not mention resolution of contradictions"
    
    @staticmethod
    def score_tool_selection_efficiency(context: AgentContext) -> Tuple[float, str]:
        """
        Score tool efficiency (0-1).
        
        Penalize unnecessary or duplicate tool calls.
        """
        total_calls = len(context.tool_call_log)
        
        if total_calls == 0:
            return 1.0, "No tools called"
        
        # Count duplicates (same tool called with similar inputs)
        tool_counts = {}
        for call in context.tool_call_log:
            tool_counts[call.tool_name] = tool_counts.get(call.tool_name, 0) + 1
        
        # Penalty for excessive calls
        max_calls_per_tool = 3
        efficiency = 1.0
        
        for tool_name, count in tool_counts.items():
            if count > max_calls_per_tool:
                penalty = (count - max_calls_per_tool) * 0.1
                efficiency -= penalty
        
        efficiency = max(0.0, efficiency)
        
        if efficiency < 0.7:
            return efficiency, f"Inefficient tool use: {total_calls} calls made"
        else:
            return efficiency, f"Good tool efficiency: {total_calls} calls"
    
    @staticmethod
    def score_budget_compliance(context: AgentContext) -> Tuple[float, str]:
        """
        Score budget compliance (0-1).
        
        Were there any policy violations?
        """
        violation_count = len(context.policy_violations)
        
        if violation_count == 0:
            return 1.0, "No policy violations"
        
        # Count by severity
        critical_count = sum(1 for v in context.policy_violations if v.severity == "critical")
        warning_count = sum(1 for v in context.policy_violations if v.severity == "warning")
        
        # Scoring
        compliance = 1.0 - (critical_count * 0.3) - (warning_count * 0.1)
        compliance = max(0.0, compliance)
        
        return compliance, f"{critical_count} critical, {warning_count} warnings"
    
    @staticmethod
    def score_critique_agreement(context: AgentContext) -> Tuple[float, str]:
        """
        Score critique agreement (0-1).
        
        Does final answer align with critique results?
        """
        if not context.critique_results:
            return 0.8, "No critiques performed"
        
        final_answer = context.final_answer or ""
        
        # Check if flagged items appear in final answer
        flagged_items = [c for c in context.critique_results if c.flagged]
        
        if not flagged_items:
            return 1.0, "All critique items addressed"
        
        # Simple check: flagged claims should not be in final answer
        addressed_count = 0
        for flagged in flagged_items:
            if flagged.claim.lower() not in final_answer.lower():
                addressed_count += 1
        
        agreement_score = addressed_count / len(flagged_items)
        return agreement_score, f"Addressed {addressed_count}/{len(flagged_items)} flagged claims"


def compute_all_scores(
    context: AgentContext,
    expected_answer: str
) -> Dict[str, Dict]:
    """
    Compute all 6 scores for an evaluation run.
    
    Returns:
        Dictionary with scores and justifications
    """
    engine = ScoringEngine()
    
    scores = {
        "answer_correctness": engine.score_answer_correctness(
            context.final_answer or "",
            expected_answer
        ),
        "citation_accuracy": engine.score_citation_accuracy(context),
        "contradiction_resolution": engine.score_contradiction_resolution(context),
        "tool_efficiency": engine.score_tool_selection_efficiency(context),
        "budget_compliance": engine.score_budget_compliance(context),
        "critique_agreement": engine.score_critique_agreement(context),
    }
    
    # Convert to dict format
    result = {}
    for dimension, (score, justification) in scores.items():
        result[dimension] = {
            "score": score,
            "justification": justification
        }
    
    return result
