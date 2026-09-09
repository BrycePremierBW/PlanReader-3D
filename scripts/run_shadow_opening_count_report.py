#!/usr/bin/env python3
"""Run the gold-joining opening-count shadow report after provider outputs freeze."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pb_shadow_opening_count_eval import run_development_shadow_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="shadow_reports/opening_count_shadow_development.json",
        help="Path for the frozen evaluator report",
    )
    args = parser.parse_args()
    report = run_development_shadow_report()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2, sort_keys=True))
    print(json.dumps(report["migration_gate"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
