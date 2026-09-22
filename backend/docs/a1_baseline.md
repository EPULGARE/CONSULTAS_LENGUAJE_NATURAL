# A1 — Baseline certificada

Fecha de certificacion: 2026-09-22.

## Estado y evidencia de cierre

A1: COMPLETO para la baseline funcional observada en CI. El commit documental
que contiene esta acta debe pasar tambien el mismo workflow antes de finalizar
la entrega; la evidencia de su SHA exacto se registra en el informe final.

- Rama: `main`.
- Remote: `origin`, https://github.com/EPULGARE/CONSULTAS_LENGUAJE_NATURAL.git.
- SHA funcional final: `aed5615d94b9d61aa5ec5dabe4c807e1412fbd0e`.
- Workflow: `A1 baseline`, `.github/workflows/a1-baseline.yml`, evento `push`.
- [Run 35732751822](https://github.com/EPULGARE/CONSULTAS_LENGUAJE_NATURAL/actions/runs/35732751822): `completed / success` observado.
- [JSON de evaluacion en Actions](https://github.com/EPULGARE/CONSULTAS_LENGUAJE_NATURAL/actions/runs/35732751822/artifacts/10695832408).

| Validacion | Local Windows | CI Linux | Exit / conclusion |
| --- | --- | --- | --- |
| Backend | 319 passed, 2 warnings, 201.74 s | 319 passed, 2 warnings, 31.13 s | 0 / success |
| Frontend | npm ci + npm run build correctos | Ambos pasos correctos | 0 / success |
| Readiness | OK=20/WARNING=0/ERROR=0 | OK=20/WARNING=0/ERROR=0 | 0 / success |
| Text-to-SQL | 5/5, failed=0, skipped=0, JSON generado | 5/5, failed=0, skipped=0, artifact subido | 0 / success |

El SHA final de entrega incluye este commit documental. Para obtenerlo desde
el checkout de cierre: `git log -1 --format=%H -- backend/docs/a1_baseline.md`.
No se inserta el hash de un commit dentro de su propio contenido: hacerlo
cambiaria ese hash. La entrega debe comprobar que dicho SHA coincide con el
`head_sha` del ultimo run verde, y proporcionar ambos valores en el informe final.
El commit funcional anterior se conserva aqui como evidencia inmutable ya observada.

El HEAD de partida era `2f312f1`; el primer commit A1 `e265ba2` incluyo los cambios
previos legitimos y los ajustes locales de A1. Durante el cierre remoto solo se
corrigieron dos assertions de rutas demostradas por CI y se actualizo esta acta,
el changelog y las tareas pendientes. No hubo cambios de aplicacion, metadata,
expectativas de evaluacion, dependencias ni workflow en esta fase.

## Continuacion de cierre — 2026-09-22

El usuario autorizo crear el commit del estado completo, hacer push normal de
`main` a `origin` y verificar Actions para ese SHA. Se incluyen los cambios previos
de acciones/procesos, fechas, limites y exportacion Excel, junto con los 16 archivos
especificos de A1 listados al final de este documento. Son trabajo ya existente,
no funcionalidades incorporadas durante esta fase de cierre. No se fragmenta el
estado que pasa las validaciones.

Quedan fuera `.env`, `.env.local`, entornos virtuales, herramientas locales,
`node_modules`, `.next`, logs y outputs. Se descartan solo contadores/timestamps
generados por tests; `next-env.d.ts` es regenerado por Next durante el build.
Las versiones preexistentes del lockfile se conservan: las adiciones corresponden
a la exportacion Excel previa, sin upgrades durante el cierre.

`OPENROUTER_API_KEY` es necesaria para `TextToSQLEvaluator -> SQLGenerator ->
OpenRouterClient.chat_completion` en cada pregunta aprobada. Los tests usan mocks,
readiness no lee esa clave y el build no llama a OpenRouter. No existe modo offline
en el CLI de evaluacion. Tras autorizacion explicita del usuario para esa
credencial y ese destino, se configuro el secret del repositorio
`EPULGARE/CONSULTAS_LENGUAJE_NATURAL` mediante cifrado con su clave publica (HTTP 201,
consulta de metadata HTTP 200). No se versiona ni se muestra su valor.

Revalidacion local: backend 319 passed, 2 warnings, exit 0; readiness
OK=20/WARNING=0/ERROR=0, exit 0; evaluacion real 5/5, exit 0 y JSON generado.
Frontend: npm ci y npm run build, ambos exit 0 (Next 16.2.7).
El run funcional final paso; el ultimo commit documental tambien debe verificarse en Actions.

La documentacion solicitada esta en `backend/docs/`, no en `docs/` de la raiz.
`decisions.md` no existia y se incorpora para las decisiones de CI y agrupacion.

## Entorno y comandos

- Python 3.12.12, entorno aislado `backend/outputs/a1-venv/`, creado con el
  interprete 3.12 disponible localmente e instalado con
  `python -m pip install -r requirements.txt`. `pip check`: exit 0.
- El comando `python` de Windows apuntaba al alias de Microsoft Store. Los
  comandos backend se ejecutaron con `outputs\a1-venv\Scripts\python.exe`
  desde `backend/`. El `.venv` anterior (Python 3.14, Pydantic 2.13.4) se conserva.
- Node 24.15.0, npm 11.12.1, Next.js 16.2.7 del lockfile existente.
- Overrides de proceso: `QUERY_ALLOW_EXECUTION=false`,
  `QUERY_DRY_RUN_DEFAULT=true`. En la suite final: `OPENROUTER_API_KEY` vacia y
  `CONVERSATION_STORAGE_BACKEND=memory`; la evaluacion usa la configuracion
  OpenRouter local existente y no ejecuta SQL. No se modifico `.env`.
- El frontend final se verifico con `NODE_TLS_REJECT_UNAUTHORIZED=1` como
  override de proceso. No se cambio la configuracion global del equipo.

| Validacion | Comando desde su directorio | Resultado | Exit |
| --- | --- | --- | --- |
| Backend | `python -m pytest -q tests` | 319 passed, 2 warnings, 201.74 s; tras corregir las dos assertions de CI | 0 |
| Frontend | `npm ci` y `npm run build` | Instalacion limpia y compilacion/TypeScript correctas | 0 / 0 |
| Readiness | `python -m scripts.project_readiness_check` | OK=20, WARNING=0, ERROR=0; tambien con valores ficticios de CI | 0 |
| Text-to-SQL | `python -m scripts.evaluate_text_to_sql --questions metadata/evaluation/questions.yml --output outputs/text_to_sql_evaluation.json --fail-on-error` | 5/5, failed=0, skipped=0, pass_rate=100 | 0 |

El reporte real esta en `backend/outputs/text_to_sql_evaluation.json`, ignorado
por Git segun la politica existente. No se filtran dominios ni preguntas.

## Fallos reproducidos y correcciones

1. Suite inicial: 308 passed, 6 failed, tanto con el entorno previo como con
   Python 3.12 y dependencias declaradas. Dos fallos del selector se debian a que
   consideraba solo palabras de la pregunta y omitia el lookup requerido por
   valores ya resueltos. Se incluyen esos valores al enriquecer las tablas, solo
   cuando coinciden con un mapping aprobado. Verificados por las pruebas
   existentes de `test_local_only_table_selection.py`, sin cambiar sus assertions.
2. El normalizador retornaba al encontrar la primera columna numerica explicita
   y perdia `CLASE_SERVICIO <> 90` cuando aparecia junto a `MEDIDA_TENSION = 3`.
   Se recorren las demas reglas tras resolver cada columna. La prueba existente
   de `test_numeric_entity_resolution.py` reproduce y verifica el fallo.
3. Dos tests de endpoint asumian el antiguo limite por defecto de 500 filas.
   Ahora fijan explicitamente 0 y 500 y comparan todo el SQL esperado, manteniendo
   las comprobaciones de dry-run y de ausencia de ejecucion.
4. Un test esperaba una frase antigua sobre MUNICIPIO. Se comprueba la frase
   vigente que prohibe comparar texto con codigos numericos, conservando las
   assertions SQL originales.
5. Trece temporales en cuatro archivos de tests dependian de `C:/tmp`. Se usa el
   directorio temporal del sistema para soportar el runner Linux, conservando
   contenido, limpieza y assertions. Se reprodujo el fallo de `mkdtemp` cuando
   el directorio padre fijo no existe.
6. La evaluacion inicial dio 2/5: estrato, tipo de servicio y estado de facturacion
   usaban descripciones de MULTITABLA en vez de codigos. El usuario confirmo
   agrupar por codigo salvo descripcion explicita. Se aclararon las reglas
   contradictorias del prompt y se preservo la agrupacion geografica por nombre
   de municipio. Tres pruebas de prompt fallaron antes del cambio y pasan despues;
   la evaluacion real completa verifica SQL y expectativas originales (5/5).
7. El sandbox impidio recorrer un temporal antiguo de pytest y acceder a la cache
   de npm (`ENOTCACHED`). Las ejecuciones autorizadas fuera del sandbox resolvieron
   esas restricciones, sin excluir pruebas ni modificar codigo para ocultarlas.

## CI configurado

`.github/workflows/a1-baseline.yml` reproduce las cuatro validaciones en
`pull_request`, `push` a `main` y ejecucion manual. Se verificaron YAML, triggers,
comandos, propagacion de errores y artifact. Los jobs usan Python 3.12 y Node 24;
no hay `continue-on-error`. Ver `decisions.md` para detalles.

La evaluacion necesita el secret `OPENROUTER_API_KEY` en GitHub. El secret fue configurado y verificado el 2026-09-22 con autorizacion explicita. Los PRs de forks
sin secrets fallaran la evaluacion en vez de omitirla. El readiness es una
comprobacion estatica, no una prueba de conexion Oracle.

El HEAD inicial `2f312f1` no tenia runs. El cierre funcional se observo en el
run 35732751822 indicado arriba; no se usa un run anterior para certificar cambios posteriores.

## Primer CI remoto y correccion de portabilidad

El commit `e265ba2aa74a752471da2cd60053fe146c4199e0` fue enviado por push normal
a `origin/main`. [Run 35731615088](https://github.com/EPULGARE/CONSULTAS_LENGUAJE_NATURAL/actions/runs/35731615088)
fallo exclusivamente en dos assertions de rutas: `test_evaluate_text_to_sql.py:247`
y `test_manual_query_debug.py:22` exigian el separador de Windows. Resultado:
317 passed, 2 failed; readiness OK=20/WARNING=0/ERROR=0, frontend correcto y
Text-to-SQL 5/5 con artifact generado. El runner usa Python 3.12.14; local, 3.12.12.

Se reprodujo la diferencia con PurePosixPath y PureWindowsPath. La correccion
compara los dos componentes finales de Path (outputs y nombre exacto del JSON),
sin cambiar la implementacion, eliminar tests ni debilitar el control de salida.
Son los unicos dos archivos de tests adicionales modificados durante este cierre.

## Control de cambios

Los cambios A1 se limitan a tres archivos de aplicacion (selector, normalizador y
prompt), seis archivos de tests, el workflow y documentacion. No se cambian
dependencias, metadata gobernada, preguntas de evaluacion ni politica de ejecucion.
Los cambios funcionales previos del usuario se conservan. Los efectos de las
pruebas sobre sugerencias generadas y del build sobre `next-env.d.ts` se restauran
a su estado anterior, sin descartar trabajo previo.

Los hallazgos de seguridad de npm se registran por separado en
`pending_tasks.md`; no forman parte de una certificacion de seguridad ni se
resuelven mediante upgrades fuera del alcance.

## Archivos de A1 (rutas desde la raiz del repositorio)

| Archivo | Motivo |
| --- | --- |
| `.github/workflows/a1-baseline.yml` | Automatizar las cuatro validaciones y conservar el informe |
| `backend/app/context_selector/selector.py` | Conservar lookups requeridos por resoluciones gobernadas |
| `backend/app/semantic_normalization/normalizer.py` | Conservar todos los filtros numericos explicitos |
| `backend/app/llm/prompts.py` | Corregir la politica de agrupacion confirmada por el usuario |
| `backend/tests/test_query_endpoint.py` | Comprobar limites 0/500 con configuracion explicita |
| `backend/tests/test_sql_generator.py` | Regresion del prompt y assertion vigente de MUNICIPIO |
| `backend/tests/test_build_approved_lookup_values.py` | Temporales portables |
| `backend/tests/test_intent_enhancer.py` | Temporales portables |
| `backend/tests/test_numeric_entity_resolution.py` | Temporales portables |
| `backend/tests/test_semantic_normalization.py` | Temporales portables |
| `backend/docs/a1_baseline.md` | Evidencia de certificacion y limites del cierre |
| `backend/docs/changelog.md` | Registrar A1 sin borrar entradas previas |
| `backend/docs/pending_tasks.md` | Separar cierre remoto y hallazgos fuera de alcance |
| `backend/docs/decisions.md` | Documentar runtimes, CI y decision semantica |
| `backend/docs/architecture.md` | Documentar la validacion automatizada |
| `backend/docs/system_context.md` | Corregir ubicacion de frontend/documentacion/CI |
