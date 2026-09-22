# Timeline

> Los timestamps exactos por intento no estaban disponibles en los logs históricos. Se usa el mejor timestamp verificable disponible y se marca como derivado.

## churn-clean-source-20260919-091935

- inicio: derivado del job_id/logs; no exacto.
- intento(s): single clean-source lifecycle.
- fallos: ver `validation_report.md` y `remediation_report.md`.
- remediación: ver `fixes/`.
- finalización: 2026-09-19T09:20:34+02:00 (derivada de artefactos de resultado).
- estado final: PASS.

## Política futura preparada

- `attempts/001/`, `attempts/002/`, etc. quedan reservados para nuevos jobs cuando el runner exponga `attempt_id`.
- Para este job histórico se usa `attempts/LEGACY_ACCUMULATED_LOGS.md`.
