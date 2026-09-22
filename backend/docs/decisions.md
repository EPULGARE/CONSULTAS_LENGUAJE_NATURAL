# Decisiones tecnicas

## 2026-09-21 — Certificacion A1 en GitHub Actions

- `.github/workflows/a1-baseline.yml` ejecuta pruebas/readiness, build frontend y evaluacion en tres jobs independientes para `pull_request`, `push` a `main` y ejecucion manual. Un fallo conserva el estado fallido del workflow; no se usa `continue-on-error`.
- Python 3.12 instala las versiones de `backend/requirements.txt`. El entorno local anterior usa Python 3.14 y dependencias distintas; no se utiliza como evidencia de instalacion reproducible. Node 24 utiliza el lockfile existente mediante `npm ci`.
- Readiness recibe configuracion Oracle ficticia y un `.env` vacio en el runner. El script comprueba estructura/configuracion; no certifica conectividad ni credenciales Oracle. La ejecucion SQL permanece deshabilitada.
- La evaluacion usa el script existente, las cinco preguntas gobernadas completas y `--fail-on-error`. No se reemplaza el LLM por respuestas prefabricadas ni se modifican expectativas para obtener verde. Se conserva el JSON como artifact durante siete dias, incluso si hay casos fallidos.
- OpenRouter requiere el secret de repositorio `OPENROUTER_API_KEY`; los modelos se fijan a `google/gemini-2.5-flash`, como en `.env.example`. No se copia la configuracion privada local a GitHub. Un PR de fork sin acceso a secrets fallara la evaluacion: no se usa `pull_request_target` para ejecutar codigo del PR con secretos.

Referencias de las acciones: [setup-python](https://github.com/actions/setup-python), [setup-node](https://github.com/actions/setup-node), [upload-artifact](https://github.com/actions/upload-artifact).

## 2026-09-21 — Agrupaciones por campos parametrizados

La evaluacion existente fallo en estrato, tipo de servicio y estado de facturacion:
exige codigo base y prohibe MULTITABLA, mientras el prompt favorecia descripciones.
El usuario confirmo durante A1 agrupar por codigo cuando no se solicita descripcion
explicitamente. Se corrige solo esa politica del prompt; se conservan metadata,
preguntas, assertions de evaluacion y mappings aprobados. Las solicitudes explicitas
de descripcion mantienen el lookup aprobado.
