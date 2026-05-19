# Integracion de Base de Datos

## Oracle
Variables requeridas:
- `DB_DIALECT=oracle`
- `DB_HOST`
- `DB_PORT`
- `DB_SERVICE_NAME`
- `DB_USER`
- `DB_PASSWORD`

## Flujo controlado de metadata
1. `inspect_oracle_schema.py` -> `metadata/generated/`.
2. `review_oracle_catalog.py` -> `metadata/approvals/`.
3. Edicion manual del approval.
4. `promote_oracle_catalog.py` con `--approval --require-approval`.

Comandos:
- `py scripts/review_oracle_catalog.py --input metadata/generated/<archivo>.yml --output metadata/approvals/<archivo_review>.yml`
- `py scripts/promote_oracle_catalog.py --input metadata/generated/<archivo>.yml --approval metadata/approvals/<archivo_review>.yml --domain <DOMINIO> --promote-tables --promote-relationships --require-approval --overwrite`
