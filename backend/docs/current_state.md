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
