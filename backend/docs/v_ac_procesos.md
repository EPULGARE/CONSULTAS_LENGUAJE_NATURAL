# Acciones individuales de procesos

Incorporacion solicitada por el usuario el 2026-09-21.

- Oracle confirma `SAC.V_AC_PROCESOS` como vista con 25 columnas, sin PK ni FK declaradas detectadas.
- La inspeccion original se conserva en `metadata/generated/v_ac_procesos.yml`.
- La revision en `metadata/approvals/v_ac_procesos_review.yml` aprueba las cinco columnas del SQL aportado: `NUMERO_PROCESO`, `USER_SISTEMA`, `FECHA_SISTEMA`, `D_ACCION` y `ESTADO`. Las otras 20 quedan pendientes de revision de negocio.
- La tabla se incorporo mediante `promote_oracle_catalog.py --require-approval`. Las descripciones se aplican mediante `curated/business_overrides.yml`.
- La relacion manual aprobada une `SAC.V_AC_PROCESOS.NUMERO_PROCESO` con `SAC.PROCESOS.NUMERO_PROCESO`. Su evidencia es el SQL y la confirmacion explicita del usuario; no se presenta como FK de Oracle. Se conserva en la revision y se incorpora en `manual_relationships` del archivo de overrides.
- `USER_SISTEMA` identifica al trabajador que termino la accion, segun la definicion del usuario. No sustituirlo por el cliente ni por el responsable asignado.
- El usuario confirmo que las acciones cerradas tienen `ESTADO = 'F'` y que su periodo se filtra por `FECHA_SISTEMA`. Para 2026 se utiliza el intervalo `>= DATE '2026-01-01' AND < DATE '2027-01-01'`. La vista inspeccionada no contiene `FECHA_FIN`.
- El estado F se aplica cuando se solicitan acciones cerradas. El texto `Respuesta`, los trabajadores y los codigos de proceso son filtros del ejemplo, no filtros obligatorios de la vista.
- Para contar acciones se usa `COUNT(*)`; `COUNT(DISTINCT NUMERO_PROCESO)` contaria procesos. La expresion "cerradas por los usuarios" identifica trabajadores y no implica agrupar; "por mes" o "por usuario" si puede solicitar agrupacion.
- Puede haber varias acciones por proceso. Para contar procesos en una union con acciones, considerar `COUNT(DISTINCT pr.NUMERO_PROCESO)`.
- El SQL de `examples/acciones_procesos.sql` conserva el `GROUP BY` original: agrupa combinaciones iguales, no cuenta acciones ni devuelve necesariamente cada accion individual.

El contexto de tablas y relaciones se regenera con `py scripts/build_context_from_catalog.py --overwrite`. La incorporacion no habilita ejecucion de consultas ni ejecuta el SQL de negocio aportado.
