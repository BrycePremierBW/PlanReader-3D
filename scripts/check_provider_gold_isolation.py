#!/usr/bin/env python3
"""CI check: registered production providers have no gold/eval import closure."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pb_provider_gold_isolation import assert_registered_providers_gold_free


def main() -> int:
    reports = assert_registered_providers_gold_free()
    payload = {
        provider_id: {
            "ok": report.ok,
            "root_module": report.root_module,
            "visited": list(report.visited),
            "findings": [item.reason for item in report.findings],
        }
        for provider_id, report in reports.items()
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
