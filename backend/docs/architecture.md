# Arquitectura

## Modulos
- `app/api`: endpoints.
- `app/llm`: clasificacion y generacion SQL.
- `app/semantic_catalog`: carga/retrieval de metadata.
- `app/sql`: dialectos, validador AST y executor.
- `app/audit`: trazabilidad por consulta.

## Principios
- Separacion de responsabilidades.
- Validacion local antes de ejecucion.
- Contexto minimo al LLM usando solo metadata relevante.
