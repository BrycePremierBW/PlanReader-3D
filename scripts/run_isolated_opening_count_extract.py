#!/usr/bin/env python3
"""Extract opening counts with gold/eval resources denied at the Python layer."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pb_provider_runtime_isolation import GoldResourceDenied, install_runtime_gold_denial


def main() -> int:
    install_runtime_gold_denial()
    if len(sys.argv) < 3:
        print("usage: run_isolated_opening_count_extract.py PDF OUT.json", file=sys.stderr)
        return 2
    pdf = Path(sys.argv[1])
    out = Path(sys.argv[2])
    try:
        import pb_public_tender_benchmark  # noqa: F401
    except GoldResourceDenied:
        pass
    else:
        raise SystemExit("gold module import was not denied")
    gold_file = ROOT / "benchmarks/public_tenders/tenders_ke_kstvet_cbc_classroom/expected_boq_summary.json"
    try:
        gold_file.read_text(encoding="utf-8")
    except GoldResourceDenied:
        pass
    else:
        raise SystemExit("gold file read was not denied")
    from pb_opening_count_control_adapter import OpeningCountControlAdapter

    quantities = OpeningCountControlAdapter().extract_quantities(pdf, pages=[0])
    payload = [item.to_dict() for item in quantities]
    out.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
