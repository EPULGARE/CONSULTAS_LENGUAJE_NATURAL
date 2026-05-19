# Reglas de Trabajo Codex

- Mantener modularidad por capas.
- Priorizar seguridad y principio read-only.
- Evitar acoplar logica a una sola tabla o dominio.
- Toda consulta debe pasar por validador SQL local antes de ejecutarse.
- Validar readiness del catalogo antes de invocar LLM.
- Usar approval gate para promocion de metadata productiva.
- No registrar secretos en logs ni auditoria.
- No inventar metadata (schemas, tablas, columnas, relaciones, dominios, synonyms o business terms).
