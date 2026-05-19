# Catalogo Semantico

## Principio
El sistema no inventa metadata.

## Fuente autorizada
- Introspeccion Oracle real.
- Curaduria manual del usuario.

## Estructura
- `metadata/generated/`: propuestas generadas por introspeccion.
- `metadata/approvals/`: archivos de revision/aprobacion formal.
- `metadata/curated/business_overrides.yml`: overrides opcionales de negocio.
- `metadata/tables.yml`, `metadata/relationships.yml`, `metadata/domains.yml`, `metadata/business_terms.yml`: catalogo principal.

## Approval Gate
1. Inspeccionar Oracle:
`py scripts/inspect_oracle_schema.py --schema <ESQUEMA_REAL> --tables <TABLAS_REALES> --output metadata/generated/<archivo>.yml`
2. Crear review:
`py scripts/review_oracle_catalog.py --input metadata/generated/<archivo>.yml --output metadata/approvals/<archivo_review>.yml`
3. Editar approval manualmente (approved/allowed_for_query/sensitive/allowed_for_select).
4. Promover con approval:
`py scripts/promote_oracle_catalog.py --input metadata/generated/<archivo>.yml --approval metadata/approvals/<archivo_review>.yml --domain <DOMINIO> --promote-tables --promote-relationships --require-approval --overwrite`

Sin approval, el script de promocion muestra warning fuerte.
