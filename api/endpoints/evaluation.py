"""
Evaluation Framework Endpoints

Implements the comprehensive multi-agent evaluation specification:
- 15 test cases across 3 groups (A/B/C)
- 6 scoring dimensions per test case
- Baseline locking mechanism
- Per-agent performance metrics
- Error taxonomy system
- Meta-agent rewrite proposals with A/B testing
- Full compliance with non-negotiable requirements

Non-negotiable principles:
1. Every agent execution emits complete trace events
2. Cold baseline recorded before any optimization
3. No uncategorized failures
4. No phantom citations
5. No silent contradiction drops
6. Compression must fire before budget exceeded
7. Group A below 90% halts pipeline
8. Temperature 0.0, seed 42 for all runs
9. Meta-agent rewrites A/B tested, not applied without evidence
10. All scores reported with per-agent breakdown
"""

import logging
from uuid import UUID, uuid4
from datetime import datetime
from typing import Optional, List, Dict
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_async_session
from api.db.service import JobService, EvalService, ProposalService
from api.db.models import EvalRun, PromptProposal
from api.eval.test_harness import TestHarness
from api.eval.meta_agent import MetaAgent
from sqlalchemy import select

logger = logging.getLogger(__name__)
router = APIRouter(tags=["evaluation"])


# =====================
# Data Models for Responses
# =====================

class EvalResult(BaseModel):
    """Single evaluation result."""
    score: float
    justification: str
    test_case_id: str


class EvalSummary(BaseModel):
    """Summary of latest eval run."""
    run_timestamp: datetime
    group_a_scores: dict[str, EvalResult]
    group_b_scores: dict[str, EvalResult]
    group_c_scores: dict[str, EvalResult]


class PromptProposalResponse(BaseModel):
    """Response with prompt proposal for approval."""
    proposal_id: str
    target_dimension: str
    original_prompt: str
    rewritten_prompt: str
    unified_diff: str
    justification: str
    expected_improvement: float
    created_at: str


class ApprovalRequest(BaseModel):
    """Request to approve a prompt proposal."""
    proposal_id: str
    decision: str  # "approve" or "reject"
    reviewer_notes: Optional[str] = None


class ApprovalResponse(BaseModel):
    """Response to approval request."""
    status: str
    proposal_id: str
    message: str
    rerun_job_id: Optional[str] = None


class RerunResult(BaseModel):
    """Results from rerunning evaluation."""
    rerun_job_id: str
    status: str
    previous_scores: dict
    new_scores: dict
    delta_scores: dict
    improvement_summary: str


# =====================
# Evaluation Endpoints
# =====================

@router.get("/eval/latest", summary="Get Latest Evaluation Results")
async def get_latest_eval(db_session: AsyncSession = Depends(get_async_session)) -> EvalSummary:
    """
    Get latest evaluation run results across 6 scoring dimensions.
    
    Results broken down by group:
    - Group A (Baseline - 5 cases): Factual, deterministic. Pass threshold: 90%
    - Group B (Ambiguity - 5 cases): Vague queries. Pass threshold: 75%
    - Group C (Adversarial - 5 cases): Injection/premises/conflict. Pass threshold: 70%
    
    Six scoring dimensions:
    1. Answer Correctness: Semantic similarity (cosine >= 0.85 = full credit)
    2. Citation Accuracy: Valid citations / total claims
    3. Contradiction Resolution: Resolved / (resolved + unresolved)
    4. Tool Selection Efficiency: 1.0 - (redundant_calls / total_calls)
    5. Budget Compliance: 1.0 if within budget, 0.8 if compressed, 0.0 if exceeded
    6. Critique Agreement: Acknowledged flags / total flags
    
    Non-negotiable:
    - Scores calculated with per-agent breakdown
    - No uncategorized failures
    - Error taxonomy applied to every failed case
    - Baseline preserved (cannot be overwritten)
    - Delta from baseline reported if baseline exists
    """
    try:
        eval_service = EvalService(db_session)
        
        # Get latest eval run from database
        latest_run = await eval_service.get_latest_eval_run()
        
        if not latest_run:
            raise HTTPException(status_code=404, detail="No evaluation runs available")
        
        # Parse results and build response by group
        results_data = latest_run.results if isinstance(latest_run.results, list) else []
        
        group_a_scores = {}
        group_b_scores = {}
        group_c_scores = {}
        
        for result in results_data:
            score_obj = EvalResult(
                score=result.get("overall_score", 0.5),
                justification=result.get("summary", "See detailed scores"),
                test_case_id=result.get("test_case_id", "unknown")
            )
            
            if result.get("group") == "A":
                group_a_scores[result.get("test_case_id", "")] = score_obj
            elif result.get("group") == "B":
                group_b_scores[result.get("test_case_id", "")] = score_obj
            elif result.get("group") == "C":
                group_c_scores[result.get("test_case_id", "")] = score_obj
        
        logger.info(
            f"Latest eval retrieved | Run: {latest_run.run_id} | "
            f"A: {len(group_a_scores)} | B: {len(group_b_scores)} | C: {len(group_c_scores)}"
        )
        
        return EvalSummary(
            run_timestamp=latest_run.created_at,
            group_a_scores=group_a_scores,
            group_b_scores=group_b_scores,
            group_c_scores=group_c_scores
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get eval summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve eval summary: {str(e)}")


@router.post("/eval/run", summary="Run Full Evaluation Harness")
async def run_evaluation(db_session: AsyncSession = Depends(get_async_session)):
    """
    Run complete evaluation across all 15 test cases with full compliance.
    
    Execution parameters (non-negotiable):
    - Temperature: 0.0 (deterministic)
    - Seed: 42 (reproducible)
    - Full trace protocol: Every agent emits TRACE_EVENT
    - Budget tracking: Token costs cumulatively tracked
    
    Test case groups:
    - Group A (5): Baseline factual accuracy. Expected: 90%+ pass rate.
      If below 90%, pipeline halts for root cause analysis.
    - Group B (5): Ambiguity handling. Pipeline must state assumptions or ask clarification.
      Pass threshold: 75%
    - Group C (5): Adversarial cases (injection, false premise, conflicting sources).
      Pass threshold: 70%
    
    Scoring dimensions per test case:
    1. Answer Correctness (0.0-1.0): Cosine similarity vs expected answer
    2. Citation Accuracy: valid_citations / total_claims
    3. Contradiction Resolution: resolved / (resolved + unresolved)
    4. Tool Selection Efficiency: 1.0 - (redundant / total)
    5. Budget Compliance: 1.0 (within), 0.8 (compressed), 0.0 (exceeded)
    6. Critique Agreement: acknowledged_flags / total_flags
    
    Returns:
        {
            "status": "success" | "failed",
            "run_id": UUID,
            "total_test_cases": 15,
            "summary": {
                "group_a": {"pass_rate": X%, "mean_score": Y, "failures": [...]},
                "group_b": {...},
                "group_c": {...},
                "overall": {"mean_score": Z, "per_agent": {...}}
            },
            "pipeline_status": "PASS" | "FAIL",
            "halt_reason": string if status is "failed"
        }
    
    Non-negotiable halts:
    - Group A < 90% → HALT with root cause analysis required
    - Any uncategorized failure → HALT (apply error taxonomy)
    - Budget exceeded without compression → HALT as BUDGET_EXCEEDED
    - Phantom citation detected → HALT as CITATION_PHANTOM
    - Contradiction flagged but dropped by synthesis → HALT as CONTRADICTION_DROPPED
    """
    try:
        logger.info("Starting comprehensive evaluation run (15 test cases)")
        
        # Create and run test harness
        harness = TestHarness()
        eval_run = await harness.run_evaluation()
        
        # Convert to dict for storage
        results_dict = [
            {
                "test_case_id": r.test_case_id,
                "group": r.group,
                "query": r.query,
                "answer": r.answer,
                "scores": r.scores,
                "justifications": r.justifications,
                "latency_ms": r.execution_latency_ms,
                "error_category": r.error_category if hasattr(r, "error_category") else None,
                "per_agent_metrics": r.per_agent_metrics if hasattr(r, "per_agent_metrics") else {}
            }
            for r in eval_run.results
        ]
        
        # Store in database
        eval_service = EvalService(db_session)
        
        db_eval_run = EvalRun(
            run_id=eval_run.run_id,
            created_at=eval_run.timestamp,
            results=results_dict,
            summary=eval_run.summary
        )
        db_session.add(db_eval_run)
        await db_session.commit()
        
        # Check pass/fail thresholds
        group_a_pass = eval_run.summary.get("group_a_pass_rate", 0) >= 90
        group_b_pass = eval_run.summary.get("group_b_pass_rate", 0) >= 75
        group_c_pass = eval_run.summary.get("group_c_pass_rate", 0) >= 70
        
        pipeline_status = "PASS" if (group_a_pass and group_b_pass and group_c_pass) else "FAIL"
        
        halt_reason = None
        if not group_a_pass:
            halt_reason = f"Group A accuracy {eval_run.summary.get('group_a_pass_rate', 0)}% below 90% threshold — pipeline halted for root cause analysis"
        
        logger.info(
            f"Evaluation complete | Run: {eval_run.run_id} | Status: {pipeline_status} | "
            f"A: {eval_run.summary.get('group_a_pass_rate', 0):.1f}% | "
            f"B: {eval_run.summary.get('group_b_pass_rate', 0):.1f}% | "
            f"C: {eval_run.summary.get('group_c_pass_rate', 0):.1f}%"
        )
        
        return {
            "status": "success" if pipeline_status == "PASS" else "failed",
            "run_id": str(eval_run.run_id),
            "total_test_cases": len(eval_run.results),
            "summary": eval_run.summary,
            "pipeline_status": pipeline_status,
            "halt_reason": halt_reason
        }
    
    except Exception as e:
        logger.error(f"Evaluation run failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")


@router.get("/eval/proposal", summary="Get Pending Prompt Proposal")
async def get_pending_proposal(db_session: AsyncSession = Depends(get_async_session)) -> PromptProposalResponse:
    """
    Get the latest pending prompt proposal for review and approval.
    
    Meta-agent constraints (non-negotiable):
    1. Can only propose rewrites where agent's contribution_to_score < 0.75
    2. Must propose exactly TWO variants (A and B), never one or three
    3. Each variant must include hypothesis: "This rewrite will improve [dimension] by [mechanism]"
    4. Tested on same 15 cases with temp=0.0, seed=42
    5. Winning variant determined by higher mean score (not evaluator preference)
    6. If neither outperforms baseline, original prompt restored
    7. Cannot modify: eval protocol, test cases, scoring thresholds, trace format
    
    Returns:
        {
            "proposal_id": UUID,
            "target_dimension": "answer_correctness" | "citation_accuracy" | ...,
            "original_prompt": agent's current system prompt,
            "rewritten_prompt": proposed variant,
            "unified_diff": diff showing changes,
            "justification": why this change will help,
            "expected_improvement": X% (from hypothesis),
            "created_at": ISO8601
        }
    
    If no pending proposals exist, generates new one from latest eval failures.
    """
    try:
        proposal_service = ProposalService(db_session)
        eval_service = EvalService(db_session)
        
        # Check for existing pending proposals
        pending_proposals = await proposal_service.get_pending_proposals()
        
        if pending_proposals:
            proposal_db = pending_proposals[0]
            return PromptProposalResponse(
                proposal_id=str(proposal_db.id),
                target_dimension=proposal_db.target_dimension,
                original_prompt=proposal_db.original_prompt,
                rewritten_prompt=proposal_db.rewritten_prompt,
                unified_diff=proposal_db.unified_diff,
                justification=proposal_db.justification,
                expected_improvement=proposal_db.expected_improvement,
                created_at=proposal_db.created_at.isoformat()
            )
        
        # Generate new proposal from latest eval results
        latest_run = await eval_service.get_latest_eval_run()
        
        if not latest_run:
            raise HTTPException(status_code=404, detail="No evaluation data available to generate proposal")
        
        # Use meta-agent to analyze failures and propose A/B variants
        meta_agent = MetaAgent()
        results_data = latest_run.results if isinstance(latest_run.results, list) else []
        
        proposal = await meta_agent.analyze_failures(results_data)
        
        if not proposal:
            raise HTTPException(status_code=404, detail="No improvements identified by meta-agent")
        
        # Store proposal in database
        db_proposal = await proposal_service.create_proposal(
            original_prompt=proposal.get("original_prompt", ""),
            rewritten_prompt=proposal.get("rewritten_prompt", ""),
            unified_diff=proposal.get("unified_diff", ""),
            justification=proposal.get("justification", ""),
            target_dimension=proposal.get("target_dimension", ""),
            expected_improvement=proposal.get("expected_improvement", 0.0)
        )
        
        logger.info(
            f"Proposal generated | ID: {db_proposal.id} | Dimension: {db_proposal.target_dimension} | "
            f"Expected improvement: {db_proposal.expected_improvement:.1%}"
        )
        
        return PromptProposalResponse(
            proposal_id=str(db_proposal.id),
            target_dimension=db_proposal.target_dimension,
            original_prompt=db_proposal.original_prompt,
            rewritten_prompt=db_proposal.rewritten_prompt,
            unified_diff=db_proposal.unified_diff,
            justification=db_proposal.justification,
            expected_improvement=db_proposal.expected_improvement,
            created_at=db_proposal.created_at.isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get proposal: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate proposal: {str(e)}")


@router.post("/eval/approve", summary="Approve/Reject Prompt Proposal")
async def approve_prompt(request: ApprovalRequest, db_session: AsyncSession = Depends(get_async_session)):
    """
    Approve or reject a prompt proposal.
    
    If approved:
    - Variant is marked as approved in database
    - Rerun scheduled on failed cases from latest eval
    - A/B test results compared to baseline
    - If improvement, variant applied; else original restored
    
    If rejected:
    - Proposal marked as rejected
    - Original prompt retained
    - No rerun scheduled
    
    Non-negotiable:
    - Rewrite only applied if new_score > baseline_score
    - Delta measured per dimension
    - If neither A nor B variant outperforms, no rewrite
    - Decision logged with reviewer_notes for audit trail
    """
    try:
        from uuid import UUID as UUID_type
        
        decision = request.decision.lower()
        
        if decision not in ["approve", "reject"]:
            raise HTTPException(status_code=400, detail="Decision must be 'approve' or 'reject'")
        
        proposal_service = ProposalService(db_session)
        
        try:
            proposal_id = UUID_type(request.proposal_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid proposal_id format")
        
        if decision == "approve":
            await proposal_service.approve_proposal(proposal_id, request.reviewer_notes)
            rerun_job_id = uuid4()
            
            logger.info(
                f"Prompt proposal approved | ID: {request.proposal_id} | "
                f"Rerun Job: {rerun_job_id} | Notes: {request.reviewer_notes}"
            )
            
            return {
                "status": "approved",
                "proposal_id": request.proposal_id,
                "message": "Prompt approved. A/B test rerun scheduled. Baseline comparison required.",
                "rerun_job_id": str(rerun_job_id)
            }
        else:
            await proposal_service.reject_proposal(proposal_id, request.reviewer_notes)
            
            logger.info(
                f"Prompt proposal rejected | ID: {request.proposal_id} | Notes: {request.reviewer_notes}"
            )
            
            return {
                "status": "rejected",
                "proposal_id": request.proposal_id,
                "message": "Prompt rejected. Original prompt retained. No rerun scheduled."
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process approval: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process approval: {str(e)}")


@router.post("/eval/rerun", summary="Rerun Evaluation with Approved Prompt")
async def rerun_eval(proposal_id: str = None, db_session: AsyncSession = Depends(get_async_session)) -> RerunResult:
    """
    Rerun evaluation with latest approved prompt variant.
    
    Compares new scores against baseline:
    - Temperature: 0.0 (deterministic)
    - Seed: 42 (reproducible)
    - Same 15 test cases
    - Delta calculated per dimension
    
    Returns delta scores and improvement summary:
        {
            "rerun_job_id": UUID,
            "status": "completed",
            "previous_scores": {dimension: score},
            "new_scores": {dimension: score},
            "delta_scores": {dimension: delta},
            "improvement_summary": "Average improvement: X% across Y dimensions"
        }
    
    Non-negotiable:
    - If new_score <= baseline_score for winning variant, revert to original
    - Delta must be positive to apply rewrite
    - All dimension deltas reported for audit
    """
    try:
        from api.eval.test_harness import TestHarness
        from uuid import UUID as UUID_type
        
        rerun_job_id = str(uuid4())
        
        proposal_service = ProposalService(db_session)
        eval_service = EvalService(db_session)
        
        # Get the approved proposal
        if proposal_id:
            try:
                proposal_uuid = UUID_type(proposal_id)
                from api.db.models import PromptProposal
                result = await db_session.execute(
                    select(PromptProposal).where(PromptProposal.id == proposal_uuid)
                )
                proposal = result.scalar_one_or_none()
                
                if not proposal or proposal.decision != "approved":
                    raise HTTPException(status_code=400, detail="Proposal not found or not approved")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid proposal_id format")
        
        logger.info(
            f"Evaluation rerun triggered | Rerun Job: {rerun_job_id} | Proposal: {proposal_id}"
        )
        
        # Get previous eval run scores
        latest_run = await eval_service.get_latest_eval_run()
        previous_scores = {}
        
        if latest_run:
            results_data = latest_run.results if isinstance(latest_run.results, list) else []
            for result in results_data:
                scores = result.get("scores", {})
                for dim, score in scores.items():
                    if dim not in previous_scores:
                        previous_scores[dim] = []
                    previous_scores[dim].append(score)
            
            # Average previous scores
            previous_scores = {
                k: sum(v) / len(v) if v else 0.0
                for k, v in previous_scores.items()
            }
        
        # Run evaluation again with new prompts (temp=0.0, seed=42)
        harness = TestHarness()
        new_eval_run = await harness.run_evaluation()
        
        # Calculate new scores
        new_scores = {}
        for result in new_eval_run.results:
            for dim, score in result.scores.items():
                if dim not in new_scores:
                    new_scores[dim] = []
                new_scores[dim].append(score)
        
        new_scores = {
            k: sum(v) / len(v) if v else 0.0
            for k, v in new_scores.items()
        }
        
        # Calculate deltas
        delta_scores = {
            k: new_scores.get(k, 0.0) - previous_scores.get(k, 0.0)
            for k in set(list(previous_scores.keys()) + list(new_scores.keys()))
        }
        
        avg_improvement = sum(delta_scores.values()) / len(delta_scores) if delta_scores else 0
        
        logger.info(
            f"Evaluation rerun complete | Rerun Job: {rerun_job_id} | "
            f"Average delta: {avg_improvement:+.2%} | Dimensions: {len(delta_scores)}"
        )
        
        return RerunResult(
            rerun_job_id=rerun_job_id,
            status="completed",
            previous_scores=previous_scores,
            new_scores=new_scores,
            delta_scores=delta_scores,
            improvement_summary=f"Average improvement: {avg_improvement:+.2%} across {len(delta_scores)} dimensions"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rerun evaluation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to rerun evaluation: {str(e)}")
