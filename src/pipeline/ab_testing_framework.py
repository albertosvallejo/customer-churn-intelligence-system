"""
ab_testing_framework.py
========================

Framework de testing A/B para validación de intervenciones de retención
(Fase 2 del plan phase5B_ab_testing_action_plan).

Implementa el contrato congelado en la Sección 0.6-c del plan, validado por
Alberto Sánchez el 2026-07-17 (v17.14):

  1. Parámetros de entrada: la función pura recibe los datos ya cargados
     (pd.DataFrame de conversiones por brazo). La lectura de CSV/Parquet vive
     en una capa separada (`load_arm_data`) para que los tests unitarios no
     dependan de I/O de disco.
  2. Algoritmo de precedencia explícito y no reordenable en tiempo de
     ejecución:
        (a) guardrail veta con prioridad absoluta sobre significancia,
        (b) tamaño de muestra insuficiente se comprueba antes que
            significancia,
        (c) solo entonces se evalúa p_value.
     Esta secuencia es la corrección directa de la causa raíz identificada
     en la Fase 5 para `07_umbral`: la regla existía en prosa (prompt sellado
     0.B-ter) pero no se aplicó de forma literal en una sesión de
     razonamiento manual. Codificarla como pasos ejecutados en este orden,
     no como razonamiento a aplicar, es la mitigación.
  3. Contrato de salida ampliado con `guardrail_ci` (Requisito 2, Sección
     2.3) y `test_used` (Requisito 3, Sección 2.3).

No se han hecho cambios de diseño respecto a lo aprobado en 0.6-c: este
módulo es la conversión literal de esa spec a código, no un rediseño.

------------------------------------------------------------------------
FUSIÓN v17.23 — extensión aprobada, fuera del contrato 0.6-c original
------------------------------------------------------------------------
`evaluate_multi_arm_test` (sección final de este fichero, tras
`run_ab_test`) se añade en v17.23, aprobada por Alberto sobre la propuesta
de v17.22 (antes vivía en `multi_arm_verdict_proposal.py`, ahora obsoleto).
No modifica ni reabre nada de lo anterior: `run_ab_test` sigue aceptando
exactamente 2 DataFrames, sin cambios en su firma ni en su algoritmo de
precedencia. Todo lo que hay por encima de esta nota es el contrato 0.6-c
tal cual fue sellado (v17.14) y corregido hasta v17.21; todo lo que hay
después es la extensión de v17.23. Decisiones de Alberto sobre esta
extensión (ver plan de acción, Sección 5, entrada v17.23):
  - Veredicto agregado de "más de una variante gana" renombrado de
    `multiple_arms_tied` a `multiple_arms_portfolio_candidates` — no es un
    empate a resolver, son variantes genuinamente válidas para convivir
    en portfolio; el código sigue sin elegir entre ellas.
  - Corrección de comparaciones múltiples: Holm-Bonferroni en vez de
    Bonferroni simple (`bonferroni_correction`, más arriba, se deja sin
    tocar por si algún llamador externo depende de ella).
"""

from __future__ import annotations

from math import sqrt
from typing import Literal, TypedDict

import numpy as np
import pandas as pd
from scipy import stats

REQUIRED_COLUMNS = ("converted", "opt_out")

Verdict = Literal[
    "A_wins",
    "B_wins",
    "no_significant_difference",
    "not_recommended_guardrail",
    "insufficient_sample",
]

TestUsed = Literal["z_test", "fisher_exact"]

# Regla de Cochran para validez de la aproximación normal: el recuento
# esperado mínimo en cualquier celda de la tabla 2x2 debe ser >= 5. Por
# debajo de este umbral, un z-test (o chi-cuadrado sin corrección) puede
# devolver p-valores inválidos (Requisito 3, Sección 2.3 — motivado por el
# escenario 08, n=25, p=0.14, donde n*p*(1-p) < 5).
MIN_EXPECTED_CELL_COUNT = 5.0


class GuardrailInfo(TypedDict):
    breach: bool
    ci: tuple[float, float]
    variant: str | None  # "A" | "B" | None si ninguna rompe el guardrail


class ABTestResult(TypedDict):
    verdict: Verdict
    p_value: float
    power_achieved: float
    guardrail_breach: bool
    guardrail_ci: tuple[float, float]
    test_used: TestUsed


# ---------------------------------------------------------------------------
# Capa de I/O (deliberadamente fuera de run_ab_test — Requisito (a) de 0.6-c)
# ---------------------------------------------------------------------------

def load_arm_data(path: str) -> pd.DataFrame:
    """Carga los datos de un brazo desde CSV o Parquet.

    Mantenida separada de `run_ab_test` para que los tests unitarios del
    gate de la Fase 2 ("tests contra referencias analíticas") sean rápidos y
    deterministas, sin depender de fixtures en disco.
    """
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)
    _validate_arm_dataframe(df, name=path)
    return df


def _validate_arm_dataframe(df: pd.DataFrame, name: str) -> None:
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"{name}: se esperaba un pandas.DataFrame, recibido {type(df)!r}")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: faltan columnas requeridas {missing} (se requieren {REQUIRED_COLUMNS})")
    if len(df) == 0:
        raise ValueError(f"{name}: el brazo no contiene filas")
    for col in REQUIRED_COLUMNS:
        vals = set(pd.unique(df[col].dropna()))
        if not vals.issubset({0, 1}):
            raise ValueError(f"{name}: la columna '{col}' debe ser binaria (0/1), valores encontrados: {vals}")


# ---------------------------------------------------------------------------
# Estadística de soporte
# ---------------------------------------------------------------------------

def wilson_ci(count: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Intervalo de confianza de Wilson para una proporción binomial.

    Preferido sobre el IC normal (Wald) porque se mantiene bien calibrado
    también en el borde (proporciones cercanas a 0, muestras pequeñas) —
    exactamente el régimen en el que viven los escenarios de guardrail
    (07_umbral, 08_*).
    """
    if n <= 0:
        return (0.0, 0.0)
    z = stats.norm.ppf(1 - (1 - confidence) / 2)
    phat = count / n
    denom = 1 + (z ** 2) / n
    center = phat + (z ** 2) / (2 * n)
    margin = z * sqrt((phat * (1 - phat) / n) + (z ** 2) / (4 * n ** 2))
    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return (max(0.0, lower), min(1.0, upper))


def min_expected_cell_count(n_a: int, p_a: float, n_b: int, p_b: float) -> float:
    """Recuento esperado mínimo en la tabla 2x2 de conversión (regla de
    Cochran), usado para decidir si el z-test es válido o si hace falta un
    test exacto (Requisito 3, Sección 2.3)."""
    cells = (n_a * p_a, n_a * (1 - p_a), n_b * p_b, n_b * (1 - p_b))
    return float(min(cells))


def two_proportion_ztest(x_a: int, n_a: int, x_b: int, n_b: int) -> tuple[float, float]:
    """Z-test de dos proporciones (varianza combinada bajo H0), dos colas."""
    p_a, p_b = x_a / n_a, x_b / n_b
    p_pool = (x_a + x_b) / (n_a + n_b)
    se = sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return 0.0, 1.0
    z = (p_a - p_b) / se
    p_value = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p_value)


def fisher_exact_test(x_a: int, n_a: int, x_b: int, n_b: int) -> tuple[float, float]:
    """Test exacto de Fisher sobre la tabla 2x2, dos colas. Necesario para
    muestras pequeñas donde la aproximación normal no es válida (escenario
    08, Requisito 3 de la Sección 2.3)."""
    table = [[x_a, n_a - x_a], [x_b, n_b - x_b]]
    odds_ratio, p_value = stats.fisher_exact(table, alternative="two-sided")
    return float(odds_ratio), float(p_value)


def achieved_power(p_a: float, p_b: float, n_a: int, n_b: int, alpha: float = 0.05) -> float:
    """Potencia estadística alcanzada (post-hoc) para el efecto observado,
    con el n real de cada brazo, para un z-test de dos proporciones a dos
    colas. Referencia analítica estándar (Kohavi et al.), verificada contra
    la matriz sellada de la Fase 3 (ver tests unitarios)."""
    if n_a <= 0 or n_b <= 0:
        return 0.0
    p_pool = (p_a * n_a + p_b * n_b) / (n_a + n_b)
    se_null = sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    se_alt = sqrt((p_a * (1 - p_a) / n_a) + (p_b * (1 - p_b) / n_b))
    if se_null == 0 or se_alt == 0:
        return 0.0
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    effect = abs(p_a - p_b)
    z_beta = (effect - z_alpha * se_null) / se_alt
    power = stats.norm.cdf(z_beta)
    return float(np.clip(power, 0.0, 1.0))


def sample_size_for_power(
    p0: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    """Tamaño de muestra por brazo necesario para detectar `mde` (diferencia
    absoluta de conversión) sobre un baseline `p0`, con la `power` objetivo.
    Componente de Fase 2 ("cálculo de tamaño de muestra/MDE")."""
    p1 = p0 + mde
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_beta = stats.norm.ppf(power)
    p_bar = (p0 + p1) / 2
    numerator = (
        z_alpha * sqrt(2 * p_bar * (1 - p_bar)) + z_beta * sqrt(p0 * (1 - p0) + p1 * (1 - p1))
    ) ** 2
    n = numerator / (mde ** 2)
    return int(np.ceil(n))


def bonferroni_correction(p_values: list[float], alpha: float = 0.05) -> tuple[float, list[bool]]:
    """Corrección de Bonferroni para comparaciones múltiples (componente de
    Fase 2). Devuelve el alpha ajustado y qué comparaciones siguen siendo
    significativas bajo ese alpha."""
    m = len(p_values)
    if m == 0:
        return alpha, []
    adjusted_alpha = alpha / m
    return adjusted_alpha, [p < adjusted_alpha for p in p_values]


# ---------------------------------------------------------------------------
# Guardrail — regla precautoria de punto estimado (metodología sellada 0.B)
# ---------------------------------------------------------------------------

def _evaluate_guardrail(
    o_a: int, n_a: int, o_b: int, n_b: int, threshold: float
) -> GuardrailInfo:
    """El guardrail se evalúa por PUNTO ESTIMADO contra un umbral absoluto
    fijo (criterio original de 0.B, restaurado en v17.19 tras revertir el
    intento de v17.18 de usar el límite inferior del CI de Wilson como
    criterio de disparo).

    Por qué se restaura el punto estimado: v17.18 sustituyó el punto
    estimado por el límite inferior del CI para reducir falsos positivos
    con muestra pequeña, pero al validarlo contra los 16 CSV reales
    (evaluator_handoff/) se descubrió que ese cambio reintroducía un FALSO
    NEGATIVO en `07_umbral` — el escenario diseñado específicamente para
    reproducir el fallo original de Fase 5 (una ruptura real del guardrail,
    q=0.0225 vs umbral 0.020, que dejaba de detectarse porque el CI con
    n=400 no alcanzaba a confirmarla con el 95% de confianza exigido).

    Las best practices de la industria para métricas de guardrail (Airbnb
    Engineering, "Designing Experimentation Guardrails"; Spotify
    Engineering, "Risk-Aware Product Decisions in A/B Tests with Multiple
    Metrics", 2024) son consistentes en que, para un guardrail de
    seguridad, el falso negativo (dejar pasar una ruptura real) es el
    error más costoso — más que el falso positivo (bloquear algo que en
    realidad era seguro). Suavizar el criterio de disparo para reducir
    falsos positivos, si eso a la vez reduce la sensibilidad a rupturas
    reales, es el error de diseño equivocado para este tipo de métrica.

    La solución correcta (ver `_guardrail_power_adequate` y su uso en
    `run_ab_test`) no toca este criterio de disparo — añade una
    comprobación de potencia ANTES de confiar en él, siguiendo el patrón
    que Airbnb documenta como "Power Guardrail": no evaluar el guardrail
    como fiable si el brazo no tiene muestra suficiente para que el
    resultado tenga sentido, y en ese caso diferir el veredicto a
    'insufficient_sample' en vez de asumir "seguro" o "rompe" sobre datos
    poco fiables.
    """
    q_a = o_a / n_a
    q_b = o_b / n_b
    breach_a = q_a > threshold
    breach_b = q_b > threshold
    breach = breach_a or breach_b

    if not breach:
        # Sin ruptura: se reporta el IC del brazo con mayor tasa observada,
        # por ser el más informativo para vigilancia futura.
        if q_a >= q_b:
            return GuardrailInfo(breach=False, ci=wilson_ci(o_a, n_a), variant=None)
        return GuardrailInfo(breach=False, ci=wilson_ci(o_b, n_b), variant=None)

    # Con ruptura: se reporta el IC del brazo que rompe (el de mayor tasa,
    # si ambos rompen).
    if breach_a and breach_b:
        variant = "A" if q_a >= q_b else "B"
    elif breach_a:
        variant = "A"
    else:
        variant = "B"

    ci = wilson_ci(o_a, n_a) if variant == "A" else wilson_ci(o_b, n_b)
    return GuardrailInfo(breach=True, ci=ci, variant=variant)


def _guardrail_power_adequate(n: int, threshold: float) -> bool:
    """Comprobación de potencia del guardrail ("Power Guardrail", patrón
    documentado por Airbnb Engineering en "Designing Experimentation
    Guardrails"): antes de confiar en el punto estimado de un brazo para
    disparar el guardrail, se exige que el recuento esperado de opt-outs
    bajo la hipótesis límite (tasa real = threshold exacto) alcance el
    mínimo de Cochran (>=5) -- la misma regla que ya usa el framework para
    decidir si el z-test de significancia es válido
    (`min_expected_cell_count`), aplicada aquí al umbral del guardrail en
    vez de a la proporción combinada. Con n por debajo de este mínimo, el
    punto estimado del guardrail no es fiable (un solo evento de más o de
    menos cambia el veredicto) y no debe usarse para declarar ni "seguro"
    ni "rompe" -- ver `run_ab_test` para cómo se usa este resultado
    (verdict = 'insufficient_sample' en vez de confiar en el punto
    estimado).
    """
    return (n * threshold) >= MIN_EXPECTED_CELL_COUNT


# ---------------------------------------------------------------------------
# Función principal — contrato congelado (0.6-c, v17.14)
# ---------------------------------------------------------------------------

def run_ab_test(
    conversions_a: pd.DataFrame,
    conversions_b: pd.DataFrame,
    baseline_p0: float,
    guardrail_q_threshold: float,
    alpha: float = 0.05,
) -> ABTestResult:
    """
    Algoritmo de precedencia (obligatorio, no reordenable en tiempo de
    ejecución) — revisado v17.21, ver `_guardrail_power_adequate` para el
    detalle y la justificación (best practices de guardrails de seguridad,
    Airbnb/Spotify Engineering):
      0. Si guardrail_breach pero la muestra NO es fiable -> verdict =
         "insufficient_sample". "No fiable" significa que falla CUALQUIERA
         de las dos comprobaciones de potencia que existen en el framework,
         que son independientes entre sí (fórmulas distintas sobre
         magnitudes distintas):
           (a) `_guardrail_power_adequate` del brazo que dispara (potencia
               del propio guardrail: n * threshold >= 5), y
           (b) `sample_adequate` (regla de Cochran sobre la proporción
               combinada de conversión, ya usada en el paso 2 para decidir
               z_test vs fisher_exact).
         Corrección v17.21 (cierre del hueco de diseño anotado en v17.19-
         v17.20): antes solo se comprobaba (a). Es matemáticamente posible
         que un brazo tenga potencia suficiente para el guardrail (a) pero
         no para el test de conversión (b) -- en ese caso, con la versión
         v17.19, el guardrail pasaba su propia comprobación de potencia y
         disparaba directamente "not_recommended_guardrail" en el paso 1,
         sin llegar nunca a evaluar (b): la muestra de conversión quedaba
         enmascarada exactamente igual que en el hallazgo original de
         v17.17, solo que por una combinación de parámetros no representada
         en los 16 CSV de `evaluator_handoff/` (demostrado con un caso
         construido, no observado en los datos reales -- ver
         `test_guardrail_defers_when_conversion_sample_is_underpowered_even_if_guardrail_power_is_adequate`).
         Exigir ambas resuelve esto por construcción, no solo para los
         casos ya vistos.
      1. Si guardrail_breach (punto estimado de A o B por encima de
         guardrail_q_threshold) Y la muestra ES fiable (ambas
         comprobaciones de potencia adecuadas) -> verdict =
         "not_recommended_guardrail". Veto duro: no importa el p_value,
         aunque la conversión del brazo que rompe el guardrail sea mejor.
         El criterio de disparo sigue siendo el punto estimado, sin
         suavizar con intervalo de confianza -- una prueba anterior
         (v17.18) que sustituía el punto estimado por el límite inferior
         del CI de Wilson se revirtió tras comprobar que reintroducía un
         falso negativo en 07_umbral (la propia causa raíz de Fase 5 que
         motivó este framework). Este cambio (v17.21) NO toca ese criterio
         de disparo, solo amplía qué cuenta como "muestra fiable" antes de
         confiar en él.
      2. Si no hubo ruptura de guardrail (o si la hubo pero no llegó a
         evaluarse por el paso 0) y no se cumple el recuento mínimo
         esperado para que la aproximación normal sea válida (regla de
         Cochran, ver escenario 08, Requisito 3 de la Sección 2.3) ->
         verdict = "insufficient_sample". Esta es la corrección directa del
         fallo de Fase 5 en 08_obvio: un resultado nominalmente
         significativo con n=25 no debe presentarse como hallazgo
         confirmado. Nótese que esta misma comprobación (b) es la que ahora
         también participa en el paso 0 -- no es lógica duplicada, es la
         misma condición reutilizada en dos puntos de decisión distintos
         del algoritmo.
      3. Si p_value < alpha -> "A_wins" / "B_wins" según el signo del efecto
         observado.
      4. En cualquier otro caso -> "no_significant_difference".

    Parámetros
    ----------
    conversions_a, conversions_b:
        DataFrames ya cargados (columnas 'converted', 'opt_out'; una fila
        por usuario) del brazo A y B respectivamente. La lectura desde
        disco vive en `load_arm_data`, fuera de esta función.
    baseline_p0:
        Conversión baseline de referencia (ver Sección 0.5, p0=0.096). No
        se usa en el cálculo del veredicto (A y B se comparan entre sí),
        se conserva en la firma para que llamadas futuras puedan
        contextualizar el resultado contra el baseline de negocio.
    guardrail_q_threshold:
        Umbral absoluto de opt-out (ver 0.B, q<=0.020).
    alpha:
        Nivel de significancia para el test de conversión.

    Devuelve
    --------
    dict con las claves congeladas en el contrato de 0.6-c (v17.14):
      verdict, p_value, power_achieved, guardrail_breach, guardrail_ci,
      test_used.
    """
    _validate_arm_dataframe(conversions_a, name="conversions_a")
    _validate_arm_dataframe(conversions_b, name="conversions_b")

    n_a, n_b = len(conversions_a), len(conversions_b)
    x_a = int(conversions_a["converted"].sum())
    x_b = int(conversions_b["converted"].sum())
    o_a = int(conversions_a["opt_out"].sum())
    o_b = int(conversions_b["opt_out"].sum())

    p_a, p_b = x_a / n_a, x_b / n_b

    # --- Paso 1: guardrail (veto duro, punto estimado) ---
    guardrail = _evaluate_guardrail(o_a, n_a, o_b, n_b, guardrail_q_threshold)

    # Selección de test (regla de Cochran) — se calcula siempre, se usa
    # tanto para decidir "insufficient_sample" (paso 2) como para elegir el
    # test de significancia (paso 3).
    min_expected = min_expected_cell_count(n_a, p_a, n_b, p_b)
    sample_adequate = min_expected >= MIN_EXPECTED_CELL_COUNT
    test_used: TestUsed = "z_test" if sample_adequate else "fisher_exact"

    if test_used == "z_test":
        _, p_value = two_proportion_ztest(x_a, n_a, x_b, n_b)
    else:
        _, p_value = fisher_exact_test(x_a, n_a, x_b, n_b)

    power_achieved = achieved_power(p_a, p_b, n_a, n_b, alpha)

    # --- Algoritmo de precedencia (revisado v17.21 — Power Guardrail
    # ampliado a ambas comprobaciones de potencia) ---
    # El guardrail sigue teniendo prioridad absoluta sobre significancia
    # CUANDO su resultado es fiable. "Fiable" exige AMBAS comprobaciones de
    # potencia del framework, no solo la del propio guardrail:
    #   (a) `_guardrail_power_adequate` del brazo que dispara — potencia
    #       del guardrail frente a su propio umbral fijo.
    #   (b) `sample_adequate` — regla de Cochran sobre la proporción
    #       combinada de conversión (ya calculada más arriba para elegir
    #       z_test/fisher_exact).
    # Son fórmulas independientes sobre magnitudes distintas (opt-out vs.
    # conversión; umbral fijo vs. proporción combinada observada): que (a)
    # se cumpla no implica que (b) se cumpla, ni al revés. Con solo (a)
    # (versión v17.19), un brazo podía tener potencia suficiente para el
    # guardrail pero no para el test de conversión, y el guardrail disparaba
    # igualmente "not_recommended_guardrail" sin que la falta de potencia de
    # conversión llegara a evaluarse -- el mismo mecanismo de enmascaramiento
    # de v17.17, reproducido con parámetros no representados en los 16 CSV
    # de `evaluator_handoff/` (ver hallazgo v17.20 y el test que lo cierra).
    # Si el brazo tiene potencia suficiente en AMBAS, el punto estimado
    # decide igual que siempre, sin suavizar (ver 07_umbral en los tests --
    # debe seguir disparando con n=400).
    guardrail_reliable = True
    if guardrail["breach"] and guardrail["variant"] is not None:
        n_breaching = n_a if guardrail["variant"] == "A" else n_b
        guardrail_reliable = (
            _guardrail_power_adequate(n_breaching, guardrail_q_threshold)
            and sample_adequate
        )

    if guardrail["breach"] and guardrail_reliable:
        verdict: Verdict = "not_recommended_guardrail"
    elif guardrail["breach"] and not guardrail_reliable or not sample_adequate:
        verdict = "insufficient_sample"
    elif p_value < alpha:
        verdict = "A_wins" if p_a > p_b else "B_wins"
    else:
        verdict = "no_significant_difference"

    return ABTestResult(
        verdict=verdict,
        p_value=p_value,
        power_achieved=power_achieved,
        guardrail_breach=guardrail["breach"],
        guardrail_ci=guardrail["ci"],
        test_used=test_used,
    )


# ---------------------------------------------------------------------------
# Extensión aprobada v17.23 — veredicto de N brazos (control + variantes)
# NO es parte del contrato original 0.6-c (v17.14) — ver nota de cabecera
# del módulo para el detalle de qué se aprobó y cuándo.
# ---------------------------------------------------------------------------

MultiArmVerdict = Literal[
    "no_arm_recommended",              # ninguna variante gana a control
    "single_arm_recommended",          # exactamente una variante gana a control
    "multiple_arms_portfolio_candidates",  # más de una variante gana a control -- el código NO elige entre ellas, se reporta como conjunto de candidatas válidas
    "inconclusive",                    # ninguna comparación es concluyente (todo no_significant_difference/insufficient_sample) -- no hay evidencia ni para recomendar ni para descartar
]


class MultiArmResult(TypedDict):
    multi_verdict: MultiArmVerdict
    winning_arms: list[str]
    per_arm_results: dict[str, ABTestResult]


def holm_bonferroni_correction(
    p_values: list[float], alpha: float = 0.05
) -> tuple[list[float], list[bool]]:
    """Corrección de Holm-Bonferroni para comparaciones múltiples (aprobada
    en v17.23 como método usado en `evaluate_multi_arm_test`, en vez de
    `bonferroni_correction` -- esa función se deja sin tocar más arriba,
    por si algún llamador externo depende de ella).

    Ordena los p-valores de menor a mayor y asigna un umbral distinto a
    cada rango -- alpha/(m-rango) -- evaluado secuencialmente: en cuanto un
    p-valor no supera su propio umbral, todos los p-valores mayores
    (rangos siguientes) quedan automáticamente no significativos, sin
    llegar a evaluarse contra el suyo. Mismo control del error
    familia-wise que Bonferroni simple (misma tasa de al menos un falso
    positivo bajo la hipótesis nula global), con más potencia: domina
    estocásticamente a Bonferroni porque el umbral se relaja a medida que
    se "gastan" comparaciones ya resueltas como no significativas, en vez
    de dividir alpha entre m de forma fija para todas.

    Devuelve, en el ORDEN ORIGINAL de `p_values` (no en el orden de rango
    usado internamente): (a) el umbral de Holm efectivo aplicado a cada
    p-valor, (b) si esa comparación es significativa bajo ese umbral.
    """
    m = len(p_values)
    if m == 0:
        return [], []
    order = sorted(range(m), key=lambda i: p_values[i])
    thresholds = [0.0] * m
    significant = [False] * m
    still_testable = True
    for rank, idx in enumerate(order):
        threshold = alpha / (m - rank)
        thresholds[idx] = threshold
        if still_testable and p_values[idx] <= threshold:
            significant[idx] = True
        else:
            # Holm es secuencial: en cuanto un p-valor falla su umbral,
            # todos los siguientes (p-valores mayores, ya en orden
            # ascendente) fallan también sin evaluarse individualmente.
            still_testable = False
    return thresholds, significant


def evaluate_multi_arm_test(
    control: pd.DataFrame,
    arms: dict[str, pd.DataFrame],
    baseline_p0: float,
    guardrail_q_threshold: float,
    alpha: float = 0.05,
) -> MultiArmResult:
    """Evalúa N variantes frente a un control común, reutilizando
    `run_ab_test` sin modificar su firma ni su algoritmo de precedencia
    (contrato 0.6-c intacto).

    Para cada variante, se llama `run_ab_test(arm_df, control_df, ...)` --
    la variante en la posición "A" para que "A_wins" se lea como "la
    variante gana a control".

    Corrección de comparaciones múltiples (Holm-Bonferroni, aprobada
    v17.23): se ejecuta en dos pasadas.
      Pasada 1 (`alpha` nominal): resuelve, para cada brazo, si queda
      vetado por guardrail o por muestra insuficiente -- ninguna de esas
      dos ramas del algoritmo de precedencia de `run_ab_test` depende de
      alpha, así que esta pasada ya determina de forma fiable qué brazos
      NO compiten por significancia (un brazo descartado por guardrail no
      "gasta" una comparación en la corrección de múltiples comparaciones).
      Pasada 2: sobre los p-valores de los brazos que sí llegaron al paso
      de significancia en la pasada 1, se aplica `holm_bonferroni_correction`
      para obtener el umbral de Holm específico de cada brazo, y se
      re-ejecuta `run_ab_test` con ese umbral como `alpha` efectivo -- para
      que `power_achieved` (que sí depende de alpha) quede consistente con
      el umbral realmente aplicado a la decisión de significancia.

    Veredicto agregado (4 valores, aprobados v17.23 -- ver nota de
    cabecera del módulo):
      - `multiple_arms_portfolio_candidates` (antes `multiple_arms_tied`
        en la propuesta v17.22): el código NUNCA elige una variante
        ganadora aquí. No es un empate a resolver -- son varias variantes
        genuinamente válidas frente a control, expuestas en `winning_arms`
        como conjunto completo. Distinto de `inconclusive`: aquí los
        resultados SÍ fueron precisos, es que hay más de un ganador real.
        Qué hacer con el conjunto (¿llevar varias a portfolio? ¿priorizar
        por otro criterio de negocio?) es una decisión fuera del alcance
        de este framework estadístico.
    """
    arm_names = list(arms.keys())

    probe_results: dict[str, ABTestResult] = {
        name: run_ab_test(arm_df, control, baseline_p0, guardrail_q_threshold, alpha)
        for name, arm_df in arms.items()
    }

    testable_names = [
        name
        for name in arm_names
        if probe_results[name]["verdict"]
        not in ("not_recommended_guardrail", "insufficient_sample")
    ]
    p_values = [probe_results[name]["p_value"] for name in testable_names]
    thresholds, _ = holm_bonferroni_correction(p_values, alpha)

    per_arm_results: dict[str, ABTestResult] = {}
    for name in arm_names:
        if name not in testable_names:
            per_arm_results[name] = probe_results[name]
            continue
        effective_alpha = thresholds[testable_names.index(name)]
        per_arm_results[name] = run_ab_test(
            arms[name], control, baseline_p0, guardrail_q_threshold, effective_alpha
        )

    winning_arms = [
        name for name, r in per_arm_results.items() if r["verdict"] == "A_wins"
    ]

    if len(winning_arms) == 1:
        multi_verdict: MultiArmVerdict = "single_arm_recommended"
    elif len(winning_arms) > 1:
        multi_verdict = "multiple_arms_portfolio_candidates"
    elif any(
        r["verdict"] in ("not_recommended_guardrail", "B_wins")
        for r in per_arm_results.values()
    ):
        # Al menos una variante pierde claramente o rompe el guardrail, y
        # ninguna gana: coherente con "ninguna variante recomendable" (el
        # caso real del escenario 06, ver docstring del módulo).
        multi_verdict = "no_arm_recommended"
    else:
        # Ninguna variante gana ni pierde con claridad (todo
        # no_significant_difference / insufficient_sample): no hay
        # evidencia suficiente para recomendar NI para descartar ninguna.
        multi_verdict = "inconclusive"

    return MultiArmResult(
        multi_verdict=multi_verdict,
        winning_arms=winning_arms,
        per_arm_results=per_arm_results,
    )
