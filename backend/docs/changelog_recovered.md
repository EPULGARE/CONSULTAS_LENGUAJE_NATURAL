# Changelog Recovered

## Scope Of This File
This is a reconstructed changelog based on:
- current code structure
- existing `docs/changelog.md`
- filenames, tests, and settings
- the visible local git snapshot

It is approximate and should be treated as a recovery aid, not authoritative release history.

## Recovered Timeline

### 2026-05-19
- The visible local history in this clone currently starts at `Initial project import`.
- Recovery documentation was added or aligned inside `backend/`:
  - `AGENTS.md`
  - `docs/system_context.md`
  - `docs/current_state.md`
  - `docs/file_index.md`
  - `docs/changelog_recovered.md`
  - `scripts/show_all_project_info.py`
  - `tests/test_show_all_project_info.py`

### 2026-05-12
Recovered directly from `docs/changelog.md`:
- formal approval gate added before metadata promotion
- `review_oracle_catalog.py` included in workflow
- `promote_oracle_catalog.py` gained `--approval` and `--require-approval`
- consistency validation added between generated metadata and approval files
- `allowed_for_select` support added at column level
- `discover_multitabla_mappings.py` added for governed mapping suggestions without auto-approval

## Undated Recovered Milestones

### API And Runtime Pipeline
- FastAPI backend established with `/query`, `/query/preview`, `/query/resolve-clarification`, and `/health`.
- Main orchestration centered in `app/api/routes_query.py`.

### Catalog Governance
- catalog loader implemented with curated override merging
- readiness validation added before query generation
- context directory layer introduced under `metadata/context/`
- generated, curated, approval, and context metadata layers separated clearly

### LLM Governance
- OpenRouter integration added
- domain classification made local-first, then LLM-assisted
- SQL generation constrained to extracted `SELECT`
- prompt debug output made optional and environment-gated

### Safety And Validation
- SQL validation based on `sqlglot`
- forbidden statement/keyword blocking
- sensitive-column blocking
- approved-relationship enforcement
- approved parametric-mapping enforcement
- query-pattern structure validation
- row limiting via dialect helpers

### Query Understanding
- semantic normalization added
- intent enhancer added
- clarification flow for ambiguous business terms added
- query-pattern detection added for top-N, grouped aggregation, municipality filters, and cardinality logic

### Context Selection
- local keyword/business-term ranking introduced
- relationship-graph join expansion introduced
- optional LLM table selector fallback introduced
- selected-column reduction introduced to minimize SQL prompt context

### Clarification Persistence
- conversation state manager added
- in-memory and SQLite storage providers added
- pending clarification resumption and TTL cleanup added

### Feedback Loops
- blocked-join candidate recording added
- ambiguity learning suggestions file added
- scripts for reviewing candidate relationships and ambiguity learning added

### Operator Tooling
- manual pipeline debugger added
- readiness check added
- evaluation runner added
- connectivity and smoke-test scripts added
- onboarding/bootstrap scripts added

### Test Expansion
- test suite grew to broad module coverage across API, validator, retrieval, context selection, conversation state, scripts, and integration-style dry-run behaviors

## Likely Historical Narrative
The code suggests the project evolved in roughly this order:
1. basic FastAPI + Text-to-SQL path
2. semantic catalog and metadata files
3. SQL validation and execution controls
4. approval-gated metadata promotion
5. context selection and join-path governance
6. intent enhancement and ambiguity handling
7. clarification persistence and operator/debug tooling
8. broader automated test coverage

This ordering is inferred from dependency shape and should be revalidated if fuller git history becomes available.
