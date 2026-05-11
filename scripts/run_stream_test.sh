#!/usr/bin/env bash
set -euo pipefail

# scripts/run_stream_test.sh
# Installs deps (if requirements.txt exists), initializes sqlite DB,
# starts the backend, and runs an SSE /query request to demonstrate
# the TRACE_EVENT streaming format expected for end-to-end agent runs.
# NOTE: This script assumes you want real LLM calls (no mocks). You MUST
# set OPENAI_API_KEY, OPENROUTER_API_KEY, or OPEN_ROUTER_KEY in the
# environment before running. If you do not have API keys, do not run
# this script.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT="${ROOT_DIR}/scripts/complete_stream_response_with_test_cases.txt"
LOGFILE="/tmp/uvicorn_stream.log"
DB_URL="sqlite+aiosqlite:///./dev_test.db"
HOST="127.0.0.1"
PORT=8000
UVICORN_MODULE="api.main:app"
START_TIMEOUT=30
UVICORN_PID=""
TMP_DIR="$(mktemp -d /tmp/mega_ai_stream.XXXXXX)"

cleanup() {
  if [ -n "${UVICORN_PID}" ] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    kill "${UVICORN_PID}" || true
  fi
  rm -rf "${TMP_DIR}" || true
}

trap cleanup EXIT

: > "${ARTIFACT}"
exec > >(tee -a "${ARTIFACT}") 2>&1

section() {
  echo
  echo "=== $1 ==="
}

run_json_request() {
  local title="$1"
  shift
  section "$title"
  echo "${*}"
  "$@"
}

extract_json_value() {
  local file_path="$1"
  local key_name="$2"
  python - "$file_path" "$key_name" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
text = path.read_text(encoding='utf-8', errors='ignore')
match = re.search(r'"%s"\s*:\s*"([^"]+)"' % re.escape(key), text)
if match:
    print(match.group(1))
PY
}

echo "Working directory: ${ROOT_DIR}"
cd "${ROOT_DIR}"

section "Artifact"
echo "Writing live output to ${ARTIFACT}"
echo "Temp workspace: ${TMP_DIR}"

# 1) Install dependencies (prefer requirements.txt)
if [ -f requirements.txt ]; then
  echo "Installing requirements from requirements.txt..."
  python -m pip install --upgrade pip
  if ! python -m pip install -r requirements.txt; then
    echo "WARNING: requirements.txt installation failed; continuing with the current environment."
  fi
else
  echo "requirements.txt not found. Please create one or install dependencies manually."
  echo "This script will attempt to continue but may fail at runtime without the right packages."
fi

LLM_READY=true

# 2) Check whether an LLM API key is present (we removed mocks)
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ] && [ -z "${OPEN_ROUTER_KEY:-}" ]; then
  LLM_READY=false
  echo "WARNING: No LLM API key detected. The script will still run non-LLM endpoints and mark query/eval sections as skipped."
fi

# 3) Export DATABASE_URL for local sqlite dev
export DATABASE_URL="${DB_URL}"

# 3b) Reset the local sqlite database so the current ORM schema is created fresh
rm -f "${ROOT_DIR}/dev_test.db"

# 4) Ensure port 8000 is free before starting the backend
if command -v lsof >/dev/null 2>&1; then
  existing_pids="$(lsof -t -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
  if [ -n "${existing_pids}" ]; then
    echo "Stopping existing process(es) on port ${PORT}: ${existing_pids}"
    kill ${existing_pids} || true
    sleep 1
  fi
fi

# 5) Start backend in background
echo "Starting backend (uvicorn) with DATABASE_URL=${DATABASE_URL}..."
rm -f "${LOGFILE}"
nohup env PYTHONUNBUFFERED=1 DATABASE_URL="${DATABASE_URL}" uvicorn ${UVICORN_MODULE} --host ${HOST} --port ${PORT} --log-level info > "${LOGFILE}" 2>&1 &
UVICORN_PID=$!

echo "uvicorn PID: ${UVICORN_PID} (logs -> ${LOGFILE})"

# 6) Wait for server readiness using the health endpoint
echo "Waiting up to ${START_TIMEOUT}s for server to be ready..."
SECS=0
while ! curl -s "http://${HOST}:${PORT}/health" >/dev/null 2>&1; do
  sleep 1
  SECS=$((SECS+1))
  if [ ${SECS} -ge ${START_TIMEOUT} ]; then
    echo "Server did not become ready within ${START_TIMEOUT}s. Tail logs for diagnosis:" && tail -n 200 "${LOGFILE}"
    kill ${UVICORN_PID} || true
    exit 2
  fi
done

echo "Server ready. Tail of log:" 
tail -n 80 "${LOGFILE}"

section "GET /"
curl -sS "http://${HOST}:${PORT}/" | tee "${TMP_DIR}/root.json"

section "GET /health"
curl -sS "http://${HOST}:${PORT}/health" | tee "${TMP_DIR}/health.json"

section "POST /submit-job"
curl -sS -X POST "http://${HOST}:${PORT}/submit-job" \
  -H "Content-Type: application/json" \
  -d '{"query":"queue test end-to-end"}' | tee "${TMP_DIR}/submit_job.json"

SUBMIT_JOB_ID="$(extract_json_value "${TMP_DIR}/submit_job.json" "job_id")"
if [ -n "${SUBMIT_JOB_ID}" ]; then
  section "GET /queue-status/${SUBMIT_JOB_ID}"
  curl -sS "http://${HOST}:${PORT}/queue-status/${SUBMIT_JOB_ID}" | tee "${TMP_DIR}/queue_status.json"
fi

section "GET /queue-stats"
curl -sS "http://${HOST}:${PORT}/queue-stats" | tee "${TMP_DIR}/queue_stats.json"

if [ "${LLM_READY}" = true ]; then
  section "POST /query"
  QUERY_PAYLOAD='{"query":"stream test end-to-end"}'
  QUERY_STREAM_FILE="${TMP_DIR}/query_stream.txt"
  curl -N -s --max-time 120 -H "Accept: text/event-stream" \
    -H "Content-Type: application/json" \
    -d "${QUERY_PAYLOAD}" \
    "http://${HOST}:${PORT}/query" | tee "${QUERY_STREAM_FILE}"

  JOB_ID="$(python - "${QUERY_STREAM_FILE}" <<'PY'
import re, sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding='utf-8', errors='ignore')
match = re.search(r'"job_id"\s*:\s*"([^"]+)"', text)
print(match.group(1) if match else "")
PY
  )"

  if [ -n "${JOB_ID}" ]; then
    section "GET /trace/${JOB_ID}"
    curl -sS "http://${HOST}:${PORT}/trace/${JOB_ID}" | tee "${TMP_DIR}/trace.json"

    section "GET /logs/${JOB_ID}"
    curl -sS "http://${HOST}:${PORT}/logs/${JOB_ID}" | tee "${TMP_DIR}/logs.json"
  fi

  section "POST /eval/run"
  curl -sS -X POST "http://${HOST}:${PORT}/eval/run" | tee "${TMP_DIR}/eval_run.json"

  section "GET /eval/latest"
  curl -sS "http://${HOST}:${PORT}/eval/latest" | tee "${TMP_DIR}/eval_latest.json"

  section "GET /eval/proposal"
  curl -sS "http://${HOST}:${PORT}/eval/proposal" | tee "${TMP_DIR}/eval_proposal.json"

  PROPOSAL_ID="$(extract_json_value "${TMP_DIR}/eval_proposal.json" "proposal_id")"
  if [ -n "${PROPOSAL_ID}" ]; then
    section "POST /eval/approve"
    curl -sS -X POST "http://${HOST}:${PORT}/eval/approve" \
      -H "Content-Type: application/json" \
      -d "{\"proposal_id\":\"${PROPOSAL_ID}\",\"decision\":\"reject\",\"reviewer_notes\":\"Automated runner capture\"}" \
      | tee "${TMP_DIR}/eval_approve.json"

    section "POST /eval/rerun"
    curl -sS -X POST "http://${HOST}:${PORT}/eval/rerun?proposal_id=${PROPOSAL_ID}" \
      | tee "${TMP_DIR}/eval_rerun.json"
  fi
else
  section "POST /query"
  echo "Skipped because no LLM API key is configured."
fi

TRACE_TARGET_JOB_ID="${JOB_ID:-${SUBMIT_JOB_ID:-}}"
if [ -n "${TRACE_TARGET_JOB_ID}" ]; then
  section "GET /trace/${TRACE_TARGET_JOB_ID}"
  curl -sS "http://${HOST}:${PORT}/trace/${TRACE_TARGET_JOB_ID}" | tee "${TMP_DIR}/trace.json"

  section "GET /logs/${TRACE_TARGET_JOB_ID}"
  curl -sS "http://${HOST}:${PORT}/logs/${TRACE_TARGET_JOB_ID}" | tee "${TMP_DIR}/logs.json"
fi

section "POST /eval/run"
curl -sS -X POST "http://${HOST}:${PORT}/eval/run" | tee "${TMP_DIR}/eval_run.json"

section "GET /eval/latest"
curl -sS "http://${HOST}:${PORT}/eval/latest" | tee "${TMP_DIR}/eval_latest.json"

section "GET /eval/proposal"
curl -sS "http://${HOST}:${PORT}/eval/proposal" | tee "${TMP_DIR}/eval_proposal.json"

section "POST /eval/approve"
if [ -n "${SUBMIT_JOB_ID}" ]; then
  curl -sS -X POST "http://${HOST}:${PORT}/eval/approve" \
    -H "Content-Type: application/json" \
    -d "{\"proposal_id\":\"${SUBMIT_JOB_ID}\",\"decision\":\"reject\",\"reviewer_notes\":\"Automated runner capture\"}" \
    | tee "${TMP_DIR}/eval_approve.json"
else
  echo "Skipped because no proposal-like UUID is available."
fi

section "POST /eval/rerun"
if [ -n "${SUBMIT_JOB_ID}" ]; then
  curl -sS -X POST "http://${HOST}:${PORT}/eval/rerun?proposal_id=${SUBMIT_JOB_ID}" \
    | tee "${TMP_DIR}/eval_rerun.json"
else
  echo "Skipped because no proposal-like UUID is available."
fi

section "Stream Response Format Notes"
cat <<'EXAMPLE'
The live /query stream now includes the full agent sequence and tool activity.
Expected order for a successful run:
AGENT_START -> orchestration_start -> routing_decision -> agent_start -> TOOL_CALL -> TOOL_RESULT -> agent_done -> ... -> critique -> synthesis -> orchestration_complete -> AGENT_END

Every event is written into the artifact file automatically while the script runs.

Common endpoint response shapes captured by this script:
- GET /health: {status, database, redis, http_status}
- GET /: API metadata, endpoint catalog, feature list
- POST /submit-job: {job_id, status, queue_size, worker_instruction}
- GET /queue-status/{job_id}: {job_id, status, query, created_at, final_answer, error_message, total_latency_ms}
- GET /queue-stats: {status, queue} or {status, error}
- POST /query: SSE stream of TRACE_EVENT objects with agent tool events
- GET /trace/{job_id}: {job_id, query, events[], final_answer, status}
- GET /logs/{job_id}: {job_id, total_events, events[]}
- POST /eval/run: evaluation summary for 15 test cases and 6 dimensions
- GET /eval/latest: latest grouped eval scores
- GET /eval/proposal: pending prompt rewrite proposal, if any
- POST /eval/approve: approval/rejection status and optional rerun_job_id
- POST /eval/rerun?proposal_id=...: rerun scores and delta vs baseline
EXAMPLE

if [[ "${KEEP_SERVER_RUNNING:-false}" == "true" ]]; then
  echo "Leaving backend running (PID ${UVICORN_PID})."
else
  echo "Stopping uvicorn (${UVICORN_PID})..."
  kill "${UVICORN_PID}" || true
  echo "Stopped. Logs available at ${LOGFILE}."
fi

exit 0
