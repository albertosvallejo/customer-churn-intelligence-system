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

from evidence.phase7_integration import build_phase7_kpi_status_view


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Phase 7 KPI status view from persisted statistical runs.")
    parser.add_argument("--run-date", default=None, help="Optional Phase 7 run date")
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    args = build_parser().parse_args()
    logging.getLogger(__name__).info("Starting Phase 7 KPI status build")
    payload = build_phase7_kpi_status_view(project_root=PROJECT_ROOT, run_date=args.run_date)
    logging.getLogger(__name__).info("Phase 7 KPI status build completed")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
