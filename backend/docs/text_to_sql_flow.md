# Flujo Text-to-SQL

1. Ejecutar bootstrap guiado de metadata real:
   `py scripts/bootstrap_real_catalog.py --schema <ESQUEMA_REAL> --tables <TABLA1,TABLA2> --domain <DOMINIO_REAL> --generated-output metadata/generated/<archivo>.yml --approval-output metadata/approvals/<archivo_review>.yml`
2. Ejecutar introspeccion segura Oracle para generar propuesta:
   `py scripts/inspect_oracle_schema.py --schema <ESQUEMA_REAL> --tables <TABLAS_REALES> --output metadata/generated/<archivo>.yml`
3. Revisar manualmente `metadata/generated/<archivo>.yml`.
4. Generar archivo de review:
   `py scripts/review_oracle_catalog.py --input metadata/generated/<archivo>.yml --output metadata/approvals/<archivo_review>.yml`
5. Opcional: crear `metadata/curated/business_overrides.yml`.
6. Ejecutar promocion en simulacion con approval gate:
   `py scripts/promote_oracle_catalog.py --input metadata/generated/<archivo>.yml --approval metadata/approvals/<archivo_review>.yml --require-approval --domain <DOMINIO> --promote-tables --promote-relationships --dry-run`
7. Ejecutar promocion efectiva con approval gate:
   `py scripts/promote_oracle_catalog.py --input metadata/generated/<archivo>.yml --approval metadata/approvals/<archivo_review>.yml --require-approval --domain <DOMINIO> --promote-tables --promote-relationships --overwrite`
8. Ejecutar smoke test Oracle sin datos de negocio:
   `py scripts/oracle_catalog_smoke_test.py --max-tables 20`
9. Ejecutar `POST /query` en dry-run para revisar dominio, metadata recuperada y SQL final sin ejecutar Oracle.
10. Revisar SQL validado (`validated_sql`) antes de habilitar ejecucion.
11. Habilitar ejecucion real solo con `QUERY_ALLOW_EXECUTION=true` y `dry_run=false`.
12. `POST /query/preview` siempre opera en dry-run.
13. Si el catalogo no esta listo, bloquea con: `Semantic catalog is not ready for query generation.`
14. Ejecutar evaluacion gobernada con preguntas `approved=true`:
   `py scripts/evaluate_text_to_sql.py --questions metadata/evaluation/questions.yml --output outputs/text_to_sql_evaluation.json`
15. Revisar `pass_rate` y `failures` antes de cambiar prompts/modelos.
