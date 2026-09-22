# Changelog

## 2026-09-21
- A1: cierre local de certificacion; cierre integral pendiente de CI remoto sobre el commit final. Baseline del estado de trabajo basada en HEAD `2f312f1`, con cambios previos del usuario conservados. Evidencia y comandos en `docs/a1_baseline.md`.
- Se corrigieron la omision de lookups gobernados ya resueltos en el selector y el retorno prematuro que perdia el segundo filtro numerico explicito. Los tests existentes reprodujeron los fallos antes de las correcciones.
- Por decision explicita del usuario, las agrupaciones parametrizadas usan codigo salvo solicitud de descripcion. Se corrigio la contradiccion del prompt, conservando agrupaciones geograficas por nombre, metadata y expectativas Text-to-SQL.
- Se estabilizaron los tests de limites con casos explicitos 0/500, la assertion de la regla vigente de MUNICIPIO y los directorios temporales para Linux. No se eliminaron pruebas ni se relajaron validaciones.
- Se agrego `.github/workflows/a1-baseline.yml` para PRs y pushes a `main`: tests/readiness, `npm ci` + build y evaluacion real con `--fail-on-error`, mas artifact JSON. Python 3.12, Node 24 y secret `OPENROUTER_API_KEY`; sin ejecucion SQL.
- Validacion final local: 319 tests aprobados (exit 0), frontend instalacion/build correctos (exit 0), readiness OK=20/WARNING=0/ERROR=0 (exit 0), evaluacion 5/5 y JSON generado (exit 0). Se reviso el diff y se restauraron efectos accidentales de tests/build.
- `npm audit` reporto siete paquetes vulnerables, registrados fuera de A1 en `docs/pending_tasks.md`; no se actualizaron dependencias ni lockfile.
- El usuario confirmo que SAC.PROCESOS.FECHA_SOL es la fecha de creacion del proceso. Se documento en el catalogo y overrides, incluyendo el filtro de procesos creados hoy, y se regenero el contexto.
- Las sesiones Oracle establecen NLS_DATE_LANGUAGE=SPANISH y los prompts solicitan textos en espanol y fechas nativas. La exportacion Excel escribe fechas ISO como celdas de fecha con formato dia/mes/ano, conservando la hora recibida. Verificados 49 tests de backend, build frontend y lectura del XLSX generado.
- Se desactivo el limite automatico de filas: DB_MAX_ROWS=0 omite FETCH FIRST/LIMIT agregado por el backend. Se conservan limites explicitos de las consultas. Validacion: 49 pruebas, incluida lectura de 750 filas sin truncamiento.
- Se separo el filtro explicito de tipo de proceso (SAC.PROCESOS.TIPO, VARCHAR2) del codigo de proceso (PROCESO). La vista previa de acciones cerradas para procesos tipo 46 genera TIPO = '46'; el validador rechaza sustituirlo por PROCESO.
- Se corrigio la deteccion de agrupacion para distinguir "cerradas por los usuarios" de "por mes". El prompt SQL ahora incluye las descripciones curadas de las columnas.
- El usuario confirmo ESTADO=F y FECHA_SISTEMA para acciones cerradas; se agregaron mapping y ejemplo de conteo de acciones por trabajadores y periodo.
- Se incorporo SAC.V_AC_PROCESOS al dominio procesos tras inspeccion de Oracle: vista con 25 columnas y sin PK/FK declaradas detectadas.
- Se aprobaron las cinco columnas del SQL aportado; las otras 20 quedan pendientes de revision. USER_SISTEMA representa al trabajador que termino la accion.
- Se registro la relacion manual con SAC.PROCESOS por NUMERO_PROCESO, respaldada por la solicitud del usuario, y se regenero el contexto.
- Se documento el alcance en docs/v_ac_procesos.md y se conservo el SQL aportado en docs/examples/acciones_procesos.sql.
- Validacion local: 43 pruebas de catalogo y validador SQL aprobadas, sin ejecutar consultas de negocio.

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
