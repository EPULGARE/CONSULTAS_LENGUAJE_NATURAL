# Current State

## Approximate Status
The project appears to be in a mid-build backend phase:
- core API flow exists
- security and validation are substantive, not placeholder-only
- semantic metadata governance is already a central design constraint
- context selection and ambiguity handling are implemented
- automated tests cover many modules
- business metadata curation is still incomplete

This is not a greenfield scaffold, but it is also not a finished production-hardened system.

## What Is Working Conceptually
- Natural-language query intake through FastAPI.
- Domain detection using local vocabulary/rules with LLM fallback.
- Intent enhancement and ambiguity-aware clarification flow.
- Retrieval of governed semantic context from YAML metadata.
- SQL generation through OpenRouter.
- Local SQL validation using `sqlglot`.
- Optional execution against Oracle or SQLite-like backends.
- Audit logging.
- Manual/debug/evaluation scripts.
- Metadata approval workflow with review and promotion steps.

## Current Default Safety Posture
Recovered from settings and examples:
- execution is blocked by default
- dry-run is on by default
- approval gate is on
- catalog readiness is validated before invoking the LLM
- prompt debug output is hidden by default

This strongly suggests the intended working mode is:
1. refine metadata
2. inspect generated SQL in dry-run
3. enable execution only deliberately

## Known Signs of Incompleteness

### Business Metadata Still Has Many Placeholders
There are many `TODO: describir ...` entries inside:
- `metadata/tables.yml`
- `metadata/context/tables/*.yml`

This means the technical pipeline is ahead of the business-description curation.

### Some Fallback/Error Paths Are Defensive Rather Than Fully Resolved
Example:
- `app/context_selector/llm_table_selector.py` contains a JSON parsing fallback path with `pass` inside exception handling.

This is not a bug by itself, but it indicates pragmatic fallback handling rather than a finalized observability or error model.

### Documentation Was Partial
Before this recovery pass, `backend/docs/` contained useful but short notes, not a full project-recovery pack.

## Test Situation
- `tests/` currently contains 40 visible test files in this clone, plus the new recovery-script test.
- Coverage is broad across API, validator, retrieval, context selection, intent enhancement, scripts, and conversation state.
- Only the recovery-script test was re-executed in this session.

That means:
- there is meaningful automated coverage
- the whole suite current green/red status was not re-verified here

## Current Repository Snapshot
- visible branch: `main`
- visible remote-tracking state: `main...origin/main`
- visible local history in this clone currently starts at `Initial project import`

This local history is shallow, so functional chronology had to be reconstructed mainly from code and `docs/changelog.md`.

## Likely Immediate Priorities For Future Work
1. complete business descriptions and semantic curation in metadata
2. validate the intended Oracle environment from `.env`
3. run readiness and evaluation scripts against the current metadata
4. verify whether conversation-state persistence should stay in memory or move to SQLite by default
5. reduce ambiguity around domain-specific status terms through curated rules and approved lookup values

## Important Operational Assumptions
- The main service is the backend only; no frontend is present in this repo.
- Oracle is the intended production-like target.
- SQLite is mainly useful for local persistence and test scenarios.
- `manual_query_debug.py` is the most complete operator-facing introspection tool in the repo.

## Approximate Confidence Statement
Confidence is high on the architectural reconstruction and module responsibilities.
Confidence is medium on historical sequencing, because the git history available locally is minimal.

## Frontend MVP
`frontend/` now contains a minimal Next.js + React + TypeScript app for the first web MVP. It is intentionally a thin UI layer over the existing governed backend and does not modify SQL generation, SQL validation, metadata, mappings, relationship approvals, or execution policy.

Local startup:
- `cd frontend`
- `npm install`
- `npm run dev`

Configuration:
- default backend URL is `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`
- `.env.local.example` documents the expected local variable

Runtime behavior:
- the browser submits chat messages to either `/api/query-preview` or `/api/query`
- Next.js proxies preview requests to FastAPI `POST /query/preview`
- Next.js proxies execution requests to FastAPI `POST /query`
- the UI renders SQL, result rows, `row_count`, retrieved tables, warnings, dry-run/execution status, resolved mappings and clarification prompts
- the UI does not decide whether execution is safe; it only displays `execution_skipped` and `execution_skip_reason` from the backend

Important assumption:
- the backend remains the source of truth for all Text-to-SQL behavior and governance

## MVP Validation Notes - 2026-06-02
- Backend health check passed on `http://127.0.0.1:8000/health`.
- Frontend health check passed on `http://127.0.0.1:3000`.
- Local `.env` config keeps `QUERY_ALLOW_EXECUTION=false` and `QUERY_DRY_RUN_DEFAULT=true`.
- SQLite conversation state was stabilized for local development. The storage now uses in-memory journaling and can recover from a corrupt configured file by quarantining it or creating a recovered alternate SQLite file when the original cannot be renamed.
- Backend focused tests passed 54/54 for `tests/test_query_endpoint.py`, `tests/test_sql_validator.py` and `tests/test_oracle_executor.py`.
- `py -m scripts.project_readiness_check` passed with OK=20, WARNING=0, ERROR=0.
- The MVP web was revalidated through `frontend /api/query-preview -> FastAPI /query/preview` using the real `.env` SQLite backend, and returned validated SQL with `execution_skipped=true`.
- In `POST /query/preview`, Oracle execution is intentionally skipped, so real result rows cannot be validated until execution is enabled through backend configuration.
- Frontend `npm run build` passed and `npm audit` reported 0 vulnerabilities.

## Controlled Oracle Execution Validation - 2026-06-02
- `/query` was validated with temporary process-only overrides: `QUERY_ALLOW_EXECUTION=true` and `QUERY_DRY_RUN_DEFAULT=false`.
- The permanent `.env` configuration was not changed and remains safe: `QUERY_ALLOW_EXECUTION=false`, `QUERY_DRY_RUN_DEFAULT=true`.
- A simple aggregate business query executed successfully against Oracle and returned one result row with `execution_skipped=false`, `execution_skip_reason=null`, validated SQL, retrieved tables and no warnings.
- A no-results query executed successfully and returned `rows=[]`, `row_count=0`, `execution_skipped=false`.
- An ambiguous query still skipped execution and returned `requires_user_confirmation=true` with a `conversation_id`.
- An invalid too-short request returned HTTP 422 before reaching SQL generation.
- `/query/preview` still forced dry-run while execution was temporarily enabled, returning `execution_skipped=true` and `execution_skip_reason=dry_run=true`.
- Manual attempts to induce unsafe SQL through natural language did not reach the validator as unsafe SQL; the generator stayed constrained to catalog-backed SELECT output. Validator blocking remains covered by automated validator tests.

## Frontend Execution Mode Validation - 2026-06-02
- The frontend now offers two modes: `Vista previa` and `Ejecutar consulta`.
- `Vista previa` calls `/api/query-preview` and always receives dry-run behavior from FastAPI `POST /query/preview`.
- `Ejecutar consulta` calls `/api/query`, which forwards to FastAPI `POST /query`; real execution still happens only if the backend process allows it.
- With the backend in safe mode, `/api/query` returned `execution_skipped=true` and `execution_skip_reason=QUERY_ALLOW_EXECUTION=false`.
- With temporary backend execution enabled, `/api/query` returned Oracle rows with `execution_skipped=false`.
- With temporary execution enabled, `/api/query-preview` still returned `execution_skipped=true` and `execution_skip_reason=dry_run=true`.
- Ambiguous requests in execution mode still return a clarification with `execution_skip_reason=requires_user_confirmation`.

## MVP Demo Closure - 2026-06-02
- The MVP web is ready for internal demo in safe mode.
- `README.md` documents backend startup, frontend startup, preview mode, controlled execution mode and final validations.
- `docs/demo_guide.md` provides a short demo script for simple, result-bearing, no-result, ambiguous and safe-mode execution cases.
- Final backend command `py -m pytest tests\test_query_endpoint.py tests\test_sql_validator.py tests\test_oracle_executor.py` passed 54/54.
- Final readiness command `py -m scripts.project_readiness_check` passed OK=20, WARNING=0, ERROR=0.
- Final frontend command `npm run build` passed.
- Real execution remains disabled by default through `.env`; demo execution requires explicit temporary process-level overrides.
