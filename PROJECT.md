# Project: ShefaGuide AI Hotfix and Performance Hardening

## Architecture
- Module/package boundaries, data flow, shared interfaces:
  - `app/safety`: PII scrubbing and safety guardrails (`EGYPTIAN_NATIONAL_ID_PATTERN`).
  - `app/agent`: LangGraph state machine, tool definitions (`ChatGoogleGenerativeAI`), session store, and async execution offload (`asyncio.to_thread`).
  - `app/main.py`: FastAPI application, traceability, audit logs, SSE streaming, and latency rounding.
  - `eval`: Clinical DEPI SLO evaluation and hybrid retrieval evaluation.
  - `frontend`: React 19 + Tailwind CSS + Vite web interface.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | R1 Tracked Files Restoration | Restore `docs/DEMO_SCRIPT_AND_LIMITATIONS.md` and `tests/test_step11_delivery_docs.py` via `git checkout` | M1 | survey |
| 2 | R2 PII Scrubber 14-Digit Float Fix | Update `EGYPTIAN_NATIONAL_ID_PATTERN` to `(?<![\d.])[23]\d{13}(?![\d.])|(?<![\d.])\d{14}(?![\d.])` and add unit test in `tests/test_step10_traceability_and_ci.py` | M1 | survey |
| 3 | R2 Latency Rounding | Round `execution_latency_ms` and `latency_ms` to 2 decimal places in `app/agent/graph.py` and `app/main.py` | M1 | survey |
| 4 | R3 Retrieval Eval PYTHONPATH | Insert `PROJECT_ROOT` into `sys.path` at top of `eval/run_retrieval_eval.py` matching `eval/run_eval.py` | M1 | survey |
| 5 | R4 LLM Timeout & Retries | Set `timeout=2.5` and `max_retries=1` on `ChatGoogleGenerativeAI` in `app/agent/tools.py` | M1 | survey |
| 6 | R4 Non-Blocking Async Graph Offloading | Offload synchronous graph execution in `run_triage_agent` via `await asyncio.to_thread(invoke_triage_graph_state, ...)` | M1 | survey |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Hotfix & Hardening (R1-R4) | Execute R1-R4 hotfixes, verify ruff, pytest, eval suites, and frontend verification | none | DONE |

Outputs: All 8 acceptance checks passed 100% (Ruff: 0 errors, Pytest: 177 passed, DEPI eval: PASS with 0% PHI leakage, Retrieval eval: 91.88% Recall@5, Frontend: 0 errors).

## Interface Contracts
### PII Scrubber & Graph Latency
- `contains_pii(text: str) -> bool`: Rejects 14-digit floats preceded or followed by `.`
- `execution_latency_ms` / `latency_ms`: Float rounded to 2 decimal places (`round(val, 2)`)

### LangGraph Async Offload
- `run_triage_agent(request: TriageRequest) -> TriageResponse`: Asynchronously runs `invoke_triage_graph_state` in worker thread via `asyncio.to_thread`, keeping FastAPI's event loop and SSE streams unblocked.

### Retrieval Eval Runner
- `python eval/run_retrieval_eval.py`: Self-contained script execution with project root injected into `sys.path`, returning Recall@5 >= 90%.

## Code Layout
- `app/safety/pii_scrubber.py`: Regex pattern definitions
- `app/agent/tools.py`: Gemini client instantiation
- `app/agent/graph.py`: LangGraph invocation, latency recording, async offloading
- `app/main.py`: Audit logging, traceability endpoint, endpoint timing
- `eval/run_retrieval_eval.py`: Standalone retrieval benchmark runner
- `tests/test_step10_traceability_and_ci.py`: Traceability and PII unit tests
- `tests/test_step11_delivery_docs.py`: Capstone delivery documentation tests
- `docs/DEMO_SCRIPT_AND_LIMITATIONS.md`: Capstone demo script & limitations
