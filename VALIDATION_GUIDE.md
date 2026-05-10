# Validation & Testing Guide

This guide helps you validate that the Mega AI system is correctly implemented and ready to run.

## ✅ Pre-Flight Checklist

### 1. Directory Structure Verification

```bash
cd "/Users/vishaljha/Desktop/mega AI"

# Expected files and directories
✓ api/main.py                    # FastAPI application
✓ api/context/schema.py          # AgentContext model
✓ api/context/budget.py          # Budget manager
✓ api/agents/orchestrator.py     # Master orchestrator
✓ api/agents/decomposition.py    # 5 sub-agents
✓ api/agents/rag.py
✓ api/agents/critique.py
✓ api/agents/synthesis.py
✓ api/agents/compression.py
✓ api/tools/base.py              # Tool system
✓ api/db/models.py               # Database models
✓ api/db/database.py             # DB connection
✓ api/eval/harness.py            # Evaluation
✓ api/eval/scoring.py            # 6 scoring dims
✓ api/eval/meta_agent.py         # Self-improving
✓ docker-compose.yml             # Docker setup
✓ Dockerfile.api                 # API container
✓ Dockerfile.worker              # Worker container
✓ requirements.txt               # Dependencies
✓ .env.example                   # Config template
✓ README.md                      # User guide
✓ ARCHITECTURE.md                # Tech specs
✓ IMPLEMENTATION_SUMMARY.md      # This summary
✓ alembic/                       # DB migrations
✓ tests/                         # Unit tests
```

### 2. Git History Verification

```bash
git log --oneline
# Should show at least:
# - Add comprehensive implementation summary
# - Initial project structure and Docker setup
```

### 3. Python Syntax Validation

```bash
# Check all Python files compile
python -m py_compile api/main.py
python -m py_compile api/agents/orchestrator.py
python -m py_compile api/context/budget.py
python -m py_compile api/tools/base.py

# Should produce no errors
```

### 4. Import Chain Validation

```bash
# Test import chain
python3 << 'EOF'
from api.context.schema import AgentContext
from api.context.budget import ContextBudgetManager
from api.agents.orchestrator import MasterOrchestrator
from api.tools.base import WebSearchTool, CodeExecutionTool
from api.db.models import Job, Event, ToolCall
from api.eval.harness import EvalHarness
from api.eval.scoring import ScoringEngine
print("✓ All imports successful")
EOF
```

### 5. Configuration Verification

```bash
# Check .env.example exists and has all required vars
grep -E "OPENAI_API_KEY|ANTHROPIC_API_KEY|DATABASE_URL|POSTGRES_PASSWORD" .env.example

# Should find all 4
```

## 🧪 Unit Tests

### Run Budget Manager Tests

```bash
pip install pytest

pytest tests/test_budget_manager.py -v
```

Expected output:
```
test_declare_budget PASSED
test_consume_tokens PASSED
test_consume_exceeds_budget PASSED
test_compression_threshold PASSED
test_sync_to_context PASSED
```

### Run Scoring Tests

```bash
pytest tests/test_scoring.py -v
```

Expected output:
```
test_answer_correctness_exact_match PASSED
test_answer_correctness_partial_match PASSED
test_answer_correctness_no_match PASSED
test_citation_accuracy PASSED
test_contradiction_resolution PASSED
test_budget_compliance PASSED
```

## 🚀 Integration Validation

### Option A: Docker Compose (Recommended)

```bash
# 1. Setup environment
cp .env.example .env

# 2. Edit .env with your API keys
# vim .env
# Set OPENAI_API_KEY or ANTHROPIC_API_KEY

# 3. Start services
docker compose up

# 4. In another terminal, verify health
sleep 5
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# 5. Check API docs
# Open http://localhost:8000/docs
```

### Option B: Local Development

```bash
# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start PostgreSQL
docker run -d --name mega_ai_db \
  -e POSTGRES_PASSWORD=testpass \
  -e POSTGRES_DB=mega_ai \
  -p 5432:5432 \
  postgres:15-alpine

# 4. Wait for DB to be ready
sleep 3

# 5. Test database connection
DATABASE_URL="postgresql+asyncpg://postgres:testpass@localhost:5432/mega_ai" \
OPENAI_API_KEY="sk-test" \
python3 -c "
from api.db.database import setup_db
import asyncio
asyncio.run(setup_db())
print('✓ Database initialized')
"

# 6. Start API
OPENAI_API_KEY="sk-test" \
DATABASE_URL="postgresql+asyncpg://postgres:testpass@localhost:5432/mega_ai" \
uvicorn api.main:app --reload

# 7. In another terminal, test endpoint
curl http://localhost:8000/health
```

## 📊 Code Quality Checks

### Type Hints Coverage

```bash
# All functions should have type hints
grep -r "def " api/ | grep -v "-> " | head -5
# Should be minimal (mostly __init__ methods)
```

### Error Handling

```bash
# Check for explicit error handling
grep -r "try:" api/ | wc -l
# Should have > 10 try blocks

# Check for structured errors
grep -r "PolicyViolation\|ToolResult\|AgentOutput" api/ | wc -l
# Should have > 20 matches
```

### Async/Await

```bash
# Count async functions
grep -r "async def" api/ | wc -l
# Should have > 15

# Verify FastAPI is async
grep -E "async def|await" api/main.py | wc -l
# Should have > 5
```

## 🔍 Behavioral Validation

### Context Budget Flow

```python
# This should work:
from api.context.schema import AgentContext, TokenBudget
from api.context.budget import ContextBudgetManager
from uuid import uuid4

# Create budget manager
mgr = ContextBudgetManager(default_budget_tokens=4000)

# Declare budgets
budget1 = mgr.declare_budget("agent1", 2000)
budget2 = mgr.declare_budget("agent2", 1500)

# Consume tokens
success = mgr.consume("agent1", 1500)
print(f"Consume success: {success}")
print(f"Remaining: {mgr.check_remaining('agent1')}")

# Create context and sync
context = AgentContext(job_id=uuid4(), query="test")
mgr.sync_to_context(context)
print(f"Context budget sync: {'agent1' in context.context_budget}")
```

### Tool Failure Contracts

```python
# This should work:
from api.tools.base import WebSearchTool, CodeExecutionTool
import asyncio

async def test_tools():
    search = WebSearchTool()
    code = CodeExecutionTool()
    
    # All tools should have these methods
    assert hasattr(search, 'on_timeout')
    assert hasattr(search, 'on_empty')
    assert hasattr(search, 'on_malformed')
    assert hasattr(code, 'on_timeout')
    
    print("✓ All tools have failure contracts")

asyncio.run(test_tools())
```

### Evaluation Setup

```python
# This should work:
from api.eval.harness import EvalHarness

harness = EvalHarness()

# Get test cases
all_cases = harness.get_all_cases()
print(f"Total test cases: {len(all_cases)}")

group_a = harness.get_cases_by_group("A")
print(f"Group A: {len(group_a)} cases")

group_c = harness.get_cases_by_group("C")
print(f"Group C (adversarial): {len(group_c)} cases")

# Should have 15 total
assert len(all_cases) == 15
print("✓ All 15 test cases loaded")
```

## 📋 Checklist Template

Use this to verify all components:

```
Infrastructure:
☐ docker-compose.yml exists and has 3 services
☐ Dockerfile.api exists and uses python:3.11-slim
☐ Dockerfile.worker exists
☐ .env.example has all required variables

Core Models:
☐ AgentContext has 19 fields
☐ TokenBudget model exists
☐ PolicyViolation model exists
☐ CritiqueResult with span_start/end exists
☐ ProvenanceEntry exists

Budget System:
☐ ContextBudgetManager has declare_budget()
☐ ContextBudgetManager has consume()
☐ ContextBudgetManager has check_remaining()
☐ Compression trigger at 80%

Orchestrator:
☐ MasterOrchestrator.execute() exists
☐ Routing decisions recorded with confidence
☐ Max 10 iteration guard

Agents (5 total):
☐ DecompositionAgent generates tasks with dependencies
☐ RAGAgent does 2-hop retrieval
☐ CritiqueAgent finds spans with character positions
☐ SynthesisAgent creates provenance map
☐ CompressionAgent frees tokens

Tools (4 total):
☐ WebSearchTool with on_timeout()
☐ CodeExecutionTool with on_malformed()
☐ StructuredDataTool with on_empty()
☐ SelfReflectionTool with error handling

API (5 endpoints):
☐ POST /query with SSE streaming
☐ GET /trace/{job_id}
☐ GET /eval/latest
☐ POST /eval/approve
☐ POST /eval/rerun

Database:
☐ 8 tables defined in models.py
☐ Alembic migration created
☐ Async support with asyncpg

Evaluation (15 cases, 6 dimensions):
☐ 5 Group A (baseline)
☐ 5 Group B (ambiguous)
☐ 5 Group C (adversarial)
☐ Correctness scorer
☐ Citation accuracy scorer
☐ Contradiction resolution scorer
☐ Tool efficiency scorer
☐ Budget compliance scorer
☐ Critique agreement scorer

Documentation:
☐ README.md (> 300 lines)
☐ ARCHITECTURE.md (> 400 lines)
☐ IMPLEMENTATION_SUMMARY.md (> 300 lines)
☐ Docstrings in all modules

Testing:
☐ test_budget_manager.py with > 4 tests
☐ test_scoring.py with > 4 tests
```

## 🚨 Common Issues & Solutions

### Issue: Import Errors
**Solution**: Make sure all `__init__.py` files exist in packages
```bash
find api -type d -exec touch {}/__init__.py \;
```

### Issue: Database Connection Failed
**Solution**: Verify PostgreSQL is running and credentials match
```bash
docker ps | grep postgres
# or check DATABASE_URL in .env
```

### Issue: LLM API Key Missing
**Solution**: Set environment variable before running
```bash
export OPENAI_API_KEY="sk-..."
# or
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Issue: Async Error
**Solution**: Ensure all database calls use `async with` pattern
```python
# Wrong
session = SessionLocal()

# Right
async with get_session() as session:
    ...
```

## ✨ What Success Looks Like

When everything is working:

1. **Docker Compose**: All 3 services start without errors
2. **API Health**: `curl localhost:8000/health` returns `{"status": "ok"}`
3. **Docs**: http://localhost:8000/docs shows all 5 endpoints
4. **Database**: `psql` can connect and see 8 tables
5. **Tests**: All pytest tests pass
6. **Traces**: `/trace/{job_id}` returns full execution history

---

**Status**: Ready for validation and testing!
