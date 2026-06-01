# Backend Text-to-SQL Seguro (Oracle)

## Flujo recomendado de metadata
1. `py scripts/inspect_oracle_schema.py --schema <ESQUEMA_REAL> --tables <TABLAS_REALES> --output metadata/generated/<archivo>.yml`
2. `py scripts/review_oracle_catalog.py --input metadata/generated/<archivo>.yml --output metadata/approvals/<archivo_review>.yml`
3. Editar approval manualmente (approved/allowed_for_query/sensitive/allowed_for_select).
4. `py scripts/promote_oracle_catalog.py --input metadata/generated/<archivo>.yml --approval metadata/approvals/<archivo_review>.yml --domain <DOMINIO> --promote-tables --promote-relationships --require-approval --overwrite`

## Regla
El sistema no inventa metadata. No se promueve nada automaticamente.

## Descubrimiento de candidatos MULTITABLA (gobernado)
`py scripts/discover_multitabla_mappings.py --schema SAC --tables MEDIDORES --output metadata/generated/multitabla_mapping_suggestions.yml --overwrite`

Este flujo solo genera sugerencias `approved: false` a partir de comentarios Oracle y contraste contra `SAC.MULTITABLA`. No modifica `business_overrides.yml` ni aprueba mappings automaticamente.

## Recuperar contexto en una nueva sesion de Codex
Cuando se pierda el chat anterior, ejecuta desde `backend/`:

`py -m scripts.show_all_project_info`

Luego pega la salida completa en el nuevo chat de Codex. El comando lee `AGENTS.md` y los documentos de recuperacion en `docs/` para resumir:
- proposito del proyecto
- arquitectura y flujo principal
- modulos y archivos clave
- estado actual, riesgos y TODOs
- comandos utiles
- notas recientes de recuperacion
