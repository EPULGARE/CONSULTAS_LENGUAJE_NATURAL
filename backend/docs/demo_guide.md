# Demo Guide - MVP Web Text-to-SQL Oracle SAC

## Preparacion

1. Levantar backend seguro:

```powershell
cd backend
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

2. Levantar frontend:

```powershell
cd frontend
npm run dev
```

3. Abrir `http://127.0.0.1:3000`.

## Caso 1: consulta simple en Vista previa

Modo: `Vista previa`

Pregunta sugerida:

```text
cantidad de clientes
```

Esperado:
- SQL validado
- tablas recuperadas
- `execution_skipped=true`
- motivo `dry_run=true` o `QUERY_ALLOW_EXECUTION=false` segun endpoint/configuracion

## Caso 2: consulta con resultados reales

Modo: `Ejecutar consulta`

Requiere backend temporal con:

```text
QUERY_ALLOW_EXECUTION=true
QUERY_DRY_RUN_DEFAULT=false
```

Pregunta sugerida:

```text
cantidad de clientes
```

Esperado:
- SQL validado
- `execution_skipped=false`
- `row_count=1`
- tabla con el conteo devuelto por Oracle

## Caso 3: consulta sin resultados

Modo: `Ejecutar consulta` con backend temporal de ejecucion, o `Vista previa` para revisar SQL sin ejecutar.

Pregunta sugerida:

```text
clientes del municipio inexistente zzz
```

Esperado con ejecucion real:
- SQL validado
- `execution_skipped=false`
- `row_count=0`
- `rows=[]`

## Caso 4: consulta ambigua con aclaracion

Modo: cualquiera

Pregunta sugerida:

```text
usuarios activos
```

Esperado:
- no ejecuta
- `requires_user_confirmation=true`
- muestra una pregunta similar a: `'activos' aplica a clientes o a medidores?`
- responder `clientes` para continuar con mapping gobernado hacia `SAC.MULTITABLA`

## Caso 5: ejecutar con backend seguro

Modo: `Ejecutar consulta`

Backend seguro:

```text
QUERY_ALLOW_EXECUTION=false
QUERY_DRY_RUN_DEFAULT=true
```

Pregunta sugerida:

```text
cantidad de clientes
```

Esperado:
- SQL validado
- `execution_skipped=true`
- `execution_skip_reason=QUERY_ALLOW_EXECUTION=false`
- la UI muestra advertencia visual de que el backend no ejecuto la consulta

## Cierre de demo

Despues de cualquier prueba temporal de ejecucion real:
- detener el backend temporal
- levantar nuevamente el backend con `.env` seguro
- confirmar que `POST /query` vuelve a reportar `QUERY_ALLOW_EXECUTION=false`
