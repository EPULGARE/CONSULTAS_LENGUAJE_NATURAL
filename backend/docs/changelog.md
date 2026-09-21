# Changelog

## 2026-06-02
- Se agrego `README.md` de ejecucion del MVP web y `docs/demo_guide.md` para demo interna.
- Se verificaron comandos finales: suite backend focal verde, readiness OK=20/WARNING=0/ERROR=0 y `npm run build` verde.
- El MVP web queda documentado como demo segura reproducible con backend en modo seguro por defecto.
- Se agrego en el frontend un selector entre `Vista previa` y `Ejecutar consulta`.
- Se agrego el proxy Next `/api/query` hacia FastAPI `POST /query`; `/api/query-preview` se mantiene para dry-run forzado.
- La UI ahora muestra una advertencia explicita cuando el backend no ejecuta la consulta e incluye el motivo (`execution_skip_reason`).
- Se valido manualmente que `Ejecutar consulta` no ejecuta si el backend esta en modo seguro y que si ejecuta solo cuando el backend se levanta temporalmente con ejecucion permitida.
- Se valido temporalmente `/query` con `QUERY_ALLOW_EXECUTION=true` y `QUERY_DRY_RUN_DEFAULT=false` solo a nivel de proceso local.
- La ejecucion real controlada contra Oracle devolvio filas para una consulta agregada simple, manteniendo SQL validado y limite `FETCH FIRST 500 ROWS ONLY`.
- Se confirmo que `/query/preview` sigue forzando dry-run aunque el proceso permita ejecucion.
- Tras la prueba se restauro el backend a la configuracion segura de `.env` con `QUERY_ALLOW_EXECUTION=false`.
- Se estabilizo `SQLiteConversationStorage` para desarrollo local: usa journaling en memoria y recupera archivos corruptos creando una base alterna si el archivo original no puede ponerse en cuarentena.
- Se corrigio el test de aclaracion/cardinalidad para declarar explicitamente las relaciones aprobadas que el SQL esperado usa.
- La suite focal `test_query_endpoint`, `test_sql_validator` y `test_oracle_executor` quedo verde en modo seguro con `QUERY_ALLOW_EXECUTION=false`.
- Se agrego `frontend/` como MVP web local con Next.js, React y TypeScript.
- El frontend ofrece una pantalla unica tipo chat y consume el backend existente mediante `POST /query/preview`.
- Se agrego proxy interno de Next en `/api/query-preview` para evitar depender de CORS sin modificar FastAPI.
- La UI muestra SQL validado, resultados tabulares, `row_count`, tablas recuperadas, warnings, estado dry-run y trazabilidad basica.
- Se mantiene intacto el pipeline Text-to-SQL, incluyendo generador SQL, validador, metadata y reglas de gobernanza.

## 2026-05-12
- Fase 2.5: approval gate formal previo a promocion (`review_oracle_catalog.py` + `--approval/--require-approval` en `promote_oracle_catalog.py`).
- Validaciones de consistencia entre generated y approval (source_file/tablas/columnas/relaciones).
- Soporte a `allowed_for_select` por columna en loader/retriever.
- Fase 2.6: `discover_multitabla_mappings.py` para descubrir candidatos de mapping desde comentarios Oracle hacia `SAC.MULTITABLA` sin auto-aprobacion y sin cambios al catalogo principal.
