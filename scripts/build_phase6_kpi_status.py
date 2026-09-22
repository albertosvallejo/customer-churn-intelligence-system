from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase6_integration import build_kpi_status_view

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    logging.getLogger(__name__).info("Starting Phase 6.4 KPI status build")
    payload = build_kpi_status_view(project_root=PROJECT_ROOT)
    logging.getLogger(__name__).info("Phase 6.4 KPI status build completed")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
