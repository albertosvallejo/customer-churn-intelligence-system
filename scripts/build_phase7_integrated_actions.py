from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_integration import build_integrated_actions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Phase 7 integrated actions for the statistical engine.")
    parser.add_argument("--run-date", help="Optional YYYYMMDD run date for the input/output artifact.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_integrated_actions(project_root=PROJECT_ROOT, run_date=args.run_date)
    LOGGER.info("Phase 7 integrated actions created at %s", payload["integrated_actions_path"])
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
