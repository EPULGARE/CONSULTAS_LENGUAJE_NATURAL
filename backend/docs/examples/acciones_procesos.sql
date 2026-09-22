-- Consulta aportada por el usuario el 2026-09-21; no ejecutada durante la incorporacion.
-- GROUP BY agrupa combinaciones iguales: no cuenta acciones ni garantiza una fila por accion.
SELECT
    TO_CHAR(TRUNC(ac.fecha_sistema, 'MM'), 'YYYY-MM') AS periodo,
    ac.user_sistema,
    pr.numero_proceso,
    pr.proceso,
    ac.d_accion
FROM sac.procesos pr
INNER JOIN sac.v_ac_procesos ac
    ON ac.numero_proceso = pr.numero_proceso
WHERE ac.user_sistema IN (
    'JRINCONL', 'EDEQ\JRINCONL',
    'GGONZAB', 'EDEQ\GGONZAB',
    'AOSPINMA', 'EDEQ\AOSPINMA'
)
AND ac.estado = 'F'
AND ac.d_accion LIKE '%Respuesta%'
AND pr.proceso IN (
    '1006', '1027', '1029', '1128', '1115', '1105', '1172',
    '1102', '1193', '1178', '1129', '1147', '1168', '1160',
    '1171', '1214', '1225', '1219', '1212', '1204', '1206',
    '1227', '1302', '1802', '4111', '4112'
)
GROUP BY
    TRUNC(ac.fecha_sistema, 'MM'),
    ac.user_sistema,
    pr.numero_proceso,
    pr.proceso,
    ac.d_accion
ORDER BY
    TRUNC(ac.fecha_sistema, 'MM'),
    ac.user_sistema;
