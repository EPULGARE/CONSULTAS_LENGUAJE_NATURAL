# File Index

## Backend Root
- `AGENTS.md`: quick recovery guide for future Codex sessions.
- `README.md`: project overview plus recovery instructions.
- `docs/`: legacy docs plus recovery docs.
- `app/`: application code.
- `metadata/`: governed semantic catalog.
- `scripts/`: operator and maintenance scripts.
- `tests/`: automated tests.

## Application

### Entry and API
- `app/main.py`: FastAPI app setup and `/health`.
- `app/api/routes_query.py`: main query orchestration endpoints.

### Core
- `app/core/config.py`: settings, feature flags, paths, execution defaults.
- `app/core/logging.py`: logging bootstrap.
- `app/core/security.py`: question normalization and security helpers.

### LLM
- `app/llm/classifier.py`: domain classifier with local-first then LLM fallback.
- `app/llm/sql_generator.py`: SQL prompt assembly and SQL extraction.
- `app/llm/openrouter_client.py`: OpenRouter HTTP client with proxy/TLS options.
- `app/llm/prompts.py`: system/user prompts.

### Intent and Normalization
- `app/intent_enhancer/enhancer.py`: governed intent enrichment and clarification logic.
- `app/intent_enhancer/models.py`: intent result models.
- `app/intent_enhancer/prompts.py`: enhancer prompts.
- `app/semantic_normalization/normalizer.py`: local semantic normalization pipeline.
- `app/semantic_normalization/rules.py`: normalization helpers and rule utilities.
- `app/semantic_normalization/models.py`: normalization models.

### Semantic Catalog and Retrieval
- `app/semantic_catalog/loader.py`: YAML loading and override merging.
- `app/semantic_catalog/retriever.py`: safe context assembly for SQL generation.
- `app/semantic_catalog/readiness.py`: preflight readiness checks.
- `app/semantic_catalog/models.py`: catalog, mapping, retrieval, and lookup models.

### Context Selection
- `app/context_selector/directory_loader.py`: loads compact and detailed context files.
- `app/context_selector/selector.py`: local plus LLM table/column selection.
- `app/context_selector/relationship_graph.py`: approved join path expansion.
- `app/context_selector/llm_table_selector.py`: LLM fallback for table choice.
- `app/context_selector/models.py`: directory/context selection models.

### Query Patterns
- `app/query_patterns/detector.py`: pattern detection from natural language.
- `app/query_patterns/patterns.py`: pattern heuristics.
- `app/query_patterns/skeletons.py`: pattern skeleton rendering.
- `app/query_patterns/models.py`: pattern model definitions.

### SQL Layer
- `app/sql/validator.py`: central safety validator using `sqlglot`.
- `app/sql/executor.py`: Oracle/SQLAlchemy execution.
- `app/sql/dialects.py`: dialect helpers and row limiting.

### Conversation State
- `app/conversation_state/manager.py`: state creation, resumption, cleanup.
- `app/conversation_state/resolver.py`: clarification resolution helpers.
- `app/conversation_state/models.py`: state and clarification models.
- `app/conversation_state/storage_providers/memory.py`: in-memory pending state backend.
- `app/conversation_state/storage_providers/sqlite.py`: SQLite pending state backend.

### Audit and Feedback
- `app/audit/models.py`: audit schema.
- `app/audit/service.py`: append-only audit logging.
- `app/relationship_feedback/detector.py`: unapproved-join candidate detection.
- `app/relationship_feedback/writer.py`: candidate persistence.
- `app/relationship_feedback/models.py`: feedback models.

### Schemas
- `app/schemas/query.py`: request model.
- `app/schemas/response.py`: response model.

## Metadata

### Primary Catalog
- `metadata/domains.yml`
- `metadata/tables.yml`
- `metadata/relationships.yml`
- `metadata/examples.yml`
- `metadata/business_terms.yml`

### Curated
- `metadata/curated/ambiguity_rules.yml`
- `metadata/curated/business_overrides.yml`
- `metadata/curated/domain_vocabulary.yml`
- `metadata/curated/lookup_value_normalization.yml`
- `metadata/curated/numeric_entity_mappings.yml`

### Generated
- `metadata/generated/oracle_comments.yml`
- `metadata/generated/approved_lookup_values.yml`
- `metadata/generated/relationship_candidates.yml`
- `metadata/generated/ambiguity_learning_suggestions.yml`
- domain/table-specific generated files such as `clientes.yml`, `medidores.yml`, `multitabla.yml`, `procesos.yml`

### Approval Layer
- `metadata/approvals/*.yml`: manual review files used before promotion.

### Context Layer
- `metadata/context/table_directory.yml`: compact directory for context selection.
- `metadata/context/relationship_index.yml`: join-path index.
- `metadata/context/tables/*.yml`: per-table detailed context files.

### Evaluation Inputs
- `metadata/evaluation/questions.yml`
- `metadata/evaluation/questions_medidores.yml`

## Scripts
- `scripts/bootstrap_real_catalog.py`: guided bootstrap for real catalog onboarding.
- `scripts/inspect_oracle_schema.py`: Oracle schema introspection.
- `scripts/review_oracle_catalog.py`: create review/approval structures.
- `scripts/promote_oracle_catalog.py`: promote approved metadata into catalog.
- `scripts/promote_approved_relationships.py`: promote reviewed relationship candidates.
- `scripts/extract_oracle_comments.py`: extract Oracle comments into generated metadata.
- `scripts/build_context_from_catalog.py`: rebuild context directory/detail artifacts.
- `scripts/build_approved_lookup_values.py`: rebuild normalized/approved lookup-value files.
- `scripts/discover_multitabla_mappings.py`: suggest mappings to `SAC.MULTITABLA`.
- `scripts/discover_and_promote_multitabla_mappings.py`: combined mapping workflow.
- `scripts/review_candidate_relationships.py`: review blocked join candidates.
- `scripts/review_ambiguity_learning.py`: review learned ambiguity suggestions.
- `scripts/check_oracle_connection.py`: Oracle connectivity diagnostic.
- `scripts/check_openrouter_connection.py`: OpenRouter connectivity diagnostic.
- `scripts/oracle_catalog_smoke_test.py`: non-business-data smoke test.
- `scripts/evaluate_text_to_sql.py`: governed dry-run evaluation runner.
- `scripts/manual_query_debug.py`: richest manual inspection tool for the whole pipeline.
- `scripts/project_readiness_check.py`: environment/readiness diagnostic.
- `scripts/show_all_project_info.py`: standardized recovery summary for new Codex chats.
- `scripts/onboard_tables.py`: onboarding helper for tables into metadata workflows.

## Tests
- `backend/pytest.ini`: pytest root configuration.
- `tests/conftest.py`: shared fixtures.
- `tests/test_query_endpoint.py`: end-to-end API behavior in dry-run and guarded modes.
- `tests/test_sql_validator.py`: validator safety and structure checks.
- `tests/test_context_selector.py`: context selection behavior.
- `tests/test_intent_enhancer*.py`: intent enrichment and clarification behavior.
- `tests/test_conversation_state.py`: pending clarification state handling.
- `tests/test_show_all_project_info.py`: recovery script smoke test.
- `tests/test_*`: broad module and script coverage across the repository.

## Existing Legacy Docs
- `docs/architecture.md`
- `docs/system_context.md`
- `docs/text_to_sql_flow.md`
- `docs/database_integration.md`
- `docs/security.md`
- `docs/semantic_catalog.md`
- `docs/codex_working_rules.md`
- `docs/changelog.md`
- `docs/current_state.md`
- `docs/file_index.md`
- `docs/changelog_recovered.md`

The recovery docs added here are intended to coexist with the earlier shorter notes.
