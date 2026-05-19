# Seguridad

## Reglas SQL
- Solo `SELECT`.
- Una sola sentencia.
- Bloqueo de `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `MERGE`, `EXEC`, `CALL`.
- Bloqueo de `UNION` por defecto.
- Bloqueo de `SELECT` sin `FROM` por defecto.
- Solo tablas del catalogo permitido.

## Gobernanza de metadata
- Ninguna tabla se aprueba automaticamente.
- Approval gate formal antes de promocion recomendada a catalogo principal.
- Tablas `allowed_for_query=false` se excluyen del retriever.
- Columnas `sensitive=true` se bloquean por defecto.
- Columnas `allowed_for_select=false` se excluyen del contexto y seleccion.
