"""
API Documentation Endpoint

Comprehensive endpoint discovery and specification.
Root endpoint returns full API specification including all 13 endpoints.
"""

from fastapi import APIRouter

router = APIRouter(tags=["documentation"])


@router.get("/", summary="API Documentation and Endpoint Discovery")
async def root():
    """
    Root endpoint providing complete API documentation.
    
    Returns:
    - API name, version, and description
    - Comprehensive endpoint listing with descriptions
    - Feature capabilities
    - Evaluation framework summary
    
    Non-negotiable endpoints (13 total):
    
    INFRASTRUCTURE:
    - GET /health: DB and Redis connectivity checks
    
    QUERY EXECUTION:
    - POST /query: Direct execution with SSE streaming (TRACE_EVENT protocol)
    
    JOB QUEUE:
    - POST /submit-job: Async job submission to Redis worker queue
    - GET /queue-status/{job_id}: Check job processing status
    - GET /queue-stats: Queue statistics
    
    EVALUATION:
    - POST /eval/run: Execute full harness (15 cases, 6 dimensions, A/B/C groups)
    - GET /eval/latest: Latest eval results by group and dimension
    - GET /eval/proposal: Get pending prompt proposal (meta-agent generated)
    - POST /eval/approve: Approve/reject proposal (triggers A/B test)
    - POST /eval/rerun: Rerun with approved variant (baseline comparison)
    
    TRACE & LOGS:
    - GET /trace/{job_id}: Complete execution trace from database
    - GET /logs/{job_id}: Event logs with metadata
    """
    return {
        "name": "Mega AI - Multi-Agent Orchestrator",
        "version": "1.0.0",
        "description": "Production-grade multi-agent LLM orchestration system with comprehensive evaluation framework",
        
        "endpoints": {
            "infrastructure": {
                "GET /health": "Infrastructure health check with DB and Redis connectivity probes"
            },
            
            "query_execution": {
                "POST /query": "Submit query for direct execution with SSE streaming (real-time TRACE_EVENT protocol)",
                "description_query": "Emits TRACE_EVENT objects: AGENT_START, TOOL_CALL, TOOL_RESULT, AGENT_END, ERROR. Full token tracking and budget compliance reported."
            },
            
            "job_queue": {
                "POST /submit-job": "Submit job for async processing via Redis worker queue",
                "GET /queue-status/{job_id}": "Check status of queued job (queued/processing/completed/failed)",
                "GET /queue-stats": "Get queue statistics (size, avg latency, connection status)"
            },
            
            "evaluation": {
                "POST /eval/run": "Run complete evaluation (15 test cases, 3 groups A/B/C, 6 scoring dimensions)",
                "description_eval_run": "Scores: answer_correctness, citation_accuracy, contradiction_resolution, tool_efficiency, budget_compliance, critique_agreement. Pass thresholds: A≥90%, B≥75%, C≥70%. Pipeline halts if Group A < 90%.",
                
                "GET /eval/latest": "Get latest eval results broken down by group (A/B/C) and scoring dimension",
                
                "GET /eval/proposal": "Get pending prompt proposal from meta-agent (generated from failure analysis)",
                "description_proposal": "Meta-agent proposes rewrites only where agent_score < 0.75. Proposals include A/B variants (never 1 or 3), hypothesis, expected improvement. Requires A/B test evidence before application.",
                
                "POST /eval/approve": "Approve/reject prompt proposal (approval triggers rerun with variant)",
                
                "POST /eval/rerun": "Rerun evaluation with approved prompt variant and report deltas vs baseline"
            },
            
            "trace_logs": {
                "GET /trace/{job_id}": "Retrieve complete execution trace (all TRACE_EVENT objects in chronological order)",
                "GET /logs/{job_id}": "Get event logs with detailed metadata (timestamp, event_type, agent_id, data, latency_ms)"
            }
        },
        
        "features": {
            "trace_protocol": "All agents emit structured TRACE_EVENT: agent_name, event_type (START/CALL/RESULT/END/ERROR), token costs, budget tracking, context snapshot",
            
            "database_backed": "All jobs, events, traces persisted to PostgreSQL async with SQLAlchemy 2.0",
            
            "sse_streaming": "POST /query streams TRACE_EVENT objects in real-time with budget compliance reporting",
            
            "async_queue": "Worker instances consume jobs from Redis queue with full trace protocol compliance",
            
            "evaluation_framework": {
                "test_cases": "15 cases across 3 groups: A (baseline, 5 cases, 90%+ expected), B (ambiguity, 5 cases, 75%+), C (adversarial injection/premise/conflict, 5 cases, 70%+)",
                "scoring_dimensions": [
                    "1. Answer Correctness: Cosine similarity vs expected (≥0.85=full, 0.70-0.84=0.5, <0.70=0)",
                    "2. Citation Accuracy: valid_citations / total_claims",
                    "3. Contradiction Resolution: resolved / (resolved + unresolved)",
                    "4. Tool Selection Efficiency: 1.0 - (redundant_calls / total_calls)",
                    "5. Budget Compliance: 1.0 (within budget), 0.8 (compressed recovery), 0.0 (exceeded)",
                    "6. Critique Agreement: acknowledged_flags / total_flags (ignored flags = disagreement)"
                ],
                "per_agent_metrics": "Invocation count, avg latency, error rate, contribution to score, redundancy rate, budget share %",
                "error_taxonomy": "HALLUCINATION, MISSING_CONTEXT, WRONG_TOOL, BUDGET_EXCEEDED, CITATION_PHANTOM, ADVERSARIAL_BYPASS, AMBIGUITY_IGNORED, CONTRADICTION_DROPPED",
                "baseline_locking": "Cold baseline (zero optimization, temp=0.0, seed=42) locked and never overwritten. All optimizations measured as delta from baseline.",
                "meta_agent_constraints": "Rewrites proposed only for agents with score<0.75. Must propose exactly 2 A/B variants. Variant selection based on higher mean score. Applied only if outperforms baseline. Cannot modify protocol/thresholds/test cases."
            },
            
            "non_negotiables": [
                "Every agent execution emits complete TRACE_EVENT",
                "No uncategorized failures (error taxonomy applied)",
                "No phantom citations (chunk_id must exist in retrieval trace)",
                "Contradiction flags never silently dropped by synthesis",
                "Compression fires before budget exceeded",
                "Group A < 90% halts pipeline",
                "Temperature 0.0, seed 42 for all eval runs",
                "Meta-agent A/B variants tested with evidence before application",
                "All scores reported with per-agent breakdown"
            ]
        },
        
        "agents": {
            "master_orchestrator": {
                "role": "Receives user query, decides agent routing (dynamic, LLM-powered, not hardcoded)",
                "outputs": ["routing_plan", "selected_agents[]", "estimated_token_cost", "policy_flags[]"],
                "tools": ["route_query", "invoke_agent", "check_budget", "emit_trace"]
            },
            
            "decomposition": {
                "role": "Breaks complex queries into DAG of subtasks with dependencies",
                "outputs": ["subtask_graph{nodes[], edges[], priority_order[]}", "complexity_score"],
                "tools": ["decompose_query", "build_dependency_graph", "tag_subtask_type"]
            },
            
            "rag": {
                "role": "Multi-hop semantic retrieval from vector store (embedding + rerank, not keyword matching)",
                "outputs": ["retrieved_chunks[]{chunk_id, score, content}", "hop_count", "top_k_used", "retrieval_latency_ms"],
                "tools": ["embed_query", "vector_search", "rerank_chunks", "multi_hop_retrieve"]
            },
            
            "critique": {
                "role": "Span-level analysis of retrieved content for contradictions, hallucinations, missing citations",
                "outputs": ["flagged_spans[]{span, issue_type, confidence, suggested_fix}", "contradiction_count", "hallucination_risk_score"],
                "tools": ["analyze_spans", "flag_contradiction", "score_confidence", "check_citation_validity"]
            },
            
            "synthesis": {
                "role": "Resolves contradictions, merges context, generates final answer with provenance tracking",
                "outputs": ["final_answer", "provenance_map{claim → chunk_id}", "resolved_contradictions[]", "unresolved_contradictions[]", "synthesis_confidence"],
                "tools": ["resolve_contradiction", "merge_context", "generate_answer", "track_provenance"]
            },
            
            "compression": {
                "role": "Auto-fires at 80% budget. Removes low-salience chunks, preserves high-confidence spans, logs dropped.",
                "outputs": ["compression_ratio", "dropped_chunks[]{chunk_id, salience}", "recovered_tokens", "post_compression_budget"],
                "tools": ["score_salience", "compress_context", "log_dropped_chunks", "recalculate_budget"]
            }
        },
        
        "execution_parameters": {
            "temperature": "0.0 (deterministic, no randomness)",
            "seed": "42 (reproducible results)",
            "evaluation_mode": "temperature 0.0, seed 42, full TRACE_EVENT protocol, comprehensive scoring",
            "token_budget": "Per-agent and cumulative tracking. Compression at 80%. Halt if exceeded without compression."
        }
    }
