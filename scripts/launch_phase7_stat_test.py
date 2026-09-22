from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_integration import evaluate_integrated_action


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch a Phase 7 statistical evaluation for an integrated action.")
    parser.add_argument("--action-id", required=True, help="Integrated action identifier to evaluate")
    parser.add_argument("--proposal-run-date", default=None, help="Optional proposal run date to disambiguate artifact")
    parser.add_argument("--launched-by", required=True, help="Operator identifier for traceability")
    parser.add_argument("--control-n", required=True, type=int, help="Control arm sample size")
    parser.add_argument("--control-converted", required=True, type=int, help="Control arm converted count")
    parser.add_argument("--control-opt-out", required=True, type=int, help="Control arm opt-out count")
    parser.add_argument("--variant-n", required=True, type=int, help="Variant arm sample size")
    parser.add_argument("--variant-converted", required=True, type=int, help="Variant arm converted count")
    parser.add_argument("--variant-opt-out", required=True, type=int, help="Variant arm opt-out count")
    parser.add_argument("--baseline-p0", default=0.096, type=float, help="Baseline conversion prior for the statistical engine")
    parser.add_argument("--guardrail-q-threshold", default=0.020, type=float, help="Guardrail threshold for opt-out rate")
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    args = build_parser().parse_args()
    logging.getLogger(__name__).info("Starting Phase 7 statistical evaluation")
    payload = evaluate_integrated_action(
        {
            "action_id": args.action_id,
            "proposal_run_date": args.proposal_run_date,
            "launched_by": args.launched_by,
            "control_n": args.control_n,
            "control_converted": args.control_converted,
            "control_opt_out": args.control_opt_out,
            "variant_n": args.variant_n,
            "variant_converted": args.variant_converted,
            "variant_opt_out": args.variant_opt_out,
            "baseline_p0": args.baseline_p0,
            "guardrail_q_threshold": args.guardrail_q_threshold,
        },
        project_root=PROJECT_ROOT,
    )
    logging.getLogger(__name__).info("Phase 7 statistical evaluation completed")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
