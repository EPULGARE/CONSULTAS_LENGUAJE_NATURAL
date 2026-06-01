# AGENTS.md

## Purpose
This repository contains a governed Text-to-SQL backend focused on Oracle data access with strong safety controls, metadata curation, dry-run-first behavior, and approval-gated catalog growth.

The working application lives under `backend/`. This `AGENTS.md` and the files in `backend/docs/` are the local recovery pack for future Codex sessions.

## Non-Negotiable Project Rules
- Do not invent metadata.
- Do not bypass SQL validation before execution.
- Keep `QUERY_ALLOW_EXECUTION=false` unless the task explicitly requires real execution.
- Preserve the approval workflow for metadata:
  `generated -> approvals -> manual review -> promotion`.
- Treat `.env` and runtime credentials as sensitive.
- Prefer documentation, tests, and metadata curation over ad hoc logic changes.

## High-Level Architecture
- API layer: `backend/app/api/`
- App entrypoint: `backend/app/main.py`
- Core settings/logging/security: `backend/app/core/`
- LLM orchestration: `backend/app/llm/`
- Intent enhancement and ambiguity handling: `backend/app/intent_enhancer/`
- Semantic normalization: `backend/app/semantic_normalization/`
- Catalog loading/retrieval/readiness: `backend/app/semantic_catalog/`
- Context narrowing and join-path selection: `backend/app/context_selector/`
- Query-pattern detection: `backend/app/query_patterns/`
- SQL validation/execution: `backend/app/sql/`
- Conversation clarification state: `backend/app/conversation_state/`
- Relationship feedback for blocked joins: `backend/app/relationship_feedback/`
- Audit logging: `backend/app/audit/`

## Main Runtime Flow
1. `POST /query` or `POST /query/preview` enters through `backend/app/api/routes_query.py`.
2. Catalog YAML is loaded from `backend/metadata/`.
3. Readiness is validated before calling LLM services.
4. Domain is classified from local vocabulary/rules and then LLM if needed.
5. Intent enhancer normalizes terms, resolves governed lookup values, and may request clarification.
6. Context selector narrows tables/columns and approved join paths.
7. Semantic retriever builds the minimal SQL-generation context.
8. SQL generator calls OpenRouter and extracts a single `SELECT`.
9. SQL validator blocks unsafe SQL, unapproved joins, sensitive columns, bad mappings, and shape mismatches.
10. Execution is skipped by default unless explicitly enabled.
11. Audit is persisted to `backend/logs/audit.log`.

## Key Commands
Run these from `backend/` unless noted otherwise.

- Start API:
  `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Run tests:
  `py -m pytest`
- Readiness check:
  `py scripts/project_readiness_check.py --json-output outputs/readiness.json`
- Manual debug pipeline:
  `py scripts/manual_query_debug.py "consulta de prueba" --show-prompt true`
- Evaluate governed question set:
  `py scripts/evaluate_text_to_sql.py --questions metadata/evaluation/questions.yml --output outputs/text_to_sql_evaluation.json`
- Oracle connectivity check:
  `py scripts/check_oracle_connection.py`
- OpenRouter connectivity check:
  `py scripts/check_openrouter_connection.py`
- Recovery summary:
  `py -m scripts.show_all_project_info`

## Metadata Workflow
- Inspect source schema:
  `py scripts/inspect_oracle_schema.py ...`
- Produce review file:
  `py scripts/review_oracle_catalog.py ...`
- Promote approved catalog:
  `py scripts/promote_oracle_catalog.py ... --require-approval`
- Build context files:
  `py scripts/build_context_from_catalog.py`
- Build approved lookup values:
  `py scripts/build_approved_lookup_values.py`

## Current State Snapshot
- The repository is in an early but substantial implementation phase.
- The backend is not a stub: it already includes API, LLM flow, context selection, validation, audit, clarification state, and many tests.
- Recovery documentation now exists inside `backend/docs/` for portable context reconstruction.
- There are many metadata placeholders (`TODO: describir ...`) that indicate incomplete business curation.
- The visible local history in this clone currently shows `Initial project import` as the oldest available commit.

## What Future Sessions Should Do First
1. Read `docs/system_context.md`.
2. Read `docs/current_state.md`.
3. Read `docs/file_index.md`.
4. Check `docs/changelog_recovered.md` and legacy `docs/changelog.md`.
5. Run `py -m scripts.show_all_project_info` when a quick recovery summary is needed.
6. Inspect `.env.example` before making environment assumptions.

## What Future Sessions Should Avoid
- Do not change query execution defaults casually.
- Do not hardcode domain assumptions outside governed metadata.
- Do not add new joins without validating the relationship workflow.
- Do not treat generated metadata as automatically trustworthy.
