# Architecture Document

## System Overview

This document provides detailed architecture information for the Mega AI multi-agent orchestration system.

## Agent Interaction Pattern

### The Shared Context Model

All agents communicate through a single `AgentContext` object. No agent ever calls another agent directly.

```
Agent A reads context
    ↓
Agent A mutates its fields
    ↓
Agent A returns context to Orchestrator
    ↓
Orchestrator passes context to Agent B
    ↓
Agent B reads context (sees A's outputs)
    ↓
Agent B mutates its fields
    ↓
...
```

**Benefits**:
- Loose coupling - agents don't import each other
- Full auditability - every mutation is tracked
- Easy to replay - context can be serialized
- Composable - can run agents in different orders

### Orchestrator Decision Logic

The orchestrator uses this heuristic:

```python
# Always try decomposition first if not done
if "decomposition" not in completed_agents:
    return "decomposition"

# Get info before critique
if "rag" not in completed_agents:
    return "rag"

# Always critique before synthesis
if "critique" not in completed_agents:
    return "critique"

# Only synthesize if we have both decomposition and RAG
if (len(completed_agents) >= 2 and 
    "decomposition" in completed_agents and
    "rag" in completed_agents):
    return "synthesis"

# If synthesis complete, we're done
if "synthesis" in completed_agents:
    return "done"
```

## Token Budget System

### Budget Declaration

```python
budget_manager = ContextBudgetManager(default_budget_tokens=4000)

# Each agent declares its budget
budget_manager.declare_budget("decomposition", 1500)  # For LLM calls
budget_manager.declare_budget("rag", 3000)
budget_manager.declare_budget("synthesis", 2000)
```

### Consumption Flow

```
Agent executes LLM call
    ↓
Count output tokens (heuristic: chars/4)
    ↓
Call budget_manager.consume(agent_name, tokens, context)
    ↓
Is consumed + new >= max?
    Yes → Record PolicyViolation
    No → Update TokenBudget.consumed_tokens
    ↓
Is percent_used >= 80%?
    Yes → Set context.metadata["needs_compression"]
    ↓
Orchestrator sees flag
    ↓
Trigger compression_agent.execute(context)
```

### Compression Strategy

**Protected (NEVER compress)**:
- Tool outputs
- Scores and metrics
- Citations and provenance
- Structured fields (arrays, objects)

**Compressible (OK to compress)**:
- Agent result text (keep first 500 chars, summarize rest)
- Metadata (keep only essentials)
- Routing history (keep last 3 decisions)
- Old tool call details

**Example**:
- Before: 12,000 tokens
- After:  8,500 tokens (freed: 3,500)
- Ratio:  0.71

## RAG Two-Hop Strategy

### Hop 1: Initial Retrieval

```
Query: "What is machine learning?"
    ↓
ChromaDB query with embedding similarity
    ↓
Top 5 chunks retrieved with scores:
  1. "Machine Learning is..." (score: 0.94)
  2. "Learning from data..." (score: 0.82)
  3. "Neural networks..." (score: 0.71)
  4. "Supervised learning..." (score: 0.68)
  5. "Pattern recognition..." (score: 0.65)
```

### Gap Analysis

```
Chunks cover:
- Definition ✓
- Learning mechanism ✓
- Examples ✓
Missing:
- Real-world applications
- Comparison with other AI

Refined queries:
  "machine learning applications"
  "machine learning vs deep learning"
```

### Hop 2: Targeted Retrieval

```
Query: "machine learning applications"
    ↓
Top 3 chunks retrieved
    ↓
Deduplicate against Hop 1 (compare IDs)
    ↓
Add new chunks to context.retrieved_chunks

Query: "machine learning vs deep learning"
    ↓
Top 3 chunks retrieved
    ↓
Add unique chunks
```

### Synthesis

```
Context has 8-10 chunks total
    ↓
LLM synthesizes into coherent answer
    ↓
Links each chunk to relevant claim
    ↓
Returns: "Machine Learning is... [sources: chunk_2, chunk_5]"
```

## Tool Failure Handling

### WebSearchTool Timeout Simulation

```python
# 10% of calls timeout
if random.random() < 0.1:
    await asyncio.sleep(timeout_seconds + 1)
    return self.on_timeout()  # Structured error

# Otherwise succeed
results = [{"url": "...", "snippet": "...", "relevance_score": 0.92}]
return ToolResult(success=True, data=results)
```

### Retry Logic (3 attempts max)

```python
for attempt in range(1, 4):
    result = await tool.execute_with_timeout(input)
    
    if result.success:
        # Accept result
        log_tool_call(tool, input, result, attempt, accepted=True)
        return result
    
    if result.error_type == "timeout":
        # Retry with simpler input
        input.data["max_results"] = 3  # Reduce complexity
        continue
    
    elif result.error_type == "empty":
        # Try different query
        input.data["query"] = simplify_query(input.data["query"])
        continue
    
    elif result.error_type == "malformed":
        # Don't retry
        log_tool_call(tool, input, result, attempt, accepted=False, 
                     rejection_reason="Malformed output")
        return result

# All 3 attempts failed
log_policy_violation("tool_failure", "critical", tool.name, ...)
```

## Critique Span Identification

The critique agent identifies specific problem spans:

```
Input: "Albert Einstein failed mathematics in school but still became a physicist."

Output:
{
  "critiques": [
    {
      "span_start": 17,
      "span_end": 50,
      "claim": "Albert Einstein failed mathematics",
      "confidence": 0.98,
      "flagged": true,
      "reasoning": "Historically inaccurate. Einstein was exceptional in mathematics."
    }
  ]
}
```

**Important constraints**:
- NEVER flag entire output
- Only flag specific, verifiable claims
- Include confidence score (0.0-1.0)
- Provide reasoning

## Provenance Mapping

After synthesis, create provenance entries:

```python
# For each sentence in final_answer:
entry = ProvenanceEntry(
    sentence_idx=0,
    sentence_text="Machine Learning enables...",
    source_agent="rag",  # Which agent provided this
    source_chunk_id="chunk_2",  # Which chunk if from RAG
    confidence=0.85  # How confident we are
)
context.provenance_map.append(entry)
```

**Why?**
- Reproducibility: trace every claim to source
- Explainability: users see where info came from
- Validation: test if cited chunks actually contain the info
- Improvement: identify weak sources

## Evaluation Scoring

### 1. Answer Correctness

```python
# Simple: keyword matching (production: embeddings)
if expected in final_answer:
    return 1.0
elif word_overlap > 0.7:
    return 0.7
else:
    return 0.1
```

### 2. Citation Accuracy

```python
# Verify all cited chunks exist
valid = 0
for entry in provenance_map:
    if entry.source_chunk_id in chunk_ids:
        valid += 1
return valid / total_citations
```

### 3. Contradiction Resolution

```python
# Did synthesis address flagged items?
flagged_count = sum(1 for c in critiques if c.flagged)
mentions = count_resolution_keywords(synthesis_output)
return min(1.0, mentions / flagged_count)
```

### 4. Tool Efficiency

```python
# Penalize excessive tool calls
efficiency = 1.0
for tool_name, count in tool_counts.items():
    if count > 3:  # Max 3 per tool
        efficiency -= (count - 3) * 0.1
return max(0, efficiency)
```

### 5. Budget Compliance

```python
# No violations = 1.0
critical = count_violations(severity="critical")
warnings = count_violations(severity="warning")
return 1.0 - (critical * 0.3) - (warnings * 0.1)
```

### 6. Critique Agreement

```python
# Does answer align with critique?
flagged_items = [c for c in critiques if c.flagged]
addressed = 0
for item in flagged_items:
    if item.claim.lower() not in answer.lower():
        addressed += 1
return addressed / len(flagged_items)
```

## Self-Improving Loop

### Process

1. **Run evaluation** on all 15 test cases
2. **Identify failures** (score < 0.6 on any dimension)
3. **Find worst dimension** across all failures
4. **Generate rewrite** with improvement guidance
5. **Store proposal** in DB with unified diff
6. **Human review** → approve or reject
7. **If approved**:
   - Re-run only previously failed cases
   - Compute delta scores (new - old)
   - Store deltas in `eval_deltas` table
   - Track improvement ratio

### Example

**Failed case**: C3 "Einstein math premise"
- Scoring dimension: `answer_correctness`
- Score: 0.35
- Problem: System didn't reject false premise

**Rewrite suggestion**:
```diff
--- Original
+++ Improved
@@ @@
- "Based on the information I have..."
+ "I need to address a factual error in this query first: 
+   Einstein was actually exceptional at mathematics. 
+   This premise is incorrect, so..."
```

**Expected improvement**: +0.3 on correctness dimension

**Human approval**: ✅ Approved by reviewer

**Re-run result**:
- New score: 0.78 (improvement: +0.43)
- Confirmed improvement exceeds expected

## Database Schema

### jobs
- id (UUID, primary key)
- query (text)
- status (pending/running/completed/failed)
- started_at, completed_at (datetime)
- final_answer (text)
- error_message (text)

### events
- id (UUID)
- job_id (FK)
- agent_id (string)
- event_type (string)
- input_hash, output_hash (SHA256)
- latency_ms, token_count
- policy_violations (JSON)

### tool_calls
- id (UUID)
- job_id (FK)
- tool_name (string)
- input/output hash and preview
- latency_ms
- attempt_number (1-3)
- accepted (boolean)
- error_type (timeout/empty/malformed)

### critique_logs
- id (UUID)
- job_id (FK)
- span_start, span_end (int)
- claim (text)
- confidence, flagged
- reasoning, source_agent

### eval_runs
- id (UUID)
- test_case_id, group (A/B/C)
- prompts_used (JSON)
- tool_calls_made (JSON)
- outputs_received (JSON)
- 6 score columns + 6 justification columns

### prompt_proposals
- id (UUID)
- original_prompt, rewritten_prompt (text)
- unified_diff (text)
- justification, target_dimension
- decision (approve/reject), reviewer_notes
- decided_at (datetime)

### eval_deltas
- id (UUID)
- proposal_id (FK)
- test_case_id (string)
- 6 delta columns (new_score - old_score)
- improvement_ratio

## Performance Considerations

### Token Efficiency

- Decomposition: 1500 tokens (LLM + prompt)
- RAG: 3000 tokens (retrieval + synthesis)
- Critique: 2000 tokens (analysis)
- Synthesis: 2000 tokens (combining)
- **Total budget: ~8500 tokens per query**

### Latency

- LLM calls: 2-5 seconds each
- Vector search: <100ms
- Database queries: <10ms
- Expected end-to-end: 15-30 seconds

### Optimization Strategies

1. **Parallel agents**: Run independent agents simultaneously
2. **Caching**: Store common queries/answers
3. **Cheaper models**: Use GPT-3.5 for decomposition
4. **Early exit**: Skip critique if high confidence

## Scaling Considerations

### Horizontal

- API can be stateless (serialize context to DB)
- Multiple workers can process jobs in parallel
- Database connections pooled

### Vertical

- Increase per-agent token budgets for complex queries
- Add more retrieval hops for deeper research
- Use better models (GPT-4 > GPT-3.5-turbo)

---

For questions, refer to README.md or review source code comments.
