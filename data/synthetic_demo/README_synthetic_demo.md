# MODE=synthetic_demo — manifest

**DATOS SINTÉTICOS — NO SON RESULTADOS REALES.**

Generado: 2026-07-27 · Namespace: `data/synthetic_demo/` (nunca mezclado con `data/processed/` real).

## Archivos

### Legacy seed package kept as reference

- `phase7_source_snapshot_20260727.json` — 9 artículos in-scope (NNGroup + Baymard, únicas fuentes automatizadas reales según 1.1.4) + 8 fuentes out-of-scope con los mismos motivos documentados en el plan real (no son cifras inventadas, son decisiones de gobernanza ya tomadas).
- `phase7_action_drafts_20260727.json` — 9 propuestas de acción:
  - 2 `activa_ganadora` (`checkout_cta_copy`, `cart_abandon_email_timing`)
  - 3 `superseded` (2 sobre `checkout_cta_copy`, 1 sobre `cart_abandon_email_timing`) — todas descartadas **antes de testear**, por la regla anti-obsolescencia de 1.5.1, con `discard_reason` explícito.
  - 2 `pending_test` en la cola priorizada (`exit_intent_discount_popup` score 0.82, `product_page_urgency_badge` score 0.61)
  - 1 `testing_escalated_insufficient_sample` (`free_shipping_threshold_banner`, INT-103)
  - 1 `draft_ready` (`checkout_progress_indicator`, aún sin entrar en la cola)
- `phase6_kpi_status_20260727.json` — 3 registros de test (los únicos proposal_id que llegaron a testearse; los 3 `superseded` nunca generan registro de KPI, por diseño de la regla anti-obsolescencia).

### Canonical synthetic-demo runtime package (2026-07-31 closure pass)

- `synthetic_demo__phase7_source_snapshot_20260727.json`
- `synthetic_demo__phase7_action_drafts_20260727.json`
- `synthetic_demo__phase6_kpi_status_20260727.json`
- `synthetic_demo__phase7_integrated_actions_20260727.json`
- `synthetic_demo__phase7_stat_test_runs.parquet`
- `synthetic_demo__phase7_action_history_log.parquet`

**Motivo del prefijo:** evitar que el aislamiento dependa solo de la carpeta. Desde el cierre de 7.3.1, los artefactos consumibles del modo sintético usan prefijo `synthetic_demo__` además de vivir en `data/synthetic_demo/`.

## Discrepancia real detectada y cómo se resolvió (no oculta)

Al inspeccionar el artefacto real subido (`phase6_kpi_status_20260724.json`) y el `README.md` real del proyecto:

- El plan v12 describe el motor como **"Power Guardrail + Wilson CI + Holm-Bonferroni"**.
- El artefacto real y el README **no coinciden con esa descripción**: el README documenta explícitamente que **Wilson-CI/non-inferiority fue evaluado como alternativa al Power Guardrail y descartado** ("reopened the safety false negative"). No hay ningún paso de Holm-Bonferroni en el código ni en el JSON real.
- El esquema real solo persiste `p_value` y `power_achieved` como campos estadísticos, más un `verdict` plano (`B_wins` en los ejemplos reales).
- El guardrail real es, por diseño, un **framework opt-out-only** (Decision C del README): solo 3 de 8 intervenciones investigadas en Fase 5 tienen guardrail cuantificable con este framework.

**Decisión aplicada aquí:** el JSON sintético de `phase6_kpi_status` replica el esquema real campo a campo (`ab_test_run_id`, `proposal_id`, `intervention_id`, `status`, `deployment_mode`, `primary_kpi`, `guardrail_kpi`, `control/variant_conversion_rate`, `conversion_lift`, `control/variant_opt_out_rate`, `verdict`, `guardrail_breach`, `p_value`, `power_achieved`, `launch_ts`). No se inventan `wilson_ci_*` ni `holm_bonferroni_*`. `guardrail_kpi` se fija a `"opt_out_rate"` en los 3 registros, coherente con el framework opt-out-only real. `verdict: "insufficient_sample"` se usa para el caso escalado, alineado con el verdict canónico real producido por `run_ab_test` cuando no hay potencia/muestra suficiente.

Si el motor real evoluciona a incluir Wilson CI/Holm-Bonferroni de verdad, este manifest queda desactualizado y debe regenerarse — no editar el JSON en silencio.

## Enlace lever_id ↔ KPI

`lever_id` es un concepto de Fase 7 (backlog 1.5.1) y no existe en el esquema real de Fase 6. Por eso **no se añadió `lever_id` a `phase6_kpi_status`**: el enlace entre un draft y su resultado de test se hace por `proposal_id` (clave ya usada en el artefacto real), igual que en el ejemplo real subido. `intervention_id` se reutiliza también, como en el real, para el concepto de catálogo/evidencia (no como sinónimo de `lever_id`).

## Verificación de aislamiento (estado tras el cierre local de 2026-07-31)

Este dataset por sí solo no prueba nada; la confirmación válida vino del código y de ejecución real local:

- `MODE=synthetic_demo` **no** es valor por defecto; el default del resolver es `real`.
- El pipeline real sigue resolviendo por namespace explícito `data/processed/` en modo real; el sintético solo entra cuando el modo se fija deliberadamente a `synthetic_demo`.
- Las vistas 2.1 y 2.2 renderizan un banner fijo y no descartable con el texto `DATOS SINTÉTICOS — NO SON RESULTADOS REALES` cuando consumen el namespace sintético.
- Los artefactos sintéticos canónicos usan prefijo `synthetic_demo__`, de modo que la colisión ya no depende solo del directorio.
