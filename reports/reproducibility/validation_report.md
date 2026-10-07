# Informe de validación sandbox

## Proyecto
customer-churn-intelligence-system (`customer-churn-intelligence-system`)

## Job
`churn-rerun-readiness-20261003-235655`

## Fecha/hora inicio
No disponible como timestamp exacto histórico. Derivada del `job_id` y logs acumulados.

## Fecha/hora fin
2026-10-04T02:06:39+02:00 (derivada de mtime de artefactos de resultado)

## Duración
No reconstruible con exactitud desde los logs acumulados históricos.

## Modalidad
reproducibility

## Resultado final
PASS

## Resumen humano
- Resultado final: PASS.
- Etapas ejecutadas con PASS: PREBUILD_VALIDATION, GITHUB_CI_PARITY, SNAPSHOT_SECRET_SCAN, BUILD, STARTUP, READINESS, PROJECT_VERIFY, CLEANUP
- Etapas no aplicables: ninguna
- Etapas no alcanzadas: LIVE_LLM_REAL_EXECUTION
- Fallos: ninguno registrado
- Servicios sondeados correctamente: api,web.
- Servicios no sondeados por no declarar healthcheck/contrato: postgres.

## Recursos
Coste API real: 0


## Estados
- PREBUILD_VALIDATION: PASS
- PREBUILD_VALIDATION_MODE: GITHUB_CI_PARITY
- GITHUB_CI_PARITY: PASS
- SNAPSHOT_SECRET_SCAN: PASS
- GIT_HISTORY_SECRET_SCAN: EXTERNAL_GITHUB_ONLY
- BUILD: PASS
- STARTUP: PASS
- READINESS: PASS
- PROJECT_VERIFY: PASS
- CLEANUP: PASS
- VALIDATION_PASS: PASS
- REPRODUCIBILITY: PASS
- LIVE_LLM_VERIFY: NOT_REQUESTED
- LIVE_LLM_REAL_EXECUTION: NOT_REACHED

## Reproducibilidad
- ORIGINAL_SOURCE_REPRODUCIBILITY: NOT_DECLARED. No se declara FAIL sin evidence directo.
- REMEDIATED_WORKSPACE_VALIDATION: NOT_APPLICABLE. No hubo remediacion de workspace.
- CLEAN_SOURCE_REPRODUCIBILITY: PASS
- PROJECT_FIXES_APPLIED: NO
- PATCHSET_RECOMMENDATION: NO

## Readiness por servicio no aplicable
- Ninguno registrado.

## Nota sobre histórico Git
El histórico Git se valida en GitHub CI cuando existe workflow real aplicable. La sandbox local registra `GIT_HISTORY_SECRET_SCAN` como estado separado y no inventa una validación histórica local si no existe evidencia.

## Número de intentos
No reconstruible exactamente.

## Problemas encontrados
- No se registraron fixes de proyecto.

## Qué se corrigió
- No aplica.

## Qué queda pendiente
- PENDING_PROJECT_REMEDIATION: NONE

## Siguiente acción recomendada
Conservar evidencia. No recomendar patchset/promocion si remediation_report no contiene fixes.

## Evidencia previa enlazada
- No enlazado en metadatos históricos.

## Detalle técnico
Ver `logs/`, `attempts/`, `fixes/`, `manifest.json` y `hashes.sha256`.

## Limitaciones reales
- Ninguna limitación crítica adicional.
