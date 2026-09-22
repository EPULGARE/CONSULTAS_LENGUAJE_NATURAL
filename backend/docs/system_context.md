# System Context

## Repository Identity
This repository implements a secure Text-to-SQL backend aimed at Oracle-backed business data. The system is designed to transform natural-language questions into validated `SELECT` queries using governed semantic metadata, while minimizing unsafe inference by the LLM.

The backend codebase is under `backend/`; the Next.js frontend is under the sibling `frontend/` directory. The recovery pack lives inside `backend/docs/`. GitHub Actions configuration lives at repository root in `.github/workflows/`.

## Architectural Style
The project follows a layered pipeline rather than a monolithic prompt wrapper:

1. API receives the question.
2. Metadata catalog is loaded from YAML.
3. Catalog readiness is validated.
4. Domain is classified.
5. Intent is normalized and ambiguity is handled.
6. Table/column context is narrowed.
7. Retrieval package is assembled.
8. LLM generates SQL.
9. SQL is validated locally with structural and governance rules.
10. Query is either skipped in dry-run or executed.
11. Audit trail is written.

This design keeps the LLM constrained by curated metadata and local validation logic.

## Main Modules

### API and Entry Point
- `app/main.py`
- `app/api/routes_query.py`

FastAPI exposes:
- `GET /health`
- `POST /query`
- `POST /query/preview`
- `POST /query/resolve-clarification`

`routes_query.py` is the orchestration center of the runtime pipeline.

### Core
- `app/core/config.py`
- `app/core/logging.py`
- `app/core/security.py`

`config.py` is the main operational switchboard. It defines execution defaults, model names, metadata locations, database mode, conversation state backend, and context-selection thresholds.

### LLM Layer
- `app/llm/classifier.py`
- `app/llm/sql_generator.py`
- `app/llm/openrouter_client.py`
- `app/llm/prompts.py`

Responsibilities:
- domain classification
- SQL generation
- OpenRouter transport
- prompt assembly

Important behavior:
- local domain vocabulary/rule classification is attempted before LLM classification
- SQL extraction accepts free text but only keeps the `SELECT` statement
- secrets are sanitized in client errors

### Intent and Semantic Normalization
- `app/intent_enhancer/`
- `app/semantic_normalization/`

This layer converts raw questions into a more governed representation:
- normalized terms
- resolved lookup values
- resolved numeric filters
- guardrails
- clarification questions
- ambiguity tracking

The project already contains special handling for ambiguous business terms such as `activos` and `conectados`.

### Semantic Catalog
- `app/semantic_catalog/loader.py`
- `app/semantic_catalog/retriever.py`
- `app/semantic_catalog/readiness.py`
- `app/semantic_catalog/models.py`

This is the heart of the governed context model.

Metadata sources:
- `metadata/domains.yml`
- `metadata/tables.yml`
- `metadata/relationships.yml`
- `metadata/examples.yml`
- `metadata/curated/*`
- `metadata/generated/*`
- `metadata/context/*`

The loader merges base metadata with curated business overrides. The retriever narrows the relevant subset of tables, columns, relationships, mappings, examples, and auxiliary Oracle-comment hints.

### Context Selection
- `app/context_selector/`

This layer reduces prompt size and keeps joins safer by:
- scoring tables locally from keywords/business terms
- optionally consulting an LLM table selector
- expanding through approved join paths
- selecting columns relevant to the question

The selector uses a hybrid local-plus-LLM approach, not LLM-only selection.

### Query Pattern Detection
- `app/query_patterns/`

This layer detects structures such as:
- grouped aggregation
- top-N ranking
- municipality filtering
- descriptive lookup
- cardinality conditions

These patterns are later enforced by the SQL validator so the generated SQL must preserve the intended structure.

### SQL Safety Layer
- `app/sql/validator.py`
- `app/sql/executor.py`
- `app/sql/dialects.py`

The validator is a major safety boundary. It blocks:
- non-`SELECT` statements
- multi-statement SQL
- forbidden keywords
- unapproved joins
- disallowed or sensitive columns
- invalid governed mappings
- shape mismatches against detected query patterns

The executor supports:
- Oracle via `oracledb`
- non-Oracle paths via SQLAlchemy, especially SQLite

### Conversation State
- `app/conversation_state/`

This supports clarification workflows:
- create pending clarification state
- resume by `conversation_id`
- implicit resume when an answer looks like a clarification reply
- TTL-based cleanup

Storage backends:
- in-memory
- SQLite

### Relationship Feedback
- `app/relationship_feedback/`

If a query requires an unapproved join path, the validator can surface candidate relationships for later review instead of silently allowing them.

### Audit
- `app/audit/`

Every processed question produces an audit entry with normalized question, SQL traces, success state, and execution metadata.

## Main Runtime Dependencies Between Modules
- `api/routes_query.py` depends on almost every functional layer.
- `intent_enhancer` depends on `semantic_normalization`, `semantic_catalog`, `query_patterns`, and `llm`.
- `semantic_retriever` depends on `context_selector`, `query_patterns`, and catalog models.
- `sql/validator.py` depends on `relationship_feedback`, query-pattern models, semantic mappings, and dialect helpers.
- `conversation_state` depends on intent models and clarification resolution logic.

## Important Conventions
- YAML metadata is a first-class source of truth.
- Generated metadata is not automatically trusted.
- Promotion into productive catalog requires explicit review.
- Runtime paths are resolved relative to `backend/`.
- Sensitive behavior is usually controlled by settings flags rather than ad hoc conditionals.
- Dry-run is the safe default.

## Operational Defaults
Recovered from `app/core/config.py` and `.env.example`:
- app port default: `8000`
- query execution default: disabled
- dry-run default: enabled
- catalog approval requirement: enabled
- Oracle is the primary database dialect
- OpenRouter is the LLM transport
- conversation state is enabled
- LLM-assisted context selection is enabled

## Important Inference
There is no evidence that this repository is only a prototype. It is better described as an actively evolving governed backend with real implementation breadth but incomplete business curation.
