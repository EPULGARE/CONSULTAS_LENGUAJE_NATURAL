# Pending Tasks

## A1 ? Completado; evidencia funcional remota observada 2026-09-22
- [x] Backend: 319 passed, exit 0, tanto local como CI.
- [x] Frontend: npm ci y npm run build, exit 0 local y CI.
- [x] Readiness: OK=20/WARNING=0/ERROR=0, exit 0 local y CI.
- [x] Text-to-SQL real: 5/5, cero fallos/omisiones, JSON local y artifact remoto.
- [x] Secret OPENROUTER_API_KEY configurado con autorizacion explicita.
- [x] Commit funcional `aed5615d94b9d61aa5ec5dabe4c807e1412fbd0e` enviado a main; [CI verde](https://github.com/EPULGARE/CONSULTAS_LENGUAJE_NATURAL/actions/runs/35732751822).
- La entrega final verifica tambien el SHA del commit documental que contiene este cierre. Ver `docs/a1_baseline.md` y el informe final con su run exacto.
- Se preservaron los cambios previos del usuario. Las unicas correcciones remotas fueron dos assertions de separadores Windows/Linux.

## Hallazgos fuera de A1 — 2026-09-21
- `npm ci` y `npm audit --json` reportaron 7 paquetes vulnerables: 1 critico (`next`), 3 altos (`nanoid`, `postcss`, `sharp`) y 3 moderados (`baseline-browser-mapping`, `exceljs`, `uuid`). Revisar aplicabilidad y actualizar en una tarea de seguridad separada. El build no requiere upgrades; no se ejecuto `npm audit fix` ni se cambio el lockfile durante A1.
- El entorno local hereda `NODE_TLS_REJECT_UNAUTHORIZED=0`. Revisar su configuracion global fuera de A1; la repeticion final de npm se lanzo con valor `1` solo para ese proceso. El workflow no desactiva TLS.
- Las versiones de Python/Pydantic del `.venv` preexistente difieren de `requirements.txt`. Para A1 se creo un entorno aislado Python 3.12 con las dependencias declaradas; no se altero el entorno anterior.

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
