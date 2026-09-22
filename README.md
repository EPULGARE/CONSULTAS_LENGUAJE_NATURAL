# Text-to-SQL Oracle SAC - MVP Web

MVP web seguro para consultar el backend gobernado Text-to-SQL Oracle SAC. La aplicacion permite escribir preguntas de negocio en una interfaz tipo chat, revisar el SQL validado, ver trazabilidad basica y, solo si el backend lo permite, ejecutar consultas `SELECT` reales contra Oracle.

## Seguridad por defecto

La configuracion segura esperada en `backend/.env` es:

```powershell
QUERY_ALLOW_EXECUTION=false
QUERY_DRY_RUN_DEFAULT=true
```

Con esa configuracion:
- `POST /query/preview` siempre opera en dry-run.
- `POST /query` valida SQL, pero no ejecuta si `QUERY_ALLOW_EXECUTION=false`.
- La UI no puede saltarse esta seguridad; solo muestra `execution_skipped` y `execution_skip_reason` devueltos por el backend.

## Levantar backend seguro

Desde `backend/`:

```powershell
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Verificar:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/health -UseBasicParsing
```

## Levantar frontend

Desde `frontend/`:

```powershell
npm install
npm run dev
```

Abrir:

```text
http://127.0.0.1:3000
```

El frontend usa `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` por defecto. Para documentar o cambiar la URL local, usar `frontend/.env.local.example` como referencia.

## Usar Vista previa

En la UI, seleccionar `Vista previa`.

Comportamiento:
- llama a `/api/query-preview`
- Next.js reenvia a FastAPI `POST /query/preview`
- el backend fuerza dry-run
- se muestra SQL validado, tablas recuperadas, warnings, `row_count=0`, `rows=[]`, `execution_skipped=true`

## Probar Ejecutar consulta

En la UI, seleccionar `Ejecutar consulta`.

Con backend seguro:
- llama a `/api/query`
- Next.js reenvia a FastAPI `POST /query`
- el backend no ejecuta si `QUERY_ALLOW_EXECUTION=false`
- la UI debe mostrar: `El backend no ejecuto la consulta. Motivo: QUERY_ALLOW_EXECUTION=false`

Para una prueba local controlada de ejecucion real, detener el backend seguro y levantar un proceso temporal:

```powershell
cmd /c "set QUERY_ALLOW_EXECUTION=true&& set QUERY_DRY_RUN_DEFAULT=false&& py -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
```

Advertencia:
- no editar `.env` para habilitar ejecucion permanente
- no guardar credenciales en frontend
- solo ejecutar en entorno local controlado
- `POST /query/preview` debe seguir en dry-run incluso si el proceso temporal permite ejecucion

## Validaciones finales

Backend:

```powershell
cd backend
py -m pytest tests\test_query_endpoint.py tests\test_sql_validator.py tests\test_oracle_executor.py
py -m scripts.project_readiness_check
```

Frontend:

```powershell
cd frontend
npm run build
```

## Descargar resultados en Excel

El limite automatico de filas esta desactivado con `DB_MAX_ROWS=0` en el backend.
Reiniciar el backend despues de cambiar este valor. Los limites pedidos explicitamente
en una consulta, como un top 10, se conservan.

Despues de ejecutar una consulta con resultados, usar `Descargar Excel` sobre la tabla.
La pagina muestra solo las primeras 10 filas; la descarga incluye todas las filas recibidas.
El archivo `.xlsx` incluye las columnas y filas recibidas, encabezados con filtros y
la primera fila fija. Respeta el limite de filas del backend; no ejecuta otra consulta.
Los codigos de texto conservan sus ceros iniciales, y numeros y booleanos conservan su tipo.
Las fechas ISO completas se exportan como fechas reales de Excel, con formato
`dd/mm/yyyy` o `dd/mm/yyyy hh:mm:ss`, para usar filtros de fecha. Se conserva la
hora recibida sin convertirla a la zona horaria del navegador.
Las sesiones Oracle usan espanol para los nombres de dias y meses.
La descarga no se ofrece en vista previa ni cuando el resultado tiene cero filas.

## Documentacion relacionada

- `backend/docs/demo_guide.md`
- `backend/docs/current_state.md`
- `backend/docs/architecture.md`
- `backend/docs/security.md`
- `backend/docs/pending_tasks.md`
