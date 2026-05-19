# Changelog

## 2026-05-12
- Fase 2.5: approval gate formal previo a promocion (`review_oracle_catalog.py` + `--approval/--require-approval` en `promote_oracle_catalog.py`).
- Validaciones de consistencia entre generated y approval (source_file/tablas/columnas/relaciones).
- Soporte a `allowed_for_select` por columna en loader/retriever.
- Fase 2.6: `discover_multitabla_mappings.py` para descubrir candidatos de mapping desde comentarios Oracle hacia `SAC.MULTITABLA` sin auto-aprobacion y sin cambios al catalogo principal.
