# Arquitectura

## Modulos
- `frontend/`: MVP web en Next.js + React + TypeScript.
- `frontend/app/page.tsx`: pantalla unica tipo chat.
- `frontend/app/api/query-preview/route.ts`: proxy local hacia FastAPI `POST /query/preview`.
- `app/api`: endpoints.
- `app/llm`: clasificacion y generacion SQL.
- `app/semantic_catalog`: carga/retrieval de metadata.
- `app/sql`: dialectos, validador AST y executor.
- `app/audit`: trazabilidad por consulta.

## Flujo Web MVP
1. El usuario escribe una pregunta en el chat web.
2. El usuario elige `Vista previa` o `Ejecutar consulta`.
3. En `Vista previa`, el frontend envia la solicitud a `/api/query-preview`.
4. En `Ejecutar consulta`, el frontend envia la solicitud a `/api/query`.
5. Next.js reenvia el payload al backend configurado por `NEXT_PUBLIC_API_BASE_URL`.
6. FastAPI procesa `POST /query/preview` con dry-run forzado o `POST /query` con la politica de ejecucion configurada en backend.
7. La UI muestra SQL validado, resultados si existen, `row_count`, tablas recuperadas, warnings y trazabilidad.
8. Si el backend pide aclaracion, la UI conserva `conversation_id` y envia la respuesta como `clarification_answer`.

## Principios
- Separacion de responsabilidades.
- Validacion local antes de ejecucion.
- Contexto minimo al LLM usando solo metadata relevante.
- El frontend no modifica el pipeline Text-to-SQL ni la gobernanza SQL.
- La ejecucion real depende exclusivamente de la configuracion segura del backend.

## Certificacion A1
El workflow `.github/workflows/a1-baseline.yml`, relativo a la raiz del repositorio,
ejecuta pruebas backend, readiness, instalacion/build frontend y evaluacion Text-to-SQL
en PRs y pushes a `main`. La evaluacion usa OpenRouter en dry-run y publica su informe
JSON; no conecta a Oracle ni ejecuta SQL. Ver `docs/decisions.md` para runtimes,
configuracion segura y dependencia del secret de OpenRouter.
