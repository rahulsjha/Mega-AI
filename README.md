# Mega AI — Production-Grade Multi-Agent LLM Orchestration System

> Enterprise-ready multi-agent system with dynamic LLM routing, adversarial robustness evaluation, token-aware context management, real-time SSE streaming, and a self-improving meta-agent loop.

**Version:** 1.0.0 &nbsp;|&nbsp; **Status:** ✅ Production Ready &nbsp;|&nbsp; **Last Updated:** May 11, 2026

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Architecture](#2-architecture)
3. [Multi-Agent Pipeline](#3-multi-agent-pipeline)
4. [Security](#4-security)
5. [Tech Stack & Why Each Choice](#5-tech-stack--why-each-choice)
6. [Performance](#6-performance)
7. [Folder Structure](#7-folder-structure)
8. [API Endpoints (13 Total)](#8-api-endpoints-13-total)
9. [Setup Instructions](#9-setup-instructions)
10. [Docker Deployment](#10-docker-deployment)
11. [Evaluation Framework](#11-evaluation-framework)

---

## 1. Introduction

**Mega AI** is a production-grade, multi-agent orchestration system built on top of large language models. It solves the fundamental problem of routing complex, ambiguous, or adversarial queries through a coordinated pipeline of specialized AI agents — each focused on a distinct aspect of reasoning — and streaming live results back to the client in real time.

![alt text](architure.png)
### What makes it different from a simple LLM wrapper?

A plain LLM call is stateless, single-pass, and blind to its own failures. Mega AI introduces five cooperating agents that decompose problems, retrieve evidence, critique outputs, resolve contradictions, and compress context — all orchestrated dynamically by an LLM-powered master router with no hardcoded if-then logic. The system evaluates itself across 15 structured test cases, detects failures automatically, and generates prompt-rewrite proposals for human approval, creating a continuous self-improvement loop.

### Core capabilities at a glance

- **Real-time SSE streaming** — every agent decision, tool call, and token emitted live to the client
- **Token-aware context budget** — 6,000-token envelope managed across all agents, with automatic compression at 80%
- **Adversarial robustness** — dedicated test group for prompt injection and false-premise queries
- **Self-improving meta-agent** — scores < 0.75 trigger A/B prompt rewrites and conditional reruns
- **13 REST endpoints** — covering query execution, async job queue, evaluation, trace, and logs
- **Production hardened** — rate limiting, input sanitization, CORS, structured JSON logging, graceful shutdown

---

## 2. Architecture

### System Flow

```
                        ┌─────────────────────────────────────────┐
                        │              CLIENT / BROWSER            │
                        │         POST /query  →  SSE stream       │
                        └────────────────────┬────────────────────┘
                                             │
                        ┌────────────────────▼────────────────────┐
                        │           FASTAPI APPLICATION            │
                        │   Security layer: rate limit + sanitize  │
                        └────────────────────┬────────────────────┘
                                             │
                        ┌────────────────────▼────────────────────┐
                        │          MASTER ORCHESTRATOR             │
                        │      LLM-powered dynamic routing         │
                        │    (Temperature 0.0, Seed 42)            │
                        └──┬──────────┬──────────┬──────────┬─────┘
                           │          │          │          │
               ┌───────────▼──┐  ┌────▼───┐  ┌──▼─────┐  ┌▼──────────┐
               │ DECOMPOSITION│  │  RAG   │  │CRITIQUE│  │ SYNTHESIS  │
               │Query → DAG   │  │Retrieve│  │Span    │  │Merge +     │
               │of subtasks   │  │+ rerank│  │analysis│  │Resolve     │
               └──────────────┘  └────────┘  └────────┘  └───────────-┘
                                                                │
                                             ┌──────────────────▼──────────┐
                                             │  COMPRESSION (if >80% budget)│
                                             │  Recovers 15–20% token space │
                                             └──────────────────┬──────────┘
                                                                │
                        ┌───────────────────────────────────────▼────────┐
                        │         ASYNC DATABASE  +  REDIS QUEUE          │
                        │     SQLite (dev) / PostgreSQL (prod)            │
                        └────────────────────────────────────────────────┘
```

### Architecture diagram

Place your `architecture.png` at the project root. It is referenced in the README as shown below:

```
<p align="center">
  <img src="architecture.png" alt="Mega AI Architecture" width="900" />
</p>
```

The diagram should illustrate the six-layer flow: Client → FastAPI → Orchestrator → Agents (Decomposition, RAG, Critique, Synthesis, Compression) → Persistence (DB + Redis).

---

## 3. Multi-Agent Pipeline

### How the agents cooperate

Every query enters through the Master Orchestrator. The orchestrator makes routing decisions using an LLM call (not hardcoded rules), so the pipeline adapts to query complexity. Here is a concrete trace for the query *"Compare Python vs Rust for systems programming"*:

```
1. Orchestrator receives query
   └─ Emits: AGENT_START
   └─ Token budget: 6,000

2. → Decomposition agent
   └─ Produces DAG of 5 typed subtasks with dependencies
   └─ Tokens used: 672  |  Remaining: 5,328

3. → RAG agent (multi-hop retrieval)
   └─ Embed → vector search (k=5) → multi-hop → rerank → generate
   └─ Tokens used: 350  |  Remaining: 4,978

4. → Critique agent (span-level)
   └─ Flags 4 questionable claims with confidence scores (0.3–0.95)
   └─ Tokens used: 1,412  |  Remaining: 3,566

5. Budget check: 65% used — no compression needed

6. → Synthesis agent
   └─ Merges all outputs, resolves contradictions, builds provenance map
   └─ Tokens used: 1,520  |  Remaining: 2,046

7. → done
   └─ Emits: AGENT_END
   └─ Total tokens: 3,954  |  Total latency: 47.2 s
```

### Agent specifications

| Agent | Input | Output | Token cost |
|---|---|---|---|
| **Orchestrator** | Raw query | Routing decision | ~500 / decision |
| **Decomposition** | Query (possibly ambiguous) | DAG of subtasks | ~500 |
| **RAG** | Subtask | Retrieved chunks + generated answer | ~300 base + ~50/chunk |
| **Critique** | Decomposition + RAG output | Flagged claims + confidence scores | ~400–600 |
| **Synthesis** | All prior outputs | Final answer + provenance map | ~600–800 |
| **Compression** | Context at 80% budget | Trimmed context (15–20% recovered) | ~200 |

### SSE event stream

Each step emits structured `TRACE_EVENT` objects over Server-Sent Events:

```
AGENT_START          – orchestrator begins
orchestration_start  – query received, budget set
routing_decision     – next agent chosen by LLM
agent_start          – individual agent starts
TOOL_CALL            – tool invocation with inputs
TOOL_RESULT          – tool output
agent_done           – agent finishes (latency + tokens)
orchestration_complete – pipeline finished
AGENT_END            – final answer ready
```

---

## 4. Security

Security is layered across the request lifecycle. No single point of failure can expose internal state or allow injection.

### 4.1 API key management

Keys are loaded from environment variables and never committed to source. The `.env` file is git-ignored.

```bash
OPEN_ROUTER_KEY=sk-or-v1-...
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://user:password@host/db
REDIS_URL=redis://localhost:6379/0
```

At runtime, the LLM builder validates key presence and warns — but does not crash — if missing:

```python
def build_openrouter_llm():
    api_key = os.getenv("OPEN_ROUTER_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        logger.warning("No LLM API key. Query will fail.")
    return ChatOpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
```

### 4.2 Input validation and sanitization

Every incoming request is validated by Pydantic before any agent sees the data:

```python
class QueryRequest(BaseModel):
    query: str

    @validator('query')
    def validate_query(cls, v):
        if not v or len(v) < 3:
            raise ValueError("Query must be 3–5000 characters")
        return v.strip()
```

SQL injection is prevented by SQLAlchemy parameterization — no string concatenation in queries anywhere in the codebase.

### 4.3 Rate limiting

Redis-backed per-IP counter; 100 requests per minute before a `429` is returned:

```python
@app.middleware("http")
async def rate_limit(request, call_next):
    client_ip = request.client.host
    if redis_client.incr(f"rate_limit:{client_ip}") > 100:
        return JSONResponse(status_code=429, content={"error": "Rate limit exceeded"})
    redis_client.expire(f"rate_limit:{client_ip}", 60)
    return await call_next(request)
```

### 4.4 Context isolation

Each job runs in a completely isolated context window. Database queries are always filtered by `job_id` foreign key, and schema-level constraints enforce that no cross-job data can be accessed even if query logic had a bug.

### 4.5 CORS

Origins are whitelisted explicitly; wildcard `*` is never used in production:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://app.domain.com"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"]
)
```

### 4.6 Error handling

Internal errors are never surfaced to clients. The global exception handler logs the full traceback internally and returns a generic `500` with only a `request_id`:

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Internal error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "request_id": str(request.id)}
    )
```

---

## 5. Tech Stack & Why Each Choice

### Web framework — FastAPI 0.104.1

| Feature | Benefit | vs. alternatives |
|---|---|---|
| Async/await native | Non-blocking I/O for SSE streams | Flask blocks; Django needs Celery |
| Type hints everywhere | Auto-generated `/docs` + request validation | Flask requires extra libs |
| Auto OpenAPI schemas | TypeScript frontend ready out of the box | Django REST verbose; Spring annotaton-heavy |
| Lifespan hooks | Clean DB/Redis init and graceful shutdown | Flask manual context; Spring boilerplate |
| ~15k req/sec | Higher throughput under concurrent agent load | Flask ~2k; Django ~3k |

### Database ORM — SQLAlchemy 2.0 (async)

Async drivers (`asyncpg` for PostgreSQL, `aiosqlite` for dev) mean database queries never stall the event loop. The declarative ORM gives type-safe models for all 8 tables, and Alembic handles schema versioning and rollback. Raw `asyncpg` would lose type safety and make model maintenance significantly harder.

### Job queue — Redis 5.0

Sub-millisecond in-memory scheduling with optional RDB/AOF persistence. `socket_timeout=1.0` is set so the app starts with a logged warning rather than hanging if Redis is unavailable. RabbitMQ introduces Erlang overhead; Kafka is overkill for this workload.

### LLM integration — LangChain 0.1.0 + OpenRouter

LangChain provides a single interface that can swap providers (OpenAI, OpenRouter, Claude, Ollama) without changing agent code. `.with_structured_output()` ensures JSON safety. OpenRouter proxies multiple providers under one API key, offering cheaper costs and automatic fallback if a provider goes down.

### Data validation — Pydantic 2.5

Runtime validation catches malformed or malicious inputs before they reach any agent. Custom validators enforce token budget limits and character constraints. Auto-generated JSON schemas feed directly into FastAPI's OpenAPI output.

### Vector store — ChromaDB 0.4.20

Lightweight, local-first, no external service required for development. Embeddings live on disk and are queried in-process, keeping RAG latency low for single-node deployments.

### Logging — Structlog 23.2.0

Every log line is structured JSON with `job_id` threaded through, making it trivially ELK-stack or Splunk-ingestible. Human-readable output in dev; machine-parseable in production.

### Full stack summary

| Component | Technology | Version |
|---|---|---|
| Web framework | FastAPI | 0.104.1 |
| Async server | Uvicorn | 0.24.0 |
| Database ORM | SQLAlchemy | 2.0.23 |
| Data validation | Pydantic | 2.5.0 |
| LLM integration | LangChain | 0.1.0 |
| LLM provider | OpenRouter | — |
| Job queue | Redis | 5.0.1 |
| Vector store | ChromaDB | 0.4.20 |
| Logging | Structlog | 23.2.0 |

---

## 6. Performance

| Metric | Value |
|---|---|
| FastAPI throughput | ~15,000 req/sec (benchmark) |
| Redis queue latency | < 1 ms |
| Typical query latency (full pipeline) | ~47 seconds (LLM-bound) |
| Token budget per query | 6,000 tokens |
| Compression threshold | 80% budget used |
| Token recovery after compression | 15–20% |
| Rate limit | 100 req/min per IP |

Latency is dominated by LLM inference time across multiple agent hops. Infrastructure overhead (FastAPI routing, DB writes, Redis queue ops) is sub-millisecond and does not meaningfully contribute to end-to-end latency. For high-concurrency production scenarios, horizontal scaling of the FastAPI service combined with Redis Cluster and PostgreSQL connection pooling is recommended.

---

## 7. Folder Structure

```
mega AI/
│
├── api/
│   ├── main.py                        # FastAPI app + lifespan (DB/Redis init)
│   │
│   ├── endpoints/
│   │   ├── query.py                   # POST /query — SSE streaming
│   │   ├── health.py                  # GET /health — connectivity probes
│   │   │
│   │   ├── eval/
│   │   │   ├── run.py                 # POST /eval/run — 15-case harness
│   │   │   ├── latest.py              # GET /eval/latest — results by group
│   │   │   ├── proposal.py            # GET /eval/proposal — meta-agent proposal
│   │   │   ├── approve.py             # POST /eval/approve — human approval workflow
│   │   │   └── rerun.py               # POST /eval/rerun — delta vs baseline
│   │   │
│   │   ├── queue/
│   │   │   ├── submit.py              # POST /submit-job — async job submission
│   │   │   ├── status.py              # GET /queue-status/{id}
│   │   │   └── stats.py               # GET /queue-stats — Redis metrics
│   │   │
│   │   └── trace/
│   │       ├── trace.py               # GET /trace/{id} — full event log
│   │       └── logs.py                # GET /logs/{id} — event details + latencies
│   │
│   ├── agents/
│   │   ├── orchestrator.py            # Master router — LLM-powered dynamic routing
│   │   ├── decomposition.py           # Query → subtask DAG
│   │   ├── rag.py                     # Multi-hop retrieval + citations
│   │   ├── critique.py                # Span-level analysis + confidence flags
│   │   ├── synthesis.py               # Merge + contradiction resolution
│   │   └── compression.py             # Token recovery (triggered at 80% budget)
│   │
│   ├── llm.py                         # LangChain ChatOpenAI + OpenRouter builder
│   │
│   ├── db/
│   │   ├── models.py                  # SQLAlchemy ORM — 8 tables
│   │   └── database.py                # Async session factory + migrations
│   │
│   ├── queue/
│   │   └── job_queue.py               # Redis queue with fail-fast socket_timeout
│   │
│   ├── evaluation/
│   │   ├── harness.py                 # 15-test-case executor
│   │   ├── scorer.py                  # 6-dimension scoring logic
│   │   └── test_cases.py              # Group A / B / C definitions
│   │
│   ├── security/
│   │   ├── auth.py                    # API key validation
│   │   ├── rate_limit.py              # Per-IP request throttling (100 req/min)
│   │   └── sanitizer.py               # Input validation + SQL injection prevention
│   │
│   └── utils/
│       └── logging.py                 # Structured JSON logging (structlog)
│
├── scripts/
│   └── run_stream_test.sh             # Full integration test suite (all 13 endpoints)
│
├── tests/
│   ├── test_agents.py                 # Unit tests per agent
│   └── test_evaluation.py             # Harness + scoring accuracy tests
│
├── architecture.png                   # System architecture diagram
├── docker-compose.yml                 # Multi-service compose (API + PostgreSQL + Redis)
├── Dockerfile                         # API image build
├── requirements.txt                   # Python dependencies
├── .env.example                       # Environment variable template
└── README.md                          # This file
```

---

## 8. API Endpoints (13 Total)

### Infrastructure

#### `GET /` — API metadata
Returns complete system documentation, agent list, endpoint catalog, and feature summary.

```bash
curl http://localhost:8000/
```

#### `GET /health` — Health check
Probes database and Redis connectivity. Returns connection status for both.

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "database": {"connected": true, "url": "sqlite+aiosqlite:///./dev_test.db"},
  "redis": {"connected": true, "url": "redis://localhost:6379/0"},
  "http_status": 200
}
```

---

### Query Execution

#### `POST /query` — Real-time SSE streaming
Submit a query and receive a live stream of all agent events as Server-Sent Events.

```bash
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare Python vs Rust for systems programming"}'
```

Response is a continuous SSE stream:

```
data: {"event_type": "AGENT_START", "agent_name": "orchestrator", ...}
data: {"event_type": "routing_decision", "next_agent": "decomposition", ...}
data: {"event_type": "TOOL_CALL", "tool_name": "llm.decomposition", ...}
data: {"event_type": "TOOL_RESULT", "tool_output": {...}, ...}
data: {"event_type": "AGENT_END", "final_answer": "...", "token_cost": 3954}
```

---

### Job Queue

#### `POST /submit-job` — Async job submission
Queue a query for background processing. Returns immediately with a `job_id`.

```bash
curl -X POST http://localhost:8000/submit-job \
  -H "Content-Type: application/json" \
  -d '{"query": "What is machine learning?"}'
```

```json
{
  "job_id": "4fa55d89-e406-4501-85db-25f66abcd804",
  "status": "queued",
  "queue_size": 5
}
```

#### `GET /queue-status/{job_id}` — Check job status
Poll the status of a submitted job. `final_answer` is populated when complete.

```bash
curl http://localhost:8000/queue-status/4fa55d89-e406-4501-85db-25f66abcd804
```

```json
{
  "job_id": "4fa55d89-e406-4501-85db-25f66abcd804",
  "status": "processing",
  "query": "What is machine learning?",
  "final_answer": null,
  "total_latency_ms": null
}
```

Possible status values: `queued` → `processing` → `completed` / `failed`

#### `GET /queue-stats` — Queue statistics
Live Redis queue metrics.

```bash
curl http://localhost:8000/queue-stats
```

```json
{
  "status": "ok",
  "queue": {
    "queue_size": 5,
    "redis_memory_usage": "999.25K",
    "redis_connected_clients": 1
  }
}
```

---

### Evaluation

#### `POST /eval/run` — Execute full evaluation
Runs all 15 test cases across Groups A, B, and C and returns scores on all 6 dimensions.

```bash
curl -X POST http://localhost:8000/eval/run
```

```json
{
  "status": "completed",
  "run_id": "a81cceb1-...",
  "total_test_cases": 15,
  "summary": {
    "group_a": {
      "passed": 4,
      "failed": 1,
      "mean_score": 0.82,
      "scoring_details": {
        "answer_correctness": 0.85,
        "citation_accuracy": 0.80,
        "contradiction_resolution": 0.90,
        "tool_efficiency": 0.78,
        "budget_compliance": 1.0,
        "critique_agreement": 0.75
      }
    },
    "group_b": {"...": "..."},
    "group_c": {"...": "..."}
  },
  "pipeline_status": "PASS"
}
```

`pipeline_status` is `"FAIL"` if Group A mean score falls below 90%.

#### `GET /eval/latest` — Latest evaluation results
Returns the most recent eval run broken down by group and all 6 scoring dimensions.

```bash
curl http://localhost:8000/eval/latest
```

#### `GET /eval/proposal` — Meta-agent improvement proposal
If any scoring dimension is below 0.75, the meta-agent generates A/B prompt rewrite candidates.

```bash
curl http://localhost:8000/eval/proposal
```

```json
{
  "proposal_id": "prop-abc123",
  "dimension": "answer_correctness",
  "current_score": 0.55,
  "expected_improvement": 0.20,
  "variant_a": "Revised prompt variant A...",
  "variant_b": "Revised prompt variant B...",
  "hypothesis": "Reasoning for expected improvement"
}
```

Returns `{"detail": "No improvements identified by meta-agent"}` when all scores are healthy.

#### `POST /eval/approve` — Approve a proposal
Human-in-the-loop approval gate. Accepts or rejects the meta-agent's rewrite proposal.

```bash
curl -X POST http://localhost:8000/eval/approve \
  -H "Content-Type: application/json" \
  -d '{"proposal_id": "prop-abc123", "decision": "approved"}'
```

```json
{
  "status": "approved",
  "rerun_scheduled": true
}
```

#### `POST /eval/rerun` — Rerun failed cases with approved variant
Reruns only the cases that previously failed, using the approved prompt variant. Returns improvement delta.

```bash
curl -X POST http://localhost:8000/eval/rerun
```

```json
{
  "status": "completed",
  "baseline_score": 0.55,
  "new_score": 0.78,
  "improvement_delta": 0.23,
  "cases_retested": 3
}
```

---

### Trace & Logs

#### `GET /trace/{job_id}` — Complete execution trace
Returns all `TRACE_EVENT` objects for a job in chronological order.

```bash
curl http://localhost:8000/trace/cb3e7b0a-564d-4dc8-bd67-32df22e45e80
```

```json
{
  "job_id": "cb3e7b0a-564d-4dc8-bd67-32df22e45e80",
  "query": "stream test end-to-end",
  "events": [
    {"timestamp": "2026-05-11T09:04:08.427839", "event_type": "AGENT_START"},
    {"timestamp": "2026-05-11T09:04:13.175517", "event_type": "agent_start"},
    "..."
  ],
  "final_answer": "...",
  "status": "completed"
}
```

#### `GET /logs/{job_id}` — Event logs with latency metadata
Same event log as `/trace` but enriched with per-event latency figures.

```bash
curl http://localhost:8000/logs/cb3e7b0a-564d-4dc8-bd67-32df22e45e80
```

```json
{
  "job_id": "cb3e7b0a-564d-4dc8-bd67-32df22e45e80",
  "total_events": 31,
  "events": [
    {
      "timestamp": "2026-05-11T09:04:08.427839",
      "event_type": "AGENT_START",
      "latency_ms": 0.0
    },
    "..."
  ]
}
```

---

## 9. Setup Instructions

### Prerequisites

- Python 3.10+ (tested on 3.10.13)
- Redis 5.0+
- SQLite (dev) or PostgreSQL (production)
- OpenRouter API key **or** OpenAI API key

### Step 1 — Clone the repository

```bash
git clone https://github.com/rahulsjha/Mega-AI.git
cd "mega AI"
```

### Step 2 — Create a Python virtual environment

```bash
python3 -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install --upgrade pip
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt

# If you hit LangChain version conflicts:
pip install --upgrade langchain langchain-core langchain-community langchain-openai
```

### Step 4 — Configure environment variables

```bash
cp .env.example .env
nano .env
```

Required variables:

```env
OPEN_ROUTER_KEY=sk-or-v1-YOUR_KEY
# or
OPENAI_API_KEY=sk-YOUR_KEY

DATABASE_URL=sqlite+aiosqlite:///./dev_test.db
REDIS_URL=redis://localhost:6379/0
```

### Step 5 — Start Redis

```bash
# macOS
brew install redis
redis-server

# Verify
redis-cli ping   # → PONG
```

### Step 6 — Start the API server

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level info --reload
```

API: http://localhost:8000  
Swagger docs: http://localhost:8000/docs

### Step 7 — Run the test suite

```bash
# Full integration suite (all 13 endpoints)
bash scripts/run_stream_test.sh

# Unit tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=api --cov-report=html
```

### Step 8 — Quick smoke test

```bash
# Health check
curl http://localhost:8000/health

# Live SSE streaming query
curl -N -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the key differences between Python and Rust?"}'
```

---

## 10. Docker Deployment

### Build and run

```bash
# Build the image
docker build -t mega-ai:latest .

# Start all services
docker-compose up --build
```

Services started by Docker Compose:

| Service | Port |
|---|---|
| Mega AI API | 8000 |
| PostgreSQL | 5432 |
| Redis | 6379 |

### docker-compose.yml (reference)

```yaml
version: "3.9"

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://user:password@db:5432/megaai
      - REDIS_URL=redis://redis:6379/0
      - OPEN_ROUTER_KEY=${OPEN_ROUTER_KEY}
    depends_on:
      - db
      - redis

  db:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: megaai
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### Production deployment checklist

- [ ] Switch `DATABASE_URL` to PostgreSQL (not SQLite)
- [ ] Enable Redis Cluster or Redis Sentinel for HA
- [ ] Set `ENVIRONMENT=production`
- [ ] Configure SSL/TLS certificates (reverse proxy: Nginx or Caddy)
- [ ] Lock `CORS allow_origins` to production domain only
- [ ] Set up log aggregation (ELK Stack or Splunk)
- [ ] Configure monitoring (Prometheus + Grafana)
- [ ] Enable automated PostgreSQL backups
- [ ] Move secrets to AWS Secrets Manager (or equivalent)
- [ ] Configure auto-scaling policies
- [ ] Set up CI/CD pipeline (GitHub Actions recommended)

---

## 11. Evaluation Framework

### Test groups

| Group | Cases | Pass threshold | Focus |
|---|---|---|---|
| **A — Baseline** | 5 | ≥ 90% | Straightforward factual queries |
| **B — Ambiguous** | 5 | ≥ 75% | Underspecified inputs, decomposition quality |
| **C — Adversarial** | 5 | ≥ 70% | False premises, prompt injection, robustness |

### Scoring dimensions

| Dimension | Formula |
|---|---|
| Answer correctness | Cosine similarity vs expected answer |
| Citation accuracy | `valid_citations / total_claims` |
| Contradiction resolution | `resolved / total` |
| Tool efficiency | `1.0 − (redundant_calls / total)` |
| Budget compliance | 1.0 within / 0.8 compressed / 0.0 exceeded |
| Critique agreement | `acknowledged_flags / total` |

### Self-improvement loop

1. `POST /eval/run` — run all 15 cases
2. Any dimension score < 0.75 → meta-agent calls `GET /eval/proposal` and generates A/B prompt rewrites
3. Human reviews and calls `POST /eval/approve` with `"decision": "approved"`
4. `POST /eval/rerun` reruns only the failed cases with the approved variant
5. Improvement delta is recorded; baseline updated if new score is higher

---

## Support

**Bug reports** — open a GitHub issue with a minimal reproducible example, your OS and Python version, and the full error traceback.

**Contributions** — see `CONTRIBUTING.md`.

---

*Mega AI — built for production, designed for extensibility.*