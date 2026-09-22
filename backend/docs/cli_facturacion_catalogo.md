# SAC.CLI_FACTURACION en el catalogo A2

La solicitud explicita del usuario de incorporar CLI_FACTURACION autoriza esta
ampliacion del catalogo y reemplaza la restriccion anterior de solo inspeccion.
No se modifican codigo, credenciales ni opciones de ejecucion de consultas.

## Evidencia y semantica

Una fila es una cabecera de facturacion del NIU/cuenta. La PK Oracle
C_CLIFAC_CLID_CNS_PK (CLIENTE_ID, CONSECUTIVO) esta ENABLED y VALIDATED.
El ultimo perfil obtuvo 44.663.876 filas, 301.119 cuentas, 332 consecutivos y
44.663.876 pares distintos; cero pares repetidos.

La FK del detalle C_CLIFACDET_CLIFAC_FK esta ENABLED, NOT VALIDATED y relaciona
CLIENTE_ID y CONSECUTIVO con las mismas columnas de la cabecera. La comprobacion
agregada anterior encontro 193.123.662 detalles con una sola cabecera, cero
huerfanos, cero ambiguedades y cobertura 100 %. La relacion cabecera a detalle
es 1:N. CONS_NRO_FAC no sustituye esa clave.

CLI_FACTURAS almacena registros tecnicos de spool y mapeo; no es esta cabecera.
No se promueve ninguna relacion nueva con CLI_FACTURAS.

## Incorporacion y restricciones

- Extraccion: metadata/generated/cli_facturacion.yml, basada en los SELECT de
  metadata Oracle ya revisados. Conserva tipos, nullability, comentarios y claves.
- Revision: metadata/approvals/cli_facturacion_review.yml; aprobacion explicita
  del usuario, con revision tecnica y restricciones por columna.
- Promocion mediante promote_oracle_catalog.py con --require-approval, primero
  dry-run y luego --overwrite. Dominio facturas, 49 columnas inventariadas.
- Curacion en business_overrides.yml, comentarios Oracle y vocabulario del dominio.
- Contexto regenerado con build_context_from_catalog.py --overwrite.
- NIT y NIT_TMP son sensibles y no seleccionables. NUMERO_FACTURA_CAR y
  CONDICION_ESPECIAL no son seleccionables: SIN EVIDENCIA SUFICIENTE.
- Las fechas NUMBER(8,0) mantienen su tipo numerico; no se presupone su codificacion.
- La FK simple CLIENTE_ID a CLIENTES.CLIENTE_ID se incorpora con su estado Oracle
  ENABLED, NOT VALIDATED. No se afirma cobertura historica medida para esa FK.

## Relacion compuesta pendiente de soporte

La relacion con CLI_FAC_DETALLE esta confirmada en Oracle, pero no esta habilitada
en las relaciones ejecutables del catalogo. RelationshipMetadata representa
una pareja de columnas y el validador acepta cada pareja por separado. Promover
dos parejas independientes permitiria un join incompleto. fixed_filter tampoco
impone esta condicion compuesta en el detector de relaciones.

Antes de activar esa union se requiere soporte de clave compuesta en modelo,
promocion, contexto, seleccion y validacion, con pruebas que exijan ambas
igualdades en el mismo join. Esta incorporacion no cambia codigo para ampliar
ese soporte. La clave y la evidencia quedan documentadas en generated, en la
descripcion de la tabla y en esta nota; no se registran dos joins simples.

## Verificacion local

Se verifican carga, aprobacion/promocion idempotente, contexto regenerable,
seleccion local de la cabecera, SELECT de cabeceras sin Oracle y bloqueo de
columnas restringidas y relaciones directas no aprobadas. Se ejecutan las pruebas
existentes de catalogo, promocion, contexto, relaciones y validador SQL, junto
con project_readiness_check.py. No se ejecutan consultas de negocio ni servicios
LLM para esta incorporacion.

Resultado: 84 pruebas aprobadas en la seleccion de nueve modulos; las dos
restantes fallaron inicialmente en la creacion de temporales, antes de ejecutar
sus assertions. Ambas pasaron con un fixture tmp_path en memoria que crea una
carpeta unica en tests/_tmp con permisos heredados (mode=0777), deshabilitando
solo el plugin tmpdir. No se modificaron los tests ni sus assertions. Total:
86 pruebas aprobadas. La repeticion de las dos pruebas uso outputs/a1-venv
(Python 3.12). git diff --check no reporta errores.

La comprobacion especifica de esta tabla paso: 49 columnas, 45 seleccionables,
seleccion local de cabeceras, SELECT de cabeceras y join con CLIENTES validos,
cuatro columnas restringidas, rechazo de joins directos al detalle (parciales
y completo aun no habilitado), contexto reproducible y promocion idempotente.
Readiness: OK=20, WARNING=0, ERROR=0 usando QUERY_ALLOW_EXECUTION=false y
QUERY_DRY_RUN_DEFAULT=true solo en el proceso de verificacion. La configuracion
persistente preexistente no se modifico; el resultado no certifica sus valores
de ejecucion fuera de ese proceso.
