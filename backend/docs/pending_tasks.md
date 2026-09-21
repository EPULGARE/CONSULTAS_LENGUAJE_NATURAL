# Pending Tasks

## Execution Readiness
- Basic real Oracle execution through `/query` was validated locally with temporary process-only overrides.
- Broader real Oracle execution validation remains pending for more domains, filters, joins, parametric mappings and larger result shapes.
- Keep `QUERY_ALLOW_EXECUTION=false` until the Oracle execution validation phase is explicitly approved.
- Keep the frontend on preview mode until execution UX, audit review and result pagination are approved.

## Frontend MVP
- Row limits and pagination for the UI remain pending.
- UI error hardening remains pending, especially richer rendering for backend validation errors and unavailable backend states.
- Result-table behavior with real Oracle rows in the UI has basic support through `Ejecutar consulta`, but broader UX validation remains pending.
- Add an operator-facing environment/status indicator before considering execution mode for non-local users.
- Add stronger confirmation and audit review UX before exposing execution mode beyond controlled local validation.
- Prepare demo feedback notes after the first internal walkthrough.

## Operations
- Review old recovered/corrupt conversation-state SQLite files under `backend/data/` when the local environment is stable.
- Decide whether local development should default to SQLite or memory for conversation state after more repeated preview sessions.
- Define an approved runbook for temporary execution validation before any non-demo use.
