# Mega AI - Multi-Agent LLM Orchestration System

## Overview

This is a production-grade, containerized multi-agent LLM orchestration system built with Python 3.11+, FastAPI, PostgreSQL, and Docker Compose.

The system implements a sophisticated architecture where multiple specialized agents collaborate through a shared context object, coordinated by an LLM-powered orchestrator. It includes full observability, token budget management, self-improving evaluation loops, and comprehensive testing.

## Quick Start (< 5 minutes)

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)
- OpenAI or Anthropic API key

### Setup

```bash
# Clone repository
cd /Users/vishaljha/Desktop/mega\ AI

# Copy environment template
cp .env.example .env

# Edit .env with your API keys
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...

# Start system
docker compose up

# Wait for services to be healthy
# DB: postgresql://mega_ai_user:password@localhost:5432/mega_ai
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### Test It

```bash
# In another terminal
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is artificial intelligence?"}'

# Watch SSE events stream back
```
