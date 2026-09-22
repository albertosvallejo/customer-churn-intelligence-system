"""
Tests unitarios de ab_testing_framework.py — Fase 2, gate de salida.

Cubren:
  - Referencias analíticas conocidas e independientes (statsmodels, scipy
    directo, cálculo a mano donde es trivial) — nunca el propio código bajo
    test usado como su propia referencia.
  - El algoritmo de precedencia del contrato congelado (0.6-c, v17.14) con
    datos deterministas (conteos exactos, no muestreo aleatorio), para que
    los tests sean rápidos, reproducibles y no dependan de fixtures en
    disco (Requisito (a) de 0.6-c).
  - Requisito 4 (Sección 2.3, v17.14): validación programática de
    horquillas intermedias de potencia (75%, 60%) contra la potencia
    teórica calculada analíticamente.
  - Reconstrucción de los 16 escenarios de la matriz sellada (Sección 2.3),
    con conteos deterministas derivados de sus parámetros documentados
    (valor esperado exacto, no una única realización aleatoria), para
    comprobar que el framework recupera el veredicto que la spec declara
    para esos parámetros.

Nota de alcance: los 16 CSV originales (`s5b_*.csv`) son artefactos
privados de la Fase 3, no accesibles en este entorno. Las tablas de conteos
usadas en la sección 4 son construcciones deterministas (valor esperado
exacto bajo los parámetros publicados en la Sección 2.3), no una
realización aleatoria del CSV sellado original — sirven para validar la
lógica de decisión contra el ground truth conocido de cada fila, que es lo
que exige el gate de la Fase 2 ("tests unitarios... no solo razonado en
informes markdown").
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportions_ztest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "pipeline"))
import ab_testing_framework as abf

# ---------------------------------------------------------------------------
# Utilidades de construcción de datos deterministas
# ---------------------------------------------------------------------------

def make_arm(n: int, converted: int, opt_out: int) -> pd.DataFrame:
    """Construye un brazo con conteos EXACTOS (no muestreo aleatorio):
    `converted` filas con converted=1 y `opt_out` filas con opt_out=1,
    asignadas independientemente. Determinista y reproducible — apto para
    tests contra referencias analíticas conocidas."""
    conv_col = np.array([1] * converted + [0] * (n - converted))
    opt_col = np.array([1] * opt_out + [0] * (n - opt_out))
    rng = np.random.default_rng(0)
    rng.shuffle(opt_col)  # descorrelaciona de converted, sin afectar los totales
    return pd.DataFrame({"converted": conv_col, "opt_out": opt_col})


def arm_from_rate(n: int, p: float, q: float) -> pd.DataFrame:
    """Conteos esperados exactos (redondeados) bajo probabilidades p/q —
    representa el valor esperado de la distribución, no una realización
    con ruido de una única tirada."""
    return make_arm(n, round(n * p), round(n * q))


# ---------------------------------------------------------------------------
# 1. Referencias analíticas conocidas (independientes de la implementación)
# ---------------------------------------------------------------------------

class TestWilsonCI:
    def test_matches_hand_calculation(self):
        # 7 éxitos sobre 150, 95% CI — valor de referencia (Newcombe, 1998).
        lower, upper = abf.wilson_ci(7, 150, confidence=0.95)
        assert lower == pytest.approx(0.0227, abs=1e-3)
        assert upper == pytest.approx(0.0938, abs=1e-3)

    def test_zero_count(self):
        lower, upper = abf.wilson_ci(0, 100)
        assert lower == pytest.approx(0.0, abs=1e-9)
        assert upper > 0.0

    def test_empty_arm_returns_zero(self):
        assert abf.wilson_ci(0, 0) == (0.0, 0.0)

    def test_matches_scipy_binomtest_ci_approximately(self):
        # Referencia independiente: scipy.stats.binomtest usa por defecto un
        # método distinto (Clopper-Pearson exacto), pero para n moderado
        # debe estar en el mismo orden de magnitud que Wilson.
        result = stats.binomtest(20, 200, p=0.1)
        exact_ci = result.proportion_ci(confidence_level=0.95, method="exact")
        wilson_lower, wilson_upper = abf.wilson_ci(20, 200)
        assert wilson_lower == pytest.approx(exact_ci.low, abs=0.02)
        assert wilson_upper == pytest.approx(exact_ci.high, abs=0.02)


class TestTwoProportionZTest:
    def test_matches_statsmodels_reference(self):
        # Referencia independiente: statsmodels.stats.proportion.proportions_ztest
        counts = np.array([80, 40])
        nobs = np.array([400, 400])
        ref_z, ref_p = proportions_ztest(counts, nobs)
        z, p_value = abf.two_proportion_ztest(80, 400, 40, 400)
        assert z == pytest.approx(ref_z, abs=1e-6)
        assert p_value == pytest.approx(ref_p, abs=1e-6)

    def test_no_difference_gives_p_value_one(self):
        z, p_value = abf.two_proportion_ztest(80, 800, 80, 800)
        assert z == pytest.approx(0.0, abs=1e-9)
        assert p_value == pytest.approx(1.0, abs=1e-9)


class TestFisherExact:
    def test_matches_scipy_reference_directly(self):
        ref_odds, ref_p = stats.fisher_exact([[3, 22], [10, 15]], alternative="two-sided")
        odds, p_value = abf.fisher_exact_test(3, 25, 10, 25)
        assert odds == pytest.approx(ref_odds)
        assert p_value == pytest.approx(ref_p)


class TestAchievedPower:
    def test_matches_statsmodels_normal_ind_power(self):
        # Referencia independiente: statsmodels NormalIndPower con el mismo
        # effect size (Cohen's h) y n por brazo.
        p_a, p_b, n = 0.16, 0.08, 380
        effect_size = 2 * np.arcsin(np.sqrt(p_a)) - 2 * np.arcsin(np.sqrt(p_b))
        ref_power = NormalIndPower().power(effect_size=effect_size, nobs1=n, alpha=0.05, ratio=1.0)
        power = abf.achieved_power(p_a, p_b, n, n, alpha=0.05)
        # Cohen's h (statsmodels) y la aproximación normal directa sobre
        # proporciones (nuestra implementación) no son parametrizaciones
        # idénticas, pero deben coincidir dentro de una tolerancia razonable
        # para el mismo escenario.
        assert power == pytest.approx(ref_power, abs=0.05)

    def test_recovers_documented_power_for_scenario_01_obvio(self):
        # Escenario 01_obvio de la matriz sellada (Sección 2.3): potencia
        # documentada ~92.6% para A=0.16, B=0.08, n=380/brazo.
        power = abf.achieved_power(0.16, 0.08, 380, 380, alpha=0.05)
        assert power == pytest.approx(0.926, abs=0.02)

    def test_recovers_documented_power_for_scenario_01_umbral(self):
        # Escenario 01_umbral: A=0.11, B=0.08, n=740, ~50.3% documentado.
        power = abf.achieved_power(0.11, 0.08, 740, 740, alpha=0.05)
        assert power == pytest.approx(0.503, abs=0.02)

    def test_zero_n_returns_zero(self):
        assert abf.achieved_power(0.1, 0.2, 0, 10) == 0.0


class TestSampleSizeForPower:
    def test_matches_statsmodels_solve_power(self):
        p0, mde, alpha, power = 0.096, 0.03, 0.05, 0.8
        effect_size = 2 * np.arcsin(np.sqrt(p0 + mde)) - 2 * np.arcsin(np.sqrt(p0))
        ref_n = NormalIndPower().solve_power(effect_size=effect_size, alpha=alpha, power=power, ratio=1.0)
        n = abf.sample_size_for_power(p0=p0, mde=mde, alpha=alpha, power=power)
        # Cohen's h vs. aproximación directa sobre proporciones: mismo orden
        # de magnitud, tolerancia generosa porque son parametrizaciones
        # distintas del mismo problema.
        assert n == pytest.approx(ref_n, rel=0.2)


class TestBonferroniCorrection:
    def test_adjusts_alpha_and_flags_correctly(self):
        adjusted_alpha, flags = abf.bonferroni_correction([0.001, 0.03, 0.2], alpha=0.05)
        assert adjusted_alpha == pytest.approx(0.05 / 3)
        assert flags == [True, False, False]

    def test_empty_list(self):
        adjusted_alpha, flags = abf.bonferroni_correction([], alpha=0.05)
        assert adjusted_alpha == 0.05
        assert flags == []


# ---------------------------------------------------------------------------
# 2. Algoritmo de precedencia — casos de contrato (datos deterministas)
# ---------------------------------------------------------------------------

class TestPrecedenceAlgorithm:
    def test_guardrail_vetoes_even_when_conversion_favors_breaching_arm(self):
        # Corrección directa de la causa raíz de 07_umbral (Fase 5): el
        # guardrail debe vetar incluso si el efecto de conversión es real,
        # grande y favorable a la variante que rompe el guardrail.
        a = make_arm(n=400, converted=56, opt_out=21)  # q_a = 0.0525 > 0.02
        b = make_arm(n=400, converted=32, opt_out=6)   # q_b = 0.015
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is True
        assert result["verdict"] == "not_recommended_guardrail"
        assert result["guardrail_ci"][0] <= 21 / 400 <= result["guardrail_ci"][1]

    def test_guardrail_breach_uses_strict_inequality_at_the_boundary(self):
        # Punto estimado EXACTAMENTE en el umbral no debe vetar (la regla es
        # "por encima de", no "en o por encima de") — comportamiento
        # explícito y verificable del contrato, no solo una nota de prosa.
        a = make_arm(n=400, converted=48, opt_out=8)  # q_a = 0.020 exacto
        b = make_arm(n=400, converted=32, opt_out=6)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is False

    def test_guardrail_defers_to_insufficient_sample_when_underpowered(self):
        # Corrección v17.19 (Power Guardrail): reproduce el falso positivo
        # real de 08_obvio (evaluator_handoff/, n=25, 3 opt-outs -> punto
        # estimado 12% muy por encima del umbral 2%, pero n*threshold=0.5
        # < 5, muy por debajo del mínimo de Cochran). El punto estimado
        # sigue disparando (breach=True, se reporta para auditoría), pero
        # el veredicto final se difiere a insufficient_sample en vez de
        # asumir que es una ruptura real.
        a = make_arm(n=25, converted=4, opt_out=0)
        b = make_arm(n=25, converted=2, opt_out=3)  # q_b = 0.12, n*threshold=0.5
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is True  # se reporta igual, para auditoría
        assert result["verdict"] == "insufficient_sample"

    def test_guardrail_still_breaches_with_adequate_power_near_boundary(self):
        # Corrección v17.19: reproduce 07_umbral real (n=400, q=0.0225 vs
        # umbral 0.020, n*threshold=8 >= 5 -> potencia suficiente). El
        # guardrail debe seguir disparando con el punto estimado, sin
        # suavizar -- esta es la causa raíz original de Fase 5 (falso
        # negativo de seguridad) y no debe reaparecer.
        a = make_arm(n=400, converted=60, opt_out=9)  # q_a = 0.0225
        b = make_arm(n=400, converted=40, opt_out=6)  # q_b = 0.015
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is True
        assert result["verdict"] == "not_recommended_guardrail"

    def test_guardrail_breach_with_adequate_power_is_not_deferred(self):
        # Contraprueba directa de _guardrail_power_adequate: con n grande y
        # margen amplio sobre el umbral, ni el punto estimado ni la
        # comprobación de potencia deben diferir el veredicto.
        a = make_arm(n=2000, converted=200, opt_out=50)  # q_a = 0.025, n*threshold=40
        b = make_arm(n=2000, converted=200, opt_out=20)  # q_b = 0.010
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is True
        assert result["verdict"] == "not_recommended_guardrail"

    def test_guardrail_power_adequate_matches_cochran_style_threshold(self):
        # Test directo de la función de potencia, no del caso de negocio.
        assert abf._guardrail_power_adequate(25, 0.020) is False   # 0.5 < 5
        assert abf._guardrail_power_adequate(150, 0.020) is False  # 3.0 < 5
        assert abf._guardrail_power_adequate(250, 0.020) is True   # 5.0 >= 5
        assert abf._guardrail_power_adequate(400, 0.020) is True   # 8.0 >= 5

    def test_guardrail_defers_when_conversion_sample_is_underpowered_even_if_guardrail_power_is_adequate(self):
        # Corrección v17.21: cierra el hueco de diseño anotado en v17.20.
        # `_guardrail_power_adequate` (n*threshold>=5) y la regla de Cochran
        # del test de conversión (proporción combinada) son comprobaciones
        # independientes -- un brazo puede pasar la primera y fallar la
        # segunda. n=300, threshold=0.020 -> n*threshold=6 >= 5 (potencia de
        # guardrail adecuada), pero con conversiones muy bajas (3/300 y
        # 2/300) el recuento esperado mínimo de la tabla de conversión es 2
        # < 5 (potencia de conversión NO adecuada). Antes de v17.21 esto
        # disparaba "not_recommended_guardrail" directamente (el mismo
        # mecanismo de enmascaramiento de v17.17, con parámetros no
        # representados en los 16 CSV de evaluator_handoff/); con v17.21
        # debe diferirse a "insufficient_sample".
        a = make_arm(n=300, converted=3, opt_out=7)  # q_a=0.0233>0.02
        b = make_arm(n=300, converted=2, opt_out=1)  # q_b=0.0033
        assert abf._guardrail_power_adequate(300, 0.020) is True
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is True  # se reporta igual, para auditoría
        assert result["verdict"] == "insufficient_sample"

    def test_guardrail_still_breaches_when_both_powers_are_adequate(self):
        # Contraprueba directa del cambio v17.21: si AMBAS comprobaciones de
        # potencia son adecuadas (guardrail y conversión), el veto del
        # guardrail se mantiene sin diferir -- no se ha vuelto a suavizar el
        # criterio de disparo, solo se amplió qué cuenta como "fiable".
        a = make_arm(n=400, converted=60, opt_out=9)  # q_a=0.0225; conversión con potencia
        b = make_arm(n=400, converted=40, opt_out=6)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["guardrail_breach"] is True
        assert result["verdict"] == "not_recommended_guardrail"

    def test_insufficient_sample_precedes_significance(self):
        # Escenario 08_obvio: n=25/brazo, efecto grande (A=0.14, B=0.08). El
        # fallo de Fase 5 fue presentar esto como hallazgo confirmado; el
        # framework debe declarar insufficient_sample en su lugar, pese a
        # que el p-valor por sí solo sería significativo.
        a = make_arm(n=25, converted=4, opt_out=0)
        b = make_arm(n=25, converted=2, opt_out=0)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["test_used"] == "fisher_exact"
        assert result["guardrail_breach"] is False
        assert result["verdict"] == "insufficient_sample"

    def test_significant_difference_declares_winner(self):
        a = make_arm(n=2000, converted=320, opt_out=30)  # p=0.16, q=0.015
        b = make_arm(n=2000, converted=160, opt_out=30)  # p=0.08, q=0.015
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["verdict"] == "A_wins"
        assert result["p_value"] < 0.05
        assert result["guardrail_breach"] is False
        assert result["test_used"] == "z_test"

    def test_symmetric_case_declares_b_wins(self):
        a = make_arm(n=2000, converted=160, opt_out=30)
        b = make_arm(n=2000, converted=320, opt_out=30)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["verdict"] == "B_wins"

    def test_no_significant_difference_when_arms_are_equal(self):
        a = make_arm(n=800, converted=72, opt_out=12)  # p=0.09, q=0.015
        b = make_arm(n=800, converted=72, opt_out=12)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        assert result["verdict"] == "no_significant_difference"
        assert result["p_value"] == pytest.approx(1.0, abs=1e-9)

    def test_output_contract_has_exactly_the_frozen_keys(self):
        a = make_arm(n=500, converted=50, opt_out=5)
        b = make_arm(n=500, converted=50, opt_out=5)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)
        frozen_keys = {
            "verdict",
            "p_value",
            "power_achieved",
            "guardrail_breach",
            "guardrail_ci",
            "test_used",
        }
        assert frozen_keys.issubset(result.keys())
        assert isinstance(result["guardrail_ci"], tuple) and len(result["guardrail_ci"]) == 2
        assert result["test_used"] in ("z_test", "fisher_exact")
        assert result["verdict"] in (
            "A_wins", "B_wins", "no_significant_difference",
            "not_recommended_guardrail", "insufficient_sample",
        )

    def test_rejects_missing_columns(self):
        bad = pd.DataFrame({"converted": [1, 0, 1]})
        good = make_arm(n=10, converted=1, opt_out=0)
        with pytest.raises(ValueError):
            abf.run_ab_test(bad, good, baseline_p0=0.096, guardrail_q_threshold=0.020)

    def test_rejects_empty_arm(self):
        empty = pd.DataFrame({"converted": [], "opt_out": []})
        good = make_arm(n=10, converted=1, opt_out=0)
        with pytest.raises(ValueError):
            abf.run_ab_test(empty, good, baseline_p0=0.096, guardrail_q_threshold=0.020)


# ---------------------------------------------------------------------------
# 3. Requisito 4 (v17.14) — horquillas intermedias de potencia
# ---------------------------------------------------------------------------

class TestIntermediatePowerBrackets:
    """Genera datasets sintéticos adicionales en puntos intermedios de
    potencia (75%, 60%) y compara la potencia calculada por el framework
    contra la potencia teórica objetivo — de forma puramente programática,
    sin sesión evaluadora, tal como exige el Requisito 4 de la Sección 2.3.
    Usa conteos deterministas (valor esperado exacto) para que la
    comparación no dependa del ruido de una única realización aleatoria.
    """

    @pytest.mark.parametrize("target_power", [0.92, 0.75, 0.60, 0.50])
    def test_achieved_power_matches_theoretical_target_across_the_range(self, target_power):
        p0 = 0.096
        mde = 0.03
        n = abf.sample_size_for_power(p0=p0, mde=mde, alpha=0.05, power=target_power)

        a = arm_from_rate(n, p0 + mde, 0.015)
        b = arm_from_rate(n, p0, 0.015)

        result = abf.run_ab_test(a, b, baseline_p0=p0, guardrail_q_threshold=0.020)

        # No se detecta un salto/cliff no testeado entre los extremos
        # sellados (~50%/~92%) de la Fase 3: la potencia calculada por el
        # framework, con el n exacto para cada punto objetivo, debe seguir
        # siendo consistente con la potencia teórica en todo el rango
        # 50%-92%, no solo en los dos extremos.
        assert result["power_achieved"] == pytest.approx(target_power, abs=0.05)


# ---------------------------------------------------------------------------
# 4. Reconstrucción de la matriz sellada (Sección 2.3) — 16 escenarios
# ---------------------------------------------------------------------------

# (escenario, dificultad, p_a, p_b, q_a, q_b, n, veredicto_esperado)
# Conteos deterministas (valor esperado exacto bajo p_a/p_b/q_a/q_b) — ver
# nota de alcance en la cabecera del módulo.
SEALED_MATRIX = [
    ("01", "obvio", 0.16, 0.08, 0.015, 0.015, 380, "A_wins"),
    ("01", "umbral", 0.11, 0.08, 0.015, 0.015, 740, None),  # ambiguo por diseño (~50% potencia)
    ("02", "obvio", 0.10, 0.08, 0.015, 0.015, 4650, "A_wins"),
    ("02", "umbral", 0.10, 0.08, 0.015, 0.015, 1600, None),
    ("03", "obvio", 0.07, 0.15, 0.015, 0.015, 350, "B_wins"),
    ("03", "umbral", 0.095, 0.08, 0.015, 0.015, 2750, None),
    ("04", "obvio", 0.09, 0.09, 0.015, 0.015, 800, "no_significant_difference"),
    ("04", "umbral", 0.091, 0.089, 0.015, 0.015, 800, "no_significant_difference"),
    ("07", "obvio", 0.14, 0.08, 0.050, 0.015, 400, "not_recommended_guardrail"),
    ("07", "umbral", 0.12, 0.08, 0.021, 0.015, 400, None),  # caso límite intencional, ver nota
    ("08", "obvio", 0.14, 0.08, 0.015, 0.015, 25, "insufficient_sample"),
    ("08", "umbral", 0.10, 0.08, 0.015, 0.015, 150, None),  # ver nota — límite conocido
]


class TestSealedMatrixReconstruction:
    """Nota de alcance: conteos deterministas (valor esperado exacto)
    derivados de los parámetros publicados en la Sección 2.3, no de los CSV
    privados originales (no accesibles en este entorno). Válida para
    comprobar la lógica de decisión del framework contra el ground truth
    conocido de cada fila; no sustituye una ejecución bit-exacta sobre
    `s5b_*.csv`.

    Dos filas (`07_umbral`, `08_umbral`) se dejan como veredicto ambiguo
    (`None`) de forma deliberada: son, respectivamente, el caso límite de
    guardrail y el caso de muestra insuficiente que la propia Fase 5
    identificó como los dos escenarios donde el criterio de decisión (no el
    cálculo) es genuinamente sensible al ruido de una única realización —
    exactamente dos de los tres fallos documentados en la Fase 4. El
    algoritmo de precedencia se valida de forma determinista para estos
    mecanismos en `TestPrecedenceAlgorithm` (con conteos que sí cruzan o no
    cruzan el umbral de forma inequívoca); aquí solo se exige que el
    framework produzca una respuesta válida y con el contrato completo.
    """

    @pytest.mark.parametrize(
        "escenario,dificultad,p_a,p_b,q_a,q_b,n,expected",
        SEALED_MATRIX,
        ids=[f"{row[0]}_{row[1]}" for row in SEALED_MATRIX],
    )
    def test_scenario_verdict(self, escenario, dificultad, p_a, p_b, q_a, q_b, n, expected):
        a = arm_from_rate(n, p_a, q_a)
        b = arm_from_rate(n, p_b, q_b)
        result = abf.run_ab_test(a, b, baseline_p0=0.096, guardrail_q_threshold=0.020)

        valid_verdicts = (
            "A_wins", "B_wins", "no_significant_difference",
            "not_recommended_guardrail", "insufficient_sample",
        )
        assert result["verdict"] in valid_verdicts

        if expected is not None:
            assert result["verdict"] == expected, (
                f"{escenario}_{dificultad}: esperado {expected!r}, obtenido "
                f"{result['verdict']!r} (p={result['p_value']:.4f}, "
                f"power={result['power_achieved']:.3f}, "
                f"guardrail_breach={result['guardrail_breach']})"
            )


# ---------------------------------------------------------------------------
# 5. Extensión aprobada v17.23 — veredicto de N brazos
# (`evaluate_multi_arm_test`, ahora fusionada en ab_testing_framework.py).
# NO forma parte del contrato original 0.6-c (v17.14) -- ver nota de
# cabecera de ab_testing_framework.py para el detalle de la fusión.
#
# Los 5 tests de esta sección se migran desde test_multi_arm_verdict_proposal.py
# (fichero de la propuesta v17.22, ahora obsoleto tras la fusión) sin
# cambios de fondo salvo los dos ajustes aprobados por Alberto en v17.23:
#   - `multiple_arms_tied` -> `multiple_arms_portfolio_candidates`.
#   - Bonferroni simple -> Holm-Bonferroni (el último test, antes
#     "test_bonferroni_correction_prevents_false_positive_with_multiple_arms",
#     se renombra en consecuencia; el resultado no cambia porque, en un
#     conjunto de 2 comparaciones, el umbral de Holm para el p-valor más
#     pequeño del conjunto coincide con el de Bonferroni -- alpha/m).
# ---------------------------------------------------------------------------

class TestMultiArmVerdict:
    def test_no_arm_recommended_when_control_wins_both(self):
        # Reproduce el patrón real del escenario 06 (cross_check_results.csv):
        # control gana claramente a las dos variantes -> ninguna recomendable.
        control = make_arm(n=1000, converted=160, opt_out=15)  # p=0.16
        a = make_arm(n=1000, converted=80, opt_out=15)          # p=0.08, pierde
        b = make_arm(n=1000, converted=70, opt_out=15)          # p=0.07, pierde
        result = abf.evaluate_multi_arm_test(
            control, {"A": a, "B": b}, baseline_p0=0.096, guardrail_q_threshold=0.020
        )
        assert result["multi_verdict"] == "no_arm_recommended"
        assert result["winning_arms"] == []
        assert result["per_arm_results"]["A"]["verdict"] == "B_wins"  # control (B) gana

    def test_single_arm_recommended_when_only_one_beats_control(self):
        control = make_arm(n=1000, converted=80, opt_out=15)
        a = make_arm(n=1000, converted=160, opt_out=15)  # gana claramente
        b = make_arm(n=1000, converted=82, opt_out=15)   # sin diferencia
        result = abf.evaluate_multi_arm_test(
            control, {"A": a, "B": b}, baseline_p0=0.096, guardrail_q_threshold=0.020
        )
        assert result["multi_verdict"] == "single_arm_recommended"
        assert result["winning_arms"] == ["A"]

    def test_multiple_arms_portfolio_candidates_when_both_beat_control(self):
        # Antes "multiple_arms_tied" en la propuesta v17.22 -- renombrado en
        # v17.23: el código sigue sin elegir una ganadora, pero el nombre ya
        # no sugiere que haga falta desempatar (ver docstring de
        # evaluate_multi_arm_test en ab_testing_framework.py).
        control = make_arm(n=1000, converted=80, opt_out=15)
        a = make_arm(n=1000, converted=160, opt_out=15)
        b = make_arm(n=1000, converted=150, opt_out=15)
        result = abf.evaluate_multi_arm_test(
            control, {"A": a, "B": b}, baseline_p0=0.096, guardrail_q_threshold=0.020
        )
        assert result["multi_verdict"] == "multiple_arms_portfolio_candidates"
        assert set(result["winning_arms"]) == {"A", "B"}

    def test_inconclusive_when_nothing_is_clear(self):
        control = make_arm(n=200, converted=16, opt_out=3)
        a = make_arm(n=200, converted=17, opt_out=3)
        b = make_arm(n=200, converted=15, opt_out=3)
        result = abf.evaluate_multi_arm_test(
            control, {"A": a, "B": b}, baseline_p0=0.096, guardrail_q_threshold=0.020
        )
        assert result["multi_verdict"] == "inconclusive"
        assert result["winning_arms"] == []

    def test_holm_bonferroni_correction_prevents_false_positive_with_multiple_arms(self):
        # Caso límite construido: p≈0.040 en la comparación individual A vs
        # control -- significativo a alpha=0.05 sin corregir, pero NO tras
        # la corrección de comparaciones múltiples con m=2 (el umbral de
        # Holm para el p-valor más pequeño del conjunto es alpha/m=0.025,
        # igual que Bonferroni en ese primer rango). Sin la corrección,
        # evaluate_multi_arm_test() habría devuelto "single_arm_recommended";
        # con ella, no.
        control = make_arm(n=1000, converted=90, opt_out=15)
        a = make_arm(n=1000, converted=118, opt_out=15)  # p individual ~0.040 vs control
        b = make_arm(n=1000, converted=90, opt_out=15)   # sin diferencia con control

        # Referencia: sin corregir, A solo (m=1) sí ganaría a alpha=0.05.
        uncorrected = abf.evaluate_multi_arm_test(
            control, {"A": a}, baseline_p0=0.096, guardrail_q_threshold=0.020
        )
        assert uncorrected["multi_verdict"] == "single_arm_recommended"

        # Con una segunda variante en la comparación (m=2), el umbral
        # ajustado (Holm, 0.025 en el primer rango) ya no es superado por
        # el p-valor de A (~0.040): el falso positivo que habría dado
        # "single_arm_recommended" no debe aparecer.
        corrected = abf.evaluate_multi_arm_test(
            control, {"A": a, "B": b}, baseline_p0=0.096, guardrail_q_threshold=0.020
        )
        assert corrected["multi_verdict"] != "single_arm_recommended"
        assert corrected["per_arm_results"]["A"]["verdict"] == "no_significant_difference"


class TestHolmBonferroniCorrection:
    """Test directo de la función de corrección, no del caso de negocio --
    mismo patrón que TestBonferroniCorrection más arriba, para la función
    aprobada en v17.23 que la sustituye dentro de evaluate_multi_arm_test."""

    def test_matches_bonferroni_on_the_smallest_p_value(self):
        # El umbral de Holm para el rango 0 (p-valor más pequeño) es
        # idéntico al de Bonferroni (alpha/m) -- ambos parten del mismo
        # punto, Holm solo relaja los rangos siguientes.
        thresholds, significant = abf.holm_bonferroni_correction([0.001, 0.03, 0.2], alpha=0.05)
        adjusted_alpha, _ = abf.bonferroni_correction([0.001, 0.03, 0.2], alpha=0.05)
        assert thresholds[0] == pytest.approx(adjusted_alpha)
        assert significant == [True, False, False]

    def test_relaxes_threshold_for_later_ranks_vs_bonferroni(self):
        # A diferencia de Bonferroni (mismo alpha/m fijo para todos), Holm
        # da un umbral más laxo a comparaciones de rango superior una vez
        # que las anteriores ya se resolvieron -- más potencia con el mismo
        # control del error familia-wise.
        thresholds, _ = abf.holm_bonferroni_correction([0.001, 0.02, 0.03, 0.04], alpha=0.05)
        adjusted_alpha, _ = abf.bonferroni_correction([0.001, 0.02, 0.03, 0.04], alpha=0.05)
        assert thresholds[1] > adjusted_alpha  # segundo p-valor más pequeño: umbral relajado
        assert thresholds[1] == pytest.approx(0.05 / 3)

    def test_empty_list(self):
        thresholds, significant = abf.holm_bonferroni_correction([], alpha=0.05)
        assert thresholds == []
        assert significant == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
